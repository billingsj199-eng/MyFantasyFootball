#!/usr/bin/env python3
"""
WEEKLY STAT SWEEP (mff-sim-engineer STATS mode, first run 2026-11-10). PROPOSE-ONLY: reads live files, writes only _tmp/ outputs.

Metric atlas re-run on the CURRENT live base instead of the old Clay live stack:
  H  2019-25: every metric in data/metric_atlas_rows.parquet (108 pre-kickoff metrics: pbp, PFF weekly, ctx) vs what the honest
     shadow replica (backtest_base_remeasure.shadow_current, TD luck OFF as wired 11-10) missed - next game and rest of season.
     Rows: top-150 ADP, final week dropped, shadow >= 3, 2+ games played. Spearman within position + seasons with the same sign.
  S  2026 lock rows W2-9: the pbp + PFF weekly metrics rebuilt season-to-date entering each week vs (actual - shipped mean)
     and (actual - shadow number ncMean).
  B  every cell with |r| >= .05 (next or rest of season) gets the generic LOYO tilt test on the shadow base:
     candidate = base x (1 + k x z), z standardised on the training seasons, k grid-fit on the training seasons.
     Bar: its position rows <= -0.3% squared error, 5+ of 7 seasons, absolute error better in 4+ of 7, within-week rank
     order better in 4+ of 7, forward (2022-25, k from earlier seasons only) better in 3+ of 4.
Outputs: _tmp/stat_sweep_<date>.log, _tmp/stat_sweep_atlas.csv, _tmp/stat_sweep_loyo.csv
"""
import json, os, pickle, re, sys, warnings, datetime
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata, spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
warnings.filterwarnings("ignore")
import backtest_base_remeasure as BR
import research_metric_atlas as MA
REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"; CACHE = MA.CACHE
TODAY = datetime.date.today().isoformat()
LOG = open(os.path.join(HERE, "_tmp", f"stat_sweep_{TODAY}.log"), "w", encoding="utf-8")
def P(s=""):
    print(s, flush=True); LOG.write(s + "\n"); LOG.flush()
POS4 = ("QB", "RB", "WR", "TE"); FWD = (2022, 2023, 2024, 2025)
NON_METRIC = {"year", "name", "pos", "team", "opp", "pid", "wk", "act", "shipped", "pos_qb", "pos_rb", "pos_wr", "pos_te", "live", "res", "ros", "resRos", "team_k", "team_t",
              "clay", "base2", "veg", "td_luck_adj", "pool_mult", "rookie_mult", "cond_mult", "weather_mult", "qb_inherit_mult"}


