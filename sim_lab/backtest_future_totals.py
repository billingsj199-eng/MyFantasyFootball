#!/usr/bin/env python3
"""
FUTURE TEAM TOTALS (Jack 2026-09-29): the lines for weeks 5-18 in betting_lines_2026.js are still
the May / July look-ahead numbers (198 of 208 games unchanged since preseason). Can the lines the
books post DURING the season re-rate each team well enough to update the future totals?

Method ("shift"): for every game already lined in-season,
    delta = closing implied total - what the PRESEASON view said for that same game
    delta(team in game) = dOff[team] + dDef[opponent]        (ridge, recency-weighted)
then a future game becomes   preseason implied + dOff[team] + dDef[opponent].

PART 1  2019-25 (closing lines live in the play-by-play files). Real preseason look-ahead lines
        do not exist for those seasons, so the preseason view is a PROXY: team ratings fit on the
        previous season's last nine weeks (regressed) plus the week-1 closing lines. Standing at
        every checkpoint week, the future closing lines are predicted with the frozen preseason
        view vs the shifted one; every tuning number is picked leave-one-season-out. Graded against
        the closing implied total AND the points actually scored.
PART 2  2026, the real thing: preseason lines from git (commit of 2026-08-26) vs this season's
        closing lines, shifts from the weeks before each graded week.
Log future_totals_backtest.log.
"""
import os, re, sys, json, subprocess, io
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = r"E:\MyFantasyFootball\pbp_cache"; REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"
PRE_COMMIT = "33758b7"
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
def tm(t): return ALIAS.get(t, t)
class Tee:
    def __init__(s, *f): s.f = f
    def write(s, x):
        for f in s.f: f.write(x)
    def flush(s):
        for f in s.f: f.flush()

def load_year(Y):
    cp = os.path.join(HERE, "data", f"_lines_{Y}.pkl")
    if os.path.exists(cp) and Y < 2026: return pd.read_pickle(cp)
    d = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), low_memory=False,
                    usecols=["game_id", "season_type", "week", "home_team", "away_team", "home_score", "away_score", "spread_line", "total_line"])
    g = d[d.season_type == "REG"].dropna(subset=["home_team", "spread_line", "total_line"]).groupby("game_id").first().reset_index()
    # sign of spread_line: pick the one that correlates with the scores
    best = None
    for s in (1, -1):
        hi = (g.total_line + s * g.spread_line) / 2; ai = (g.total_line - s * g.spread_line) / 2
        c = np.corrcoef(np.r_[hi, ai], np.r_[g.home_score, g.away_score])[0, 1]
        if best is None or c > best[0]: best = (c, s)
    s = best[1]
    out = pd.DataFrame({"year": Y, "wk": g.week.astype(int), "home": g.home_team.map(tm), "away": g.away_team.map(tm),
                        "hi": (g.total_line + s * g.spread_line) / 2, "ai": (g.total_line - s * g.spread_line) / 2,
                        "hs": g.home_score, "as_": g.away_score})
    if Y < 2026: out.to_pickle(cp)
    return out

def long(g):
    """one row per team-game: team, opp, home flag, closing implied, points scored"""
    a = pd.DataFrame({"year": g.year, "wk": g.wk, "team": g.home, "opp": g.away, "home": 1.0, "imp": g.hi, "pts": g.hs})
    b = pd.DataFrame({"year": g.year, "wk": g.wk, "team": g.away, "opp": g.home, "home": 0.0, "imp": g.ai, "pts": g.as_})
    return pd.concat([a, b], ignore_index=True)

def ridge_od(rows, y, w, teams, lam, intercept=True, home=True):
    """y ~ [mu] + O[team] + D[opp] [+ h*home]; ridge on O, D only."""
    ix = {t: i for i, t in enumerate(teams)}; n = len(teams); k = 2 * n + (1 if intercept else 0) + (1 if home else 0)
    X = np.zeros((len(rows), k))
    ti = rows.team.map(ix).values; oi = rows.opp.map(ix).values
    X[np.arange(len(rows)), ti] = 1; X[np.arange(len(rows)), n + oi] = 1
    c = 2 * n
    if intercept: X[:, c] = 1; c += 1
    if home: X[:, c] = rows.home.values
    Wm = np.sqrt(w)[:, None]; A = X * Wm; b = y * np.sqrt(w)
    pen = np.zeros(k); pen[:2 * n] = lam
    beta = np.linalg.solve(A.T @ A + np.diag(pen) + 1e-9 * np.eye(k), A.T @ b)
    return {"O": dict(zip(teams, beta[:n])), "D": dict(zip(teams, beta[n:2 * n])), "rest": beta[2 * n:], "int": intercept, "hm": home}
def predict(m, rows):
    p = rows.team.map(m["O"]).values + rows.opp.map(m["D"]).values
    c = 0
    if m["int"]: p = p + m["rest"][c]; c += 1
    if m["hm"]: p = p + m["rest"][c] * rows.home.values
    return p

