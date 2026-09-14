#!/usr/bin/env python3
r"""
Does CONTEXT-ADJUSTED per-game production predict next season better than the
raw PPG the recency core currently uses? (2019-2025)

The core averages every game a player played, which silently mixes:
  * games he played hurt / on a snap count (30% snaps, 4 points)
  * games his starting QB was out (a backup throwing him the ball)
  * games a teammate ahead of him was out (inflated opportunity)

Each is reconstructible:
  snap%   nflverse snap_counts — his offense_pct that week vs his OWN season
          median. "Healthy" = >= HEALTHY_FRAC of his median.
  QB      each team's primary QB per season = most pass attempts (pbp).
          A week is "starter QB" if that QB threw the most attempts that week.
  mates   for pass-catchers: the share of the team's OTHER top-3 receivers
          (by season targets) who were ACTIVE that week. Games missing a
          teammate are inflated; games with everyone healthy are the norm.

Variants of the per-game rate fed into the 3-yr recency core:
  raw       every played game                       (what ships today)
  healthy   snap% >= 80% of his own median
  qbok      starting QB played
  both      healthy AND starting QB
  mateadj   raw, but each game re-weighted by teammate availability
            (down-weight games where a teammate ahead of him was out)

Graded on actual season-Y PPG, LOYO by season, per position.
"""
import numpy as np
import pandas as pd
import os
from collections import defaultdict
from backtest_sim_calibration import played, WEEKLY, infer_team, POS_KEEP
import backtest_sim_calibration as cal

CACHE = r"E:\MyFantasyFootball\pbp_cache"
W3 = [0.5, 0.3, 0.2]
YEARS = range(2019, 2026)
HIST = range(2016, 2026)
HEALTHY_FRAC = 0.80
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS"}

def rows_of(rec, Y):
    return [w for w in rec.get("seasons", {}).get(str(Y), []) if played(w)]

def abbrev(name):
    parts = [p for p in str(name).replace(".", " ").split() if p]
    return cal.norm(parts[0][0] + "." + parts[-1]) if len(parts) >= 2 else None

def load_snaps(y):
    p = os.path.join(CACHE, f"snap_counts_{y}.parquet")
    if not os.path.exists(p):
        return {}
    df = pd.read_parquet(p, columns=["player", "week", "game_type", "offense_pct"])
    df = df[(df.game_type == "REG")].dropna(subset=["offense_pct"])
    out = defaultdict(dict)
    for _, r in df.iterrows():
        out[cal.norm(r.player)][int(r.week)] = float(r.offense_pct)
    return out

def qb_starters(y):
    """(team, week) -> abbrev of the QB with the most attempts that week."""
    p = os.path.join(CACHE, f"play_by_play_{y}.csv.gz")
    if not os.path.exists(p):
        return {}, {}
    df = pd.read_csv(p, usecols=["season_type", "week", "posteam", "passer_player_name",
                                 "pass_attempt"], low_memory=False)
    df = df[(df.season_type == "REG") & (df.pass_attempt == 1)]
    df = df.dropna(subset=["posteam", "passer_player_name"])
    df["tm"] = df.posteam.map(lambda t: ALIAS.get(t, t))
    wk = {}
    for (t, w, nm), n in df.groupby(["tm", "week", "passer_player_name"]).size().items():
        k = (t, int(w))
        if k not in wk or n > wk[k][1]:
            wk[k] = (cal.norm(nm), int(n))
    season = {}
    for (t, w, nm), n in df.groupby(["tm", "week", "passer_player_name"]).size().items():
        season[(t, cal.norm(nm))] = season.get((t, cal.norm(nm)), 0) + n
    primary = {}
    for (t, nm), n in season.items():
        if t not in primary or n > primary[t][1]:
            primary[t] = (nm, n)
    return {k: v[0] for k, v in wk.items()}, {t: v[0] for t, v in primary.items()}

