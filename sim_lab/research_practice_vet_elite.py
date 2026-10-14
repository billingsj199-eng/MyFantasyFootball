#!/usr/bin/env python3
"""
VETERANS / ELITE vs PRACTICE (Jack 2026-10-08: "make sure it factors in veterans vs younger players - I feel like
elite players / veterans historically take Wednesday off more frequently - lmk if there is any data that suggests it").

Rows: build_practice_trajectory.load() (FootballDB day-by-day reports 2019-25 x nflverse snaps, regular starters).
  vet   = age 30+ on Sep 1          young = 25 or younger
  elite = last season top-12 QB/TE or top-24 RB/WR by PPG (site weekly DB, 8+ games)
  rest  = injury text says rest / not injury related

  Q1 how often each group sits Wednesday (DNP on report day 1), and how often that DNP is tagged rest
  Q2 given a Wednesday DNP (and given DNP then later days), how often each group plays
  Q3 does a group shift on top of the trajectory rates improve leave-one-season-out Brier (days 1-3)?
Writes practice_vet_elite.log.
"""
import math, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import build_practice_trajectory as T

lg = T.lg; sg = T.sg
LOG = open(os.path.join(HERE, "practice_vet_elite.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n")


def grp(A):
    A = A.copy()
    A["vet"] = (A.age >= 30).astype(int)
    A["young"] = (A.age <= 25).astype(int)
    A["mid"] = ((A.age > 25) & (A.age < 30)).astype(int)
    return A


def rate(s):
    return f"{100*s.played.mean():5.1f}% (n {len(s)})" if len(s) else "   -  (n 0)"


def main():
    A = grp(T.load())
    A = A[A.age.notna()]
    P(f"{len(A)} report rows with age (regular starters 2019-25)")
    groups = [("young <=25", A.young == 1), ("26-29", A.mid == 1), ("vet 30+", A.vet == 1), ("elite", A.elite == 1), ("non-elite", A.elite == 0),
              ("elite vet", (A.elite == 1) & (A.vet == 1))]
    P("\nQ1  how often listed starters sit WEDNESDAY (report day 1 = DNP), and how much of it is a rest tag")
    for name, m in groups:
        s = A[m]
        d1 = s[s.s1 == "DNP"]
        P(f"  {name:11s} Wed DNP {100*len(d1)/max(1,len(s)):5.1f}% of {len(s)} listings; of those tagged rest {100*d1.rest.mean() if len(d1) else 0:5.1f}%"
          f"; Wed DNP then FULL by Friday {100*(d1.s3=='FP').mean() if len(d1) else 0:5.1f}%")
    P("\nQ2  plays after a Wednesday DNP")
    for name, m in groups:
        s = A[m & (A.s1 == "DNP")]
        P(f"  {name:11s} Wed DNP: {rate(s)}   not rest: {rate(s[s.rest == 0])}   DNP-LP-*: {rate(s[s.s2 == 'LP'])}   DNP-DNP-*: {rate(s[s.s2 == 'DNP'])}")
    P("\n    final pattern x group (Questionable only)")
    for pat in ("DNP-LP-LP", "DNP-LP-FP", "DNP-DNP-LP", "DNP-DNP-DNP", "LP-LP-LP", "LP-LP-FP"):
        a, b, c = pat.split("-")
        base = A[(A.s1 == a) & (A.s2 == b) & (A.s3 == c) & (A.des == "Questionable")]
        P(f"  {pat:11s} Q: all {rate(base)}  vet {rate(base[base.vet == 1])}  young {rate(base[base.young == 1])}  elite {rate(base[base.elite == 1])}")

    P("\nQ3  leave-one-season-out Brier: trajectory alone vs + group shift (shrunk K=60, by day and latest status)")
    for gname, col in (("vet 30+", "vet"), ("elite", "elite"), ("rest tag", "rest")):
        for k, final in ((1, False), (2, False), (3, False), (3, True)):
            e0, e1 = [], []
            for Y in T.YEARS:
                tr, te = A[A.year != Y], A[A.year == Y]
                M = T.fit(tr, max(tr.year))
                # shift per (group flag, latest status at day k) = shrunk logit residual of the group on train
                sh = {}
                cs = ["s1", "s2", "s3"][k - 1]
                pr = np.array([T.predict(M, r, k, final) for r in tr.itertuples(index=False)])
                trv = tr.assign(p=pr)
                for X in ("FP", "LP", "DNP"):
                    g = trv[(trv[col] == 1) & (trv[cs] == X)]
                    if len(g) < 10: continue
                    obs, exp_ = g.played.sum(), g.p.sum()
                    p_bar = (obs + 60 * g.p.mean()) / (len(g) + 60)
                    sh[X] = lg(p_bar) - lg(g.p.mean())
                for r in te.itertuples(index=False):
                    p = T.predict(M, r, k, final)
                    X = [r.s1, r.s2, r.s3][k - 1]
                    q = sg(lg(p) + sh.get(X, 0)) if getattr(r, col) == 1 else p
                    e0.append((p - r.played) ** 2); e1.append((q - r.played) ** 2)
            P(f"  {gname:9s} day {k}{' +des' if final else '     '}: {np.mean(e0):.4f} -> {np.mean(e1):.4f} ({100*(np.mean(e1)/np.mean(e0)-1):+.2f}%)")
    LOG.close()


if __name__ == "__main__":
    main()
