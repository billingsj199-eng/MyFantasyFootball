#!/usr/bin/env python3
"""
CLAY-FREE BACKTEST POOL for the extended history (2026-10-20, Jack: "yes download back to 2012 and rebuild").

The ROS / next-game harnesses take their player pool from Clay's preseason sheet (>= 40 projected half-PPR pts),
which only exists 2019-25. For SIM_BT_YEARS outside that window (bt_ext.EXT) the pool comes from this file instead:
preseason-known, Clay-free sources only -

  ADP     FFC 12-team preseason ADP (data/ffc_adp_hist.json; half-PPR, else PPR, else standard) <= ADP_MAX
  CHART   week-1 depth chart (nflverse) string <= CHART[pos]   (2025: last ESPN chart before Sep 4)
  HIST    3-yr weighted half-PPR PPG (.5/.3/.2 over Y-1..Y-3, >= 4 games a season, >= 8 total) >= HIST[pos]
  ROOKIE  drafted that spring in rounds <= ROOKIE_RD
  union of the four, QB/RB/WR/TE.

`python build_bt_pool_ext.py --grid` scores a grid of settings against Clay's pool on 2019-25 (player-seasons that
produce harness rows: weekly record + team inferred; Jaccard, recall of Clay rows, precision) and prints the best.
`python build_bt_pool_ext.py` writes data/bt_pool_ext.json (atomic temp + rename) for 2012-2025 with RULE below.
"""
import json, os, sys, time, itertools
from collections import defaultdict
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_sim_calibration as cal

CACHE = r"E:\MyFantasyFootball\pbp_cache"
POS4 = ("QB", "RB", "WR", "TE")
OUT = os.path.join(HERE, "data", "bt_pool_ext.json")
ALL_YEARS = list(range(2012, 2026))
# chosen by --grid on 2019-25 (see the memory project_backtest_2012_extension.md)
RULE = {"adp": 200, "chart": {"QB": 1, "RB": 2, "WR": 1, "TE": 2}, "hist": {"QB": 14.0, "RB": 6.0, "WR": 4.0, "TE": 4.5}, "rookie_rd": 3}
SLOTS = {"QB": 1, "RB": 1, "WR": 3, "TE": 1}


def display_names():
    """norm -> original key in the weekly_stats JS files (active file first), so harness rows carry readable names."""
    out = {}
    for f in ["weekly_stats_active.js", "weekly_stats_retired_1.js", "weekly_stats_retired_2.js", "weekly_stats_retired_3.js"]:
        raw = open(os.path.join(cal.REPO, "data", f), encoding="utf-8").read()
        d, _ = json.JSONDecoder().raw_decode(raw, raw.index('{"'))
        for name in d:
            out.setdefault(cal.norm(name), name)
    return out


def adp_sets():
    d = json.load(open(os.path.join(HERE, "data", "ffc_adp_hist.json"), encoding="utf-8"))
    out = {}
    for y, blk in d.items():
        out[int(y)] = {(cal.norm(p["name"]), p["pos"]): float(p["adp"]) for p in blk["players"] if p["pos"] in POS4 and isinstance(p.get("adp"), (int, float))}
    return out


def chart_strings(Y):
    """{(norm, pos): week-1 string}"""
    p = os.path.join(CACHE, f"depth_charts_{Y}.parquet")
    if not os.path.exists(p): return {}
    d = pd.read_parquet(p); out = {}
    if "depth_team" in d.columns:
        d = d[(d.game_type == "REG") & (d.week == 1) & d.position.isin(POS4) & (d.depth_position == d.position)]
        for r in d.itertuples(index=False):
            try: s = int(r.depth_team)
            except Exception: continue
            k = (cal.norm(str(r.full_name)), r.position); out[k] = min(out.get(k, 99), s)
    else:
        d = d[d.pos_abb.isin(POS4)].copy(); d["dt"] = pd.to_datetime(d.dt, utc=True).dt.tz_localize(None)
        d = d[d.dt < pd.Timestamp(f"{Y}-09-04")]
        if len(d):
            d = d[d.dt == d.dt.max()]
            for r in d.itertuples(index=False):
                k = (cal.norm(str(r.player_name)), r.pos_abb); s = int(np.ceil(int(r.pos_rank) / SLOTS[r.pos_abb])); out[k] = min(out.get(k, 99), s)
    return out


def hist_ppg(rec, Y):
    num = den = 0.0; gms = 0
    for i, yy in enumerate((Y - 1, Y - 2, Y - 3)):
        pts = [w["fpts"] for w in rec.get("seasons", {}).get(str(yy), []) if cal.played(w) and isinstance(w.get("fpts"), (int, float))]
        if len(pts) >= 4:
            num += (0.5, 0.3, 0.2)[i] * (sum(pts) / len(pts)); den += (0.5, 0.3, 0.2)[i]; gms += len(pts)
    return (num / den) if (den > 0 and gms >= 8) else None


def rookie_rounds():
    dp = pd.read_parquet(os.path.join(CACHE, "draft_picks.parquet"), columns=["season", "round", "pfr_player_name", "position"])
    out = defaultdict(dict)
    for r in dp.itertuples(index=False):
        if r.position in POS4 and isinstance(r.pfr_player_name, str):
            out[int(r.season)][(cal.norm(r.pfr_player_name), r.position)] = int(r[1])
    return out


