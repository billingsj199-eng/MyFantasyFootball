#!/usr/bin/env python3
"""
TARGET-AREA MATCHUP backtest, 2019-2025 (Jack 2026-09-14: "backtest the
target-area matchup next").

Idea: defenses leak in specific AREAS of the field (deep / intermediate /
short / behind the LOS; left / middle / right) and receivers get their
targets from specific areas, so a deep-ball WR against a deep-leaky defense
should beat a projection that only knows position-level points allowed.

Everything from nflverse pbp (air_yards, pass_location, completion, yards,
TD per target) SEASON-TO-DATE (weeks < W) — the live engine could rebuild it
nightly. Grading harness = every other Sim Lab layer: P=5 Clay/PPG base x
shipped Vegas (WR/TE e=.25) x shipped in-season FPA layer (e=.25, trust
min(1,g/8), clamp [0.8,1.25]) = "shipped"; LOYO sweeps; WR + TE.

Defense zone metric  r_z = pts allowed per target in zone z (half-PPR rec pts)
                           / league pts per target in zone z (same season),
                           shrunk toward 1 with a K_DEF-target prior
Player zone profile  w_z = share of his targets from zone z, season-to-date
                           shrunk toward his prior-season mix (K_PLR targets)
Matchup              M    = sum_z w_z r_z / r_all      (r_all = the defense's
                           overall pts/tgt ratio — what position FPA already
                           prices; M isolates the ZONE interaction)
Funnel               F    = sum_z w_z (s_z / s_z_lg)   (s_z = share of the
                           defense's targets faced that land in zone z — do
                           defenses push volume toward a receiver's areas?)

GATES first (the man/zone lesson):
  G1 player zone mix persists YoY?        (deep share, behind-LOS share)
  G2 defense zone residual persists in-season (wk<=8 -> wk>=9) and YoY?
Then bucket tables and LOYO sweeps on M (depth), M (side), F, and M x F.

Usage: python backtest_target_area.py   (~3 min)
"""
import numpy as np
import pandas as pd
import json, os, sys, io
from collections import defaultdict
from backtest_sim_calibration import (played, weekly_rec, infer_team,
                                      POOL_MIN_PTS, OPP_ALIAS, WEEKLY)
import backtest_sim_calibration as cal
from backtest_snap_defense import build_fpa

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CACHE = r"E:\MyFantasyFootball\pbp_cache"
P = 5
YEARS = range(2019, 2026)
LOAD_YEARS = range(2018, 2026)
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS",
         "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
def tm(t): return ALIAS.get(t, t)
VEGAS_E = {"WR": 0.25, "TE": 0.25, "RB": 0.50, "QB": 0.25}
FPA_E, FPA_TRUST_G = 0.25, 8
K_DEF = 60.0      # defense zone rate prior weight (targets)
K_PLR = 40.0      # player zone mix prior weight (targets)
DEPTH = ["bl", "sh", "in", "dp"]
SIDE = ["left", "middle", "right"]
POS_TEST = ("WR", "TE")

PBP_COLS = ["game_id", "season_type", "week", "posteam", "defteam", "home_team", "away_team",
            "home_score", "away_score", "spread_line", "total_line", "pass_attempt", "sack",
            "receiver_player_id", "air_yards", "pass_location", "complete_pass",
            "yards_gained", "pass_touchdown"]

def load_players():
    p = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False,
                    usecols=["gsis_id", "display_name", "position", "rookie_season", "last_season"])
    p = p.dropna(subset=["gsis_id"])
    by_norm = defaultdict(list)
    for r in p[p.position.isin(["WR", "TE", "RB"])].itertuples(index=False):
        by_norm[(cal.norm(str(r.display_name)), r.position)].append(
            (r.gsis_id, r.rookie_season if pd.notna(r.rookie_season) else 0,
             r.last_season if pd.notna(r.last_season) else 9999))
    return by_norm

def resolve_gsis(by_norm, name, pos, Y):
    c = [x for x in by_norm.get((cal.norm(name), pos), []) if x[1] <= Y <= x[2] + 1]
    return c[0][0] if len(c) == 1 else None

