#!/usr/bin/env python3
"""
When a fantasy STARTER sits, what happens to everyone else on his offense? 2019-25, same base as the other
Sim Lab backtests (bt_common: P=5 blend x Vegas x FPA - Vegas already reflects the absence when the line was
set knowing it). Absent starter = preseason guide >= 8 half-PPR a game (QB >= 13), had played that season,
missing a game his team played. For every OTHER player on that team that week: actual / projected, split by
who is missing and by the player's own position, and by first missed game vs later ones.
Same-position rows are the raw vacancy bump (this base has no vacancy layer); other-position rows answer
"does losing a starter drag the rest of the offense beyond what Vegas prices?"
Log absence_teammates.log.
"""
import json, os, sys, io
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_common as B
import backtest_sim_calibration as cal
from backtest_sim_calibration import played, weekly_rec, infer_team
REPO = cal.REPO

def absences():
    ch = json.load(open(os.path.join(REPO, "data", "clay_history.json"), encoding="utf-8"))
    out = defaultdict(list)     # (Y, team, wk) -> [(pos, pg, k-th missed game, name)]
    for Y in range(2019, 2026):
        W = 16 if Y <= 2020 else 17
        for name, c in ch[str(Y)].items():
            pos = c.get("pos")
            if pos not in ("QB", "RB", "WR", "TE"): continue
            pg = max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2) / W
            if pg < (13 if pos == "QB" else 8): continue
            rec = weekly_rec(name, pos)
            if rec is None: continue
            team = infer_team(rec, Y)
            if not team: continue
            sched = cal.SCHEDULES.get(Y, {}).get(team, {})
            gw = sorted(int(w) for w in sched if 1 <= int(w) <= W + 1)
            pl = set(w["wk"] for w in rec.get("seasons", {}).get(str(Y), []) if played(w))
            seen = False; k = 0
            for w in gw:
                if w in pl: seen = True; k = 0; continue
                if not seen: continue
                k += 1
                out[(Y, B.tm(team), w)].append((pos, pg, k, name))
    return out

def main():
    log = open(os.path.join(HERE, "absence_teammates.log"), "w", encoding="utf-8")
    def P(s=""):
        print(s); log.write(s + "\n")
    A = absences()
    S = [s for s in B.iter_samples(verbose=False) if s["shipped"] >= 5]
    P(f"=== starters out -> the rest of the offense, 2019-25 ({len(S)} player-weeks projected 5+; {len(A)} team-weeks with an absent starter) ===")
    rows = []
    for s in S:
        ab = [a for a in A.get((s["year"], B.tm(s["team"]), s["wk"]), []) if a[3] != s["name"]]
        rows.append((s, ab))
    def line(lab, x):
        if len(x) < 80: P(f"   {lab:50s} n={len(x):5d} (too few)"); return
        act = np.array([r[0]["act"] for r in x]); sh = np.array([r[0]["shipped"] for r in x]); yrs = np.array([r[0]["year"] for r in x])
        per = [act[yrs == y].sum() / sh[yrs == y].sum() for y in range(2019, 2026) if (yrs == y).sum() >= 10]
        e = sh - act; t = e.mean() / (e.std() / np.sqrt(len(e)))
        P(f"   {lab:50s} n={len(x):5d}  actual/projected {act.sum()/sh.sum():.3f}  (t {-t:+5.1f})  seasons under 1.0: {sum(1 for v in per if v < 1)}/{len(per)}")
    base = [r for r in rows if not r[1]]
    P("  baseline - nobody missing:")
    for pos in ("QB", "RB", "WR", "TE"): line(f"{pos}", [r for r in base if r[0]["pos"] == pos])
    basev = {pos: sum(r[0]["act"] for r in base if r[0]["pos"] == pos) / sum(r[0]["shipped"] for r in base if r[0]["pos"] == pos) for pos in ("QB", "RB", "WR", "TE")}
    for out_pos in ("QB", "RB", "WR", "TE"):
        P(f"\n  a starting {out_pos} is out:")
        for pos in ("QB", "RB", "WR", "TE"):
            x = [r for r in rows if any(a[0] == out_pos for a in r[1]) and r[0]["pos"] == pos]
            tag = "  <- same position: the vacancy bump" if pos == out_pos else ""
            line(f"{pos} teammates{tag}", x)
        x1 = [r for r in rows if any(a[0] == out_pos and a[2] == 1 for a in r[1]) and r[0]["pos"] != out_pos]
        x2 = [r for r in rows if any(a[0] == out_pos and a[2] >= 2 for a in r[1]) and not any(a[0] == out_pos and a[2] == 1 for a in r[1]) and r[0]["pos"] != out_pos]
        line("other positions, his FIRST missed game", x1); line("other positions, later missed games", x2)
    P("\n  how many starters are missing (players at OTHER positions than the absentees):")
    for n in (1, 2, 3):
        x = [r for r in rows if len(r[1]) == n and not any(a[0] == r[0]["pos"] for a in r[1])] if n < 3 else [r for r in rows if len(r[1]) >= 3 and not any(a[0] == r[0]["pos"] for a in r[1])]
        line(f"{n}{'+' if n == 3 else ''} starter{'s' if n > 1 else ''} out", x)
    P("\n  elite absentee (guide 14+ a game; QB 18+) vs ordinary starter, other positions:")
    line("elite out", [r for r in rows if any(a[1] >= (18 if a[0] == 'QB' else 14) and a[0] != r[0]["pos"] for a in r[1])])
    line("ordinary starter out", [r for r in rows if r[1] and not any(a[1] >= (18 if a[0] == 'QB' else 14) for a in r[1]) and not any(a[0] == r[0]["pos"] for a in r[1])])
    P("\n  baseline ratios for reference: " + ", ".join(f"{p} {v:.3f}" for p, v in basev.items()))
    log.close()

if __name__ == "__main__":
    main()
