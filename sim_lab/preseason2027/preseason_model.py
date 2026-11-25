#!/usr/bin/env python3
"""
2027 PRESEASON PROTOTYPE - step 2: preseason player projection, walk-forward 2015-2025.

Everything on the prediction side is known BEFORE week 1 of the target season Y:
  history      Y-1 / Y-2 / Y-3 half-PPR PPG, games, targets / carries / attempts per game, target + carry share,
               QB rush yards / pass att per game, TD rates (regressed by the fit)
  age / career age on Sept 1 of Y, years since rookie season, rookie flag, log draft pick, draft round 1 / 2
  role         week-1 depth-chart rank at his position (nflverse REG week 1 2012-24, ESPN pre-Sept chart 2025)
  team context team change, team expected wins from the de-vigged preseason WIN TOTAL, team's Y-1 pass attempts /
               rushing attempts per game, vacated target / carry share (Y-1 team volume from players not on the Y roster),
               new QB1 flag + QB1's Y-1 PPG (from the week-1 chart)
  market       FFC preseason ADP (log) and positional ADP rank (optional; the 'stats' model leaves it out)

Targets (final week of each season excluded, per the grading rules):
  ppg    half-PPR points per game over games played (graded with games weights, >= 4 games)
  total  season half-PPR points through the second-to-last week (0 if he never plays) = what a draft buys

Models are fit per position on seasons strictly before Y (walk-forward, first test year 2015):
  ridge_stats  ridge on history/age/role/team features (no ADP)
  ridge_full   + ADP
  gbm_full     gradient boosting on the same set
  ens          0.5 ridge_full + 0.5 gbm_full
  games model  expected games share (GBM) -> total = ppg_pred x games_pred
Baselines: ADP curve (walk-forward isotonic fit of PPG / total on log positional ADP rank), naive last-season PPG,
and on 2019-25 ESPN's week-1 projection, Clay's season sheet (fair per game) and the live engine's week-1 base
(the shadow preseason prior, from sim_lab/season_long_table.parquet).

Writes data/preseason_backtest_rows.parquet and prints the grade tables (log: preseason_backtest.log).
Read-only on everything outside sim_lab/preseason2027.
"""
import json, os, re, sys, time, warnings
import numpy as np
import pandas as pd
from scipy.stats import norm as N, spearmanr

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SIM = os.path.dirname(HERE)
CACHE = r"E:\MyFantasyFootball\pbp_cache"
REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"
POS4 = ("QB", "RB", "WR", "TE")
TEST_YEARS = list(range(2015, 2026))
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI"}
LOG = None   # opened in main() so importing this module never truncates the log


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def nrm(s):
    s = str(s).lower().replace(".", "").replace("'", "").replace("-", " ")
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def tm(t):
    return ALIAS.get(t, t)


def final_week(Y):
    return 17 if Y <= 2020 else 18


# ---------------------------------------------------------------- tables
def season_table():
    W = pd.read_parquet(os.path.join(DATA, "player_weeks.parquet"))
    W = W[W.week < W.season.map(final_week)]
    g = W.groupby(["season", "pid"])
    S = g.agg(name=("display_name", "first"), pos=("position", "first"), games=("half", "size"), pts=("half", "sum"),
              ppr=("ppr", "sum"), dk=("dk", "sum"), tgt=("tgt", "sum"), car=("car", "sum"), att=("att", "sum"), pyd=("pyd", "sum"),
              ptd=("ptd", "sum"), ryd=("ryd", "sum"), rtd=("rtd", "sum"), cyd=("cyd", "sum"), ctd=("ctd", "sum"), rec=("rec", "sum"),
              team_tgt=("team_tgt", "sum"), team_car=("team_car", "sum"),
              team=("team", lambda s: s.value_counts().index[0]), birth=("birth_date", "first"), rookie_season=("rookie_season", "first"),
              dp_pick=("dp_pick", "first"), dp_year=("dp_year", "first"), draft_pick=("draft_pick", "first")).reset_index()
    S["ppg"] = S.pts / S.games
    S["tgt_sh"] = S.tgt / S.team_tgt.replace(0, np.nan); S["car_sh"] = S.car / S.team_car.replace(0, np.nan)
    return S, W


