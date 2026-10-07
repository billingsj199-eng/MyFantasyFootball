#!/usr/bin/env python3
"""
SOLVE THE SHADOW ALONE (Jack 2026-10-07: "can we try to just solve our own shadow no blend?").  The player-type read
(backtest_base_segments.py) found where the live Clay blend still beats the Clay-free shadow on the next game:
tight ends (every cut), players listed Questionable (the shadow has no injury dock), players running hot vs their
prior (the shadow chases), second-year QBs, RB committees (30-55% of carries). This ladder tests a fix for each on the
shadow itself, stacks the ones that pass, and grades the stacked shadow against the live blend and the 70/30 blend.

Rows / models: backtest_base_remeasure (2019-25, next game pre-book, shadow as wired today, live as wired today).
Grading (house rules): touched rows, top-150 importance-weighted squared error vs the shadow as wired, seasons better of
7; whole-board guard; setting picked LEAVE-ONE-SEASON-OUT and FORWARD (2022-25). Ship bar: LOYO better in 5+ of 7 and
forward 3+ of 4 on the touched rows, whole board not worse. Log shadow_solo.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
SN = BR.SN; NW = BR.NW; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "shadow_solo.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def shadow_parts(X):
    """the shadow as wired, broken into prior / evidence / weight / chain so the pieces can be changed"""
    F = X["F"]; n = X["n"]; pos, g, wk, adp = X["pos"], X["g"], X["wk"], X["adp"]
    finw = np.where(X["year"] <= 2020, 17, 18); final = wk == finw
    SH0 = SN.shadow(X); allr = ~final & (SH0 >= 3)
    base_lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
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
    car_sh = np.where(has, C["car_sh"].values[np.maximum(idx, 0)], np.nan).astype(float)
    L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet")); lk = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(L.year, L.pid, L.wk)) if isinstance(b, str)}
    lidx = np.array([lk.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); lhas = lidx >= 0
    cond = np.where(lhas, L["cond_mult"].values[np.maximum(lidx, 0)], 1.0).astype(float); cond = np.nan_to_num(cond, nan=1.0)
    wx = np.where(lhas, L["weather_mult"].values[np.maximum(lidx, 0)], 1.0).astype(float); wx = np.nan_to_num(wx, nan=1.0)
    rep_q = np.where(has, C["rep_q"].values[np.maximum(idx, 0)], 0.0).astype(float) == 1
    Pw = F["Pvec"] * np.where((pos == "WR") & (g == 1), 5.0, 1.0)
    Pw = Pw * np.where(X["rookie"] & (pos == "RB"), 1.6, np.where(X["rookie"] & (pos == "TE"), 2.5, 1.0))
    # multiplicative chain after the rate (everything in shadow_current after the blend)
    chain = X["layers"].copy()
    for gi, m_ in enumerate([0.7, 0.8], start=1): chain = np.where(F["buried_rk"] & (wk == gi), chain * m_, chain)
    chain = np.where(F["on"], chain * np.power(F["pm"], 0.75), chain)
    chain = np.where(pos == "QB", chain * np.exp(0.03 * X["z"]), chain)
    chain = np.where((pos == "WR") & X["qbo"], chain * np.where(adp <= 60, 0.85, 0.95), chain)
    for ps_ in ("RB", "TE"): chain = np.where(pos == ps_, chain * smx, chain)
    chain = np.where(np.isin(pos, ("WR", "TE")), chain * np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4), chain)
    chain = np.where((pos == "QB") & X["mover"], chain * 0.90, chain)
    chain = np.where(pos == "QB", chain * (1 - 0.75 * low), chain)
    chain = np.where((pos == "WR") & X["rookie"] & (g >= 2) & (g <= 5), chain * 0.90, chain)
    chain = np.where((pos == "RB") & (g >= 2) & (g <= 5) & (car_sh < 0.30), chain * 0.90, chain)
    ev = base_lam * X["xf"] + (1 - base_lam) * X["ppg_v"]
    return dict(prior=X["prior"].copy(), ev=ev, Pw=Pw, chain=chain, cond=cond, wx=wx, rep_q=rep_q, car_sh=car_sh, market=F["adp_curve"].copy(), final=final)


def build(S, g, prior=None, ev=None, Pw=None, mult=None):
    prior = S["prior"] if prior is None else prior; ev = S["ev"] if ev is None else ev; Pw = S["Pw"] if Pw is None else Pw
    rate = (Pw * prior + g * ev) / np.maximum(Pw + g, 1e-9)
    out = rate * S["chain"]
    if mult is not None: out = out * mult
    return np.maximum(0.0, out)


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    TODAY, LV = BR.live_today(X); SHADOW_REF, _ = BR.shadow_current(X)
    S = shadow_parts(X); SHADOW = build(S, g)
    top150 = adp <= 150; base = top150 & ~S["final"] & ~LV["inh"]
    P(f"=== SOLVE THE SHADOW ALONE: {int(base.sum()):,} top-150 player-weeks, next game pre-book, 2019-25 ===")
    P(f"    rebuild check: parts-built shadow vs shadow_current max |diff| {np.max(np.abs(SHADOW - SHADOW_REF)[base]):.4f}")
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    wm = lambda q, mm: float(np.average((q[mm] - act[mm]) ** 2, weights=wt[mm])) if mm.any() else np.nan
    def rho(p, m):
        groups = defaultdict(list)
        for i in np.where(m)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
        rh = [np.corrcoef(rankdata(act[ix]), rankdata(p[ix]))[0, 1] for ix in (np.array(v) for v in groups.values()) if len(ix) >= 8]
        return float(np.mean(rh)) if rh else np.nan
    prior0, ev0, Pw0 = S["prior"], S["ev"], S["Pw"]
    hot = np.where(prior0 > 1, ev0 / prior0, 1.0); hotm = (g >= 3) & (hot >= 1.25); coldm = (g >= 3) & (hot <= 0.8)
    mkt = S["market"]; hasm = ~np.isnan(mkt)
    yr2qb = (pos == "QB") & (np.array(X["A"]["exp"], float) == 1)
    comm = (pos == "RB") & (S["car_sh"] >= 0.30) & (S["car_sh"] < 0.55)
    # --------------------------------------------------------------- the ladder
    def shrink(k, m):   # evidence pulled toward the prior on rows m
        return np.where(m, prior0 + k * (ev0 - prior0), ev0)
    FAMS = [
        ("A  injury chain: x banged-up dock (Questionable / Doubtful, the live cond_mult)", "cur", {"off": None, "x cond": dict(mult=S["cond"])}),
        ("A2 weather multiplier (live)", "cur", {"off": None, "x weather": dict(mult=S["wx"])}),
        ("B  hot streak (3+ games, evidence >= 1.25x prior): evidence pulled toward the prior, WR", "cur",
         {"off": None, **{f"k {k}": dict(ev=shrink(k, hotm & (pos == "WR"))) for k in (0.6, 0.75, 0.9)}}),
        ("B  hot streak: TE", "cur", {"off": None, **{f"k {k}": dict(ev=shrink(k, hotm & (pos == "TE"))) for k in (0.6, 0.75, 0.9)}}),
        ("B  hot streak: RB", "cur", {"off": None, **{f"k {k}": dict(ev=shrink(k, hotm & (pos == "RB"))) for k in (0.6, 0.75, 0.9)}}),
        ("B  hot streak: QB", "cur", {"off": None, **{f"k {k}": dict(ev=shrink(k, hotm & (pos == "QB"))) for k in (0.6, 0.75, 0.9)}}),
        ("B2 cold streak (evidence <= .8x prior): evidence pulled toward the prior, WR (check only)", "cur",
         {"off": None, **{f"k {k}": dict(ev=shrink(k, coldm & (pos == "WR"))) for k in (0.75, 0.9)}}),
        ("C1 TE prior weight (shadow P 8 today)", "cur", {"off": None, **{f"x{k}": dict(Pw=np.where(pos == "TE", Pw0 * k, Pw0)) for k in (0.6, 1.5, 2.0, 3.0)}}),
        ("C2 TE level", "cur", {"off": None, **{f"x{k}": dict(mult=np.where(pos == "TE", k, 1.0)) for k in (1.03, 1.05, 1.08)}}),
        ("C3 TE prior pulled toward the market (ADP curve) where it exists", "cur",
         {"off": None, **{f"w {w}": dict(prior=np.where((pos == "TE") & hasm, (1 - w) * prior0 + w * np.nan_to_num(mkt), prior0)) for w in (0.3, 0.5, 0.7)}}),
        ("C4 TE prior pulled toward the market AND hot-streak shrink k .75", "cur",
         {"off": None, **{f"w {w}": dict(prior=np.where((pos == "TE") & hasm, (1 - w) * prior0 + w * np.nan_to_num(mkt), prior0), ev=shrink(0.75, hotm & (pos == "TE"))) for w in (0.3, 0.5)}}),
        ("D1 second-year QB: prior pulled toward the market", "cur",
         {"off": None, **{f"w {w}": dict(prior=np.where(yr2qb & hasm, (1 - w) * prior0 + w * np.nan_to_num(mkt), prior0)) for w in (0.5, 0.75)}}),
        ("D2 second-year QB: prior weight", "cur", {"off": None, **{f"x{k}": dict(Pw=np.where(yr2qb, Pw0 * k, Pw0)) for k in (0.5, 1.5, 2.0)}}),
        ("E  RB committee (30-55% of carries): level", "cur", {"off": None, **{f"x{k}": dict(mult=np.where(comm, k, 1.0)) for k in (1.03, 1.05, 1.08)}}),
        ("F  WR prior pulled toward the market (ADP curve)", "cur", {"off": None, **{f"w {w}": dict(prior=np.where((pos == "WR") & hasm, (1 - w) * prior0 + w * np.nan_to_num(mkt), prior0)) for w in (0.3, 0.5)}}),
        ("F2 RB prior pulled toward the market (ADP curve)", "cur", {"off": None, **{f"w {w}": dict(prior=np.where((pos == "RB") & hasm, (1 - w) * prior0 + w * np.nan_to_num(mkt), prior0)) for w in (0.3, 0.5)}}),
    ]
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    passed = []
    state = dict(prior=prior0.copy(), ev=ev0.copy(), Pw=Pw0.copy(), mult=np.ones(n))
    def cur(**kw):
        d = dict(prior=state["prior"], ev=state["ev"], Pw=state["Pw"], mult=state["mult"])
        for k, v in kw.items():
            d[k] = (d["mult"] * v) if k == "mult" else v
        return build(S, g, **d)
    P("\n--- LADDER: each fix on the shadow as it stands (earlier passes stacked); touched rows weighted error vs the current shadow ---")
    for title, _, fam in FAMS:
        names = list(fam); b = cur()
        preds = {k: (b if v is None else cur(**v)) for k, v in fam.items()}
        touched = np.zeros(n, bool)
        for k in names[1:]: touched |= np.abs(preds[k] - b) > 1e-9
        tm = touched & base
        if tm.sum() < 60: P(f"\n  {title}: only {int(tm.sum())} rows touched - skipped"); continue
        pick = lambda yrs, mm: min(names, key=lambda k: wm(preds[k], mm & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = b.copy()
            for tr_, te in folds:
                k = pick(tr_, tm); picks.append(k); m = year == te; pr[m] = preds[k][m]; wins += wm(preds[k], tm & m) < wm(b, tm & m) - 1e-12
            tem = np.isin(year, [te for _, te in folds])
            return pr, 100 * (wm(pr, tm & tem) / wm(b, tm & tem) - 1), 100 * (wm(pr, base & tem) / wm(b, base & tem) - 1), wins, picks
        lo = run(LOSO); fw = run(FORW)
        best = pick(YEARS, tm)
        fixed = "  ".join(f"{k}: {100*(wm(preds[k], tm)/wm(b, tm)-1):+.2f}% ({sum(1 for y in YEARS if (tm & (year == y)).sum() >= 8 and wm(preds[k], tm & (year == y)) < wm(b, tm & (year == y)) - 1e-12)}/7)" for k in names[1:])
        okk = best != "off" and lo[1] < -0.3 and lo[3] >= 5 and fw[1] < 0 and fw[3] >= 3 and lo[2] <= 0.02
        P(f"\n  {title}")
        P(f"    rows {int(tm.sum()):,} | actual / shadow on them {act[tm].sum()/b[tm].sum():.3f} | vs live blend on them {100*(wm(b, tm)/wm(TODAY, tm)-1):+.2f}%")
        P(f"    fixed: {fixed}")
        P(f"    LOYO {lo[1]:+.2f}% {lo[3]}/7 | board {lo[2]:+.3f}% | picks {lo[4]}")
        P(f"    FWD  {fw[1]:+.2f}% {fw[3]}/4 | board {fw[2]:+.3f}% | picks {fw[4]}")
        P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
        if okk:
            v = fam[best]
            for k, val in v.items(): state[k] = (state["mult"] * val) if k == "mult" else val
            passed.append((title.split(":")[0].strip(), best))
    # --------------------------------------------------------------- the stacked shadow
    FINAL = cur()
    P("\n=== STACKED SHADOW (fixes that passed: " + "; ".join(f"{t} {b}" for t, b in passed) + ") ===")
    def line(lab, p, m, ref):
        d = 100 * (wm(p, m) / wm(ref, m) - 1); wins = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and wm(p, m & (year == y)) < wm(ref, m & (year == y)) - 1e-12)
        return f"{d:+6.2f}% ({wins}/7)"
    blend = 0.7 * SHADOW + 0.3 * TODAY; blendF = 0.7 * FINAL + 0.3 * TODAY
    P(f"    {'cut':34s} {'n':>5s} | {'shadow wired vs live':>20s} | {'stacked shadow vs live':>22s} | {'stacked vs shadow wired':>23s} | {'70/30 blend vs live':>19s} | {'70/30 w/ stacked vs live':>24s} | rank rho live/shadow/stacked")
    cuts = [("ALL top 150", np.ones(n, bool))] + [(ps, pos == ps) for ps in POS4] + [("listed Questionable", S["rep_q"]), ("running hot (ev >= 1.25x prior)", hotm), ("second-year QB", yr2qb), ("RB committee 30-55%", comm),
            ("ADP 1-30", adp <= 30), ("ADP 31-60", (adp > 30) & (adp <= 60)), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150", adp > 100), ("rookies", X["rookie"]), ("weeks 1-4", wk <= 4), ("weeks 5+", wk >= 5)]
    for lab, cm in cuts:
        m = base & cm
        if m.sum() < 60: continue
        P(f"    {lab:34s} {int(m.sum()):5d} | {line(lab, SHADOW, m, TODAY):>20s} | {line(lab, FINAL, m, TODAY):>22s} | {line(lab, FINAL, m, SHADOW):>23s} | {line(lab, blend, m, TODAY):>19s} | {line(lab, blendF, m, TODAY):>24s} | {rho(TODAY, m):.3f} / {rho(SHADOW, m):.3f} / {rho(FINAL, m):.3f}")
    P("\n    by season, stacked shadow vs live: " + "  ".join(f"{y}: {100*(wm(FINAL, base & (year == y))/wm(TODAY, base & (year == y))-1):+.1f}%" for y in YEARS))
    P("    by season, stacked shadow vs shadow wired: " + "  ".join(f"{y}: {100*(wm(FINAL, base & (year == y))/wm(SHADOW, base & (year == y))-1):+.1f}%" for y in YEARS))
    P(f"    level: actual / stacked shadow by position: " + "  ".join(f"{ps} {act[base & (pos == ps)].sum()/FINAL[base & (pos == ps)].sum():.3f}" for ps in POS4))
    P("\nNot replicable here (sit on top of either base): book anchor, pecking dock, banged-up prior lift; shadow v2.32 competitive-snap read; rest-of-season structure.")
    LOG.close()


if __name__ == "__main__":
    main()
