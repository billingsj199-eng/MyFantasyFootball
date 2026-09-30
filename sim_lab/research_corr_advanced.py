#!/usr/bin/env python3
"""
ADVANCED STATS, ROUTE SHARE AND ALIGNMENT-BY-OFFENSE: correlations with scoring, season vs weekly, by position
(2026-09-16). Jack: "did we find the highest correlation in advanced stats by position or route share or
alignments in certain offenses?" The horizon study (research_corr_horizons.py) had none of these. Added here:
  PFF season files (pbp_cache/pff, 2019-25, matched by pff_id -> gsis): route rate, YPRR, targets per route,
     aDOT, route grade, offense grade, SLOT / WIDE / INLINE rate, YAC per catch, drop rate, contested-catch rate;
     RB: YPA, yards after contact, elusive rating, breakaway %, run grade, GAP share of carries, receiving routes
  Participation (pbp_participation, 2018-25): per-player ROUTE SHARE (pass plays on the field / team pass
     plays) season-to-date and last 3 games, routes per game, TPRR and YPRR season-to-date; per-team pass plays
     per game, 11-personnel rate, 12-personnel rate, shotgun rate (prior season and season-to-date)
  Alignment x offense interactions: prior slot rate x team 11-personnel rate, prior inline rate x 12-personnel
     rate, route share x team pass plays, route share x PROE
Same two horizons as before: SEASON (player-season PPG vs prior-season / preseason features) and WEEKLY (points
vs everything known pre-kickoff). Pearson r and Spearman rho by position; then "does any advanced stat beat the
basics" (prior-year PPG at season, target / carry share at weekly). data/corr_advanced.js (SIM_CORR_ADV), ZONES.
"""
import json, os, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_sim_calibration as cal
import bt_common as B
import backtest_noclay_weekly as NW

sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "corr_advanced.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

POS4 = ("QB", "RB", "WR", "TE"); YEARS = list(range(2019, 2026))
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "season": {}, "weekly": {}, "beats": {}, "n": {}}
LABEL = {"route_rate_py": "prior-yr route rate (PFF)", "yprr_py": "prior-yr yards per route run", "tprr_py": "prior-yr targets per route", "adot_py": "prior-yr aDOT", "grade_route_py": "prior-yr PFF route grade", "grade_off_py": "prior-yr PFF offense grade",
         "slot_py": "prior-yr slot rate", "wide_py": "prior-yr wide rate", "inline_py": "prior-yr inline rate (TE)", "yac_py": "prior-yr YAC per catch", "drop_py": "prior-yr drop rate", "contested_py": "prior-yr contested-catch rate", "routes_py": "prior-yr routes (volume)", "targets_py": "prior-yr targets (volume)",
         "ypa_py": "prior-yr yards per carry", "yco_py": "prior-yr yards after contact / carry", "elusive_py": "prior-yr elusive rating", "breakaway_py": "prior-yr breakaway %", "grade_run_py": "prior-yr PFF run grade", "gap_share_py": "prior-yr gap-scheme carry share", "rb_routes_py": "prior-yr routes (RB receiving)", "rb_yprr_py": "prior-yr YPRR (RB)",
         "tm_pass_pg_py": "team pass plays / game (prior yr)", "tm_p11_py": "team 11-personnel rate (prior yr)", "tm_p12_py": "team 12-personnel rate (prior yr)", "tm_shotgun_py": "team shotgun rate (prior yr)",
         "slot_x_p11": "prior slot rate x team 11-personnel (now)", "inline_x_p12": "prior inline rate x team 12-personnel (now)", "rs_x_pass": "route share x team pass plays", "rs_x_proe": "route share x team PROE",
         "route_share": "route share (season-to-date)", "route_share_l3": "route share (last 3)", "routes_pg": "routes / game (season-to-date)", "tprr": "targets per route (season-to-date)", "yprr": "yards per route run (season-to-date)",
         "tm_pass_pg": "team pass plays / game (season-to-date)", "tm_p11": "team 11-personnel rate (season-to-date)", "tm_p12": "team 12-personnel rate (season-to-date)", "tm_shotgun": "team shotgun rate (season-to-date)",
         "ppg_py": "prior-yr PPG (basic, for reference)", "tgt_sh": "target share (basic, for reference)", "car_sh": "carry share (basic, for reference)", "ppg": "season-to-date PPG (basic, for reference)", "proe_std": "team PROE (season-to-date)"}


