"""One-off patch: build_dynasty_sim.py emits points quintiles + replacement tables for league-aware DYN SIM."""
p = r'E:\MyFantasyFootball\sim_lab\build_dynasty_sim.py'
s = open(p, encoding='utf-8').read()


def rep(a, b):
    global s
    assert s.count(a) == 1, (a[:80], s.count(a))
    s = s.replace(a, b)


# replacement table per scoring/TEP world (computed on the 1QB pass)
rep("""            vk = fmt + '_' + sc_key + ('_tep%g' % tep if tep else '')
            rows = w.rows(starters, Y_NOW - 1)
            comps = Comps(rows, LAST_DATA, AGE_SCALE)
            vals = {}""",
"""            vk = fmt + '_' + sc_key + ('_tep%g' % tep if tep else '')
            dk = sc_key + ('_tep%g' % tep if tep else '')       # distribution key (format-free)
            rows = w.rows(starters, Y_NOW - 1)
            comps = Comps(rows, LAST_DATA, AGE_SCALE)
            want_d = fmt == '1qb'
            if want_d:
                tbl = w.repl_table(range(Y_NOW - 5, Y_NOW))
                out['meta'].setdefault('repl', {})[dk] = {'TE': tbl['TE']} if tep else tbl
            vals = {}""")
# vet + rookie distributions alongside the value
rep("""                        vet_ev, vc = comps.ev(pos, False, comps.feat_v(pos, age0, rel, gp1), Y_NOW, K,
                                              n_comps=5, local_linear=LL)""",
"""                        fv = comps.feat_v(pos, age0, rel, gp1)
                        vet_ev, vc = comps.ev(pos, False, fv, Y_NOW, K, n_comps=5, local_linear=LL)
                        vet_d = comps.ev_dist(pos, False, fv, Y_NOW, K, local_linear=LL) if want_d else None""")
rep("""                vet_ev = None
                g_behind = 99""", """                vet_ev = None
                vet_d = None
                g_behind = 99""")
rep("""                    ev = [(1 - a) * x + a * (y if vet_ev else 0) for x, y in zip(r_ev, vet_ev or r_ev)]
                    cmp = vc if (vet_ev and a >= 0.5) else rc""",
"""                    ev = [(1 - a) * x + a * (y if vet_ev else 0) for x, y in zip(r_ev, vet_ev or r_ev)]
                    cmp = vc if (vet_ev and a >= 0.5) else rc
                    dist = None
                    if want_d:
                        r_d = comps.ev_dist(pos, True, Comps.feat_rookie(pick, age0), Y_NOW, K, local_linear=LL)
                        dist = [[(1 - a) * x + a * y for x, y in zip(rk, vk_)] for rk, vk_ in zip(r_d, vet_d)] if vet_d else r_d""")
rep("""                    if not vet_ev:
                        continue
                    ev, cmp = vet_ev, vc""", """                    if not vet_ev:
                        continue
                    ev, cmp = vet_ev, vc
                    dist = vet_d""")
rep("""                if vk == '1qb_ppr':
                    e['c'] = [[w.players[c[0]]['name'], c[1], round(c[2])] for c in cmp]""",
"""                if vk == '1qb_ppr':
                    e['c'] = [[w.players[c[0]]['name'], c[1], round(c[2])] for c in cmp]
                # season-points quintiles (league-aware VOR on the site); all-zero ranges dropped
                if want_d and dist and any(q > 0 for row in dist for q in row):
                    e.setdefault('d', {})[dk] = [[round(q) for q in row] for row in dist]""")
# picks: slot-group points quintiles
rep("""                for pname, x in dyn_picks.pick_values(curves, ratio, W_CLASS, Y_NOW, frac, YOUTH_W).items():
                    pk = pname + '|PICK'
                    e = out['players'].setdefault(pk, {'n': pname, 'pos': 'PICK', 'age': None, 'rookie': False,
                                                       'pick': None, 'g26': 0, 'v': {}, 'cls': {}})
                    e['cls'][vk] = round(x[4], 3)
                    vals[pk] = x[:4]""",
"""                pdist = dyn_picks.pick_dists(w, LAST_DATA, Y_NOW) if want_d else {}
                if pdist:
                    out['meta']['pickPos'] = pdist['_pos']
                for pname, x in dyn_picks.pick_values(curves, ratio, W_CLASS, Y_NOW, frac, YOUTH_W).items():
                    pk = pname + '|PICK'
                    e = out['players'].setdefault(pk, {'n': pname, 'pos': 'PICK', 'age': None, 'rookie': False,
                                                       'pick': None, 'g26': 0, 'v': {}, 'cls': {}})
                    e['cls'][vk] = round(x[4], 3)
                    if pname in pdist:
                        e.setdefault('d', {})[dk] = pdist[pname]
                    vals[pk] = x[:4]""")
rep("""                    'v': 'val,win3,youth,rk,y0,y1,y2,y3,y4 (rk 0 on TE-premium keys: the site ranks client-side)',""",
"""                    'v': 'val,win3,youth,rk,y0,y1,y2,y3,y4 (rk 0 on TE-premium keys: the site ranks client-side)',
                    'd': 'points quintiles (10/30/50/70/90) per season from Y_NOW, by scoring[_tep]; site prices VOR vs a league replacement and scales v by (league / 12-team default) — backtest_dynasty_league.py',
                    'frac': round(frac, 4),""")
open(p, 'w', encoding='utf-8').write(s)
print('patched generator')
