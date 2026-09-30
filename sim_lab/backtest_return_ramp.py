#!/usr/bin/env python3
"""
RETURN RAMP backtest (Jack 2026-09-30): the 09-15 first-game-back dock passed but was never wired. Re-graded
here as the ramp that will ship, on the shared bt_common base (P=5 blend x Vegas x FPA), snap counts decide
played / missed like backtest_return_game.py:

  missed 1 game       first game back x0.95
  missed 2-3 games    first game back x0.92
  missed 4+ games     first x0.85, second x0.92, third x0.96
  QB / RB / WR only (TE showed no effect)

Fixed schedule graded per season (MSE on the flagged rows, seasons better) and, for reference, the LOYO-picked
multiplier per cell. Log return_ramp_backtest.log.
"""
import os, sys
from collections import defaultdict
import numpy as np
from bt_common import iter_samples, to_arrays, load_games, YEARS, POS4
from backtest_return_game import snaps_year
import backtest_sim_calibration as cal
HERE = os.path.dirname(os.path.abspath(__file__))
RAMP = {"1": [0.95], "2-3": [0.92], "4+": [0.85, 0.92, 0.96]}

def main():
    log = open(os.path.join(HERE, "return_ramp_backtest.log"), "w", encoding="utf-8")
    def P(s=""):
        print(s); log.write(s + "\n")
    S = iter_samples(POS4, verbose=False); A = to_arrays(S); years = sorted(set(A["year"]))
    cell = np.array([""] * len(S), dtype=object)
    for Y in years:
        sn = snaps_year(Y); games = load_games(Y)
        tw_all = defaultdict(set)
        for (t, wk) in games: tw_all[t].add(wk)
        for i, s in enumerate(S):
            if s["year"] != Y: continue
            p = sn.get(cal.norm(s["name"]))
            if not p: continue
            playedw = {w for w, v in p.items() if v[0] > 0}
            if s["wk"] not in playedw: continue
            tw = sorted(tw_all.get(s["team"], [])); prior = [w for w in tw if w < s["wk"]]
            back = 0; j = len(prior) - 1
            while j >= 0 and prior[j] in playedw: back += 1; j -= 1
            k = 0
            while j >= 0 and prior[j] not in playedw: k += 1; j -= 1
            if k == 0 or not any(w in playedw for w in prior[:max(0, j + 1)]): continue
            b = "1" if k == 1 else "2-3" if k <= 3 else "4+"
            if back < len(RAMP[b]): cell[i] = f"{b}|{back + 1}"
    act, ship, pos, year = A["act"], A["shipped"], A["pos"], A["year"]
    P(f"=== return ramp on {len(S)} player-weeks 2019-25 (flagged rows: {int((cell != '').sum())}) ===")
    P("  actual / projected on the flagged rows (no ramp):")
    for b in ("1", "2-3", "4+"):
        for g in range(1, len(RAMP[b]) + 1):
            m = cell == f"{b}|{g}"
            if m.sum() < 30: continue
            byp = "  ".join(f"{p} {act[m & (pos == p)].sum()/ship[m & (pos == p)].sum():.2f} (n={int((m & (pos == p)).sum())})" for p in POS4 if (m & (pos == p)).sum() >= 15)
            P(f"    missed {b:3s}, game {g} back: n={int(m.sum()):4d}  {act[m].sum()/ship[m].sum():.3f}   | {byp}")
    mult = np.ones(len(S))
    for i in range(len(S)):
        if cell[i] and pos[i] != "TE":
            b, g = cell[i].split("|"); mult[i] = RAMP[b][int(g) - 1]
    fl = mult != 1
    P(f"\n  shipped ramp (QB/RB/WR, TE untouched): flagged rows {int(fl.sum())}")
    e0 = (ship - act) ** 2; e1 = (ship * mult - act) ** 2
    wins = sum(1 for Y in years if e1[fl & (year == Y)].mean() < e0[fl & (year == Y)].mean())
    P(f"    MSE on flagged rows {100*(e1[fl].mean()/e0[fl].mean()-1):+.2f}% ({wins}/{len(years)} seasons)   MAE {100*(np.abs(ship*mult-act)[fl].mean()/np.abs(ship-act)[fl].mean()-1):+.2f}%   all rows MSE {100*(e1.mean()/e0.mean()-1):+.3f}%")
    for p in POS4:
        m = fl & (pos == p)
        if m.sum() < 30: continue
        w = sum(1 for Y in years if (m & (year == Y)).sum() >= 5 and e1[m & (year == Y)].mean() < e0[m & (year == Y)].mean())
        P(f"    {p}: n={int(m.sum()):4d}  MSE {100*(e1[m].mean()/e0[m].mean()-1):+.2f}% ({w}/{len(years)})")
    m = cell != ""; te = m & (pos == "TE")
    if te.sum() >= 30: P(f"    TE (no dock): actual/projected {act[te].sum()/ship[te].sum():.3f} on {int(te.sum())} rows")
    P("\n  LOYO-picked multiplier per cell (reference; grid 1.0 .. 0.75):")
    grid = [1.0, 0.95, 0.9, 0.85, 0.8, 0.75]
    for b in ("1", "2-3", "4+"):
        for g in range(1, len(RAMP[b]) + 1):
            mm = (cell == f"{b}|{g}") & (pos != "TE")
            if mm.sum() < 40: continue
            picks = []
            for Y in years:
                tr = mm & (year != Y)
                picks.append(min(grid, key=lambda v: ((ship[tr] * v - act[tr]) ** 2).mean()))
            P(f"    missed {b:3s}, game {g} back: picks {picks}  shipped x{RAMP[b][g-1]}")
    log.close()

if __name__ == "__main__":
    main()