def history():
    X = pickle.load(open(os.path.join(HERE, "_tmp", "X_cache.pkl"), "rb")); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, name, adp, layers = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["name"], X["adp"], X["layers"]
    pid = X["A"]["pid"]; adpx = np.where(np.isnan(adp), 999.0, adp)
    SH, SH0 = BR.shadow_current(X, luck=False)
    finw = np.where(year <= 2020, 17, 18); final = wk == finw
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & (adpx <= 150)].mean()
    wt = np.maximum(0.05, lv) ** 2
    okN = (adpx <= 150) & ~final & (SH0 >= 3) & (g >= 2)
    seq = defaultdict(list)
    for i in range(n):
        if not final[i]: seq[(name[i], pos[i], int(year[i]))].append(i)
    T = np.full(n, np.nan); ctx = np.full(n, np.nan)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(layers[ix], .5, 1.8)
        for a, i in enumerate(ix):
            if len(ix) - a >= 4: T[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    R = SH / np.where(layers > 0, layers, 1.0) * ctx
    okR = (adpx <= 150) & ~np.isnan(T) & (g >= 3) & (g <= 10) & (R >= 3)
    M = pd.read_parquet(os.path.join(HERE, "data", "metric_atlas_rows.parquet")).dropna(subset=["pid"]).drop_duplicates(["year", "pid", "wk"])
    feats = [c for c in M.columns if c not in NON_METRIC and M[c].dtype.kind in "fi" and not c.endswith("_t")]
    key = pd.MultiIndex.from_arrays([year.astype(int), [p if p else "" for p in pid], wk.astype(int)])
    Mi = M.set_index(["year", "pid", "wk"])[feats].reindex(key)
    FV = {f: Mi[f].values.astype(float) for f in feats}
    P(f"H rows: next game {int(okN.sum()):,} | rest of season {int(okR.sum()):,} checkpoints | metrics {len(feats)} | matched to the metric table {int((~np.isnan(FV['ppg'])) [okN].sum()) if 'ppg' in FV else -1:,}")
    P(f"  shadow base (TD luck off): next-game MAE {np.abs(act[okN]-SH[okN]).mean():.3f} act/proj {act[okN].sum()/SH[okN].sum():.3f} | ROS MAE {np.abs(T[okR]-R[okR]).mean():.3f} act/proj {T[okR].sum()/R[okR].sum():.3f}")
    YEARS = sorted(set(int(y) for y in year))
    recs = []
    for f in feats:
        v = FV[f]
        for ps in POS4:
            out = {"metric": f, "pos": ps}
            for tag, ok, base, tgt in (("next", okN, SH, act), ("ros", okR, R, T)):
                m = ok & (pos == ps) & ~np.isnan(v)
                if m.sum() < 300 or len(np.unique(v[m])) < 5: out.update({f"n_{tag}": int(m.sum()), f"r_{tag}": np.nan, f"yrs_{tag}": ""}); continue
                r = float(spearmanr(v[m], tgt[m] - base[m])[0]); same = tot = 0
                for y in YEARS:
                    my = m & (year == y)
                    if my.sum() >= 40 and len(np.unique(v[my])) >= 5:
                        ry = spearmanr(v[my], tgt[my] - base[my])[0]; tot += 1; same += int(np.sign(ry) == np.sign(r))
                out.update({f"n_{tag}": int(m.sum()), f"r_{tag}": r, f"yrs_{tag}": f"{same}/{tot}"})
            recs.append(out)
    A = pd.DataFrame(recs)
    # ---- old atlas comparison (residual vs the old Clay live stack)
    old = pd.read_csv(os.path.join(HERE, "data", "metric_atlas.csv")).rename(columns={"r_res": "old_res", "r_resRos": "old_resRos"})[["metric", "pos", "old_res", "old_resRos"]]
    A = A.merge(old, on=["metric", "pos"], how="left")
    A.to_csv(os.path.join(HERE, "_tmp", "stat_sweep_atlas.csv"), index=False)
    flag = A[(A.r_next.abs() >= .05) | (A.r_ros.abs() >= .05)]
    P(f"\n=== H1 atlas on the shadow base: {len(A)} metric x position cells, {len(flag)} with |r| >= .05 (next or rest of season); old atlas (Clay live stack) had {int(((old.old_res.abs() >= .05) | (old.old_resRos.abs() >= .05)).sum())} ===")
    for ps in POS4:
        x = flag[flag.pos == ps].copy(); x["k"] = x[["r_next", "r_ros"]].abs().max(axis=1); x = x.sort_values("k", ascending=False)
        P(f"\n  {ps}: {len(x)} flagged   {'metric':30s} {'n':>5s} {'res next':>8s} {'yrs':>4s} | {'res ROS':>8s} {'yrs':>4s} || old atlas next / ROS")
        for r in x.itertuples():
            P(f"      {r.metric:38s} {r.n_next:5d} {r.r_next:+8.3f} {r.yrs_next:>4s} | {r.r_ros:+8.3f} {r.yrs_ros:>4s} || {r.old_res:+.3f} / {r.old_resRos:+.3f}")

    # ---- B: LOYO tilt test on every flagged cell
    grid = np.round(np.arange(-0.20, 0.2001, 0.01), 2)
    def rho(q, tgt, ix_groups):
        rh = [np.corrcoef(rankdata(tgt[ix]), rankdata(q[ix]))[0, 1] for ix in ix_groups]
        return float(np.mean(rh)) if rh else float("nan")
    def fitk(z, base, tgt, w):
        best = (None, 1e99)
        for k in grid:
            e = float(np.average((base * (1 + k * z) - tgt) ** 2, weights=w))
            if e < best[1]: best = (k, e)
        return best[0]
    out = []
    for r in flag.itertuples():
        v = FV[r.metric]
        for tag, ok, base, tgt, rr in (("next", okN, SH, act, r.r_next), ("ros", okR, R, T, r.r_ros)):
            if not (rr == rr and abs(rr) >= .05): continue
            m = ok & (pos == r.pos); has = m & ~np.isnan(v)
            cand = base.copy(); candF = base.copy(); ks = []
            for y in YEARS:
                tr = has & (year != y); te = m & (year == y)
                if tr.sum() < 200: continue
                mu, sd = v[tr].mean(), v[tr].std() or 1.0
                z = np.nan_to_num(np.clip((v - mu) / sd, -2.5, 2.5), nan=0.0)
                k = fitk(z[tr], base[tr], tgt[tr], wt[tr]); ks.append(k); cand[te] = base[te] * (1 + k * z[te])
            for y in FWD:
                tr = has & (year < y); te = m & (year == y)
                if tr.sum() < 200: continue
                mu, sd = v[tr].mean(), v[tr].std() or 1.0
                z = np.nan_to_num(np.clip((v - mu) / sd, -2.5, 2.5), nan=0.0)
                k = fitk(z[tr], base[tr], tgt[tr], wt[tr]); candF[te] = base[te] * (1 + k * z[te])
            mse = lambda q, mm: float(np.mean((q[mm] - tgt[mm]) ** 2)); mae = lambda q, mm: float(np.mean(np.abs(q[mm] - tgt[mm])))
            ys = [y for y in YEARS if (m & (year == y)).sum() >= 30]
            w_mse = sum(mse(cand, m & (year == y)) < mse(base, m & (year == y)) for y in ys); w_mae = sum(mae(cand, m & (year == y)) < mae(base, m & (year == y)) for y in ys)
            def yr_groups(y):
                gr = defaultdict(list)
                for i in np.where(m & (year == y))[0]: gr[int(wk[i])].append(i)
                return [np.array(ix) for ix in gr.values() if len(ix) >= 8]
            rb = []; rc = []; w_rk = 0
            for y in ys:
                G = yr_groups(y)
                if not G: continue
                a, b = rho(base, tgt, G), rho(cand, tgt, G); rb.append(a); rc.append(b); w_rk += int(b > a)
            fm = m & np.isin(year, FWD); w_f = sum(mse(candF, m & (year == y)) < mse(base, m & (year == y)) for y in FWD)
            folds = " | ".join(f"{y} {100*(mse(cand, m & (year == y))/mse(base, m & (year == y))-1):+.2f}" for y in ys)
            d_mse = 100 * (mse(cand, m) / mse(base, m) - 1); d_mae = 100 * (mae(cand, m) / mae(base, m) - 1); d_f = 100 * (mse(candF, fm) / mse(base, fm) - 1)
            ok_pass = (d_mse <= -0.3) and (w_mse >= 5) and (w_mae >= 4) and (w_rk >= 4) and (np.mean(rc) > np.mean(rb)) and (w_f >= 3) and d_mae < 0
            out.append(dict(metric=r.metric, pos=r.pos, horizon=tag, r=rr, n=int(m.sum()), cover=float(has.sum() / max(1, m.sum())), k_med=float(np.median(ks)) if ks else np.nan, k_min=min(ks) if ks else np.nan, k_max=max(ks) if ks else np.nan,
                            mse=d_mse, mse_yrs=f"{w_mse}/{len(ys)}", mae=d_mae, mae_yrs=f"{w_mae}/{len(ys)}", rank_base=float(np.mean(rb)), rank_cand=float(np.mean(rc)), rank_yrs=f"{w_rk}/{len(rb)}",
                            fwd=d_f, fwd_yrs=f"{w_f}/4", folds=folds, PASS=bool(ok_pass)))
    B = pd.DataFrame(out).sort_values(["PASS", "mse"], ascending=[False, True]); B.to_csv(os.path.join(HERE, "_tmp", "stat_sweep_loyo.csv"), index=False)
    P(f"\n=== B  LOYO tilt test, {len(B)} flagged cells (base x (1 + k z), k fit on training seasons; % = squared error on that position's rows, negative = better) ===")
    P(f"  {'metric':34s} {'pos':3s} {'hor':4s} {'r':>6s} {'k med':>6s} | {'MSE':>7s} {'yrs':>4s} | {'MAE':>7s} {'yrs':>4s} | {'rank base':>9s} {'cand':>6s} {'yrs':>4s} | {'fwd':>7s} {'yrs':>4s} | PASS")
    for b in B.itertuples():
        P(f"  {b.metric:34s} {b.pos:3s} {b.horizon:4s} {b.r:+6.3f} {b.k_med:+6.2f} | {b.mse:+6.2f}% {b.mse_yrs:>4s} | {b.mae:+6.2f}% {b.mae_yrs:>4s} | {b.rank_base:9.4f} {b.rank_cand:6.4f} {b.rank_yrs:>4s} | {b.fwd:+6.2f}% {b.fwd_yrs:>4s} | {'PASS' if b.PASS else ''}")
    P("\n  fold detail for cells that pass or come within reach (MSE <= -0.2%):")
    for b in B[(B.PASS) | (B.mse <= -0.2)].itertuples():
        P(f"    {b.metric} {b.pos} {b.horizon}: k {b.k_min:+.2f}..{b.k_max:+.2f} cover {100*b.cover:.0f}% | {b.folds}")
    return A, B, dict(FV=FV, year=year, pos=pos, okN=okN, okR=okR)


def norm(s):
    s = s.lower().replace(".", "").replace("'", "").replace("-", " "); s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s); return re.sub(r"\s+", " ", s).strip()


