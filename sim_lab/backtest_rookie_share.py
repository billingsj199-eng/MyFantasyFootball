#!/usr/bin/env python3
"""
ROOKIE SHARE model (the depth-chart absorption question), 2019-2025:
what share of his team's target/carry pool does a drafted RB/WR/TE rookie
absorb, and is it predicted by (a) draft capital and (b) the ROOM — how much
of the team's position share RETURNS that year (less returning share = more
room to absorb)?

Rookies from nflverse draft_picks x our weekly DB (rookie season = draft
season). Returning share for team T, position P, year Y = sum over players
with 2019+ data of (their Y-1 share of T's pool) if they played for T in
BOTH Y-1 and Y. Grades a share-based rookie PPG projection (share x team
volume x position-mean efficiency) against round-bucket mean PPG baselines.
"""
import numpy as np
import pandas as pd
import json, os
from collections import defaultdict
from backtest_sim_calibration import played, WEEKLY, infer_team, SCHEDULES
import backtest_sim_calibration as cal

CACHE = r"E:\MyFantasyFootball\pbp_cache"
POS = ("RB", "WR", "TE")
PFR_TEAM = {"NWE": "NE", "GNB": "GB", "KAN": "KC", "NOR": "NO", "SFO": "SF",
            "TAM": "TB", "LVR": "LV", "SDG": "LAC", "OAK": "LV", "STL": "LAR"}

def rows_of(rec, Y):
    return [w for w in rec.get("seasons", {}).get(str(Y), []) if played(w)]

