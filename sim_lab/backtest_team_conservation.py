#!/usr/bin/env python3
"""
TEAM CONSERVATION CHECK (Jack 2026-10-09: "add pierce to the pool and test the conservation check").
Question: when a pass catcher sits, the QB is not docked (backtest_qb_vacated_targets.py), so the team's receiving production
should mostly survive. Today's layers (pool .75 inside the shadow, NMU cells, PROMO, TEAM_VAC k .2) hand teammates only part of
the missing player's points. Conservation rule tested here: per team-week, LOST = the absent regulars' own unboosted shadow
(latest row in the prior 4 weeks); GAINED = sum over healthy pass catchers of (shipped base - unboosted shadow). If GAINED <
c x LOST, the gap is topped up across the healthy pass catchers (by projection share or by trailing target share).
Base = shipped: shadow (pool inside) x NMU x PROMO x (1 + .2 x vacated share).
Grading (house): rows RB/WR/TE shadow >= 1, final week out; LOYO + forward pick-best over c, bar LOYO < -0.3% on touched rows
5/7, forward 3/4, board not worse. Log team_conservation.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
_tvlog = os.path.join(HERE, "team_vacated_boost.log")
_tvkeep = open(_tvlog, encoding="utf-8").read() if os.path.exists(_tvlog) else None
import backtest_team_vacated_boost as TV
TV.LOG.close()
if _tvkeep is not None: open(_tvlog, "w", encoding="utf-8").write(_tvkeep)   # importing truncates its log - restore
BR = TV.BR; cal = TV.cal; YEARS = TV.YEARS; FWD = TV.FWD; SK = TV.SK; PROMO = TV.PROMO
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "team_conservation.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()


def main():
    X = BR.SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, name, adp, team = X["act"], X["year"], X["wk"], X["pos"], X["name"], X["adp"], X["team"]
    SH, _ = BR.shadow_current(X)
    finw = np.where(year <= 2020, 17, 18)
    nlog = os.path.join(HERE, "next_man_up.log"); keep = open(nlog, encoding="utf-8").read() if os.path.exists(nlog) else None
    import research_next_man_up as R
    if keep is not None: R.LOG.close(); open(nlog, "w", encoding="utf-8").write(keep)
    Ev, _c = R.events(); TODAY, LV = BR.live_today(X)
    adpx = np.where(np.isnan(adp), 999.0, adp); nbase = (adpx <= 150) & (wk != finw) & ~LV["inh"] & (SH >= 3)
    idx = {(R.nz(name[i]), int(year[i]), int(wk[i])): i for i in range(n)}
    NMU = np.ones(n)
    for r in Ev:
        i = idx.get((R.nz(r["n"]), r["Y"], r["wk"]))
        if i is None or not nbase[i] or r["rank"] > 6: continue
        NMU[i] = 1.04 if r["rank"] == 1 else 0.99 if r["rank"] <= 3 else 1.03
    tg, promo, cg = TV.tables()
    PR = np.ones(n)
    for i in range(n):
        if pos[i] in PROMO and (cal.norm(name[i]), int(year[i]), int(wk[i])) in promo: PR[i] = PROMO[pos[i]]
    poolm = np.where(F["on"], np.power(F["pm"], 0.75), 1.0)
    U = SH / np.maximum(poolm, 1e-9)                        # unboosted shadow (no pool)
    team_wks = defaultdict(list)
    for (Y, t, w) in tg: team_wks[(Y, t)].append(w)
    for k in team_wks: team_wks[k].sort()
    # absent regulars per team-week (same definition as TEAM_VAC)
    absent = {}
    for (Y, t), wl in team_wks.items():
        for w in wl:
            prior = [u for u in wl if u < w][-3:]
            if len(prior) < 2: continue
            tot = 0.0; by = defaultdict(float); gp = defaultdict(int)
            for u in prior:
                for kk, v in tg[(Y, t, u)].items(): tot += v; by[kk] += v; gp[kk] += 1
            if tot < 30: continue
            ab = [(kk, v / tot) for kk, v in by.items() if gp[kk] >= 2 and v / tot >= 0.10 and kk not in tg[(Y, t, w)]]
            absent[(Y, t, w)] = (ab, {kk: v / tot for kk, v in by.items()})
    rowsby = defaultdict(list)
    for i in range(n):
        if pos[i] in SK: rowsby[(cal.norm(name[i]), int(year[i]))].append(i)
    def lost_of(nm, Y, w):
        rs = [i for i in rowsby.get((cal.norm(nm), Y), []) if w - 4 <= int(wk[i]) < w]
        if not rs: return np.nan
        return float(U[max(rs, key=lambda i: int(wk[i]))])
    vac = np.full(n, np.nan); LOST = np.zeros(n); tsh = np.zeros(n); key_of = [None] * n
    lost_cache = {}; miss_lost = [0, 0]
    for i in range(n):
        if not (team[i] and pos[i] in SK): continue
        k = (int(year[i]), team[i], int(wk[i]))
        if k not in absent: continue
        ab, shares = absent[k]; vac[i] = sum(s for _, s in ab)
        if k not in lost_cache:
            L = 0.0
            for (nm, ps), s in ab:
                l = lost_of(nm, k[0], k[2]); miss_lost[1] += 1
                if np.isnan(l): miss_lost[0] += 1; L = -1e9; continue   # any absentee without a read -> team-week not graded
                L += l
            lost_cache[k] = (L, any(ps in ("WR", "TE") for (nm, ps), s in ab))
        LOST[i] = lost_cache[k][0]; key_of[i] = k
        nn = cal.norm(name[i]); tsh[i] = next((s for (nm, ps), s in shares.items() if cal.norm(nm) == nn), 0.0)
    B1 = SH * NMU * PR
    ok = np.isin(pos, SK) & (wk != finw) & (SH >= 1) & np.isfinite(act) & np.isfinite(vac)
    B1 = np.where(ok, B1 * (1 + 0.2 * np.nan_to_num(vac)), B1)
    G = B1 - U
    P(f"rows {int(ok.sum())}; team-weeks with an absence {sum(1 for k, v in absent.items() if v[0])}; absent regulars with no recent row {miss_lost[0]} of {miss_lost[1]}")
    grp = defaultdict(list)
    for i in np.where(ok)[0]:
        if key_of[i] is not None: grp[key_of[i]].append(i)
    tw = [(k, np.array(v)) for k, v in grp.items() if lost_cache[k][0] > 0]
    P(f"team-weeks graded (absence with a lost read, healthy rows): {len(tw)}")
    P("\nDIAGNOSTIC: share of the absent players' points the healthy rows actually gained vs what we gave them")
    P("  (actual gain = sum act - sum unboosted shadow; given = sum shipped - sum unboosted)")
    for lab, lo, hi in (("vac .10-.20", .10, .20), ("vac .20-.30", .20, .30), ("vac .30-.40", .30, .40), ("vac .40+", .40, 9), ("ALL", 0, 9)):
        sel = [(k, r) for k, r in tw if lo <= vac[r[0]] < hi]
        if not sel: continue
        L = sum(lost_cache[k][0] for k, r in sel); A = sum(act[r].sum() - U[r].sum() for k, r in sel); Gv = sum(G[r].sum() for k, r in sel)
        P(f"  {lab:12s} team-weeks {len(sel):5d} lost {L/len(sel):5.1f}/tw  actual gain {100*A/L:5.1f}%  given {100*Gv/L:5.1f}%  act/shipped {sum(act[r].sum() for k,r in sel)/sum(B1[r].sum() for k,r in sel):.3f}")
    base_nob = ok & (vac == 0)
    P(f"  reference nobody out: act/unboosted {act[base_nob].sum()/U[base_nob].sum():.3f}  act/shipped {act[base_nob].sum()/B1[base_nob].sum():.3f}")
    preds = {"off": B1}
    def topup(c, how, wt_only=False, vmin=0.0):
        out = B1.copy()
        for k, r in tw:
            L, wt = lost_cache[k]
            if wt_only and not wt: continue
            if vac[r[0]] < vmin: continue
            gap = c * L - G[r].sum()
            if gap <= 0: continue
            w_ = B1[r] if how == "proj" else np.maximum(tsh[r], 0.01)
            out[r] = B1[r] + gap * w_ / w_.sum()
        return out
    for c in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0):
        preds[f"c{c}p"] = topup(c, "proj"); preds[f"c{c}t"] = topup(c, "tgt"); preds[f"c{c}pW"] = topup(c, "proj", True)
        preds[f"c{c}S30"] = topup(c, "proj", vmin=0.30); preds[f"c{c}S40"] = topup(c, "proj", vmin=0.40)
    touched = np.zeros(n, dtype=bool)
    for k, r in tw: touched[r] = True
    mse = lambda p, m: float(np.mean((p[m] - act[m]) ** 2))
    names = list(preds)
    def pick(yrs): return min(names, key=lambda kk: mse(preds[kk], ok & np.isin(year, yrs)))
    P(f"\ntouched rows {int(touched.sum())}")
    for label, folds in (("LOYO", [(tuple(y for y in YEARS if y != t), t) for t in YEARS]), ("FORWARD", [(tuple(y for y in YEARS if y < t), t) for t in FWD])):
        wins = 0; a0 = a1 = b0 = b1 = 0.0; picks = []
        for tr, te in folds:
            kk = pick(tr); picks.append(kk); r = touched & (year == te); w_ = ok & (year == te)
            e0, e1 = mse(B1, r), mse(preds[kk], r); wins += int(e1 < e0)
            a0 += e0 * r.sum(); a1 += e1 * r.sum(); b0 += mse(B1, w_) * w_.sum(); b1 += mse(preds[kk], w_) * w_.sum()
        P(f"{label}: touched rows {100*(a1/a0-1):+.2f}% ({wins}/{len(folds)}), board {100*(b1/b0-1):+.3f}% | picks {picks}")
    P("fixed (all seasons, touched rows):")
    for kk in names[1:]:
        per = [mse(preds[kk], touched & (year == y)) < mse(B1, touched & (year == y)) for y in YEARS]
        P(f"  {kk:8s} {100*(mse(preds[kk], touched)/mse(B1, touched)-1):+.2f}%  seasons better {sum(per)}/7  act/pred {act[touched].sum()/preds[kk][touched].sum():.3f}")
    P(f"  off      act/pred {act[touched].sum()/B1[touched].sum():.3f}")
    best = min(names[1:], key=lambda kk: mse(preds[kk], touched)); P(f"best fixed {best}")
    for ps in SK:
        m = touched & (pos == ps)
        if m.sum(): P(f"  {ps} n{int(m.sum())} {100*(mse(preds[best], m)/mse(B1, m)-1):+.2f}%")
    for lab, lo, hi in (("vac <.30", 0, .30), ("vac .30-.40", .30, .40), ("vac .40+", .40, 9)):
        m = touched & (vac >= lo) & (vac < hi)
        if m.sum(): P(f"  {lab} n{int(m.sum())} {100*(mse(preds[best], m)/mse(B1, m)-1):+.2f}%")
    m = touched & (adpx <= 150)
    P(f"  ADP<=150 n{int(m.sum())} {100*(mse(preds[best], m)/mse(B1, m)-1):+.2f}%")
    LOG.close()


if __name__ == "__main__":
    main()
