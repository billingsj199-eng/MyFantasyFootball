#!/usr/bin/env python3
"""
AGE x EXPERIENCE WORKLOAD CURVES (2026-09-15).

Jack: "projecting trends of increase workload or decrease workload throughout the seasons
based on age/experience/injuries" -> "start on the age and experience workload curves next".

Two questions, two uses:

PART A - IN-SEASON (would be a live layer): does the shipped projection drift wrong as the
season goes on for young / old / inexperienced players? bt_common samples 2019-25 (QB/RB/WR/TE,
shipped = P=5 blend x Vegas x FPA). The engine also ships a snap-trend layer (snapMult, 1%/snap
point) that bt_common's base lacks, so everything is graded on base2 = shipped x snapMult
rebuilt from nflverse snap counts - the increment beyond what already ships.
  buckets    actual / base2 by position x age bucket x week band (2-6 / 7-12 / 13-18) and by
             experience bucket, REL = bucket ratio / all rows of that position + band
  workload   within-player trajectories: snap share and touches per game by band, relative to
             the same player's weeks 2-6, by position x experience and age
  LOYO       rookie x week slope, second-year x week slope, old x late flag, continuous
             age x week interaction, age level (does the blend already price age?)

PART B - SEASON OVER SEASON (feeds the Clay-free shadow prior and next preseason): player-season
table from the weekly DB 2014-2025 (games >= 6). Prior = the shadow's 3-yr weighted PPG (.5/.3/.2
over seasons with >= 6 games, Y-1 required). Target = PPG in Y.
  curves     multiplier by position x age (pairs within +-1 year pooled, log-ratio shrunk K=30) for
             PPG and touches per game; experience curve (2nd, 3rd, 4th, 5th+ season); availability =
             P(>= 6 games in Y | >= 6 in Y-1) by position x age
  LOYO       over seasons 2019-2025: prior x age curve, prior x exp curve, prior x both, vs prior
             (curves refit without the held-out season)

Ship bar (README): <= -0.3% LOYO MSE with >= 5/7 years better. Log age_exp_backtest.log;
results -> data/age_exp_backtest.js (SIM_AGEEXP_BT), ZONES tab.
"""
import json, math, os, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B
from bt_common import iter_samples, to_arrays, POS4
from backtest_target_area import mse
import backtest_sim_calibration as cal

LOG = open(os.path.join(HERE, "age_exp_backtest.log"), "w", encoding="utf-8")


class _Tee:
    def __init__(self, a, b): self.a, self.b = a, b
    def write(self, t): self.a.write(t); self.b.write(t); self.a.flush(); self.b.flush()
    def flush(self): self.a.flush(); self.b.flush()


sys.stdout = _Tee(sys.stdout, LOG)
def P(*a): print(" ".join(str(x) for x in a))

YEARS = list(range(2019, 2026))
AGE_MID = {"QB": 29, "RB": 25, "WR": 26, "TE": 27}
OLD = {"QB": 35, "RB": 28, "WR": 30, "TE": 30}
AGE_BUCKETS = {"QB": [(0, 25, "<=25"), (26, 29, "26-29"), (30, 33, "30-33"), (34, 99, "34+")],
               "RB": [(0, 23, "<=23"), (24, 25, "24-25"), (26, 27, "26-27"), (28, 99, "28+")],
               "WR": [(0, 23, "<=23"), (24, 26, "24-26"), (27, 29, "27-29"), (30, 99, "30+")],
               "TE": [(0, 24, "<=24"), (25, 27, "25-27"), (28, 30, "28-30"), (31, 99, "31+")]}
EXP_BUCKETS = [(0, 0, "rookie"), (1, 1, "yr2"), (2, 3, "yr3-4"), (4, 6, "yr5-7"), (7, 99, "yr8+")]
BANDS = [(2, 6, "wk2-6"), (7, 12, "wk7-12"), (13, 18, "wk13-18")]
SNAP_W = [0.5, 0.3, 0.2]
K_CURVE = 30.0
SHIP_PCT, SHIP_WINS = -0.30, 5
RES = {"loyo": [], "inseason": [], "workload": [], "yoy": {}, "yoyExp": {}, "n": 0}


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


