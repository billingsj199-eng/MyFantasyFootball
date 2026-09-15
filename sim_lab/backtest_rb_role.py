#!/usr/bin/env python3
"""
RB ROLE DECOMPOSITION backtest, 2019-2025 (Jack 2026-09-14: "backtest the RB
role decomposition first").

The engine applies ONE Vegas elasticity to every RB (VEGAS_ELAS.RB = 0.50,
backtest_vegas_layer.py: "game script is real"). But game script cuts both
ways inside an RB room: the early-down / closing back should gain when his
team is favored, the passing-down back should gain when it is trailing. And
TD-heavy RB scoring means a back's realized PPG (half the P=5 base by ~wk 5)
carries TD luck that his red-zone USAGE says should regress.

Everything below is reconstructed from nflverse play-by-play SEASON-TO-DATE
(weeks < W only, shrunk toward the player's prior-season profile), so the live
engine could compute the identical numbers nightly from play_by_play_2026.

Role metrics per RB (shares are of his TEAM'S RB-room totals, RB = players.csv
position):
  touch_share  his share of team RB touches (carries + targets)
  pass_role    target share - carry share          (+ = passing-down back)
  tilt         touch share when LEADING - touch share when TRAILING
               (pre-snap score differential > 0 / < 0)   (+ = closer/grinder)
  tilt7        same at +-7 or more
  d3_gap       share of 3rd-down + two-minute RB touches - touch share
  rz_gap       share of inside-10 RB carries - carry share  (+ = goal-line back)
  td_luck      (expected TDs from touch locations - actual TDs) per game
               (+ = unlucky so far -> should regress UP)

Tests (base = P=5 Clay/PPG blend x shipped Vegas e=0.50 -> "shipped"):
  1. residual by tercile of each metric (is any of it new information?)
  2. empirical Vegas elasticity INSIDE tilt / pass_role terciles
  3. LOYO MSE sweeps: role-dependent elasticity, spread x role interaction,
     TD-luck correction, goal-line share multiplier, and the combination.

Usage: python backtest_rb_role.py   (~3 min; reads 8 pbp csv.gz)
"""
import numpy as np
import pandas as pd
import json, os, sys, io
from collections import defaultdict
from backtest_sim_calibration import (played, weekly_rec, infer_team,
                                      POOL_MIN_PTS, OPP_ALIAS)
import backtest_sim_calibration as cal

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CACHE = r"E:\MyFantasyFootball\pbp_cache"
P = 5
YEARS = range(2019, 2026)
LOAD_YEARS = range(2018, 2026)          # 2018 = prior-season profile for 2019
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS",
         "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
def tm(t): return ALIAS.get(t, t)
PRIOR_TOUCHES = 30.0                    # prior-season profile worth ~2 games of touches
E_SHIP = 0.50

PBP_COLS = ["game_id", "season_type", "week", "posteam", "home_team", "away_team", "home_score", "away_score",
            "spread_line", "total_line", "rush_attempt", "pass_attempt",
            "rusher_player_id", "receiver_player_id", "yardline_100", "down",
            "ydstogo", "score_differential", "half_seconds_remaining",
            "rush_touchdown", "pass_touchdown"]

# ---------------------------------------------------------------- players
def load_players():
    p = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False,
                    usecols=["gsis_id", "display_name", "position", "rookie_season", "last_season"])
    p = p.dropna(subset=["gsis_id"])
    rb_ids = set(p[p.position == "RB"].gsis_id)
    by_norm = defaultdict(list)
    for r in p[p.position == "RB"].itertuples(index=False):
        by_norm[cal.norm(str(r.display_name))].append(
            (r.gsis_id, r.rookie_season if pd.notna(r.rookie_season) else 0,
             r.last_season if pd.notna(r.last_season) else 9999))
    return rb_ids, by_norm

def resolve_gsis(by_norm, name, Y):
    c = by_norm.get(cal.norm(name), [])
    c = [x for x in c if x[1] <= Y <= x[2] + 1]
    return c[0][0] if len(c) == 1 else None

