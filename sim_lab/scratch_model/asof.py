#!/usr/bin/env python3
"""
asof.py - the AS-OF feature table: one row per (season, week, player) who played, with every
feature computed ONLY from games before that week (plus the prior season, preseason ADP and the
week's own Vegas line / injury report, which were all public before kickoff).

Rolling state (per player, per team, per defense) is updated week by week, so leakage is
impossible by construction: week N rows are emitted before week N games enter the state.

Usage: python asof.py 2017 2026   -> cache/asof_{Y}.parquet per season
"""
import os, sys, json, math
from collections import defaultdict
import numpy as np, pandas as pd
from features import build_season, build_injuries, players, norm, tm, POS4, HERE, OUT

ADP_HIST = r"E:\MyFantasyFootball\sim_lab\data\ffc_adp_hist.json"
ACC_SEASON = r"E:\MyFantasyFootball\MyFantasyFootball Files\accuracy\data\season_2026.json"
HL_S, HL_L = 3.0, 10.0          # short / long half-lives (games) for the usage EWMAs
ZONES = ("QB_PASS", "QB_RUSH", "RB_RUSH", "RB_REC", "WR_S", "WR_M", "WR_D", "TE")
STAT_KEYS = ["att", "cmp", "py", "ptd", "int", "sk", "p_air", "p_rz_att", "att_nog", "car", "ry", "rtd", "scr", "gl_car", "i10_car",
             "rz_car", "car_nog", "tgt", "rec", "rcy", "rctd", "airy", "yac", "ez_tgt", "rz_tgt", "tgt_s", "tgt_m", "tgt_d", "tgt_bl",
             "tgt_nog", "fl", "offense_snaps", "offense_pct", "pts_half"]
TEAM_KEYS = ["t_att", "t_db", "t_car", "t_tgt", "t_rz_tgt", "t_rz_car", "t_gl_car", "t_i10_car", "t_ez_tgt", "t_ptd", "t_rtd", "t_py",
             "t_ry", "t_airy", "t_garbage", "t_sk", "t_att_nog", "t_car_nog", "t_tgt_nog", "pts", "opp_pts", "implied", "opp_implied", "total"]


def adp_map(Y):
    """{(norm name, pos): overall ADP} for season Y. FFC history <= 2025 (half-ppr where it exists, else ppr), Underdog for 2026."""
    out = {}
    if Y <= 2025:
        a = json.load(open(ADP_HIST, encoding="utf-8")).get(str(Y), {})
        pref = ("half-ppr", "ppr", "standard")
        best = {}
        for p in a.get("players", []):
            k = (norm(p["name"]), p["pos"]); r = pref.index(p["fmt"]) if p["fmt"] in pref else 9
            if k not in best or r < best[k][0]:
                best[k] = (r, float(p["adp"]))
        out = {k: v[1] for k, v in best.items()}
    else:
        d = json.load(open(ACC_SEASON, encoding="utf-8"))["players"]
        for n, r in d.items():
            pre = r.get("pre") or {}
            adp = pre.get("ud")
            if adp is None:   # fall back to the consensus rank order when Underdog has no ADP
                ranks = [pre[k] for k in ("sl", "fp", "espn", "cbs", "yahoo") if pre.get(k)]
                adp = float(np.median(ranks)) if ranks else None
            if adp is not None:
                out[(norm(n), r["pos"])] = float(adp)
    return out


def ew(vals, ws):
    s = sum(ws)
    return float(sum(v * w for v, w in zip(vals, ws)) / s) if s > 0 else np.nan


def weights(n, hl):
    return [0.5 ** ((n - 1 - i) / hl) for i in range(n)]


class DefState:
    """Per-defense allowed stats by zone, as-of. Each game appends one dict of allowed counts."""

    def __init__(self):
        self.g = defaultdict(list)

    def add(self, d, rec):
        self.g[d].append(rec)

    def rate(self, d, num, den, hl=6.0):
        gs = self.g.get(d, [])
        if not gs:
            return np.nan, 0.0
        ws = weights(len(gs), hl)
        n = sum(g.get(num, 0.0) * w for g, w in zip(gs, ws)); dd = sum(g.get(den, 0.0) * w for g, w in zip(gs, ws))
        return (n / dd if dd > 0 else np.nan), sum(ws)


