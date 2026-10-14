#!/usr/bin/env python3
"""
PROMOTED BACKUPS (Jack 2026-10-08: Will Shipley 4.7 with Saquon + Tank Bigsby out - "make sure that goes for all players
replacing injured guys in front of them in depth chart").

Question: on the weeks a REGULAR ahead of him sits (same team + position, Clay per game >= 5.0 half-PPR and above his own -
the fill-in study's definition), how does the live shadow (vacated pool inside it) do for the backup who plays? If promoted
backups run above the number, a promotion multiplier by position x how many regulars are out x his own level is tested.

Rows: backtest_base_remeasure / backtest_shadow_next harness (2019-25 player-weeks he played, final week dropped), RB/WR/TE,
shadow >= 1. Ratio = sum(actual) / sum(shadow) per cell; 'none absent' rows are the calibration reference.
Rule: x M[pos][cell], M = shrunk (K 40) cell ratio / reference ratio, fit on the training seasons; LOYO + forward (2022-25),
bar: rows LOYO <= -0.3% with 5/7 and forward 3/4, whole-board MSE not worse. Writes promoted_backup.log.
"""
import json, os, sys, warnings
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
cal = BR.cal; YEARS = BR.YEARS; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
SK = ("RB", "WR", "TE"); REG_MIN = 5.0; K = 40
LOG = open(os.path.join(HERE, "promoted_backup" + ("_" + os.environ["PB_VAR"] if os.environ.get("PB_VAR") else "") + ".log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()


def week_team(Y, w, opp):
    o = cal.OPP_ALIAS.get(opp, opp)
    for t, s in cal.SCHEDULES.get(Y, {}).items():
        if s.get(str(w)) == o: return t
    return None


def absences():
    """{(norm name, Y, wk): (n regulars absent, his clay pg, lead absent?)} for RB/WR/TE player-weeks he played."""
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    tcache = {}; roster = defaultdict(list); games = {}
    for Y in YEARS:
        W = 16 if Y <= 2020 else 17
        for nm, c in ch[str(Y)].items():
            ps = c.get("pos")
            if ps not in SK: continue
            rec = cal.weekly_rec(nm, ps)
            if rec is None: continue
            team = cal.infer_team(rec, Y)
            gmv = (c.get("gm") or 0); half = max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0)
            cpg = half / gmv if gmv >= 4 else half / W
            gl = {}
            for w in rec.get("seasons", {}).get(str(Y), []):
                if cal.played(w) and w.get("opp"):
                    k = (Y, int(w["wk"]), w["opp"])
                    if k not in tcache: tcache[k] = week_team(Y, int(w["wk"]), w["opp"])
                    gl[int(w["wk"])] = tcache[k]
            games[(nm, ps, Y)] = (team, cpg, gl)
            if team: roster[(Y, team, ps)].append((nm, cpg))
    out = {}
    for (nm, ps, Y), (team, cpg, gl) in games.items():
        if not team: continue
        regs = [(r, rc) for r, rc in roster[(Y, team, ps)] if r != nm and rc > cpg and rc >= REG_MIN]
        lead = max(roster[(Y, team, ps)], key=lambda t: t[1])[0]
        rplay = {r: {w for w, t in games[(r, ps, Y)][2].items() if t == team} for r, _ in regs}
        for w, t in gl.items():
            if t != team: continue
            ab = [r for r, _ in regs if w not in rplay[r]]
            out[(cal.norm(nm), Y, w)] = (len(ab), cpg, int(lead in ab))
    return out


def main():
    X = BR.SN.setup(); n = X["n"]
    act, year, wk, pos, name, adp = X["act"], X["year"], X["wk"], X["pos"], X["name"], X["adp"]
    SH, _ = BR.shadow_current(X)
    finw = np.where(year <= 2020, 17, 18)
    # wired NEXT MAN UP rank cells (engine NMU: #1 x1.04, #2-3 x.99, #4-6 x1.03) so the promotion is fit ON TOP of them
    nlog = os.path.join(HERE, "next_man_up.log"); keep = open(nlog, encoding="utf-8").read() if os.path.exists(nlog) else None
    import research_next_man_up as R
    if keep is not None:
        R.LOG.close(); open(nlog, "w", encoding="utf-8").write(keep)
    Ev, _c = R.events()
    TODAY, LV = BR.live_today(X)
    adpx = np.where(np.isnan(adp), 999.0, adp)
    nbase = (adpx <= 150) & (wk != finw) & ~LV["inh"] & (SH >= 3)
    idx = {(R.nz(name[i]), int(year[i]), int(wk[i])): i for i in range(n)}
    NMU = np.ones(n)
    for r in Ev:
        i = idx.get((R.nz(r["n"]), r["Y"], r["wk"]))
        if i is None or not nbase[i] or r["rank"] > 6: continue
        NMU[i] = 1.04 if r["rank"] == 1 else 0.99 if r["rank"] <= 3 else 1.03
    if os.environ.get('PB_NMU') == '1':
        SH0 = SH.copy()
        SH = SH * NMU
        P(f"base = shadow x wired NMU ({int((NMU != 1).sum())} rows moved)")
    AB = absences()
    nab = np.zeros(n, int); own = np.full(n, np.nan); leadab = np.zeros(n, int)
    for i in range(n):
        if pos[i] not in SK: continue
        r = AB.get((cal.norm(name[i]), int(year[i]), int(wk[i])))
        if r: nab[i], own[i], leadab[i] = r
    ok = np.isin(pos, SK) & (wk != finw) & (SH >= 1) & np.isfinite(act)
    P(f"rows {ok.sum()} RB/WR/TE player-weeks (shadow >= 1); with a regular ahead absent: {(ok & (nab > 0)).sum()}")
    band = np.where(own < 4, "lo", np.where(own < 7, "mid", "hi"))
    def ratio(m): return act[m].sum() / max(1e-9, SH[m].sum())
    P("\nactual / shadow by cell (reference = no regular absent)")
    for ps in SK:
        ref = ok & (pos == ps) & (nab == 0)
        P(f"  {ps} reference {ratio(ref):.3f} (n {ref.sum()})")
        for b in ("lo", "mid", "hi"):
            for k_ in (1, 2):
                m = ok & (pos == ps) & (band == b) & ((nab == 1) if k_ == 1 else (nab >= 2))
                if m.sum() >= 5: P(f"    own {b:3s} (clay/g {'<4' if b == 'lo' else '4-7' if b == 'mid' else '7+'}) regulars out {k_}{'+' if k_ == 2 else ' '}: {ratio(m):.3f} (n {m.sum()})")
        m = ok & (pos == ps) & (leadab == 1)
        P(f"    lead regular out (any level): {ratio(m):.3f} (n {m.sum()})")

    VAR = os.environ.get('PB_VAR', 'full')
    def cell_of(i):
        if VAR == 'pos': return (pos[i], 'any', 1)
        if VAR == 'lead': return (pos[i], 'lead' if leadab[i] else 'other', 1)
        if VAR == 'leadlvl': return (pos[i], ('lead' if leadab[i] else 'other') + '-' + ('lo' if own[i] < 4 else 'up'), 1)
        return (pos[i], band[i], 1 if nab[i] == 1 else 2)
    def in_cell(c):
        ps, b, k_ = c
        if VAR == 'pos': return (pos == ps) & (nab > 0)
        if VAR == 'lead': return (pos == ps) & (nab > 0) & ((leadab == 1) if b == 'lead' else (leadab == 0))
        if VAR == 'leadlvl':
            lb, lv = b.split('-')
            return (pos == ps) & (nab > 0) & ((leadab == 1) if lb == 'lead' else (leadab == 0)) & ((own < 4) if lv == 'lo' else (own >= 4))
        return (pos == ps) & (band == b) & ((nab == 1) if k_ == 1 else (nab >= 2))
    cells = sorted({cell_of(i) for i in np.where(ok & (nab > 0))[0]})
    def fit(train):
        M = {}
        for c in cells:
            ps, b, k_ = c
            ref = train & (pos == ps) & (nab == 0)
            m = train & in_cell(c)
            if m.sum() < 5 or ref.sum() < 50: continue
            raw = ratio(m) / max(1e-9, ratio(ref)); nn = m.sum()
            M[c] = 1 + (raw - 1) * nn / (nn + K)
        return M
    def apply(M, rows):
        pr = SH.copy()
        for i in np.where(rows & (nab > 0))[0]:
            pr[i] = SH[i] * M.get(cell_of(i), 1.0)
        return pr
    def mse(pr, m): return float(np.mean((pr[m] - act[m]) ** 2))
    tgt = ok & (nab > 0)
    for label, folds in (("LOYO", [(tuple(y for y in YEARS if y != t), t) for t in YEARS]), ("FORWARD", [(tuple(y for y in YEARS if y < t), t) for t in FWD])):
        wins = 0; a0 = a1 = b0 = b1 = 0.0
        for tr, te in folds:
            M = fit(ok & np.isin(year, tr))
            pr = apply(M, ok & (year == te))
            r = tgt & (year == te); w = ok & (year == te)
            e0, e1 = mse(SH, r), mse(pr, r); wins += int(e1 < e0)
            a0 += e0 * r.sum(); a1 += e1 * r.sum(); b0 += mse(SH, w) * w.sum(); b1 += mse(pr, w) * w.sum()
        P(f"\n{label}: promoted rows MSE {100*(a1/a0-1):+.2f}% ({wins}/{len(folds)} seasons better), whole board {100*(b1/b0-1):+.3f}%")
    M = fit(ok)
    P("\nfitted multipliers (all seasons): " + ", ".join(f"{c[0]} {c[1]} out{c[2]}{'+' if c[2] == 2 else ''}: {v:.3f}" for c, v in sorted(M.items())))
    json.dump({"M": {f"{c[0]}|{c[1]}|{c[2]}": round(v, 3) for c, v in M.items()}, "K": K, "regMin": REG_MIN}, open(os.path.join(HERE, "data", "promoted_backup" + ("_" + VAR if VAR != "full" else "") + ".json"), "w"), indent=1)
    LOG.close()


if __name__ == "__main__":
    main()
