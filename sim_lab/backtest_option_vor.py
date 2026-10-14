#!/usr/bin/env python3
"""
OPTION VOR - redraft (Jack 2026-10-09). "Include the high range of outcomes to guys like Emmett Johnson and Kaelon Black that
don't project a high number but if the RB1 gets hurt they have insane upside ... value VOR on the high end rather than averaging
it out - a guy like Kamara or Braelon Allen that steps in to the RB1 for a couple weeks is much more valuable ... than a WR that
is getting 7 a game but is consistent" + "we don't have to make their season projections higher but account for upside" +
"same for rookies that haven't performed well but historically could improve as the season goes on vs a veteran that isn't
useful for the whole season".  RESEARCH ONLY - projections untouched; this grades a RANKING VALUE.

Idea: VOR today = sum over remaining weeks of max(0, projection - replacement). A backup's projection is the healthy-starter
world, so his value is ~0 even though in some future weeks he WILL be a startable RB1 - and you will know it before lineup lock.
Option VOR prices the worlds you can see coming, never in-game variance:
  A  backup RB: per future week k ahead, (1 - h_k) x max(0, in - R) + h_k x max(0, out - R); h_k = P(the team's starting RB
     misses that game | he plays now), out = in + alpha x starter rate (alpha = share of the starter's production he absorbs)
  B  A + everyone's own-miss risk: every player's week value x (1 - own_k) (a starter who gets hurt contributes 0 that week)
  C  growth option: the projection itself moves over the season (rookies rise, roles change) and you start him once it does:
     E[max(0, in x e^Z - R)], Z ~ N(mu_g(k), sigma_g(k)) fit by group (pos x rookie x weeks ahead) - lognormal call
  A+C, B+C combined
Target (no hindsight boom credit): REALIZED STARTABLE VALUE over the rest of the season = sum over his remaining games of
(act - R_week) in the weeks his PRE-GAME projection was >= replacement (a backup whose starter sits that week gets the known
bump in his pre-game number: pre + alpha_T x starter rate, alpha_T pooled = target definition). Weeks he did not play = 0.
Replacement (12-team default, half-PPR, harness rate): RB26 / WR36 of the active players' projections that week.
Graded per checkpoint (season, week 4 .. final-4) on players active that week: Spearman rank vs realized value - RB pool, RB+WR
flex pool, and the BENCH ZONE (projection below replacement, where VOR ties at 0; tie-break = projection) - plus the realized
value captured by each method's top-12 bench-zone picks. Parameters fit leave-one-season-out (and forward 2022-25).
Log option_vor.log.
"""
import os, sys, math, warnings
from collections import defaultdict
import numpy as np
from scipy.stats import rankdata, norm as NORM
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
import backtest_shadow_ros as R
YEARS = list(SN.YEARS); FWD = (2022, 2023, 2024, 2025)
REPL = {"RB": 26, "WR": 36}
KMAX = 14
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "option_vor.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + "\n"); LOG.flush()


def spearman(a, b):
    if len(a) < 6 or np.std(a) == 0 or np.std(b) == 0: return np.nan
    return float(np.corrcoef(rankdata(a), rankdata(b))[0, 1])


