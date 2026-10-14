import json, os, sys
sys.path.insert(0, r'E:\MyFantasyFootball\sim_lab')
from dyn_common import World, FORMATS, _norm_name, DATA_DIR
w = World(2025); w.rows(FORMATS['1qb'], 2025)
w._repl.update({(2025, p): w._repl[(2025, p)] for p in ('QB','RB','WR','TE')})
jm = json.load(open(os.path.join(DATA_DIR, 'jm_scores.json'), encoding='utf-8'))['scores']
jmk = {(_norm_name(n), v['pos']): v['jm'] for n, v in jm.items() if v.get('jm') is not None}
out = []
for key, dr in w.draft.items():
    if dr[0] not in (2024, 2025) or key not in jmk or jmk[key] < 60: continue
    s = w.players[key]['by'].get(2025) or {}
    g = s.get('gp') or 0
    b = w.base_at(key, 2026)
    rel = w.rel(b[0], 2026, key[1]) if b else 0
    g26, _ = w.cur_season(key, 2026, 5)
    out.append((dr[0], key[1], key[0], dr[1], jmk[key], g, round(rel, 2), g26))
for r in sorted(out, key=lambda r: (r[0], -r[4])):
    print(('SLOW ' if (r[5] < 4 or r[6] < 1.0) else '     ') + ' '.join(map(str, r)))
