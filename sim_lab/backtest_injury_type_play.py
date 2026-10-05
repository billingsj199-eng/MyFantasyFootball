#!/usr/bin/env python3
"""
INJURY TYPE -> "does he play this week" (Jack 2026-10-01: "use historical data with what kind of injury they have
to predict ... if they will play that week ... favor more recent data").

The banged-up docks (backtest_banged_up.py) price a designation x latest practice by position. This asks what the
KIND of injury adds on top, and whether weighting recent seasons more changes the rates.

  rows      nflverse injuries x snap counts 2019-25, skill players averaging 40%+ of offensive snaps over 2+ prior
            games that season (the banged-up population), classes Q-FP / Q-LP / Q-DNP
  base      P(plays | class, position), shrunk K=50 to the class rate (the shipped form)
  type      logit shift per (class, injury group) vs the class rate, shrunk K_TYPE, added to the base in logit space
  recency   season weights 0.5 ** ((last train season - season) / half-life)
  grading   Brier on 'played', leave-one-season-out AND forward (train on earlier seasons only, test 2022-25)

Writes injury_type_play.log and data/injury_type_play.json (the table the engine reads as INJ_TYPE_SHIFT).
"""
import json, os, sys, math
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_common as B
POS4 = ("QB", "RB", "WR", "TE"); YEARS = list(range(2019, 2026)); CLASSES = ("Q-FP", "Q-LP", "Q-DNP")
K_POS, K_TYPE, MIN_N = 50, 40, 25

GROUPS = [("hamstring", ("hamstring",)), ("ankle", ("ankle",)), ("knee", ("knee", "acl", "mcl", "meniscus", "pcl")), ("concussion", ("concussion", "head")),
          ("shoulder", ("shoulder", "collarbone", "clavicle", "ac joint")), ("groin", ("groin", "abductor", "adductor")), ("calf", ("calf",)), ("achilles", ("achilles",)),
          ("foot", ("foot", "heel", "lisfranc")), ("toe", ("toe",)), ("back", ("back", "lumbar")), ("hip", ("hip",)), ("quad", ("quad", "thigh")),
          ("core", ("rib", "chest", "oblique", "abdomen", "core", "pectoral", "sternum", "abdominal")), ("hand", ("hand", "wrist", "finger", "thumb", "forearm", "elbow")),
          ("neck", ("neck", "stinger")), ("illness", ("illness", "covid")), ("rest", ("not injury related", "rest", "personal", "coach"))]
def grp(inj):
    s = str(inj or "").lower()
    if not s or s == "nan": return "unlisted"
    for g, keys in GROUPS:
        if any(k in s for k in keys): return g
    return "other"
def prac(s):
    s = str(s or "")
    return "DNP" if s.startswith("Did Not") else "LP" if s.startswith("Limited") else "FP" if s.startswith("Full") else ""
def cls(rs, pr):
    rs = str(rs or "")
    if rs == "Doubtful": return "D"
    if rs == "Out": return "Out"
    if rs == "Questionable": return {"DNP": "Q-DNP", "LP": "Q-LP"}.get(pr, "Q-FP")
    return {"DNP": "none-DNP", "LP": "none-LP"}.get(pr, "healthy")
logit = lambda p: math.log(min(.995, max(.005, p)) / (1 - min(.995, max(.005, p))))
sig = lambda z: 1 / (1 + math.exp(-z))

def load():
    rows = []
    for Y in YEARS:
        inj = pd.read_parquet(os.path.join(B.CACHE, f"injuries_{Y}.parquet"))
        inj = inj[(inj.game_type == "REG") & inj.position.isin(POS4)].drop_duplicates(["team", "week", "gsis_id"])
        sn = pd.read_parquet(os.path.join(B.CACHE, f"snap_counts_{Y}.parquet"), columns=["week", "game_type", "player", "position", "team", "offense_snaps", "offense_pct"])
        sn = sn[(sn.game_type == "REG") & sn.position.isin(POS4) & (sn.offense_snaps > 0)]
        hist = defaultdict(dict)
        for r in sn.itertuples(index=False): hist[B.cal.norm(str(r.player))][int(r.week)] = float(r.offense_pct)
        for r in inj.itertuples(index=False):
            c = cls(r.report_status, prac(r.practice_status))
            if c not in CLASSES: continue
            k = B.cal.norm(str(r.full_name)); W = int(r.week)
            prev = [p for w, p in hist.get(k, {}).items() if w < W]
            if len(prev) < 2 or np.mean(prev) < .40: continue
            pi = r.report_primary_injury if isinstance(r.report_primary_injury, str) else r.practice_primary_injury
            rows.append(dict(year=Y, pos=r.position, cls=c, g=grp(pi), played=int(W in hist.get(k, {}))))
    return pd.DataFrame(rows)

