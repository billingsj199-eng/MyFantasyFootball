#!/usr/bin/env python3
"""
Backtest the SIM DISTRIBUTIONS (not the means — backtest_hybrid.py did that).

For each season Y in 2019-2025, rebuild the player pool from that year's
PRESEASON Clay guide (clay_history.json), reconstruct each player's weekly
sigma exactly the way the engine does (3-yr weighted CV entering Y, low-sample
widening, position-default fallback), then run the engine's sampling math
(gamma around an env-shifted mean, ENV_BETA 0.20, RESID_SHRINK 0.9) and grade
against actual weekly results (weekly_stats_active + retired splits):

  1. WEEKLY calibration   — % of actual played-weeks inside the sim's p10-p90
                            (target ~80%) and p25-p75 (~50%).
  2. SEASON-TOTAL bands   — % of actual season totals inside p10-p90, and the
                            share landing BELOW p10 (the injury tail the 2026
                            engine doesn't model).
  3. FINISH ODDS          — sim top-3/12/24 positional finish probabilities vs
                            realized finishes (within the same pool): Brier
                            score + reliability buckets.

Two engine variants, same seeds:
  A = the engine as shipped: every player plays all W games at halfPts/W.
  B = candidate injury layer: each week played with prob gm/W (Clay's own
      games projection), at the TRUE per-game rate halfPts/gm. Season mean is
      ~unchanged; the variance moves into the tails like real seasons do.

No Vegas layer or defense adj (no historical lines/grades wired in) — those
shift weekly means around a season constant and mostly cancel over a season,
so the distribution calibration read stays fair.

Data quirks handled: 16-game seasons pre-2021; name collisions dropped unless
position disambiguates; players found in the weekly DB but with zero weeks in
Y count as REAL zero seasons (that's the tail!), names never found anywhere
are dropped as unmatched.
"""
import json, math, os, re, sys
import numpy as np

REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"
SEASONS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
SIMS = 2000
SEED = 20260730
POOL_MIN_PTS = 40.0          # projected regulars only (matches backtest_hybrid)
POS_KEEP = {"QB", "RB", "WR", "TE"}
POS_SIGMA = {"QB": 0.42, "RB": 0.52, "WR": 0.62, "TE": 0.70}
# per-position weekly-width calibration shipped 2026-07-30 (see
# backtest_weekly_sigma.py) — mirrored from engine.js SIGMA_CAL
SIGMA_CAL = {"QB": 1.0, "RB": 1.15, "WR": 1.15, "TE": 1.10}
ENV_BETA = 0.20
RESID_SHRINK = 0.9
SIGMA_WTS = [0.5, 0.3, 0.2]

# Variants: A = engine as shipped pre-shock (no shock, no gm layer).
# Everything else = gm injury layer + a season shock:
#   gamma: symmetric-ish right-skewed gamma(mean 1, cv tau) — C45 was the
#          2026-07-30 ship; its residual is an ASYMMETRY error (below-p10
#          ~19% vs above-p90 ~7%; real tails are downside-fat).
#   mix:   wrecked-season mixture — with prob q the season multiplier is
#          U(0.10, 0.60) (major injury / role collapse), else gamma(cv tau)
#          scaled so the overall mean stays exactly 1.
# Upside-trim add-ons (fix the fat up-tail: above-p90 ran 7.2% vs target 10,
# i.e. p90s too high): draws above 1 keep only a fraction u of their excess,
# then the whole shock renormalizes to mean 1.
#   "u":     global fraction
#   "uproj": (a, b, lo) -> u = clamp(a - halfPts/b, lo, 1.0): projection-
#            scaled — elite projections have less relative headroom.
# Elite-bucket add-ons (2026-07-31: flat q=.20 wreck is ~1.6x too frequent and
# too deep for top-projected players — empirical top-6 <50%-of-proj rate is
# ~11%, and its P(>1.5x) runs 4x too fat; see elite_tail_check.py):
#   "qproj": (a, b, lo, hi) -> q = clamp(a - halfPts/b, lo, hi): projection-
#            scaled wreck probability (elite ~lo, deep bench ~hi).
#   "tilt":  exponent e on the wreck-depth uniform draw — wreck = wlo +
#            (whi-wlo) * U^e; e < 1 pushes mass toward the MILD (whi) end.
MIXBASE = {"kind": "mix", "q": 0.20, "tau": 0.30, "wlo": 0.05, "whi": 0.50}
# SHIPPED 2026-07-31 (v4 elite-bucket recalibration, sweep winner "QP2TP"):
# projection-scaled wreck prob + drift width on top of the v3 uptrim.
# Sweep notes (2026-07-31): qproj alone fixed wreck rates but left the elite
# band too wide both sides (rank 1-6 below-p10 ~6% / above-p90 ~2%, model
# >1.5x 8.7% vs act 1.2%); wreck-depth tilts (milder wrecks for everyone)
# degraded pooled below-p10 to 13-14% — deep pool needs the deep wrecks;
# harder elite uptrim floors (u lo .25) were ~neutral; tauproj closed the
# up-tail (elite above-p90 2->7%). Winner: pooled cov 80.4 / below-p10 10.6 /
# above-p90 8.9 / Brier12 .1144, elite bucket 6.0/7.1 with wreck 13.5 vs
# act 10.7 and >1.5x 5.0 vs act 1.2.
SHIPPED_SHOCK = dict(MIXBASE, qproj=(0.28, 1800, 0.12, 0.26),
                     tauproj=(0.30, 2000, 0.15), uproj=(1.05, 400, 0.40))
