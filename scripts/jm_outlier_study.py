"""jm_outlier_study.py - what do high-pick busts and low-pick hits have in common?

Groups (settled classes only, four or more NFL seasons played out):
  early bust     pick <= 50, career grade < 20          vs  early success  pick <= 50, career >= 50
  late hit       pick >= 90, career grade >= 40         vs  late miss      pick >= 90, career < 10

For each comparison: how the NFL careers differ (health, snap share, when the role came,
alignment, teammates at the position, quarterback) and which COLLEGE inputs separate the
groups (AUC: 0.5 = no separation, 1.0 = every player in the first group is higher).

    python scripts/jm_outlier_study.py --table scripts/jm_study_table.json [--out file.json]
"""
import argparse
import json
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
POS = ["QB", "RB", "WR", "TE"]
NFL = [("n_avail3", "share of games played, yrs 1-3"), ("n_out3", "weeks listed out, yrs 1-3"), ("n_snap1", "snap share, rookie year"),
       ("n_snapMax3", "best snap share, yrs 1-3"), ("n_first50", "first season with a 50% snap share"), ("n_pff3", "PFF grade, yrs 1-3"),
       ("n_slot3", "NFL slot rate"), ("slotShift", "NFL slot rate minus college slot rate"), ("n_matePrior", "best returning player at his position when drafted"),
       ("n_mateMax1", "best teammate at his position, rookie year"), ("n_mateMax3", "best teammate at his position, yrs 1-3"),
       ("n_qb3", "quarterback quality, yrs 1-3"), ("n_teams4", "teams in first four seasons")]
COLLEGE = ["age", "breakoutAge", "bestPpg", "fptsPerGame", "totFpts", "gp", "numSeasons", "tdPg", "recPg", "ypc", "ypr", "mktShare", "domRate",
           "improvSlope", "pffGrade", "pffRush", "ras", "htIn", "wt", "t_forty", "t_vert", "t_broad", "t_bench", "t_cone", "t_shuttle", "speedScore",
           "schoolDraftCount", "tm", "tmCompShare", "confScore", "k_adot", "k_slotRate", "k_wideRate", "k_inlineRate", "k_yprr", "k_contestedRate",
           "k_dropRate", "k_yacPerRec", "qbRushFppg", "qbCompPct", "qbIntRate", "teRecPg"]
NICE = {"age": "draft age", "breakoutAge": "breakout age", "bestPpg": "best-season points per game", "fptsPerGame": "career points per game", "totFpts": "career fantasy points",
        "gp": "college games played", "numSeasons": "college seasons", "tdPg": "touchdowns per game", "recPg": "receptions per game", "ypc": "yards per carry", "ypr": "yards per reception",
        "mktShare": "share of team yards", "domRate": "dominator rating", "improvSlope": "year-over-year improvement", "pffGrade": "PFF grade", "pffRush": "PFF rushing grade", "ras": "RAS",
        "htIn": "height", "wt": "weight", "t_forty": "forty time", "t_vert": "vertical", "t_broad": "broad jump", "t_bench": "bench", "t_cone": "three-cone", "t_shuttle": "shuttle",
        "speedScore": "speed score", "schoolDraftCount": "school's recent draft picks", "tm": "quality of college teammates", "tmCompShare": "share of touches vs teammates",
        "confScore": "conference strength", "k_adot": "depth of target", "k_slotRate": "college slot rate", "k_wideRate": "college wide rate", "k_inlineRate": "college inline rate",
        "k_yprr": "yards per route run", "k_contestedRate": "contested catch rate", "k_dropRate": "drop rate", "k_yacPerRec": "yards after catch per reception",
        "qbRushFppg": "QB rushing points per game", "qbCompPct": "completion percentage", "qbIntRate": "interception rate", "teRecPg": "TE receptions per game"}


