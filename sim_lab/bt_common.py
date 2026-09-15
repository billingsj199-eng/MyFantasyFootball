#!/usr/bin/env python3
"""
Shared harness for the 2026-09-15 game-context backtests (rest / return /
garbage time / precipitation). Same grading base as every other Sim Lab layer:

  shipped = P=5 blend(Clay per-game, season-to-date PPG) x Vegas(pos e)
            x in-season FPA layer (e=.25, trust min(1,g/8), clamp [0.8,1.25])

iter_samples(POS) yields one dict per player-week 2019-25 (QB/RB/WR/TE from
clay_history, >= 40 Clay pts) with: year, name, pos, team, opp, pid (gsis),
wk, act, g, ppg, clay, base, veg, fpa, shipped, home (bool). Games table via
load_games(Y): per (season, team, week) -> date, kickoff ET hour, home, opp,
roof, weather string, implied totals.
"""
import numpy as np
import pandas as pd
import json, os, re
from collections import defaultdict
from backtest_sim_calibration import (played, weekly_rec, infer_team, POOL_MIN_PTS, OPP_ALIAS)
import backtest_sim_calibration as cal
from backtest_snap_defense import build_fpa
from backtest_target_area import implied_map, mse, loyo, LOAD_YEARS, YEARS, VEGAS_E, FPA_E, FPA_TRUST_G, P, CACHE
# (stdout re-wrapped by backtest_target_area on import)

VEG = dict(VEGAS_E); VEG["QB"] = 0.25
POS4 = ("QB", "RB", "WR", "TE")
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
def tm(t): return ALIAS.get(t, t)

def player_ids():
    p = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False,
                    usecols=["gsis_id", "display_name", "position", "rookie_season", "last_season"])
    p = p[p.position.isin(POS4) & p.gsis_id.notna()]
    by = defaultdict(list)
    for r in p.itertuples(index=False):
        by[(cal.norm(str(r.display_name)), r.position)].append(
            (r.gsis_id, r.rookie_season if pd.notna(r.rookie_season) else 0, r.last_season if pd.notna(r.last_season) else 9999))
    def resolve(name, pos, Y):
        c = [x for x in by.get((cal.norm(name), pos), []) if x[1] <= Y <= x[2] + 1]
        return c[0][0] if len(c) == 1 else None
    return resolve

_GAMES = {}
def load_games(Y):
    """{(team, wk): {date, hour, home, opp, roof, weather, implied, oppImplied, game_id}} + lines df."""
    if Y in _GAMES: return _GAMES[Y]
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"),
                     usecols=["game_id", "season_type", "week", "posteam", "home_team", "away_team", "home_score", "away_score",
                              "spread_line", "total_line", "game_date", "start_time", "roof", "weather"], low_memory=False)
    df = df[(df.season_type == "REG")]
    g = df.dropna(subset=["home_team"]).groupby("game_id").first()
    lines = df.dropna(subset=["spread_line", "total_line", "posteam"]).groupby("game_id").first()
    imp = implied_map(lines)
    out = {}
    for gid, r in g.iterrows():
        wk = int(r.week); h, a = tm(r.home_team), tm(r.away_team)
        hour = None
        if isinstance(r.start_time, str):
            m = re.search(r"(\d{1,2}):(\d{2})", r.start_time.split(",")[-1])
            if m: hour = int(m.group(1)) + int(m.group(2)) / 60.0
        base = {"date": pd.Timestamp(r.game_date), "hour": hour, "roof": r.roof, "weather": r.weather if isinstance(r.weather, str) else "", "game_id": gid}
        out[(h, wk)] = dict(base, home=True, opp=a, implied=imp.get((h, wk)), oppImplied=imp.get((a, wk)))
        out[(a, wk)] = dict(base, home=False, opp=h, implied=imp.get((a, wk)), oppImplied=imp.get((h, wk)))
    _GAMES[Y] = out
    return out

