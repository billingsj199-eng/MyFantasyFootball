#!/usr/bin/env python3
"""
RUN-vs-PASS SNAP SPLIT backtest, 2019-2025 (Jack 2026-09-14: "backtest the run
vs pass snap split next" - "rbs most important but wrs and tes useful too").

What total snap share hides: WHICH plays a player is on the field for. From
nflverse participation (offense_players per play) x pbp play type we rebuild,
per player-week, snaps on PASS plays (qb_dropback) and snaps on designed RUN
plays, plus his targets and carries and the team totals. Season-to-date
(weeks < W) only. Live twin = PFF weekly offense/summary snap_counts_pass_play
/ snap_counts_run_play (the weekly puller would need to keep those columns).

Two families of hypotheses:

A. ROLE vs USAGE GAP (untested anywhere in the lab):
   route_gap = expected target share from his PASS snaps (pass snaps x his
               anchor targets-per-pass-snap / team targets) - actual target
               share.  + = on the field for passes but under-targeted so far
               -> targets should regress UP toward routes (routes are the
               sticky part, targets the noisy part).
   run_gap   = same for RUN snaps vs carry share (RB).
   Anchor TPRR / carries-per-run-snap = his PRIOR season (>= 100 / 60 snaps)
   else the position's league rate. Gate: do TPRR / CPRS persist YoY?

B. TREND DECOMPOSITION: the shipped snapMult uses the TOTAL snap-share trend
   (recent-3 weighted vs season avg, 1.0%/pt). Replace it with separate
   pass-snap and run-snap trend elasticities per position (a, b grid).
   TE pass-snap trend == the shipped routeMult, so TE is the control.

Harness = every other layer: P=5 Clay/PPG base x Vegas (pos e) x in-season
FPA layer x participation-based snapMult (the shipped design) = "shipped";
LOYO sweeps; RB / WR / TE reported separately.

Usage: python backtest_snap_split.py   (~4 min; 8 pbp + 8 participation files)
"""
import numpy as np
import pandas as pd
import json, os, sys, io
from collections import defaultdict
from backtest_sim_calibration import (played, weekly_rec, infer_team,
                                      POOL_MIN_PTS, OPP_ALIAS)
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
VEGAS_E = {"WR": 0.25, "TE": 0.25, "RB": 0.50}
FPA_E, FPA_TRUST_G = 0.25, 8
SNAP_W = [0.5, 0.3, 0.2]
SNAP_E = 1.0          # %/snap-pt, the shipped (bumped) snapMult
POS_TEST = ("RB", "WR", "TE")
F = ["ps", "rs", "tg", "ca"]   # pass snaps, run snaps, targets, carries

def load_players():
    p = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False,
                    usecols=["gsis_id", "display_name", "position", "rookie_season", "last_season"])
    p = p.dropna(subset=["gsis_id"])
    by_norm = defaultdict(list); pos_of = {}
    for r in p.itertuples(index=False):
        pos_of[r.gsis_id] = r.position
        if r.position in POS_TEST:
            by_norm[(cal.norm(str(r.display_name)), r.position)].append(
                (r.gsis_id, r.rookie_season if pd.notna(r.rookie_season) else 0,
                 r.last_season if pd.notna(r.last_season) else 9999))
    return by_norm, pos_of

def resolve_gsis(by_norm, name, pos, Y):
    c = [x for x in by_norm.get((cal.norm(name), pos), []) if x[1] <= Y <= x[2] + 1]
    return c[0][0] if len(c) == 1 else None