def team_volume(W):
    """team-season pass attempts / carries per game and each player's share of them."""
    G = pd.read_parquet(os.path.join(DATA, "team_games.parquet"))
    G = G[G.week < G.season.map(final_week)]
    T = G.groupby(["season", "team"]).agg(pa_pg=("passatt", "mean"), ra_pg=("rushatt", "mean"), pf_pg=("pf", "mean"), pa_allowed=("pa", "mean"),
                                         plays_pg=("plays", "mean"), wins=("pf", lambda s: 0)).reset_index()
    wins = G.assign(w=(G.pf > G.pa).astype(float) + 0.5 * (G.pf == G.pa)).groupby(["season", "team"]).w.sum().reset_index(name="wins")
    T = T.drop(columns="wins").merge(wins, on=["season", "team"])
    return T, G


def win_totals():
    """de-vigged expected wins per team-season from the preseason win total line (covers.com / SportsOddsHistory)."""
    w = pd.read_csv(os.path.join(DATA, "win_totals_2012_2025.csv"))
    w["team"] = w.team.map(tm)
    def dec(o):
        o = float(str(o).replace("+", ""))
        return 1 + (o / 100 if o > 0 else 100 / -o)
    po = 1 / w.over_odds.map(dec); pu = 1 / w.under_odds.map(dec)
    w["p_over"] = po / (po + pu)                       # two-way multiplicative de-vig
    w["hold"] = po + pu - 1
    sd = 2.0                                           # sd of season wins around the market's centre (game-level luck ~2.0)
    w["exp_w"] = w.win_total + sd * N.ppf(w.p_over.clip(.02, .98))
    games = w.season.map(lambda y: 16 if y <= 2020 else 17)
    w["exp_w"] = w.exp_w + (games * 16 - w.groupby("season").exp_w.transform("sum")) / 32   # league wins sum to 16 x games
    return w[["season", "team", "win_total", "p_over", "hold", "exp_w"]]


def ffc_adp():
    d = json.load(open(os.path.join(SIM, "data", "ffc_adp_hist.json"), encoding="utf-8"))
    rows = []
    for y, v in d.items():
        for p in v["players"]:
            if p["pos"] in POS4: rows.append({"season": int(y), "key": nrm(p["name"]), "pos": p["pos"], "adp": float(p["adp"]), "adp_fmt": p.get("fmt")})
    A = pd.DataFrame(rows).sort_values("adp").drop_duplicates(["season", "key", "pos"])
    A["pos_adp_rank"] = A.groupby(["season", "pos"]).adp.rank(method="first")
    return A


def week1_depth():
    """{(season, gsis): rank at his position in the week-1 chart}; QB1 per team-season."""
    out, qb1 = {}, {}
    for Y in range(2012, 2026):
        f = os.path.join(CACHE, f"depth_charts_{Y}.parquet")
        d = pd.read_parquet(f)
        if "week" in d.columns:
            d = d[(d.game_type == "REG") & (d.week == 1) & d.position.isin(POS4) & (d.formation == "Offense")]
            d = d.assign(team=d.club_code.map(tm), rk=pd.to_numeric(d.depth_team, errors="coerce"))
            d = d.sort_values("rk").drop_duplicates(["gsis_id"])
            for r in d.itertuples(index=False):
                out[(Y, r.gsis_id)] = r.rk
                if r.position == "QB" and r.rk == 1: qb1.setdefault((Y, r.team), r.gsis_id)
        else:   # 2025: ESPN daily charts; latest snapshot before the opener
            d = d[d.pos_abb.isin(POS4)].copy(); d["dt"] = pd.to_datetime(d.dt, utc=True)
            d = d[d.dt < pd.Timestamp(f"{Y}-09-04", tz="UTC")]
            if len(d) == 0: continue
            d = d[d.dt == d.groupby("team").dt.transform("max")]
            d = d.assign(team=d.team.map(tm)).sort_values("pos_rank").drop_duplicates(["gsis_id"])
            for r in d.itertuples(index=False):
                out[(Y, r.gsis_id)] = r.pos_rank
                if r.pos_abb == "QB" and r.pos_rank == 1: qb1.setdefault((Y, r.team), r.gsis_id)
    return out, qb1


def week1_team():
    out = {}
    for Y in range(2012, 2026):
        r = pd.read_parquet(os.path.join(CACHE, f"roster_weekly_{Y}.parquet"), columns=["season", "team", "gsis_id", "week", "game_type"])
        r = r[r.gsis_id.notna() & (r.game_type == "REG")].sort_values("week").drop_duplicates("gsis_id")
        for a, b in zip(r.gsis_id, r.team): out[(Y, a)] = tm(b)
    return out


