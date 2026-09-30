#!/usr/bin/env python3
"""
CLAY-FREE POOL DEFINITION (2026-09-16).

Jack: "build the Clay-free pool definition next." Today the engine projects exactly the players in Clay's sheet
(493 in 2026). Without Clay, WHO gets a projection? A membership rule from Clay-free sources, scored on how much
of the fantasy-relevant season it captures, 2019-25, against Clay's own pool:
  relevant player-weeks   STARTER = weekly top QB12 / RB24 / WR36 / TE12 (half-PPR, all players in the weekly DB);
                          ROSTERABLE = top QB24 / RB48 / WR72 / TE24
  preseason rules         CLAY     Clay's sheet (the harness pool, >= 40 projected pts; and Clay ALL)
                          ADP      listed in FFC preseason ADP (~200-250 players)
                          CHART    on the week-1 depth chart at string <= 2 (QB/RB/TE; WR = top 6)
                          HIST     >= 8 games and >= 4 half-PPR PPG over the prior three seasons (weighted .5/.3/.2)
                          ROOKIE   drafted in rounds 1-4 that spring
                          unions   ADP+CHART, ADP+CHART+HIST, ADP+CHART+HIST+ROOKIE (= the Clay-free candidate)
  in-season adds          from week 2, anyone who posted >= 10 half-PPR points in an earlier week joins the pool
Metrics per rule and season: pool size, recall of STARTER and ROSTERABLE player-weeks (all weeks / week 1 / with
in-season adds), share of relevant points captured. Log pool_definition_backtest.log;
results -> data/pool_definition_backtest.js (SIM_POOLDEF_BT), ZONES tab.
"""
import json, os, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_sim_calibration as cal
import bt_common as B
import backtest_noclay_weekly as NW

sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "pool_definition_backtest.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

YEARS = list(range(2019, 2026)); POS4 = ("QB", "RB", "WR", "TE")
STARTER = {"QB": 12, "RB": 24, "WR": 36, "TE": 12}; ROSTER = {"QB": 24, "RB": 48, "WR": 72, "TE": 24}
ADD_PTS = 10.0
SLOTS = {"QB": 1, "RB": 1, "WR": 3, "TE": 1}
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "rules": [], "bySeason": {}, "missed": []}


def weekly_universe(Y):
    """rows (norm, pos, wk, fpts) for every played week in season Y, every player in the weekly DB."""
    rows = []
    for nk, lst in cal.WEEKLY.items():
        for rec in lst:
            pos = rec.get("pos")
            if pos not in POS4: continue
            for w in rec.get("seasons", {}).get(str(Y), []):
                if cal.played(w) and isinstance(w.get("fpts"), (int, float)):
                    rows.append((nk, pos, int(w["wk"]), float(w["fpts"])))
    return rows


def hist_ok(nk, pos, Y):
    for rec in cal.WEEKLY.get(nk, []):
        if rec.get("pos") != pos: continue
        num = den = 0.0; gms = 0
        for i, yy in enumerate((Y - 1, Y - 2, Y - 3)):
            pts = [w["fpts"] for w in rec.get("seasons", {}).get(str(yy), []) if cal.played(w) and isinstance(w.get("fpts"), (int, float))]
            if len(pts) >= 4:
                num += (0.5, 0.3, 0.2)[i] * (sum(pts) / len(pts)); den += (0.5, 0.3, 0.2)[i]; gms += len(pts)
        if den > 0 and gms >= 8 and num / den >= 4: return True
    return False


