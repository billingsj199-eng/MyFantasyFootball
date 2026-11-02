#!/usr/bin/env python3
"""
QUESTIONABLE THIS WEEK -> does he play the NEXT games (Jack 2026-11-02 "contnue looking", the open lead from
research_q_streak_play.py). The engine's Questionable dock is current-week only and the availability curve reads only Out / IR /
Doubtful, so a Questionable player is projected at full strength from next week on - the same as a healthy starter.
Rows: starters (40%+ snaps over 2+ prior games that season) in a team week W, by their final report class at W (healthy = no
game status; Q-FP / Q-LP / Q-DNP) and miss streak k before W; outcome = plays the team's 1st / 2nd / 3rd game after W.
Graded on Brier, Q rows only: the engine's implied odds (= a healthy starter's) vs a Q-specific rate by class (and x streak),
leave-one-season-out + forward. The later-week dock the engine would carry = Q rate / healthy rate (relative, so healthy
starters stay the 1.0 reference). Q_YEARS env as research_q_streak_play.py. Log q_later_weeks[_<start>].log
"""
import os, sys
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_common as B
import backtest_injury_type_play as IT
a_, _, b_ = os.environ.get("Q_YEARS", "2019-2025").partition("-")
YEARS = list(range(int(a_), int(b_) + 1)); FWD = [y for y in YEARS if y >= 2022]
LOG = open(os.path.join(HERE, "q_later_weeks.log" if YEARS[0] == 2019 else f"q_later_weeks_{YEARS[0]}.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
HALF, K = 3, 40
kband = lambda k: "k0" if k == 0 else ("k1" if k == 1 else "k2+")


def load():
    rows = []
    for Y in YEARS:
        inj = pd.read_parquet(os.path.join(B.CACHE, f"injuries_{Y}.parquet"))
        inj = inj[(inj.game_type == "REG") & inj.position.isin(IT.POS4)].drop_duplicates(["team", "week", "gsis_id"])
        rep = {(B.cal.norm(str(r.full_name)), r.team, int(r.week)): IT.cls(r.report_status, IT.prac(r.practice_status)) for r in inj.itertuples(index=False)}
        sn = pd.read_parquet(os.path.join(B.CACHE, f"snap_counts_{Y}.parquet"), columns=["week", "game_type", "player", "position", "team", "offense_snaps", "offense_pct"])
        sn = sn[(sn.game_type == "REG") & sn.position.isin(IT.POS4)]
        tw = defaultdict(set)
        for r in sn.itertuples(index=False): tw[r.team].add(int(r.week))
        hist = defaultdict(dict); posof = {}
        for r in sn[sn.offense_snaps > 0].itertuples(index=False):
            k_ = (B.cal.norm(str(r.player)), r.team); hist[k_][int(r.week)] = float(r.offense_pct); posof[k_] = r.position
        for k_, h in hist.items():
            nm, tm = k_; gw = sorted(tw[tm])
            for i, W in enumerate(gw):
                prev = [h[w] for w in gw[:i] if w in h]
                if len(prev) < 2 or np.mean(prev) < .40: continue
                c = rep.get((nm, tm, W), "healthy")
                if c in ("healthy", "none-LP", "none-DNP"): c = "healthy"
                elif c not in IT.CLASSES: continue            # Out / Doubtful: the engine's availability curve already covers them
                if c == "healthy" and W not in h and not any(w > W and w in h for w in gw): continue   # gone for good without a report (cut / traded)
                k = 0
                for w in reversed(gw[:i]):
                    if w in h: break
                    k += 1
                nxt = gw[i + 1:i + 4]
                if not nxt: continue
                rows.append(dict(year=Y, pos=posof[k_], cls=c, kb=kband(k), **{f"n{j+1}": (int(nxt[j] in h) if j < len(nxt) else np.nan) for j in range(3)}))
    return pd.DataFrame(rows)


def rate(tr, keys, col, ref, prior=None):
    """recency-weighted rate per key, shrunk K toward prior (dict key -> p) or the pooled rate"""
    x = tr[tr[col].notna()]; w = 0.5 ** ((ref - x.year.values) / HALF); x = x.assign(w=w, wp=w * x[col].values)
    pooled = x.wp.sum() / x.w.sum(); out = {}
    for k, v in x.groupby(keys)[["wp", "w"]].sum().iterrows():
        pr = prior(k) if prior else pooled
        out[k] = (v.wp + K * pr) / (v.w + K)
    return out, pooled


def main():
    A = load()
    P(f"=== starters {YEARS[0]}-{YEARS[-1]}: {len(A):,} team-weeks ({int((A.cls != 'healthy').sum()):,} Questionable) ===")
    P("  plays the team's next game / 2nd / 3rd game after this week (raw)")
    for c in ("healthy",) + IT.CLASSES:
        for kb in ("k0", "k1", "k2+"):
            x = A[(A.cls == c) & (A.kb == kb)]
            if len(x) < 25: continue
            P(f"    {c:8s} {kb:4s} n {len(x):6d}  next {100*x.n1.mean():5.1f}%  2nd {100*np.nanmean(x.n2):5.1f}%  3rd {100*np.nanmean(x.n3):5.1f}%")
    Q = A.cls != "healthy"
    for h in (1, 2, 3):
        col = f"n{h}"
        P(f"\n  HORIZON {h} (the team's {['next', '2nd', '3rd'][h-1]} game after the Questionable week): Brier on Questionable rows")
        for title, folds in (("LOYO", [([y for y in YEARS if y != t], t) for t in YEARS]), ("FWD ", [([y for y in YEARS if y < t], t) for t in FWD])):
            E = defaultdict(list); EY = defaultdict(lambda: defaultdict(list))
            for tr_y, te_y in folds:
                tr = A[A.year.isin(tr_y)]; ref = max(tr_y)
                hp, hpool = rate(tr[tr.cls == "healthy"], ["pos"], col, ref)
                cp, _ = rate(tr[tr.cls != "healthy"], ["cls"], col, ref)
                ckp, _ = rate(tr[tr.cls != "healthy"], ["cls", "kb"], col, ref, prior=lambda k: cp.get(k[0], .8))
                te = A[(A.year == te_y) & Q & A[col].notna()]
                for r in te.itertuples(index=False):
                    y = getattr(r, col); ph = hp.get(r.pos, hpool)
                    for m, p in (("engine (= healthy)", ph), ("Q class", cp.get(r.cls, ph)), ("Q class x streak", ckp.get((r.cls, r.kb), cp.get(r.cls, ph)))):
                        E[m].append((p - y) ** 2); EY[m][te_y].append((p - y) ** 2)
            b0 = np.mean(E["engine (= healthy)"])
            P(f"    {title} " + " | ".join(f"{m}: {np.mean(v):.4f} ({100*(np.mean(v)/b0-1):+.2f}%, {sum(1 for _, t in folds if np.mean(EY[m][t]) < np.mean(EY['engine (= healthy)'][t]) - 1e-12)}/{len(folds)})" for m, v in E.items()))
        # the dock on all seasons: Q rate / healthy rate (by class x streak), position-pooled healthy reference
        ref = A.year.max(); hp, hpool = rate(A[A.cls == "healthy"], ["pos"], col, ref)
        cp, _ = rate(A[Q], ["cls"], col, ref); ckp, _ = rate(A[Q], ["cls", "kb"], col, ref, prior=lambda k: cp.get(k[0], .8))
        P(f"    fit (all seasons, half-life {HALF}): healthy " + " ".join(f"{p} {100*v:.1f}%" for p, v in sorted(hp.items())) + " | relative dock = Q rate / healthy (pooled " + f"{100*hpool:.1f}%):")
        P("      " + "  ".join(f"{c} {kb} {ckp[(c, kb)]/hpool:.3f}" for (c, kb) in sorted(ckp)))
    LOG.close()


if __name__ == "__main__":
    main()
