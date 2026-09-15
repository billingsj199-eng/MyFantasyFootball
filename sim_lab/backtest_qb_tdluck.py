#!/usr/bin/env python3
"""
QB PASSING-TD LUCK backtest, 2019-2025 (Jack 2026-09-14: "backtest the QB
passing-TD luck next"). Last member of the TD-luck family (RB shipped
backtest_rb_role.py, WR/TE shipped backtest_wr_tdluck.py).

xPassTD = sum over his targeted pass attempts of the receiver table's TD
probability (yardline bucket x end-zone-throw flag, pooled pbp 2018-25).
xRushTD = sum over his carries (designed + scrambles) of a QB-SPECIFIC rush
table by yardline (sneaks at the 1 convert far more often than RB carries).
luck_pass = (xPassTD - passTD)/g   luck_rush = (xRushTD - rushTD)/g

Tests (base = P=5 Clay/PPG x Vegas .25 x in-season QB FPA = "shipped", LOYO):
  1. residual by luck tercile (pass, rush, combined points)
  2. additive + k * (4*luck_pass + 6*luck_rush) * g/(P+g): pass only, rush
     only, combined; centered control; by games-into-season
Log: qb_tdluck_backtest.log
"""
import numpy as np
import pandas as pd
import json, os
from collections import defaultdict
from backtest_sim_calibration import (played, weekly_rec, infer_team, POOL_MIN_PTS, OPP_ALIAS)
import backtest_sim_calibration as cal
from backtest_snap_defense import build_fpa
from backtest_target_area import implied_map, mse, loyo, LOAD_YEARS, YEARS, FPA_E, FPA_TRUST_G, P, CACHE
# (stdout re-wrapped by backtest_target_area on import)

VEGAS_E_QB = 0.25
YL_BINS = [0, 5, 10, 20, 40, 100]
XTD_NONEZ = [0.264, 0.213, 0.080, 0.030, 0.007]     # receiver table (backtest_wr_tdluck.py, pooled 2018-25)
XTD_EZ    = [0.501, 0.384, 0.330, 0.271, 0.232]
RUSH_BINS = [0, 1, 2, 3, 5, 10, 20, 40, 100]

def load_qbs():
    p = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False,
                    usecols=["gsis_id", "display_name", "position", "rookie_season", "last_season"])
    p = p[(p.position == "QB") & p.gsis_id.notna()]
    by_norm = defaultdict(list)
    for r in p.itertuples(index=False):
        by_norm[cal.norm(str(r.display_name))].append(
            (r.gsis_id, r.rookie_season if pd.notna(r.rookie_season) else 0, r.last_season if pd.notna(r.last_season) else 9999))
    return set(p.gsis_id), by_norm

def resolve(by_norm, name, Y):
    c = [x for x in by_norm.get(cal.norm(name), []) if x[1] <= Y <= x[2] + 1]
    return c[0][0] if len(c) == 1 else None

def load_year(Y, qb_ids):
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"),
                     usecols=["game_id", "season_type", "week", "posteam", "home_team", "away_team", "home_score",
                              "away_score", "spread_line", "total_line", "pass_attempt", "rush_attempt", "sack",
                              "passer_player_id", "rusher_player_id", "receiver_player_id", "air_yards",
                              "yardline_100", "pass_touchdown", "rush_touchdown"], low_memory=False)
    df = df[(df.season_type == "REG") & df.posteam.notna()]
    lines = df.dropna(subset=["spread_line", "total_line"]).groupby("game_id").first()
    pa = df[(df.pass_attempt == 1) & (df.sack != 1) & df.passer_player_id.isin(qb_ids) & df.yardline_100.notna()].copy()
    pa["pid"] = pa.passer_player_id
    ez = (pa.air_yards.fillna(0) >= pa.yardline_100)
    yb = pd.cut(pa.yardline_100, YL_BINS, right=True, labels=False).fillna(4).astype(int)
    tgt = pa.receiver_player_id.notna()
    pa["xtd"] = np.where(tgt, np.where(ez, np.array(XTD_EZ)[yb], np.array(XTD_NONEZ)[yb]), 0.0)   # throwaways: 0
    pa["td"] = pa.pass_touchdown.fillna(0); pa["kind"] = "pass"
    ru = df[(df.rush_attempt == 1) & df.rusher_player_id.isin(qb_ids) & df.yardline_100.notna()].copy()
    ru["pid"] = ru.rusher_player_id; ru["td"] = ru.rush_touchdown.fillna(0); ru["kind"] = "rush"
    ru["yb"] = pd.cut(ru.yardline_100, RUSH_BINS, right=True, labels=False)
    ru["xtd"] = np.nan
    t = pd.concat([pa[["week", "pid", "kind", "xtd", "td"]].assign(yb=np.nan), ru[["week", "pid", "kind", "xtd", "td", "yb"]]], ignore_index=True)
    t["season"] = Y
    return t, lines

