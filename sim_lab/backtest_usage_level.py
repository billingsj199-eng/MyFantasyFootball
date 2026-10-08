#!/usr/bin/env python3
"""
USAGE LEVEL INSTEAD OF SNAPS (Jack 2026-10-08: "RB snaps may be misleading when it's really about the usage - same with TEs:
some TEs don't block, they come off on obvious run plays but run almost all the routes; backups come in just to block").
Honest replica, next game. The shadow's in-season role reads are snap-based: TE / WR snap-share LEVEL (last game vs what players
at the same projection usually play) and the RB snap TREND (engine snapmult). Replacements built the same way from USAGE:
  TE  route LEVEL: last-3 route rate (PFF, routes / team dropbacks) vs the projection-bin reference; e grid; vs / with snap level
  RB  touch LEVEL: last-3 share of team carries + targets vs the projection-bin reference; e grid; vs / with the snap trend
Graded on the position's rows, LOYO + forward (bar 5/7 + 3/4, LOYO < -0.3%), whole-board guard, rank line, and Jack's
bands (top 30 / 31-100 / 101-150). Log usage_level.log.
"""
import os, sys, warnings
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "usage_level.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, g, adp, name, pid = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], A["pid"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2; wt3 = np.maximum(0.05, lv) ** 3
    TODAY, LV = BR.live_today(X); SHADOW, SH0 = BR.shadow_current(X)
    base = top150 & ~final & ~LV["inh"] & (SHADOW >= 3)
    from backtest_inseason_usage import route_features
    rt_std, rt_l3 = route_features(year, pid, wk)
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    cv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    car3, tgt3, car_s, tgt_s, smx = cv("car_sh_l3"), cv("tgt_sh_l3"), cv("car_sh"), cv("tgt_sh"), cv("snapmult")
    smx = np.where(np.isnan(smx), 1.0, smx); touch3 = car3 + tgt3; touch_s = car_s + tgt_s
    def level_dev(v, ps):
        """deviation of v from the reference of players at the same projection (8 bins of the harness shadow), like the snap level"""
        dev = np.full(n, np.nan); m = (pos == ps) & (g >= 1) & ~np.isnan(v) & ~final & (SH0 >= 3)
        q = np.quantile(SH0[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, SH0, side="right") - 1, 0, 7)
        for k in range(8):
            mk = m & (b_ == k)
            if mk.sum() >= 30: dev[mk] = v[mk] - np.nanmean(v[mk])
        return dev
    wm = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    w3 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt3[m])) if m.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    def test(title, preds, m):
        names = list(preds); b0 = preds["off"]; pick = lambda yrs: min(names, key=lambda kk: wm(preds[kk], m & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = b0.copy()
            for tr_, te in folds:
                kk = pick(tr_); picks.append(kk); mm = year == te; pr[mm] = preds[kk][mm]; wins += wm(preds[kk], m & mm) < wm(b0, m & mm) - 1e-12
            tem = np.isin(year, [te for _, te in folds]); return 100 * (wm(pr, m & tem) / wm(b0, m & tem) - 1), 100 * (wm(pr, base & tem) / wm(b0, base & tem) - 1), wins, picks
        lo = run(LOSO); fw = run(FORW); best = pick(YEARS); pb = preds[best]
        fixed = "  ".join(f"{kk}: {100*(wm(preds[kk], m)/wm(b0, m)-1):+.2f}% ({sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and wm(preds[kk], m & (year == y)) < wm(b0, m & (year == y)) - 1e-12)}/7)" for kk in names[1:])
        okk = best != "off" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
        P(f"\n  {title} (rows {int(m.sum()):,}, act/shadow {act[m].sum()/b0[m].sum():.3f})"); P(f"    fixed: {fixed}")
        P("    " + RG.rank_line(preds, m, act, year, wk, pos))
        P(f"    best {best} by band: top-30 {100*(w3(pb, m & (adpx <= 30))/w3(b0, m & (adpx <= 30))-1):+.2f}% | 31-100 {100*(w3(pb, m & (adpx > 30) & (adpx <= 100))/w3(b0, m & (adpx > 30) & (adpx <= 100))-1):+.2f}% | 101-150 {100*(wm(pb, m & (adpx > 100))/wm(b0, m & (adpx > 100))-1):+.2f}%")
        P(f"    LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | picks {lo[3]}"); P(f"    FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}"); P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
        return best if okk else None
    P(f"=== USAGE LEVEL vs SNAPS, next game ===")
    # ---- TE: route level
    TE = base & (pos == "TE"); dr = level_dev(rt_l3, "TE"); ds = level_dev(X["snap_l1"], "TE")
    P(f"  TE rows {int(TE.sum()):,}: route rate (l3) available {int((TE & ~np.isnan(rt_l3)).sum()):,}; corr(route dev, snap dev) {np.corrcoef(dr[TE & ~np.isnan(dr) & ~np.isnan(ds)], ds[TE & ~np.isnan(dr) & ~np.isnan(ds)])[0,1]:.3f}")
    # the wired TE snap level inside SHADOW is sqrt(clip(1 + .3 dev/100)); strip it to build replacements
    snapTE = np.where(pos == "TE", np.sqrt(np.clip(1 + 0.3 * np.nan_to_num(level_dev(X["snap_l1"], "TE"), nan=0.0) / 100.0, 0.7, 1.4)), 1.0)
    NOSNAP = SHADOW / snapTE
    m = TE & ~np.isnan(dr); preds = {"off": SHADOW}
    for e in (0.15, 0.3, 0.5):
        p = NOSNAP.copy(); p[m] = NOSNAP[m] * np.clip(1 + e * dr[m], 0.7, 1.4); preds[f"route level e {e} (snap level off)"] = p
    for e in (0.15, 0.3):
        p = SHADOW.copy(); p[m] = SHADOW[m] * np.clip(1 + e * dr[m], 0.7, 1.4); preds[f"route level e {e} + snap level (wired)"] = p
    preds["snap level off"] = NOSNAP
    test("TE: route-rate LEVEL in place of / on top of the snap level", preds, m)
    # ---- RB: touch level vs snap trend
    RB = base & (pos == "RB"); dt = level_dev(touch3, "RB"); dts = level_dev(touch_s, "RB")
    P(f"\n  RB rows {int(RB.sum()):,}: touch share (l3) available {int((RB & ~np.isnan(touch3)).sum()):,}; corr(touch-l3 dev, snap trend) {np.corrcoef(dt[RB & ~np.isnan(dt)], smx[RB & ~np.isnan(dt)])[0,1]:.3f}")
    NOTREND = np.where(pos == "RB", SHADOW / np.where(smx > 0, smx, 1.0), SHADOW)
    m = RB & ~np.isnan(dt); preds = {"off": SHADOW}
    for e in (0.3, 0.6, 1.0):
        p = NOTREND.copy(); p[m] = NOTREND[m] * np.clip(1 + e * dt[m], 0.6, 1.5); preds[f"touch level e {e} (snap trend off)"] = p
    for e in (0.3, 0.6):
        p = SHADOW.copy(); p[m] = SHADOW[m] * np.clip(1 + e * dt[m], 0.6, 1.5); preds[f"touch level e {e} + snap trend (wired)"] = p
    # touch TREND: last-3 share vs season share
    tr_ = np.where(~np.isnan(touch3) & ~np.isnan(touch_s) & (touch_s > 0.05), touch3 / touch_s, np.nan); m2 = RB & ~np.isnan(tr_)
    for e in (0.5, 1.0):
        p = NOTREND.copy(); p[m2] = NOTREND[m2] * np.clip(1 + e * (tr_[m2] - 1), 0.6, 1.5); preds[f"touch trend e {e} (snap trend off)"] = p
    preds["snap trend off"] = NOTREND
    test("RB: touch-share LEVEL / TREND in place of / on top of the snap trend", preds, RB & (~np.isnan(dt) | ~np.isnan(tr_)))
    P("\nLimitations: route rate = PFF weekly receiving summaries (routes / dropbacks), last 3 games; touch share from ctx (season to date and last 3); the snap level reference bins are rebuilt here; honest replica, next game only.")
    LOG.close()


if __name__ == "__main__":
    main()