def load_bio():
    p = pd.read_csv(os.path.join(B.CACHE, "players.csv"), usecols=["gsis_id", "birth_date", "rookie_season"], low_memory=False)
    bio = {}
    for r in p.itertuples(index=False):
        if not isinstance(r.gsis_id, str):
            continue
        bd = pd.to_datetime(r.birth_date, errors="coerce") if isinstance(r.birth_date, str) else pd.NaT
        bio[r.gsis_id] = (bd, int(r.rookie_season) if pd.notna(r.rookie_season) else None)
    return bio


def age_at(bd, Y):
    if bd is None or pd.isna(bd):
        return None
    return (pd.Timestamp(Y, 9, 1) - bd).days / 365.25


def bucket_of(v, buckets):
    for lo, hi, lab in buckets:
        if lo <= v <= hi:
            return lab
    return None


def load_snaps(Y):
    d = pd.read_parquet(os.path.join(B.CACHE, f"snap_counts_{Y}.parquet"),
                        columns=["week", "game_type", "player", "position", "team", "offense_snaps", "offense_pct"])
    d = d[(d.game_type == "REG") & d.position.isin(POS4) & (d.offense_snaps > 0)]
    out = defaultdict(dict)
    for r in d.itertuples(index=False):
        out[(B.cal.norm(str(r.player)), B.tm(str(r.team)))][int(r.week)] = 100.0 * float(r.offense_pct)
    return out


def snap_mult(wkpct, wk):
    past = sorted([w for w in wkpct if w < wk], reverse=True)
    if len(past) < 2 or past[0] < wk - 3:
        return 1.0
    rec = sum(wkpct[w] * SNAP_W[i] for i, w in enumerate(past[:3])) / sum(SNAP_W[:len(past[:3])])
    avg = float(np.mean([wkpct[w] for w in past]))
    return min(1.30, max(0.75, 1 + (rec - avg) / 100.0))


def band_of(wk):
    for lo, hi, lab in BANDS:
        if lo <= wk <= hi:
            return lab
    return None


