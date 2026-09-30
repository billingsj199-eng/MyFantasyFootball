#!/usr/bin/env python3
"""2026 pass for research_early_season_types.py: who fits the historical early-season types after 3 games,
plus a one-week check (features from weeks 1-2 -> week 3 result vs the locked projection)."""
import json, os, re, sys, numpy as np, pandas as pd
from score_week import norm
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"
def js(path, var=None):
    raw = open(path, encoding="utf-8", errors="replace").read()
    i = raw.index("window." + var) if var else (raw.index("window.") if "window." in raw[:2000] else 0)
    return json.JSONDecoder().raw_decode(raw[raw.index("{", i):])[0]
stats = js(os.path.join(REPO, "data", "weekly_stats_active.js"))
xfp = js(os.path.join(HERE, "data", "sim_routes.js"), "SIM_XFP_2026")
snaps = {norm(k): v for k, v in js(os.path.join(HERE, "data", "sim_snaps.js")).items()}
slp = {norm(p["n"]): p for p in js(os.path.join(HERE, "data", "sleeper_players.js"))["players"]}
proj = json.load(open(os.path.join(REPO, "data", "sim_proj_2026.json")))
def xf(a): return 0.5 * a[1] + 0.1 * a[2] + 6 * a[3] + 0.1 * a[5] + 6 * a[6]
def played(w): return (w.get("fpts") or 0) != 0 or (w.get("ra") or 0) > 0 or (w.get("tgt") or 0) > 0 or (w.get("pa") or 0) > 0
rows = []
for name, rec in stats.items():
    pos = rec.get("pos"); nk = norm(name)
    if pos not in ("RB", "WR", "TE"): continue
    ws = sorted([w for w in (rec.get("seasons") or {}).get("2026") or [] if played(w) and w["wk"] <= 3], key=lambda w: w["wk"])
    s = slp.get(nk)
    if len(ws) < 2 or not s or not s.get("cPts"): continue
    clay = max(0.2, s["cPts"] - (s.get("cRec") or 0) / 2) / 17
    x = (xfp.get(nk) or {}).get("w") or {}
    def feat(ww):
        pts = sum(w["fpts"] for w in ww); g = len(ww)
        td = sum((w.get("rtd") or 0) + (w.get("rctd") or 0) for w in ww)
        xs = [xf(x[str(w["wk"])]) for w in ww if str(w["wk"]) in x]
        return dict(g=g, ppg=pts / g, td=td, tdsh=(6 * td / pts) if pts > 3 else None, xfp=(np.mean(xs) if len(xs) == g else None),
                    tgt=sum(w.get("tgt") or 0 for w in ww) / g, ra=sum(w.get("ra") or 0 for w in ww) / g)
    f = feat(ws); sw = (snaps.get(nk) or {}).get("w") or {}
    sn = [sw[str(w["wk"])] for w in ws if str(w["wk"]) in sw]
    w4 = (proj["weeks"].get("4") or {}).get(name)
    r = dict(name=name, pos=pos, tm=ws[-1].get("tm"), clay=clay, snap=(np.mean(sn) if sn else None), wk4=(w4[0] if w4 else None), adp=s.get("a"), **f)
    r["fwd"] = (5 * clay + f["g"] * f["ppg"]) / (5 + f["g"]); r["gap"] = (f["xfp"] - f["ppg"]) if f["xfp"] is not None else None
    r["start"] = f["ppg"] / max(clay, 1)
    e = [w for w in ws if w["wk"] <= 2]; w3 = [w for w in ws if w["wk"] == 3]
    if len(e) == 2 and w3:
        fe = feat(e); r.update(e_tdsh=fe["tdsh"], e_td=fe["td"], e_gap=(fe["xfp"] - fe["ppg"]) if fe["xfp"] is not None else None, e_ppg=fe["ppg"], w3=w3[0]["fpts"])
    rows.append(r)
