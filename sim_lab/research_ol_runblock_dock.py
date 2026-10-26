#!/usr/bin/env python3
"""
OL DOCK SIZED BY THE LOST LINEMAN'S RUN-BLOCK GRADE (2026-10-23, propose-only run; Jack approved the test).
RESEARCH ONLY - nothing here touches engine.js.

The live layer (engine.js olOutDock, OL_OUT_DOCK = { rb1: .98, rb2: .95, other2: .97 }, TE removed 09-30, kill SIM_OL_DOCK):
a FLAT dock by the COUNT of the team's starting-five linemen that are out (SIM_OL_2026 from refresh_data.py: five = top
C/G/T/OL by games at >= 60% snaps then mean snap pct this season; out = Sleeper status / NFL report Out-Doubtful). It applies
to every projected week (no week argument) for the team's own RB (1 out .98, 2+ .95), QB and WR (2+ .97).

10-23 descriptive read (_tmp/ol_quality_read.py): RB act/proj 1.009 when the lost lineman's PFF run-block grade is top
tercile vs 1.207 bottom tercile (r -.08) - losing a GOOD run blocker is what hurts backs; the count dock misses it.

Walk-forward feature (per team-week, 2013-25): expected five by the live rule from snap_counts (positions C/G/T/OL/OG/OT -
the nflverse 'OL' label fixed 09-30), week 1 / short seasons from last season's five on this week's roster; a five member is
OUT when the NFL report says Out/Doubtful or the roster status is reserve/PUP/NFI/SUS/cut/traded (ABSENT_ROSTER) that week.
Lost lineman's run-block grade (2019-25): season-to-date PFF weekly gradesRunBlock (pff/weekly/pff_v2_offense_<Y>_w<N>.csv,
snap-weighted over weeks < wk) blended with LAST season's pff_blocking grade as the prior, both shrunk 300 snaps to replacement
(median of 150-600-snap linemen); q = grade - replacement (positive = a good lineman lost). 2013-18 rows have the count only.

Harness: ENGINE-BASE shadow (bt_ext X_cache 2012-25 team-fix, SN.shadow = the live base form) with the Vegas layer rebuilt in the
P-20261023-1 SPLIT form (game deviation vs the team's walk-forward avg implied shrunk 2 games, e' QB .50 RB .50 WR .375 TE .375;
week 1 / no implied = league-relative form) = the engine as deployed 2026-10-23 13:01. The old league-relative form is reported
as a cross-check. The harness carries NO OL dock, so the shipped flat dock is applied here as arm (a).

Arms on touched rows (team has 1+ starting lineman out): (a) shipped flat count dock, (b) no dock, (c) graded by the lost
lineman's run-block grade (tercile cells / linear in q, picked per fold on the training seasons, shrunk), RB primary;
QB / WR / TE spill reported. Grading: top-150 by preseason ADP, final week out, next game + ROS proxy, MAE + MSE + within
position-week rank rho on the whole board, LOYO fold table + forward, ADP 1-60 split. Bar: LOYO < -0.3% on touched rows,
70% of folds, forward < 0 and 70%, whole-board top-150 weighted <= +0.1%.  Log: _tmp/ol_runblock_dock.log
"""
import os, sys, math, pickle, glob
os.environ.setdefault("SIM_BT_YEARS", "2012-2025")
from collections import defaultdict, Counter
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_ext as BX
import bt_common as B
import backtest_shadow_next as SN
PBP = B.CACHE
LOG = None   # opened in main(): importing this module (research_qb_inherit_grade.py reuses split_layers) must not truncate the log
def P(s=""):
    print(s)
    if LOG: LOG.write(s + "\n"); LOG.flush()
norm = lambda s: B.cal.norm(str(s))
YEARS = list(range(2013, 2026)); GY = list(range(2019, 2026))   # count rows / graded rows
OLPOS = {"C", "G", "T", "OL", "OG", "OT"}
ABSENT_ROSTER = {"RES", "CUT", "DEV", "RET", "EXE", "PUP", "NFI", "SUS", "TRC", "TRD", "TRT"}
OL_K = 300.0
FLAT = {"rb1": 0.98, "rb2": 0.95, "other2": 0.97}
E_SPLIT = {"QB": .50, "RB": .50, "WR": .375, "TE": .375}

# ---------------------------------------------------------------- OL feature table
def snap_fives(Y):
    """live rule: per team, linemen ranked by (games at >= 60% snaps before wk, mean pct); returns tw snaps + per-(team, wk) five"""
    sc = pd.read_parquet(os.path.join(PBP, f"snap_counts_{Y}.parquet"), columns=["week", "game_type", "player", "position", "team", "offense_pct"])
    sc = sc[(sc.game_type == "REG") & sc.position.isin(OLPOS) & (sc.offense_pct > 0)]
    tw = defaultdict(dict)
    for r in sc.itertuples(index=False): tw[(B.tm(str(r.team)), int(r.week))][norm(r.player)] = float(r.offense_pct)
    return tw

def five_at(tw, t, wk):
    cnt, tot, n = Counter(), Counter(), Counter()
    for (tt, w), d in tw.items():
        if tt != t or w >= wk: continue
        for nm, pct in d.items():
            n[nm] += 1; tot[nm] += pct
            if pct >= 0.6: cnt[nm] += 1
    if not cnt: return None
    lst = sorted(cnt, key=lambda nm: (cnt[nm], tot[nm] / n[nm]), reverse=True)
    return lst[:5] if len(lst) >= 5 else None