def position_overrides():
    """{(gsis, season): fantasy position} from data/position_overrides.csv (A9 fix 3: players nflverse lists at the wrong
    position, e.g. Travis Hunter = CB). One row per player with a season range, a reason and the date added."""
    import csv
    f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "position_overrides.csv")
    out = {}
    if not os.path.exists(f): return out
    for r in csv.DictReader(open(f, encoding="utf-8")):
        for y in range(int(r["from_season"]), min(int(r["to_season"]), 2030) + 1): out[(r["gsis_id"], y)] = r["position"]
    return out


# ---------------------------------------------------------------- features
def build():
    t0 = time.time()
    S, W = season_table(); T, G = team_volume(W); WT = win_totals(); A = ffc_adp()
    dc, qb1 = week1_depth(); w1t = week1_team()
    P(f"  tables: {len(S)} player-seasons, {len(T)} team-seasons, win totals {len(WT)}, ADP rows {len(A)}, depth {len(dc)} ({time.time()-t0:.0f}s)")
    hist = {(r.season, r.pid): r for r in S.itertuples(index=False)}
    pl = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False,
                     usecols=["gsis_id", "display_name", "position", "birth_date", "rookie_season", "draft_pick", "draft_round", "draft_year"])
    POV = position_overrides(); pov_ids = {g for g, _ in POV}
    pl = pl[pl.gsis_id.notna() & (pl.position.isin(POS4 + ("FB",)) | pl.gsis_id.isin(pov_ids))].drop_duplicates("gsis_id")
    pl.loc[pl.position == "FB", "position"] = "RB"
    pl["key"] = pl.display_name.map(nrm)
    tv = {(r.season, r.team): r for r in T.itertuples(index=False)}
    wt = {(r.season, r.team): r.exp_w for r in WT.itertuples(index=False)}
    # roster of team Y (week-1 team) for vacated volume
    rost = {}
    for (Y, pid), t in w1t.items(): rost.setdefault((Y, t), set()).add(pid)
    team_pl = S.groupby(["season", "team"])
    vac = {}
    for (Y, t), grp in team_pl:
        stay = rost.get((Y + 1, t), set())
        gone = grp[~grp.pid.isin(stay)]
        vac[(Y + 1, t)] = (gone.tgt.sum() / max(grp.tgt.sum(), 1), gone.car.sum() / max(grp.car.sum(), 1))
    rows = []
    for Y in range(2013, 2026):
        # candidate pool: everyone with a Y-1 game, every rookie drafted in Y, every ADP player
        cand = set(S[S.season == Y - 1].pid) | set(pl[(pl.rookie_season == Y)].gsis_id)
        adpY = A[A.season == Y]
        keymap = pl[(pl.rookie_season.fillna(0) <= Y) & (pl.rookie_season.fillna(0) >= Y - 20)].groupby(["key", "position"]).gsis_id.apply(list).to_dict()
        adp_pid = {}
        for r in adpY.itertuples(index=False):
            c = keymap.get((r.key, r.pos), [])
            if len(c) == 1: adp_pid[c[0]] = r; cand.add(c[0])
        info = pl.set_index("gsis_id")
        actual = {r.pid: r for r in S[S.season == Y].itertuples(index=False)}
        for pid in cand:
            if pid not in info.index: continue
            ii = info.loc[pid]; pos = POV.get((pid, Y), ii.position)
            if pos not in POS4: continue
            h = [hist.get((Y - k, pid)) for k in (1, 2, 3)]
            team = w1t.get((Y, pid)) or (h[0].team if h[0] is not None else None)
            if team is None and pid not in adp_pid: continue
            rk = ii.rookie_season if pd.notna(ii.rookie_season) else Y
            try: age = (pd.Timestamp(f"{Y}-09-01") - pd.Timestamp(ii.birth_date)).days / 365.25
            except Exception: age = np.nan
            pick = ii.draft_pick if pd.notna(ii.draft_pick) else 262
            f = {"season": Y, "pid": pid, "name": ii.display_name, "key": ii.key, "pos": pos, "team": team, "age": age,
                 "exp": Y - rk, "rookie": float(Y == rk), "lpick": np.log(pick), "rd1": float(pick <= 32), "rd2": float(32 < pick <= 64),
                 "undrafted": float(pick >= 262)}
            for k, hh in enumerate(h, start=1):
                f[f"ppg{k}"] = hh.ppg if hh is not None else np.nan
                f[f"g{k}"] = hh.games if hh is not None else 0.0
                if k == 1:
                    gg = hh.games if hh is not None else np.nan
                    f.update({"tpg1": hh.tgt / gg if hh is not None else np.nan, "cpg1": hh.car / gg if hh is not None else np.nan,
                              "apg1": hh.att / gg if hh is not None else np.nan, "qbr1": hh.ryd / gg if hh is not None else np.nan,
                              "tsh1": hh.tgt_sh if hh is not None else np.nan, "csh1": hh.car_sh if hh is not None else np.nan,
                              "tdpg1": (hh.rtd + hh.ctd + hh.ptd / 1.5) / gg if hh is not None else np.nan,
                              "ydpg1": (hh.ryd + hh.cyd + hh.pyd / 2.5) / gg if hh is not None else np.nan,
                              "team1": hh.team if hh is not None else None})
            # weighted history ppg (games x decay), the classic Marcel-style core
            num = sum(w * hh.pts for w, hh in zip((5, 3, 2), h) if hh is not None); den = sum(w * hh.games for w, hh in zip((5, 3, 2), h) if hh is not None)
            f["hppg"] = num / den if den > 0 else np.nan
            f["hgames"] = den
            f["moved"] = float(f.get("team1") is not None and team is not None and f.get("team1") != team)
            f["dc"] = dc.get((Y, pid), np.nan)
            tvp = tv.get((Y - 1, team)); f["team_pa1"] = tvp.pa_pg if tvp is not None else np.nan; f["team_ra1"] = tvp.ra_pg if tvp is not None else np.nan
            f["team_pf1"] = tvp.pf_pg if tvp is not None else np.nan
            f["exp_w"] = wt.get((Y, team), np.nan)
            v = vac.get((Y, team), (np.nan, np.nan)); f["vac_tgt"], f["vac_car"] = v
            q = qb1.get((Y, team)); hq = hist.get((Y - 1, q)) if q else None
            f["qb1_ppg1"] = hq.ppg if (hq is not None and hq.games >= 4) else np.nan
            prev_q = None
            if tvp is not None:
                qs = S[(S.season == Y - 1) & (S.team == team) & (S.pos == "QB")]
                if len(qs): prev_q = qs.sort_values("att").pid.iloc[-1]
            f["new_qb"] = float(q is not None and prev_q is not None and q != prev_q)
            f["is_qb1"] = float(q == pid)
            a = adp_pid.get(pid)
            f["adp"] = a.adp if a is not None else np.nan; f["pos_adp"] = a.pos_adp_rank if a is not None else np.nan
            act = actual.get(pid)
            f["act_games"] = act.games if act is not None else 0
            f["act_ppg"] = act.ppg if act is not None else np.nan
            f["act_total"] = act.pts if act is not None else 0.0
            f["act_ppr_total"] = act.ppr if act is not None else 0.0
            f["G"] = final_week(Y) - 1
            rows.append(f)
        P(f"  {Y}: {sum(1 for r in rows if r['season'] == Y)} candidates ({time.time()-t0:.0f}s)")
    D = pd.DataFrame(rows)
    D["ladp"] = np.log(D.adp.fillna(260)); D["lpadp"] = np.log(D.pos_adp.fillna(D.groupby(["season", "pos"]).pos_adp.transform("max").fillna(80) + 20))
    D["no_adp"] = D.adp.isna().astype(float)
    D["dc1"] = (D.dc == 1).astype(float); D["dc2"] = (D.dc == 2).astype(float); D["dcna"] = D.dc.isna().astype(float)
    D["gsh1"] = D.g1 / D.season.map(lambda y: final_week(y - 1) - 1)
    D["age2"] = (D.age - 27) ** 2
    return D