def main():
    qb_ids, by_norm = load_qbs()
    frames, lines_all = {}, {}
    for Y in LOAD_YEARS:
        frames[Y], lines_all[Y] = load_year(Y, qb_ids)
        print(f"  pbp {Y}: {int((frames[Y].kind=='pass').sum())} QB attempts, {int((frames[Y].kind=='rush').sum())} QB rushes")
    allt = pd.concat(frames.values(), ignore_index=True)
    ru = allt[allt.kind == "rush"]
    qrate = ru.groupby("yb").td.agg(["mean", "count"])
    print("  QB rush xTD by yardline: " + "  ".join(f"<={RUSH_BINS[i+1]}:{qrate['mean'].get(i,0):.3f}(n={int(qrate['count'].get(i,0))})" for i in range(len(RUSH_BINS)-1)))
    allt.loc[allt.kind == "rush", "xtd"] = [qrate["mean"].get(b, 0.0) for b in ru.yb]
    pw = allt.groupby(["season", "pid", "week", "kind"]).agg(td=("td", "sum"), xtd=("xtd", "sum")).reset_index()
    look = {}
    for (s, pid), grp in pw.sort_values("week").groupby(["season", "pid"]):
        cum = {"ptd": 0.0, "pxtd": 0.0, "rtd": 0.0, "rxtd": 0.0, "g": 0}; lst = []; last = None
        for r in grp.itertuples(index=False):
            if r.kind == "pass": cum["ptd"] += r.td; cum["pxtd"] += r.xtd
            else: cum["rtd"] += r.td; cum["rxtd"] += r.xtd
            if r.week != last: cum["g"] += 1; last = r.week
            if lst and lst[-1][0] == int(r.week): lst[-1] = (int(r.week), dict(cum))
            else: lst.append((int(r.week), dict(cum)))
        look[(s, pid)] = lst
    def before(lst, wk):
        best = None
        for w, c in lst or []:
            if w < wk: best = c
            else: break
        return best

    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    weekly_fpa, season_fpa, lg_fpa = build_fpa()
    S = defaultdict(list); miss = defaultdict(int)
    for Y in YEARS:
        if str(Y) not in clay_hist: continue
        imp = implied_map(lines_all[Y]); avg = float(np.mean(list(imp.values())))
        W = 16 if Y <= 2020 else 17
        for name, c in clay_hist[str(Y)].items():
            if c.get("pos") != "QB" or (c.get("pts") or 0) < POOL_MIN_PTS: continue
            wrec = weekly_rec(name, "QB")
            if wrec is None: miss["weekly"] += 1; continue
            team = infer_team(wrec, Y)
            if not team: miss["team"] += 1; continue
            pid = resolve(by_norm, name, Y)
            if pid is None: miss["gsis"] += 1; continue
            rows = sorted([(w["wk"], w["fpts"], OPP_ALIAS.get(w.get("opp"), w.get("opp")))
                           for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            hist = []
            for wk, fpts, opp in rows:
                li = imp.get((team, wk))
                if li is not None and hist and opp:
                    g = len(hist); ppg = sum(hist) / g
                    base = (P * clay_pg + g * ppg) / (P + g)
                    veg = min(1.35, max(0.7, 1 + VEGAS_E_QB * (li - avg) / avg))
                    cur = weekly_fpa.get((Y, opp, "QB"), {}); past = [w for w in cur if w < wk]
                    fpa = 1.0
                    if past and lg_fpa.get((Y, "QB")):
                        ratio = min(1.25, max(0.8, (sum(cur[w] for w in past) / len(past)) / lg_fpa[(Y, "QB")]))
                        fpa = 1 + FPA_E * (ratio - 1) * min(1, len(past) / FPA_TRUST_G)
                    cm = before(look.get((Y, pid)), wk)
                    if not cm or cm["g"] < 1: hist.append(fpts); miss["notouch"] += 1; continue
                    S["year"].append(Y); S["act"].append(fpts); S["g"].append(g); S["base"].append(base)
                    S["veg"].append(veg); S["fpa"].append(fpa)
                    S["lp"].append((cm["pxtd"] - cm["ptd"]) / cm["g"]); S["lr"].append((cm["rxtd"] - cm["rtd"]) / cm["g"])
                    S["pxtd_g"].append(cm["pxtd"] / cm["g"]); S["ptd_g"].append(cm["ptd"] / cm["g"])
                hist.append(fpts)
        print(f"  {Y}: samples so far {len(S['act'])}")
    print(f"  skipped: {dict(miss)}")
    S = {k: np.array(v, float) for k, v in S.items()}; S["year"] = S["year"].astype(int); years = sorted(set(S["year"]))
    act = S["act"]; chain = S["veg"] * S["fpa"]; shipped = S["base"] * chain
    wreal = S["g"] / (P + S["g"])
    lp, lr = S["lp"], S["lr"]; lpts = 4.0 * lp + 6.0 * lr
    print(f"\n{len(act)} QB player-weeks | shipped MSE {mse(shipped, act):.4f} | mean act/shipped {act.mean()/shipped.mean():.3f}")
    print(f"  pass luck mean {lp.mean():+.4f}/g (xTD/g {S['pxtd_g'].mean():.3f} vs TD/g {S['ptd_g'].mean():.3f}) | rush luck mean {lr.mean():+.4f}/g")
    print("  by year pass luck: " + " ".join(f"{y}:{lp[S['year']==y].mean():+.3f}" for y in years))

    def terc(x, label, mask=None):
        mask = np.ones_like(act, bool) if mask is None else mask
        q = np.quantile(x[mask], [1/3, 2/3]); parts = []
        for lo, hi, lab in ((-np.inf, q[0], "low"), (q[0], q[1], "mid"), (q[1], np.inf, "high")):
            m = mask & (x >= lo) & (x < hi)
            parts.append(f"{lab} {x[m].mean():+.3f}: {act[m].mean()/shipped[m].mean():.3f} (n={m.sum()})")
        r = np.corrcoef(x[mask], act[mask] - shipped[mask])[0, 1]
        print(f"  {label:26s} " + " | ".join(parts) + f"   corr(x, act-shipped) {r:+.3f}")
    print("\n=== 1. actual / shipped by tercile ===")
    terc(lp, "pass luck (xTD-TD)/g"); terc(lr, "rush luck (xTD-TD)/g"); terc(lpts, "combined luck pts/g")
    for lo, hi in ((1, 4), (5, 9), (10, 20)):
        terc(lpts, f"   combined, games {lo}-{hi}", (S["g"] >= lo) & (S["g"] <= hi))

    print("\n=== 2. LOYO: shipped + k * luckPts * g/(P+g)  (grid[0] = shipped) ===")
    grid = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]
    loyo(S, years, grid, lambda k: shipped + k * 4.0 * lp * wreal, "a) PASS luck only (x4 pts)")
    loyo(S, years, grid, lambda k: shipped + k * 6.0 * lr * wreal, "b) RUSH luck only (x6 pts)")
    lpc = lp.copy()
    for y in years:
        m = S["year"] == y; lpc[m] = lp[m] - lp[m].mean()
    loyo(S, years, grid, lambda k: shipped + k * 4.0 * lpc * wreal, "a2) PASS luck CENTERED per season (league mean removed - the live form)")
    # live-form centering: season-to-date league mean is what the engine can see; approximate by centering on samples <= same week
    lps = lp.copy()
    for y in years:
        for wk in range(2, 19):
            m = (S["year"] == y) & (S["g"] == wk - 1)
            mm = (S["year"] == y) & (S["g"] <= wk - 1)
            if m.any(): lps[m] = lp[m] - lp[mm].mean()
    loyo(S, years, grid, lambda k: shipped + k * 4.0 * lps * wreal, "a3) PASS luck centered on SEASON-TO-DATE league mean (no hindsight)")
    res = loyo(S, years, grid, lambda k: shipped + k * lpts * wreal, "c) COMBINED")
    lc = lpts.copy()
    for y in years:
        m = S["year"] == y; lc[m] = lpts[m] - lpts[m].mean()
    loyo(S, years, grid, lambda k: shipped + k * lc * wreal, "d) combined CENTERED per season (regression only)")
    loyo(S, years, grid, lambda k: shipped * np.clip(1 + k * lpts * wreal / np.maximum(S["base"], 4.0), 0.7, 1.4), "e) multiplicative form")
    k = res[0] if res[1] < 0 else 0.75
    pred = shipped + k * lpts * wreal
    print(f"\n=== 3. combined k={k} by games-into-season and by year ===")
    for lo, hi in ((1, 4), (5, 9), (10, 20)):
        m = (S["g"] >= lo) & (S["g"] <= hi)
        print(f"  games {lo}-{hi}: n={m.sum()}  {mse(shipped[m],act[m]):.3f} -> {mse(pred[m],act[m]):.3f} ({(mse(pred[m],act[m])/mse(shipped[m],act[m])-1)*100:+.2f}%)")
    for y in years:
        m = S["year"] == y
        print(f"  {y}: {mse(shipped[m],act[m]):.3f} -> {mse(pred[m],act[m]):.3f} ({(mse(pred[m],act[m])/mse(shipped[m],act[m])-1)*100:+.2f}%)")

if __name__ == "__main__":
    main()
