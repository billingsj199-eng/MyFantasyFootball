#!/usr/bin/env python3
"""
AVAILABILITY CURVE backtest (Jack 2026-09-30: "do injuries (how long out for) an issue?").

The engine's injury layer assumes a player tagged Out is back next game and an IR player is back after four.
History (research_injury_vacancy.py): a starter who just missed a game misses the next one 65% of the time.
Curve: P(misses the next game | has missed k so far) = CONT[k], fit on the other six seasons (LOYO), and
P(plays j games from now) = 1 - CONT[k] x CONT[k+1] x ... x CONT[k+j-1].

For every absence state (starter, guide >= 8 half-PPR a game, missed k games so far, season not over):
  engine   Out (k < 4):  plays every later game       IR-like (k >= 4): misses through game 4, then plays
  curve    the chain above
graded on whether he actually played each of the next 1..4 team games (Brier score, calibration, expected
games played over the next four vs actual). Log avail_curve_backtest.log.
"""
import json, os, sys, io
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_sim_calibration as cal
from backtest_sim_calibration import played, weekly_rec, infer_team
REPO = cal.REPO
KMAX = 8

def spells():
    ch = json.load(open(os.path.join(REPO, "data", "clay_history.json"), encoding="utf-8"))
    out = []   # (year, pos, k, plays_next[0..3] or None past season end)
    for Y in range(2019, 2026):
        W = 16 if Y <= 2020 else 17
        for name, c in ch[str(Y)].items():
            pos = c.get("pos")
            if pos not in ("QB", "RB", "WR", "TE"): continue
            pg = max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2) / W
            if pg < 8: continue
            rec = weekly_rec(name, pos)
            if rec is None: continue
            team = infer_team(rec, Y)
            if not team: continue
            gw = sorted(int(w) for w in cal.SCHEDULES.get(Y, {}).get(team, {}) if 1 <= int(w) <= W + 1)
            pl = set(w["wk"] for w in rec.get("seasons", {}).get(str(Y), []) if played(w))
            seq = [w in pl for w in gw]
            seen = False; k = 0
            for i, v in enumerate(seq):
                if v: seen = True; k = 0; continue
                if not seen: continue
                k += 1
                nxt = [seq[i + j] if i + j < len(seq) else None for j in range(1, 5)]
                out.append((Y, pos, min(k, KMAX), nxt))
    return out

def fit_cont(rows):
    n = defaultdict(int); m = defaultdict(int)
    for Y, pos, k, nxt in rows:
        if nxt[0] is None: continue
        n[k] += 1; m[k] += (nxt[0] is False)
    return {k: (m[k] + 0.7 * 5) / (n[k] + 5) for k in range(1, KMAX + 1)}   # light prior toward .70

def main():
    log = open(os.path.join(HERE, "avail_curve_backtest.log"), "w", encoding="utf-8")
    def P(s=""):
        print(s); log.write(s + "\n")
    S = spells(); years = sorted(set(r[0] for r in S))
    P(f"=== availability curve, 2019-25: {len(S)} absence states (starter, missed k games so far) ===")
    full = fit_cont(S)
    P("  P(misses the next game | missed k so far), all seasons: " + "  ".join(f"k={k}: {full[k]:.2f}" for k in range(1, KMAX + 1)))
    P("  by position (k=1 / k=2 / k=3):")
    for pos in ("QB", "RB", "WR", "TE"):
        c = fit_cont([r for r in S if r[1] == pos]); P(f"    {pos}: {c[1]:.2f} / {c[2]:.2f} / {c[3]:.2f}")
    # LOYO grading
    br = {"engine": [], "curve": []}; eg = {"engine": [], "curve": [], "act": []}; calib = defaultdict(lambda: [0, 0, 0])
    for Y in years:
        cont = fit_cont([r for r in S if r[0] != Y])
        for (y, pos, k, nxt) in S:
            if y != Y: continue
            surv = 1.0; pc = []; pe = []
            for j in range(4):
                surv *= cont[min(KMAX, k + j)]
                pc.append(1 - surv)
                pe.append(1.0 if k < 4 else (1.0 if k + j + 1 > 4 else 0.0))   # Out: back next game; IR: out through game 4
            known = [(a, b, c) for a, b, c in zip(nxt, pc, pe) if a is not None]
            for a, b, c in known:
                br["curve"].append((b - float(a)) ** 2); br["engine"].append((c - float(a)) ** 2)
                calib[round(b, 1)][0] += 1; calib[round(b, 1)][1] += float(a)
            if len(known) == 4:
                eg["act"].append(sum(float(a) for a, _, _ in known)); eg["curve"].append(sum(b for _, b, _ in known)); eg["engine"].append(sum(c for _, _, c in known))
    P(f"\n  Brier score on 'plays this game' over the next four games (lower = better): engine {np.mean(br['engine']):.3f}  curve {np.mean(br['curve']):.3f}  ({100*(np.mean(br['curve'])/np.mean(br['engine'])-1):+.0f}%)")
    a, c, e = np.array(eg["act"]), np.array(eg["curve"]), np.array(eg["engine"])
    P(f"  games played over the next four (states with four games left, n={len(a)}): actual {a.mean():.2f}  engine {e.mean():.2f} (MAE {np.abs(e-a).mean():.2f})  curve {c.mean():.2f} (MAE {np.abs(c-a).mean():.2f})")
    for kk in (1, 2, 3, 4):
        m = [i for i, r in enumerate([r for r in S if len([x for x in r[3] if x is not None]) == 4]) if r[2] == kk]
    P("  calibration of the curve (predicted P(plays) -> share who did):")
    for pb in sorted(calib):
        n, s, _ = calib[pb]
        if n >= 40: P(f"    {pb:.1f}: {s/n:.2f}  (n={n})")
    P("\n  by missed-so-far, next game only: actual play rate vs engine vs curve (LOYO)")
    for kk in (1, 2, 3, 4, 5, 6):
        x = [r for r in S if r[2] == kk and r[3][0] is not None]
        if not x: continue
        act = np.mean([float(r[3][0]) for r in x]); eng = 1.0 if kk < 4 else (0.0 if kk < 4 else 1.0)
        pcs = []
        for Y in years:
            cont = fit_cont([r for r in S if r[0] != Y]); pcs += [1 - cont[kk]] * sum(1 for r in x if r[0] == Y)
        P(f"    missed {kk}: n={len(x):4d}  actually played next {act:.2f}   engine assumes {eng:.2f}   curve {np.mean(pcs):.2f}")
    log.close()
    return full

if __name__ == "__main__":
    main()
