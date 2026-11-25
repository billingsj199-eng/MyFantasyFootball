#!/usr/bin/env python3
"""
In-house preseason rankings (NO ADP input anywhere; ADP is only a comparison column). Jack 2026-11-21: "lets see what it looks
like without adp for now".

  A. 2026 check: the model as it would have run before week 1 of 2026 (training on 2012-25, features from seasons <= 2025,
     the ESPN depth chart of 2026-09-11 15:07 ET from the repo git history (commit c9e33926; the first pre-Sunday chart with WRs - earlier pulls had no WR lists; only the Thursday opener had been played), 2026 expected wins from the frozen preseason
     game lines (sim_lab/data/preseason_lines_2026_frozen.js, 2026-08-26), 2026 rookies + draft capital). Actual 2026 so far =
     weeks 1-10 from play_by_play_2026 (later weeks excluded). Comparison ADP = Underdog best-ball ADP of 2026-09-03
     (repo data/ud_adp_history.json; best ball, half-PPR scoring).
  B. Early 2027 look: features from 2026 weeks 1-10 (partial season, games scaled to a 17-game rate), roles = RB / WR / TE
     by 2026 usage per game (3+ games; WRs two to a string - A21 hybrid, adopted 2026-11-24), QBs by the current ESPN depth
     chart (sim_lab/data/sim_depth.js) + most 2026 starts, no 2027 rookies, no 2027 win totals (team expected wins = unknown ->
     the training median), age + 1.
Model = the final in-house per-game model (A7: S6 = .75 x lean structural + .25 x ridge, no ADP) x the in-house games-played
model (A2). Format: half-PPR (the prototype's native scoring), 12-team 1QB (QB/2RB/3WR/TE/FLEX) for the overall VOR order.
Writes output/2026_inhouse_check.md|csv, output/2027_inhouse_early.md|csv, output/output_rankings.log. Read-only elsewhere.
"""
import inspect, json, os, re, shutil, sys, time, warnings, zlib
import numpy as np
import pandas as pd
from scipy.stats import norm as N

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "output"); WORK = os.path.join(OUT, "_work"); os.makedirs(WORK, exist_ok=True)
import preseason_model as PM
import games_model as GM
import pergame_model as G
import build_player_weeks as BPW
import fixes_a9 as FX

LAST_WK = int(os.environ.get("PRE27_LAST_WK", "10"))   # refresh_2027.py sets this to the latest completed 2026 week
REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"
LOG = None
# v7 (Jack 2026-11-21 "Yes, ranges only"): the A14 RB VOLUME change (share inputs + half-way team rescale) is switched OFF;
# RB averages are v5's. The A14 RB ranges by backfield tier stay ON. Re-test the volume change after the full 2026 season.
RB_VOLUME_V6 = False
RB_TIER_RANGES = True
REPL = {"QB": 12, "RB": 31, "WR": 41, "TE": 12}      # 12-team half-PPR 1QB starters incl. flex share (review part 21/22 table)


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def nrm(s): return PM.nrm(s)


# ------------------------------------------------------------------ 2026 data into a private work dir
def build_work_data():
    W26, TG26 = BPW.season(2026)
    W26 = W26[W26.week <= LAST_WK]
    pl = pd.read_csv(os.path.join(PM.CACHE, "players.csv"), low_memory=False,
                     usecols=["gsis_id", "display_name", "position", "birth_date", "rookie_season", "draft_year", "draft_round", "draft_pick"]).drop_duplicates("gsis_id")
    dp = pd.read_parquet(os.path.join(PM.CACHE, "draft_picks.parquet"), columns=["season", "pick", "gsis_id", "position"])
    dp = dp[dp.gsis_id.notna()].drop_duplicates("gsis_id").rename(columns={"season": "dp_year", "pick": "dp_pick", "position": "dp_pos"})
    W26 = W26.merge(pl.rename(columns={"gsis_id": "pid"}), on="pid", how="left").merge(dp.rename(columns={"gsis_id": "pid"}), on="pid", how="left")
    POV = PM.position_overrides()   # A9 fix 3
    W26["position"] = [POV.get((p_, 2026), ps) for p_, ps in zip(W26.pid, W26.position)]
    W26 = W26[W26.position.isin(["QB", "RB", "WR", "TE", "FB"])].copy(); W26.loc[W26.position == "FB", "position"] = "RB"
    Wall = pd.concat([pd.read_parquet(os.path.join(PM.DATA, "player_weeks.parquet")), W26], ignore_index=True)
    Wall.to_parquet(os.path.join(WORK, "player_weeks.parquet"), index=False)
    # team games 2026 (completed weeks) from the schedule
    S = pd.read_csv(os.path.join(PM.CACHE, "schedules_games.csv")); S = S[(S.game_type == "REG") & (S.season == 2026) & (S.week <= LAST_WK) & S.home_score.notna()]
    rec = []
    for r in S.itertuples(index=False):
        h, a = PM.tm(r.home_team), PM.tm(r.away_team)
        for team, opp, home, pf, pa in ((h, a, 1, r.home_score, r.away_score), (a, h, 0, r.away_score, r.home_score)):
            rec.append({"game_id": r.game_id, "season": 2026, "week": r.week, "team": team, "opp": opp, "home": home, "pf": pf, "pa": pa,
                        "exp_margin": r.spread_line if home else -r.spread_line, "total_line": r.total_line, "div_game": r.div_game, "roof": r.roof,
                        "wind": r.wind, "temp": r.temp, "overtime": r.overtime, "ml": np.nan, "rest": np.nan, "neutral": int(r.location == "Neutral")})
    G26 = pd.DataFrame(rec).merge(TG26.drop(columns=["week", "season"]), on=["game_id", "team"], how="left")
    pd.concat([pd.read_parquet(os.path.join(PM.DATA, "team_games.parquet")), G26], ignore_index=True).to_parquet(os.path.join(WORK, "team_games.parquet"), index=False)
    # 2026 expected wins from the frozen preseason game lines
    s = open(os.path.join(PM.SIM, "data", "preseason_lines_2026_frozen.js"), encoding="utf-8").read()
    ew = {}
    for wk, aw, hm, tot, sp in re.findall(r"'W(\d+)_([A-Z]+)_([A-Z]+)'\s*:\s*\{\s*total:\s*([\d.]+),\s*spread:\s*(-?[\d.]+)", s):
        p_home = N.cdf(-float(sp) / 13.0)
        ew[PM.tm(hm)] = ew.get(PM.tm(hm), 0) + p_home; ew[PM.tm(aw)] = ew.get(PM.tm(aw), 0) + 1 - p_home
    wt = pd.read_csv(os.path.join(PM.DATA, "win_totals_2012_2025.csv"))
    add = pd.DataFrame([{"season": 2026, "team": t, "win_total": round(v, 2), "over_odds": "-110", "under_odds": "-110", "source_url": "derived: preseason_lines_2026_frozen.js spreads"} for t, v in ew.items()])
    pd.concat([wt, add], ignore_index=True).to_csv(os.path.join(WORK, "win_totals_2012_2025.csv"), index=False)
    P(f"  2026 work data: {len(W26)} player-games weeks 1-{LAST_WK}; {len(G26)} team-games; 2026 expected wins for {len(ew)} teams (from preseason game lines)")
    return W26


