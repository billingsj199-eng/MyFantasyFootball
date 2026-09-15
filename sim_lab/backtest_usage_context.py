#!/usr/bin/env python3
"""
USAGE IN CONTEXT backtest (2026-09-15).

Jack: "projections need to heavily take into consideration not just past production but snap counts /
routes run and what game scripts these are happening in, and where on the field - snaps near the goal
line are more valuable, and playing more snaps in 2WR sets is way more valuable than just slot usage,
along with factoring in team totals" + "and spreads".

DATA: nflverse pbp_participation 2018-2025 (every play's on-field offensive players + personnel; published
after the season, NOT in-season) joined to play_by_play (down, yardline, score, dropback, who got the ball).

Every play gets a CONTEXT CELL = zone (goal line <= 5 yds / red zone 6-20 / field) x kind (dropback / run)
x script (neutral |score diff| <= 8 / lopsided) - 12 cells. League half-PPR points per ON-FIELD SNAP by
cell and position (RB / WR / TE), fit on the other seasons (LOYO-clean). Walk-forward per player at week W
(weeks >= 4, >= 3 prior games with snaps):
  ctx_pg     sum over cells of (snaps per game in the cell) x (league points per snap in the cell)
             = what his snaps are worth given WHERE and WHEN they happen
  flat_pg    snaps per game x league points per snap overall (no context)
  ctx_ratio  ctx_pg / flat_pg (context richness), rz_rel / gl_rel (red-zone / goal-line snap share over
             overall share), neu_rel (neutral-script share over overall), two_rel (share of the team's
             2-or-fewer-WR plays over overall; WR/TE), db_rel (dropback share over overall; route proxy)
Base: bt_common shipped (P=5 blend x Vegas implied total x FPA) x the shipped snap trend rebuilt from
nflverse snap counts (base2), same as the age study. Team totals are already in via the Vegas multiplier.
  T1  blend   (1-w) base2 + w x usage projection (ctx_pg or flat_pg x Vegas x FPA x snap trend)
  T2  level   base2 x clip(1 + k x z) for each context feature
  T3  spread  base2 x clip(1 + k x team spread / 7), per position, and RB split by receiving role
Ship bar: <= -0.3% LOYO MSE with >= 5/7 years better. Log usage_context_backtest.log;
results -> data/usage_context_backtest.js (SIM_USAGE_BT), ZONES tab.
"""
import json, os, re, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B
from bt_common import iter_samples, to_arrays, POS4
from backtest_target_area import mse

LOG = open(os.path.join(HERE, "usage_context_backtest.log"), "w", encoding="utf-8")


class _Tee:
    def __init__(self, a, b): self.a, self.b = a, b
    def write(self, t): self.a.write(t); self.b.write(t); self.a.flush(); self.b.flush()
    def flush(self): self.a.flush(); self.b.flush()


sys.stdout = _Tee(sys.stdout, LOG)
def P(*a): print(" ".join(str(x) for x in a))

LOAD = list(range(2018, 2026))
YEARS = list(range(2019, 2026))
SKILL = ("RB", "WR", "TE")
SNAP_W = [0.5, 0.3, 0.2]
MIN_WK = 4
SHIP_PCT, SHIP_WINS = -0.30, 5
RES = {"loyo": [], "values": {}, "buckets": [], "n": 0}
ZONES = ("gl", "rz", "fd")
CELLS = [f"{z}|{k}|{s}" for z in ZONES for k in ("db", "run") for s in ("neu", "lop")]


def loyo2(S, years, grid, predfn, label, family, pos):
    act = S["act"]; per = {}
    ys = [y for y in years if (S["year"] == y).any()]
    for v in grid:
        pred = predfn(v)
        per[v] = {y: mse(pred[S["year"] == y], act[S["year"] == y]) for y in ys}
    ship = per[grid[0]]; tot = n = wins = 0; picks = []
    for y in ys:
        m = S["year"] == y
        best = min(grid, key=lambda v: sum(per[v][yy] for yy in ys if yy != y))
        picks.append(best); e = mse(predfn(best)[m], act[m])
        tot += e * m.sum(); n += m.sum(); wins += e < ship[y]
    pooled_best = min(grid, key=lambda v: sum(per[v].values()))
    base_mse = sum(ship[y] * (S["year"] == y).sum() for y in ys) / n
    pct = (tot / n / base_mse - 1) * 100
    P(f"  {label}")
    P("    grid pooled MSE: " + "  ".join(f"{v:+.2f}:{sum(per[v].values())/len(ys):.3f}" for v in grid))
    P(f"    pooled best {pooled_best:+.2f} | LOYO MSE {tot/n:.4f} vs base {base_mse:.4f} ({pct:+.2f}%), years better {wins}/{len(ys)}, picks {picks}")
    RES["loyo"].append({"label": label, "family": family, "pos": pos, "n": int(n), "best": float(pooled_best), "pct": round(pct, 3),
                        "wins": int(wins), "years": len(ys), "picks": [float(p) for p in picks],
                        "verdict": "PASS" if (pct <= SHIP_PCT and wins >= SHIP_WINS) else ("lean" if (pct <= -0.1 and wins >= 4) else "FAIL")})


