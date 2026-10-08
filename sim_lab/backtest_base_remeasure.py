#!/usr/bin/env python3
"""
RE-MEASURE THE LIVE BASE (Jack 2026-10-07: "re-measure it with the current shadow then").  The 09-17 base decision
(backtest_most_accurate_base.py / backtest_live_candidate.py) compared shadow v2.21-v2.24 with the Clay blend as it ran
then. Both sides have moved: the live form gained TD luck, usage evidence, the late-WR prior and the banged-up prior;
the shadow gained the v2.25 layers, the v2.29 prune and the v2.33 rookie prior weights. This script rebuilds both as
wired TODAY on the same 2019-25 rows (next game, pre-book) and grades every blend weight.

  TODAY   = live form replicated (Clay per-game prior P 5, late-WR P 4, WR/TE usage evidence incl. TE from game 1,
            RB snap mix, rookie level, QB floor, TD luck, x Vegas x FPA x snap trend x banged-up x weather x pool)
            [not replicable: the banged-up PRIOR lift, pecking dock, book anchor - they sit on top of either base]
  SHADOW  = ablate_shadow_next.full() as wired: v2.24 form + v2.25 layers, WR snap trend removed (v2.29 prune),
            v2.33 rookie prior weights (RB x1.6, TE x2.5)
            [not replicable: v2.32 competitive-snap level read / blowout no-dock; rest-of-season structure v2.26-28 is
            for later weeks only and does not touch the next-game number]
  BLENDS  = w x SHADOW + (1 - w) x TODAY, w in .3 .. .9; ESPN 50/50 on top where ESPN has a row.
Grading (house rules): final week dropped, top-150 importance-weighted squared error vs TODAY, seasons better of 7,
weekly within-position rank rho + pairs; cuts by ADP band / position / stage / games played; LOYO + forward weight.
Log base_remeasure.log.
"""
import json, os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
NW = SN.NW; cal = NW.cal; YEARS = list(NW.YEARS); POS4 = ("QB", "RB", "WR", "TE"); FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "base_remeasure.log"), "w", encoding="utf-8") if __name__ == "__main__" else None
def P(s=""):
    print(s)
    if LOG: LOG.write(s + chr(10)); LOG.flush()

LIVE_P = 5
TDK = {"QB": 0.5 * 4.0, "RB": 0.75 * 6.0, "WR": 1.0 * 6.0, "TE": 1.0 * 6.0}
USE_C = {"WR": (0.37, 0.53, 0.005, 0.050), "TE": (-1.87, 0.47, 0.023, 0.057)}