def main():
    snaps, qbwk, qbprim = {}, {}, {}
    for y in HIST:
        snaps[y] = load_snaps(y)
        qbwk[y], qbprim[y] = qb_starters(y)
        print(f"  ctx {y} loaded")

    recs = [(nk, rec) for nk, lst in WEEKLY.items() for rec in lst if rec.get("pos") in POS_KEEP]
    # per (player, season): weekly rows + team + season target rank on his team
    info = {}
    team_tgts = defaultdict(list)
    for nk, rec in recs:
        for Ys in rec.get("seasons", {}):
            Y = int(Ys)
            rws = rows_of(rec, Y)
            if not rws:
                continue
            t = infer_team(rec, Y)
            tg = sum(w.get("tgt") or 0 for w in rws)
            info[(nk, rec["pos"], Y)] = {"rows": rws, "team": t, "tgt": tg}
            if t and rec["pos"] in ("WR", "TE", "RB"):
                team_tgts[(t, Y)].append((nk, rec["pos"], tg))

    def variants(nk, pos, Y):
        """returns dict of per-game rates under each context definition."""
        d = info.get((nk, pos, Y))
        if not d:
            return None
        rws = d["rows"]
        pts = [(w["wk"], w["fpts"]) for w in rws if isinstance(w.get("fpts"), (int, float))]
        if not pts:
            return None
        sn = snaps.get(Y, {}).get(nk, {})
        med = float(np.median(list(sn.values()))) if sn else None
        # teammate availability: the other top-3 target earners on his team
        mates = []
        if d["team"]:
            ranked = sorted(team_tgts.get((d["team"], Y), []), key=lambda x: -x[2])[:3]
            mates = [(m_nk, m_pos) for m_nk, m_pos, _ in ranked if m_nk != nk]
        out = {"raw": [], "healthy": [], "qbok": [], "both": [], "mateadj": [], "mw": []}
        for wk, f in pts:
            out["raw"].append(f)
            ok_snap = (med is None) or (sn.get(wk, med) >= HEALTHY_FRAC * med)
            prim = qbprim.get(Y, {}).get(d["team"]) if d["team"] else None
            ok_qb = True
            if prim and d["team"]:
                wq = qbwk.get(Y, {}).get((d["team"], wk))
                ok_qb = (wq is None) or (wq == prim)
            if ok_snap:
                out["healthy"].append(f)
            if ok_qb:
                out["qbok"].append(f)
            if ok_snap and ok_qb:
                out["both"].append(f)
            # teammate weighting: full weight when all mates played
            n_out = 0
            for m_nk, m_pos in mates:
                mi = info.get((m_nk, m_pos, Y))
                if mi and not any(x.get("wk") == wk for x in mi["rows"]):
                    n_out += 1
            w_ = 1.0 / (1.0 + 0.5 * n_out)
            out["mateadj"].append(f * w_)
            out["mw"].append(w_)
        res = {}
        for k in ("raw", "healthy", "qbok", "both"):
            res[k] = float(np.mean(out[k])) if len(out[k]) >= 3 else None
        res["mateadj"] = (float(np.sum(out["mateadj"]) / np.sum(out["mw"]))
                          if out["mw"] else None)
        res["_n"] = len(pts)
        return res

    MODELS = ["raw", "healthy", "qbok", "both", "mateadj"]
    cache = {}
    def V(nk, pos, Y):
        k = (nk, pos, Y)
        if k not in cache:
            cache[k] = variants(nk, pos, Y)
        return cache[k]

    rows = []
    for nk, rec in recs:
        pos = rec["pos"]
        for Y in YEARS:
            cur = V(nk, pos, Y)
            if not cur or cur["_n"] < 6 or cur["raw"] is None:
                continue
            r = {"pos": pos, "Y": Y, "act": cur["raw"]}
            ok = True
            for m in MODELS:
                num = den = 0.0
                for i, yy in enumerate((Y - 1, Y - 2, Y - 3)):
                    pv = V(nk, pos, yy)
                    if pv and pv["_n"] >= 4 and pv.get(m) is not None:
                        num += W3[i] * pv[m]; den += W3[i]
                if den == 0:
                    ok = False; break
                r[m] = num / den
            if ok and r["raw"] >= 3:
                rows.append(r)
        # progress
    df = pd.DataFrame(rows)
    print(f"\n{len(df)} player-seasons with all context variants\n")
    print("=== MAE predicting season-Y PPG (LOYO) ===")
    print(f"{'pos':<5}{'n':>6}" + "".join(f"{m:>10}" for m in MODELS))
    for pos in ("QB", "RB", "WR", "TE"):
        sel = df[df.pos == pos]
        if len(sel) < 60:
            continue
        line = f"{pos:<5}{len(sel):>6}"
        base = None
        for m in MODELS:
            errs = []
            for Y in YEARS:
                te = sel[sel.Y == Y]
                if not len(te):
                    continue
                errs.extend(np.abs(te[m] - te.act).tolist())
            v = float(np.mean(errs))
            if m == "raw":
                base = v
            line += f"{v:>10.3f}"
        print(line)
    # deltas vs raw
    print("\n=== delta vs raw ===")
    for pos in ("QB", "RB", "WR", "TE"):
        sel = df[df.pos == pos]
        if len(sel) < 60:
            continue
        b = float(np.mean(np.abs(sel["raw"] - sel.act)))
        outs = []
        for m in MODELS[1:]:
            v = float(np.mean(np.abs(sel[m] - sel.act)))
            outs.append(f"{m} {(v-b)/b*100:+.2f}%")
        print(f"  {pos}: " + "  ".join(outs))

if __name__ == "__main__":
    main()