# ---------------------------------------------------------------- pbp
def load_touches(year, rb_ids):
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{year}.csv.gz"),
                     usecols=PBP_COLS, low_memory=False)
    df = df[(df.season_type == "REG") & df.posteam.notna()]
    lines = df.dropna(subset=["spread_line", "total_line"]).groupby("game_id").first()
    rush = df[(df.rush_attempt == 1) & df.rusher_player_id.isin(rb_ids)].copy()
    rush["pid"] = rush.rusher_player_id; rush["is_rush"] = 1
    rush["td"] = rush.rush_touchdown.fillna(0)
    tgt = df[(df.pass_attempt == 1) & df.receiver_player_id.isin(rb_ids)].copy()
    tgt["pid"] = tgt.receiver_player_id; tgt["is_rush"] = 0
    tgt["td"] = tgt.pass_touchdown.fillna(0)
    t = pd.concat([rush, tgt], ignore_index=True)
    t["season"] = year
    t["team"] = t.posteam.map(tm)
    sd = t.score_differential.fillna(0)
    t["lead"] = (sd > 0).astype(int); t["trail"] = (sd < 0).astype(int)
    t["lead7"] = (sd >= 7).astype(int); t["trail7"] = (sd <= -7).astype(int)
    yl = t.yardline_100.fillna(99)
    t["i10"] = ((yl <= 10) & (t.is_rush == 1)).astype(int)
    t["rz_tgt"] = ((yl <= 20) & (t.is_rush == 0)).astype(int)
    t["d3"] = ((t.down == 3) | (t.half_seconds_remaining.fillna(9999) <= 120)).astype(int)
    t["yl"] = yl
    return t[["season", "week", "team", "pid", "is_rush", "td", "lead", "trail",
              "lead7", "trail7", "i10", "rz_tgt", "d3", "yl"]], lines

def xtd_rates(t):
    """league TD probability per touch by (is_rush, yardline bucket), pooled."""
    bins = [0, 1, 2, 3, 4, 5, 10, 20, 40, 100]
    t = t.copy()
    t["yb"] = pd.cut(t.yl, bins=bins, right=True, labels=False)
    t.loc[(t.is_rush == 0) & (t.yb <= 4), "yb"] = 4      # targets: one bucket inside the 5
    rate = t.groupby(["is_rush", "yb"]).td.mean()
    for b in range(4):                                     # fill the pooled bucket for lookup
        rate[(0, b)] = rate[(0, 4)]
    return rate, bins

def aggregate(t, rate, bins):
    t = t.copy()
    t["yb"] = pd.cut(t.yl, bins=bins, right=True, labels=False)
    t.loc[(t.is_rush == 0) & (t.yb <= 4), "yb"] = 4
    t["xtd"] = [rate.get((r, b), 0.0) for r, b in zip(t.is_rush, t.yb)]
    t["touch"] = 1
    t["car"] = t.is_rush; t["tgt"] = 1 - t.is_rush
    t["t_lead"] = t.lead; t["t_trail"] = t.trail
    t["t_lead7"] = t.lead7; t["t_trail7"] = t.trail7
    t["c_i10"] = t.i10; t["t_d3"] = t.d3
    F = ["touch", "car", "tgt", "t_lead", "t_trail", "t_lead7", "t_trail7",
         "c_i10", "t_d3", "td", "xtd"]
    pw = t.groupby(["season", "week", "team", "pid"])[F].sum().reset_index()
    tw = t.groupby(["season", "week", "team"])[F].sum().reset_index()
    m = pw.merge(tw, on=["season", "week", "team"], suffixes=("", "_tm"))
    m["g"] = 1
    return m, F

def build_lookup(m, F):
    """(season,pid) -> sorted [(week, cumulative dict INCLUDING that week)]."""
    cols = F + [f + "_tm" for f in F] + ["g"]
    look = {}
    m = m.sort_values(["season", "pid", "week"])
    for (s, pid), grp in m.groupby(["season", "pid"]):
        cum = {c: 0.0 for c in cols}
        lst = []
        for r in grp.itertuples(index=False):
            d = r._asdict()
            for c in cols:
                cum[c] += float(d[c])
            lst.append((int(r.week), dict(cum)))
        look[(s, pid)] = lst
    return look

def std_before(look, Y, pid, wk):
    lst = look.get((Y, pid))
    if not lst:
        return None
    best = None
    for w, cum in lst:
        if w < wk:
            best = cum
        else:
            break
    return best

def season_total(look, Y, pid):
    lst = look.get((Y, pid))
    return lst[-1][1] if lst else None

def sh(a, b):
    return a / b if b > 0 else None

