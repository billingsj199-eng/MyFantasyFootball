#!/usr/bin/env python3
"""
AVAILABILITY CURVE v2 (Jack 2026-10-01: "favor more recent data since players seem to come back earlier from major
injuries" + "use historical data with what kind of injury they have to predict the timeline").

Same absence states as backtest_avail_curve.py (starter by the preseason guide, missed k games so far), now with the
player's position, the injury on his report (nflverse injuries, the week he first sat or the report before it) and
the season kept, so the curve P(misses the next game | missed k) can be fit
  pooled               the shipped table
  + recency            season weights 0.5 ** (seasons back / half-life)
  + position           per-position rate at each k, shrunk to the pooled rate
  + injury type        per-injury-group rate at k = 1..3, shrunk, as a logit shift on the above
Graded FORWARD (train on earlier seasons, test 2022-25) and leave-one-season-out: Brier on 'plays the next game'
and on each of the next four games (the chain the engine uses). Log avail_recency.log; table -> data/avail_curve_v2.json
"""
import json, os, sys, math
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_sim_calibration as cal
from backtest_sim_calibration import played, weekly_rec, infer_team
import bt_common as B
from backtest_injury_type_play import grp
REPO = cal.REPO; KMAX = 8; YEARS = list(range(2019, 2026))
K_POS, K_GRP, MIN_GRP = 30, 30, 20
logit = lambda p: math.log(min(.98, max(.02, p)) / (1 - min(.98, max(.02, p))))
sig = lambda z: 1 / (1 + math.exp(-z))

def reports():
    rep = {}
    for Y in YEARS:
        d = pd.read_parquet(os.path.join(B.CACHE, f"injuries_{Y}.parquet"))
        d = d[d.game_type == "REG"]
        for r in d.itertuples(index=False):
            pi = r.report_primary_injury if isinstance(r.report_primary_injury, str) else r.practice_primary_injury
            rep[(Y, cal.norm(str(r.full_name)), int(r.week))] = grp(pi)
    return rep

def spells():
    ch = json.load(open(os.path.join(REPO, "data", "clay_history.json"), encoding="utf-8")); rep = reports()
    out = []
    for Y in YEARS:
        W = 16 if Y <= 2020 else 17
        for name, c in ch[str(Y)].items():
            pos = c.get("pos")
            if pos not in ("QB", "RB", "WR", "TE"): continue
            pg = max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2) / W
            if pg < 8: continue
            rec = weekly_rec(name, pos)
            if rec is None: continue
            team = infer_team(rec, Y)
            if not team: continue
            gw = sorted(int(w) for w in cal.SCHEDULES.get(Y, {}).get(team, {}) if 1 <= int(w) <= W + 1)
            pl = set(w["wk"] for w in rec.get("seasons", {}).get(str(Y), []) if played(w))
            seq = [w in pl for w in gw]; nm = cal.norm(name)
            seen = False; k = 0; g = "unlisted"; sid = 0
            for i, v in enumerate(seq):
                if v: seen = True; k = 0; continue
                if not seen: continue
                k += 1
                if k == 1:
                    sid += 1
                    g = rep.get((Y, nm, gw[i])) or (rep.get((Y, nm, gw[i - 1])) if i > 0 else None) or "unlisted"
                nxt = [seq[i + j] if i + j < len(seq) else None for j in range(1, 5)]
                out.append(dict(year=Y, pos=pos, k=min(k, KMAX), nxt=nxt, g=g, name=nm, sid=f"{Y}|{nm}|{sid}", wk=gw[i], pg=pg))
    return out