STATS_F = ["hppg", "ppg1", "ppg2", "ppg3", "g1", "g2", "hgames", "tpg1", "cpg1", "apg1", "qbr1", "tsh1", "csh1", "tdpg1", "ydpg1",
           "age", "age2", "exp", "rookie", "lpick", "rd1", "rd2", "undrafted", "moved", "dc1", "dc2", "dcna", "team_pa1", "team_ra1",
           "team_pf1", "exp_w", "vac_tgt", "vac_car", "qb1_ppg1", "new_qb", "is_qb1"]
MKT_F = ["ladp", "lpadp", "no_adp"]


def prep(Xtr, Xte):
    med = np.nanmedian(Xtr, axis=0); med = np.where(np.isnan(med), 0, med)
    miss = [j for j in range(Xtr.shape[1]) if np.isnan(Xtr[:, j]).mean() > 0.02]
    def f(M):
        ind = np.isnan(M[:, miss]).astype(float) if miss else np.zeros((len(M), 0))
        return np.column_stack([np.where(np.isnan(M), med, M), ind])
    return f(Xtr), f(Xte)


def fit_ridge(Xtr, ytr, wtr, Xte, alpha=10.0):
    from sklearn.linear_model import Ridge
    A, B = prep(Xtr, Xte); mu, sd = A.mean(0), A.std(0); sd[sd == 0] = 1
    m = Ridge(alpha=alpha).fit((A - mu) / sd, ytr, sample_weight=wtr)
    return m.predict((B - mu) / sd)