def part_a(bio):
    P("\n================ PART A: IN-SEASON ================")
    snaps = {Y: load_snaps(Y) for Y in YEARS}
    S = iter_samples(POS4)
    A = to_arrays(S); n = len(S)
    act, ship = A["act"], A["shipped"]
    age = np.full(n, np.nan); exp = np.full(n, np.nan); sm = np.ones(n)
    for i, s in enumerate(S):
        b = bio.get(s["pid"]) if s["pid"] else None
        if b:
            a = age_at(b[0], s["year"])
            if a is not None: age[i] = a
            if b[1] is not None: exp[i] = s["year"] - b[1]
        wp = snaps[s["year"]].get((B.cal.norm(s["name"]), s["team"]))
        if wp:
            sm[i] = snap_mult(wp, s["wk"])
    base2 = ship * sm
    wk = A["wk"]; pos = A["pos"]
    bandlab = np.array([band_of(int(w)) for w in wk], dtype=object)
    P(f"  {n} player-weeks; age known {int(np.isfinite(age).sum())}, exp known {int(np.isfinite(exp).sum())}; "
      f"snap trend active on {int((sm != 1).sum())} rows; MSE shipped {mse(ship, act):.3f} vs base2 (x snapMult) {mse(base2, act):.3f}")
    RES["n"] = int(n)

    def ratio(m):
        return float(act[m].sum() / base2[m].sum()) if m.sum() else None

    P("\n=== actual / base2 by position x AGE bucket x week band (REL = / all rows of that position + band) ===")
    ageint = np.floor(age)
    for p in POS4:
        for lo, hi, lab in AGE_BUCKETS[p]:
            parts = []
            for blo, bhi, blab in BANDS:
                ref = (pos == p) & (bandlab == blab)
                m = ref & (ageint >= lo) & (ageint <= hi)
                if m.sum() < 30:
                    parts.append(f"{blab} -"); continue
                rl = ratio(m) / ratio(ref)
                parts.append(f"{blab} {rl:.3f} (n {int(m.sum())})")
                RES["inseason"].append({"kind": "age", "pos": p, "bucket": lab, "band": blab, "n": int(m.sum()), "rel": round(rl, 3)})
            P(f"  {p} age {lab:6s} " + " | ".join(parts))
    P("\n=== actual / base2 by position x EXPERIENCE bucket x week band ===")
    for p in POS4:
        for lo, hi, lab in EXP_BUCKETS:
            parts = []
            for blo, bhi, blab in BANDS:
                ref = (pos == p) & (bandlab == blab)
                m = ref & (exp >= lo) & (exp <= hi)
                if m.sum() < 30:
                    parts.append(f"{blab} -"); continue
                rl = ratio(m) / ratio(ref)
                parts.append(f"{blab} {rl:.3f} (n {int(m.sum())})")
                RES["inseason"].append({"kind": "exp", "pos": p, "bucket": lab, "band": blab, "n": int(m.sum()), "rel": round(rl, 3)})
            P(f"  {p} {lab:7s} " + " | ".join(parts))

    # ---- within-player workload trajectories ----
    P("\n=== WORKLOAD within player: snap share and touches/g by band, relative to the same player's weeks 2-6 ===")
    seen = {}
    for i, s in enumerate(S):
        k = (s["year"], s["name"], s["pos"])
        if k not in seen:
            seen[k] = (s, age[i], exp[i])
    traj = defaultdict(lambda: {"snap": [[], []], "tou": [[], []]})
    for (Y, name, p), (s, a, e) in seen.items():
        wp = snaps[Y].get((B.cal.norm(name), s["team"]), {})
        rec = cal.weekly_rec(name, p)
        rows = [r for r in (rec or {}).get("seasons", {}).get(str(Y), []) if cal.played(r)] if rec else []
        tou = {int(r["wk"]): (r.get("pa") or 0) + (r.get("ra") or 0) if p == "QB" else (r.get("tgt") or 0) + (r.get("ra") or 0) for r in rows}
        keys = []
        if np.isfinite(e): keys.append(("exp", p, bucket_of(int(e), EXP_BUCKETS)))
        if np.isfinite(a): keys.append(("age", p, bucket_of(int(math.floor(a)), AGE_BUCKETS[p])))
        for metric, src in (("snap", wp), ("tou", tou)):
            bands = {lab: [v for w, v in src.items() if lo <= w <= hi] for lo, hi, lab in BANDS}
            if min(len(bands[lab]) for _, _, lab in BANDS) < 2:
                continue
            b1 = np.mean(bands["wk2-6"])
            if b1 <= (10 if metric == "snap" else 2):
                continue
            r2, r3 = np.mean(bands["wk7-12"]) / b1, np.mean(bands["wk13-18"]) / b1
            for k in keys:
                if k[2]:
                    traj[k][metric][0].append(r2); traj[k][metric][1].append(r3)
    for kind in ("exp", "age"):
        for p in POS4:
            labs = [b[2] for b in (EXP_BUCKETS if kind == "exp" else AGE_BUCKETS[p])]
            for lab in labs:
                t = traj.get((kind, p, lab))
                if not t:
                    continue
                parts = []
                rec = {"kind": kind, "pos": p, "bucket": lab}
                for metric in ("snap", "tou"):
                    r2, r3 = t[metric]
                    if len(r2) >= 15:
                        parts.append(f"{metric} wk7-12 {np.mean(r2):.3f} wk13-18 {np.mean(r3):.3f} (n {len(r2)})")
                        rec[metric] = [round(float(np.mean(r2)), 3), round(float(np.mean(r3)), 3), len(r2)]
                if parts:
                    P(f"  {p} {kind} {lab:7s} " + " | ".join(parts))
                    RES["workload"].append(rec)

    # ---- LOYO ----
    years = YEARS
    P("\n=== LOYO in-season terms on base2 (shipped x snapMult) ===")
    wkc = (wk - 9.5) / 8.0
    grid_s = [0.0, 0.02, 0.05, 0.08, 0.12, -0.03, -0.06]
    for p in POS4:
        pm = pos == p
        Ssub = {"year": A["year"][pm], "act": act[pm]}; b2 = base2[pm]; wc = wkc[pm]
        rook = np.nan_to_num(exp[pm], nan=99) == 0
        yr2 = np.nan_to_num(exp[pm], nan=99) == 1
        oldm = np.nan_to_num(np.floor(age[pm]), nan=0) >= OLD[p]
        late = wk[pm] >= 10
        az = np.nan_to_num((age[pm] - AGE_MID[p]) / 5.0, nan=0.0)
        if rook.sum() >= 60:
            loyo2(Ssub, years, grid_s, lambda k, m=rook, b2=b2, wc=wc: b2 * np.clip(1 + k * m * wc, 0.8, 1.25), f"{p} rookie x week slope (rows {int(rook.sum())})", "rookie x (wk-9.5)/8", f"{p} rookie ramp")
        if yr2.sum() >= 60:
            loyo2(Ssub, years, grid_s, lambda k, m=yr2, b2=b2, wc=wc: b2 * np.clip(1 + k * m * wc, 0.8, 1.25), f"{p} 2nd-year x week slope (rows {int(yr2.sum())})", "yr2 x (wk-9.5)/8", f"{p} 2nd-year ramp")
        lvl_grid = [1.0, 1.03, 1.06, 1.09, 1.12, 1.15, 0.97]
        if rook.sum() >= 60:
            loyo2(Ssub, years, lvl_grid, lambda m_, mk=rook, b2=b2: np.where(mk, b2 * m_, b2), f"{p} rookie LEVEL (rows {int(rook.sum())})", "rookie flag x m", f"{p} rookie level")
        if yr2.sum() >= 60:
            loyo2(Ssub, years, lvl_grid, lambda m_, mk=yr2, b2=b2: np.where(mk, b2 * m_, b2), f"{p} 2nd-year LEVEL (rows {int(yr2.sum())})", "yr2 flag x m", f"{p} 2nd-year level")
        mk = oldm & late
        if mk.sum() >= 60:
            loyo2(Ssub, years, [1.0, 0.97, 0.94, 0.91, 1.03], lambda m_, mk=mk, b2=b2: np.where(mk, b2 * m_, b2), f"{p} age >= {OLD[p]} in weeks 10+ (rows {int(mk.sum())})", "old x late flag", f"{p} old late")
        loyo2(Ssub, years, [0.0, 0.02, 0.04, 0.08, -0.02, -0.04, -0.08], lambda k, az=az, b2=b2, wc=wc: b2 * np.clip(1 + k * az * wc, 0.8, 1.25), f"{p} age x week interaction", "(age-mid)/5 x (wk-9.5)/8", f"{p} age x week")
        loyo2(Ssub, years, [0.0, 0.02, 0.04, 0.08, -0.02, -0.04, -0.08], lambda k, az=az, b2=b2: b2 * np.clip(1 + k * az, 0.8, 1.25), f"{p} age level", "(age-mid)/5 level", f"{p} age level")


