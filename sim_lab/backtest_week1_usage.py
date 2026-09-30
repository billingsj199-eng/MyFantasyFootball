#!/usr/bin/env python3
"""
WEEK-1 USAGE AS A STAND-IN FOR A PRESEASON DEPTH CHART (2026-09-16).

Jack: "lets try it - we can also use route data for week one just to back test, and next season i can set up the
depth charts." The ESPN chart cannot order receivers (every starter is depth 1 at his own slot) and no August charts
exist for 2019-24, so this test asks what a GOOD preseason chart would be worth: week-1 usage stands in for it.
Features per player-season (PFF weekly receiving summary week 1, nflverse snap counts week 1):
  rt_rate1   week-1 route participation (routes / team pass plays), WR/TE/RB
  rt_share1  week-1 routes / the team's top route runner at WR+TE (WR/TE) - the receiver ORDER the chart cannot give
  rt_rank1   week-1 rank on the team by routes among WR+TE: 1 / 2 / 3+ dummies
  snap1      week-1 offensive snap share, every position;  snap_rank1  rank on the team at the position by snaps
The target is the player's PPG over his games AFTER his first game (week 1 itself is excluded, so the week-1 usage is
never graded against the week it came from). Graded importance-weighted (Jack's rule) on the top 150 by tier, LOYO
per position and forward 2021-25, vs the v2.16 prior (LIVE + jm) and vs Clay. Log week1_usage.log;
results -> data/week1_usage.js (SIM_W1USAGE_BT).
"""
import json, os, sys, time, warnings
from collections import defaultdict
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B
import backtest_noclay_weekly as NW
import backtest_season_long as SL
import backtest_top150_weighted as TW
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "week1_usage.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
YEARS, POS4 = NW.YEARS, NW.POS4
BASE = [f for f in SL.BASIC if f != "mover"] + ["jm"]          # v2.16 live feature set
ROUTE = ["rt_rate1", "rt_share1", "rt_rk1", "rt_rk2", "rt_rk3"]
SNAP = ["snap1", "snap_rk1", "snap_rk2", "snap_rk3"]
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "rows": [], "forward": []}


def week1_features(T):
    pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "pff_id", "pfr_id"])
    pff2g = {int(r.pff_id): r.gsis_id for r in pl.itertuples(index=False) if pd.notna(r.pff_id) and isinstance(r.gsis_id, str)}
    pfr2g = {r.pfr_id: r.gsis_id for r in pl.itertuples(index=False) if isinstance(r.pfr_id, str) and isinstance(r.gsis_id, str)}
    rt = {}; sn = {}
    for Y in YEARS:
        f = os.path.join(B.CACHE, "pff", "weekly", f"pff_receiving_summary_{Y}_w1.csv")
        if os.path.exists(f):
            d = pd.read_csv(f); d = d[d.position.isin(["WR", "TE", "HB", "RB"])]
            top = d[d.position.isin(["WR", "TE"])].groupby("team_name").routes.max().to_dict()
            d["rk"] = d[d.position.isin(["WR", "TE"])].groupby("team_name").routes.rank(ascending=False, method="first")
            for r in d.itertuples(index=False):
                g = pff2g.get(int(r.player_id))
                if g: rt[(Y, g)] = {"rt_rate1": r.route_rate, "rt_share1": (r.routes / top[r.team_name]) if top.get(r.team_name) else np.nan, "rk": r.rk if not pd.isna(r.rk) else np.nan}
        s = pd.read_parquet(os.path.join(B.CACHE, f"snap_counts_{Y}.parquet"))
        s = s[(s.week == 1) & (s.game_type == "REG") & (s.position.isin(["QB", "RB", "WR", "TE"])) & (s.offense_snaps > 0)].copy()
        s["rk"] = s.groupby(["team", "position"]).offense_pct.rank(ascending=False, method="first")
        for r in s.itertuples(index=False):
            g = pfr2g.get(r.pfr_player_id)
            if g: sn[(Y, g)] = {"snap1": r.offense_pct, "rk": r.rk}
    n = len(T); cols = {c: np.full(n, np.nan) for c in ROUTE + SNAP}
    hit_rt = hit_sn = 0
    for i, r in enumerate(T.itertuples(index=False)):
        k = (int(r.year), r.pid)
        a = rt.get(k)
        if a and r.pos != "QB":
            hit_rt += 1; cols["rt_rate1"][i] = a["rt_rate1"]; cols["rt_share1"][i] = a["rt_share1"]
            if r.pos in ("WR", "TE") and not np.isnan(a["rk"]): cols["rt_rk1"][i] = float(a["rk"] == 1); cols["rt_rk2"][i] = float(a["rk"] == 2); cols["rt_rk3"][i] = float(a["rk"] >= 3)
        b = sn.get(k)
        if b:
            hit_sn += 1; cols["snap1"][i] = b["snap1"]; cols["snap_rk1"][i] = float(b["rk"] == 1); cols["snap_rk2"][i] = float(b["rk"] == 2); cols["snap_rk3"][i] = float(b["rk"] >= 3)
    for c, v in cols.items(): T[c] = v
    P(f"  week-1 route rows matched {hit_rt} / {int((T.pos != 'QB').sum())} non-QB | snap rows matched {hit_sn} / {n}")
    return T


