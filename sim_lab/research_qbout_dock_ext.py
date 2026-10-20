#!/usr/bin/env python3
"""
BACKUP-QB WR DOCK, re-test with a bigger sample (Jack 2026-10-20: Nabers x.85 / DeVonta Smith "too low"; both on qboutS).

Stand-alone WR harness built straight from nflverse play-by-play (E:/MyFantasyFootball/pbp_cache/play_by_play_<yr>.csv.gz), so it
reaches back before the Clay / ADP era: priors from 2016 on, graded seasons 2017-2025 (9). The engine's shadow harness (2019-25) is
checked separately (research_qbout_dock_shadow.py).

Base (QB-unaware, shadow-shaped): prior = .8-shrunk last-season half-PPR PPG (6+ games, else the WR mean x .7), evidence = season to
date, lam x xFP/g + (1 - lam) x points/g (lam = max(.25, 1 - .08 (g - 1))), prior weight 8; x Vegas (1 + .25 (implied - week avg) /
week avg, from the pbp spread / total). One global level fitted on QB-IN rows (seasons out).
Regular QB = the team's most frequent starter in its games so far this season (2+ starts). QB OUT game = a different starter AND the
regular threw no pass in that game. Injury-confirmed (2019+) = the regular is on that week's nflverse injury report or he never starts
again (season-ending); benchings are the noise left in 2017-18.
Star definitions: preseason prior rank (top 25 WR ~ engine ADP <= 60), in-season target share to date, in-season xFP/g rank.
Targets: NEXT GAME (act) and REST OF SEASON (mean of the remaining games, final week out, 4+ left, checkpoints after 3-10 games).
ROS prediction under a dock applies it to each future week the regular is out (ex post, like the engine's known season-long outs).
Log qbout_dock_ext.log.
"""
import os, sys, math
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); PBP = r"E:/MyFantasyFootball/pbp_cache"
CACHE = os.path.join(HERE, "_tmp", "qbx_cache"); os.makedirs(CACHE, exist_ok=True)
LOG = open(os.path.join(HERE, "qbout_dock_ext.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()
YRS_ALL = list(range(2016, 2026)); YEARS = list(range(2017, 2026)); FWD = (2022, 2023, 2024, 2025)
COLS = ["game_id", "season", "week", "season_type", "posteam", "home_team", "away_team", "spread_line", "total_line", "passer_player_id", "passer_player_name",
        "receiver_player_id", "receiver_player_name", "rusher_player_id", "pass_attempt", "sack", "complete_pass", "receiving_yards", "rushing_yards", "pass_touchdown",
        "rush_touchdown", "air_yards", "yardline_100", "cp", "xyac_mean_yardage", "fumble_lost", "fumbled_1_player_id", "two_point_attempt", "epa", "qb_dropback", "play_type"]

def season_tables(y):
    fp = os.path.join(CACHE, f"wr_{y}.pkl")
    if os.path.exists(fp): return pd.read_pickle(fp)
    d = pd.read_csv(os.path.join(PBP, f"play_by_play_{y}.csv.gz"), usecols=COLS, low_memory=False)
    d = d[(d.season_type == "REG") & (d.two_point_attempt != 1)]
    # game lines -> team implied
    g = d.drop_duplicates("game_id")[["game_id", "week", "home_team", "away_team", "spread_line", "total_line"]]
    imp = {}
    for r in g.itertuples():
        if pd.notna(r.total_line) and pd.notna(r.spread_line):
            imp[(r.game_id, r.home_team)] = r.total_line / 2 + r.spread_line / 2; imp[(r.game_id, r.away_team)] = r.total_line / 2 - r.spread_line / 2
    # starters: most dropbacks (pass attempts + sacks) by passer id
    pa = d[(d.pass_attempt == 1) | (d.sack == 1)].dropna(subset=["passer_player_id"])
    qb = pa.groupby(["game_id", "week", "posteam", "passer_player_id", "passer_player_name"]).agg(db=("pass_attempt", "size"), epa=("epa", "sum")).reset_index()
    st = qb.sort_values("db", ascending=False).drop_duplicates(["game_id", "posteam"])
    team_tgt = d[d.receiver_player_id.notna() & (d.pass_attempt == 1)].groupby(["game_id", "posteam"]).size()
    # xTD per target by yardline bin (season league rate)
    t = d[d.receiver_player_id.notna() & (d.pass_attempt == 1)].copy()
    t["ybin"] = pd.cut(t.yardline_100, [0, 5, 10, 20, 40, 100], include_lowest=True)
    tdr = t.groupby("ybin", observed=False).pass_touchdown.mean()
    t["xtd"] = t.ybin.map(tdr).astype(float).fillna(0.03)
    cpm = t.cp.mean()
    t["xfp"] = t.cp.fillna(cpm) * (0.5 + 0.1 * (t.air_yards.fillna(8) + t.xyac_mean_yardage.fillna(4))) + 6 * t.xtd
    rec = t.groupby(["game_id", "week", "posteam", "receiver_player_id", "receiver_player_name"]).agg(tgt=("pass_attempt", "size"), rec=("complete_pass", "sum"),
          ry=("receiving_yards", "sum"), rtd=("pass_touchdown", "sum"), xfp=("xfp", "sum"), ay=("air_yards", "sum")).reset_index().rename(columns={"receiver_player_id": "pid", "receiver_player_name": "pname"})
    ru = d[d.rusher_player_id.notna() & (d.play_type == "run")].groupby(["game_id", "rusher_player_id"]).agg(rush_y=("rushing_yards", "sum"), rush_td=("rush_touchdown", "sum")).reset_index().rename(columns={"rusher_player_id": "pid"})
    fl = d[d.fumble_lost == 1].groupby(["game_id", "fumbled_1_player_id"]).size().reset_index(name="fl").rename(columns={"fumbled_1_player_id": "pid"})
    rec = rec.merge(ru, on=["game_id", "pid"], how="left").merge(fl, on=["game_id", "pid"], how="left").fillna({"rush_y": 0, "rush_td": 0, "fl": 0})
    rec["pts"] = 0.5 * rec.rec + 0.1 * (rec.ry + rec.rush_y) + 6 * (rec.rtd + rec.rush_td) - 2 * rec.fl
    rec["team_tgt"] = [team_tgt.get((a, b), np.nan) for a, b in zip(rec.game_id, rec.posteam)]
    rec["implied"] = [imp.get((a, b), np.nan) for a, b in zip(rec.game_id, rec.posteam)]
    rec["season"] = y
    sts = st.rename(columns={"passer_player_id": "qb_id", "passer_player_name": "qb_name"})[["game_id", "week", "posteam", "qb_id", "qb_name", "db", "epa"]]
    sts["season"] = y
    qball = qb.rename(columns={"passer_player_id": "qb_id"}); qball["season"] = y
    out = dict(rec=rec, st=sts, qball=qball, imp=imp)
    pd.to_pickle(out, fp)
    return out

def main():
    pl = pd.read_csv(os.path.join(PBP, "players.csv"), usecols=["gsis_id", "position"], low_memory=False)
    POS = dict(zip(pl.gsis_id, pl.position))
    S = {y: season_tables(y) for y in YRS_ALL}
    P(f"seasons loaded {YRS_ALL}")
    # QB quality: EPA per dropback, previous season (100+ dropbacks), else career to date, else replacement -.10
    qb_season = {}
    for y in YRS_ALL:
        a = S[y]["qball"].groupby("qb_id").agg(db=("db", "sum"), epa=("epa", "sum"))
        for q, r in a.iterrows(): qb_season[(q, y)] = (r.db, r.epa)
    def qb_quality(q, y):
        if (q, y - 1) in qb_season and qb_season[(q, y - 1)][0] >= 100: db, e = qb_season[(q, y - 1)]; return e / db
        db = e = 0.0
        for yy in range(2016, y):
            if (q, yy) in qb_season: db += qb_season[(q, yy)][0]; e += qb_season[(q, yy)][1]
        return e / db if db >= 100 else -0.10
    # injury reports (2019+)
    inj = set()
    for y in range(2019, 2026):
        fp = os.path.join(PBP, f"injuries_{y}.parquet")
        if os.path.exists(fp):
            ii = pd.read_parquet(fp)
            for r in ii.itertuples(): inj.add((r.gsis_id, int(r.season), int(r.week)))
    # per-season WR rows
    rows = []
    wr_mean = None
    lastppg = {}
    for y in YRS_ALL:
        rec = S[y]["rec"]; rec = rec[rec.pid.map(POS) == "WR"]
        gp = rec.groupby("pid").agg(g=("pts", "size"), ppg=("pts", "mean"))
        for q, r in gp.iterrows(): lastppg[(q, y)] = (r.g, r.ppg)
    allp = np.array([v[1] for k, v in lastppg.items() if v[0] >= 6]); wr_mean = float(np.mean(allp))
    P(f"WR mean half PPG (6+ g seasons) {wr_mean:.2f}")
    for y in YEARS:
        rec = S[y]["rec"]; st = S[y]["st"]
        rec = rec[rec.pid.map(POS) == "WR"].copy()
        starters = {(r.posteam, int(r.week)): (r.qb_id, r.qb_name) for r in st.itertuples()}
        passers = defaultdict(set)
        for r in S[y]["qball"].itertuples(): passers[(r.posteam, int(r.week))].add(r.qb_id)
        team_weeks = defaultdict(list)
        for (tm, w) in starters: team_weeks[tm].append(w)
        for tm in team_weeks: team_weeks[tm].sort()
        # regular QB per team-week (as of that week) + out flag
        reg = {}; out = {}
        for tm, wks in team_weeks.items():
            cnt = defaultdict(int); last = {}
            for w in wks:
                r_ = max(cnt, key=lambda q: (cnt[q], last.get(q, 0))) if cnt and max(cnt.values()) >= 2 else None
                reg[(tm, w)] = r_
                s_ = starters[(tm, w)][0]
                out[(tm, w)] = bool(r_ and s_ != r_ and r_ not in passers[(tm, w)])
                cnt[s_] += 1; last[s_] = w
        ever_start_after = lambda tm, q, w: any(starters[(tm, w2)][0] == q for w2 in team_weeks[tm] if w2 > w)
        wkimp = rec.groupby("week").implied.mean().to_dict()
        prior_pts = {}
        for pid in rec.pid.unique():
            g0, p0 = lastppg.get((pid, y - 1), (0, None))
            prior_pts[pid] = (wr_mean + 0.8 * (p0 - wr_mean)) if g0 >= 6 else wr_mean * 0.7
        pr_rank = {pid: i + 1 for i, pid in enumerate(sorted(prior_pts, key=lambda q: -prior_pts[q]))}
        for pid, grp in rec.sort_values("week").groupby("pid"):
            grp = grp.reset_index(drop=True)
            pts = grp.pts.values; xf = grp.xfp.values; tgt = grp.tgt.values; ttg = grp.team_tgt.values; wks = grp.week.values.astype(int); tms = grp.posteam.values
            for a in range(len(grp)):
                w = wks[a]; tm = tms[a]
                vm = 1 + 0.25 * ((grp.implied.values[a] - wkimp.get(w, 22.0)) / wkimp.get(w, 22.0)) if pd.notna(grp.implied.values[a]) else 1.0
                rq = reg.get((tm, w)); o = out.get((tm, w), False)
                k_b = sum(1 for b in range(a) if out.get((tms[b], wks[b]), False))
                stq = starters.get((tm, w), (None, None))[0]
                injc = None
                if o and y >= 2019:
                    injc = ((rq, y, w) in inj) or not ever_start_after(tm, rq, w)
                rows.append(dict(year=y, wk=w, pid=pid, name=grp.pname.values[a], tm=tm, g=a, act=pts[a], tgt=tgt[a], ttg=ttg[a], xfp=xf[a],
                                 ppg=float(pts[:a].mean()) if a else np.nan, xpg=float(xf[:a].mean()) if a else np.nan,
                                 tsh=float(tgt[:a].sum() / max(1, np.nansum(ttg[:a]))) if a else np.nan, prior=prior_pts[pid], prank=pr_rank[pid], vm=float(np.clip(vm, 0.7, 1.35)),
                                 out=o, kb=k_b, reg=rq, stq=stq, injc=injc, dq=(qb_quality(rq, y) - qb_quality(stq, y)) if (o and rq and stq) else np.nan))
    R = pd.DataFrame(rows)
    tw = R.drop_duplicates(["year", "tm", "wk"])[["year", "tm", "wk", "out", "reg", "stq", "dq", "injc"]].copy(); tw["tm"] = tw.tm.replace({"LA": "LAR"})
    pd.to_pickle(tw, os.path.join(CACHE, "teamweek.pkl"))
    P(f"WR player-weeks {len(R):,}; QB-out weeks {int(R.out.sum()):,} ({R[R.out].groupby(['year', 'tm', 'wk']).ngroups} team-weeks)")
    # ---------- base rate ----------
    g = R.g.values.astype(float); lam = np.maximum(0.25, 1 - 0.08 * np.maximum(g - 1, 0))
    ev = np.where(g > 0, lam * R.xpg.fillna(0).values + (1 - lam) * R.ppg.fillna(0).values, 0)
    rate = (8 * R.prior.values + g * ev) / (8 + g)
    R["rate"] = rate; R["base"] = rate * R.vm.values
    # rest-of-season target + future outages
    finw = np.where(R.year.values <= 2020, 17, 18)
    R["final"] = R.wk.values == finw
    T = np.full(len(R), np.nan); futout = np.full(len(R), np.nan); futvm = np.full(len(R), np.nan); futvm_out = np.full(len(R), np.nan)
    for (y, pid), ix in R.groupby(["year", "pid"]).indices.items():
        ix = np.array(sorted(ix, key=lambda i: R.wk.values[i])); ix = ix[~R.final.values[ix]]
        for a, i in enumerate(ix):
            fut = ix[a:]
            if len(fut) >= 4:
                T[i] = R.act.values[fut].mean(); futout[i] = R.out.values[fut].mean(); futvm[i] = R.vm.values[fut].mean()
                futvm_out[i] = (R.vm.values[fut] * R.out.values[fut]).sum() / len(fut)   # share of vm mass on out weeks
    R["T"] = T; R["futout"] = futout; R["futvm"] = futvm; R["futvm_out"] = futvm_out
    act = R.act.values; year = R.year.values
    okN = (R.g.values >= 1) & ~R.final.values & (R.base.values >= 3) & (R.prank.values <= 90)
    okR = ~np.isnan(T) & (R.g.values >= 3) & (R.g.values <= 10) & (R.rate.values * np.nan_to_num(futvm) >= 3) & (R.prank.values <= 90)
    qin = okN & ~R.out.values
    lvl = act[qin].sum() / R.base.values[qin].sum(); lvlR = T[okR & (futout == 0)].sum() / (R.rate.values * futvm)[okR & (futout == 0)].sum()
    P(f"global level on QB-in rows: next game {lvl:.3f}, ROS {lvlR:.3f} (applied)")
    baseN = R.base.values * lvl; baseR = R.rate.values * np.nan_to_num(futvm) * lvlR
    top = R.prank.values <= 60
    star_prior = R.prank.values <= 25
    tsh = R.tsh.values; xr = np.full(len(R), np.nan)
    for (y, w), ix in R[okN].groupby(["year", "wk"]).indices.items():
        sub = R[okN].iloc[ix]; ranks = sub.xpg.rank(ascending=False).values; xr[sub.index.values] = ranks
    R["xrank"] = xr
    # ---------- helpers ----------
    ms = lambda q, m, tt: float(np.mean((q[m] - tt[m]) ** 2)) if m.any() else np.nan
    def test(title, fam, m, tt, okm):
        names = list(fam); b = fam[names[0]]; touched = np.zeros(len(R), bool)
        for k in names[1:]: touched |= np.abs(fam[k] - b) > 1e-9
        tm = m & okm & touched
        if tm.sum() < 20: P(f"  {title}: too few rows ({int(tm.sum())})"); return None
        pick = lambda ys: min(names, key=lambda k: ms(fam[k], tm & np.isin(year, ys), tt))
        def run(folds):
            pr = b.copy(); wins = ny = 0; picks = []
            for tr, te in folds:
                k = pick(tr); picks.append(k); mm = year == te; pr[mm] = fam[k][mm]
                if (tm & mm).sum() >= 5: ny += 1; wins += ms(fam[k], tm & mm, tt) < ms(b, tm & mm, tt) - 1e-12
            tem = np.isin(year, [te for _, te in folds])
            return 100 * (ms(pr, tm & tem, tt) / ms(b, tm & tem, tt) - 1), wins, ny, picks, 100 * (ms(pr, tm & tem & top, tt) / ms(b, tm & tem & top, tt) - 1)
        lo = run([([y for y in YEARS if y != t], t) for t in YEARS]); fw = run([([y for y in YEARS if y < t], t) for t in FWD])
        best = pick(YEARS); okk = best != names[0] and lo[0] < -0.3 and lo[1] >= math.ceil(0.6 * lo[2]) and fw[0] < 0 and fw[1] >= 3 and lo[4] <= 0.1
        P(f"  {title}   (rows {int(tm.sum())}, act/base {tt[tm].sum()/b[tm].sum():.3f})")
        P("    pooled: " + "  ".join(f"{k}: {100*(ms(fam[k], tm, tt)/ms(b, tm, tt)-1):+.2f}%" for k in names[1:]))
        P(f"    LOYO {lo[0]:+.2f}% {lo[1]}/{lo[2]} | top-60 WR {lo[4]:+.2f}% | picks {lo[3]}")
        P(f"    FWD  {fw[0]:+.2f}% {fw[1]}/{fw[2]} | picks {fw[3]}")
        P(f"    -> {'PASS: ' + best if okk else 'FAIL (best pooled: ' + best + ')'}")
        return best if okk else None
    def tab(lab, m, tt, pr, okm):
        mm = m & okm
        if mm.sum() < 8: return
        ys = [y for y in YEARS if (mm & (year == y)).sum() >= 3]
        P(f"    {lab:56s} n {int(mm.sum()):5d} ({R[mm].groupby(['year', 'pid']).ngroups:3d} p-s)  act/undocked {tt[mm].sum()/pr[mm].sum():.3f}  seasons under {sum(1 for y in ys if tt[mm & (year == y)].sum() < pr[mm & (year == y)].sum())}/{len(ys)}")
    out = R.out.values; kb = R.kb.values
    engine_d = np.where(star_prior, 0.15, 0.05)
    # ================= 1 bigger sample: levels =================
    P("\n=== 1  LEVEL with the regular QB out, undocked base (QB-unaware), 2017-25 ===")
    for tlab, tt, pr, okm, m0 in (("NEXT GAME", act, baseN, okN, out), ("REST OF SEASON (regular out now, 75%+ of the rest)", T, baseR, okR, out & (np.nan_to_num(futout) >= 0.75))):
        P(f"  --- {tlab} ---")
        tab("QB in (reference)", ~out, tt, pr, okm)
        tab("QB out, all WRs", m0, tt, pr, okm)
        tab("QB out, 2019+ injury-confirmed", m0 & (R.injc.values == True), tt, pr, okm)
        tab("QB out, 2017-18 only", m0 & (year <= 2018), tt, pr, okm)
        tab("QB out, prior rank 1-25, 2019+", m0 & star_prior & (year >= 2019), tt, pr, okm)
        tab("QB out, prior rank 1-25, 2019+ injury-confirmed", m0 & star_prior & (R.injc.values == True), tt, pr, okm)
        tab("QB out, prior rank 1-25, 2017-18", m0 & star_prior & (year <= 2018), tt, pr, okm)
        tab("QB out, prior rank 1-25, 2+ backup games, 2019+ injury-confirmed", m0 & star_prior & (kb >= 2) & (R.injc.values == True), tt, pr, okm)
        tab("QB out, tsh 22%+, 2+ backup games, 2019+ injury-confirmed", m0 & (tsh >= 0.22) & (kb >= 2) & (R.injc.values == True), tt, pr, okm)
        for lab, sm in (("prior rank 1-25 (= engine star)", star_prior), ("prior rank 26-60", (R.prank.values > 25) & top),
                        ("target share to date 25%+", tsh >= 0.25), ("target share 20-25%", (tsh >= 0.20) & (tsh < 0.25)), ("target share 15-20%", (tsh >= 0.15) & (tsh < 0.20)), ("target share <15%", tsh < 0.15),
                        ("xFP/g rank 1-24 this week", xr <= 24), ("xFP/g rank 25-48", (xr > 24) & (xr <= 48))):
            tab(f"QB out, {lab}", m0 & sm, tt, pr, okm)
        for lab, km in (("0 backup games in evidence", kb == 0), ("1", kb == 1), ("2-3", (kb >= 2) & (kb <= 3)), ("4+", kb >= 4)):
            tab(f"QB out, {lab}", m0 & km, tt, pr, okm)
            tab(f"QB out, target share 22%+, {lab}", m0 & km & (tsh >= 0.22), tt, pr, okm)
    # ================= 2-4 dock tests =================
    def famN(dfun):
        return np.where(out, baseN * (1 - np.clip(dfun, 0, 0.6)), baseN)
    def famR(dfun):   # applied to the share of future weeks with the regular out (vm-weighted)
        fr = np.where(np.nan_to_num(futvm) > 0, np.nan_to_num(futvm_out) / np.where(np.nan_to_num(futvm) > 0, futvm, 1), 0)
        return baseR * (1 - np.clip(dfun, 0, 0.6) * fr)
    mRos = (np.nan_to_num(futout) >= 0.4) & out
    for tlab, F_, mm, tt, okm in (("NEXT GAME", famN, out, act, okN), ("ROS", famR, mRos, T, okR)):
        P(f"\n=== 2-4  DOCK FORMS, {tlab} (baseline = engine dock: .15 prior-top-25 / .05 others) ===")
        base = F_(engine_d)
        test(f"2a flat dock size (all WRs)", {"engine": base, **{f"d {d}": F_(np.full(len(R), d)) for d in (0.0, 0.05, 0.10, 0.15, 0.20)}}, mm, tt, okm)
        fam = {"engine": base}
        bands = [(tsh >= 0.25), (tsh >= 0.18) & (tsh < 0.25), ~(tsh >= 0.18)]
        for e1 in (0.0, 0.05, 0.10, 0.15, 0.20):
            for e2 in (0.0, 0.05, 0.10, 0.15, 0.20):
                for e3 in (0.0, 0.05, 0.10, 0.15):
                    fam[f"tsh25+ {e1} / 18-25 {e2} / <18 {e3}"] = F_(np.select(bands, [e1, e2, e3], 0.05))
        test("2b dock size by target-share band (25%+ / 18-25% / under 18%)", fam, mm, tt, okm)
        fam = {"engine": base}
        for e1 in (0.0, 0.05, 0.10, 0.15, 0.20):
            for e2 in (0.0, 0.05, 0.10, 0.15):
                fam[f"prior-top25 {e1} / other {e2}"] = F_(np.where(star_prior, e1, e2))
        test("2c dock size by preseason star level (prior rank 25)", fam, mm, tt, okm)
        fam = {"engine": base}
        for c in (0.5, 1, 2, 4, 8):
            fam[f"fade c {c}"] = F_(engine_d * c / (kb + c))
        test("3  double counting: engine dock x c / (k backup games in evidence + c)", fam, mm, tt, okm)
        dq = R.dq.values; dqf = np.nan_to_num(dq, nan=np.nanmean(dq[out]))
        fam = {"engine": base}
        for a_ in (0.25, 0.5, 0.75, 1.0):
            fam[f"engine x (dEPA / mean)^ {a_}"] = F_(engine_d * np.clip(np.maximum(dqf, 0) / max(1e-6, np.nanmean(np.maximum(dq[out & okm], 0))), 0, 3) ** a_)
        for s_ in (0.3, 0.5, 0.8):
            fam[f"dock = {s_} x dEPA/db (star x1.0, other x.33)"] = F_(np.where(star_prior, 1.0, 0.33) * s_ * np.maximum(dqf, 0))
        test("4  backup quality: dock scaled by the EPA/dropback drop regular -> starter (prior season)", fam, mm, tt, okm)
        fade1 = engine_d * 1.0 / (kb + 1.0)
        fam = {"fade c 1": F_(fade1)}
        for a_ in (0.25, 0.5):
            fam[f"fade c 1 x (dEPA / mean)^ {a_}"] = F_(fade1 * np.clip(np.maximum(dqf, 0) / max(1e-6, np.nanmean(np.maximum(dq[out & okm], 0))), 0, 3) ** a_)
        test("4b backup quality ON TOP of the k-fade (c 1)", fam, mm, tt, okm)
        fam = {"fade c 1": F_(fade1)}
        for e1, e2 in ((0.10, 0.05), (0.10, 0.10), (0.15, 0.10), (0.20, 0.05), (0.20, 0.10)):
            fam[f"fade c 1, top25 {e1} / other {e2}"] = F_(np.where(star_prior, e1, e2) / (kb + 1.0))
        test("2d star split ON TOP of the k-fade (c 1)", fam, mm, tt, okm)
        for lab_, sm_ in (("prior top 25", star_prior), ("target share 22%+", tsh >= 0.22), ("others", ~star_prior & ~(tsh >= 0.22))):
            mmm = mm & okm & sm_
            if mmm.sum() >= 10: P(f"    {lab_:20s} n {int(mmm.sum()):4d}  error vs engine: fade c 1 {100*(ms(F_(fade1), mmm, tt)/ms(base, mmm, tt)-1):+.2f}%  no dock {100*(ms(F_(np.zeros(len(R))), mmm, tt)/ms(base, mmm, tt)-1):+.2f}%  act/engine {tt[mmm].sum()/base[mmm].sum():.3f} act/fade {tt[mmm].sum()/F_(fade1)[mmm].sum():.3f}")
    # ================= 5 target share / efficiency =================
    P("\n=== 5  STAR WRs WITH THE BACKUP: target share and per-target value, same player-season, QB-in games vs QB-out games ===")
    G = R[(R.prank <= 60) & R.ttg.notna()].copy(); G["gsh"] = G.tgt / G.ttg
    for lab, sel in (("prior rank 1-25", G.prank <= 25), ("prior rank 26-60", G.prank > 25)):
        sub = G[sel]; res = []
        for (y, pid), q in sub.groupby(["year", "pid"]):
            if q.out.sum() >= 1 and (~q.out).sum() >= 3:
                a_, b_ = q[~q.out], q[q.out]
                res.append((a_.gsh.mean(), b_.gsh.mean(), a_.act.sum() / max(1, a_.tgt.sum()), b_.act.sum() / max(1, b_.tgt.sum()), a_.xfp.sum() / max(1, a_.tgt.sum()), b_.xfp.sum() / max(1, b_.tgt.sum()),
                            a_.ttg.mean(), b_.ttg.mean(), a_.act.mean(), b_.act.mean(), a_.tgt.mean(), b_.tgt.mean(), len(b_)))
        if not res: continue
        A = np.array(res)
        P(f"  {lab}: {len(A)} player-seasons with both | target share {A[:,0].mean():.3f} -> {A[:,1].mean():.3f} (up in {int((A[:,1] > A[:,0]).sum())}/{len(A)})"
          f" | team targets/g {A[:,6].mean():.1f} -> {A[:,7].mean():.1f} | his targets/g {A[:,10].mean():.2f} -> {A[:,11].mean():.2f}"
          f" | pts/target {A[:,2].mean():.3f} -> {A[:,3].mean():.3f} | xFP/target {A[:,4].mean():.3f} -> {A[:,5].mean():.3f} | pts/g {A[:,8].mean():.2f} -> {A[:,9].mean():.2f}")
    LOG.close()

if __name__ == "__main__":
    main()
