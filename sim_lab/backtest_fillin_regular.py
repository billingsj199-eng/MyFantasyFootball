#!/usr/bin/env python3
"""
FILL-IN RESCALE + RETURNING-STARTER DOCK on the Clay-free SHADOW (Jack 2026-10-09, Emanuel Wilson: "he should be high while
Jadarian Price and Charbonnet are out ... but they should both be back in roughly 3-4 weeks ... prop guys up in the meantime
but understand they aren't long-term assets").  RESEARCH ONLY - nothing here touches engine.js.

Background: SIM_FILLIN (engine fillinStale / fillinPtsF, backtest_fillin_usage.py) divides a backup's STALE fill-in games
(he played while a same-team same-position regular sat, and that regular is back for the projected week) by RB 1.26 / WR 1.08.
It was fit and wired on the LIVE (Clay-blend) form.  Since 2026-10-08 every week runs on the shadow alone, and the shadow's
jsBasePg / shadowUsage never received the rescale -> backups carry their fill-in evidence into the weeks after the starter returns.

Harness = backtest_shadow_ros.py (checkpoints with 3-10 games played; target = per-game average over the rest of the season,
final week dropped; ROS_MINF games left, default 4, run with ROS_MINF=1 too).  Here the prediction is built PER FUTURE WEEK:
for each of his remaining games the stale set is the fill-in games whose absent regular plays THAT week (hindsight stands in
for the engine's injury timeline, as in backtest_fillin_usage.py), rate_k = shadow rate with those games' points / xFP divided,
prediction = mean_k(rate_k x layer_k).

  1  the rescale on the shadow: fixed engine values (RB 1.26, WR 1.08 ADP > 100) and a divisor grid; scopes RB / WR / TE
  2  returning-starter layer on top of 1: docks on rows whose evidence holds stale games
       2a  flat dock by position (x.97 ... x.80)
       2b  dock scaled by the stale share of his evidence: 1 - k x stale share
       2c  divisor per absent regular (two starters out in one game -> 1 + 2 x (B - 1))
       2d  dock by number of distinct regulars returning (d ** n)
  3  next game (first remaining game only) for the picks, as a check
Pass bar (backtest_shadow_ros.py): LOYO < -0.3% and 5/7 seasons, forward < 0 and 3/4, top-150 weighted not worse (+0.1%).
Log shadow_fillin.log (shadow_fillin_minf1.log with ROS_MINF=1).
"""
import json, os, sys, warnings
from collections import defaultdict
import numpy as np
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
import backtest_shadow_ros as R
cal = SN.cal; YEARS = list(SN.YEARS); POS4 = ("QB", "RB", "WR", "TE"); SK = ("RB", "WR", "TE"); FWD = (2022, 2023, 2024, 2025)
MINF = int(os.environ.get("ROS_MINF", "4"))
REG_MIN = 5.0
ENG_B = {"RB": 1.26, "WR": 1.08}
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "fillin_regular.log" if MINF == 4 else f"fillin_regular_minf{MINF}.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + "\n"); LOG.flush()


# ------------------------------------------------------------------ fill-in tagging (copied from backtest_fillin_usage.py -
# importing that module truncates its log)
def week_team(Y, w, opp):
    o = cal.OPP_ALIAS.get(opp, opp)
    for t, s in cal.SCHEDULES.get(Y, {}).items():
        if s.get(str(w)) == o: return t
    return None


def build_fillin(ch, regf=None):
    tcache = {}; roster = defaultdict(list); games = {}
    for Y in YEARS:
        W = 16 if Y <= 2020 else 17
        for nm, c in ch[str(Y)].items():
            ps = c.get("pos")
            if ps not in SK: continue
            rec = cal.weekly_rec(nm, ps)
            if rec is None: continue
            team = cal.infer_team(rec, Y)
            gmv = (c.get("gm") or 0); half = max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0)
            cpg = half / gmv if gmv >= 4 else half / W
            gl = {}
            for w in rec.get("seasons", {}).get(str(Y), []):
                if cal.played(w) and isinstance(w.get("fpts"), (int, float)) and w.get("opp"):
                    k = (Y, int(w["wk"]), w["opp"])
                    if k not in tcache: tcache[k] = week_team(Y, int(w["wk"]), w["opp"])
                    gl[int(w["wk"])] = (float(w["fpts"]), tcache[k])
            games[(nm, ps, Y)] = (team, cpg, gl)
            if team: roster[(Y, team, ps)].append((nm, cpg))
    info = {}
    for (nm, ps, Y), (team, cpg, gl) in games.items():
        if not team: continue
        regs = [(r, rc) for r, rc in roster[(Y, team, ps)] if r != nm and rc > cpg and rc >= REG_MIN and (regf is None or regf(cpg, rc))]
        rplay = {r: {w for w, (f, t) in games[(r, ps, Y)][2].items() if t == team} for r, _ in regs}
        rows = []
        for w in sorted(gl):
            f, t = gl[w]
            ab = tuple(r for r, _ in regs if t == team and w not in rplay[r])
            rows.append((w, f, ab))
        info[(nm, ps, Y)] = (rows, rplay, team)
    return info


