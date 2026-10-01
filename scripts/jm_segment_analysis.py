"""jm_segment_analysis.py - do transfers and small-conference careers move NFL outcomes
beyond what the JM model (and draft capital) already price in?

Input : a scripts/jm_optimize_results_*.json from scripts/jm_optimize.js (its `rows`
        = 2017-2024 backtest players with jm, cs = graded career outcome 0-100, pick, and
          verdict = band of that grade: stud 70+, hit 45+, contributor 20+, bust below).
Joins : data/college_stats.js (+ patch files) season rows -> school + conference
        per college season, so each player gets
          transfer      : played for 2+ schools
          path          : up (G5/FCS -> P4), down (P4 -> G5/FCS), lateral, none
          final_tier    : P4 / G5 / FCS of the last college season
          ever_small    : any season outside the Power conferences
Output: per segment (pooled + by position): n, hit+ rate, bust rate, mean outcome,
        mean JM, and two residuals with a t-stat:
          resid_jm  = outcome - E[outcome | jm]     (does JM mis-price the segment?)
          resid_dc  = outcome - E[outcome | pick]   (does the NFL mis-price it?)
        E[.] are per-position OLS fits on the full backtest sample.
        Written to scripts/jm_segments_<date>.json and printed as tables.

    python scripts/jm_segment_analysis.py scripts/jm_optimize_results_2026-09-30.json
"""
import datetime
import json
import math
import re
import sys

ROOT = __file__.rsplit("scripts", 1)[0] or "."
P4 = {"SEC", "Big Ten", "ACC", "Big 12", "Pac-12", "Pac-10", "Big East", "FBS Independents"}
P4_IND = {"Notre Dame", "BYU"}  # independents treated as Power-level programs
G5 = {"American Athletic", "AAC", "Mountain West", "Mid-American", "MAC", "Sun Belt", "Conference USA", "C-USA",
      "Western Athletic", "WAC", "FBS Independents"}


def conf_tier(conf, team):
    c = (conf or "").strip()
    if team in P4_IND:
        return "P4"
    if c in P4 and c != "FBS Independents":
        return "P4"
    if c in G5:
        return "G5"
    if not c:
        return "?"
    return "FCS"


def load_college():
    txt = open(ROOT + "data/college_stats.js", encoding="utf-8").read()
    for pf in ("college_stats_patch.js", "college_stats_manual_patch.js", "college_stats_patch_phase3.js"):
        try:
            txt += open(ROOT + "data/" + pf, encoding="utf-8").read()
        except OSError:
            pass
    entries = {}
    for m in re.finditer(r'"([^"]+)"\s*:\s*\[((?:\{[^\]]*?\})*)\]', txt):
        name = m.group(1)
        rows = []
        for r in re.finditer(r"\{([^}]*)\}", m.group(2)):
            body = r.group(1)
            yr = re.search(r"\byr:(\d{4})", body)
            tm = re.search(r'\btm:"([^"]*)"', body)
            cf = re.search(r'\bconf:"([^"]*)"', body)
            if yr and tm:
                rows.append({"yr": int(yr.group(1)), "tm": tm.group(1), "conf": cf.group(1) if cf else ""})
        if rows:
            entries.setdefault(name, []).extend(rows)
    return entries


def nrm(s):
    s = s.lower()
    s = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def ols(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0
    return b, my - b * mx


def tstat(vals):
    n = len(vals)
    if n < 3:
        return 0.0
    m = sum(vals) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))
    return m / (sd / math.sqrt(n)) if sd else 0.0


