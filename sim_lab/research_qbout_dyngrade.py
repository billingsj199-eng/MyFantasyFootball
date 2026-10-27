#!/usr/bin/env python3
"""
BACKUP-QB DYNAMIC GRADE DOCK (Jack 2026-10-27 addendum to test 5: "make sure it changes quickly based on current team performance").
PROPOSE ONLY. Harness (B) rows as research_qbout_grade.py (data block of research_qbout_acquired.py exec'd; its log untouched).

Grade_t = w x observed + (1 - w) x prior, w = n / (n + k), n = the backup's starts this season for this team (before the game),
k in {1, 2, 3} (fitted LOSO), prior = 1.0 (flat dock) or the static draft tier from test 5 (rd 1-2 -> 1.0, else 1.25).
Observed ratio r (1 = the offense with him looks like the offense with the primary):
  OBS1  QB fantasy points per dropback in his starts / the primary's rate this season (league rate if the primary has no games)
  OBS2  team points scored / Vegas implied total in his starts (environment-neutral by construction)
  OBS3  team receiving fantasy points per dropback in his starts / the team's rate in the primary's starts this season
Dock multiplier f = prior x clip(1 + b x (1 - r_shrunk), 0.25, 2.0), r_shrunk = w r + (1 - w) x 1, b in {0.5, 1, 1.5, 2} (fitted LOSO),
so a backup whose offense produces above the primary's level sheds the dock continuously, a bad one earns more of it.
Grading: the 10-27 grade() (bar LOSO < -0.3%, 70% folds, fwd < 0 and 70%, top-150 <= +0.1%) on LOSO-/forward-picked predictions,
per season, Cooper Rush list, NYG / PHI 2026 readout with McCarthy's week-by-week grade path, the 2026 W1-7 lock rows.
Log: _tmp/qbout_dyngrade.log
"""
import os, sys, math, json, pickle, re
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
os.environ.setdefault("SIM_BT_YEARS", "2012-2025")
import bt_ext as BX
import backtest_shadow_next as SN
src = open(os.path.join(HERE, "research_qbout_acquired.py"), encoding="utf-8").read()
start = src.index("CACHE = os.path.join"); end = src.index("# ---------------------------------------------------------------- harness (B)")
block = src[start:end].replace('os.path.join(HERE, "_tmp", "qbout_acquired.log")', 'os.path.join(HERE, "_tmp", "qbout_dyngrade.log")')
exec(block)
PL = pd.read_csv(os.path.join(PBP, "players.csv"), low_memory=False, usecols=["gsis_id", "display_name", "draft_round", "draft_pick"]).drop_duplicates("gsis_id").set_index("gsis_id")
SMC = os.path.join(HERE, "scratch_model", "cache")
# team-week output 2012-2026 from the scratch feature tables: receiving fantasy pts, dropbacks, points scored, implied
TWO = {}
for y in range(2012, 2027):
    try:
        tg = pd.read_parquet(os.path.join(SMC, f"tg_{y}.parquet")); pg = pd.read_parquet(os.path.join(SMC, f"pg_{y}.parquet"))
    except FileNotFoundError:
        continue
    pg["recpts"] = pg.rec * .5 + pg.rcy * .1 + pg.rctd * 6
    rp = pg.groupby(["team", "week"]).recpts.sum()
    for r in tg.itertuples():
        TWO[(y, nt(r.team), int(r.week))] = (float(rp.get((r.team, int(r.week)), 0.0)), float(r.t_db), float(r.pts), float(r.implied) if not np.isnan(r.implied) else np.nan)