def load_pff():
    pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "pff_id"])
    pff2g = {int(r.pff_id): r.gsis_id for r in pl.itertuples(index=False) if pd.notna(r.pff_id) and isinstance(r.gsis_id, str)}
    rec, rush = {}, {}
    for Y in range(2018, 2026):
        fr = os.path.join(B.CACHE, "pff", f"pff_receiving_{Y}.csv"); fu = os.path.join(B.CACHE, "pff", f"pff_rushing_{Y}.csv")
        if os.path.exists(fr):
            d = pd.read_csv(fr)
            for r in d.itertuples(index=False):
                g = pff2g.get(int(r.player_id))
                if not g or (r.routes or 0) < 50: continue
                rec[(Y, g)] = {"route_rate_py": r.route_rate, "yprr_py": r.yprr, "tprr_py": (r.targets / r.routes) if r.routes else np.nan, "adot_py": r.avg_depth_of_target, "grade_route_py": r.grades_pass_route, "grade_off_py": r.grades_offense,
                               "slot_py": r.slot_rate, "wide_py": r.wide_rate, "inline_py": r.inline_rate, "yac_py": r.yards_after_catch_per_reception, "drop_py": r.drop_rate, "contested_py": r.contested_catch_rate, "routes_py": r.routes, "targets_py": r.targets}
        if os.path.exists(fu):
            d = pd.read_csv(fu)
            for r in d.itertuples(index=False):
                g = pff2g.get(int(r.player_id))
                if not g or (r.attempts or 0) < 40: continue
                ga, za = (r.gap_attempts or 0), (r.zone_attempts or 0)
                rush[(Y, g)] = {"ypa_py": r.ypa, "yco_py": r.yco_attempt, "elusive_py": r.elusive_rating, "breakaway_py": r.breakaway_percent, "grade_run_py": r.grades_run, "gap_share_py": ga / (ga + za) if (ga + za) else np.nan, "rb_routes_py": r.routes, "rb_yprr_py": r.yprr}
    return rec, rush


def load_participation():
    """per (Y, team): weekly pass plays, 11/12 personnel, shotgun; per (Y, gsis): weekly routes; all by week."""
    tm_w = defaultdict(lambda: defaultdict(lambda: {"pass": 0, "plays": 0, "p11": 0, "p12": 0, "sg": 0}))
    pl_w = defaultdict(lambda: defaultdict(int))
    for Y in range(2018, 2026):
        pbp = pd.read_csv(os.path.join(B.CACHE, f"play_by_play_{Y}.csv.gz"), usecols=["game_id", "play_id", "season_type", "week", "posteam", "pass_attempt", "rush_attempt", "sack"], low_memory=False)
        pbp = pbp[(pbp.season_type == "REG") & pbp.posteam.notna() & ((pbp.pass_attempt == 1) | (pbp.rush_attempt == 1))]
        kind = {(g, int(p)): (int(w), bool(pa)) for g, p, w, pa in zip(pbp.game_id, pbp.play_id, pbp.week, pbp.pass_attempt)}
        part = pd.read_parquet(os.path.join(B.CACHE, f"pbp_participation_{Y}.parquet"), columns=["nflverse_game_id", "play_id", "possession_team", "offense_players", "offense_personnel", "offense_formation"])
        for r in part.itertuples(index=False):
            k = kind.get((r.nflverse_game_id, int(r.play_id)))
            if not k: continue
            wk, is_pass = k; t = B.tm(str(r.possession_team)); tw = tm_w[(Y, t)][wk]
            tw["plays"] += 1
            pers = str(r.offense_personnel or "")
            if "1 TE, 3 WR" in pers: tw["p11"] += 1
            if "2 TE, 2 WR" in pers: tw["p12"] += 1
            if str(r.offense_formation) == "SHOTGUN": tw["sg"] += 1
            if is_pass:
                tw["pass"] += 1
                if isinstance(r.offense_players, str):
                    for gid in r.offense_players.split(";"): pl_w[(Y, gid)][wk] += 1
        P(f"  participation {Y}: {len([k for k in tm_w if k[0] == Y])} teams")
    return tm_w, pl_w


def corr_table(df, feats, y, min_n=150):
    out = []
    for f in feats:
        if f not in df.columns: continue
        x = pd.to_numeric(df[f], errors="coerce"); m = x.notna() & df[y].notna()
        if m.sum() < min_n or x[m].std() == 0: continue
        out.append({"feat": f, "label": LABEL.get(f, f), "n": int(m.sum()), "r": round(float(np.corrcoef(x[m], df[y][m])[0, 1]), 3), "rho": round(float(spearmanr(x[m], df[y][m]).correlation), 3)})
    out.sort(key=lambda d: -abs(d["r"]))
    return out


