#!/usr/bin/env python3
"""
Two harness tests Jack approved 2026-10-27 (scratch_model_report.md, "Harness replay" section):

 TEST 3  UPSIDE TAIL CALIBRATION - p10/p90 coverage of the engine's distribution by position x ADP band
         (engine sampler replica: backtest_sim_calibration.sim_player gamma draws, sigma = entering-season CV, around the
         engine-parity shadow), 2019-25 top-150 player-weeks, plus 2026 W1-7 from the live locks' own p10/p90.
         If the 31-100 band is under-covered on the top side: smallest fix candidates on that band only -
           (a) upper-tail stretch u (draws above the mean pulled out by u), (b) band sigma multiplier, (c) mean multiplier -
         graded on coverage (toward 10/10), CRPS, pinball, BOOM Brier (P(act >= boom line): QB 25 / RB WR 20 / TE 15 half-PPR),
         with the mean's MAE / rank as the guard; leave-one-season-out pick.
 TEST 4  TEAM-LEVEL OFFENSE DRIFT - after N team games (3 / 4) the team's skill players' actual vs shadow ratio R (season to
         date, or trailing K games) nudges every player on the team: mult = 1 + f (R - 1) x games/(games + s), f .25 / .50,
         s 2 / 4.  House grading (backtest_shadow_next.test rules): LOSO + forward picks, touched rows, whole-board guard,
         rank rho, per-season table.  Default harness 2019-25; SIM_BT_YEARS=2012-2025 for the long one (test 4 only there).
Logs: scratch_model/out/tail_team<TAG>.log
"""
import os, sys, json, pickle
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata, spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import bt_ext as BX
import backtest_shadow_next as SN
import backtest_sim_calibration as cal
OUT = os.path.join(HERE, "scratch_model", "out")
LOG = open(os.path.join(OUT, f"tail_team{BX.TAG}.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + "\n"); LOG.flush()
POS4 = ("QB", "RB", "WR", "TE")
BANDS = (("1-12", 0, 12), ("13-30", 12, 30), ("31-60", 30, 60), ("61-100", 60, 100), ("101-150", 100, 150))
BOOM = {"QB": 25.0, "RB": 20.0, "WR": 20.0, "TE": 15.0}
NS = 1000


def load_X():
    if BX.EXT:
        p = BX.ext_path("X_cache.pkl")
        if os.path.exists(p):
            return pickle.load(open(p, "rb"))
    return SN.setup()


def rho(p, m, year, wk, pos, act):
    groups = defaultdict(list)
    for i in np.where(m)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
    rh = [np.corrcoef(rankdata(act[ix]), rankdata(p[ix]))[0, 1] for ix in (np.array(x) for x in groups.values()) if len(ix) >= 8]
    return float(np.mean(rh)) if rh else np.nan


def metrics(p, m, wt, year, wk, pos, act):
    mae = float(np.average(np.abs(p[m] - act[m]), weights=wt[m]))
    groups = defaultdict(list)
    for i in np.where(m)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
    rh = []; ok = tot = 0
    for ix in groups.values():
        ix = np.array(ix)
        if len(ix) < 8: continue
        a = act[ix]; q = p[ix]
        r = spearmanr(a, q).correlation
        if not np.isnan(r): rh.append(r)
        order = np.argsort(-q)[: max(2, len(ix) // 2)]
        for s in range(len(order)):
            for t in range(s + 1, len(order)):
                x, y_ = order[s], order[t]
                if abs(q[x] - q[y_]) < 1.0 or a[x] == a[y_]: continue
                tot += 1; ok += (q[x] > q[y_]) == (a[x] > a[y_])
    return mae, float(np.mean(rh)) if rh else np.nan, ok / tot if tot else np.nan


# ============================================================================================= TEST 3
def test3(X, SH, wt, base):
    n = X["n"]; act, year, wk, pos, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["adp"], X["name"]
    yrs = sorted(set(int(y) for y in year))
    P("\n" + "=" * 100); P("TEST 3  UPSIDE TAIL CALIBRATION (engine sampler replica around the shadow; sigma = entering-season CV)")
    sig = np.full(n, np.nan); cache = {}
    for i in np.where(base)[0]:
        k = (name[i], pos[i], int(year[i]))
        if k not in cache: cache[k] = cal.sigma_entering(name[i], pos[i], int(year[i]))
        sig[i] = cache[k]
    rng = np.random.default_rng(7); cal.SIMS = NS
    idx = np.where(base)[0]
    # one draw matrix for the whole base (rows x NS), reused by every variant through transforms
    D = np.empty((len(idx), NS))
    for r_, i in enumerate(idx):
        D[r_] = cal.sim_player(rng, float(SH[i]), float(sig[i]), 1, 1.0)[:, 0]
    A = act[idx]; M = SH[idx]; PS = pos[idx]; AD = adp[idx]; YR = year[idx]
    band = np.full(len(idx), "", dtype=object)
    for nm, lo, hi in BANDS: band[(AD > lo) & (AD <= hi)] = nm
    boom = np.array([BOOM[p_] for p_ in PS])
    perm = rng.permutation(NS)

    def score(Dv, Mv, m):
        q10 = np.quantile(Dv[m], 0.1, axis=1); q90 = np.quantile(Dv[m], 0.9, axis=1); y = A[m]
        cov = np.mean((q10 <= y) & (y <= q90)); lo = np.mean(y < q10); hi = np.mean(y > q90)
        crps = np.mean(np.mean(np.abs(Dv[m] - y[:, None]), axis=1) - 0.5 * np.mean(np.abs(Dv[m] - Dv[m][:, perm]), axis=1))
        pin = np.mean(np.maximum(0.1 * (y - q10), 0.9 * (q10 - y)) + np.maximum(0.9 * (y - q90), 0.1 * (q90 - y)))
        pb = np.mean(Dv[m] >= boom[m][:, None], axis=1); yb = (y >= boom[m]).astype(float)
        brier = np.mean((pb - yb) ** 2)
        return dict(cov=100 * cov, lo=100 * lo, hi=100 * hi, crps=crps, pin=pin, brier=brier, pboom=100 * pb.mean(), aboom=100 * yb.mean(),
                    level=y.sum() / Mv[m].sum(), mae=np.mean(np.abs(Mv[m] - y)), n=int(m.sum()))

    def row(lab, r):
        P(f"  {lab:26s} n{r['n']:5d} | p10-p90 {r['cov']:5.1f}% (below {r['lo']:4.1f} / above {r['hi']:4.1f}) | act/mean {r['level']:.3f} | CRPS {r['crps']:.3f} pinball {r['pin']:.3f} | boom P {r['pboom']:4.1f}% real {r['aboom']:4.1f}% Brier {r['brier']:.4f} | MAE {r['mae']:.3f}")
    P(f"\n--- A. coverage by ADP band x position, 2019-25 top-150 ({len(idx):,} rows, {NS} draws each; target 80 / 10 / 10) ---")
    for nm, lo, hi in BANDS:
        P(f"\n ADP {nm}")
        row("ALL", score(D, M, band == nm))
        for ps in POS4:
            m = (band == nm) & (PS == ps)
            if m.sum() >= 60: row(ps, score(D, M, m))
    P("\n--- B. 2026 W1-7 from the live locks' own p10 / p90 (scratch_model/out/bt_rows.csv, top-150) ---")
    bt = pd.read_csv(os.path.join(OUT, "bt_rows.csv")); bt = bt[(bt.adp <= 150) & bt.live_p10.notna()]
    bband = np.full(len(bt), "", dtype=object); ad = bt.adp.values
    for nm, lo, hi in BANDS: bband[(ad > lo) & (ad <= hi)] = nm
    for nm, lo, hi in BANDS:
        m = bband == nm
        for lab, mm in (("ALL", m), *[(ps, m & (bt.pos.values == ps)) for ps in POS4]):
            if mm.sum() < 12: continue
            y = bt.act.values[mm]; p10 = bt.live_p10.values[mm]; p90 = bt.live_p90.values[mm]; mu = bt.LIVE.values[mm]
            P(f"  ADP {nm:8s} {lab:4s} n{int(mm.sum()):4d} | p10-p90 {100 * np.mean((p10 <= y) & (y <= p90)):5.1f}% (below {100 * np.mean(y < p10):4.1f} / above {100 * np.mean(y > p90):4.1f}) | act/mean {y.sum() / mu.sum():.3f} bias {np.mean(mu - y):+.2f} | boom real {100 * np.mean(y >= np.array([BOOM[q] for q in bt.pos.values[mm]])):.1f}%")
    # ---- fixes on the 31-100 band
    P("\n--- C. fix candidates on ADP 31-100 only (other rows untouched); LOSO pick on CRPS, guard = coverage / boom Brier / MAE ---")
    tgt = (band == "31-60") | (band == "61-100")
    def variant(kind, v):
        Dv = D.copy(); Mv = M.copy()
        if kind == "stretch":
            up = Dv[tgt] > M[tgt][:, None]
            Dv[tgt] = np.where(up, M[tgt][:, None] + (Dv[tgt] - M[tgt][:, None]) * v, Dv[tgt])
        elif kind == "sigma":
            Dv[tgt] = M[tgt][:, None] + (Dv[tgt] - M[tgt][:, None]) * v; Dv = np.maximum(Dv, 0.0)
        elif kind == "mean":
            Dv[tgt] = Dv[tgt] * v; Mv[tgt] = Mv[tgt] * v
        return Dv, Mv
    fam = {"as is": (D, M)}
    for v in (1.10, 1.20, 1.30): fam[f"upper stretch x{v:.2f}"] = variant("stretch", v)
    for v in (1.10, 1.20): fam[f"band sigma x{v:.2f}"] = variant("sigma", v)
    for v in (1.02, 1.04): fam[f"band mean x{v:.2f}"] = variant("mean", v)
    P("\n pooled, ADP 31-100 rows:")
    for lab, (Dv, Mv) in fam.items(): row(lab, score(Dv, Mv, tgt))
    P("\n pooled, ADP 31-100 rows, top side only = WR + TE (the under-covered cells if any):")
    for lab, (Dv, Mv) in fam.items(): row(lab, score(Dv, Mv, tgt & np.isin(PS, ["WR", "TE"])))
    # LOSO pick on CRPS per season
    def crps_of(Dv, m):
        return float(np.mean(np.mean(np.abs(Dv[m] - A[m][:, None]), axis=1) - 0.5 * np.mean(np.abs(Dv[m] - Dv[m][:, perm]), axis=1)))
    names = list(fam); picks = []; wins = 0
    P("\n leave-one-season-out on CRPS (31-100 rows): season -> pick, CRPS as-is vs pick, coverage above p90 as-is vs pick")
    for y in yrs:
        tr = tgt & (YR != y); te = tgt & (YR == y)
        k = min(names, key=lambda k_: crps_of(fam[k_][0], tr)); picks.append(k)
        c0 = crps_of(D, te); c1 = crps_of(fam[k][0], te); wins += c1 < c0 - 1e-9
        s0 = score(D, M, te); s1 = score(fam[k][0], fam[k][1], te)
        P(f"   {y}: {k:22s} CRPS {c0:.3f} -> {c1:.3f}  above p90 {s0['hi']:.1f} -> {s1['hi']:.1f}  boom Brier {s0['brier']:.4f} -> {s1['brier']:.4f}")
    P(f"   seasons CRPS better {wins}/{len(yrs)}  picks {picks}")
    # guard for the mean variants: MAE / rank on the whole top-150 board
    P("\n mean-multiplier guard (whole top-150 board, weighted MAE / rank rho):")
    SHv = SH.copy(); base_idx = idx
    for v in (1.0, 1.02, 1.04):
        q = SH.copy(); q[base_idx[tgt]] = q[base_idx[tgt]] * v
        P(f"   band mean x{v:.2f}: MAE {np.average(np.abs(q[base] - act[base]), weights=wt[base]):.4f}  rank rho {rho(q, base, year, wk, pos, act):.4f}  31-100 bias {np.mean(q[base_idx[tgt]] - act[base_idx[tgt]]):+.3f}")


# ============================================================================================= TEST 4
def test4(X, SH, wt, base, allr):
    n = X["n"]; act, year, wk, pos, adp, team = X["act"], X["year"], X["wk"], X["pos"], X["adp"], X["team"]
    yrs = sorted(set(int(y) for y in year)); FWD = list(BX.FWD)
    finw = np.where(year <= 2020, 17, 18); final = wk == finw
    P("\n" + "=" * 100); P(f"TEST 4  TEAM-LEVEL OFFENSE DRIFT  ({BX.describe()})")
    # team-week residual table from the harness rows themselves (SH >= 3 rows, all positions)
    tw = defaultdict(lambda: [0.0, 0.0])
    use = (SH >= 3) & ~np.isnan(act)
    for i in np.where(use)[0]:
        k = (int(year[i]), team[i], int(wk[i])); tw[k][0] += act[i]; tw[k][1] += SH[i]
    # as-of ratio per (year, team, wk): season to date (sum act / sum SH over weeks < wk) and trailing K team games
    def ratios(K=None):
        R = np.ones(n); G = np.zeros(n)
        cache = {}
        for i in range(n):
            k = (int(year[i]), team[i], int(wk[i]))
            if k not in cache:
                prev = sorted(((w, v) for (y, t, w), v in tw.items() if y == k[0] and t == k[1] and w < k[2]), key=lambda x: x[0])
                if K: prev = prev[-K:]
                sa = sum(v[0] for _, v in prev); ss = sum(v[1] for _, v in prev)
                cache[k] = (sa / ss if ss > 0 else 1.0, len(prev))
            R[i], G[i] = cache[k]
        return R, G
    Rall, Gall = ratios(None); R3, G3 = ratios(3); R4, G4 = ratios(4)
    m_t = base
    P(f"  persistence check (top-150 rows): corr(team ratio to date, this week's act/SH) = {np.corrcoef(Rall[m_t & (Gall >= 3)], (act / SH)[m_t & (Gall >= 3)])[0, 1]:+.3f} (3+ games); "
      f"trailing-3 {np.corrcoef(R3[m_t & (G3 >= 3)], (act / SH)[m_t & (G3 >= 3)])[0, 1]:+.3f}; trailing-4 {np.corrcoef(R4[m_t & (G4 >= 4)], (act / SH)[m_t & (G4 >= 4)])[0, 1]:+.3f}")
    for lo, hi in ((0, .85), (.85, .95), (.95, 1.05), (1.05, 1.15), (1.15, 9)):
        m = m_t & (Gall >= 3) & (Rall >= lo) & (Rall < hi)
        if m.sum(): P(f"    team ratio to date {lo:.2f}-{hi:.2f}: n {int(m.sum()):5d}  next-week act/SH {act[m].sum() / SH[m].sum():.3f}")
    fam = {"shadow": SH}
    for Nmin, Rv, Gv, wlab in ((3, Rall, Gall, "to date"), (4, Rall, Gall, "to date"), (3, R3, G3, "trail3"), (4, R4, G4, "trail4")):
        for f in (0.25, 0.50):
            for s in (2.0, 4.0):
                on = Gv >= Nmin
                mult = np.where(on, 1 + f * (Rv - 1) * Gv / (Gv + s), 1.0)
                fam[f"N{Nmin} {wlab} f{f:.2f} s{s:.0f}"] = SH * np.clip(mult, 0.8, 1.25)
    names = list(fam); b = SH
    touched = np.zeros(n, bool)
    for k in names[1:]: touched |= np.abs(fam[k] - b) > 1e-9
    tm = touched & allr
    wm = lambda q, mm: float(np.average((q[mm] - act[mm]) ** 2, weights=wt[mm])) if mm.any() else np.nan
    ms = lambda q, mm: float(np.mean((q[mm] - act[mm]) ** 2)) if mm.any() else np.nan
    pick = lambda trs: min(names, key=lambda k: ms(fam[k], tm & np.isin(year, trs)))
    def run(folds):
        wins = ny = 0; picks = []; pred = b.copy()
        for trs, te in folds:
            k = pick(trs); picks.append(k); m = year == te; pred[m] = fam[k][m]
            if (tm & m).sum() >= 8:
                ny += 1; wins += ms(fam[k], tm & m) < ms(b, tm & m) - 1e-12
        tem = np.isin(year, [te for _, te in folds])
        return pred, 100 * (wm(pred, base & tem) / wm(b, base & tem) - 1), 100 * (ms(pred, tm & tem) / ms(b, tm & tem) - 1), wins, picks, ny
    lo = run([([y for y in yrs if y != t], t) for t in yrs]); fw = run([([y for y in yrs if y < t], t) for t in FWD])
    best = pick(yrs); need = max(5, lo[5] - 2)
    ok = best != names[0] and lo[2] < -0.3 and lo[3] >= need and fw[2] < 0 and fw[3] >= 3 and lo[1] <= 0.02
    P(f"\n  rows touched {int(tm.sum()):,} ({int((tm & (adp <= 150)).sum()):,} top-150); actual / shadow on them {act[tm].sum() / b[tm].sum():.3f}")
    P("  pooled touched rows: " + "  ".join(f"{k}: {100 * (ms(fam[k], tm) / ms(b, tm) - 1):+.2f}%" for k in names[1:]))
    P(f"  LEAVE-ONE-SEASON-OUT  touched {lo[2]:+.2f}%  seasons better {lo[3]}/{lo[5]}  | whole board top-150 wtd {lo[1]:+.2f}%  rank rho {rho(lo[0], base, year, wk, pos, act) - rho(b, base, year, wk, pos, act):+.4f}  | picks {lo[4]}")
    P(f"  FORWARD {FWD[0]}-{FWD[-1]}       touched {fw[2]:+.2f}%  seasons better {fw[3]}/{fw[5]}  | whole board top-150 wtd {fw[1]:+.2f}%  | picks {fw[4]}")
    P(f"  -> {'PASS: ' + best if ok else 'FAIL'}  (bar: LOSO {need}+/{lo[5]} and forward 3+/{fw[5]}, touched -0.3%+, guard <= +0.02%)")
    # per-season table for the four headline settings
    show = ["N3 to date f0.25 s2", "N3 to date f0.50 s2", "N4 to date f0.25 s4", "N4 trail4 f0.50 s4"]
    P("\n  per season, top-150 rows, final week out: wtd MAE / Spearman / pair acc")
    P("  | season | n | shadow | " + " | ".join(show) + " |"); P("  |" + "---|" * (len(show) + 3))
    wins = {k: [0, 0, 0] for k in show}; ny = 0
    for y in yrs:
        m = base & (year == y)
        if m.sum() < 100: continue
        ny += 1; rb = metrics(b, m, wt, year, wk, pos, act); cells = [f"{rb[0]:.3f} / {rb[1]:.3f} / {rb[2]:.3f}"]
        for k in show:
            r = metrics(fam[k], m, wt, year, wk, pos, act)
            wins[k][0] += r[0] < rb[0] - 1e-9; wins[k][1] += r[1] > rb[1] + 1e-9; wins[k][2] += r[2] > rb[2] + 1e-9
            cells.append(f"{r[0]:.3f} / {r[1]:.3f} / {r[2]:.3f}")
        P(f"  | {y} | {int(m.sum())} | " + " | ".join(cells) + " |")
    P("  | wins (MAE/rho/pair) | | | " + " | ".join(f"{wins[k][0]}/{wins[k][1]}/{wins[k][2]} of {ny}" for k in show) + " |")
    # by position, touched rows, the two main settings
    P("\n  by position (touched rows, pooled error vs shadow): " + "; ".join(
        f"{ps}: " + ", ".join(f"{k.split(' s')[0]} {100 * (ms(fam[k], tm & (pos == ps)) / ms(b, tm & (pos == ps)) - 1):+.2f}%" for k in show[:2]) for ps in POS4))


def main():
    X = load_X(); n = X["n"]; F = X["F"]
    act, year, wk, pos, adp = X["act"], X["year"], X["wk"], X["pos"], X["adp"]
    SH = SN.shadow(X)
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    base = top150 & ~final & (SH >= 3); allr = ~final & (SH >= 3)
    P(f"=== tail + team tests  {BX.describe()}  rows {n:,}  top-150 graded {int(base.sum()):,} ===")
    if not BX.EXT and not os.environ.get("SKIP_TEST3"):
        test3(X, SH, wt, base)
    test4(X, SH, wt, base, allr)
    P(f"\nlog: {LOG.name}")


if __name__ == "__main__":
    main()