def load(path):
    d = pd.DataFrame(json.load(open(path, encoding="utf-8"))["rows"])
    d = d[d.career.notna()].reset_index(drop=True)
    d["pickn"] = pd.to_numeric(d.o_pick, errors="coerce").fillna(280)
    m = d.ht.astype(str).str.extract(r"(\d)-(\d{1,2})")
    d["htIn"] = pd.to_numeric(m[0], errors="coerce") * 12 + pd.to_numeric(m[1], errors="coerce")
    for c in COLLEGE + [k for k, _ in NFL if k != "slotShift"]:
        if c in d:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d["speedScore"] = d.wt * 200 / d.t_forty ** 4
    d["confScore"] = pd.to_numeric(d.get("c_conf"), errors="coerce")
    d["slotShift"] = d.n_slot3 - d.k_slotRate
    return d


def auc(a, b):
    a, b = a.dropna(), b.dropna()
    if len(a) < 5 or len(b) < 5:
        return None
    r = pd.concat([a, b]).rank()
    return float((r.iloc[:len(a)].sum() - len(a) * (len(a) + 1) / 2) / (len(a) * len(b)))


def compare(A, B, cols, labels, min_gap=0.0):
    out = []
    for c in cols:
        if c not in A:
            continue
        v = auc(A[c], B[c])
        if v is None or abs(v - 0.5) < min_gap:
            continue
        out.append((abs(v - 0.5), c, labels.get(c, c), v, A[c].mean(), B[c].mean(), int(A[c].notna().sum()), int(B[c].notna().sum())))
    out.sort(reverse=True)
    return out


