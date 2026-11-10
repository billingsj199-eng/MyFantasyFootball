#!/usr/bin/env python3
"""
TD-LUCK LAYER: DOES IT PREDICT ANYTHING?  (Jack 2026-11-10: "remove td luck I feel like it doesnt actually have correlation")

Full-board ON / OFF read of the per-player TD-luck mean reversion (engine tdLuckAdj: RB k .75, WR / TE 1.0, QB pass .5), every
position it touches. Read-only on every live file; writes only its own log tdluck_onoff.log.

  H  HISTORY 2019-25 on the honest Clay-free shadow replica (backtest_base_remeasure.shadow_current, luck=True vs luck=False - the
     form the engine runs since v2.22: k x TD pts x (xTD - TD)/g x g/(P + g) x (1 - usage lam)). Rows = top-150 ADP, final week
     dropped, shadow >= 3, 1+ game played. NEXT GAME and REST OF SEASON (3-10 games played, 4+ left; rate x future context + luck).
     Per position: error with / without the layer (squared and absolute), seasons better of 7, forward 2022-25 of 4, act / proj,
     share of moved rows where OFF was closer, within-week rank order, the raw correlation between season-to-date touchdowns under
     expected per game (xTD - TD)/g and the miss of the OFF number, tercile levels, and the best-fit strength b of the luck term
     (b 1 = as shipped, b 0 = no signal).
  L  2026 LOCK ROWS W2-9 (data/snapshots, half-PPR): shipped mean with the layer vs with it taken out ((1 - market weight) x the
     stored luck, the luck_scorecard.py convention) and the model number before the book anchor; same metrics; raw correlation of
     as-of-week (xTD - TD)/g (weekly maps in data/sim_routes.js) with next week's miss and with the W6-9 miss from the W6 lock.

Bar for a layer to earn its place (same as every layer decision): its rows < -0.3% squared error, 5+ of 7 seasons, forward
better in 3+ of 4, board not worse.
"""
import json, math, os, pickle, re, sys, warnings
from collections import defaultdict
import numpy as np
from scipy.stats import rankdata, spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
warnings.filterwarnings("ignore")
import backtest_base_remeasure as BR
REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"
LOG = open(os.path.join(HERE, "tdluck_onoff.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + "\n"); LOG.flush()
POS4 = ("QB", "RB", "WR", "TE"); FWD = (2022, 2023, 2024, 2025)


def pear(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float)
    if len(a) < 10 or a.std() == 0 or b.std() == 0: return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def fit_b(resid_off, luck):
    """resid_off = a + b x luck: b 1 = the term is right-sized, b 0 = no signal. Returns b, se."""
    x = np.asarray(luck, float); y = np.asarray(resid_off, float)
    if len(x) < 30 or x.std() == 0: return float("nan"), float("nan")
    xm = x - x.mean(); b = float((xm * (y - y.mean())).sum() / (xm ** 2).sum())
    r = y - y.mean() - b * xm; se = float(np.sqrt((r ** 2).sum() / (len(x) - 2) / (xm ** 2).sum()))
    return b, se


def history():
    X = pickle.load(open(os.path.join(HERE, "_tmp", "X_cache.pkl"), "rb")); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, name, adp, layers = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["name"], X["adp"], X["layers"]
    YEARS = sorted(set(int(y) for y in year)); adpx = np.where(np.isnan(adp), 999.0, adp)
    ON, SH0 = BR.shadow_current(X, luck=True); OFF, _ = BR.shadow_current(X, luck=False)
    luckT = ON - OFF
    import pandas as pd
    L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet")); lk = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(L.year, L.pid, L.wk)) if isinstance(b, str)}
    pid = X["A"]["pid"]; lix = np.array([lk.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)])
    tdl = np.where(lix >= 0, np.nan_to_num(L["td_luck_pg"].values[np.maximum(lix, 0)].astype(float), nan=0.0), 0.0)   # (xTD - TD) / g season to date: + = fewer TDs than expected
    finw = np.where(year <= 2020, 17, 18); final = wk == finw
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & (adpx <= 150)].mean()
    wt = np.maximum(0.05, lv) ** 2
    okN = (adpx <= 150) & ~final & (SH0 >= 3) & (g >= 1)
    moved = np.abs(luckT) >= 0.05
    # rest of season: target + future context
    seq = defaultdict(list)
    for i in range(n):
        if not final[i]: seq[(name[i], pos[i], int(year[i]))].append(i)
    T = np.full(n, np.nan); ctx = np.full(n, np.nan)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(layers[ix], .5, 1.8)
        for a, i in enumerate(ix):
            if len(ix) - a >= 4: T[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    rate_off = OFF / np.where(layers > 0, layers, 1.0); R_OFF = rate_off * ctx; R_ON = R_OFF + luckT
    okR = (adpx <= 150) & ~np.isnan(T) & (g >= 3) & (g <= 10) & (R_OFF >= 3)

    def rho(q, tgt, m):
        gr = defaultdict(list)
        for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        rh = [np.corrcoef(rankdata(tgt[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]
        return float(np.mean(rh)) if rh else float("nan")

    def block(title, on, off, tgt, ok):
        P(f"\n--- {title} ---")
        P(f"  {'cell':22s} {'n':>6s} {'p-s':>5s} {'|luck|':>6s} | {'MSE on vs off':>13s} {'yrs':>4s} {'fwd':>10s} | {'wtd MSE':>8s} | {'MAE on vs off':>13s} {'yrs':>4s} | {'act/on':>6s} {'act/off':>7s} | {'off closer':>10s} | {'rank on':>7s} {'off':>6s}")
        for lab, m0 in [("ALL moved rows", np.ones(n, bool))] + [(ps + " moved rows", pos == ps) for ps in POS4] + [("ALL rows (board)", None)] + [(ps + " all rows", (pos == ps, 1)) for ps in POS4]:
            if m0 is None: m = ok
            elif isinstance(m0, tuple): m = ok & m0[0]
            else: m = ok & moved & m0
            if m.sum() < 30: continue
            mse = lambda q, mm: float(np.mean((q[mm] - tgt[mm]) ** 2)); mae = lambda q, mm: float(np.mean(np.abs(q[mm] - tgt[mm]))); wm = lambda q, mm: float(np.average((q[mm] - tgt[mm]) ** 2, weights=wt[mm]))
            ys = [y for y in YEARS if (m & (year == y)).sum() >= 10]
            w1 = sum(1 for y in ys if mse(on, m & (year == y)) < mse(off, m & (year == y))); w2 = sum(1 for y in ys if mae(on, m & (year == y)) < mae(off, m & (year == y)))
            fm = m & np.isin(year, FWD); wf = sum(1 for y in FWD if (m & (year == y)).sum() >= 10 and mse(on, m & (year == y)) < mse(off, m & (year == y)))
            closer = float(np.mean(np.abs(off[m] - tgt[m]) < np.abs(on[m] - tgt[m])))
            P(f"  {lab:22s} {int(m.sum()):6d} {len(set(zip(name[m], year[m]))):5d} {np.abs(luckT[m]).mean():6.2f} | {100*(mse(on, m)/mse(off, m)-1):+12.2f}% {w1}/{len(ys)} {100*(mse(on, fm)/mse(off, fm)-1):+6.2f}% {wf}/4 | {100*(wm(on, m)/wm(off, m)-1):+7.2f}% | {100*(mae(on, m)/mae(off, m)-1):+12.2f}% {w2}/{len(ys)} | {tgt[m].sum()/on[m].sum():6.3f} {tgt[m].sum()/off[m].sum():7.3f} | {100*closer:9.0f}% | {rho(on, tgt, m):7.4f} {rho(off, tgt, m):6.4f}")
        P("  (negative % = the layer makes the number better; 'yrs' = seasons the layer wins; 'off closer' = share of rows where the number WITHOUT the layer was nearer the actual)")
        P(f"\n  raw signal: season-to-date TDs under expected per game (xTD - TD)/g vs the miss of the OFF number (actual - off), 3+ games played")
        P(f"  {'pos':4s} {'n':>6s} | {'pearson r':>9s} {'spearman':>9s} | {'best-fit strength b (se)':>26s} | act / off by tercile of (xTD - TD)/g: lucky (most TDs over) / middle / unlucky")
        for ps in ("ALL",) + POS4:
            m = ok & (g >= 3) & (np.abs(tdl) > 1e-9) & ((pos == ps) if ps != "ALL" else np.ones(n, bool))
            if m.sum() < 60: continue
            res = tgt[m] - off[m]; r = pear(tdl[m], res); sr = float(spearmanr(tdl[m], res)[0]); b, se = fit_b(res, luckT[m])
            q1, q2 = np.quantile(tdl[m], [1 / 3, 2 / 3]); ter = [m & (tdl <= q1), m & (tdl > q1) & (tdl <= q2), m & (tdl > q2)]
            P(f"  {ps:4s} {int(m.sum()):6d} | {r:+9.3f} {sr:+9.3f} | {b:+12.2f} ({se:.2f}){'':10s} | " + " / ".join(f"{tgt[t].sum()/off[t].sum():.3f}" for t in ter) + "   with the layer: " + " / ".join(f"{tgt[t].sum()/on[t].sum():.3f}" for t in ter))
        P("  (r > 0 and unlucky tercile above 1 = players short on touchdowns go on to beat the number without the layer, i.e. the signal is real; b near 1 = sized right)")

    P(f"=== H  HISTORY 2019-25, honest shadow replica (BR.shadow_current luck on vs off), top-150 ADP, half-PPR ===")
    block(f"H1 NEXT GAME ({int(okN.sum()):,} rows, {int((okN & moved).sum()):,} moved by the layer)", ON, OFF, act, okN)
    block(f"H2 REST OF SEASON per game ({int(okR.sum()):,} checkpoints with 3-10 games played and 4+ left)", R_ON, R_OFF, T, okR)


def tdmaps():
    s = open(os.path.join(HERE, "data", "sim_routes.js"), encoding="utf-8").read(); out = {}
    for key, nm in (("RB", "SIM_RB_TDLUCK_2026"), ("REC", "SIM_REC_TDLUCK_2026"), ("QB", "SIM_QB_TDLUCK_2026")):
        i = s.find(nm); j = s.find("{", i); out[key], _ = json.JSONDecoder().raw_decode(s[j:])
    return out


def norm(s):
    s = s.lower().replace(".", "").replace("'", "").replace("-", " "); s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s); return re.sub(r"\s+", " ", s).strip()


def locks():
    raw = open(os.path.join(REPO, "data", "weekly_stats_active.js"), encoding="utf-8").read(); D = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    acts = {w: {} for w in range(1, 10)}
    for nm, rec in D.items():
        for w in (rec.get("seasons") or {}).get("2026") or []:
            if w.get("wk") in acts and isinstance(w.get("fpts"), (int, float)): acts[w["wk"]][norm(nm)] = float(w["fpts"])
    TM = tdmaps(); rows = []
    for wk in range(2, 10):
        f = os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{wk}.json")
        if not os.path.exists(f): continue
        S = json.load(open(f, encoding="utf-8"))
        for p in S["players"]:
            ps = p.get("pos")
            if ps not in POS4 or "luck" not in p or not isinstance(p.get("mean"), (int, float)) or p.get("jsMean") is None: continue
            nk = norm(p["name"]); a = acts[wk].get(nk)
            if a is None: continue
            wa = (p.get("tun") or {}).get("wa")
            if wa is None: wa = 0.70 if p.get("propMean") is not None else 0.0
            if p.get("propMean") is None: wa = 0.0
            l = float(p.get("luck") or 0.0)
            mp = TM["QB" if ps == "QB" else "RB" if ps == "RB" else "REC"].get(nk); xs = td = 0.0; gg = 0
            if mp and mp.get("w"):
                for k, v in mp["w"].items():
                    if int(k) < wk: xs += v[0]; td += v[1]; gg += 1
            rows.append(dict(wk=wk, pos=ps, name=p["name"], nk=nk, ship=float(p["mean"]), js=float(p["jsMean"]), luck=l, wa=float(wa), act=a, tdl=(xs - td) / gg if gg else float("nan"), g=gg))
    A = lambda k: np.array([r[k] for r in rows]); ship, js, luck, wa, act, pos, wk, tdl, g = A("ship"), A("js"), A("luck"), A("wa"), A("act"), A("pos"), A("wk"), A("tdl"), A("g")
    ship_off = ship - (1 - wa) * luck; js_off = js - luck
    P(f"\n=== L  2026 LOCK ROWS W2-9: {len(rows):,} QB/RB/WR/TE player-weeks with a stored luck term, {int((np.abs(luck) >= .05).sum()):,} moved by 0.05+ (half-PPR) ===")
    for title, on, off in (("L1 SHIPPED number (market blend: (1 - market weight) x luck inside it)", ship, ship_off), ("L2 MODEL number before the book anchor", js, js_off)):
        P(f"\n--- {title} ---")
        P(f"  {'cell':16s} {'n':>5s} {'|move|':>6s} | {'MSE on':>7s} {'off':>7s} {'on vs off':>9s} | {'MAE on':>6s} {'off':>6s} {'on vs off':>9s} | {'weeks on better':>15s} | {'act/on':>6s} {'act/off':>7s} | {'off closer':>10s}")
        for lab, m0 in [("ALL moved", np.ones(len(rows), bool))] + [(ps + " moved", pos == ps) for ps in POS4]:
            m = m0 & (np.abs(luck) >= .05)
            if m.sum() < 20: continue
            mse = lambda q, mm: float(np.mean((q[mm] - act[mm]) ** 2)); mae = lambda q, mm: float(np.mean(np.abs(q[mm] - act[mm])))
            wks = [w for w in sorted(set(wk[m])) if (m & (wk == w)).sum() >= 5]; ww = sum(1 for w in wks if mse(on, m & (wk == w)) < mse(off, m & (wk == w)))
            P(f"  {lab:16s} {int(m.sum()):5d} {np.abs(on[m]-off[m]).mean():6.2f} | {mse(on, m):7.2f} {mse(off, m):7.2f} {100*(mse(on, m)/mse(off, m)-1):+8.2f}% | {mae(on, m):6.3f} {mae(off, m):6.3f} {100*(mae(on, m)/mae(off, m)-1):+8.2f}% | {ww:>7d}/{len(wks):<7d} | {act[m].sum()/on[m].sum():6.3f} {act[m].sum()/off[m].sum():7.3f} | {100*np.mean(np.abs(off[m]-act[m]) < np.abs(on[m]-act[m])):9.0f}%")
    P("  (negative % = the layer helped in 2026)")
    P(f"\n--- L3 raw signal 2026: as-of-week (xTD - TD)/g (3+ games in the luck file) vs next week's miss of the shipped number WITHOUT the layer ---")
    P(f"  {'pos':4s} {'n':>5s} | {'pearson r':>9s} {'spearman':>9s} | {'best-fit strength b (se) on the stored luck':>44s} | act / off by tercile: lucky / middle / unlucky")
    for ps in ("ALL",) + POS4:
        m = (g >= 3) & ~np.isnan(tdl) & ((pos == ps) if ps != "ALL" else np.ones(len(rows), bool))
        if m.sum() < 60: continue
        res = act[m] - ship_off[m]; b, se = fit_b(act[m] - js_off[m], luck[m]); q1, q2 = np.quantile(tdl[m], [1 / 3, 2 / 3]); ter = [m & (tdl <= q1), m & (tdl > q1) & (tdl <= q2), m & (tdl > q2)]
        P(f"  {ps:4s} {int(m.sum()):5d} | {pear(tdl[m], res):+9.3f} {float(spearmanr(tdl[m], res)[0]):+9.3f} | {b:+22.2f} ({se:.2f}){'':16s} | " + " / ".join(f"{act[t].sum()/ship_off[t].sum():.3f}" for t in ter))
    # rest of season 2026: TD luck through W5 vs W6-9 average actual minus the W6 no-luck number
    by = defaultdict(dict)
    for r, so in zip(rows, ship_off): by[(r["nk"], r["pos"])][r["wk"]] = (r, so)
    xs, ys, pp = [], [], []
    for (nk, ps), d in by.items():
        if 6 not in d or d[6][0]["g"] < 3 or math.isnan(d[6][0]["tdl"]): continue
        fut = [acts[w][nk] for w in range(6, 10) if nk in acts[w]]
        if len(fut) < 3: continue
        xs.append(d[6][0]["tdl"]); ys.append(float(np.mean(fut)) - d[6][1]); pp.append(ps)
    xs, ys, pp = np.array(xs), np.array(ys), np.array(pp)
    P(f"\n--- L4 rest of season 2026: (xTD - TD)/g through W5 vs (average actual W6-9, 3+ games) - (W6 number without the layer) ---")
    for ps in ("ALL",) + POS4:
        m = (pp == ps) if ps != "ALL" else np.ones(len(xs), bool)
        if m.sum() >= 25: P(f"  {ps:4s} n {int(m.sum()):4d} | pearson r {pear(xs[m], ys[m]):+.3f}  spearman {float(spearmanr(xs[m], ys[m])[0]):+.3f}")
    P("\nLimitations: 2026 lock rows store the LIVE-side luck term (x (1 - usage lam)); since 10-08 the published base is the shadow, whose term is the same sign scaled by its own weight on points, so L1 / L2 are close but not exact after W5. H uses the harness replica of the shadow (no book anchor, no volume / box context).")


if __name__ == "__main__":
    history(); locks(); LOG.close()