def run_variant(X, ch, regf, want_test=False):
    n = X["n"]; F = X["F"]
    act, year, wk, pos, g, name, adp, layers = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["name"], X["adp"], X["layers"]
    finw = np.where(year <= 2020, 17, 18)
    info = build_fillin(ch, regf)

    # player-season sequences (final week dropped, as the ROS harness)
    seq = defaultdict(list)
    for i in range(n):
        if wk[i] != finw[i]: seq[(name[i], pos[i], int(year[i]))].append(i)
    for ix in seq.values(): ix.sort(key=lambda i: wk[i])
    T = np.full(n, np.nan); T1 = np.full(n, np.nan); fut = {}
    for k, ix in seq.items():
        for a, i in enumerate(ix):
            f = ix[a:]
            fut[i] = f
            T1[i] = act[i]
            if len(f) >= MINF: T[i] = act[f].mean()

    # per checkpoint: evidence games (w < wk) with absent regulars; per future week, which absentees play that week
    # ev_rows[i] = (tot_pts, [(pts, absent tuple)]) ; rplay for "back" checks
    R0 = R.rate(X)
    lt = np.clip(layers, 0.5, 1.8)
    # stale-points share per (checkpoint, future week) under several weightings
    #   st1 = points of stale games, nst = stale game count, st_ab = sum over stale games of points x (# absent regulars back)
    #   nb = distinct regulars back that week (among those absent in his evidence)
    rec_cache = {}
    def ev_of(i):
        key = (name[i], pos[i], int(year[i]))
        if key not in info: return None
        rows, rplay, team = info[key]
        E = [(f, ab) for (w, f, ab) in rows if w < wk[i]]
        return E, rplay
    # Build flat arrays over (checkpoint, future k) pairs for checkpoints in SK with any fill-in evidence
    pi, pk, tot_a, st_a, ab_a, nb_a, ns_a = [], [], [], [], [], [], []
    has_fi = np.zeros(n, bool)
    for i in np.where((g >= 3) & (g <= 10))[0]:
        if pos[i] not in SK or i not in fut: continue
        r = ev_of(i)
        if r is None: continue
        E, rplay = r
        if not any(ab for _, ab in E): continue
        has_fi[i] = True
        tot = sum(max(0.0, f) for f, _ in E)
        for j in fut[i]:
            wj = int(wk[j])
            back = {rg for _, ab in E for rg in ab if wj in rplay.get(rg, ())}
            st = sum(max(0.0, f) for f, ab in E if any(rg in back for rg in ab))
            sab = sum(max(0.0, f) * sum(1 for rg in ab if rg in back) for f, ab in E if any(rg in back for rg in ab))
            ns = sum(1 for f, ab in E if any(rg in back for rg in ab))
            pi.append(i); pk.append(j); tot_a.append(tot); st_a.append(st); ab_a.append(sab); nb_a.append(len(back)); ns_a.append(ns)
    pi, pk = np.array(pi), np.array(pk); tot_a, st_a, ab_a, nb_a, ns_a = map(np.array, (tot_a, st_a, ab_a, nb_a, ns_a))
    nE = np.array([g[i] for i in pi], dtype=float)
    SH = np.full(n, np.nan)
    for i, f in fut.items(): SH[i] = R0[i] * lt[f].mean()
    ok = ~np.isnan(T) & (g >= 3) & (g <= 10) & (np.nan_to_num(SH) >= 3)
    if want_test: P(f"=== shadow fill-in / returning starter, rest of season ({MINF}+ games left): {int(ok.sum()):,} checkpoints; "
      f"{int((ok & has_fi).sum()):,} with fill-in games in the evidence; (checkpoint, future week) pairs {len(pi):,} ===")

    lam = R.base_lam(pos, g)
    Pw, prior, xf, ppv = X["Pw"], X["prior"], X["xf"], X["ppg_v"]
    def rate_scaled(ix, fac):
        """shadow rate for checkpoints ix with points AND xFP evidence scaled by fac (engine: ppg x ptsF, xFP per stale game / B)"""
        ev = lam[ix] * xf[ix] * fac + (1 - lam[ix]) * ppv[ix] * fac
        return (Pw[ix] * prior[ix] + g[ix] * ev) / np.maximum(Pw[ix] + g[ix], 1e-9)
    base_pair = R0[pi] * lt[pk]
    # baseline ROS prediction for every checkpoint: mean over future weeks of R0 x layer
    def ros_from_pairs(vals, base_full=None):
        out = (R0 * np.nan) if base_full is None else base_full.copy()
        s = defaultdict(float); c = defaultdict(int)
        for a, v in zip(pi, vals): s[a] += v; c[a] += 1
        for a in s: out[a] = s[a] / c[a]
        return out
    SH1 = R0 * lt   # next game

    top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2

    def make_test(Tt, okm):
        ms = lambda q, m: float(np.mean((q[m] - Tt[m]) ** 2)) if m.any() else np.nan
        wm = lambda q, m: float(np.average((q[m] - Tt[m]) ** 2, weights=wt[m])) if m.any() else np.nan
        def rho(q, m):
            gr = defaultdict(list)
            for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
            rh = [np.corrcoef(rankdata(Tt[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]
            return float(np.mean(rh)) if rh else np.nan
        def test(title, fam, m_rows):
            names = list(fam); b = fam[names[0]]; touched = np.zeros(n, bool)
            for k_ in names[1:]: touched |= np.abs(np.nan_to_num(fam[k_]) - np.nan_to_num(b)) > 1e-9
            tm = m_rows & okm & touched
            pick = lambda yrs: min(names, key=lambda k: ms(fam[k], tm & np.isin(year, yrs)))
            def run(folds):
                wins = 0; picks = []; pr = b.copy()
                for tr, te in folds:
                    k = pick(tr); picks.append(k); m = year == te; pr[m] = fam[k][m]; wins += ms(fam[k], tm & m) < ms(b, tm & m) - 1e-12
                tem = np.isin(year, [te for _, te in folds])
                return pr, 100 * (ms(pr, tm & tem) / ms(b, tm & tem) - 1), 100 * (wm(pr, tm & tem & top150) / wm(b, tm & tem & top150) - 1), wins, picks
            if tm.sum() < 30:
                P(f"\n  {title}   (rows {int(tm.sum())}) - too few rows"); return False, names[0]
            lo = run([([y for y in YEARS if y != t], t) for t in YEARS]); fw = run([([y for y in YEARS if y < t], t) for t in FWD])
            best = pick(YEARS)
            okk = best != names[0] and lo[1] < -0.3 and lo[3] >= 5 and fw[1] < 0 and fw[3] >= 3 and lo[2] <= 0.1
            sb = lambda k: sum(1 for y in YEARS if (tm & (year == y)).sum() >= 8 and ms(fam[k], tm & (year == y)) < ms(b, tm & (year == y)) - 1e-12)
            okm_all = okm & m_rows
            P(f"\n  {title}   (rows touched {int(tm.sum()):,}; actual {Tt[tm].mean():.2f}, base {b[tm].mean():.2f})")
            P("    pooled on touched rows (seasons better): " + "  ".join(f"{k}: {100*(ms(fam[k], tm)/ms(b, tm)-1):+.2f}% lvl {fam[k][tm].mean():.2f} ({sb(k)})" for k in names[1:]))
            P("    whole position group: " + "  ".join(f"{k}: {100*(ms(fam[k], okm_all)/ms(b, okm_all)-1):+.3f}%" for k in names[1:]))
            P(f"    LEAVE-ONE-SEASON-OUT  {lo[1]:+.2f}%  seasons better {lo[3]}/7  | top-150 weighted {lo[2]:+.2f}%  rank order {rho(lo[0], tm & top150) - rho(b, tm & top150):+.4f}  | picks {lo[4]}")
            P(f"    FORWARD 2022-25       {fw[1]:+.2f}%  seasons better {fw[3]}/4  | top-150 weighted {fw[2]:+.2f}%  | picks {fw[4]}")
            P(f"    -> {'PASS: ' + str(best) if okk else 'FAIL (best pooled: ' + str(best) + ')'}")
            return okk, best
        return test, ms

    test, ms = make_test(T, ok)
    adpx = np.where(np.isnan(adp), 999.0, adp)
    ppos = pos[pi]; padp = adpx[pi]

    def fac_div(Bmap, per_abs=False, scope=None):
        """per (checkpoint, future week) evidence factor: stale games divided by B (per_abs: B grows with absent regulars back)"""
        Bv = np.array([Bmap.get(p_, 1.0) for p_ in ppos])
        if scope is not None: Bv = np.where(scope, Bv, 1.0)
        if per_abs:
            # sum over stale games f x (1 - 1 / (1 + (B-1) x nab)); approximated with the points-weighted mean number of absentees back
            nab = np.where(st_a > 0, ab_a / np.maximum(st_a, 1e-9), 0.0); Be = 1 + (Bv - 1) * nab
        else: Be = Bv
        fac = np.where(tot_a > 0, (tot_a - st_a * (1 - 1 / np.maximum(Be, 1e-9))) / np.maximum(tot_a, 1e-9), 1.0)
        # engine rule: only with 2+ stale games
        return np.where(ns_a >= 2, fac, 1.0)
    def ros_of(fac, mult=None):
        r = rate_scaled(pi, fac) * lt[pk]
        if mult is not None: r = r * mult
        out = SH.copy(); s = defaultdict(float); c = defaultdict(int)
        for a, v in zip(pi, r): s[a] += v; c[a] += 1
        for a in s: out[a] = s[a] / c[a]
        return out
    def next_of(fac, mult=None):
        first = np.array([fut[a][0] == j for a, j in zip(pi, pk)])
        r = rate_scaled(pi, fac) * lt[pk]
        if mult is not None: r = r * mult
        out = SH1.copy(); out[pi[first]] = r[first]; return out

    wr_late = (ppos != "WR") | (padp > 100)
    facW = fac_div({"RB": 2.0, "WR": 1.7}, scope=wr_late)   # as wired (FILLIN.ncBoost RB 2.0 / WR 1.7)
    return dict(ros=ros_of(facW), nxt=next_of(facW), SH=SH, SH1=SH1, T=T, T1=T1, ok=ok, make_test=make_test, has_fi=has_fi, info=info)


def main():
    X = SN.setup(); pos, year, g, adp = X["pos"], X["year"], X["g"], X["adp"]
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    P("=== WHO COUNTS AS A REGULAR (Jack 2026-10-10, 'fix the fill-in rule for chuba'): Chuba Hubbard's games were filed as fill-in")
    P("    for Jonathon Brooks because Brooks's Clay level was a hair above his. Variants on the regular definition, on top of the wired")
    P("    shadow fill-in (RB 2.0 / WR 1.7 ADP > 100, 2+ stale games). Base = the wired rule (regular = Clay half PPG >= 5 and > his own). ===")
    base = run_variant(X, ch, None, True)
    test, ms = base["make_test"](base["T"], base["ok"]); test1, _ = base["make_test"](base["T1"], ~np.isnan(base["T1"]) & (g >= 3) & (g <= 10))
    V = {}
    for m in (1.1, 1.2, 1.3, 1.5): V[f"regular >= {m}x his level"] = run_variant(X, ch, (lambda c, r, m=m: r >= m * c))
    for f in (6.0, 7.0, 8.0, 9.0): V[f"no regular if his own level >= {f}"] = run_variant(X, ch, (lambda c, r, f=f: c < f))
    V["no fill-in rule at all"] = dict(ros=base["SH"], nxt=base["SH1"])
    rb, wr = pos == "RB", pos == "WR"
    for lab, m_ in (("RB + WR", rb | wr), ("RB", rb), ("WR", wr)):
        fam = {"wired regular rule": base["ros"], **{k: v["ros"] for k, v in V.items()}}
        test(f"ROS {lab}: who counts as a regular", fam, m_)
        fam1 = {"wired regular rule": base["nxt"], **{k: v["nxt"] for k, v in V.items()}}
        test1(f"NEXT GAME {lab}: who counts as a regular", fam1, m_)
    # level on rows the variants release (rows the wired rule rescales and the variant does not)
    P(); P("--- level on the rows each variant gives back (wired rescaled them, variant does not), rest of season ---")
    T, ok = base["T"], base["ok"]
    for k, v in V.items():
        d = ok & (np.abs(v["ros"] - base["ros"]) > 1e-9)
        if d.sum() < 5: P(f"    {k:34s} n {int(d.sum())}"); continue
        P(f"    {k:34s} n {int(d.sum()):4d}  actual {T[d].mean():5.2f}  wired {base['ros'][d].mean():5.2f}  variant {v['ros'][d].mean():5.2f}   error {100*(ms(v['ros'], d)/ms(base['ros'], d)-1):+6.2f}%")
    # named examples on the near-tie variant
    P(); P("--- who the 1.2x rule releases (player-seasons, RB/WR) ---")
    v = V["regular >= 1.2x his level"]; d = ok & (np.abs(v["ros"] - base["ros"]) > 1e-9)
    seen = {}
    for i in np.where(d)[0]: seen.setdefault((X["name"][i], pos[i], int(year[i])), []).append(i)
    for (nm, ps, y), ix in sorted(seen.items(), key=lambda t: (t[0][2], t[0][0]))[:60]:
        P(f"    {y} {ps} {nm:24s} rows {len(ix):2d}  actual {T[ix].mean():5.2f}  wired {base['ros'][ix].mean():5.2f}  variant {v['ros'][ix].mean():5.2f}")
    LOG.close()


if __name__ == "__main__":
    main()
