#!/usr/bin/env python3
"""
RECEIVER YARDAGE / CATCH LUCK backtest, 2019-2025 (Jack 2026-09-15: "continue
adding" - item 4). TD luck catches the scores; this asks whether the YARDS and
CATCHES a receiver has banked relative to his target depths also regress.

Per target (nflverse pbp): xYds = league mean yards gained for the air-yards
bucket (<0, 0-4, 5-9, 10-14, 15-19, 20-29, 30+; pooled 2018-25); xRec = league
catch rate for the bucket. Season-to-date (weeks < W):
  yluck = (xYds - yds)/g    (+ = under-produced on his depths -> due up)
  rluck = (xRec - rec)/g
Points: half-PPR 0.1/yd, 0.5/rec. Base = P=5 x Vegas .25 x in-season FPA,
PLUS the shipped WR/TE TD-luck term (k=1.0) so long TDs are not credited twice.
GATE: do yards-over-expected per target and catch rate over expected persist
YoY? (YAC / hands may be real skill - if so only the residual regresses.)
LOYO sweeps: yards luck, catch luck, combined; per position.
Log: yds_luck_backtest.log
"""
import numpy as np
import pandas as pd
import json, os
from collections import defaultdict
from backtest_sim_calibration import (played, weekly_rec, infer_team, POOL_MIN_PTS, OPP_ALIAS)
import backtest_sim_calibration as cal
from backtest_snap_defense import build_fpa
from backtest_target_area import (load_players, resolve_gsis, implied_map, mse, loyo,
                                  LOAD_YEARS, YEARS, VEGAS_E, FPA_E, FPA_TRUST_G, P, CACHE)
# (stdout re-wrapped by backtest_target_area on import)

POS_TEST = ("WR", "TE")
AY_BINS = [-100, -0.01, 4.99, 9.99, 14.99, 19.99, 29.99, 200]
YL_BINS = [0, 5, 10, 20, 40, 100]
XTD_NONEZ = [0.264, 0.213, 0.080, 0.030, 0.007]
XTD_EZ    = [0.501, 0.384, 0.330, 0.271, 0.232]
K_TD = 1.0

def load_year(Y):
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"),
                     usecols=["game_id", "season_type", "week", "posteam", "home_team", "away_team", "home_score", "away_score",
                              "spread_line", "total_line", "pass_attempt", "sack", "receiver_player_id", "air_yards",
                              "yardline_100", "complete_pass", "yards_gained", "pass_touchdown"], low_memory=False)
    df = df[(df.season_type == "REG") & df.posteam.notna()]
    lines = df.dropna(subset=["spread_line", "total_line"]).groupby("game_id").first()
    t = df[(df.pass_attempt == 1) & (df.sack != 1) & df.receiver_player_id.notna() & df.air_yards.notna()].copy()
    t["pid"] = t.receiver_player_id
    t["ab"] = pd.cut(t.air_yards, AY_BINS, right=True, labels=False).astype(int)
    comp = t.complete_pass.fillna(0)
    t["rec"] = comp; t["yds"] = np.where(comp == 1, t.yards_gained.fillna(0), 0.0)
    t["td"] = t.pass_touchdown.fillna(0)
    yl = t.yardline_100.fillna(50); yb = pd.cut(yl, YL_BINS, right=True, labels=False).fillna(4).astype(int)
    ez = t.air_yards >= yl
    t["xtd"] = np.where(ez, np.array(XTD_EZ)[yb], np.array(XTD_NONEZ)[yb])
    t["season"] = Y
    return t[["season", "week", "pid", "ab", "rec", "yds", "td", "xtd"]], lines