def main():
    dp = pd.read_parquet(os.path.join(CACHE, "draft_picks.parquet"),
                         columns=["season", "round", "pick", "pfr_player_name", "position", "team"])
    dp = dp[(dp.season >= 2019) & (dp.position.isin(POS))].copy()
    dp["norm"] = dp.pfr_player_name.map(lambda n: cal.norm(str(n)))
    dp["tm"] = dp.team.map(lambda t: PFR_TEAM.get(t, t))

    # player-season shares + team pools (same construction as the VS model)
    P, team_pool = {}, defaultdict(lambda: [0.0, 0.0])
    for nk, lst in WEEKLY.items():
        for rec in lst:
            if rec.get("pos") not in ("QB",) + POS:
                continue
            for Ys in rec.get("seasons", {}):
                Y = int(Ys)
                if Y < 2018:
                    continue
                rws = rows_of(rec, Y)
                if not rws:
                    continue
                t = infer_team(rec, Y)
                fpts = [w["fpts"] for w in rws if isinstance(w.get("fpts"), (int, float))]
                d = {"team": t, "tgt": sum(w.get("tgt") or 0 for w in rws),
                     "car": sum(w.get("ra") or 0 for w in rws), "g": len(rws),
                     "ppg": (sum(fpts) / len(fpts)) if fpts else None,
                     "pos": rec["pos"], "norm": nk}
                P[(nk, rec["pos"], Y)] = d
                if t:
                    team_pool[(t, Y)][0] += d["tgt"]
                    team_pool[(t, Y)][1] += d["car"]

    def games(t, Y):
        return len(SCHEDULES.get(Y, {}).get(t, {})) or (16 if Y <= 2020 else 17)

    # returning share per (team, pos, Y): players who played for T in Y-1 AND Y
    ret_share = defaultdict(float)
    for (nk, pos, Y), d in P.items():
        if pos not in POS or not d["team"]:
            continue
        prev = P.get((nk, pos, Y - 1))
        if prev and prev["team"] == d["team"] and team_pool.get((d["team"], Y - 1)):
            tp = team_pool[(d["team"], Y - 1)]
            if tp[0] > 200:
                key = "tgt" if pos in ("WR", "TE") else "car"
                pool = tp[0] if key == "tgt" else max(1, tp[1])
                ret_share[(d["team"], pos, Y)] += d[key] / pool

    rows = []
    for _, r in dp.iterrows():
        Y = int(r.season)
        d = P.get((r.norm, r.position, Y))
        if not d or d["g"] < 4 or not d["team"] or not team_pool.get((d["team"], Y)):
            continue
        tp = team_pool[(d["team"], Y)]
        if tp[0] < 200:
            continue
        share = (d["tgt"] / tp[0]) if r.position in ("WR", "TE") else (d["car"] / max(1, tp[1]))
        rows.append({"pos": r.position, "pick": int(r.pick), "round": int(r["round"]),
                     "share": share, "ppg": d["ppg"], "Y": Y, "team": d["team"],
                     "ret": ret_share.get((d["team"], r.position, Y), None)})
    df = pd.DataFrame(rows)
    print(f"{len(df)} rookie seasons matched (>=4 games)\n")

    print("=== Rookie share of team pool by draft capital ===")
    for pos in POS:
        line = f"  {pos}:"
        for lo, hi, lab in [(1, 13, "top-12"), (13, 33, "R1 late"), (33, 75, "R2-eR3"),
                            (75, 150, "mid"), (150, 300, "day3")]:
            sel = df[(df.pos == pos) & (df.pick >= lo) & (df.pick < hi)]
            if len(sel) >= 8:
                line += f"  {lab} {sel.share.mean()*100:.1f}% (n={len(sel)})"
        print(line)

    print("\n=== Does the ROOM matter? share vs returning-share, controlling capital ===")
    for pos in POS:
        sel = df[(df.pos == pos) & df.ret.notna()]
        for lo, hi, lab in [(1, 75, "picks 1-74"), (75, 300, "picks 75+")]:
            s2 = sel[(sel.pick >= lo) & (sel.pick < hi)]
            if len(s2) < 20:
                continue
            med = s2.ret.median()
            open_room = s2[s2.ret < med]
            crowded = s2[s2.ret >= med]
            print(f"  {pos} {lab}: open room {open_room.share.mean()*100:.1f}% "
                  f"vs crowded {crowded.share.mean()*100:.1f}%  "
                  f"(corr {np.corrcoef(s2.ret, s2.share)[0,1]:+.2f}, n={len(s2)})")

    # PPG prediction test: capital-share x room-mult x team volume x pos-mean eff
    print("\n=== Rookie PPG MAE: round-bucket baseline vs share-model ===")
    # fit share curve + eff means LOYO
    for pos in POS:
        errs_base, errs_model = [], []
        sel = df[(df.pos == pos) & df.ppg.notna()]
        for Y in range(2019, 2026):
            tr = sel[sel.Y != Y]; te = sel[sel.Y == Y]
            if len(te) == 0:
                continue
            # capital curve: log-linear fit share ~ a + b*log(pick)
            b, a = np.polyfit(np.log(tr.pick), tr.share, 1)
            # room effect: linear mult fit on residual ratio
            trr = tr[tr.ret.notna()]
            broom = np.polyfit(trr.ret, trr.share - (a + b * np.log(trr.pick)), 1)[0] if len(trr) > 20 else 0.0
            # ppg-per-share slope (converts share -> PPG; folds volume+eff)
            slope = (tr.ppg / tr.share.clip(lower=0.01)).median()
            base_ppg = {rd: tr[tr["round"] == rd].ppg.mean() for rd in range(1, 8)}
            for _, t in te.iterrows():
                sh = a + b * np.log(t.pick)
                if t.ret is not None and not (isinstance(t.ret, float) and np.isnan(t.ret)):
                    sh += broom * (t.ret - tr.ret.mean() if tr.ret.notna().any() else 0)
                sh = max(0.01, sh)
                errs_model.append(abs(sh * slope - t.ppg))
                bb = base_ppg.get(t["round"])
                errs_base.append(abs((bb if bb == bb and bb is not None else tr.ppg.mean()) - t.ppg))
        print(f"  {pos}: round-bucket {np.mean(errs_base):.3f}  share-model {np.mean(errs_model):.3f}  (n={len(errs_model)})")

if __name__ == "__main__":
    main()