def iter_samples(POS=POS4, verbose=True):
    resolve = player_ids()
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    weekly_fpa, season_fpa, lg_fpa = build_fpa()
    out = []; miss = defaultdict(int)
    for Y in YEARS:
        if str(Y) not in clay_hist: continue
        games = load_games(Y)
        imps = [v["implied"] for v in games.values() if v["implied"] is not None]
        avg = float(np.mean(imps))
        W = 16 if Y <= 2020 else 17
        for name, c in clay_hist[str(Y)].items():
            pos = c.get("pos")
            if pos not in POS or (c.get("pts") or 0) < POOL_MIN_PTS: continue
            wrec = weekly_rec(name, pos)
            if wrec is None: miss["weekly"] += 1; continue
            team = infer_team(wrec, Y)
            if not team: miss["team"] += 1; continue
            pid = resolve(name, pos, Y)
            rows = sorted([(w["wk"], w["fpts"], OPP_ALIAS.get(w.get("opp"), w.get("opp"))) for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            hist = []
            for wk, fpts, opp in rows:
                gm = games.get((team, wk))
                if gm and gm["implied"] is not None and hist and opp:
                    g = len(hist); ppg = sum(hist) / g
                    base = (P * clay_pg + g * ppg) / (P + g)
                    veg = min(1.35, max(0.7, 1 + VEG[pos] * (gm["implied"] - avg) / avg))
                    cur = weekly_fpa.get((Y, opp, pos), {}); past = [w for w in cur if w < wk]
                    fpa = 1.0
                    if past and lg_fpa.get((Y, pos)):
                        ratio = min(1.25, max(0.8, (sum(cur[w] for w in past) / len(past)) / lg_fpa[(Y, pos)]))
                        fpa = 1 + FPA_E * (ratio - 1) * min(1, len(past) / FPA_TRUST_G)
                    out.append({"year": Y, "name": name, "pos": pos, "team": team, "opp": gm["opp"], "pid": pid, "wk": wk, "act": fpts,
                                "g": g, "ppg": ppg, "clay": clay_pg, "base": base, "veg": veg, "fpa": fpa, "shipped": base * veg * fpa,
                                "home": gm["home"]})
                hist.append(fpts)
        if verbose: print(f"  {Y}: samples so far {len(out)}")
    if verbose: print(f"  skipped: {dict(miss)}")
    return out

def to_arrays(S):
    keys = S[0].keys()
    A = {}
    for k in keys:
        v = [s[k] for s in S]
        if k in ("name", "pos", "team", "opp", "pid"): A[k] = np.array(v, dtype=object)
        elif k == "home": A[k] = np.array(v, dtype=bool)
        else: A[k] = np.array([np.nan if x is None else x for x in v], dtype=float)
    A["year"] = A["year"].astype(int)
    return A

def bucket_table(A, mask_sets, label):
    """print actual/shipped for each named mask, per position."""
    print(f"\n=== {label} ===")
    for nm, m in mask_sets:
        parts = []
        for p in POS4:
            mm = m & (A["pos"] == p)
            if mm.sum() < 40: parts.append(f"{p} — (n={mm.sum()})"); continue
            parts.append(f"{p} {A['act'][mm].mean()/A['shipped'][mm].mean():.3f} (n={mm.sum()})")
        allm = m
        parts.append(f"ALL {A['act'][allm].mean()/A['shipped'][allm].mean():.3f} (n={allm.sum()})" if allm.sum() else "ALL —")
        print(f"  {nm:26s} " + " | ".join(parts))

def loyo_flag(A, years, mask, label, grid=(1.0, 0.97, 0.94, 0.91, 1.03, 1.06), pos=None):
    """LOYO multiplier applied to flagged rows only (optionally within one position)."""
    S = {"year": A["year"], "act": A["act"]}
    if pos is not None:
        pm = A["pos"] == pos
        S = {"year": A["year"][pm], "act": A["act"][pm]}; ship = A["shipped"][pm]; mk = mask[pm]
    else:
        ship = A["shipped"]; mk = mask
    if mk.sum() < 60:
        print(f"  {label}: too few flagged rows ({mk.sum()})"); return None
    return loyo(S, years, list(grid), lambda m: np.where(mk, ship * m, ship), f"{label} (flagged n={mk.sum()})")
