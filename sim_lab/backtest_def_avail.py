#!/usr/bin/env python3
"""
DEFENSE AVAILABILITY layer backtest (2026-09-15).

Jack: "injuries (banged up playing or missing actual time) how that impacts teammates
and player performance or even on defense and how that impacts the defenses" ->
"start on the defense availability layer".

Question: when a defense is missing regular starters - weighted by how GOOD they are -
do opposing offenses beat the shipped projection, and does the defense's own DST
score drop? The shipped engine already has one piece of this: cb1OutBoost (CB1 out ->
WR x1.02-1.08, QB x1.04), sized in backtest_cb1_boost.py. bt_common's base does NOT
include that boost, so every coverage test also runs "beyond CB1" (CB1 absences removed)
- that is the increment a new layer would add.

DATA (one source for availability AND quality): PFF weekly defense_summary 2018-2025
(pbp_cache/pff/weekly/pff_defense_summary_<yr>_w<N>.csv: every defender who played,
snaps, grades) + defense_coverage_scheme (man/zone coverage grades) + nflverse
injuries_<yr>.parquet (final report Out/Doubtful = PRE-GAME KNOWN absences).

  share     player defensive snaps / team defensive snaps that week (team = max player)
  regular   WALK-FORWARD at week W (no lookahead): share >= .5 in >= 60% of the team's
            games before W, >= 3 team games before W -> graded weeks are W >= 4
  absent    regular with share < .2 at W (REALIZED - includes surprise inactives, a small
            leak) / _pre: regular listed Out or Doubtful on the week's final injury report
            (the clean, knowable-before-kickoff version) / _fresh: absent at W but played
            the team's previous game
  quality   snap-weighted grade before W (this season) blended with last season
            (capped 300 snaps): unit grade = coverage (CB/S), pass rush (ED/DI), run
            defense (ED/DI/LB), overall; q = max(0, grade - 55) / 10 x regular's avg share
  features  cov_q / cov_q_nocb1 / n_db / cb1_out, rush_q / n_rush, run_q / n_front,
            all_q / n_out  (+ _pre and _fresh versions)

Tests (all LOYO 2019-25 on bt_common's shipped base, ship bar <= -0.3% with >= 5/7):
  buckets   actual/shipped for flag rows, and REL = flagged ratio / unflagged ratio within
            the same position and week band (4-8 / 9-13 / 14-18 - injuries pile up late
            while the blend tightens, the OL-out confound)
  cont      shipped x clip(1 + k x feature)  per position
  flags     shipped x m on flagged rows (2+ DBs out, quality secondary out beyond CB1,
            quality pass rush out, 2+ front starters out)
  DST       own defense's missing quality vs DST points: shipped (16.2 - .436 x opp
            implied) + k x feature
Log def_avail_backtest.log; results -> data/def_avail_backtest.js (SIM_DEFAV_BT), ZONES tab.
"""
import json, math, os, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B
from bt_common import iter_samples, to_arrays, POS4
from backtest_target_area import mse, implied_map
import backtest_dst_regression as DR
import build_scheme as BS

LOG = open(os.path.join(HERE, "def_avail_backtest.log"), "w", encoding="utf-8")


class _Tee:
    def __init__(self, a, b): self.a, self.b = a, b
    def write(self, t): self.a.write(t); self.b.write(t); self.a.flush(); self.b.flush()
    def flush(self): self.a.flush(); self.b.flush()


sys.stdout = _Tee(sys.stdout, LOG)
def P(*a): print(" ".join(str(x) for x in a))

YEARS = list(range(2019, 2026))
REPL, K_PRIOR_SNAPS, MIN_WK = 55.0, 300.0, 4
DEF_POS = ("CB", "S", "LB", "ED", "DI")
SHIP_PCT, SHIP_WINS = -0.30, 5
RES = {"loyo": [], "buckets": [], "check": {}, "n": 0}


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
    P(f"    pooled best {pooled_best:+.2f} | LOYO MSE {tot/n:.4f} vs shipped {base_mse:.4f} ({pct:+.2f}%), years better {wins}/{len(ys)}, picks {picks}")
    RES["loyo"].append({"label": label, "family": family, "pos": pos, "n": int(n), "best": float(pooled_best), "pct": round(pct, 3),
                        "wins": int(wins), "years": len(ys), "picks": [float(p) for p in picks],
                        "verdict": "PASS" if (pct <= SHIP_PCT and wins >= SHIP_WINS) else ("lean" if (pct <= -0.1 and wins >= 4) else "FAIL")})