def metrics(c):
    """role metrics from a cumulative dict (None where undefined)."""
    if c is None or c["touch"] < 1:
        return None
    ts = sh(c["touch"], c["touch_tm"]); cs = sh(c["car"], c["car_tm"]); gs = sh(c["tgt"], c["tgt_tm"])
    ls = sh(c["t_lead"], c["t_lead_tm"]); trs = sh(c["t_trail"], c["t_trail_tm"])
    l7 = sh(c["t_lead7"], c["t_lead7_tm"]); tr7 = sh(c["t_trail7"], c["t_trail7_tm"])
    d3 = sh(c["t_d3"], c["t_d3_tm"]); i10 = sh(c["c_i10"], c["c_i10_tm"])
    out = {"n": c["touch"], "g": c["g"], "touch_share": ts}
    out["pass_role"] = (gs - cs) if (gs is not None and cs is not None) else None
    out["tilt"] = (ls - trs) if (ls is not None and trs is not None) else None
    out["tilt7"] = (l7 - tr7) if (l7 is not None and tr7 is not None) else None
    out["d3_gap"] = (d3 - ts) if (d3 is not None and ts is not None) else None
    out["rz_gap"] = (i10 - cs) if (i10 is not None and cs is not None) else None
    out["td_luck"] = (c["xtd"] - c["td"]) / max(1.0, c["g"])
    return out

METRICS = ["touch_share", "pass_role", "tilt", "tilt7", "d3_gap", "rz_gap", "td_luck"]

def shrink(cur, prior):
    """touch-weighted blend of season-to-date and prior-season profile.
    Without a prior, shrink toward league-neutral 0 (touch_share -> its own value)."""
    out = {}
    n = cur["n"] if cur else 0.0
    for k in METRICS:
        cv = cur.get(k) if cur else None
        pv = prior.get(k) if prior else None
        neutral = 0.0
        if k == "td_luck":
            # luck resets every season: no prior, shrink to 0 by games
            out[k] = (cv or 0.0) * (n / (n + PRIOR_TOUCHES)) if cv is not None else 0.0
            continue
        if pv is None:
            pv = neutral if k != "touch_share" else cv
        if cv is None and pv is None:
            out[k] = None
        elif cv is None:
            out[k] = pv
        else:
            out[k] = (n * cv + PRIOR_TOUCHES * pv) / (n + PRIOR_TOUCHES)
    return out

# ---------------------------------------------------------------- lines
def implied_map(lines):
    """(team, week) -> (implied, oppImplied); sign auto-validated like the engine test."""
    g = lines
    out = {}
    best = None
    for sign in (1, -1):
        hi = (g.total_line + sign * g.spread_line) / 2
        ai = (g.total_line - sign * g.spread_line) / 2
        c = np.corrcoef(np.concatenate([hi, ai]),
                        np.concatenate([g.home_score, g.away_score]))[0, 1]
        if best is None or c > best[0]:
            best = (c, sign)
    sign = best[1]
    for gid, r in g.iterrows():
        hi = (r.total_line + sign * r.spread_line) / 2
        ai = (r.total_line - sign * r.spread_line) / 2
        out[(tm(r.home_team), int(r.week))] = (hi, ai)
        out[(tm(r.away_team), int(r.week))] = (ai, hi)
    return out

# ---------------------------------------------------------------- grading
def mse(pred, act): return float(((pred - act) ** 2).mean())
def mae(pred, act): return float(np.abs(pred - act).mean())

def loyo(S, years, grid, predfn, label):
    """LOYO: pick the grid value on the other years, apply to the held year."""
    act = S["act"]
    per_year = {}
    for v in grid:
        pred = predfn(v)
        per_year[v] = {y: mse(pred[S["year"] == y], act[S["year"] == y]) for y in years}
    ship = per_year[grid[0]]
    tot = 0.0; n = 0; wins = 0; picks = []
    for y in years:
        m = S["year"] == y
        best = min(grid, key=lambda v: sum(per_year[v][yy] for yy in years if yy != y))
        picks.append(best)
        pred = predfn(best)
        e = mse(pred[m], act[m]); tot += e * m.sum(); n += m.sum()
        wins += e < ship[y]
    pooled_best = min(grid, key=lambda v: sum(per_year[v].values()))
    base_mse = sum(ship[y] * (S["year"] == y).sum() for y in years) / n
    print(f"  {label}")
    print(f"    grid pooled MSE: " + "  ".join(f"{v:+.2f}:{sum(per_year[v].values())/len(years):.3f}" for v in grid))
    print(f"    pooled best {pooled_best:+.2f} | LOYO MSE {tot/n:.4f} vs shipped {base_mse:.4f} "
          f"({(tot/n/base_mse-1)*100:+.2f}%), years better {wins}/{len(years)}, picks {picks}")
    return pooled_best, tot / n - base_mse