def load_targets(year):
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{year}.csv.gz"),
                     usecols=PBP_COLS, low_memory=False)
    df = df[(df.season_type == "REG") & df.posteam.notna()]
    lines = df.dropna(subset=["spread_line", "total_line"]).groupby("game_id").first()
    t = df[(df.pass_attempt == 1) & df.receiver_player_id.notna() & (df.sack != 1)
           & df.air_yards.notna() & df.pass_location.isin(SIDE)].copy()
    t["season"] = year
    t["def"] = t.defteam.map(tm)
    t["pid"] = t.receiver_player_id
    t["depth"] = pd.cut(t.air_yards, [-100, -0.01, 9.99, 19.99, 200], labels=DEPTH).astype(str)
    t["side"] = t.pass_location
    comp = t.complete_pass.fillna(0)
    t["pts"] = 0.5 * comp + 0.1 * t.yards_gained.fillna(0) * comp + 6 * t.pass_touchdown.fillna(0)
    return t[["season", "week", "def", "pid", "depth", "side", "pts"]], lines

def implied_map(lines):
    g = lines; best = None
    for sign in (1, -1):
        hi = (g.total_line + sign * g.spread_line) / 2
        ai = (g.total_line - sign * g.spread_line) / 2
        c = np.corrcoef(np.concatenate([hi, ai]), np.concatenate([g.home_score, g.away_score]))[0, 1]
        if best is None or c > best[0]:
            best = (c, sign)
    sign = best[1]; out = {}
    for gid, r in g.iterrows():
        hi = (r.total_line + sign * r.spread_line) / 2
        ai = (r.total_line - sign * r.spread_line) / 2
        out[(tm(r.home_team), int(r.week))] = hi
        out[(tm(r.away_team), int(r.week))] = ai
    return out

# ---------------------------------------------------------------- cumulative structures
def cum_by_week(df, keys, zone_col):
    """{key: sorted [(week, {'n': {z: tgt}, 'p': {z: pts}, 'N': tgt, 'P': pts})]} cumulative."""
    agg = df.groupby(keys + ["week", zone_col]).pts.agg(["count", "sum"]).reset_index()
    out = {}
    for key, grp in agg.groupby(keys):
        key = key if isinstance(key, tuple) else (key,)
        cum = {"n": defaultdict(float), "p": defaultdict(float), "N": 0.0, "P": 0.0}
        lst = []
        for wk, g2 in grp.groupby("week"):
            for r in g2.itertuples(index=False):
                z = getattr(r, zone_col)
                cum["n"][z] += r.count; cum["p"][z] += r.sum
                cum["N"] += r.count; cum["P"] += r.sum
            lst.append((int(wk), {"n": dict(cum["n"]), "p": dict(cum["p"]), "N": cum["N"], "P": cum["P"]}))
        out[key] = lst
    return out

def before(lst, wk):
    best = None
    for w, c in lst or []:
        if w < wk: best = c
        else: break
    return best

def league_rates(df, zone_col):
    """(season, zone) -> pts per target; (season, zone) -> share of targets."""
    g = df.groupby(["season", zone_col]).pts.agg(["count", "sum"])
    tot = df.groupby("season").pts.count()
    rate = {(s, z): r["sum"] / r["count"] for (s, z), r in g.iterrows()}
    share = {(s, z): r["count"] / tot[s] for (s, z), r in g.iterrows()}
    return rate, share

def def_ratios(c, Y, zones, lg_rate, lg_share):
    """r_z (shrunk pts/tgt ratio), s_z/s_lg (shrunk funnel ratio), r_all."""
    if not c or c["N"] < 1:
        return None
    r, f = {}, {}
    for z in zones:
        n = c["n"].get(z, 0.0); p = c["p"].get(z, 0.0)
        lr = lg_rate[(Y, z)]
        raw = (p / n / lr) if n > 0 else 1.0
        r[z] = (n * raw + K_DEF * 1.0) / (n + K_DEF)
        sh = (n / c["N"]) / lg_share[(Y, z)] if c["N"] > 0 else 1.0
        f[z] = (c["N"] * sh + K_DEF * 1.0) / (c["N"] + K_DEF)
    lg_all = sum(lg_rate[(Y, z)] * lg_share[(Y, z)] for z in zones)
    r_all = (c["N"] * (c["P"] / c["N"] / lg_all) + K_DEF) / (c["N"] + K_DEF)
    return r, f, r_all

