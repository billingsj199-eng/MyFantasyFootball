"""Which TYPES of players did the shipped sim miss on, W1-3 2026? (half-PPR, shipped mean >= 5)"""
import json, os, re, sys, math, statistics as st
from collections import defaultdict
SIM = r"E:\MyFantasyFootball\sim_lab"
REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"
sys.path.insert(0, SIM)
from score_week import norm

def js(path):
    raw = open(path, encoding="utf-8").read()
    i = raw.index("{", raw.index("=")) if "window." in raw[:400] or "=" in raw[:300] else raw.index("{")
    return json.JSONDecoder().raw_decode(raw[i:])[0]

stats = js(os.path.join(REPO, "data", "weekly_stats_active.js"))
act = defaultdict(dict); last_tm25 = {}
for name, rec in stats.items():
    for w in (rec.get("seasons") or {}).get("2026") or []:
        if isinstance(w.get("fpts"), (int, float)): act[w["wk"]][norm(name)] = w
    r25 = [w for w in (rec.get("seasons") or {}).get("2025") or [] if w.get("tm")]
    if r25: last_tm25[norm(name)] = r25[-1]["tm"]
snaps = {norm(k): v for k, v in js(os.path.join(SIM, "data", "sim_snaps.js")).items()}
meta = js(os.path.join(SIM, "data", "sleeper_meta.js"))
slp = {str(p.get("sid")): p for p in js(os.path.join(SIM, "data", "sleeper_players.js"))["players"]}
kick = json.load(open(os.path.join(SIM, "data", "kickoffs_2026.json")))
site = {}
for wk in (1, 2, 3):
    w = json.load(open(os.path.join(REPO, "accuracy", "data", f"w{wk}.json")))
    for n, p in w["players"].items():
        s = p.get("site")
        if s and p.get("act") is not None and all(x is not None for x in s[:4]):
            site[(wk, norm(n))] = sum(s[:4]) / 4 - p["act"]          # PPR site avg error

rows = []
for wk in (1, 2, 3):
    snap = json.load(open(os.path.join(SIM, "data", "snapshots", f"simlab_snapshot_w{wk}.json"), encoding="utf-8"))
    imp = {}
    for p in snap["players"]:
        if p.get("tm") and isinstance(p.get("implied"), (int, float)): imp[p["tm"]] = p["implied"]
    team = defaultdict(list)
    for p in snap["players"]:
        if p.get("pos") in ("QB", "RB", "WR", "TE"): team[(p["tm"], p["pos"])].append(p)
    for k in team: team[k].sort(key=lambda p: -(p.get("mean") or 0))
    for p in snap["players"]:
        if p.get("pos") not in ("QB", "RB", "WR", "TE") or (p.get("mean") or 0) < 5: continue
        a = act[wk].get(norm(p["name"]))
        if not a: continue
        nk = norm(p["name"]); c = p.get("comps") or {}; m = p["mean"]
        sw = (snaps.get(nk) or {}).get("w") or {}
        this = sw.get(str(wk)); others = [v for k, v in sw.items() if k != str(wk)]
        ref = max(others) if others else None
        lim = None
        if this is not None and ref: lim = this < 0.6 * ref
        elif this is None and sw: lim = True
        mt = meta.get(str(p.get("sid"))) or {}; sl = slp.get(str(p.get("sid"))) or {}
        ko = (kick.get(str(wk)) or {}).get(p["tm"], "")
        slot = "?"
        if ko:
            hh = int(ko[11:13]); dow = __import__("datetime").datetime.strptime(ko[:10], "%Y-%m-%d").weekday()
            slot = "primetime/standalone" if (hh in (0, 1) or dow in (3, 4, 5)) else "Sunday day"
        tdpts = 6 * ((c.get("rtd") or 0) + (c.get("rctd") or 0)) + 4 * (c.get("ptd") or 0)
        recpts = 0.5 * (c.get("rec") or 0) + 0.1 * (c.get("rcy") or 0) + 6 * (c.get("rctd") or 0)
        prev = None
        if wk > 1:
            pa = act[wk - 1].get(nk); pp = prevproj.get(nk)
            if pa and pp: prev = (pa["fpts"], pp)
        rows.append(dict(wk=wk, name=p["name"], pos=p["pos"], tm=p["tm"], proj=m, act=float(a["fpts"]), err=m - float(a["fpts"]),
                         js=p.get("jsMean"), p10=p.get("p10"), p90=p.get("p90"), implied=p.get("implied"),
                         spread=(p["implied"] - imp[p["opp"]]) if p.get("opp") in imp and isinstance(p.get("implied"), (int, float)) else None,
                         rank=team[(p["tm"], p["pos"])].index(p) + 1, lim=lim, snap=this, exp=mt.get("exp"), pick=mt.get("dp"),
                         age=sl.get("age"), adp=sl.get("a"), slot=slot, tdshare=tdpts / m, recshare=recpts / m, qbry=c.get("ry") or 0,
                         width=((p["p90"] - p["p10"]) / m) if p.get("p90") is not None else None, prev=prev,
                         newtm=(last_tm25.get(nk) != p["tm"]) if nk in last_tm25 else None,
                         site=site.get((wk, nk)), tgt=a.get("tgt"), ra=a.get("ra")))
    prevproj = {norm(p["name"]): p["mean"] for p in snap["players"] if (p.get("mean") or 0) > 0}
    if wk == 1: pass
