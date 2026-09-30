"""jm_feature_discovery.py - candidate NEW inputs for the JM model, measured on the
2017-2024 backtest classes. First pass: teammate / situation features.

Input : a jm_optimize results JSON (rows = backtest players with jm, curveScore
        outcome `cs`, pick, draft year).
Data  : data/college_stats.js (+patches) season rows for every player the site
        knows (thousands of NFL draftees) -> team-season index; data/combine_data.js
        for each teammate's position and draft pick.

Features per backtest player (college seasons before the draft year):
  tm_skill_n      drafted QB/RB/WR/TE teammates who overlapped >= 1 season
  tm_skill_best   best (lowest) pick among them (300 = none)
  tm_ol_n         drafted offensive linemen who overlapped (line quality proxy)
  tm_ol_best      best pick among them
  qb_pick         (RB/WR/TE) best drafted-QB teammate pick in the player's best season
  qb_pff          that QB's PFF season grade map value (if any)
  wpn_n / wpn_best(QB) drafted WR/TE teammates in the best season, count / best pick
  comp_share      (WR/TE) player's receiving yards / (player + other drafted WR/TE)
                  in the best season; (RB) same with rushing yards vs other drafted RBs
  comp_yds        the other drafted teammates' yards in that season

Each feature is scored three ways per position (Spearman):
  vs outcome                raw signal
  vs outcome | pick         residual of outcome on log(pick): does the NFL already price it?
  vs outcome | jm           residual of outcome on JM: is it new information for the model?
plus bucketed hit rates. A feature is worth promoting only when the |jm residual|
correlation is material (>= ~.12) and consistent across years.

    python scripts/jm_feature_discovery.py scripts/jm_optimize_results_2026-09-30.json
"""
import datetime
import json
import math
import re
import sys
from collections import defaultdict

ROOT = __file__.rsplit("scripts", 1)[0] or "."
SKILL = {"QB", "RB", "WR", "TE"}
OL = {"OT", "OG", "C", "G", "T", "OL", "IOL", "OC"}


def nrm(s):
    s = (s or "").lower()
    s = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def load_college():
    txt = open(ROOT + "data/college_stats.js", encoding="utf-8").read()
    for pf in ("college_stats_patch.js", "college_stats_manual_patch.js", "college_stats_patch_phase3.js"):
        try:
            txt += open(ROOT + "data/" + pf, encoding="utf-8").read()
        except OSError:
            pass
    out = {}
    for m in re.finditer(r'"([^"]+)"\s*:\s*\[((?:\{[^\]]*?\})*)\]', txt):
        rows = []
        for r in re.finditer(r"\{([^}]*)\}", m.group(2)):
            b = r.group(1)
            d = {}
            for k, v in re.findall(r"\b(\w+):(\"[^\"]*\"|-?[\d.]+)", b):
                d[k] = v.strip('"') if v.startswith('"') else float(v)
            if "yr" in d and "tm" in d:
                rows.append(d)
        if rows:
            out.setdefault(m.group(1), []).extend(rows)
    return out


def load_combine():
    txt = open(ROOT + "data/combine_data.js", encoding="utf-8").read()
    return json.loads(txt.split("=", 1)[1].strip().rstrip(";"))


def load_draft_picks():
    """HISTORICAL_DRAFT_PICKS (nflverse 2014-2025, all positions) keyed by normalized name."""
    txt = open(ROOT + "data/historical_draft_picks.js", encoding="utf-8").read()
    m = re.search(r"const HISTORICAL_DRAFT_PICKS\s*=\s*(\{.*\});", txt, re.S)
    return json.loads(m.group(1)) if m else {}


def load_pff_qb():
    txt = open(ROOT + "data/pff_grades.js", encoding="utf-8").read()
    m = re.search(r"window\._PFF_QB_GRADES\s*=\s*(\{.*?\});", txt, re.S)
    try:
        return json.loads(m.group(1)) if m else {}
    except ValueError:
        return {}


def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    def rank(a):
        idx = sorted(range(n), key=lambda i: a[i]); r = [0] * n; i = 0
        while i < n:
            j = i
            while j + 1 < n and a[idx[j + 1]] == a[idx[i]]:
                j += 1
            for k in range(i, j + 1):
                r[idx[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx)); dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return num / (dx * dy) if dx and dy else 0.0


