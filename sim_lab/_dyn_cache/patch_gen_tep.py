"""One-off patch: build_dynasty_sim.py emits TE-premium values (TEs only)."""
p = r'E:\MyFantasyFootball\sim_lab\build_dynasty_sim.py'
s = open(p, encoding='utf-8').read()


def rep(a, b):
    global s
    assert s.count(a) == 1, (a[:80], s.count(a))
    s = s.replace(a, b)


rep("""    for sc_key, sc_name in SCORINGS.items():
        if sc_key != 'ppr':
            w = World(LAST_DATA, scoring=sc_name)
        cands = set()
        for key, P in w.players.items():""",
"""    # TE premium (+0.5 / +1.0 per TE reception, backtest_dynasty_scoring.py --tep):
    # only TE values change, so those jobs value TEs only, stored under
    # '<fmt>_<scoring>_tep<x>'; the site ranks everyone client-side.
    TEPS = (0.5, 1.0)
    jobs = [(k, n, 0.0) for k, n in SCORINGS.items()] + [(k, n, t) for t in TEPS for k, n in SCORINGS.items()]
    out['meta']['teps'] = list(TEPS)
    for sc_key, sc_name, tep in jobs:
        if (sc_key, tep) != ('ppr', 0.0):
            w = World(LAST_DATA, scoring=sc_name, tep=tep)
        cands = set()
        for key, P in w.players.items():
            if tep and key[1] != 'TE':
                continue""")
rep("""            vk = fmt + '_' + sc_key
""", """            vk = fmt + '_' + sc_key + ('_tep%g' % tep if tep else '')
""")
rep("""                        base = score_rates({k: tot[k] / g_cur for k in STAT_KEYS}, w.sc)""",
    """                        base = score_rates({k: tot[k] / g_cur for k in STAT_KEYS}, w.sc_for(pos))""")
rep("""            if P['draft'] and P['draft'][0] == Y_NOW:
                cands.add(key)
        for fmt, starters""", """            if P['draft'] and P['draft'][0] == Y_NOW:
                cands.add(key)
        if tep:
            cands = {k for k in cands if k[1] == 'TE'}
        for fmt, starters""")
rep("""                    'v': 'val,win3,youth,rk,y0,y1,y2,y3,y4',""",
    """                    'v': 'val,win3,youth,rk,y0,y1,y2,y3,y4 (rk 0 on TE-premium keys: the site ranks client-side)',""")
rep("""            for i, (pk, x) in enumerate(sorted(vals.items(), key=lambda kv: -kv[1][0])):
                out['players'][pk]['v'][vk] = [round(x[0]), round(x[1]), round(x[2]), i + 1] + [round(y) for y in x[3]]""",
    """            for i, (pk, x) in enumerate(sorted(vals.items(), key=lambda kv: -kv[1][0])):
                out['players'][pk]['v'][vk] = [round(x[0]), round(x[1]), round(x[2]), 0 if tep else i + 1] + [round(y) for y in x[3]]""")
rep("""    for vk in ('1qb_ppr', '1qb_half', '1qb_std', 'sf_ppr'):
        top = sorted((e for e in out['players'].values() if vk in e['v']), key=lambda e: e['v'][vk][3])[:15]
        print(f'--- {vk} top 15: ' + ', '.join(f"{e['n']} {e['v'][vk][0]}" for e in top))""",
    """    for vk in ('1qb_ppr', '1qb_half', '1qb_std', 'sf_ppr'):
        top = sorted((e for e in out['players'].values() if vk in e['v']), key=lambda e: e['v'][vk][3])[:15]
        print(f'--- {vk} top 15: ' + ', '.join(f"{e['n']} {e['v'][vk][0]}" for e in top))
    for vk in ('1qb_ppr', '1qb_ppr_tep0.5', '1qb_ppr_tep1'):
        te = sorted((e for e in out['players'].values() if e['pos'] == 'TE' and vk in e['v']), key=lambda e: -e['v'][vk][0])[:6]
        print(f'--- TEs {vk}: ' + ', '.join(f"{e['n']} {e['v'][vk][0]}" for e in te))""")
open(p, 'w', encoding='utf-8').write(s)
print('patched generator')