def live_today(X):
    """today's live pre-book number on the harness rows (backtest_fillin_usage live form + late-WR P 4 + TE usage from game 1)"""
    F = X["F"]; A = F["A"]; n = X["n"]
    act, year, wk, pos, g, ppg, clay, layers, adp, pid, name = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"], F["adp"], A["pid"], A["name"]
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, name)], dtype=float)
    W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay)
    mu_y = {}
    for y in YEARS:
        wy = 16.0 if y <= 2020 else 17.0
        lv = sorted([max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0) / wy for c in ch[str(y)].values() if c.get("pos") == "QB"], reverse=True)[:32]
        mu_y[y] = float(np.mean(lv))
    mu = np.array([mu_y[int(y)] for y in year])
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet"))
    def joiner(D):
        k = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(D.year, D.pid, D.wk)) if isinstance(b, str)}
        ix = np.array([k.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)])
        return lambda c, d=np.nan: np.where(ix >= 0, D[c].values[np.maximum(ix, 0)].astype(float), d), ix >= 0
    cv, hasC = joiner(C); lv_, hasL = joiner(L)
    from backtest_inseason_usage import route_features
    xfp, snap = cv("xfp_pg"), cv("snap_std"); rt, _ = route_features(year, pid, wk)
    useok = hasC & (g >= 1) & ~np.isnan(xfp) & ~np.isnan(snap) & ~np.isnan(rt)
    lam_wr = np.select([g <= 2, g <= 5, g <= 8], [0.8, 0.6, 0.5], 0.3); lam_te = np.full(n, 0.3)   # TE from game 1 (2026-10-07)
    lam = np.where(useok & (pos == "WR"), lam_wr, np.where(useok & (pos == "TE"), lam_te, 0.0))
    cw, ct = USE_C["WR"], USE_C["TE"]
    uimp = np.maximum(0.0, np.nan_to_num(np.where(pos == "WR", cw[0] + cw[1] * xfp + cw[2] * rt + cw[3] * snap, ct[0] + ct[1] * xfp + ct[2] * rt + ct[3] * snap), nan=0.0))
    ppg0 = np.maximum(0.0, ppg)
    tdl = np.nan_to_num(lv_("td_luck_pg", 0.0), nan=0.0); tdk = np.array([TDK[p_] for p_ in pos])
    rook = np.nan_to_num(lv_("rookie_mult", 1.0), nan=1.0); cond = np.nan_to_num(lv_("cond_mult", 1.0), nan=1.0)
    wx = np.nan_to_num(lv_("weather_mult", 1.0), nan=1.0); pool = np.nan_to_num(lv_("pool_mult", 1.0), nan=1.0)
    inh = np.nan_to_num(lv_("qb_inherit_mult", 1.0), nan=1.0) > 1.0
    rbu = lv_("usage_half"); rbu = np.where(pos == "RB", rbu, np.nan)
    snapm = np.nan_to_num(cv("snapmult", 1.0), nan=1.0)
    chain = layers * snapm * cond * wx * pool
    PS = np.where((pos == "WR") & (lam > 0) & (np.isnan(adp) | (adp > 60)), 4.0, float(LIVE_P))   # late-WR prior (2026-10-05)
    ev = np.where(lam > 0, lam * uimp + (1 - lam) * ppg0, ppg0)
    base = np.where(g > 0, (PS * clay_gm + g * ev) / (PS + g), clay_gm) * rook
    fl = (pos == "QB") & ~inh & (base >= 5) & (base < mu); base = np.where(fl, mu + 0.70 * (base - mu), base)
    base = np.where(~np.isnan(rbu), 0.85 * base + 0.15 * np.nan_to_num(rbu, nan=0.0), base)
    luck = np.where(g > 0, tdk * tdl * g / (LIVE_P + g) * (1 - lam), 0.0)
    return np.maximum(0.0, base * chain + luck), dict(clay_gm=clay_gm, chain=chain, inh=inh, useok=useok)


SHADOW_LUCK = True   # 2026-10-08: the engine shadow has carried the TD-luck term since v2.22 (ncLuckScale); the replica did not - parity restored


def shadow_current(X, luck=None, lam_override=None, te_dock_k=0.5, te_lift_k=0.5):
    """ablate_shadow_next.full() as wired today: v2.25 layers on, WR snap trend off (v2.29), v2.33 rookie prior weights, TE docks at .5 (10-08), TD luck (v2.22)"""
    luck_on = SHADOW_LUCK if luck is None else luck
    F = X["F"]; n = X["n"]; pos, g, wk, adp, act = X["pos"], X["g"], X["wk"], X["adp"], X["act"]
    finw = np.where(X["year"] <= 2020, 17, 18); final = wk == finw
    SH0 = SN.shadow(X); allr = ~final & (SH0 >= 3)
    base_lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    if lam_override is not None: base_lam = np.where(np.isnan(lam_override), base_lam, lam_override)   # 2026-10-08 rookie evidence tests
    l1 = X["snap_l1"]; dev = np.zeros(n)
    for ps in ("WR", "TE"):
        m = (pos == ps) & (g >= 1) & ~np.isnan(l1) & allr
        q = np.quantile(SH0[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, SH0, side="right") - 1, 0, 7)
        for k in range(8):
            mk = m & (b_ == k)
            if mk.sum() >= 30: dev[mk] = l1[mk] - np.nanmean(l1[mk])
    low = np.maximum(0, 19 - np.nan_to_num(X["implied"], nan=19)) / 19
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = X["A"]["pid"]; year = X["year"]
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    smx = np.where(has, C["snapmult"].values[np.maximum(idx, 0)], np.nan).astype(float); smx = np.where(np.isnan(smx) | (pos == "QB"), 1.0, smx)
    ev = base_lam * X["xf"] + (1 - base_lam) * X["ppg_v"]
    Pw = F["Pvec"] * np.where((pos == "WR") & (g == 1), 5.0, 1.0)
    Pw = Pw * np.where(X["rookie"] & (pos == "RB"), 1.6, np.where(X["rookie"] & (pos == "TE"), 2.5, 1.0))   # v2.33 rookieP
    out = (Pw * X["prior"] + g * ev) / np.maximum(Pw + g, 1e-9) * X["layers"]
    L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet")); lk = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(L.year, L.pid, L.wk)) if isinstance(b, str)}
    lix = np.array([lk.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); tdl = np.where(lix >= 0, L["td_luck_pg"].values[np.maximum(lix, 0)].astype(float), 0.0)
    tdk = np.array([TDK[p_] for p_ in pos]); luckT = np.where((g > 0) & luck_on, tdk * np.nan_to_num(tdl, nan=0.0) * g / np.maximum(Pw + g, 1e-9) * (1 - base_lam), 0.0)
    for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
    out = np.where(F["on"], out * np.power(F["pm"], 0.75), out)
    out = np.where(pos == "QB", out * np.exp(0.03 * X["z"]), out)
    out = np.where((pos == "WR") & X["qbo"], out * np.where(adp <= 60, 0.85, 0.95), out)
    tek = lambda M: np.where(M < 1, np.power(M, te_dock_k), np.power(M, te_lift_k))   # TE dock / lift exponents (wired .5 / .5 current week, 10-08)
    out = np.where(pos == "RB", out * smx, out); out = np.where(pos == "TE", out * tek(smx), out)          # WR snap trend removed (v2.29 prune)
    out = np.where(pos == "WR", out * np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4), out)
    out = np.where(pos == "TE", out * tek(np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4)), out)
    out = np.where((pos == "QB") & X["mover"], out * 0.90, out)
    out = np.where(pos == "QB", out * (1 - 0.75 * low), out)
    # (WR rookie games 2-5 x.90 is PRUNED in the engine - v2.29 ncPrune skips it - so the replica no longer applies it; 2026-10-08)
    out = np.where((pos == "RB") & (g >= 2) & (g <= 5) & (X["car_sh"] < 0.30), out * 0.90, out)
    return np.maximum(0.0, out + luckT), SH0


