#!/usr/bin/env python3
"""
WHAT CORRELATES WITH SCORING - SEASON-LONG vs WEEKLY, BY POSITION (2026-09-16).

Jack: "find the biggest correlation for season long and weekly points scoring, see how it's different between the
two and the same - by position." Two horizons on the same 2019-25 player-weeks (ctx_features.parquet, 17,657
rows, 91 pre-kickoff variables) plus preseason ADP (FFC), depth-chart string and recent scoring from the weekly DB:
  SEASON   one row per player-season: outcome = season points per game (played weeks); features = what was known
           before week 1 (prior-year PPG / shares / xFP / games, ADP, draft pick, age, experience, week-1 string,
           team / coach change, Clay's preseason number for reference)
  WEEKLY   one row per player-week (weeks 2+): outcome = that week's points; features = everything known before
           kickoff (the preseason set + season-to-date PPG, last game, last 3, shares and trends, snaps, Vegas,
           opponent, weather, injury report, this week's string)
Pearson and Spearman correlations per position, ranked; then the same feature at both horizons side by side.
Log corr_horizons.log; results -> data/corr_horizons.js (SIM_CORR_HORIZONS), ZONES tab.
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
import backtest_rookie_prior as RP
import backtest_rookie_depth_live as RD
import backtest_nochart_vets as NC
import backtest_noclay_weekly as NW

sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "corr_horizons.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

POS4 = ("QB", "RB", "WR", "TE"); YEARS = list(range(2019, 2026))
LABEL = {"ppg_py": "prior-year PPG", "g_py": "prior-year games", "tgt_sh_py": "prior-year target share", "car_sh_py": "prior-year carry share", "xfp_pg_py": "prior-year xFP / game",
         "ln_adp": "preseason ADP (log, lower = earlier)", "draft_pick": "draft pick (lower = earlier)", "age": "age", "exp": "experience (yrs)", "rookie": "rookie", "yr2": "2nd year",
         "string_wk1": "week-1 depth string", "team_change": "changed team", "new_hc": "new head coach", "new_pc": "new play-caller", "clay": "Clay preseason PPG (reference)", "jm": "JM prospect score",
         "ppg": "season-to-date PPG", "last1": "last game points", "last3": "last 3 games avg", "g": "games played so far", "tgt_sh": "target share (season)", "car_sh": "carry share (season)",
         "tgt_sh_l3": "target share (last 3)", "car_sh_l3": "carry share (last 3)", "tgt_trend": "target share trend", "car_trend": "carry share trend", "rz_tgt_sh": "red-zone target share", "rz_car_sh": "red-zone carry share",
         "gl_car_sh": "goal-line carry share", "ay_sh": "air-yards share", "xfp_pg": "xFP / game (season)", "wopr": "WOPR", "db_sh": "dropback share (QB)", "att_pg": "attempts / game",
         "pts_over_xfp": "points over xFP (efficiency)", "snap_std": "snap share (season)", "snap_l1": "snap share last game", "snap_trend": "snap share trend", "snapmult": "engine snap multiplier",
         "implied": "team implied total", "opp_implied": "opponent implied total", "spread": "spread (team favored = negative)", "game_total": "game total", "fpa_mult": "opponent FPA multiplier",
         "veg": "engine Vegas multiplier", "dome": "dome", "wind": "wind (mph)", "temp": "temperature", "precip": "precipitation", "rep_q": "Questionable", "prac_dnp": "DNP practice", "prac_lim": "limited practice",
         "qb_out": "starting QB out", "vac_tgt": "vacated targets (team)", "vac_car": "vacated carries (team)", "inherit_tgt": "inherited targets", "inherit_car": "inherited carries",
         "string_now": "this week's depth string", "opp_man_std": "opponent man-coverage rate", "proe_std": "team pass rate over expected", "plays_pg_std": "team plays / game", "ol_pb_now": "OL pass-block grade (now)", "ol_rb_now": "OL run-block grade (now)", "ol_out_n": "OL starters out"}
SEASON_FEATS = ["ppg_py", "g_py", "tgt_sh_py", "car_sh_py", "xfp_pg_py", "ln_adp", "draft_pick", "age", "exp", "rookie", "yr2", "string_wk1", "team_change", "new_hc", "new_pc", "jm", "clay"]
WEEKLY_FEATS = SEASON_FEATS + ["ppg", "last1", "last3", "g", "tgt_sh", "car_sh", "tgt_sh_l3", "car_sh_l3", "tgt_trend", "car_trend", "rz_tgt_sh", "rz_car_sh", "gl_car_sh", "ay_sh", "xfp_pg", "wopr", "db_sh", "att_pg",
                               "pts_over_xfp", "snap_std", "snap_l1", "snap_trend", "implied", "opp_implied", "spread", "game_total", "fpa_mult", "dome", "wind", "temp", "precip", "rep_q", "prac_dnp", "prac_lim", "qb_out",
                               "vac_tgt", "vac_car", "inherit_tgt", "inherit_car", "string_now", "opp_man_std", "proe_std", "plays_pg_std", "ol_pb_now", "ol_rb_now", "ol_out_n"]
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "season": {}, "weekly": {}, "compare": {}, "n": {}}


def corr_table(df, feats, y, min_n=150):
    out = []
    for f in feats:
        if f not in df.columns: continue
        x = pd.to_numeric(df[f], errors="coerce"); m = x.notna() & df[y].notna()
        if m.sum() < min_n or x[m].std() == 0: continue
        r = float(np.corrcoef(x[m], df[y][m])[0, 1]); rho = float(spearmanr(x[m], df[y][m]).correlation)
        out.append({"feat": f, "label": LABEL.get(f, f), "n": int(m.sum()), "r": round(r, 3), "rho": round(rho, 3)})
    out.sort(key=lambda d: -abs(d["r"]))
    return out


def main():
    t0 = time.time()
    P("=== Correlates of scoring: season-long vs weekly, by position ===")
    df = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet"))
    df = df[df.pos.isin(POS4)].copy()
    df["ln_adp"] = np.nan
    adp_map = RP.load_adp()
    df["ln_adp"] = [np.log(adp_map[(int(y), cal.norm(n), p)]) if (int(y), cal.norm(n), p) in adp_map else np.nan for y, n, p in zip(df.year, df.name, df.pos)]
    # depth strings: this week's (any team) and week 1's
    weekly, dated = RD.load_depth(); weekly_any, dated_any = NC.load_depth_any(); games25 = B.load_games(2025)
    def string_at(y, pid, tm, w):
        if not isinstance(pid, str): return np.nan
        if y <= 2024:
            v = weekly_any.get((y, pid, w)); return v[0] if v else np.nan
        gm = games25.get((tm, w)); lst = dated_any.get(pid)
        if not gm or not lst: return np.nan
        before = [x for x in lst if x[0] < gm["date"]]; return before[-1][1] if before else np.nan
    df["string_now"] = [string_at(int(y), p, t, int(w)) for y, p, t, w in zip(df.year, df.pid, df.team, df.wk)]
    df["string_wk1"] = [string_at(int(y), p, t, 1) for y, p, t in zip(df.year, df.pid, df.team)]
    # recent scoring from the weekly DB
    last1 = np.full(len(df), np.nan); last3 = np.full(len(df), np.nan)
    cache = {}
    for i, (y, n, p, w) in enumerate(zip(df.year, df.name, df.pos, df.wk)):
        k = (int(y), n, p)
        if k not in cache:
            rec = cal.weekly_rec(n, p); rows = sorted([(int(r["wk"]), float(r["fpts"])) for r in (rec.get("seasons", {}).get(str(int(y)), []) if rec else []) if cal.played(r) and isinstance(r.get("fpts"), (int, float))])
            cache[k] = rows
        prev = [f for ww, f in cache[k] if ww < int(w)]
        if prev: last1[i] = prev[-1]; last3[i] = float(np.mean(prev[-3:]))
    df["last1"] = last1; df["last3"] = last3
    # ---- SEASON table: one row per player-season ----
    df["y"] = pd.to_numeric(df["act"], errors="coerce")
    first = df.sort_values("wk").groupby(["year", "name", "pos"]).first().reset_index()
    seas = df.groupby(["year", "name", "pos"]).agg(season_ppg=("y", "mean"), games=("y", "size")).reset_index()
    seas = seas.merge(first[["year", "name", "pos"] + [f for f in SEASON_FEATS if f in first.columns]], on=["year", "name", "pos"])
    seas = seas[seas.games >= 4]
    wk = df[df.wk >= 2].copy()
    P(f"  season rows {len(seas)} (player-seasons, >= 4 graded weeks) | weekly rows {len(wk)} (weeks 2+)")
    for ps in POS4:
        s = seas[seas.pos == ps]; w = wk[wk.pos == ps]
        RES["n"][ps] = {"season": int(len(s)), "weekly": int(len(w))}
        RES["season"][ps] = corr_table(s, SEASON_FEATS, "season_ppg", min_n=60)
        RES["weekly"][ps] = corr_table(w, WEEKLY_FEATS, "y", min_n=200)
        P(f"\n=== {ps}: SEASON points per game (n={len(s)} player-seasons) - top correlates ===")
        for d in RES["season"][ps][:12]: P(f"  {d['label']:40s} r {d['r']:+.3f}  rho {d['rho']:+.3f}  (n {d['n']})")
        P(f"=== {ps}: WEEKLY points (n={len(w)} player-weeks) - top correlates ===")
        for d in RES["weekly"][ps][:15]: P(f"  {d['label']:40s} r {d['r']:+.3f}  rho {d['rho']:+.3f}  (n {d['n']})")
        # same feature, both horizons
        sd = {d["feat"]: d for d in RES["season"][ps]}; wd = {d["feat"]: d for d in RES["weekly"][ps]}
        both = [{"feat": f, "label": LABEL.get(f, f), "season_r": sd[f]["r"], "weekly_r": wd[f]["r"], "season_rho": sd[f]["rho"], "weekly_rho": wd[f]["rho"]} for f in SEASON_FEATS if f in sd and f in wd]
        both.sort(key=lambda d: -abs(d["season_r"]))
        RES["compare"][ps] = both
        P(f"=== {ps}: the same preseason feature at both horizons (r season | r weekly) ===")
        for d in both: P(f"  {d['label']:40s} {d['season_r']:+.3f} | {d['weekly_r']:+.3f}")
    # a cross-position summary: top-3 at each horizon
    RES["summary"] = {ps: {"season": [d["label"] + f" ({d['r']:+.2f})" for d in RES["season"][ps][:3]], "weekly": [d["label"] + f" ({d['r']:+.2f})" for d in RES["weekly"][ps][:3]]} for ps in POS4}
    P("\n=== Summary ===")
    for ps in POS4: P(f"  {ps}: season -> " + ", ".join(RES["summary"][ps]["season"]) + " | weekly -> " + ", ".join(RES["summary"][ps]["weekly"]))
    with open(os.path.join(HERE, "data", "corr_horizons.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_CORR_HORIZONS = " + json.dumps(RES) + ";\n")
    P(f"wrote data/corr_horizons.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