def fit_gbm(Xtr, ytr, wtr, Xte, loss="squared_error", q=None):
    from sklearn.ensemble import HistGradientBoostingRegressor
    kw = dict(max_iter=250, max_depth=3, learning_rate=0.04, min_samples_leaf=25, random_state=0)
    if q is not None: kw.update(loss="quantile", quantile=q)
    keep = ~np.all(np.isnan(Xtr), axis=0) & (np.nanstd(np.where(np.isnan(Xtr), 0, Xtr), axis=0) > 0)
    Xtr, Xte = Xtr[:, keep], Xte[:, keep]
    m = HistGradientBoostingRegressor(**kw).fit(Xtr, ytr, sample_weight=wtr)
    return m.predict(Xte)


def walk_forward(D):
    out = D.copy()
    for c in ("ridge_stats", "ridge_full", "gbm_full", "ens", "adp_curve", "naive", "games_pred", "q10", "q90", "adp_total", "anchor_r", "anchor_r30", "anchor_g"): out[c] = np.nan
    from sklearn.isotonic import IsotonicRegression
    for Y in TEST_YEARS:
        for ps in POS4:
            tr = (D.season < Y) & (D.pos == ps) & (D.act_games >= 4)
            te = (D.season == Y) & (D.pos == ps)
            if tr.sum() < 100 or te.sum() == 0: continue
            y = D.act_ppg[tr].values; w = D.act_games[tr].values.astype(float)
            # light recency weight on the training seasons (half-life 4 seasons)
            w = w * 0.5 ** ((Y - 1 - D.season[tr].values) / 4.0)
            Xs_tr, Xs_te = D.loc[tr, STATS_F].values.astype(float), D.loc[te, STATS_F].values.astype(float)
            Xf_tr, Xf_te = D.loc[tr, STATS_F + MKT_F].values.astype(float), D.loc[te, STATS_F + MKT_F].values.astype(float)
            out.loc[te, "ridge_stats"] = np.maximum(0.3, fit_ridge(Xs_tr, y, w, Xs_te))
            out.loc[te, "ridge_full"] = np.maximum(0.3, fit_ridge(Xf_tr, y, w, Xf_te))
            out.loc[te, "gbm_full"] = np.maximum(0.3, fit_gbm(Xf_tr, y, w, Xf_te))
            # MARKET-ANCHORED: the ADP curve is the prior (sportsbook-style: market first), the stats model only explains the
            # residual, heavily shrunk. Train-set curve is fit on the training seasons themselves.
            ta0 = tr & D.pos_adp.notna(); te0 = te & D.pos_adp.notna()
            if ta0.sum() > 50 and te0.sum() > 0:
                iso0 = IsotonicRegression(increasing=False, out_of_bounds="clip").fit(np.log(D.pos_adp[ta0]), D.act_ppg[ta0], sample_weight=D.act_games[ta0])
                c_tr = iso0.predict(np.log(D.pos_adp[ta0])); c_te = iso0.predict(np.log(D.pos_adp[te0]))
                wa = D.act_games[ta0].values.astype(float) * 0.5 ** ((Y - 1 - D.season[ta0].values) / 4.0)
                Xa_tr = D.loc[ta0, STATS_F].values.astype(float); Xa_te = D.loc[te0, STATS_F].values.astype(float)
                for nm_, al in (("anchor_r", 300.0), ("anchor_r30", 30.0)):
                    res_ = fit_ridge(Xa_tr, D.act_ppg[ta0].values - c_tr, wa, Xa_te, alpha=al)
                    out.loc[te0, nm_] = np.maximum(0.3, c_te + res_)
                res_g = fit_gbm(Xa_tr, D.act_ppg[ta0].values - c_tr, wa, Xa_te)
                out.loc[te0, "anchor_g"] = np.maximum(0.3, c_te + 0.5 * res_g)
            # quantile range on the ratio scale: q10 / q90 of log((act+1)/(pred+1)) from the TRAIN residuals of the same fit (in-sample
            # residuals understate spread, so the train residuals come from an inner walk-forward pass on the training seasons)
            # games share model on ALL training rows of the position (incl. 0-game seasons of ADP players)
            trg = (D.season < Y) & (D.pos == ps) & ((D.g1 > 0) | (D.adp.notna()))
            gy = (D.act_games[trg] / D.G[trg]).clip(0, 1).values
            out.loc[te, "games_pred"] = np.clip(fit_gbm(D.loc[trg, STATS_F + MKT_F].values.astype(float), gy, None, Xf_te), 0.05, 1.0)
            # ADP curve baselines (isotonic on log positional ADP rank)
            ta = tr & D.pos_adp.notna(); ea = te & D.pos_adp.notna()
            if ta.sum() > 30 and ea.sum() > 0:   # guard: no ADP rows in the test year (2026/27 in-house runs)
                iso = IsotonicRegression(increasing=False, out_of_bounds="clip").fit(np.log(D.pos_adp[ta]), D.act_ppg[ta], sample_weight=D.act_games[ta])
                out.loc[ea, "adp_curve"] = iso.predict(np.log(D.pos_adp[ea]))
                tt = (D.season < Y) & (D.pos == ps) & D.pos_adp.notna()
                iso2 = IsotonicRegression(increasing=False, out_of_bounds="clip").fit(np.log(D.pos_adp[tt]), D.act_total[tt])
                out.loc[ea, "adp_total"] = iso2.predict(np.log(D.pos_adp[ea]))
        # naive: last season PPG (4+ games), else mean of last two, else rookie mean by round from earlier seasons
        m = out.season == Y
        nv = np.where(out.g1 >= 4, out.ppg1, np.where(out.g2 >= 4, out.ppg2, np.nan))
        out.loc[m, "naive"] = nv[m.values]
        P(f"  fitted {Y}")
    out["ens"] = 0.5 * out.ridge_full + 0.5 * out.gbm_full
    # fill naive / adp gaps with the stats model so every baseline grades on the same rows (flagged in the report)
    out["naive_f"] = out.naive.fillna(out.ridge_stats)
    out["adp_curve_f"] = out.adp_curve.fillna(out.ridge_stats)
    out["anchor_f"] = out.anchor_r.fillna(out.ens)
    out["anchor_mix"] = (0.5 * out.anchor_r + 0.5 * out.anchor_g).fillna(out.ens)
    out["mkt50"] = (0.5 * out.ens + 0.5 * out.adp_curve).fillna(out.ens)
    out["total_pred"] = out.ens * out.games_pred * out.G
    out["total_anchor"] = out.anchor_mix * out.games_pred * out.G
    return out


