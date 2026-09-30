#!/usr/bin/env python3
"""
CLAY-FREE WEEKLY LADDER (2026-09-16).

Jack: "continue to tweak our sim labs to improve them and eventually remove Clay's projections."
The live Clay-free shadow (engine ncMean) is graded live from W2 on, one week at a time. This is the
historical version of that scorecard: the SAME shadow prior rebuilt walk-forward for every 2019-25
player-week, graded against the shipped Clay blend, so we know the size of the gap, WHERE it lives
(week of season / position / segment) and which knob closes it - before the live ledger has a sample.

Samples: every Clay-pool player-week 2019-25 (QB/RB/WR/TE, >= 40 Clay pts, played, game has a line),
INCLUDING week 1 (bt_common drops g=0 rows; here the prior IS the projection in week 1).
  shipped   = P=5 blend(Clay per game, season-to-date PPG) x Vegas(pos e) x in-season FPA
  shadow    = the same blend and layers with the prior swapped:
    H3      3-yr weighted PPG (.5/.3/.2 over Y-1..Y-3, >= 4 games a season, >= 8 total)  = engine histPpg
    L8      last 8 played games before this week across Y-2..Y (>= 4)                      = refresh_data l8
    MIX     .5 H3 + .5 L8 (whichever exist)                                                 = engine ncPrior
    +AGE    engine SHADOW_AGE log-regression + age curve (prior >= 4 half PPG)               = shadowAgeAdjust
    +OPP    vets: calibrated history + opportunity prior (opp_prior_preds.json SHADOWCAL)   ~ engine +opp
    fallback (no H3, no L8 = rookies + no history): Clay (the live shadow) or the Clay-free options
            POS  position mean of the pool (other seasons)
            DC   rookies: draft-round bucket mean (other seasons), others POS
            ROOK rookies: opportunity prior where it exists (SHADOWCAL), else DC
Every "other seasons" constant is leave-one-year-out. Sweeps are LOYO too (pick on the other six).

Ship bar (README): <= -0.3% LOYO MSE with >= 5/7 years better - but the question here is the reverse:
how much WORSE than Clay is each Clay-free version, and where. Log noclay_weekly_backtest.log;
results -> data/noclay_weekly_backtest.js (SIM_NOCLAY_BT), ZONES tab.
"""
import json, os, re, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B
import backtest_sim_calibration as cal
from backtest_snap_defense import build_fpa
from backtest_target_area import mse

class _Tee:
    def __init__(self, a, b): self.a, self.b = a, b
    def write(self, t): self.a.write(t); self.b.write(t); self.a.flush(); self.b.flush()
    def flush(self): self.a.flush(); self.b.flush()