def observed(y, tm, wk, s):
    """(r1, r2, r3, n) from his starts before wk this season for this team"""
    starts = s["starts"]; n = len(starts)
    if n == 0: return np.nan, np.nan, np.nan, 0
    f = d = 0.0; pts = imp = 0.0; rp = db = 0.0
    for w in starts:
        v = QG.get((y, tm, w, s["stq"]))
        if v: f += v[0]; d += v[1]
        t = TWO.get((y, tm, w))
        if t:
            rp += t[0]; db += t[1]; pts += t[2]
            imp += t[3] if not np.isnan(t[3]) else 22.0
    # primary's rate this season (weeks before the outage, with him starting)
    reg = s["reg"]; rf = rd = rrp = rdb = 0.0
    if reg:
        for (yy, t_, w), q in STARTER.items():
            if yy == y and t_ == tm and w < wk and q == reg:
                v = QG.get((y, tm, w, reg))
                if v: rf += v[0]; rd += v[1]
                t = TWO.get((y, tm, w))
                if t: rrp += t[0]; rdb += t[1]
    reg_rate = rf / rd if rd >= 60 else LEAGUE["fpp"]
    r1 = (f / d) / reg_rate if d > 0 else np.nan
    r2 = pts / imp if imp > 0 else np.nan
    reg_rp = rrp / rdb if rdb >= 60 else np.nan
    r3 = (rp / db) / reg_rp if (db > 0 and not np.isnan(reg_rp) and reg_rp > 0) else np.nan
    return r1, r2, r3, n


