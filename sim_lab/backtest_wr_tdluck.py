#!/usr/bin/env python3
"""
RECEIVER TD-SHARE REGRESSION backtest, 2019-2025 (Jack 2026-09-14: "backtest
the receiver TD-share regression next"). The RB TD-luck layer (shipped
09-14, backtest_rb_role.py) applied to WR/TE: a receiver's realized PPG
carries TD luck that the LOCATION and DEPTH of his targets says should
regress. Also the candidate mechanism behind the aDOT tilt
(backtest_adot_level.py): deep receivers' points are TD-heavier.

xTD per TARGET = league TD probability by (yardline bucket x end-zone-throw
flag [air_yards >= yardline_100]) pooled nflverse pbp 2018-25; xTD per
CARRY (WR/TE rushes) = the RB table's yardline buckets. luck = (xTD - TD)/g
season-to-date (weeks < W), g = games with a touch.

Tests (base = P=5 Clay/PPG x Vegas .25 x in-season FPA = "shipped", WR + TE,
LOYO):
  1. residual by luck tercile; TD share of realized points tercile
  2. additive correction + k * tdPts * luck * g/(P+g) (the RB form), LOYO k
  3. per position; centered-per-season control (level vs regression)
  4. does the correction flatten the aDOT tilt?
Log: wr_tdluck_backtest.log
"""
import numpy as np
import pandas as pd
import json, os
from collections import defaultdict
from backtest_sim_calibration import (played, weekly_rec, infer_team,
                                      POOL_MIN_PTS, OPP_ALIAS)
import backtest_sim_calibration as cal
from backtest_snap_defense import build_fpa
from backtest_target_area import (load_players, resolve_gsis, implied_map, mse, loyo,
                                  LOAD_YEARS, YEARS, VEGAS_E, FPA_E, FPA_TRUST_G, P, CACHE)
# (stdout already re-wrapped by backtest_target_area on import)

POS_TEST = ("WR", "TE")
YL_BINS = [0, 1, 2, 3, 5, 10, 20, 40, 100]
RUSH_BINS = [0, 1, 2, 3, 4, 5, 10, 20, 40, 100]

def load_touches(Y):
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"),
                     usecols=["game_id", "season_type", "week", "posteam", "home_team", "away_team", "home_score",
                              "away_score", "spread_line", "total_line", "pass_attempt", "rush_attempt", "sack",
                              "receiver_player_id", "rusher_player_id", "air_yards", "yardline_100",
                              "pass_touchdown", "rush_touchdown"], low_memory=False)
    df = df[(df.season_type == "REG") & df.posteam.notna()]
    lines = df.dropna(subset=["spread_line", "total_line"]).groupby("game_id").first()
    tg = df[(df.pass_attempt == 1) & (df.sack != 1) & df.receiver_player_id.notna() & df.yardline_100.notna()].copy()
    tg["pid"] = tg.receiver_player_id; tg["is_rush"] = 0
    tg["td"] = tg.pass_touchdown.fillna(0)
    tg["ez"] = (tg.air_yards.fillna(0) >= tg.yardline_100).astype(int)
    tg["yb"] = pd.cut(tg.yardline_100, YL_BINS, right=True, labels=False)
    ru = df[(df.rush_attempt == 1) & df.rusher_player_id.notna() & df.yardline_100.notna()].copy()
    ru["pid"] = ru.rusher_player_id; ru["is_rush"] = 1
    ru["td"] = ru.rush_touchdown.fillna(0); ru["ez"] = 0
    ru["yb"] = pd.cut(ru.yardline_100, RUSH_BINS, right=True, labels=False)
    t = pd.concat([tg, ru], ignore_index=True)
    t["season"] = Y
    return t[["season", "week", "pid", "is_rush", "ez", "yb", "td"]], lines