# prevproj must exist before wk2 loop body uses it: rebuild prev in a second pass
proj_by = {(r["wk"], norm(r["name"])): r["proj"] for r in rows}
for r in rows:
    r["prev"] = None; r["dproj"] = None
    if r["wk"] > 1:
        pa = act[r["wk"] - 1].get(norm(r["name"])); pp = proj_by.get((r["wk"] - 1, norm(r["name"])))
        if pa and pp: r["prev"] = float(pa["fpts"]) / pp; r["dproj"] = r["proj"] - pp
        elif not pa and pp: r["prev"] = -1      # did not play last week

def line(label, rs, ind="  "):
    if len(rs) < 8:
        print(f"{ind}{label:34s} n={len(rs):3d}  (too few)"); return
    e = [r["err"] for r in rs]; b = st.mean(e); se = st.pstdev(e) / math.sqrt(len(e))
    h = [r["err"] for r in rs if r["lim"] is not True]
    hb = st.mean(h) if h else float("nan"); hse = (st.pstdev(h) / math.sqrt(len(h))) if len(h) > 1 else float("nan")
    ins = [r for r in rs if r["p10"] is not None]
    lo = sum(1 for r in ins if r["act"] < r["p10"]) / len(ins); hi = sum(1 for r in ins if r["act"] > r["p90"]) / len(ins)
    s = [r["site"] for r in rs if r["site"] is not None]
    flag = "  <<<" if abs(hb / hse) >= 2 else ""
    print(f"{ind}{label:34s} n={len(rs):3d}  bias {b:+5.2f} (t {b/se:+4.1f})  healthy-only {hb:+5.2f} (t {hb/hse:+4.1f}, n={len(h)})  "
          f"MAE {st.mean(abs(x) for x in e):5.2f}  act/proj {sum(r['act'] for r in rs)/sum(r['proj'] for r in rs):.2f}  "
          f"bust<p10 {lo:4.0%} boom>p90 {hi:4.0%}  sites bias {st.mean(s) if s else float('nan'):+5.2f}{flag}")

def cut(title, keyf, order=None, base=None):
    rs0 = base if base is not None else rows
    print(f"\n=== {title} ===")
    g = defaultdict(list)
    for r in rs0:
        k = keyf(r)
        if k is not None: g[k].append(r)
    for k in (order or sorted(g)):
        if k in g: line(str(k), g[k])

print(f"rows: {len(rows)} player-weeks (shipped mean >= 5 half-PPR, played). bias = proj - actual: POSITIVE = we were too HIGH.")
print("healthy-only drops weeks where the player's snap share was < 60% of his best other week (in-game exit / limited role).")
print("'<<<' = healthy-only bias at least 2 standard errors from zero.")
line("ALL", rows, "")
cut("0. availability that week", lambda r: {True: "limited/exited (<60% usual snaps)", False: "normal snaps", None: "no snap data"}[r["lim"]])
for pos in ("QB", "RB", "WR", "TE"):
    line(f"limited/exited {pos}", [r for r in rows if r["lim"] is True and r["pos"] == pos])
cut("1. position", lambda r: r["pos"], ["QB", "RB", "WR", "TE"])
cut("2. experience", lambda r: None if r["exp"] is None else ("a rookie" if r["exp"] == 0 else "b 2nd year" if r["exp"] == 1 else "c 3rd-4th year" if r["exp"] <= 3 else "d 5th-8th year" if r["exp"] <= 7 else "e 9+ years"))
for pos in ("QB", "RB", "WR", "TE"):
    cut(f"2b. experience, {pos}", lambda r: None if r["exp"] is None else ("rookie" if r["exp"] == 0 else "yr 2-3" if r["exp"] <= 2 else "yr 4-7" if r["exp"] <= 6 else "yr 8+"), ["rookie", "yr 2-3", "yr 4-7", "yr 8+"], [r for r in rows if r["pos"] == pos])
