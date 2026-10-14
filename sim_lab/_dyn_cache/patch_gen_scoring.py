"""One-off patch: build_dynasty_sim.py -> 3 scorings + compact lazy-load layout."""
p = r'E:\MyFantasyFootball\sim_lab\build_dynasty_sim.py'
s = open(p, encoding='utf-8').read()
i = s.index("    w = World(LAST_DATA)\n    W = args.week")
j = s.index("if __name__ == '__main__':")
new_main = r'''    SCORINGS = {'ppr': 'full_ppr', 'half': 'half_ppr', 'std': 'non_ppr'}
    w = World(LAST_DATA)
    W = args.week if args.week is not None else completed_weeks(w)
    frac = (WEEKS - W) / WEEKS
    print(f'2026 valuation after week {W} (year-0 share {frac:.2f})')

    # Compact layout (lazy-loaded by the site): per player
    #   v[<fmt>_<scoring>] = [val, win3, youth, rank, y0..y4]  (ints; y0 = rest of 2026)
    #   c = closest comps for the 1QB PPR year-0 read: [[name, season, VOR], ...]
    out = {'meta': {'built': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), 'valuationYear': Y_NOW,
                    'week': W, 'dataThrough': LAST_DATA, 'K': K, 'youthW': YOUTH_W, 'cCur': C_CUR,
                    'rRookie': R_ROOKIE, 'localLinear': list(LL), 'ageScale': AGE_SCALE,
                    'formats': FORMATS, 'scorings': list(SCORINGS),
                    'v': 'val,win3,youth,rk,y0,y1,y2,y3,y4',
                    'note': 'PROTOTYPE — comparables model; 2026 weeks 1-%d folded in' % W},
           'players': {}}

    for sc_key, sc_name in SCORINGS.items():
        if sc_key != 'ppr':
            w = World(LAST_DATA, scoring=sc_name)
        cands = set()
        for key, P in w.players.items():
            if any(y in P['by'] for y in (2023, 2024, 2025)) or w.weekly.get(key, {}).get(Y_NOW):
                cands.add(key)
            if P['draft'] and P['draft'][0] == Y_NOW:
                cands.add(key)
        for fmt, starters in FORMATS.items():
            vk = fmt + '_' + sc_key
            rows = w.rows(starters, Y_NOW - 1)
            comps = Comps(rows, LAST_DATA, AGE_SCALE)
            vals = {}
            for key in cands:
                pos = key[1]
                age0 = w.age(key, Y_NOW)
                if age0 is None:
                    continue
                P = w.players[key]
                g_cur, tot = w.cur_season(key, Y_NOW, W)
                dr = P['draft']
                drafted_now = bool(dr and dr[0] == Y_NOW)
                # undrafted first-year players: no NFL history before 2026
                rookie = drafted_now or (not any(y < Y_NOW for y in P['by']) and g_cur > 0 and not dr)
                vet_ev = None
                g_behind = 99
                if g_cur > 0 or not rookie:
                    b = w.base_at(key, Y_NOW, W, C_CUR) if not rookie else None
                    if rookie:
                        base = score_rates({k: tot[k] / g_cur for k in STAT_KEYS}, w.sc)
                        gp1 = min(17.0, g_cur * 17.0 / max(W, 1))
                    elif b:
                        base, gp1 = b[0], b[1]
                        g_behind = b[4]
                    else:
                        base = None
                    if base is not None:
                        rel = w.rel(base, Y_NOW, pos)
                        if not rookie and g_behind < LOW_G:
                            rel = (g_behind * rel + LOW_G0 * LOW_TO) / (g_behind + LOW_G0)
                        vet_ev, vc = comps.ev(pos, False, comps.feat_v(pos, age0, rel, gp1), Y_NOW, K,
                                              n_comps=5, local_linear=LL)
                if rookie:
                    pick = dr[1] if drafted_now else UDFA_PICK
                    r_ev, rc = comps.ev(pos, True, Comps.feat_rookie(pick, age0), Y_NOW, K, n_comps=5, local_linear=LL)
                    a = g_cur / (g_cur + R_ROOKIE) if vet_ev else 0.0
                    ev = [(1 - a) * x + a * (y if vet_ev else 0) for x, y in zip(r_ev, vet_ev or r_ev)]
                    cmp = vc if (vet_ev and a >= 0.5) else rc
                else:
                    if not vet_ev:
                        continue
                    ev, cmp = vet_ev, vc
                win3 = ev[0] * frac + ev[1] + ev[2]
                youth = ev[3] + ev[4]
                pk = P['name'] + '|' + pos
                e = out['players'].setdefault(pk, {'n': P['name'], 'pos': pos, 'age': age0, 'rookie': rookie,
                                                   'pick': (dr[1] if drafted_now else None), 'g26': g_cur, 'v': {}})
                if vk == '1qb_ppr':
                    e['c'] = [[w.players[c[0]]['name'], c[1], round(c[2])] for c in cmp]
                vals[pk] = (win3 + YOUTH_W * youth, win3, youth, [ev[0] * frac] + list(ev[1:]))
            for i, (pk, x) in enumerate(sorted(vals.items(), key=lambda kv: -kv[1][0])):
                out['players'][pk]['v'][vk] = [round(x[0]), round(x[1]), round(x[2]), i + 1] + [round(y) for y in x[3]]
            print(f'{vk}: {len(vals)} players valued')

    with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write('// Dynasty SIM values (PROTOTYPE) — built by sim_lab/build_dynasty_sim.py. Do not hand-edit.\n')
        f.write('window.DYNASTY_SIM_2026 = ' + json.dumps(out, separators=(',', ':')) + ';\n')
    print(f'wrote {args.out}: {len(out["players"])} players, {os.path.getsize(args.out) // 1024} KB')
    for vk in ('1qb_ppr', '1qb_half', '1qb_std', 'sf_ppr'):
        top = sorted((e for e in out['players'].values() if vk in e['v']), key=lambda e: e['v'][vk][3])[:15]
        print(f'--- {vk} top 15: ' + ', '.join(f"{e['n']} {e['v'][vk][0]}" for e in top))


'''
s = s[:i] + new_main + s[j:]
s = s.replace("from dyn_common import World, Comps, FORMATS, WEEKS, SC, STAT_KEYS, score_rates, DATA_DIR",
              "from dyn_common import World, Comps, FORMATS, WEEKS, STAT_KEYS, score_rates, DATA_DIR")
s = s.replace("PPR. 1QB (QB12/RB30/WR42/TE12) and SF (QB24/...).",
              "PPR / Half / STD x 1QB (QB12/RB30/WR42/TE12) and SF (QB24/...).")
open(p, 'w', encoding='utf-8').write(s)
print('patched')