def season_five(tw):
    """last season's five per team (6+ games at 60%) for week-1 use"""
    out = {}
    teams = {t for (t, _) in tw}
    for t in teams:
        f = five_at(tw, t, 99)
        if f: out[t] = f
    return out

def grades_prior(Y):
    gp = os.path.join(PBP, "pff", f"pff_blocking_{Y-1}.csv")
    if not os.path.exists(gp): return {}, np.nan
    g = pd.read_csv(gp); g = g[g.position.isin(["C", "G", "T"])]
    out = {}
    for r in g.itertuples(index=False):
        n = float(r.snap_counts_offense or 0)
        if n > 0 and pd.notna(r.grades_run_block):
            k = norm(r.player); o = out.get(k)
            if o is None or n > o[1]: out[k] = (float(r.grades_run_block), n)
    reg = g[g.snap_counts_offense.between(150, 600)]
    return out, float(reg.grades_run_block.median())

def grades_weekly(Y):
    """{wk: {norm name: (gradesRunBlock, run-block snaps)}} from the single-week PFF offense files"""
    out = {}
    for f in glob.glob(os.path.join(PBP, "pff", "weekly", f"pff_v2_offense_{Y}_w*.csv")):
        w = int(os.path.basename(f).rsplit("_w", 1)[1].split(".")[0])
        d = pd.read_csv(f, usecols=["player", "position", "gradesRunBlock", "snapCountsRunBlock", "snapCountsTotal"])
        d = d[d.position.isin(["T", "G", "C"]) & d.gradesRunBlock.notna()]
        out[w] = {norm(r.player): (float(r.gradesRunBlock), float(r.snapCountsRunBlock if pd.notna(r.snapCountsRunBlock) else r.snapCountsTotal)) for r in d.itertuples(index=False)}
    return out

def build_features():
    """(year, team, wk) -> dict(n_out, q_sum, q_max, n_known, five_q_mean, src)"""
    feats = {}; prev_tw = None; prev_five = {}
    for Y in range(2012, 2026):
        tw = snap_fives(Y)
        if Y == 2012: prev_tw = tw; prev_five = season_five(tw); continue
        inj = pd.read_parquet(os.path.join(PBP, f"injuries_{Y}.parquet"), columns=["game_type", "team", "week", "full_name", "report_status", "position"])
        inj = inj[(inj.game_type == "REG")]
        injm = {(B.tm(str(r.team)), int(r.week), norm(r.full_name)): str(r.report_status or "") for r in inj.itertuples(index=False)}
        ros = pd.read_parquet(os.path.join(PBP, f"roster_weekly_{Y}.parquet"), columns=["team", "week", "game_type", "status", "full_name", "position"])
        ros = ros[(ros.game_type == "REG") & ros.position.isin(OLPOS)]
        rosm = {(B.tm(str(r.team)), int(r.week), norm(r.full_name)): str(r.status) for r in ros.itertuples(index=False)}
        ros_have = {(B.tm(str(t)), int(w)) for t, w in zip(ros.team, ros.week)}
        gp, rep = grades_prior(Y); gw = grades_weekly(Y) if Y >= 2019 else {}
        if np.isnan(rep) and gw:   # 2019: no prior file - replacement from this season's weekly grades (linemen with 30+ run-block snaps)
            vals = [g for d in gw.values() for g, s in d.values() if s >= 30]; rep = float(np.median(vals)) if vals else np.nan
        def grade_at(nm, wk):
            """walk-forward run-block grade minus replacement; None when nothing is known"""
            if np.isnan(rep): return None
            pr = gp.get(nm); known = pr is not None
            m0 = (pr[0] * pr[1] + rep * OL_K) / (pr[1] + OL_K) if pr else rep
            gs = sn = 0.0
            for w, d in gw.items():
                if w < wk and nm in d: gs += d[nm][0] * d[nm][1]; sn += d[nm][1]; known = True
            if not known: return None
            return (m0 * OL_K + gs) / (OL_K + sn) - rep
        teams = {t for (t, _) in tw} | {t for (t, _, _) in rosm}
        for t in teams:
            for wk in range(1, 19):
                five = five_at(tw, t, wk); src = "season"
                if five is None:
                    cand = prev_five.get(t)
                    if not cand: continue
                    on = [nm for nm in cand if (t, wk, nm) in rosm]
                    if len(on) < 4: continue
                    five = on; src = "prev"
                n_out = 0; qs = []; nk = 0; allq = []; n_rep = 0; qr = []; nkr = 0
                for nm in five:
                    st = injm.get((t, wk, nm), ""); rs = rosm.get((t, wk, nm))
                    rep_out = st in ("Out", "Doubtful")
                    out = rep_out or (rs in ABSENT_ROSTER) or ((t, wk) in ros_have and rs is None)
                    q = grade_at(nm, wk)
                    if q is not None: allq.append(q)
                    if out:
                        n_out += 1
                        if q is not None: qs.append(q); nk += 1
                    if rep_out:   # FRESH absence: on this week's NFL report as Out/Doubtful (the ctx_features definition)
                        n_rep += 1
                        if q is not None: qr.append(q); nkr += 1
                feats[(Y, t, wk)] = dict(n_out=n_out, q_sum=float(sum(qs)) if qs else np.nan, q_max=float(max(qs)) if qs else np.nan, n_known=nk,
                                         five_q=float(np.mean(allq)) if allq else np.nan, src=src, n_rep=n_rep, q_rep=float(sum(qr)) if qr else np.nan, nk_rep=nkr)
        prev_tw = tw; prev_five = season_five(tw)
        P(f"  {Y}: team-weeks {sum(1 for k in feats if k[0] == Y)}, with a starter out {sum(1 for k, v in feats.items() if k[0] == Y and v['n_out'] >= 1)} (2+ {sum(1 for k, v in feats.items() if k[0] == Y and v['n_out'] >= 2)}), out with a grade {sum(1 for k, v in feats.items() if k[0] == Y and v['n_out'] >= 1 and v['n_known'] >= 1)}, replacement rb {rep:.1f}" if not np.isnan(rep) else f"  {Y}: team-weeks {sum(1 for k in feats if k[0] == Y)}, with a starter out {sum(1 for k, v in feats.items() if k[0] == Y and v['n_out'] >= 1)} (no grades)")
    return feats

