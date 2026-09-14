#!/usr/bin/env python3
"""
Backtest the CORRELATION structure: do teammates/opponents actually boom
together the way the engine assumes?

Empirical side (2019-25): for every pooled player (Clay regulars, team via
opponent-sequence matching, >=6 played games), standardize each week's score
against the player's own season mean/sd -> z. Then pool (z_i, z_j) samples
for every pair type and week where both played:
  same team:  QB-WR1, QB-WR2+, QB-TE1, QB-RB1, WR1-WR2+, WR-TE, RB1-WR1, ...
  opponents:  QB-oppQB, QB-oppWR1, WR1-oppWR1, RB1-oppRB1, ...
(WR1/RB1/TE1 = team's top season PPG at the position that year.)

Engine-implied side: score_i = m(1 + BETA*zSide) + eps, eps sd = 0.9*sigma*m;
teammates share zSide fully, opponents share only the game factor (RHO=0.35):
  corr_tm  = BETA^2 / sqrt((BETA^2+.81 s_i^2)(BETA^2+.81 s_j^2))
  corr_opp = RHO * corr_tm
— one number per sigma pair, IDENTICAL for every position combo. This run
measures how wrong that uniformity is and gives the targets for a
position-aware structure (e.g. a shared passing-game factor).
"""
import numpy as np
from backtest_sim_calibration import (played, weekly_rec, infer_team,
                                      POS_KEEP, POOL_MIN_PTS, SCHEDULES)
import backtest_sim_calibration as cal
import json, os
from collections import defaultdict

MIN_GAMES = 6
BETA, RHO, SHRINK = 0.20, 0.35, 0.9
POS_SIGMA = {"QB": 0.42, "RB": 0.52, "WR": 0.62, "TE": 0.70}

def rank_label(pos, rank):
    if pos in ("WR", "RB", "TE"):
        return pos + ("1" if rank == 1 else "2+")
    return pos

def main():
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    same, opp = defaultdict(list), defaultdict(list)
    for Y in range(2019, 2026):
        if str(Y) not in clay_hist:
            continue
        # per team: [{label, zByWeek}]
        teams = defaultdict(list)
        for name, c in clay_hist[str(Y)].items():
            pos = c.get("pos")
            if pos not in POS_KEEP or (c.get("pts") or 0) < POOL_MIN_PTS:
                continue
            wrec = weekly_rec(name, pos)
            if wrec is None:
                continue
            t = infer_team(wrec, Y)
            if not t:
                continue
            rows = [(w["wk"], w["fpts"]) for w in wrec.get("seasons", {}).get(str(Y), [])
                    if played(w) and isinstance(w.get("fpts"), (int, float))]
            if len(rows) < MIN_GAMES:
                continue
            pts = np.array([f for _, f in rows], float)
            mu, sd = pts.mean(), pts.std(ddof=1)
            if sd < 1 or mu < 1:
                continue
            teams[(t, Y)].append({"pos": pos, "ppg": mu,
                                  "z": {wk: (f - mu) / sd for wk, f in rows}})
        # rank within team-position by ppg
        for key, ps in teams.items():
            for pos in ("WR", "RB", "TE"):
                grp = sorted([p for p in ps if p["pos"] == pos],
                             key=lambda p: -p["ppg"])
                for r, p in enumerate(grp):
                    p["label"] = rank_label(pos, r + 1)
            for p in ps:
                if p["pos"] == "QB":
                    p["label"] = "QB"
        # same-team pairs
        for (t, _), ps in teams.items():
            for i in range(len(ps)):
                for j in range(i + 1, len(ps)):
                    a, b = sorted((ps[i], ps[j]), key=lambda p: p["label"])
                    shared = set(a["z"]) & set(b["z"])
                    for wk in shared:
                        same[(a["label"], b["label"])].append((a["z"][wk], b["z"][wk]))
        # opponent pairs via schedules
        sched = SCHEDULES.get(Y, {})
        for (t, _), ps in teams.items():
            for wk_s, o in sched.get(t, {}).items():
                if t >= o:   # each game once
                    continue
                wk = int(wk_s)
                qs = teams.get((o, Y), [])
                for a in ps:
                    if wk not in a["z"]:
                        continue
                    for b in qs:
                        if wk not in b["z"]:
                            continue
                        x, y = sorted((a, b), key=lambda p: p["label"])
                        opp[(x["label"], y["label"])].append((x["z"][wk], y["z"][wk]))
        print(f"  {Y} done")

    def engine_implied(p1, p2, shared):
        s1, s2 = POS_SIGMA[p1.rstrip("12+")], POS_SIGMA[p2.rstrip("12+")]
        c = BETA ** 2 / np.sqrt((BETA ** 2 + (SHRINK * s1) ** 2) * (BETA ** 2 + (SHRINK * s2) ** 2))
        return c * (1 if shared else RHO)

    # ---- proposed QB-hub structure (fractions of each player's total sd) ----
    # V = passing environment (game share GV); G_r = per-receiver draw that
    # ALSO flows into the QB via share weights (QB points ARE receiver
    # points, which links QB<->each receiver without linking the receivers
    # to each other); R = antisymmetric rush-script game factor.
    GV = 0.50
    FV = {"QB": .63, "WR": .24, "TE": .22, "RB": .06}
    FH_QB = .65
    FG = {"WR": .58, "TE": .60, "RB": .30}
    FR_RB = .25
    WSHARE = {"WR1": .55, "WR2+": .30, "TE1": .35, "TE2+": .15, "RB1": .25, "RB2+": .12}

    def proposed(p1, p2, shared):
        b1, b2 = p1.rstrip("12+"), p2.rstrip("12+")
        c = FV[b1] * FV[b2] * (1 if shared else GV)
        if shared and "QB" in (b1, b2) and b1 != b2:
            rec, lab = (b2, p2) if b1 == "QB" else (b1, p1)
            c += FH_QB * WSHARE.get(lab, .2) * FG.get(rec, 0)
        if b1 == "RB" and b2 == "RB":
            c += (FR_RB ** 2) * (1 if shared else -1)
        return c

    def report(d, tag, shared):
        print(f"\n=== {tag} pair correlations (empirical vs engine vs PROPOSED) ===")
        rows, err_old, err_new = [], [], []
        for (a, b), pr in d.items():
            if len(pr) < 300:
                continue
            x = np.array([p[0] for p in pr]); y = np.array([p[1] for p in pr])
            emp = float(np.corrcoef(x, y)[0, 1])
            rows.append((a, b, emp, len(pr), engine_implied(a, b, shared), proposed(a, b, shared)))
            err_old.append(abs(emp - rows[-1][4])); err_new.append(abs(emp - rows[-1][5]))
        rows.sort(key=lambda r: -abs(r[2]))
        for a, b, r, n, imp, prop in rows:
            flag = " <-- still off" if abs(r - prop) > 0.06 else ""
            print(f"  {a:<5}-{b:<5} emp {r:+.3f}  engine {imp:+.3f}  proposed {prop:+.3f}  (n={n}){flag}")
        print(f"  mean |error|: engine {np.mean(err_old):.3f} -> proposed {np.mean(err_new):.3f}")

    report(same, "SAME-TEAM", True)
    report(opp, "OPPONENT", False)

if __name__ == "__main__":
    main()
