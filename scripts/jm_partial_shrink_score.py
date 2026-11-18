"""jm_partial_shrink_score.py - score the early-season shrink experiment (window._JM_EXP.partialShrink = k).

Inputs: jm_partial_season.js outputs for k = 0 (no shrink) and each k, in one mode (main or --devy):
  python -I scripts/jm_partial_shrink_score.py MODE k0.json k2.json k4.json ...   (file names must end _k<k>.json,
                                                                                  the no-shrink run is k = 0)
For each position and each N (games into the final season):
  acc   Spearman(JM after N games, graded NFL career), same players for every k
  stab  Spearman(JM after N games, full-season JM)
Leave-one-class-out: per position, k chosen on 7 classes by pooled early-season accuracy (N = 3 and 5),
scored on the 8th; pooled held-out accuracy vs k = 0 is the ship number.
"""
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G = json.load(open(os.path.join(ROOT, "scripts", "jm_outcome_grades.json"), encoding="utf-8"))["players"]
POS = ("QB", "RB", "WR", "TE")


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


mode, files = sys.argv[1], sys.argv[2:]
runs = {}
for f in files:
    k = int(re.search(r"_k(\d+)\.json$", f).group(1))
    runs[k] = json.load(open(f))
ks = sorted(runs)
Ns = sorted(set(int(n) for n in runs[ks[0]]["byN"]) & set(int(n) for k in ks for n in runs[k]["byN"]))
Ns = [n for n in Ns if all(str(n) in runs[k]["byN"] for k in ks)]
full = {(r[0], r[2]): r[3] for r in runs[ks[0]]["full"]}


def rows(k, N, pos, years=None):
    return [r for r in runs[k]["byN"][str(N)] if r[1] == pos and (r[0] + "|%d" % r[2]) in G
            and (years is None or r[2] in years) and (r[0], r[2]) in full]


out = {"mode": mode, "ks": ks, "ns": Ns, "table": {}, "loco": {}}
print("mode %s   accuracy (stability) by k" % mode)
for pos in POS:
    out["table"][pos] = {}
    print("\n%s" % pos)
    print("  N   " + "".join(("k=%d" % k).rjust(15) for k in ks))
    for N in Ns:
        line = "  %-3d " % N
        out["table"][pos][N] = {}
        for k in ks:
            rr = rows(k, N, pos)
            acc = spearman([r[3] for r in rr], [G[r[0] + "|%d" % r[2]]["grade"] for r in rr])
            stab = spearman([r[3] for r in rr], [full[(r[0], r[2])] for r in rr])
            out["table"][pos][N][k] = {"acc": acc, "stab": stab, "n": len(rr)}
            line += ("%.3f (%.3f)" % (acc, stab)).rjust(15)
        print(line)

EARLY = [n for n in Ns if n <= 5]
years = sorted({r[2] for r in runs[ks[0]]["full"]})
print("\nleave-one-class-out (k chosen on 7 classes by accuracy at N = %s, scored on the 8th)" % EARLY)
for pos in POS:
    picks, sel, base = {}, [], []
    for y in years:
        fit = set(years) - {y}
        def acc(k):
            return sum(spearman([r[3] for r in rows(k, N, pos, fit)], [G[r[0] + "|%d" % r[2]]["grade"] for r in rows(k, N, pos, fit)]) for N in EARLY)
        best = max(ks, key=lambda k: (acc(k), -k))
        picks[y] = best
        for N in EARLY:
            sel += [(N, r[3], G[r[0] + "|%d" % r[2]]["grade"]) for r in rows(best, N, pos, {y})]
            base += [(N, r[3], G[r[0] + "|%d" % r[2]]["grade"]) for r in rows(0, N, pos, {y})]
    # pooled per N, then averaged over N (grades at different N are not on one scale)
    a = sum(spearman([x[1] for x in sel if x[0] == N], [x[2] for x in sel if x[0] == N]) for N in EARLY) / len(EARLY)
    b = sum(spearman([x[1] for x in base if x[0] == N], [x[2] for x in base if x[0] == N]) for N in EARLY) / len(EARLY)
    out["loco"][pos] = {"base": b, "selected": a, "picks": picks}
    print("  %s: held-out accuracy %.3f -> %.3f   picks: %s" % (pos, b, a, " / ".join(str(picks[y]) for y in years)))
dst =os.path.join(ROOT, "scripts", "jm_partial_shrink_%s_%s.json" % (mode, runs[ks[0]]["date"]))
json.dump(out, open(dst, "w"), indent=1)
print("wrote", dst)