def player_mix(cur, prior, zones, lg_share_Y):
    """w_z: season-to-date target mix shrunk toward prior-season mix (else league mix)."""
    n = cur["N"] if cur else 0.0
    w = {}
    for z in zones:
        cv = (cur["n"].get(z, 0.0) / n) if n > 0 else None
        pv = (prior["n"].get(z, 0.0) / prior["N"]) if (prior and prior["N"] >= 30) else lg_share_Y[z]
        w[z] = pv if cv is None else (n * cv + K_PLR * pv) / (n + K_PLR)
    s = sum(w.values()) or 1.0
    return {z: w[z] / s for z in zones}

def mse(a, b): return float(((a - b) ** 2).mean())

def loyo(S, years, grid, predfn, label):
    act = S["act"]; per = {}
    for v in grid:
        pred = predfn(v)
        per[v] = {y: mse(pred[S["year"] == y], act[S["year"] == y]) for y in years}
    ship = per[grid[0]]; tot = n = wins = 0; picks = []
    for y in years:
        m = S["year"] == y
        best = min(grid, key=lambda v: sum(per[v][yy] for yy in years if yy != y))
        picks.append(best); e = mse(predfn(best)[m], act[m])
        tot += e * m.sum(); n += m.sum(); wins += e < ship[y]
    pooled_best = min(grid, key=lambda v: sum(per[v].values()))
    base_mse = sum(ship[y] * (S["year"] == y).sum() for y in years) / n
    print(f"  {label}")
    print("    grid pooled MSE: " + "  ".join(f"{v:+.2f}:{sum(per[v].values())/len(years):.3f}" for v in grid))
    print(f"    pooled best {pooled_best:+.2f} | LOYO MSE {tot/n:.4f} vs shipped {base_mse:.4f} "
          f"({(tot/n/base_mse-1)*100:+.2f}%), years better {wins}/{len(years)}, picks {picks}")
    return pooled_best, tot / n - base_mse

