#!/usr/bin/env python3
"""
BACKUP QB DOUBLE COUNT (Jack 2026-10-09: "test the backup QB double count").
Engine shadow QB vacancy (engine.js '+vacx'): lost = SUM over absent room QBs of full x (1 - cap); the healthy QB with the best
depth string gets max(own, .85 x lost). Trace 10-09 W7: Caleb Williams 15.3 (out -> Bagent 14.5); Caleb AND Bagent out -> Keenum
18.7, above Caleb's own number - the sum adds Bagent's level on top of Caleb's though only one QB plays.

Weekly DB 2019-25, fill-in starts: team-week where the team's PRIMARY QB (most starts, pa >= 15, in the last 3 team games, 2+ of
them) has no row and another QB starts (pa >= 15). Half-PPR from stats (.04 py, 4 ptd, -2 int, .1 ry, 6 rtd, -2 fl).
  S   = primary's mean over his last <= 8 starts (this season, else last season's; >= 3)
  O   = fill-in's own mean over his starts in the prior 2 seasons + this season before the week (>= 2), else NaN
  REL = fill-in's mean over all his games this season before the week (relief included)
Part 1 (single absence): rules for the fill-in's number - .85 S | O | max(O, .85 S) [engine] | blends.
Part 2 (double absence): an earlier fill-in starter this season (P2) is ALSO absent and a third QB starts -> SUM rule
.85 x (S + REL_P2) vs MAX rule .85 x max(S, REL_P2) = .85 S. Log qb_fillin_double.log.
"""
import os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_sim_calibration as cal
LOG = open(os.path.join(HERE, "qb_fillin_double.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()
YEARS = range(2019, 2026); START = 15


def pts(w): return .04 * float(w.get("py") or 0) + 4 * float(w.get("ptd") or 0) - 2 * float(w.get("int") or 0) + .1 * float(w.get("ry") or 0) + 6 * float(w.get("rtd") or 0) - 2 * float(w.get("fl") or 0)


def week_team(Y, w, opp, cache={}):
    k = (Y, w, opp)
    if k not in cache:
        o = cal.OPP_ALIAS.get(opp, opp); cache[k] = None
        for t, s in cal.SCHEDULES.get(Y, {}).items():
            if s.get(str(w)) == o: cache[k] = t; break
    return cache[k]


def main():
    games = defaultdict(dict)   # (Y, team) -> {wk: {name: row}}
    for nm, recs in cal.WEEKLY.items():
        for rec in recs:
            if rec.get("pos") != "QB": continue
            for yy, rows in (rec.get("seasons") or {}).items():
                Y = int(yy)
                if Y not in YEARS and Y != 2018: continue
                for w in rows:
                    if not cal.played(w) or not w.get("opp"): continue
                    t = w.get("tm") or week_team(Y, int(w["wk"]), w["opp"])
                    if t: games[(Y, t)].setdefault(int(w["wk"]), {})[nm] = w
    starts_by = defaultdict(list)   # name -> [(Y, wk, pts)] starts
    all_by = defaultdict(list)
    for (Y, t), wk_map in games.items():
        for wk, d in wk_map.items():
            for nm, w in d.items():
                all_by[nm].append((Y, wk, t, pts(w)))
                if float(w.get("pa") or 0) >= START: starts_by[nm].append((Y, wk, pts(w)))
    def mean_before(lst, Y, wk, seasons, nmax=8, nmin=3):
        xs = [p for (y, w, p) in sorted(lst) if (y < Y or (y == Y and w < wk)) and y >= Y - seasons]
        xs = xs[-nmax:]
        return np.mean(xs) if len(xs) >= nmin else np.nan
    rows1, rows2 = [], []
    for (Y, t), wk_map in games.items():
        if Y not in YEARS: continue
        wks = sorted(wk_map); fill_hist = []   # earlier fill-in starters this season
        for j, wk in enumerate(wks):
            prior = wks[max(0, j - 3):j]
            if len(prior) < 2: continue
            cnt = defaultdict(int)
            for u in prior:
                for nm, w in wk_map[u].items():
                    if float(w.get("pa") or 0) >= START: cnt[nm] += 1
            if not cnt: continue
            prim, c = max(cnt.items(), key=lambda kv: kv[1])
            if c < 2: continue
            cur = wk_map[wk]
            starter = max(cur.items(), key=lambda kv: float(kv[1].get("pa") or 0))
            if float(starter[1].get("pa") or 0) < START: continue
            F = starter[0]
            if prim in cur or F == prim:
                continue
            S = mean_before(starts_by[prim], Y, wk, 1)
            if np.isnan(S): continue
            O = mean_before([(y, w, p) for (y, w, p) in starts_by[F]], Y, wk, 2, nmin=2)
            OA = mean_before([(y, w, p) for (y, w, tt, p) in all_by[F]], Y, wk, 2, nmin=2)   # engine-like own: last <= 8 played games (relief incl.)
            act = pts(starter[1])
            p2 = next((q for q in reversed(fill_hist) if q not in (F, prim) and q not in cur), None)
            if p2:
                rel = [p for (y, w, tt, p) in all_by[p2] if y == Y and w < wk]
                rows2.append((Y, t, wk, F, act, S, np.mean(rel) if rel else 0.0, p2, prim))
            else:
                rows1.append((Y, t, wk, F, act, S, O, OA))
            fill_hist.append(F)
    P(f"single-absence fill-in starts: {len(rows1)}; double-absence (earlier fill-in also out): {len(rows2)}")
    A = np.array([r[4] for r in rows1]); S = np.array([r[5] for r in rows1]); O = np.array([r[6] for r in rows1], dtype=float)
    hasO = ~np.isnan(O)
    P(f"  actual mean {A.mean():.2f} | starter S mean {S.mean():.2f} | act/S {A.sum()/S.sum():.3f} | fill-ins with a start record {hasO.sum()}")
    mae = lambda p, m=None: float(np.mean(np.abs((p - A) if m is None else (p[m] - A[m]))))
    preds = {
        ".85 S": .85 * S,
        "own O (else .85 S)": np.where(hasO, O, .85 * S),
        "max(O, .85 S) [engine]": np.where(hasO, np.maximum(O, .85 * S), .85 * S),
        "O + .85 S [additive]": np.where(hasO, O + .85 * S, .85 * S),
        "mean(O, .85 S)": np.where(hasO, (O + .85 * S) / 2, .85 * S),
    }
    for k in (0.70, 0.75, 0.80, 0.90): preds[f"{k:.2f} S"] = k * S
    P("PART 1 - fill-in's number (MAE, half-PPR; all rows | rows with a start record):")
    for k, v in preds.items():
        P(f"  {k:24s} {mae(v):5.2f} | {mae(v, hasO):5.2f}   bias {np.mean(v - A):+.2f}")
    # per-season wins of the max rule vs .85 S and vs mean
    yrs = np.array([r[0] for r in rows1])
    OA = np.array([r[7] for r in rows1], dtype=float); hasA = ~np.isnan(OA); OAz = np.where(hasA, OA, 0.0)
    P("PART 1b - ENGINE-LIKE own (all played games, relief included, as the shadow's l8 / hist):")
    eng = {
        "max(OA, .85 S) [engine]": np.maximum(OAz, .85 * S),
    }
    for w in (0.3, 0.4, 0.5, 0.6):
        eng[f"w{w} OA + (1-w) .85S, OA>=.5x"] = np.where(hasA & (OAz >= .5 * .85 * S), w * OAz + (1 - w) * .85 * S, .85 * S)
        eng[f"w{w} max-blend"] = w * np.maximum(OAz, .85 * S) + (1 - w) * .85 * S
    for k, v in eng.items(): P(f"  {k:32s} MAE {mae(v):5.2f}  bias {np.mean(v - A):+.2f}  seasons better than engine {sum(1 for y in YEARS if (yrs == y).sum() and mae(v, yrs == y) < mae(eng['max(OA, .85 S) [engine]'], yrs == y))}/7")
    names = list(eng)[1:]
    for label, folds in (("LOYO", [(tuple(y for y in YEARS if y != t), t) for t in YEARS]), ("FORWARD", [(tuple(y for y in YEARS if y < t), t) for t in (2022, 2023, 2024, 2025)])):
        e0 = e1 = 0.0; wins = 0; picks = []
        for tr, te in folds:
            mtr = np.isin(yrs, tr); kk = min(names, key=lambda k: mae(eng[k], mtr)); picks.append(kk)
            mte = yrs == te
            if not mte.sum(): continue
            a0, a1 = mae(eng["max(OA, .85 S) [engine]"], mte), mae(eng[kk], mte); wins += int(a1 < a0); e0 += a0 * mte.sum(); e1 += a1 * mte.sum()
        P(f"  {label}: {100*(e1/e0-1):+.1f}% MAE vs engine ({wins}/{len(folds)}) picks {picks}")
    for alt in (".85 S", "mean(O, .85 S)"):
        w = sum(1 for y in YEARS if (yrs == y).sum() and mae(preds["max(O, .85 S) [engine]"], yrs == y) < mae(preds[alt], yrs == y))
        P(f"  max rule beats {alt} in {w}/7 seasons")
    if rows2:
        A2 = np.array([r[4] for r in rows2]); S2 = np.array([r[5] for r in rows2]); R2 = np.array([r[6] for r in rows2])
        P(f"\nPART 2 - double absence (n {len(rows2)}): actual mean {A2.mean():.2f}, starter S {S2.mean():.2f}, earlier fill-in's level {R2.mean():.2f}")
        for k, v in (("SUM .85 (S + P2) [engine]", .85 * (S2 + R2)), ("MAX .85 max(S, P2)", .85 * np.maximum(S2, R2)), (".75 S", .75 * S2)):
            P(f"  {k:28s} MAE {np.mean(np.abs(v - A2)):5.2f}  bias {np.mean(v - A2):+.2f}")
        for r in rows2[:15]: P(f"    {r[0]} {r[1]} wk{r[2]:2d} {r[3]:20s} act {r[4]:5.1f}  starter {r[8]} {r[5]:4.1f}  also out {r[7]} {r[6]:4.1f}")
    LOG.close()


if __name__ == "__main__":
    main()