def residual_quantiles(R, col="anchor_mix"):
    """walk-forward ratio-scale p10 / p90: quantiles of (act+1)/(pred+1) from earlier TEST seasons (true out-of-sample residuals)."""
    R = R.copy(); R["p10"] = np.nan; R["p90"] = np.nan; R["t10"] = np.nan; R["t90"] = np.nan
    for Y in TEST_YEARS[2:]:
        for ps in POS4:
            past = (R.season < Y) & (R.season >= 2015) & (R.pos == ps) & (R.act_games >= 4) & R[col].notna() & R.adp.notna()
            te = (R.season == Y) & (R.pos == ps)
            if past.sum() < 50: continue
            ratio = (R.act_ppg[past] + 1) / (R[col][past] + 1)
            lo, hi = np.quantile(ratio, [.10, .90])
            R.loc[te, "p10"] = (R[col][te] + 1) * lo - 1; R.loc[te, "p90"] = (R[col][te] + 1) * hi - 1
            pt = (R.season < Y) & (R.season >= 2015) & (R.pos == ps) & R.adp.notna() & R.total_anchor.notna()
            rt = (R.act_total[pt] + 5) / (R.total_anchor[pt] + 5)
            lo, hi = np.quantile(rt, [.10, .90])
            R.loc[te, "t10"] = (R.total_anchor[te] + 5) * lo - 5; R.loc[te, "t90"] = (R.total_anchor[te] + 5) * hi - 5
    return R


