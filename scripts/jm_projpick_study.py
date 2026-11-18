"""jm_projpick_study.py - how good is JM when draft capital is a NOVEMBER projection, not the real pick?

Devy prospects with a projected pick (combine_data draftProj) are scored with the main JM weights, where
draft capital is 30-50% of the grade. Every backtest used the real pick, so this measures what that costs
and tests fixes, on the 2021-2024 classes (the only ones with a free November consensus board).

Data: scripts/jm_nov_picks_2021_2024.json - NFL Mock Draft Database consensus big board as archived by
the Wayback Machine in November of each class's final college season (2020-11-22, 2021-11-26,
2022-11-20, 2023-11-19). Projected pick = the board's projected pick where shown (about round 1), else
the big-board rank; players not on the board = 'U' (as the live draftProj does).
NFLMDD opts out of AI crawlers (robots.txt); Jack approved these four archived boards only (2026-11-18).
Do not pull more dates / classes or the live site without asking him.

  python -I scripts/jm_projpick_study.py build <dir with wb2021_nov.html, wb2022.html, wb2023.html, wb2024.html>
  python -I scripts/jm_projpick_study.py scenarios scen.json
  node scripts/jm_projpick_eval.js --scenarios scen.json --out rows.json
  python -I scripts/jm_projpick_study.py score rows.json [--out scripts/jm_projpick_results_<date>.json]

Scenarios: nov_raw (projection as is), nov_off260 (off-board = pick 260), shrink_w (log pick pulled toward
the 2017-20 median drafted skill pick, keeping share w), dc_xk (draft-capital weight x k), combinations,
real_dc_x0.50. Judged by Spearman(JM, graded NFL career, jm_outcome_grades.json) per position, pooled
n-weighted, and leave-one-class-out (choose the best November scenario on three classes, score the fourth).

Result 2026-11-18 (262 players): JM on November picks .575 vs JM on real picks .609, the real pick alone
.576 and the November board alone .505. No shrink / weight cut beat nov_raw (held-out .556 vs .562);
'U' for off-board beats 260 (.575 vs .558). Keep the live draftProj handling as is.
"""
import datetime
import html
import json
import math
import os
import re
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PICKS = os.path.join(ROOT, "scripts", "jm_nov_picks_2021_2024.json")
GRADES = os.path.join(ROOT, "scripts", "jm_outcome_grades.json")
FILES = {2021: "wb2021_nov.html", 2022: "wb2022.html", 2023: "wb2023.html", 2024: "wb2024.html"}
SNAP = {2021: "2020-11-22", 2022: "2021-11-26", 2023: "2022-11-20", 2024: "2023-11-19"}
POS = ("QB", "RB", "WR", "TE")


