#!/usr/bin/env python3
"""
BUILD THE 2026 CLAY-FREE POOL (2026-09-16).

Applies the pool rule from backtest_pool_definition.py to the live Clay-free sources and diffs it against Clay's
current sheet (the engine's pool today). Nothing in the engine changes: this is the membership list a Clay-free
engine would project, with each member's provenance and a history-based per-game stat mix (the comps a Clay-free
engine needs to turn a half-PPR prior into a stat line).
  ADP      site consensus ADP (data/sleeper_players.js `a`) <= ADP_MAX
  CHART    ESPN depth chart (data/sim_depth.js) string <= 2 (index / slots + 1; WR 3 slots)
  HIST     player_weekly_sigma: >= 8 games and mean_ppg >= 4 half-PPR
  ROOKIE   sleeper_meta dp (draft pick, this season) <= 135 (rounds 1-4)
Members are keyed by norm name; positions QB/RB/WR/TE (K/DST stay engine-synthesized: DST from Vegas, K = open).
Stat mix = per-game rates over the player's last two seasons in the site's weekly DB (pa/py/ptd/int/ra/ry/rtd/
tgt/rec/rcy/rctd), position mean for anyone without games.
Writes data/noclay_pool_2026.js (SIM_NOCLAY_POOL) and prints the Clay diff.
"""
import json, os, re, sys, time
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_sim_calibration as cal

ADP_MAX, ROOKIE_PICK_MAX = 250, 135
POS4 = ("QB", "RB", "WR", "TE"); SLOTS = {"QB": 1, "RB": 1, "WR": 3, "TE": 1}
STATS = ("pa", "pc", "py", "ptd", "int", "ra", "ry", "rtd", "tgt", "rec", "rcy", "rctd", "fl")


