#!/usr/bin/env python3
"""
DEPTH-CHART POOL (Jack 2026-10-09: "i thought we are clay free now" -> "just look at depth charts ideally").
The engine's membership was Clay's preseason sheet, so in-season bodies (Dameon Pierce, PHI RB3) never got a row and the
opportunity pool's shares for their depth slots were simply lost. This adds every RB / WR / TE on the ESPN depth chart
(data/sim_depth.js) inside the pool's depth ranks - QB top 3 (Jack 10-09 "add the QBs from depth charts too"; ALWAYS the slot
line, never own history; engine keeps them out of the QB start split), RB top 3, WR top 4, TE top 2 - who is
not already on the sheet (alias-aware: exact norm, or same position + team + last name).
Each extra gets a Clay-FORMAT season line built from HIS OWN games (per-game rates over 2024-26 in the weekly DB x 17;
build_noclay_pool.py's stat mix), so the engine's prior for him is history, not Clay. No usable history (< 4 games) ->
SLOT PRIOR (Jack 2026-10-09 "add the no-history depth guys too"): what the players currently at the same position + depth
slot league-wide produce per TEAM game this season (his games with that team since his first row there; DNPs count as 0).
Writes data/sim_depth_pool.js (window.SIM_DEPTH_POOL = {name: row}); engine buildPlayers merges it (kill
window.SIM_DEPTH_POOL_ON = false). --dry-run prints without writing.
"""
import json, os, sys, time
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import re
import backtest_sim_calibration as cal

DEPTH_MAX = {"QB": 3, "RB": 3, "WR": 4, "TE": 2}
K_MAX = 1   # kickers (Jack 10-09 "add kickers from depth charts too"): the chart K1; his line is the engine's Clay-free Vegas kicker line (SIM_K_CLAYFREE), so the row only needs membership
QB_START_PA = 15      # a game with 15+ pass attempts = a start (excluded from the backup slot line)
QB_SLOT_ONLY = True   # QBs ALWAYS take the slot line: a backup's history is his starting days (shadow v2.8 lesson); the injury layer hands him the starter's share when he inherits
MIN_G = 4
STATS = ("pa", "pc", "py", "ptd", "int", "ra", "ry", "rtd", "tgt", "rec", "rcy", "rctd", "fl")