def nrm(s):
    s = (s or "").lower()
    s = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def spearman(xs, ys):
    n = len(xs)
    if n < 5:
        return float("nan")
    def rank(a):
        o = sorted(range(n), key=lambda i: a[i]); r = [0.0] * n; i = 0
        while i < n:
            j = i
            while j + 1 < n and a[o[j + 1]] == a[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    d = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / d if d else float("nan")


def parse_board(path):
    s = open(path, encoding="utf-8", errors="replace").read()
    s = re.sub(r"<script.*?</script>", "", s, flags=re.S)
    rows = []
    for p in re.split(r"<li[ >]", s):
        m = re.search(r'href="(?:https?://[^"]*)?/players/\d{4}/([a-z0-9-]+)"[^>]*>(?:<div[^>]*>)?([^<]+)<', p)
        pos = re.search(r">\s*(QB|RB|WR|TE|OT|IOL|OG|C|G|OL|EDGE|DL|DT|DE|LB|CB|S|K|P|LS|ATH|FB|DB) \| ", p)
        if not (m and pos):
            continue
        rk = re.search(r'class="pick-number[^"]*"[^>]*>\s*(\d+)', p)
        pj = (re.search(r"projection-text[^>]*>.*?<span>(\d+)</span>", p, flags=re.S)
              or re.search(r"Projected to be drafted at:.*?#(\d+)", p, flags=re.S))
        rows.append({"rank": int(rk.group(1)) if rk else None, "name": html.unescape(m.group(2).strip()),
                     "pos": pos.group(1), "mock": int(pj.group(1)) if pj else None})
    return rows


def backtest_players():
    """[name, pos, yr, pick] for every drafted 2017-2024 skill player with a graded career."""
    g = json.load(open(GRADES, encoding="utf-8"))["players"]
    txt = open(os.path.join(ROOT, "data", "backtest_outcomes.js"), encoding="utf-8").read()
    body = txt[txt.index("BACKTEST_OUTCOMES = ") + len("BACKTEST_OUTCOMES = "):]
    data, _ = json.JSONDecoder().raw_decode(body)
    # grades are keyed by the site name ("Brian Thomas Jr.|2024"), backtest rows by the bare name
    site = {(nrm(k.rsplit("|", 1)[0]), int(k.rsplit("|", 1)[1])): k.rsplit("|", 1)[0] for k in g}
    return [[site[(nrm(r["n"]), int(yr))], r["pos"], int(yr), r["pick"]] for yr, rows in data.items() for r in rows
            if r.get("pos") in POS and isinstance(r.get("pick"), int) and (nrm(r["n"]), int(yr)) in site]


def cmd_build(src_dir):
    bt = backtest_players()
    out = {"source": "NFL Mock Draft Database consensus big board, Wayback Machine copies taken in November of each class's final college season",
           "fields": "board_rank = consensus big-board rank (null = not on the board); mock = projected pick where shown (about round 1); pick = actual pick",
           "snapshot": SNAP, "players": {}}
    for yr, f in FILES.items():
        rows = parse_board(os.path.join(src_dir, f)); depth = max(r["rank"] or 0 for r in rows)
        idx = {nrm(r["name"]): r for r in rows}
        for n, pos, y, pick in bt:
            if y != yr:
                continue
            r = idx.get(nrm(n))
            if r is None:   # nickname / suffix spellings: unique last name + first initial
                parts = [w for w in n.split() if w.lower().rstrip(".") not in ("jr", "sr", "ii", "iii", "iv", "v")]
                ln = nrm(parts[-1])
                c = [x for x in rows if nrm(x["name"]).endswith(ln) and nrm(x["name"])[:1] == nrm(n)[:1]]
                r = c[0] if len(c) == 1 else None
            out["players"]["%s|%d" % (n, yr)] = {"pos": pos, "yr": yr, "pick": pick, "board_rank": r["rank"] if r else None,
                                                "mock": r["mock"] if r else None, "board_name": r["name"] if r else None,
                                                "depth": depth, "nboard": len(rows)}
    json.dump(out, open(PICKS, "w", encoding="utf-8"), indent=1)
    print("wrote", PICKS, len(out["players"]), "players")


def proj(v):
    return v["mock"] or v["board_rank"]


def cmd_scenarios(dst):
    P = json.load(open(PICKS, encoding="utf-8"))["players"]
    p0 = statistics.median(p for _, _, y, p in backtest_players() if y < 2021)
    S = {"nov_raw": {"picks": {k: (proj(v) if v["board_rank"] else "U") for k, v in P.items()}},
         "nov_off260": {"picks": {k: (proj(v) if v["board_rank"] else 260) for k, v in P.items()}}}
    for w in (0.8, 0.6, 0.4, 0.2):
        S["shrink_%.1f" % w] = {"picks": {k: round(math.exp(w * math.log(proj(v) if v["board_rank"] else 260) + (1 - w) * math.log(p0)))
                                          for k, v in P.items()}}
    for k in (0.75, 0.5, 0.25):
        S["dc_x%.2f" % k] = {"picks": S["nov_raw"]["picks"], "dcScale": k}
        S["shrink0.6_dc_x%.2f" % k] = {"picks": S["shrink_0.6"]["picks"], "dcScale": k}
    S["real_dc_x0.50"] = {"picks": {}, "dcScale": 0.5}
    json.dump(S, open(dst, "w"))
    print("prior pick %s; wrote %d scenarios to %s" % (p0, len(S), dst))


def cmd_eval(rows_path, out_path):
    R = json.load(open(rows_path))
    G = json.load(open(GRADES, encoding="utf-8"))["players"]
    P = json.load(open(PICKS, encoding="utf-8"))["players"]
    idx = {s: {(r[0], r[2]): r for r in rows if r[2] >= 2021} for s, rows in R.items()}
    common = set.intersection(*[set(v) for v in idx.values()])
    common = {k for k in common if "%s|%d" % k in G}

    def score(fn, years=(2021, 2022, 2023, 2024)):
        out, tot, n = {}, 0.0, 0
        for p in POS:
            ks = [k for k in common if idx["real"][k][1] == p and k[1] in years]
            r = spearman([fn(k) for k in ks], [G["%s|%d" % k]["grade"] for k in ks]); out[p] = round(r, 3); tot += r * len(ks); n += len(ks)
        out["pooled"] = round(tot / n, 3); out["n"] = n
        return out

    jm = lambda s: (lambda k: idx[s][k][3])
    res = {"date": datetime.date.today().isoformat(), "players": len(common), "scenarios": {s: score(jm(s)) for s in R},
           "baselines": {"nov_board_alone": score(lambda k: -(proj(P["%s|%d" % k]) if P["%s|%d" % k]["board_rank"] else 400)),
                         "real_pick_alone": score(lambda k: -P["%s|%d" % k]["pick"])},
           "by_class": {y: {s: score(jm(s), (y,))["pooled"] for s in R} for y in (2021, 2022, 2023, 2024)}}
    cands = [s for s in R if s not in ("real", "real_dc_x0.50")]
    loco, tot, base, n = [], 0.0, 0.0, 0
    for y in (2021, 2022, 2023, 2024):
        tr = tuple(t for t in (2021, 2022, 2023, 2024) if t != y)
        best = max(cands, key=lambda s: score(jm(s), tr)["pooled"])
        a, b = score(jm(best), (y,)), score(jm("nov_raw"), (y,))
        loco.append({"held_out": y, "chosen": best, "held_out_rho": a["pooled"], "nov_raw_rho": b["pooled"]})
        tot += a["pooled"] * a["n"]; base += b["pooled"] * b["n"]; n += a["n"]
    res["leave_one_class_out"] = {"folds": loco, "chosen_pooled": round(tot / n, 3), "nov_raw_pooled": round(base / n, 3)}
    print("players 2021-24 scored in every scenario with a grade:", len(common))
    print("%-24s" % "" + "".join("%8s" % p for p in POS) + "  pooled")
    for label, sc in list(res["baselines"].items()) + list(res["scenarios"].items()):
        print("%-24s" % label + "".join("%8.3f" % sc[p] for p in POS) + "  %6.3f" % sc["pooled"])
    print("leave-one-class-out: chosen %.3f vs nov_raw %.3f  %s" % (res["leave_one_class_out"]["chosen_pooled"],
          res["leave_one_class_out"]["nov_raw_pooled"], [(f["held_out"], f["chosen"]) for f in loco]))
    out_path = out_path or os.path.join(ROOT, "scripts", "jm_projpick_results_%s.json" % res["date"])
    json.dump(res, open(out_path, "w", encoding="utf-8"), indent=1)
    print("wrote", out_path)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "build":
        cmd_build(a[1])
    elif a[0] == "scenarios":
        cmd_scenarios(a[1])
    elif a[0] == "score":
        cmd_eval(a[1], a[a.index("--out") + 1] if "--out" in a else None)
    else:
        sys.exit(__doc__)