def fit(tr, half=None, use_type=True, ref=None):
    """returns predict(row) -> p. Weighted rates; position shrunk to class, type shift shrunk in logit space."""
    ref = ref if ref is not None else tr.year.max()
    w = np.ones(len(tr)) if not half else 0.5 ** ((ref - tr.year.values) / half)
    tr = tr.assign(w=w, wp=w * tr.played.values)
    cr = tr.groupby("cls")[["wp", "w"]].sum(); crate = (cr.wp / cr.w).to_dict()
    pr = tr.groupby(["cls", "pos"])[["wp", "w"]].sum()
    prate = {k: (v.wp + K_POS * crate[k[0]]) / (v.w + K_POS) for k, v in pr.iterrows()}
    shift = {}
    if use_type:
        gr = tr.groupby(["cls", "g"])[["wp", "w"]].sum(); cnt = tr.groupby(["cls", "g"]).size()
        for k, v in gr.iterrows():
            if cnt[k] < MIN_N: continue
            raw = (v.wp + K_TYPE * crate[k[0]]) / (v.w + K_TYPE)
            shift[k] = logit(raw) - logit(crate[k[0]])
    def pred(r):
        p = prate.get((r.cls, r.pos), crate.get(r.cls, .7))
        s = shift.get((r.cls, r.g), 0.0)
        return sig(logit(p) + s) if s else p
    return pred, crate, prate, shift

def grade(A, variants, folds):
    out = {name: defaultdict(list) for name in variants}
    for tr_years, te_year in folds:
        tr, te = A[A.year.isin(tr_years)], A[A.year == te_year]
        for name, kw in variants.items():
            pred = fit(tr, ref=max(tr_years) if kw.get("half") else None, **kw)[0]
            for r in te.itertuples(index=False):
                e = (pred(r) - r.played) ** 2
                out[name]["all"].append(e); out[name][r.cls].append(e); out[name][("yr", te_year)].append(e)
    return out

def main():
    log = open(os.path.join(HERE, "injury_type_play.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n")
    A = load()
    P(f"=== injury type -> plays this week: {len(A)} Questionable report rows (starters), 2019-25 ===")
    P("\n  play rate by season (is it drifting?):")
    for c in CLASSES:
        P(f"    {c:6s} " + "  ".join(f"{y}: {100*A[(A.cls==c)&(A.year==y)].played.mean():3.0f}% (n {((A.cls==c)&(A.year==y)).sum():3d})" for y in YEARS))
    P("    2019-22 vs 2023-25: " + "  ".join(f"{c} {100*A[(A.cls==c)&(A.year<=2022)].played.mean():.0f}% -> {100*A[(A.cls==c)&(A.year>=2023)].played.mean():.0f}%" for c in CLASSES))
    V = {"class x position (shipped form)": dict(use_type=False), "+ recency (half-life 3 seasons)": dict(use_type=False, half=3), "+ recency (half-life 2)": dict(use_type=False, half=2),
         "+ injury type": dict(use_type=True), "+ injury type + recency 3": dict(use_type=True, half=3), "+ injury type + recency 2": dict(use_type=True, half=2)}
    for title, folds in (("LEAVE-ONE-SEASON-OUT", [([y for y in YEARS if y != t], t) for t in YEARS]), ("FORWARD (train on earlier seasons only)", [([y for y in YEARS if y < t], t) for t in (2022, 2023, 2024, 2025)])):
        R = grade(A, V, folds); base = R["class x position (shipped form)"]
        P(f"\n  {title} - Brier on 'played' (lower = better)")
        for name in V:
            r = R[name]; yrs = [k for k in base if isinstance(k, tuple)]
            wins = sum(np.mean(r[k]) < np.mean(base[k]) for k in yrs)
            P(f"    {name:34s} all {np.mean(r['all']):.4f} ({100*(np.mean(r['all'])/np.mean(base['all'])-1):+.2f}%)  " + "  ".join(f"{c} {100*(np.mean(r[c])/np.mean(base[c])-1):+.2f}%" for c in CLASSES) + f"  seasons better {wins}/{len(yrs)}")
    # final table on all seasons, recency half-life chosen below
    HALF = 3
    pred, crate, prate, shift = fit(A, half=HALF, use_type=True, ref=2025)
    P(f"\n  SHIPPED TABLE (all seasons, half-life {HALF}): logit shift by class x injury group (n >= {MIN_N}, shrunk K={K_TYPE}); play rate at the class average shown")
    table = {}
    for c in CLASSES:
        P(f"    {c} (class {100*crate[c]:.0f}%):")
        for (cc, g), s in sorted(shift.items(), key=lambda kv: -kv[1]):
            if cc != c: continue
            n = ((A.cls == c) & (A.g == g)).sum(); raw = A[(A.cls == c) & (A.g == g)].played.mean()
            flag = "" if abs(s) >= 0.15 else "  (inside the noise, dropped)"
            P(f"      {g:11s} shift {s:+.2f}  -> {100*sig(logit(crate[c])+s):3.0f}%   raw {100*raw:3.0f}%  n {n}{flag}")
            if abs(s) >= 0.15: table.setdefault(c, {})[g] = round(s, 2)
    P("\n  recency-weighted play rate by class x position (shrunk K=50) - replaces the BANGED play column:")
    play = {}
    for c in CLASSES:
        play[c] = {pos: round(prate.get((c, pos), crate[c]), 3) for pos in POS4}
        P(f"    {c:6s} " + "  ".join(f"{pos} {play[c][pos]:.3f}" for pos in POS4) + f"   (unweighted class {A[A.cls==c].played.mean():.3f})")
    json.dump({"asOf": "2026-10-01", "half": HALF, "k": K_TYPE, "classRate": {c: round(crate[c], 3) for c in CLASSES}, "play": play, "shift": table}, open(os.path.join(HERE, "data", "injury_type_play.json"), "w"), indent=1)
    P("\n  -> data/injury_type_play.json")
    log.close()

if __name__ == "__main__":
    main()
