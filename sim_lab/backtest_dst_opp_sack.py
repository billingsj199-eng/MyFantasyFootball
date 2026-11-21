#!/usr/bin/env python3
"""
OPPONENT SACK-PRONENESS layer for the D/ST weekly mean (Jack 2026-11-21: "Yes, build it").

Shipped D/ST mean = 16.2 - 0.436 x oppImplied (Vegas only; tuner dstShift omitted here).
The D/ST's OWN realized components were ruled out 09-15 (backtest_dst_regression.py).
First pass (scratch bt_dst_opp_sacks.py): opponent OFFENSE sacks-taken/g over league,
shrunk og/(5+og) -> -0.16% MSE 4/7. This is the full build:

  pred = shipped + k * x          x = expected opp sacks - league sacks/g (in sack units)

  V0  team sacks-taken per GAME, shrunk og/(5+og)              (first-pass replica)
  V1  team sacks-taken per DROPBACK, season-to-date, shrunk K dropbacks to league
  V2  V1 + prior-season carry-in (prior season dropbacks x d, fades as games accrue)
  V3  QB-level: the opponent's starting QB (first dropback of the game), his career
      dropbacks (this season x1, prior seasons x d^j), shrunk K to league
  V3h QB-level shrunk to the TEAM's V2 rate (OL) instead of league
  V4  mix a x QB + (1-a) x team(V2)
  each with volume = league dropbacks (rate only, "r") or expected opp dropbacks ("v":
  opp season-to-date db/g shrunk 4 g to league + b x (dst implied - opp implied)).
  V5  best opp term x D/ST own pass-rush ratio (own sacks/opp dropback faced, shrunk,
      prior carry-in), multiplicative matchup;  V5a additive own term
  OWN own pass-rush term alone (reference)

Grading: LOYO 2019-25 (and 2013-25), forward (train on all prior seasons) 2022-25,
final week excluded (wk17 <=2020 / wk18 2021+), fantasy-playoff cut (14-16 / 15-17).
Rank: mean within-week Spearman, top-12 overlap with actual top-12, mean actual pts of
the model's top-5 / top-12 (streaming value). Params (k plus shape) picked per fold.

Log: dst_opp_sack_backtest.log            Usage: python backtest_dst_opp_sack.py
"""
import numpy as np
import pandas as pd
import os, itertools
from collections import defaultdict
from scipy.stats import spearmanr
from backtest_target_area import implied_map, mse, CACHE
import backtest_dst_regression as B

LOAD = range(2012, 2027)          # 2026 = untouched holdout (never in a fit)
SAMPLE_YEARS = range(2013, 2027)
MAIN = list(range(2019, 2026))
POOL = list(range(2013, 2026))
FWD = [2022, 2023, 2024, 2025]

def final_week(Y): return 17 if Y <= 2020 else 18
def playoff(Y, w): return (14 <= w <= 16) if Y <= 2020 else (15 <= w <= 17)

def load_dropbacks(Y):
    cols = ["season_type", "week", "game_id", "play_id", "posteam", "defteam", "qb_dropback", "sack", "passer_id"]
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), usecols=cols, low_memory=False)
    df = df[(df.season_type == "REG") & df.posteam.notna() & (df.qb_dropback == 1)].copy()
    df["off"] = df.posteam.map(B.tm); df["dfn"] = df.defteam.map(B.tm); df["sack"] = df.sack.fillna(0)
    df = df.sort_values(["game_id", "play_id"])
    off = df.groupby(["off", "week"]).agg(db=("sack", "size"), s=("sack", "sum")).reset_index()
    dfn = df.groupby(["dfn", "week"]).agg(db=("sack", "size"), s=("sack", "sum")).reset_index()
    first = df[df.passer_id.notna()].groupby(["off", "week"]).passer_id.first()
    qbw = df[df.passer_id.notna()].groupby(["passer_id", "week"]).agg(db=("sack", "size"), s=("sack", "sum")).reset_index()
    return off, dfn, first, qbw

