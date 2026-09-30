#!/usr/bin/env python3
"""
STAT-LINE USAGE UPDATE: should the per-stat components (rush yds / receptions / rec yds) learn from in-season
usage? (2026-09-20)

Jack: "usage should be involved in our sims" - after the W2 prop list showed the model fading full-time receivers
(Coker, Vele, Douglas) because weeklyProjection's compsWk is the PRESEASON Clay stat line per game x matchup x injury
for all 18 weeks. The fantasy mean learns in season (P=5 blend, shadow usage evidence v2.18); the stat lines that
grade against the books never do.

Walk-forward 2019-25, per player-week with >= 1 game played, per stat k in (ry, rec, rcy):
    post_k = (P x prior_k + g x (lam x U_k + (1 - lam) x A_k)) / (P + g)
  prior_k  preseason per-game stat line. Receptions = Clay's own projection (clay_history rec / gm). Yardage has no
           historical Clay line, so PROXY: Clay half-PPR ppg x the player's prior-season stat mix (stat per half-PPR
           point, >= 6 games), else the position's median mix from the training seasons.
  A_k      actual stat per game so far          U_k   usage-expected stat per game so far (pull_pace_tracker xFP
           tables: targets x air-yard bucket catch rate / yards, carries x field position) - the SIM_XFP_2026 feed.
  P        prior strength in games (inf = today's engine).   lam   usage share of the evidence.
(P, lam) chosen per stat x position on TRAINING seasons only (LOYO and forward 2021-25), graded on the prop-relevant
pool (prior or evidence above the book-line minimums), by games played. Also the head-to-head a bettor cares about:
when the updated number and the static number disagree by >= 20%, which one was the actual closer to?
Log comp_usage.log; results -> data/comp_usage_bt.json.
"""
import json, os, sys, time, warnings
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
warnings.filterwarnings("ignore")
import bt_common as B
import backtest_xfp as BX
BX.P = lambda *a: None      # its logger prints to a stdout the harness imports re-wrap

CACHE_PQ = os.path.join(HERE, "_tmp", "comp_usage_weeks.parquet")
YEARS = list(range(2019, 2026))
STATS = {"ry": ("ruyd", "xruyd", ("RB", "QB")), "rec": ("rec", "xrec", ("RB", "WR", "TE")), "rcy": ("recyd", "xrecyd", ("RB", "WR", "TE"))}
MINLINE = {"ry": 20.0, "rec": 2.0, "rcy": 20.0}
PG = [1, 2, 3, 5, 8, 12, 20, 40]
LG = [0.0, 0.25, 0.5, 0.75, 1.0]
BUCKETS = (("1 game", 1, 1), ("2 games", 2, 2), ("3 games", 3, 3), ("4-5", 4, 5), ("6-8", 6, 8), ("9+", 9, 99))

class _Tee:
    def __init__(self, *s): self.s = s
    def write(self, x):
        for f in self.s: f.write(x)
    def flush(self):
        for f in self.s: f.flush()
_LOG = None
def P_(*a):
    t = " ".join(str(x) for x in a)
    if _LOG: _LOG.write(t + chr(10)); _LOG.flush()
    try: sys.__stdout__.write(t + chr(10)); sys.__stdout__.flush()
    except Exception: pass


def load_weeks():
    if os.path.exists(CACHE_PQ): return pd.read_parquet(CACHE_PQ)
    pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "position"])
    pos_of = {r.gsis_id: r.position for r in pl.itertuples(index=False) if isinstance(r.gsis_id, str) and r.position in B.POS4}
    df = pd.concat([BX.build_year(Y, pos_of) for Y in [2018] + YEARS if os.path.exists(os.path.join(B.CACHE, f"play_by_play_{Y}.csv.gz"))], ignore_index=True)
    os.makedirs(os.path.dirname(CACHE_PQ), exist_ok=True); df.to_parquet(CACHE_PQ)
    return df


