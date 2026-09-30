#!/usr/bin/env python3
"""
TE x OFFENSIVE LINE OUT (Jack 2026-09-30: "go test the te line dock"). The live olOutDock trims a team's TEs x0.97
when 2+ starting linemen are out; the signal ledger found TE residuals POSITIVE when linemen are out (checkdowns).

Two harnesses, both with the 'OL' position label fixed (nflverse labels many linemen plain 'OL' in 2020 / 2025 / 2026;
the 09-01 test only took C/G/T, dropping those teams):
  H1  backtest_ol_out.py form: starting five per season = most games at 60%+ snaps; P=5 blend base (no Vegas);
      per position, rows by missing-starter count, week-controlled ratio (same week bucket, nobody missing), LOYO dock.
  H2  ctx_features form: ol_out_n (Out / Doubtful starters known before kickoff) vs the rebuilt live stack.
Log te_ol_dock_backtest.log.
"""
import os, sys
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_ol_out as O

def load_ol_missing_fixed():
    missing = {}
    for Y in O.YEARS:
        df = pd.read_parquet(os.path.join(O.CACHE, f"snap_counts_{Y}.parquet"), columns=["week", "game_type", "player", "position", "team", "offense_pct"])
        df = df[df.game_type == "REG"]
        tw = defaultdict(set)
        for t, wk in df[["team", "week"]].drop_duplicates().itertuples(index=False): tw[O.TEAM_FIX.get(t, t)].add(int(wk))
        ol = df[df.position.isin(["C", "G", "T", "OL"]) & (df.offense_pct >= 0.6)]
        for t, grp in ol.groupby("team"):
            tm = O.TEAM_FIX.get(t, t)
            counts = [(len(rows), float(rows.offense_pct.mean()), nm, set(int(w) for w in rows.week)) for nm, rows in grp.groupby("player") if len(rows) >= 6]
            five = sorted(counts, reverse=True)[:5]
            if len(five) < 5: continue
            for wk in tw[tm]: missing[(Y, tm, wk)] = sum(1 for _, _, _, wks in five if wk not in wks)
    return missing

def loyo(rows, grid, years):
    a = np.array([r["act"] for r in rows]); b = np.array([r["base"] for r in rows]); y = np.array([r["Y"] for r in rows])
    picks = []; sse1 = sse0 = 0.0; wins = 0
    for Y in years:
        tr = y != Y
        if not (~tr).any(): continue
        k = min(grid, key=lambda k: ((b[tr] * k - a[tr]) ** 2).mean()); picks.append(k)
        e1 = ((b[~tr] * k - a[~tr]) ** 2).sum(); e0 = ((b[~tr] - a[~tr]) ** 2).sum(); sse1 += e1; sse0 += e0; wins += e1 < e0
    return picks, 100 * (sse1 / sse0 - 1), wins

def main():
    lf = open(os.path.join(HERE, "te_ol_dock_backtest.log"), "w", encoding="utf-8")
    def P(s=""):
        print(s); lf.write(s + "\n")
    years = list(O.YEARS)
    miss = load_ol_missing_fixed()
    P(f"=== H1: starting-five availability from snaps ('OL' label included): {len(miss)} team-weeks resolved ===")
    grid = (1.10, 1.06, 1.03, 1.00, 0.97, 0.94, 0.91, 0.88)
    for pos in ("TE", "QB", "RB", "WR"):
        S = O.build_samples(pos)
        for s in S: s["m"] = miss.get((s["Y"], s["tm"], s["wk"]))
        S = [s for s in S if s["m"] is not None and s["base"] >= 4]
        P(f"\n  {pos} ({len(S)} own-team player-weeks, base >= 4):")
        # week-controlled ratios: compare to the same week bucket with nobody missing
        def ratio(x): return sum(r["act"] for r in x) / sum(r["base"] for r in x)
        for lab, f in (("0 missing", lambda s: s["m"] == 0), ("1 missing", lambda s: s["m"] == 1), ("2+ missing", lambda s: s["m"] >= 2)):
            x = [s for s in S if f(s)]
            if len(x) < 40: P(f"    {lab:11s} n={len(x)} (too few)"); continue
            ctrl = []
            for lo, hi in ((1, 6), (7, 12), (13, 18)):
                xb = [s for s in x if lo <= s["wk"] <= hi]; cb = [s for s in S if s["m"] == 0 and lo <= s["wk"] <= hi]
                if len(xb) >= 15 and cb: ctrl.append((len(xb), ratio(xb) / ratio(cb)))
            wc = sum(n * v for n, v in ctrl) / sum(n for n, v in ctrl) if ctrl else float("nan")
            per = [ratio([s for s in x if s["Y"] == Y]) / ratio([s for s in S if s["m"] == 0 and s["Y"] == Y]) for Y in years if sum(1 for s in x if s["Y"] == Y) >= 10]
            P(f"    {lab:11s} n={len(x):5d}  actual/base {ratio(x):.3f}  week-controlled vs nobody missing {wc:.3f}  seasons above 1.0: {sum(1 for v in per if v > 1)}/{len(per)}")
        for lab, f in (("1 missing", lambda s: s["m"] == 1), ("2+ missing", lambda s: s["m"] >= 2)):
            x = [s for s in S if f(s)]
            if len(x) < 60: continue
            picks, d, w = loyo(x, grid, years)
            P(f"    LOYO dock on {lab} rows: picks {picks}  MSE {d:+.2f}% ({w}/{len(years)})   live engine: {'x0.97 at 2+' if pos != 'RB' else 'x0.98 / x0.95'}")
    P("\n=== H2: ctx_features ol_out_n (Out / Doubtful starters, known pre-kickoff) vs the rebuilt live stack ===")
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet")).set_index(["year", "pid", "wk"])
    C = C.join(L[["td_luck_adj", "pool_mult", "rookie_mult", "cond_mult", "weather_mult", "qb_inherit_mult"]], on=["year", "pid", "wk"])
    C["live"] = (C.shipped * C.rookie_mult.fillna(1) * C.pool_mult.fillna(1) * C.cond_mult.fillna(1) * C.weather_mult.fillna(1) * C.qb_inherit_mult.fillna(1) + C.td_luck_adj.fillna(0)).clip(lower=0.2)
    for pos in ("TE", "QB", "RB", "WR"):
        d = C[(C.pos == pos) & (C.live >= 4) & C.ol_out_n.notna()]
        cells = []
        for lab, m in (("0", d.ol_out_n == 0), ("1", d.ol_out_n == 1), ("2+", d.ol_out_n >= 2)):
            x = d[m]
            cells.append(f"{lab} out: {x.act.sum()/x.live.sum():.3f} (n={len(x)})" if len(x) >= 30 else f"{lab} out: n={len(x)}")
        P(f"  {pos}: " + "   ".join(cells))
        for lab, m in (("1 out", d.ol_out_n == 1), ("2+ out", d.ol_out_n >= 2)):
            x = d[m]
            if len(x) < 60: continue
            rows = [{"act": r.act, "base": r.live, "Y": int(r.year)} for r in x.itertuples()]
            picks, dd, w = loyo(rows, grid, years)
            P(f"     LOYO on {lab} rows: picks {picks}  MSE {dd:+.2f}% ({w}/{len(years)})")
    lf.close()

if __name__ == "__main__":
    main()