VARIANTS = {
    "A": None,
    "SHIPPED": SHIPPED_SHOCK,
}
def vtag(v):
    if v == "A":
        return "A no-shock baseline "
    c = VARIANTS[v]
    if c["kind"] == "gamma":
        return "gamma tau=%.2f      " % c["tau"]
    if "qproj" in c:
        tag = "mix qproj%s" % (c["qproj"],)
    else:
        tag = "mix q=%.02d%%" % (c["q"] * 100)
    if c.get("tilt"):
        tag += " tilt %.1f" % c["tilt"]
    if "tauproj" in c:
        tag += " tauproj%s" % (c["tauproj"],)
    if "u" in c:
        tag += " uptrim %.2f     " % c["u"]
    elif "uproj" in c:
        tag += " uptrim proj%s" % (c["uproj"],)
    else:
        tag += " (no uptrim)     "
    return tag

def draw_shock(rng, cfg, half=None):
    """(SIMS,1) season-shock draws with mean exactly 1."""
    t = cfg["tau"]
    if "tauproj" in cfg and half is not None:
        a, b, lo = cfg["tauproj"]
        t = min(a, max(lo, a - half / b))
    gam = rng.gamma(1.0 / t ** 2, t ** 2, (SIMS, 1))
    if cfg["kind"] == "gamma":
        return gam
    q = cfg["q"]
    if "qproj" in cfg and half is not None:
        a, b, lo, hi = cfg["qproj"]
        q = min(hi, max(lo, a - half / b))
    wlo, whi = cfg.get("wlo", 0.10), cfg.get("whi", 0.60)
    tilt = cfg.get("tilt")
    if tilt:  # wreck = wlo + (whi-wlo)*U^tilt; E[U^tilt] = 1/(1+tilt)
        wreck_mean = wlo + (whi - wlo) / (1.0 + tilt)
        wreck = wlo + (whi - wlo) * rng.random((SIMS, 1)) ** tilt
    else:
        wreck_mean = (wlo + whi) / 2
        wreck = rng.uniform(wlo, whi, (SIMS, 1))
    gam *= (1 - wreck_mean * q) / (1 - q)     # keep E[shock] = 1
    arr = np.where(rng.random((SIMS, 1)) < q, wreck, gam)
    u = cfg.get("u")
    if u is None and "uproj" in cfg and half is not None:
        a, b, lo = cfg["uproj"]
        u = min(1.0, max(lo, a - half / b))
    if u is not None and u < 1.0:
        arr = np.where(arr > 1, 1 + (arr - 1) * u, arr)
        arr /= arr.mean()
    return arr

COACH_PATH = r"E:\MyFantasyFootball\pbp_cache\coach_research.json"
COACH = json.load(open(COACH_PATH, encoding="utf-8"))
CHANGES = {int(y): set(ts) for y, ts in COACH["changes"].items()}
SCHEDULES = {int(y): s for y, s in COACH["schedules"].items()}
OPP_ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS",
             "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}

def infer_team(rec, season):
    """Match a player's opponent sequence against every team's schedule."""
    wks = rec.get("seasons", {}).get(str(season), [])
    pairs = [(str(w.get("wk")), OPP_ALIAS.get(w.get("opp"), w.get("opp")))
             for w in wks if played(w) and w.get("opp")]
    if len(pairs) < 4:
        return None
    best, best_score = None, 0.0
    for t, s in SCHEDULES.get(season, {}).items():
        hit = sum(1 for wk, opp in pairs if s.get(wk) == opp)
        score = hit / len(pairs)
        if score > best_score:
            best, best_score = t, score
    return best if best_score >= 0.7 else None