# ---------------------------------------------------------------- harness + Vegas split
def split_layers(X):
    """layers rebuilt with the P-20261023-1 Vegas split (team avg shrunk 2 games); returns (layers_split, veg_old, veg_new)"""
    n = X["n"]; year, wk, pos, team, imp = X["year"], X["wk"], X["pos"], X["team"], X["implied"]
    C = pd.read_parquet(BX.ext_path("ctx_features.parquet"), columns=["year", "pid", "wk", "veg", "fpa_mult"])
    pid = X["A"]["pid"]; ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    veg = np.where(has, C.veg.values[np.maximum(idx, 0)], np.nan); fpa = np.where(has, C.fpa_mult.values[np.maximum(idx, 0)], np.nan)
    vnew = veg.copy()
    for Y in sorted(set(year.tolist())):
        games = B.load_games(Y)
        imps = [v["implied"] for v in games.values() if v["implied"] is not None]; avg = float(np.mean(imps))
        byteam = {}
        for (t, w), v in games.items():
            if v["implied"] is not None: byteam.setdefault(t, {})[w] = v["implied"]
        for i in np.where(year == Y)[0]:
            if np.isnan(imp[i]) or np.isnan(veg[i]): continue
            hist = [v for w, v in byteam.get(team[i], {}).items() if w < wk[i]]
            if not hist: continue
            ta = (sum(hist) + 2 * avg) / (len(hist) + 2)
            vnew[i] = float(np.clip(1 + E_SPLIT.get(pos[i], .25) * (imp[i] - ta) / avg, 0.7, 1.35))
    ratio = np.where(np.isnan(vnew) | np.isnan(veg) | (veg <= 0), 1.0, vnew / veg)
    return X["layers"] * ratio, veg, vnew, ratio