d = pd.DataFrame(rows)
snap3 = {norm(p["name"]): p for p in json.load(open(os.path.join(HERE, "data", "snapshots", "simlab_snapshot_w3.json"), encoding="utf-8"))["players"]}
d["w3proj"] = [ (snap3.get(norm(n)) or {}).get("mean") for n in d.name]
print("=== A. did the historical patterns show up in 2026 week 3? (features from weeks 1-2, week-3 points vs our locked week-3 projection, proj >= 5) ===")
c = d[d.w3.notna() & d.w3proj.notna() & (d.w3proj >= 5)]
def ln(lab, x):
    if len(x) < 6: print(f"  {lab:52s} n={len(x):3d} (too few)"); return
    print(f"  {lab:52s} n={len(x):3d}  week 3 actual/projected {x.w3.sum()/x.w3proj.sum():.2f}  avg {x.w3.mean():.1f} vs proj {x.w3proj.mean():.1f}  beat projection {100*(x.w3 > x.w3proj).mean():.0f}%")
ln("everyone", c)
for pos in ("RB", "WR", "TE"):
    p = c[c.pos == pos]
    ln(f"{pos} baseline", p)
    ln(f"{pos} no TDs in weeks 1-2", p[p.e_td == 0])
    ln(f"{pos} TDs 40%+ of his points in weeks 1-2", p[p.e_tdsh.fillna(0) >= .4])
    ln(f"{pos} points 3+ ABOVE his usage in weeks 1-2", p[p.e_gap.fillna(0) <= -3])
    ln(f"{pos} usage 3+ above his points in weeks 1-2", p[p.e_gap.fillna(0) >= 3])
t = d[(d.g == 3) | (d.g == 2)]
t = t[t.fwd >= 6]
def show(title, x, sort, asc=False, n=14):
    print(f"\n=== {title} ===")
    print(f"  {'player':24s} pos tm   gms  pts/g  usage-exp/g  TDs  TD share  snaps  preseason/g  forward  our wk4")
    for r in x.sort_values(sort, ascending=asc).head(n).itertuples():
        print(f"  {r.name:24s} {r.pos:3s} {str(r.tm):4s} {r.g:3d}  {r.ppg:5.1f}  {r.xfp if r.xfp is not None else float('nan'):10.1f}  {r.td:3d}  {100*(r.tdsh or 0):6.0f}%  {r.snap if r.snap is not None else float('nan'):5.0f}  {r.clay:10.1f}  {r.fwd:7.1f}  {r.wk4 if r.wk4 is not None else float('nan'):7.1f}")
show("B. REGRESSION type 1: receivers whose start is 40%+ touchdowns (history: rest of season 87% of projection, 44% finish under 80%)",
     t[(t.pos == "WR") & (t.tdsh.fillna(0) >= .40)], "ppg")
show("B2. REGRESSION type 2: receivers scoring 3+ a game ABOVE what their usage is worth (history: 94%, 2 of 7 seasons above)",
     t[(t.pos == "WR") & (t.gap.fillna(0) <= -3)], "gap", asc=True)
show("B3. same two flags, tight ends and running backs (history: weaker / too few, watch list only)",
     t[(t.pos != "WR") & ((t.tdsh.fillna(0) >= .40) | (t.gap.fillna(0) <= -3))], "gap", asc=True)
show("C. BOUNCE-BACK type 1: tight ends with no touchdown yet (history: 125% of projection, 6 of 6 seasons, 56% beat it by 20%+)",
     t[(t.pos == "TE") & (t.td == 0)], "fwd")
show("C2. BOUNCE-BACK type 2: running backs with no touchdown yet (history: 121%, 5 of 5 seasons)",
     t[(t.pos == "RB") & (t.td == 0)], "fwd")
show("C3. BOUNCE-BACK type 3: receivers with no touchdown and usage worth more than their points (history: 107% / 108%)",
     t[(t.pos == "WR") & (t.td == 0) & (t.gap.fillna(0) >= 1)], "gap")
show("D. UPSIDE type: running backs under 50% of snaps (history: 113%, 7 of 7 seasons; 41% beat it by 20%+, 30% finish under 80%)",
     t[(t.pos == "RB") & (t.snap.fillna(100) < 50)], "fwd")
d.to_pickle(os.path.join(HERE, "data", "early_types_2026.pkl"))