def shifts(obs, delta, teams, lam, half_life, now_wk):
    w = 0.5 ** ((now_wk - obs.wk.values) / half_life) if half_life else np.ones(len(obs))
    return ridge_od(obs, delta, w, teams, lam, intercept=False, home=False)

def part1():
    print("=== PART 1: 2019-25, closing lines; preseason view = PROXY (last season's final nine weeks regressed + week-1 lines) ===")
    L = {Y: long(load_year(Y)) for Y in range(2018, 2026)}
    years = list(range(2019, 2026))
    P0 = {}
    for Y in years:
        cur, prev = L[Y], L[Y - 1]
        teams = sorted(set(cur.team))
        tr = pd.concat([prev[prev.wk >= 10].assign(w=0.35), cur[cur.wk == 1].assign(w=1.0)], ignore_index=True)
        tr = tr[tr.team.isin(teams) & tr.opp.isin(teams)]
        m = ridge_od(tr, tr.imp.values, tr.w.values, teams, 1.5)
        cur = cur.copy(); cur["p0"] = predict(m, cur) + (cur[cur.wk == 1].imp.mean() - predict(m, cur[cur.wk == 1]).mean())
        P0[Y] = cur
    allr = pd.concat(P0.values(), ignore_index=True)
    print(f"  proxy quality: future closing lines vs the proxy preseason view, weeks 2+  MAE {np.abs(allr[allr.wk>=2].imp-allr[allr.wk>=2].p0).mean():.2f} pts"
          f"   (2026 real preseason lines vs closing, weeks 1-4: see part 2)")
    CHECK = (2, 3, 4, 6, 8, 10, 12)
    GRID = [(lam, hl) for lam in (0.5, 1, 2, 4, 8) for hl in (0, 2, 4)]
    # collect predictions for every (season, checkpoint, grid) on future games
    rec = []
    for Y in years:
        cur = P0[Y]; teams = sorted(set(cur.team))
        for W in CHECK:
            obs = cur[(cur.wk >= 2) & (cur.wk <= W)] if W >= 2 else cur.iloc[0:0]
            fut = cur[cur.wk > W]
            if obs.empty or fut.empty: continue
            d = (obs.imp - obs.p0).values
            for gi, (lam, hl) in enumerate(GRID):
                s = shifts(obs, d, teams, lam, hl, W)
                adj = fut.team.map(s["O"]).values + fut.opp.map(s["D"]).values
                rec.append(pd.DataFrame({"year": Y, "W": W, "gi": gi, "wk": fut.wk.values, "imp": fut.imp.values, "pts": fut.pts.values, "p0": fut.p0.values, "adj": adj}))
    R = pd.concat(rec, ignore_index=True)
    R["h"] = R.wk - R.W
    # leave-one-season-out choice of (lam, half-life) per checkpoint, on closing-line MSE
    pick = {}
    out = []
    for Y in years:
        for W in CHECK:
            tr = R[(R.year != Y) & (R.W == W)]
            if tr.empty: continue
            e = tr.assign(e=(tr.p0 + tr.adj - tr.imp) ** 2).groupby("gi").e.mean()
            gi = int(e.idxmin()); pick.setdefault(W, []).append(GRID[gi])
            out.append(R[(R.year == Y) & (R.W == W) & (R.gi == gi)])
    T = pd.concat(out, ignore_index=True); T["p1"] = T.p0 + T.adj
    def line(lab, x):
        if len(x) < 100: return
        a0 = np.abs(x.p0 - x.imp).mean(); a1 = np.abs(x.p1 - x.imp).mean()
        s0 = np.abs(x.p0 - x.pts).mean(); s1 = np.abs(x.p1 - x.pts).mean()
        wins = sum(1 for Y in years if (x.year == Y).any() and np.abs(x[x.year == Y].p1 - x[x.year == Y].imp).mean() < np.abs(x[x.year == Y].p0 - x[x.year == Y].imp).mean())
        winp = sum(1 for Y in years if (x.year == Y).any() and ((x[x.year == Y].p1 - x[x.year == Y].pts) ** 2).mean() < ((x[x.year == Y].p0 - x[x.year == Y].pts) ** 2).mean())
        q0 = ((x.p0 - x.pts) ** 2).mean(); q1 = ((x.p1 - x.pts) ** 2).mean()
        print(f"  {lab:34s} n={len(x):5d} | vs the eventual closing line: miss {a0:.2f} -> {a1:.2f} pts ({100*(a1/a0-1):+.1f}%, {wins}/7 seasons) | vs points scored: MAE {s0:.2f} -> {s1:.2f} ({100*(s1/s0-1):+.2f}%), MSE {100*(q1/q0-1):+.2f}% ({winp}/7)")
    print("\n  standing after week W, all later games (every tuning number held out by season):")
    for W in CHECK: line(f"after week {W}", T[T.W == W])
    print("\n  by how far ahead the game is:")
    for lab, lo, hi in (("next week", 1, 1), ("2-4 weeks ahead", 2, 4), ("5-8 weeks ahead", 5, 8), ("9+ weeks ahead", 9, 99)):
        line(lab, T[(T.h >= lo) & (T.h <= hi)])
    print("\n  standing after week 4 (where 2026 is now), by how far ahead:")
    for lab, lo, hi in (("next week", 1, 1), ("2-4 weeks ahead", 2, 4), ("5-8 weeks ahead", 5, 8), ("9+ weeks ahead", 9, 99)):
        line(lab, T[(T.W == 4) & (T.h >= lo) & (T.h <= hi)])
    print("\n  ridge strength / recency half-life picked (mode over the 7 held-out fits):")
    best = {}
    for W in CHECK:
        v = pick[W]; mode = max(set(v), key=v.count); best[W] = mode
        print(f"    after week {W}: lambda {mode[0]}, half-life {mode[1] or 'none'}   (all picks {v})")
    # how much of a measured shift survives (slope of future delta on estimated shift, unshrunk-ish lam .5)
    print("\n  how much of a team's measured shift shows up in its later closing lines (slope; 1.0 = all of it):")
    for W in (2, 4, 8):
        x = R[(R.W == W) & (R.gi == GRID.index((0.5, 0)))]
        b = np.polyfit(x.adj, x.imp - x.p0, 1)[0]; c = np.corrcoef(x.adj, x.imp - x.p0)[0, 1]
        print(f"    after week {W}: slope {b:.2f}, corr {c:+.2f}")
    return best