def load_year(Y):
    pbp = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"),
                      usecols=["game_id", "play_id", "week", "season_type", "posteam", "qb_dropback",
                               "rush_attempt", "pass_attempt", "receiver_player_id", "rusher_player_id"],
                      low_memory=False)
    pbp = pbp[(pbp.season_type == "REG") & pbp.posteam.notna()
              & ((pbp.qb_dropback == 1) | (pbp.rush_attempt == 1))].copy()
    pbp["is_pass"] = (pbp.qb_dropback == 1).astype(int)
    pbp["team"] = pbp.posteam.map(tm)
    part = pd.read_parquet(os.path.join(CACHE, f"pbp_participation_{Y}.parquet"),
                           columns=["nflverse_game_id", "play_id", "offense_players"])
    part = part[part.offense_players.notna() & (part.offense_players != "")]
    m = pbp.merge(part, left_on=["game_id", "play_id"], right_on=["nflverse_game_id", "play_id"], how="inner")
    # team-week totals
    tw = m.groupby(["week", "team"]).agg(ps_tm=("is_pass", "sum")).reset_index()
    tw["rs_tm"] = m.groupby(["week", "team"]).is_pass.count().values - tw.ps_tm
    tg = pbp[(pbp.pass_attempt == 1) & pbp.receiver_player_id.notna()]
    ca = pbp[(pbp.rush_attempt == 1) & (pbp.qb_dropback == 0) & pbp.rusher_player_id.notna()]
    tw = tw.merge(tg.groupby(["week", "team"]).size().rename("tg_tm").reset_index(), on=["week", "team"], how="left")
    tw = tw.merge(ca.groupby(["week", "team"]).size().rename("ca_tm").reset_index(), on=["week", "team"], how="left")
    tw = tw.fillna(0)
    # player-week snaps by play type
    ex = m[["week", "team", "is_pass", "offense_players"]].copy()
    ex["pid"] = ex.offense_players.str.split(";")
    ex = ex.explode("pid"); ex = ex[ex.pid.notna() & (ex.pid != "")]
    pw = ex.groupby(["week", "team", "pid"]).agg(ps=("is_pass", "sum"), n=("is_pass", "count")).reset_index()
    pw["rs"] = pw.n - pw.ps
    ptg = tg.groupby(["week", "team", "receiver_player_id"]).size().rename("tg").reset_index().rename(columns={"receiver_player_id": "pid"})
    pca = ca.groupby(["week", "team", "rusher_player_id"]).size().rename("ca").reset_index().rename(columns={"rusher_player_id": "pid"})
    pw = pw.merge(ptg, on=["week", "team", "pid"], how="outer").merge(pca, on=["week", "team", "pid"], how="outer").fillna(0)
    pw = pw.merge(tw, on=["week", "team"], how="left").fillna(0)
    pw["season"] = Y
    return pw

def build_lookup(pw):
    """(season,pid) -> sorted [(week, cumulative dict incl. that week, that-week dict)]."""
    cols = F + [f + "_tm" for f in F]
    look = {}
    pw = pw.sort_values(["season", "pid", "week"])
    for (s, pid), grp in pw.groupby(["season", "pid"]):
        cum = {c: 0.0 for c in cols}; cum["g"] = 0
        lst = []
        for r in grp.itertuples(index=False):
            d = r._asdict()
            wkd = {c: float(d[c]) for c in cols}
            for c in cols: cum[c] += wkd[c]
            cum["g"] += 1
            lst.append((int(r.week), dict(cum), wkd))
        look[(s, pid)] = lst
    return look

def before(lst, wk):
    out = None; weekly = []
    for w, c, wd in lst or []:
        if w < wk: out = c; weekly.append((w, wd))
        else: break
    return out, weekly

def share(a, b): return a / b if b > 0 else None

def trend(weekly, num, den, wk):
    """recent-3 weighted share (0.5/0.3/0.2) minus season-to-date avg share, in share points; None if <2 games or stale."""
    rows = [(w, wd[num] / wd[den]) for w, wd in weekly if wd[den] > 0]
    if len(rows) < 2 or rows[-1][0] < wk - 3: return None
    rec = rows[::-1][:3]
    r = sum(v * SNAP_W[i] for i, (w, v) in enumerate(rec)) / sum(SNAP_W[:len(rec)])
    return (r - sum(v for _, v in rows) / len(rows)) * 100

def trend_total(weekly, wk):
    rows = [(w, (wd["ps"] + wd["rs"]) / (wd["ps_tm"] + wd["rs_tm"])) for w, wd in weekly if wd["ps_tm"] + wd["rs_tm"] > 0]
    if len(rows) < 2 or rows[-1][0] < wk - 3: return None
    rec = rows[::-1][:3]
    r = sum(v * SNAP_W[i] for i, (w, v) in enumerate(rec)) / sum(SNAP_W[:len(rec)])
    return (r - sum(v for _, v in rows) / len(rows)) * 100

def mse(a, b): return float(((a - b) ** 2).mean())