# ------------------------------------------------------------------ PFF defense seasons
def load_season(Y):
    """-> (cur {(tm, wk): {pid: row}}, grades {pid: [(wk, unit sums...)]}) or None."""
    ds = BS.load("defense_summary", Y)
    if ds is None:
        return None
    ds = ds[ds.position.isin(DEF_POS) & ds.player_id.notna()].copy()
    covg = {}
    cov = BS.load("defense_coverage_scheme", Y)
    if cov is not None:
        for r in cov.itertuples(index=False):
            ms = r.man_snap_counts_coverage if pd.notna(r.man_snap_counts_coverage) else 0.0
            zs = r.zone_snap_counts_coverage if pd.notna(r.zone_snap_counts_coverage) else 0.0
            mg = r.man_grades_coverage_defense; zg = r.zone_grades_coverage_defense
            num = (ms * mg if pd.notna(mg) else 0.0) + (zs * zg if pd.notna(zg) else 0.0)
            den = (ms if pd.notna(mg) else 0.0) + (zs if pd.notna(zg) else 0.0)
            if den > 0 and pd.notna(r.player_id):
                covg[(int(r.player_id), int(r.week))] = (den, num / den)
    tsn = ds.groupby(["tm", "week"]).snap_counts_defense.transform("max")
    ds["share"] = ds.snap_counts_defense.fillna(0) / tsn.where(tsn > 0, 1.0)
    cur = defaultdict(dict)
    grades = defaultdict(list)
    for r in ds.itertuples(index=False):
        pid, wk = int(r.player_id), int(r.week)
        cs = covg.get((pid, wk))
        row = {"pos": r.position, "name": str(r.player), "share": float(r.share)}
        cur[(r.tm, wk)][pid] = row

        def g(val, sn):
            return (float(sn), float(val)) if pd.notna(val) and pd.notna(sn) and sn > 0 else (0.0, 0.0)
        grades[pid].append((wk,
                            g(r.grades_defense, r.snap_counts_defense),
                            cs if cs else g(r.grades_defense, r.snap_counts_coverage),
                            g(r.grades_pass_rush_defense, r.snap_counts_pass_rush),
                            g(r.grades_run_defense, r.snap_counts_run_defense)))
    return cur, grades


UNIT = {"def": 1, "cov": 2, "rush": 3, "run": 4}


def unit_sums(entries, unit, before=None):
    s = w = 0.0
    i = UNIT[unit]
    for e in entries:
        if before is not None and e[0] >= before:
            continue
        sn, gr = e[i]
        s += sn * gr; w += sn
    return s, w


def grade_of(pid, W, unit, grades_cur, grades_pri):
    cs, cw = unit_sums(grades_cur.get(pid, ()), unit, W)
    ps, pw = unit_sums(grades_pri.get(pid, ()), unit) if grades_pri else (0.0, 0.0)
    wp = min(pw, K_PRIOR_SNAPS)
    num = cs + (ps / pw * wp if pw else 0.0)
    den = cw + wp
    return num / den if den else 60.0


def injury_sets(Y):
    p = os.path.join(B.CACHE, f"injuries_{Y}.parquet")
    out = defaultdict(set)
    if not os.path.exists(p):
        return out
    d = pd.read_parquet(p, columns=["game_type", "team", "week", "full_name", "report_status"])
    d = d[(d.game_type == "REG") & d.report_status.isin(["Out", "Doubtful"])]
    for r in d.itertuples(index=False):
        out[(B.tm(str(r.team)), int(r.week))].add(B.cal.norm(str(r.full_name)))
    return out


KNOWN_STATUS = ("RES", "PUP", "EXE", "SUS", "NFI", "INA")


