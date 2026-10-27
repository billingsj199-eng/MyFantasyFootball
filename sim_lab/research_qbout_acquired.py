#!/usr/bin/env python3
"""
ACQUIRED / NEW STARTING QB vs the backup-QB WR dock (2026-10-27; Jack on Nabers x.85 with McCarthy now NYG's QB). RESEARCH ONLY.

Question: should NC_SHADOW.qbOutWrDock {star .15, other .05, starAdp 60} lift once the team's starter is a QB brought in from
OUTSIDE (not on the team's Week-1 roster: trade / FA signing), and - per Jack's scope update - only once that QB has PROVEN
himself (N starts for this team AND production at/above a bar known before kickoff)?

Harness (B) = engine base, same as research_backup_qb_rating.py / research_qbout_dock_shadow.py:
  X = _bt_ext/X_cache_ext2012_2025_tf.pkl, next game = SN.shadow(X) (carries the flat dock), undocked = / (1 - d_eng);
  ROS = shadow rate x future context x (1 - d x share of future out weeks), target = mean of remaining games (final week out).
Team-week table: _tmp/qbx_cache/teamweek_2012.pkl (out / reg / stq); starters + WR xFP per game: _tmp/qbx_cache/wr_<y>.pkl;
QB production: _tmp/qbx_cache/qbgame_<y>.pkl; Week-1 rosters: pbp_cache/roster_weekly_<y>.parquet.
Grading: LOYO 2013-25 + forward 2016-25 on all WR QB-out rows (the dock's population); bar pooled < -0.3%, 70% folds,
fwd < 0 and 70%, top-150 weighted <= +0.1%. Log: _tmp/qbout_acquired.log
"""
import os, sys, math, pickle
os.environ.setdefault("SIM_BT_YEARS", "2012-2025")
from collections import defaultdict, Counter
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_ext as BX
import backtest_shadow_next as SN
CACHE = os.path.join(HERE, "_tmp", "qbx_cache"); PBP = r"E:/MyFantasyFootball/pbp_cache"
LOG = open(os.path.join(HERE, "_tmp", "qbout_acquired.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()
YEARS = list(range(2012, 2026)); LOY = [y for y in YEARS if y >= 2013]; FWY = [y for y in YEARS if y >= 2016]
NM = {"LA": "LAR", "STL": "LAR", "SD": "LAC", "OAK": "LV"}
nt = lambda t: NM.get(str(t), str(t))

# ---------------------------------------------------------------- data
Q = pd.concat([pd.read_pickle(os.path.join(CACHE, f"qbgame_{y}.pkl")) for y in YEARS], ignore_index=True)
Q["posteam"] = Q.posteam.map(nt); Q["fpp"] = 0.04 * Q.pyds + 4 * Q.ptd - 1 * Q["int"]
Qs = Q.sort_values(["season", "week"])
_cum = Qs.groupby("pid").db.cumsum() - Qs.db; _low = Qs.loc[_cum.index[_cum.values < 300]]
REPL = dict(fpp=_low.fpp.sum() / _low.db.sum(), epa=_low.epa.sum() / _low.db.sum())
LEAGUE = dict(fpp=Q.fpp.sum() / Q.db.sum(), epa=Q.epa.sum() / Q.db.sum())
QG = {(int(s), str(t), int(w), str(p)): (float(f), float(d), float(e)) for s, t, w, p, f, d, e in zip(Q.season, Q.posteam, Q.week, Q.pid, Q.fpp, Q.db, Q.epa)}
QSEASON = defaultdict(list)   # (pid, season) -> [(week, team)]
for s, t, w, p, d in zip(Q.season, Q.posteam, Q.week, Q.pid, Q.db):
    if d >= 5: QSEASON[(str(p), int(s))].append((int(w), str(t)))

TW = pd.read_pickle(os.path.join(CACHE, "teamweek_2012.pkl")); TW["tm"] = TW.tm.map(nt)
TWD = {(int(a), str(b), int(c)): (bool(o), r, s) for a, b, c, o, r, s in zip(TW.year, TW.tm, TW.wk, TW.out, TW.reg, TW.stq)}
STARTER = {}; WRX = {}   # (y, tm, wk) -> qb_id ; (y, pid) -> {wk: (tm, xfp, pts)}
for y in YEARS:
    S = pd.read_pickle(os.path.join(CACHE, f"wr_{y}.pkl"))
    for r in S["st"].itertuples(): STARTER[(y, nt(r.posteam), int(r.week))] = str(r.qb_id)
    for r in S["rec"].itertuples(): WRX.setdefault((y, str(r.pid)), {})[int(r.week)] = (nt(r.posteam), float(r.xfp), float(r.pts))
W1 = {}   # (y, tm) -> set of gsis ids on the team's first REG-week roster (any status: ACT / INA / RES / DEV)
for y in YEARS:
    R = pd.read_parquet(os.path.join(PBP, f"roster_weekly_{y}.parquet"), columns=["team", "week", "gsis_id", "game_type", "position"])
    if "game_type" in R: R = R[R.game_type.isin(["REG"]) | R.game_type.isna()]
    R = R.copy(); R["team"] = R.team.map(nt)
    for tm, g in R.groupby("team"):
        w0 = g.week.min(); W1[(y, tm)] = set(g[g.week == w0].gsis_id.dropna().astype(str))

def qb_state(y, tm, wk):
    """state of this team-week's starter, known before kickoff (starts / production use weeks < wk only)"""
    rec = TWD.get((y, tm, wk)); stq = STARTER.get((y, tm, wk))
    if rec is None or not rec[0] or stq is None: return None
    reg = rec[1] if isinstance(rec[1], str) else None
    acq = (y, tm) in W1 and stq not in W1[(y, tm)]
    other_tm = any(t != tm and w < wk for w, t in QSEASON.get((stq, y), []))   # played for another team earlier this season = traded / cut-signed
    starts = [w for (yy, t, w), q in STARTER.items() if yy == y and t == tm and w < wk and q == stq]
    f = d = e = 0.0
    for w in starts:
        v = QG.get((y, tm, w, stq))
        if v: f += v[0]; d += v[1]; e += v[2]
    fpp = f / d if d > 0 else np.nan; epa = e / d if d > 0 else np.nan
    fpp_sh = (f + 120 * REPL["fpp"]) / (d + 120)
    return dict(stq=stq, reg=reg, acq=acq, traded=other_tm, n=len(starts), starts=starts, fpp=fpp, epa=epa, fpp_sh=fpp_sh, db=d)
_qs = {}
def qbs(y, tm, wk):
    k = (y, tm, wk)
    if k not in _qs: _qs[k] = qb_state(y, tm, wk)
    return _qs[k]

def xfp_hold(y, pid, tm, s):
    """WR's xFP/g in earlier games with this starter vs with the team's regular QB this season (None if either is empty)"""
    g = WRX.get((y, pid))
    if not g or s is None or s["reg"] is None: return np.nan
    a = [g[w][1] for w in s["starts"] if w in g and g[w][0] == tm]
    b = [v[1] for w, v in g.items() if v[0] == tm and STARTER.get((y, tm, w)) == s["reg"] and w not in s["starts"]]
    if not a or not b: return np.nan
    return float(np.mean(a) / max(0.5, np.mean(b)))

# ---------------------------------------------------------------- grading (copied from research_backup_qb_rating.grade, fixed candidates only)
def grade(title, b0, cands, tm, okm, act, year, wt, top150, pos, wk, star, changed_masks):
    mse = lambda q, m: float(np.mean((q[m] - act[m]) ** 2)) if m.any() else np.nan
    mae = lambda q, m: float(np.mean(np.abs(q[m] - act[m]))) if m.any() else np.nan
    wms = lambda q, m: float(np.average((q[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    def rho(q, m):
        gr = defaultdict(list)
        for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        rh = [np.corrcoef(rankdata(act[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]
        return float(np.mean(rh)) if rh else np.nan
    P(); P(f"  {title}   (out rows {int(tm.sum())})")
    P(f"    {'candidate':44s} {'chg':>4s} {'LOYO MSE':>9s} {'folds':>6s} {'chgF':>6s} {'MAE':>7s} {'top150w':>8s} {'rank':>8s} {'FWD MSE':>8s} {'folds':>6s} {'chg-row MSE':>11s}")
    temL = np.isin(year, LOY); temF = np.isin(year, FWY); res = {}
    board = okm & top150 & (pos == "WR") & temL; r0 = rho(b0, board)
    for lab, pr in cands.items():
        prF = pr
        if isinstance(pr, tuple): pr, prF = pr
        ch = changed_masks[lab] & tm
        nl = [t for t in LOY if (tm & (year == t)).sum() >= 5]; nf = [t for t in FWY if (tm & (year == t)).sum() >= 5]
        wl = sum(1 for t in nl if mse(pr, tm & (year == t)) < mse(b0, tm & (year == t)) - 1e-12)
        wf = sum(1 for t in nf if mse(prF, tm & (year == t)) < mse(b0, tm & (year == t)) - 1e-12)
        cl = [t for t in nl if (ch & (year == t)).any()]; wcl = sum(1 for t in cl if mse(pr, tm & (year == t)) < mse(b0, tm & (year == t)) - 1e-12)
        dL = 100 * (mse(pr, tm & temL) / mse(b0, tm & temL) - 1); dLa = 100 * (mae(pr, tm & temL) / mae(b0, tm & temL) - 1)
        dF = 100 * (mse(prF, tm & temF) / mse(b0, tm & temF) - 1)
        dW = 100 * (wms(pr, tm & temL & top150) / wms(b0, tm & temL & top150) - 1)
        q_ = b0.copy(); q_[tm] = pr[tm]; dR = rho(q_, board) - r0
        dC = 100 * (mse(pr, ch & temL) / mse(b0, ch & temL) - 1) if (ch & temL).any() else np.nan
        ok = dL < -0.3 and wl >= math.ceil(0.7 * len(nl)) and dF < 0 and wf >= math.ceil(0.7 * len(nf)) and dW <= 0.1
        P(f"    {lab:44s} {int(ch.sum()):4d} {dL:+8.2f}% {wl:2d}/{len(nl):<3d} {wcl:2d}/{len(cl):<3d} {dLa:+6.2f}% {dW:+7.2f}% {dR:+8.4f} {dF:+7.2f}% {wf:2d}/{len(nf):<3d} {dC:+10.2f}%   {'PASS' if ok else 'fail'}")
        res[lab] = dict(pr=pr, dL=dL, wl=wl, nl=len(nl), wcl=wcl, ncl=len(cl), dF=dF, wf=wf, nf=len(nf), dW=dW, dLa=dLa, dR=dR, dC=dC, n=int(ch.sum()), ok=ok)
    return res

def ratio_line(lab, m, act, und, eng, name, year, star=None):
    if not m.any(): P(f"    {lab:46s} n    0"); return
    ps = len({(name[i], int(year[i])) for i in np.where(m)[0]}); ys = len(set(year[m].tolist()))
    yrs = [t for t in YEARS if (m & (year == t)).sum() >= 3]; under = sum(1 for t in yrs if act[m & (year == t)].sum() < eng[m & (year == t)].sum())
    P(f"    {lab:46s} n {int(m.sum()):4d}  p-s {ps:3d}  seasons {ys:2d}  act/undocked {act[m].sum()/und[m].sum():.3f}  act/engine {act[m].sum()/eng[m].sum():.3f}  (engine over in {under}/{len(yrs)} seasons w/3+ rows)")

# ---------------------------------------------------------------- harness (B)
def main():
    P(f"acquired-starter QB-out dock study {pd.Timestamp.now():%Y-%m-%d %H:%M}  {BX.describe()}")
    P(f"  replacement fpp/db {REPL['fpp']:.3f} epa/db {REPL['epa']:+.3f}; league fpp/db {LEAGUE['fpp']:.3f} epa/db {LEAGUE['epa']:+.3f}")
    X = pickle.load(open(BX.ext_path("X_cache.pkl"), "rb")); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    team = np.array([nt(t) for t in X["team"]]); pid = X["A"]["pid"]
    C = pd.read_parquet(BX.ext_path("ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    qbo_c = np.where(has, C["qb_out"].values[np.maximum(idx, 0)], np.nan).astype(float) == 1
    finw = np.where(year <= 2020, 17, 18); top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in ("QB", "RB", "WR", "TE"):
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    N14 = SN.shadow(X); qbN = X["qbo"]; WR = pos == "WR"; star = adp <= 60
    d_eng = np.where(star, 0.15, 0.05)
    okN = (g >= 1) & (wk != finw) & (N14 >= 3)
    undN = np.where(WR & qbN, N14 / (1 - d_eng), N14)

    # per-row QB state
    st = [None] * n; acq = np.zeros(n, bool); trd = np.zeros(n, bool); nst = np.full(n, -1); fsh = np.full(n, np.nan); fraw = np.full(n, np.nan)
    epa = np.full(n, np.nan); xh = np.full(n, np.nan); known = np.zeros(n, bool)
    for i in np.where(WR & (qbN | qbo_c))[0]:
        s = qbs(int(year[i]), team[i], int(wk[i]))
        if s is None: continue
        st[i] = s; known[i] = True; acq[i] = s["acq"]; trd[i] = s["traded"]; nst[i] = s["n"]; fsh[i] = s["fpp_sh"]; fraw[i] = s["fpp"]; epa[i] = s["epa"]
        xh[i] = xfp_hold(int(year[i]), str(pid[i]), team[i], s)
    rowsN = WR & qbN & okN & known
    P(f"  WR next-game rows with the regular QB out: {int((WR & qbN & okN).sum())}; starter state known {int(rowsN.sum())}; acquired starter {int((rowsN & acq).sum())} (traded mid-season {int((rowsN & trd).sum())})")
    # event list
    ev = {}
    for i in np.where(rowsN & acq)[0]:
        s = st[i]; k = (int(year[i]), team[i], s["stq"]); ev.setdefault(k, set()).add(int(wk[i]))
    qn = dict(zip(Q.pid.astype(str), Q.name))
    P(f"  acquired-starter events (QB not on the team's Week-1 roster) with graded WR rows: {len(ev)}")
    for (y, tm, q), wks in sorted(ev.items()):
        P(f"    {y} {tm:4s} {qn.get(q, q):18s} weeks {sorted(wks)}")

    # ---------------- descriptive
    P(); P("  DESCRIPTIVE (next game, engine base): act / undocked and act / engine (docked)")
    ih = rowsN & ~acq
    for lab, m in (("all QB-out rows", rowsN), ("in-house backup", ih), ("ACQUIRED starter", rowsN & acq), ("  acquired, traded mid-season (played elsewhere)", rowsN & acq & trd),
                   ("  acquired, signed (no earlier game elsewhere)", rowsN & acq & ~trd),
                   ("in-house, ADP 1-60", ih & star), ("in-house, other", ih & ~star), ("ACQUIRED, ADP 1-60", rowsN & acq & star), ("ACQUIRED, other", rowsN & acq & ~star),
                   ("ACQUIRED, his 1st start for the team", rowsN & acq & (nst == 0)), ("ACQUIRED, 2nd+ start", rowsN & acq & (nst >= 1)), ("ACQUIRED, 3rd+ start", rowsN & acq & (nst >= 2)),
                   ("in-house, backup's 1st start", ih & (nst == 0)), ("in-house, 2nd+ start", ih & (nst >= 1)), ("in-house, 3rd+ start", ih & (nst >= 2))):
        ratio_line(lab, m, act, undN, N14, name, year)
    P("  production-gated splits (gate uses only his earlier starts for THIS team):")
    for scope_lab, sc in (("ACQUIRED", rowsN & acq), ("any backup", rowsN)):
        for N in (1, 2, 3):
            base = sc & (nst >= N)
            ratio_line(f"{scope_lab} {N}+ starts, fpp/db >= repl", base & (fraw >= REPL["fpp"]), act, undN, N14, name, year)
            ratio_line(f"{scope_lab} {N}+ starts, fpp/db <  repl", base & (fraw < REPL["fpp"]), act, undN, N14, name, year)
            ratio_line(f"{scope_lab} {N}+ starts, shrunk fpp >= league", base & (fsh >= LEAGUE["fpp"]), act, undN, N14, name, year)
            ratio_line(f"{scope_lab} {N}+ starts, WR xFP held >= .9", base & (xh >= 0.9), act, undN, N14, name, year)
            ratio_line(f"{scope_lab} {N}+ starts, WR xFP fell < .9", base & (xh < 0.9), act, undN, N14, name, year)

    # ---------------- candidates (next game)
    def build(f):   # f = per-row multiplier on the dock (1 keep, .5 half, 0 lift)
        return np.where(WR & qbN, undN * (1 - d_eng * f), N14)
    gates = {"fpp>=repl": lambda: fraw >= REPL["fpp"], "shrunk fpp>=league": lambda: fsh >= LEAGUE["fpp"], "epa>=repl": lambda: epa >= REPL["epa"], "WR xFP held>=.9": lambda: xh >= 0.9}
    specs = {"REF acquired: no dock": (rowsN & acq, 0.0), "REF acquired: half dock": (rowsN & acq, 0.5), "REF acquired: no dock from 2nd start": (rowsN & acq & (nst >= 1), 0.0)}
    for scope_lab, sc in (("acq", acq), ("any", np.ones(n, bool))):
        for N in (1, 2, 3):
            for gl, gf in gates.items():
                for lift_lab, f in (("lift", 0.0), ("half", 0.5)):
                    specs[f"{scope_lab} N{N} {gl} {lift_lab}"] = (rowsN & sc & (nst >= N) & gf(), f)
    candsN = {k: build(np.where(m, f, 1.0)) for k, (m, f) in specs.items()}; chN = {k: m for k, (m, f) in specs.items()}
    candsN["no dock (all out rows)"] = undN; chN["no dock (all out rows)"] = rowsN
    resN = grade("NEXT GAME vs engine (all WR QB-out rows graded; chg = rows changed; chgF = wins / folds with a changed row; chg-row MSE = on changed rows)",
                 N14, candsN, rowsN, okN, act, year, wt, top150, pos, wk, star, chN)

    # ---------------- ROS
    lam0 = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    rate = (X["Pw"] * X["prior"] + g * (lam0 * X["xf"] + (1 - lam0) * X["ppg_v"])) / np.maximum(X["Pw"] + g, 1e-9)
    seq = defaultdict(list)
    for i in range(n):
        if wk[i] != finw[i]: seq[(name[i], pos[i], int(year[i]))].append(i)
    T = np.full(n, np.nan); ctx = np.full(n, np.nan); futq = np.full(n, np.nan)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(X["layers"][ix], 0.5, 1.8); q_ = qbo_c[ix].astype(float)
        for a, i in enumerate(ix):
            if len(ix) - a >= 4: T[i] = a_[a:].mean(); ctx[i] = l_[a:].mean(); futq[i] = q_[a:].mean()
    okR = ~np.isnan(T) & (g >= 3) & (g <= 10) & (rate * ctx >= 3)
    S0 = rate * ctx; fq = np.nan_to_num(futq)
    rowsR = WR & qbo_c & (fq >= 0.4) & okR & known
    engR = np.where(WR & qbo_c, S0 * (1 - d_eng * fq), S0)
    P(); P("  DESCRIPTIVE ROS (out now, 40%+ of the rest): act / undocked and act / engine")
    for lab, m in (("all", rowsR), ("in-house", rowsR & ~acq), ("ACQUIRED", rowsR & acq), ("ACQUIRED ADP 1-60", rowsR & acq & star), ("ACQUIRED 1+ starts", rowsR & acq & (nst >= 1)),
                   ("ACQUIRED 2+ starts fpp>=repl", rowsR & acq & (nst >= 2) & (fraw >= REPL["fpp"]))):
        ratio_line(lab, m, T, S0, engR, name, year)
    specsR = {}
    for k, (m, f) in specs.items():
        mR = (m & False)  # rebuild on ROS rows with the same gate definition
    def gate_mask(rows, k):
        if k == "REF acquired: no dock": return rows & acq, 0.0
        if k == "REF acquired: half dock": return rows & acq, 0.5
        if k == "REF acquired: no dock from 2nd start": return rows & acq & (nst >= 1), 0.0
        sc_, Nn, rest = k.split(" ", 2); gl, lift_lab = rest.rsplit(" ", 1)
        sc = acq if sc_ == "acq" else np.ones(n, bool)
        return rows & sc & (nst >= int(Nn[1])) & gates[gl](), (0.0 if lift_lab == "lift" else 0.5)
    candsR = {}; chR = {}
    for k in specs:
        m, f = gate_mask(rowsR, k); candsR[k] = np.where(WR & qbo_c, S0 * (1 - d_eng * np.where(m, f, 1.0) * fq), S0); chR[k] = m
    candsR["no dock (all out rows)"] = S0; chR["no dock (all out rows)"] = rowsR
    resR = grade("ROS vs engine (dock x share of future out weeks; gate state at the checkpoint)", engR, candsR, rowsR, okR, T, year, wt, top150, pos, wk, star, chR)
    # summary of passes
    P(); P("  PASSES (bar: LOYO < -0.3%, 70% folds, fwd < 0 and 70%, top-150 <= +0.1%):")
    for lab, R in (("next", resN), ("ROS", resR)):
        ps = [k for k, v in R.items() if v["ok"]]
        P(f"    {lab}: {ps if ps else 'none'}")
    resT = team_total_section(locals())
    strip = lambda R: {k: {a: b for a, b in v.items() if a != "pr"} for k, v in R.items()}
    pickle.dump(dict(resN=strip(resN), resR=strip(resR), resT=strip(resT["resT"]), resTR=strip(resT["resTR"])), open(os.path.join(HERE, "_tmp", "qbout_acquired_res.pkl"), "wb"))

def fold_table(title, b0, pr, tm, act, year):
    mse = lambda q, m: float(np.mean((q[m] - act[m]) ** 2))
    if isinstance(pr, tuple): pr = pr[0]
    P(f"    fold table {title}: " + "  ".join(f"{t} {100*(mse(pr, tm & (year == t))/mse(b0, tm & (year == t))-1):+.2f}% (n{int((tm & (year == t)).sum())})" for t in LOY if (tm & (year == t)).sum() >= 5))

# ---------------------------------------------------------------- TEAM-TOTAL-GATED dock (Jack 10-27: dock only when the QB-adjusted implied total is very low)
def team_total_section(L):
    X = L["X"]; n = L["n"]; act, year, wk, pos, adp, name, team = L["act"], L["year"], L["wk"], L["pos"], L["adp"], L["name"], L["team"]
    N14, undN, d_eng, rowsN, okN, WR, qbN, star, wt, top150 = L["N14"], L["undN"], L["d_eng"], L["rowsN"], L["okN"], L["WR"], L["qbN"], L["star"], L["wt"], L["top150"]
    S0, engR, rowsR, okR, T, fq, qbo_c = L["S0"], L["engR"], L["rowsR"], L["okR"], L["T"], L["fq"], L["qbo_c"]
    imp = X["implied"].astype(float)
    P(); P("=" * 110); P("TEAM-TOTAL-GATED DOCK (replace the flat dock: dock WRs on primary-QB-out weeks only when the QB-adjusted implied team total is low)")
    twk = defaultdict(list); twq = defaultdict(bool)
    for i in range(n):
        if not np.isnan(imp[i]): twk[(int(year[i]), team[i], int(wk[i]))].append(imp[i])
        if qbN[i]: twq[(int(year[i]), team[i], int(wk[i]))] = True
    TWI = {k: float(np.mean(v)) for k, v in twk.items()}
    slate = defaultdict(list)
    for (y, t, w), v in TWI.items(): slate[(y, w)].append(v)
    SL = {k: (np.mean(v), np.std(v) + 1e-9, np.quantile(v, 1 / 3)) for k, v in slate.items() if len(v) >= 6}
    season_mean = defaultdict(list)
    for (y, t, w), v in TWI.items(): season_mean[(y, t)].append(v)
    def reg_implied(y, t, w):
        v = [TWI[(y, t, w2)] for w2 in range(1, w) if (y, t, w2) in TWI and not twq.get((y, t, w2), False)]
        if v: return float(np.mean(v))
        pv = season_mean.get((y - 1, t))
        return float(np.mean(pv)) if pv else np.nan
    ti = np.full(n, np.nan); tz = np.full(n, np.nan); tter = np.full(n, np.nan); treg = np.full(n, np.nan)
    for i in range(n):
        k = (int(year[i]), team[i], int(wk[i])); v = TWI.get(k)
        if v is None: continue
        ti[i] = v; sl = SL.get((k[0], k[2]))
        if sl: tz[i] = (v - sl[0]) / sl[1]; tter[i] = sl[2]
        if WR[i] and (qbN[i] or qbo_c[i]): treg[i] = reg_implied(*k)
    drop = treg - ti
    miss = np.isnan(ti)
    P(f"  QB-out WR next-game rows {int(rowsN.sum())}: implied known {int((rowsN & ~miss).sum())} (missing -> keep the flat dock); regular-QB implied known {int((rowsN & ~np.isnan(treg)).sum())}")
    P(f"  implied on QB-out rows: mean {np.nanmean(ti[rowsN]):.2f}, z mean {np.nanmean(tz[rowsN]):+.2f}; drop vs regular-QB implied mean {np.nanmean(drop[rowsN]):+.2f} (median {np.nanmedian(drop[rowsN]):+.2f})")
    P("  DESCRIPTIVE next game (QB-out WR rows): act / undocked by implied band")
    for lab, m in (("z < -1", tz < -1), ("-1 <= z < -0.5", (tz >= -1) & (tz < -0.5)), ("-0.5 <= z < 0", (tz >= -0.5) & (tz < 0)), ("z >= 0", tz >= 0),
                   ("implied <= 18", ti <= 18), ("18 < implied <= 20", (ti > 18) & (ti <= 20)), ("20 < implied <= 23", (ti > 20) & (ti <= 23)), ("implied > 23", ti > 23),
                   ("drop >= 4", drop >= 4), ("2 <= drop < 4", (drop >= 2) & (drop < 4)), ("0 <= drop < 2", (drop >= 0) & (drop < 2)), ("drop < 0 (implied UP)", drop < 0)):
        ratio_line(lab, rowsN & m, act, undN, N14, name, year)
        ratio_line("   ADP 1-60", rowsN & m & star, act, undN, N14, name, year)
    def keep(gate):  # dock only where gate True (or implied unknown)
        g_ = gate | miss
        return np.where(WR & qbN, np.where(g_, N14, undN), N14), rowsN & ~g_
    with np.errstate(invalid="ignore"):
        gates = {"T1 bottom tercile of slate": ti <= tter, "T1 z < -0.5": tz < -0.5, "T1 implied <= 18": ti <= 18, "T1 implied <= 19": ti <= 19, "T1 implied <= 20": ti <= 20,
                 "T2 drop >= 2": drop >= 2, "T2 drop >= 3": drop >= 3, "T2 drop >= 4": drop >= 4}
        gates["T2 drop >= 2 (unknown regular implied -> dock)"] = (drop >= 2) | np.isnan(drop)
    cands = {"T0 no dock": undN}; chg = {"T0 no dock": rowsN}
    for k, gm in gates.items():
        cands[k], chg[k] = keep(gm)
    dpos = np.maximum(0, np.nan_to_num(drop, nan=0)); dunk = np.isnan(drop) | miss
    KG = (0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08)
    def t3_pred(ks, ko):
        d = np.where(star, np.minimum(.25, ks * dpos), np.minimum(.25, ko * dpos)); d = np.where(dunk, d_eng, d)
        return np.where(WR & qbN, undN * (1 - d), N14), d
    def t3_fit(train):
        mtr = rowsN & np.isin(year, train)
        best = {}
        for grp, msk in (("s", star), ("o", ~star)):
            mm = mtr & msk
            best[grp] = min(KG, key=lambda k: float(np.average((t3_pred(k, k)[0][mm] - act[mm]) ** 2, weights=wt[mm])))
        return best["s"], best["o"]
    def t3_folds(folds):
        pr = N14.copy(); picks = []
        for tr, te in folds:
            ks, ko = t3_fit(tr); picks.append((te, ks, ko)); m = (year == te); pr[m] = t3_pred(ks, ko)[0][m]
        return pr, picks
    prL, pkL = t3_folds([([y for y in YEARS if y != t], t) for t in LOY]); prF, pkF = t3_folds([([y for y in YEARS if y < t], t) for t in FWY])
    cands["T3 scaled k x drop (fit per fold)"] = (prL, prF); chg["T3 scaled k x drop (fit per fold)"] = rowsN & ~dunk
    ksA, koA = t3_fit(YEARS)
    resT = grade("TEAM-TOTAL NEXT GAME vs engine (flat dock)", N14, cands, rowsN, okN, act, year, wt, top150, pos, wk, star, chg)
    P(f"    T3 picks all seasons: k_star {ksA}, k_other {koA}; LOYO picks " + ", ".join(f"{t}:{a}/{b}" for t, a, b in pkL))
    best = min((k for k in resT if k != "T0 no dock"), key=lambda k: resT[k]["dL"])
    fold_table(best, N14, cands[best], rowsN, act, year)
    allW = WR & okN & ~qbN
    P(); P("  T4 (secondary): low implied without a QB out - is it the QB or just low totals? (non-QB-out WR rows; act/engine)")
    for lab, m in (("z < -1", tz < -1), ("-1 <= z < -0.5", (tz >= -1) & (tz < -0.5)), ("z >= -0.5", tz >= -0.5)):
        ratio_line(lab, allW & m, act, N14, N14, name, year); ratio_line("   ADP 1-60", allW & m & star, act, N14, N14, name, year)
    t4 = np.where(allW & (tz < -1), N14 * (1 - d_eng), N14)
    t4h = np.where(allW & (tz < -1), N14 * (1 - d_eng / 2), N14)
    grade("T4 low-total dock (star .15 / other .05) on NON-QB-out WR rows with z < -1, graded on all non-out WR rows", N14, {"T4 full": t4, "T4 half": t4h}, allW, okN, act, year, wt, top150, pos, wk, star, {"T4 full": allW & (tz < -1), "T4 half": allW & (tz < -1)})
    P(); P("  ROS")
    candsR = {"T0 no dock": S0}; chR = {"T0 no dock": rowsR}
    for k, gm in gates.items():
        g_ = gm | miss
        candsR[k] = np.where(WR & qbo_c, np.where(g_, engR, S0), S0); chR[k] = rowsR & ~g_
    def t3r(folds):
        pr = engR.copy()
        for tr, te in folds:
            ks, ko = t3_fit(tr); d = t3_pred(ks, ko)[1]; m = year == te
            pr[m] = np.where(WR & qbo_c, S0 * (1 - d * fq), S0)[m]
        return pr
    candsR["T3 scaled k x drop (fit per fold)"] = (t3r([([y for y in YEARS if y != t], t) for t in LOY]), t3r([([y for y in YEARS if y < t], t) for t in FWY])); chR["T3 scaled k x drop (fit per fold)"] = rowsR & ~dunk
    resTR = grade("TEAM-TOTAL ROS vs engine", engR, candsR, rowsR, okR, T, year, wt, top150, pos, wk, star, chR)
    bestR = min((k for k in resTR if k != "T0 no dock"), key=lambda k: resTR[k]["dL"])
    fold_table("ROS " + bestR, engR, candsR[bestR], rowsR, T, year)
    P(); P("  10 WORST backup-QB team-weeks 2012-25 by WR act/undocked (2+ graded WR rows): does each gate still dock?")
    agg = defaultdict(list)
    for i in np.where(rowsN)[0]: agg[(int(year[i]), team[i], int(wk[i]))].append(i)
    worst = sorted([k for k, v in agg.items() if len(v) >= 2], key=lambda k: act[agg[k]].sum() / undN[agg[k]].sum())[:10]
    show = ["T1 bottom tercile of slate", "T1 z < -0.5", "T1 implied <= 19", "T1 implied <= 20", "T2 drop >= 2", "T2 drop >= 3", "T2 drop >= 2 (unknown regular implied -> dock)"]
    qn = dict(zip(Q.pid.astype(str), Q.name)); cnt = Counter()
    for k in worst:
        ix = agg[k]; i0 = ix[0]; s = qbs(*k)
        fl = {g: bool(gates[g][i0] | miss[i0]) for g in show}
        for g in show: cnt[g] += fl[g]
        P(f"    {k[0]} {k[1]:4s} W{k[2]:<2d} starter {(qn.get(s['stq'], s['stq']) if s else '?'):14s} WR act {act[ix].sum():5.1f} / undocked {undN[ix].sum():5.1f} = {act[ix].sum()/undN[ix].sum():.2f}  implied {ti[i0]:5.2f} z {tz[i0]:+.2f} drop {drop[i0]:+.2f}  | " + " ".join(f"{g.split(' ',1)[1][:12]}={'D' if fl[g] else '-'}" for g in show))
    P("    docked by gate (of 10; the flat dock docks 10/10): " + ", ".join(f"{g}: {cnt[g]}" for g in show))
    # slate reference for live checks
    P(f"  slate reference: mean implied by week over 2016-25 = {np.mean([v[0] for k, v in SL.items() if k[0] >= 2016]):.2f}, sd {np.mean([v[1] for k, v in SL.items() if k[0] >= 2016]):.2f}, bottom-tercile cut {np.mean([v[2] for k, v in SL.items() if k[0] >= 2016]):.2f}")
    return dict(resT=resT, resTR=resTR, ti=ti, tz=tz, drop=drop)


if __name__ == "__main__":
    main(); LOG.close()