def loyo(S, years, grid, predfn, label, quiet=False):
    act = S["act"]; per = {}
    for v in grid:
        pred = predfn(v)
        per[v] = {y: mse(pred[S["year"] == y], act[S["year"] == y]) for y in years}
    ship = per[grid[0]]; tot = n = wins = 0; picks = []
    for y in years:
        m = S["year"] == y
        if m.sum() == 0: continue
        best = min(grid, key=lambda v: sum(per[v][yy] for yy in years if yy != y))
        picks.append(best); e = mse(predfn(best)[m], act[m])
        tot += e * m.sum(); n += m.sum(); wins += e < ship[y]
    pooled_best = min(grid, key=lambda v: sum(per[v].values()))
    base_mse = sum(ship[y] * (S["year"] == y).sum() for y in years) / n
    if not quiet:
        print(f"  {label}")
        print("    grid pooled MSE: " + "  ".join(f"{str(v):>5}:{sum(per[v].values())/len(years):.3f}" for v in grid))
        print(f"    pooled best {pooled_best} | LOYO MSE {tot/n:.4f} vs shipped {base_mse:.4f} "
              f"({(tot/n/base_mse-1)*100:+.2f}%), years better {wins}/{len(years)}, picks {picks}")
    return pooled_best, (tot / n / base_mse - 1) * 100, wins

def zs(x, clip=2.5):
    x = np.asarray(x, float); ok = ~np.isnan(x)
    s = x[ok].std() if ok.sum() > 10 else 1.0
    return np.clip(np.where(ok, x / (s if s > 0 else 1), 0.0), -clip, clip), s

