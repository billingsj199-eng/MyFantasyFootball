#!/usr/bin/env python3
"""
aDOT LEVEL layer backtest, 2019-2025 (Jack 2026-09-14: "backtest the aDOT level
layer next"). Follow-up to backtest_target_area.py's side finding: actual /
shipped by receiver DEEP-share tercile = low 1.09 / mid 1.04 / high 0.95 -
the model under-projects short-area receivers and over-projects deep-ball
receivers as a LEVEL, independent of the opponent.

Questions, in order:
  1. Is it real and stable? actual/shipped by aDOT quintile, per position,
     per season, and by games-into-season (g buckets).
  2. WHERE does it live? Grade Clay's prior alone and realized PPG alone by
     aDOT quintile. If Clay's guide carries the tilt and realized PPG does
     not, the fix belongs on the PRIOR inside the P=5 blend (and decays as
     the season sample grows); if both carry it, it is a level term.
  3. LOYO sweeps: (a) whole-mean multiplier x(1 - e*adot_z), (b) prior-only
     multiplier inside the blend, (c) deep-share and behind-LOS-share
     variants, (d) prior-season-only profile (usable preseason / Week 1).

aDOT = mean air yards per target, season-to-date shrunk toward the prior
season (K=40 targets); z-scored WITHIN position (WR and TE run at different
depths). Harness = P=5 Clay/PPG base x Vegas (WR/TE e=.25) x in-season FPA
layer = "shipped", WR + TE, LOYO by season. Log: adot_level_backtest.log.
"""
import numpy as np
import pandas as pd
import json, os, sys, io
from collections import defaultdict
from backtest_sim_calibration import (played, weekly_rec, infer_team,
                                      POOL_MIN_PTS, OPP_ALIAS)
import backtest_sim_calibration as cal
from backtest_snap_defense import build_fpa
from backtest_target_area import (load_players, resolve_gsis, load_targets, implied_map,
                                  mse, loyo, LOAD_YEARS, YEARS, VEGAS_E, FPA_E, FPA_TRUST_G, P, CACHE)

# stdout is already re-wrapped by backtest_target_area on import (a second wrapper closes the buffer)

K_PLR = 40.0
POS_TEST = ("WR", "TE")

def cum_profile(t):
    """(season,pid) -> sorted [(week, cum {n, ay, dp, bl, sh})]."""
    t = t.copy()
    t["dp"] = (t.depth == "dp").astype(int); t["bl"] = (t.depth == "bl").astype(int); t["sh"] = (t.depth == "sh").astype(int)
    agg = t.groupby(["season", "pid", "week"]).agg(n=("pts", "count"), ay=("ay", "sum"), dp=("dp", "sum"),
                                                   bl=("bl", "sum"), sh=("sh", "sum")).reset_index()
    out = {}
    for (s, pid), grp in agg.sort_values("week").groupby(["season", "pid"]):
        cum = {"n": 0.0, "ay": 0.0, "dp": 0.0, "bl": 0.0, "sh": 0.0}; lst = []
        for r in grp.itertuples(index=False):
            for k in cum: cum[k] += float(getattr(r, k))
            lst.append((int(r.week), dict(cum)))
        out[(s, pid)] = lst
    return out

def before(lst, wk):
    best = None
    for w, c in lst or []:
        if w < wk: best = c
        else: break
    return best

def profile(cur, prior, lg):
    """shrunk aDOT / deep share / behind-LOS share / short share."""
    n = cur["n"] if cur else 0.0
    out = {}
    for k, num in (("adot", "ay"), ("deep", "dp"), ("bl", "bl"), ("sh", "sh")):
        cv = (cur[num] / n) if n > 0 else None
        pv = (prior[num] / prior["n"]) if (prior and prior["n"] >= 30) else lg[k]
        out[k] = pv if cv is None else (n * cv + K_PLR * pv) / (n + K_PLR)
        out[k + "_prior"] = (prior[num] / prior["n"]) if (prior and prior["n"] >= 30) else None
    return out

def zs_within(x, pos, clip=2.5):
    z = np.zeros_like(x)
    for p in set(pos):
        m = (pos == p) & ~np.isnan(x)
        mu, sd = x[m].mean(), x[m].std()
        z[m] = np.clip((x[m] - mu) / (sd if sd > 0 else 1), -clip, clip)
    return z