def target_after_week1(T, F):
    """PPG over the player's games after his first game (harness rows with g >= 1)."""
    A = F["A"]; acc = defaultdict(lambda: [0.0, 0])
    for i in range(F["n"]):
        if A["g"][i] >= 1: k = (int(A["year"][i]), A["name"][i], A["pos"][i]); acc[k][0] += A["act"][i]; acc[k][1] += 1
    y = np.full(len(T), np.nan); g = np.zeros(len(T))
    for i, r in enumerate(T.itertuples(index=False)):
        v = acc.get((int(r.year), r.name, r.pos))
        if v and v[1] >= 3: y[i] = v[0] / v[1]; g[i] = v[1]
    return y, g


def main():
    t0 = time.time()
    P("=== Week-1 usage as a preseason-chart stand-in (target = PPG after the first game) ===")
    T, F = SL.build_table(return_F=True); T = week1_features(T)
    y2, g2 = target_after_week1(T, F); ok = ~np.isnan(y2)
    T = T[ok].reset_index(drop=True); y2, g2 = y2[ok], g2[ok]
    T["ppg"] = y2; T["games"] = g2            # the harness fitters read T.ppg / T.games
    act, g, yr, adp, pos, clay, hand = T.ppg.values, T.games.values.astype(float), T.year.values, T.adp.values, T.pos.values, T.clay.values, T.prior.values
    lv = TW.level_of(T); top150 = adp <= 150; rel = lv.copy()
    for ps in POS4:
        m = pos == ps; rel[m] = lv[m] / np.average(lv[m & top150], weights=g[m & top150])
    wg = g * rel ** 2
    P(f"  {len(T)} player-seasons with 3+ games after the first | route features on {int((~T.rt_rate1.isna()).sum())}, snap features on {int((~T.snap1.isna()).sum())}")
    def wm(p, m): return SL.wmse(p[m], act[m], wg[m])
    TIERS = (("top 60", adp <= 60), ("61-100", (adp > 60) & (adp <= 100)), ("101-150", (adp > 100) & (adp <= 150)), ("top 150", top150), ("top 150 WR", top150 & (pos == "WR")), ("top 150 RB", top150 & (pos == "RB")), ("top 150 TE", top150 & (pos == "TE")))
    def grade(label, pred, base, store, fm=None):
        cells = []
        for lab, m in TIERS:
            mm = m & ~np.isnan(pred) & ~np.isnan(base) & (fm if fm is not None else True); ys = [y for y in YEARS if (mm & (yr == y)).sum() >= 10]
            e, eb, ec = wm(pred, mm), wm(base, mm), wm(clay, mm)
            wb = sum(1 for y in ys if wm(pred, mm & (yr == y)) < wm(base, mm & (yr == y))); wc = sum(1 for y in ys if wm(pred, mm & (yr == y)) < wm(clay, mm & (yr == y)))
            store.append({"label": f"{label} | {lab}", "n": int(mm.sum()), "vsBase": round((e / eb - 1) * 100, 2), "baseWins": int(wb), "vsClay": round((e / ec - 1) * 100, 2), "clayWins": int(wc), "years": len(ys)})
            cells.append(f"{lab} {(e/ec-1)*100:+5.1f}% ({wc}/{len(ys)}) [{(e/eb-1)*100:+5.2f}% {wb}/{len(ys)}]")
        P(f"  {label:30s} " + " | ".join(cells))
    SETS = {"v2.16 (LIVE + jm)": BASE, "+ routes wk1": BASE + ROUTE, "+ snaps wk1": BASE + SNAP, "+ routes + snaps wk1": BASE + ROUTE + SNAP}
    P("\n--- LOYO: cell = vs Clay (seasons won) [vs v2.16 prior, seasons won]; importance-weighted ---")
    lo = {k: SL.loyo(T, fs, "ridge", 10.0) for k, fs in SETS.items()}; mk = lambda r: np.where(np.isnan(r), hand, 0.5 * r + 0.5 * hand)
    base = mk(lo["v2.16 (LIVE + jm)"])
    for k in SETS: grade(k, mk(lo[k]), base, RES["rows"])
    grade("ridge alone + routes + snaps", lo["+ routes + snaps wk1"], base, RES["rows"])
    grade("0.5 (+routes+snaps) + 0.5 Clay", 0.5 * mk(lo["+ routes + snaps wk1"]) + 0.5 * clay, base, RES["rows"])
    P("\n--- FORWARD 2021-25 ---")
    fm = yr >= YEARS[2]; fw = {k: SL.forward(T, fs, "ridge", 10.0) for k, fs in SETS.items()}; basef = mk(fw["v2.16 (LIVE + jm)"])
    for k in SETS: grade("forward " + k, mk(fw[k]), basef, RES["forward"], fm)
    # riser rows: the top-60 player-seasons where Clay sat 2+ above the v2.16 prior
    d = (clay - base >= 2) & (adp <= 60); best = mk(lo["+ routes + snaps wk1"])
    P(f"\n--- the {d.sum()} top-60 rows where Clay sat 2+ above the prior: mean pred v2.16 {np.average(base[d], weights=g[d]):.2f} -> +wk1 usage {np.average(best[d], weights=g[d]):.2f} (act {np.average(act[d], weights=g[d]):.2f}, Clay {np.average(clay[d], weights=g[d]):.2f}) ---")
    for i in np.where(d)[0][:12]:
        r = T.iloc[i]; P(f"  {int(r.year)} {r['name']:22s} {r.pos} adp {r.adp:4.0f} | snap1 {r.snap1 if not np.isnan(r.snap1) else float('nan'):.2f} rt_rate1 {r.rt_rate1 if not np.isnan(r.rt_rate1) else float('nan'):5.1f} rt_share1 {r.rt_share1 if not np.isnan(r.rt_share1) else float('nan'):.2f} | v2.16 {base[i]:5.1f} -> {best[i]:5.1f} | act {r.ppg:5.1f} Clay {r.clay:5.1f}")
    r150 = [r for r in RES["rows"] if r["label"].endswith("| top 150")]; f150 = [r for r in RES["forward"] if r["label"].endswith("| top 150")]
    RES["summary"] = ("Top 150 LOYO vs v2.16: " + "; ".join(f"{r['label'].split(' | ')[0]} {r['vsBase']:+.2f}% ({r['baseWins']}/{r['years']})" for r in r150 if "v2.16" not in r["label"].split(" | ")[0]) +
                      ". Forward: " + "; ".join(f"{r['label'].split(' | ')[0].replace('forward ', '')} {r['vsBase']:+.2f}% ({r['baseWins']}/{r['years']})" for r in f150 if "v2.16" not in r["label"].split(" | ")[0]) + ".")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "week1_usage.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_W1USAGE_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/week1_usage.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