def main():
    by_norm = load_players()
    frames, lines_all = {}, {}
    for Y in LOAD_YEARS:
        t, lines = load_targets(Y); frames[Y] = t; lines_all[Y] = lines
        print(f"  pbp {Y}: {len(t)} targets with air yards + location")
    allt = pd.concat(frames.values(), ignore_index=True)
    lg_rate_d, lg_share_d = league_rates(allt, "depth")
    lg_rate_s, lg_share_s = league_rates(allt, "side")
    print("  league pts/tgt by depth (2025): " + "  ".join(f"{z} {lg_rate_d[(2025,z)]:.2f} ({lg_share_d[(2025,z)]*100:.0f}%)" for z in DEPTH))
    print("  league pts/tgt by side  (2025): " + "  ".join(f"{z} {lg_rate_s[(2025,z)]:.2f} ({lg_share_s[(2025,z)]*100:.0f}%)" for z in SIDE))
    def_d = cum_by_week(allt, ["season", "def"], "depth")
    def_s = cum_by_week(allt, ["season", "def"], "side")
    plr_d = cum_by_week(allt, ["season", "pid"], "depth")
    plr_s = cum_by_week(allt, ["season", "pid"], "side")

    # ---------------- GATES
    print("\n=== G1. player zone mix persistence (YoY, >=40 targets both seasons) ===")
    for zc, store, zones in (("depth", plr_d, DEPTH), ("side", plr_s, SIDE)):
        for z in zones:
            a, b = [], []
            for (Y, pid), lst in store.items():
                if (Y + 1, pid) not in store: continue
                c0, c1 = lst[-1][1], store[(Y + 1, pid)][-1][1]
                if c0["N"] >= 40 and c1["N"] >= 40:
                    a.append(c0["n"].get(z, 0) / c0["N"]); b.append(c1["n"].get(z, 0) / c1["N"])
            print(f"  {zc} {z:6s} share YoY r={np.corrcoef(a,b)[0,1]:+.2f} (n={len(a)}, sd {np.std(a):.3f})")
    print("\n=== G2. defense zone RESIDUAL persistence (pts/tgt ratio in zone / overall ratio) ===")
    for zc, store, zones, lgr, lgs in (("depth", def_d, DEPTH, lg_rate_d, lg_share_d), ("side", def_s, SIDE, lg_rate_s, lg_share_s)):
        for z in zones:
            e, l, y0, y1 = [], [], [], []
            for (Y, d), lst in store.items():
                if Y < 2019: continue
                c8 = before(lst, 9); cE = lst[-1][1]
                if not c8: continue
                # late-season only = full minus through-8
                nl = cE["n"].get(z, 0) - c8["n"].get(z, 0); pl = cE["p"].get(z, 0) - c8["p"].get(z, 0)
                Nl = cE["N"] - c8["N"]; Pl = cE["P"] - c8["P"]
                n8 = c8["n"].get(z, 0); p8 = c8["p"].get(z, 0)
                if n8 < 20 or nl < 20: continue
                lg_all = sum(lgr[(Y, zz)] * lgs[(Y, zz)] for zz in zones)
                e.append((p8 / n8 / lgr[(Y, z)]) / (c8["P"] / c8["N"] / lg_all))
                l.append((pl / nl / lgr[(Y, z)]) / (Pl / Nl / lg_all))
                if (Y + 1, d) in store:
                    cN = store[(Y + 1, d)][-1][1]; nN = cN["n"].get(z, 0)
                    if nN >= 20:
                        lg_allN = sum(lgr[(Y + 1, zz)] * lgs[(Y + 1, zz)] for zz in zones)
                        y0.append((cE["p"].get(z, 0) / cE["n"].get(z, 1) / lgr[(Y, z)]) / (cE["P"] / cE["N"] / lg_all))
                        y1.append((cN["p"].get(z, 0) / nN / lgr[(Y + 1, z)]) / (cN["P"] / cN["N"] / lg_allN))
            print(f"  {zc} {z:6s} early->late r={np.corrcoef(e,l)[0,1]:+.2f} (n={len(e)}, sd early {np.std(e):.3f})   YoY r={np.corrcoef(y0,y1)[0,1]:+.2f} (n={len(y0)})")
    print("\n=== G2b. defense zone FUNNEL persistence (share of targets faced in zone) ===")
    for zc, store, zones in (("depth", def_d, DEPTH), ("side", def_s, SIDE)):
        for z in zones:
            e, l = [], []
            for (Y, d), lst in store.items():
                if Y < 2019: continue
                c8 = before(lst, 9); cE = lst[-1][1]
                if not c8 or cE["N"] - c8["N"] < 50: continue
                e.append(c8["n"].get(z, 0) / c8["N"]); l.append((cE["n"].get(z, 0) - c8["n"].get(z, 0)) / (cE["N"] - c8["N"]))
            print(f"  {zc} {z:6s} early->late r={np.corrcoef(e,l)[0,1]:+.2f} (n={len(e)}, sd {np.std(e):.3f})")

    # ---------------- samples
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    weekly_fpa, season_fpa, lg_fpa = build_fpa()
    S = defaultdict(list); miss = defaultdict(int)
    for Y in YEARS:
        if str(Y) not in clay_hist: continue
        imp = implied_map(lines_all[Y]); avg = float(np.mean(list(imp.values())))
        W = 16 if Y <= 2020 else 17
        lgsd = {z: lg_share_d[(Y, z)] for z in DEPTH}; lgss = {z: lg_share_s[(Y, z)] for z in SIDE}
        for name, c in clay_hist[str(Y)].items():
            pos = c.get("pos")
            if pos not in POS_TEST or (c.get("pts") or 0) < POOL_MIN_PTS: continue
            wrec = weekly_rec(name, pos)
            if wrec is None: miss["weekly"] += 1; continue
            team = infer_team(wrec, Y)
            if not team: miss["team"] += 1; continue
            pid = resolve_gsis(by_norm, name, pos, Y)
            if pid is None: miss["gsis"] += 1; continue
            prior_d = plr_d.get((Y - 1, pid)); prior_d = prior_d[-1][1] if prior_d else None
            prior_s = plr_s.get((Y - 1, pid)); prior_s = prior_s[-1][1] if prior_s else None
            rows = sorted([(w["wk"], w["fpts"], OPP_ALIAS.get(w.get("opp"), w.get("opp")))
                           for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            hist = []
            for wk, fpts, opp in rows:
                li = imp.get((team, wk))
                if li is not None and hist and opp:
                    g = len(hist)
                    base = (P * clay_pg + g * (sum(hist) / g)) / (P + g)
                    veg = min(1.35, max(0.7, 1 + VEGAS_E[pos] * (li - avg) / avg))
                    cur = weekly_fpa.get((Y, opp, pos), {}); past = [w for w in cur if w < wk]
                    fpa = 1.0
                    if past and lg_fpa.get((Y, pos)):
                        ratio = min(1.25, max(0.8, (sum(cur[w] for w in past) / len(past)) / lg_fpa[(Y, pos)]))
                        fpa = 1 + FPA_E * (ratio - 1) * min(1, len(past) / FPA_TRUST_G)
                    dd = def_ratios(before(def_d.get((Y, opp)), wk), Y, DEPTH, lg_rate_d, lg_share_d)
                    ds = def_ratios(before(def_s.get((Y, opp)), wk), Y, SIDE, lg_rate_s, lg_share_s)
                    if dd is None or ds is None: hist.append(fpts); miss["nodef"] += 1; continue
                    cur_d = before(plr_d.get((Y, pid)), wk); cur_s = before(plr_s.get((Y, pid)), wk)
                    wd = player_mix(cur_d, prior_d, DEPTH, lgsd); ws = player_mix(cur_s, prior_s, SIDE, lgss)
                    rd, fd, rall = dd; rs, fs, _ = ds
                    S["year"].append(Y); S["pos"].append(pos); S["base"].append(base); S["act"].append(fpts)
                    S["veg"].append(veg); S["fpa"].append(fpa)
                    S["Md"].append(sum(wd[z] * rd[z] for z in DEPTH) / rall)
                    S["Ms"].append(sum(ws[z] * rs[z] for z in SIDE) / rall)
                    S["Fd"].append(sum(wd[z] * fd[z] for z in DEPTH))
                    S["Fs"].append(sum(ws[z] * fs[z] for z in SIDE))
                    S["Rall"].append(rall)
                    S["deep_w"].append(wd["dp"]); S["deep_r"].append(rd["dp"]); S["bl_w"].append(wd["bl"]); S["bl_r"].append(rd["bl"])
                    S["mid_w"].append(ws["middle"]); S["mid_r"].append(rs["middle"])
                    S["defN"].append(before(def_d.get((Y, opp)), wk)["N"])
                    S["ntgt"].append(cur_d["N"] if cur_d else 0.0)
                hist.append(fpts)
        print(f"  {Y}: samples so far {len(S['act'])}")
    print(f"  skipped: {dict(miss)}")
    S = {k: (np.array(v) if k == "pos" else np.array(v, float)) for k, v in S.items()}
    S["year"] = S["year"].astype(int); years = sorted(set(S["year"]))
    act, base = S["act"], S["base"]
    shipped = base * S["veg"] * S["fpa"]
    print(f"\n{len(act)} WR/TE player-weeks | MSE base {mse(base,act):.4f} | base*Vegas {mse(base*S['veg'],act):.4f} | shipped (+FPA) {mse(shipped,act):.4f}")

    # ---------------- 1. bucket tables
    print("\n=== 1. actual/shipped: player DEEP share tercile x defense DEEP ratio tercile (defN>=150) ===")
    ok = S["defN"] >= 150
    qw = np.quantile(S["deep_w"][ok], [1/3, 2/3]); qr = np.quantile(S["deep_r"][ok], [1/3, 2/3])
    def terc(x, q): return np.where(x < q[0], 0, np.where(x < q[1], 1, 2))
    tw, tr = terc(S["deep_w"], qw), terc(S["deep_r"], qr)
    print(f"  deep_w cuts {qw.round(3)}  deep_r cuts {qr.round(3)}")
    print("  rows = player deep share (low/mid/high); cols = defense deep ratio (stingy/avg/leaky)")
    for i in range(3):
        cells = []
        for j in range(3):
            m = ok & (tw == i) & (tr == j)
            cells.append(f"{act[m].mean()/shipped[m].mean():.3f} (n={m.sum()})")
        print(f"    {['low ','mid ','high'][i]}: " + "  ".join(cells))
    for lab, key in (("Md depth matchup", "Md"), ("Ms side matchup", "Ms"), ("Fd depth funnel", "Fd"), ("Fs side funnel", "Fs"), ("Rall overall (FPA-like)", "Rall")):
        x = S[key]; q = np.quantile(x[ok], [.2, .4, .6, .8]); parts = []
        edges = [-np.inf] + list(q) + [np.inf]
        for k in range(5):
            m = ok & (x >= edges[k]) & (x < edges[k + 1])
            parts.append(f"{x[m].mean():.3f}->{act[m].mean()/shipped[m].mean():.3f}")
        r = np.corrcoef(x[ok], (act[ok] - shipped[ok]) / np.maximum(shipped[ok], 1))[0, 1]
        print(f"  {lab:24s} quintiles: " + " | ".join(parts) + f"   corr w/ rel resid {r:+.3f}")

    # ---------------- 2. LOYO sweeps
    print("\n=== 2. LOYO MSE sweeps on shipped (grid[0] = shipped) ===")
    grid = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]
    trust = np.minimum(1.0, S["defN"] / 200.0)
    res = {}
    for key, lab in (("Md", "a) depth matchup M_d: x(1 + e*trust*(Md-1))"),
                     ("Ms", "b) side matchup M_s"),
                     ("Fd", "c) depth funnel F_d"),
                     ("Fs", "d) side funnel F_s")):
        x = S[key]
        res[key] = loyo(S, years, grid, lambda e, x=x: shipped * np.clip(1 + e * trust * (x - 1), 0.8, 1.25), lab)
    res["MdFd"] = loyo(S, years, grid, lambda e: shipped * np.clip(1 + e * trust * (S["Md"] * S["Fd"] - 1), 0.8, 1.25),
                       "e) depth matchup x depth funnel")
    for pos in POS_TEST:
        m = S["pos"] == pos
        Sp = {k: v[m] for k, v in S.items()}
        shp = shipped[m]; tr_ = trust[m]
        print(f"  -- {pos} only ({m.sum()}) --")
        loyo(Sp, years, grid, lambda e: shp * np.clip(1 + e * tr_ * (Sp["Md"] - 1), 0.8, 1.25), f"   {pos} depth matchup")
        loyo(Sp, years, grid, lambda e: shp * np.clip(1 + e * tr_ * (Sp["Fd"] - 1), 0.8, 1.25), f"   {pos} depth funnel")
        loyo(Sp, years, grid, lambda e: shp * np.clip(1 + e * tr_ * (Sp["Ms"] - 1), 0.8, 1.25), f"   {pos} side matchup")
    # zone-level defense as a REPLACEMENT for position FPA (not on top of it)
    print("\n=== 3. zone-aware defense INSTEAD of position FPA: base*Vegas*(1 + e*trust*(sum w_z r_z - 1)) ===")
    bv = base * S["veg"]; raw = S["Md"] * S["Rall"]
    loyo(dict(S, act=act), years, grid, lambda e: bv * np.clip(1 + e * trust * (raw - 1), 0.8, 1.25), "   depth-weighted pts/tgt allowed (replaces FPA)")
    print(f"   reference: shipped FPA layer MSE {mse(shipped,act):.4f} vs no-FPA {mse(bv,act):.4f}")

if __name__ == "__main__":
    main()