def zscore(x, clip=2.5):
    x = np.asarray(x, float)
    ok = ~np.isnan(x)
    s = x[ok].std() if ok.sum() > 10 else 1.0
    z = np.where(ok, x / (s if s > 0 else 1.0), 0.0)
    return np.clip(z, -clip, clip), s

def main():
    rb_ids, by_norm = load_players()
    frames = {}; lines_all = {}
    for Y in LOAD_YEARS:
        t, lines = load_touches(Y, rb_ids)
        frames[Y] = t; lines_all[Y] = lines
        print(f"  pbp {Y}: {len(t)} RB touches, {len(lines)} games with lines")
    allt = pd.concat(frames.values(), ignore_index=True)
    rate, bins = xtd_rates(allt)
    print("  xTD rates (rush): " + "  ".join(f"<={bins[i+1]}:{rate.get((1,i),0):.3f}" for i in range(len(bins)-1)))
    print("  xTD rates (tgt) : " + "  ".join(f"<={bins[i+1]}:{rate.get((0,i),0):.3f}" for i in range(len(bins)-1)))
    m, F = aggregate(allt, rate, bins)
    look = build_lookup(m, F)

    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    S = defaultdict(list)
    miss = defaultdict(int)
    for Y in YEARS:
        if str(Y) not in clay_hist:
            continue
        imp = implied_map(lines_all[Y])
        avg = float(np.mean([v[0] for v in imp.values()]))
        W = 16 if Y <= 2020 else 17
        for name, c in clay_hist[str(Y)].items():
            if c.get("pos") != "RB" or (c.get("pts") or 0) < POOL_MIN_PTS:
                continue
            wrec = weekly_rec(name, "RB")
            if wrec is None:
                miss["weekly"] += 1; continue
            team = infer_team(wrec, Y)
            if not team:
                miss["team"] += 1; continue
            pid = resolve_gsis(by_norm, name, Y)
            if pid is None:
                miss["gsis"] += 1; continue
            prior = metrics(season_total(look, Y - 1, pid))
            if prior and prior["n"] < 50:
                prior = None
            rows = sorted([(w["wk"], w["fpts"]) for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            hist = []
            for wk, fpts in rows:
                li = imp.get((team, wk))
                if li is not None and hist:
                    g = len(hist)
                    base = (P * clay_pg + g * (sum(hist) / g)) / (P + g)
                    cur = metrics(std_before(look, Y, pid, wk))
                    role = shrink(cur, prior)
                    if (cur is None or cur["n"] < 1) and prior is None:
                        hist.append(fpts); miss["norole"] += 1; continue
                    S["year"].append(Y); S["base"].append(base); S["act"].append(fpts)
                    S["dev"].append((li[0] - avg) / avg)
                    S["spread"].append((li[0] - li[1]) / avg)     # + = favored
                    S["g"].append(g); S["n_std"].append(cur["n"] if cur else 0.0)
                    for k in METRICS:
                        S[k].append(np.nan if role.get(k) is None else role[k])
                hist.append(fpts)
        print(f"  {Y}: lgAvg implied {avg:.1f}, samples so far {len(S['act'])}")
    print(f"  skipped: {dict(miss)}")

    S = {k: np.array(v, float) for k, v in S.items()}
    S["year"] = S["year"].astype(int)
    years = sorted(set(S["year"]))
    act, base, dev, spread = S["act"], S["base"], S["dev"], S["spread"]
    shipped = base * np.clip(1 + E_SHIP * dev, 0.7, 1.35)
    print(f"\n{len(act)} RB player-weeks 2019-25 with base + lines + role profile")
    print(f"  MSE base-only {mse(base, act):.4f} | shipped (e=.50) {mse(shipped, act):.4f} | MAE shipped {mae(shipped, act):.4f}")

    # ---- 1. residual by tercile
    print("\n=== 1. actual / shipped by metric tercile (is the metric new information?) ===")
    resid = act / np.maximum(shipped, 0.5)
    for k in METRICS:
        x = S[k]; ok = ~np.isnan(x)
        if ok.sum() < 300:
            print(f"  {k}: too few ({ok.sum()})"); continue
        q = np.quantile(x[ok], [1/3, 2/3])
        parts = []
        for lo, hi, lab in ((-np.inf, q[0], "low"), (q[0], q[1], "mid"), (q[1], np.inf, "high")):
            mm = ok & (x >= lo) & (x < hi)
            parts.append(f"{lab} {x[mm].mean():+.3f}: {act[mm].mean()/shipped[mm].mean():.3f} (n={mm.sum()})")
        r = np.corrcoef(x[ok], (act[ok] - shipped[ok]))[0, 1]
        print(f"  {k:12s} " + " | ".join(parts) + f"   corr(x, act-shipped) {r:+.3f}")

    # ---- 2. empirical elasticity inside role terciles
    print("\n=== 2. empirical Vegas elasticity by role tercile (slope of actual/base vs implied dev; vs spread) ===")
    edges = [-1, -.15, -.08, -.03, .03, .08, .15, 1]
    def slope(mask, x):
        xs, ys = [], []
        for i in range(len(edges) - 1):
            mm = mask & (x >= edges[i]) & (x < edges[i + 1])
            if mm.sum() < 150:
                continue
            xs.append(x[mm].mean()); ys.append(act[mm].mean() / base[mm].mean())
        return (np.polyfit(xs, ys, 1)[0], len(xs)) if len(xs) >= 3 else (np.nan, len(xs))
    for k in ("tilt", "tilt7", "pass_role", "rz_gap", "touch_share"):
        x = S[k]; ok = ~np.isnan(x)
        q = np.quantile(x[ok], [1/3, 2/3])
        line = f"  {k:11s}"
        for lo, hi, lab in ((-np.inf, q[0], "low"), (q[0], q[1], "mid"), (q[1], np.inf, "high")):
            mm = ok & (x >= lo) & (x < hi)
            si, ni = slope(mm, dev); ss, ns = slope(mm, spread)
            line += f" | {lab}: e_implied {si:.2f} e_spread {ss:.2f} (n={mm.sum()})"
        print(line)
    si, _ = slope(np.ones_like(act, bool), dev); ss, _ = slope(np.ones_like(act, bool), spread)
    print(f"  ALL RB      e_implied {si:.2f}  e_spread {ss:.2f}")

    # ---- 3. LOYO sweeps
    print("\n=== 3. LOYO MSE sweeps (grid[0] = shipped, negative delta = better) ===")
    tilt_z, s_tilt = zscore(S["tilt"]); tilt7_z, _ = zscore(S["tilt7"])
    pr_z, s_pr = zscore(S["pass_role"]); rz_z, s_rz = zscore(S["rz_gap"]); d3_z, _ = zscore(S["d3_gap"])
    luck = np.nan_to_num(S["td_luck"]); rzg = np.nan_to_num(S["rz_gap"])
    print(f"  metric sds: tilt {s_tilt:.3f}  pass_role {s_pr:.3f}  rz_gap {s_rz:.3f}")
    results = {}
    grid = [0.0, -0.3, -0.2, -0.1, 0.1, 0.2, 0.3, 0.4]
    results["a"] = loyo(S, years, grid,
        lambda e1: base * np.clip(1 + (E_SHIP + e1 * tilt_z) * dev, 0.7, 1.35),
        "a) role-dependent implied elasticity: e = 0.50 + e1*tilt_z")
    results["a7"] = loyo(S, years, grid,
        lambda e1: base * np.clip(1 + (E_SHIP + e1 * tilt7_z) * dev, 0.7, 1.35),
        "a7) same with tilt7_z")
    results["ap"] = loyo(S, years, grid,
        lambda e1: base * np.clip(1 + (E_SHIP - e1 * pr_z) * dev, 0.7, 1.35),
        "ap) e = 0.50 - e1*pass_role_z (passing-down backs less Vegas-elastic)")
    grid_s = [0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0]
    results["b"] = loyo(S, years, grid_s,
        lambda s: shipped * np.clip(1 + s * spread * tilt_z, 0.7, 1.35),
        "b) spread x tilt interaction on top of shipped: x(1 + s*spreadFrac*tilt_z)")
    results["b7"] = loyo(S, years, grid_s,
        lambda s: shipped * np.clip(1 + s * spread * tilt7_z, 0.7, 1.35),
        "b7) spread x tilt7")
    results["c"] = loyo(S, years, grid_s,
        lambda s: shipped * np.clip(1 - s * spread * pr_z, 0.7, 1.35),
        "c) spread x pass_role: passing-down backs gain as underdogs, x(1 - s*spreadFrac*passRole_z)")
    results["c3"] = loyo(S, years, grid_s,
        lambda s: shipped * np.clip(1 - s * spread * d3_z, 0.7, 1.35),
        "c3) spread x d3_gap (3rd-down/2-min share)")
    grid_k = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]
    wreal = S["g"] / (P + S["g"])
    results["d"] = loyo(S, years, grid_k,
        lambda k: shipped + k * 6.0 * luck * wreal,
        "d) TD-luck correction: + k * 6 * (xTD - TD)/g * realizedWeight")
    # level check: is the gain just "add points to an under-projecting model"?
    luck_c = luck.copy()
    for y in years:
        mm = S["year"] == y
        luck_c[mm] = luck[mm] - luck[mm].mean()
    print(f"  td_luck mean {luck.mean():+.4f}/g (overall), by year: " +
          " ".join(f"{y}:{luck[S['year']==y].mean():+.3f}" for y in years))
    results["dc"] = loyo(S, years, grid_k,
        lambda k: shipped + k * 6.0 * luck_c * wreal,
        "dc) TD-luck CENTERED per season (pure mean reversion, no level effect)")
    lvl = float((act - shipped).mean())
    results["dl"] = loyo(S, years, grid_k,
        lambda k: shipped + k * 6.0 * luck * wreal + (lvl if k > 0 else 0.0),
        f"dl) TD-luck + flat level shift {lvl:+.2f} (does luck add beyond a level fix?)")
    results["l0"] = loyo(S, years, [0.0, 1.0],
        lambda k: shipped + k * lvl,
        "l0) flat level shift alone (reference)")
    grid_r = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]
    results["e"] = loyo(S, years, grid_r,
        lambda r: shipped * np.clip(1 + r * rzg, 0.7, 1.35),
        "e) goal-line share multiplier: x(1 + r * rz_gap)")
    # combination of whatever helped
    best_a = results["a"][0] if results["a"][1] < 0 else 0.0
    best_c = results["c"][0] if results["c"][1] < 0 else 0.0
    best_d = results["d"][0] if results["d"][1] < 0 else 0.0
    best_e = results["e"][0] if results["e"][1] < 0 else 0.0
    comb = base * np.clip(1 + (E_SHIP + best_a * tilt_z) * dev, 0.7, 1.35)
    comb = comb * np.clip(1 - best_c * spread * pr_z, 0.7, 1.35) * np.clip(1 + best_e * rzg, 0.7, 1.35)
    comb = comb + best_d * 6.0 * luck * wreal
    print(f"\n  COMBINED (a {best_a:+.2f}, c {best_c:.2f}, d {best_d:.2f}, e {best_e:.2f}) pooled: "
          f"MSE {mse(comb, act):.4f} vs shipped {mse(shipped, act):.4f} ({(mse(comb,act)/mse(shipped,act)-1)*100:+.2f}%), "
          f"MAE {mae(comb, act):.4f} vs {mae(shipped, act):.4f}")
    for y in years:
        mm = S["year"] == y
        print(f"    {y}: shipped {mse(shipped[mm], act[mm]):.3f} -> combined {mse(comb[mm], act[mm]):.3f}  (n={mm.sum()})")

    # ---- 4. sample-depth cut: does it need a few weeks of data?
    print("\n=== 4. combined delta by season-to-date touches (does the role need data?) ===")
    for lo, hi in ((0, 30), (30, 80), (80, 160), (160, 9999)):
        mm = (S["n_std"] >= lo) & (S["n_std"] < hi)
        if mm.sum() < 200: continue
        print(f"  touches {lo}-{hi}: n={mm.sum()}  shipped {mse(shipped[mm], act[mm]):.3f}  combined {mse(comb[mm], act[mm]):.3f}")

if __name__ == "__main__":
    main()