def load_chart(path, var):
    s = open(path, encoding="utf-8").read(); m = re.search(var + r"\s*=\s*(\{.*\})", s, re.S)
    return json.loads(m.group(1))["teams"]


def name_index():
    pl = pd.read_csv(os.path.join(PM.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "display_name", "position", "latest_team"])
    POV = PM.position_overrides()   # A9 fix 3: latest override position per player
    last = {}
    for (g, y), ps in sorted(POV.items(), key=lambda t: t[0][1]): last[g] = ps
    pl["position"] = [last.get(g, ps) for g, ps in zip(pl.gsis_id, pl.position)]
    pl = pl[pl.gsis_id.notna() & pl.position.isin(["QB", "RB", "WR", "TE", "FB"])]
    idx = {}
    for g, n, p in zip(pl.gsis_id, pl.display_name, pl.position):
        idx.setdefault((nrm(n), "RB" if p == "FB" else p), []).append(g)
    return idx


def chart_maps(teams, idx, recent):
    """chart -> ({gsis: (team, rank)}, {team: QB1 gsis}); ambiguous names resolved by who played most recently."""
    dc, qb1 = {}, {}
    for t, pos in teams.items():
        t2 = PM.tm(t)
        for ps in ("QB", "RB", "WR", "TE"):
            for i, nm in enumerate(pos.get(ps, [])):
                c = idx.get((nrm(nm), ps), [])
                if len(c) > 1: c = sorted(c, key=lambda g: -recent.get(g, 0))
                if not c: continue
                dc[c[0]] = (t2, i + 1)
                if ps == "QB" and i == 0: qb1[t2] = c[0]
    return dc, qb1


def patch(dc26, qb26, dc27, qb27, team26, team27):
    PM.DATA = WORK; G.DATA = WORK; GM.DATA = WORK
    o_team, o_depth = PM.week1_team, PM.week1_depth
    def week1_team():
        d = o_team()
        for g, t in team26.items(): d[(2026, g)] = t
        for g, t in team27.items(): d[(2027, g)] = t
        return d
    def week1_depth():
        d, q = o_depth()
        for g, (t, r) in dc26.items(): d[(2026, g)] = r
        for g, (t, r) in dc27.items(): d[(2027, g)] = r
        for t, g in qb26.items(): q[(2026, t)] = g
        for t, g in qb27.items(): q[(2027, t)] = g
        return d, q
    PM.week1_team = week1_team; PM.week1_depth = week1_depth
    src = inspect.getsource(PM.build).replace("for Y in range(2013, 2026):", "for Y in range(2013, 2028):")
    exec(compile(src, "PM.build(patched)", "exec"), PM.__dict__)