class Cum:
    """season-to-date sums before week W: {key: (weeks[], cum_db[], cum_s[])}"""
    def __init__(self, df, key):
        self.d = {}
        for k, g in df.sort_values("week").groupby(key):
            self.d[k] = (g.week.values, np.cumsum(g.db.values), np.cumsum(g.s.values), np.arange(1, len(g) + 1))
    def before(self, k, W):
        t = self.d.get(k)
        if t is None: return 0.0, 0.0, 0
        i = np.searchsorted(t[0], W) - 1
        if i < 0: return 0.0, 0.0, 0
        return float(t[1][i]), float(t[2][i]), int(t[3][i])
    def season(self, k):
        t = self.d.get(k)
        if t is None: return 0.0, 0.0, 0
        return float(t[1][-1]), float(t[2][-1]), int(t[3][-1])

def main():
    frames, lines, OFF, DEF, FIRST, QB = {}, {}, {}, {}, {}, {}
    lg = {}
    for Y in LOAD:
        frames[Y], lines[Y] = B.load_year(Y)
        off, dfn, first, qbw = load_dropbacks(Y)
        OFF[Y], DEF[Y], FIRST[Y], QB[Y] = Cum(off, "off"), Cum(dfn, "dfn"), first, Cum(qbw, "passer_id")
        lw = off.groupby("week").agg(db=("db", "sum"), s=("s", "sum"), n=("db", "size")).sort_index()
        lg[Y] = lw
        print(f"  pbp {Y}: {len(frames[Y])} DST team-weeks, sack rate {off.s.sum()/off.db.sum():.4f}, db/g {off.db.mean():.1f}")

    def league(Y, W):
        """league sack rate, db per team-game, sacks per team-game before week W (fallback prior season)."""
        lw = lg[Y][lg[Y].index < W]
        if lw.n.sum() < 32:
            lw = lg[Y - 1] if (Y - 1) in lg else lg[Y]
        return lw.s.sum() / lw.db.sum(), lw.db.sum() / lw.n.sum(), lw.s.sum() / lw.n.sum()

    # ---------------- samples
    S = defaultdict(list)
    for Y in SAMPLE_YEARS:
        imp = implied_map(lines[Y]); w = frames[Y]
        fw = final_week(Y)
        for r in w.itertuples(index=False):
            W = int(r.week)
            if W >= fw: continue
            oi, ti = imp.get((r.opp, W)), imp.get((r.team, W))
            if oi is None or ti is None: continue
            o, t = r.opp, r.team
            rl, dbl, sl = league(Y, W)
            S["year"].append(Y); S["week"].append(W); S["team"].append(t)
            S["act"].append(r.pts); S["act_sack"].append(r.sack); S["act_to"].append(r.to); S["act_pa"].append(r.pa); S["act_td"].append(r.td); S["ship"].append(max(1.0, 16.2 - 0.436 * oi))
            S["diff"].append(ti - oi); S["rl"].append(rl); S["dbl"].append(dbl); S["sl"].append(sl)
            # opponent offense, team level
            db, s, g = OFF[Y].before(o, W); S["o_db"].append(db); S["o_s"].append(s); S["o_g"].append(g)
            pdb, ps, pg = OFF[Y - 1].season(o) if (Y - 1) in OFF else (0, 0, 0)
            prl = (lg[Y - 1].s.sum() / lg[Y - 1].db.sum()) if (Y - 1) in lg else rl
            S["o_pdb"].append(pdb); S["o_ps"].append(ps); S["o_prl"].append(prl)
            # opponent starting QB
            q = FIRST[Y].get((o, W))
            S["q_known"].append(q is not None)
            cdb, cs, _ = QB[Y].before(q, W) if q is not None else (0, 0, 0)
            hist = []
            for j in (1, 2, 3):
                if (Y - j) in QB and q is not None:
                    a, b, _ = QB[Y - j].season(q); hist.append((a, b))
                else: hist.append((0.0, 0.0))
            S["q_cdb"].append(cdb); S["q_cs"].append(cs)
            for j in range(3): S[f"q_db{j+1}"].append(hist[j][0]); S[f"q_s{j+1}"].append(hist[j][1])
            # QB change flag: starter differs from the team's most common first-dropback QB so far
            prev = [FIRST[Y].get((o, ww)) for ww in range(1, W)]
            prev = [p for p in prev if p is not None]
            S["q_change"].append(bool(prev) and q is not None and q != max(set(prev), key=prev.count))
            # D/ST own pass rush
            ddb, ds, dg = DEF[Y].before(t, W); S["d_db"].append(ddb); S["d_s"].append(ds)
            pddb, pds, _ = DEF[Y - 1].season(t) if (Y - 1) in DEF else (0, 0, 0)
            S["d_pdb"].append(pddb); S["d_ps"].append(pds)
            # actual opp dropbacks this game (for b fit only)
            a1 = OFF[Y].before(o, W + 1)
            S["o_db_game"].append(a1[0] - db)
    S = {k: np.array(v) for k, v in S.items()}
    for k in list(S):
        if S[k].dtype == object and k != "team": S[k] = S[k].astype(float)
    Yr = S["year"].astype(int); act, ship = S["act"].astype(float), S["ship"].astype(float)
    N = len(act)
    print(f"\n{N} DST team-weeks 2013-26 (final week excluded; 2026 = holdout only) | main 2019-25 n={np.isin(Yr, MAIN).sum()}")

    # ---- expected opp dropbacks: to-date db/g shrunk 4 g to league + b x (dst implied - opp implied)
    og = S["o_g"]; dbl = S["dbl"]
    base_db = (S["o_db"] + 4 * dbl) / (og + 4)
    m = og >= 1
    resid = S["o_db_game"][m] - base_db[m]
    bfit = float(np.polyfit(S["diff"][m], resid, 1)[0])
    print(f"expected-dropback model: shrink 4 g to league; b = {bfit:+.3f} dropbacks per point of (DST implied - opp implied)")
    expdb = base_db + bfit * S["diff"]
    print(f"  corr(expected, actual opp dropbacks) {np.corrcoef(expdb, S['o_db_game'])[0,1]:+.3f} vs to-date only {np.corrcoef(base_db, S['o_db_game'])[0,1]:+.3f}")
    rl = S["rl"]; sl = S["sl"]

    # ---------------- rate builders
    def team_rate(K, d):
        n = S["o_db"] + d * S["o_pdb"]; s = S["o_s"] + d * S["o_ps"]
        return (s + K * rl) / (n + K)
    def qb_rate(K, d, prior):
        n = S["q_cdb"] + d * S["q_db1"] + d ** 2 * S["q_db2"] + d ** 3 * S["q_db3"]
        s = S["q_cs"] + d * S["q_s1"] + d ** 2 * S["q_s2"] + d ** 3 * S["q_s3"]
        return (s + K * prior) / (n + K)
    def own_ratio(K, d):
        n = S["d_db"] + d * S["d_pdb"]; s = S["d_s"] + d * S["d_ps"]
        return ((s + K * rl) / (n + K)) / rl
    rawdb = (S["o_db"] + 1 * dbl) / (og + 1)   # opp's own to-date dropbacks/g, barely shrunk
    def x_of(r, vol):
        if vol == "w": return rawdb * r - dbl * rl
        return (expdb * r - expdb * rl) if vol == "v" else (dbl * (r - rl))

    # ---------------- diagnostics: persistence of sack rate per dropback (team, QB)
    print("\n=== GATE: persistence of sacks taken per DROPBACK ===")
    e, l = [], []
    for Y in POOL:
        for t, (wk, cdb, cs, _) in OFF[Y].d.items():
            i8 = np.searchsorted(wk, 9) - 1
            if i8 >= 5 and len(wk) - i8 - 1 >= 6:
                e.append(cs[i8] / cdb[i8]); l.append((cs[-1] - cs[i8]) / (cdb[-1] - cdb[i8]))
    y0, y1 = [], []
    for Y in POOL:
        for t in OFF[Y].d:
            a = OFF[Y - 1].season(t); b_ = OFF[Y].season(t)
            if a[0] > 300 and b_[0] > 300: y0.append(a[1] / a[0]); y1.append(b_[1] / b_[0])
    print(f"  team  early->late r={np.corrcoef(e,l)[0,1]:+.2f} (n={len(e)})  YoY r={np.corrcoef(y0,y1)[0,1]:+.2f} (n={len(y0)})")
    q0, q1, sameT = [], [], []
    for Y in POOL:
        for q in QB[Y].d:
            a = QB[Y - 1].season(q); b_ = QB[Y].season(q)
            if a[0] > 250 and b_[0] > 250: q0.append(a[1] / a[0]); q1.append(b_[1] / b_[0])
    print(f"  QB    YoY r={np.corrcoef(q0,q1)[0,1]:+.2f} (n={len(q0)})  (QBs with 250+ dropbacks both seasons)")
    lowh = (S["q_cdb"] + S["q_db1"] + S["q_db2"] + S["q_db3"]) < 100
    qa = S["act_sack"]  # DST sacks this game = opp sacks taken
    print(f"  starters with <100 career dropbacks: n={lowh.sum()}, opp sacks/g {qa[lowh].mean():.2f} vs league {sl[lowh].mean():.2f} "
          f"(per expected db {qa[lowh].sum()/expdb[lowh].sum():.4f} vs {rl[lowh].mean():.4f})")
    qc = S["q_change"].astype(bool)
    print(f"  QB-change games (starter != team's usual): n={qc.sum()}")

    # ---------------- variants: name -> (param grid list, fn(params)->x)
    V = {}
    wp = og / (5 + og)
    V["V0 team per game, og/(5+og)"] = ([()], lambda p: ((S["o_s"] / np.maximum(og, 1)) - sl) * wp * (og > 0))
    for vol in ("r", "v"):
        V[f"V1{vol} team per dropback, season-to-date"] = (
            [(K,) for K in (150, 300, 600)], lambda p, vol=vol: x_of(team_rate(p[0], 0.0), vol))
        V[f"V2{vol} team + prior-season carry-in"] = (
            [(K, d) for K in (150, 300, 600) for d in (0.25, 0.5, 1.0)], lambda p, vol=vol: x_of(team_rate(p[0], p[1]), vol))
        V[f"V3{vol} QB-level, shrunk to league"] = (
            [(K, d) for K in (150, 300, 600) for d in (0.5, 0.75, 1.0)], lambda p, vol=vol: x_of(qb_rate(p[0], p[1], rl), vol))
        V[f"V3h{vol} QB-level, shrunk to team (V2 K300 d.5)"] = (
            [(K, d) for K in (150, 300, 600) for d in (0.5, 0.75, 1.0)],
            lambda p, vol=vol: x_of(qb_rate(p[0], p[1], team_rate(300, 0.5)), vol))
        V[f"V4{vol} mix a*QB + (1-a)*team"] = (
            [(a, K) for a in (0.25, 0.5, 0.75) for K in (300, 600)],
            lambda p, vol=vol: x_of(p[0] * qb_rate(p[1], 0.75, rl) + (1 - p[0]) * team_rate(p[1], 0.5), vol))
    # per-game shape checks: shrink P, prior-season carry-in, and per-dropback rates x the opp's OWN volume ("w")
    ppg_prev = np.where(S["o_pdb"] > 0, S["o_ps"] / 16.5, sl)
    V["V0P team per game, shrink P grid"] = ([(Pv,) for Pv in (3, 5, 8, 12)],
        lambda p: (S["o_s"] + p[0] * sl) / (og + p[0]) - sl)
    V["V0c team per game + prior-season carry-in"] = ([(Pv, d) for Pv in (5, 8) for d in (0.25, 0.5)],
        lambda p: (S["o_s"] + p[0] * (sl + p[1] * (ppg_prev - sl))) / (og + p[0]) - sl)
    V["V1w team per dropback x opp own db/g"] = ([(K,) for K in (150, 300, 600)], lambda p: x_of(team_rate(p[0], 0.0), "w"))
    V["V2w team + carry-in x opp own db/g"] = ([(K, d) for K in (150, 300) for d in (0.25, 0.5)], lambda p: x_of(team_rate(p[0], p[1]), "w"))
    V["V3hw QB->team x opp own db/g"] = ([(K, d) for K in (300, 600) for d in (0.5, 1.0)],
        lambda p: x_of(qb_rate(p[0], p[1], team_rate(300, 0.5)), "w"))
    V["V4w mix QB/team x opp own db/g"] = ([(a, K) for a in (0.25, 0.5) for K in (300, 600)],
        lambda p: x_of(p[0] * qb_rate(p[1], 0.75, rl) + (1 - p[0]) * team_rate(p[1], 0.5), "w"))
    V["VOL opp own db/g only (rate at league)"] = ([()], lambda p: rawdb * rl - dbl * rl)
    # does the sack RATE add beyond the opponent's pass VOLUME?  x = vol_x + c * rate_x  (c = 1 is V1w)
    def volsh(G): return (S["o_db"] + G * dbl) / (og + G)
    V["V7 volume + c x rate (c grid: rate beyond volume)"] = ([(c, K) for c in (0.0, 0.5, 1.0, 1.5, 2.0) for K in (300, 600)],
        lambda p: (rawdb - dbl) * rl + p[0] * rawdb * (team_rate(p[1], 0.0) - rl))
    V["V8 rate x volume, volume shrink G grid"] = ([(G, K) for G in (0.5, 1, 2, 4) for K in (300, 600, 1000)],
        lambda p: volsh(p[0]) * team_rate(p[1], 0.0) - dbl * rl)
    V["RATE rate-only at opp own volume (no volume term)"] = ([(K,) for K in (300, 600, 1000)],
        lambda p: rawdb * (team_rate(p[0], 0.0) - rl))
    V["OWN D/ST pass-rush alone (ratio, carry-in)"] = (
        [(K, d) for K in (300, 600) for d in (0.25, 0.5)], lambda p: dbl * rl * (own_ratio(p[0], p[1]) - 1))

    KG = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5]

    def evaluate(name, grid, fn, years, quiet=False):
        """LOYO over (k, params); returns dict with pred (out-of-fold), stats."""
        msk = np.isin(Yr, years)
        cand = {}
        for p in grid:
            x = fn(p)
            for k in KG:
                cand[(k,) + tuple(p)] = x
        err = {c: {y: float(((ship + c[0] * x - act)[Yr == y] ** 2).sum()) for y in years} for c, x in cand.items()}
        oof = ship.copy(); picks = []; wins = 0
        for y in years:
            best = min(cand, key=lambda c: sum(err[c][yy] for yy in years if yy != y))
            picks.append(best); mm = Yr == y
            oof[mm] = ship[mm] + best[0] * cand[best][mm]
            wins += mse(oof[mm], act[mm]) < mse(ship[mm], act[mm])
        pooled = min(cand, key=lambda c: sum(err[c].values()))
        base = mse(ship[msk], act[msk]); new = mse(oof[msk], act[msk])
        pm = msk & np.array([playoff(Y, w) for Y, w in zip(Yr, S["week"].astype(int))])
        res = dict(name=name, d=(new / base - 1) * 100, wins=wins, n=len(years), picks=picks, pooled=pooled, oof=oof,
                   cand=cand, err=err, po=(mse(oof[pm], act[pm]) / mse(ship[pm], act[pm]) - 1) * 100)
        if not quiet:
            print(f"  {name:48s} LOYO {res['d']:+.2f}% MSE  yrs better {wins}/{len(years)}  playoff wks {res['po']:+.2f}%  "
                  f"pooled best {pooled}  picks k {[p[0] for p in picks]}")
        return res

    def forward(res, years_train_from=2013):
        out, wins = [], 0; tot_new = tot_base = 0
        for y in FWD:
            tr = [yy for yy in range(years_train_from, y)]
            best = min(res["cand"], key=lambda c: sum(((ship + c[0] * res["cand"][c] - act)[np.isin(Yr, tr)]) ** 2))
            mm = Yr == y; pr = ship[mm] + best[0] * res["cand"][best][mm]
            a, b = mse(pr, act[mm]), mse(ship[mm], act[mm]); wins += a < b; tot_new += a * mm.sum(); tot_base += b * mm.sum()
            out.append(f"{y}:{(a/b-1)*100:+.2f}%")
        return f"fwd {wins}/{len(FWD)} ({(tot_new/tot_base-1)*100:+.2f}%) " + " ".join(out)

    def rank(pred, years):
        """mean within-week Spearman, top-12 overlap, mean actual of model top-5 / top-12."""
        rho, ov, t5, t12 = [], [], [], []
        for (y, w), idx in pd.DataFrame({"y": Yr, "w": S["week"]}).groupby(["y", "w"]).groups.items():
            if y not in years: continue
            idx = np.array(list(idx))
            if len(idx) < 16: continue
            a, p = act[idx], pred[idx]
            rho.append(spearmanr(p, a).correlation)
            o = np.argsort(-p); at = set(np.argsort(-a)[:12])
            ov.append(len(set(o[:12]) & at) / 12); t5.append(a[o[:5]].mean()); t12.append(a[o[:12]].mean())
        return np.mean(rho), np.mean(ov), np.mean(t5), np.mean(t12)

    def rank_line(res, years):
        b = rank(ship, years); c = rank(res["oof"], years)
        return (f"rho {b[0]:.4f}->{c[0]:.4f} ({c[0]-b[0]:+.4f}) | top12 overlap {b[1]:.3f}->{c[1]:.3f} | "
                f"top5 act {b[2]:.2f}->{c[2]:.2f} | top12 act {b[3]:.2f}->{c[3]:.2f}")

    def rank_years(res, years):
        out = []; w = 0
        for y in years:
            b = rank(ship, [y])[0]; c = rank(res["oof"], [y])[0]; w += c > b; out.append(f"{y}:{c-b:+.4f}")
        return f"rho yrs better {w}/{len(years)}  " + " ".join(out)

    RES = {}
    for label, years in (("2019-25 (main)", MAIN), ("2013-25 (pool)", POOL)):
        msk = np.isin(Yr, years)
        print(f"\n=== LOYO {label}: shipped + k x (expected opp sacks - league), n={msk.sum()}, shipped MSE {mse(ship[msk], act[msk]):.4f} ===")
        for name, (grid, fn) in V.items():
            RES[(label, name)] = evaluate(name, grid, fn, years)

    # pick the best opponent variant on MAIN for the matchup + rank detail
    opp_names = [n for n in V if not n.startswith("OWN")]
    best_name = min(opp_names, key=lambda n: RES[("2019-25 (main)", n)]["d"])
    print(f"\nBest opponent variant on 2019-25: {best_name}")

    # V5: best opp rate x own ratio (multiplicative) / additive own
    grid_b, fn_b = V[best_name]
    pb = RES[("2019-25 (main)", best_name)]["pooled"][1:]
    vol = "v" if best_name.split(" ")[0].endswith("v") else "r"
    x_opp = fn_b(pb)
    r_opp = x_opp / (expdb if vol == "v" else dbl) + rl
    V5 = {
        f"V5 {best_name.split(' ')[0]} x own ratio (mult)": (
            [(K, d) for K in (300, 600) for d in (0.25, 0.5)],
            lambda p: ((expdb if vol == "v" else dbl) * r_opp * own_ratio(p[0], p[1])) - (expdb if vol == "v" else dbl) * rl),
        f"V5a {best_name.split(' ')[0]} + 0.5 x own term (add)": (
            [(K, d) for K in (300, 600) for d in (0.25, 0.5)],
            lambda p: x_opp + 0.5 * dbl * rl * (own_ratio(p[0], p[1]) - 1)),
    }
    for label, years in (("2019-25 (main)", MAIN), ("2013-25 (pool)", POOL)):
        print(f"\n=== {label}: D/ST own pass-rush interaction on top of {best_name} (opp params fixed at pooled {pb}) ===")
        for name, (grid, fn) in V5.items():
            RES[(label, name)] = evaluate(name, grid, fn, years)

    print("\n=== Detail: forward (train all prior seasons 2013..Y-1), rank metrics (LOYO out-of-fold preds) ===")
    for name in list(V) + list(V5):
        r1 = RES[("2019-25 (main)", name)]; r2 = RES[("2013-25 (pool)", name)]
        print(f"  {name}")
        print(f"     2019-25 {r1['d']:+.2f}% {r1['wins']}/7 | 2013-25 {r2['d']:+.2f}% {r2['wins']}/13 | {forward(r1)}")
        print(f"     rank 19-25: {rank_line(r1, MAIN)}")
        py = [f"{y}:{(mse(r2['oof'][Yr==y], act[Yr==y])/mse(ship[Yr==y], act[Yr==y])-1)*100:+.2f}" for y in POOL]
        print(f"     MSE by year (2013-25 LOYO): {' '.join(py)}")
        print(f"     {rank_years(r1, MAIN)}")

    # chosen variant deep dive
    ch = RES[("2019-25 (main)", best_name)]
    k0 = ch["pooled"]; x = ch["cand"][k0]
    print(f"\n=== Chosen {best_name}, pooled params {k0} ===")
    q = np.quantile(x, [1/3, 2/3])
    for lab, mm in (("low", x < q[0]), ("mid", (x >= q[0]) & (x < q[1])), ("high", x >= q[1])):
        mm = mm & np.isin(Yr, MAIN)
        print(f"  x tercile {lab}: x {x[mm].mean():+.2f} sacks | act/ship {act[mm].mean()/ship[mm].mean():.3f} | "
              f"act/(ship+kx) {act[mm].mean()/(ship[mm]+k0[0]*x[mm]).mean():.3f} | sacks {S['act_sack'][mm].mean():.2f}")
    print(f"  sd of k*x {np.std(k0[0]*x[np.isin(Yr, MAIN)]):.3f} pts, max |k*x| {np.abs(k0[0]*x).max():.2f}")
    for wk_lo, wk_hi in ((1, 4), (5, 9), (10, 17)):
        mm = np.isin(Yr, MAIN) & (S["week"] >= wk_lo) & (S["week"] <= wk_hi)
        print(f"  weeks {wk_lo}-{wk_hi}: n {mm.sum()}  LOYO {(mse(ch['oof'][mm], act[mm])/mse(ship[mm], act[mm])-1)*100:+.2f}%")
    mm = np.isin(Yr, MAIN) & qc
    if mm.sum(): print(f"  QB-change games n {mm.sum()}: LOYO {(mse(ch['oof'][mm], act[mm])/mse(ship[mm], act[mm])-1)*100:+.2f}%")
    # component split + 2026 holdout for the leading variants (params = pooled best on 2019-25, nothing refit)
    mm = np.isin(Yr, MAIN)
    for nm in (best_name, "VOL opp own db/g only (rate at league)", "RATE rate-only at opp own volume (no volume term)", "V0 team per game, og/(5+og)"):
        rr = RES[("2019-25 (main)", nm)]; c = rr["pooled"]; xx = c[0] * rr["cand"][c]
        b = [np.polyfit(xx[mm], (S[f"act_{cp}"] - S[f"act_{cp}"][mm].mean())[mm], 1)[0] for cp in ("sack", "to", "pa", "td")]
        tot = np.polyfit(xx[mm], (act - ship)[mm], 1)[0]
        h = Yr == 2026
        hb, hc = mse(ship[h], act[h]), mse((ship + xx)[h], act[h])
        rb, rc = rank(ship, [2026]), rank(ship + xx, [2026])
        print(f"  {nm[:40]:40s} params {c}: slope of (act-ship) on k*x {tot:+.2f} = sack {b[0]:+.2f} / TO {b[1]:+.2f} / PA {b[2]:+.2f} / TD {b[3]:+.2f}"
              f" | 2026 HOLDOUT n={h.sum()} MSE {(hc/hb-1)*100:+.2f}% rho {rb[0]:.3f}->{rc[0]:.3f}")
    # bootstrap by team-week
    rng = np.random.default_rng(7); mm = np.where(np.isin(Yr, MAIN))[0]; ds = []
    e1 = (ch["oof"][mm] - act[mm]) ** 2; e0 = (ship[mm] - act[mm]) ** 2
    for _ in range(2000):
        i = rng.integers(0, len(mm), len(mm)); ds.append(e1[i].mean() / e0[i].mean() - 1)
    ds = np.array(ds) * 100
    print(f"  bootstrap 90% CI {np.percentile(ds,5):+.2f}% .. {np.percentile(ds,95):+.2f}%, P(improve) {(ds<0).mean():.2f}")

if __name__ == "__main__":
    main()