def load_espn(X):
    VE = None
    for modname in ("backtest_vs_espn", "research_vs_espn", "backtest_espn_weekly"):
        try: VE = __import__(modname); break
        except Exception: VE = None
    if VE is None or not hasattr(VE, "ESPN_DIR"): return None
    n = X["n"]; year, wk, name, pos = X["year"], X["wk"], X["name"], X["pos"]; E = {}
    try:
        for Y in YEARS:
            d = json.load(open(os.path.join(VE.ESPN_DIR, f"espn_proj_{Y}.json"), encoding="utf-8"))
            for w_, rows in d["weeks"].items():
                for k, v in rows.items():
                    nm, ps = k.rsplit("|", 1); E[(Y, int(w_), VE.nrm(nm), ps)] = VE.espn_half(v.get("s") or {})
    except Exception as e:
        P(f"  ESPN rows unavailable ({e})"); return None
    esp = np.array([E.get((int(year[i]), int(wk[i]), VE.nrm(name[i]), pos[i]), np.nan) for i in range(n)], dtype=float)
    return esp


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    TODAY, LV = live_today(X); SHADOW, SH_OLD = shadow_current(X)
    esp = load_espn(X); okE = (esp is not None) & (~np.isnan(esp) if esp is not None else False) & ((esp > 0.5) if esp is not None else False)
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; po = (wk >= finw - 3) & (wk < finw); top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    base = top150 & ~final & ~LV["inh"]
    wm = lambda q, mm: float(np.average((q[mm] - act[mm]) ** 2, weights=wt[mm])) if mm.any() else np.nan
    ms = lambda q, mm: float(np.mean((q[mm] - act[mm]) ** 2)) if mm.any() else np.nan
    def rank_stats(p, m):
        groups = defaultdict(list)
        for i in np.where(m)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
        rh, pw, tot = [], 0, 0
        for ix in (np.array(x) for x in groups.values()):
            if len(ix) < 8: continue
            a, pv = act[ix], p[ix]; rh.append(np.corrcoef(rankdata(a), rankdata(pv))[0, 1])
            d = pv[:, None] - pv[None, :]; o = a[:, None] - a[None, :]; iu = np.triu_indices(len(ix), 1); okp = (d[iu] != 0) & (o[iu] != 0)
            pw += int(((d[iu] > 0) == (o[iu] > 0))[okp].sum()); tot += int(okp.sum())
        return (float(np.mean(rh)) if rh else np.nan), 100.0 * pw / max(1, tot)
    WG = (0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
    blend = lambda w: w * SHADOW + (1 - w) * TODAY
    withE = lambda p: np.where(okE, 0.5 * p + 0.5 * esp, p) if esp is not None else p
    MODELS = [("TODAY (live pre-book, as wired)", TODAY), ("shadow as wired today", SHADOW), ("shadow v2.24 form (09-17 comparison)", SH_OLD)]
    MODELS += [(f"blend w={w:.1f} shadow", blend(w)) for w in WG[1:-1]]
    if esp is not None: MODELS += [("blend w=0.7 + ESPN 50/50", withE(blend(0.7))), ("shadow + ESPN 50/50 (rank mix)", withE(SHADOW)), ("TODAY + ESPN 50/50", withE(TODAY))]
    P(f"=== RE-MEASURE THE BASE: {int(base.sum()):,} top-150 player-weeks 2019-25, final week dropped, next game pre-book ===")
    P(f"    rows: {n:,}; shadow vs live replica level: shadow/actual {SHADOW[base].sum()/act[base].sum():.3f}, live/actual {TODAY[base].sum()/act[base].sum():.3f}")
    P(f"\n--- 1  LADDER: importance-weighted error vs TODAY (seasons better of 7) | rank rho | pairs right | typical miss | bias ---")
    for lab, p in MODELS:
        d = 100 * (wm(p, base) / wm(TODAY, base) - 1); wins = sum(1 for y in YEARS if wm(p, base & (year == y)) < wm(TODAY, base & (year == y)) - 1e-12); rh, pr = rank_stats(p, base)
        P(f"  {lab:40s} {d:+6.2f}% ({wins}/7) | rho {rh:.4f} | pairs {pr:.2f}% | miss {np.sqrt(ms(p, base)):.3f} | bias {np.mean(p[base] - act[base]):+.2f}")
    P(f"\n--- 2  HEAD TO HEAD: each blend vs the SHADOW ALONE (seasons better of 7) and vs the 09-17 shadow form ---")
    for w in WG[1:-1]:
        p = blend(w); d = 100 * (wm(p, base) / wm(SHADOW, base) - 1); wins = sum(1 for y in YEARS if wm(p, base & (year == y)) < wm(SHADOW, base & (year == y)) - 1e-12)
        P(f"  blend w={w:.1f}: vs shadow {d:+6.2f}% ({wins}/7)")
    d = 100 * (wm(SHADOW, base) / wm(SH_OLD, base) - 1); wins = sum(1 for y in YEARS if wm(SHADOW, base & (year == y)) < wm(SH_OLD, base & (year == y)) - 1e-12)
    P(f"  shadow as wired vs the 09-17 shadow form: {d:+6.2f}% ({wins}/7)")
    P(f"\n--- 3  BEST WEIGHT per cut (grid {WG}), error vs TODAY at that weight, and the shadow-alone / w=0.7 cells ---")
    cuts = (("ALL", np.ones(n, bool)), ("QB", pos == "QB"), ("RB", pos == "RB"), ("WR", pos == "WR"), ("TE", pos == "TE"),
            ("ADP 1-10", adp <= 10), ("ADP 11-30", (adp > 10) & (adp <= 30)), ("ADP 31-60", (adp > 30) & (adp <= 60)), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150", adp > 100),
            ("week 1", wk == 1), ("weeks 2-4", (wk >= 2) & (wk <= 4)), ("weeks 5-9", (wk >= 5) & (wk <= 9)), ("10 to playoffs", (wk >= 10) & ~po), ("FANTASY PLAYOFFS", po),
            ("rookies", X["rookie"]), ("vets, 1-2 games", ~X["rookie"] & (g >= 1) & (g <= 2)), ("vets, 3-6 games", ~X["rookie"] & (g >= 3) & (g <= 6)), ("vets, 7+ games", ~X["rookie"] & (g >= 7)))
    def cellw(w, m):
        p = blend(w); d = 100 * (wm(p, m) / wm(TODAY, m) - 1); wins = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and wm(p, m & (year == y)) < wm(TODAY, m & (year == y)) - 1e-12)
        return d, wins
    for lab, cm in cuts:
        m = base & cm
        if m.sum() < 60: P(f"  {lab:18s} n={int(m.sum())} (too few)"); continue
        best = min(WG, key=lambda w: wm(blend(w), m)); db, wb = cellw(best, m); d1, w1 = cellw(1.0, m); d7, w7 = cellw(0.7, m)
        rh0, _ = rank_stats(TODAY, m); rh1, _ = rank_stats(SHADOW, m); rh7, _ = rank_stats(blend(0.7), m)
        P(f"  {lab:18s} n={int(m.sum()):5d} | best w {best:.1f}: {db:+6.2f}% ({wb}/7) | shadow alone {d1:+6.2f}% ({w1}/7) rho {rh1 - rh0:+.4f} | w=0.7 {d7:+6.2f}% ({w7}/7) rho {rh7 - rh0:+.4f}")
    P(f"\n--- 4  WEIGHT PICKED LEAVE-ONE-SEASON-OUT and FORWARD (2022-25), per position and overall ---")
    def fit(scopes, folds):
        out = TODAY.copy(); picks = [[] for _ in scopes]
        for tr, te in folds:
            trm = np.isin(year, tr)
            for k, sm in enumerate(scopes):
                m = sm & base & trm
                if m.sum() < 60: picks[k].append(None); continue
                w = min(WG, key=lambda w_: wm(blend(w_), m)); picks[k].append(w); sel = sm & (year == te); out[sel] = blend(w)[sel]
        return out, picks
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    for lab, scopes, names in (("one weight for everyone", [np.ones(n, bool)], ("all",)), ("per position", [pos == ps for ps in POS4], POS4),
                               ("per position x ADP <= 60 / 61+", [(pos == ps) & (adp <= 60) for ps in POS4] + [(pos == ps) & (adp > 60) for ps in POS4], tuple(f"{p_}<=60" for p_ in POS4) + tuple(f"{p_}61+" for p_ in POS4))):
        pr, pk = fit(scopes, LOSO); d = 100 * (wm(pr, base) / wm(TODAY, base) - 1); wins = sum(1 for y in YEARS if wm(pr, base & (year == y)) < wm(TODAY, base & (year == y)) - 1e-12); rh, pq = rank_stats(pr, base)
        ds = 100 * (wm(pr, base) / wm(SHADOW, base) - 1)
        P(f"  {lab:34s} LOYO {d:+6.2f}% vs TODAY ({wins}/7), {ds:+.2f}% vs shadow alone | rho {rh:.4f} pairs {pq:.2f}% | picks " + " | ".join(f"{names[k]} {pk[k]}" for k in range(len(scopes))))
        prf, pkf = fit(scopes, FORW); fm = base & (year >= 2022); d = 100 * (wm(prf, fm) / wm(TODAY, fm) - 1); wins = sum(1 for y in FWD if wm(prf, fm & (year == y)) < wm(TODAY, fm & (year == y)) - 1e-12)
        ds = 100 * (wm(prf, fm) / wm(SHADOW, fm) - 1)
        P(f"  {'   forward 2022-25':34s}      {d:+6.2f}% vs TODAY ({wins}/4), {ds:+.2f}% vs shadow alone | picks " + " | ".join(f"{names[k]} {pkf[k]}" for k in range(len(scopes))))
    P(f"\n--- 5  BY SEASON (top 150, final week dropped): error vs TODAY ---")
    for lab, p in (("shadow alone", SHADOW), ("blend w=0.7", blend(0.7)), ("blend w=0.8", blend(0.8))):
        P(f"  {lab:14s} " + "  ".join(f"{y}: {100*(wm(p, base & (year == y))/wm(TODAY, base & (year == y))-1):+.1f}%" for y in YEARS))
    P(f"\n--- 6  LEVEL: actual / projected by position (top 150) ---")
    for ps in POS4:
        m = base & (pos == ps)
        P(f"  {ps}: TODAY {act[m].sum()/TODAY[m].sum():.3f}  shadow {act[m].sum()/SHADOW[m].sum():.3f}  blend .7 {act[m].sum()/blend(0.7)[m].sum():.3f}")
    P("\nNot in either replica: book anchor, pecking dock, banged-up PRIOR lift (all sit on top of the base); shadow's v2.32 competitive-snap read;")
    P("rest-of-season structure (v2.26-28, later weeks only). ESPN mix shown only where the ESPN weekly file has the row.")
    LOG.close()


if __name__ == "__main__":
    main()