def main():
    dry = "--dry-run" in sys.argv
    depth = json.load(open(os.path.join(cal.REPO, "data", "depth_charts_2026.json"), encoding="utf-8"))   # same source as sim_depth.js
    clay = {}   # the sheet is a JS literal with bare keys - read name / pos / tm by regex (no node dependency for the scheduled refresh)
    for m in re.finditer(r'^\s*"([^"]+)":\s*\{pos:"([A-Z]+)",tm:"([A-Z]+)"', open(os.path.join(HERE, "data", "mike_clay_projections.js"), encoding="utf-8").read(), re.M):
        clay[m.group(1)] = {"pos": m.group(2), "tm": m.group(3)}
    TEAMFIX = {"ARZ": "ARI", "WSH": "WAS", "JAC": "JAX", "LA": "LAR"}
    have = set(); have_last = set()
    for nm, r in clay.items():
        if not isinstance(r, dict): continue
        k = cal.norm(nm); have.add(k)
        parts = k.split()
        if parts: have_last.add((r.get("pos"), TEAMFIX.get(r.get("tm"), r.get("tm")), parts[-1]))
    # SLOT PRIOR: per (pos, depth index) stats per team game, 2026, over everyone currently charted there with 2026 rows
    team_wks = defaultdict(set)
    for recs in cal.WEEKLY.values():
        for rec in recs:
            for w in rec.get("seasons", {}).get("2026", []):
                if w.get("tm"): team_wks[TEAMFIX.get(w["tm"], w["tm"])].add(int(w["wk"]))
    slot_acc = defaultdict(lambda: defaultdict(float)); slot_g = defaultdict(int); slot_n = defaultdict(int)
    for tm, byp in (depth.get("teams") or {}).items():
        for ps, lim in DEPTH_MAX.items():
            for i, nm in enumerate((byp.get(ps) or [])[:lim]):
                rows = [w for rec in cal.WEEKLY.get(cal.norm(nm), []) if rec.get("pos") == ps for w in rec.get("seasons", {}).get("2026", []) if TEAMFIX.get(w.get("tm"), w.get("tm")) == tm]
                if not rows: continue
                first = min(int(w["wk"]) for w in rows); tg_ = sum(1 for wk_ in team_wks[tm] if wk_ >= first)
                if tg_ <= 0: continue
                slot_g[(ps, i)] += tg_; slot_n[(ps, i)] += 1
                for w in rows:
                    if ps == "QB" and i >= 1 and float(w.get("pa") or 0) >= QB_START_PA: continue   # backup QB line = RELIEF only: fill-in starts come from the injury layer's inheritance, counting them double-pays
                    for st in STATS: slot_acc[(ps, i)][st] += float(w.get(st) or 0)
    slot_pg = {k: {st: max(0.0, slot_acc[k][st] / slot_g[k]) for st in STATS} for k in slot_g}   # floored: QB3 kneel-downs ran rushing yards negative
    # MONOTONE: a deeper string never out-projects the one above it (QB3 = only the 4 who got on the field: 4.1 vs QB2 1.7)
    ppr = lambda v: 0.04 * v["py"] + 4 * v["ptd"] - 2 * v["int"] + 0.1 * (v["ry"] + v["rcy"]) + 6 * (v["rtd"] + v["rctd"]) + v["rec"]
    for ps in DEPTH_MAX:
        for i in range(1, DEPTH_MAX[ps]):
            up, k = (ps, i - 1), (ps, i)
            if k in slot_pg and up in slot_pg and ppr(slot_pg[k]) > ppr(slot_pg[up]): slot_pg[k] = dict(slot_pg[up])
    # league-wide spelling match (mirrors engine CHART TEAMS): a chart name with no sheet match on its own team is the sheet player
    # with the same pos + last name + first initial when exactly one such sheet player is on NO chart (moved + respelled)
    on_chart = {cal.norm(n) for byp in (depth.get("teams") or {}).values() for lst in byp.values() for n in lst}
    lf_free = defaultdict(list)
    for nm, r in clay.items():
        k = cal.norm(nm); parts = k.split()
        if len(parts) >= 2 and k not in on_chart: lf_free[(r.get("pos"), parts[-1], parts[0][0])].append(nm)
    def sheet_alias(k, ps):
        parts = k.split()
        return len(parts) >= 2 and len(lf_free.get((ps, parts[-1], parts[0][0]), [])) == 1
    out = {}; skipped = []
    for tm, byp in sorted((depth.get("teams") or {}).items()):
        for ps, lim in DEPTH_MAX.items():
            for i, nm in enumerate((byp.get(ps) or [])[:lim]):
                k = cal.norm(nm); parts = k.split()
                if k in have or (parts and (ps, tm, parts[-1]) in have_last) or sheet_alias(k, ps): continue
                acc = defaultdict(float); gms = 0
                for rec in cal.WEEKLY.get(k, []):
                    if rec.get("pos") != ps: continue
                    for yy in ("2024", "2025", "2026"):
                        for w in rec.get("seasons", {}).get(yy, []):
                            if not cal.played(w): continue
                            gms += 1
                            for st in STATS: acc[st] += float(w.get(st) or 0)
                if gms >= MIN_G and not (ps == "QB" and QB_SLOT_ONLY):
                    pg = {st: acc[st] / gms for st in STATS}; src = f"depth {ps}{i+1}, own {gms} g 2024-26"
                elif (ps, i) in slot_pg:
                    pg = slot_pg[(ps, i)]; src = f"depth {ps}{i+1}, slot prior ({slot_n[(ps, i)]} players, {slot_g[(ps, i)]} team g)"
                else:
                    skipped.append(f"{nm} {tm} {ps}{i+1} ({gms} g, no slot prior)"); continue
                row = {"pos": ps, "tm": tm, "gm": 17}
                for st, key in (("py", "py"), ("ptd", "ptd"), ("ry", "ry"), ("rtd", "rtd"), ("rec", "rec"), ("rcy", "rcy"), ("rctd", "rctd")):
                    v = round(pg[st] * 17, 1 if st.endswith("td") else 0)
                    if v: row[key] = v
                row["rec"] = row.get("rec", 0)
                # Clay's pts = standard scoring + receptions (full PPR), the sheet's convention
                row["pts"] = max(0, round(0.04 * row.get("py", 0) + 4 * row.get("ptd", 0) - 2 * round(pg["int"] * 17, 1) + 0.1 * row.get("ry", 0) + 6 * row.get("rtd", 0) + 0.1 * row.get("rcy", 0) + 6 * row.get("rctd", 0) + row["rec"]))
                row["src"] = src
                out[nm] = row
    for tm, byp in sorted((depth.get("teams") or {}).items()):
        for i, nm in enumerate((byp.get("K") or [])[:K_MAX]):
            k = cal.norm(nm); parts = k.split()
            if k in have or (parts and ("K", tm, parts[-1]) in have_last): continue
            out[nm] = {"pos": "K", "tm": tm, "gm": 17, "rec": 0, "pts": 0, "src": f"depth K{i+1}, team Vegas kicker line"}
    print("slot priors (PPR per team game): " + ", ".join(f"{ps}{i+1} {0.1*v['ry']+6*v['rtd']+0.1*v['rcy']+6*v['rctd']+v['rec']+0.04*v['py']+4*v['ptd']-2*v['int']:.1f} (n{slot_n[(ps, i)]})" for (ps, i), v in sorted(slot_pg.items())))
    print(f"depth-chart pool: {len(out)} extras not on Clay's sheet (QB top {DEPTH_MAX['QB']} on the slot line, RB top {DEPTH_MAX['RB']}, WR top {DEPTH_MAX['WR']}, TE top {DEPTH_MAX['TE']}; own line with >= {MIN_G} games, else slot prior)")
    for nm, r in out.items(): print(f"  {r['tm']:3s} {nm:26s} {r['src']:48s} season-line PPR {r['pts']:4d}  ({r['pts']/17:.1f}/g)" if r["pos"] != "K" else f"  {r['tm']:3s} {nm:26s} {r['src']}")
    print(f"skipped (no history): {len(skipped)}: " + "; ".join(skipped))
    if dry: return
    with open(os.path.join(HERE, "data", "sim_depth_pool.js"), "w", encoding="utf-8") as f:
        f.write(f"// AUTO-GENERATED by build_depth_pool.py {time.strftime('%Y-%m-%d %H:%M')} - depth-chart players not on Clay's sheet, season line from their own 2024-26 games\n")
        f.write("window.SIM_DEPTH_POOL = " + json.dumps(out, separators=(",", ":")) + ";\n")
    print("wrote data/sim_depth_pool.js")


if __name__ == "__main__":
    main()