def roster_status(Y):
    """{(pff_id, week): nflverse weekly roster status} - RES/PUP/EXE/SUS/NFI known days ahead, INA game-day."""
    p = os.path.join(B.CACHE, f"roster_weekly_{Y}.parquet")
    out = {}
    if not os.path.exists(p):
        return out
    d = pd.read_parquet(p, columns=["week", "game_type", "status", "pff_id"])
    d = d[(d.game_type == "REG") & d.pff_id.notna()]
    for r in d.itertuples(index=False):
        try:
            out[(int(float(r.pff_id)), int(r.week))] = str(r.status)
        except (TypeError, ValueError):
            continue
    return out


def season_features(Y, cur, gcur, gpri, inj, ros=None):
    out = {}
    tw = defaultdict(list)
    for (T, wk) in cur:
        tw[T].append(wk)
    chk = defaultdict(int)
    for T, weeks in tw.items():
        weeks = sorted(weeks)
        for W in weeks:
            if W < MIN_WK:
                continue
            G = [w for w in weeks if w < W]
            if len(G) < 3:
                continue
            qual = defaultdict(int); tot = defaultdict(float); pos_of = {}; name_of = {}
            for gw in G:
                for pid, r in cur[(T, gw)].items():
                    if r["share"] >= 0.5:
                        qual[pid] += 1
                    tot[pid] += r["share"]; pos_of[pid] = r["pos"]; name_of[pid] = r["name"]
            need = max(2, math.ceil(0.6 * len(G)))
            regs = [pid for pid, q in qual.items() if q >= need]
            now = cur.get((T, W), {})
            last = cur.get((T, G[-1]), {})
            cbs = [pid for pid in regs if pos_of[pid] == "CB"]
            cb1 = max(cbs, key=lambda x: (qual[x], tot[x])) if cbs else None
            injs = inj.get((T, W), set())
            f = defaultdict(float)
            f["n_reg"] = len(regs)
            for pid in regs:
                absent = now.get(pid, {}).get("share", 0.0) < 0.2
                pre = B.cal.norm(name_of[pid]) in injs
                rs = (ros or {}).get((pid, W), "")
                known = pre or rs in KNOWN_STATUS
                fresh = absent and last.get(pid, {}).get("share", 0.0) >= 0.2
                if absent: chk["absent"] += 1
                if pre: chk["pre"] += 1
                if absent and pre: chk["both"] += 1
                if known: chk["known"] += 1
                if absent and known: chk["absknown"] += 1
                if known and not absent: chk["knownPlayed"] += 1
                if not (absent or known):
                    continue
                pos = pos_of[pid]; avg = tot[pid] / len(G)
                qd = max(0.0, grade_of(pid, W, "def", gcur, gpri) - REPL) / 10 * avg
                qc = max(0.0, grade_of(pid, W, "cov", gcur, gpri) - REPL) / 10 * avg if pos in ("CB", "S") else 0.0
                qr = max(0.0, grade_of(pid, W, "rush", gcur, gpri) - REPL) / 10 * avg if pos in ("ED", "DI") else 0.0
                qn = max(0.0, grade_of(pid, W, "run", gcur, gpri) - REPL) / 10 * avg if pos in ("ED", "DI", "LB") else 0.0
                for tag, cond in (("", absent), ("_pre", pre), ("_known", known), ("_fresh", fresh)):
                    if not cond:
                        continue
                    f["all_q" + tag] += qd; f["n_out" + tag] += 1
                    if pos in ("CB", "S"):
                        f["cov_q" + tag] += qc; f["n_db" + tag] += 1
                        if pid == cb1: f["cb1_out" + tag] = 1.0
                        else: f["cov_q_nocb1" + tag] += qc
                    if pos in ("ED", "DI"):
                        f["rush_q" + tag] += qr; f["n_rush" + tag] += 1
                    if pos in ("ED", "DI", "LB"):
                        f["run_q" + tag] += qn; f["n_front" + tag] += 1
            out[(T, W)] = dict(f)
    return out, chk


