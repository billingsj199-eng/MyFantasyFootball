#!/usr/bin/env python3
"""
DECAYED-GAMES HISTORY inside the full shadow (2026-09-17). Jack: "lets build the decayed history".

backtest_history_window.py: as a raw predictor of the coming season, an exponentially decayed average of a player's
past games (half-life 10-16 games) beats today's 0.5 x 3-season + 0.5 x last-8 by ~3% (6/7 seasons, top 150 weighted;
ADP 1-30 -6%); the last 8 games deserve ~0.2 weight, not 0.5. Here the decayed history (dk, PRESEASON: games before the
season only; in-season evidence stays the blend's job) replaces the history everywhere it enters the shadow:
  1. HIST + OPP blend (veterans): refit  ppg ~ 1 + history + OPP  per position with dk instead of the regressed
     3-season history (LOYO; forward = earlier seasons only). Raw OPP comes from opp_prior_preds.json (now dumped).
  2. hand prior: that blend for veterans with an opportunity row, age-adjusted dk for the rest; then the same ADP
     market blend, docks, 2nd-year boost and 0.8 shrink as today.
  3. ridge half: features hist / h3 / l8 replaced by dk (+ the refit oppcal), LOYO and forward.
Variants: current | hand prior only | ridge only | both; half-lives 8 / 12 / 16.
Graded on the season table (prior vs the season) and on the weekly harness (full v2.22-form shadow): importance-
weighted top 150, non-overlapping ADP bands, weekly rank, by stage; vs the current shadow and today's Clay blend.
Log decayed_history.log; results -> data/decayed_history.js (SIM_DECAYHIST_BT).
"""
import json, os, sys, time, warnings
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy.stats import rankdata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import research_clay_vs_shadow as CS
import backtest_season_long as SL
cal = NW.cal
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "decayed_history.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
YEARS, POS4 = NW.YEARS, NW.POS4
HLS = (8, 12, 16)
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "blend": [], "season": [], "weekly": [], "forward": [], "coef": {}}


def decayed(name, pos, Y, hl):
    wrec = cal.weekly_rec(name, pos)
    if wrec is None: return np.nan, 0
    games = []
    for yy in range(Y - 4, Y):
        for w in wrec.get("seasons", {}).get(str(yy), []):
            if cal.played(w) and isinstance(w.get("fpts"), (int, float)): games.append((yy, int(w["wk"]), float(w["fpts"])))
    if len(games) < 8: return np.nan, len(games)
    games.sort(); pts = np.array([g_[2] for g_ in games]); k = np.arange(len(pts))[::-1]; w_ = 0.5 ** (k / hl)
    return float(np.sum(w_ * pts) / np.sum(w_)), len(games)


