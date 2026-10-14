#!/usr/bin/env python3
"""
CONCUSSION RETURNS (Jack 2026-10-08, Ja'Marr Chase W5: "coming back from a concussion so it's a little different for his
return ... week 5 proj feels low assuming he is playing").

Two questions:
 1. PRACTICE ODDS: do concussion weeks run a different practice pattern -> play rate than other injuries? (FootballDB
    day-by-day reports 2019-25 via build_practice_trajectory.load, injury text contains 'concussion'.) Tested as one more
    shift on top of the shipped trajectory + rest / vet / elite model, leave-one-season-out.
 2. PRODUCTION WHEN HE PLAYS: the engine's banged-up COND multiplies a Questionable player's projection when he plays
    (Q-FP .951-.961, Q-LP .933-.943, Q-DNP .877-.891 by position) whatever the injury. Is that right for a concussion?
    nflverse injuries (final report) x bt_common.iter_samples (actual vs the shipped base, no injury layer): ratio
    actual / base for concussion vs other injuries in the same class, relative to healthy players in the same position
    and week band (the backtest_banged_up REL definition).
Writes concussion_return.log.
"""
import os, sys
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_common as B
import build_practice_trajectory as T

LOG = open(os.path.join(HERE, "concussion_return.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n")


def practice_part():
    A = T.load()
    A["conc"] = A.inj.str.contains("concussion").astype(int)
    P(f"PRACTICE: {len(A)} starter injury-weeks, {A.conc.sum()} concussion weeks")
    for pat in ("DNP", "DNP-DNP", "DNP-DNP-DNP", "DNP-DNP-LP", "DNP-LP", "DNP-LP-LP", "DNP-LP-FP", "LP", "LP-LP", "LP-LP-FP", "LP-FP", "DNP-DNP-FP", "DNP-LP-FP"):
        parts = pat.split("-"); m = np.ones(len(A), bool)
        for i, x in enumerate(parts): m &= (A[["s1", "s2", "s3"][i]] == x).values
        c, o = A[m & (A.conc == 1)], A[m & (A.conc == 0)]
        P(f"  {pat:12s} concussion {100*c.played.mean() if len(c) else float('nan'):5.1f}% (n {len(c):3d})   other {100*o.played.mean():5.1f}% (n {len(o)})")
    c = A[A.conc == 1]
    P(f"  concussion weeks: final FULL {100*(c.s3=='FP').mean():.0f}%, Q {100*(c.des=='Questionable').mean():.0f}%, Out {100*(c.des=='Out').mean():.0f}%; "
      f"other weeks: final FULL {100*(A[A.conc==0].s3=='FP').mean():.0f}%, Out {100*(A[A.conc==0].des=='Out').mean():.0f}%")
    # LOSO: + concussion shift on top of the shipped model
    old = T.FLAGS
    for k, final in T.STAGES:
        e0, e1, wins = [], [], 0
        for Y in T.YEARS:
            tr, te = A[A.year != Y], A[A.year == Y]
            M = T.fit(tr, max(tr.year))
            T.FLAGS = old; adj0 = T.fit_adj(tr, M)
            T.FLAGS = old + ("conc",); adj1 = T.fit_adj(tr, M)
            a, b = [], []
            for r in te.itertuples(index=False):
                T.FLAGS = old; a.append((T.predict_adj(M, adj0, r, k, final) - r.played) ** 2)
                T.FLAGS = old + ("conc",); b.append((T.predict_adj(M, adj1, r, k, final) - r.played) ** 2)
            e0 += a; e1 += b; wins += int(np.mean(b) < np.mean(a))
        T.FLAGS = old + ("conc",)
        P(f"  day {k}{' +des' if final else '     '}: + concussion shift {np.mean(e0):.4f} -> {np.mean(e1):.4f} ({100*(np.mean(e1)/np.mean(e0)-1):+.2f}%, {wins}/7 seasons)")
    T.FLAGS = old
    M = T.fit(A, 2025); T.FLAGS = old + ("conc",); adj = T.fit_adj(A, M); T.FLAGS = old
    P("  concussion shifts (all seasons): " + str({st: {x: round(v, 2) for x, v in d.items()} for st, d in adj["conc"].items()}))
    return A


def prac(s):
    s = str(s or "")
    return "DNP" if s.startswith("Did Not") else "LP" if s.startswith("Limited") else "FP" if s.startswith("Full") else ""


def production_part():
    inj = {}
    for Y in T.YEARS:
        d = pd.read_parquet(os.path.join(B.CACHE, f"injuries_{Y}.parquet"))
        d = d[(d.game_type == "REG") & d.position.isin(B.POS4)]
        for r in d.itertuples(index=False):
            rs = str(r.report_status or ""); pr = prac(r.practice_status)
            txt = " ".join(str(x) for x in (r.report_primary_injury, r.practice_primary_injury) if isinstance(x, str)).lower()
            cls = "D" if rs == "Doubtful" else "Out" if rs == "Out" else ("Q-" + (pr or "FP")) if rs == "Questionable" else ("none-" + pr if pr in ("LP", "DNP") else "healthy")
            inj[(Y, int(r.week), B.cal.norm(str(r.full_name)))] = (cls, "concussion" in txt)
    rows = []
    for s in B.iter_samples(verbose=False):
        if not s.get("base") or s["base"] <= 0 or s["act"] is None: continue
        c = inj.get((s["year"], s["wk"], B.cal.norm(s["name"])), ("healthy", False))
        if c[0] in ("Out", "D"): continue
        band = 0 if s["wk"] <= 8 else 1 if s["wk"] <= 13 else 2
        rows.append(dict(year=s["year"], pos=s["pos"], band=band, cls=c[0], conc=int(c[1]), act=s["act"], base=s["base"]))
    A = pd.DataFrame(rows)
    P(f"\nPRODUCTION WHEN HE PLAYS: {len(A)} player-weeks (played), {int(A.conc.sum())} concussion-listed")
    # REL = class ratio / healthy ratio, same position + week band, pooled
    def rel(mask):
        num = den = 0.0; n = 0
        for (pos, band), g in A[mask].groupby(["pos", "band"]):
            h = A[(A.pos == pos) & (A.band == band) & (A.cls == "healthy")]
            if len(h) < 30: continue
            hr = h.act.sum() / h.base.sum()
            num += g.act.sum() / hr; den += g.base.sum(); n += len(g)
        return (num / den if den else float("nan")), n
    for cls in ("Q-FP", "Q-LP", "Q-DNP", "none-LP", "none-DNP"):
        rc, nc = rel((A.cls == cls) & (A.conc == 1)); ro, no = rel((A.cls == cls) & (A.conc == 0))
        P(f"  {cls:8s} concussion REL {rc:5.3f} (n {nc:3d})   other injuries REL {ro:5.3f} (n {no})")
    rc, nc = rel((A.cls.str.startswith("Q-")) & (A.conc == 1)); ro, no = rel((A.cls.str.startswith("Q-")) & (A.conc == 0))
    P(f"  any Q   concussion REL {rc:5.3f} (n {nc:3d})   other injuries REL {ro:5.3f} (n {no})")
    rc, nc = rel(A.conc == 1)
    P(f"  any listing with concussion (incl. full practice, no tag) REL {rc:5.3f} (n {nc})")
    # by season, any Q concussion
    P("  any-Q concussion REL by season: " + ", ".join(f"{Y}: {rel((A.year == Y) & A.cls.str.startswith('Q-') & (A.conc == 1))[0]:.2f} (n {rel((A.year == Y) & A.cls.str.startswith('Q-') & (A.conc == 1))[1]})" for Y in T.YEARS))


if __name__ == "__main__":
    practice_part()
    production_part()
    LOG.close()