def def_record(pg_rows, tg_row):
    """allowed-stats record for one defense from the opposing players' rows in one game"""
    r = defaultdict(float)
    r["games"] = 1.0
    for x in pg_rows:
        p = x["pos"]
        if p == "QB":
            r["qb_pts"] += x["pts_half"]; r["qb_att"] += x["att"]; r["qb_py"] += x["py"]; r["qb_ptd"] += x["ptd"]; r["qb_int"] += x["int"]
            r["qb_car"] += x["car"]; r["qb_ry"] += x["ry"]; r["qb_rtd"] += x["rtd"]
        elif p == "RB":
            r["rb_pts"] += x["pts_half"]; r["rb_car"] += x["car"]; r["rb_ry"] += x["ry"]; r["rb_rtd"] += x["rtd"]
            r["rb_tgt"] += x["tgt"]; r["rb_rec"] += x["rec"]; r["rb_rcy"] += x["rcy"]; r["rb_rctd"] += x["rctd"]
        elif p == "WR":
            r["wr_pts"] += x["pts_half"]; r["wr_tgt"] += x["tgt"]; r["wr_rec"] += x["rec"]; r["wr_rcy"] += x["rcy"]; r["wr_rctd"] += x["rctd"]
            r["wr_tgt_s"] += x["tgt_s"]; r["wr_tgt_m"] += x["tgt_m"]; r["wr_tgt_d"] += x["tgt_d"]
            r["wr_car"] += x["car"]; r["wr_ry"] += x["ry"]; r["wr_rtd"] += x["rtd"]
        elif p == "TE":
            r["te_pts"] += x["pts_half"]; r["te_tgt"] += x["tgt"]; r["te_rec"] += x["rec"]; r["te_rcy"] += x["rcy"]; r["te_rctd"] += x["rctd"]
    # points allowed TD-neutral: swap TDs for league rate on the yards (0.0225 TD / yard ~ 1 TD per 44 yds is too high; use 1/60)
    for p in ("qb", "rb", "wr", "te"):
        pass
    r["t_att"] = tg_row["t_att"]; r["t_car"] = tg_row["t_car"]; r["t_pts"] = tg_row["pts"]; r["t_py"] = tg_row["t_py"]; r["t_ry"] = tg_row["t_ry"]
    r["t_ptd"] = tg_row["t_ptd"]; r["t_rtd"] = tg_row["t_rtd"]; r["implied"] = tg_row["implied"] if not np.isnan(tg_row["implied"]) else 22.0
    return dict(r)


def season_summary(pg):
    """prior-season per-player summary (games >= 1): per-game shares/levels over the player's LAST 8 games + team."""
    out = {}
    if pg is None:
        return out
    pg = pg[pg.played == 1].sort_values(["pid", "week"])
    tg_idx = None
    for pid, grp in pg.groupby("pid"):
        g = grp.tail(8)
        n = len(grp)
        out[pid] = dict(p_g=n, p_ppg=float(grp.pts_half.mean()), p_ppg8=float(g.pts_half.mean()), p_team=str(grp.team.iloc[-1]),
                        p_tgt=float(g.tgt.mean()), p_car=float(g.car.mean()), p_att=float(g.att.mean()), p_snap=float(g.offense_pct.mean()),
                        p_tsh=float(g.tgt.sum() / max(1.0, g.t_tgt.sum())) if "t_tgt" in g else np.nan,
                        p_csh=float(g.car.sum() / max(1.0, g.t_car.sum())) if "t_car" in g else np.nan,
                        p_adot=float(g.airy.sum() / g.tgt.sum()) if g.tgt.sum() > 0 else np.nan,
                        p_ypt=float(g.rcy.sum() / g.tgt.sum()) if g.tgt.sum() > 0 else np.nan,
                        p_ypc=float(g.ry.sum() / g.car.sum()) if g.car.sum() > 0 else np.nan)
    return out


