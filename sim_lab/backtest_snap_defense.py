#!/usr/bin/env python3
"""
Backtest the last two in-season layers, 2019-2025:

1. SNAP TREND (engine snapMult): weighted recent snap share (last 3 recorded
   games before week W, 0.5/0.3/0.2) vs season-to-date average ->
   1 + 0.8%/snap-pt, clamp [0.75, 1.30], RB/WR/TE. Replayed exactly from
   nflverse historical snap counts; graded on NEXT-WEEK points vs the P=5
   blend base, plus the empirical slope per snap-point.

2. POSITIONAL DEFENSE ADJUSTMENT: the engine's preseason layer uses Clay
   unit grades (no historical archive exists), so the FUNCTION is tested
   with what was knowable at the time:
     A "preseason-style":  opponent's PRIOR-SEASON fantasy points allowed
        to the position (dev vs league avg) -> mult 1 + eA*dev, capped +-8%
        like the engine. If eA ~ 0 helps, preseason defense identity carries
        signal; if not, the +-8% cap is generous.
     B "in-season" (= the JS Weekly jsOppMult design): current-season FPA
        through W-1, trust min(1, defGames/8), ratio clamp [0.8, 1.25].
        Sweep the elasticity on top.
   FPA is computed from the FULL weekly DB (active+retired, all players
   with the position, summed per defense per week).
"""
import numpy as np
import pandas as pd
import json, os
from collections import defaultdict
from backtest_sim_calibration import (played, weekly_rec, infer_team,
                                      POS_KEEP, POOL_MIN_PTS, OPP_ALIAS, WEEKLY)
import backtest_sim_calibration as cal

CACHE = r"E:\MyFantasyFootball\pbp_cache"
P = 5
SNAP_W = [0.5, 0.3, 0.2]

def load_snaps(year):
    df = pd.read_parquet(os.path.join(CACHE, f"snap_counts_{year}.parquet"),
                         columns=["player", "week", "game_type", "offense_pct"])
    df = df[df.game_type == "REG"].dropna(subset=["offense_pct"])
    out = {}
    for _, r in df.iterrows():
        out.setdefault(cal.norm(r.player), {})[int(r.week)] = float(r.offense_pct) * 100
    return out

def snap_mult(snaps, wk):
    past = sorted((w for w in snaps if w < wk), reverse=True)
    if len(past) < 2 or past[0] < wk - 3:
        return None
    recent = wsum = 0.0
    for i, w in enumerate(past[:3]):
        recent += snaps[w] * SNAP_W[i]
        wsum += SNAP_W[i]
    recent /= wsum
    avg = sum(snaps[w] for w in past) / len(past)
    return min(1.30, max(0.75, 1 + 0.8 * (recent - avg) / 100)), recent - avg

def build_fpa():
    """fpa[Y][def][pos] = mean pooled pts allowed per game; also per-week map."""
    weekly_fpa = defaultdict(lambda: defaultdict(float))  # (Y, def, pos, wk) sums
    for recs in WEEKLY.values():
        for rec in recs:
            pos = rec.get("pos")
            if pos not in POS_KEEP:
                continue
            for y, rows in rec.get("seasons", {}).items():
                Y = int(y)
                if Y < 2018:
                    continue
                for w in rows:
                    if not played(w) or not w.get("opp"):
                        continue
                    d = OPP_ALIAS.get(w["opp"], w["opp"])
                    weekly_fpa[(Y, d, pos)][int(w["wk"])] += w["fpts"] or 0
    season_fpa = {}   # (Y, def, pos) -> per-game mean
    for (Y, d, pos), wks in weekly_fpa.items():
        if len(wks) >= 10:
            season_fpa[(Y, d, pos)] = sum(wks.values()) / len(wks)
    lg = {}
    for (Y, d, pos), v in season_fpa.items():
        lg.setdefault((Y, pos), []).append(v)
    lg = {k: float(np.mean(v)) for k, v in lg.items()}
    return weekly_fpa, season_fpa, lg