def norm(n):
    n = n.lower().replace(".", "").replace("'", "").replace("-", " ")
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return re.sub(r"\s+", " ", n).strip()

def load_weekly():
    """Merge active + retired weekly stats; norm-name keyed, collision-aware."""
    files = ["weekly_stats_active.js", "weekly_stats_retired_1.js",
             "weekly_stats_retired_2.js", "weekly_stats_retired_3.js"]
    by = {}
    for f in files:
        path = os.path.join(REPO, "data", f)
        raw = open(path, encoding="utf-8").read()
        d, _ = json.JSONDecoder().raw_decode(raw, raw.index("{"))
        for name, rec in d.items():
            k = norm(name)
            if k in by:
                by[k].append(rec)
            else:
                by[k] = [rec]
    return by

WEEKLY = load_weekly()

def weekly_rec(name, pos):
    """Resolve a player's weekly record; None if unmatched or ambiguous."""
    cands = WEEKLY.get(norm(name))
    if not cands:
        return None
    same = [c for c in cands if c.get("pos") == pos]
    if len(same) == 1:
        return same[0]
    if len(cands) == 1 and not same:
        return None  # name matched, position didn't — likely a collision
    return None if len(same) != 1 else same[0]

def played(row):
    return (row.get("fpts") or 0) != 0 or (row.get("pa") or 0) > 0 or \
           (row.get("ra") or 0) > 0 or (row.get("tgt") or 0) > 0

def played_weeks(rec, season):
    wks = rec.get("seasons", {}).get(str(season), [])
    return [w["fpts"] for w in wks if played(w) and isinstance(w.get("fpts"), (int, float))]

def sigma_entering(name, pos, season):
    """Engine's sigma build: 3-yr weighted weekly CV, widen for thin samples."""
    rec = weekly_rec(name, pos)
    num = den = 0.0
    total_g = 0
    if rec:
        for i, yr in enumerate([season - 1, season - 2, season - 3]):
            pts = played_weeks(rec, yr)
            if len(pts) < 4:
                continue
            m = sum(pts) / len(pts)
            if m <= 1:
                continue
            sd = (sum((p - m) ** 2 for p in pts) / (len(pts) - 1)) ** 0.5
            num += SIGMA_WTS[i] * (sd / m)
            den += SIGMA_WTS[i]
            total_g += len(pts)
    if den > 0 and total_g >= 8:
        s = (num / den) * (1 + 0.25 * (1 - min(1.0, total_g / 30.0)))
    else:
        s = POS_SIGMA[pos] * 1.15  # no usable history (engine: 1.10 vet / 1.20 rookie)
    s *= SIGMA_CAL.get(pos, 1.0)
    return min(1.35, max(0.28, s))

def sim_player(rng, weekly_mean, sigma, n_weeks, p_play, tau=0.0, shock=None):
    """(SIMS, n_weeks) gamma draws mirroring samplePlayerScore.

    A SEASON SHOCK (via `shock` array, or gamma(cv tau) if tau > 0) scales
    every week's mean AND sd together — the persistent role/health/breakout
    component that independent weekly draws can't produce (they shrink
    season CV by ~1/sqrt(17))."""
    if shock is not None:
        base = weekly_mean * shock
    elif tau > 0:
        base = weekly_mean * rng.gamma(1.0 / tau ** 2, tau ** 2, (SIMS, 1))
    else:
        base = weekly_mean
    z = rng.standard_normal((SIMS, n_weeks))
    m = base * np.maximum(0.4, 1 + ENV_BETA * z)
    sd = np.maximum(1e-4, base * sigma * RESID_SHRINK)
    k = (m / sd) ** 2
    th = (sd * sd) / m
    draws = rng.gamma(k, th)
    if p_play < 1.0:
        draws = draws * (rng.random((SIMS, n_weeks)) < p_play)
    return draws

def pctile(a, q):
    return float(np.percentile(a, q))

def rank_within(totals):
    """1-indexed descending ranks."""
    order = np.argsort(-totals)
    ranks = np.empty_like(order)
    ranks[order] = np.arange(1, len(totals) + 1)
    return ranks