def season_2026(A):
    MA.YEARS = [2026]
    parts = MA.pbp_metrics(); feats = {}
    for kind, Y, g in parts:
        if kind == "rec":
            cu = MA.cumulate(g, "receiver_player_id", ["tgt", "rec", "yds", "ay", "yac", "td", "epa", "succ", "deep", "rz", "ez", "cpv", "xyac", "first", "team_tgt", "team_ay", "team_rz_tgt"],
                             {"tgt_per_g": ("tgt", "g"), "target_share": ("tgt", "team_tgt"), "air_yards_share": ("ay", "team_ay"), "adot": ("ay", "tgt"), "catch_rate": ("rec", "tgt"),
                              "yac_per_rec": ("yac", "rec"), "yds_per_tgt": ("yds", "tgt"), "epa_per_tgt": ("epa", "tgt"), "succ_rate_tgt": ("succ", "tgt"), "deep_tgt_rate": ("deep", "tgt"),
                              "rz_tgt_share": ("rz", "team_rz_tgt"), "endzone_tgt_per_g": ("ez", "g"), "target_quality_cp": ("cpv", "tgt"), "xyac_per_tgt": ("xyac", "tgt"),
                              "first_down_per_tgt": ("first", "tgt"), "rec_td_per_tgt": ("td", "tgt"), "catch_over_exp": ("rec", "cpv")})
            cu["catch_over_exp"] = cu.rec_cum - cu.cpv_cum; feats["rec"] = cu.rename(columns={"receiver_player_id": "pid"})
        elif kind == "rush":
            cu = MA.cumulate(g, "rusher_player_id", ["car", "ryds", "rtd", "repa", "rsucc", "stuff", "expl", "gl", "rrz", "rfirst", "tfl", "short", "team_car", "team_gl"],
                             {"car_per_g": ("car", "g"), "carry_share": ("car", "team_car"), "ypc": ("ryds", "car"), "epa_per_rush": ("repa", "car"), "succ_rate_rush": ("rsucc", "car"),
                              "stuff_rate": ("stuff", "car"), "explosive_rate": ("expl", "car"), "goalline_share": ("gl", "team_gl"), "rz_car_per_g": ("rrz", "g"),
                              "first_down_per_car": ("rfirst", "car"), "tfl_rate": ("tfl", "car"), "short_yd_car_per_g": ("short", "g"), "rush_td_per_car": ("rtd", "car")})
            feats["rush"] = cu.rename(columns={"rusher_player_id": "pid"})
        elif kind == "pass":
            cu = MA.cumulate(g, "passer_player_id", ["db", "att", "cmp", "pyds", "ptd", "pint", "sk", "scr", "qay", "qdeep", "qepa", "qsucc", "hit", "shot"],
                             {"dropbacks_per_g": ("db", "g"), "comp_pct": ("cmp", "att"), "yds_per_att": ("pyds", "att"), "td_rate": ("ptd", "att"), "int_rate": ("pint", "att"),
                              "sack_rate": ("sk", "db"), "scramble_rate": ("scr", "db"), "qb_adot": ("qay", "att"), "qb_deep_rate": ("qdeep", "att"), "epa_per_db": ("qepa", "db"),
                              "succ_rate_db": ("qsucc", "db"), "hit_rate": ("hit", "db"), "shotgun_rate": ("shot", "db")})
            feats["pass"] = cu.rename(columns={"passer_player_id": "pid"})
        else:
            tm = g.sort_values(["posteam", "week"]).copy()
            for c in ("plays", "team_pass_rate", "team_neutral_pass_rate", "team_epa_play", "team_nohuddle_rate"):
                tm[c + "_std"] = tm.groupby("posteam")[c].transform(lambda s: s.expanding().mean().shift())
            feats["team"] = tm.rename(columns={"plays_std": "team_plays_per_g"})
    # PFF weekly 2026
    def pffw(kinds, cols, pre):
        rows = []
        for w in range(1, 19):
            for kind in kinds:
                f = os.path.join(CACHE, "pff", "weekly", f"pff_{kind}_2026_w{w}.csv")
                if os.path.exists(f):
                    d = pd.read_csv(f); d = d[["player_id"] + [c for c in cols if c in d.columns]].copy(); d["week"] = w; rows.append(d); break
        d = pd.concat(rows, ignore_index=True).sort_values(["player_id", "week"]); o = d[["player_id", "week"]].copy()
        for c in cols:
            if c not in d.columns: continue
            cs = d.groupby("player_id")[c].cumsum() - d[c]; nn = d.groupby("player_id").cumcount(); o[pre + c] = np.where(nn > 0, cs / nn.replace(0, np.nan), np.nan)
        return o
    PR = pffw(["receiving_summary", "receiving"], ["grades_offense", "grades_pass_route", "yprr", "route_rate", "slot_rate", "contested_catch_rate", "drop_rate", "avg_depth_of_target", "yards_after_catch_per_reception", "targeted_qb_rating", "grades_hands_drop", "avoided_tackles", "positive_epa_percent"], "pff_")
    PU = pffw(["rushing_summary"], ["grades_run", "grades_offense", "yco_attempt", "elusive_rating", "breakaway_percent", "elu_rush_mtf", "explosive", "grades_pass_block", "yprr"], "pffr_")
    pl = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "pff_id", "display_name", "position", "last_season"])
    pff2g = dict(zip(pl.dropna(subset=["pff_id"]).pff_id.astype(int), pl.dropna(subset=["pff_id"]).gsis_id))
    for df in (PR, PU): df["pid"] = df.player_id.map(pff2g)
    cur = pl[(pl.last_season >= 2025) & pl.gsis_id.notna()]
    n2g = {(norm(a), b): c for a, b, c in zip(cur.display_name, cur.position, cur.gsis_id)}
    # lock rows
    raw = open(os.path.join(REPO, "data", "weekly_stats_active.js"), encoding="utf-8").read(); D = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    acts = defaultdict(dict)
    for nm, rec in D.items():
        for w in (rec.get("seasons") or {}).get("2026") or []:
            if isinstance(w.get("fpts"), (int, float)): acts[w.get("wk")][norm(nm)] = float(w["fpts"])
    rows = []
    for wk in range(2, 19):
        f = os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{wk}.json")
        if not os.path.exists(f): continue
        for p in json.load(open(f, encoding="utf-8"))["players"]:
            ps = p.get("pos")
            if ps not in POS4 or not isinstance(p.get("mean"), (int, float)) or p["mean"] < 5: continue
            a = acts[wk].get(norm(p["name"])); gid = n2g.get((norm(p["name"]), ps))
            if a is None or gid is None: continue
            rows.append(dict(pid=gid, week=wk, pos=ps, name=p["name"], team=p.get("tm"), ship=float(p["mean"]), nc=float(p["ncMean"]) if isinstance(p.get("ncMean"), (int, float)) else np.nan, act=a))
    L = pd.DataFrame(rows)
    for k in ("rec", "rush", "pass"):
        Fk = feats[k].drop(columns=[c for c in feats[k].columns if c.endswith("_cum") or c == "g_cum"]); L = L.merge(Fk, on=["pid", "week"], how="left")
    T = feats["team"][["posteam", "week", "team_plays_per_g", "team_pass_rate_std", "team_neutral_pass_rate_std", "team_epa_play_std", "team_nohuddle_rate_std"]].copy()
    T["posteam"] = T.posteam.replace({"LA": "LAR", "WSH": "WAS", "JAC": "JAX"}); L["tk"] = L.team.replace({"LA": "LAR", "WSH": "WAS", "JAC": "JAX"})
    L = L.merge(T, left_on=["tk", "week"], right_on=["posteam", "week"], how="left")
    L = L.merge(PR.drop(columns=["player_id"]).dropna(subset=["pid"]).drop_duplicates(["pid", "week"]), on=["pid", "week"], how="left").merge(PU.drop(columns=["player_id"]).dropna(subset=["pid"]).drop_duplicates(["pid", "week"]), on=["pid", "week"], how="left")
    L.to_parquet(os.path.join(HERE, "_tmp", "stat_sweep_2026_rows.parquet"))
    mets = [c for c in L.columns if c not in ("pid", "week", "pos", "name", "team", "ship", "nc", "act", "tk", "posteam")]
    P(f"\n=== S  2026 lock rows W2-{int(L.week.max())}: {len(L):,} player-weeks (shipped mean >= 5, matched to actuals + ids), {len(mets)} pbp / PFF metrics (ctx-family metrics not rebuilt for 2026) ===")
    P(f"  shipped MAE {np.abs(L.act-L.ship).mean():.3f} | shadow MAE {np.abs(L.act-L.nc).mean():.3f}")
    recs = []
    for f in mets:
        for ps in POS4:
            d = L[(L.pos == ps) & L[f].notna()]
            if len(d) < 80 or d[f].nunique() < 5: continue
            recs.append(dict(metric=f, pos=ps, n26=len(d), r26_ship=float(spearmanr(d[f], d.act - d.ship)[0]), r26_nc=float(spearmanr(d[f], d.act - d.nc)[0])))
    S = pd.DataFrame(recs); J = A.merge(S, on=["metric", "pos"], how="inner")
    Jf = J[(J.r_next.abs() >= .05)]
    agree = int((np.sign(Jf.r_next) == np.sign(Jf.r26_nc)).sum())
    P(f"  history next-game flags with a 2026 read: {len(Jf)}; same sign in 2026 (vs the shadow number): {agree}/{len(Jf)}")
    P(f"  {'metric':32s} {'pos':3s} {'hist r':>7s} {'yrs':>4s} | {'n 2026':>6s} {'r vs shipped':>12s} {'r vs shadow':>11s}")
    for r in Jf.reindex(Jf.r_next.abs().sort_values(ascending=False).index).itertuples():
        P(f"  {r.metric:32s} {r.pos:3s} {r.r_next:+7.3f} {r.yrs_next:>4s} | {r.n26:6d} {r.r26_ship:+12.3f} {r.r26_nc:+11.3f}")
    big = S[(S.r26_ship.abs() >= .15) & (S.n26 >= 120)].sort_values("r26_ship")
    P(f"\n  2026-only reads with |r vs shipped| >= .15 and n >= 120 (one season, 8 weeks: watch list only, not a test):")
    for r in big.itertuples():
        h = A[(A.metric == r.metric) & (A.pos == r.pos)]
        P(f"  {r.metric:32s} {r.pos:3s} n {r.n26:4d} r {r.r26_ship:+.3f} (vs shadow {r.r26_nc:+.3f}) | history r {float(h.r_next.iloc[0]) if len(h) else float('nan'):+.3f}")
    S.to_csv(os.path.join(HERE, "_tmp", "stat_sweep_2026.csv"), index=False)


if __name__ == "__main__":
    A, B, _ = history(); season_2026(A); LOG.close()