def ols(xs, ys):
    n = len(xs); mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0
    return b, my - b * mx


def main():
    src = sys.argv[1]
    res = json.load(open(src, encoding="utf-8"))
    rows = [r for r in res["rows"] if r.get("verdict") != "pending" and r.get("cs") is not None]
    college = load_college()
    combine = load_combine()
    picks = load_draft_picks()
    pff_qb = load_pff_qb()
    by_nrm = {nrm(k): k for k in college}
    print("draft picks on file: %d (%s-%s)" % (len(picks), min(v["y"] for v in picks.values()), max(v["y"] for v in picks.values())))

    def pick_rec(name):
        return picks.get(nrm(name))

    def pick_of(name):
        e = pick_rec(name)
        return int(e["p"]) if e and e.get("p") else None

    def pos_of(name):
        e = pick_rec(name)
        return (e.get("pos") or "").upper() if e else ""

    # team-season index: (school, yr) -> [(name, row)]
    index = defaultdict(list)
    for name, seasons in college.items():
        for s in seasons:
            index[(s["tm"], int(s["yr"]))].append((name, s))
    print("college players: %d, team-seasons: %d" % (len(college), len(index)))

    def fpts(s):
        return (s.get("py", 0) * 0.04 + s.get("ptd", 0) * 4 - s.get("int", 0) + s.get("ry", 0) * 0.1 + s.get("rtd", 0) * 6
                + s.get("rec", 0) * 0.5 + s.get("rcy", 0) * 0.1 + s.get("rctd", 0) * 6 - s.get("fl", 0) * 2)

    feats = []
    for r in rows:
        name = r["n"]
        seasons = college.get(name) or college.get(by_nrm.get(nrm(name), ""), [])
        seasons = [s for s in seasons if int(s["yr"]) < r["yr"]]
        if not seasons:
            continue
        best = max(seasons, key=lambda s: fpts(s) / max(1, s.get("gp", 1)) if s.get("gp") else 0)
        f = {"n": name, "pos": r["pos"], "yr": r["yr"], "pick": r["pick"], "cs": r["cs"], "jm": r["jm"]}
        skill, ol, qb_best, qb_name, wpn, comp_yds = set(), set(), 300, None, [], 0.0
        own_yds = best.get("rcy", 0) if r["pos"] in ("WR", "TE") else best.get("ry", 0)
        for s in seasons:
            for tn, ts in index.get((s["tm"], int(s["yr"])), []):
                if nrm(tn) == nrm(name):
                    continue
                tp, pk = pos_of(tn), pick_of(tn)
                if pk is None or pk >= 300:
                    continue        # only NFL-drafted teammates count
                if tp in SKILL:
                    skill.add((tn, pk))
                if tp in OL:
                    ol.add((tn, pk))
                if s is best:
                    if tp == "QB" and r["pos"] != "QB" and pk < qb_best:
                        qb_best, qb_name = pk, tn
                    if r["pos"] == "QB" and tp in ("WR", "TE"):
                        wpn.append(pk)
                    if r["pos"] in ("WR", "TE") and tp in ("WR", "TE"):
                        comp_yds += ts.get("rcy", 0)
                    if r["pos"] == "RB" and tp == "RB":
                        comp_yds += ts.get("ry", 0)
        f["tm_skill_n"] = len(skill)
        f["tm_skill_best"] = min([p for _, p in skill], default=300)
        f["tm_ol_n"] = len(ol)
        f["tm_ol_best"] = min([p for _, p in ol], default=300)
        if r["pos"] != "QB":
            f["qb_pick"] = qb_best
            g = pff_qb.get(qb_name) if qb_name else None
            f["qb_pff"] = g if g else None
        else:
            f["wpn_n"] = len(wpn)
            f["wpn_best"] = min(wpn, default=300)
        f["comp_yds"] = comp_yds
        f["comp_share"] = own_yds / (own_yds + comp_yds) if (own_yds + comp_yds) > 0 else None
        f["best_yr"] = int(best["yr"])
        feats.append(f)
    print("backtest players with college seasons: %d / %d" % (len(feats), len(rows)))

    # residuals per position
    for pos in SKILL:
        sub = [f for f in feats if f["pos"] == pos]
        if len(sub) < 10:
            continue
        b1, a1 = ols([math.log(f["pick"]) for f in sub], [f["cs"] for f in sub])
        b2, a2 = ols([f["jm"] for f in sub], [f["cs"] for f in sub])
        for f in sub:
            f["res_dc"] = f["cs"] - (a1 + b1 * math.log(f["pick"]))
            f["res_jm"] = f["cs"] - (a2 + b2 * f["jm"])

    FEATS = ["tm_skill_n", "tm_skill_best", "tm_ol_n", "tm_ol_best", "qb_pick", "qb_pff", "wpn_n", "wpn_best", "comp_yds", "comp_share"]
    out = {"source": src, "date": datetime.date.today().isoformat(), "n": len(feats), "by_pos": {}}
    print("\n%-4s %-14s %4s %8s %10s %10s   note" % ("pos", "feature", "n", "rho_out", "rho|pick", "rho|jm"))
    for pos in ["QB", "RB", "WR", "TE"]:
        sub = [f for f in feats if f["pos"] == pos and "res_dc" in f]
        out["by_pos"][pos] = {}
        for k in FEATS:
            vals = [f for f in sub if f.get(k) is not None]
            if len(vals) < 25:
                continue
            xs = [f[k] for f in vals]
            r1 = spearman(xs, [f["cs"] for f in vals]); r2 = spearman(xs, [f["res_dc"] for f in vals]); r3 = spearman(xs, [f["res_jm"] for f in vals])
            # year consistency: sign of rho|jm per draft year (n>=8)
            signs = []
            for y in sorted({f["yr"] for f in vals}):
                yy = [f for f in vals if f["yr"] == y]
                if len(yy) >= 8:
                    signs.append(1 if spearman([f[k] for f in yy], [f["res_jm"] for f in yy]) > 0 else -1)
            cons = (sum(1 for s in signs if s == (1 if r3 > 0 else -1)), len(signs))
            note = "NEW INFO" if abs(r3) >= 0.12 and cons[1] and cons[0] / cons[1] >= 0.7 else ""
            out["by_pos"][pos][k] = {"n": len(vals), "rho_out": round(r1, 3), "rho_pick": round(r2, 3), "rho_jm": round(r3, 3), "years_agree": "%d/%d" % cons}
            print("%-4s %-14s %4d %8.3f %10.3f %10.3f   %s %s" % (pos, k, len(vals), r1, r2, r3, "yrs %d/%d" % cons, note))
        print()

    # bucketed hit rates for the headline teammate features
    def bucket(pos, key, cuts, labels):
        sub = [f for f in feats if f["pos"] == pos and f.get(key) is not None and "res_jm" in f]
        print("  %s x %s" % (pos, key))
        for lo, hi, lab in zip(cuts[:-1], cuts[1:], labels):
            g = [f for f in sub if lo <= f[key] < hi]
            if len(g) < 6:
                continue
            hit = sum(1 for f in g if f["cs"] >= 45) / len(g)
            print("    %-14s n %3d  hit+ %.2f  outcome %6.1f  jm %5.1f  pick %5.1f  res_jm %+6.1f" % (
                lab, len(g), hit, sum(f["cs"] for f in g) / len(g), sum(f["jm"] for f in g) / len(g), sum(f["pick"] for f in g) / len(g), sum(f["res_jm"] for f in g) / len(g)))
    print("\n== buckets ==")
    for pos in ["RB", "WR", "TE"]:
        bucket(pos, "tm_ol_n", [0, 1, 3, 99], ["0 drafted OL", "1-2 drafted OL", "3+ drafted OL"])
        bucket(pos, "qb_pick", [1, 33, 101, 300, 301], ["QB R1", "QB R2-3", "QB day 3", "no drafted QB"])
        bucket(pos, "comp_share", [0, 0.4, 0.6, 0.8, 1.01], ["share <40%", "40-60%", "60-80%", "80%+"])
    bucket("QB", "wpn_n", [0, 1, 2, 4, 99], ["0 drafted WR/TE", "1", "2-3", "4+"])
    for pos in ["QB", "RB", "WR", "TE"]:
        bucket(pos, "tm_skill_n", [0, 2, 4, 7, 99], ["0-1 drafted skill", "2-3", "4-6", "7+"])

    dst = ROOT + "scripts/jm_features_%s.json" % out["date"]
    out["players"] = feats
    json.dump(out, open(dst, "w", encoding="utf-8"), indent=1)
    print("\nwrote", dst)


if __name__ == "__main__":
    main()