def main():
    by_norm, pos_of = load_players()
    frames = {}
    for Y in LOAD_YEARS:
        frames[Y] = load_year(Y)
        print(f"  {Y}: {len(frames[Y])} player-weeks with snaps/usage")
    pw = pd.concat(frames.values(), ignore_index=True)
    pw["pos"] = pw.pid.map(pos_of)
    look = build_lookup(pw)

    # league anchors per season x pos: targets per pass snap, carries per run snap
    lg = {}
    for (s, pos), g in pw[pw.pos.isin(POS_TEST)].groupby(["season", "pos"]):
        lg[(s, pos)] = {"tprr": g.tg.sum() / max(1, g.ps.sum()), "cprs": g.ca.sum() / max(1, g.rs.sum())}
    print("  league anchors 2025: " + "  ".join(f"{p} TPRR {lg[(2025,p)]['tprr']:.3f} CPRS {lg[(2025,p)]['cprs']:.3f}" for p in POS_TEST))

    # ---- GATE: do TPRR / CPRS persist YoY?
    print("\n=== GATE. persistence of targets-per-pass-snap (TPRR) and carries-per-run-snap (CPRS), YoY ===")
    for pos in POS_TEST:
        a, b, c, d = [], [], [], []
        for (Y, pid), lst in look.items():
            if pos_of.get(pid) != pos or (Y + 1, pid) not in look: continue
            c0, c1 = lst[-1][1], look[(Y + 1, pid)][-1][1]
            if c0["ps"] >= 100 and c1["ps"] >= 100:
                a.append(c0["tg"] / c0["ps"]); b.append(c1["tg"] / c1["ps"])
            if pos == "RB" and c0["rs"] >= 60 and c1["rs"] >= 60:
                c.append(c0["ca"] / c0["rs"]); d.append(c1["ca"] / c1["rs"])
        line = f"  {pos}: TPRR YoY r={np.corrcoef(a,b)[0,1]:+.2f} (n={len(a)}, sd {np.std(a):.3f}, mean {np.mean(a):.3f})"
        if c: line += f" | CPRS YoY r={np.corrcoef(c,d)[0,1]:+.2f} (n={len(c)}, sd {np.std(c):.3f}, mean {np.mean(c):.3f})"
        print(line)
    print("  in-season: TPRR through wk 8 -> wk 9+ (same season, >=60 pass snaps each half)")
    for pos in POS_TEST:
        a, b = [], []
        for (Y, pid), lst in look.items():
            if pos_of.get(pid) != pos: continue
            c8, _ = before(lst, 9); cE = lst[-1][1]
            if not c8: continue
            ps_l = cE["ps"] - c8["ps"]; tg_l = cE["tg"] - c8["tg"]
            if c8["ps"] >= 60 and ps_l >= 60:
                a.append(c8["tg"] / c8["ps"]); b.append(tg_l / ps_l)
        print(f"  {pos}: early->late TPRR r={np.corrcoef(a,b)[0,1]:+.2f} (n={len(a)})")

    # ---- samples
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    weekly_fpa, season_fpa, lg_fpa = build_fpa()
    from backtest_vegas_layer import load_lines
    S = defaultdict(list); miss = defaultdict(int)
    for Y in YEARS:
        if str(Y) not in clay_hist: continue
        lines, _ = load_lines(Y); avg = float(np.mean(list(lines.values())))
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
            prior = look.get((Y - 1, pid)); prior = prior[-1][1] if prior else None
            tprr_a = (prior["tg"] / prior["ps"]) if (prior and prior["ps"] >= 100) else lg[(Y, pos)]["tprr"]
            cprs_a = (prior["ca"] / prior["rs"]) if (prior and prior["rs"] >= 60) else lg[(Y, pos)]["cprs"]
            rows = sorted([(w["wk"], w["fpts"], OPP_ALIAS.get(w.get("opp"), w.get("opp")))
                           for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            hist = []
            for wk, fpts, opp in rows:
                imp = lines.get((team, wk))
                if imp is not None and hist and opp:
                    g = len(hist)
                    base = (P * clay_pg + g * (sum(hist) / g)) / (P + g)
                    veg = min(1.35, max(0.7, 1 + VEGAS_E[pos] * (imp - avg) / avg))
                    cur = weekly_fpa.get((Y, opp, pos), {}); past = [w for w in cur if w < wk]
                    fpa = 1.0
                    if past and lg_fpa.get((Y, pos)):
                        ratio = min(1.25, max(0.8, (sum(cur[w] for w in past) / len(past)) / lg_fpa[(Y, pos)]))
                        fpa = 1 + FPA_E * (ratio - 1) * min(1, len(past) / FPA_TRUST_G)
                    cum, weekly = before(look.get((Y, pid)), wk)
                    if not cum or cum["ps"] + cum["rs"] < 10: hist.append(fpts); miss["nosnaps"] += 1; continue
                    ttot = trend_total(weekly, wk)
                    if ttot is None: hist.append(fpts); miss["notrend"] += 1; continue
                    tp = trend(weekly, "ps", "ps_tm", wk); tr = trend(weekly, "rs", "rs_tm", wk)
                    pass_sh = share(cum["ps"], cum["ps_tm"]); run_sh = share(cum["rs"], cum["rs_tm"])
                    tgt_sh = share(cum["tg"], cum["tg_tm"]); car_sh = share(cum["ca"], cum["ca_tm"])
                    route_gap = (cum["ps"] * tprr_a / cum["tg_tm"] - tgt_sh) if cum["tg_tm"] > 0 else None
                    run_gap = (cum["rs"] * cprs_a / cum["ca_tm"] - car_sh) if cum["ca_tm"] > 0 else None
                    S["year"].append(Y); S["pos"].append(pos); S["base"].append(base); S["act"].append(fpts)
                    S["veg"].append(veg); S["fpa"].append(fpa); S["ttot"].append(ttot)
                    S["tp"].append(np.nan if tp is None else tp); S["tr"].append(np.nan if tr is None else tr)
                    S["pass_sh"].append(pass_sh or 0); S["run_sh"].append(run_sh or 0)
                    S["route_gap"].append(np.nan if route_gap is None else route_gap)
                    S["run_gap"].append(np.nan if run_gap is None else run_gap)
                    S["split"].append(share(cum["ps"], cum["ps"] + cum["rs"]) or 0)   # pass share of his snaps
                    S["g"].append(g)
                hist.append(fpts)
        print(f"  {Y}: samples so far {len(S['act'])}")
    print(f"  skipped: {dict(miss)}")
    S = {k: (np.array(v) if k == "pos" else np.array(v, float)) for k, v in S.items()}
    S["year"] = S["year"].astype(int); years = sorted(set(S["year"]))
    act, base = S["act"], S["base"]
    snapm = np.clip(1 + SNAP_E * S["ttot"] / 100, 0.75, 1.30)
    shipped = base * S["veg"] * S["fpa"] * snapm
    print(f"\n{len(act)} RB/WR/TE player-weeks | MSE base*Vegas*FPA {mse(base*S['veg']*S['fpa'],act):.4f} -> +snapMult(total, participation twin) {mse(shipped,act):.4f}")
    for pos in POS_TEST:
        m = S["pos"] == pos
        print(f"  {pos}: n={m.sum()}  no-snap {mse((base*S['veg']*S['fpa'])[m],act[m]):.3f} -> shipped {mse(shipped[m],act[m]):.3f}")

    # ---- A. gaps
    print("\n=== A. ROLE-vs-USAGE GAPS: actual/shipped by tercile (per position) ===")
    for key in ("route_gap", "run_gap", "split"):
        for pos in POS_TEST:
            if key == "run_gap" and pos != "RB": continue
            m = (S["pos"] == pos) & ~np.isnan(S[key])
            x = S[key]
            if m.sum() < 300: continue
            q = np.quantile(x[m], [1/3, 2/3]); parts = []
            for lo, hi, lab in ((-np.inf, q[0], "low"), (q[0], q[1], "mid"), (q[1], np.inf, "high")):
                mm = m & (x >= lo) & (x < hi)
                parts.append(f"{lab} {x[mm].mean():+.3f}: {act[mm].mean()/shipped[mm].mean():.3f} (n={mm.sum()})")
            r = np.corrcoef(x[m], (act[m] - shipped[m]) / np.maximum(shipped[m], 1))[0, 1]
            print(f"  {key:9s} {pos}: " + " | ".join(parts) + f"   corr rel-resid {r:+.3f}")

    print("\n=== A2. LOYO sweeps: shipped x (1 + e * gap_z) per position ===")
    grid = [0.0, 0.02, 0.04, 0.06, 0.08, 0.12]
    res = {}
    for key in ("route_gap", "run_gap"):
        for pos in POS_TEST:
            if key == "run_gap" and pos != "RB": continue
            m = S["pos"] == pos
            Sp = {k: v[m] for k, v in S.items()}; shp = shipped[m]
            z, sd = zs(Sp[key])
            res[(key, pos)] = loyo(Sp, years, grid, lambda e, z=z, shp=shp: shp * np.clip(1 + e * z, 0.8, 1.25),
                                   f"{pos} {key} (sd {sd:.3f} share-pts)")

    # ---- B. trend decomposition
    print("\n=== B. TREND DECOMPOSITION: replace snapMult(total) with 1 + a*passTrend + b*runTrend (%/pt) ===")
    bvf = base * S["veg"] * S["fpa"]
    for pos in POS_TEST:
        m = S["pos"] == pos
        Sp = {k: v[m] for k, v in S.items()}
        tp = np.nan_to_num(Sp["tp"]); tr = np.nan_to_num(Sp["tr"]); tt = Sp["ttot"]; bv = bvf[m]
        pairs = [(1.0, 1.0)]  # index 0 = proxy for shipped (a=b=1 on the components ~ total)
        for a in (0.0, 0.5, 1.0, 1.5, 2.0):
            for b in (0.0, 0.5, 1.0, 1.5, 2.0):
                if (a, b) != (1.0, 1.0): pairs.append((a, b))
        def pred(ab, tp=tp, tr=tr, bv=bv, Sp=Sp):
            a, b = ab
            # weight components by his snap mix so a=b=1 reproduces the total trend
            return bv * np.clip(1 + (a * Sp["split"] * tp + b * (1 - Sp["split"]) * tr) / 100, 0.75, 1.30)
        shp = shipped[m]
        print(f"  -- {pos} (n={m.sum()}) shipped total-trend MSE {mse(shp, Sp['act']):.4f}; a=b=1 recomposed {mse(pred((1.0,1.0)), Sp['act']):.4f}")
        best, delta, wins = loyo(Sp, years, pairs, pred, f"   {pos} (a=pass, b=run)")
        # single-component views
        loyo(Sp, years, [0.0, 0.5, 1.0, 1.5, 2.0], lambda a, tp=tp, bv=bv: bv * np.clip(1 + a * tp / 100, 0.75, 1.30), f"   {pos} pass-snap trend ONLY (no run, no total)")
        if pos == "RB":
            loyo(Sp, years, [0.0, 0.5, 1.0, 1.5, 2.0], lambda b, tr=tr, bv=bv: bv * np.clip(1 + b * tr / 100, 0.75, 1.30), f"   {pos} run-snap trend ONLY")
        # on TOP of shipped total: add the pass/run DIFFERENCE trend (does the split add beyond the total?)
        diff = tp - tr
        loyo(Sp, years, [0.0, 0.25, 0.5, 0.75, 1.0], lambda c, diff=diff, shp=shp: shp * np.clip(1 + c * diff / 100, 0.75, 1.30), f"   {pos} shipped x (1 + c*(passTrend - runTrend))")

if __name__ == "__main__":
    main()