def rb_backfield_v6(D, S, comp7, Y):
    """v6 (A14): RB volume from share inputs (last-season shares of the team's RB carries / RB targets / goal-line carries,
    RB investment, a rd 1-3 back added, rushing-QB share, new play-caller, team RB volume last season) in the RB volume
    ridge, then each team's listed backs rescaled HALF-WAY (alpha .5) toward a walk-forward team total for RB carries and
    RB targets per team game. Only RB rows change: per-game += .75 x structural change. Tier (lead / committee / backup /
    rookie) is kept for the RB range spread."""
    import rb_a14_common as RC, rb_a14_build as RB
    GLx = RC.gl_table()
    if Y >= 2027: GLx = pd.concat([GLx, RC.gl_extra(2026, LAST_WK)], ignore_index=True)
    D = RC.rb_features(D, S, GLx=GLx, max_year=Y).reset_index(drop=True)
    for k, v in comp7.items(): D[k] = v.values
    D["g_use"] = D.g_main
    LEAN = G.BASIC + G.ROSTER + ["lp_rook"]
    D["rb_tier"] = np.select([D.rookie == 1, D.dc.isin([1, 2]) & (D.moved == 0) & D.q_car1.between(.25, .5), (D.dc == 1)], ["rookie", "committee", "lead back"], "backup")
    D["ppg_v5"] = D.ppg
    if not RB_VOLUME_V6:   # v7: v5 averages; v5 volumes kept only as table columns
        D = RB.team_model(D, keep_year=Y, quiet=True)
        D["rb_car_pg"] = np.where(D.pos == "RB", D.S7_v_car, np.nan); D["rb_tgt_pg"] = np.where(D.pos == "RB", D.S7_v_tgt, np.nan)
        P(f"  v7 ({Y}): RB volume change OFF (v5 averages); RB tier ranges {'ON' if RB_TIER_RANGES else 'OFF'}")
        return D
    b_c = RB.ridge_vol(D, LEAN, "y_carpg"); b_t = RB.ridge_vol(D, LEAN, "y_tgtpg")
    x_c = RB.ridge_vol(D, LEAN + RB.EXTRA, "y_carpg"); x_t = RB.ridge_vol(D, LEAN + RB.EXTRA, "y_tgtpg")
    D = RB.team_model(D, keep_year=Y, quiet=True)
    vc, vt = D.S7_v_car, D.S7_v_tgt
    nc, nt = RB.rescale(D, vc + (x_c - b_c), vt + (x_t - b_t), 0.5)
    rv = 0.1 * D.S7_e_ryd_c + 6 * D.S7_e_rtd_c; tv = 0.5 * D.S7_e_rec_t + 0.1 * D.S7_e_cyd_t + 6 * D.S7_e_ctd_t
    d = ((nc - vc) * rv + (nt - vt) * tv).where(D.pos == "RB", 0.0).fillna(0.0)
    D["ppg_v5"] = D.ppg
    D["ppg"] = np.where(D.pos == "RB", np.maximum(0.3, D.ppg + 0.75 * d), D.ppg)
    D["rb_car_pg"] = np.where(D.pos == "RB", nc, np.nan); D["rb_tgt_pg"] = np.where(D.pos == "RB", nt, np.nan)
    D["T_car_hat"] = D.T_car_hat; D["T_tgt_hat"] = D.T_tgt_hat
    D["rb_tier"] = np.select([D.rookie == 1, D.dc.isin([1, 2]) & (D.moved == 0) & D.q_car1.between(.25, .5), (D.dc == 1)], ["rookie", "committee", "lead back"], "backup")
    P(f"  v6 RB backfield ({Y}): RB rows changed {int(((D.pos == 'RB') & (D.season == Y) & (D.ppg != D.ppg_v5)).sum())}; mean RB per-game change {(D.ppg - D.ppg_v5)[(D.pos == 'RB') & (D.season == Y)].mean():+.2f}")
    return D