def fit(rows, half=None, ref=None, use_pos=False, use_grp=False):
    ref = ref if ref is not None else max(r["year"] for r in rows)
    wt = lambda r: 1.0 if not half else 0.5 ** ((ref - r["year"]) / half)
    n = defaultdict(float); m = defaultdict(float); np_ = defaultdict(float); mp = defaultdict(float); ng = defaultdict(float); mg = defaultdict(float); cg = defaultdict(int)
    for r in rows:
        if r["nxt"][0] is None: continue
        w = wt(r); miss = float(r["nxt"][0] is False); k = r["k"]
        n[k] += w; m[k] += w * miss
        np_[(k, r["pos"])] += w; mp[(k, r["pos"])] += w * miss
        kk = min(k, 3); ng[(kk, r["g"])] += w; mg[(kk, r["g"])] += w * miss; cg[(kk, r["g"])] += 1
    pooled = {k: (m[k] + 0.7 * 5) / (n[k] + 5) for k in range(1, KMAX + 1)}
    # the injury-type shift is measured against the pooled rate over the same k band (1, 2, 3+)
    band = {kk: (sum(m[k] for k in range(1, KMAX + 1) if min(k, 3) == kk) / max(1e-9, sum(n[k] for k in range(1, KMAX + 1) if min(k, 3) == kk))) for kk in (1, 2, 3)}
    def cont(k, pos, g):
        p = pooled[k]
        if use_pos and np_[(k, pos)] > 0: p = (mp[(k, pos)] + K_POS * p) / (np_[(k, pos)] + K_POS)
        if use_grp:
            kk = min(k, 3)
            if cg[(kk, g)] >= MIN_GRP:
                raw = (mg[(kk, g)] + K_GRP * band[kk]) / (ng[(kk, g)] + K_GRP)
                p = sig(logit(p) + logit(raw) - logit(band[kk]))
        return p
    return cont, pooled

def grade(S, variants, folds):
    res = {v: dict(b1=[], b4=[], yr=defaultdict(list)) for v in variants}
    for tr_years, te in folds:
        tr = [r for r in S if r["year"] in tr_years]; tt = [r for r in S if r["year"] == te]
        for v, kw in variants.items():
            cont = fit(tr, ref=max(tr_years) if kw.get("half") else None, **kw)[0]
            for r in tt:
                surv = 1.0
                for j in range(4):
                    surv *= cont(min(KMAX, r["k"] + j), r["pos"], r["g"])
                    a = r["nxt"][j]
                    if a is None: continue
                    e = ((1 - surv) - float(a)) ** 2
                    res[v]["b4"].append(e)
                    if j == 0: res[v]["b1"].append(e); res[v]["yr"][te].append(e)
    return res