if __name__ == "__main__":   # importable by backtest_rookie_prior.py without truncating this log
    sys.stdout = _Tee(sys.stdout, open(os.path.join(HERE, "noclay_weekly_backtest.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

YEARS = list(range(2019, 2026))
PRIOR_P = 5
W3 = (0.5, 0.3, 0.2)
MIN_SEASON_G, MIN_H3_G, MIN_L8_G = 4, 8, 4
POS4 = ("QB", "RB", "WR", "TE")
BANDS = [("wk1", 1, 1), ("wk2-4", 2, 4), ("wk5-8", 5, 8), ("wk9-12", 9, 12), ("wk13+", 13, 18)]
RES = {"n": 0, "variants": [], "bands": [], "segments": [], "sweeps": [], "fallback": [], "updated": time.strftime("%Y-%m-%d %H:%M")}


def load_shadow_age():
    src = open(os.path.join(HERE, "engine.js"), encoding="utf-8").read()
    m = re.search(r"var SHADOW_AGE = (\{.*?\});\n", src)
    return json.loads(m.group(1))


SHADOW_AGE = load_shadow_age()


def age_adjust(pos, half, age):
    """engine shadowAgeAdjust: log regression toward the position mean, then the residual age curve."""
    if not (half >= 4):
        return half
    v = half
    rg = SHADOW_AGE.get("useReg") and SHADOW_AGE["reg"].get(pos)
    if rg:
        v = np.exp(rg[0] + rg[1] * np.log(v)) * rg[2]
    ac = SHADOW_AGE.get("useAge") and SHADOW_AGE["age"].get(pos)
    if ac and age is not None and not np.isnan(age):
        ks = sorted(int(k) for k in ac)
        a = min(ks[-1], max(ks[0], int(np.floor(age))))
        if ac.get(str(a)) is not None:
            v *= ac[str(a)]
    return v


def season_pts(wrec, yy):
    return [w["fpts"] for w in wrec.get("seasons", {}).get(str(yy), []) if cal.played(w) and isinstance(w.get("fpts"), (int, float))]


def build_shares():
    """per (norm, pos, Y): team + share of the team's Y pool (targets WR/TE, carries RB, pass attempts QB) - the
    historical proxy for the depth chart: a rookie's n_ahead = returning teammates with a real share last year."""
    per, pool = {}, defaultdict(lambda: [0.0, 0.0, 0.0])
    for nk, lst in cal.WEEKLY.items():
        for rec in lst:
            pos = rec.get("pos")
            if pos not in POS4:
                continue
            for Ys, rws in rec.get("seasons", {}).items():
                Y = int(Ys); rws = [w for w in rws if cal.played(w)]
                if len(rws) < 2:
                    continue
                t = cal.infer_team(rec, Y)
                tg = sum(w.get("tgt") or 0 for w in rws); car = sum(w.get("ra") or 0 for w in rws); pa = sum(w.get("pa") or 0 for w in rws)
                per[(nk, pos, Y)] = {"team": t, "tgt": tg, "car": car, "pa": pa}
                if t:
                    pool[(t, Y)][0] += tg; pool[(t, Y)][1] += car; pool[(t, Y)][2] += pa
    roster = defaultdict(list)
    for (nk, pos, Y), d in per.items():
        if d["team"]:
            roster[(d["team"], pos, Y)].append((nk, d))
    def n_ahead(nk, pos, team, Y):
        tp = pool.get((team, Y - 1))
        if not tp or tp[0] < 150:
            return np.nan
        n = 0
        for onk, od in roster.get((team, pos, Y - 1), []):
            if onk == nk:
                continue
            share = (od["tgt"] / tp[0]) if pos in ("WR", "TE") else ((od["car"] / max(1, tp[1])) if pos == "RB" else (od["pa"] / max(1, tp[2])))
            nxt = per.get((onk, pos, Y))
            if share >= (0.30 if pos == "QB" else 0.08) and nxt and nxt["team"] == team:
                n += 1
        return n
    return n_ahead


def build_samples():
    resolve = B.player_ids()
    n_ahead = build_shares()
    pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "birth_date", "rookie_season"])
    birth = {r.gsis_id: pd.to_datetime(r.birth_date, errors="coerce") for r in pl.itertuples(index=False) if isinstance(r.gsis_id, str)}
    rook = {r.gsis_id: (int(r.rookie_season) if pd.notna(r.rookie_season) else None) for r in pl.itertuples(index=False) if isinstance(r.gsis_id, str)}
    dp = pd.read_parquet(os.path.join(B.CACHE, "draft_picks.parquet"), columns=["season", "round", "pick", "gsis_id"])
    draft = {r.gsis_id: (int(r.season), int(r.round), int(r.pick)) for r in dp.itertuples(index=False) if isinstance(r.gsis_id, str)}
    preds = json.load(open(os.path.join(HERE, "opp_prior_preds.json"), encoding="utf-8"))
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    weekly_fpa, season_fpa, lg_fpa = build_fpa()
    out = []; miss = defaultdict(int)
    for Y in YEARS:
        games = B.load_games(Y)
        imps = [v["implied"] for v in games.values() if v["implied"] is not None]
        avg = float(np.mean(imps)); W = 16 if Y <= 2020 else 17
        for name, c in clay_hist[str(Y)].items():
            pos = c.get("pos")
            if pos not in POS4 or (c.get("pts") or 0) < cal.POOL_MIN_PTS:
                continue
            wrec = cal.weekly_rec(name, pos)
            if wrec is None: miss["weekly"] += 1; continue
            team = cal.infer_team(wrec, Y)
            if not team: miss["team"] += 1; continue
            team_prev = cal.infer_team(wrec, Y - 1)
            pid = resolve(name, pos, Y)
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            # H3: 3-yr weighted PPG, walk-forward (seasons before Y only)
            num = den = 0.0; h3g = 0
            for i, yy in enumerate((Y - 1, Y - 2, Y - 3)):
                pts = season_pts(wrec, yy)
                if len(pts) >= MIN_SEASON_G:
                    num += W3[i] * (sum(pts) / len(pts)); den += W3[i]; h3g += len(pts)
            h3 = num / den if (den > 0 and h3g >= MIN_H3_G) else None
            prior_games = []   # (yy, wk, fpts) for the L8 tail across Y-2..Y
            for yy in (Y - 2, Y - 1, Y):
                for w in wrec.get("seasons", {}).get(str(yy), []):
                    if cal.played(w) and isinstance(w.get("fpts"), (int, float)):
                        prior_games.append((yy, int(w["wk"]), float(w["fpts"])))
            prior_games.sort()
            bd = birth.get(pid) if pid else None
            age = ((pd.Timestamp(year=Y, month=9, day=1) - bd).days / 365.25) if (bd is not None and pd.notna(bd)) else np.nan
            dr = draft.get(pid) if pid else None
            rs = rook.get(pid) if pid else None
            is_rookie = bool((rs == Y) or (dr and dr[0] == Y))
            exp = (Y - rs) if rs is not None else np.nan
            rnd = dr[1] if (dr and dr[0] == Y) else (8 if is_rookie else 0)   # 8 = undrafted rookie
            pick = float(dr[2]) if (dr and dr[0] == Y) else (262.0 if is_rookie else np.nan)
            nah = n_ahead(cal.norm(name), pos, team, Y) if is_rookie else np.nan
            pr = preds.get(f"{Y}|{pid}") if pid else None
            opp_cal = pr.get("SHADOWCAL") if pr else None
            seg = pr.get("seg") if pr else None
            rows = sorted([(int(w["wk"]), float(w["fpts"]), cal.OPP_ALIAS.get(w.get("opp"), w.get("opp")))
                           for w in wrec.get("seasons", {}).get(str(Y), []) if cal.played(w) and isinstance(w.get("fpts"), (int, float))])
            hist = []
            for wk, fpts, opp in rows:
                gm = games.get((team, wk))
                if gm and gm["implied"] is not None and opp:
                    g = len(hist); ppg = (sum(hist) / g) if g else 0.0
                    veg = min(1.35, max(0.7, 1 + B.VEG[pos] * (gm["implied"] - avg) / avg))
                    cur = weekly_fpa.get((Y, opp, pos), {}); past = [w for w in cur if w < wk]
                    fpa = 1.0
                    if past and lg_fpa.get((Y, pos)):
                        ratio = min(1.25, max(0.8, (sum(cur[w] for w in past) / len(past)) / lg_fpa[(Y, pos)]))
                        fpa = 1 + B.FPA_E * (ratio - 1) * min(1, len(past) / B.FPA_TRUST_G)
                    tail = [f for (yy, ww, f) in prior_games if (yy, ww) < (Y, wk)][-8:]
                    l8 = (sum(tail) / len(tail)) if len(tail) >= MIN_L8_G else None
                    out.append({"year": Y, "name": name, "pos": pos, "team": team, "pid": pid, "wk": wk, "act": fpts, "g": g, "ppg": ppg,
                                "clay": clay_pg, "layers": veg * fpa, "h3": h3, "h3g": h3g, "l8": l8, "l8g": len(tail), "age": age,
                                "rookie": is_rookie, "exp": exp, "rnd": rnd, "mover": bool(team_prev and team_prev != team),
                                "oppcal": opp_cal, "seg": seg, "pick": pick, "nahead": nah})
                hist.append(fpts)
        P(f"  {Y}: samples so far {len(out)}")
    P(f"  skipped: {dict(miss)}")
    return out


def arrays(S):
    A = {}
    for k in S[0]:
        v = [s[k] for s in S]
        if k in ("name", "pos", "team", "pid", "seg"): A[k] = np.array(v, dtype=object)
        elif k in ("rookie", "mover"): A[k] = np.array(v, dtype=bool)
        else: A[k] = np.array([np.nan if x is None else x for x in v], dtype=float)
    A["year"] = A["year"].astype(int); A["wk"] = A["wk"].astype(int)
    return A


def blend(prior, g, ppg, Pn):
    return (Pn * prior + g * ppg) / (Pn + g)


def loyo_const(A, mask_fn, years):
    """per-year constant = mean act over the OTHER years' rows in mask (leave-one-year-out)."""
    out = {}
    for y in years:
        m = mask_fn() & (A["year"] != y)
        out[y] = float(A["act"][m].mean()) if m.sum() >= 30 else np.nan
    return out


def year_map(A, per_year):
    return np.array([per_year.get(y, np.nan) for y in A["year"]])


def pct_vs(pred, base, act, year):
    """pooled MSE change vs base and years-better count."""
    ys = sorted(set(year))
    wins = sum(1 for y in ys if mse(pred[year == y], act[year == y]) < mse(base[year == y], act[year == y]))
    return (mse(pred, act) / mse(base, act) - 1) * 100, wins, len(ys)


def loyo_pick(A, base, grid, predfn, label, family=None, mask=None):
    """LOYO sweep graded vs an external baseline (shipped). grid[0] is the current config."""
    m = np.ones(len(base), dtype=bool) if mask is None else mask
    act, year = A["act"][m], A["year"][m]
    ys = [y for y in YEARS if (year == y).any()]
    per = {v: {y: mse(predfn(v)[m][year == y], act[year == y]) for y in ys} for v in grid}
    tot = n = wins = 0; picks = []
    for y in ys:
        my = year == y
        best = min(grid, key=lambda v: sum(per[v][yy] for yy in ys if yy != y))
        picks.append(best); e = per[best][y]
        tot += e * my.sum(); n += my.sum(); wins += e < mse(base[m][my], act[my])
    base_mse = mse(base[m], act); cur = sum(per[grid[0]][y] * (year == y).sum() for y in ys) / n
    pooled_best = min(grid, key=lambda v: sum(per[v].values()))
    P(f"  {label} (n={n})")
    P("    grid pooled MSE: " + "  ".join(f"{v}:{sum(per[v].values())/len(ys):.3f}" for v in grid))
    P(f"    current {grid[0]} {(cur/base_mse-1)*100:+.2f}% vs shipped | LOYO best {tot/n:.4f} ({(tot/n/base_mse-1)*100:+.2f}%), years better than shipped {wins}/{len(ys)}, picks {picks}, pooled best {pooled_best}")
    RES["sweeps"].append({"label": label, "family": family or label, "n": int(n), "grid": [float(v) for v in grid], "current": float(grid[0]),
                          "curPct": round((cur / base_mse - 1) * 100, 3), "loyoPct": round((tot / n / base_mse - 1) * 100, 3),
                          "wins": int(wins), "years": len(ys), "picks": [float(p) for p in picks], "pooledBest": float(pooled_best)})
    return pooled_best


def main():
    t0 = time.time()
    P("=== Clay-free weekly ladder: rebuilding the shadow prior walk-forward 2019-25 ===")
    S = build_samples(); A = arrays(S); n = len(S); RES["n"] = n
    act, year, wk, pos, g, ppg, clay, layers = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"]
    shipped = blend(clay, g, ppg, PRIOR_P) * layers
    P(f"  {n} player-weeks in {time.time()-t0:.0f}s | shipped MSE {mse(shipped, act):.4f}")

    # ---- prior pieces (half-PPR, walk-forward) ----
    h3, l8 = A["h3"], A["l8"]
    has_h3, has_l8 = ~np.isnan(h3), ~np.isnan(l8)

    def mix(w):
        p = np.full(n, np.nan)
        both = has_h3 & has_l8
        p[both] = (1 - w) * h3[both] + w * l8[both]
        p[has_h3 & ~has_l8] = h3[has_h3 & ~has_l8]
        p[~has_h3 & has_l8] = l8[~has_h3 & has_l8]
        return p

    def with_age(p):
        q = p.copy()
        for i in np.where(~np.isnan(p))[0]:
            q[i] = age_adjust(pos[i], p[i], A["age"][i])
        return q

    oppcal = A["oppcal"]; is_rookie = A["rookie"]; seg = A["seg"]
    vet_opp = (~np.isnan(oppcal)) & (seg != "rookie") & (~is_rookie)

    def with_opp(p, how="replace"):
        q = p.copy(); m = vet_opp & ~np.isnan(p) & (p >= 4)
        q[m] = oppcal[m] if how == "replace" else 0.5 * p[m] + 0.5 * oppcal[m]
        return q

    # ---- fallbacks (LOYO constants) ----
    pos_mean = {ps: loyo_const(A, lambda ps=ps: (pos == ps), YEARS) for ps in POS4}
    fb_pos = np.array([pos_mean[ps].get(y, np.nan) for ps, y in zip(pos, year)])
    rnd = A["rnd"]
    def rbucket(r): return 1 if r == 1 else (2 if r == 2 else (3 if r == 3 else (4 if 4 <= r <= 7 else 5)))
    rb_arr = np.array([rbucket(int(r)) if not np.isnan(r) else 0 for r in rnd])
    dc_mean = {}
    for ps in POS4:
        for b in (1, 2, 3, 4, 5):
            dc_mean[(ps, b)] = loyo_const(A, lambda ps=ps, b=b: (pos == ps) & is_rookie & (rb_arr == b), YEARS)
    fb_dc = fb_pos.copy()
    for i in np.where(is_rookie)[0]:
        v = dc_mean.get((pos[i], rb_arr[i]), {}).get(year[i], np.nan)
        if not np.isnan(v): fb_dc[i] = v
    fb_rook = fb_dc.copy()
    m = is_rookie & ~np.isnan(oppcal)
    fb_rook[m] = oppcal[m]

    def fill(p, fb):
        q = p.copy(); miss = np.isnan(q); q[miss] = fb[miss]; return q

    # ---- rookie fallback MODEL: ppg ~ a + b log(pick) + c min(n_ahead, 3), per position, fit on other seasons ----
    pick, nah = A["pick"], A["nahead"]
    lp = np.log(np.where(np.isnan(pick), 262.0, pick))
    nah3 = np.minimum(np.where(np.isnan(nah), np.nan, nah), 3)

    def fit_rookie(train_mask, use_depth):
        coef = {}
        for ps in POS4:
            m = train_mask & is_rookie & (pos == ps)
            if m.sum() < 60:
                continue
            nm = float(np.nanmean(nah3[m])) if np.isfinite(np.nanmean(nah3[m])) else 1.0
            X = [np.ones(m.sum()), lp[m]]
            if use_depth: X.append(np.where(np.isnan(nah3[m]), nm, nah3[m]))
            X = np.column_stack(X)
            b, *_ = np.linalg.lstsq(X, act[m], rcond=None)
            coef[ps] = {"a": float(b[0]), "b": float(b[1]), "c": float(b[2]) if use_depth else 0.0, "nahMean": nm}
        return coef

    def apply_rookie(coef, fb):
        q = fb.copy()
        for i in np.where(is_rookie)[0]:
            cf = coef.get(pos[i])
            if not cf: continue
            d = nah3[i] if not np.isnan(nah3[i]) else cf["nahMean"]
            q[i] = max(0.5, cf["a"] + cf["b"] * lp[i] + cf["c"] * d)
        return q

    fb_pick, fb_depth = fb_pos.copy(), fb_pos.copy()
    for y in YEARS:
        my = year == y
        cp = fit_rookie(year != y, False); cd = fit_rookie(year != y, True)
        fb_pick[my] = apply_rookie(cp, fb_pos)[my]; fb_depth[my] = apply_rookie(cd, fb_pos)[my]
    RES["rookieCoefAll"] = fit_rookie(np.ones(n, dtype=bool), True)
    RES["rookieCoefPickAll"] = fit_rookie(np.ones(n, dtype=bool), False)   # the engine version (no depth proxy)
    RES["posMeanAll"] = {ps: round(float(act[pos == ps].mean()), 3) for ps in POS4}
    P("\n=== Rookie fallback model (all seasons, for reference): ppg = a + b log(pick) + c min(n_ahead,3) ===")
    for ps, cf in RES["rookieCoefAll"].items():
        P(f"  {ps}: a {cf['a']:6.2f}  b {cf['b']:6.2f} (per log pick)  c {cf['c']:6.2f} (per vet ahead)  | pick 10 & 0 ahead -> {cf['a'] + cf['b']*np.log(10):5.2f}, pick 100 & 2 ahead -> {cf['a'] + cf['b']*np.log(100) + 2*cf['c']:5.2f}")
    rk = is_rookie & (wk <= 4)
    P(f"  rookie rows weeks 1-4 (n={rk.sum()}), MSE of the PRIOR alone vs actual: Clay {mse(clay[rk], act[rk]):.2f} | draft-round mean {mse(fb_dc[rk], act[rk]):.2f} | log-pick {mse(fb_pick[rk], act[rk]):.2f} | log-pick + depth {mse(fb_depth[rk], act[rk]):.2f} | rookie OPP where it exists {mse(fb_rook[rk], act[rk]):.2f}")
    RES["rookiePrior"] = {"n": int(rk.sum()), "clay": round(mse(clay[rk], act[rk]), 3), "dc": round(mse(fb_dc[rk], act[rk]), 3), "pick": round(mse(fb_pick[rk], act[rk]), 3),
                          "depth": round(mse(fb_depth[rk], act[rk]), 3), "opp": round(mse(fb_rook[rk], act[rk]), 3)}

    # ---- variants ----
    base_mix = with_age(mix(0.5))
    variants = [
        ("SHIPPED (Clay prior)", clay, "clay"),
        ("H3 only, Clay fallback", fill(h3, clay), "clay"),
        ("MIX .5 H3 + .5 L8, Clay fallback", fill(mix(0.5), clay), "clay"),
        ("MIX + age curve, Clay fallback", fill(base_mix, clay), "clay"),
        ("MIX + age + OPP (replace), Clay fallback  [= live shadow]", fill(with_opp(base_mix), clay), "clay"),
        ("MIX + age + OPP (half), Clay fallback", fill(with_opp(base_mix, "half"), clay), "clay"),
        ("CLAY-FREE: MIX + age + OPP, POS-mean fallback", fill(with_opp(base_mix), fb_pos), "pos"),
        ("CLAY-FREE: MIX + age + OPP, draft-round fallback", fill(with_opp(base_mix), fb_dc), "dc"),
        ("CLAY-FREE: MIX + age + OPP, rookie-OPP fallback", fill(with_opp(base_mix), fb_rook), "rook"),
        ("CLAY-FREE: MIX + age + OPP, rookie log-pick fallback", fill(with_opp(base_mix), fb_pick), "pick"),
        ("CLAY-FREE: MIX + age + OPP, rookie log-pick + depth fallback", fill(with_opp(base_mix), fb_depth), "depth"),
    ]
    preds = {}
    P("\n=== Variants (P=5 blend x layers), MSE vs shipped ===")
    P(f"  {'variant':62s} {'MSE':>7s} {'vs ship':>8s} {'yrs':>4s}   QB      RB      WR      TE")
    for lab, prior, fbk in variants:
        pred = blend(prior, g, ppg, PRIOR_P) * layers; preds[lab] = pred
        pc, w, ny = pct_vs(pred, shipped, act, year)
        bypos = {}
        for ps in POS4:
            mm = pos == ps
            bypos[ps] = round((mse(pred[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 2)
        P(f"  {lab:62s} {mse(pred, act):7.3f} {pc:+7.2f}% {w}/{ny}   " + "  ".join(f"{bypos[ps]:+6.2f}" for ps in POS4))
        RES["variants"].append({"label": lab, "fallback": fbk, "mse": round(mse(pred, act), 4), "pct": round(pc, 3), "wins": int(w), "years": ny, "byPos": bypos})

    # ---- fallback share by band ----
    P("\n=== Rows with no Clay-free prior (fallback) by week band ===")
    for lab, lo, hi in BANDS:
        mm = (wk >= lo) & (wk <= hi)
        fbm = np.isnan(base_mix) & mm
        rk = fbm & is_rookie
        P(f"  {lab:7s} n={mm.sum():5d}  fallback {100*fbm.sum()/max(1,mm.sum()):5.1f}%  (rookies {rk.sum()}, others {fbm.sum()-rk.sum()})")
        RES["fallback"].append({"band": lab, "n": int(mm.sum()), "fbPct": round(100 * fbm.sum() / max(1, mm.sum()), 2), "rookies": int(rk.sum()), "others": int(fbm.sum() - rk.sum())})

    # ---- by week band ----
    key_live = "MIX + age + OPP (replace), Clay fallback  [= live shadow]"
    key_free = "CLAY-FREE: MIX + age + OPP, draft-round fallback"
    P("\n=== By week band: MSE change vs shipped (live shadow | fully Clay-free) ===")
    for lab, lo, hi in BANDS:
        mm = (wk >= lo) & (wk <= hi)
        row = {"band": lab, "n": int(mm.sum())}
        parts = []
        for key, tag in ((key_live, "live"), (key_free, "free")):
            pc = (mse(preds[key][mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100
            row[tag] = round(pc, 3); parts.append(f"{tag} {pc:+6.2f}%")
            for ps in POS4:
                mp = mm & (pos == ps)
                row[f"{tag}_{ps}"] = round((mse(preds[key][mp], act[mp]) / mse(shipped[mp], act[mp]) - 1) * 100, 2) if mp.sum() >= 40 else None
        P(f"  {lab:7s} n={mm.sum():5d}  " + " | ".join(parts) + "   free by pos " + " ".join(f"{ps} {row.get('free_'+ps)}" for ps in POS4))
        RES["bands"].append(row)

    # ---- by segment ----
    P("\n=== By segment: MSE change vs shipped (live shadow | fully Clay-free) ===")
    nohist = np.isnan(base_mix)
    segs = [("vet, same team", ~is_rookie & ~A["mover"] & ~nohist), ("vet, changed team", ~is_rookie & A["mover"] & ~nohist),
            ("rookie", is_rookie), ("no history, not rookie", nohist & ~is_rookie), ("2nd year", (A["exp"] == 1) & ~nohist)]
    for lab, mm in segs:
        if mm.sum() < 50: continue
        row = {"seg": lab, "n": int(mm.sum()), "actOverShip": round(float(act[mm].mean() / shipped[mm].mean()), 3)}
        for key, tag in ((key_live, "live"), (key_free, "free")):
            row[tag] = round((mse(preds[key][mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 3)
        P(f"  {lab:24s} n={mm.sum():5d} actual/shipped {row['actOverShip']:.3f}  live {row['live']:+6.2f}%  free {row['free']:+6.2f}%")
        RES["segments"].append(row)

    # ---- sweeps on the fully Clay-free version ----
    P("\n=== Sweeps (LOYO, graded vs shipped) on the Clay-free version (draft-round fallback) ===")
    free_prior = fill(with_opp(base_mix), fb_dc)
    loyo_pick(A, shipped, [5, 2, 3, 4, 6, 8, 12], lambda Pn: blend(free_prior, g, ppg, Pn) * layers, "prior strength P for the Clay-free prior", "P")
    for ps in POS4:
        loyo_pick(A, shipped, [5, 2, 3, 4, 6, 8, 12], lambda Pn: blend(free_prior, g, ppg, Pn) * layers, f"  P, {ps} only", "P", mask=(pos == ps))
    loyo_pick(A, shipped, [0.5, 0.0, 0.25, 0.75, 1.0], lambda w: blend(fill(with_opp(with_age(mix(w))), fb_dc), g, ppg, PRIOR_P) * layers, "L8 weight in the prior (0 = H3 only, 1 = L8 only)", "w_l8")
    def shrink(k):
        p = free_prior.copy(); return fb_pos + k * (p - fb_pos)
    loyo_pick(A, shipped, [1.0, 0.9, 0.8, 0.7, 0.6], lambda k: blend(shrink(k), g, ppg, PRIOR_P) * layers, "shrink the prior toward the position mean (k)", "shrink")
    def mover_dock(mlt):
        p = free_prior.copy(); p[A["mover"] & ~is_rookie] *= mlt; return p
    loyo_pick(A, shipped, [1.0, 0.95, 0.9, 0.85, 0.8, 1.05], lambda mlt: blend(mover_dock(mlt), g, ppg, PRIOR_P) * layers, "team-changer prior multiplier", "mover")
    def rookie_lvl(mlt):
        p = free_prior.copy(); p[is_rookie] *= mlt; return p
    loyo_pick(A, shipped, [1.0, 0.8, 0.9, 1.1, 1.2, 1.3], lambda mlt: blend(rookie_lvl(mlt), g, ppg, PRIOR_P) * layers, "rookie fallback level multiplier", "rookie")
    # a Clay-free prior with a weaker P AND the l8-heavy mix: the combined candidate
    def combo(Pn):
        return blend(free_prior, g, ppg, Pn) * layers
    P("\n=== Where the remaining gap sits at the LOYO-best P (Clay-free, by band) ===")
    bestP = RES["sweeps"][0]["pooledBest"]
    for lab, lo, hi in BANDS:
        mm = (wk >= lo) & (wk <= hi)
        pc = (mse(combo(bestP)[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100
        P(f"  {lab:7s} {pc:+6.2f}%")
        for r in RES["bands"]:
            if r["band"] == lab: r["freeBestP"] = round(pc, 3)
    RES["bestP"] = float(bestP)

    # ---- COMBINED candidate: rookie pick+depth fallback, shrink k toward the position mean, per-position prior strength ----
    PPOS = {"QB": 12, "RB": 5, "WR": 8, "TE": 8}; K = 0.8
    Pvec = np.array([PPOS[ps] for ps in pos], dtype=float)
    def combined_prior(fb, fbpos):
        return fbpos + K * (fill(with_opp(base_mix), fb) - fbpos)
    pred_c = blend(combined_prior(fb_depth, fb_pos), g, ppg, Pvec) * layers
    pc, w, ny = pct_vs(pred_c, shipped, act, year)
    pl, wl, _ = pct_vs(pred_c, preds[key_live], act, year)
    P(f"\n=== COMBINED Clay-free candidate (rookie log-pick + depth fallback, shrink k={K}, P {PPOS}) ===")
    P(f"  vs shipped {pc:+.2f}% ({w}/{ny} seasons better) | vs the live shadow {pl:+.2f}% ({wl}/{ny})")
    comb = {"pct": round(pc, 3), "wins": int(w), "years": ny, "vsLive": round(pl, 3), "vsLiveWins": int(wl), "byPos": {}, "bands": [], "segments": []}
    for ps in POS4:
        mm = pos == ps; comb["byPos"][ps] = round((mse(pred_c[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 2)
    P("  by position: " + "  ".join(f"{ps} {comb['byPos'][ps]:+.2f}%" for ps in POS4))
    for lab, lo, hi in BANDS:
        mm = (wk >= lo) & (wk <= hi)
        row = {"band": lab, "n": int(mm.sum()), "pct": round((mse(pred_c[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 3)}
        for ps in POS4:
            mp = mm & (pos == ps)
            row[ps] = round((mse(pred_c[mp], act[mp]) / mse(shipped[mp], act[mp]) - 1) * 100, 2) if mp.sum() >= 40 else None
        comb["bands"].append(row)
        P(f"  {lab:7s} {row['pct']:+6.2f}%   " + " ".join(f"{ps} {row[ps]}" for ps in POS4))
    for lab, mm in segs:
        if mm.sum() < 50: continue
        comb["segments"].append({"seg": lab, "n": int(mm.sum()), "pct": round((mse(pred_c[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 3)})
        P(f"  {lab:24s} {comb['segments'][-1]['pct']:+6.2f}%")
    # FORWARD: every constant (position means, rookie model) from EARLIER seasons only; P and k fixed as above
    fwd_pred = np.full(n, np.nan)
    for y in YEARS[2:]:
        tr = year < y; my = year == y
        pm = np.array([float(act[tr & (pos == ps)].mean()) for ps in pos])
        cd = fit_rookie(tr, True)
        fb = apply_rookie(cd, pm)
        pr = pm + K * (fill(with_opp(base_mix), fb) - pm)
        fwd_pred[my] = (blend(pr, g, ppg, Pvec) * layers)[my]
    fm = ~np.isnan(fwd_pred)
    fp, fw, fy = pct_vs(fwd_pred[fm], shipped[fm], act[fm], year[fm])
    fpl, fwl, _ = pct_vs(fwd_pred[fm], preds[key_live][fm], act[fm], year[fm])
    P(f"  FORWARD (2021-25, constants from earlier seasons only): vs shipped {fp:+.2f}% ({fw}/{fy}) | vs live shadow {fpl:+.2f}% ({fwl}/{fy})")
    for lab, lo, hi in BANDS:
        mm = fm & (wk >= lo) & (wk <= hi)
        P(f"    {lab:7s} {(mse(fwd_pred[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100:+6.2f}%")
    comb["forward"] = {"pct": round(fp, 3), "wins": int(fw), "years": fy, "vsLive": round(fpl, 3), "vsLiveWins": int(fwl)}
    comb["P"] = PPOS; comb["k"] = K
    RES["combined"] = comb
    RES["summary"] = (f"Live shadow (Clay fallback) {RES['variants'][4]['pct']:+.2f}% vs shipped; fully Clay-free {RES['variants'][7]['pct']:+.2f}%; "
                      f"combined candidate (rookie pick + depth fallback, shrink {K}, per-position P) {pc:+.2f}% ({w}/{ny}), forward {fp:+.2f}% ({fw}/{fy}).")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "noclay_weekly_backtest.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_NOCLAY_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/noclay_weekly_backtest.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