def main():
    X = SN.setup(); n = X["n"]
    act, year, wk, pos, name, team, rook = X["act"], X["year"], X["wk"], X["pos"], X["name"], X["team"], X["rookie"]
    R0 = R.rate(X); lay = np.clip(X["layers"], 0.5, 1.8); pre = R0 * lay
    finw = {y: (17 if y <= 2020 else 18) for y in YEARS}
    m = np.isin(pos, ["RB", "WR"])
    row = {}; teamwk = defaultdict(set); byw = defaultdict(list)
    for i in np.where(m)[0]:
        k = (int(year[i]), name[i], pos[i]); row[(k, int(wk[i]))] = i
        teamwk[(int(year[i]), team[i])].add(int(wk[i])); byw[(int(year[i]), int(wk[i]))].append(i)
    # all positions for team schedules (a team-week exists if anyone on it has a row)
    for i in range(n): teamwk[(int(year[i]), team[i])].add(int(wk[i]))

    def repl_of(vals_by_pos):
        out = {}
        for ps, v in vals_by_pos.items():
            v = sorted(v, reverse=True); out[ps] = v[REPL[ps] - 1] if len(v) >= REPL[ps] else (v[-1] if v else 0.0)
        return out
    # weekly replacement on pre-game projections (target) and on context-free rates (prediction)
    Rw, Rc = {}, {}
    for (y, w), ix in byw.items():
        Rw[(y, w)] = repl_of({ps: [pre[i] for i in ix if pos[i] == ps] for ps in ("RB", "WR")})
        Rc[(y, w)] = repl_of({ps: [R0[i] for i in ix if pos[i] == ps] for ps in ("RB", "WR")})

    # ---------- checkpoints ----------
    # per (season, week c): active RB/WR (row at c); team starter RB = highest rate among the team's active RBs
    CP = []   # dicts per checkpoint player
    for (y, c), ix in sorted(byw.items()):
        if c < 4 or c > finw[y] - 4: continue
        tRB = defaultdict(list)
        for i in ix:
            if pos[i] == "RB": tRB[team[i]].append(i)
        start = {t: max(v, key=lambda i: R0[i]) for t, v in tRB.items()}
        rbrank = {}
        for t, v in tRB.items():
            for r_, i in enumerate(sorted(v, key=lambda i: -R0[i])): rbrank[i] = r_ + 1
        for i in ix:
            key = (y, name[i], pos[i]); t = team[i]
            futw = sorted(w for w in teamwk[(y, t)] if c <= w < finw[y])
            if len(futw) < 4: continue
            s = start.get(t) if pos[i] == "RB" else None
            isb = s is not None and s != i
            CP.append(dict(i=i, y=y, c=c, key=key, t=t, pos=pos[i], rook=bool(rook[i]), inr=float(R0[i]), futw=futw,
                           s=s if isb else None, sname=name[s] if isb else None, srate=float(R0[s]) if isb else 0.0,
                           isS=(s == i), rbr=rbrank.get(i, 0)))
    P(f"=== option VOR backtest: {len(CP):,} checkpoint players (RB/WR active, weeks 4..final-4) 2019-25 ===")

    # ---------- empirical pieces, per season (fit on other seasons later) ----------
    # starter-miss hazard h[k] (RB starters), own-miss hazard by pos, alpha (backup absorbs starter rate), growth Z by group
    hz_s = defaultdict(lambda: np.zeros((KMAX + 1, 2)))     # y -> [k] = (missed, n)
    hz_o = defaultdict(lambda: defaultdict(lambda: np.zeros((KMAX + 1, 2))))   # y -> pos -> k
    al = defaultdict(lambda: np.zeros(2))                     # y -> (sum xy, sum xx)
    mj = defaultdict(lambda: np.zeros(2)); mj2 = defaultdict(lambda: np.zeros(2))   # y -> (sum act, sum in x layer), starter-out weeks
    gz = defaultdict(lambda: defaultdict(list))               # y -> (pos, rook, kb) -> [log ratio]
    kb_of = lambda k: 0 if k <= 2 else (1 if k <= 5 else (2 if k <= 9 else 3))
    for d in CP:
        y, c = d["y"], d["c"]
        for w in d["futw"]:
            k = min(KMAX, w - c)
            if k == 0: continue
            j = row.get((d["key"], w))
            hz_o[y][d["pos"]][k] += (j is None, 1)
            if j is not None and d["inr"] > 0.5:
                gz[y][(d["pos"], d["rook"], kb_of(k))].append(math.log(max(0.3, R0[j]) / d["inr"]))
            if d["isS"]: hz_s[y][k] += (j is None, 1)
            if d["s"] is not None and j is not None:
                sj = row.get(((y, d["sname"], "RB"), w))
                if sj is None:   # starter out, backup played
                    x = d["srate"] * lay[j]; al[y] += (x * (act[j] - d["inr"] * lay[j]), x * x)
                    mj[y] += (act[j], d["inr"] * lay[j])
                    if d.get("rbr") == 2: mj2[y] += (act[j], d["inr"] * lay[j])
    def fit(train):
        hs = sum((hz_s[y] for y in train), np.zeros((KMAX + 1, 2)))
        h = np.where(hs[:, 1] > 20, hs[:, 0] / np.maximum(hs[:, 1], 1), np.nan)
        for k in range(1, KMAX + 1):
            if np.isnan(h[k]): h[k] = h[k - 1] if k > 1 and not np.isnan(h[k - 1]) else 0.1
        own = {}
        for ps in ("RB", "WR"):
            ho = sum((hz_o[y][ps] for y in train), np.zeros((KMAX + 1, 2)))
            o = np.where(ho[:, 1] > 20, ho[:, 0] / np.maximum(ho[:, 1], 1), np.nan)
            for k in range(1, KMAX + 1):
                if np.isnan(o[k]): o[k] = o[k - 1] if k > 1 and not np.isnan(o[k - 1]) else 0.1
            own[ps] = o
        a = sum((al[y] for y in train), np.zeros(2)); alpha = a[0] / a[1] if a[1] > 0 else 0.3
        g = {}
        keys = set(k for y in train for k in gz[y])
        for kk in keys:
            v = np.concatenate([np.array(gz[y][kk]) for y in train if kk in gz[y]]) if any(kk in gz[y] for y in train) else np.array([])
            if len(v) >= 30: g[kk] = (float(np.mean(v)), float(np.std(v)))
        mm = sum((mj2[y] for y in train), np.zeros(2)); FIT_MULT[0] = mm[0] / mm[1] if mm[1] > 0 else 1.0
        return h, own, alpha, g
    FIT_MULT = [1.0]
    hA, ownA, alphaA, gA = fit(YEARS)
    m_all = sum((mj[y] for y in YEARS), np.zeros(2)); m_2 = sum((mj2[y] for y in YEARS), np.zeros(2))
    P(f"  backups in starter-out weeks: actual / own projection = all backups {m_all[0]/max(m_all[1],1e-9):.3f} (n pts {m_all[1]:.0f}), RB2 {m_2[0]/max(m_2[1],1e-9):.3f}")
    P(f"  pooled: alpha (backup absorbs starter rate) {alphaA:.3f} | starter-miss h(k) k1 {hA[1]:.3f} k3 {hA[3]:.3f} k6 {hA[6]:.3f} k10 {hA[10]:.3f}"
      f" | own-miss RB k1 {ownA['RB'][1]:.3f} k6 {ownA['RB'][6]:.3f}  WR k1 {ownA['WR'][1]:.3f} k6 {ownA['WR'][6]:.3f}")
    for kk in sorted(gA): P(f"  growth {kk}: mu {gA[kk][0]:+.3f}  sigma {gA[kk][1]:.3f}")

    # ---------- realized startable value (target) ----------
    ALPHA_T = alphaA
    for d in CP:
        y, c = d["y"], d["c"]; sv = 0.0
        for w in d["futw"]:
            j = row.get((d["key"], w))
            if j is None: continue
            p_ = pre[j]
            if d["s"] is not None and row.get(((y, d["sname"], "RB"), w)) is None:
                p_ = (R0[j] + ALPHA_T * d["srate"]) * lay[j]
            rw = Rw[(y, w)][d["pos"]]
            if p_ >= rw: sv += act[j] - rw
        d["sv"] = sv

    # ---------- predictions ----------
    def call(a, Rr, mu, sg):
        if a <= 0: return 0.0
        if sg < 1e-6: return max(0.0, a * math.exp(mu) - Rr)
        if Rr <= 0: return a * math.exp(mu + sg * sg / 2)
        d2 = (math.log(a / Rr) + mu) / sg; d1 = d2 + sg
        return a * math.exp(mu + sg * sg / 2) * NORM.cdf(d1) - Rr * NORM.cdf(d2)
    def predict(d, params, variant):
        h, own, alpha, g = params
        Rr = Rc[(d["y"], d["c"])][d["pos"]]; tot = 0.0
        for w in d["futw"]:
            k = min(KMAX, w - d["c"])
            if "C" in variant and k > 0:
                mu, sg = g.get((d["pos"], d["rook"], kb_of(k)), (0.0, 0.0))
                vin = call(d["inr"], Rr, mu, sg)
                vout = call(d["inr"] + alpha * d["srate"], Rr, mu, sg) if d["s"] is not None else vin
                if "M" in variant and d["s"] is not None: vout = call(d["inr"] * FIT_MULT[0], Rr, mu, sg)
            else:
                vin = max(0.0, d["inr"] - Rr)
                vout = max(0.0, d["inr"] + alpha * d["srate"] - Rr) if d["s"] is not None else vin
                if "M" in variant and d["s"] is not None: vout = max(0.0, d["inr"] * FIT_MULT[0] - Rr)
            v = vin
            if "2" in variant and d.get("rbr") != 2: v = vin
            elif ("A" in variant or "B" in variant or "M" in variant) and d["s"] is not None and k > 0:
                v = (1 - h[k]) * vin + h[k] * vout
            if "B" in variant and k > 0:
                v *= (1 - own[d["pos"]][k])
            tot += v
        return tot
    VARS = ["cur", "A2", "M2", "C", "M2C", "A2C"]
    for d in CP: d["pr"] = {}
    def fill(fold_years, test_year):
        prm = fit(fold_years)
        for d in CP:
            if d["y"] != test_year: continue
            for v in VARS: d["pr"][v] = predict(d, prm, v) if v != "cur" else predict(d, prm, "")

    # ---------- evaluation ----------
    def evaluate(tag, folds):
        for tr, te in folds: fill(tr, te)
        tey = [te for _, te in folds]
        bycp = defaultdict(list)
        for d in CP:
            if d["y"] in tey: bycp[(d["y"], d["c"])].append(d)
        res = {v: defaultdict(lambda: defaultdict(list)) for v in VARS}   # v -> metric -> year -> [values]
        for (y, c), L in bycp.items():
            Rr = Rc[(y, c)]
            for v in VARS:
                pv = lambda d: d["pr"][v] + 1e-3 * d["inr"]   # tie-break = projection (VOR ties at 0)
                for lab, sel in (("RB", [d for d in L if d["pos"] == "RB"]), ("FLEX", L),
                                 ("BENCH", [d for d in L if d["inr"] < Rr[d["pos"]]]),
                                 ("RB-BACKUP", [d for d in L if d["s"] is not None])):
                    if len(sel) < 8: continue
                    res[v][lab][y].append(spearman(np.array([pv(d) for d in sel]), np.array([d["sv"] for d in sel])))
                bz = [d for d in L if d["inr"] < Rr[d["pos"]]]
                if len(bz) >= 24:
                    top = sorted(bz, key=pv, reverse=True)[:12]
                    res[v]["TOP12-BENCH"][y].append(sum(d["sv"] for d in top))
        P(f"\n--- {tag} ---")
        for lab in ("RB", "FLEX", "BENCH", "RB-BACKUP", "TOP12-BENCH"):
            base = {y: np.nanmean(res["cur"][lab][y]) for y in tey if res["cur"][lab][y]}
            line = f"  {lab:12s} cur {np.nanmean(list(base.values())):.4f}"
            for v in VARS[1:]:
                vy = {y: np.nanmean(res[v][lab][y]) for y in tey if res[v][lab][y]}
                better = sum(1 for y in vy if y in base and vy[y] > base[y] + 1e-9)
                line += f" | {v} {np.nanmean(list(vy.values())):.4f} ({better}/{len(vy)})"
            P(line)
        return res
    P("\n(Spearman rank vs realized startable value, averaged per checkpoint; TOP12-BENCH = realized value of each method's 12 best"
      " stashes among players projected below replacement, half-PPR points; (x/y) = seasons better than cur)")
    evaluate("LEAVE-ONE-SEASON-OUT 2019-25", [([y for y in YEARS if y != t], t) for t in YEARS])
    evaluate("FORWARD 2022-25 (earlier seasons only)", [([y for y in YEARS if y < t], t) for t in FWD])

    # ---------- who moves (pooled params, latest season) ----------
    fill([y for y in YEARS if y != 2025], 2025)
    L = [d for d in CP if d["y"] == 2025 and d["c"] == 8]
    if L:
        P("\n--- example: 2025 week 8 checkpoint, biggest option-VOR gains (A+C) vs cur, with realized startable value ---")
        for d in sorted(L, key=lambda d: d["pr"]["AC"] - d["pr"]["cur"], reverse=True)[:15]:
            P(f"    {d['key'][1]:24s} {d['pos']} {'rookie' if d['rook'] else '      '} rate {d['inr']:5.2f}  cur {d['pr']['cur']:6.1f}  A {d['pr']['A']:6.1f}  C {d['pr']['C']:6.1f}  AC {d['pr']['AC']:6.1f}  realized {d['sv']:6.1f}"
              + (f"  (behind {d['sname']})" if d['sname'] else ""))
    LOG.close()


if __name__ == "__main__":
    main()
