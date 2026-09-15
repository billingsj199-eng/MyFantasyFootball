#!/usr/bin/env python3
"""
KICKER FG-DISTANCE LUCK backtest, 2019-2025 (Jack 2026-09-15: "backtest the
kicker FG-distance luck next"). TD-luck family logic applied to kickers.

Kicker weekly points reconstructed from nflverse pbp exactly like
backtest_k_dst_sigma.py (FG made 0-39 +3 / 40-49 +4 / 50+ +5, miss -1, XP
+1 / miss -1). Expected points per ATTEMPT = league make rate by distance
bucket (pooled 2018-25) x points if made - miss rate x 1; XP the same with
the league XP rate. luck = (xPts - actPts)/g season-to-date (weeks < W):
positive = missed more than the distances say -> should regress UP.

Base (no Clay K history exists): P=5 blend of the kicker's PRIOR-season
points/game (>= 8 games, else league K mean) toward season-to-date PPG, x
Vegas (K e=.50 on team implied vs league). LOYO by season.

GATE: does FG accuracy over expected persist YoY? (public wisdom: weakly)
TESTS: residual by luck tercile; additive + k * luck * g/(P+g); attempts
per game (opportunity, NOT luck) as a control - that one should be real.
Log: k_fgluck_backtest.log
"""
import numpy as np
import pandas as pd
import os
from collections import defaultdict
from backtest_target_area import implied_map, mse, loyo, LOAD_YEARS, YEARS, P, CACHE
# (stdout re-wrapped by backtest_target_area on import)

VEGAS_E_K = 0.50
FG_BINS = [0, 29, 39, 49, 54, 99]      # <30, 30-39, 40-49, 50-54, 55+
def fg_pts(d): return 5 if d >= 50 else (4 if d >= 40 else 3)

def load_year(Y):
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"),
                     usecols=["game_id", "season_type", "week", "posteam", "home_team", "away_team", "home_score",
                              "away_score", "spread_line", "total_line", "kicker_player_id", "kicker_player_name",
                              "field_goal_result", "kick_distance", "extra_point_result"], low_memory=False)
    df = df[(df.season_type == "REG") & df.posteam.notna()]
    lines = df.dropna(subset=["spread_line", "total_line"]).groupby("game_id").first()
    fg = df[df.field_goal_result.notna() & df.kicker_player_id.notna()].copy()
    fg["kind"] = "fg"; fg["made"] = (fg.field_goal_result == "made").astype(int)
    fg["dist"] = fg.kick_distance.fillna(40).astype(float)
    fg["yb"] = pd.cut(fg.dist, FG_BINS, right=True, labels=False).fillna(2).astype(int)
    fg["pts"] = np.where(fg.made == 1, fg.dist.map(fg_pts), -1)
    xp = df[df.extra_point_result.notna() & df.kicker_player_id.notna()].copy()
    xp["kind"] = "xp"; xp["made"] = (xp.extra_point_result == "good").astype(int)
    xp["dist"] = 33.0; xp["yb"] = -1
    xp["pts"] = np.where(xp.made == 1, 1, -1)
    t = pd.concat([fg, xp], ignore_index=True)
    t["season"] = Y; t["team"] = t.posteam
    return t[["season", "week", "team", "kicker_player_id", "kicker_player_name", "kind", "yb", "dist", "made", "pts"]], lines