def run_year(D_all, Y, AV, wk1, partial_hist):
    """v2 (A9): fix 1 (last season's games share shrunk toward the player's own longer-run rate for established starters),
    fix 3 (position overrides, applied when the tables are built), fix 4 (games distribution recalibrated walk-forward on the
    model's OWN top-150 history + per-game spread from those draftable rows), backup-RB take-over probability shown as
    information only (it did not improve the mean on history). The whole 2015-25 history is walked forward in the same run so
    the calibration and spread use only seasons before Y."""
    from sklearn.isotonic import IsotonicRegression
    D = D_all[(D_all.season < 2026) | (D_all.season == Y)].copy().reset_index(drop=True)
    PM.TEST_YEARS = list(range(2015, 2026)) + [Y]
    D = GM.add_features(D, AV, wk1)
    te = D.season == Y
    for c in ("w1_res", "w1_sus", "w1_off", "w1_out", "w1_q"): D.loc[te, c] = 0.0     # week-1 roster/report status not on disk for 2026/27
    if Y == 2027:   # 2026 availability from the partial season (games share of team games so far)
        ph = partial_hist.set_index("pid")
        D.loc[te, "gs1"] = D.loc[te, "pid"].map(ph.gshare).values
        for c in ("inj1", "role1", "resw1", "outw1", "snap1", "big1"): D.loc[te, c] = np.nan
        D.loc[te, "tpg1x"] = D.loc[te, "pid"].map(ph.tpg).values
    S = G.stat_seasons()
    D = G.add_history(D, S); D = G.add_context(D, S)
    if Y == 2027:   # 17-game rate for the partial 2026 season counts that feed volume features
        sc = D.loc[te, "pid"].map(partial_hist.set_index("pid").scale).fillna(1.0).values
        D.loc[te, "h1_g"] = D.loc[te, "h1_g"].values * sc
        D.loc[te, "g1"] = D.loc[te, "g1"].values * sc
        D.loc[te, "gsh1"] = D.loc[te, "pid"].map(partial_hist.set_index("pid").gshare).values
    D = FX.add_fix1_features(D)
    R0 = PM.walk_forward(D)
    D["ridge_stats"] = R0.ridge_stats.values
    feats = [f if f != "gs1" else "gs1_shrunk" for f in GM.GF]
    O = GM.walk(D, feats, "g")
    D = pd.concat([D, O], axis=1)
    D["g_main"] = 0.75 * D.g_ridge + 0.25 * D.g_dist
    hist = D.season.between(2015, 2025)
    br = [np.mean(np.digitize(D.miss[hist & D.rel], [2, 4, 8]) == k) for k in range(4)]
    for k in range(4): D[f"g_pb{k}"] = 0.8 * D[f"g_pb{k}"] + 0.2 * br[k]
    s7, comp7, _ = G.walk(D, G.BASIC + G.ROSTER + ["lp_rook"], "S7", use_role_prior=True)
    D["s7"] = s7.values
    D["ppg"] = 0.75 * D.s7 + 0.25 * D.ridge_stats
    D = rb_backfield_v6(D, S, comp7, Y)
    # fix 4: isotonic on the model's own top 150 (by projected total) of earlier seasons
    D["tot_m"] = D.ppg * D.g_main * D.G
    D["mtop"] = D.groupby("season").tot_m.rank(ascending=False) <= 150
    fit = hist & D.mtop & D.g_pb0.notna()
    c = {2: D.g_pb1 + D.g_pb2 + D.g_pb3, 4: D.g_pb2 + D.g_pb3, 8: D.g_pb3}; a = {}
    for k in c:
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(c[k][fit], (D.miss[fit] >= k).astype(float))
        a[k] = iso.predict(c[k].fillna(c[k][fit].mean()))
    a4 = np.minimum(a[4], a[2]); a8 = np.minimum(a[8], a4)
    pb = np.clip(np.column_stack([1 - a[2], a[2] - a4, a4 - a8, a8]), 1e-4, None); pb = pb / pb.sum(1, keepdims=True)
    for k in range(4): D[f"g_pb{k}"] = pb[:, k]
    ratios = {ps: ((D.act_ppg[hist & D.mtop & (D.pos == ps) & (D.act_games >= 4)] + 1) /
                              (D.ppg[hist & D.mtop & (D.pos == ps) & (D.act_games >= 4)] + 1)).values for ps in PM.POS4}
    for t_ in ("lead back", "committee", "backup", "rookie") if RB_TIER_RANGES else ():    # A14: RB spread by backfield tier (kept in v7)
        mt = hist & (D.pos == "RB") & (D.rb_tier == t_) & D.dc.isin([1, 2, 3]) & (D.act_games >= 4)
        if mt.sum() >= 30: ratios[f"RB:{t_}"] = ((D.act_ppg[mt] + 1) / (D.ppg[mt] + 1)).values
    ratios = {k_: np.sort(v_) for k_, v_ in ratios.items()}    # v7: sorted so the seeded draws do not depend on run-dependent row order
    # backup-RB take-over probability (information column)
    D = FX.takeover_table(D)
    pt = FX.fit_takeover(D, Y)
    D["p_take"] = np.nan; D.loc[pt.index, "p_take"] = pt.values
    # v4 (A11): QB job security - P(lose the job while healthy) from point-in-time contracts (cap share), a QB drafted in
    # rounds 1-2 this year or last behind him, and team outlook (expected wins). Logistic fit on 2013-25 week-1 QB1 history.
    # Applied to week-1 QB1s as  games share - (P - base rate) x games lost when benched / G  (the A11 walk-forward winner).
    import qb_a11 as JS
    K, _ = JS.contracts_asof(range(2013, Y + 1))
    D["money"] = [K.get((y, p_), {}).get("apy_cap", np.nan) for y, p_ in zip(D.season, D.pid)]
    dp = pd.read_parquet(os.path.join(PM.CACHE, "draft_picks.parquet"), columns=["season", "pick", "team", "position", "gsis_id"]); dp["team"] = dp.team.map(PM.tm)
    hi = {}
    for r_ in dp[(dp.position == "QB") & (dp.pick <= 64)].itertuples(index=False):
        for yy in (r_.season, r_.season + 1): hi.setdefault((yy, r_.team), set()).add(r_.gsis_id)
    D["comp_hi"] = [float(len(hi.get((y, t), set()) - {p_}) > 0) for y, t, p_ in zip(D.season, D.team, D.pid)]
    # v5 (A13): one "investment" input replaces cap share, so a rookie deal's small cap share is not read as a weak hold:
    # inv = max(min(1, cap share / .15), draft score x fade); draft score = 1 - log(pick)/log(262) (UDFA 0), fade = max(0, 1 - exp/5).
    rkd = pd.Series([K.get((y, p_), {}).get("rookie_deal", np.nan) for y, p_ in zip(D.season, D.pid)], index=D.index)
    D["dscore"] = np.where(D.undrafted == 1, 0.0, (1 - D.lpick / np.log(262)).clip(0, 1))
    D["inv"] = np.maximum((D.money / .15).clip(0, 1).fillna(0), D.dscore * (1 - D.exp / 5).clip(lower=0))
    rk_deal = (D.exp <= 3) & (rkd.fillna(1) == 1)
    D.loc[D.money.isna() & ~rk_deal, "inv"] = np.nan
    qb1h = (D.pos == "QB") & (D.is_qb1 == 1) & D.season.between(2013, 2025)
    H_ = JS.outcomes(D[qb1h].copy()); bench = (H_.healthy_lost_wks >= 2).astype(float)
    F = ["inv", "comp_hi", "exp_w"]
    tgt = (D.pos == "QB") & (D.is_qb1 == 1) & (D.season == Y)
    D["p_bench"] = np.nan
    if tgt.sum():
        D.loc[tgt, "p_bench"] = JS.logit_fit(H_[F].values.astype(float), bench.values, D.loc[tgt, F].values.astype(float))
    base_rate = float(bench.mean()); lost = (H_.act_games[bench == 0].mean() - H_.act_games[bench == 1].mean()) / 16.5
    D["g_main_v3"] = D.g_main
    D.loc[tgt, "g_main"] = (D.g_main[tgt] - (D.p_bench[tgt] - base_rate) * lost).clip(.05, 1)
    D["g_ratio"] = (D.g_main / D.g_main_v3).fillna(1.0)
    out = D[D.season == Y].copy(); out.attrs["ratios"] = ratios
    return out


