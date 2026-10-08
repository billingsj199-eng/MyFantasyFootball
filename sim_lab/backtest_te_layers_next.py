#!/usr/bin/env python3
"""
TIGHT-END LAYERS, NEXT GAME (Jack 2026-10-08 "run all three and wire what passes"; the season half = backtest_shadow_ros.py
section 14). From research_te_bias.py the shadow under-projects (1) tight ends with a role and no touchdowns yet, (2) full-snap
tight ends, (3) tight ends on run-heavy offenses, (4) tight ends on high team totals. Honest replica, TE rows:
  A  TD floor: x (1 + e x max(0, 1.8 - TD points per game so far)), 2+ games, role gate (target share >= .15 or snap >= 70)
  B  snap level / snap trend: dock exponent x lift exponent (wired .5 / .5 for the current week)
  C  run-heavy tilt: x (1 + e x max(0, -z(team pass rate over expected)))        D  implied-total tilt: x (1 + e x z(implied))
LOYO + forward (bar 5/7 + 3/4, LOYO < -0.3%), whole-board guard, rank line. Log te_layers_next.log.
"""
import os, sys, warnings
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; cal = SN.NW.cal; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "te_layers_next.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, g, adp, name, pid = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], A["pid"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    base = top150 & ~final & ~LV["inh"] & (SHADOW >= 3); TE = base & (pos == "TE")
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    cv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    tsh, snap, proe, imp = cv("tgt_sh"), cv("snap_std"), cv("proe_std"), cv("implied")
    def zweek(v, grp):
        z = np.full(n, np.nan)
        for y in YEARS:
            for w in range(1, 19):
                m = base & (year == y) & (wk == w) & ~np.isnan(v) & grp
                if m.sum() >= 12 and np.nanstd(v[m]) > 0: z[m] = np.clip((v[m] - np.nanmean(v[m])) / np.nanstd(v[m]), -2.5, 2.5)
        return z
    zp = zweek(proe, pos == "TE"); zi = zweek(imp, pos == "TE")
    tdp = np.full(n, np.nan); logs = {}
    for i in np.where(TE)[0]:
        Y = int(year[i]); k = (name[i], Y)
        if k not in logs:
            rec = cal.weekly_rec(name[i], "TE"); logs[k] = {int(w["wk"]): 6 * float(w.get("rctd") or 0) + 6 * float(w.get("rtd") or 0) for w in (rec or {}).get("seasons", {}).get(str(Y), []) if cal.played(w) and isinstance(w.get("fpts"), (int, float))}
        past = [v for w, v in logs[k].items() if w < wk[i]]
        if past: tdp[i] = float(np.mean(past))
    wm = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    def test(title, preds, m):
        names = list(preds); b0 = preds["off"]; pick = lambda yrs: min(names, key=lambda kk: wm(preds[kk], m & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = b0.copy()
            for tr_, te in folds:
                kk = pick(tr_); picks.append(kk); mm = year == te; pr[mm] = preds[kk][mm]; wins += wm(preds[kk], m & mm) < wm(b0, m & mm) - 1e-12
            tem = np.isin(year, [te for _, te in folds]); return 100 * (wm(pr, m & tem) / wm(b0, m & tem) - 1), 100 * (wm(pr, base & tem) / wm(b0, base & tem) - 1), wins, picks
        lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
        fixed = "  ".join(f"{kk}: {100*(wm(preds[kk], m)/wm(b0, m)-1):+.2f}% ({sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and wm(preds[kk], m & (year == y)) < wm(b0, m & (year == y)) - 1e-12)}/7)" for kk in names[1:])
        okk = best != "off" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
        P(f"\n  {title} (rows {int(m.sum()):,}, act/shadow {act[m].sum()/b0[m].sum():.3f})"); P(f"    fixed: {fixed}")
        P("    " + RG.rank_line(preds, m, act, year, wk, pos))
        P(f"    LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | picks {lo[3]}"); P(f"    FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}"); P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
        return best if okk else None
    P(f"=== TE LAYERS, next game: {int(TE.sum()):,} TE rows; act/shadow {act[TE].sum()/SHADOW[TE].sum():.3f} ===")
    role = TE & ((tsh >= 0.15) | (snap >= 70)); gap = np.clip(1.8 - np.nan_to_num(tdp, nan=1.8), 0, 1.8)
    m = role & ~np.isnan(tdp) & (g >= 2); preds = {"off": SHADOW}
    for e in (0.02, 0.04, 0.06, 0.08): p = SHADOW.copy(); p[m] = SHADOW[m] * (1 + e * gap[m]); preds[f"e {e}"] = p
    test("A  TD floor for tight ends with a role and few TDs so far", preds, m)
    m = TE & ~np.isnan(tdp) & (g >= 2); preds = {"off": SHADOW}
    for e in (0.02, 0.04, 0.06): p = SHADOW.copy(); p[m] = SHADOW[m] * (1 + e * gap[m]); preds[f"e {e}"] = p
    test("A' TD floor, no role gate", preds, m)
    preds = {"off": SHADOW}
    for kd, kl in ((0.5, 1.0), (0.5, 1.5), (1.0, 1.0), (1.0, 1.5), (0.25, 1.0), (0.5, 2.0)): preds[f"dock ^{kd} / lift ^{kl}"] = BR.shadow_current(X, te_dock_k=kd, te_lift_k=kl)[0]
    test("B  TE snap level / trend: dock and lift exponents (wired .5 / .5)", preds, TE)
    m = TE & ~np.isnan(zp); preds = {"off": SHADOW}
    for e in (0.03, 0.06, 0.09, 0.12): p = SHADOW.copy(); p[m] = SHADOW[m] * (1 + e * np.clip(-zp[m], 0, 2.5)); preds[f"e {e}"] = p
    test("C  run-heavy offense tilt (run-heavy side only)", preds, m)
    preds = {"off": SHADOW}
    for e in (0.02, 0.04, 0.06): p = SHADOW.copy(); p[m] = SHADOW[m] * np.clip(1 - e * zp[m], 0.8, 1.2); preds[f"e {e}"] = p
    test("C' pass-rate tilt symmetric", preds, m)
    m = TE & ~np.isnan(zi); preds = {"off": SHADOW}
    for e in (0.02, 0.04, 0.06): p = SHADOW.copy(); p[m] = SHADOW[m] * np.clip(1 + e * zi[m], 0.8, 1.2); preds[f"e {e}"] = p
    test("D  implied-total tilt (on top of the Vegas layer)", preds, m)
    P("\nLimitations: honest replica (TD luck, TE exponents .5/.5 current week); layers are multiplicative on the finished shadow; proe / implied z within week across TE rows.")
    LOG.close()


if __name__ == "__main__":
    main()