def main():
    t0 = time.time()
    P("=== Advanced stats / route share / alignment: correlations with scoring by position ===")
    df = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); df = df[df.pos.isin(POS4)].copy()
    rec, rush = load_pff(); tm_w, pl_w = load_participation()
    # prior-season PFF + team context
    for col in ["route_rate_py", "yprr_py", "tprr_py", "adot_py", "grade_route_py", "grade_off_py", "slot_py", "wide_py", "inline_py", "yac_py", "drop_py", "contested_py", "routes_py", "targets_py",
                "ypa_py", "yco_py", "elusive_py", "breakaway_py", "grade_run_py", "gap_share_py", "rb_routes_py", "rb_yprr_py"]:
        df[col] = np.nan
    for i, (y, pid) in enumerate(zip(df.year, df.pid)):
        if not isinstance(pid, str): continue
        a = rec.get((int(y) - 1, pid)); b = rush.get((int(y) - 1, pid))
        if a:
            for k, v in a.items(): df.iat[i, df.columns.get_loc(k)] = v
        if b:
            for k, v in b.items(): df.iat[i, df.columns.get_loc(k)] = v
    def tm_rates(Y, t, upto):
        ws = [w for w in tm_w.get((Y, t), {}) if w < upto]
        if not ws: return (np.nan,) * 4
        agg = {k: sum(tm_w[(Y, t)][w][k] for w in ws) for k in ("pass", "plays", "p11", "p12", "sg")}
        return agg["pass"] / len(ws), agg["p11"] / max(1, agg["plays"]), agg["p12"] / max(1, agg["plays"]), agg["sg"] / max(1, agg["plays"])
    py = np.array([tm_rates(int(y) - 1, t, 99) for y, t in zip(df.year, df.team)]); df["tm_pass_pg_py"], df["tm_p11_py"], df["tm_p12_py"], df["tm_shotgun_py"] = py[:, 0], py[:, 1], py[:, 2], py[:, 3]
    now = np.array([tm_rates(int(y), t, int(w)) for y, t, w in zip(df.year, df.team, df.wk)]); df["tm_pass_pg"], df["tm_p11"], df["tm_p12"], df["tm_shotgun"] = now[:, 0], now[:, 1], now[:, 2], now[:, 3]
    # player route share season-to-date / last 3, routes per game, TPRR, YPRR (targets & yards from the weekly DB)
    rs, rs3, rpg, tprr, yprr = (np.full(len(df), np.nan) for _ in range(5))
    cache = {}
    for i, (y, pid, t, w, nm, ps) in enumerate(zip(df.year, df.pid, df.team, df.wk, df.name, df.pos)):
        if not isinstance(pid, str): continue
        Y, W = int(y), int(w); pr = pl_w.get((Y, pid), {}); tw = tm_w.get((Y, t), {})
        ws = [ww for ww in tw if ww < W]
        if not ws: continue
        routes = sum(pr.get(ww, 0) for ww in ws); tpass = sum(tw[ww]["pass"] for ww in ws)
        if tpass <= 0: continue
        rs[i] = routes / tpass; rpg[i] = routes / len(ws)
        l3 = sorted(ws)[-3:]; tp3 = sum(tw[ww]["pass"] for ww in l3); rs3[i] = sum(pr.get(ww, 0) for ww in l3) / tp3 if tp3 else np.nan
        k = (Y, nm, ps)
        if k not in cache:
            r_ = cal.weekly_rec(nm, ps); cache[k] = {int(x["wk"]): (float(x.get("tgt") or 0), float(x.get("rcy") or 0)) for x in (r_.get("seasons", {}).get(str(Y), []) if r_ else []) if cal.played(x)}
        tg = sum(cache[k].get(ww, (0, 0))[0] for ww in ws); yd = sum(cache[k].get(ww, (0, 0))[1] for ww in ws)
        if routes >= 20: tprr[i] = tg / routes; yprr[i] = yd / routes
    df["route_share"], df["route_share_l3"], df["routes_pg"], df["tprr"], df["yprr"] = rs, rs3, rpg, tprr, yprr
    # alignment x offense interactions
    df["slot_x_p11"] = df["slot_py"] / 100.0 * df["tm_p11"]; df["inline_x_p12"] = df["inline_py"] / 100.0 * df["tm_p12"]
    df["rs_x_pass"] = df["route_share"] * df["tm_pass_pg"]; df["rs_x_proe"] = df["route_share"] * pd.to_numeric(df.get("proe_std"), errors="coerce")
    df["y"] = pd.to_numeric(df["act"], errors="coerce")
    SEASON_FEATS = ["route_rate_py", "yprr_py", "tprr_py", "adot_py", "grade_route_py", "grade_off_py", "slot_py", "wide_py", "inline_py", "yac_py", "drop_py", "contested_py", "routes_py", "targets_py",
                    "ypa_py", "yco_py", "elusive_py", "breakaway_py", "grade_run_py", "gap_share_py", "rb_routes_py", "rb_yprr_py", "tm_pass_pg_py", "tm_p11_py", "tm_p12_py", "tm_shotgun_py", "ppg_py"]
    WEEKLY_FEATS = SEASON_FEATS + ["route_share", "route_share_l3", "routes_pg", "tprr", "yprr", "tm_pass_pg", "tm_p11", "tm_p12", "tm_shotgun", "proe_std", "slot_x_p11", "inline_x_p12", "rs_x_pass", "rs_x_proe", "tgt_sh", "car_sh", "ppg"]
    first = df.sort_values("wk").groupby(["year", "name", "pos"]).first().reset_index()
    seas = df.groupby(["year", "name", "pos"]).agg(season_ppg=("y", "mean"), games=("y", "size")).reset_index()
    seas = seas.merge(first[["year", "name", "pos"] + [f for f in SEASON_FEATS if f in first.columns]], on=["year", "name", "pos"]); seas = seas[seas.games >= 4]
    wk = df[df.wk >= 2].copy()
    for ps in POS4:
        s = seas[seas.pos == ps]; w = wk[wk.pos == ps]
        RES["n"][ps] = {"season": int(len(s)), "weekly": int(len(w))}
        RES["season"][ps] = corr_table(s, SEASON_FEATS, "season_ppg", min_n=50); RES["weekly"][ps] = corr_table(w, WEEKLY_FEATS, "y", min_n=200)
        P(f"\n=== {ps}: SEASON PPG (n={len(s)}) - advanced correlates ===")
        for d in RES["season"][ps][:14]: P(f"  {d['label']:44s} r {d['r']:+.3f}  rho {d['rho']:+.3f}  (n {d['n']})")
        P(f"=== {ps}: WEEKLY points (n={len(w)}) - advanced correlates ===")
        for d in RES["weekly"][ps][:16]: P(f"  {d['label']:44s} r {d['r']:+.3f}  rho {d['rho']:+.3f}  (n {d['n']})")
        basic_s = [d for d in RES["season"][ps] if d["feat"] == "ppg_py"]; adv_s = [d for d in RES["season"][ps] if d["feat"] != "ppg_py"]
        basic_w = [d for d in RES["weekly"][ps] if d["feat"] in ("tgt_sh", "car_sh", "ppg")]; adv_w = [d for d in RES["weekly"][ps] if d["feat"] not in ("tgt_sh", "car_sh", "ppg", "ppg_py")]
        RES["beats"][ps] = {"seasonBasic": basic_s[0] if basic_s else None, "seasonBestAdv": adv_s[0] if adv_s else None, "weeklyBasic": max(basic_w, key=lambda d: abs(d["r"])) if basic_w else None, "weeklyBestAdv": adv_w[0] if adv_w else None}
        b = RES["beats"][ps]
        P(f"  beats the basics? season: {b['seasonBestAdv']['label'] if b['seasonBestAdv'] else '-'} {b['seasonBestAdv']['r'] if b['seasonBestAdv'] else ''} vs prior-yr PPG {b['seasonBasic']['r'] if b['seasonBasic'] else '-'} | weekly: {b['weeklyBestAdv']['label'] if b['weeklyBestAdv'] else '-'} {b['weeklyBestAdv']['r'] if b['weeklyBestAdv'] else ''} vs {b['weeklyBasic']['label'] if b['weeklyBasic'] else '-'} {b['weeklyBasic']['r'] if b['weeklyBasic'] else ''}")
    with open(os.path.join(HERE, "data", "corr_advanced.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_CORR_ADV = " + json.dumps(RES) + ";\n")
    P(f"wrote data/corr_advanced.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