def main():
    by_norm = load_players()
    frames, lines_all = {}, {}
    for Y in LOAD_YEARS:
        frames[Y], lines_all[Y] = load_touches(Y)
        print(f"  pbp {Y}: {len(frames[Y])} touches")
    allt = pd.concat(frames.values(), ignore_index=True)
    rate = allt.groupby(["is_rush", "ez", "yb"]).td.agg(["mean", "count"])
    print("  xTD per target (not end-zone throw): " + "  ".join(f"<={YL_BINS[i+1]}:{rate['mean'].get((0,0,i),0):.3f}" for i in range(len(YL_BINS)-1)))
    print("  xTD per target (END-ZONE throw)    : " + "  ".join(f"<={YL_BINS[i+1]}:{rate['mean'].get((0,1,i),0):.3f}" for i in range(len(YL_BINS)-1)))
    allt["xtd"] = [rate["mean"].get((r, e, b), 0.0) for r, e, b in zip(allt.is_rush, allt.ez, allt.yb)]
    pw = allt.groupby(["season", "pid", "week"]).agg(td=("td", "sum"), xtd=("xtd", "sum"), n=("td", "count")).reset_index()
    look = {}
    for (s, pid), grp in pw.sort_values("week").groupby(["season", "pid"]):
        cum = {"td": 0.0, "xtd": 0.0, "n": 0.0, "g": 0}; lst = []
        for r in grp.itertuples(index=False):
            cum["td"] += r.td; cum["xtd"] += r.xtd; cum["n"] += r.n; cum["g"] += 1
            lst.append((int(r.week), dict(cum)))
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
            pos = c.get("pos")
            if pos not in POS_TEST or (c.get("pts") or 0) < POOL_MIN_PTS: continue
            wrec = weekly_rec(name, pos)
            if wrec is None: miss["weekly"] += 1; continue
            team = infer_team(wrec, Y)
            if not team: miss["team"] += 1; continue
            pid = resolve_gsis(by_norm, name, pos, Y)
            if pid is None: miss["gsis"] += 1; continue
            rows = sorted([(w["wk"], w["fpts"], OPP_ALIAS.get(w.get("opp"), w.get("opp")),
                            (w.get("rctd") or 0) + (w.get("rtd") or 0))
                           for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            hist = []; tds = 0
            for wk, fpts, opp, wtd in rows:
                li = imp.get((team, wk))
                if li is not None and hist and opp:
                    g = len(hist); ppg = sum(hist) / g
                    base = (P * clay_pg + g * ppg) / (P + g)
                    veg = min(1.35, max(0.7, 1 + VEGAS_E[pos] * (li - avg) / avg))
                    cur = weekly_fpa.get((Y, opp, pos), {}); past = [w for w in cur if w < wk]
                    fpa = 1.0
                    if past and lg_fpa.get((Y, pos)):
                        ratio = min(1.25, max(0.8, (sum(cur[w] for w in past) / len(past)) / lg_fpa[(Y, pos)]))
                        fpa = 1 + FPA_E * (ratio - 1) * min(1, len(past) / FPA_TRUST_G)
                    cm = before(look.get((Y, pid)), wk)
                    if not cm: hist.append(fpts); tds += wtd; miss["notouch"] += 1; continue
                    S["year"].append(Y); S["pos"].append(pos); S["act"].append(fpts); S["g"].append(g)
                    S["clay"].append(clay_pg); S["ppg"].append(ppg); S["base"].append(base)
                    S["veg"].append(veg); S["fpa"].append(fpa)
                    S["luck"].append((cm["xtd"] - cm["td"]) / cm["g"])
                    S["xtd_g"].append(cm["xtd"] / cm["g"]); S["td_g"].append(cm["td"] / cm["g"])
                    S["tdshare"].append(6.0 * tds / max(1e-9, sum(hist)))   # TD share of realized half-PPR points
                    S["ntg"].append(cm["n"])
                hist.append(fpts); tds += wtd
        print(f"  {Y}: samples so far {len(S['act'])}")
    print(f"  skipped: {dict(miss)}")
    S = {k: (np.array(v) if k == "pos" else np.array(v, float)) for k, v in S.items()}
    S["year"] = S["year"].astype(int); years = sorted(set(S["year"]))
    act, pos = S["act"], S["pos"]
    chain = S["veg"] * S["fpa"]; shipped = S["base"] * chain
    luck = S["luck"]; wreal = S["g"] / (P + S["g"])
    print(f"\n{len(act)} WR/TE player-weeks | shipped MSE {mse(shipped, act):.4f} | mean act/shipped {act.mean()/shipped.mean():.3f}")
    print(f"  luck mean {luck.mean():+.4f}/g (xTD/g {S['xtd_g'].mean():.3f} vs TD/g {S['td_g'].mean():.3f}); by year: " +
          " ".join(f"{y}:{luck[S['year']==y].mean():+.3f}" for y in years))

    def terc(x, label, pred, mask):
        q = np.quantile(x[mask], [1/3, 2/3]); parts = []
        for lo, hi, lab in ((-np.inf, q[0], "low"), (q[0], q[1], "mid"), (q[1], np.inf, "high")):
            m = mask & (x >= lo) & (x < hi)
            parts.append(f"{lab} {x[m].mean():+.3f}: {act[m].mean()/pred[m].mean():.3f} (n={m.sum()})")
        r = np.corrcoef(x[mask], act[mask] - pred[mask])[0, 1]
        print(f"  {label:26s} " + " | ".join(parts) + f"   corr(x, act-pred) {r:+.3f}")
    print("\n=== 1. actual / shipped by tercile ===")
    for p in POS_TEST:
        m = pos == p
        terc(luck, f"{p} TD luck (xTD-TD)/g", shipped, m)
        terc(S["tdshare"], f"{p} TD share of pts", shipped, m)
        for lo, hi in ((1, 4), (5, 9), (10, 20)):
            mm = m & (S["g"] >= lo) & (S["g"] <= hi)
            terc(luck, f"   {p} luck, games {lo}-{hi}", shipped, mm)

    print("\n=== 2. LOYO: shipped + k * 6 * luck * g/(P+g)   (RB layer form; grid[0] = shipped) ===")
    grid = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]
    res = {}
    res["all"] = loyo(S, years, grid, lambda k: shipped + k * 6.0 * luck * wreal, "a) WR + TE")
    for p in POS_TEST:
        m = pos == p; Sp = {k: v[m] for k, v in S.items()}; shp = shipped[m]; lk = luck[m]; wr = wreal[m]
        res[p] = loyo(Sp, years, grid, lambda k, shp=shp, lk=lk, wr=wr: shp + k * 6.0 * lk * wr, f"   {p} only")
    luck_c = luck.copy()
    for y in years:
        for p in POS_TEST:
            m = (S["year"] == y) & (pos == p); luck_c[m] = luck[m] - luck[m].mean()
    res["c"] = loyo(S, years, grid, lambda k: shipped + k * 6.0 * luck_c * wreal, "b) CENTERED per season x position (pure regression, no level)")
    res["m"] = loyo(S, years, grid, lambda k: shipped * np.clip(1 + k * 6.0 * luck * wreal / np.maximum(S["base"], 2.0), 0.7, 1.4),
                    "c) multiplicative form (same points, scaled through the chain)")
    # TD share of realized points as the predictor instead of xTD (no pbp needed - weekly DB only)
    lgsh = {p: S["tdshare"][pos == p].mean() for p in POS_TEST}
    dev = np.array([S["tdshare"][i] - lgsh[pos[i]] for i in range(len(act))])
    res["s"] = loyo(S, years, [0.0, 0.1, 0.2, 0.3, 0.4, 0.6], lambda k: shipped * np.clip(1 - k * dev * wreal, 0.7, 1.4),
                    "d) TD-SHARE dev only (weekly-DB predictor, no pbp): x(1 - k*(tdShare - posAvg)*g/(P+g))")

    print("\n=== 3. by games-into-season (k=.75 pooled) and by touches ===")
    pred = shipped + 0.75 * 6.0 * luck * wreal
    for lo, hi in ((1, 4), (5, 9), (10, 20)):
        m = (S["g"] >= lo) & (S["g"] <= hi)
        print(f"  games {lo}-{hi}: n={m.sum()}  shipped {mse(shipped[m],act[m]):.3f} -> luck {mse(pred[m],act[m]):.3f} ({(mse(pred[m],act[m])/mse(shipped[m],act[m])-1)*100:+.2f}%)")
    for y in years:
        m = S["year"] == y
        print(f"  {y}: shipped {mse(shipped[m],act[m]):.3f} -> {mse(pred[m],act[m]):.3f} ({(mse(pred[m],act[m])/mse(shipped[m],act[m])-1)*100:+.2f}%)")

    print("\n=== 4. does it explain the aDOT tilt? need aDOT: TD-heaviness by xTD/g quintile instead ===")
    x = S["xtd_g"]; m = pos == "WR"
    q = np.quantile(x[m], [.2, .4, .6, .8]); edges = [-np.inf] + list(q) + [np.inf]
    for lab, pr in (("shipped", shipped), ("with luck k=.75", pred)):
        parts = []
        for i in range(5):
            mm = m & (x >= edges[i]) & (x < edges[i + 1])
            parts.append(f"xTD/g {x[mm].mean():.2f}->{act[mm].mean()/pr[mm].mean():.3f}")
        print(f"  {lab:16s} " + " | ".join(parts))

if __name__ == "__main__":
    main()