# ------------------------------------------------------------------ PART B
def part_b(bio):
    P("\n================ PART B: SEASON OVER SEASON ================")
    resolve = B.player_ids()
    table = {}     # (norm, pos) -> {Y: (g, ppg, tou)}
    meta = {}      # (norm, pos) -> gsis per Y
    for nk, recs in cal.WEEKLY.items():
        byp = defaultdict(list)
        for r in recs:
            if r.get("pos") in POS4:
                byp[r["pos"]].append(r)
        for p, rs in byp.items():
            if len(rs) != 1:
                continue                     # name collision at the position: skip
            rec = rs[0]; seasons = {}
            for ys, rows in rec.get("seasons", {}).items():
                if not ys.isdigit() or not (2013 <= int(ys) <= 2025):
                    continue
                pl = [r for r in rows if cal.played(r) and isinstance(r.get("fpts"), (int, float))]
                if not pl:
                    continue
                tou = [(r.get("pa") or 0) + (r.get("ra") or 0) if p == "QB" else (r.get("tgt") or 0) + (r.get("ra") or 0) for r in pl]
                seasons[int(ys)] = (len(pl), float(np.mean([r["fpts"] for r in pl])), float(np.mean(tou)))
            if seasons:
                table[(nk, p)] = seasons
    pairs = []
    avail = []
    for (nk, p), seas in table.items():
        for Y in range(2016, 2026):
            prev = seas.get(Y - 1)
            if not prev or prev[0] < 6 or prev[1] < 4.0:
                continue
            gsis = resolve(nk, p, Y) or resolve(nk, p, Y - 1)
            b = bio.get(gsis) if gsis else None
            if not b:
                continue
            a = age_at(b[0], Y); e = (Y - b[1]) if b[1] is not None else None
            if a is None:
                continue
            cur = seas.get(Y)
            avail.append((p, int(math.floor(a)), 1 if (cur and cur[0] >= 6) else 0, Y))
            if not cur or cur[0] < 6:
                continue
            w, num, tnum = 0.0, 0.0, 0.0
            for lag, wt in ((1, 0.5), (2, 0.3), (3, 0.2)):
                s3 = seas.get(Y - lag)
                if s3 and s3[0] >= 6:
                    w += wt; num += wt * s3[1]; tnum += wt * s3[2]
            prior, tprior = num / w, tnum / w
            if prior < 4.0 or tprior < 1.0:
                continue
            pairs.append({"pos": p, "Y": Y, "age": int(math.floor(a)), "exp": e, "prior": prior, "act": cur[1],
                          "lr": math.log(max(cur[1], 0.5) / prior), "tlr": math.log(max(cur[2], 0.2) / tprior)})
    P(f"  {len(pairs)} player-season pairs 2016-2025 (>= 6 games both, prior PPG >= 4); availability rows {len(avail)}")

    def fit_age(rows, key="lr"):
        out = {}
        for p in POS4:
            rp = [r for r in rows if r["pos"] == p]
            ages = [r["age"] for r in rp]
            if not ages:
                continue
            for a in range(min(ages), max(ages) + 1):
                v = [r[key] for r in rp if abs(r["age"] - a) <= 1]
                if v:
                    out[(p, a)] = (math.exp(np.mean(v) * len(v) / (len(v) + K_CURVE)), len(v))
        return out

    def fit_exp(rows):
        out = {}
        for p in POS4:
            for e in (1, 2, 3, 4):
                v = [r["lr"] for r in rows if r["pos"] == p and r["exp"] is not None and (r["exp"] == e if e < 4 else r["exp"] >= 4)]
                if v:
                    out[(p, e)] = (math.exp(np.mean(v) * len(v) / (len(v) + K_CURVE)), len(v))
        return out

    allA, allT, allE = fit_age(pairs), fit_age(pairs, "tlr"), fit_exp(pairs)
    av = defaultdict(list)
    for p, a, ok, Y in avail:
        for aa in (a - 1, a, a + 1):
            av[(p, aa)].append(ok)
    P("\n=== YoY multiplier on the 3-yr prior by position x age (PPG | touches/g | P(keeps a 6+ game role)) ===")
    for p in POS4:
        rows = []
        RES["yoy"][p] = []
        for (pp, a), (m, nn) in sorted(allA.items()):
            if pp != p or nn < 25:
                continue
            tm_ = allT.get((p, a), (None, 0))[0]
            avl = av.get((p, a), [])
            ar = float(np.mean(avl)) if len(avl) >= 25 else None
            rows.append(f"{a}: {m:.2f}|{tm_:.2f}|{'-' if ar is None else f'{ar:.2f}'} (n {nn})")
            RES["yoy"][p].append({"age": a, "n": nn, "ppg": round(m, 3), "tou": round(tm_, 3) if tm_ else None, "avail": None if ar is None else round(ar, 3)})
        P(f"  {p}: " + "  ".join(rows))
    P("\n=== YoY multiplier by experience (season number) ===")
    for p in POS4:
        RES["yoyExp"][p] = []
        parts = []
        for e in (1, 2, 3, 4):
            if (p, e) in allE:
                m, nn = allE[(p, e)]
                lab = {1: "2nd", 2: "3rd", 3: "4th", 4: "5th+"}[e]
                parts.append(f"{lab} season {m:.2f} (n {nn})")
                RES["yoyExp"][p].append({"season": lab, "n": nn, "ppg": round(m, 3)})
        P(f"  {p}: " + " | ".join(parts))

    P("\n=== LOYO season-over-season: PPG_Y predicted by the 3-yr prior x curve (curves refit without the held-out season) ===")
    for label, use_age, use_exp in (("prior x age curve", True, False), ("prior x experience curve", False, True), ("prior x age x experience (exp <= 4th season)", True, True)):
        for p in POS4 + ("ALL",):
            tot_b = tot_c = 0.0; nrows = 0; wins = 0; ys = 0
            for Y in YEARS:
                test = [r for r in pairs if r["Y"] == Y and (p == "ALL" or r["pos"] == p)]
                if len(test) < 20:
                    continue
                train = [r for r in pairs if r["Y"] != Y]
                fa = fit_age(train) if use_age else {}
                fe = fit_exp(train) if use_exp else {}
                pb = np.array([r["prior"] for r in test]); ac = np.array([r["act"] for r in test])
                mult = np.ones(len(test))
                for i, r in enumerate(test):
                    if use_age:
                        mult[i] *= fa.get((r["pos"], r["age"]), (1.0, 0))[0]
                    if use_exp and r["exp"] is not None and r["exp"] <= (3 if use_age else 99):
                        e = r["exp"] if r["exp"] < 4 else 4
                        if e >= 1:
                            mult[i] *= fe.get((r["pos"], e), (1.0, 0))[0]
                eb, ec = mse(pb, ac), mse(pb * mult, ac)
                tot_b += eb * len(test); tot_c += ec * len(test); nrows += len(test); wins += ec < eb; ys += 1
            if not nrows:
                continue
            pct = (tot_c / tot_b - 1) * 100
            verdict = "PASS" if (pct <= SHIP_PCT and wins >= SHIP_WINS) else ("lean" if (pct <= -0.1 and wins >= 4) else "FAIL")
            P(f"  {p:4s} {label:46s} MSE {tot_c / nrows:.3f} vs prior {tot_b / nrows:.3f} ({pct:+.2f}%), years better {wins}/{ys}, n {nrows}  {verdict}")
            RES["loyo"].append({"label": f"{p} YoY {label}", "family": "season-over-season curve", "pos": f"{p} {label}", "n": int(nrows), "best": 1.0,
                                "pct": round(pct, 3), "wins": int(wins), "years": ys, "picks": [], "verdict": verdict})
    P("\n=== CONTROLS: is it age, or plain regression of high priors? (log act = a + b log prior, smeared) ===")

    def fit_reg(rows):
        out = {}
        for p in POS4:
            rp = [r for r in rows if r["pos"] == p]
            if len(rp) < 30:
                continue
            x = np.log([r["prior"] for r in rp]); y = np.log([max(r["act"], 0.5) for r in rp])
            b, a = np.polyfit(x, y, 1)
            smear = float(np.mean(np.exp(y - (a + b * x))))
            out[p] = (float(a), float(b), smear)
        return out

    def resid_rows(rows, reg):
        out = []
        for r in rows:
            a, b, sm = reg.get(r["pos"], (0.0, 1.0, 1.0))
            out.append(dict(r, lr=math.log(max(r["act"], 0.5)) - (a + b * math.log(r["prior"])) - math.log(sm)))
        return out

    def predict(model, train, test):
        pb = np.array([r["prior"] for r in test])
        if model == "constant":
            mult = {}
            for p in POS4:
                v = [r["lr"] for r in train if r["pos"] == p]
                mult[p] = float(np.mean(np.exp(v))) if v else 1.0
            return pb * np.array([mult[r["pos"]] for r in test])
        reg = fit_reg(train)
        base = np.array([math.exp(reg[r["pos"]][0] + reg[r["pos"]][1] * math.log(r["prior"])) * reg[r["pos"]][2] if r["pos"] in reg else r["prior"] for r in test])
        if model == "regression":
            return base
        rr = resid_rows(train, reg)
        if model == "regression + age":
            fa = fit_age(rr)
            return base * np.array([fa.get((r["pos"], r["age"]), (1.0, 0))[0] for r in test])
        if model == "regression + exp":
            fe = fit_exp(rr)
            return base * np.array([fe.get((r["pos"], min(r["exp"], 4)), (1.0, 0))[0] if (r["exp"] is not None and r["exp"] >= 1) else 1.0 for r in test])
        if model == "regression + age + exp<=4th":
            fa = fit_age(rr); fe = fit_exp(rr)
            m = []
            for r in test:
                v = fa.get((r["pos"], r["age"]), (1.0, 0))[0]
                if r["exp"] is not None and 1 <= r["exp"] <= 3:
                    v *= fe.get((r["pos"], r["exp"]), (1.0, 0))[0]
                m.append(v)
            return base * np.array(m)
        raise ValueError(model)

    for model, ref in (("constant", "prior"), ("regression", "prior"), ("regression + age", "regression"),
                       ("regression + exp", "regression"), ("regression + age + exp<=4th", "regression")):
        for p in POS4 + ("ALL",):
            tot_r = tot_c = 0.0; nrows = 0; wins = 0; ys = 0
            for Y in YEARS:
                test = [r for r in pairs if r["Y"] == Y and (p == "ALL" or r["pos"] == p)]
                if len(test) < 20:
                    continue
                train = [r for r in pairs if r["Y"] != Y]
                ac = np.array([r["act"] for r in test])
                pr = np.array([r["prior"] for r in test]) if ref == "prior" else predict("regression", train, test)
                pc = predict(model, train, test)
                er, ec = mse(pr, ac), mse(pc, ac)
                tot_r += er * len(test); tot_c += ec * len(test); nrows += len(test); wins += ec < er; ys += 1
            if not nrows:
                continue
            pct = (tot_c / tot_r - 1) * 100
            verdict = "PASS" if (pct <= SHIP_PCT and wins >= SHIP_WINS) else ("lean" if (pct <= -0.1 and wins >= 4) else "FAIL")
            P(f"  {p:4s} {model:30s} vs {ref:10s} MSE {tot_c / nrows:.3f} vs {tot_r / nrows:.3f} ({pct:+.2f}%), years better {wins}/{ys}, n {nrows}  {verdict}")
            RES["loyo"].append({"label": f"{p} YoY {model} vs {ref}", "family": f"season-over-season, graded vs {ref}", "pos": f"{p} {model} (vs {ref})",
                                "n": int(nrows), "best": 1.0, "pct": round(pct, 3), "wins": int(wins), "years": ys, "picks": [], "verdict": verdict})
    reg_all = fit_reg(pairs)
    rr_all = resid_rows(pairs, reg_all)
    ra, re_ = fit_age(rr_all), fit_exp(rr_all)
    RES["regAll"] = {p: [round(v[0], 4), round(v[1], 4), round(v[2], 4)] for p, v in reg_all.items()}
    RES["curvesResid"] = {p: {str(a): round(m, 3) for (pp, a), (m, nn) in ra.items() if pp == p and nn >= 25} for p in POS4}
    RES["expResid"] = {p: {str(e): round(m, 3) for (pp, e), (m, nn) in re_.items() if pp == p} for p in POS4}
    P("  regression per position (a, b, smear): " + "; ".join(f"{p} {v[0]:+.2f} {v[1]:.2f} {v[2]:.3f}" for p, v in reg_all.items()))
    P("  residual age curves: " + " | ".join(p + " " + ", ".join(f"{a}:{m}" for a, m in RES["curvesResid"][p].items()) for p in POS4))
    P("  residual experience curves: " + " | ".join(p + " " + ", ".join(f"{e}:{m}" for e, m in RES["expResid"][p].items()) for p in POS4))

    # curves shipped with the results so the shadow prior can read them
    RES["curvesAll"] = {p: {str(a): round(m, 3) for (pp, a), (m, nn) in allA.items() if pp == p and nn >= 25} for p in POS4}
    RES["expAll"] = {p: {str(e): round(m, 3) for (pp, e), (m, nn) in allE.items() if pp == p} for p in POS4}


