#!/usr/bin/env python3
"""
ROUTE-PARTICIPATION TREND backtest, 2023-2025 (participation carries full
names those seasons — the same path the live 2026 layer would use).

Route participation ~ share of team dropbacks the player was on the field
for (nflverse participation offense_names joined to pbp qb_dropback plays).
Same trend construction as the shipped snap layer: weighted last-3 recorded
games (0.5/0.3/0.2) vs season-to-date average, staleness guard.

The question that decides shipping: does the route trend add anything ON
TOP of the shipped snapMult (route %% and snap %% correlate heavily)?
  A base                 B base*snapMult(shipped 1.0%%/pt)
  C base*routeMult(e)    D base*snapMult*routeMult(e)  <- the increment
"""
import numpy as np
import pandas as pd
import json, os
from collections import defaultdict
from backtest_sim_calibration import (played, weekly_rec, infer_team,
                                      POOL_MIN_PTS, OPP_ALIAS)
import backtest_sim_calibration as cal
from backtest_snap_defense import load_snaps, snap_mult

CACHE = r"E:\MyFantasyFootball\pbp_cache"
P = 5
YEARS = (2023, 2024, 2025)
W3 = [0.5, 0.3, 0.2]
TEAM_FIX = {"WSH": "WAS", "LA": "LAR", "OAK": "LV", "SD": "LAC",
            "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}

def build_routes(year):
    """(norm, team, wk) -> route participation %% of team dropbacks."""
    pbp = pd.read_csv(os.path.join(CACHE, f"play_by_play_{year}.csv.gz"),
                      usecols=["game_id", "play_id", "week", "posteam",
                               "qb_dropback", "season_type"], low_memory=False)
    pbp = pbp[(pbp.season_type == "REG") & (pbp.qb_dropback == 1)]
    part = pd.read_parquet(
        os.path.join(CACHE, f"pbp_participation_{year}.parquet"),
        columns=["nflverse_game_id", "play_id", "offense_names"])
    m = part.merge(pbp, left_on=["nflverse_game_id", "play_id"],
                   right_on=["game_id", "play_id"], how="inner")
    pres = defaultdict(int)          # (norm, team, wk) -> plays on field
    team_db = defaultdict(int)       # (team, wk) -> dropbacks
    for r in m.itertuples(index=False):
        if not isinstance(r.offense_names, str) or not r.offense_names:
            continue
        tm = TEAM_FIX.get(r.posteam, r.posteam)
        wk = int(r.week)
        team_db[(tm, wk)] += 1
        for nm in r.offense_names.split(";"):
            pres[(cal.norm(nm), tm, wk)] += 1
    out = {}
    for (nm, tm, wk), c in pres.items():
        db = team_db[(tm, wk)]
        if db >= 10:
            out[(nm, tm, wk)] = 100.0 * c / db
    return out

def trend(series, wk):
    """shipped-snap-style trend: (delta pct-pts, ) or None."""
    past = sorted((w for w in series if w < wk), reverse=True)
    if len(past) < 2 or past[0] < wk - 3:
        return None
    recent = wsum = 0.0
    for i, w in enumerate(past[:3]):
        recent += series[w] * W3[i]
        wsum += W3[i]
    recent /= wsum
    avg = sum(series[w] for w in past) / len(past)
    return recent - avg

def main():
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"),
                               encoding="utf-8"))
    S = []
    for Y in YEARS:
        if str(Y) not in clay_hist:
            continue
        routes = build_routes(Y)
        snaps_all = load_snaps(Y)
        # per-player weekly route series
        for name, c in clay_hist[str(Y)].items():
            pos = c.get("pos")
            if pos not in ("RB", "WR", "TE") or (c.get("pts") or 0) < POOL_MIN_PTS:
                continue
            wrec = weekly_rec(name, pos)
            if wrec is None:
                continue
            team = infer_team(wrec, Y)
            if team is None:
                continue
            nrm = cal.norm(name)
            rser = {wk: v for (nm, tm, wk), v in routes.items()
                    if nm == nrm and tm == team}
            if not rser:
                continue
            sn = snaps_all.get(nrm)
            rows = sorted([(w["wk"], w["fpts"]) for w in
                           wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            W = 17
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            hist = []
            for wk, fpts in rows:
                if hist:
                    g = len(hist)
                    base = (P * clay_pg + g * (sum(hist) / g)) / (P + g)
                    smp = {"pos": pos, "base": base, "act": fpts}
                    rd = trend(rser, wk)
                    if rd is not None:
                        smp["rdelta"] = rd
                    if sn:
                        r = snap_mult(sn, wk)
                        if r:
                            smp["smult"], smp["sdelta"] = r
                    S.append(smp)
                hist.append(fpts)
        print(f"  {Y} done ({len(S)} cumulative samples)")

    sub = [s for s in S if "rdelta" in s and "smult" in s]
    print(f"\n{len(sub)} player-weeks with BOTH route + snap trends\n")
    base = np.array([s["base"] for s in sub])
    act = np.array([s["act"] for s in sub])
    sm = np.array([s["smult"] for s in sub])
    rd = np.array([s["rdelta"] for s in sub])
    sd = np.array([s["sdelta"] for s in sub])
    print(f"corr(route delta, snap delta) = {np.corrcoef(rd, sd)[0,1]:.3f}")

    def mse(pred):
        return float(np.mean((pred - act) ** 2))
    print(f"\nA base only:          {mse(base):.3f}")
    print(f"B base*snap (shipped): {mse(base*sm):.3f}")
    for tag, arr in (("C base*route(e)      ", base), ("D base*snap*route(e) ", base * sm)):
        line = tag
        best = None
        for e in (0.0, 0.25, 0.5, 0.75, 1.0, 1.5):
            mult = np.clip(1 + e * rd / 100, 0.75, 1.30)
            v = mse(arr * mult)
            line += f"  e{e:.2f} {v:.3f}"
            if best is None or v < best[1]:
                best = (e, v)
        print(line + f"  <- best e={best[0]}")

    # dose-response of route delta AFTER snap adjustment
    print("\ndose-response: actual/(base*snap) by route-delta bucket")
    resid_base = base * sm
    for lo, hi in [(-40, -12), (-12, -6), (-6, -2), (-2, 2), (2, 6), (6, 12), (12, 40)]:
        m = (rd >= lo) & (rd < hi)
        if m.sum() < 150:
            continue
        print(f"  route delta {rd[m].mean():+6.1f}: {act[m].sum()/resid_base[m].sum():.3f} (n={m.sum()})")

    # per-position D test at the pooled best elasticity
    print("\nper-position increment (D vs B), e swept per pos:")
    for pos in ("RB", "WR", "TE"):
        pm = np.array([s["pos"] == pos for s in sub])
        if pm.sum() < 300:
            continue
        b = mse((base * sm)[None][0][pm] * 1) if False else float(np.mean(((base*sm)[pm] - act[pm])**2))
        line = f"  {pos}: B {b:.3f}"
        best = None
        for e in (0.0, 0.25, 0.5, 0.75, 1.0, 1.5):
            mult = np.clip(1 + e * rd[pm] / 100, 0.75, 1.30)
            v = float(np.mean(((base*sm)[pm] * mult - act[pm]) ** 2))
            line += f"  e{e:.2f} {v:.3f}"
            if best is None or v < best[1]:
                best = (e, v)
        print(line + f"  <- best e={best[0]}")

if __name__ == "__main__":
    main()