def attach_external(R):
    """ESPN week-1 projection, Clay fair per-game, engine week-1 base (shadow prior) on 2019-25."""
    R = R.copy()
    T = pd.read_parquet(os.path.join(SIM, "season_long_table.parquet"), columns=["year", "name", "pos", "prior", "clay"])
    T["key"] = T.name.map(nrm)
    tk = {(int(a), b, c): (p, cl) for a, b, c, p, cl in zip(T.year, T.key, T.pos, T.prior, T.clay)}
    R["engine_wk1"] = [tk.get((s, k, p), (np.nan, np.nan))[0] for s, k, p in zip(R.season, R.key, R.pos)]
    R["clay"] = [tk.get((s, k, p), (np.nan, np.nan))[1] for s, k, p in zip(R.season, R.key, R.pos)]
    # Clay for the whole Clay pool, not just the harness rows
    ch = json.load(open(os.path.join(REPO, "data", "clay_history.json"), encoding="utf-8"))
    cl = {}
    for y, d in ch.items():
        for nm, c in d.items():
            if c.get("pos") in POS4 and (c.get("gm") or 0) >= 4: cl[(int(y), nrm(nm), c["pos"])] = (max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0) / c["gm"], c.get("pts"), c.get("gm"))
    R["clay"] = [cl.get((s, k, p), (np.nan,))[0] for s, k, p in zip(R.season, R.key, R.pos)]
    R["clay_total_half"] = [((cl[(s, k, p)][1] or 0) - 0) if (s, k, p) in cl else np.nan for s, k, p in zip(R.season, R.key, R.pos)]
    def espn_half(s):
        g = lambda k: float(s.get(k, 0) or 0)
        return 0.04 * g("3") + 4 * g("4") - 1 * g("20") + 0.1 * g("24") + 6 * g("25") + 0.1 * g("42") + 6 * g("43") + 0.5 * g("53") - 2 * g("72")
    E = {}
    for Y in range(2019, 2026):
        f = os.path.join(CACHE, "espn_proj", f"espn_proj_{Y}.json")
        if not os.path.exists(f): continue
        d = json.load(open(f, encoding="utf-8"))
        for k, v in (d["weeks"].get("1") or {}).items():
            nm, ps = k.rsplit("|", 1); E[(Y, nrm(nm), ps)] = espn_half(v.get("s") or {})
    R["espn_wk1"] = [E.get((s, k, p), np.nan) for s, k, p in zip(R.season, R.key, R.pos)]
    R.loc[R.espn_wk1 <= 0.3, "espn_wk1"] = np.nan
    return R


# ---------------------------------------------------------------- grading
def wmae(p, a, w): return float(np.sum(w * np.abs(p - a)) / np.sum(w))
def wrmse(p, a, w): return float(np.sqrt(np.sum(w * (p - a) ** 2) / np.sum(w)))


def grade_ppg(R, cols, mask, label, base=None):
    m = mask & (R.act_games >= 4)
    for c in cols: m = m & R[c].notna()
    P(f"\n=== {label}: PPG (games-weighted), n={int(m.sum())} player-seasons ===")
    P(f"  {'model':16s} {'MAE':>6s} {'RMSE':>6s} {'bias':>6s} {'rho':>6s} {'top12':>6s} {'yrs<base':>8s}")
    a = R.act_ppg[m].values; w = R.act_games[m].values.astype(float)
    res = {}
    for c in cols:
        p = R[c][m].values
        rhos, hits, yrs = [], [], []
        for (y, ps), grp in R[m].groupby(["season", "pos"]):
            if len(grp) < 12: continue
            rhos.append(spearmanr(grp[c], grp.act_ppg).correlation)
            k = 12; hits.append(len(set(grp.nlargest(k, c).pid) & set(grp.nlargest(k, "act_ppg").pid)) / k)
        wins = 0; ny = 0
        if base is not None:
            for y in sorted(R[m].season.unique()):
                mm = m & (R.season == y)
                if mm.sum() < 20: continue
                ny += 1; wins += wmae(R[c][mm], R.act_ppg[mm], R.act_games[mm]) < wmae(R[base][mm], R.act_ppg[mm], R.act_games[mm])
        res[c] = dict(mae=wmae(p, a, w), rmse=wrmse(p, a, w), bias=float(np.sum(w * a) / np.sum(w * p)), rho=float(np.mean(rhos)), hit=float(np.mean(hits)), wins=wins, ny=ny)
        r = res[c]
        P(f"  {c:16s} {r['mae']:6.3f} {r['rmse']:6.3f} {r['bias']:6.3f} {r['rho']:6.3f} {r['hit']:6.3f} {str(wins)+'/'+str(ny) if base else '':>8s}")
    return res


def grade_total(R, cols, mask, label):
    m = mask.copy()
    for c in cols: m = m & R[c].notna()
    P(f"\n=== {label}: SEASON TOTAL (0 if he never played), n={int(m.sum())} ===")
    P(f"  {'model':16s} {'MAE':>7s} {'rho':>6s} {'top12':>6s} {'top24':>6s}")
    for c in cols:
        rhos, h12, h24 = [], [], []
        for (y, ps), grp in R[m].groupby(["season", "pos"]):
            if len(grp) < 24: continue
            rhos.append(spearmanr(grp[c], grp.act_total).correlation)
            h12.append(len(set(grp.nlargest(12, c).pid) & set(grp.nlargest(12, "act_total").pid)) / 12)
            h24.append(len(set(grp.nlargest(24, c).pid) & set(grp.nlargest(24, "act_total").pid)) / 24)
        P(f"  {c:16s} {np.mean(np.abs(R[c][m] - R.act_total[m])):7.2f} {np.mean(rhos):6.3f} {np.mean(h12):6.3f} {np.mean(h24):6.3f}")


