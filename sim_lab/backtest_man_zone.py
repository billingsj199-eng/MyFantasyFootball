#!/usr/bin/env python3
"""
MAN/ZONE MATCHUP layer backtest, 2018-2025.

Per-play coverage labels (participation defense_man_zone_type, ~half of
dropbacks labeled) joined to pbp targets -> per-player man/zone splits and
per-defense man rates.

GATE 1 (decides everything): do a player's man-vs-zone splits PERSIST
year-over-year? If corr ~ 0 the matchup product is unshippable.
GATE 2: are defense man rates stable in-season (early -> late)?
LAYER TEST: prior-years man-zone differential x opponent man-rate deviation
as a weekly multiplier on the P=5 base, MSE swept.
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
YEARS = range(2018, 2026)
TEAM_FIX = {"WSH": "WAS", "LA": "LAR", "OAK": "LV", "SD": "LAC",
            "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}

def id_name_map():
    """GSIS id -> full name, from 2023-25 participation alignment."""
    m = {}
    for y in (2023, 2024, 2025):
        df = pd.read_parquet(os.path.join(CACHE, f"pbp_participation_{y}.parquet"),
                             columns=["offense_players", "offense_names"])
        for r in df.itertuples(index=False):
            if not isinstance(r.offense_names, str) or not r.offense_names:
                continue
            ids = (r.offense_players or "").split(";")
            nms = r.offense_names.split(";")
            if len(ids) != len(nms):
                continue
            for i, n in zip(ids, nms):
                if i and i not in m:
                    m[i] = n
    return m

def build_targets(year):
    """target-level rows: (def_team, week, receiver_id, cov(M/Z), halfppr_pts)"""
    pbp = pd.read_csv(os.path.join(CACHE, f"play_by_play_{year}.csv.gz"),
                      usecols=["game_id", "play_id", "week", "season_type", "defteam",
                               "receiver_player_id", "complete_pass", "receiving_yards",
                               "pass_touchdown", "interception", "fumble_lost"],
                      low_memory=False)
    pbp = pbp[(pbp.season_type == "REG") & pbp.receiver_player_id.notna()]
    part = pd.read_parquet(os.path.join(CACHE, f"pbp_participation_{year}.parquet"),
                           columns=["nflverse_game_id", "play_id", "defense_man_zone_type"])
    part = part[part.defense_man_zone_type.isin(["MAN_COVERAGE", "ZONE_COVERAGE"])]
    m = part.merge(pbp, left_on=["nflverse_game_id", "play_id"],
                   right_on=["game_id", "play_id"], how="inner")
    rows = []
    for r in m.itertuples(index=False):
        pts = 0.0
        if r.complete_pass == 1:
            pts += 0.5 + 0.1 * (r.receiving_yards or 0) + 6 * (r.pass_touchdown or 0)
        if r.fumble_lost == 1:
            pts -= 2
        rows.append((TEAM_FIX.get(r.defteam, r.defteam), int(r.week),
                     r.receiver_player_id, r.defense_man_zone_type[0], pts))
    return rows

def main():
    idn = id_name_map()
    # per player-season splits + per defense-season/week man rates
    splits = defaultdict(lambda: [0, 0.0, 0, 0.0])   # (Y,id) -> [tM, pM, tZ, pZ]
    dweek = defaultdict(lambda: [0, 0])              # (Y,def,wk) -> [man, labeled]
    for Y in YEARS:
        try:
            rows = build_targets(Y)
        except Exception as e:
            print(f"  {Y} skipped ({e})")
            continue
        for d, wk, rid, cov, pts in rows:
            s = splits[(Y, rid)]
            if cov == "M":
                s[0] += 1; s[1] += pts
            else:
                s[2] += 1; s[3] += pts
            dw = dweek[(Y, d, wk)]
            dw[1] += 1
            if cov == "M":
                dw[0] += 1
        print(f"  {Y}: {len(rows)} labeled targets")

    # GATE 1: YoY persistence of player man-zone differential
    MIN_T = 25
    diffs = {}
    for (Y, rid), (tm_, pm, tz, pz) in splits.items():
        if tm_ >= MIN_T and tz >= MIN_T:
            diffs[(Y, rid)] = pm / tm_ - pz / tz
    xs, ys = [], []
    for (Y, rid), d in diffs.items():
        if (Y + 1, rid) in diffs:
            xs.append(d); ys.append(diffs[(Y + 1, rid)])
    xs, ys = np.array(xs), np.array(ys)
    print(f"\n=== GATE 1: player man-zone diff persistence ===")
    print(f"  {len(diffs)} qualifying player-seasons (>= {MIN_T} tgts each side)")
    print(f"  {len(xs)} consecutive pairs: corr(diff_Y, diff_Y+1) = {np.corrcoef(xs, ys)[0,1]:+.3f}")
    print(f"  diff spread: sd {np.array(list(diffs.values())).std():.3f} half-PPR pts/target")
    lo = xs <= np.percentile(xs, 25); hi = xs >= np.percentile(xs, 75)
    print(f"  man-beaters (Y diff {xs[hi].mean():+.3f}) -> next yr {ys[hi].mean():+.3f}")
    print(f"  zone-beaters (Y diff {xs[lo].mean():+.3f}) -> next yr {ys[lo].mean():+.3f}")

    # GATE 2: defense man-rate stability (early wks 1-8 vs late 9+ same season)
    dse = defaultdict(lambda: [0, 0]); dsl = defaultdict(lambda: [0, 0])
    for (Y, d, wk), (mn, tot) in dweek.items():
        tgt = dse if wk <= 8 else dsl
        tgt[(Y, d)][0] += mn; tgt[(Y, d)][1] += tot
    xs2, ys2 = [], []
    for k in dse:
        if k in dsl and dse[k][1] >= 80 and dsl[k][1] >= 80:
            xs2.append(dse[k][0] / dse[k][1]); ys2.append(dsl[k][0] / dsl[k][1])
    xs2, ys2 = np.array(xs2), np.array(ys2)
    print(f"\n=== GATE 2: defense man-rate stability (wk1-8 -> wk9+, same season) ===")
    print(f"  {len(xs2)} defense-seasons: corr = {np.corrcoef(xs2, ys2)[0,1]:+.3f}   "
          f"rate spread sd {xs2.std():.3f} (mean {xs2.mean():.3f})")
    # and YoY
    dsy = defaultdict(lambda: [0, 0])
    for (Y, d, wk), (mn, tot) in dweek.items():
        dsy[(Y, d)][0] += mn; dsy[(Y, d)][1] += tot
    xs3, ys3 = [], []
    for (Y, d) in dsy:
        if (Y + 1, d) in dsy and dsy[(Y, d)][1] >= 150 and dsy[(Y + 1, d)][1] >= 150:
            xs3.append(dsy[(Y, d)][0] / dsy[(Y, d)][1])
            ys3.append(dsy[(Y + 1, d)][0] / dsy[(Y + 1, d)][1])
    print(f"  YoY: {len(xs3)} pairs, corr = {np.corrcoef(np.array(xs3), np.array(ys3))[0,1]:+.3f}")

    # LAYER TEST (only meaningful if Gate 1 shows life): weekly WR samples,
    # x = shrunk prior-years diff x (opp man rate to date - league avg)
    print("\n=== LAYER TEST: WR weekly mult 1 + e*(priorDiff_shrunk x manRateDev x 10) ===")
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    # name -> id via idn reverse (norm match)
    idn_norm = {}
    for i, n in idn.items():
        idn_norm.setdefault(cal.norm(n), i)
    K = 60  # shrink targets
    S = []
    lg_man = {}
    for Y in range(2021, 2026):
        tots = [(mn, tot) for (yy, d, wk), (mn, tot) in dweek.items() if yy == Y]
        lg_man[Y] = sum(m for m, _ in tots) / max(1, sum(t for _, t in tots))
    for Y in range(2021, 2026):
        if str(Y) not in clay_hist:
            continue
        for name, c in clay_hist[str(Y)].items():
            if c.get("pos") != "WR" or (c.get("pts") or 0) < POOL_MIN_PTS:
                continue
            rid = idn_norm.get(cal.norm(name))
            if rid is None:
                continue
            # pooled prior 3 seasons
            tm_ = pm = tz = pz = 0
            for yy in (Y - 1, Y - 2, Y - 3):
                s = splits.get((yy, rid))
                if s:
                    tm_ += s[0]; pm += s[1]; tz += s[2]; pz += s[3]
            if tm_ < 20 or tz < 20:
                continue
            diff = pm / tm_ - pz / tz
            neff = min(tm_, tz)
            diff_shrunk = diff * neff / (neff + K)
            wrec = weekly_rec(name, "WR")
            if wrec is None:
                continue
            rows = sorted([(w["wk"], w["fpts"], OPP_ALIAS.get(w.get("opp"), w.get("opp")))
                           for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / 17
            hist = []
            for wk, fpts, opp in rows:
                if hist and opp:
                    g = len(hist)
                    base = (P * clay_pg + g * (sum(hist) / g)) / (P + g)
                    # opp man rate to date (weeks < wk)
                    mn = tot = 0
                    for w in range(1, wk):
                        dw = dweek.get((Y, opp, w))
                        if dw:
                            mn += dw[0]; tot += dw[1]
                    if tot >= 40:
                        dev = mn / tot - lg_man[Y]
                        S.append({"base": base, "act": fpts, "x": diff_shrunk * dev * 10})
                hist.append(fpts)
    if not S:
        print("  no samples")
        return
    base = np.array([s["base"] for s in S]); act = np.array([s["act"] for s in S])
    x = np.array([s["x"] for s in S])
    print(f"  {len(S)} WR player-weeks; x sd = {x.std():.4f}")
    line = "  MSE:"
    best = None
    for e in (0.0, 0.5, 1.0, 2.0, 4.0):
        v = float(np.mean((base * np.clip(1 + e * x, 0.8, 1.2) - act) ** 2))
        line += f"  e{e:.1f} {v:.3f}"
        if best is None or v < best[1]:
            best = (e, v)
    print(line + f"  <- best e={best[0]}")
    for lo_, hi_ in [(-1, -0.02), (-0.02, 0.02), (0.02, 1)]:
        m = (x >= lo_) & (x < hi_)
        if m.sum() < 100:
            continue
        print(f"  x {lo_:+.2f}..{hi_:+.2f}: act/base {act[m].sum()/base[m].sum():.3f} (n={m.sum()})")

if __name__ == "__main__":
    main()
