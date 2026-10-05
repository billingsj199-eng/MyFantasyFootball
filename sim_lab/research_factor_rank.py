#!/usr/bin/env python3
"""
FACTOR RANKING by position (Jack 2026-10-02: "can you rank the best factors for each position (most predictive)").
Rows = data/metric_atlas_rows.parquet (fantasy-relevant player-weeks 2019-25: live number 5+, built entering the
game) with 3+ games played, joined to the shadow harness for ADP / past-season history. Factors are grouped into
families; for each family and position:
    alone      how well the family predicts by itself (multiple correlation R) - next game, and rest-of-season PPG
    unique     what is lost when the family is taken out of a model that has every family (drop in R-squared, as a
               share of the full model's R-squared) - what it knows that nothing else does
    best       the single strongest metric in the family (its own r with next-game points)
Missing values take the position median. Log factor_rank.log.
"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN

VEGAS = ["implied", "spread", "game_total"]; HEALTH = ["rep_q", "prac_dnp", "prac_lim"]; AGE = ["age", "exp"]; TALENT = ["jm", "draft_pick_log"]
FAM = {
    "QB": {"This season's points per game": ["ppg"], "Vegas (team implied total, spread, game total)": VEGAS,
           "Passing efficiency (EPA, success, yards per attempt, CPOE)": ["epa_per_db", "succ_rate_db", "yds_per_att", "cpoe", "comp_pct", "td_rate", "int_rate", "sack_rate"],
           "Rushing role (carries, red-zone carries, scrambles)": ["car_sh", "rz_car_per_g", "rz_car_sh", "car_per_g", "scramble_rate"],
           "Passing volume (attempts, dropbacks, team pass rate)": ["att_pg", "dropbacks_per_g", "db_sh", "team_pass_rate_std", "proe_std"],
           "Usage-based expected points (xFP)": ["xfp_pg", "pts_over_xfp"], "Draft market (ADP)": ["ladp"], "Past seasons (history, last year's PPG)": ["hist", "ppg_py", "xfp_pg_py"],
           "Team offense quality (EPA per play, plays per game)": ["team_epa_play_std", "plays_pg_std"], "Matchup (points the defense allows)": ["fpa_mult"],
           "Offensive line (pass block)": ["ol_pb_now"], "Age / experience": AGE, "Prospect grade (JM) / draft pick": TALENT, "Injury report / practice": HEALTH},
    "RB": {"This season's points per game": ["ppg"], "Workload (carry share, carries, red-zone and goal-line share)": ["car_sh", "car_per_g", "rz_car_sh", "gl_car_sh", "rz_car_per_g", "car_trend"],
           "Usage-based expected points (xFP)": ["xfp_pg", "pts_over_xfp"], "Playing time (snap share, last game, trend)": ["snap_std", "snap_l1", "snap_trend"],
           "Passing-game role (target share)": ["tgt_sh", "rz_tgt_sh", "pffr_yprr"], "Running efficiency (PFF elusive, explosive, run grade, EPA)": ["pffr_elu_rush_mtf", "pffr_explosive", "pffr_grades_run", "pffr_yco_attempt", "pffr_elusive_rating", "epa_per_rush", "succ_rate_rush"],
           "Vegas (team implied total, spread, game total)": VEGAS, "Draft market (ADP)": ["ladp"], "Past seasons (history, last year's PPG and usage)": ["hist", "ppg_py", "xfp_pg_py", "car_sh_py"],
           "Depth chart spot": ["strb"], "Team offense (EPA per play, plays, pass rate)": ["team_epa_play_std", "plays_pg_std", "proe_std"], "Matchup (points the defense allows)": ["fpa_mult"],
           "Offensive line (run block)": ["ol_rb_now"], "Age / experience": AGE, "Prospect grade (JM) / draft pick": TALENT, "Injury report / practice": HEALTH},
    "WR": {"This season's points per game": ["ppg"], "Target volume (target share, targets, air yards, WOPR)": ["tgt_sh", "tgt_per_g", "wopr", "ay_sh", "rz_tgt_sh", "tgt_trend"],
           "Usage-based expected points (xFP)": ["xfp_pg", "pts_over_xfp"], "Playing time (snap share, routes, trend)": ["snap_std", "snap_l1", "snap_trend", "pff_route_rate"],
           "Receiving quality (PFF grades, yards per route, EPA per target)": ["pff_grades_pass_route", "pff_grades_offense", "pff_yprr", "yprr_zone", "yprr_man", "epa_per_tgt", "catch_rate"],
           "Vegas (team implied total, spread, game total)": VEGAS, "Draft market (ADP)": ["ladp"], "Past seasons (history, last year's PPG and targets)": ["hist", "ppg_py", "xfp_pg_py", "tgt_sh_py"],
           "Depth chart spot": ["strb"], "Team passing (pass rate, EPA per play, plays)": ["team_pass_rate_std", "proe_std", "team_epa_play_std", "plays_pg_std"], "Quarterback out": ["qb_out"],
           "Matchup (points the defense allows)": ["fpa_mult"], "Depth of target (aDOT, deep rate)": ["adot", "deep_tgt_rate"], "Age / experience": AGE, "Prospect grade (JM) / draft pick": TALENT, "Injury report / practice": HEALTH},
}
FAM["TE"] = dict(FAM["WR"])

def main():
    log = open(os.path.join(HERE, "factor_rank.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n"); log.flush()
    D = pd.read_parquet(os.path.join(HERE, "data", "metric_atlas_rows.parquet"))
    X = SN.setup(); F = X["F"]; A = X["A"]
    H = pd.DataFrame({"year": X["year"].astype(int), "pid": A["pid"], "wk": X["wk"].astype(int), "ladp": np.log(np.where(np.isnan(X["adp"]), 260.0, X["adp"])), "hist": F["hist"], "strb": F["strb"]})
    H = H[H.pid.notna()].drop_duplicates(["year", "pid", "wk"])
    D = D.merge(H, on=["year", "pid", "wk"], how="left", suffixes=("", "_h"))
    if "draft_pick" in D: D["draft_pick_log"] = np.log(D["draft_pick"].fillna(262.0).clip(lower=1))
    D = D[(D.g >= 3)].copy()
    P(f"=== factor ranking: {len(D):,} player-weeks 2019-25 with 3+ games played (fantasy-relevant: live number 5+); rest-of-season target on {int(D.ros.notna().sum()):,} ===")
    def r2(Xm, y):
        Xd = np.column_stack([np.ones(len(y)), Xm]); b = np.linalg.lstsq(Xd, y, rcond=None)[0]; res = y - Xd @ b
        return max(0.0, 1 - res.var() / y.var())
    for ps in ("QB", "RB", "WR", "TE"):
        d = D[D.pos == ps]; fam = {}
        for k, cols in FAM[ps].items():
            cc = [c for c in cols if c in d.columns and d[c].notna().sum() > 0.3 * len(d)]
            if cc: fam[k] = cc
        allc = sorted({c for v in fam.values() for c in v})
        Z = d[allc].astype(float); Z = Z.fillna(Z.median()); Z = (Z - Z.mean()) / Z.std().replace(0, 1)
        P(f"\n##### {ps}: {len(d):,} player-weeks #####")
        for tlab, y, m in (("NEXT GAME", d.act.values.astype(float), np.ones(len(d), bool)), ("REST OF SEASON (per game)", d.ros.values.astype(float), d.ros.notna().values)):
            Zm = Z[m]; ym = y[m]; full = r2(Zm.values, ym); rows = []
            for k, cc in fam.items():
                alone = np.sqrt(r2(Zm[cc].values, ym)); rest = [c for c in allc if c not in cc]; uniq = (full - r2(Zm[rest].values, ym)) / max(full, 1e-9)
                best = max(cc, key=lambda c: abs(np.corrcoef(Zm[c].values, ym)[0, 1])); rb = np.corrcoef(Zm[best].values, ym)[0, 1]
                rows.append((alone, k, uniq, best, rb))
            P(f"  {tlab}: every factor together explains R {np.sqrt(full):.3f} ({100*full:.0f}% of the variance), n {int(m.sum()):,}")
            P(f"    {'rank  factor':66s} alone (R)   unique share   strongest single metric")
            for i, (alone, k, uniq, best, rb) in enumerate(sorted(rows, reverse=True), 1):
                P(f"    {i:2d}  {k:62s} {alone:.3f}       {100*uniq:5.1f}%        {best} ({rb:+.2f})")
    log.close()

if __name__ == "__main__":
    main()