def main():
    global LOG
    LOG = open(os.path.join(HERE, "preseason_backtest.log"), "w", encoding="utf-8")
    t0 = time.time()
    P("=== 2027 preseason prototype: walk-forward 2015-2025 (train on seasons < Y only) ===")
    D = build()
    R = walk_forward(D)
    R = residual_quantiles(R)
    R = attach_external(R)
    R.to_parquet(os.path.join(DATA, "preseason_backtest_rows.parquet"), index=False)
    pool = R.season.isin(TEST_YEARS) & R.adp.notna() & (R.adp <= 150)
    MODELS = ["anchor_mix", "anchor_f", "anchor_r30", "mkt50", "ens", "ridge_full", "gbm_full", "ridge_stats", "adp_curve_f", "naive_f"]
    grade_ppg(R, MODELS, pool, "ADP top-150 pool, 2015-25", base="adp_curve_f")
    for lab, mk in (("ADP 1-30", R.adp <= 30), ("ADP 31-100", (R.adp > 30) & (R.adp <= 100)), ("ADP 101-150", (R.adp > 100) & (R.adp <= 150))):
        grade_ppg(R, ["anchor_mix", "ens", "adp_curve_f", "naive_f"], pool & mk, lab, base="adp_curve_f")
    for ps in POS4:
        grade_ppg(R, ["anchor_mix", "ens", "ridge_stats", "adp_curve_f", "naive_f"], pool & (R.pos == ps), f"{ps} (ADP top 150)", base="adp_curve_f")
    grade_ppg(R, ["anchor_mix", "ens", "adp_curve_f"], pool & (R.rookie == 1), "rookies (ADP top 150)", base="adp_curve_f")
    # vs outside projections 2019-25
    p19 = pool & (R.season >= 2019)
    grade_ppg(R, ["anchor_mix", "ens", "adp_curve_f", "espn_wk1", "clay", "engine_wk1"], p19, "2019-25 vs ESPN wk1 / Clay / engine wk1 (rows with all five)", base="clay")
    R["anc_espn"] = 0.5 * R.anchor_mix + 0.5 * R.espn_wk1; R["anc_clay"] = 0.5 * R.anchor_mix + 0.5 * R.clay
    R["anc_espn_clay"] = (R.anchor_mix + R.espn_wk1 + R.clay) / 3
    grade_ppg(R, ["anchor_mix", "anc_espn", "anc_clay", "anc_espn_clay", "espn_wk1", "clay"], p19, "2019-25 ensembles", base="clay")
    # season totals (what a draft buys)
    grade_total(R, ["total_anchor", "total_pred", "adp_total"], pool, "ADP top-150 pool, 2015-25")
    # ranges
    cov = pool & (R.act_games >= 4) & R.p10.notna()
    inr = ((R.act_ppg >= R.p10) & (R.act_ppg <= R.p90))[cov]
    P(f"\n=== Ranges (walk-forward residual quantiles, 2017-25): PPG p10-p90 coverage {inr.mean()*100:.1f}% (target 80), below {(R.act_ppg < R.p10)[cov].mean()*100:.1f}, above {(R.act_ppg > R.p90)[cov].mean()*100:.1f}")
    for ps in POS4:
        mm = cov & (R.pos == ps)
        P(f"  {ps}: {((R.act_ppg >= R.p10) & (R.act_ppg <= R.p90))[mm].mean()*100:.1f}% (n {int(mm.sum())})")
    ct = pool & R.t10.notna()
    P(f"  season TOTAL p10-p90 coverage {((R.act_total >= R.t10) & (R.act_total <= R.t90))[ct].mean()*100:.1f}% (n {int(ct.sum())}); below p10 {(R.act_total < R.t10)[ct].mean()*100:.1f}%")
    P(f"\n  games model: mean predicted share {R.games_pred[pool].mean():.3f} vs actual {(R.act_games/R.G)[pool].mean():.3f}; corr {pd.Series(R.games_pred[pool]).corr((R.act_games/R.G)[pool]):.3f}")
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