def main():
    by_norm = load_players()
    frames, lines_all = {}, {}
    for Y in LOAD_YEARS:
        frames[Y], lines_all[Y] = load_year(Y); print(f"  pbp {Y}: {len(frames[Y])} targets")
    allt = pd.concat(frames.values(), ignore_index=True)
    xy = allt.groupby("ab").yds.mean(); xr = allt.groupby("ab").rec.mean()
    labels = ["<0", "0-4", "5-9", "10-14", "15-19", "20-29", "30+"]
    print("  xYds/target by air yards: " + "  ".join(f"{labels[i]}:{xy[i]:.1f}" for i in range(7)))
    print("  catch rate by air yards : " + "  ".join(f"{labels[i]}:{xr[i]:.2f}" for i in range(7)))
    allt["xyds"] = allt.ab.map(xy); allt["xrec"] = allt.ab.map(xr)
    pw = allt.groupby(["season", "pid", "week"]).agg(n=("rec", "count"), rec=("rec", "sum"), xrec=("xrec", "sum"), yds=("yds", "sum"),
                                                    xyds=("xyds", "sum"), td=("td", "sum"), xtd=("xtd", "sum")).reset_index()
    look = {}; season = {}
    for (s, pid), grp in pw.sort_values("week").groupby(["season", "pid"]):
        cum = {k: 0.0 for k in ("n", "rec", "xrec", "yds", "xyds", "td", "xtd")}; cum["g"] = 0; lst = []
        for r in grp.itertuples(index=False):
            for k in ("n", "rec", "xrec", "yds", "xyds", "td", "xtd"): cum[k] += getattr(r, k)
            cum["g"] += 1; lst.append((int(r.week), dict(cum)))
        look[(s, pid)] = lst; season[(s, pid)] = dict(cum)
    def before(lst, wk):
        best = None
        for w, c in lst or []:
            if w < wk: best = c
            else: break
        return best

    print("\n=== GATE. persistence YoY (>= 60 targets both seasons) ===")
    for lab, f in (("yards over expected / target", lambda c: (c["yds"] - c["xyds"]) / c["n"]),
                   ("catch rate over expected", lambda c: (c["rec"] - c["xrec"]) / c["n"]),
                   ("TD over expected / target", lambda c: (c["td"] - c["xtd"]) / c["n"])):
        a, b = [], []
        for (Y, pid), c in season.items():
            nx = season.get((Y + 1, pid))
            if nx and c["n"] >= 60 and nx["n"] >= 60: a.append(f(c)); b.append(f(nx))
        print(f"  {lab:30s} r={np.corrcoef(a,b)[0,1]:+.2f} (n={len(a)}, sd {np.std(a):.3f})")

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
            rows = sorted([(w["wk"], w["fpts"], OPP_ALIAS.get(w.get("opp"), w.get("opp"))) for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            hist = []
            for wk, fpts, opp in rows:
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
                    if not cm or cm["n"] < 1: hist.append(fpts); miss["notgt"] += 1; continue
                    S["year"].append(Y); S["pos"].append(pos); S["act"].append(fpts); S["g"].append(g)
                    S["base"].append(base); S["chain"].append(veg * fpa)
                    S["tdl"].append((cm["xtd"] - cm["td"]) / cm["g"])
                    S["yl"].append((cm["xyds"] - cm["yds"]) / cm["g"]); S["rl"].append((cm["xrec"] - cm["rec"]) / cm["g"])
                    S["ntg"].append(cm["n"])
                hist.append(fpts)
        print(f"  {Y}: samples so far {len(S['act'])}")
    print(f"  skipped: {dict(miss)}")
    S = {k: (np.array(v) if k == "pos" else np.array(v, float)) for k, v in S.items()}
    S["year"] = S["year"].astype(int); years = sorted(set(S["year"]))
    act, pos = S["act"], S["pos"]; wreal = S["g"] / (P + S["g"])
    ship0 = S["base"] * S["chain"]
    shipped = ship0 + K_TD * 6.0 * S["tdl"] * wreal          # the live WR/TE TD-luck layer
    ypts = 0.1 * S["yl"]; rpts = 0.5 * S["rl"]
    print(f"\n{len(act)} WR/TE player-weeks | MSE base x chain {mse(ship0, act):.4f} -> + TD luck (shipped) {mse(shipped, act):.4f}")
    print(f"  yards luck mean {S['yl'].mean():+.2f} yds/g (sd {S['yl'].std():.1f}) | catch luck mean {S['rl'].mean():+.3f} rec/g (sd {S['rl'].std():.2f}) | corr(yards luck, TD luck) {np.corrcoef(S['yl'], S['tdl'])[0,1]:+.2f}")

    def terc(x, label, mask):
        q = np.quantile(x[mask], [1/3, 2/3]); parts = []
        for lo, hi, lab in ((-np.inf, q[0], "low"), (q[0], q[1], "mid"), (q[1], np.inf, "high")):
            m = mask & (x >= lo) & (x < hi); parts.append(f"{lab} {x[m].mean():+.2f}: {act[m].mean()/shipped[m].mean():.3f} (n={m.sum()})")
        print(f"  {label:22s} " + " | ".join(parts) + f"   corr(x, act-shipped) {np.corrcoef(x[mask], act[mask]-shipped[mask])[0,1]:+.3f}")
    print("\n=== 1. actual / shipped (TD luck already in) by tercile ===")
    for p in POS_TEST:
        m = pos == p
        terc(S["yl"], f"{p} yards luck yds/g", m); terc(S["rl"], f"{p} catch luck rec/g", m)

    print("\n=== 2. LOYO on top of the shipped TD-luck base (grid[0] = shipped) ===")
    grid = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]
    loyo(S, years, grid, lambda k: shipped + k * ypts * wreal, "a) yards luck: + k * 0.1 * (xYds - yds)/g * g/(P+g)")
    loyo(S, years, grid, lambda k: shipped + k * rpts * wreal, "b) catch luck: + k * 0.5 * (xRec - rec)/g * g/(P+g)")
    loyo(S, years, grid, lambda k: shipped + k * (ypts + rpts) * wreal, "c) yards + catches combined")
    for p in POS_TEST:
        m = pos == p; Sp = {k: v[m] for k, v in S.items()}; shp = shipped[m]; yp = ypts[m]; rp = rpts[m]; wr = wreal[m]
        loyo(Sp, years, grid, lambda k, shp=shp, yp=yp, wr=wr: shp + k * yp * wr, f"   {p} yards luck")
        loyo(Sp, years, grid, lambda k, shp=shp, rp=rp, wr=wr: shp + k * rp * wr, f"   {p} catch luck")
    # centered control
    yc = ypts.copy()
    for y in years:
        for p in POS_TEST:
            m = (S["year"] == y) & (pos == p); yc[m] = ypts[m] - ypts[m].mean()
    loyo(S, years, grid, lambda k: shipped + k * yc * wreal, "d) yards luck centered per season x position")

if __name__ == "__main__":
    main()