def build_rows(df):
    """one row per (player, season, week with >= 1 earlier game): priors, evidence, actuals for every stat."""
    resolve = B.player_ids()
    ch = json.load(open(os.path.join(B.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    by = {k: g.sort_values("wk") for k, g in df.groupby(["Y", "pid"])}
    # prior-season per-game mix: stat per half-PPR point
    seas = df.groupby(["Y", "pid"]).agg(g=("wk", "size"), act=("act", "sum"), ruyd=("ruyd", "sum"), rec=("rec", "sum"), recyd=("recyd", "sum")).reset_index()
    mix = {(int(r.Y), r.pid): {"ry": r.ruyd / r.act, "rec": r.rec / r.act, "rcy": r.recyd / r.act} for r in seas.itertuples(index=False) if r.g >= 6 and r.act > 20}
    rows = []
    for Y in YEARS:
        W = 16.0 if Y <= 2020 else 17.0
        for name, c in ch[str(Y)].items():
            pos = c.get("pos")
            if pos not in B.POS4 or (c.get("pts") or 0) < B.POOL_MIN_PTS: continue
            pid = resolve(name, pos, Y)
            if not pid or (Y, pid) not in by: continue
            gm = c.get("gm") or 0; div = gm if gm >= 4 else W
            half_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / div
            clay_rec_pg = (c.get("rec") or 0) / div if c.get("rec") is not None else np.nan
            m = mix.get((Y - 1, pid))
            w = by[(Y, pid)]
            a = {k: w[STATS[k][0]].values.astype(float) for k in STATS}; u = {k: w[STATS[k][1]].values.astype(float) for k in STATS}
            wks = w.wk.values
            for i in range(1, len(w)):
                r = {"year": Y, "name": name, "pos": pos, "pid": pid, "wk": int(wks[i]), "g": i, "half_pg": half_pg, "clay_rec_pg": clay_rec_pg, "has_mix": m is not None}
                for k in STATS:
                    r["mix_" + k] = m[k] if m else np.nan
                    r["A_" + k] = a[k][:i].mean(); r["U_" + k] = u[k][:i].mean(); r["y_" + k] = a[k][i]
                rows.append(r)
    return pd.DataFrame(rows)


def add_priors(R, train_mask):
    """yardage prior = Clay half ppg x mix (own prior-season mix, else the training seasons' position median)."""
    out = {}
    for k in STATS:
        med = {ps: float(np.nanmedian(R.loc[train_mask & (R.pos == ps) & R.has_mix, "mix_" + k])) for ps in B.POS4}
        mx = np.where(R.has_mix, R["mix_" + k], R.pos.map(med)).astype(float)
        pr = R.half_pg.values * mx
        if k == "rec": pr = np.where(np.isnan(R.clay_rec_pg.values), pr, R.clay_rec_pg.values)      # receptions: Clay's real line
        out[k] = pr
    return out


def post(prior, g, A, U, P, lam):
    ev = lam * U + (1 - lam) * A
    return (P * prior + g * ev) / (P + g)


def main():
    global _LOG; _LOG = open(os.path.join(HERE, "comp_usage.log"), "w", encoding="utf-8")
    t0 = time.time(); P_("=== Stat-line usage update: do the prop components learn from in-season usage? ===")
    df = load_weeks(); P_(f"  player-weeks from play-by-play: {len(df)}  ({time.time()-t0:.0f}s)")
    R = build_rows(df); P_(f"  walk-forward rows (Clay pool, >= 1 game played): {len(R)}")
    g = R.g.values.astype(float); year = R.year.values; pos = R.pos.values
    bk = np.array([next(i for i, (_, a, b) in enumerate(BUCKETS) if a <= x <= b) for x in R.g.values])
    RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "stats": {}}
    for k, (_, _, poss) in STATS.items():
        A = R["A_" + k].values; U = R["U_" + k].values; y = R["y_" + k].values
        P_(f"\n##### {k}  (positions {', '.join(poss)}) #####")
        RES["stats"][k] = {}
        for mode in ("LOYO", "forward"):
            pred = np.full(len(R), np.nan); stat = np.full(len(R), np.nan); picks = {}
            for yv in (YEARS[2:] if mode == "forward" else YEARS):
                tr_y = (year < yv) if mode == "forward" else (year != yv); te_y = year == yv
                prior = add_priors(R, tr_y)[k]
                pool = (np.maximum(prior, A) >= MINLINE[k])
                for ps in poss:
                    tr = tr_y & (pos == ps) & pool; te = te_y & (pos == ps)
                    if tr.sum() < 200 or not te.any(): continue
                    best, bm = None, 1e18
                    for Pv in PG:
                        for lam in LG:
                            e = float(np.mean((post(prior[tr], g[tr], A[tr], U[tr], Pv, lam) - y[tr]) ** 2))
                            if e < bm: bm, best = e, (Pv, lam)
                    pred[te] = post(prior[te], g[te], A[te], U[te], best[0], best[1]); stat[te] = prior[te]
                    picks.setdefault(ps, []).append(best)
            ok = ~np.isnan(pred) & (np.maximum(stat, A) >= MINLINE[k])
            def line(lbl, m):
                if m.sum() < 30: return None
                ms, mu = float(np.mean((stat[m] - y[m]) ** 2)), float(np.mean((pred[m] - y[m]) ** 2))
                as_, au = float(np.mean(np.abs(stat[m] - y[m]))), float(np.mean(np.abs(pred[m] - y[m])))
                yrs = sorted(set(year[m])); wins = sum(1 for yy in yrs if np.mean((pred[m & (year == yy)] - y[m & (year == yy)]) ** 2) < np.mean((stat[m & (year == yy)] - y[m & (year == yy)]) ** 2))
                P_(f"    {lbl:22s} n {int(m.sum()):6d}  MSE static {ms:8.2f} -> usage {mu:8.2f}  ({100*(mu/ms-1):+6.2f}%)  MAE {as_:6.2f} -> {au:6.2f} ({100*(au/as_-1):+5.2f}%)  seasons won {wins}/{len(yrs)}")
                return {"n": int(m.sum()), "mse": round(100 * (mu / ms - 1), 2), "mae": round(100 * (au / as_ - 1), 2), "won": f"{wins}/{len(yrs)}"}
            P_(f"  --- {mode}: picks (P games, lam usage share) " + "; ".join(f"{ps} {sorted(set(v), key=v.count)[-1]} {[str(x) for x in v]}" for ps, v in picks.items()))
            out = {"picks": {ps: [list(x) for x in v] for ps, v in picks.items()}, "all": line("ALL", ok)}
            for ps in poss: out[ps] = line(ps, ok & (pos == ps))
            for b, (lbl, _, _) in enumerate(BUCKETS): out["g " + lbl] = line("after " + lbl, ok & (bk == b))
            # bettor's head-to-head: the two numbers disagree by >= 20% - who was closer, and which side of the STATIC number did the actual land?
            dis = ok & (np.abs(pred - stat) / np.maximum(stat, 1e-6) >= 0.20)
            for lbl, m in (("disagree >=20% (all g)", dis), ("disagree >=20%, g<=3", dis & (g <= 3))):
                if m.sum() < 30: continue
                closer = float(np.mean(np.abs(pred[m] - y[m]) < np.abs(stat[m] - y[m])))
                med_adj = 0.9 if k != "rec" else 1.0      # yardage medians sit ~10% under means (vs_books_week MEAN_TO_MED)
                side = float(np.mean(np.sign(y[m] - stat[m] * med_adj) == np.sign(pred[m] - stat[m])))
                P_(f"    {lbl:22s} n {int(m.sum()):6d}  updated number closer {100*closer:5.1f}%   actual landed on the updated side of the static median {100*side:5.1f}%")
                out[lbl] = {"n": int(m.sum()), "closer": round(100 * closer, 1), "side": round(100 * side, 1)}
            RES["stats"][k][mode] = out
    # ---- one fixed, shippable table: P and lam per stat x position on ALL seasons (what the engine would carry)
    P_("\n##### shippable table (all seasons) + the neighbours, so the pick isn't a knife edge #####")
    prior_all = add_priors(R, np.ones(len(R), bool)); RES["ship"] = {}
    for k, (_, _, poss) in STATS.items():
        A = R["A_" + k].values; U = R["U_" + k].values; y = R["y_" + k].values; prior = prior_all[k]
        for ps in poss:
            m = (pos == ps) & (np.maximum(prior, A) >= MINLINE[k])
            base = float(np.mean((prior[m] - y[m]) ** 2))
            grid = {(Pv, lam): float(np.mean((post(prior[m], g[m], A[m], U[m], Pv, lam) - y[m]) ** 2)) / base - 1 for Pv in PG for lam in LG}
            best = min(grid, key=grid.get)
            P_(f"  {k:3s} {ps}: best P {best[0]:>2} lam {best[1]:.2f} -> {100*grid[best]:+.2f}% | " + "  ".join(f"P{Pv}: {100*min(grid[(Pv, l)] for l in LG):+.1f}%" for Pv in PG) + " | lam @best P: " + " ".join(f"{l:.2f}:{100*grid[(best[0], l)]:+.1f}%" for l in LG))
            RES["ship"][f"{k}_{ps}"] = {"P": best[0], "lam": best[1], "mse": round(100 * grid[best], 2)}
    json.dump(RES, open(os.path.join(HERE, "data", "comp_usage_bt.json"), "w"), indent=1)
    P_(f"\ndone in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