def run_season(Y, clay):
    W = 16 if Y <= 2020 else 17
    rng = np.random.default_rng(SEED + Y)
    pool = []
    unmatched = 0
    for name, c in clay.items():
        pos = c.get("pos")
        if pos not in POS_KEEP:
            continue
        pts, gm, rec_n = c.get("pts") or 0, c.get("gm") or 0, c.get("rec") or 0
        if pts < POOL_MIN_PTS or gm < 2:
            continue
        half = max(0.5, pts - rec_n / 2.0)
        wrec = weekly_rec(name, pos)
        if wrec is None:
            unmatched += 1
            continue
        actual = played_weeks(wrec, Y)          # [] = real zero season, kept
        team = infer_team(wrec, Y)
        pool.append({
            "name": name, "pos": pos, "half": half, "gm": min(gm, W),
            "sigma": sigma_entering(name, pos, Y),
            "changed": team in CHANGES.get(Y, set()),
            "teamed": team is not None,
            "actual_weeks": actual, "actual_total": sum(actual),
        })
    # positional projection rank (1 = highest projected at his position) —
    # elite-bucket calibration is graded separately per rank bucket
    for pos in POS_KEEP:
        idx = sorted([i for i, p in enumerate(pool) if p["pos"] == pos],
                     key=lambda i: -pool[i]["half"])
        for rk, i in enumerate(idx, 1):
            pool[i]["posrank"] = rk

    res = {"Y": Y, "W": W, "n": len(pool), "unmatched": unmatched,
           "teamed": sum(p["teamed"] for p in pool),
           "n_changed": sum(p["changed"] for p in pool)}

    for variant, cfg in VARIANTS.items():
        totals = np.zeros((len(pool), SIMS))
        wk_cov80 = wk_cov50 = wk_n = 0
        for i, p in enumerate(pool):
            if cfg is None:
                draws = sim_player(rng, p["half"] / W, p["sigma"], W, 1.0)
            else:
                draws = sim_player(rng, p["half"] / p["gm"], p["sigma"], W, p["gm"] / W,
                                   shock=draw_shock(rng, cfg, p["half"]))
            totals[i] = draws.sum(axis=1)
            if variant == list(VARIANTS)[0] and p["actual_weeks"]:
                flat = draws.ravel()
                lo10, hi90 = pctile(flat, 10), pctile(flat, 90)
                lo25, hi75 = pctile(flat, 25), pctile(flat, 75)
                for a in p["actual_weeks"]:
                    wk_n += 1
                    if lo10 <= a <= hi90: wk_cov80 += 1
                    if lo25 <= a <= hi75: wk_cov50 += 1
        if variant == list(VARIANTS)[0]:
            res["wk_n"] = wk_n
            res["wk_cov80"] = wk_cov80 / wk_n if wk_n else 0
            res["wk_cov50"] = wk_cov50 / wk_n if wk_n else 0

        act = np.array([p["actual_total"] for p in pool])
        lo10 = np.percentile(totals, 10, axis=1)
        hi90 = np.percentile(totals, 90, axis=1)
        mean = totals.mean(axis=1)
        res[variant] = {
            "cov80": float(((act >= lo10) & (act <= hi90)).mean()),
            "below_p10": float((act < lo10).mean()),
            "above_p90": float((act > hi90).mean()),
            "mae": float(np.abs(mean - act).mean()),
        }

        # per-projection-rank bucket tails: below/above sim band + wreck
        # (<50% of proj) and big-hit (>150%) rates, model vs actual
        halfs = np.array([p["half"] for p in pool])
        ranks = np.array([p["posrank"] for p in pool])
        bstats = {}
        for bname, blo, bhi in (("1-6", 1, 6), ("7-12", 7, 12), ("13-24", 13, 24), ("25+", 25, 10 ** 9)):
            m = (ranks >= blo) & (ranks <= bhi)
            if not m.any():
                continue
            bstats[bname] = {
                "n": int(m.sum()),
                "below_p10": float((act[m] < lo10[m]).mean()),
                "above_p90": float((act[m] > hi90[m]).mean()),
                "mod_wreck": float((totals[m] < 0.5 * halfs[m, None]).mean()),
                "act_wreck": float((act[m] < 0.5 * halfs[m]).mean()),
                "mod_hit15": float((totals[m] > 1.5 * halfs[m, None]).mean()),
                "act_hit15": float((act[m] > 1.5 * halfs[m]).mean()),
            }
        res[variant]["buckets"] = bstats

        # finish odds vs realized, per position within the pool
        briers, cal = {12: [], 24: []}, {12: []}
        for pos in POS_KEEP:
            idx = [i for i, p in enumerate(pool) if p["pos"] == pos]
            if len(idx) < 13:
                continue
            sub = totals[idx]                       # (n_pos, SIMS)
            sim_ranks = np.argsort(-sub, axis=0).argsort(axis=0) + 1
            act_ranks = rank_within(act[idx])
            for cut in (12, 24):
                if len(idx) <= cut:
                    continue
                prob = (sim_ranks <= cut).mean(axis=1)
                real = (act_ranks <= cut).astype(float)
                briers[cut].extend(((prob - real) ** 2).tolist())
                if cut == 12:
                    cal[12].extend(zip(prob.tolist(), real.tolist()))
        for cut in (12, 24):
            res[variant][f"brier{cut}"] = float(np.mean(briers[cut])) if briers[cut] else None
        res[variant]["cal12"] = cal[12]
    return res

