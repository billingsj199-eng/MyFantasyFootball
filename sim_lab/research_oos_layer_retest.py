#!/usr/bin/env python3
"""
RE-TEST OF THE WIRED LAYERS THAT FAILED THE 2012-18 OUT-OF-SAMPLE CHECK, ON THE FULL 2013-25 HARNESS, WITH ERA DRIFT
(2026-10-20, Jack approved: "re-test ... handle era drift explicitly"; "the game has changed ... if the earlier years are a problem lmk").
RESEARCH ONLY - nothing here touches engine.js / the export / the extensions.

Harness = bt_ext_oos.py's full_next() / full_ros() (the wired Clay-free shadow, team fix on) re-built here with a STRENGTH per piece
(s = 1 wired, 0 off, 0.5 / 1.5 resize; multiplicative constants scale as m**s, exponents / usage weights linearly). Data =
_bt_ext/X_cache_ext2012_2025_tf.pkl (SN.setup cached by _tmp/cache_setup.py). 2012 = warm-up (no 2011 pbp): graded 2013-25.

For every piece and horizon (NEXT game / ROS = rest of season after 3-10 games, 4+ left), final week out:
  (a) layer effect by season 2013-25 (wired vs off, % MSE all rows; negative = the layer helps), OLS trend slope per season
      with a 95% CI (t, 11 df), and the 2013-18 vs 2019-25 era means
  (b) three reads side by side: ALL 2013-25 (pooled, seasons the layer helps x/13, forward 2016-25); 2016-25 only;
      RECENCY (seasons weighted 0.85**(2025-y))
  (c) resize: s picked from {0, .5, 1, 1.5} leave-one-season-out / forward on each read (weighted the same way); graded
      vs wired: pooled MSE on touched rows (bar < -0.3%), LOYO 70%+, forward 60%+, top-150 wtd <= +0.1%, rank not worse
Optional joint run: JOINT_NEXT="piece|piece=0.5" JOINT_ROS="piece|piece" -> changed together (no "=" = pulled; + each alone) in section D.
Other env: ONLY="piece|piece" (just those), SKIP_MAIN=1 (joint only), SGRID="0,0.25,0.5,1" (resize grid, keep 0 and 1), OUT_TAG.
Engine note: the QB game-total tilt skips top-30 QBs as the engine does (SIM_NC_TOTAL_ELITE); bt_ext_oos.py tilted every QB.
Runs 2026-10-20: oos_layer_retest (main), _wrgrid (WR usage grid), _joint (every OOS-failed piece pulled), _wrhalf (WR usage x0.5).
Live scratch (nothing written to the site): _tmp/oos_retest_live_run.js + _tmp/oos_retest_live_diff.py.
Log: _bt_ext/oos_layer_retest_ext2012_2025_tf.log
  SIM_BT_YEARS=2012-2025 python research_oos_layer_retest.py
"""
import os, sys, pickle
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata, t as tdist
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_ext as BX
import backtest_nochart_vets as NC
POS4 = ("QB", "RB", "WR", "TE")
GY = list(range(2013, 2026)); NY = len(GY)
REC = float(os.environ.get("RECENCY", "0.85"))
READS = {   # name: (season weights, forward folds)
    "ALL 13-25": ({y: 1.0 for y in GY}, [y for y in GY if y >= 2016]),
    "16-25": ({y: (1.0 if y >= 2016 else 0.0) for y in GY}, [y for y in GY if y >= 2019]),
    "RECENCY": ({y: REC ** (2025 - y) for y in GY}, [y for y in GY if y >= 2016]),
}
SGRID = tuple(float(x) for x in os.environ.get("SGRID", "0,0.5,1,1.5").split(","))   # must contain 0 and 1


