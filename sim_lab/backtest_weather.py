#!/usr/bin/env python3
"""
WEATHER layer backtest, 2019-2025.

Game weather from pbp (roof/temp/wind, 97%% coverage on outdoor games).
Key design point: Vegas totals already price bad weather, so QB/WR/TE are
graded on BOTH the raw P=5 base and a Vegas-adjusted base (implied totals
from the same pbp closing lines, per-pos VEGAS_ELAS) — only the increment
over Vegas is shippable. Kickers (where wind should matter most) are
reconstructed from pbp FG/XP events (no K weekly fantasy data exists) and
graded vs their own season mean.
"""
import numpy as np
import pandas as pd
import json, os
from collections import defaultdict
from backtest_sim_calibration import (played, weekly_rec, infer_team,
                                      POOL_MIN_PTS, OPP_ALIAS)
import backtest_sim_calibration as cal

CACHE = r"E:\MyFantasyFootball\pbp_cache"
P = 5
YEARS = range(2019, 2026)
TEAM_FIX = {"WSH": "WAS", "LA": "LAR", "OAK": "LV", "SD": "LAC",
            "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
VEGAS_ELAS = {"QB": 0.25, "RB": 0.50, "WR": 0.25, "TE": 0.25}

def game_table(year):
    """(team, wk) -> {roof, temp, wind, implied} for both teams of each game."""
    pbp = pd.read_csv(os.path.join(CACHE, f"play_by_play_{year}.csv.gz"),
                      usecols=["game_id", "week", "season_type", "home_team", "away_team",
                               "roof", "temp", "wind", "spread_line", "total_line"],
                      low_memory=False)
    g = pbp[pbp.season_type == "REG"].groupby("game_id").first()
    out = {}
    for _, r in g.iterrows():
        wk = int(r.week)
        indoor = r.roof in ("dome", "closed")
        # spread_line is home margin (positive = home favored)
        hi = (r.total_line + r.spread_line) / 2 if pd.notna(r.total_line) and pd.notna(r.spread_line) else None
        ai = (r.total_line - r.spread_line) / 2 if hi is not None else None
        for t, imp in ((r.home_team, hi), (r.away_team, ai)):
            out[(TEAM_FIX.get(t, t), wk)] = {
                "indoor": indoor,
                "temp": None if indoor or pd.isna(r.temp) else float(r.temp),
                "wind": None if indoor or pd.isna(r.wind) else float(r.wind),
                "implied": imp}
    return out

def kicker_weeks(year):
    """(kicker, wk) -> pts (3/4/5 FG by dist, -1 miss, +-1 XP) + game key (team, wk)."""
    pbp = pd.read_csv(os.path.join(CACHE, f"play_by_play_{year}.csv.gz"),
                      usecols=["week", "season_type", "posteam", "kicker_player_name",
                               "field_goal_result", "kick_distance", "extra_point_result"],
                      low_memory=False)
    pbp = pbp[pbp.season_type == "REG"]
    pts = defaultdict(float)
    for r in pbp.itertuples(index=False):
        if not isinstance(r.kicker_player_name, str):
            continue
        k = (r.kicker_player_name, TEAM_FIX.get(r.posteam, r.posteam), int(r.week))
        if isinstance(r.field_goal_result, str):
            if r.field_goal_result == "made":
                d = r.kick_distance or 0
                pts[k] += 5 if d >= 50 else 4 if d >= 40 else 3
            else:
                pts[k] -= 1
        elif isinstance(r.extra_point_result, str):
            pts[k] += 1 if r.extra_point_result == "good" else -1
    return pts

def wbucket(gw):
    if gw is None:
        return None
    if gw["indoor"]:
        return "indoor"
    w = gw["wind"]
    if w is None:
        return None
    return "wind15+" if w >= 15 else "wind10-15" if w >= 10 else "calm<10"

def main():
    GT = {Y: game_table(Y) for Y in YEARS}
    avg_imp = {Y: float(np.mean([v["implied"] for v in GT[Y].values() if v["implied"]]))
               for Y in YEARS}
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"),
                               encoding="utf-8"))

    for pos in ("QB", "WR", "TE", "RB"):
        S = []
        for Y in YEARS:
            if str(Y) not in clay_hist:
                continue
            for name, c in clay_hist[str(Y)].items():
                if c.get("pos") != pos or (c.get("pts") or 0) < POOL_MIN_PTS:
                    continue
                wrec = weekly_rec(name, pos)
                if wrec is None:
                    continue
                team = infer_team(wrec, Y)
                if team is None:
                    continue
                rows = sorted([(w["wk"], w["fpts"]) for w in
                               wrec.get("seasons", {}).get(str(Y), [])
                               if played(w) and isinstance(w.get("fpts"), (int, float))])
                W = 16 if Y <= 2020 else 17
                clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
                hist = []
                for wk, fpts in rows:
                    if hist:
                        g = len(hist)
                        base = (P * clay_pg + g * (sum(hist) / g)) / (P + g)
                        gw = GT[Y].get((team, wk))
                        b = wbucket(gw)
                        if b:
                            bv = base
                            if gw["implied"]:
                                e = VEGAS_ELAS[pos]
                                bv = base * min(1.35, max(0.65, 1 + e * (gw["implied"] - avg_imp[Y]) / avg_imp[Y] / 0.25 * 0.25))
                                bv = base * (1 + e * (gw["implied"] / avg_imp[Y] - 1))
                            S.append({"base": base, "bv": bv, "act": fpts, "b": b,
                                      "temp": gw["temp"]})
                    hist.append(fpts)
        print(f"\n=== {pos} ({len(S)} player-weeks) ===")
        for b in ("indoor", "calm<10", "wind10-15", "wind15+"):
            sub = [s for s in S if s["b"] == b]
            if len(sub) < 50:
                continue
            r1 = sum(s["act"] for s in sub) / sum(s["base"] for s in sub)
            r2 = sum(s["act"] for s in sub) / sum(s["bv"] for s in sub)
            print(f"  {b:10s}: raw {r1:.3f}   vegas-adj {r2:.3f}   (n={len(sub)})")
        cold = [s for s in S if s["temp"] is not None and s["temp"] <= 30]
        mild = [s for s in S if s["temp"] is not None and s["temp"] > 45]
        if len(cold) >= 80:
            rc = sum(s["act"] for s in cold) / sum(s["bv"] for s in cold)
            rm = sum(s["act"] for s in mild) / sum(s["bv"] for s in mild)
            print(f"  temp<=30F: vegas-adj {rc:.3f} (n={len(cold)})   temp>45F: {rm:.3f} (n={len(mild)})")

    # kickers vs their own season mean
    print("\n=== K (pbp-reconstructed, vs own season mean) ===")
    agg = defaultdict(lambda: defaultdict(list))   # bucket -> ratios
    fg_att = defaultdict(lambda: [0, 0])           # bucket -> [long att, games]
    for Y in YEARS:
        kw = kicker_weeks(Y)
        by_k = defaultdict(dict)
        for (nm, tmm, wk), p in kw.items():
            by_k[(nm, tmm)][wk] = p
        for (nm, tmm), wks in by_k.items():
            if len(wks) < 8:
                continue
            mean = sum(wks.values()) / len(wks)
            if mean < 4:
                continue
            for wk, p in wks.items():
                b = wbucket(GT[Y].get((tmm, wk)))
                if b:
                    agg[b]["r"].append(p - mean)
    for b in ("indoor", "calm<10", "wind10-15", "wind15+"):
        v = agg[b]["r"]
        if len(v) >= 50:
            print(f"  {b:10s}: mean pts vs own avg {np.mean(v):+.2f}  (n={len(v)})")

if __name__ == "__main__":
    main()
