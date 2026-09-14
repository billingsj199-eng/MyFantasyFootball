#!/usr/bin/env python3
"""
Why do buried rookies (Jam Miller RB5, Phil Mafah RB4) rank near real
players? The rookie template is keyed on draft capital + a TEAM-level room
multiplier, so it can't see that a specific rookie is 4th or 5th in line.

Two candidate fixes, both testable historically (2019-2025):

  n_ahead   count of RETURNING teammates at his position who held a real
            share of the team's pool last year (>=8% targets for WR/TE,
            >=8% carries for RB). This is the historical proxy for
            "depth-chart slot" — ESPN charts don't exist for past seasons.
  in_clay   whether Clay's preseason guide projected the player at all.
            Clay covers essentially every fantasy-relevant player, so his
            SILENCE is itself a signal.

Target is SEASON fantasy points / 17 (not PPG over games played) so that
"never played" counts as the failure it is — the whole point of the
complaint. Graded against a draft-capital baseline (round-bucket mean),
LOYO by season.
"""
import numpy as np
import pandas as pd
import json, os
from collections import defaultdict
from backtest_sim_calibration import played, WEEKLY, infer_team
import backtest_sim_calibration as cal

CACHE = r"E:\MyFantasyFootball\pbp_cache"
REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"
POS = ("RB", "WR", "TE")
PFR_TEAM = {"NWE": "NE", "GNB": "GB", "KAN": "KC", "NOR": "NO", "SFO": "SF",
            "TAM": "TB", "LVR": "LV", "SDG": "LAC", "OAK": "LV", "STL": "LAR"}
SHARE_MIN = 0.08

def rows_of(rec, Y):
    return [w for w in rec.get("seasons", {}).get(str(Y), []) if played(w)]

def main():
    clay = {int(y): {cal.norm(n) for n in ps}
            for y, ps in json.load(open(os.path.join(REPO, "data", "clay_history.json"),
                                        encoding="utf-8")).items()}
    dp = pd.read_parquet(os.path.join(CACHE, "draft_picks.parquet"),
                         columns=["season", "round", "pick", "pfr_player_name", "position", "team"])
    dp = dp[(dp.season >= 2019) & (dp.position.isin(POS))].copy()
    dp["norm"] = dp.pfr_player_name.map(lambda n: cal.norm(str(n)))
    dp["tm"] = dp.team.map(lambda t: PFR_TEAM.get(t, t))

    # per player-season: team + share of team pool + season points
    P, pool = {}, defaultdict(lambda: [0.0, 0.0])
    for nk, lst in WEEKLY.items():
        for rec in lst:
            pos = rec.get("pos")
            if pos not in POS + ("QB",):
                continue
            for Ys in rec.get("seasons", {}):
                Y = int(Ys)
                rws = rows_of(rec, Y)
                if not rws:
                    continue
                t = infer_team(rec, Y)
                tg = sum(w.get("tgt") or 0 for w in rws)
                car = sum(w.get("ra") or 0 for w in rws)
                sp = sum(w["fpts"] for w in rws if isinstance(w.get("fpts"), (int, float)))
                P[(nk, pos, Y)] = {"team": t, "tgt": tg, "car": car, "season": sp, "g": len(rws)}
                if t:
                    pool[(t, Y)][0] += tg; pool[(t, Y)][1] += car
    # index players by (team, pos, year) for the n_ahead count
    roster = defaultdict(list)
    for (nk, pos, Y), d in P.items():
        if d["team"]:
            roster[(d["team"], pos, Y)].append((nk, d))

    rows = []
    for _, r in dp.iterrows():
        Y, pos, nk, tm = int(r.season), r.position, r["norm"], r.tm
        cur = P.get((nk, pos, Y))
        season_pts = cur["season"] if cur else 0.0   # never played = 0
        # returning teammates with real share last year
        n_ahead = 0
        for onk, od in roster.get((tm, pos, Y - 1), []):
            if onk == nk:
                continue
            tp = pool.get((tm, Y - 1))
            if not tp or tp[0] < 150:
                continue
            share = (od["tgt"] / tp[0]) if pos in ("WR", "TE") else (od["car"] / max(1, tp[1]))
            # still on the team this year?
            nxt = P.get((onk, pos, Y))
            if share >= SHARE_MIN and nxt and nxt["team"] == tm:
                n_ahead += 1
        rows.append({"Y": Y, "pos": pos, "pick": int(r.pick), "round": int(r["round"]),
                     "n_ahead": n_ahead, "in_clay": 1.0 if nk in clay.get(Y, set()) else 0.0,
                     "val": season_pts / 17.0})
    df = pd.DataFrame(rows)
    print(f"{len(df)} drafted rookies 2019-25 (season pts / 17; never-played = 0)\n")

    print("=== Rookie value by DEPTH (returning teammates with a real share) ===")
    for pos in POS:
        s = df[df.pos == pos]
        line = f"  {pos}:"
        for n in (0, 1, 2, 3):
            sel = s[s.n_ahead == n] if n < 3 else s[s.n_ahead >= 3]
            if len(sel) >= 8:
                line += f"  {n}{'+' if n==3 else ''} ahead: {sel.val.mean():5.2f} (n={len(sel)})"
        print(line)

    print("\n=== Rookie value by whether Clay projected him ===")
    for pos in POS:
        s = df[df.pos == pos]
        a = s[s.in_clay == 1]; b = s[s.in_clay == 0]
        if len(a) >= 8 and len(b) >= 8:
            print(f"  {pos}: in Clay {a.val.mean():5.2f} (n={len(a)})   NOT in Clay {b.val.mean():5.2f} (n={len(b)})"
                  f"   ratio {b.val.mean()/max(0.01,a.val.mean()):.2f}")

    print("\n=== LOYO MAE: round-bucket baseline vs adding each signal ===")
    for pos in POS:
        s = df[df.pos == pos]
        if len(s) < 60:
            continue
        base, m_dep, m_clay, m_both = [], [], [], []
        for Y in sorted(s.Y.unique()):
            tr, te = s[s.Y != Y], s[s.Y == Y]
            if len(tr) < 40 or not len(te):
                continue
            bm = {rd: tr[tr["round"] == rd].val.mean() for rd in range(1, 8)}
            gm = tr.val.mean()
            dep = tr.groupby(tr.n_ahead.clip(upper=3)).val.mean() / max(0.01, gm)
            clr = tr.groupby("in_clay").val.mean() / max(0.01, gm)
            for _, t in te.iterrows():
                b = bm.get(t["round"], gm)
                if b != b:
                    b = gm
                base.append(abs(b - t.val))
                dmul = float(dep.get(min(3, t.n_ahead), 1.0))
                cmul = float(clr.get(t.in_clay, 1.0))
                m_dep.append(abs(b * dmul - t.val))
                m_clay.append(abs(b * cmul - t.val))
                m_both.append(abs(b * dmul * cmul / max(0.2, 1.0) - t.val))
        f = lambda x: (np.mean(x) - np.mean(base)) / np.mean(base) * 100
        print(f"  {pos}: baseline {np.mean(base):.3f}  +depth {np.mean(m_dep):.3f} ({f(m_dep):+.2f}%)"
              f"  +noClay {np.mean(m_clay):.3f} ({f(m_clay):+.2f}%)  +both {np.mean(m_both):.3f} ({f(m_both):+.2f}%)")

if __name__ == "__main__":
    main()