def main():
    src = sys.argv[1]
    res = json.load(open(src, encoding="utf-8"))
    rows = [r for r in res["rows"] if r.get("verdict") != "pending" and r.get("cs") is not None]
    college = load_college()
    by_nrm = {nrm(k): k for k in college}

    for r in rows:
        seasons = college.get(r["n"]) or college.get(by_nrm.get(nrm(r["n"]), "")) or []
        seasons = sorted({(s["yr"], s["tm"], s["conf"]) for s in seasons if s["yr"] < r["yr"]})
        teams = []
        for _, tm, _ in seasons:
            if not teams or teams[-1] != tm:
                teams.append(tm)
        tiers = [conf_tier(cf, tm) for _, tm, cf in seasons]
        r["teams"] = teams
        r["transfer"] = len(set(teams)) >= 2
        r["final_tier"] = tiers[-1] if tiers else "?"
        r["ever_small"] = any(t in ("G5", "FCS") for t in tiers)
        if r["transfer"] and tiers:
            first, last = tiers[0], tiers[-1]
            rank = {"FCS": 0, "G5": 1, "P4": 2, "?": 1}
            r["path"] = "up" if rank[last] > rank[first] else "down" if rank[last] < rank[first] else "lateral"
        else:
            r["path"] = "none"
        r["hitplus"] = r["verdict"] in ("stud", "hit")
        r["bust"] = r["verdict"] == "bust"

    # per-position expectation fits
    for pos in {r["pos"] for r in rows}:
        sub = [r for r in rows if r["pos"] == pos]
        b1, a1 = ols([r["jm"] for r in sub], [r["cs"] for r in sub])
        b2, a2 = ols([math.log(r["pick"]) for r in sub], [r["cs"] for r in sub])
        for r in sub:
            r["resid_jm"] = r["cs"] - (a1 + b1 * r["jm"])
            r["resid_dc"] = r["cs"] - (a2 + b2 * math.log(r["pick"]))

    def seg(rs):
        n = len(rs)
        if not n:
            return None
        rj = [r["resid_jm"] for r in rs]; rd = [r["resid_dc"] for r in rs]
        return {"n": n, "hit_plus": round(sum(r["hitplus"] for r in rs) / n, 3), "bust": round(sum(r["bust"] for r in rs) / n, 3),
                "mean_outcome": round(sum(r["cs"] for r in rs) / n, 1), "mean_jm": round(sum(r["jm"] for r in rs) / n, 1),
                "mean_pick": round(sum(r["pick"] for r in rs) / n, 1),
                "resid_jm": round(sum(rj) / n, 2), "t_jm": round(tstat(rj), 2), "resid_dc": round(sum(rd) / n, 2), "t_dc": round(tstat(rd), 2)}

    groups = {
        "transfer": lambda r: "transfer" if r["transfer"] else "one school",
        "path": lambda r: r["path"],
        "final_tier": lambda r: r["final_tier"],
        "ever_small": lambda r: "played G5/FCS" if r["ever_small"] else "P4 only",
    }
    out = {"source": src, "date": datetime.date.today().isoformat(), "n": len(rows), "segments": {}}
    for gname, fn in groups.items():
        out["segments"][gname] = {}
        for pos in ["ALL", "QB", "RB", "WR", "TE"]:
            sub = rows if pos == "ALL" else [r for r in rows if r["pos"] == pos]
            labels = sorted({fn(r) for r in sub})
            out["segments"][gname][pos] = {lab: seg([r for r in sub if fn(r) == lab]) for lab in labels}
    # notable players: biggest |resid_jm| among transfers / small-school
    out["examples"] = {
        "small_school_overperformers": [(r["n"], r["pos"], r["yr"], r["pick"], round(r["jm"], 1), r["cs"], r["final_tier"]) for r in sorted([r for r in rows if r["ever_small"]], key=lambda r: -r["resid_jm"])[:12]],
        "small_school_underperformers": [(r["n"], r["pos"], r["yr"], r["pick"], round(r["jm"], 1), r["cs"], r["final_tier"]) for r in sorted([r for r in rows if r["ever_small"]], key=lambda r: r["resid_jm"])[:12]],
        "transfer_up_overperformers": [(r["n"], r["pos"], r["yr"], r["pick"], round(r["jm"], 1), r["cs"], "->".join(r["teams"])) for r in sorted([r for r in rows if r["path"] == "up"], key=lambda r: -r["resid_jm"])[:10]],
        "transfer_underperformers": [(r["n"], r["pos"], r["yr"], r["pick"], round(r["jm"], 1), r["cs"], "->".join(r["teams"])) for r in sorted([r for r in rows if r["transfer"]], key=lambda r: r["resid_jm"])[:10]],
    }
    dst = ROOT + "scripts/jm_segments_%s.json" % out["date"]
    json.dump(out, open(dst, "w", encoding="utf-8"), indent=1)

    print("backtest players with outcomes: %d (college seasons matched for %d)" % (len(rows), sum(1 for r in rows if r["teams"])))
    for gname in groups:
        print("\n== %s ==" % gname)
        print("%-4s %-16s %4s %6s %6s %7s %6s %6s %8s %6s %8s %6s" % ("pos", "segment", "n", "hit+", "bust", "outcome", "JM", "pick", "residJM", "t", "residDC", "t"))
        for pos in ["ALL", "QB", "RB", "WR", "TE"]:
            for lab, s in out["segments"][gname][pos].items():
                if not s or s["n"] < 5:
                    continue
                print("%-4s %-16s %4d %6.2f %6.2f %7.1f %6.1f %6.1f %8.2f %6.2f %8.2f %6.2f" % (pos, lab, s["n"], s["hit_plus"], s["bust"], s["mean_outcome"], s["mean_jm"], s["mean_pick"], s["resid_jm"], s["t_jm"], s["resid_dc"], s["t_dc"]))
    for k, v in out["examples"].items():
        print("\n%s:" % k)
        for row in v:
            print("  ", row)
    print("\nwrote", dst)


if __name__ == "__main__":
    main()