def main():
    frames, lines_all = {}, {}
    for Y in LOAD_YEARS:
        frames[Y], lines_all[Y] = load_year(Y)
        print(f"  pbp {Y}: {int((frames[Y].kind=='fg').sum())} FG att, {int((frames[Y].kind=='xp').sum())} XP att")
    allt = pd.concat(frames.values(), ignore_index=True)
    rate = allt.groupby(["kind", "yb"]).made.mean()
    xp_rate = float(rate[("xp", -1)])
    labels = ["<30", "30-39", "40-49", "50-54", "55+"]
    print("  FG make rate: " + "  ".join(f"{labels[i]}:{rate.get(('fg', i), 0):.3f}" for i in range(5)) + f"  | XP {xp_rate:.3f}")
    # expected points per attempt
    def xpts(row):
        if row.kind == "xp": return xp_rate * 1 - (1 - xp_rate) * 1
        pm = rate[("fg", row.yb)]; return pm * fg_pts(row.dist) - (1 - pm) * 1
    allt["xpts"] = [xpts(r) for r in allt.itertuples(index=False)]
    allt["is_fg"] = (allt.kind == "fg").astype(int)
    pw = allt.groupby(["season", "kicker_player_id", "week"]).agg(pts=("pts", "sum"), xpts=("xpts", "sum"), att=("is_fg", "sum"),
                                                                 team=("team", "first"), name=("kicker_player_name", "first")).reset_index()
    # cumulative lookup + season totals
    look = {}; season = {}
    for (s, pid), grp in pw.sort_values("week").groupby(["season", "kicker_player_id"]):
        cum = {"pts": 0.0, "xpts": 0.0, "att": 0.0, "g": 0}; lst = []
        for r in grp.itertuples(index=False):
            cum["pts"] += r.pts; cum["xpts"] += r.xpts; cum["att"] += r.att; cum["g"] += 1
            lst.append((int(r.week), dict(cum), r.pts, r.team))
        look[(s, pid)] = lst; season[(s, pid)] = dict(cum)
    lg_ppg = {Y: pw[pw.season == Y].pts.sum() / pw[pw.season == Y].shape[0] for Y in LOAD_YEARS}
    print("  league K pts/game: " + " ".join(f"{Y}:{lg_ppg[Y]:.2f}" for Y in YEARS))

    # ---- GATE: accuracy over expected persistence
    print("\n=== GATE. kicker (pts - xPts)/g persistence YoY (>= 10 games both seasons) ===")
    a, b = [], []
    for (Y, pid), c in season.items():
        n = season.get((Y + 1, pid))
        if n and c["g"] >= 10 and n["g"] >= 10:
            a.append((c["pts"] - c["xpts"]) / c["g"]); b.append((n["pts"] - n["xpts"]) / n["g"])
    print(f"  YoY r = {np.corrcoef(a, b)[0,1]:+.2f} (n={len(a)}, sd {np.std(a):.2f} pts/g)")
    a, b = [], []
    for (Y, pid), lst in look.items():
        c8 = None
        for w, c, _, _ in lst:
            if w <= 8: c8 = c
        cE = lst[-1][1]
        if c8 and c8["g"] >= 5 and cE["g"] - c8["g"] >= 5:
            a.append((c8["pts"] - c8["xpts"]) / c8["g"]); b.append(((cE["pts"] - c8["pts"]) - (cE["xpts"] - c8["xpts"])) / (cE["g"] - c8["g"]))
    print(f"  early->late (wk<=8 vs 9+) r = {np.corrcoef(a, b)[0,1]:+.2f} (n={len(a)})")
    a, b = [], []
    for (Y, pid), c in season.items():
        n = season.get((Y + 1, pid))
        if n and c["g"] >= 10 and n["g"] >= 10: a.append(c["att"] / c["g"]); b.append(n["att"] / n["g"])
    print(f"  FG attempts/game YoY r = {np.corrcoef(a, b)[0,1]:+.2f} (opportunity - expected to persist somewhat)")

    # ---- samples
    S = defaultdict(list)
    for Y in YEARS:
        imp = implied_map(lines_all[Y]); avg = float(np.mean(list(imp.values())))
        for (s, pid), lst in look.items():
            if s != Y: continue
            prior = season.get((Y - 1, pid))
            prior_pg = (prior["pts"] / prior["g"]) if (prior and prior["g"] >= 8) else lg_ppg[Y - 1]
            hist = []
            for wk, cum_incl, pts, team in lst:
                li = imp.get((team, wk))
                if hist and li is not None:
                    g = len(hist); ppg = sum(hist) / g
                    base = (P * prior_pg + g * ppg) / (P + g)
                    veg = min(1.35, max(0.7, 1 + VEGAS_E_K * (li - avg) / avg))
                    # season-to-date BEFORE this week = cumulative minus this week's contribution
                    cb = {k: cum_incl[k] for k in ("pts", "xpts", "att", "g")}
                    cb["pts"] -= pts; cb["g"] -= 1
                    # xpts/att this week not separable from cum_incl here -> recompute via previous entry
                    S["year"].append(Y); S["act"].append(pts); S["g"].append(g); S["base"].append(base); S["veg"].append(veg)
                    S["key"].append((Y, pid, wk))
                hist.append(pts)
    # season-to-date luck / attempts from the entry BEFORE wk
    luck, attpg = [], []
    for (Y, pid, wk) in S["key"]:
        prev = None
        for w, c, _, _ in look[(Y, pid)]:
            if w < wk: prev = c
            else: break
        luck.append((prev["xpts"] - prev["pts"]) / prev["g"]); attpg.append(prev["att"] / prev["g"])
    S = {k: (np.array(v, float) if k != "key" else v) for k, v in S.items()}
    S["year"] = S["year"].astype(int); years = sorted(set(S["year"]))
    S["luck"] = np.array(luck); S["attpg"] = np.array(attpg)
    act, base = S["act"], S["base"]; shipped = base * S["veg"]; wreal = S["g"] / (P + S["g"])
    print(f"\n{len(act)} kicker-weeks 2019-25 | MSE prior-blend {mse(base, act):.4f} -> x Vegas {mse(shipped, act):.4f} | mean act/shipped {act.mean()/shipped.mean():.3f}")
    print(f"  luck mean {S['luck'].mean():+.3f} pts/g; by year: " + " ".join(f"{y}:{S['luck'][S['year']==y].mean():+.2f}" for y in years))

    def terc(x, label):
        q = np.quantile(x, [1/3, 2/3]); parts = []
        for lo, hi, lab in ((-np.inf, q[0], "low"), (q[0], q[1], "mid"), (q[1], np.inf, "high")):
            m = (x >= lo) & (x < hi)
            parts.append(f"{lab} {x[m].mean():+.2f}: {act[m].mean()/shipped[m].mean():.3f} (n={m.sum()})")
        print(f"  {label:22s} " + " | ".join(parts) + f"   corr(x, act-shipped) {np.corrcoef(x, act-shipped)[0,1]:+.3f}")
    print("\n=== 1. actual / shipped by tercile ===")
    terc(S["luck"], "FG/XP luck pts/g"); terc(S["attpg"], "FG attempts/g (opp.)")
    for lo, hi in ((1, 4), (5, 9), (10, 20)):
        m = (S["g"] >= lo) & (S["g"] <= hi); q = np.quantile(S["luck"][m], [1/3, 2/3])
        lo_m = m & (S["luck"] < q[0]); hi_m = m & (S["luck"] >= q[1])
        print(f"   games {lo}-{hi}: lucky tercile {act[lo_m].mean()/shipped[lo_m].mean():.3f}  unlucky tercile {act[hi_m].mean()/shipped[hi_m].mean():.3f} (n={m.sum()})")

    print("\n=== 2. LOYO sweeps (grid[0] = shipped) ===")
    grid = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]
    loyo(S, years, grid, lambda k: shipped + k * S["luck"] * wreal, "a) FG/XP luck: + k * luck * g/(P+g)")
    lc = S["luck"].copy()
    for y in years:
        m = S["year"] == y; lc[m] = S["luck"][m] - S["luck"][m].mean()
    loyo(S, years, grid, lambda k: shipped + k * lc * wreal, "b) luck centered per season")
    loyo(S, years, grid, lambda k: shipped * np.clip(1 + k * S["luck"] * wreal / np.maximum(base, 3.0), 0.6, 1.5), "c) multiplicative form")
    # note: k=1 in a) == replacing season-to-date PPG with xPts/g (pure opportunity) inside the blend.
    print("\n=== 3. how much should the realized K half be trusted at all? P sweep (no luck) and P + luck ===")
    # recover prior_pg and ppg from base: base = (P*prior + g*ppg)/(P+g); ppg = mean of hist = act history -> rebuild directly
    ppg_arr, prior_arr = [], []
    for idx, (Y, pid, wk) in enumerate(S["key"]):
        lst = look[(Y, pid)]
        prev = None
        for w, c, _, _ in lst:
            if w < wk: prev = c
            else: break
        ppg_arr.append(prev["pts"] / prev["g"])
        pr = season.get((Y - 1, pid)); prior_arr.append((pr["pts"] / pr["g"]) if (pr and pr["g"] >= 8) else lg_ppg[Y - 1])
    ppg_arr = np.array(ppg_arr); prior_arr = np.array(prior_arr)
    def blendP(Pv, k=0.0):
        b = (Pv * prior_arr + S["g"] * (ppg_arr + k * S["luck"])) / (Pv + S["g"])
        return b * S["veg"]
    print(f"  sanity: rebuilt P=5 base MSE {mse(blendP(5.0), act):.4f} vs shipped {mse(shipped, act):.4f}")
    loyo(S, years, [5, 3, 8, 12, 20, 40, 1000], lambda Pv: blendP(float(Pv)), "a) prior strength P (1000 ~ prior/league only)")
    loyo(S, years, [5, 8, 12, 20, 40], lambda Pv: blendP(float(Pv), 0.75), "b) P with luck k=.75 on the realized half")
    loyo(S, years, [0.0, 0.25, 0.5, 0.75, 1.0], lambda k: blendP(12.0, k), "c) luck k at P=12")
    # pure league-mean prior (ignore the kicker's own prior season) as the ultimate shrink target
    lgp = np.array([lg_ppg[Y - 1] for (Y, pid, wk) in S["key"]])
    loyo(S, years, [5, 12, 20, 40], lambda Pv: ((float(Pv) * lgp + S["g"] * ppg_arr) / (float(Pv) + S["g"])) * S["veg"], "d) league-mean prior instead of own prior season")

if __name__ == "__main__":
    main()
