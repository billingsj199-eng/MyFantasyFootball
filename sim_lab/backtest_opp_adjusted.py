#!/usr/bin/env python3
"""
OPPONENT-ADJUSTED POINTS ALLOWED (Jack 2026-10-08: "can we maybe adjust by how good the opponents were").
The wired opponent factor (engine jsOppMult, harness layers = veg x fpa) = 1 + .25 x (raw points allowed per game to the
position / league, clip .8-1.25) x min(1, games / 8) - RAW: a defense that faced Chase, Jefferson and Nacua looks bad.
Here each past game's points allowed is divided by how productive THAT offense is at the position against everyone else
(its per-game points at the position in its other games so far, shrunk 3 games toward the league), then averaged:
  RAW   wired (reference)
  ADJ e .25 / .35 / .5    adjusted ratio, same trust ramp
  ADJ+P e .25 / .35       adjusted ratio blended with LAST season's adjusted ratio for the early weeks (Clay-free prior;
                          the live engine still blends Clay's unit grades there)
Swapped into the honest shadow replica (SH / fpa_raw x fpa_new); LOYO + forward vs the wired factor, bar 5/7 + 3/4 and
< -0.3% on the rows, board guard; ADP bands cubed; rank line. Log opp_adjusted.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import backtest_sim_calibration as cal
from backtest_snap_defense import OPP_ALIAS
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "opp_adjusted.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
TM_ALIAS = {"ARZ": "ARI", "WSH": "WAS", "JAC": "JAX", "LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "HST": "HOU", "BLT": "BAL", "CLV": "CLE"}


def build():
    allowed = defaultdict(lambda: defaultdict(float)); scored = defaultdict(lambda: defaultdict(float)); offOf = {}
    for recs in cal.WEEKLY.values():
        for rec in recs:
            pos = rec.get("pos")
            if pos not in POS4: continue
            for y, rows in rec.get("seasons", {}).items():
                Y = int(y)
                if Y < 2018: continue
                inferred = None
                for w in rows:
                    if not cal.played(w) or not w.get("opp"): continue
                    d = OPP_ALIAS.get(w["opp"], w["opp"]); wk = int(w["wk"]); f = w.get("fpts") or 0
                    tm = w.get("tm"); tm = TM_ALIAS.get(tm, tm) if tm else None
                    if not tm:
                        if inferred is None: inferred = cal.infer_team(rec, Y) or ""
                        tm = TM_ALIAS.get(inferred, inferred)
                    allowed[(Y, d, pos)][wk] += f
                    if tm:
                        tm = OPP_ALIAS.get(tm, tm); scored[(Y, tm, pos)][wk] += f; offOf[(Y, d, wk)] = tm
    lg = {}
    for (Y, d, pos), wks in allowed.items():
        if len(wks) >= 10: lg.setdefault((Y, pos), []).append(np.mean(list(wks.values())))
    lg = {k: float(np.mean(v)) for k, v in lg.items()}
    return allowed, scored, offOf, lg


def main():
    allowed, scored, offOf, lg = build()
    def ratios(Y, d, pos, wk, adjust):
        cur = allowed.get((Y, d, pos), {}); past = [w for w in cur if w < wk]
        L = lg.get((Y, pos))
        if not past or not L: return None, 0
        vals = []
        for w in past:
            a = cur[w]
            if adjust:
                o = offOf.get((Y, d, w)); oq = 1.0
                if o:
                    og = [v for w2, v in scored.get((Y, o, pos), {}).items() if w2 < wk and w2 != w]
                    oq = (np.sum(og) / L + 3.0) / (len(og) + 3.0) if og else 1.0
                a = a / max(oq, 0.4)
            vals.append(a)
        return float(np.mean(vals)) / L, len(past)
    def season_ratio(Y, d, pos, adjust):
        r, n_ = ratios(Y, d, pos, 19, adjust)
        return r if n_ >= 10 else None
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["adp"], X["name"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & (adpx <= 150)].mean()
    wt2 = np.maximum(0.05, lv) ** 2; wt3 = np.maximum(0.05, lv) ** 3
    TODAY, LV = BR.live_today(X); SH, _ = BR.shadow_current(X)
    base = (adpx <= 150) & ~final & ~LV["inh"] & (SH >= 3)
    # opponent per row from the context features
    import pandas as pd
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = X["A"]["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)])
    opp = np.array([C["opp"].values[j] if j >= 0 else None for j in idx], dtype=object)
    raw = np.full(n, np.nan); adj = np.full(n, np.nan); gpast = np.zeros(n); prior = np.full(n, np.nan)
    pcache = {}
    for i in np.where(base)[0]:
        if opp[i] is None: continue
        Y, d, p_, w_ = int(year[i]), OPP_ALIAS.get(opp[i], opp[i]), pos[i], int(wk[i])
        r0, g0 = ratios(Y, d, p_, w_, False); r1, _ = ratios(Y, d, p_, w_, True)
        if r0 is None: continue
        raw[i] = r0; adj[i] = r1; gpast[i] = g0
        k = (Y - 1, d, p_)
        if k not in pcache: pcache[k] = season_ratio(Y - 1, d, p_, True)
        if pcache[k] is not None: prior[i] = pcache[k]
    rows = base & ~np.isnan(raw)
    trust = np.minimum(1.0, gpast / 8.0)
    f_raw = np.where(rows, 1 + 0.25 * (np.clip(raw, 0.8, 1.25) - 1) * trust, 1.0)
    P(f"=== OPPONENT-ADJUSTED POINTS ALLOWED: {int(rows.sum()):,} board rows with a defense read | corr raw vs adjusted ratio {np.corrcoef(raw[rows], adj[rows])[0,1]:.2f} | mean |adj - raw| {np.mean(np.abs(adj[rows]-raw[rows])):.3f} ===")
    # does the adjusted ratio predict the defense better? defense rest-of-season (weeks > wk) raw ratio vs each read, at week 5
    for wk0 in (5, 9):
        a_, b_, c_ = [], [], []
        for (Y, d, p_), cur in allowed.items():
            if Y < 2019 or Y > 2025 or len(cur) < 12 or not lg.get((Y, p_)): continue
            r0, g0 = ratios(Y, d, p_, wk0, False); r1, _ = ratios(Y, d, p_, wk0, True)
            fut = [cur[w] for w in cur if w >= wk0]
            if r0 is None or len(fut) < 5: continue
            # future adjusted too (what the defense IS, net of opponents)
            a_.append(r0); b_.append(r1); c_.append(np.mean(fut) / lg[(Y, p_)])
        a_, b_, c_ = map(np.array, (a_, b_, c_))
        P(f"  defense read after {wk0 - 1} games -> rest of season points allowed: raw r {np.corrcoef(a_, c_)[0,1]:+.3f} | adjusted r {np.corrcoef(b_, c_)[0,1]:+.3f} (n{len(a_)})")
    preds = {"off": SH}
    def fnew(ratio, e, use_prior=False):
        r = np.clip(ratio, 0.75, 1.33)
        if use_prior:
            pr = np.where(np.isnan(prior), 1.0, np.clip(prior, 0.75, 1.33)); r = trust * r + (1 - trust) * pr; t = 1.0
        else: t = trust
        return np.where(rows, 1 + e * (r - 1) * t, 1.0)
    for e in (0.25, 0.35, 0.5):
        preds[f"ADJ e {e}"] = SH / f_raw * fnew(adj, e)
    for e in (0.25, 0.35):
        preds[f"ADJ+P e {e}"] = SH / f_raw * fnew(adj, e, True)
    preds["RAW e .35"] = SH / f_raw * fnew(raw, 0.35)
    w2 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt2[m])) if m.any() else np.nan
    w3 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt3[m])) if m.any() else np.nan
    m = rows; b0 = SH; t100 = base & (adpx <= 100)
    P("\n  fixed vs the wired raw factor (rows squared | seasons better | top-100 cubed | by position | bands cubed):")
    for kk, p in preds.items():
        if kk == "off": continue
        bands = " ".join(f"{lab}:{100*(w3(p, base & bm)/w3(b0, base & bm)-1):+.2f}" for lab, bm in (("1-12", adpx <= 12), ("13-30", (adpx > 12) & (adpx <= 30)), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100))))
        bp = " ".join(f"{ps}:{100*(w2(p, m & (pos == ps))/w2(b0, m & (pos == ps))-1):+.2f}" for ps in POS4)
        P(f"    {kk:14s} {100*(w2(p, m)/w2(b0, m)-1):+.2f}% ({sum(1 for y in YEARS if w2(p, m & (year == y)) < w2(b0, m & (year == y)) - 1e-12)}/7) | top-100 {100*(w3(p, t100)/w3(b0, t100)-1):+.3f}% | {bp} | {bands}")
    P("  " + RG.rank_line(preds, m, act, year, wk, pos))
    names = list(preds); pick = lambda yrs: min(names, key=lambda kk: w2(preds[kk], m & np.isin(year, yrs)))
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    def run(folds):
        wins = 0; picks = []; pr = b0.copy()
        for tr_, te in folds:
            kk = pick(tr_); picks.append(kk); mx = year == te; pr[mx] = preds[kk][mx]; wins += w2(preds[kk], m & mx) < w2(b0, m & mx) - 1e-12
        tem = np.isin(year, [te for _, te in folds]); return 100 * (w2(pr, m & tem) / w2(b0, m & tem) - 1), 100 * (w2(pr, base & tem) / w2(b0, base & tem) - 1), wins, picks
    lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
    okk = best != "off" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
    P(f"\n  LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | picks {lo[3]}"); P(f"  FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}")
    P(f"  -> {'PASS: ' + best if okk else 'FAIL (wired raw factor stays)'}")
    P("\nLimitations: offense quality = its per-game points at the position in its OTHER games so far (shrunk 3 games to the league); honest replica next game, no book anchor; the harness factor ramps from 1, the engine ramps from Clay's unit grades.")
    LOG.close()


if __name__ == "__main__":
    main()
