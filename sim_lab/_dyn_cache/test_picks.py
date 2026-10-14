import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dyn_common import World, FORMATS  # noqa: E402
import dyn_picks  # noqa: E402

w = World(2025)
w.rows(FORMATS['1qb'], 2025)
cur = dyn_picks.slot_curves(w, 2025)
ratio, info = dyn_picks.class_ratio(w, 2025)
print('class info', info)
print('ratio by slot group:', {g: round(sum(ratio[s] for s in r) / len(r), 2) for g, r in dyn_picks.GROUPS.items()})
pv = dyn_picks.pick_values(cur, ratio, 0.35, 2026, 14 / 18, 1.5)
for P in (2027, 2028, 2029, 2030):
    print(P, ', '.join(f"{g} {pv[f'{P} {g}'][0]:.0f} (x{pv[f'{P} {g}'][4]:.2f})" for g in dyn_picks.GROUPS))