def main():
    bio = load_bio()
    P(f"players.csv bio rows: {len(bio)}")
    part_a(bio)
    part_b(bio)
    RES["updated"] = time.strftime("%Y-%m-%d %H:%M"); RES["years"] = YEARS; RES["bar"] = {"pct": SHIP_PCT, "wins": SHIP_WINS}
    passed = [r for r in RES["loyo"] if r["verdict"] == "PASS"]
    RES["summary"] = (f"Age x experience: {len(RES['loyo'])} LOYO tests (in-season on {RES['n']} player-weeks + season-over-season curves); " +
                      (f"{len(passed)} pass: " + "; ".join(f"{r['pos']} {r['pct']:+.2f}% ({r['wins']}/{r['years']})" for r in passed) if passed else "none pass the ship bar"))
    with open(os.path.join(HERE, "data", "age_exp_backtest.js"), "w", encoding="utf-8") as fh:
        fh.write("// built by backtest_age_exp.py - age x experience: in-season drift, workload trajectories, season-over-season curves; shown on the ZONES tab\n")
        fh.write("window.SIM_AGEEXP_BT = "); json.dump(RES, fh, separators=(",", ":")); fh.write(";\n")
    P(f"\nwrote data/age_exp_backtest.js: {RES['summary']}")
    P("done")


if __name__ == "__main__":
    main()