cut("3. age (RB)", lambda r: None if not r["age"] else ("<=23" if r["age"] <= 23 else "24-26" if r["age"] <= 26 else "27+"), ["<=23", "24-26", "27+"], [r for r in rows if r["pos"] == "RB"])
cut("3b. age (WR)", lambda r: None if not r["age"] else ("<=23" if r["age"] <= 23 else "24-27" if r["age"] <= 27 else "28+"), ["<=23", "24-27", "28+"], [r for r in rows if r["pos"] == "WR"])
cut("3c. age (TE)", lambda r: None if not r["age"] else ("<=24" if r["age"] <= 24 else "25-28" if r["age"] <= 28 else "29+"), ["<=24", "25-28", "29+"], [r for r in rows if r["pos"] == "TE"])
cut("3d. age (QB)", lambda r: None if not r["age"] else ("<=25" if r["age"] <= 25 else "26-31" if r["age"] <= 31 else "32+"), ["<=25", "26-31", "32+"], [r for r in rows if r["pos"] == "QB"])
cut("4. preseason ADP band", lambda r: "f undrafted/none" if not r["adp"] else ("a 1-30" if r["adp"] <= 30 else "b 31-60" if r["adp"] <= 60 else "c 61-100" if r["adp"] <= 100 else "d 101-150" if r["adp"] <= 150 else "e 151+"))
cut("5. role on own team (by our projection)", lambda r: None if r["pos"] == "QB" else f"{r['pos']}{min(r['rank'], 3)}{'+' if r['rank'] >= 3 else ''}",
    ["RB1", "RB2", "RB3+", "WR1", "WR2", "WR3+", "TE1", "TE2"])
cut("6. team implied total", lambda r: None if r["implied"] is None else ("a under 20" if r["implied"] < 20 else "b 20-23.5" if r["implied"] < 23.5 else "c 23.5-26" if r["implied"] < 26 else "d 26+"))
cut("7. spread", lambda r: None if r["spread"] is None else ("a favored by 6+" if r["spread"] >= 6 else "b favored 2.5-6" if r["spread"] >= 2.5 else "c pick'em (within 2.5)" if r["spread"] > -2.5 else "d dog 2.5-6" if r["spread"] > -6 else "e dog by 6+"))
for pos in ("QB", "RB", "WR", "TE"):
    cut(f"7b. spread, {pos}", lambda r: None if r["spread"] is None else ("favored 3+" if r["spread"] >= 3 else "close" if r["spread"] > -3 else "dog 3+"), ["favored 3+", "close", "dog 3+"], [r for r in rows if r["pos"] == pos])
cut("8. TD dependence (share of projection from TDs), RB/WR/TE", lambda r: "a low (<22%)" if r["tdshare"] < .22 else "b mid" if r["tdshare"] < .30 else "c high (30%+)", None, [r for r in rows if r["pos"] != "QB"])
cut("9. RB type (share of projection from receiving)", lambda r: "a runner (<25% rec)" if r["recshare"] < .25 else "b mixed" if r["recshare"] < .40 else "c pass-catcher (40%+)", None, [r for r in rows if r["pos"] == "RB"])
cut("10. QB type (projected rush yards)", lambda r: "a pocket (<12)" if r["qbry"] < 12 else "b some (12-25)" if r["qbry"] < 25 else "c runner (25+)", None, [r for r in rows if r["pos"] == "QB"])
cut("11. what he did LAST week vs our projection (W2-3)", lambda r: None if r["prev"] is None else ("e did not play last week" if r["prev"] < 0 else "a busted (<50%)" if r["prev"] < .5 else "b under (50-90%)" if r["prev"] < .9 else "c on target" if r["prev"] < 1.25 else "d boomed (125%+)"))
cut("12. did our projection move from last week (W2-3)", lambda r: None if r["dproj"] is None else ("a cut 1.5+" if r["dproj"] <= -1.5 else "b steady" if r["dproj"] < 1.5 else "c raised 1.5+"))
cut("13. changed teams since 2025", lambda r: None if r["newtm"] is None else ("new team" if r["newtm"] else "same team"))
cut("14. game slot", lambda r: r["slot"])
cut("15. our range width (p90-p10)/mean", lambda r: None if r["width"] is None else ("a tight (<1.3)" if r["width"] < 1.3 else "b mid" if r["width"] < 1.8 else "c wide (1.8+)"))
cut("16. tier by our projection", lambda r: "a 5-8" if r["proj"] < 8 else "b 8-12" if r["proj"] < 12 else "c 12-16" if r["proj"] < 16 else "d 16+")
cut("17. by week", lambda r: f"W{r['wk']}")

print("\n=== teams: biggest healthy-only bias (all positions, n>=8) ===")
g = defaultdict(list)
for r in rows:
    if r["lim"] is not True: g[r["tm"]].append(r)
t = sorted(((st.mean(x["err"] for x in v), k, v) for k, v in g.items() if len(v) >= 8))
for b, k, v in t[:6] + t[-6:]:
    se = st.pstdev([x["err"] for x in v]) / math.sqrt(len(v))
    print(f"  {k:4s} n={len(v):2d} bias {b:+5.2f} (t {b/se:+4.1f})  act/proj {sum(x['act'] for x in v)/sum(x['proj'] for x in v):.2f}   avg implied {st.mean(x['implied'] for x in v):.1f}")
json.dump(rows, open(os.path.join(os.path.dirname(__file__), "segrows.json"), "w"))