def load_positions():
    p = pd.read_csv(os.path.join(B.CACHE, "players.csv"), usecols=["gsis_id", "position"], low_memory=False)
    return {r.gsis_id: r.position for r in p.itertuples(index=False) if isinstance(r.gsis_id, str)}


def load_season(Y, posmap):
    """-> (snaps {(gsis, tm, wk): {cell: n, 'two': n, 'all': n, 'db': n}}, team {(tm, wk): same},
           pts {(gsis, cell): points} , snaps_by_pos_cell {(pos, cell): n}, pts_by_pos_cell {(pos, cell): pts})"""
    cols = ["season_type", "week", "game_id", "play_id", "posteam", "yardline_100", "score_differential", "qb_dropback",
            "play_type", "rusher_player_id", "receiver_player_id", "rushing_yards", "receiving_yards", "complete_pass",
            "pass_touchdown", "rush_touchdown"]
    pbp = pd.read_csv(os.path.join(B.CACHE, f"play_by_play_{Y}.csv.gz"), usecols=cols, low_memory=False)
    pbp = pbp[(pbp.season_type == "REG") & pbp.play_type.isin(["run", "pass"]) & pbp.posteam.notna() & pbp.yardline_100.notna()].copy()
    pbp["play_id"] = pbp.play_id.astype(int)
    part = pd.read_parquet(os.path.join(B.CACHE, f"pbp_participation_{Y}.parquet"),
                           columns=["nflverse_game_id", "play_id", "offense_players", "offense_personnel"])
    part = part[part.offense_players.fillna("") != ""].copy()
    part["play_id"] = part.play_id.astype(int)
    d = pbp.merge(part, left_on=["game_id", "play_id"], right_on=["nflverse_game_id", "play_id"], how="inner")
    zone = np.where(d.yardline_100 <= 5, "gl", np.where(d.yardline_100 <= 20, "rz", "fd"))
    kind = np.where(d.qb_dropback.fillna(0) == 1, "db", "run")
    script = np.where(d.score_differential.fillna(0).abs() <= 8, "neu", "lop")
    d["cell"] = pd.Series(zone, index=d.index) + "|" + pd.Series(kind, index=d.index) + "|" + pd.Series(script, index=d.index)
    nwr = d.offense_personnel.fillna("").str.extract(r"(\d+)\s*WR")[0]
    d["two"] = pd.to_numeric(nwr, errors="coerce").fillna(3) <= 2
    d["tm"] = d.posteam.map(lambda t: B.tm(str(t)))
    d["wk"] = d.week.astype(int)
    comp = d.complete_pass.fillna(0)
    d["rec_pts"] = 0.5 * comp + 0.1 * d.receiving_yards.fillna(0) + 6 * d.pass_touchdown.fillna(0)
    d["rush_pts"] = 0.1 * d.rushing_yards.fillna(0) + 6 * d.rush_touchdown.fillna(0)

    team = defaultdict(lambda: defaultdict(float))
    for (tm, wk, cell, two), g in d.groupby(["tm", "wk", "cell", "two"]).size().items():
        t = team[(tm, wk)]; t[cell] += g; t["all"] += g
        if two: t["two"] += g
        if cell.split("|")[1] == "db": t["db"] += g
    ex = d[["tm", "wk", "cell", "two", "offense_players"]].copy()
    ex["gsis"] = ex.offense_players.str.split(";")
    ex = ex.explode("gsis")
    ex = ex[ex.gsis.map(lambda x: posmap.get(x) in SKILL)]
    snaps = defaultdict(lambda: defaultdict(float))
    for (gs, tm, wk, cell, two), n in ex.groupby(["gsis", "tm", "wk", "cell", "two"]).size().items():
        s = snaps[(gs, tm, wk)]; s[cell] += n; s["all"] += n
        if two: s["two"] += n
        if cell.split("|")[1] == "db": s["db"] += n
    spc = defaultdict(float)
    for (gs, cell), n in ex.groupby(["gsis", "cell"]).size().items():
        spc[(posmap.get(gs), cell)] += n
    ppc = defaultdict(float)
    for col, idcol in (("rec_pts", "receiver_player_id"), ("rush_pts", "rusher_player_id")):
        sub = d[d[idcol].notna()]
        for (gs, cell), v in sub.groupby([idcol, "cell"])[col].sum().items():
            if posmap.get(gs) in SKILL:
                ppc[(posmap.get(gs), cell)] += v
    return snaps, team, spc, ppc