FEATS = ["all_q", "n_out", "cov_q", "n_db", "cb1_out", "cov_q_nocb1", "rush_q", "n_rush", "run_q", "n_front"]
FEATS = FEATS + [k + "_pre" for k in FEATS] + [k + "_known" for k in FEATS] + [k + "_fresh" for k in FEATS]


def main():
    P("loading PFF weekly defense 2018-2025 + nflverse injury reports...")
    seasons = {}
    for Y in range(2018, 2026):
        seasons[Y] = load_season(Y)
        if seasons[Y]:
            P(f"  {Y}: {len(seasons[Y][0])} team-weeks, {len(seasons[Y][1])} defenders")
    feats = {}
    for Y in YEARS:
        if not seasons.get(Y):
            continue
        cur, gcur = seasons[Y]
        gpri = seasons[Y - 1][1] if seasons.get(Y - 1) else {}
        feats[Y], chk = season_features(Y, cur, gcur, gpri, injury_sets(Y), roster_status(Y))
        nreg = [v["n_reg"] for v in feats[Y].values()]
        P(f"  {Y}: {len(feats[Y])} graded team-weeks, regulars/team median {int(np.median(nreg))}, "
          f"absent regular-weeks {chk['absent']}, on final report Out/Doubtful {chk['pre']} (both {chk['both']}); "
          f"KNOWN before lock (report + reserve/PUP/exempt/inactive) {chk['known']} (absent {chk['absknown']}, played anyway {chk['knownPlayed']})")
        RES["check"][str(Y)] = dict(chk)

    P("\nloading offensive samples (bt_common)...")
    S = iter_samples(POS4)
    A = to_arrays(S); n = len(S)
    act, ship = A["act"], A["shipped"]
    X = {k: np.zeros(n) for k in FEATS}
    have = np.zeros(n, dtype=bool)
    for i, s in enumerate(S):
        f = feats.get(s["year"], {}).get((s["opp"], s["wk"]))
        if f is None:
            continue
        have[i] = True
        for k in FEATS:
            X[k][i] = f.get(k, 0.0)
    wk = A["wk"]; band = np.where(wk <= 8, 0, np.where(wk <= 13, 1, 2))
    P(f"  {n} player-weeks, {have.sum()} with opponent availability features (weeks >= {MIN_WK})")

    def ratio(m):
        return float(act[m].sum() / ship[m].sum()) if m.sum() else None

    def rel(mask, pm):
        num = nf = 0.0
        for b in (0, 1, 2):
            bm = pm & have & (band == b)
            fm = bm & mask; um = bm & ~mask
            if fm.sum() < 10 or um.sum() < 50:
                continue
            num += fm.sum() * ratio(fm) / ratio(um); nf += fm.sum()
        return num / nf if nf else None

    def bucket(name, pos, mask, pm):
        mm = mask & pm & have
        r, rl = ratio(mm), rel(mask, pm)
        P(f"  {pos:5s} {name:44s} n {int(mm.sum()):5d}  act/ship {r if r is None else round(r, 3)}  REL (same pos + week band) {rl if rl is None else round(rl, 3)}")
        RES["buckets"].append({"pos": pos, "name": name, "n": int(mm.sum()), "ratio": None if r is None else round(r, 3), "rel": None if rl is None else round(rl, 3)})

    P("\n=== buckets: opposing defense availability ===")
    for pos in POS4:
        pm = A["pos"] == pos
        bucket("healthy (no regular out)", pos, X["n_out"] == 0, pm)
        if pos in ("WR", "TE", "QB"):
            bucket("CB1 out (shipped boost covers WR/QB)", pos, X["cb1_out"] > 0, pm)
            bucket("1 DB regular out", pos, X["n_db"] == 1, pm)
            bucket("2+ DB regulars out", pos, X["n_db"] >= 2, pm)
            bucket("quality DB out beyond CB1 (cov_q_nocb1 >= 1)", pos, X["cov_q_nocb1"] >= 1.0, pm)
            bucket("quality DB out beyond CB1, KNOWN before lock", pos, X["cov_q_nocb1_known"] >= 1.0, pm)
            bucket("2+ DB regulars out, KNOWN before lock", pos, X["n_db_known"] >= 2, pm)
            bucket("quality pass rush out (rush_q >= 1.5)", pos, X["rush_q"] >= 1.5, pm)
            bucket("2+ pass rushers out", pos, X["n_rush"] >= 2, pm)
        if pos == "RB":
            bucket("1 front-7 regular out", pos, X["n_front"] == 1, pm)
            bucket("2+ front-7 regulars out", pos, X["n_front"] >= 2, pm)
            bucket("quality run defender out (run_q >= 1.5)", pos, X["run_q"] >= 1.5, pm)
            bucket("quality run defender out, KNOWN before lock", pos, X["run_q_known"] >= 1.5, pm)
            bucket("2+ front-7 regulars out, KNOWN before lock", pos, X["n_front_known"] >= 2, pm)
        bucket("3+ regulars out (any unit)", pos, X["n_out"] >= 3, pm)
        bucket("3+ regulars out, KNOWN before lock", pos, X["n_out_known"] >= 3, pm)
        bucket("heavy quality loss (all_q >= 3)", pos, X["all_q"] >= 3.0, pm)

    years = YEARS
    P("\n=== LOYO continuous: shipped x clip(1 + k x feature, 0.8, 1.25) ===")
    grid = [0.0, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12, -0.02]
    plan = {"WR": ["cov_q", "cov_q_nocb1", "cov_q_nocb1_known", "cov_q_fresh", "rush_q", "all_q", "all_q_known"],
            "TE": ["cov_q", "cov_q_known", "rush_q", "rush_q_known", "all_q", "all_q_known", "n_db_known"],
            "QB": ["cov_q", "cov_q_nocb1", "cov_q_known", "rush_q", "rush_q_known", "all_q", "all_q_known"],
            "RB": ["run_q", "run_q_known", "run_q_fresh", "n_front", "n_front_known", "all_q", "all_q_known"]}
    for pos, keys in plan.items():
        pm = A["pos"] == pos
        Ssub = {"year": A["year"][pm], "act": act[pm]}; sp = ship[pm]
        for k in keys:
            v = X[k][pm]
            loyo2(Ssub, years, grid, lambda kk, v=v, sp=sp: sp * np.clip(1 + kk * v, 0.8, 1.25),
                  f"{pos} x {k} (rows with feature > 0: {int((v > 0).sum())})", "continuous 1 + k x", f"{pos} {k}")

    P("\n=== LOYO flagged rows: shipped x m ===")
    fgrid = [1.0, 1.02, 1.04, 1.06, 1.08, 1.10, 0.98]
    flags = [("WR", "2+ DB regulars out", X["n_db"] >= 2), ("WR", "quality DB out beyond CB1", X["cov_q_nocb1"] >= 1.0),
             ("WR", "quality DB out beyond CB1, known", X["cov_q_nocb1_known"] >= 1.0),
             ("TE", "2+ DB regulars out", X["n_db"] >= 2), ("TE", "2+ DB regulars out, known", X["n_db_known"] >= 2),
             ("QB", "2+ DB regulars out", X["n_db"] >= 2), ("QB", "2+ DB regulars out, known", X["n_db_known"] >= 2),
             ("QB", "quality DB out beyond CB1, known", X["cov_q_nocb1_known"] >= 1.0),
             ("QB", "quality pass rush out", X["rush_q"] >= 1.5), ("QB", "quality pass rush out, known", X["rush_q_known"] >= 1.5),
             ("RB", "2+ front-7 regulars out", X["n_front"] >= 2), ("RB", "2+ front-7 regulars out, known", X["n_front_known"] >= 2),
             ("RB", "quality run defender out", X["run_q"] >= 1.5), ("RB", "quality run defender out, known", X["run_q_known"] >= 1.5),
             ("RB", "3+ regulars out, known", X["n_out_known"] >= 3), ("TE", "3+ regulars out, known", X["n_out_known"] >= 3)]
    for pos, lab, mask in flags:
        pm = A["pos"] == pos
        mk = mask[pm]
        if mk.sum() < 60:
            P(f"  {pos} {lab}: too few flagged rows ({int(mk.sum())})"); continue
        Ssub = {"year": A["year"][pm], "act": act[pm]}; sp = ship[pm]
        loyo2(Ssub, years, fgrid, lambda m, mk=mk, sp=sp: np.where(mk, sp * m, sp), f"{pos} {lab} (flagged n={int(mk.sum())})", "flagged rows x m", f"{pos} {lab}")

    # ---------------------------------------------------------------- DST side
    P("\n=== DST: own defense availability vs DST points (shipped = 16.2 - .436 x opp implied) ===")
    D = defaultdict(list)
    for Y in YEARS:
        frame, lines = DR.load_year(Y)
        imp = implied_map(lines)
        for r in frame.itertuples(index=False):
            oi = imp.get((r.opp, int(r.week)))
            f = feats.get(Y, {}).get((r.team, int(r.week)))
            if oi is None or f is None:
                continue
            D["year"].append(Y); D["act"].append(r.pts); D["ship"].append(max(1.0, 16.2 - 0.436 * oi)); D["wk"].append(int(r.week))
            for k in ("all_q", "all_q_pre", "all_q_known", "rush_q", "cov_q", "cov_q_known", "n_out", "n_out_pre", "n_out_known"):
                D[k].append(f.get(k, 0.0))
    D = {k: np.array(v, float) for k, v in D.items()}; D["year"] = D["year"].astype(int)
    dact, dship = D["act"], D["ship"]
    P(f"  {len(dact)} DST team-weeks (weeks >= {MIN_WK}); mean actual {dact.mean():.2f} vs shipped {dship.mean():.2f}")
    for lab, m in (("healthy", D["n_out"] == 0), ("1-2 regulars out", (D["n_out"] >= 1) & (D["n_out"] <= 2)), ("3+ regulars out", D["n_out"] >= 3),
                   ("all_q >= 3 (heavy quality loss)", D["all_q"] >= 3), ("pass rush q >= 1.5 out", D["rush_q"] >= 1.5),
                   ("3+ regulars out, known before lock", D["n_out_known"] >= 3), ("all_q >= 3, known before lock", D["all_q_known"] >= 3)):
        if m.sum():
            diff = float((dact[m] - dship[m]).mean())
            P(f"  DST {lab:34s} n {int(m.sum()):4d}  actual - shipped {diff:+.2f} pts")
            RES["buckets"].append({"pos": "DST", "name": lab, "n": int(m.sum()), "ratio": round(float(dact[m].mean() / dship[m].mean()), 3), "diff": round(diff, 2)})
    dgrid = [0.0, -0.25, -0.5, -1.0, -1.5, -2.0, 0.5]
    for k in ("all_q", "all_q_pre", "all_q_known", "rush_q", "cov_q", "cov_q_known", "n_out", "n_out_known"):
        v = D[k]
        loyo2({"year": D["year"], "act": dact}, years, dgrid, lambda kk, v=v: np.maximum(0.0, dship + kk * v), f"DST shipped + k x {k}", "DST additive pts", f"DST {k}")

    RES["n"] = int(n); RES["years"] = years; RES["updated"] = time.strftime("%Y-%m-%d %H:%M")
    RES["bar"] = {"pct": SHIP_PCT, "wins": SHIP_WINS}
    passed = [r for r in RES["loyo"] if r["verdict"] == "PASS"]
    RES["summary"] = (f"Defense availability: {len(RES['loyo'])} tests on {n} player-weeks + DST, LOYO 2019-25; " +
                      (f"{len(passed)} pass: " + "; ".join(f"{r['pos']} {r['pct']:+.2f}% ({r['wins']}/7)" for r in passed) if passed else "none pass the ship bar"))
    with open(os.path.join(HERE, "data", "def_avail_backtest.js"), "w", encoding="utf-8") as fh:
        fh.write("// built by backtest_def_avail.py - defense availability (missing regular defenders x quality) LOYO verdicts; shown on the ZONES tab\n")
        fh.write("window.SIM_DEFAV_BT = "); json.dump(RES, fh, separators=(",", ":")); fh.write(";\n")
    P(f"\nwrote data/def_avail_backtest.js: {RES['summary']}")
    P("done")


if __name__ == "__main__":
    main()