def main():
    t0 = time.time()
    P("=== Decayed-games history inside the full shadow ===")
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, clay, layers, adp, pid = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"], F["adp"], A["pid"]
    T = SL.build_table()
    preds = json.load(open(os.path.join(HERE, "opp_prior_preds.json"), encoding="utf-8"))
    # ---- per player-season: dk for each half-life, raw OPP ----
    PS = {}
    for r in T.itertuples(index=False):
        k = (int(r.year), r.name, r.pos); pr = preds.get(f"{int(r.year)}|{r.pid}") if isinstance(r.pid, str) else None
        PS[k] = {"opp": (pr or {}).get("OPP"), "histreg": (pr or {}).get("HISTREG"), "seg": (pr or {}).get("seg"), **{f"dk{h}": decayed(r.name, r.pos, int(r.year), h)[0] for h in HLS}}
    for h in HLS: T[f"dk{h}"] = [PS[(int(a), b, c)][f"dk{h}"] for a, b, c in zip(T.year, T.name, T.pos)]
    T["opp_raw"] = [PS[(int(a), b, c)]["opp"] if PS[(int(a), b, c)]["opp"] is not None else np.nan for a, b, c in zip(T.year, T.name, T.pos)]
    T["histreg"] = [PS[(int(a), b, c)]["histreg"] if PS[(int(a), b, c)]["histreg"] is not None else np.nan for a, b, c in zip(T.year, T.name, T.pos)]
    P(f"  player-seasons {len(T)} | raw OPP available {int((~T.opp_raw.isna()).sum())} | decayed history (hl 12) available {int((~T.dk12.isna()).sum())}")
    tpos, tyr, tppg, tg = T.pos.values, T.year.values, T.ppg.values, T.games.values.astype(float)
    # ---- 1. refit HIST + OPP ----
    def fit_blend(hcol, fwd):
        out = np.full(len(T), np.nan); hv, ov = T[hcol].values.astype(float), T.opp_raw.values.astype(float); okr = ~np.isnan(hv) & ~np.isnan(ov) & (T.rookie.values == 0)
        coefs = {}
        for ps in ("RB", "WR", "TE"):
            for y in YEARS:
                tr = okr & (tpos == ps) & ((tyr < y) if fwd else (tyr != y)); te = okr & (tpos == ps) & (tyr == y)
                if tr.sum() < 40:
                    if fwd: tr = okr & (tpos == ps) & (tyr != y)      # no earlier seasons yet: fall back to LOYO (those seasons are not forward-graded)
                    if tr.sum() < 40: continue
                if not te.any(): continue
                X = np.column_stack([np.ones(tr.sum()), hv[tr], ov[tr]]); sw = np.sqrt(tg[tr]); b = np.linalg.lstsq(X * sw[:, None], tppg[tr] * sw, rcond=None)[0]
                out[te] = b[0] + b[1] * hv[te] + b[2] * ov[te]; coefs[ps] = [round(float(v), 4) for v in b]
        return out, coefs
    BL = {}
    P("\n=== 1. HIST + OPP blend refit (veterans with an opportunity row): games-weighted MSE vs the season, LOYO ===")
    for hcol, lab in (("histreg", "regressed 3-season history (today)"),) + tuple((f"dk{h}", f"decayed games, half-life {h}") for h in HLS):
        bl, cf = fit_blend(hcol, False); BL[hcol] = bl; m = ~np.isnan(bl) & ~np.isnan(fit_blend("histreg", False)[0])
        e = SL.wmse(bl[m], tppg[m], tg[m]); RES["blend"].append({"hist": lab, "n": int(m.sum()), "mse": round(e, 3), "coef": cf}); P(f"  {lab:40s} n={m.sum():4d} MSE {e:6.3f} | coefficients [a, b history, c opportunity] {cf}")
    BLF = {hcol: fit_blend(hcol, True)[0] for hcol in ("histreg",) + tuple(f"dk{h}" for h in HLS)}
    # full-sample coefficients for the live build
    for h in HLS:
        hv, ov = T[f"dk{h}"].values.astype(float), T.opp_raw.values.astype(float); okr = ~np.isnan(hv) & ~np.isnan(ov) & (T.rookie.values == 0); RES["coef"][f"dk{h}"] = {}
        for ps in ("RB", "WR", "TE"):
            m = okr & (tpos == ps); X = np.column_stack([np.ones(m.sum()), hv[m], ov[m]]); sw = np.sqrt(tg[m]); b = np.linalg.lstsq(X * sw[:, None], tppg[m] * sw, rcond=None)[0]; RES["coef"][f"dk{h}"][ps] = [round(float(v), 4) for v in b]
    # ---- map player-season values onto weekly rows ----
    tkey = {(int(a), b, c): i for i, (a, b, c) in enumerate(zip(T.year, T.name, T.pos))}; ti = np.array([tkey.get((int(year[i]), A["name"][i], pos[i]), -1) for i in range(n)]); hasT = ti >= 0
    def to_rows(v): return np.where(hasT, np.asarray(v, dtype=float)[np.maximum(ti, 0)], np.nan)
    hand0, fb_pos, curve = F["prior"], F["fb_pos"], F["adp_curve"]
    hist_adj = np.array([NW.age_adjust(pos[i], F["hist"][i], A["age"][i]) if not np.isnan(F["hist"][i]) else np.nan for i in range(n)])
    hist0 = np.where(F["vet_opp"], A["oppcal"], hist_adj); wv = np.where(A["exp"] == 1, 0.5, 0.75)
    pr0 = fb_pos + (hand0 - fb_pos) / 0.8; base0 = np.where(F["mkt_ok"], (1 - wv) * hist0 + wv * curve, hist0); tun = ~np.isnan(hist0) & (base0 > 0) & ~A["rookie"]
    mult = np.where(tun, pr0 / base0, 1.0)
    def hand_with(h, fwd, wvet=None):
        wv = np.where(A["exp"] == 1, 0.5, 0.75 if wvet is None else wvet)
        dk = to_rows(T[f"dk{h}"].values); bl = to_rows((BLF if fwd else BL)[f"dk{h}"])
        dk_adj = np.array([NW.age_adjust(pos[i], dk[i], A["age"][i]) if not np.isnan(dk[i]) else np.nan for i in range(n)])
        hnew = np.where(F["vet_opp"] & ~np.isnan(bl), bl, np.where(~np.isnan(dk_adj), dk_adj, hist0))
        base = np.where(F["mkt_ok"], (1 - wv) * hnew + wv * curve, hnew); pr = mult * base
        return np.where(tun & ~np.isnan(pr), fb_pos + 0.8 * (pr - fb_pos), hand0)
    # ---- ridge variants ----
    LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]
    def ridge_feats(h): return [f for f in LIVE if f not in ("hist", "h3", "l8", "oppcal")] + [f"dk{h}", f"oppcal_dk{h}"]
    for h in HLS: T[f"oppcal_dk{h}"] = BL[f"dk{h}"]
    RLO = {"cur": SL.loyo(T, LIVE, "ridge", 10.0), **{h: SL.loyo(T, ridge_feats(h), "ridge", 10.0) for h in HLS}}
    RLO["add"] = SL.loyo(T, LIVE + ["dk12"], "ridge", 10.0)
    Tf = T.copy()
    for h in HLS: Tf[f"oppcal_dk{h}"] = BLF[f"dk{h}"]
    RFW = {"cur": SL.forward(T, LIVE, "ridge", 10.0), **{h: SL.forward(Tf, ridge_feats(h), "ridge", 10.0) for h in HLS}}
    RFW["add"] = SL.forward(T, LIVE + ["dk12"], "ridge", 10.0)
    # ---- 2. season-table grade of the PRIOR (week-1 rows) ----
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    def colv(c): return np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    xfp = colv("xfp_pg"); ev = has & (g >= 1) & ~np.isnan(xfp); xf = np.where(ev, xfp, ppg)
    lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0)); evid = lam * xf + (1 - lam) * ppg
    gt = colv("game_total"); z = np.zeros(n)
    for y in YEARS:
        for w_ in range(1, 19):
            m = (year == y) & (wk == w_) & ~np.isnan(gt)
            if m.sum() > 20 and gt[m].std() > 0: z[m] = np.clip((gt[m] - gt[m].mean()) / gt[m].std(), -2.5, 2.5)
    qbo = colv("qb_out") == 1; PW = np.where((pos == "WR") & (g == 1), F["Pvec"] * 5, F["Pvec"])
    def shadow(hand, ridge_T):
        r = to_rows(ridge_T); prior = np.where(np.isnan(r) | (pos == "QB"), hand, 0.5 * r + 0.5 * hand); out = NW.blend(prior, g, evid, PW) * layers
        for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
        out = np.where(F["on"], out * np.power(F["pm"], 0.75), out); out = np.where(pos == "QB", out * np.exp(0.03 * z), out)
        return np.where((pos == "WR") & qbo, out * np.where(adp <= 60, 0.85, 0.95), out), prior
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, A["name"])], dtype=float)
    W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay); CUR = NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers
    lv = curve.copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & (adp <= 150)].mean()
    wt = np.maximum(0.05, lv) ** 2; top150 = adp <= 150
    groups = defaultdict(list)
    for i in np.where(top150)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
    groups = {k: np.array(v) for k, v in groups.items() if len(v) >= 8}
    def rho(p, ys): return float(np.mean([np.corrcoef(rankdata(act[ix]), rankdata(p[ix]))[0, 1] for (y, w_, ps), ix in groups.items() if y in ys]))
    def wm(p, m): return float(np.average((p[m] - act[m]) ** 2, weights=wt[m]))
    e = lambda p, m: float(np.mean((p[m] - act[m]) ** 2))
    def run(fwd):
        R = RFW if fwd else RLO; base, prior0 = shadow(hand0, R["cur"]); V = {"current shadow": (base, prior0)}
        for h in HLS:
            V[f"hl {h}: hand prior only"] = shadow(hand_with(h, fwd), R["cur"]); V[f"hl {h}: ridge only"] = shadow(hand0, R[h]); V[f"hl {h}: BOTH"] = shadow(hand_with(h, fwd), R[h])
        V["hl 12: ridge ADDS dk (keeps hist/h3/l8)"] = shadow(hand0, R["add"])
        for wvv in (0.65, 0.55, 0.45): V[f"hl 12 hand, market weight {wvv}"] = shadow(hand_with(12, fwd, wvv), R["cur"])
        for wvv in (0.65, 0.55): V[f"TODAY's history, market weight {wvv}"] = shadow(np.where(tun, fb_pos + 0.8 * (mult * np.where(F["mkt_ok"], (1 - np.where(A["exp"] == 1, 0.5, wvv)) * hist0 + np.where(A["exp"] == 1, 0.5, wvv) * curve, hist0) - fb_pos), hand0), R["cur"])
        return V
    def report(V, store, title, ys, fm):
        base = V["current shadow"][0]; P(f"\n=== {title}: cell = error vs the CURRENT shadow (seasons better); top 150 is importance-weighted, bands unweighted ===")
        cuts = (("TOP 150 wtd", top150, True), ("ADP 1-30", adp <= 30, False), ("31-60", (adp > 30) & (adp <= 60), False), ("61-100", (adp > 60) & (adp <= 100), False), ("101-150", (adp > 100) & (adp <= 150), False), ("week 1", top150 & (g == 0), True), ("games 1-3", top150 & (g >= 1) & (g <= 3), True), ("games 4+", top150 & (g >= 4), True))
        for nm, (p, _) in V.items():
            cells = []
            for lab, m, wtd in cuts:
                mm = m & fm; f_ = wm if wtd else e; d = (f_(p, mm) / f_(base, mm) - 1) * 100; wins = sum(1 for y in ys if f_(p, mm & (year == y)) < f_(base, mm & (year == y)) - 1e-12)
                store.append({"variant": nm, "cut": lab, "d": round(d, 2), "wins": wins, "years": len(ys), "vsClay": round((f_(p, mm) / f_(CUR, mm) - 1) * 100, 2)}); cells.append(f"{lab}: {d:+.2f}% ({wins}/{len(ys)})")
            P(f"  {nm:42s} " + " | ".join(cells) + f" || rho {rho(p, set(ys)):.4f} | top150 vs Clay {(wm(p, top150 & fm)/wm(CUR, top150 & fm)-1)*100:+.2f}%")
    V = run(False)
    # prior-level grade vs the season (week-1 rows)
    P("\n=== 2. The PRIOR itself vs the player's season rate (week-1 rows, top 150): RMSE and correlation ===")
    w1 = top150 & (g == 0); seas = defaultdict(list)
    for i in range(n): seas[(year[i], A["name"][i])].append(act[i] / max(layers[i], 0.3))
    sp = np.array([np.mean(seas[(year[i], A["name"][i])]) for i in range(n)])
    for nm, (_, prior) in V.items():
        rm = float(np.sqrt(np.average((prior[w1] - sp[w1]) ** 2, weights=wt[w1]))); cc = float(np.corrcoef(prior[w1], sp[w1])[0, 1]); RES["season"].append({"variant": nm, "rmse": round(rm, 3), "corr": round(cc, 3)})
        P(f"  {nm:42s} weighted RMSE {rm:.3f} | corr {cc:.3f} | 1-30 corr {np.corrcoef(prior[w1 & (adp <= 30)], sp[w1 & (adp <= 30)])[0,1]:.3f} | 31-60 corr {np.corrcoef(prior[w1 & (adp > 30) & (adp <= 60)], sp[w1 & (adp > 30) & (adp <= 60)])[0,1]:.3f}")
    report(V, RES["weekly"], "3. WEEKLY shadow, LOYO", YEARS, np.ones(n, bool))
    report(run(True), RES["forward"], "4. WEEKLY shadow, FORWARD 2021-25 (blend refit + ridge on earlier seasons only)", YEARS[2:], year >= YEARS[2])
    b = [r for r in RES["weekly"] if r["cut"] == "TOP 150 wtd" and r["variant"] != "current shadow"]; best = min(b, key=lambda r: r["d"]); fb = [r for r in RES["forward"] if r["cut"] == "TOP 150 wtd" and r["variant"] == best["variant"]][0]
    RES["summary"] = f"Decayed history in the full shadow, top 150 weighted: best = {best['variant']} {best['d']:+.2f}% vs the current shadow ({best['wins']}/7), {best['vsClay']:+.2f}% vs the Clay blend; forward {fb['d']:+.2f}% ({fb['wins']}/5)."
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "decayed_history.js"), "w", encoding="utf-8") as fh:
        fh.write("window.SIM_DECAYHIST_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/decayed_history.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