def main():
    clay_hist = json.load(open(os.path.join(REPO, "data", "clay_history.json"), encoding="utf-8"))
    all_res = []
    for Y in SEASONS:
        if str(Y) not in clay_hist:
            continue
        r = run_season(Y, clay_hist[str(Y)])
        all_res.append(r)
        print(f"\n=== {Y} ({r['n']} players pooled, {r['unmatched']} unmatched, {r['W']}-game season, "
              f"{r['teamed']} team-matched, {r['n_changed']} on new-HC teams) ===")
        print(f"  weekly (A): p10-p90 coverage {r['wk_cov80']*100:5.1f}%  (target 80)   "
              f"p25-p75 {r['wk_cov50']*100:5.1f}%  (target 50)   [{r['wk_n']} player-weeks]")
        for v in VARIANTS:
            d = r[v]
            tag = vtag(v)
            print(f"  season {tag}: p10-p90 cov {d['cov80']*100:5.1f}%  below-p10 {d['below_p10']*100:5.1f}%  "
                  f"above-p90 {d['above_p90']*100:4.1f}%  MAE {d['mae']:6.1f}  "
                  f"Brier top12 {d['brier12']:.4f}  top24 {d['brier24']:.4f}")

    # pooled summary + top-12 reliability buckets
    print("\n=== POOLED " + str(SEASONS[0]) + "-" + str(SEASONS[-1]) + " ===")
    wk_n = sum(r["wk_n"] for r in all_res)
    wk80 = sum(r["wk_cov80"] * r["wk_n"] for r in all_res) / wk_n
    wk50 = sum(r["wk_cov50"] * r["wk_n"] for r in all_res) / wk_n
    print(f"  weekly: p10-p90 {wk80*100:.1f}% (target 80)   p25-p75 {wk50*100:.1f}% (target 50)")
    for v in VARIANTS:
        n = sum(r["n"] for r in all_res)
        cov = sum(r[v]["cov80"] * r["n"] for r in all_res) / n
        blo = sum(r[v]["below_p10"] * r["n"] for r in all_res) / n
        ahi = sum(r[v]["above_p90"] * r["n"] for r in all_res) / n
        mae = sum(r[v]["mae"] * r["n"] for r in all_res) / n
        b12 = np.mean([x for r in all_res for x in [(r[v]["brier12"])] if x is not None])
        b24 = np.mean([x for r in all_res for x in [(r[v]["brier24"])] if x is not None])
        tag = vtag(v)
        print(f"  {tag}: season p10-p90 cov {cov*100:5.1f}%  below-p10 {blo*100:5.1f}% (target 10)  "
              f"above-p90 {ahi*100:4.1f}% (target 10)  MAE {mae:.1f}  Brier12 {b12:.4f}  Brier24 {b24:.4f}")
        for bname in ("1-6", "7-12", "13-24", "25+"):
            bs = [r[v]["buckets"][bname] for r in all_res if bname in r[v]["buckets"]]
            if not bs:
                continue
            bn = sum(b["n"] for b in bs)
            agg = {k: sum(b[k] * b["n"] for b in bs) / bn for k in
                   ("below_p10", "above_p90", "mod_wreck", "act_wreck", "mod_hit15", "act_hit15")}
            print(f"    rank {bname:5s} (n={bn:4d}): below-p10 {agg['below_p10']*100:5.1f}%  above-p90 {agg['above_p90']*100:4.1f}%  "
                  f"wreck<50% mod {agg['mod_wreck']*100:5.1f}% / act {agg['act_wreck']*100:5.1f}%  "
                  f">150% mod {agg['mod_hit15']*100:4.1f}% / act {agg['act_hit15']*100:4.1f}%")
        pairs = [x for r in all_res for x in r[v]["cal12"]]
        buckets = [(0, .05), (.05, .15), (.15, .3), (.3, .5), (.5, .7), (.7, .9), (.9, 1.01)]
        print(f"    top-12 reliability ({len(pairs)} player-seasons): pred -> realized")
        for lo, hi in buckets:
            hit = [real for prob, real in pairs if lo <= prob < hi]
            if len(hit) >= 10:
                mid = [prob for prob, real in pairs if lo <= prob < hi]
                print(f"      {np.mean(mid)*100:5.1f}% predicted -> {np.mean(hit)*100:5.1f}% realized   (n={len(hit)})")

if __name__ == "__main__":
    main()
