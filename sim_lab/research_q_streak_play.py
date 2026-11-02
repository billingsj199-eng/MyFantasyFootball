#!/usr/bin/env python3
"""
QUESTIONABLE + MISS STREAK -> does he play (Jack 2026-11-02, Breece Hall: Q / out W4-8, projected back every week).
The shipped play odds (INJ_PLAY = class x position, recency half-life 3, + INJ_TYPE injury-group shift; backtest_injury_type_play.py)
ignore how many games in a row he has already missed. research_q_streak.py: Q + limited plays 81% after 0 misses, 67% after 1,
51% after 2, 54% after 3+. Here: a streak logit shift on top of the shipped form, graded on Brier like INJ_TYPE was
(leave-one-season-out + forward). Also the LATER weeks: the Questionable dock is current-week only and the availability curve
only reads Out / IR / Doubtful, so a Q player with a streak is assumed back at full strength from next week on.
  SIM_BT_YEARS-style range via Q_YEARS (default 2019-2025 = the INJ_TYPE seasons; 2013-2025 also run).  Log q_streak_play[_<range>].log
"""
import os, sys, math
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_common as B
import backtest_injury_type_play as IT
a_, _, b_ = os.environ.get("Q_YEARS", "2019-2025").partition("-")
YEARS = list(range(int(a_), int(b_) + 1)); FWD = [y for y in YEARS if y >= 2022]
LOG = open(os.path.join(HERE, "q_streak_play.log" if YEARS[0] == 2019 else f"q_streak_play_{YEARS[0]}.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
K_STREAK = 40
kband = lambda k: "k0" if k == 0 else ("k1" if k == 1 else ("k2" if k == 2 else "k3+"))


def load():
    rows = []
    for Y in YEARS:
        inj = pd.read_parquet(os.path.join(B.CACHE, f"injuries_{Y}.parquet"))
        inj = inj[(inj.game_type == "REG") & inj.position.isin(IT.POS4)].drop_duplicates(["team", "week", "gsis_id"])
        sn = pd.read_parquet(os.path.join(B.CACHE, f"snap_counts_{Y}.parquet"), columns=["week", "game_type", "player", "position", "team", "offense_snaps", "offense_pct"])
        sn = sn[(sn.game_type == "REG") & sn.position.isin(IT.POS4)]
        tw = defaultdict(set)
        for r in sn.itertuples(index=False): tw[r.team].add(int(r.week))
        hist = defaultdict(dict)
        for r in sn[sn.offense_snaps > 0].itertuples(index=False): hist[(B.cal.norm(str(r.player)), r.team)][int(r.week)] = float(r.offense_pct)
        for r in inj.itertuples(index=False):
            c = IT.cls(r.report_status, IT.prac(r.practice_status))
            if c not in IT.CLASSES: continue
            k_ = (B.cal.norm(str(r.full_name)), r.team); W = int(r.week); h = hist.get(k_, {})
            if W not in tw[r.team]: continue
            prev = [p for w, p in h.items() if w < W]
            if len(prev) < 2 or np.mean(prev) < .40: continue
            gw = sorted(w for w in tw[r.team] if w < W); k = 0
            for w in reversed(gw):
                if w in h: break
                k += 1
            nxt = sorted(w for w in tw[r.team] if w > W)
            pi = r.report_primary_injury if isinstance(r.report_primary_injury, str) else r.practice_primary_injury
            rows.append(dict(year=Y, pos=r.position, cls=c, g=IT.grp(pi), k=k, kb=kband(k), played=int(W in h),
                             n1=(int(nxt[0] in h) if len(nxt) >= 1 else np.nan), n2=(int(nxt[1] in h) if len(nxt) >= 2 else np.nan)))
    return pd.DataFrame(rows)


def fit(tr, mode, half=3):
    """shipped form (class x position, half-life 3, + injury-group shift) + optional streak shift in logit space.
    mode: 'shipped' | 'streak pooled' (one shift per k band, all classes) | 'streak x class' (per class, shrunk to the pooled shift)"""
    ref = tr.year.max()
    base, _, _, _ = IT.fit(tr, half=half, use_type=True, ref=ref)
    if mode == "shipped": return base
    w = 0.5 ** ((ref - tr.year.values) / half)
    bp = np.array([base(r) for r in tr.itertuples(index=False)])
    tr = tr.assign(w=w, bp=bp)
    pooled = {}
    for kb, x in tr.groupby("kb"):
        if kb == "k0": continue
        obs = (np.sum(x.w * x.played) + K_STREAK * np.average(x.bp, weights=x.w)) / (x.w.sum() + K_STREAK)
        pooled[kb] = IT.logit(obs) - IT.logit(np.average(x.bp, weights=x.w))
    pc = {}
    if mode == "streak x class":
        for (c, kb), x in tr.groupby(["cls", "kb"]):
            if kb == "k0": continue
            mb = np.average(x.bp, weights=x.w); tgt = IT.sig(IT.logit(mb) + pooled.get(kb, 0.0))
            obs = (np.sum(x.w * x.played) + K_STREAK * tgt) / (x.w.sum() + K_STREAK)
            pc[(c, kb)] = IT.logit(obs) - IT.logit(mb)
    def pred(r):
        p = base(r)
        if r.kb == "k0": return p
        s = pc.get((r.cls, r.kb), pooled.get(r.kb, 0.0))
        return IT.sig(IT.logit(p) + s)
    return pred, pooled, pc


def main():
    A = load()
    P(f"=== Questionable starters (40%+ snaps over 2+ prior games) {YEARS[0]}-{YEARS[-1]}: {len(A):,} rows ===")
    P("  played by miss streak (raw):  " + " | ".join(f"{kb}: {100*A[A.kb==kb].played.mean():.0f}% n {int((A.kb==kb).sum())}" for kb in ("k0", "k1", "k2", "k3+")))
    for c in IT.CLASSES: P(f"    {c:6s} " + " | ".join(f"{kb}: {100*A[(A.kb==kb)&(A.cls==c)].played.mean():.0f}% n {int(((A.kb==kb)&(A.cls==c)).sum())}" for kb in ("k0", "k1", "k2", "k3+") if ((A.kb==kb)&(A.cls==c)).sum() >= 10))
    modes = ["shipped", "streak pooled", "streak x class"]
    for title, folds in (("LEAVE-ONE-SEASON-OUT", [([y for y in YEARS if y != t], t) for t in YEARS]), (f"FORWARD (train on earlier seasons, test {FWD[0]}-{FWD[-1]})", [([y for y in YEARS if y < t], t) for t in FWD])):
        E = {m: defaultdict(list) for m in modes}
        for tr_y, te_y in folds:
            tr, te = A[A.year.isin(tr_y)], A[A.year == te_y]
            preds = {m: (fit(tr, m) if m == "shipped" else fit(tr, m)[0]) for m in modes}
            for r in te.itertuples(index=False):
                for m in modes:
                    e = (preds[m](r) - r.played) ** 2; E[m]["all"].append(e); E[m][("y", te_y)].append(e); E[m][r.kb if r.kb != "k0" else "k0"].append(e)
                    if r.kb != "k0": E[m]["streak"].append(e)
        P(f"\n  {title}: Brier")
        b0 = np.mean(E["shipped"]["all"])
        for m in modes:
            wins = sum(1 for _, t in folds if np.mean(E[m][("y", t)]) < np.mean(E["shipped"][("y", t)]) - 1e-12)
            P(f"    {m:16s} all {np.mean(E[m]['all']):.5f} ({100*(np.mean(E[m]['all'])/b0-1):+.2f}%, seasons better {wins}/{len(folds)}) | streak rows {np.mean(E[m]['streak']):.5f} ({100*(np.mean(E[m]['streak'])/np.mean(E['shipped']['streak'])-1):+.2f}%, n {len(E[m]['streak'])})"
              + "".join(f" | {kb} {100*(np.mean(E[m][kb])/np.mean(E['shipped'][kb])-1):+.2f}%" for kb in ("k1", "k2", "k3+") if E[m][kb]))
    pred, pooled, pc = fit(A, "streak x class")
    P(f"\n  FIT ON ALL SEASONS (half-life 3, K {K_STREAK}): pooled logit shift " + "  ".join(f"{k}: {v:+.2f}" for k, v in sorted(pooled.items())))
    for (c, kb), v in sorted(pc.items()): P(f"    {c:6s} {kb:4s} shift {v:+.2f}")
    # what it does to the engine's play odds (RB) by class
    for c in IT.CLASSES:
        p0 = IT.fit(A, half=3, use_type=False, ref=A.year.max())[2].get((c, "RB"))
        if p0: P(f"    RB {c}: shipped {100*p0:.0f}% -> " + "  ".join(f"{kb} {100*IT.sig(IT.logit(p0) + pc.get((c, kb), pooled.get(kb, 0))):.0f}%" for kb in ("k1", "k2", "k3+")))
    # LATER WEEKS: plays the next game / the one after, given Q this week with a streak (engine assumes he is back at full strength)
    P("\n  LATER WEEKS (engine: Q dock is current-week only; availability curve skips Questionable -> next games assumed 100%)")
    for kb in ("k0", "k1", "k2", "k3+"):
        x = A[A.kb == kb]
        P(f"    Q this week, {kb:4s} n {len(x):5d}: plays this week {100*x.played.mean():3.0f}% | plays next game {100*np.nanmean(x.n1):3.0f}% | game after {100*np.nanmean(x.n2):3.0f}%"
          f" | sat this week -> plays next {100*np.nanmean(x[x.played == 0].n1):3.0f}% (n {int((x.played == 0).sum())})")
    LOG.close()


if __name__ == "__main__":
    main()