def features(years):
    """per Y: {(norm,pos): {adp, str, hist, rd, rows}} for every weekly-DB player of the position, + Clay pool where it exists."""
    adp = adp_sets(); rk = rookie_rounds()
    clay = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    out = {}
    for Y in years:
        ch = chart_strings(Y); feat = {}
        for nk, lst in cal.WEEKLY.items():
            for rec in lst:
                pos = rec.get("pos")
                if pos not in POS4: continue
                k = (nk, pos)
                if cal.weekly_rec(nk, pos) is not rec: continue          # ambiguous names never make harness rows
                rows = sum(1 for w in rec.get("seasons", {}).get(str(Y), []) if cal.played(w))
                team = cal.infer_team(rec, Y) if rows >= 4 else None
                feat[k] = {"adp": adp.get(Y, {}).get(k), "str": ch.get(k), "hist": hist_ppg(rec, Y), "rd": rk.get(Y, {}).get(k), "rows": rows if team else 0}
        cl = None
        if str(Y) in clay:
            cl = {(cal.norm(n), c.get("pos")) for n, c in clay[str(Y)].items() if c.get("pos") in POS4 and (c.get("pts") or 0) >= cal.POOL_MIN_PTS}
        out[Y] = (feat, cl)
    return out


def member(f, pos, rule):
    src = []
    if f["adp"] is not None and f["adp"] <= rule["adp"]: src.append("adp")
    if f["str"] is not None and f["str"] <= rule["chart"][pos]: src.append("chart")
    if f["hist"] is not None and f["hist"] >= rule["hist"][pos]: src.append("hist")
    if f["rd"] is not None and f["rd"] <= rule["rookie_rd"]: src.append("rookie")
    return src


def score(FE, rule, years=range(2019, 2026)):
    tot = {"E": 0, "C": 0, "I": 0, "rE": 0, "rC": 0, "rI": 0}; per = {}
    for Y in years:
        feat, cl = FE[Y]
        E = {k for k, f in feat.items() if f["rows"] and member(f, k[1], rule)}
        C = {k for k in (cl or ()) if k in feat and feat[k]["rows"]}
        I = E & C
        rows = lambda S: sum(feat[k]["rows"] for k in S)
        d = {"E": len(E), "C": len(C), "I": len(I), "rE": rows(E), "rC": rows(C), "rI": rows(I)}
        per[Y] = d
        for k2 in tot: tot[k2] += d[k2]
    tot["jac"] = tot["I"] / max(1, tot["E"] + tot["C"] - tot["I"]); tot["rjac"] = tot["rI"] / max(1, tot["rE"] + tot["rC"] - tot["rI"])
    tot["recall"] = tot["rI"] / max(1, tot["rC"]); tot["prec"] = tot["rI"] / max(1, tot["rE"])
    return tot, per


def grid():
    t0 = time.time()
    FE = features(range(2019, 2026))
    print(f"features built {time.time()-t0:.0f}s")
    best = []
    for adp_, cq, cr, cw, ct, hq, hr, hw, ht, rd in itertools.product((120, 160, 200), (1, 2), (1, 2, 3), (1, 2, 3), (1, 2), (8.0, 10.0, 12.0, 14.0), (4.0, 5.0, 6.0, 7.0), (4.0, 5.0, 6.0, 7.0), (2.5, 3.5, 4.5), (3, 4, 5)):
        rule = {"adp": adp_, "chart": {"QB": cq, "RB": cr, "WR": cw, "TE": ct}, "hist": {"QB": hq, "RB": hr, "WR": hw, "TE": ht}, "rookie_rd": rd}
        tot, _ = score(FE, rule)
        best.append((tot["rjac"], tot["jac"], rule, tot))
    best.sort(key=lambda x: -x[0])
    for rj, j, rule, tot in best[:12]:
        print(f"  rows Jaccard {rj:.4f}  players Jaccard {j:.4f}  recall {tot['recall']:.4f} precision {tot['prec']:.4f}  sizes ext {tot['E']/7:.0f} clay {tot['C']/7:.0f}/yr  {json.dumps(rule)}")
    return best[0][2], FE


def write(rule):
    t0 = time.time()
    names = display_names()
    FE = features(ALL_YEARS)
    out = {"updated": time.strftime("%Y-%m-%d %H:%M"), "rule": rule, "src": "build_bt_pool_ext.py", "years": {}}
    for Y in ALL_YEARS:
        feat, cl = FE[Y]; mem = {}
        for (nk, pos), f in feat.items():
            src = member(f, pos, rule)
            if src: mem[names.get(nk, nk)] = {"pos": pos, "src": src, "adp": f["adp"], "str": f["str"]}
        out["years"][str(Y)] = mem
    tot, per = score(FE, rule)
    out["overlap"] = {"total": tot, "bySeason": per}
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh: json.dump(out, fh)
    os.replace(tmp, OUT)
    print(f"wrote {OUT} ({time.time()-t0:.0f}s): " + ", ".join(f"{Y} {len(out['years'][str(Y)])}" for Y in ALL_YEARS))
    print(f"2019-25 overlap with Clay's pool (players that make rows): rows Jaccard {tot['rjac']:.4f}, players Jaccard {tot['jac']:.4f}, Clay rows recalled {tot['recall']:.4f}, ext rows that are Clay rows {tot['prec']:.4f}")
    for Y, d in per.items():
        print(f"  {Y}: ext {d['E']} clay {d['C']} both {d['I']} | rows ext {d['rE']} clay {d['rC']} both {d['rI']}")


if __name__ == "__main__":
    if "--grid" in sys.argv:
        r, _ = grid(); print("BEST", json.dumps(r))
    else:
        write(RULE)