def bust_reason(r):
    if r.n_avail3 == r.n_avail3 and r.n_avail3 < 0.6:
        return "hurt or unavailable"
    if r.n_snapMax3 == r.n_snapMax3 and r.n_snapMax3 < 0.5:
        return "never won a role"
    return "had the role, did not produce"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="scripts/jm_study_table.json")
    ap.add_argument("--out")
    a = ap.parse_args()
    d = load(a.table)
    s = d[d.o_yr <= 2022].copy()
    eb = s[(s.pickn <= 50) & (s.career < 20)]; es = s[(s.pickn <= 50) & (s.career >= 50)]
    lh = s[(s.pickn >= 90) & (s.career >= 40)]; lm = s[(s.pickn >= 90) & (s.career < 10)]
    em = s[(s.pickn <= 50) & (s.career >= 20) & (s.career < 50)]
    print("settled classes 2017-2022: %d players | picks 1-50: %d (bust %d, middling %d, success %d) | picks 90+: %d (hit %d, miss %d)" % (
        len(s), (s.pickn <= 50).sum(), len(eb), len(em), len(es), (s.pickn >= 90).sum(), len(lh), len(lm)))
    for pos in POS:
        print("  %s: early bust %d, early success %d | late hit %d, late miss %d" % (pos, (eb.pos == pos).sum(), (es.pos == pos).sum(), (lh.pos == pos).sum(), (lm.pos == pos).sum()))
    res = {"groups": {}, "nfl": {}, "college": {}}

    nfl_labels = dict(NFL)
    print("\n=== NFL CAREERS: early busts vs early successes (all positions) ===")
    print("  %-52s %8s %9s %6s" % ("", "busts", "successes", "AUC"))
    rows = compare(eb, es, [k for k, _ in NFL], nfl_labels)
    res["nfl"]["early"] = rows
    for _, c, lab, v, ma, mb, na, nb in rows:
        print("  %-52s %8.2f %9.2f %6.2f   (n %d / %d)" % (lab, ma, mb, v, na, nb))
    eb = eb.assign(reason=eb.apply(bust_reason, axis=1))
    print("\n  why the early picks busted:")
    for reason, g in eb.groupby("reason"):
        print("    %-32s %2d  %s" % (reason, len(g), ", ".join("%s (%s #%d)" % (r["name"], r.pos, r.pickn) for _, r in g.sort_values("pickn").iterrows())))
    res["groups"]["early_bust"] = [dict(name=r["name"], pos=r.pos, yr=int(r.o_yr), pick=int(r.pickn), career=r.career, reason=r.reason, avail=r.n_avail3, snap=r.n_snapMax3,
                                        pff=r.n_pff3, mate=r.n_matePrior, qb=r.n_qb3, seasons=r.seasons) for _, r in eb.sort_values("pickn").iterrows()]

    print("\n=== NFL CAREERS: late hits vs late misses ===")
    print("  %-52s %8s %9s %6s" % ("", "hits", "misses", "AUC"))
    rows = compare(lh, lm, [k for k, _ in NFL], nfl_labels)
    res["nfl"]["late"] = rows
    for _, c, lab, v, ma, mb, na, nb in rows:
        print("  %-52s %8.2f %9.2f %6.2f   (n %d / %d)" % (lab, ma, mb, v, na, nb))
    print("\n  the late hits:")
    for _, r in lh.sort_values("career", ascending=False).iterrows():
        print("    %-22s %s %d #%-3d career %3.0f | role by year %s | rookie snap %s | room when drafted %s | QB %s | teams %s" % (
            r["name"], r.pos, r.o_yr, r.pickn, r.career, ("%d" % r.n_first50) if r.n_first50 == r.n_first50 else "-",
            ("%.0f%%" % (100 * r.n_snap1)) if r.n_snap1 == r.n_snap1 else "n/a", ("%.0f" % r.n_matePrior) if r.n_matePrior == r.n_matePrior else "n/a",
            ("%.0f" % r.n_qb3) if r.n_qb3 == r.n_qb3 else "n/a", ("%d" % r.n_teams4) if r.n_teams4 == r.n_teams4 else "-"))
    res["groups"]["late_hit"] = [dict(name=r["name"], pos=r.pos, yr=int(r.o_yr), pick=int(r.pickn), career=r.career, first50=r.n_first50, snap1=r.n_snap1, mate=r.n_matePrior,
                                      qb=r.n_qb3, seasons=r.seasons) for _, r in lh.sort_values("career", ascending=False).iterrows()]

    print("\n=== COLLEGE: what separates early busts from early successes ===")
    for pos in POS + ["ALL"]:
        A = eb if pos == "ALL" else eb[eb.pos == pos]; B = es if pos == "ALL" else es[es.pos == pos]
        if pos == "ALL":   # z-score within position first
            z = s.copy()
            for c in COLLEGE:
                if c in z:
                    z[c] = z.groupby("pos")[c].transform(lambda x: (x - x.mean()) / (x.std() or 1))
            A, B = z.loc[eb.index], z.loc[es.index]
        rows = compare(A, B, COLLEGE, NICE, min_gap=0.12)
        res["college"]["early_" + pos] = rows
        print("  %s (busts %d, successes %d): %s" % (pos, len(A), len(B), "; ".join("%s %.2f" % (lab, v) for _, c, lab, v, *_ in rows[:9]) or "nothing separates them"))
    print("\n=== COLLEGE: what separates late hits from late misses ===")
    for pos in ["RB", "WR", "TE", "ALL"]:
        A = lh if pos == "ALL" else lh[lh.pos == pos]; B = lm if pos == "ALL" else lm[lm.pos == pos]
        if pos == "ALL":
            z = s.copy()
            for c in COLLEGE:
                if c in z:
                    z[c] = z.groupby("pos")[c].transform(lambda x: (x - x.mean()) / (x.std() or 1))
            A, B = z.loc[lh.index], z.loc[lm.index]
        rows = compare(A, B, COLLEGE, NICE, min_gap=0.12)
        res["college"]["late_" + pos] = rows
        print("  %s (hits %d, misses %d): %s" % (pos, len(A), len(B), "; ".join("%s %.2f" % (lab, v) for _, c, lab, v, *_ in rows[:9]) or "nothing separates them"))
    res["counts"] = {"settled": len(s), "early": int((s.pickn <= 50).sum()), "early_bust": len(eb), "early_mid": len(em), "early_success": len(es),
                     "late": int((s.pickn >= 90).sum()), "late_hit": len(lh), "late_miss": len(lm)}
    if a.out:
        def clean(o):
            if isinstance(o, float) and not np.isfinite(o):
                return None
            if isinstance(o, (np.floating, np.integer)):
                return clean(float(o))
            if isinstance(o, dict):
                return {k: clean(v) for k, v in o.items()}
            if isinstance(o, (list, tuple)):
                return [clean(v) for v in o]
            return o
        json.dump(clean(res), open(a.out, "w", encoding="utf-8"), separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