def parse_lines(text):
    out = {}
    for w, a, h, tot, sp, d in re.findall(r"'W(\d+)_([A-Z]+)_([A-Z]+)':\s*\{\s*total:\s*([\d.]+),\s*spread:\s*([+-]?[\d.]+),\s*asOf:\s*'([\d-]+)'", text):
        out[(int(w), tm(a), tm(h))] = {"total": float(tot), "spread": float(sp), "asOf": d}
    return out
def lines_long(d, tag):
    r = []
    for (w, a, h), v in d.items():
        r.append({"wk": w, "team": h, "opp": a, "home": 1.0, tag: (v["total"] - v["spread"]) / 2, "asOf_" + tag: v["asOf"]})
        r.append({"wk": w, "team": a, "opp": h, "home": 0.0, tag: (v["total"] + v["spread"]) / 2, "asOf_" + tag: v["asOf"]})
    return pd.DataFrame(r)

def part2(best):
    print("\n=== PART 2: 2026, real preseason lines (git 2026-08-26) vs this season's closing lines ===")
    pre = parse_lines(subprocess.run(["git", "-C", REPO, "show", f"{PRE_COMMIT}:data/betting_lines_2026.js"], capture_output=True, text=True, encoding="utf-8").stdout)
    now = parse_lines(open(os.path.join(REPO, "data", "betting_lines_2026.js"), encoding="utf-8").read())
    P = lines_long(pre, "pre").merge(lines_long(now, "now"), on=["wk", "team", "opp", "home"])
    sc = long(load_year(2026)); P = P.merge(sc[["wk", "team", "pts"]], on=["wk", "team"], how="left")
    done = P[P.wk <= 4].copy(); done["d"] = done.now - done.pre
    print(f"  games matched: {len(P)//2}; weeks 1-4 team-games {len(done)}; preseason line vs closing line, weeks 1-4: avg miss {done.d.abs().mean():.2f} pts, largest {done.d.abs().max():.1f}")
    for w in (1, 2, 3, 4):
        x = done[done.wk == w]; print(f"    week {w}: avg |closing - preseason| {x.d.abs().mean():.2f}   (2019-25 proxy had ~2 pts at this distance)")
    teams = sorted(set(P.team))
    print("\n  walk-forward: shifts from the weeks before, graded on the next weeks' closing lines")
    tot = []
    for W in (1, 2, 3):
        obs = done[done.wk <= W]; fut = done[done.wk > W]
        for lam, hl in ((1, 0), (2, 0), (4, 0), (8, 0)):
            s = shifts(obs, obs.d.values, teams, lam, hl, W)
            p1 = fut.pre.values + fut.team.map(s["O"]).values + fut.opp.map(s["D"]).values
            a0 = np.abs(fut.pre - fut.now).mean(); a1 = np.abs(p1 - fut.now).mean()
            f2 = fut[fut.pts.notna()]; p2 = p1[fut.pts.notna().values]
            tot.append((W, lam, a0, a1))
            print(f"    after week {W}, lambda {lam}: miss vs closing {a0:.2f} -> {a1:.2f} ({100*(a1/a0-1):+.0f}%)   vs points scored MAE {np.abs(f2.pre-f2.pts).mean():.2f} -> {np.abs(p2-f2.pts).mean():.2f}  (n={len(fut)} team-games, {len(f2)} played)")
    return P, done, teams

if __name__ == "__main__":
    sys.stdout = Tee(sys.__stdout__, open(os.path.join(HERE, "future_totals_backtest.log"), "w", encoding="utf-8"))
    best = part1()
    part2(best)