def ranges(R):
    """p10 / p90 of PPG and season total: per-game spread from the model's own draftable (top-150) history rows x the
    recalibrated games distribution (A9 fix 4)."""
    rat = R.attrs["ratios"]
    rng = np.random.default_rng(11); BINS = [(0, 1), (2, 3), (4, 7), (8, 99)]
    out = []
    for r in R.itertuples(index=False):
        Gm = 17; ra = rat[r.pos]
        rt = rat.get(f"RB:{getattr(r, 'rb_tier', '')}") if r.pos == "RB" else None
        if rt is not None: ra = rt      # A14: RB spread by backfield tier
        # v7: one seeded stream per player (was one shared stream in row order, and the row order is not stable between runs,
        # so every earlier version's ranges re-drew by a few points on each run)
        rng = np.random.default_rng([11, zlib.crc32(str(r.pid).encode())])
        pb = np.array([r.g_pb0, r.g_pb1, r.g_pb2, r.g_pb3]); pb = np.clip(np.nan_to_num(pb, nan=.25), 1e-6, None); pb /= pb.sum()
        k = rng.choice(4, 3000, p=pb); lo = np.array([BINS[j][0] for j in k]); hi = np.array([min(BINS[j][1], Gm) for j in k])
        gm = np.clip(Gm - np.floor(lo + rng.random(3000) * (hi - lo + 1)), 0, Gm) * getattr(r, "g_ratio", 1.0)
        q10, q90 = np.quantile((r.ppg + 1) * ra - 1, [.1, .9])
        draw = rng.choice(ra, 3000)
        tot = np.maximum(0, (r.ppg + 1) * draw - 1) * gm
        # format columns (2026-11-23): the SAME 3000 seeded draws (games + per-game ratio) applied to the PPR / STD per-game
        # mean (half +/- .5 x the model's receptions per game), so half-PPR numbers are unchanged and the three formats share sims
        rp = float(getattr(r, "rec_pg", 0.0) or 0.0); rp = 0.0 if rp != rp else rp
        tp = np.maximum(0, (r.ppg + .5 * rp + 1) * draw - 1) * gm
        ts = np.maximum(0, (max(0.0, r.ppg - .5 * rp) + 1) * draw - 1) * gm
        out.append((max(0, q10), q90, np.quantile(tot, .1), np.quantile(tot, .9), np.quantile(tp, .1), np.quantile(tp, .9), np.quantile(ts, .1), np.quantile(ts, .9)))
    R["ppg_p10"], R["ppg_p90"], R["tot_p10"], R["tot_p90"], R["tot_p10_ppr"], R["tot_p90_ppr"], R["tot_p10_std"], R["tot_p90_std"] = zip(*out)
    return R


def rec_cols(R):
    """Receptions per game from the model's own structural part (S7: targets/g x catch rate). The half-PPR ppg is
    .75 x S7 + .25 x ridge; the ridge has no reception split, so the S7 reception projection stands for the whole."""
    v = R["S7_v_tgt"] if "S7_v_tgt" in R else 0.0
    e = R["S7_e_rec_t"] if "S7_e_rec_t" in R else 0.0
    R["rec_pg"] = (pd.Series(v, index=R.index).fillna(0) * pd.Series(e, index=R.index).fillna(0)).clip(lower=0)
    return R


def fmt_totals(R):
    R["ppg_ppr"] = R.ppg + .5 * R.rec_pg; R["ppg_std"] = (R.ppg - .5 * R.rec_pg).clip(lower=0)
    R["total_ppr"] = R.ppg_ppr * R.games; R["total_std"] = R.ppg_std * R.games
    return R


def finish(R):
    R["games"] = R.g_main * 17
    R["total"] = R.ppg * R.games
    R["pos_rank"] = R.groupby("pos").total.rank(ascending=False, method="first").astype(int)
    repl = {ps: R[R.pos == ps].sort_values("total", ascending=False).total.values[min(REPL[ps], (R.pos == ps).sum() - 1)] for ps in PM.POS4}
    R["vor"] = R.total - R.pos.map(repl)
    # v7: ties (the replacement-level players all sit at VOR 0) broken by total, then name, not by run-dependent row order
    R = R.sort_values(["vor", "total", "name"], ascending=[False, False, True]); R["rank"] = np.arange(1, len(R) + 1)
    return R.sort_values("rank")


def md_table(df, cols, heads):
    lines = ["| " + " | ".join(heads) + " |", "|" + "---|" * len(heads)]
    for r in df[cols].itertuples(index=False):
        lines.append("| " + " | ".join("" if (isinstance(v, float) and np.isnan(v)) else (f"{v:.1f}" if isinstance(v, float) else str(v)) for v in r) + " |")
    return "\n".join(lines)


