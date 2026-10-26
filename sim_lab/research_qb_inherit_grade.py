#!/usr/bin/env python3
"""
QB INHERIT x.85 GRADED (2026-10-23, propose-only run; never backtested as a layer). RESEARCH ONLY - nothing touches engine.js.

What the engine does (engine.js, read 2026-10-23):
  applyInSeasonInjuries: per team|QB group and week, lost = the BEST absent QB's per-game level x (1 - mult) (ONE QB SLOT,
  SIM_NC_QB_ONESLOT); the healthy in-window QB with the best depth rank is nextQb and gets iA = 1 + INJ_SHARE.QB (.85) x lost / own.
  weeklyProjection (live side): for a QB with iA > 1, qbInh = (iA - 1) x seasonPoints / games = .85 x lost in POINTS (additive fix
  09-18); qbJoin = max(own capped at qb2Cap, qbInh) when the chart is known (SIM_LIVE_QB2), else own + qbInh.
  Shadow side (the base since 10-08): ncFull per QB, lost = max over absent QBs of ncFull x (1 - cap); bestQb (lowest effective
  string, tie higher own) gets gained = .85 x lost; ncMean = max(ncOwn, gained) (qbMax, SIM_NC_QBMAX) - never added.
  Weeks: every projected week in which the starter's availability cap < 1 (current week Out/Doubtful/Questionable docks, later
  weeks the injury curve), under the per-team current week (SIM_TEAM_CURWK). qboutS (the WR dock) is a separate layer on the
  receivers; the backup cap qb2Cap / +qb prior cap only bind at effective string 2+, so the fill-in STARTER (string 1 among
  available QBs this week) is uncapped: his number = max(own shadow, .85 x the starter's full shadow number).

Harness: ENGINE-BASE shadow (bt_ext X_cache 2012-25 team-fix, SN.shadow) with the Vegas layer rebuilt in the P-20261023-1 split
form (live engine as of 10-23 13:01). Rows = pool QBs with a game in a week where the team's main QB (most rows that season)
has no row; TRIGGER split: 'known' = the main QB was Out/Doubtful on the report or on reserve/not on the roster that week
(what the engine can see pre-kickoff) vs 'any' (benchings, surprise scratches included). Starter's full number S = his shadow
rate after his last game x this week's layers (same team) x the QB game-total tilt.
Arms: (a) shipped max(own, .85 S); (b) off = own only; (b2) fraction 1.0 = max(own, S); (c) fitted fraction k per fold (LOYO /
forward); (d) backup's own history-based level: shrunk fantasy pts per dropback (season-decayed, 120-dropback shrink to
replacement, _tmp/qbx_cache/qbgame_<y>.pkl) x the team's dropbacks per game + rushing pts/g history, as max(own, L) / L alone /
blended; (d2) the quality GAP form max(own, S x clip(fpp_B / fpp_R, .5, 1.1)). Grading: top-150 rows, final week out, MAE + MSE,
rank rho on the whole QB board, LOYO 2013-25 fold table, forward 2016-25, ADP 1-60 split. Log: _tmp/qb_inherit_grade.log
"""
import os, sys, math, pickle
os.environ.setdefault("SIM_BT_YEARS", "2012-2025")
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_ext as BX
import bt_common as B
import backtest_shadow_next as SN
from research_ol_runblock_dock import split_layers
PBP = B.CACHE; CACHE = os.path.join(HERE, "_tmp", "qbx_cache")
LOG = open(os.path.join(HERE, "_tmp", "qb_inherit_grade.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()
YEARS = list(range(2013, 2026)); FWY = [y for y in YEARS if y >= 2016]
ABSENT_ROSTER = {"RES", "CUT", "DEV", "RET", "EXE", "PUP", "NFI", "SUS", "TRC", "TRD", "TRT"}
REPL_K = 120; DECAY = 0.6

# ---------------------------------------------------------------- QB history (as research_backup_qb_rating.py)
def load_qbgames():
    Q = pd.concat([pd.read_pickle(os.path.join(CACHE, f"qbgame_{y}.pkl")) for y in range(2012, 2026)], ignore_index=True)
    Q["t"] = Q.season * 100 + Q.week
    Q["fpp"] = 0.04 * Q.pyds + 4 * Q.ptd - 1 * Q["int"]
    Q["posteam"] = Q.posteam.replace({"LA": "LAR", "STL": "LAR", "SD": "LAC", "OAK": "LV"})
    return Q
Q = load_qbgames(); QB_ROWS = {pid: g.sort_values("t") for pid, g in Q.groupby("pid")}
_cum = Q.sort_values("t").groupby("pid").db.cumsum() - Q.sort_values("t").db
_low = Q.loc[_cum.index[_cum.values < 300]]
REPL = dict(fpp=_low.fpp.sum() / _low.db.sum(), rush=float((0.1 * _low.rush_yds + 6 * _low.rush_td)[_low.db >= 10].mean()))
_hc = {}
def qb_hist(pid, year, wk):
    key = (pid, year, wk)
    if key in _hc: return _hc[key]
    g = QB_ROWS.get(pid); out = dict(db=0.0, fpp=REPL["fpp"], rush=REPL["rush"], games=0)
    if g is not None:
        h = g[g.t < year * 100 + wk]
        if len(h):
            w = DECAY ** (year - h.season.values).astype(float); db = float(np.sum(w * h.db.values))
            out["db"] = float(h.db.sum()); out["fpp"] = (float(np.sum(w * h.fpp.values)) + REPL_K * REPL["fpp"]) / (db + REPL_K)
            gm = h[h.db >= 10]; wg = DECAY ** (year - gm.season.values).astype(float)
            rp = 0.1 * gm.rush_yds.values + 6 * gm.rush_td.values
            out["rush"] = (float(np.sum(wg * rp)) + 6 * REPL["rush"]) / (float(wg.sum()) + 6) if len(gm) else REPL["rush"]; out["games"] = int(len(gm))
    _hc[key] = out; return out
TEAM_DB = Q.groupby(["season", "posteam", "week"]).db.sum().reset_index()
def team_db_pg(year, tm, wk):
    h = TEAM_DB[(TEAM_DB.season == year) & (TEAM_DB.posteam == tm) & (TEAM_DB.week < wk)]
    if len(h) >= 2: return float(h.db.mean())
    h2 = TEAM_DB[(TEAM_DB.season == year - 1) & (TEAM_DB.posteam == tm)]
    return float(h2.db.mean()) if len(h2) else float(TEAM_DB[TEAM_DB.season == year].db.mean())

def main():
    P(f"QB inherit x.85 graded - {pd.Timestamp.now():%Y-%m-%d %H:%M}  harness {BX.describe()}; replacement fpp {REPL['fpp']:.3f} rush/g {REPL['rush']:.2f}")
    X = pickle.load(open(BX.ext_path("X_cache.pkl"), "rb")); n = X["n"]
    act, year, wk, pos, g, adp, name, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["team"]
    pid = X["A"]["pid"]; F = X["F"]; finw = np.where(year <= 2020, 17, 18); top150 = adp <= 150; star = adp <= 60
    lv = F["adp_curve"].copy()
    for ps in ("QB", "RB", "WR", "TE"):
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    SH_old = SN.shadow(X); Lsplit, veg, vnew, ratio = split_layers(X); SH = SH_old * ratio
    rate = (X["Pw"] * X["prior"] + g * X["ppg_v"]) / np.maximum(X["Pw"] + g, 1e-9)   # QB evidence = points (lam 0)
    allr = (wk != finw) & (SH >= 3)
    # injury / roster status of QBs by gsis id
    inj = {}; ros = {}; ros_have = set()
    for Y in YEARS:
        d = pd.read_parquet(os.path.join(PBP, f"injuries_{Y}.parquet"), columns=["game_type", "team", "week", "gsis_id", "report_status", "position"])
        d = d[(d.game_type == "REG") & (d.position == "QB")]
        for r in d.itertuples(index=False):
            if isinstance(r.gsis_id, str): inj[(Y, B.tm(str(r.team)), int(r.week), r.gsis_id)] = str(r.report_status or "")
        d = pd.read_parquet(os.path.join(PBP, f"roster_weekly_{Y}.parquet"), columns=["team", "week", "game_type", "status", "gsis_id", "position"])
        d = d[(d.game_type == "REG") & (d.position == "QB")]
        for r in d.itertuples(index=False):
            t = B.tm(str(r.team)); ros_have.add((Y, t, int(r.week)))
            if isinstance(r.gsis_id, str): ros[(Y, t, int(r.week), r.gsis_id)] = str(r.status)
    # fill-in rows
    S = np.full(n, np.nan); fill = np.zeros(n, bool); known = np.zeros(n, bool); mainpid = {}; consec = np.zeros(n)
    byteam = defaultdict(list)
    for i in np.where(pos == "QB")[0]: byteam[(int(year[i]), team[i])].append(i)
    for (Y, t), ix in byteam.items():
        cnt = defaultdict(int)
        for i in ix: cnt[name[i]] += 1
        mq = max(cnt, key=cnt.get)
        if cnt[mq] < 4: continue
        rows_m = sorted([i for i in ix if name[i] == mq], key=lambda i: wk[i]); wk_m = {int(wk[i]) for i in rows_m}; mp = pid[rows_m[0]]; mainpid[(Y, t)] = mp
        for i in ix:
            if name[i] == mq or int(wk[i]) in wk_m or not allr[i] or Y < 2013: continue
            prev = [j for j in rows_m if wk[j] < wk[i]]
            if not prev: continue   # the starter must have played this season (the engine's lost level is his shadow number)
            j = prev[-1]
            r_upd = (X["Pw"][j] * X["prior"][j] + g[j] * X["ppg_v"][j] + act[j]) / (X["Pw"][j] + g[j] + 1)   # rate after his last game
            S[i] = r_upd * Lsplit[i] * np.exp(0.03 * X["z"][i]); fill[i] = True
            st = inj.get((Y, t, int(wk[i]), mp), "") if isinstance(mp, str) else ""; rs = ros.get((Y, t, int(wk[i]), mp)) if isinstance(mp, str) else None
            known[i] = st in ("Out", "Doubtful") or (rs in ABSENT_ROSTER) or ((Y, t, int(wk[i])) in ros_have and rs is None and isinstance(mp, str))
            consec[i] = sum(1 for w in range(int(wk[j]) + 1, int(wk[i])) if w not in wk_m)   # starter's missed weeks before this one
    # the harness's own pre-kickoff flag (ctx qb_out of the team's skill rows that week = top-dropback QB Out/Doubtful/reserve)
    qbo_tw = {}
    for i in np.where(X["qbo"] & (pos != "QB"))[0]: qbo_tw[(int(year[i]), team[i], int(wk[i]))] = True
    known2 = np.array([qbo_tw.get((int(year[i]), team[i], int(wk[i])), False) for i in range(n)])
    fm = fill & ~np.isnan(S); fk = fm & (known | known2)
    P(f"  fill-in starts (pool QB playing, main QB without a game): {int(fill.sum())}; graded rows (final week out, shadow >= 3) {int(fm.sum())}, of them top-150 by ADP {int((fm & top150).sum())}; pre-kickoff KNOWN (main QB Out/Doubtful/reserve by id {int((fm & known).sum())}, by the ctx qb_out flag {int((fm & known2).sum())}) {int(fk.sum())}")
    for i in np.where(fm & ~(known | known2) & (year >= 2024))[0][:12]:
        P(f"    not-known example: {int(year[i])} wk {int(wk[i]):2d} {team[i]} {name[i]} (main QB pid {mainpid.get((int(year[i]), team[i]))})")
    P("  per season: all / known / known ADP 1-60 / known first start / actual / own / .85 S / shipped max")
    for Y in YEARS:
        m = fm & (year == Y); k = fk & (year == Y)
        if m.sum(): P(f"    {Y}: {int(m.sum()):3d} / {int(k.sum()):3d} / {int((k & star).sum()):2d} / {int((k & (consec == 0)).sum()):3d}   act {act[k].mean():5.2f}  own {SH[k].mean():5.2f}  .85S {0.85*S[k].mean():5.2f}  max {np.maximum(SH, 0.85*S)[k].mean():5.2f}" if k.sum() else f"    {Y}: {int(m.sum()):3d} / 0")
    own = SH
    # history-based level (d)
    L = np.full(n, np.nan); kB = np.full(n, np.nan); hgames = np.zeros(n)
    for i in np.where(fm)[0]:
        b = qb_hist(pid[i], int(year[i]), int(wk[i])) if isinstance(pid[i], str) else dict(fpp=REPL["fpp"], rush=REPL["rush"], games=0)
        mp = mainpid.get((int(year[i]), team[i]))
        L[i] = b["fpp"] * team_db_pg(int(year[i]), team[i], int(wk[i])) + b["rush"]; hgames[i] = b["games"]
    # regular's fpp for the gap form
    for (Y, t), ix in byteam.items():
        cnt = defaultdict(int)
        for i in ix: cnt[name[i]] += 1
        mq = max(cnt, key=cnt.get); mp = pid[[i for i in ix if name[i] == mq][0]]
        for i in ix:
            if fm[i] and isinstance(mp, str) and isinstance(pid[i], str):
                rb = qb_hist(mp, int(year[i]), int(wk[i])); bb = qb_hist(pid[i], int(year[i]), int(wk[i]))
                kB[i] = float(np.clip(bb["fpp"] / max(1e-6, rb["fpp"]), 0.5, 1.1))
    # ---------------- descriptive ----------------
    for lab, m in (("ALL fill-ins", fm), ("KNOWN pre-kickoff", fk), ("KNOWN, first start of the absence", fk & (consec == 0)), ("KNOWN, 2nd+ consecutive start", fk & (consec >= 1)), ("KNOWN, ADP 1-60", fk & star), ("KNOWN, top-150 ADP", fk & top150), ("KNOWN, own >= 10", fk & (own >= 10)), ("KNOWN, own < 10", fk & (own < 10))):
        if m.sum() < 15: continue
        P(f"  {lab:38s} n {int(m.sum()):3d}  actual {act[m].mean():5.2f} | own {own[m].mean():5.2f} (act/own {act[m].sum()/own[m].sum():.3f})  .85 S {0.85*S[m].mean():5.2f} (act/.85S {act[m].sum()/(0.85*S[m]).sum():.3f})  max(own,.85S) {np.maximum(own, .85*S)[m].mean():5.2f} (act/max {act[m].sum()/np.maximum(own, .85*S)[m].sum():.3f})  hist L {L[m].mean():5.2f} (act/L {act[m].sum()/L[m].sum():.3f})  gap k {np.nanmean(kB[m]):.2f}")
    m = fk
    P(f"  correlations on KNOWN rows: r(act, own) {np.corrcoef(act[m], own[m])[0,1]:+.3f}  r(act, S) {np.corrcoef(act[m], S[m])[0,1]:+.3f}  r(act, L) {np.corrcoef(act[m], L[m])[0,1]:+.3f}  r(act, max) {np.corrcoef(act[m], np.maximum(own, .85*S)[m])[0,1]:+.3f}; share of rows where .85 S > own {float((0.85*S[m] > own[m]).mean()):.2f}")
    # ---------------- grading ----------------
    def rho(q, mm):
        gr = defaultdict(list)
        for i in np.where(mm)[0]: gr[(int(year[i]), int(wk[i]))].append(i)
        rh = [np.corrcoef(rankdata(act[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]
        return float(np.mean(rh)) if rh else np.nan
    board = (pos == "QB") & top150 & allr
    def grade(title, base, cands, rows, years, fwd_years):
        ms_ = lambda q, mm: float(np.mean((q[mm] - act[mm]) ** 2)) if mm.any() else np.nan
        ma_ = lambda q, mm: float(np.mean(np.abs(q[mm] - act[mm]))) if mm.any() else np.nan
        wm_ = lambda q, mm: float(np.average((q[mm] - act[mm]) ** 2, weights=wt[mm])) if mm.any() else np.nan
        P(); P(f"  {title}  (rows {int(rows.sum())}, ADP 1-60 {int((rows & star).sum())}; act/engine {act[rows].sum()/base[rows].sum():.3f}, engine mean {base[rows].mean():.2f} actual {act[rows].mean():.2f})")
        P(f"    {'candidate':46s} {'LOYO MAE':>9s} {'LOYO MSE':>9s} {'folds':>6s} {'board w':>8s} {'rank':>7s} {'FWD MAE':>8s} {'FWD MSE':>8s} {'folds':>6s} {'1-60 MAE':>9s} {'61-150':>8s}")
        out = {}; loyo = [([y for y in years if y != t], t) for t in years]; fwdf = [([y for y in years if y < t], t) for t in fwd_years]
        for lab, c in cands.items():
            def fold_pred(folds):
                pr = base.copy()
                for tr, te in folds:
                    arr = c if not callable(c) else c(tr); mm = (year == te) & rows; pr[mm] = arr[mm]
                return pr
            prL = fold_pred(loyo); prF = fold_pred(fwdf); tL = rows & np.isin(year, years); tF = rows & np.isin(year, fwd_years)
            wl = sum(1 for t in years if (rows & (year == t)).sum() >= 4 and ms_(prL, rows & (year == t)) < ms_(base, rows & (year == t)) - 1e-12); nl = sum(1 for t in years if (rows & (year == t)).sum() >= 4)
            wf = sum(1 for t in fwd_years if (rows & (year == t)).sum() >= 4 and ms_(prF, rows & (year == t)) < ms_(base, rows & (year == t)) - 1e-12); nf = sum(1 for t in fwd_years if (rows & (year == t)).sum() >= 4)
            dLa = 100 * (ma_(prL, tL) / ma_(base, tL) - 1); dL = 100 * (ms_(prL, tL) / ms_(base, tL) - 1); dFa = 100 * (ma_(prF, tF) / ma_(base, tF) - 1); dF = 100 * (ms_(prF, tF) / ms_(base, tF) - 1)
            bd = board & np.isin(year, years); q_ = base.copy(); q_[tL] = prL[tL]; dW = 100 * (wm_(q_, bd) / wm_(base, bd) - 1); dR = rho(q_, bd) - rho(base, bd)
            dS = 100 * (ma_(prL, tL & star) / ma_(base, tL & star) - 1) if (tL & star).sum() >= 15 else float("nan"); dO = 100 * (ma_(prL, tL & ~star) / ma_(base, tL & ~star) - 1)
            ok = dLa < -0.3 and dL < 0 and wl >= math.ceil(0.7 * nl) and dF < 0 and wf >= math.ceil(0.7 * nf) and dW <= 0.1
            P(f"    {lab:46s} {dLa:+8.2f}% {dL:+8.2f}% {wl:2d}/{nl:<3d} {dW:+7.2f}% {dR:+7.4f} {dFa:+7.2f}% {dF:+7.2f}% {wf:2d}/{nf:<3d} {dS:+8.2f}% {dO:+7.2f}%   {'PASS' if ok else 'fail'}")
            out[lab] = dict(prL=prL, dLa=dLa, dL=dL, wl=wl, nl=nl, dF=dF, wf=wf, nf=nf, ok=ok)
        labs = list(out); P("    per-season LOYO (MAE vs engine on the rows; n):"); P("      " + "year".rjust(6) + "    n " + " ".join(f"{k[:18]:>19s}" for k in labs))
        for t in years:
            mm = rows & (year == t)
            if mm.sum() < 4: continue
            P("      " + f"{t:>6d} {int(mm.sum()):4d} " + " ".join(f"{100*(ma_(out[k]['prL'], mm)/ma_(base, mm)-1):+18.2f}%" for k in labs))
        return out
    ENG = np.where(fm, np.maximum(own, 0.85 * S), SH)
    KGRID = (0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1)
    def fit_k(rows, form):
        def fn(train):
            mtr = rows & np.isin(year, train)
            def err(k):
                pr = form(k); return float(np.average((pr[mtr] - act[mtr]) ** 2, weights=wt[mtr]))
            k = min(KGRID, key=err); fn.last = k; return form(k)
        return fn
    for lab_rows, rows in (("KNOWN pre-kickoff", fk), ("ALL fill-ins", fm)):
        cands = {"(b) OFF: own only": own, "(b2) fraction 1.0: max(own, S)": np.maximum(own, S), "(a-add) own + .85 S (pre-09-18 live form)": own + 0.85 * S,
                 ".85 S alone": 0.85 * S, "avg(own, .85 S)": (own + 0.85 * S) / 2, "max(own, .70 S)": np.maximum(own, 0.70 * S), "max(own, .60 S)": np.maximum(own, 0.60 * S),
                 "(c) fitted k: max(own, k S)": fit_k(rows, lambda k: np.maximum(own, k * S)), "(c') fitted k: k S alone": fit_k(rows, lambda k: k * S), "(c'') fitted k: avg(own, k S)": fit_k(rows, lambda k: (own + k * S) / 2),
                 "(d) max(own, history L)": np.maximum(own, L), "(d) history L alone": L, "(d) avg(L, max(own, .85 S))": (L + np.maximum(own, 0.85 * S)) / 2, "(d) max(own, .85 S) x (L / own)^.5 ": np.maximum(own, 0.85 * S) * np.sqrt(np.where(own > 0, L / own, 1.0)),
                 "(d2) gap: max(own, S x clip(fppB/fppR, .5, 1.1))": np.maximum(own, S * np.nan_to_num(kB, nan=0.85)), "(d2) gap x .95": np.maximum(own, 0.95 * S * np.nan_to_num(kB, nan=0.85))}
        res = grade(f"NEXT GAME QB fill-in rows - {lab_rows} (engine = max(own, .85 S), 2013-25)", ENG, cands, rows, YEARS, FWY)
        for lab in ("(c) fitted k: max(own, k S)", "(c') fitted k: k S alone", "(c'') fitted k: avg(own, k S)"):
            fn = cands[lab]; fn(YEARS); P(f"    all-seasons pick {lab}: k = {fn.last}; per fold: " + " ".join(f"{t}:{(fn([y for y in YEARS if y != t]) is not None) and fn.last}" for t in YEARS))
    # splits on the known rows: first start vs 2nd+, own >= 10 vs < 10
    for lab, rows in (("KNOWN first start of the absence", fk & (consec == 0)), ("KNOWN 2nd+ consecutive start", fk & (consec >= 1)), ("KNOWN own < 10 (thin backups)", fk & (own < 10)), ("KNOWN own >= 10", fk & (own >= 10)), ("KNOWN top-150 by preseason ADP", fk & top150), ("KNOWN no ADP / outside top 150", fk & ~top150)):
        if rows.sum() < 25: continue
        grade(f"NEXT GAME split: {lab}", ENG, {"(b) OFF: own only": own, "(b2) max(own, S)": np.maximum(own, S), "avg(own, .85 S)": (own + 0.85 * S) / 2, "(d) max(own, history L)": np.maximum(own, L), "(d) avg(L, max(own, .85 S))": (L + np.maximum(own, 0.85 * S)) / 2}, rows, YEARS, FWY)
    # cross-check on the old Vegas form
    S_o = S * X["layers"] / np.where(Lsplit > 0, Lsplit, 1); own_o = SH_old; ENG_o = np.where(fm, np.maximum(own_o, 0.85 * S_o), SH_old)
    grade("CROSS-CHECK known rows on the OLD league-relative Vegas base", ENG_o, {"(b) OFF: own only": own_o, "(b2) max(own, S)": np.maximum(own_o, S_o), "avg(own, .85 S)": (own_o + 0.85 * S_o) / 2, "(d) max(own, L)": np.maximum(own_o, L)}, fk, YEARS, FWY)
    # 2025 examples
    P(); P("  2025 known fill-in rows: name, wk, own, .85 S, max, history L, actual")
    for i in sorted(np.where(fk & (year == 2025))[0], key=lambda i: wk[i]):
        P(f"    wk {int(wk[i]):2d} {name[i]:22s} {team[i]:4s} own {own[i]:5.2f}  .85S {0.85*S[i]:5.2f}  engine {ENG[i]:5.2f}  L {L[i]:5.2f} (hist games {int(hgames[i])})  actual {act[i]:5.1f}")
    LOG.close()

if __name__ == "__main__":
    main()
