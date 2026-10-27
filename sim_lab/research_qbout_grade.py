#!/usr/bin/env python3
"""
BACKUP-QB GRADE DOCK (Jack 2026-10-27 via the scratch-model queue: "a grade makes more sense, backups are not equal").
PROPOSE ONLY. Harness (B) = the 10-27 study's rows (research_qbout_acquired.py data block, exec'd here with its own log
left untouched): engine base X_cache 2012-25, next game = SN.shadow (carries the flat dock), undocked = / (1 - d_eng),
1,111 WR QB-out next-game rows.

Grade candidates (per the brief):
  (a) backup fpp/db or EPA/db vs the primary      -> ALREADY REJECTED 10-23 (project_backup_qb_rating: ridge rating, gap-only,
  (b) backup career YPA + TD rate vs replacement      backup-absolute, flat x rating tilt; 10-20 dEPA on harness B) - NOT re-run.
  (c) preseason per-start projection ratio (Clay / pool seasonPoints)  -> checked for gradeability (2019-25 only; Clay gives
      pure backups scraps, not a per-start rate).
  (d) draft capital + career starts tier: "real" = day-1/2 pick or 16+ career starts (2012+ pbp), else "replacement".
      Dock shapes: real x f_real (.5 / .75) and replacement x f_rep (1.0 / 1.25) on the flat dock; starts-only and draft-only
      tiers; linear-in-starts.  Fit LOYO / forward with the 10-27 grade() (bar: LOYO < -0.3%, 70% folds, fwd < 0 and 70%,
      top-150 <= +0.1%).
Required checks: the 10 worst backup team-weeks (Cooper Rush list), 2026 NYG McCarthy / PHI backup, in-house vs acquired.
Log: _tmp/qbout_grade.log
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
block = src[start:end].replace('os.path.join(HERE, "_tmp", "qbout_acquired.log")', 'os.path.join(HERE, "_tmp", "qbout_grade.log")')
exec(block)   # defines CACHE, PBP, LOG, P, YEARS, LOY, FWY, nt, Q, REPL, LEAGUE, QG, QSEASON, TW, TWD, STARTER, WRX, W1, qb_state, qbs, xfp_hold, grade, ratio_line
PL = pd.read_csv(os.path.join(PBP, "players.csv"), low_memory=False, usecols=["gsis_id", "display_name", "draft_round", "draft_pick", "rookie_season"]).drop_duplicates("gsis_id").set_index("gsis_id")
REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"


def career_starts(pid, y, wk):
    """starts (15+ dropbacks) before this game, 2012+ play-by-play (a floor for pre-2012 veterans)"""
    s = Q[(Q.pid.astype(str) == pid) & (Q.db >= 15)]
    return int(((s.season < y) | ((s.season == y) & (s.week < wk))).sum())


def main():
    P(f"backup-QB GRADE dock study {pd.Timestamp.now():%Y-%m-%d %H:%M}  {BX.describe()}")
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
    st = [None] * n; acq = np.zeros(n, bool); known = np.zeros(n, bool); starts = np.full(n, np.nan); rnd = np.full(n, np.nan); bq = [None] * n
    cs_cache = {}
    for i in np.where(WR & (qbN | qbo_c))[0]:
        s = qbs(int(year[i]), team[i], int(wk[i]))
        if s is None: continue
        st[i] = s; known[i] = True; acq[i] = s["acq"]; bq[i] = s["stq"]
        k = (s["stq"], int(year[i]), int(wk[i]))
        if k not in cs_cache: cs_cache[k] = career_starts(s["stq"], int(year[i]), int(wk[i]))
        starts[i] = cs_cache[k]
        rnd[i] = PL.draft_round.get(s["stq"], np.nan) if s["stq"] in PL.index else np.nan
    rowsN = WR & qbN & okN & known
    P(f"  WR next-game rows with the regular QB out: {int((WR & qbN & okN).sum())}; backup known {int(rowsN.sum())}; acquired {int((rowsN & acq).sum())}")
    real_draft = rnd <= 2; real_starts = starts >= 16
    real = real_draft | real_starts
    P("\n  (a)/(b) performance-based grades (fpp/db, EPA/db, YPA + TD vs replacement, gap to the primary): NOT re-run - rejected 10-23 in "
      "project_backup_qb_rating (ridge rating, backup-absolute, gap-only, starter-quality cells, flat x rating tilt; 0-8/13 LOSO, forward fails) "
      "and 10-20 (dEPA scaling on harness B, 0-5/7). Four failures; the descriptive finding there: once shrunk, backups are all near replacement.")
    # ---- (c) Clay per-start ratio: gradeability
    P("\n  (c) preseason projection ratio (Clay seasonPoints, 2019-25 only - no Clay before 2019):")
    ch = json.load(open(os.path.join(REPO, "data", "clay_history.json"), encoding="utf-8"))
    nm_of = lambda q: PL.display_name.get(q, None) if q in PL.index else None
    def clay_pts(y, q):
        nmq = nm_of(q)
        r = ch.get(str(y), {}).get(nmq or "", None)
        return float(r["pts"]) if r and r.get("pos") == "QB" else np.nan
    cb = np.full(n, np.nan); cp = np.full(n, np.nan)
    for i in np.where(rowsN & (year >= 2019))[0]:
        s = st[i]; cb[i] = clay_pts(int(year[i]), s["stq"]); cp[i] = clay_pts(int(year[i]), s["reg"]) if s["reg"] else np.nan
    m19 = rowsN & (year >= 2019)
    P(f"    rows 2019-25 {int(m19.sum())}: backup Clay pts known {int((m19 & ~np.isnan(cb)).sum())}, median backup pts {np.nanmedian(cb[m19]):.0f} vs primary {np.nanmedian(cp[m19]):.0f}; "
      f"backup >= 40 pts (a projected starter-level line) {int((m19 & (cb >= 40)).sum())} rows, >= 100 pts {int((m19 & (cb >= 100)).sum())} rows")
    for lo, hi, lab in ((0, 20, "backup Clay < 20 pts"), (20, 40, "20-40"), (40, 100, "40-100"), (100, 9999, "100+ (a real starter in the sheet)")):
        m = m19 & (cb >= lo) & (cb < hi)
        ratio_line(f"  {lab}", m, act, undN, N14, name, year)
    P("    -> Clay's sheet projects backups as roster scraps (gm 17, 2-30 pts): the per-start rate does not exist there, and the engine's QB window "
      "already treats a backup as 85% of the leader. Only the 40+ cells carry a grade and they are too small to fit. UNGRADEABLE as a general rule.")
    # ---- (d) draft capital + career starts
    P("\n  (d) DRAFT CAPITAL + CAREER STARTS tier (known before kickoff; starts = 15+ dropback games in 2012+ pbp)")
    for lab, m in (("all QB-out rows", rowsN), ("REAL (rd 1-2 or 16+ starts)", rowsN & real), ("replacement (else)", rowsN & ~real),
                   ("day-1/2 pick", rowsN & real_draft), ("later / undrafted", rowsN & ~real_draft & ~np.isnan(rnd)), ("16+ starts", rowsN & real_starts), ("< 16 starts", rowsN & ~real_starts),
                   ("0-3 starts", rowsN & (starts <= 3)), ("4-15 starts", rowsN & (starts >= 4) & (starts < 16)), ("16-47 starts", rowsN & (starts >= 16) & (starts < 48)), ("48+ starts", rowsN & (starts >= 48)),
                   ("REAL, ADP 1-60", rowsN & real & star), ("replacement, ADP 1-60", rowsN & ~real & star), ("REAL, other", rowsN & real & ~star), ("replacement, other", rowsN & ~real & ~star),
                   ("in-house REAL", rowsN & ~acq & real), ("in-house replacement", rowsN & ~acq & ~real), ("ACQUIRED REAL", rowsN & acq & real), ("ACQUIRED replacement", rowsN & acq & ~real)):
        ratio_line(lab, m, act, undN, N14, name, year)
    def build(f):
        return np.where(WR & qbN, undN * (1 - d_eng * f), N14)
    cands = {}; chg = {}
    tiers = {"real = rd1-2 or 16+ starts": real, "real = 16+ starts": real_starts, "real = rd1-2": real_draft, "real = rd1-2 AND 16+ starts": real_draft & real_starts}
    for tl, tmask in tiers.items():
        for fr, fp in ((0.5, 1.0), (0.75, 1.0), (0.5, 1.25), (0.75, 1.25), (1.0, 1.25)):
            f = np.where(tmask, fr, fp); lab = f"{tl}: real x{fr:.2f} rep x{fp:.2f}"
            cands[lab] = build(f); chg[lab] = rowsN & (np.abs(f - 1) > 1e-9)
    for k in (0.25, 0.5):
        f = np.clip(1 - k * np.minimum(np.nan_to_num(starts, nan=0.0), 48) / 48, 0.5, 1.0); lab = f"linear in starts k{k:.2f}"
        cands[lab] = build(f); chg[lab] = rowsN & (np.abs(f - 1) > 1e-9)
    f = np.clip(1 + 0.25 - 0.5 * np.minimum(np.nan_to_num(starts, nan=0.0), 48) / 48, 0.75, 1.25); lab = "linear in starts, rep x1.25 -> vet x.75"
    cands[lab] = build(f); chg[lab] = rowsN & (np.abs(f - 1) > 1e-9)
    cands["REF: no dock"] = build(np.zeros(n)); chg["REF: no dock"] = rowsN
    res = grade("next game vs the engine (flat dock)", N14, cands, rowsN, okN, act, year, wt, top150, pos, wk, star, chg)
    best = min(res, key=lambda k: res[k]["dL"])
    passing = [k for k in res if res[k]["ok"]]
    P(f"\n  PASSING candidates: {passing if passing else 'none'}")
    P(f"\n  best LOYO candidate: {best}  ({res[best]['dL']:+.2f}% {res[best]['wl']}/{res[best]['nl']} folds, fwd {res[best]['dF']:+.2f}% {res[best]['wf']}/{res[best]['nf']}, top-150 {res[best]['dW']:+.2f}%, rank {res[best]['dR']:+.4f}) -> {'PASS' if res[best]['ok'] else 'FAIL'}")
    P("    fold table (best): " + "  ".join(f"{t} {100 * (np.mean((cands[best][rowsN & (year == t)] - act[rowsN & (year == t)]) ** 2) / np.mean((N14[rowsN & (year == t)] - act[rowsN & (year == t)]) ** 2) - 1):+.2f}% (n{int((rowsN & (year == t)).sum())})" for t in LOY if (rowsN & (year == t)).sum() >= 5))
    # per-season table for two headline tiers
    P("\n  per season, QB-out WR rows: MSE vs engine (flat) | all top-150 WR rows: weighted MSE vs engine, rank rho delta")
    board = okN & top150 & WR
    def rho(q, m):
        gr = defaultdict(list)
        for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]))].append(i)
        rh = [np.corrcoef(rankdata(act[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]
        return float(np.mean(rh)) if rh else np.nan
    show = [best] + passing + ["real = rd1-2 or 16+ starts: real x0.50 rep x1.00", "REF: no dock"]
    show = list(dict.fromkeys(show))
    P("    | season | out rows | " + " | ".join(show) + " |")
    for t in LOY:
        m = rowsN & (year == t); mb = board & (year == t)
        if m.sum() < 5: continue
        cells = []
        for k in show:
            q = cands[k]
            dm = 100 * (np.mean((q[m] - act[m]) ** 2) / np.mean((N14[m] - act[m]) ** 2) - 1)
            dw = 100 * (np.average((q[mb] - act[mb]) ** 2, weights=wt[mb]) / np.average((N14[mb] - act[mb]) ** 2, weights=wt[mb]) - 1)
            cells.append(f"{dm:+.1f}% / {dw:+.2f}% / {rho(q, mb) - rho(N14, mb):+.3f}")
        P(f"    | {t} | {int(m.sum())} | " + " | ".join(cells) + " |")
    def pairs(q, m):
        gr = defaultdict(list)
        for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]))].append(i)
        ok = tot = 0
        for ix in gr.values():
            ix = np.array(ix)
            for a_ in range(len(ix)):
                for b_ in range(a_ + 1, len(ix)):
                    x, y_ = ix[a_], ix[b_]
                    if abs(q[x] - q[y_]) < 1.0 or act[x] == act[y_]: continue
                    tot += 1; ok += (q[x] > q[y_]) == (act[x] > act[y_])
        return ok / tot if tot else np.nan, tot
    P("\n  QB-out WR rows: within-week pair accuracy (pairs among the out rows themselves) and Spearman, pooled 2013-25")
    for k in ["engine (flat)"] + show:
        q = N14 if k == "engine (flat)" else cands[k]
        pa, nt_ = pairs(q, rowsN)
        gr = defaultdict(list)
        for i in np.where(rowsN)[0]: gr[(int(year[i]), int(wk[i]))].append(i)
        rh = [np.corrcoef(rankdata(act[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 5]
        P(f"    {k:52s} pair acc {pa:.3f} (n {nt_})  Spearman {np.mean(rh):.3f} ({len(rh)} team-weeks with 5+ rows)")
    # ---- check 1: the 10 worst backup team-weeks
    P("\n  CHECK 1 - the 10 worst backup team-weeks from the 10-27 study: tier and dock under the best candidate vs flat")
    worst = []
    for line in open(os.path.join(HERE, "_tmp", "qbout_acquired.log"), encoding="utf-8"):
        mm = re.match(r"\s+(\d{4}) (\w+)\s+W(\d+)\s+starter (\S+)\s+WR act\s+([\d.]+) / undocked\s+([\d.]+)", line)
        if mm: worst.append((int(mm.group(1)), mm.group(2), int(mm.group(3)), mm.group(4), float(mm.group(5)), float(mm.group(6))))
    fbest = None
    for k in cands:
        if k == best: break
    for cand in [best] + passing:
        P(f"   candidate: {cand}")
        for y, tm, w, qn, a, u in worst[:10]:
            rows = np.where(rowsN & (year == y) & (team == tm) & (wk == w))[0]
            if len(rows) == 0: P(f"    {y} {tm} W{w} {qn}: no graded rows"); continue
            i = rows[0]; s = st[i]
            fl = N14[rows].sum(); cb_ = cands[cand][rows].sum()
            P(f"    {y} {tm:4s} W{w:2d} {qn:14s} rd {rnd[i]:.0f} starts {starts[i]:.0f} {'REAL' if real[i] else 'repl'} {'acq' if acq[i] else 'in-house'} | WR act {a:5.1f} undocked {u:5.1f} flat {fl:5.1f} cand {cb_:5.1f} -> {'docks harder/equal' if cb_ <= fl + 1e-9 else 'DOCKS LESS'}")
    P("    2026 W2 ATL Cooper Rush: rd 7 (2017 UDFA-class late pick / undrafted), career starts 2012+ = " + str(career_starts(str(PL[PL.display_name == 'Cooper Rush'].index[0]), 2026, 2) if (PL.display_name == 'Cooper Rush').any() else 'n/a') + " -> tier per best candidate below")
    # ---- check 2: 2026 NYG / PHI
    P("\n  CHECK 2 - 2026 NYG (McCarthy for Dart) and PHI (Hurts out)")
    pg26 = pd.read_parquet(os.path.join(HERE, "scratch_model", "cache", "pg_2026.parquet"))
    for qname in ("J.J. McCarthy", "Tanner McKee", "Cooper Rush", "Jaxson Dart", "Jalen Hurts"):
        hit = PL[PL.display_name == qname]
        if len(hit) == 0: P(f"    {qname}: not in players.csv"); continue
        q = str(hit.index[0]); st12 = career_starts(q, 2026, 1); st26 = int((pg26[(pg26.pid == q) & (pg26.att >= 10)]).shape[0])
        P(f"    {qname:14s} draft rd {hit.draft_round.iloc[0]} pick {hit.draft_pick.iloc[0]} | starts 2012-25 {st12} + 2026 {st26} = {st12 + st26} -> {'REAL' if (hit.draft_round.iloc[0] <= 2 or st12 + st26 >= 16) else 'replacement'} under the rd1-2 / 16+ tier")
    snap = json.load(open(os.path.join(HERE, "data", "snapshots", "simlab_snapshot_w7.json"), encoding="utf-8"))
    for p in snap["players"]:
        if p.get("pos") == "WR" and p.get("tm") in ("NYG", "PHI") and "+qbout" in (p.get("ncSrc") or ""):
            d = 0.15 if "+qboutS" in p["ncSrc"] else 0.05; nc = p.get("ncMean"); und = nc / (1 - d)
            P(f"    W7 lock {p['name']:18s} {p['tm']} ncMean {nc:.2f} (dock {d:.2f}, undocked {und:.2f}) -> real x.5 {und * (1 - d * .5):.2f}, rep x1.25 {und * (1 - d * 1.25):.2f}, live mean {p.get('mean'):.2f}")
    # ---- check 3: in-house vs acquired under the candidates
    P("\n  CHECK 3 - in-house vs acquired, MSE vs engine on each subset:")
    for lab, m in (("in-house", rowsN & ~acq), ("acquired", rowsN & acq)):
        P(f"    {lab:9s} n {int(m.sum())}: " + "  ".join(f"{k.split(':')[0][:22]}{k.split(':')[1] if ':' in k else ''} {100 * (np.mean((cands[k][m] - act[m]) ** 2) / np.mean((N14[m] - act[m]) ** 2) - 1):+.2f}%" for k in show))
    # ---- check 4: 2026 W1-7 QB-out WR rows (live locks), tier of the actual starter that week
    P("\n  CHECK 4 - 2026 W1-7 QB-out WR rows from the live locks (ncMean carries the flat dock): tier of the week's starter, act vs flat vs rd1-2 x1.25 rule")
    bt = pd.read_csv(os.path.join(HERE, "scratch_model", "out", "bt_rows.csv"))
    actmap = {(int(w), k): a for w, k, a in zip(bt.week, bt.key, bt.act)}
    sys.path.insert(0, os.path.join(HERE, 'scratch_model')); from features import norm as fnorm
    starters26 = {}
    for r in pg26[(pg26.pos == "QB") & (pg26.att >= 10)].sort_values("att", ascending=False).itertuples():
        starters26.setdefault((r.team, int(r.week)), (r.pid, r.name))
    rows26 = []
    for w in range(1, 8):
        snap = json.load(open(os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{w}.json"), encoding="utf-8"))
        for p in snap["players"]:
            if p.get("pos") != "WR" or "+qbout" not in (p.get("ncSrc") or "") or not p.get("ncMean"): continue
            a = actmap.get((w, fnorm(p["name"])))
            if a is None: continue
            q = starters26.get((p["tm"], w))
            if not q: continue
            d = 0.15 if "+qboutS" in p["ncSrc"] else 0.05; nc = p["ncMean"]; und = nc / (1 - d)
            hit = PL.loc[q[0]] if q[0] in PL.index else None
            rd_ = float(hit.draft_round) if hit is not None and not pd.isna(hit.draft_round) else np.nan
            st_ = career_starts(q[0], 2026, w) + int(((pg26.pid == q[0]) & (pg26.att >= 10) & (pg26.week < w)).sum())
            isreal = (rd_ <= 2) if not np.isnan(rd_) else False
            rows26.append(dict(wk=w, name=p["name"], tm=p["tm"], qb=q[1], rd=rd_, starts=st_, real=isreal, act=a, nc=nc, und=und, cand=und * (1 - d * (1.0 if isreal else 1.25)), live=p.get("mean")))
    R = pd.DataFrame(rows26)
    if len(R):
        for lab, m in (("all", np.ones(len(R), bool)), ("real (rd 1-2)", R.real.values), ("replacement", ~R.real.values)):
            x = R[m]
            if len(x) == 0: continue
            P(f"    {lab:14s} n {len(x):3d}  act/undocked {x.act.sum() / x.und.sum():.3f}  act/flat {x.act.sum() / x.nc.sum():.3f}  act/cand {x.act.sum() / x.cand.sum():.3f}  MSE flat {np.mean((x.nc - x.act) ** 2):.2f} cand {np.mean((x.cand - x.act) ** 2):.2f}  QBs {sorted(set(x.qb))}")
        for r in R.sort_values(["wk", "tm"]).itertuples():
            if r.nc >= 5: P(f"      W{r.wk} {r.name:18s} {r.tm} QB {r.qb:12s} rd {r.rd:.0f} starts {r.starts:2d} {'REAL' if r.real else 'repl'} | act {r.act:5.1f} flat {r.nc:5.2f} cand {r.cand:5.2f} live {r.live:5.2f}")
    LOG.close()


if __name__ == "__main__":
    main()