def main():
    global LOG; LOG = open(os.path.join(HERE, "_tmp", "ol_runblock_dock.log"), "w", encoding="utf-8")
    P(f"OL dock by the lost lineman's run-block grade - {pd.Timestamp.now():%Y-%m-%d %H:%M}  harness {BX.describe()}")
    P("building the OL feature table (live five rule, Out/Doubtful/reserve, walk-forward PFF run-block grade)")
    FE = build_features()
    pickle.dump(FE, open(os.path.join(HERE, "_tmp", "ol_feats.pkl"), "wb"))
    X = pickle.load(open(BX.ext_path("X_cache.pkl"), "rb")); n = X["n"]
    act, year, wk, pos, g, adp, name, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["team"]
    F = X["F"]; finw = np.where(year <= 2020, 17, 18); top150 = adp <= 150; star = adp <= 60
    lv = F["adp_curve"].copy()
    for ps in ("QB", "RB", "WR", "TE"):
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    SH_old = SN.shadow(X); Lsplit, veg, vnew, ratio = split_layers(X); SH = SH_old * ratio
    P(f"  Vegas split rebuilt: {int((np.abs(ratio - 1) > 1e-9).sum())} of {n} rows change, mean |veg' - veg| {np.nanmean(np.abs(vnew - veg)):.4f}")
    # features onto rows
    n_out = np.zeros(n); q_sum = np.full(n, np.nan); q_max = np.full(n, np.nan); n_known = np.zeros(n); five_q = np.full(n, np.nan); hasf = np.zeros(n, bool)
    n_rep = np.zeros(n); q_rep = np.full(n, np.nan); nk_rep = np.zeros(n)
    for i in range(n):
        f = FE.get((int(year[i]), team[i], int(wk[i])))
        if f is None: continue
        hasf[i] = True; n_out[i] = f["n_out"]; q_sum[i] = f["q_sum"]; q_max[i] = f["q_max"]; n_known[i] = f["n_known"]; five_q[i] = f["five_q"]
        n_rep[i] = f["n_rep"]; q_rep[i] = f["q_rep"]; nk_rep[i] = f["nk_rep"]
    okN = (g >= 1) & (wk != finw) & (SH >= 3) & top150 & (year >= 2013)
    touched = hasf & (n_out >= 1)
    P(f"  rows with an OL feature {int(hasf.sum())} / {n}; touched (1+ starter out) top-150 next-game rows {int((touched & okN).sum())}, graded {int((touched & okN & (n_known >= 1)).sum())}")
    P("  per season (top-150 next-game rows): touched RB / QB / WR / TE, graded RB")
    for Y in YEARS:
        m = touched & okN & (year == Y)
        P(f"    {Y}: RB {int((m & (pos == 'RB')).sum()):3d}  QB {int((m & (pos == 'QB')).sum()):3d}  WR {int((m & (pos == 'WR')).sum()):3d}  TE {int((m & (pos == 'TE')).sum()):3d}  | graded RB {int((m & (pos == 'RB') & (n_known >= 1)).sum()):3d}  2+ out RB {int((m & (pos == 'RB') & (n_out >= 2)).sum()):3d}")
    flat = np.ones(n)
    flat[(pos == "RB") & touched & (n_out == 1)] = FLAT["rb1"]; flat[(pos == "RB") & touched & (n_out >= 2)] = FLAT["rb2"]
    flat[np.isin(pos, ["QB", "WR"]) & touched & (n_out >= 2)] = FLAT["other2"]
    ENG = SH * flat; NONE = SH.copy()
    # ---------------- descriptive: act / undocked by position x count, and by lost-lineman grade tercile (RB) ----------------
    P(); P("  DESCRIPTIVE act / undocked (no OL dock) on top-150 next-game rows, 2013-25:")
    for ps in ("QB", "RB", "WR", "TE"):
        for lab, m in (("no OL out", hasf & (n_out == 0)), ("1 out", touched & (n_out == 1)), ("2+ out", touched & (n_out >= 2))):
            mm = m & okN & (pos == ps)
            if mm.sum() < 30: continue
            yrs = [Y for Y in YEARS if (mm & (year == Y)).sum() >= 10]; under = sum(1 for Y in yrs if act[mm & (year == Y)].sum() / NONE[mm & (year == Y)].sum() < act[hasf & (n_out == 0) & okN & (pos == ps) & (year == Y)].sum() / NONE[hasf & (n_out == 0) & okN & (pos == ps) & (year == Y)].sum())
            P(f"    {ps} {lab:10s} n {int(mm.sum()):5d}  act/undocked {act[mm].sum()/NONE[mm].sum():.3f}  (seasons under the no-out ratio: {under}/{len(yrs)})")
    P("  by the LOST lineman's run-block grade (q_sum = sum over out starters of grade - replacement; 2019-25 graded rows):")
    gm = touched & okN & (n_known >= 1)
    qc = np.nanquantile(q_sum[gm & (pos == "RB")], [1 / 3, 2 / 3]); P(f"    RB tercile cuts of q_sum: {qc[0]:+.2f} / {qc[1]:+.2f} grade points")
    for ps in ("QB", "RB", "WR", "TE"):
        for lab, m in (("low q (weak lost)", gm & (q_sum <= qc[0])), ("mid", gm & (q_sum > qc[0]) & (q_sum <= qc[1])), ("high q (good lost)", gm & (q_sum > qc[1]))):
            mm = m & (pos == ps)
            if mm.sum() < 25: continue
            yrs = [Y for Y in GY if (mm & (year == Y)).sum() >= 6]
            P(f"    {ps} {lab:20s} n {int(mm.sum()):4d}  act/undocked {act[mm].sum()/NONE[mm].sum():.3f}  act/flat {act[mm].sum()/ENG[mm].sum():.3f}  | by season: " + " ".join(f"{Y%100:02d} {act[mm & (year == Y)].sum()/NONE[mm & (year == Y)].sum():.2f}" for Y in yrs))
        mm = gm & (pos == ps) & ~np.isnan(q_sum)
        if mm.sum() >= 50:
            r_ = act[mm] / NONE[mm]
            P(f"    {ps}: r(act/undocked, q_sum) {np.corrcoef(np.clip(r_, 0, 4), q_sum[mm])[0,1]:+.3f}  r(q_max) {np.corrcoef(np.clip(r_, 0, 4), q_max[mm])[0,1]:+.3f}  n {int(mm.sum())}")
    # also the five's overall quality (is a weak LINE what hurts, rather than the lost man?)
    mm = hasf & okN & (pos == "RB") & ~np.isnan(five_q)
    P(f"    RB rows: r(act/undocked, expected-five mean q) {np.corrcoef(np.clip(act[mm]/NONE[mm], 0, 4), five_q[mm])[0,1]:+.3f} on all rows (n {int(mm.sum())}); on touched rows {np.corrcoef(np.clip(act[mm & touched]/NONE[mm & touched], 0, 4), five_q[mm & touched])[0,1]:+.3f} (n {int((mm & touched).sum())})")

    # ---------------- grading machinery ----------------
    mse = lambda q, m: float(np.mean((q[m] - act[m]) ** 2)) if m.any() else np.nan
    mae = lambda q, m: float(np.mean(np.abs(q[m] - act[m]))) if m.any() else np.nan
    wms = lambda q, m: float(np.average((q[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    def rho(q, m):
        gr = defaultdict(list)
        for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        rh = [np.corrcoef(rankdata(act[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]
        return float(np.mean(rh)) if rh else np.nan
    def grade(title, base, cands, rows, years, fwd_years, board, tgt=None, show_folds=True):
        """base = engine prediction; cands = {label: fixed array or fn(train_years) -> array}; rows = touched rows graded; years = LOYO folds"""
        A_ = act if tgt is None else tgt
        ms_ = lambda q, m: float(np.mean((q[m] - A_[m]) ** 2)) if m.any() else np.nan
        ma_ = lambda q, m: float(np.mean(np.abs(q[m] - A_[m]))) if m.any() else np.nan
        wm_ = lambda q, m: float(np.average((q[m] - A_[m]) ** 2, weights=wt[m])) if m.any() else np.nan
        P(); P(f"  {title}  (rows {int(rows.sum())}, ADP 1-60 {int((rows & star).sum())}; act/engine {A_[rows].sum()/base[rows].sum():.3f})")
        P(f"    {'candidate':44s} {'LOYO MAE':>9s} {'LOYO MSE':>9s} {'folds':>6s} {'board w':>8s} {'rank':>7s} {'FWD MAE':>8s} {'FWD MSE':>8s} {'folds':>6s} {'1-60 MAE':>9s} {'61-150':>8s}")
        out = {}
        loyo = [([y for y in years if y != t], t) for t in years]; fwdf = [([y for y in years if y < t], t) for t in fwd_years]
        for lab, c in cands.items():
            def fold_pred(folds):
                pr = base.copy()
                for tr, te in folds:
                    arr = c if not callable(c) else c(tr)
                    m = (year == te) & rows; pr[m] = arr[m]
                return pr
            prL = fold_pred(loyo); prF = fold_pred(fwdf)
            tL = rows & np.isin(year, years); tF = rows & np.isin(year, fwd_years)
            wl = sum(1 for t in years if (rows & (year == t)).sum() >= 5 and ms_(prL, rows & (year == t)) < ms_(base, rows & (year == t)) - 1e-12); nl = sum(1 for t in years if (rows & (year == t)).sum() >= 5)
            wf = sum(1 for t in fwd_years if (rows & (year == t)).sum() >= 5 and ms_(prF, rows & (year == t)) < ms_(base, rows & (year == t)) - 1e-12); nf = sum(1 for t in fwd_years if (rows & (year == t)).sum() >= 5)
            dLa = 100 * (ma_(prL, tL) / ma_(base, tL) - 1); dL = 100 * (ms_(prL, tL) / ms_(base, tL) - 1)
            dFa = 100 * (ma_(prF, tF) / ma_(base, tF) - 1); dF = 100 * (ms_(prF, tF) / ms_(base, tF) - 1)
            bd = board & np.isin(year, years); q_ = base.copy(); q_[tL] = prL[tL]
            dW = 100 * (wm_(q_, bd) / wm_(base, bd) - 1); dR = (rho(q_, bd) - rho(base, bd)) if tgt is None else float("nan")
            dS = 100 * (ma_(prL, tL & star) / ma_(base, tL & star) - 1) if (tL & star).sum() >= 20 else float("nan"); dO = 100 * (ma_(prL, tL & ~star) / ma_(base, tL & ~star) - 1)
            ok = dLa < -0.3 and dL < 0 and wl >= math.ceil(0.7 * nl) and dF < 0 and wf >= math.ceil(0.7 * nf) and dW <= 0.1
            P(f"    {lab:44s} {dLa:+8.2f}% {dL:+8.2f}% {wl:2d}/{nl:<3d} {dW:+7.2f}% {dR:+7.4f} {dFa:+7.2f}% {dF:+7.2f}% {wf:2d}/{nf:<3d} {dS:+8.2f}% {dO:+7.2f}%   {'PASS' if ok else 'fail'}")
            out[lab] = dict(prL=prL, dLa=dLa, dL=dL, wl=wl, nl=nl, dF=dF, wf=wf, nf=nf, ok=ok)
        if show_folds:
            labs = list(out); P("    per-season LOYO (MAE vs engine on the rows; n):")
            P("      " + "year".rjust(6) + "    n " + " ".join(f"{k[:18]:>19s}" for k in labs))
            for t in years:
                m = rows & (year == t)
                if m.sum() < 5: continue
                P("      " + f"{t:>6d} {int(m.sum()):4d} " + " ".join(f"{100*(ma_(out[k]['prL'], m)/ma_(base, m)-1):+18.2f}%" for k in labs))
        return out

    # ---------------- NEXT GAME: flat vs none, 2013-25, by position ----------------
    board = okN
    FWD13 = [y for y in YEARS if y >= 2016]
    for ps in ("RB", "QB", "WR", "TE"):
        rows = touched & okN & (pos == ps)
        if ps == "TE": rows = rows & (n_out >= 2)
        cands = {"(b) no OL dock": NONE}
        if ps == "RB":
            for r1, r2 in ((0.96, 0.92), (0.95, 0.90), (0.98, 0.90), (1.0, 0.95), (0.97, 0.94)):
                m_ = np.ones(n); m_[(pos == "RB") & touched & (n_out == 1)] = r1; m_[(pos == "RB") & touched & (n_out >= 2)] = r2
                cands[f"flat RB {r1:.2f} / {r2:.2f}"] = SH * m_
        elif ps in ("QB", "WR"):
            for r2 in (0.95, 0.93, 0.90):
                m_ = np.ones(n); m_[(pos == ps) & touched & (n_out >= 2)] = r2; cands[f"flat {ps} 2+ out {r2:.2f}"] = SH * m_
            m_ = np.ones(n); m_[(pos == ps) & touched & (n_out == 1)] = 0.98; m_[(pos == ps) & touched & (n_out >= 2)] = 0.95; cands[f"flat {ps} .98 / .95"] = SH * m_
        else:
            for r2 in (0.97, 1.05, 1.10):
                m_ = np.ones(n); m_[(pos == "TE") & touched & (n_out >= 2)] = r2; cands[f"TE 2+ out x{r2:.2f}"] = SH * m_
        grade(f"NEXT GAME {ps}: shipped flat count dock vs alternatives (2013-25, split-Vegas base)", ENG, cands, rows, YEARS, FWD13, board, show_folds=(ps == "RB"))

    # ---------------- NEXT GAME RB: graded by the lost lineman's run-block grade (2019-25) ----------------
    rowsG = touched & okN & (pos == "RB") & (n_known >= 1) & (year >= 2019)
    rowsT = touched & okN & (pos == "RB") & (year >= 2019)   # all touched RB rows 2019-25 (ungraded keep the flat dock)
    FWDG = [y for y in GY if y >= 2022]
    qv = np.where(np.isnan(q_sum), 0.0, q_sum)
    GRID = [1.0, 0.98, 0.96, 0.94, 0.92, 0.90, 0.88, 0.85]
    def cells_fn(shrink, use_count):
        def fn(train):
            mtr = rowsG & np.isin(year, train)
            c1, c2 = np.nanquantile(q_sum[mtr], [1 / 3, 2 / 3]); ter = np.where(qv <= c1, 0, np.where(qv <= c2, 1, 2))
            best = []
            for t_ in range(3):
                mm = mtr & (ter == t_)
                err = lambda k: float(np.average((SH[mm] * k - act[mm]) ** 2, weights=wt[mm])) if mm.sum() else np.inf
                best.append(min(GRID, key=err))
            fn.last = (best, (c1, c2))
            mult = np.select([ter == 2, ter == 1], [best[2], best[1]], best[0])
            if use_count: mult = mult * np.where(n_out >= 2, FLAT["rb2"] / FLAT["rb1"], 1.0)   # extra body out keeps the count step
            mult = flat + shrink * (mult - flat)
            return np.where(rowsG, SH * mult, ENG)
        return fn
    def linear_fn(shrink):
        def fn(train):
            mtr = rowsG & np.isin(year, train)
            grid = [(a, b) for a in (0.0, 0.02, 0.04, 0.06) for b in (0.0, 0.005, 0.01, 0.015, 0.02, 0.03, 0.04)]
            def err(ab):
                m_ = np.clip(1 - ab[0] - ab[1] * qv, 0.75, 1.03); return float(np.average((SH[mtr] * m_[mtr] - act[mtr]) ** 2, weights=wt[mtr]))
            a, b = min(grid, key=err); fn.last = (a, b)
            m_ = np.clip(1 - a - b * qv, 0.75, 1.03); m_ = flat + shrink * (m_ - flat)
            return np.where(rowsG, SH * m_, ENG)
        return fn
    def tilt_fn():
        def fn(train):   # shipped count dock x (1 - k x z(q)), k picked on training rows
            mtr = rowsG & np.isin(year, train); mu, sd = qv[mtr].mean(), qv[mtr].std() + 1e-9; z = np.clip((qv - mu) / sd, -2.5, 2.5)
            def err(k):
                m_ = flat * np.clip(1 - k * z, 0.8, 1.1); return float(np.average((SH[mtr] * m_[mtr] - act[mtr]) ** 2, weights=wt[mtr]))
            k = min((0.0, 0.01, 0.02, 0.03, 0.04, 0.06), key=err); fn.last = k
            m_ = flat * np.clip(1 - k * z, 0.8, 1.1); return np.where(rowsG, SH * m_, ENG)
        return fn
    # fixed cells from the descriptive read (no fitting): good lineman lost .90, mid .96, weak 1.00
    c1, c2 = qc; ter_all = np.where(qv <= c1, 0, np.where(qv <= c2, 1, 2))
    fixed = np.select([ter_all == 2, ter_all == 1], [0.90, 0.96], 1.0); FIX = np.where(rowsG, SH * fixed, ENG)
    fixed2 = np.select([ter_all == 2, ter_all == 1], [0.93, 0.97], 1.0); FIX2 = np.where(rowsG, SH * fixed2, ENG)
    cands = {"(b) no OL dock": NONE, "fixed cells good .90 / mid .96 / weak 1.00": FIX, "fixed cells .93 / .97 / 1.00": FIX2,
             "(c1) tercile cells, fit per fold": cells_fn(1.0, False), "(c1s) tercile cells, shrunk 50% to flat": cells_fn(0.5, False),
             "(c2) linear 1 - a - b q, fit per fold": linear_fn(1.0), "(c2s) linear shrunk 50%": linear_fn(0.5), "(c3) count dock x (1 - k z(q))": tilt_fn()}
    res = grade("NEXT GAME RB: dock by the LOST lineman's run-block grade (graded rows 2019-25; ungraded rows keep the flat dock)", ENG, cands, rowsG, GY, FWDG, board)
    for lab in ("(c1) tercile cells, fit per fold", "(c2) linear 1 - a - b q, fit per fold", "(c3) count dock x (1 - k z(q))"):
        fn = cands[lab]; fn(GY); P(f"    all-seasons pick {lab}: {fn.last}")
    P("    fold picks (training years = all but the fold):")
    for t in GY:
        fn = cells_fn(1.0, False); fn([y for y in GY if y != t]); fl = linear_fn(1.0); fl([y for y in GY if y != t])
        P(f"      fold {t}: cells (weak, mid, good) {fn.last[0]} cuts {fn.last[1][0]:+.2f}/{fn.last[1][1]:+.2f}; linear a {fl.last[0]:.2f} b {fl.last[1]:.3f}")
    # ---------------- VARIANT: FRESH absences only (lineman on THIS week's report as Out/Doubtful; the 10-23 ctx read's definition) ----------------
    P(); P("  VARIANT fresh-report absences (five member Out/Doubtful on this week's report; reserve / long-gone linemen NOT counted): descriptive + graded cells, RB")
    fresh = hasf & (n_rep >= 1); qvr = np.where(np.isnan(q_rep), 0.0, q_rep)
    rowsF = fresh & okN & (pos == "RB"); rowsFG = rowsF & (nk_rep >= 1) & (year >= 2019)
    for lab, m in (("fresh 1 out", fresh & (n_rep == 1)), ("fresh 2+ out", fresh & (n_rep >= 2)), ("stale only (reserve, not on report)", touched & ~fresh)):
        mm = m & okN & (pos == "RB")
        if mm.sum() >= 30:
            yrs = [Y for Y in YEARS if (mm & (year == Y)).sum() >= 10]
            P(f"    RB {lab:36s} n {int(mm.sum()):5d}  act/undocked {act[mm].sum()/NONE[mm].sum():.3f}  act/flat-shipped {act[mm].sum()/ENG[mm].sum():.3f}  seasons under 1: {sum(1 for Y in yrs if act[mm & (year == Y)].sum()/NONE[mm & (year == Y)].sum() < 1)}/{len(yrs)}")
    qcr = np.nanquantile(q_rep[rowsFG], [1 / 3, 2 / 3]); P(f"    RB fresh graded rows {int(rowsFG.sum())}; q_rep tercile cuts {qcr[0]:+.2f} / {qcr[1]:+.2f}")
    terF = np.where(qvr <= qcr[0], 0, np.where(qvr <= qcr[1], 1, 2))
    for lab, m in (("low q (weak lost)", rowsFG & (terF == 0)), ("mid", rowsFG & (terF == 1)), ("high q (good lost)", rowsFG & (terF == 2))):
        yrs = [Y for Y in GY if (m & (year == Y)).sum() >= 6]
        P(f"    RB {lab:20s} n {int(m.sum()):4d}  act/undocked {act[m].sum()/NONE[m].sum():.3f}  act/flat {act[m].sum()/ENG[m].sum():.3f}  | by season: " + " ".join(f"{Y%100:02d} {act[m & (year == Y)].sum()/NONE[m & (year == Y)].sum():.2f}" for Y in yrs))
    rr = np.clip(act[rowsFG] / NONE[rowsFG], 0, 4); P(f"    r(act/undocked, q_rep) {np.corrcoef(rr, q_rep[rowsFG])[0,1]:+.3f} (n {int(rowsFG.sum())})")
    def cellsF_fn(shrink):
        def fn(train):
            mtr = rowsFG & np.isin(year, train)
            c1, c2 = np.nanquantile(q_rep[mtr], [1 / 3, 2 / 3]); ter = np.where(qvr <= c1, 0, np.where(qvr <= c2, 1, 2))
            best = []
            for t_ in range(3):
                mm = mtr & (ter == t_)
                err = lambda k: float(np.average((SH[mm] * k - act[mm]) ** 2, weights=wt[mm])) if mm.sum() else np.inf
                best.append(min(GRID, key=err))
            fn.last = (best, (c1, c2))
            mult = np.select([ter == 2, ter == 1], [best[2], best[1]], best[0]); mult = flat + shrink * (mult - flat)
            return np.where(rowsFG, SH * mult, ENG)
        return fn
    fixF = np.select([terF == 2, terF == 1], [0.90, 0.96], 1.0)
    cands = {"(b) no OL dock": NONE, "fixed cells good .90 / mid .96 / weak 1.00": np.where(rowsFG, SH * fixF, ENG), "fixed cells good .92 / mid 1.00 / weak 1.00": np.where(rowsFG, SH * np.select([terF == 2], [0.92], 1.0), ENG),
             "(c1) tercile cells, fit per fold": cellsF_fn(1.0), "(c1s) tercile cells, shrunk 50% to flat": cellsF_fn(0.5)}
    grade("NEXT GAME RB, FRESH-report absences: dock by the lost lineman's run-block grade (2019-25)", ENG, cands, rowsFG, GY, FWDG, board)
    for t in GY:
        fn = cellsF_fn(1.0); fn([y for y in GY if y != t]); P(f"      fold {t}: cells (weak, mid, good) {fn.last[0]} cuts {fn.last[1][0]:+.2f}/{fn.last[1][1]:+.2f}")
    for lab, rows in (("FRESH rows", rowsF), ("STALE rows (reserve / gone, not on the report)", touched & ~fresh & okN & (pos == "RB"))):
        grade(f"NEXT GAME RB count dock on {lab} (2013-25)", ENG, {"(b) no OL dock": NONE, "flat RB .96 / .92": SH * np.where((pos == "RB") & touched & (n_out >= 2), 0.92, np.where((pos == "RB") & touched, 0.96, 1.0))}, rows, YEARS, FWD13, board, show_folds=False)
    # spill: graded arms applied to QB / WR / TE rows with the RB fit shape (good lineman lost -> dock)
    for ps in ("QB", "WR", "TE"):
        rowsP = touched & okN & (pos == ps) & (n_known >= 1) & (year >= 2019)
        fx = np.select([ter_all == 2, ter_all == 1], [0.95, 0.98], 1.0)
        cands = {"(b) no OL dock": NONE, "fixed cells good .95 / mid .98 / weak 1.00": np.where(rowsP, SH * fx, ENG), "fixed cells good 1.05 / weak 1.00 (TE check)": np.where(rowsP, SH * np.select([ter_all == 2], [1.05], 1.0), ENG)}
        grade(f"NEXT GAME {ps} spill: lost-lineman grade cells (2019-25)", ENG, cands, rowsP, GY, FWDG, board, show_folds=False)

    # ---------------- cross-check: old league-relative Vegas form ----------------
    ENG_o = SH_old * flat
    rows = touched & okN & (pos == "RB")
    grade("CROSS-CHECK RB next game on the OLD league-relative Vegas base (2013-25)", ENG_o, {"(b) no OL dock": SH_old, "flat RB .96 / .92": SH_old * np.where((pos == "RB") & touched & (n_out >= 2), 0.92, np.where((pos == "RB") & touched, 0.96, 1.0))}, rows, YEARS, FWD13, board, show_folds=False)
    FIXo = np.where(rowsG, SH_old * fixed, ENG_o)
    grade("CROSS-CHECK RB graded cells on the OLD Vegas base (2019-25)", ENG_o, {"(b) no OL dock": SH_old, "fixed cells good .90 / mid .96 / weak 1.00": FIXo}, rowsG, GY, FWDG, board, show_folds=False)

    # ---------------- ROS proxy: the engine docks every future week while the lineman is out now ----------------
    P(); P("  REST OF SEASON proxy (rows at a week with a starter out NOW, 3-10 games played, 4+ games left; target = mean actual over the remaining games; engine = shadow rate x mean future layers x the dock on every future week)")
    lam0 = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    rate = (X["Pw"] * X["prior"] + g * (lam0 * X["xf"] + (1 - lam0) * X["ppg_v"])) / np.maximum(X["Pw"] + g, 1e-9)
    seq = defaultdict(list)
    for i in range(n):
        if wk[i] != finw[i]: seq[(name[i], pos[i], int(year[i]))].append(i)
    T = np.full(n, np.nan); ctx = np.full(n, np.nan); fut_out = np.full(n, np.nan)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(Lsplit[ix], 0.5, 1.8); o_ = (n_out[ix] >= 1).astype(float)
        for a, i in enumerate(ix):
            if len(ix) - a >= 4: T[i] = a_[a:].mean(); ctx[i] = l_[a:].mean(); fut_out[i] = o_[a + 1:].mean() if len(ix) - a > 1 else np.nan
    S0 = rate * ctx; okR = ~np.isnan(T) & (g >= 3) & (g <= 10) & (S0 >= 3) & top150 & (year >= 2013)
    P(f"    share of the REMAINING games that still have a starting lineman out, rows out now: RB mean {np.nanmean(fut_out[touched & okR & (pos == 'RB')]):.2f}")
    for ps in ("RB", "QB", "WR"):
        rowsR = touched & okR & (pos == ps)
        engR = S0 * flat
        cands = {"(b) no OL dock": S0}
        if ps == "RB":
            cands["flat .96 / .92 all future weeks"] = S0 * np.where((pos == "RB") & touched & (n_out >= 2), 0.92, np.where((pos == "RB") & touched, 0.96, 1.0))
            cands["flat dock x share of future weeks out (oracle)"] = S0 * (1 - (1 - flat) * np.nan_to_num(fut_out))
            rowsRG = rowsR & (n_known >= 1) & (year >= 2019)
            cands["graded fixed cells .90/.96/1.00 all future weeks"] = np.where(rowsRG, S0 * fixed, engR)
            cands["graded cells x share out (oracle)"] = np.where(rowsRG, S0 * (1 - (1 - fixed) * np.nan_to_num(fut_out)), engR)
        grade(f"ROS {ps}: dock on every future week (shipped) vs alternatives", engR, cands, rowsR, YEARS, FWD13, okR, tgt=T, show_folds=(ps == "RB"))
    LOG.close()

if __name__ == "__main__":
    main()