def main():
    log = open(os.path.join(HERE, "avail_recency.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n")
    S = spells()
    P(f"=== availability curve v2: {len(S)} absence states, {len(set(r['sid'] for r in S))} absences, 2019-25 ===")
    P("\n  are players coming back sooner? P(misses the next game | missed k so far), by season:")
    for lab, f in (("missed 1", lambda r: r["k"] == 1), ("missed 2-3", lambda r: 2 <= r["k"] <= 3), ("missed 4+", lambda r: r["k"] >= 4)):
        parts = []
        for y in YEARS:
            x = [r for r in S if r["year"] == y and f(r) and r["nxt"][0] is not None]
            parts.append(f"{y}: {100*np.mean([r['nxt'][0] is False for r in x]):3.0f}% ({len(x)})" if x else f"{y}: -")
        e = [r for r in S if r["year"] <= 2022 and f(r) and r["nxt"][0] is not None]; l = [r for r in S if r["year"] >= 2023 and f(r) and r["nxt"][0] is not None]
        P(f"    {lab:10s} " + "  ".join(parts) + f"   | 2019-22 {100*np.mean([r['nxt'][0] is False for r in e]):.0f}% -> 2023-25 {100*np.mean([r['nxt'][0] is False for r in l]):.0f}%")
    # long absences: how long, by era (absences whose 4th missed game came with 4+ team games left)
    P("\n  absences that reached 4 missed games with 4+ games left in the season: share back within the next 4 games")
    for era, ys in (("2019-22", range(2019, 2023)), ("2023-25", range(2023, 2026))):
        x = [r for r in S if r["year"] in ys and r["k"] == 4 and all(a is not None for a in r["nxt"])]
        P(f"    {era}: n {len(x):3d}  back for game 5: {100*np.mean([r['nxt'][0] for r in x]):3.0f}%  back within 2: {100*np.mean([any(r['nxt'][:2]) for r in x]):3.0f}%  within 4: {100*np.mean([any(r['nxt']) for r in x]):3.0f}%")
    P("\n  by injury on the report, P(misses the next game) after 1 / 2 / 3+ missed (n >= 20):")
    for g in sorted(set(r["g"] for r in S)):
        parts = []
        for kk in (1, 2, 3):
            x = [r for r in S if r["g"] == g and min(r["k"], 3) == kk and r["nxt"][0] is not None]
            parts.append(f"{100*np.mean([r['nxt'][0] is False for r in x]):3.0f}% ({len(x):3d})" if len(x) >= 20 else "   -      ")
        if any("%" in p for p in parts): P(f"    {g:11s} " + "   ".join(parts))
    allk = []
    for kk in (1, 2, 3):
        x = [r for r in S if min(r["k"], 3) == kk and r["nxt"][0] is not None]; allk.append(f"{100*np.mean([r['nxt'][0] is False for r in x]):3.0f}% ({len(x):3d})")
    P(f"    {'ALL':11s} " + "   ".join(allk))
    V = {"pooled (shipped)": {}, "recency half-life 3": dict(half=3), "recency half-life 2": dict(half=2), "recency half-life 1": dict(half=1),
         "position": dict(use_pos=True), "injury type": dict(use_grp=True), "position + injury type": dict(use_pos=True, use_grp=True),
         "position + injury type + recency 3": dict(use_pos=True, use_grp=True, half=3), "position + injury type + recency 2": dict(use_pos=True, use_grp=True, half=2),
         "injury type + recency 3": dict(use_grp=True, half=3)}
    for title, folds in (("FORWARD (train on earlier seasons, test 2022-25)", [([y for y in YEARS if y < t], t) for t in (2022, 2023, 2024, 2025)]),
                         ("LEAVE-ONE-SEASON-OUT", [([y for y in YEARS if y != t], t) for t in YEARS])):
        R = grade(S, V, folds); b = R["pooled (shipped)"]
        P(f"\n  {title}: Brier, next game / next four games")
        for v in V:
            r = R[v]; wins = sum(np.mean(r["yr"][y]) < np.mean(b["yr"][y]) for y in b["yr"])
            P(f"    {v:38s} next {np.mean(r['b1']):.4f} ({100*(np.mean(r['b1'])/np.mean(b['b1'])-1):+.2f}%)   next four {np.mean(r['b4']):.4f} ({100*(np.mean(r['b4'])/np.mean(b['b4'])-1):+.2f}%)   seasons better {wins}/{len(b['yr'])}")
    # shipped table: position + injury type, all seasons, no recency (recency failed forward)
    cont, pooled = fit(S, use_pos=True, use_grp=True)
    pos_t = {pos: {k: round(fit(S, use_pos=True)[0](k, pos, "-"), 3) for k in range(1, KMAX + 1)} for pos in ("QB", "RB", "WR", "TE")}
    base = fit(S)[0]; shifts = {}
    P("\n  SHIPPED TABLE (all seasons): P(misses the next game | missed k)")
    P("    pooled   " + "  ".join(f"k{k} {pooled[k]:.2f}" for k in range(1, KMAX + 1)))
    for pos in pos_t: P(f"    {pos}       " + "  ".join(f"k{k} {pos_t[pos][k]:.2f}" for k in range(1, KMAX + 1)))
    P("    injury-type logit shift at k = 1 / 2 / 3+ (and the rate it gives at the pooled level):")
    gonly = fit(S, use_grp=True)[0]
    for g in sorted(set(r["g"] for r in S)):
        row = {}
        for kk, kref in ((1, 1), (2, 2), (3, 4)):
            s = logit(gonly(kref, "-", g)) - logit(base(kref, "-", g))
            if abs(s) >= 0.10: row[kk] = round(s, 2)
        if row:
            shifts[g] = row
            P(f"      {g:11s} " + "   ".join((f"k{kk}: {row[kk]:+.2f} -> {100*sig(logit(pooled[kref])+row[kk]):.0f}%" if kk in row else f"k{kk}:   -        ") for kk, kref in ((1, 1), (2, 2), (3, 4))))
    json.dump({"asOf": "2026-10-01", "cont": {str(k): round(v, 3) for k, v in pooled.items()}, "pos": {p: {str(k): v for k, v in t.items()} for p, t in pos_t.items()}, "grpShift": {g: {str(k): v for k, v in r.items()} for g, r in shifts.items()}},
              open(os.path.join(HERE, "data", "avail_curve_v2.json"), "w"), indent=1)
    P("\n  -> data/avail_curve_v2.json")
    log.close()
    return S

if __name__ == "__main__":
    main()