def main():
    global LOG
    LOG = open(os.path.join(OUT, "output_rankings.log"), "w", encoding="utf-8")   # earlier logs kept as output_rankings_v1..v6.log
    t0 = time.time()
    P("=== In-house rankings (no ADP input) ===")
    W26 = build_work_data()
    idx = name_index()
    recent = W26.groupby("pid").week.max().to_dict()
    ch26 = load_chart(os.path.join(WORK, "depth_charts_2026_preseason.js"), r"window\.DEPTH_2026")
    ch27 = load_chart(os.path.join(PM.SIM, "data", "sim_depth.js"), r"window\.SIM_DEPTH_2026")
    dc26, qb26 = chart_maps(ch26, idx, recent); dc27, qb27 = chart_maps(ch27, idx, recent)
    # 2027 ROLE RULE = HYBRID (A21 "USEPGQ2"; Jack 2026-11-24: "Yes, QBs unchanged"; evidence _board_tests/a21_depth_history.log,
    # a21_stability_roles.log, a21_qb_hybrid.log, usepgq_compare.log; write-up output/preseason_2027_readiness.md sections I, I10).
    #   RB / WR / TE: role = usage per game played this season on his latest team (RB carries, WR / TE targets; players with
    #     3+ games), ranked within team and position and read as a depth STRING: WRs two to a string (WR1-2 = 1, WR3-4 = 2,
    #     ...), RB / TE one. Today's ESPN chart is NOT used for them (it moved players day to day and was read as a rank: one
    #     WR per team at depth 1). Under 3 games this season = no role (the model's "not listed" input).
    #   QB: unchanged v3 (A10) rule - the CURRENT chart lists injured starters behind their backups (Lamar, Hurts were 2nd on
    #     2026-11-21), so rank = min(current chart rank, his 2026 starts rank on that team), and QB1 = the QB with the most
    #     2026 starts (15+ attempts) for the team. (Usage per game was NOT adopted for QBs: pass attempts per game put
    #     fill-ins ahead of injured starters. The all-positions build is kept in output_rankings.py.usepg2_adopted_20261124_held.)
    # The whole v3 block is kept in output_rankings.py.pre_usepg2_20261124. Only the 2027 look uses this; the 2026 check keeps
    # its preseason chart.
    use = W26.groupby(["pid", "team"]).agg(att=("att", "sum"), car=("car", "sum"), tgt=("tgt", "sum"), starts=("att", lambda x: int((x >= 15).sum()))).reset_index()
    posof = {}
    for (n_, ps), gl in idx.items():
        for g_ in gl: posof.setdefault(g_, ps)
    use["pos"] = use.pid.map(posof); use["vol"] = np.where(use.pos == "QB", use.starts, np.where(use.pos == "RB", use.car, use.tgt))
    use["urank"] = use.groupby(["team", "pos"]).vol.rank(ascending=False, method="first")
    qd_ = {g_: v_ for g_, v_ in dc27.items() if posof.get(g_) == "QB"}                      # QBs: chart index, then min with the starts rank
    for r_ in use.itertuples(index=False):
        if r_.pos == "QB" and r_.pid in qd_ and qd_[r_.pid][0] == r_.team and r_.vol > 0:
            qd_[r_.pid] = (r_.team, int(min(qd_[r_.pid][1], r_.urank)))
    for t_, g_ in use[(use.pos == "QB")].sort_values("starts", ascending=False).drop_duplicates("team")[["team", "pid"]].values:
        if use[(use.team == t_) & (use.pos == "QB")].starts.max() >= 3 and g_ in qd_ and qd_[g_][0] == t_: qb27[t_] = g_
    _lt = W26.sort_values("week").groupby("pid").team.last()                              # RB / WR / TE: usage per game on the latest team
    _w = W26[W26.team == W26.pid.map(_lt)]
    U_ = _w.groupby(["pid", "team"]).agg(games=("week", "nunique"), car=("car", "sum"), tgt=("tgt", "sum")).reset_index()
    U_["pos"] = U_.pid.map(posof); U_ = U_[U_.pos.isin(["RB", "WR", "TE"])].copy()
    U_["vol"] = np.where(U_.games >= 3, np.where(U_.pos == "RB", U_.car, U_.tgt) / U_.games, np.nan)
    U_ = U_[U_.vol > 0].copy(); U_["urank"] = U_.groupby(["team", "pos"]).vol.rank(ascending=False, method="first")
    dc27 = {r_.pid: (r_.team, int(np.ceil(r_.urank / 2)) if r_.pos == "WR" else int(r_.urank)) for r_ in U_.itertuples(index=False)}
    dc27.update(qd_)
    first_team = W26.sort_values("week").groupby("pid").team.first().to_dict(); last_team = W26.sort_values("week").groupby("pid").team.last().to_dict()
    team26 = {g: t for g, (t, r) in dc26.items()}
    for g, t in first_team.items(): team26.setdefault(g, t)
    team27 = {g: t for g, (t, r) in dc27.items()}
    for g, t in last_team.items(): team27.setdefault(g, t)
    P(f"  charts: 2026 preseason {len(dc26)} skill players / {len(qb26)} QB1s; current {len(dc27)} / {len(qb27)}")
    patch(dc26, qb26, dc27, qb27, team26, team27)
    D_all = PM.build()
    AV, wk1 = GM.availability()
    # partial 2026 history (for 2027): games share of team games so far, touches per game, 17-game scale
    tg = W26.groupby("team").week.nunique()
    ph = W26.groupby("pid").agg(g=("week", "nunique"), team=("team", "last"), tch=("tgt", "sum"), car=("car", "sum")).reset_index()
    ph["tgames"] = ph.team.map(tg); ph["gshare"] = (ph.g / ph.tgames).clip(0, 1); ph["tpg"] = (ph.tch + ph.car) / ph.g; ph["scale"] = 17 / ph.tgames
    # ---------------- A. 2026
    R26 = run_year(D_all, 2026, AV, wk1, ph)
    rat = R26.attrs["ratios"]; R26 = R26[R26.ppg.notna()].copy(); R26.attrs["ratios"] = rat
    R26 = finish(ranges(R26))
    ud = json.load(open(os.path.join(REPO, "data", "ud_adp_history.json"), encoding="utf-8"))
    pre = [d for d in ud["days"] if d["date"] <= "2026-09-09"][-1]
    adp = {nrm(k): v.get("bbm") for k, v in pre["adps"].items() if v.get("bbm")}
    R26["adp"] = R26.key.map(adp)
    R26["adp_rank"] = R26.adp.rank(method="first")
    R26["adp_pos_rank"] = R26.groupby("pos").adp.rank(method="first")
    # actual so far: weeks 1-10
    act = W26.groupby("pid").agg(g26=("week", "nunique"), pts26=("half", "sum")).reset_index()
    R26 = R26.merge(act, on="pid", how="left"); R26["ppg26"] = R26.pts26 / R26.g26
    R26["act_pos_rank"] = R26.groupby("pos").pts26.rank(ascending=False, method="first")
    R26 = R26.sort_values("rank")
    cols = ["rank", "name", "pos", "team", "pos_rank", "ppg", "games", "total", "tot_p10", "tot_p90", "adp_rank", "adp_pos_rank", "ppg26", "g26", "act_pos_rank"]
    R26["p_bench"] = R26.p_bench
    R26["p_take"] = np.where((R26.pos == "RB") & (R26.dc == 2), R26.p_take, np.nan)
    R26[cols + ["age", "rookie", "dc", "p_take", "p_bench", "rb_car_pg", "rb_tgt_pg", "T_car_hat", "T_tgt_hat", "rb_tier", "ppg_v5"]].to_csv(os.path.join(OUT, "2026_inhouse_check.csv"), index=False)
    # disagreements: overall rank vs ADP rank, among players either list has in its top 150
    Z = R26[(R26.adp_rank <= 150) | (R26["rank"] <= 150)].copy()
    Z["diff"] = Z.adp_rank.fillna(200) - Z["rank"]      # > 0 = model higher than ADP
    hi = Z.sort_values("diff", ascending=False).head(15); lo = Z.sort_values("diff").head(15)
    def verdict(r):
        if np.isnan(r.act_pos_rank) or (r.g26 or 0) < 3: return "too few games"
        a, m_, d_ = r.act_pos_rank, r.pos_rank, (r.adp_pos_rank if not np.isnan(r.adp_pos_rank) else 99)
        return "model" if abs(a - m_) < abs(a - d_) else ("ADP" if abs(a - d_) < abs(a - m_) else "tie")
    for T in (hi, lo): T["closer"] = [verdict(r) for r in T.itertuples(index=False)]
    tally = pd.concat([hi, lo]).closer.value_counts().to_dict()
    # ---------------- B. 2027
    R27 = run_year(D_all, 2027, AV, wk1, ph)
    rat = R27.attrs["ratios"]; R27 = R27[R27.ppg.notna() & R27.pid.isin(ph.pid)].copy(); R27.attrs["ratios"] = rat   # players with 2026 snaps; no 2027 rookies yet
    R27 = finish(ranges(rec_cols(R27)))
    R27 = fmt_totals(R27)
    R27["ppg26"] = R27.pid.map((W26.groupby("pid").half.sum() / W26.groupby("pid").week.nunique()))
    cols27 = ["rank", "name", "pos", "team", "pos_rank", "ppg", "games", "total", "tot_p10", "tot_p90", "ppg26", "age", "p_bench"]
    FMT = ["rec_pg", "ppg_ppr", "total_ppr", "tot_p10_ppr", "tot_p90_ppr", "ppg_std", "total_std", "tot_p10_std", "tot_p90_std"]
    import sf_view_a10 as SV
    R27 = SV.format_ranks(R27)   # rank_ppr / pos_rank_ppr / rank_std / pos_rank_std (re-done after the rookies by a15 insert)
    R27[cols27 + ["dc", "rb_car_pg", "rb_tgt_pg", "T_car_hat", "T_tgt_hat", "rb_tier", "ppg_v5"] + FMT + SV.FMT_RANKS].to_csv(os.path.join(OUT, "2027_inhouse_early.csv"), index=False)
    # ---------------- markdown
    H26 = ["Rk", "Player", "Pos", "Team", "Pos rk", "Proj PPG", "Proj G", "Proj total", "p10", "p90", "ADP rk", "ADP pos rk", "2026 PPG (wk1-10)", "2026 G", "2026 pos rk"]
    with open(os.path.join(OUT, "2026_inhouse_check.md"), "w", encoding="utf-8") as f:
        f.write("# 2026 check: in-house preseason model (no ADP input)\n\n")
        f.write("Built only from data before week 1 of 2026, the same way as the backtest. "
                "Scoring: half-PPR. Order: 12-team 1QB (QB, 2 RB, 3 WR, TE, FLEX); the overall rank is by value over replacement. "
                "ADP (comparison only, not an input): Underdog best ball, 2026-09-03. "
                f"Actual 2026: weeks 1-{LAST_WK} (later weeks excluded). The 2026 position rank is by total points so far, so missed games count against a player.\n\n")
        f.write("## Overall top 150\n\n" + md_table(R26.head(150), cols, H26) + "\n\n")
        for ps in PM.POS4:
            k = {"QB": 32, "RB": 50, "WR": 60, "TE": 24}[ps]
            f.write(f"## {ps} (top {k})\n\n" + md_table(R26[R26.pos == ps].sort_values("pos_rank").head(k), cols, H26) + "\n\n")
        dcols = ["name", "pos", "team", "rank", "adp_rank", "pos_rank", "adp_pos_rank", "ppg", "ppg26", "g26", "act_pos_rank", "closer"]
        dh = ["Player", "Pos", "Team", "Model rk", "ADP rk", "Model pos rk", "ADP pos rk", "Proj PPG", "2026 PPG", "2026 G", "2026 pos rk", "Closer so far"]
        f.write("## Biggest disagreements\n\nOne season and 10 weeks is a small sample. 'Closer so far' compares the actual 2026 position rank with each side's position rank.\n\n")
        f.write("### Model much HIGHER than ADP\n\n" + md_table(hi, dcols, dh) + "\n\n### Model much LOWER than ADP\n\n" + md_table(lo, dcols, dh) + "\n\n")
        f.write(f"**Tally (30 players): {tally}**\n")
    H27 = ["Rk", "Player", "Pos", "Team", "Pos rk", "Proj PPG", "Proj G", "Proj total", "p10", "p90", "2026 PPG (wk1-10)", "Age (2027)"]
    with open(os.path.join(OUT, "2027_inhouse_early.md"), "w", encoding="utf-8") as f:
        f.write("# Early 2027 look: in-house model, PRELIMINARY (no ADP input)\n\n")
        f.write(f"Built from data through week {LAST_WK} of 2026. Scoring: half-PPR. Order: 12-team 1QB (QB, 2 RB, 3 WR, TE, FLEX), overall rank by value over replacement.\n\n")
        f.write("**What it can't know yet:**\n\n"
                "- the rest of the 2026 season (it uses a partial season, scaled to a 17-game rate)\n"
                "- free agency and trades\n"
                "- the 2027 draft: no 2027 rookies are in the list\n"
                "- coaching changes\n"
                "- 2027 depth charts: RB / WR / TE roles are each player's 2026 usage per game (3+ games; WRs two to a string); QBs use today's ESPN chart and most 2026 starts\n"
                "- the 2027 Vegas win totals: team strength is set to the league median\n"
                "- offseason injuries and retirements\n\n"
                "Age is age on Sept 1, 2027.\n\n")
        f.write("## Overall top 150\n\n" + md_table(R27.head(150), cols27, H27) + "\n\n")
        for ps in PM.POS4:
            k = {"QB": 32, "RB": 50, "WR": 60, "TE": 24}[ps]
            f.write(f"## {ps} (top {k})\n\n" + md_table(R27[R27.pos == ps].sort_values("pos_rank").head(k), cols27, H27) + "\n\n")
    P(f"  2026 list {len(R26)} players; 2027 list {len(R27)}; disagreement tally {tally}")
    P("\n2026 top 24:"); [P(f"  {r.rank:3d} {r.name:24s} {r.pos} {r.team:4s} pos{r.pos_rank:<3d} {r.ppg:5.1f} ppg x {r.games:4.1f} g = {r.total:5.0f} [{r.tot_p10:4.0f}-{r.tot_p90:4.0f}] ADP {r.adp_rank if r.adp_rank == r.adp_rank else '-'} | 2026 {r.ppg26 if r.ppg26 == r.ppg26 else 0:4.1f} ppg {r.g26 if r.g26 == r.g26 else 0:.0f} g pos{r.act_pos_rank if r.act_pos_rank == r.act_pos_rank else '-'}") for r in R26.head(24).itertuples(index=False)]
    for ps in PM.POS4:
        P(f"2026 {ps} top 12:"); [P(f"  {r.pos_rank:2d} {r.name:24s} {r.team:4s} {r.ppg:5.1f} ppg {r.total:5.0f} | ADP pos {r.adp_pos_rank if r.adp_pos_rank == r.adp_pos_rank else '-'} | 2026 {r.ppg26 if r.ppg26 == r.ppg26 else 0:4.1f} ppg pos{r.act_pos_rank if r.act_pos_rank == r.act_pos_rank else '-'}") for r in R26[R26.pos == ps].sort_values("pos_rank").head(12).itertuples(index=False)]
    P("\nDisagreements HIGH:"); [P(f"  {r.name:24s} {r.pos} model {r.rank} ADP {r.adp_rank if r.adp_rank == r.adp_rank else '-'} | pos {r.pos_rank} vs {r.adp_pos_rank if r.adp_pos_rank == r.adp_pos_rank else '-'} | 2026 pos {r.act_pos_rank if r.act_pos_rank == r.act_pos_rank else '-'} ({r.g26 if r.g26 == r.g26 else 0:.0f} g) -> {r.closer}") for r in hi.itertuples(index=False)]
    P("Disagreements LOW:"); [P(f"  {r.name:24s} {r.pos} model {r.rank} ADP {r.adp_rank if r.adp_rank == r.adp_rank else '-'} | pos {r.pos_rank} vs {r.adp_pos_rank if r.adp_pos_rank == r.adp_pos_rank else '-'} | 2026 pos {r.act_pos_rank if r.act_pos_rank == r.act_pos_rank else '-'} ({r.g26 if r.g26 == r.g26 else 0:.0f} g) -> {r.closer}") for r in lo.itertuples(index=False)]
    P("\n2027 top 24:"); [P(f"  {r.rank:3d} {r.name:24s} {r.pos} {r.team:4s} pos{r.pos_rank:<3d} {r.ppg:5.1f} ppg x {r.games:4.1f} g = {r.total:5.0f} [{r.tot_p10:4.0f}-{r.tot_p90:4.0f}] | 2026 {r.ppg26 if r.ppg26 == r.ppg26 else 0:4.1f} age {r.age:.0f}") for r in R27.head(24).itertuples(index=False)]
    for ps in PM.POS4:
        P(f"2027 {ps} top 12:"); [P(f"  {r.pos_rank:2d} {r.name:24s} {r.team:4s} {r.ppg:5.1f} ppg {r.total:5.0f} | 2026 {r.ppg26 if r.ppg26 == r.ppg26 else 0:4.1f}") for r in R27[R27.pos == ps].sort_values("pos_rank").head(12).itertuples(index=False)]
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
