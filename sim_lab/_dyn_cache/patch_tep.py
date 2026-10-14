"""One-off patch: TE premium (per-position scoring) in dyn_common.World."""
p = r'E:\MyFantasyFootball\sim_lab\dyn_common.py'
s = open(p, encoding='utf-8').read()


def rep(a, b):
    global s
    assert s.count(a) == 1, (a[:70], s.count(a))
    s = s.replace(a, b)


rep("    def __init__(self, last_data, shrink_g0=0.0, shrink_to=0.8, scoring='full_ppr'):",
    "    def __init__(self, last_data, shrink_g0=0.0, shrink_to=0.8, scoring='full_ppr', tep=0.0):")
rep("        self.sc = SCORING[scoring]",
    "        self.sc = SCORING[scoring]\n"
    "        # TE premium: + tep points per TE reception (season + weekly + rates)\n"
    "        self.tep = float(tep or 0.0)\n"
    "        self._sc_te = dict(self.sc, rc=self.sc['rc'] + self.tep) if self.tep else self.sc")
rep("                    self.pts[yr][key] = season_pts(s, self.sc)",
    "                    self.pts[yr][key] = season_pts(s, self.sc_for(pos))")
rep("        return sum(score_rates(s, self.sc) for w, s in wk if w > W)",
    "        sc = self.sc_for(key[1])\n        return sum(score_rates(s, sc) for w, s in wk if w > W)")
rep("        tot = score_rates(br, self.sc)\n        rush = (br['ry'] * self.sc['ry'] + br['rtd'] * self.sc['rtd']) / tot if tot > 0 else 0.0",
    "        sc = self.sc_for(key[1])\n        tot = score_rates(br, sc)\n"
    "        rush = (br['ry'] * sc['ry'] + br['rtd'] * sc['rtd']) / tot if tot > 0 else 0.0")
rep("    def age(self, key, Y):",
    "    def sc_for(self, pos):\n        return self._sc_te if pos == 'TE' else self.sc\n\n    def age(self, key, Y):")
open(p, 'w', encoding='utf-8').write(s)
print('patched dyn_common')

# backtest_dynasty_scoring.py: TEP rows + --quick (shipped + plain mean only)
p = r'E:\MyFantasyFootball\sim_lab\backtest_dynasty_scoring.py'
s = open(p, encoding='utf-8').read()
rep("SCORINGS = (('PPR', 'full_ppr'), ('HALF', 'half_ppr'), ('STD', 'non_ppr'))",
    "SCORINGS = (('PPR', 'full_ppr', 0.0), ('HALF', 'half_ppr', 0.0), ('STD', 'non_ppr', 0.0))\n"
    "TEP_SCORINGS = (('PPR+TEP.5', 'full_ppr', 0.5), ('PPR+TEP1', 'full_ppr', 1.0), ('HALF+TEP.5', 'half_ppr', 0.5))")
rep("    for sc_lbl, sc in SCORINGS:\n        w = World(LAST_DATA, scoring=sc)",
    "    tep_only = '--tep' in sys.argv\n"
    "    for sc_lbl, sc, tep in (TEP_SCORINGS if tep_only else SCORINGS):\n"
    "        w = World(LAST_DATA, scoring=sc, tep=tep)")
rep("        for lbl, ll, age, cw in CONFIGS:",
    "        for lbl, ll, age, cw in (CONFIGS[:2] if tep_only else CONFIGS):")
rep("                        base = score_rates({k: r['tot'][k] / r['gcur'] for k in STAT_KEYS}, w.sc)",
    "                        base = score_rates({k: r['tot'][k] / r['gcur'] for k in STAT_KEYS}, w.sc_for(pos))")
open(p, 'w', encoding='utf-8').write(s)
print('patched backtest_dynasty_scoring')