def main():
    posmap = load_positions()
    P("loading pbp x participation 2018-2025 ...")
    SEAS = {}
    for Y in LOAD:
        SEAS[Y] = load_season(Y, posmap)
        P(f"  {Y}: {len(SEAS[Y][0])} skill player-team-weeks with snaps, {len(SEAS[Y][1])} team-weeks")

    def values_excluding(Y):
        spc, ppc = defaultdict(float), defaultdict(float)
        for Z, (_, _, s, p) in SEAS.items():
            if Z == Y:
                continue
            for k, v in s.items(): spc[k] += v
            for k, v in p.items(): ppc[k] += v
        V = {pos: {c: (ppc[(pos, c)] / spc[(pos, c)] if spc[(pos, c)] else 0.0) for c in CELLS} for pos in SKILL}
        Vall = {pos: (sum(ppc[(pos, c)] for c in CELLS) / max(1.0, sum(spc[(pos, c)] for c in CELLS))) for pos in SKILL}
        return V, Vall

    Vfull, Vallfull = values_excluding(None)
    P("\n=== league half-PPR points per on-field snap by context cell (all seasons) ===")
    for pos in SKILL:
        P(f"  {pos}: overall {Vallfull[pos]:.3f} | " + "  ".join(f"{c} {Vfull[pos][c]:.3f}" for c in CELLS))
        RES["values"][pos] = {"all": round(Vallfull[pos], 4), **{c: round(Vfull[pos][c], 4) for c in CELLS}}

    # snap counts for the shipped snap trend (same rebuild as the age study)
    snapct = {}
    for Y in YEARS:
        dd = pd.read_parquet(os.path.join(B.CACHE, f"snap_counts_{Y}.parquet"), columns=["week", "game_type", "player", "team", "offense_snaps", "offense_pct"])
        dd = dd[(dd.game_type == "REG") & (dd.offense_snaps > 0)]
        m = defaultdict(dict)
        for r in dd.itertuples(index=False):
            m[(B.cal.norm(str(r.player)), B.tm(str(r.team)))][int(r.week)] = 100.0 * float(r.offense_pct)
        snapct[Y] = m

    def snap_mult(wkpct, wk):
        past = sorted([w for w in wkpct if w < wk], reverse=True)
        if len(past) < 2 or past[0] < wk - 3:
            return 1.0
        rec = sum(wkpct[w] * SNAP_W[i] for i, w in enumerate(past[:3])) / sum(SNAP_W[:len(past[:3])])
        return min(1.30, max(0.75, 1 + (rec - float(np.mean([wkpct[w] for w in past]))) / 100.0))

    P("\nloading base samples (bt_common)...")
    S = iter_samples(POS4)
    A = to_arrays(S); n = len(S)
    act, ship = A["act"], A["shipped"]
    FE = ["ctx_pg", "flat_pg", "ctx_ratio", "rz_rel", "gl_rel", "neu_rel", "two_rel", "db_rel", "spread"]
    X = {k: np.full(n, np.nan) for k in FE}
    sm = np.ones(n)
    Vcache = {}
    by_player = {Y: defaultdict(list) for Y in YEARS}
    for Y in YEARS:
        for (gs, tm, wk), s in SEAS[Y][0].items():
            by_player[Y][(gs, tm)].append((wk, s))
    games = {Y: B.load_games(Y) for Y in YEARS}
    for i, s in enumerate(S):
        Y, W, p = s["year"], s["wk"], s["pos"]
        wp = snapct[Y].get((B.cal.norm(s["name"]), s["team"]))
        if wp:
            sm[i] = snap_mult(wp, W)
        gm = games[Y].get((s["team"], W))
        if gm and gm.get("implied") is not None and gm.get("oppImplied") is not None:
            X["spread"][i] = (gm["implied"] - gm["oppImplied"]) / 7.0
        if p not in SKILL or not s["pid"] or W < MIN_WK:
            continue
        rows = [(w, sn) for w, sn in by_player[Y].get((s["pid"], s["team"]), []) if w < W and sn["all"] > 0]
        if len(rows) < 3:
            continue
        if Y not in Vcache:
            Vcache[Y] = values_excluding(Y)
        V, Vall = Vcache[Y]
        g = len(rows)
        team = SEAS[Y][1]
        tot = defaultdict(float); ttot = defaultdict(float)
        for w, sn in rows:
            for k, v in sn.items(): tot[k] += v
            for k, v in team[(s["team"], w)].items(): ttot[k] += v
        ctx = sum(tot[c] / g * V[p][c] for c in CELLS)
        flat = tot["all"] / g * Vall[p]
        sh_all = tot["all"] / ttot["all"] if ttot["all"] else None
        if not sh_all:
            continue
        def share(keys):
            num = sum(tot[k] for k in keys); den = sum(ttot[k] for k in keys)
            return num / den if den else None
        rz = share([c for c in CELLS if c.startswith("rz") or c.startswith("gl")])
        gl = share([c for c in CELLS if c.startswith("gl")])
        neu = share([c for c in CELLS if c.endswith("neu")])
        X["ctx_pg"][i] = ctx; X["flat_pg"][i] = flat
        X["ctx_ratio"][i] = ctx / flat if flat > 0 else np.nan
        X["rz_rel"][i] = rz / sh_all if rz is not None else np.nan
        X["gl_rel"][i] = gl / sh_all if gl is not None else np.nan
        X["neu_rel"][i] = neu / sh_all if neu is not None else np.nan
        if p in ("WR", "TE") and ttot["two"] >= 20:
            X["two_rel"][i] = (tot["two"] / ttot["two"]) / sh_all
        if ttot["db"]:
            X["db_rel"][i] = (tot["db"] / ttot["db"]) / sh_all
    base2 = ship * sm
    pos = A["pos"]
    RES["n"] = int(n)
    P(f"  {n} player-weeks; usage features on {int(np.isfinite(X['ctx_pg']).sum())} RB/WR/TE rows (weeks >= {MIN_WK}); spread on {int(np.isfinite(X['spread']).sum())}")
    for p in SKILL:
        m = (pos == p) & np.isfinite(X["ctx_pg"])
        if m.sum():
            r_b = np.corrcoef(base2[m], act[m])[0, 1]; r_c = np.corrcoef(X["ctx_pg"][m] * A["veg"][m] * A["fpa"][m] * sm[m], act[m])[0, 1]
            r_f = np.corrcoef(X["flat_pg"][m] * A["veg"][m] * A["fpa"][m] * sm[m], act[m])[0, 1]
            P(f"  {p}: corr with actual - shipped x snap trend {r_b:.3f} | context usage {r_c:.3f} | flat snaps {r_f:.3f}  (n {int(m.sum())})")

    years = YEARS
    P("\n=== T1 usage blend: (1-w) base2 + w x usage projection (rows without features keep base2) ===")
    for p in SKILL:
        pm = pos == p
        Ssub = {"year": A["year"][pm], "act": act[pm]}; b2 = base2[pm]
        for lab, key in (("context-valued snaps", "ctx_pg"), ("flat snaps (no context)", "flat_pg")):
            u = X[key][pm] * A["veg"][pm] * A["fpa"][pm] * sm[pm]
            u = np.where(np.isfinite(u), u, b2)
            loyo2(Ssub, years, [0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0], lambda w, u=u, b2=b2: (1 - w) * b2 + w * u, f"{p} blend with {lab}", "blend w", f"{p} {lab}")

    P("\n=== T2 context level terms: base2 x clip(1 + k x z), z standardized within the position ===")
    grid = [0.0, 0.01, 0.02, 0.04, 0.06, -0.01, -0.02, -0.04]
    for p in SKILL:
        pm = pos == p
        Ssub = {"year": A["year"][pm], "act": act[pm]}; b2 = base2[pm]
        for key in ("ctx_ratio", "rz_rel", "gl_rel", "neu_rel", "two_rel", "db_rel"):
            v = X[key][pm]; ok = np.isfinite(v)
            if ok.sum() < 300:
                continue
            z = np.zeros(pm.sum()); z[ok] = np.clip((v[ok] - v[ok].mean()) / (v[ok].std() or 1.0), -3, 3)
            q = np.quantile(v[ok], [1 / 3, 2 / 3])
            terc = [float(act[pm][ok & (v <= q[0])].sum() / b2[ok & (v <= q[0])].sum()),
                    float(act[pm][ok & (v > q[0]) & (v < q[1])].sum() / b2[ok & (v > q[0]) & (v < q[1])].sum()),
                    float(act[pm][ok & (v >= q[1])].sum() / b2[ok & (v >= q[1])].sum())]
            P(f"  {p} {key}: terciles actual/base2 low {terc[0]:.3f} mid {terc[1]:.3f} high {terc[2]:.3f} (cuts {q[0]:.2f} / {q[1]:.2f}, n {int(ok.sum())})")
            RES["buckets"].append({"pos": p, "feature": key, "terciles": [round(t, 3) for t in terc], "cuts": [round(float(q[0]), 3), round(float(q[1]), 3)], "n": int(ok.sum())})
            loyo2(Ssub, years, grid, lambda k, z=z, b2=b2: b2 * np.clip(1 + k * z, 0.8, 1.25), f"{p} {key} level", "level (1 + k z)", f"{p} {key}")

    P("\n=== T3 spread beyond the implied total: base2 x clip(1 + k x team spread / 7) (+ = favorite) ===")
    sgrid = [0.0, 0.01, 0.02, 0.04, 0.06, -0.01, -0.02, -0.04]
    for p in POS4:
        pm = pos == p
        Ssub = {"year": A["year"][pm], "act": act[pm]}; b2 = base2[pm]
        sp = np.nan_to_num(X["spread"][pm], nan=0.0)
        loyo2(Ssub, years, sgrid, lambda k, sp=sp, b2=b2: b2 * np.clip(1 + k * sp, 0.8, 1.25), f"{p} spread", "spread/7", f"{p} spread")
        if p == "RB":
            dbr = X["db_rel"][pm]; ok = np.isfinite(dbr)
            if ok.sum() >= 300:
                med = np.median(dbr[ok])
                for lab, mk in (("receiving back (dropback share above median)", ok & (dbr > med)), ("early-down back (below median)", ok & (dbr <= med))):
                    spm = np.where(mk, sp, 0.0)
                    loyo2(Ssub, years, sgrid, lambda k, spm=spm, b2=b2: b2 * np.clip(1 + k * spm, 0.8, 1.25), f"RB spread x {lab}", "spread/7 on role rows", f"RB spread {lab.split(' (')[0]}")
        fav = sp >= 1.0; dog = sp <= -1.0
        for lab, mk in (("favored by 7+", fav), ("underdog by 7+", dog)):
            if mk.sum() >= 60:
                r = float(act[pm][mk].sum() / b2[mk].sum()); r0 = float(act[pm][~mk].sum() / b2[~mk].sum())
                P(f"  {p} {lab}: actual/base2 {r:.3f} vs rest {r0:.3f} (n {int(mk.sum())})")
                RES["buckets"].append({"pos": p, "feature": lab, "ratio": round(r, 3), "rest": round(r0, 3), "n": int(mk.sum())})

    RES["updated"] = time.strftime("%Y-%m-%d %H:%M"); RES["years"] = YEARS; RES["bar"] = {"pct": SHIP_PCT, "wins": SHIP_WINS}
    passed = [r for r in RES["loyo"] if r["verdict"] == "PASS"]
    RES["summary"] = (f"Usage in context: {len(RES['loyo'])} LOYO tests on {n} player-weeks 2019-25; " +
                      (f"{len(passed)} pass: " + "; ".join(f"{r['pos']} {r['pct']:+.2f}% ({r['wins']}/7)" for r in passed) if passed else "none pass the ship bar"))
    with open(os.path.join(HERE, "data", "usage_context_backtest.js"), "w", encoding="utf-8") as fh:
        fh.write("// built by backtest_usage_context.py - snaps valued by field zone x dropback x game script, personnel, spread; shown on the ZONES tab\n")
        fh.write("window.SIM_USAGE_BT = "); json.dump(RES, fh, separators=(",", ":")); fh.write(";\n")
    P(f"\nwrote data/usage_context_backtest.js: {RES['summary']}")
    P("done")


if __name__ == "__main__":
    main()
