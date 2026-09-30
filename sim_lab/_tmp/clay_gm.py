import sys, json, os, numpy as np
sys.path.insert(0, ".")
import backtest_noclay_weekly as NW
from backtest_target_area import mse
S = NW.build_samples(); A = NW.arrays(S); n = len(S)
act, year, g, ppg, pos, clay, layers = A["act"], A["year"], A["g"], A["ppg"], A["pos"], A["clay"], A["layers"]
ch = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, A["name"])], dtype=float)
W = np.where(year <= 2020, 16.0, 17.0); ok = gm >= 4
clay_gm = np.where(ok, clay * W / np.maximum(gm, 1), clay)
ship = NW.blend(clay, g, ppg, NW.PRIOR_P) * layers; ship2 = NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers
lt = ok & (gm < W)
print(f"{n} player-weeks | rows whose Clay season had gm < full: {lt.sum()} ({lt.mean()*100:.1f}%) across {len(set(zip(year[lt], A['name'][lt])))} player-seasons | gm<=14: {(ok & (gm <= 14)).sum()}")
pc, w, ny = NW.pct_vs(ship2, ship, act, year); print(f"Clay pts/gm instead of pts/W, ALL rows: {pc:+.2f}% MSE ({w}/{ny} seasons better) | bias act/proj /W {act.mean()/ship.mean():.3f} -> /gm {act.mean()/ship2.mean():.3f}")
pc, w, ny = NW.pct_vs(ship2[lt], ship[lt], act[lt], year[lt]); print(f"  affected rows only: {pc:+.2f}% ({w}/{ny}) | bias /W {act[lt].mean()/ship[lt].mean():.3f} -> /gm {act[lt].mean()/ship2[lt].mean():.3f}")
for ps in ("QB", "RB", "WR", "TE"):
    m = lt & (pos == ps)
    if m.sum() >= 40: pc, w, ny = NW.pct_vs(ship2[m], ship[m], act[m], year[m]); print(f"  {ps} affected n={m.sum()}: {pc:+.2f}% ({w}/{ny}) bias /W {act[m].mean()/ship[m].mean():.3f} -> /gm {act[m].mean()/ship2[m].mean():.3f}")
for lab, m in (("gm 15-16", lt & (gm >= 15)), ("gm 11-14", lt & (gm >= 11) & (gm <= 14)), ("gm <= 10", lt & (gm <= 10)), ("first 4 games", lt & (g < 4)), ("games 4+", lt & (g >= 4))):
    if m.sum() >= 40: pc, w, ny = NW.pct_vs(ship2[m], ship[m], act[m], year[m]); print(f"  {lab:14s} n={m.sum()}: {pc:+.2f}% ({w}/{ny}) bias /W {act[m].mean()/ship[m].mean():.3f} -> /gm {act[m].mean()/ship2[m].mean():.3f}")