def main():
    P(f"backup-QB DYNAMIC grade dock {pd.Timestamp.now():%Y-%m-%d %H:%M}  {BX.describe()}")
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
    st = [None] * n; known = np.zeros(n, bool); acq = np.zeros(n, bool); nst = np.zeros(n); R = np.full((n, 3), np.nan); prior_t = np.ones(n)
    for i in np.where(WR & (qbN | qbo_c))[0]:
        s = qbs(int(year[i]), team[i], int(wk[i]))
        if s is None: continue
        st[i] = s; known[i] = True; acq[i] = s["acq"]
        r1, r2, r3, k_ = observed(int(year[i]), team[i], int(wk[i]), s); R[i] = (r1, r2, r3); nst[i] = k_
        rd = PL.draft_round.get(s["stq"], np.nan) if s["stq"] in PL.index else np.nan
        prior_t[i] = 1.0 if (not np.isnan(rd) and rd <= 2) else 1.25
    rowsN = WR & qbN & okN & known
    P(f"  QB-out WR rows {int(rowsN.sum())}; backup's 1st start (no observation yet, prior only) {int((rowsN & (nst == 0)).sum())}; 2nd+ start {int((rowsN & (nst >= 1)).sum())}")
    OBS = {"OBS1 QB fpp/db vs primary": 0, "OBS2 team pts / implied": 1, "OBS3 team rec pts/db vs primary": 2}
    P("\n  descriptive: next-game act / undocked by the observed ratio in his earlier starts (2nd+ start rows):")
    for lab, j in OBS.items():
        r = R[:, j]; m2 = rowsN & (nst >= 1) & ~np.isnan(r)
        P(f"   {lab} (n {int(m2.sum())}, corr with act/undocked {np.corrcoef(r[m2], (act / undN)[m2])[0, 1]:+.3f})")
        for lo, hi in ((0, .7), (.7, .9), (.9, 1.1), (1.1, 1.3), (1.3, 9)):
            m = m2 & (r >= lo) & (r < hi)
            if m.sum() >= 10: ratio_line(f"     r {lo:.1f}-{hi:.1f}", m, act, undN, N14, name, year)
    def build(j, k, b, prior):
        r = R[:, j]; w = nst / (nst + k); rs = np.where(np.isnan(r), 1.0, w * r + (1 - w) * 1.0)
        f = (prior_t if prior else 1.0) * np.clip(1 + b * (1 - rs), 0.25, 2.0)
        return np.where(WR & qbN, undN * (1 - d_eng * f), N14), f
    mse = lambda q, m: float(np.mean((q[m] - act[m]) ** 2)) if m.any() else np.nan
    cands = {}; chg = {}; picks_log = {}
    for lab, j in OBS.items():
        for prior in (False, True):
            fam = {(k, b): build(j, k, b, prior) for k in (1, 2, 3) for b in (0.5, 1.0, 1.5, 2.0)}
            def pick(trs):
                return min(fam, key=lambda kb: mse(fam[kb][0], rowsN & np.isin(year, trs)))
            prL = N14.copy(); prF = N14.copy(); pl = []; pf = []
            for t in LOY:
                kb = pick([y for y in YEARS if y != t]); pl.append(kb); m = year == t; prL[m] = fam[kb][0][m]
            for t in FWY:
                kb = pick([y for y in YEARS if y < t]); pf.append(kb); m = year == t; prF[m] = fam[kb][0][m]
            key = f"{lab}{' x draft prior' if prior else ''} [LOSO/fwd-picked k,b]"
            cands[key] = (prL, prF); chg[key] = rowsN; picks_log[key] = (pl, pf, pick(YEARS))
            kb0 = pick(YEARS); cands[key.replace("[LOSO/fwd-picked k,b]", f"fixed k{kb0[0]} b{kb0[1]:.1f}")] = fam[kb0][0]; chg[key.replace("[LOSO/fwd-picked k,b]", f"fixed k{kb0[0]} b{kb0[1]:.1f}")] = rowsN
    cands["REF static draft tier (rd 1-2 x1, else x1.25)"] = np.where(WR & qbN, undN * (1 - d_eng * prior_t), N14); chg["REF static draft tier (rd 1-2 x1, else x1.25)"] = rowsN
    res = grade("next game vs the engine (flat dock)", N14, cands, rowsN, okN, act, year, wt, top150, pos, wk, star, chg)
    P("\n  picks (LOSO per held-out season | forward per season | all-season):")
    for key, (pl, pf, p0) in picks_log.items():
        P(f"   {key}: LOSO {pl} | fwd {pf} | all {p0}")
    passing = [k for k in res if res[k]["ok"]]
    P(f"\n  PASSING: {passing if passing else 'none'}")
    # per-season table for the picked versions
    P("\n  per season (LOSO-picked predictions), QB-out WR rows: MSE vs engine | all top-150 WR rows: weighted MSE, rank rho delta")
    show = [k for k in cands if "LOSO/fwd" in k]
    board = okN & top150 & WR
    def rho(q, m):
        gr = defaultdict(list)
        for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]))].append(i)
        rh = [np.corrcoef(rankdata(act[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]
        return float(np.mean(rh)) if rh else np.nan
    P("    | season | out rows | " + " | ".join(k.split(" [")[0] for k in show) + " |")
    wins = {k: 0 for k in show}
    for t in LOY:
        m = rowsN & (year == t); mb = board & (year == t)
        cells = []
        for k in show:
            q = cands[k][0]
            dm = 100 * (mse(q, m) / mse(N14, m) - 1); wins[k] += dm < 0
            dw = 100 * (np.average((q[mb] - act[mb]) ** 2, weights=wt[mb]) / np.average((N14[mb] - act[mb]) ** 2, weights=wt[mb]) - 1)
            cells.append(f"{dm:+.1f}% / {dw:+.2f}% / {rho(q, mb) - rho(N14, mb):+.3f}")
        P(f"    | {t} | {int(m.sum())} | " + " | ".join(cells) + " |")
    P("    | wins | | " + " | ".join(f"{wins[k]}/{len(LOY)}" for k in show) + " |")
    # first vs later starts
    P("\n  by start number (LOSO-picked), MSE vs engine:")
    for k in show:
        q = cands[k][0]
        P(f"   {k.split(' [')[0]:40s} 1st start {100 * (mse(q, rowsN & (nst == 0)) / mse(N14, rowsN & (nst == 0)) - 1):+.2f}% (n {int((rowsN & (nst == 0)).sum())}) | 2nd {100 * (mse(q, rowsN & (nst == 1)) / mse(N14, rowsN & (nst == 1)) - 1):+.2f}% | 3rd+ {100 * (mse(q, rowsN & (nst >= 2)) / mse(N14, rowsN & (nst >= 2)) - 1):+.2f}% (n {int((rowsN & (nst >= 2)).sum())}) | in-house {100 * (mse(q, rowsN & ~acq) / mse(N14, rowsN & ~acq) - 1):+.2f}% acquired {100 * (mse(q, rowsN & acq) / mse(N14, rowsN & acq) - 1):+.2f}%")
    # Cooper Rush list under each picked version (all-season pick)
    P("\n  CHECK 1 - the 10 worst backup team-weeks: dock under the all-season pick of each observation (vs flat)")
    worst = []
    for line in open(os.path.join(HERE, "_tmp", "qbout_acquired.log"), encoding="utf-8"):
        mm = re.match(r"\s+(\d{4}) (\w+)\s+W(\d+)\s+starter (\S+)\s+WR act\s+([\d.]+) / undocked\s+([\d.]+)", line)
        if mm: worst.append((int(mm.group(1)), mm.group(2), int(mm.group(3)), mm.group(4), float(mm.group(5)), float(mm.group(6))))
    fixed = [k for k in cands if "fixed" in k]
    for y, tm, w, qn, a, u in worst[:10]:
        rows = np.where(rowsN & (year == y) & (team == tm) & (wk == w))[0]
        if len(rows) == 0: P(f"    {y} {tm} W{w} {qn}: no graded rows"); continue
        i = rows[0]
        P(f"    {y} {tm:4s} W{w:2d} {qn:12s} start #{int(nst[i]) + 1} r1 {R[i, 0]:.2f} r2 {R[i, 1]:.2f} r3 {R[i, 2]:.2f} | act {a:5.1f} undocked {u:5.1f} flat {N14[rows].sum():5.1f} | " +
          " ".join(f"{k.split(' ')[0]}{'p' if 'prior' in k else ''} {cands[k][rows].sum():5.1f}{'<' if cands[k][rows].sum() <= N14[rows].sum() + 1e-9 else '>'}" for k in fixed))
    # 2026 readout: McCarthy path and PHI
    P("\n  CHECK 2 - 2026 readout (observed from the 2026 feature tables; prior = draft tier; k and b = the all-season picks of OBS1/OBS2)")
    pg26 = pd.read_parquet(os.path.join(SMC, "pg_2026.parquet")); tg26 = pd.read_parquet(os.path.join(SMC, "tg_2026.parquet"))
    for qname, tm_, reg_name in (("J.J. McCarthy", "NYG", "Jaxson Dart"), ("Jameis Winston", "NYG", "Jaxson Dart"), ("Tanner McKee", "PHI", "Jalen Hurts"), ("Cooper Rush", "ATL", "Michael Penix Jr.")):
        q = pg26[(pg26.name == qname) & (pg26.pos == "QB") & (pg26.att >= 10)].sort_values("week")
        reg = pg26[(pg26.name == reg_name) & (pg26.pos == "QB") & (pg26.att >= 10)]
        regrate = (reg.py.sum() * .04 + reg.ptd.sum() * 4 - reg["int"].sum()) / max(1.0, (reg.att + reg.sk).sum()) if len(reg) and (reg.att + reg.sk).sum() >= 60 else LEAGUE["fpp"]
        rd = PL.draft_round.get(PL[PL.display_name == qname].index[0], np.nan) if (PL.display_name == qname).any() else np.nan
        pr = 1.0 if (not np.isnan(rd) and rd <= 2) else 1.25
        P(f"    {qname} ({tm_}, draft rd {rd:.0f} -> prior {pr:.2f}); primary rate fpp/db {regrate:.3f} (league {LEAGUE['fpp']:.3f})")
        f = d = pts = imp = 0.0; n_ = 0
        for r in q.itertuples():
            tgr = tg26[(tg26.team == tm_) & (tg26.week == r.week)]
            f += r.py * .04 + r.ptd * 4 - r.int; d += r.att + r.sk; n_ += 1
            pts += float(tgr.pts.iloc[0]) if len(tgr) else 0; imp += float(tgr.implied.iloc[0]) if len(tgr) and not np.isnan(tgr.implied.iloc[0]) else 22.0
            r1 = (f / d) / regrate; r2 = pts / imp
            for k, b in ((1, 1.0), (2, 1.0), (3, 1.0)):
                w = n_ / (n_ + k)
                f1 = pr * np.clip(1 + b * (1 - (w * r1 + (1 - w))), .25, 2); f2 = pr * np.clip(1 + b * (1 - (w * r2 + (1 - w))), .25, 2)
                P(f"      after W{int(r.week)} (start #{n_}): r1 {r1:.2f} r2 {r2:.2f} | k{k} b{b:.0f}: dock mult OBS1 {f1:.2f} -> star dock {.15 * f1:.3f}, OBS2 {f2:.2f} -> {.15 * f2:.3f}")
    LOG.close()


if __name__ == "__main__":
    main()