def main():
    by_norm = load_players()
    frames, lines_all = {}, {}
    for Y in LOAD_YEARS:
        t, lines = load_targets(Y)
        # load_targets drops air_yards; rebuild it from the raw file for aDOT
        raw = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"),
                          usecols=["season_type", "posteam", "pass_attempt", "sack", "receiver_player_id", "air_yards", "pass_location"],
                          low_memory=False)
        raw = raw[(raw.season_type == "REG") & raw.posteam.notna() & (raw.pass_attempt == 1) & raw.receiver_player_id.notna() & (raw.sack != 1)
                  & raw.air_yards.notna() & raw.pass_location.isin(["left", "middle", "right"])]
        assert len(raw) == len(t), (len(raw), len(t))
        t = t.reset_index(drop=True); t["ay"] = raw.air_yards.values
        frames[Y] = t; lines_all[Y] = lines
        print(f"  pbp {Y}: {len(t)} targets")
    allt = pd.concat(frames.values(), ignore_index=True)
    prof = cum_profile(allt)
    # league profile per position (players.csv position via by_norm is name-keyed; use pooled receivers instead)
    lg_all = {"adot": float(allt.ay.mean()), "deep": float((allt.depth == "dp").mean()),
              "bl": float((allt.depth == "bl").mean()), "sh": float((allt.depth == "sh").mean())}

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
            prior = prof.get((Y - 1, pid)); prior = prior[-1][1] if prior else None
            rows = sorted([(w["wk"], w["fpts"], OPP_ALIAS.get(w.get("opp"), w.get("opp")))
                           for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            sig = cal.sigma_entering(name, pos, Y)
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
                    pr = profile(before(prof.get((Y, pid)), wk), prior, lg_all)
                    S["year"].append(Y); S["pos"].append(pos); S["act"].append(fpts); S["g"].append(g)
                    S["clay"].append(clay_pg); S["ppg"].append(ppg); S["base"].append(base)
                    S["veg"].append(veg); S["fpa"].append(fpa)
                    S["sig"].append(sig)
                    for k in ("adot", "deep", "bl", "sh"):
                        S[k].append(pr[k]); S[k + "_prior"].append(np.nan if pr[k + "_prior"] is None else pr[k + "_prior"])
                hist.append(fpts)
        print(f"  {Y}: samples so far {len(S['act'])}")
    print(f"  skipped: {dict(miss)}")
    S = {k: (np.array(v) if k == "pos" else np.array(v, float)) for k, v in S.items()}
    S["year"] = S["year"].astype(int); years = sorted(set(S["year"]))
    act, base, pos = S["act"], S["base"], S["pos"]
    chain = S["veg"] * S["fpa"]
    shipped = base * chain
    print(f"\n{len(act)} WR/TE player-weeks | shipped MSE {mse(shipped, act):.4f} | mean act/shipped {act.mean()/shipped.mean():.3f}")

    # ---- 1. is it real and stable?
    def qtable(x, label, pred, mask=None, nq=5):
        mask = np.ones_like(act, bool) if mask is None else mask
        q = np.quantile(x[mask], np.linspace(0, 1, nq + 1)[1:-1]); edges = [-np.inf] + list(q) + [np.inf]
        parts = []
        for i in range(nq):
            m = mask & (x >= edges[i]) & (x < edges[i + 1])
            parts.append(f"{x[m].mean():5.1f}->{act[m].mean()/pred[m].mean():.3f}" if m.sum() else "   -   ")
        return f"  {label:28s} " + " | ".join(parts)
    print("\n=== 1. actual / shipped by aDOT quintile (within-position cuts) ===")
    for p in POS_TEST:
        m = pos == p
        print(qtable(S["adot"], f"{p} all (n={m.sum()})", shipped, m))
        for lo, hi in ((1, 4), (5, 9), (10, 20)):
            mm = m & (S["g"] >= lo) & (S["g"] <= hi)
            print(qtable(S["adot"], f"{p} games {lo}-{hi} (n={mm.sum()})", shipped, mm))
    print("  per season (WR, aDOT terciles low/mid/high):")
    for y in years:
        m = (pos == "WR") & (S["year"] == y)
        print(qtable(S["adot"], f"   {y} (n={m.sum()})", shipped, m, nq=3))
    print(qtable(S["deep"] * 100, "WR deep share %", shipped, pos == "WR"))
    print(qtable(S["bl"] * 100, "WR behind-LOS share %", shipped, pos == "WR"))
    print(qtable(S["sh"] * 100, "WR short share %", shipped, pos == "WR"))

    # ---- 2. where does it live?
    print("\n=== 2. which component carries the tilt? actual / X by WR aDOT quintile ===")
    m = pos == "WR"
    print(qtable(S["adot"], "X = Clay prior x chain", S["clay"] * chain, m))
    print(qtable(S["adot"], "X = realized PPG x chain", S["ppg"] * chain, m))
    print(qtable(S["adot"], "X = P=5 blend x chain (shipped)", shipped, m))
    mm = m & (S["g"] >= 8)
    print(qtable(S["adot"], "X = realized PPG, g>=8 only", S["ppg"] * chain, mm))
    print("  (a ratio slope on the Clay line but a flat realized line = a prior bias that the blend dilutes;")
    print("   slopes on both = a level effect the realized mean does not remove, e.g. skew/selection)")

    # ---- 3. LOYO sweeps
    print("\n=== 3. LOYO sweeps (grid[0] = shipped) ===")
    az = zs_within(S["adot"], pos); dz = zs_within(S["deep"], pos); bz = zs_within(S["bl"], pos)
    apz = zs_within(np.where(np.isnan(S["adot_prior"]), S["adot"], S["adot_prior"]), pos)
    grid = [0.0, 0.01, 0.02, 0.03, 0.04, 0.06, 0.08]
    wP = P / (P + S["g"])   # prior weight inside the blend
    res = {}
    res["a"] = loyo(S, years, grid, lambda e: shipped * np.clip(1 - e * az, 0.8, 1.25), "a) whole mean x(1 - e*adot_z)")
    res["b"] = loyo(S, years, grid, lambda e: (S["clay"] * np.clip(1 - e * az, 0.8, 1.25) * wP + S["ppg"] * (1 - wP)) * chain,
                    "b) Clay PRIOR only x(1 - e*adot_z) inside the P=5 blend (decays with g)")
    res["c"] = loyo(S, years, grid, lambda e: shipped * np.clip(1 - e * dz, 0.8, 1.25), "c) whole mean x(1 - e*deepShare_z)")
    res["d"] = loyo(S, years, grid, lambda e: shipped * np.clip(1 + e * bz, 0.8, 1.25), "d) whole mean x(1 + e*behindLOS_z)")
    res["e"] = loyo(S, years, grid, lambda e: shipped * np.clip(1 - e * apz, 0.8, 1.25), "e) PRIOR-SEASON aDOT only (preseason-usable)")
    for p in POS_TEST:
        m = pos == p; Sp = {k: v[m] for k, v in S.items()}; shp = shipped[m]; azp = az[m]
        loyo(Sp, years, grid, lambda e, shp=shp, azp=azp: shp * np.clip(1 - e * azp, 0.8, 1.25), f"   {p} only: whole mean x(1 - e*adot_z)")
        wPp = wP[m]
        loyo(Sp, years, grid, lambda e, Sp=Sp, wPp=wPp, azp=azp: (Sp["clay"] * np.clip(1 - e * azp, 0.8, 1.25) * wPp + Sp["ppg"] * (1 - wPp)) * Sp["veg"] * Sp["fpa"],
             f"   {p} only: prior-only")
    # ---- 4. the mechanism: shrink NOISY players harder (sigma-aware prior strength)
    print("\n=== 4. sigma-aware prior strength: P_i = P * (sigma_i / mean sigma_pos)^k inside the blend ===")
    sig = S["sig"]; sigrel = np.ones_like(sig)
    for p in POS_TEST:
        m = pos == p; sigrel[m] = sig[m] / sig[m].mean()
    print("  sigma (CV) by aDOT quintile, WR: " + qtable(S["adot"], "", sig * 0 + 1, pos == "WR").strip()[:0] +
          " | ".join(f"{np.quantile(S['adot'][pos=='WR'], q):.1f}:{sig[(pos=='WR') & (S['adot'] >= np.quantile(S['adot'][pos=='WR'], q))].mean():.3f}" for q in (0, .2, .4, .6, .8)))
    print(f"  corr(aDOT, sigma) WR {np.corrcoef(S['adot'][pos=='WR'], sig[pos=='WR'])[0,1]:+.2f}  TE {np.corrcoef(S['adot'][pos=='TE'], sig[pos=='TE'])[0,1]:+.2f}")
    def blend(Pi): return ((Pi * S["clay"] + S["g"] * S["ppg"]) / (Pi + S["g"])) * chain
    loyo(S, years, [0.0, 0.5, 1.0, 1.5, 2.0, 3.0], lambda k: blend(P * sigrel ** k), "a) P_i = 5 * sigrel^k")
    loyo(S, years, [5, 3, 4, 6, 7, 8], lambda Pv: blend(float(Pv) * np.ones_like(sig)), "b) reference: flat P re-swept")
    loyo(S, years, [0.0, 0.25, 0.5, 0.75, 1.0], lambda e: blend(P * np.clip(1 + e * az, 0.3, 3.0)), "c) P_i = 5 * (1 + e*adot_z) (aDOT as the noise proxy)")
    for p in POS_TEST:
        m = pos == p; Sp = {k: v[m] for k, v in S.items()}; sr = sigrel[m]; ch = chain[m]
        def blend_p(Pi, Sp=Sp, ch=ch): return ((Pi * Sp["clay"] + Sp["g"] * Sp["ppg"]) / (Pi + Sp["g"])) * ch
        loyo(Sp, years, [0.0, 0.5, 1.0, 1.5, 2.0, 3.0], lambda k, sr=sr, blend_p=blend_p: blend_p(P * sr ** k), f"   {p} only: P_i = 5 * sigrel^k")
    # does sigma-aware P remove the aDOT tilt?
    for k in (0.0, 1.0, 2.0):
        pr = blend(P * sigrel ** k)
        print(qtable(S["adot"], f"  act/pred by WR aDOT quintile, k={k}", pr, pos == "WR"))
    # level check: is the gain just the WR under-projection level (act/shipped 1.04)?
    lvl = act.mean() / shipped.mean()
    res["l"] = loyo(S, years, [0.0, 1.0], lambda k: shipped * (lvl if k else 1.0), f"l) flat level x{lvl:.3f} alone (reference)")
    res["al"] = loyo(S, years, grid, lambda e: shipped * lvl * np.clip(1 - e * az, 0.8, 1.25), "al) level fix + aDOT on top (does aDOT add beyond the level?)")

if __name__ == "__main__":
    main()