def js_var(path, var):
    """evaluate a Sim Lab data file under node's window shim and return the named global as Python (dump_js_var.js)."""
    import subprocess
    out = subprocess.run(["node", os.path.join(HERE, "dump_js_var.js"), path, var], capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return json.loads(out)


def main():
    t0 = time.time()
    sp = js_var(os.path.join(HERE, "data", "sleeper_players.js"), "SIM_SLEEPER")
    players = sp["players"] if isinstance(sp, dict) else sp
    depth = js_var(os.path.join(HERE, "data", "sim_depth.js"), "SIM_DEPTH_2026")
    sig = js_var(os.path.join(HERE, "data", "player_weekly_sigma.js"), "PLAYER_WEEKLY_SIGMA")
    meta = js_var(os.path.join(HERE, "data", "sleeper_meta.js"), "SIM_SLEEPER_META")
    clay = js_var(os.path.join(HERE, "data", "mike_clay_projections.js"), "MIKE_CLAY_PROJ")
    clay_pool = {}
    for nm, r in clay.items():
        if isinstance(r, dict) and r.get("pos") in POS4: clay_pool[(cal.norm(nm), r["pos"])] = {"tm": r.get("tm"), "pts": r.get("pts")}
    # sources
    by_norm = {}
    for p in players:
        if p.get("s") not in POS4: continue
        k = (cal.norm(p["n"]), p["s"]); by_norm[k] = p
    chart = {}
    for tm, byp in (depth.get("teams") or {}).items():
        for ps, lst in byp.items():
            if ps not in POS4: continue
            for i, nm in enumerate(lst or []): chart.setdefault((cal.norm(nm), ps), (tm, i // SLOTS[ps] + 1))
    sig_by = {cal.norm(n): v for n, v in sig.items()} if isinstance(sig, dict) else {}
    members = {}
    def add(k, src, tm=None):
        m = members.setdefault(k, {"n": k[0], "pos": k[1], "tm": tm, "src": []}); m["src"].append(src)
        if tm and not m["tm"]: m["tm"] = tm
    for k, p in by_norm.items():
        a = p.get("a")
        if isinstance(a, (int, float)) and a <= ADP_MAX: add(k, "adp", p.get("sTm"))
        mt = meta.get(str(p.get("sid"))) if p.get("sid") else None
        if mt and mt.get("dy") == 2026 and isinstance(mt.get("dp"), (int, float)) and mt["dp"] <= ROOKIE_PICK_MAX: add(k, "rookie", p.get("sTm"))
        sg = sig_by.get(k[0])
        if sg and (sg.get("games") or 0) >= 8 and (sg.get("mean_ppg") or 0) >= 4: add(k, "hist", p.get("sTm"))
    for k, (tm, s) in chart.items():
        if s <= 2: add(k, "chart", tm)
    # history-only players not in the site universe (sigma file has them) - add by name if hist qualifies
    for nk, sg in sig_by.items():
        if (sg.get("games") or 0) >= 8 and (sg.get("mean_ppg") or 0) >= 4:
            ps = sg.get("pos")
            if ps in POS4 and (nk, ps) not in members: add((nk, ps), "hist")
    # ROSTER GATE: a member needs a current team (Sleeper sTm or the chart) - history alone keeps retired / unsigned players
    for k in list(members):
        if not members[k].get("tm"): members[k]["dropped"] = "no team"; del members[k]
    # stat mix from the weekly DB (last two seasons)
    pos_acc = defaultdict(lambda: defaultdict(float)); pos_g = defaultdict(int)
    for k, m in members.items():
        acc = defaultdict(float); gms = 0
        for rec in cal.WEEKLY.get(k[0], []):
            if rec.get("pos") != k[1]: continue
            for yy in ("2024", "2025", "2026"):
                for w in rec.get("seasons", {}).get(yy, []):
                    if not cal.played(w): continue
                    gms += 1
                    for st in STATS: acc[st] += float(w.get(st) or 0)
        if gms >= 4:
            m["mix"] = {st: round(acc[st] / gms, 3) for st in STATS if acc[st]}; m["mixG"] = gms
            for st in STATS: pos_acc[k[1]][st] += acc[st]
            pos_g[k[1]] += gms
    pos_mix = {ps: {st: round(pos_acc[ps][st] / pos_g[ps], 3) for st in STATS if pos_acc[ps][st]} for ps in POS4 if pos_g[ps]}
    for m in members.values():
        if "mix" not in m: m["mix"] = pos_mix.get(m["pos"], {}); m["mixG"] = 0; m["mixSrc"] = "pos-mean"
    # diff vs Clay - alias-aware (Clay: Ken Walker III / Cameron Ward / Chigoziem Okonkwo vs Sleeper: Kenneth Walker / Cam Ward / Chig):
    # exact norm first, then same position + same last name + shared 3-letter first-name prefix or a unique last name
    def alias_key(k):
        parts = k[0].split(); return (k[1], parts[-1] if parts else k[0], (parts[0][:3] if parts else ""))
    mem_alias = defaultdict(list)
    for k in members: mem_alias[alias_key(k)[:2]].append(k)
    clay_to_mem = {}
    for k in clay_pool:
        if k in members: clay_to_mem[k] = k; continue
        cands = mem_alias.get(alias_key(k)[:2], [])
        pref = [c for c in cands if alias_key(c)[2] == alias_key(k)[2] or alias_key(c)[2][:1] == alias_key(k)[2][:1]]
        if len(pref) == 1: clay_to_mem[k] = pref[0]
        elif len(cands) == 1: clay_to_mem[k] = cands[0]
    matched = set(clay_to_mem.values())
    both = [k for k in members if k in matched]; pool_only = [k for k in members if k not in matched]; clay_only = [k for k in clay_pool if k not in clay_to_mem]
    out = {"updated": time.strftime("%Y-%m-%d %H:%M"), "rule": {"adpMax": ADP_MAX, "chartString": 2, "hist": ">=8 games & >=4 half-PPR PPG", "rookiePickMax": ROOKIE_PICK_MAX},
           "members": sorted(members.values(), key=lambda m: (m["pos"], m["n"])), "posMix": pos_mix,
           "counts": {"members": len(members), "clay": len(clay_pool), "both": len(both), "poolOnly": len(pool_only), "clayOnly": len(clay_only),
                      "byPos": {ps: {"members": sum(1 for k in members if k[1] == ps), "clay": sum(1 for k in clay_pool if k[1] == ps)} for ps in POS4},
                      "bySrc": {s: sum(1 for m in members.values() if s in m["src"]) for s in ("adp", "chart", "hist", "rookie")}},
           "clayOnly": [{"n": k[0], "pos": k[1], "tm": clay_pool[k]["tm"], "pts": clay_pool[k]["pts"]} for k in sorted(clay_only, key=lambda k: -(clay_pool[k]["pts"] or 0))],
           "poolOnly": [{"n": k[0], "pos": k[1], "tm": members[k]["tm"], "src": members[k]["src"]} for k in sorted(pool_only)]}
    print(f"Clay-free pool 2026: {len(members)} members ({out['counts']['bySrc']}) vs Clay {len(clay_pool)} | both {len(both)} | pool-only {len(pool_only)} | Clay-only {len(clay_only)}")
    print("  by position: " + ", ".join(f"{ps} {out['counts']['byPos'][ps]['members']} vs Clay {out['counts']['byPos'][ps]['clay']}" for ps in POS4))
    print("  Clay-only (top by Clay pts): " + ", ".join(f"{c['n']} {c['pos']} {c['pts']}" for c in out["clayOnly"][:15]))
    print("  pool-only (sample): " + ", ".join(f"{c['n']} {c['pos']} {'/'.join(c['src'])}" for c in out["poolOnly"][:15]))
    print(f"  stat mix from history: {sum(1 for m in members.values() if m.get('mixG', 0) >= 4)} members, position mean for {sum(1 for m in members.values() if m.get('mixSrc') == 'pos-mean')}")
    with open(os.path.join(HERE, "data", "noclay_pool_2026.js"), "w", encoding="utf-8") as f:
        f.write("// AUTO-GENERATED by build_noclay_pool.py - the membership a Clay-free engine would project (research; engine still uses Clay's sheet)\n")
        f.write("window.SIM_NOCLAY_POOL = " + json.dumps(out, separators=(",", ":")) + ";\n")
    print(f"wrote data/noclay_pool_2026.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