def main():
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    weekly_fpa, season_fpa, lg = build_fpa()
    S = []   # samples: dicts
    for Y in range(2019, 2026):
        if str(Y) not in clay_hist:
            continue
        snaps_all = load_snaps(Y)
        W = 16 if Y <= 2020 else 17
        for name, c in clay_hist[str(Y)].items():
            pos = c.get("pos")
            if pos not in POS_KEEP or (c.get("pts") or 0) < POOL_MIN_PTS:
                continue
            wrec = weekly_rec(name, pos)
            if wrec is None:
                continue
            rows = sorted([(w["wk"], w["fpts"], OPP_ALIAS.get(w.get("opp"), w.get("opp")))
                           for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            sn = snaps_all.get(cal.norm(name))
            hist = []
            for wk, fpts, opp in rows:
                if hist and opp:
                    g = len(hist)
                    base = (P * clay_pg + g * (sum(hist) / g)) / (P + g)
                    smp = {"pos": pos, "base": base, "act": fpts}
                    if sn and pos != "QB":
                        r = snap_mult(sn, wk)
                        if r:
                            smp["smult"], smp["sdelta"] = r
                    prev = season_fpa.get((Y - 1, opp, pos))
                    lgprev = lg.get((Y - 1, pos))
                    if prev and lgprev:
                        smp["devA"] = prev / lgprev - 1
                    cur = weekly_fpa.get((Y, opp, pos), {})
                    past_wks = [w for w in cur if w < wk]
                    if len(past_wks) >= 4 and lg.get((Y, pos)):
                        ratio = (sum(cur[w] for w in past_wks) / len(past_wks)) / lg[(Y, pos)]
                        smp["devB"] = min(1.25, max(0.8, ratio)) - 1
                        smp["gB"] = len(past_wks)
                    S.append(smp)
                hist.append(fpts)
        print(f"  {Y} done")
    print(f"\n{len(S)} player-weeks\n")

    def mse(pred, act):
        return float(np.mean((pred - act) ** 2))

    # ---- 1. snap layer ----
    sub = [s for s in S if "smult" in s]
    base = np.array([s["base"] for s in sub]); act = np.array([s["act"] for s in sub])
    mult = np.array([s["smult"] for s in sub]); delta = np.array([s["sdelta"] for s in sub])
    print(f"=== 1. SNAP TREND ({len(sub)} RB/WR/TE player-weeks with snap history) ===")
    print(f"  MSE base {mse(base, act):.3f} -> with snapMult {mse(base*mult, act):.3f}")
    aff = np.abs(mult - 1) >= 0.03
    print(f"  affected (|mult-1|>=3%): n={aff.sum()}  MSE {mse(base[aff], act[aff]):.3f} -> {mse((base*mult)[aff], act[aff]):.3f}")
    xs, ys = [], []
    for lo, hi in [(-40, -10), (-10, -5), (-5, -2), (-2, 2), (2, 5), (5, 10), (10, 40)]:
        m = (delta >= lo) & (delta < hi)
        if m.sum() < 300:
            continue
        xs.append(delta[m].mean()); ys.append(act[m].mean() / base[m].mean())
        print(f"  snap delta {delta[m].mean():+6.1f}pts: actual/base {ys[-1]:.3f}  (n={m.sum()})")
    print(f"  empirical slope {np.polyfit(xs, ys, 1)[0]*100:.2f}%/snap-pt   (engine ships 0.80%/pt)")

    # ---- 2. defense layers ----
    for tag, key in (("A prior-season FPA (preseason proxy)", "devA"),
                     ("B in-season FPA >=4 gms (jsOppMult design)", "devB")):
        sub = [s for s in S if key in s]
        base = np.array([s["base"] for s in sub]); act = np.array([s["act"] for s in sub])
        dev = np.array([s[key] for s in sub])
        w = np.minimum(1, np.array([s.get("gB", 8) for s in sub]) / 8.0) if key == "devB" else 1.0
        print(f"\n=== 2{key[-1]}. {tag} ({len(sub)} player-weeks) ===")
        line = "  MSE:"
        best = None
        for e in (0.0, 0.25, 0.5, 0.75, 1.0):
            pred = base * np.clip(1 + e * w * dev, 0.92, 1.08) if key == "devA" else \
                   base * (1 + e * w * dev)
            v = mse(pred, act)
            line += f"  e{e:.2f} {v:.3f}"
            if best is None or v < best[0]:
                best = (v, e)
        print(line + f"   <- best e={best[1]}")
        xs, ys = [], []
        for lo, hi in [(-1, -.15), (-.15, -.07), (-.07, -.02), (-.02, .02), (.02, .07), (.07, .15), (.15, 1)]:
            m = (dev >= lo) & (dev < hi)
            if m.sum() < 400:
                continue
            xs.append(dev[m].mean()); ys.append(act[m].mean() / base[m].mean())
            print(f"  FPA dev {dev[m].mean():+.3f}: actual/base {ys[-1]:.3f}  (n={m.sum()})")
        if len(xs) >= 3:
            print(f"  empirical slope = {np.polyfit(xs, ys, 1)[0]:.2f}")

if __name__ == "__main__":
    main()
