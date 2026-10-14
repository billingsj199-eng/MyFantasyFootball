#!/usr/bin/env python3
"""
PROMOTED BACKUP x CO-STARTER MARGIN (Jack 2026-10-10/11, follow-up to the fill-in margin for Chuba Hubbard): the PROMO layer
(promotedMult, RB x1.034 / WR x1.071 / TE x1.207 when a same-position regular is out) uses the old regular test (Clay half/g >= 5
and above his own). Rows it RELEASES under a 1.1x margin = weeks where every absent regular was within 10% of the player's own
level. Graded: wired boost vs no boost on exactly those rows, shadow x wired NMU base (research_promoted_backup.py, PB_NMU=1 form),
2019-25, final week out. Log promo_margin.log.
"""
import os, sys
os.environ["PB_VAR"] = "margin_import"          # keeps research_promoted_backup's own log untouched
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import research_promoted_backup as PB
LOG = open(os.path.join(HERE, "promo_margin.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()
MULT = {"RB": 1.034, "WR": 1.071, "TE": 1.207}

def absences(margin):
    src_regs = lambda roster, Y, team, ps, nm, cpg: [(r, rc) for r, rc in roster[(Y, team, ps)] if r != nm and rc > cpg * margin and rc >= PB.REG_MIN]
    import json
    from collections import defaultdict
    cal = PB.cal
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    tcache = {}; roster = defaultdict(list); games = {}
    for Y in PB.YEARS:
        W = 16 if Y <= 2020 else 17
        for nm, c in ch[str(Y)].items():
            ps = c.get("pos")
            if ps not in PB.SK: continue
            rec = cal.weekly_rec(nm, ps)
            if rec is None: continue
            team = cal.infer_team(rec, Y)
            gmv = (c.get("gm") or 0); half = max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0)
            cpg = half / gmv if gmv >= 4 else half / W
            gl = {}
            for w in rec.get("seasons", {}).get(str(Y), []):
                if cal.played(w) and w.get("opp"):
                    k = (Y, int(w["wk"]), w["opp"])
                    if k not in tcache: tcache[k] = PB.week_team(Y, int(w["wk"]), w["opp"])
                    gl[int(w["wk"])] = tcache[k]
            games[(nm, ps, Y)] = (team, cpg, gl)
            if team: roster[(Y, team, ps)].append((nm, cpg))
    out = {}
    for (nm, ps, Y), (team, cpg, gl) in games.items():
        if not team: continue
        regs = src_regs(roster, Y, team, ps, nm, cpg)
        rplay = {r: {w for w, t in games[(r, ps, Y)][2].items() if t == team} for r, _ in regs}
        for w, t in gl.items():
            if t != team: continue
            out[(cal.norm(nm), Y, w)] = sum(1 for r, _ in regs if w not in rplay[r])
    return out

def main():
    BR = PB.BR; X = BR.SN.setup(); n = X["n"]
    act, year, wk, pos, name, adp = X["act"], X["year"], X["wk"], X["pos"], X["name"], X["adp"]
    SH, _ = BR.shadow_current(X)
    finw = np.where(year <= 2020, 17, 18)
    import research_next_man_up as R
    nlog = os.path.join(HERE, "next_man_up.log"); keep = open(nlog, encoding="utf-8").read() if os.path.exists(nlog) else None
    if keep is not None: R.LOG.close(); open(nlog, "w", encoding="utf-8").write(keep)
    Ev, _c = R.events(); TODAY, LV = BR.live_today(X)
    adpx = np.where(np.isnan(adp), 999.0, adp); nbase = (adpx <= 150) & (wk != finw) & ~LV["inh"] & (SH >= 3)
    idx = {(R.nz(name[i]), int(year[i]), int(wk[i])): i for i in range(n)}; NMU = np.ones(n)
    for r in Ev:
        i = idx.get((R.nz(r["n"]), r["Y"], r["wk"]))
        if i is None or not nbase[i] or r["rank"] > 6: continue
        NMU[i] = 1.04 if r["rank"] == 1 else 0.99 if r["rank"] <= 3 else 1.03
    SH = SH * NMU
    A0, A1 = absences(1.0), absences(1.1)
    nab0 = np.array([A0.get((PB.cal.norm(name[i]), int(year[i]), int(wk[i])), 0) if pos[i] in PB.SK else 0 for i in range(n)])
    nab1 = np.array([A1.get((PB.cal.norm(name[i]), int(year[i]), int(wk[i])), 0) if pos[i] in PB.SK else 0 for i in range(n)])
    ok = np.isin(pos, PB.SK) & (wk != finw) & (SH >= 1) & np.isfinite(act)
    mult = np.array([MULT.get(p, 1.0) for p in pos])
    wired = np.where(ok & (nab0 > 0), SH * mult, SH); marg = np.where(ok & (nab1 > 0), SH * mult, SH)
    rel = ok & (nab0 > 0) & (nab1 == 0)
    mse = lambda q, m: float(np.mean((q[m] - act[m]) ** 2))
    P(f"rows {int(ok.sum()):,}; promoted under wired rule {int((ok & (nab0 > 0)).sum()):,}; under 1.1x margin {int((ok & (nab1 > 0)).sum()):,}; RELEASED {int(rel.sum())}")
    for lab, m in (("released, all", rel), *((f"released, {ps}", rel & (pos == ps)) for ps in PB.SK)):
        if m.sum() < 5: P(f"  {lab}: n {int(m.sum())}"); continue
        wins = sum(1 for y in PB.YEARS if (m & (year == y)).sum() >= 3 and mse(marg, m & (year == y)) < mse(wired, m & (year == y)))
        fw = sum(1 for y in (2022, 2023, 2024, 2025) if (m & (year == y)).sum() >= 3 and mse(marg, m & (year == y)) < mse(wired, m & (year == y)))
        P(f"  {lab:18s} n {int(m.sum()):4d}  actual {act[m].mean():5.2f}  no boost {SH[m].mean():5.2f}  wired boost {wired[m].mean():5.2f}  actual/no-boost {act[m].sum()/SH[m].sum():.3f}"
          f"  | margin (no boost) error {100*(mse(marg, m)/mse(wired, m)-1):+.2f}%  seasons better {wins}/7, 2022-25 {fw}/4")
    P(f"  whole board (RB/WR/TE rows): {100*(mse(marg, ok)/mse(wired, ok)-1):+.4f}%")
    LOG.close()

if __name__ == "__main__":
    main()
