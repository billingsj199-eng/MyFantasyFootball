#!/usr/bin/env python3
"""
FTN CHARTING AS RECEIVER / QB CONTEXT (Jack 2026-10-07 evening: the one unopened dataset).  RESEARCH SCREEN.
pbp_cache/ftn_charting_2022-25 joined to the play-by-play on (nflverse_game_id, nflverse_play_id). Season to date before
the week:
  TEAM   play-action rate, motion rate, screen rate, no-huddle rate, RPO rate, blitz-faced rate (1+ blitzers), average pass
         rushers, QB out-of-pocket rate, interception-worthy rate, throw-away rate, average box count, catchable-ball rate
  RECEIVER   screen share of his targets, catchable share, contested share, drop rate, created-reception rate
Rows: 2022-25 top-150 player-weeks (FTN coverage), base = blended number as wired (QB/RB/WR .7, TE .3 shadow). Spearman of
actual / base with each metric's within-week z by position; quintile act/base; multiplier 1 + e x z, leave-one-season-out
over the 4 seasons (no formal ship bar at 4 seasons - a screen for leads). Log ftn_context.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
SN = BR.SN; NW = BR.NW; cal = NW.cal; YEARS = [2022, 2023, 2024, 2025]; POS4 = BR.POS4
CACHE = r"E:\MyFantasyFootball\pbp_cache"
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "ftn_context.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
TM_ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI"}
BBW = {"QB": 0.7, "RB": 0.7, "WR": 0.7, "TE": 0.3}
TEAM_M = ("pa", "motion", "screen", "huddle", "rpo", "blitz", "rushers", "oop", "intw", "throwaway", "box", "catchable")
RECV_M = ("r_screen", "r_catchable", "r_contested", "r_drop", "r_created")


def load():
    team = defaultdict(lambda: np.zeros(14))   # (Y, team, wk): [plays, dropbacks, pa, motion, screen, huddle, rpo, blitz, rushers_sum, oop, intw, throwaway, box_sum, catchable]
    recv = defaultdict(lambda: np.zeros(6))    # (Y, gsis, wk): [targets, screen, catchable, contested, drop, created]
    for Y in YEARS:
        f = pd.read_parquet(os.path.join(CACHE, f"ftn_charting_{Y}.parquet"))
        p = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), compression="gzip", usecols=["game_id", "play_id", "week", "posteam", "season_type", "play_type", "qb_dropback", "pass_attempt", "receiver_player_id"], low_memory=False)
        p = p[(p.season_type == "REG") & p.posteam.notna() & p.play_type.isin(["pass", "run"])]
        d = p.merge(f, left_on=["game_id", "play_id"], right_on=["nflverse_game_id", "nflverse_play_id"], how="inner")
        d["tm"] = d.posteam.map(lambda t: TM_ALIAS.get(str(t), str(t)))
        for (tm, wk), g in d.groupby(["tm", "week_x"]):
            db = g[g.qb_dropback == 1]; att = g[g.pass_attempt == 1]
            team[(Y, tm, int(wk))] += np.array([len(g), len(db), db.is_play_action.sum(), g.is_motion.sum(), att.is_screen_pass.sum(), g.is_no_huddle.sum(), g.is_rpo.sum(),
                                                (db.n_blitzers.fillna(0) > 0).sum(), db.n_pass_rushers.fillna(0).sum(), db.is_qb_out_of_pocket.sum(), att.is_interception_worthy.sum(), att.is_throw_away.sum(),
                                                g.n_defense_box.fillna(0).sum(), att.is_catchable_ball.sum()], dtype=float)
        tg = d[(d.pass_attempt == 1) & d.receiver_player_id.notna()]
        for (rid, wk), g in tg.groupby(["receiver_player_id", "week_x"]):
            recv[(Y, rid, int(wk))] += np.array([len(g), g.is_screen_pass.sum(), g.is_catchable_ball.sum(), g.is_contested_ball.sum(), g.is_drop.sum(), g.is_created_reception.sum()], dtype=float)
        P(f"  {Y}: {len(d):,} charted plays joined")
    return team, recv


def main():
    team_wk, recv_wk = load()
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name, team, pid = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["team"], X["A"]["pid"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    bw = np.array([BBW[p_] for p_ in pos]); BASE = bw * SHADOW + (1 - bw) * TODAY
    ok = (g >= 1) & ~final & ~LV["inh"] & top150 & np.isin(year, YEARS) & (BASE >= 3)
    M = {k: np.full(n, np.nan) for k in TEAM_M + RECV_M}
    for i in np.where(ok)[0]:
        Y = int(year[i]); rows = [team_wk[(Y, team[i], w)] for w in range(1, int(wk[i])) if (Y, team[i], w) in team_wk]
        if len(rows) >= 2:
            a = np.sum(rows, axis=0); pl, db, att = max(a[0], 1), max(a[1], 1), max(a[4] + 1e-9, 1)
            natt = sum(1 for r in rows) and max(sum(r[1] for r in rows), 1)
            M["pa"][i] = a[2] / db; M["motion"][i] = a[3] / pl; M["screen"][i] = a[4] / db; M["huddle"][i] = a[5] / pl; M["rpo"][i] = a[6] / pl; M["blitz"][i] = a[7] / db
            M["rushers"][i] = a[8] / db; M["oop"][i] = a[9] / db; M["intw"][i] = a[10] / db; M["throwaway"][i] = a[11] / db; M["box"][i] = a[12] / pl; M["catchable"][i] = a[13] / db
        if isinstance(pid[i], str):
            rr = [recv_wk[(Y, pid[i], w)] for w in range(1, int(wk[i])) if (Y, pid[i], w) in recv_wk]
            if rr:
                a = np.sum(rr, axis=0)
                if a[0] >= 10: M["r_screen"][i] = a[1] / a[0]; M["r_catchable"][i] = a[2] / a[0]; M["r_contested"][i] = a[3] / a[0]; M["r_drop"][i] = a[4] / a[0]; M["r_created"][i] = a[5] / a[0]
    Z = {}
    for k in M:
        z = np.full(n, np.nan)
        for y in YEARS:
            for w in range(1, 19):
                m = ok & (year == y) & (wk == w) & ~np.isnan(M[k])
                if m.sum() >= 20 and np.nanstd(M[k][m]) > 0: z[m] = np.clip((M[k][m] - np.nanmean(M[k][m])) / np.nanstd(M[k][m]), -2.5, 2.5)
        Z[k] = z
    ratio = np.where(BASE > 0, act / BASE, np.nan)
    P(f"\n=== FTN CONTEXT SCREEN: {int(ok.sum()):,} top-150 player-weeks 2022-25, base = blended number as wired ===")
    P("\n--- 1  Spearman of actual / base with each metric's within-week z, by position (|rho| >= .05 flagged) ---")
    P(f"    {'metric':12s} " + " ".join(f"{ps:>14s}" for ps in POS4))
    for k in TEAM_M + RECV_M:
        cells = []
        for ps in POS4:
            m = ok & (pos == ps) & ~np.isnan(Z[k])
            if m.sum() < 150: cells.append(f"{'n/a':>14s}"); continue
            r = spearmanr(Z[k][m], ratio[m]).correlation; cells.append(f"{r:+.3f}{'*' if abs(r) >= 0.05 else ' '} n{int(m.sum()):<5d}")
        P(f"    {k:12s} " + " ".join(cells))
    P("\n--- 2  quintiles (WR + TE for team metrics / receiver metrics; RB for team metrics): actual / base low -> high ---")
    for k in TEAM_M + RECV_M:
        for grp, gm in (("WR+TE", np.isin(pos, ("WR", "TE"))), ("RB", pos == "RB"), ("QB", pos == "QB")):
            if k.startswith("r_") and grp != "WR+TE": continue
            m = ok & gm & ~np.isnan(Z[k])
            if m.sum() < 300: continue
            q = np.nanpercentile(Z[k][m], [20, 40, 60, 80]); e = [-9] + list(q) + [9]; cells = []
            for a in range(5):
                mm = m & (Z[k] >= e[a]) & (Z[k] < e[a + 1]); cells.append(f"{act[mm].sum()/BASE[mm].sum():.3f}")
            P(f"    {k:12s} {grp:5s} " + " ".join(cells) + f"   (metric {np.nanmean(M[k][m & (Z[k] < e[1])]):.3f} -> {np.nanmean(M[k][m & (Z[k] >= e[4])]):.3f})")
    P("\n--- 3  multipliers 1 + e x z (sign from the correlation), leave-one-season-out over 4 seasons; weighted error vs base ---")
    wm = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    for k in TEAM_M + RECV_M:
        for grp, gm in (("WR+TE", np.isin(pos, ("WR", "TE"))), ("RB", pos == "RB"), ("QB", pos == "QB")):
            if k.startswith("r_") and grp != "WR+TE": continue
            m = ok & gm & ~np.isnan(Z[k])
            if m.sum() < 300: continue
            r = spearmanr(Z[k][m], ratio[m]).correlation
            if abs(r) < 0.03: continue
            sgn = 1.0 if r > 0 else -1.0; preds = {"off": BASE}
            for e_ in (0.01, 0.02, 0.04): p = BASE.copy(); p[m] = BASE[m] * np.clip(1 + sgn * e_ * Z[k][m], 0.85, 1.15); preds[f"e {e_}"] = p
            names = list(preds); pick = lambda yrs: min(names, key=lambda kk: wm(preds[kk], m & np.isin(year, yrs)))
            wins = 0; pr = BASE.copy(); picks = []
            for te in YEARS:
                kk = pick([y for y in YEARS if y != te]); picks.append(kk); mm = year == te; pr[mm] = preds[kk][mm]; wins += wm(preds[kk], m & mm) < wm(BASE, m & mm) - 1e-12
            fixed = "  ".join(f"{kk}: {100*(wm(preds[kk], m)/wm(BASE, m)-1):+.2f}%" for kk in names[1:])
            P(f"    {k:12s} {grp:5s} rho {r:+.3f} | {fixed} | LOYO {100*(wm(pr, m)/wm(BASE, m)-1):+.2f}% {wins}/4 picks {picks}")
    P("\nLimitations: 4 seasons of charting (2022-25), screen only; team rates season to date from charted plays; receiver metrics need 10+ charted targets; the blended base already carries Vegas, FPA and the shadow's context.")
    LOG.close()


if __name__ == "__main__":
    main()