def chart_pool(Y):
    d = pd.read_parquet(os.path.join(B.CACHE, f"depth_charts_{Y}.parquet"))
    out = set()
    if "depth_team" in d.columns:
        d = d[(d.game_type == "REG") & (d.week == 1) & d.position.isin(POS4) & (d.depth_position == d.position)]
        for r in d.itertuples(index=False):
            try: s = int(r.depth_team)
            except Exception: continue
            if s <= 2: out.add((cal.norm(str(r.full_name)), r.position))
    else:
        d = d[d.pos_abb.isin(POS4)].copy(); d["dt"] = pd.to_datetime(d.dt, utc=True).dt.tz_localize(None)
        d = d[d.dt < pd.Timestamp(f"{Y}-09-04")]
        if len(d):
            last = d.dt.max(); d = d[d.dt == last]
            for r in d.itertuples(index=False):
                if int(np.ceil(int(r.pos_rank) / SLOTS[r.pos_abb])) <= 2: out.add((cal.norm(str(r.player_name)), r.pos_abb))
    return out


def main():
    t0 = time.time()
    P("=== Clay-free pool definition ===")
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    adp = json.load(open(os.path.join(HERE, "data", "ffc_adp_hist.json"), encoding="utf-8"))
    dp = pd.read_parquet(os.path.join(B.CACHE, "draft_picks.parquet"), columns=["season", "round", "pfr_player_name", "position"])
    agg = defaultdict(lambda: defaultdict(list))
    for Y in YEARS:
        rows = weekly_universe(Y)
        # weekly ranks
        byw = defaultdict(list)
        for nk, pos, wk, f in rows: byw[(pos, wk)].append((f, nk))
        starter, roster = set(), set(); pts_rel = {}
        for (pos, wk), lst in byw.items():
            lst.sort(reverse=True)
            for i, (f, nk) in enumerate(lst):
                if i < ROSTER[pos]: roster.add((nk, pos, wk)); pts_rel[(nk, pos, wk)] = f
                if i < STARTER[pos]: starter.add((nk, pos, wk))
        players = {(nk, pos) for nk, pos, _, _ in rows}
        # pools
        pool_clay = {(cal.norm(n), c.get("pos")) for n, c in clay_hist[str(Y)].items() if c.get("pos") in POS4 and (c.get("pts") or 0) >= cal.POOL_MIN_PTS}
        pool_clay_all = {(cal.norm(n), c.get("pos")) for n, c in clay_hist[str(Y)].items() if c.get("pos") in POS4}
        pool_adp = {(cal.norm(p["name"]), p["pos"]) for p in adp[str(Y)]["players"] if p["pos"] in POS4}
        pool_chart = chart_pool(Y)
        pool_hist = {(nk, pos) for (nk, pos) in players if hist_ok(nk, pos, Y)} | {(nk, pos) for nk in cal.WEEKLY for pos in POS4 if any(r.get("pos") == pos for r in cal.WEEKLY[nk]) and hist_ok(nk, pos, Y)}
        pool_rook = {(cal.norm(str(r.pfr_player_name)), r.position) for r in dp[(dp.season == Y) & (dp["round"] <= 4) & dp.position.isin(POS4)].itertuples(index=False)}
        rules = [("CLAY (>= 40 pts)", pool_clay), ("CLAY all", pool_clay_all), ("ADP", pool_adp), ("CHART string <= 2", pool_chart), ("HIST", pool_hist), ("ROOKIE rd 1-4", pool_rook),
                 ("ADP + CHART", pool_adp | pool_chart), ("ADP + CHART + HIST", pool_adp | pool_chart | pool_hist), ("ADP + CHART + HIST + ROOKIE", pool_adp | pool_chart | pool_hist | pool_rook),
                 ("ADP + HIST + ROOKIE (no chart)", pool_adp | pool_hist | pool_rook)]
        # in-season adds: first week after a >= ADD_PTS game
        first_big = {}
        for nk, pos, wk, f in rows:
            if f >= ADD_PTS and ((nk, pos) not in first_big or wk < first_big[(nk, pos)]): first_big[(nk, pos)] = wk
        RES["bySeason"][Y] = {}
        for lab, pool in rules:
            def recall(target, dynamic):
                hit = 0
                for (nk, pos, wk) in target:
                    if (nk, pos) in pool or (dynamic and (nk, pos) in first_big and first_big[(nk, pos)] < wk): hit += 1
                return hit / max(1, len(target))
            st_all = recall(starter, False); st_w1 = recall({t for t in starter if t[2] == 1}, False); st_dyn = recall(starter, True)
            ro_all = recall(roster, False); ro_dyn = recall(roster, True)
            pts_cov = sum(f for (nk, pos, wk), f in pts_rel.items() if (nk, pos) in pool) / max(1e-9, sum(pts_rel.values()))
            row = {"size": len(pool), "starterAll": st_all, "starterWk1": st_w1, "starterDyn": st_dyn, "rosterAll": ro_all, "rosterDyn": ro_dyn, "ptsShare": pts_cov}
            RES["bySeason"][Y][lab] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()}
            for k, v in row.items(): agg[lab][k].append(v)
        # who does the candidate miss among starters (all weeks) - for the record
        cand = pool_adp | pool_chart | pool_hist | pool_rook
        miss = defaultdict(int)
        for (nk, pos, wk) in starter:
            if (nk, pos) not in cand: miss[(nk, pos)] += 1
        top = sorted(miss.items(), key=lambda kv: -kv[1])[:8]
        RES["missed"].append({"season": Y, "top": [{"name": nk, "pos": pos, "starterWeeks": c, "inClay": (nk, pos) in pool_clay_all} for (nk, pos), c in top]})
        P(f"  {Y}: universe {len(players)} players, starter weeks {len(starter)}, rosterable {len(roster)} | Clay {len(pool_clay)} / all {len(pool_clay_all)} | ADP {len(pool_adp)} chart {len(pool_chart)} hist {len(pool_hist)} rookies {len(pool_rook)} | candidate {len(cand)} | top missed starters: " + ", ".join(f"{nk} {pos} {c}wk{'*' if (nk, pos) in pool_clay_all else ''}" for (nk, pos), c in top[:5]))
    P("\n=== Averages 2019-25 (recall of relevant player-weeks; DYN = with in-season adds after a 10-pt game) ===")
    P(f"  {'rule':34s} {'size':>5s} {'starter':>8s} {'st wk1':>7s} {'st DYN':>7s} {'roster':>7s} {'ro DYN':>7s} {'pts%':>6s}")
    for lab in agg:
        a = agg[lab]
        row = {"rule": lab, "size": round(float(np.mean(a["size"])), 0), "starterAll": round(float(np.mean(a["starterAll"])), 4), "starterWk1": round(float(np.mean(a["starterWk1"])), 4), "starterDyn": round(float(np.mean(a["starterDyn"])), 4),
               "rosterAll": round(float(np.mean(a["rosterAll"])), 4), "rosterDyn": round(float(np.mean(a["rosterDyn"])), 4), "ptsShare": round(float(np.mean(a["ptsShare"])), 4)}
        RES["rules"].append(row)
        P(f"  {lab:34s} {row['size']:5.0f} {100*row['starterAll']:7.1f}% {100*row['starterWk1']:6.1f}% {100*row['starterDyn']:6.1f}% {100*row['rosterAll']:6.1f}% {100*row['rosterDyn']:6.1f}% {100*row['ptsShare']:5.1f}%")
    c = [r for r in RES["rules"] if r["rule"] == "ADP + CHART + HIST + ROOKIE"][0]; k = [r for r in RES["rules"] if r["rule"] == "CLAY (>= 40 pts)"][0]
    RES["summary"] = (f"Candidate pool (ADP + week-1 chart string <= 2 + own history + rookies rd 1-4): {c['size']:.0f} players a season, captures {100*c['starterAll']:.1f}% of starter weeks "
                      f"({100*c['starterDyn']:.1f}% with in-season adds) vs Clay's pool {k['size']:.0f} players / {100*k['starterAll']:.1f}% ({100*k['starterDyn']:.1f}%).")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "pool_definition_backtest.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_POOLDEF_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/pool_definition_backtest.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