def main():
    tag = os.environ.get("OUT_TAG", "")
    log = open(BX.ext_path(f"oos_layer_retest{tag}.log"), "w", encoding="utf-8")
    def P(s=""): print(s, flush=True); log.write(s + "\n"); log.flush()
    X = pickle.load(open(BX.ext_path("X_cache.pkl"), "rb"))
    n = X["n"]; F = X["F"]; A = X["A"]
    act, year, wk, pos, g, name, adp, layers = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["name"], X["adp"], X["layers"]
    year = year.astype(int)
    P(f"=== OOS layer re-test with era drift: {BX.describe()} | {n:,} player-weeks | graded 2013-25 | recency {REC} ===")

    # ---------------- prior (bt_ext_oos.prior_of with strengths) ----------------
    fb_pos, hist, adp_curve, mkt_ok, fb, wv, vet, yr2lo, strb = F["fb_pos"], F["hist_adj"], F["adp_curve"], F["mkt_ok"], F["fb"], F["wv"], F["vet"], F["yr2lo"], F["strb"]
    mixed = (pos != "QB") & (np.abs(X["prior"] - F["prior"]) > 1e-12)
    ridge_half = np.where(mixed, X["prior"] - 0.5 * F["prior"], np.nan)
    def prior_of(S):
        pr = np.where(mkt_ok, (1 - wv) * hist + wv * adp_curve, hist)
        miss = np.isnan(pr); pr = np.where(miss, fb, pr)
        s = S.get("depth-string docks (vets)", 1.0)
        for ps, d in NC.VETDOCK.items():
            for sb, mm_ in d.items():
                mk = vet & (pos == ps) & (strb == sb); pr = np.where(mk, pr * mm_ ** s, pr)
        pr = np.where(yr2lo & vet, pr * 1.2, pr)
        fp = fb_pos + 0.8 * (pr - fb_pos)
        return np.where(mixed, ridge_half + 0.5 * fp, fp)
    P(f"  prior rebuild check: max |rebuilt - harness| = {np.nanmax(np.abs(prior_of({}) - X['prior'])):.2e}")

    C = pd.read_parquet(BX.ext_path("ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = A["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)

    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
    def wt_of():
        lv = F["adp_curve"].copy()
        for ps in POS4:
            m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
        return np.maximum(0.05, lv) ** 2
    wt = wt_of()

    # ================= NEXT GAME (bt_ext_oos.full_next with strengths) =================
    # SH: the shadow as SN.shadow (row filter SH >= 3, as the OOS script)
    lamb = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    ev0 = lamb * X["xf"] + (1 - lamb) * X["ppg_v"]
    SH = (X["Pw"] * X["prior"] + g * ev0) / np.maximum(X["Pw"] + g, 1e-9) * layers
    for gi, m_ in enumerate([0.7, 0.8], start=1): SH = np.where(F["buried_rk"] & (wk == gi), SH * m_, SH)
    SH = np.where(F["on"], SH * np.power(F["pm"], 0.75), SH); SH = np.where(pos == "QB", SH * np.exp(0.03 * X["z"]), SH)
    SH = np.where((pos == "WR") & X["qbo"], SH * np.where(adp <= 60, 0.85, 0.95), SH)
    base = top150 & ~final & (year >= 2013); allr = ~final & (SH >= 3) & (year >= 2013)
    l1n = X["snap_l1"]; devn = np.zeros(n)
    allr12 = ~final & (SH >= 3)
    for ps in ("WR", "TE"):
        m = (pos == ps) & (g >= 1) & ~np.isnan(l1n) & allr12
        q = np.quantile(SH[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, SH, side="right") - 1, 0, 7)
        for k in range(8):
            mk = m & (b_ == k)
            if mk.sum() >= 30: devn[mk] = l1n[mk] - np.nanmean(l1n[mk])
    low = np.maximum(0, 19 - np.nan_to_num(X["implied"], nan=19)) / 19
    smx = colv("snapmult"); smx = np.where(np.isnan(smx) | (pos == "QB"), 1.0, smx)
    def full_next(S=None):
        S = S or {}; s = lambda k: S.get(k, 1.0)
        lam = lamb.copy()
        lam = np.where(pos == "WR", np.clip(lam * s("usage evidence, WR"), 0, 1), lam)
        lam = np.where(pos == "RB", np.clip(lam * s("usage evidence, RB"), 0, 1), lam)
        ev = lam * X["xf"] + (1 - lam) * X["ppg_v"]
        pr_ = prior_of(S)
        Pw = F["Pvec"] * np.where((pos == "WR") & (g == 1), 5.0 ** s("WR one-game prior x5"), 1.0)
        out = (Pw * pr_ + g * ev) / np.maximum(Pw + g, 1e-9) * layers
        for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_ ** s("rookie ramp (weeks 1-2)"), out)
        out = np.where(F["on"], out * np.power(F["pm"], 0.75 * s("vacated-role pool")), out)
        # engine: no shootout tilt on top-30 QBs (SIM_NC_TOTAL_ELITE, tier test T3); the OOS script tilted every QB ("_tilt_all")
        tq = (pos == "QB") & ((adp > 30) | np.isnan(adp) | bool(S.get("_tilt_all", 0)))
        out = np.where(tq, out * np.exp(0.03 * s("QB game-total tilt") * X["z"]), out)
        out = np.where((pos == "WR") & X["qbo"], out * np.where(adp <= 60, 0.85, 0.95), out)
        out = np.where(np.isin(pos, ["RB", "TE"]), out * smx, out)
        out = np.where(pos == "WR", out * np.clip(1 + 0.3 * devn / 100.0, 0.7, 1.4), out)
        out = np.where(pos == "TE", out * np.clip(1 + 0.3 * devn / 100.0, 0.7, 1.4), out)
        out = np.where((pos == "QB") & X["mover"], out * 0.90 ** s("QB changed teams x.90"), out)
        out = np.where(pos == "QB", out * (1 - 0.75 * low), out)
        out = np.where((pos == "RB") & (g >= 2) & (g <= 5) & (X["car_sh"] < 0.30), out * 0.90, out)
        return out

    # ================= REST OF SEASON (bt_ext_oos.full_ros with strengths) =================
    import backtest_shadow_ros as SR
    MINF = 4; seq = defaultdict(list)
    for i in range(n):
        if wk[i] != finw[i]: seq[(name[i], pos[i], int(year[i]))].append(i)
    T = np.full(n, np.nan); ctx = np.full(n, np.nan)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(layers[ix], 0.5, 1.8)
        for a, i in enumerate(ix):
            if len(ix) - a >= MINF: T[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    R0 = SR.rate(X); ok12 = ~np.isnan(T) & (g >= 3) & (g <= 10) & (R0 * ctx >= 3); ok = ok12 & (year >= 2013)
    SHr = R0 * ctx
    def z_of(v, m):
        out = np.zeros(n); mm = m & ok12 & ~np.isnan(v); ap = m & ~np.isnan(v)
        if mm.sum() > 50: out[ap] = np.clip((v[ap] - v[mm].mean()) / v[mm].std(), -2, 2)
        return out
    rk, y2 = colv("rookie") == 1, colv("yr2") == 1
    sm = colv("snapmult"); sm = np.where(np.isnan(sm), 1.0, sm)
    l1 = colv("snap_l1"); dev = np.zeros(n)
    for ps in ("WR", "TE"):
        m = ok12 & (pos == ps) & ~np.isnan(l1); q = np.quantile(SHr[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, SHr, side="right") - 1, 0, 7)
        for k in range(8):
            mk = m & (b_ == k)
            if mk.sum() >= 30: dev[mk] = l1[mk] - l1[mk].mean()
    zp = z_of(colv("proe_std"), pos == "TE"); zpl10 = z_of(colv("plays_pg_std"), pos == "RB")
    b61 = (adp > 60) & (adp <= 100); b101 = (adp > 100) & (adp <= 150)
    t36 = (pos == "TE") & (adp > 30) & (adp <= 60)
    bl = SR.base_lam(pos, g)
    def full_ros(S=None):
        S = S or {}; s = lambda k: S.get(k, 1.0)
        lam_ = np.clip(bl * s("usage evidence (all positions)"), 0, 1)
        lam_ = np.where(pos == "RB", np.clip(lam_ * s("usage evidence, RB (ROS)"), 0, 1), lam_)
        lam_ = np.where(pos == "WR", np.clip(lam_ * s("usage evidence, WR (ROS)"), 0, 1), lam_)
        lam_ = np.where((pos == "WR") & b101, np.minimum(lam_, 0.25), lam_)
        ev = lam_ * X["xf"] + (1 - lam_) * X["ppg_v"]
        pr_ = prior_of(S)
        pm_ = np.ones(n)
        pm_ = np.where((pos == "RB") & b61, 2.5 ** s("RB 61-100 prior weight x2.5"), pm_)
        pm_ = np.where((pos == "WR") & b61, 0.6 ** s("WR 61-100 prior weight x0.6"), pm_)
        pm_ = np.where((pos == "QB") & y2, 0.75 ** s("second-year QB prior weight x0.75"), pm_)
        pm_ = np.where((pos == "WR") & b101 & (ev < pr_), pm_ * 0.4, pm_)
        sr = s("rookie prior weight RB 1.6 / TE 2.5 (v2.33)")
        pm_ = np.where(rk & (pos == "RB"), pm_ * 1.6 ** sr, np.where(rk & (pos == "TE"), pm_ * 2.5 ** sr, pm_))
        Pw = X["Pw"] * pm_
        out = (Pw * pr_ + g * ev) / np.maximum(Pw + g, 1e-9) * ctx
        out = np.where(pos == "RB", out * sm, out)
        out = np.where((pos == "QB") & X["mover"], out * 0.84 ** s("QB changed teams x.84"), out)
        out = np.where((pos == "TE") & ~np.isnan(l1), out * np.clip(1 + 0.3 * s("TE snap-share level e .3") * dev / 100.0, 0.7, 1.4), out)
        out = np.where(pos == "TE", out * (1 - 0.04 * zp), out)
        out = np.where(t36, out * 1.10 ** s("TE 31-60 x1.10"), out)
        out = np.where(pos == "RB", out * np.clip(1 - 0.04 * zpl10, 0.8, 1.25), out)
        out = np.where((pos == "RB") & (strb >= 2) & (adp <= 150), out * 1.04 ** s("RB backup (top 150) x1.04"), out)
        return out

    # ---------------- per-season sufficient statistics ----------------
    YIX = {y: k for k, y in enumerate(GY)}; RPOS = []   # rank graded on the groups of the positions the piece touches
    def prep(rows, brows, tgt):
        yi_r = np.array([YIX.get(int(y), -1) for y in year[rows]])
        gr = defaultdict(list)
        for i in np.where(brows)[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        groups = [(YIX[k[0]], np.array(v), rankdata(tgt[np.array(v)]), POS4.index(k[2])) for k, v in gr.items() if len(v) >= 8]
        return dict(rows=rows, brows=brows, tgt=tgt, yi_r=yi_r, yi_b=np.array([YIX[int(y)] for y in year[brows]]), groups=groups)
    HN = prep(allr, base, act); HR = prep(ok, ok & top150, T)
    def stats(Q, H, touch=None):
        r, b, t_ = H["rows"], H["brows"], H["tgt"]
        e = (Q[r] - t_[r]); yi = H["yi_r"]
        out = dict(se=np.bincount(yi, e ** 2, NY), ae=np.bincount(yi, np.abs(e), NY), cn=np.bincount(yi, minlength=NY).astype(float),
                   wse=np.bincount(H["yi_b"], wt[b] * (Q[b] - t_[b]) ** 2, NY))
        rs4 = np.zeros((NY, 4)); rc4 = np.zeros((NY, 4))
        for y_, ix, tr, pj in H["groups"]:
            rs4[y_, pj] += np.corrcoef(tr, rankdata(Q[ix]))[0, 1]; rc4[y_, pj] += 1
        out["rs4"], out["rc4"] = rs4, rc4
        pm = RPOS[0] if RPOS else [True] * 4
        out["rs"], out["rc"] = rs4[:, pm].sum(1), rc4[:, pm].sum(1)
        if touch is not None:
            tm = touch[r]
            out["tse"] = np.bincount(yi[tm], e[tm] ** 2, NY); out["tcn"] = np.bincount(yi[tm], minlength=NY).astype(float)
        return out
    def comp(a, b, w):   # a vs b, season weights w (array NY): % err, % wtd, % MAE, rank diff, touched %
        w = np.asarray(w)
        pct = lambda k: 100 * (np.sum(w * a[k]) / max(1e-12, np.sum(w * b[k])) - 1)
        rk_ = np.sum(w * a["rs"]) / np.sum(w * a["rc"]) - np.sum(w * b["rs"]) / np.sum(w * b["rc"])
        tt = pct("tse") if "tse" in a and np.sum(w * b.get("tse", 0)) > 0 else np.nan
        return dict(err=pct("se"), wtd=pct("wse"), mae=pct("ae"), rk=rk_, terr=tt)
    def season_eff(a, b, k="se"):
        return np.array([100 * (a[k][j] / b[k][j] - 1) if b[k][j] > 0 else np.nan for j in range(NY)])
    def slope_ci(v):
        x = np.array(GY, float); m = ~np.isnan(v)
        x, v = x[m], v[m]
        if len(v) < 4: return (np.nan, np.nan, np.nan)
        xc = x - x.mean(); b1 = np.sum(xc * (v - v.mean())) / np.sum(xc ** 2)
        res = v - v.mean() - b1 * xc; se = np.sqrt(np.sum(res ** 2) / (len(v) - 2) / np.sum(xc ** 2)); h = tdist.ppf(.975, len(v) - 2) * se
        return (b1, b1 - h, b1 + h)
    def read_tag(c, share):
        sc = int(c["err"] < 0) + int(c["wtd"] < 0) + int(c["rk"] > 0) + int(share >= 0.6)
        if abs(c["err"]) < 0.01 and abs(c["wtd"]) < 0.01: return "wash"
        return "HELPS" if sc >= 3 else ("HURTS" if sc <= 1 else "wash")

    RESULTS = {}
    def run_piece(hz, k, fullf, H, resize=True):
        Wd = fullf(); RPOS.clear()
        preds = {s_: fullf({k: s_}) for s_ in SGRID}
        touched = H["rows"] & (np.abs(preds[0.0] - Wd) > 1e-9)
        tp = set(pos[touched]); RPOS.append([p_ in tp for p_ in POS4])
        Wst = stats(Wd, H, touched)
        st = {s_: stats(preds[s_], H, touched) for s_ in SGRID}
        off = st[0.0]
        # (a) layer effect by season (wired vs off): negative = the layer helps
        se_ = season_eff(Wst, off); sw_ = season_eff(Wst, off, "wse")
        sl = slope_ci(se_); slw = slope_ci(sw_)
        e1 = np.nanmean(se_[:6]); e2 = np.nanmean(se_[6:])
        P(f"\n  [{hz}] {k}   rows touched {int(touched.sum()):,} of {int(H['rows'].sum()):,}")
        P("    layer effect by season, % MSE all rows (neg = layer helps): " + " ".join(f"{y % 100:02d}:{v:+.2f}" for y, v in zip(GY, se_)))
        P("    layer effect by season, top-150 wtd %:                     " + " ".join(f"{y % 100:02d}:{v:+.2f}" for y, v in zip(GY, sw_)))
        srk = np.array([Wst["rs"][j] / Wst["rc"][j] - off["rs"][j] / off["rc"][j] if off["rc"][j] else np.nan for j in range(NY)])
        slr = slope_ci(srk * 100)
        P(f"    layer effect by season, rank order ({'/'.join(p_ for p_ in POS4 if p_ in tp)} groups, + = helps): " + " ".join(f"{y % 100:02d}:{v:+.4f}" for y, v in zip(GY, srk)) +
          f" | slope {slr[0] / 100:+.5f} [{slr[1] / 100:+.5f}, {slr[2] / 100:+.5f}] | 13-18 {np.nanmean(srk[:6]):+.4f} 19-25 {np.nanmean(srk[6:]):+.4f}")
        P(f"    trend slope (all rows) {sl[0]:+.3f}%/season [95% CI {sl[1]:+.3f}, {sl[2]:+.3f}] | top-150 wtd {slw[0]:+.3f} [{slw[1]:+.3f}, {slw[2]:+.3f}] | era mean 13-18 {e1:+.3f}%  19-25 {e2:+.3f}%  (neg slope = helps more lately)")
        rows = {}
        for rn, (wd, fw) in READS.items():
            w = np.array([wd[y] for y in GY]); c = comp(Wst, off, w)
            hy = [y for y in GY if wd[y] > 0]
            helped = [y for y in hy if Wst["se"][YIX[y]] < off["se"][YIX[y]]]
            share = sum(wd[y] for y in helped) / sum(wd[y] for y in hy)
            fh = [y for y in fw if Wst["se"][YIX[y]] < off["se"][YIX[y]]]
            tag_ = read_tag(c, share)
            line = f"    {rn:9s} LAYER: err {c['err']:+6.2f}% (touched {c['terr']:+6.2f}%) wtd {c['wtd']:+6.2f}% MAE {c['mae']:+6.2f}% rank {c['rk']:+.4f} | helps {len(helped)}/{len(hy)} seasons (wtd share {share:.2f}), fwd {len(fh)}/{len(fw)} -> {tag_}"
            rz = None
            if resize:
                # resize: pick s on training seasons (weighted), graded vs wired on held-out
                def pick(train):
                    return min(SGRID, key=lambda s_: (sum(wd[y] * st[s_]["se"][YIX[y]] for y in train), abs(s_ - 1)))
                lo = {ty: pick([y for y in hy if y != ty]) for ty in hy}
                fo = {ty: pick([y for y in hy if y < ty]) for ty in fw}
                def assemble(choice):
                    out = {kk: np.zeros_like(np.asarray(Wst[kk], float)) for kk in Wst}
                    for ty, s_ in choice.items():
                        j = YIX[ty]
                        for kk in Wst: out[kk][j] = st[s_][kk][j]
                    return out
                L = assemble(lo); Fw = assemble(fo)
                wl = np.array([wd[y] if y in lo else 0 for y in GY]); wf = np.array([wd[y] if y in fo else 0 for y in GY])
                cl = comp(L, Wst, wl); cf = comp(Fw, Wst, wf)
                s7 = sum(1 for y in lo if L["se"][YIX[y]] < Wst["se"][YIX[y]] - 1e-9); s4 = sum(1 for y in fo if Fw["se"][YIX[y]] < Wst["se"][YIX[y]] - 1e-9)
                best_all = pick(hy)
                ca = comp(st[best_all], Wst, np.array([wd[y] for y in GY])) if best_all != 1.0 else None
                passes = bool(best_all != 1.0 and cl["terr"] < -0.3 and s7 >= np.ceil(0.7 * len(hy)) and cf["err"] < 0 and s4 >= np.ceil(0.6 * len(fw)) and cl["wtd"] <= 0.1 and cl["rk"] >= -0.0005)
                picks = defaultdict(int)
                for v in lo.values(): picks[v] += 1
                line += (f"\n              RESIZE: best s on all {best_all:g}" + (f" (in-sample err {ca['err']:+.2f}% touched {ca['terr']:+.2f}% wtd {ca['wtd']:+.2f}% rank {ca['rk']:+.4f})" if ca else "") +
                         f" | LOYO picks {dict(sorted(picks.items()))} err {cl['err']:+.2f}% touched {cl['terr']:+.2f}% wtd {cl['wtd']:+.2f}% rank {cl['rk']:+.4f} better {s7}/{len(lo)}"
                         f" | FWD err {cf['err']:+.2f}% better {s4}/{len(fo)}" + ("  ** RESIZE PASSES" if passes else ""))
                rz = dict(best=best_all, loyo=cl, fwd=cf, s7=s7, s4=s4, passes=passes)
            P(line)
            rows[rn] = dict(c=c, share=share, helped=len(helped), ny=len(hy), fh=len(fh), nf=len(fw), tag=tag_, rz=rz)
        # 0.5x / 1.5x in-sample vs wired, all 13-25
        P("    fixed resizes vs wired (ALL 13-25 / 16-25 / RECENCY err%): " + " | ".join(
            f"x{s_:g}: " + " / ".join(f"{comp(st[s_], Wst, np.array([READS[r][0][y] for y in GY]))['err']:+.2f}" for r in READS) for s_ in SGRID if s_ not in (0.0, 1.0)))
        RESULTS[(hz, k)] = dict(reads=rows, slope=sl, slope_w=slw, slope_rk=slr, season_rk=srk, e1=e1, e2=e2, season=se_, touched=int(touched.sum()))

    RPOS.clear(); WN = full_next(); WR_ = full_ros()
    for lab, H, Q in (("NEXT", HN, WN), ("ROS", HR, WR_)):
        s0 = stats(Q, H); w = np.ones(NY)
        P(f"  {lab} wired model 2013-25: rows {int(H['rows'].sum()):,} MSE {s0['se'].sum() / s0['cn'].sum():.3f} top-150 wtd {s0['wse'].sum():.0f} rank {s0['rs'].sum() / s0['rc'].sum():.4f}")
    # sanity: OOS script full-model 2012-18 next MSE 40.426 (2012 incl.) -> recompute
    m12 = ~final & (SH >= 3) & (year <= 2018)
    WNa = full_next({"_tilt_all": 1})
    P(f"  check vs bt_ext_oos: next 2012-18 MSE {np.mean((WNa[m12] - act[m12]) ** 2):.3f} (log 40.426; engine top-30 QB exemption on: {np.mean((WN[m12] - act[m12]) ** 2):.3f}); ROS 2012-18 MSE {np.mean((WR_[ok12 & (year <= 2018)] - T[ok12 & (year <= 2018)]) ** 2):.3f} (log 10.450)")

    NEXT_P = ["vacated-role pool", "QB game-total tilt", "usage evidence, RB", "usage evidence, WR", "QB changed teams x.90", "WR one-game prior x5", "rookie ramp (weeks 1-2)", "depth-string docks (vets)"]
    ROS_P = ["usage evidence (all positions)", "usage evidence, RB (ROS)", "usage evidence, WR (ROS)", "TE snap-share level e .3", "TE 31-60 x1.10", "WR 61-100 prior weight x0.6", "second-year QB prior weight x0.75",
             "RB backup (top 150) x1.04", "QB changed teams x.84", "rookie prior weight RB 1.6 / TE 2.5 (v2.33)", "RB 61-100 prior weight x2.5", "depth-string docks (vets)"]
    only = [k for k in os.environ.get("ONLY", "").split("|") if k]
    if only:
        for k in only:
            if k in NEXT_P: run_piece("NEXT", k, full_next, HN)
            if k in ROS_P: run_piece("ROS", k, full_ros, HR)
    if not only and not os.environ.get("SKIP_MAIN"):
        P("\n=== A  NEXT GAME ===")
        for k in NEXT_P: run_piece("NEXT", k, full_next, HN)
        P("\n=== B  REST OF SEASON ===")
        for k in ROS_P: run_piece("ROS", k, full_ros, HR)

        P("\n=== C  SUMMARY (layer effect: neg = helps; reads ALL 13-25 | 16-25 | RECENCY .85) ===")
        for (hz, k), r in RESULTS.items():
            rr = r["reads"]
            cell = " | ".join(f"{rn}: {v['c']['err']:+.2f}%/w{v['c']['wtd']:+.2f}% {v['helped']}/{v['ny']} {v['tag']}" + (f" rz{v['rz']['best']:g}{'*' if v['rz']['passes'] else ''}" if v['rz'] else "") for rn, v in rr.items())
            sl = r["slope"]; sig = "CI<0" if sl[2] < 0 else ("CI>0" if sl[1] > 0 else "ns")
            P(f"  {hz:4s} {k:44s} | {cell} | slope {sl[0]:+.3f} [{sl[1]:+.3f},{sl[2]:+.3f}] {sig} | 13-18 {r['e1']:+.2f} 19-25 {r['e2']:+.2f}")
        pickle.dump({k: {kk: vv for kk, vv in v.items()} for k, v in RESULTS.items()}, open(BX.ext_path(f"oos_layer_retest{tag}.pkl"), "wb"))

    # ================= D  JOINT PULLS =================
    for hz, env, fullf, H in (("NEXT", "JOINT_NEXT", full_next, HN), ("ROS", "JOINT_ROS", full_ros, HR)):
        spec = {kv.split("=")[0]: (float(kv.split("=")[1]) if "=" in kv else 0.0) for kv in os.environ.get(env, "").split("|") if kv}
        ks = list(spec)
        if not ks: continue
        RPOS.clear(); W = fullf(); Wst = stats(W, H)
        J = fullf(dict(spec)); touched = H["rows"] & (np.abs(J - W) > 1e-9); Wst = stats(W, H, touched); Jst = stats(J, H, touched)
        P(f"\n=== D  JOINT CHANGE [{hz}] (strength per piece, 0 = pulled): {spec}  rows touched {int(touched.sum()):,} ===")
        P("    by season, % MSE all rows (pulled vs wired; neg = pulling helps): " + " ".join(f"{y % 100:02d}:{v:+.2f}" for y, v in zip(GY, season_eff(Jst, Wst))))
        P("    by season, top-150 wtd %: " + " ".join(f"{y % 100:02d}:{v:+.2f}" for y, v in zip(GY, season_eff(Jst, Wst, 'wse'))))
        sl = slope_ci(season_eff(Jst, Wst)); P(f"    trend slope {sl[0]:+.3f} [{sl[1]:+.3f}, {sl[2]:+.3f}]")
        sumind = 0.0
        for rn, (wd, fw) in READS.items():
            w = np.array([wd[y] for y in GY]); c = comp(Jst, Wst, w); hy = [y for y in GY if wd[y] > 0]
            b = [y for y in hy if Jst["se"][YIX[y]] < Wst["se"][YIX[y]]]; fb_ = [y for y in fw if Jst["se"][YIX[y]] < Wst["se"][YIX[y]]]
            P(f"    {rn:9s} pulled together: err {c['err']:+.3f}% (touched {c['terr']:+.2f}%) wtd {c['wtd']:+.3f}% MAE {c['mae']:+.3f}% rank {c['rk']:+.4f} | better {len(b)}/{len(hy)} fwd {len(fb_)}/{len(fw)}")
        for k in ks:
            o = stats(fullf({k: spec[k]}), H); c = comp(o, Wst, np.ones(NY)); P(f"      alone: {k:40s} s={spec[k]:g} err {c['err']:+.3f}% wtd {c['wtd']:+.3f}% rank {c['rk']:+.4f}")
    log.close()


if __name__ == "__main__":
    main()
