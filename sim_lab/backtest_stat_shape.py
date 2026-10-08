#!/usr/bin/env python3
"""
CLAY-FREE STAT SHAPE (Jack 2026-10-08 "lets do it": replace Clay's season stat mix behind every player's components).
The engine splits a player's projected points into py / ptd / ry / rtd / rec / rcy / rctd using Clay's season line as the
SHAPE (compsWk = Clay per game x the chain; compsU updates ry / rec / rcy with usage). Clay's historical lines carry no
per-stat components, so history can only tune OUR shape; the Clay comparison is 2026 W1-4 (grade_stat_shape.py).
Shape candidates per player-week (per-game stat line, then rescaled so its half-PPR points equal the same reference level
for every candidate - only the SPLIT is graded):
  A  this season's per-game line (games before this week)        B  last season's per-game line (4+ games)
  C  position shape: pooled per-point shares from last season's pool, at the player's level
  shrunk: (g x A + K1 x B + K2 x C) / (g + K1 + K2), K1 in {2, 4, 8}, K2 in {1, 2, 4}
  oracle: this game's actual split at the same level (ceiling)
Grade: per-stat absolute error vs the actual stat line (half-PPR points per stat, so yards and TDs weigh as they score),
by position; (K1, K2) picked LOYO + forward per position. 2019-25 top-150 player-weeks. Log stat_shape.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
SN = BR.SN; cal = SN.NW.cal; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "stat_shape.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
STATS = ("py", "ptd", "ry", "rtd", "rec", "rcy", "rctd"); VAL = {"py": 0.04, "ptd": 4.0, "ry": 0.1, "rtd": 6.0, "rec": 0.5, "rcy": 0.1, "rctd": 6.0}
POSSTATS = {"QB": ("py", "ptd", "ry", "rtd"), "RB": ("ry", "rtd", "rec", "rcy", "rctd"), "WR": ("ry", "rtd", "rec", "rcy", "rctd"), "TE": ("rec", "rcy", "rctd")}


def pts_of(line): return sum(VAL[k] * line.get(k, 0.0) for k in STATS)


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    REF = np.maximum(SHADOW, 0.5)   # the level every candidate is scaled to (only the split is graded)
    base = top150 & ~final & ~LV["inh"] & (SHADOW >= 3)
    # per player-season game lines
    logs = {}
    def games_of(nm, ps, Y):
        k = (nm, ps, Y)
        if k in logs: return logs[k]
        rec = cal.weekly_rec(nm, ps); out = {}
        for w in (rec or {}).get("seasons", {}).get(str(Y), []):
            if cal.played(w) and isinstance(w.get("fpts"), (int, float)): out[int(w["wk"])] = {s: float(w.get(s) or 0) for s in STATS}
        logs[k] = out; return out
    def mean_line(rows):
        if not rows: return None
        return {s: float(np.mean([r[s] for r in rows])) for s in STATS}
    # position shape per point from last season's pool (players with 8+ games, by position)
    shape_py = {}
    for Y in YEARS:
        acc = {ps: defaultdict(float) for ps in POS4}; ptsum = {ps: 0.0 for ps in POS4}
        for i in np.where((year == Y) & top150)[0]:
            key = (name[i], pos[i], Y - 1)
            if key in shape_py.get("_seen", set()): continue
            shape_py.setdefault("_seen", set()).add(key)
            gl = games_of(name[i], pos[i], Y - 1)
            if len(gl) < 8: continue
            for r in gl.values():
                for s in STATS: acc[pos[i]][s] += r[s]
                ptsum[pos[i]] += pts_of(r)
        shape_py[Y] = {ps: ({s: acc[ps][s] / ptsum[ps] for s in STATS} if ptsum[ps] > 0 else None) for ps in POS4}
    P("position shapes (stat per half-PPR point, from the prior season's pool):")
    for Y in (2019, 2022, 2025):
        for ps in POS4:
            sh = shape_py[Y][ps]
            if sh: P(f"  {Y} {ps}: " + " ".join(f"{s} {sh[s]:.3f}" for s in POSSTATS[ps]))
    def scale(line, lvl):
        p0 = pts_of(line)
        return {s: line.get(s, 0.0) * (lvl / p0) for s in STATS} if p0 > 0 else None
    # build candidates per row
    K1G = (2, 4, 8); K2G = (1, 2, 4)
    CANDS = ["A this season", "B last season", "C position shape"] + [f"K1 {k1} K2 {k2}" for k1 in K1G for k2 in K2G]
    err = {c: {s: np.full(n, np.nan) for s in STATS} for c in CANDS + ["oracle"]}; tot = {c: np.full(n, np.nan) for c in CANDS + ["oracle"]}
    have = np.zeros(n, bool)
    for i in np.where(base)[0]:
        Y = int(year[i]); ps = pos[i]; gl = games_of(name[i], ps, Y); a_rows = [gl[w] for w in gl if w < wk[i]]; actual = gl.get(int(wk[i]))
        if actual is None: continue
        A = mean_line(a_rows); B = mean_line(list(games_of(name[i], ps, Y - 1).values())) if len(games_of(name[i], ps, Y - 1)) >= 4 else None
        shp = shape_py[Y][ps]; C = {s: shp[s] * REF[i] for s in STATS} if shp else None
        lvl = REF[i]; lines = {}
        lines["A this season"] = A; lines["B last season"] = B; lines["C position shape"] = C
        gA = len(a_rows)
        for k1 in K1G:
            for k2 in K2G:
                num = {s: 0.0 for s in STATS}; den = 0.0
                for L_, w_ in ((A, gA), (B, k1 if B else 0), (C, k2 if C else 0)):
                    if L_ is None or w_ <= 0: continue
                    for s in STATS: num[s] += w_ * L_[s]
                    den += w_
                lines[f"K1 {k1} K2 {k2}"] = {s: num[s] / den for s in STATS} if den > 0 else None
        lines["oracle"] = actual
        have[i] = True
        for c, L_ in lines.items():
            if L_ is None: continue
            S = scale(L_, lvl)
            if S is None: continue
            for s in STATS: err[c][s][i] = abs(S[s] - actual[s]) * VAL[s]
            tot[c][i] = sum(err[c][s][i] for s in POSSTATS[ps])
    P(f"\n=== STAT SHAPE: {int(have.sum()):,} top-150 player-weeks 2019-25, every candidate scaled to the same level (shadow number) ===")
    def mean_err(c, m): v = tot[c][m]; return float(np.nanmean(v)) if np.isfinite(v).any() else np.nan
    for ps in POS4:
        m = have & (pos == ps); ref = "A this season"
        P(f"\n--- {ps} (n{int(m.sum())}) : points-weighted abs error per stat, vs A (this season alone) ---")
        for c in CANDS + ["oracle"]:
            v = tot[c][m]; ok_ = np.isfinite(v)
            if ok_.sum() < 100: continue
            mref = tot[ref][m]; both = ok_ & np.isfinite(mref); d = 100 * (np.nanmean(v[both]) / np.nanmean(mref[both]) - 1)
            wins = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and np.nanmean(tot[c][m & (year == y)]) < np.nanmean(tot[ref][m & (year == y)]) - 1e-12)
            P(f"  {c:18s} n{int(ok_.sum()):5d} | total {np.nanmean(v[both]):.3f} ({d:+6.2f}% vs A, {wins}/7) | " + " ".join(f"{s} {np.nanmean(err[c][s][m][both]):.3f}" for s in POSSTATS[ps]))
        for glab, gm in (("games 1-3", (g >= 1) & (g <= 3)), ("games 4-8", (g >= 4) & (g <= 8)), ("games 9+", g >= 9), ("rookies (no B)", np.array([tot['B last season'][i] != tot['B last season'][i] for i in range(n)]))):
            mm = m & gm; best = min([c for c in CANDS if np.isfinite(tot[c][mm]).sum() >= 50], key=lambda c: mean_err(c, mm), default=None)
            if best: P(f"    {glab:16s} n{int(mm.sum()):5d} | best {best} ({100*(mean_err(best, mm)/mean_err('A this season', mm)-1):+.2f}% vs A) | C alone {100*(mean_err('C position shape', mm)/mean_err('A this season', mm)-1):+.2f}%")
        # LOYO / forward pick of (K1, K2)
        KC = [f"K1 {k1} K2 {k2}" for k1 in K1G for k2 in K2G]
        for flab, folds in (("LOYO", [([y for y in YEARS if y != t], t) for t in YEARS]), ("forward", [([y for y in YEARS if y < t], t) for t in FWD])):
            picks = []; out = np.full(n, np.nan)
            for tr, te in folds:
                mm = m & np.isin(year, tr); c = min(KC, key=lambda c_: mean_err(c_, mm)); picks.append(c.replace("K1 ", "").replace(" K2 ", "/")); sel = m & (year == te); out[sel] = tot[c][sel]
            tem = m & np.isin(year, [te for _, te in folds]); wins = sum(1 for _, te in folds if np.nanmean(out[tem & (year == te)]) < np.nanmean(tot["A this season"][tem & (year == te)]) - 1e-12)
            P(f"    {flab:8s} pick: {100*(np.nanmean(out[tem])/np.nanmean(tot['A this season'][tem])-1):+.2f}% vs A ({wins}/{len(folds)}) | picks {picks}")
    P("\nLimitations: level fixed to the shadow number for every candidate (split only); Clay's historical lines have no per-stat components, so the Clay comparison is 2026 W1-4 only; rookies have no B and take A + C; fumbles / interceptions not in the component set.")
    LOG.close()


if __name__ == "__main__":
    main()
