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
LOG = open(os.path.join(HERE, "shadow_fillin.log" if MINF == 4 else f"shadow_fillin_minf{MINF}.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + "\n"); LOG.flush()


# ------------------------------------------------------------------ fill-in tagging (copied from backtest_fillin_usage.py -
# importing that module truncates its log)
def week_team(Y, w, opp):
    o = cal.OPP_ALIAS.get(opp, opp)
    for t, s in cal.SCHEDULES.get(Y, {}).items():
        if s.get(str(w)) == o: return t
    return None


def build_fillin(ch):
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
        regs = [(r, rc) for r, rc in roster[(Y, team, ps)] if r != nm and rc > cpg and rc >= REG_MIN]
        rplay = {r: {w for w, (f, t) in games[(r, ps, Y)][2].items() if t == team} for r, _ in regs}
        rows = []
        for w in sorted(gl):
            f, t = gl[w]
            ab = tuple(r for r, _ in regs if t == team and w not in rplay[r])
            rows.append((w, f, ab))
        info[(nm, ps, Y)] = (rows, rplay, team)
    return info


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, name, adp, layers = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["name"], X["adp"], X["layers"]
    finw = np.where(year <= 2020, 17, 18)
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    info = build_fillin(ch)

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
    P(f"=== shadow fill-in / returning starter, rest of season ({MINF}+ games left): {int(ok.sum()):,} checkpoints; "
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
    # ---------------- 1 ----------------
    P("\n--- 1  FILL-IN RESCALE ON THE SHADOW (stale games' points + xFP / B; 2+ stale games) ---")
    eng = fac_div(ENG_B, scope=wr_late)
    E1 = ros_of(eng)
    for ps in ("RB", "WR"):
        fam = {"shadow (shipped, no rescale)": SH, "engine values (RB 1.26 / WR 1.08 ADP>100)": E1}
        for Bx in (1.1, 1.2, 1.3, 1.4, 1.5, 1.7, 2.0, 2.5, 3.0, 4.0): fam[f"B {Bx}"] = ros_of(fac_div({ps: Bx}, scope=wr_late if ps == "WR" else None))
        test(f"1 {ps}: rescale on the shadow", fam, pos == ps)
    fam = {"shadow": SH, **{f"B {Bx}": ros_of(fac_div({"WR": Bx})) for Bx in (1.08, 1.2, 1.3)}}
    test("1 WR all ADP (engine limits WR to ADP > 100)", fam, pos == "WR")
    fam = {"shadow": SH, **{f"B {Bx}": ros_of(fac_div({"TE": Bx})) for Bx in (1.1, 1.15, 1.3, 1.5)}}
    test("1 TE (not in the engine)", fam, pos == "TE")
    fam = {"shadow": SH, "engine values": E1}
    okE, _ = test("1 RB + WR together, engine values", fam, (pos == "RB") | (pos == "WR"))
    for rb_, wr_ in ((1.5, 1.2), (1.7, 1.3), (2.0, 1.3), (2.0, 1.5)):
        fam = {"shadow": SH, "engine values": E1, f"RB {rb_} / WR {wr_} (ADP>100)": ros_of(fac_div({"RB": rb_, "WR": wr_}, scope=wr_late))}
        test(f"1 RB + WR fixed RB {rb_} / WR {wr_} vs engine values", {"engine values": E1, f"RB {rb_} / WR {wr_}": fam[f"RB {rb_} / WR {wr_} (ADP>100)"]}, (pos == "RB") | (pos == "WR"))

    # ---------------- 2 ----------------
    P("\n--- 2  RETURNING-STARTER LAYER on top of the engine rescale (rows with stale games in the evidence that week) ---")
    sh_share = np.where(tot_a > 0, st_a / np.maximum(tot_a, 1e-9), 0.0); gshare = ns_a / np.maximum(nE, 1)
    stale_any = (ns_a >= 1)
    for ps in ("RB", "WR"):
        sc = (ppos == ps) & stale_any & (wr_late if ps == "WR" else True)
        fam = {"engine rescale": E1}
        for d in (0.97, 0.94, 0.90, 0.85, 0.80): fam[f"x{d}"] = ros_of(eng, np.where(sc, d, 1.0))
        test(f"2a {ps}: flat dock when a regular returns", fam, pos == ps)
        fam = {"engine rescale": E1}
        for k in (0.1, 0.2, 0.3, 0.4, 0.5): fam[f"1-{k} x stale game share"] = ros_of(eng, np.where(sc, 1 - k * gshare, 1.0))
        test(f"2b {ps}: dock x stale share of his games", fam, pos == ps)
        fam = {"engine rescale": E1}
        for Bx in (1.26, 1.4, 1.6) if ps == "RB" else (1.08, 1.15, 1.25):
            fam[f"B {Bx} per absent regular"] = ros_of(fac_div({ps: Bx}, per_abs=True, scope=wr_late if ps == "WR" else None))
        test(f"2c {ps}: divisor per absent regular back", fam, pos == ps)
        fam = {"engine rescale": E1}
        for d in (0.97, 0.94, 0.90, 0.85): fam[f"{d}^n back"] = ros_of(eng, np.where(sc, d ** nb_a, 1.0))
        test(f"2d {ps}: dock per distinct regular back", fam, pos == ps)
        fam = {"engine rescale": E1}
        for d in (0.95, 0.90, 0.85, 0.80): fam[f"x{d} if 2+ back"] = ros_of(eng, np.where(sc & (nb_a >= 2), d, 1.0))
        test(f"2e {ps}: dock only when 2+ regulars return (the Seattle case)", fam, pos == ps)

    # who the 2+ back rows were, and their level (is the Seattle shape over-projected?)
    P("\n--- level check: actual / prediction on rows where regulars return (rest of season, rows ok) ---")
    for ps in ("RB", "WR"):
        for lab, cond in (("1 regular back", nb_a == 1), ("2+ regulars back", nb_a >= 2)):
            sel = (ppos == ps) & cond & (ns_a >= 1)
            cps = np.unique(pi[sel]); cps = cps[ok[cps]]
            if len(cps) < 10: P(f"    {ps} {lab}: n {len(cps)}"); continue
            P(f"    {ps} {lab:18s} n {len(cps):4d}  actual {T[cps].mean():5.2f}  shadow {SH[cps].mean():5.2f} ({T[cps].mean()/SH[cps].mean():.3f})  engine rescale {E1[cps].mean():5.2f} ({T[cps].mean()/E1[cps].mean():.3f})")

    # ---------------- 3 next game ----------------
    P("\n--- 3  NEXT GAME check (first remaining game) ---")
    ok1 = ~np.isnan(T1) & (g >= 3) & (g <= 10)
    test1, _ = make_test(T1, ok1)
    N1 = next_of(eng)
    for ps in ("RB", "WR"):
        fam = {"shadow": SH1, "engine rescale": N1}
        for Bx in (1.4, 1.6): fam[f"B {Bx}"] = next_of(fac_div({ps: Bx}, scope=wr_late if ps == "WR" else None))
        test1(f"3 {ps}: next game", fam, pos == ps)

    # ---------------- 4 RB room cap (on top of the wired fill-in RB 2.0 / WR 1.3) ----------------
    P("\n--- 4  RB ROOM CAP: a team's RB projections summed vs what its RB room has scored so far (on top of fill-in RB 2.0 / WR 1.3) ---")
    team = X["team"]; rbm = pos == "RB"
    facW = fac_div({"RB": 2.0, "WR": 1.3}, scope=wr_late)
    NB = next_of(facW); RB_ = ros_of(facW)
    wkp = defaultdict(float)
    for i in np.where(rbm)[0]: wkp[(int(year[i]), team[i], int(wk[i]))] += act[i]
    byyt = defaultdict(list)
    for (y_, t_, w_), v in wkp.items(): byyt[(y_, t_)].append((w_, v))
    so_far = {}
    for k_, lst in byyt.items():
        lst.sort()
        for j_, (w_, v) in enumerate(lst):
            prev = [x[1] for x in lst[:j_]]
            so_far[(k_[0], k_[1], w_)] = (float(np.mean(prev)) if prev else np.nan, len(prev))
    room = defaultdict(list)
    for i in np.where(rbm & ~np.isnan(NB))[0]: room[(int(year[i]), team[i], int(wk[i]))].append(i)
    lg_room = {y_: float(np.mean([v for (yy, t_, w_), v in wkp.items() if yy == y_])) for y_ in YEARS}
    P(f"    league-average RB room per team-game: " + "  ".join(f"{y_} {lg_room[y_]:.1f}" for y_ in YEARS))
    over = []
    for key, ix in room.items():
        sf, ng = so_far.get(key, (np.nan, 0))
        if ng >= 2: over.append(sum(NB[ix]) / max(sf, 1e-9))
    over = np.array(over)
    P(f"    projected room / room so far: median {np.median(over):.3f}  p75 {np.percentile(over, 75):.3f}  p90 {np.percentile(over, 90):.3f}  share > 1.2: {np.mean(over > 1.2):.1%}")
    def cap_mult(kind, m, who):
        mult = np.ones(n)
        for key, ix in room.items():
            sf, ng = so_far.get(key, (np.nan, 0))
            if kind == "sofar":
                if ng < 2 or np.isnan(sf): continue
                cap = sf * (1 + m)
            else:
                cap = lg_room[key[0]] * (1 + m)
            tot = float(np.sum(NB[ix]))
            if tot <= cap: continue
            if who == "all":
                mult[ix] = cap / tot
            else:
                top = ix[int(np.argmax(NB[ix]))]; oth = [i for i in ix if i != top]
                os_ = float(np.sum(NB[oth])) if oth else 0.0
                if os_ <= 0: continue
                f_ = max(0.0, (os_ - (tot - cap)) / os_); f_ = max(f_, 0.5)   # backups never cut below half
                for i in oth: mult[i] = f_
        return mult
    test1b, _ = make_test(T1, ok1)
    for kind, grid in (("sofar", (0.1, 0.2, 0.3, 0.5)), ("league", (0.2, 0.35, 0.5, 0.75))):
        for who in ("all", "backups"):
            fam_r = {"fill-in RB 2.0 (wired)": RB_}; fam_n = {"fill-in RB 2.0 (wired)": NB}
            for m in grid:
                cm = cap_mult(kind, m, who); lab = f"cap {kind} +{int(m*100)}% ({who})"
                fam_r[lab] = RB_ * cm; fam_n[lab] = NB * cm
            test(f"4 ROS  room cap vs {kind}, cut {who}", fam_r, rbm)
            test1b(f"4 NEXT room cap vs {kind}, cut {who}", fam_n, rbm)
    # who is over-projected in crowded rooms (level check)
    P("\n    level check, ROS rows by projected room / room so far (wired fill-in):")
    rr = np.full(n, np.nan)
    for key, ix in room.items():
        sf, ng = so_far.get(key, (np.nan, 0))
        if ng >= 2: rr[ix] = np.sum(NB[ix]) / max(sf, 1e-9)
    for lo_, hi_ in ((0, 0.9), (0.9, 1.1), (1.1, 1.3), (1.3, 1.6), (1.6, 99)):
        for lab, sel in (("top RB", None), ("backups", None)):
            pass
        m_ = ok & rbm & (rr >= lo_) & (rr < hi_)
        if m_.sum() >= 30: P(f"      room x{lo_:.1f}-{hi_:.1f}: n {int(m_.sum()):5d}  actual {T[m_].mean():5.2f}  pred {RB_[m_].mean():5.2f}  ratio {T[m_].mean()/RB_[m_].mean():.3f}")
    LOG.close()


if __name__ == "__main__":
    main()