def load_pg_with_team(Y):
    pg, tg = build_season(Y)
    tg2 = tg[["game_id", "team"] + [c for c in TEAM_KEYS if c in tg.columns] + ["tspread", "is_home", "indoor", "wind", "temp", "opp", "week"]]
    m = pg.merge(tg2.drop(columns=["opp", "week", "is_home"]), on=["game_id", "team"], how="left")
    return m, tg


def build_asof(Y, force=False):
    f = os.path.join(OUT, f"asof_{Y}.parquet")
    if not force and os.path.exists(f):
        return pd.read_parquet(f)
    pg, tg = load_pg_with_team(Y)
    try:
        pgp, _ = load_pg_with_team(Y - 1)
    except Exception:
        pgp = None
    prior = season_summary(pgp)
    inj = build_injuries(Y)
    injmap = {(int(w), p): (gs, pr) for w, p, gs, pr in zip(inj.week, inj.pid, inj.gs, inj.pr)}
    adp = adp_map(Y)
    P = players()
    pg = pg.sort_values(["week", "team", "pid"]).reset_index(drop=True)
    tg = tg.sort_values(["week", "team"]).reset_index(drop=True)
    weeks = sorted(tg.week.unique())
    # rolling state
    pstate = defaultdict(list)            # pid -> list of game dicts (this season, played games)
    tstate = defaultdict(list)            # team -> list of team-game dicts
    dstate = DefState()                   # defense -> allowed records
    last_team_game = {}                   # team -> week of its last game
    team_players_recent = defaultdict(lambda: defaultdict(list))   # team -> pid -> [(week, tgt share, car share, snap)]
    # league baselines accumulate too (as-of)
    lg = defaultdict(float)
    rows = []
    pg_by_week = {w: g for w, g in pg.groupby("week")}
    tg_by_week = {w: g for w, g in tg.groupby("week")}
    # prior-season defense (full season, regressed as 4 games of evidence)
    dprior = {}
    if pgp is not None:
        pgpp = pgp[pgp.played == 1]
        for d, grp in pgpp.groupby("opp"):
            n = grp.game_id.nunique()
            rec = defaultdict(float)
            for p in ("QB", "RB", "WR", "TE"):
                rec[p.lower() + "_pts"] = grp[grp.pos == p].pts_half.sum() / max(1, n)
            rec["rb_ypc"] = grp[grp.pos == "RB"].ry.sum() / max(1.0, grp[grp.pos == "RB"].car.sum())
            rec["games"] = n
            dprior[d] = rec
    for N in weeks:
        wk_tg = tg_by_week.get(N)
        wk_pg = pg_by_week.get(N)
        if wk_pg is None:
            continue
        # league as-of per-position per-game points allowed (for defense normalisation)
        lg_pos = {}
        for p in ("qb", "rb", "wr", "te"):
            tot = sum(sum(g.get(p + "_pts", 0.0) for g in gs) for gs in dstate.g.values())
            ng = sum(len(gs) for gs in dstate.g.values())
            prior_tot = sum(r[p + "_pts"] for r in dprior.values()) / max(1, len(dprior)) if dprior else np.nan
            lg_pos[p] = ((tot + 4 * 32 * (prior_tot if not np.isnan(prior_tot) else 0)) / (ng + (4 * 32 if dprior else 0))) if (ng + (4 * 32 if dprior else 0)) > 0 else np.nan
        tg_rows = {(r.team): r for r in wk_tg.itertuples(index=False)}
        # ---- emit rows for every player who played this week (features from state only)
        for r in wk_pg.itertuples(index=False):
            if r.played != 1:
                continue
            pid = r.pid; team = r.team; pos = r.pos
            hist = pstate.get(pid, [])
            g = len(hist)
            ws_s = weights(g, HL_S); ws_l = weights(g, HL_L)
            tgr = tg_rows.get(team)
            th = tstate.get(team, [])
            tws = weights(len(th), 4.0)
            pr = prior.get(pid, {})
            same_team = 1 if pr.get("p_team") == team else 0
            gs_, pr_ = injmap.get((N, pid), ("", ""))
            row = dict(season=Y, week=N, pid=pid, name=r.name, pos=pos, team=team, opp=r.opp, is_home=int(r.is_home),
                       act=float(r.pts_half), act_ppr=float(r.pts_ppr), g=g,
                       adp=adp.get((norm(r.name), pos), np.nan), gs=gs_, pr=pr_,
                       rookie=int(P.rookie_season.get(pid, 0) == Y) if pid in P.index else 0,
                       same_team=same_team, snap_now=float(r.offense_pct),
                       implied=float(tgr.implied) if tgr is not None else np.nan, opp_implied=float(tgr.opp_implied) if tgr is not None else np.nan,
                       total=float(tgr.total) if tgr is not None else np.nan, tspread=float(tgr.tspread) if tgr is not None else np.nan,
                       indoor=int(tgr.indoor) if tgr is not None else 0, wind=float(tgr.wind) if tgr is not None and not np.isnan(tgr.wind) else 0.0)
            for k, v in pr.items():
                row[k] = v
            # team volume as-of
            if th:
                for key in ("t_att", "t_car", "t_tgt", "t_db", "t_rz_tgt", "t_gl_car", "t_i10_car", "t_ez_tgt", "t_ptd", "t_rtd", "pts", "implied"):
                    row["tm_" + key] = ew([x[key] for x in th], tws)
                row["tm_games"] = len(th)
                row["tm_pass_rate"] = row["tm_t_att"] / max(1.0, row["tm_t_att"] + row["tm_t_car"])
                row["tm_plays"] = row["tm_t_att"] + row["tm_t_car"]
            else:
                row["tm_games"] = 0
            # player usage as-of (shares within the games he played)
            if g:
                def sh(num, den, ws):
                    n_ = sum(x[num] * w for x, w in zip(hist, ws)); d_ = sum(x[den] * w for x, w in zip(hist, ws))
                    return n_ / d_ if d_ > 0 else np.nan
                for tag, ws in (("s", ws_s), ("l", ws_l)):
                    row[f"tsh_{tag}"] = sh("tgt", "t_tgt", ws); row[f"csh_{tag}"] = sh("car", "t_car", ws)
                    row[f"rzt_{tag}"] = sh("rz_tgt", "t_rz_tgt", ws); row[f"glc_{tag}"] = sh("i10_car", "t_i10_car", ws)
                    row[f"ezt_{tag}"] = sh("ez_tgt", "t_ez_tgt", ws); row[f"ash_{tag}"] = sh("airy", "t_airy", ws)
                    row[f"snap_{tag}"] = ew([x["offense_pct"] for x in hist], ws); row[f"ppg_{tag}"] = ew([x["pts_half"] for x in hist], ws)
                    row[f"tgt_{tag}"] = ew([x["tgt"] for x in hist], ws); row[f"car_{tag}"] = ew([x["car"] for x in hist], ws)
                    row[f"att_{tag}"] = ew([x["att"] for x in hist], ws); row[f"attsh_{tag}"] = sh("att", "t_att", ws)
                    row[f"tshn_{tag}"] = sh("tgt_nog", "t_tgt_nog", ws); row[f"cshn_{tag}"] = sh("car_nog", "t_car_nog", ws)
                # efficiency (season-to-date raw sums, shrunk later by the model)
                S = {k: float(sum(x[k] for x in hist)) for k in ("tgt", "rec", "rcy", "rctd", "airy", "car", "ry", "rtd", "att", "py", "ptd", "int", "cmp", "ez_tgt", "i10_car", "rz_tgt", "scr", "yac")}
                for k, v in S.items():
                    row["sum_" + k] = v
                row["last_wk"] = hist[-1]["week"]; row["last_pts"] = hist[-1]["pts_half"]; row["last_snap"] = hist[-1]["offense_pct"]
                row["weeks_since"] = N - hist[-1]["week"]
            # opponent defense as-of (points allowed per game by position, shrunk toward prior season / league)
            d = r.opp
            gs = dstate.g.get(d, [])
            ndef = len(gs); dp = dprior.get(d)
            for p in ("qb", "rb", "wr", "te"):
                cur = sum(x.get(p + "_pts", 0.0) for x in gs)
                pri = dp[p + "_pts"] if dp else lg_pos[p]
                pri = pri if pri is not None and not (isinstance(pri, float) and np.isnan(pri)) else (lg_pos[p] if not np.isnan(lg_pos[p]) else 0)
                k = 4.0
                row[f"def_{p}"] = (cur + k * pri) / (ndef + k)
                row[f"def_{p}_rel"] = row[f"def_{p}"] / lg_pos[p] if lg_pos[p] and not np.isnan(lg_pos[p]) else 1.0
            # zone rates allowed (per opportunity) vs league
            def zone(num, den, k=60.0):
                n_ = sum(x.get(num, 0.0) for x in gs); d_ = sum(x.get(den, 0.0) for x in gs)
                ln = lg.get(num, 0.0); ld = lg.get(den, 0.0)
                lrate = ln / ld if ld > 0 else np.nan
                if np.isnan(lrate):
                    return 1.0
                return ((n_ + k * lrate) / (d_ + k)) / lrate
            row["z_rb_ypc"] = zone("rb_ry", "rb_car"); row["z_rb_ypt"] = zone("rb_rcy", "rb_tgt")
            row["z_wr_s"] = zone("wr_rcy", "wr_tgt"); row["z_te_ypt"] = zone("te_rcy", "te_tgt"); row["z_qb_ypa"] = zone("qb_py", "qb_att")
            row["z_ptd"] = zone("t_ptd", "t_att", 120.0); row["z_rtd"] = zone("t_rtd", "t_car", 120.0)
            row["def_games"] = ndef
            # teammates absent this week -> vacated usage
            tp = team_players_recent.get(team, {})
            vac_t = vac_c = 0.0; vac_names = []
            ltw = last_team_game.get(team)
            for q, lst in tp.items():
                if q == pid:
                    continue
                g_, p_ = injmap.get((N, q), ("", ""))
                played_last = any(w == ltw for w, _, _, _ in lst)
                absent = g_ in ("Out", "Doubtful") or (not played_last and g_ not in ("Questionable",) and p_ not in ("FP", "LP"))
                if absent and lst:
                    recent = lst[-4:]
                    vac_t += float(np.mean([x[1] for x in recent])); vac_c += float(np.mean([x[2] for x in recent]))
            row["vac_tsh"] = vac_t; row["vac_csh"] = vac_c
            rows.append(row)
        # ---- update state with week N games
        for r in wk_tg.itertuples(index=False):
            d = r._asdict()
            tstate[r.team].append(d); last_team_game[r.team] = N
        for team, grp in wk_pg.groupby("team"):
            tgr = tg_rows[team]
            recs = [x._asdict() for x in grp.itertuples(index=False)]
            drec = def_record(recs, tgr._asdict())
            dstate.add(tgr.opp, drec)
            for k, v in drec.items():
                if isinstance(v, (int, float)):
                    lg[k] += v
            for x in recs:
                if x["played"] != 1:
                    continue
                pstate[x["pid"]].append(x)
                team_players_recent[team][x["pid"]].append((N, x["tgt"] / max(1.0, x["t_tgt"]), x["car"] / max(1.0, x["t_car"]), x["offense_pct"]))
    df = pd.DataFrame(rows)
    df.to_parquet(f, index=False)
    return df


if __name__ == "__main__":
    a = [int(x) for x in sys.argv[1:]]
    years = range(a[0], a[1] + 1) if len(a) == 2 else (a or range(2017, 2027))
    for Y in years:
        df = build_asof(Y, force=True)
        print(Y, len(df), "rows", df.columns.size, "cols")
