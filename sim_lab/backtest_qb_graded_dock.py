#!/usr/bin/env python3
"""
GRADED QB-OUT DOCK (Jack 2026-10-07: "can we maybe contextualize the actual qbs vs just starter and backup?").
Today a receiver whose team's regular QB is out gets a FLAT dock in the shadow (WR x.85 ADP <= 60, x.95 otherwise;
live has no dock and over-projects those WRs by 10%). Here the dock is graded by who the replacement is:
   r = replacement QB level / regular QB level   (Clay per-game numbers that season; backups off the sheet = 6/g)
   dock = r^b (b .25 .5 .75 1), with and without a floor / cap, vs the flat dock, vs no dock; WR and TE; ADP <= 60 / 61+.
Rows: WR/TE player-weeks where the team's regular starter (most frequent starter in the prior weeks) is NOT the
starter this week. Live form, 2019-25, next game (the dock is a this-week layer). LOYO + forward, ship bar 5/7 + 3/4.
Also: the same grading when the regular QB IS starting but is a different QB than most of the evidence (new starter
by trade / benching) - replacement level vs the evidence-weighted QB level. Log qb_graded_dock.log.
"""
import os, sys, warnings
from collections import defaultdict, Counter
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_qb_injury_usage as QI
NW = QI.NW; cal = QI.cal; YEARS = QI.YEARS; SK = QI.SK; FWD = QI.FWD; POS4 = QI.POS4
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "qb_graded_dock.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    X = QI.setup(); n = X["n"]
    act, year, wk, pos, g, adp, name, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["team"]
    F = X["F"]; finw = np.where(year <= 2020, 17, 18); final = wk == finw
    adpx = np.where(np.isnan(adp), 999.0, adp); top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    games, roster, starter, team_weeks = QI.build_games(X); ch = X["ch"]
    def qclay(Y, qb):
        c = (ch.get(str(Y)) or {}).get(qb)
        if not c: return 6.0
        gm = c.get("gm") or 0; W = 16 if Y <= 2020 else 17
        return max(3.0, (c.get("pts") or 0) / (gm if gm >= 4 else W))
    # per row: regular starter (most frequent in prior weeks, ties -> most recent), this week's starter, levels
    reg = [None] * n; cur = [None] * n; ratio = np.full(n, np.nan); outrow = np.zeros(n, bool); newrow = np.zeros(n, bool)
    for i in range(n):
        if pos[i] not in ("WR", "TE") or not team[i]: continue
        Y = int(year[i]); tm_ = team[i]
        prior_w = [w for w in team_weeks.get((Y, tm_), []) if w < wk[i]]
        s_now = starter.get((Y, tm_, int(wk[i])))
        if s_now is None: continue
        if not prior_w:
            continue
        cnt = Counter(starter[(Y, tm_, w)] for w in prior_w); top = max(cnt.values()); cands = [q for q, c in cnt.items() if c == top]
        r_ = cands[0] if len(cands) == 1 else max(cands, key=lambda q: max(w for w in prior_w if starter[(Y, tm_, w)] == q))
        reg[i] = r_; cur[i] = s_now
        if s_now != r_:
            ratio[i] = qclay(Y, s_now) / max(qclay(Y, r_), 3.0)
            # out (the regular is not starting) vs new (the regular has been replaced for 2+ straight weeks already)
            last2 = [starter[(Y, tm_, w)] for w in prior_w[-2:]]
            newrow[i] = len(last2) == 2 and all(q == s_now for q in last2)
            outrow[i] = not newrow[i]
    # market grade of the replacement: this week's team implied total vs the median implied total in the regular's starts (this player's rows)
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = X["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    implied = np.where(has, C["implied"].values[np.maximum(idx, 0)], np.nan).astype(float)
    rowof = {(name[i], pos[i], int(year[i]), int(wk[i])): i for i in range(n)}
    vratio = np.full(n, np.nan)
    for i in np.where(~np.isnan(ratio))[0]:
        Y = int(year[i]); tm_ = team[i]
        if np.isnan(implied[i]): continue
        regw = [w for w in team_weeks.get((Y, tm_), []) if w < wk[i] and starter.get((Y, tm_, w)) == reg[i]]
        vals = [implied[rowof[(name[i], pos[i], Y, w)]] for w in regw if (name[i], pos[i], Y, w) in rowof and not np.isnan(implied[rowof[(name[i], pos[i], Y, w)]])]
        if len(vals) >= 2: vratio[i] = implied[i] / max(np.median(vals), 10.0)
    RECV = np.isin(pos, ("WR", "TE")); okN = (g >= 1) & ~final & ~X["inh"]
    base_rows = RECV & okN & (outrow | newrow) & ~np.isnan(ratio)
    P(f"rows: regular QB not starting this week (WR/TE, 1+ games): {int((RECV & okN & outrow).sum()):,} | replacement already in for 2+ weeks: {int((RECV & okN & newrow).sum()):,}")
    rr = ratio[base_rows]
    P(f"replacement / regular level: mean {np.nanmean(rr):.2f}, quartiles {np.nanpercentile(rr, 25):.2f} / {np.nanpercentile(rr, 50):.2f} / {np.nanpercentile(rr, 75):.2f}; share with a better replacement (r > 1): {np.mean(rr > 1):.2f}")
    BASE = np.maximum(0.0, QI.live_base(X, X["ppg"], g.astype(float), X["xfp"], X["snap"])[0] * X["chain"] + QI.live_base(X, X["ppg"], g.astype(float), X["xfp"], X["snap"])[1])
    mse = lambda p, m: float(np.mean((p[m] - act[m]) ** 2)) if m.any() else np.nan
    wmse = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    # descriptive: actual / live by replacement-level bucket
    P("\n--- actual / live by replacement level (regular QB out this week), WR then TE ---")
    for ps in ("WR", "TE"):
        m0 = RECV & okN & outrow & (pos == ps); cells = []
        for lo, hi, lab in ((0, 0.5, "r < .5"), (0.5, 0.7, ".5-.7"), (0.7, 0.9, ".7-.9"), (0.9, 1.1, ".9-1.1"), (1.1, 9, "1.1+ (better)")):
            m = m0 & (ratio >= lo) & (ratio < hi)
            if m.sum() >= 15: cells.append(f"{lab}: n{int(m.sum())} act/live {act[m].sum()/BASE[m].sum():.3f}")
        P(f"  {ps} out rows n{int(m0.sum())} act/live {act[m0].sum()/BASE[m0].sum():.3f} | " + " | ".join(cells))
        for lab, mm in (("ADP <= 60", m0 & (adpx <= 60)), ("ADP 61-150", m0 & (adpx > 60) & (adpx <= 150)), ("ADP 151+", m0 & (adpx > 150))):
            if mm.sum() >= 15: P(f"      {lab}: n{int(mm.sum())} act/live {act[mm].sum()/BASE[mm].sum():.3f}  r<.8 {act[mm & (ratio < .8)].sum()/max(1e-9, BASE[mm & (ratio < .8)].sum()):.3f} (n{int((mm & (ratio < .8)).sum())})  r>=.8 {act[mm & (ratio >= .8)].sum()/max(1e-9, BASE[mm & (ratio >= .8)].sum()):.3f} (n{int((mm & (ratio >= .8)).sum())})")
        m1 = RECV & okN & newrow & (pos == ps)
        if m1.sum() >= 15: P(f"  {ps} replacement already in 2+ weeks n{int(m1.sum())} act/live {act[m1].sum()/BASE[m1].sum():.3f} | r<.8 {act[m1 & (ratio < .8)].sum()/max(1e-9, BASE[m1 & (ratio < .8)].sum()):.3f} (n{int((m1 & (ratio < .8)).sum())}) r>=.8 {act[m1 & (ratio >= .8)].sum()/max(1e-9, BASE[m1 & (ratio >= .8)].sum()):.3f}")
    # variants (this-week multiplier on the live number)
    def dock(mult_fn, scope, r=None):
        rr_ = ratio if r is None else r
        out = BASE.copy(); m = scope & ~np.isnan(rr_)
        out[m] = BASE[m] * mult_fn(rr_[m], adpx[m], pos[m]); return out
    rc = lambda r: np.clip(r, 0.4, 1.25)
    V = {"flat .85 / .95 (shadow today)": lambda r, a, p: np.where(a <= 60, 0.85, 0.95),
         "flat .90 everyone": lambda r, a, p: np.full(len(r), 0.90),
         "graded r^.25": lambda r, a, p: rc(r) ** 0.25, "graded r^.5": lambda r, a, p: rc(r) ** 0.5, "graded r^.75": lambda r, a, p: rc(r) ** 0.75, "graded r^1": lambda r, a, p: rc(r),
         "graded r^.5, capped at 1 (never a boost)": lambda r, a, p: np.minimum(1.0, rc(r) ** 0.5),
         "graded r^.5 x flat .95": lambda r, a, p: 0.95 * rc(r) ** 0.5,
         "flat .85/.95 if r < .8 else none": lambda r, a, p: np.where(r < 0.8, np.where(a <= 60, 0.85, 0.95), 1.0),
         "flat .85/.95 if r < .8 else x.97": lambda r, a, p: np.where(r < 0.8, np.where(a <= 60, 0.85, 0.95), 0.97)}
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    for title, scope in (("REGULAR QB OUT THIS WEEK (WR + TE)", RECV & outrow), ("REGULAR QB OUT, WR only", (pos == "WR") & outrow), ("REGULAR QB OUT, TE only", (pos == "TE") & outrow),
                         ("REPLACEMENT ALREADY IN 2+ WEEKS (WR + TE)", RECV & newrow), ("OUT or NEW (all QB-change weeks, WR + TE)", RECV & (outrow | newrow))):
        tm = scope & okN & ~np.isnan(ratio)
        if tm.sum() < 60: P(f"\n=== {title}: too few rows ({int(tm.sum())})"); continue
        preds = {"off": BASE, **{k: dock(f, scope) for k, f in V.items()}}
        VV = {"VEGAS graded v^.5 (team implied now / with the regular)": lambda r, a, p: np.clip(r, 0.6, 1.3) ** 0.5, "VEGAS graded v^1": lambda r, a, p: np.clip(r, 0.6, 1.3),
              "VEGAS graded v^1, capped at 1": lambda r, a, p: np.minimum(1.0, np.clip(r, 0.6, 1.3)), "VEGAS v^1 x Clay-level r^.25": None}
        for k, f in VV.items():
            if f is None: preds[k] = dock(lambda r, a, p: np.clip(r, 0.6, 1.3), scope, vratio); mm = scope & ~np.isnan(ratio) & ~np.isnan(vratio); preds[k][mm] = preds[k][mm] * rc(ratio[mm]) ** 0.25
            else: preds[k] = dock(f, scope, vratio)
        names = list(preds)
        mv = tm & ~np.isnan(vratio); P(f"    (Vegas ratio available on {int(mv.sum())} of {int(tm.sum())} rows; mean {np.nanmean(vratio[mv]):.3f}; act/live where v < .9: {act[mv & (vratio < .9)].sum()/max(1e-9, BASE[mv & (vratio < .9)].sum()):.3f} n{int((mv & (vratio < .9)).sum())}, v >= .9: {act[mv & (vratio >= .9)].sum()/max(1e-9, BASE[mv & (vratio >= .9)].sum()):.3f} n{int((mv & (vratio >= .9)).sum())})")
        P(f"\n=== {title}: rows {int(tm.sum()):,}, actual / live {act[tm].sum()/BASE[tm].sum():.3f} (top-150 rows {int((tm & top150).sum())}) ===")
        for k in names[1:]:
            wins = sum(1 for y in YEARS if (tm & (year == y)).sum() >= 8 and mse(preds[k], tm & (year == y)) < mse(BASE, tm & (year == y)) - 1e-12)
            t150 = tm & top150
            P(f"    {k:42s} all rows {100*(mse(preds[k], tm)/mse(BASE, tm)-1):+6.2f}% ({wins}/7) | top-150 wtd {100*(wmse(preds[k], t150)/wmse(BASE, t150)-1):+6.2f}% | act/pred {act[tm].sum()/preds[k][tm].sum():.3f}")
        pick = lambda yrs: min(names, key=lambda k: mse(preds[k], tm & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = BASE.copy()
            for tr_, te in folds:
                k = pick(tr_); picks.append(k); m = year == te; pr[m] = preds[k][m]; wins += mse(preds[k], tm & m) < mse(BASE, tm & m) - 1e-12
            tem = np.isin(year, [te for _, te in folds])
            return pr, 100 * (mse(pr, tm & tem) / mse(BASE, tm & tem) - 1), wins, picks
        lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
        okk = best != "off" and lo[1] < -0.3 and lo[2] >= 5 and fw[1] < 0 and fw[2] >= 3
        P(f"    LOYO {lo[1]:+.2f}% {lo[2]}/7 picks {lo[3]}")
        P(f"    FWD  {fw[1]:+.2f}% {fw[2]}/4 picks {fw[3]}")
        P(f"    -> {'PASS: ' + best if okk else 'FAIL'}  (best fixed: {best})")
    P("\nLimitations: QB level = Clay's preseason per-game number (backups off the sheet = 6/g); the replacement is the game's actual top passer (the engine would use the depth chart); regular = most frequent prior starter.")
    LOG.close()


if __name__ == "__main__":
    main()
