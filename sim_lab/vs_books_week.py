#!/usr/bin/env python3
"""
Model vs the BOOKS for one scored week — headless twin of the Sim Lab
vsBooks grading. Uses the CLEAN model components stored in the lock
(comps: never touched by the market anchor) against the pregame lines the
lock captured (DK / FD / MGM / UD / PP), graded on actual stat lines.

  1. stat props: model comp vs consensus line (median across books) -> OVER/UNDER
     call -> hit if the actual landed on the called side (pushes dropped).
     Hit rate overall / by stat / by position, binomial p vs 50%.
  2. edge buckets: |model − line| / line -> does a bigger disagreement win more?
  3. anytime-TD: model rush+rec TD mean -> P(≥1 TD) = 1 − e^−λ vs devigged
     book probability -> call -> hit; Brier both sides.
  4. fantasy mean: model (JS) vs market-implied mean per player -> when they
     disagree by X, who was closer? (bucketed)
  5. randomness: runs/sign test on the per-call outcomes + shuffle baseline.

Caveat: lines are MEDIANS, comps are MEANS. Yardage/reception distributions
are right-skewed, so mean > median and a raw mean-vs-line call leans OVER;
the median-scale conversion is applied with a per-stat skew factor
(MEAN_TO_MED) estimated from the same week's over-rate, and results are
shown BOTH raw and adjusted so the lean is visible, not hidden.

Usage: python vs_books_week.py --week 1
"""
import argparse, json, math, os
import numpy as np
from score_week import HERE, norm
from diagnose_week import load_rows

STAT_KEYS = {"py": "py", "ptd": "ptd", "int": "int", "ry": "ry", "rec": "rec", "rcy": "rcy"}
BOOKS = ("DK", "FD", "MGM", "UD", "PP")
MIN_LINE = {"py": 100, "ptd": 0.5, "int": 0.5, "ry": 10, "rec": 1.5, "rcy": 10}

def consensus(lines, key):
    vals = [lines[b][key] for b in BOOKS if isinstance(lines.get(b), dict) and isinstance(lines[b].get(key), (int, float))]
    return (float(np.median(vals)), len(vals)) if vals else (None, 0)

def devig_atd(lines):
    """mean implied P(TD) across books' anytime-TD odds, flat 6% juice removed."""
    ps = []
    for b in BOOKS:
        o = lines.get(b, {}).get("atd") if isinstance(lines.get(b), dict) else None
        if isinstance(o, (int, float)) and o != 0:
            p = (-o / (-o + 100)) if o < 0 else (100 / (o + 100))
            ps.append(p / 1.06)
    return float(np.mean(ps)) if ps else None

def binom_p(k, n):
    """two-sided p-value vs 0.5 (normal approx w/ continuity)."""
    if n == 0:
        return 1.0
    z = (abs(k - n / 2) - 0.5) / math.sqrt(n / 4)
    return float(2 * (1 - 0.5 * (1 + math.erf(max(0, z) / math.sqrt(2)))))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--week", type=int, required=True); a = ap.parse_args()
    snap = json.load(open(os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{a.week}.json"), encoding="utf-8"))
    act = load_rows(a.week)
    calls = []      # stat prop calls
    tds = []        # anytime-TD
    means = []      # model vs market fantasy mean
    for p in snap["players"]:
        if p.get("pos") not in ("QB", "RB", "WR", "TE") or not p.get("lines"):
            continue
        w = act.get(norm(p["name"]))
        if not w:
            continue
        comps = p.get("comps") or {}
        for lk, sk in STAT_KEYS.items():
            line, nb = consensus(p["lines"], lk)
            mc = comps.get(lk)
            av = w.get(sk)
            if line is None or not isinstance(mc, (int, float)) or not isinstance(av, (int, float)):
                continue
            if line < MIN_LINE.get(lk, 0):   # 0.5-yard novelty lines are not a market
                continue
            calls.append({"name": p["name"], "pos": p["pos"], "stat": lk, "line": line, "nb": nb, "model": mc, "act": av,
                          "edge": (mc - line) / line if line else 0.0})
        pb = devig_atd(p["lines"])
        lam = comps.get("rrtd")
        if pb is not None and isinstance(lam, (int, float)):
            pm = 1 - math.exp(-lam)
            scored = 1 if ((w.get("rtd") or 0) + (w.get("rctd") or 0)) >= 1 else 0
            tds.append({"name": p["name"], "pos": p["pos"], "pm": pm, "pb": pb, "y": scored})
        if p.get("propSrc") == "line" and isinstance(p.get("propMean"), (int, float)) and isinstance(p.get("jsMean"), (int, float)):
            wl = (p.get("tun") or {}).get("wa") or (p.get("tun") or {}).get("w") or 0.70
            market = (p["propMean"] - (1 - wl) * p["jsMean"]) / wl
            means.append({"name": p["name"], "pos": p["pos"], "js": p["jsMean"], "mkt": market, "act": float(w["fpts"])})

    print(f"W{a.week}: {len(calls)} stat-prop calls, {len(tds)} anytime-TD calls, {len(means)} market-vs-model means")

    # ---- 1. stat props, raw
    def grade(rows, adj=None):
        out = []
        for r in rows:
            m = r["model"] * (adj.get(r["stat"], 1.0) if adj else 1.0)
            if abs(m - r["line"]) < 1e-9 or r["act"] == r["line"]:
                continue   # no call / push
            call = "O" if m > r["line"] else "U"
            hit = (r["act"] > r["line"]) if call == "O" else (r["act"] < r["line"])
            out.append(dict(r, madj=m, call=call, hit=hit))
        return out
    print("\n=== 1. stat props: model vs consensus line (RAW mean-vs-line) ===")
    g = grade(calls)
    over_calls = sum(1 for r in g if r["call"] == "O"); over_act = sum(1 for r in g if r["act"] > r["line"])
    hits = sum(1 for r in g if r["hit"])
    print(f"  all: {hits}/{len(g)} = {100*hits/len(g):.1f}%  (p vs coin {binom_p(hits, len(g)):.3f}) | model called OVER {100*over_calls/len(g):.0f}%, actual went OVER {100*over_act/len(g):.0f}%")
    # per-stat mean->median skew factor from this week's over-rate (median line should be hit 50/50)
    adj = {}
    for st in STAT_KEYS:
        rs = [r for r in calls if r["stat"] == st and r["line"]]
        if len(rs) < 15:
            continue
        # scale model so its call split matches 50/50 on the median line: ratio of medians
        ratio = float(np.median([r["line"] / r["model"] for r in rs if r["model"] > 0]))
        adj[st] = ratio
    print("  per-stat table (raw):  stat   n   hit%   p     over-call%  over-act%   median line/model")
    for st in STAT_KEYS:
        rs = [r for r in g if r["stat"] == st]
        if len(rs) < 10:
            continue
        h = sum(1 for r in rs if r["hit"])
        print(f"    {st:4s} {len(rs):4d}  {100*h/len(rs):5.1f}%  {binom_p(h, len(rs)):.3f}    {100*sum(1 for r in rs if r['call']=='O')/len(rs):5.0f}%     {100*sum(1 for r in rs if r['act']>r['line'])/len(rs):5.0f}%      {adj.get(st, float('nan')):.3f}")
    print("\n=== 1b. stat props, MEDIAN-ADJUSTED (model scaled by the median line/model ratio per stat) ===")
    ga = grade(calls, adj)
    hits = sum(1 for r in ga if r["hit"])
    print(f"  all: {hits}/{len(ga)} = {100*hits/len(ga):.1f}%  (p {binom_p(hits, len(ga)):.3f}) | OVER calls {100*sum(1 for r in ga if r['call']=='O')/len(ga):.0f}%")
    for pos in ("QB", "RB", "WR", "TE"):
        rs = [r for r in ga if r["pos"] == pos]
        if len(rs) >= 10:
            h = sum(1 for r in rs if r["hit"]); print(f"    {pos}: {h}/{len(rs)} = {100*h/len(rs):.1f}%  (p {binom_p(h, len(rs)):.3f})")

    # ---- 2. edge buckets
    print("\n=== 2. does a bigger disagreement win more? (median-adjusted, |model−line|/line) ===")
    for lo, hi in ((0, .05), (.05, .10), (.10, .20), (.20, .35), (.35, 9)):
        rs = [r for r in ga if lo <= abs(r["madj"] - r["line"]) / r["line"] < hi]
        if len(rs) < 8:
            continue
        h = sum(1 for r in rs if r["hit"])
        print(f"  edge [{lo:.2f},{hi:.2f}) n={len(rs):3d}  hit {100*h/len(rs):5.1f}%  p {binom_p(h, len(rs)):.3f}")
    big = sorted(ga, key=lambda r: -abs(r["madj"] - r["line"]) / r["line"])[:12]
    print("  biggest 12 disagreements:")
    for r in big:
        print(f"    {r['name']:20s} {r['pos']} {r['stat']:4s} line {r['line']:6.1f} model {r['madj']:6.1f} -> {r['call']}  act {r['act']:6.1f}  {'HIT' if r['hit'] else 'miss'}")

    # ---- 3. anytime TD
    if tds:
        print("\n=== 3. anytime-TD: model P(TD) vs devigged book P(TD) ===")
        y = np.array([t["y"] for t in tds]); pm = np.array([t["pm"] for t in tds]); pb = np.array([t["pb"] for t in tds])
        print(f"  n={len(tds)}  scored {100*y.mean():.0f}% | model avg P {100*pm.mean():.0f}%  book avg P {100*pb.mean():.0f}%")
        print(f"  Brier: model {np.mean((pm-y)**2):.4f}  book {np.mean((pb-y)**2):.4f}  (lower = better)")
        dis = [t for t in tds if abs(t["pm"] - t["pb"]) >= 0.05]
        if dis:
            right = sum(1 for t in dis if (t["pm"] > t["pb"]) == bool(t["y"]))
            print(f"  disagreements >=5pts: {len(dis)}; model side right {right} ({100*right/len(dis):.0f}%) -- BASE-RATE TRAP: split by direction:")
            for lab, f in (("model HIGHER than book", lambda t: t["pm"] > t["pb"]), ("model LOWER than book ", lambda t: t["pm"] < t["pb"])):
                d2 = [t for t in dis if f(t)]
                if d2:
                    sc = np.mean([t["y"] for t in d2]); print(f"    {lab}: n={len(d2):3d}  scored {100*sc:.0f}%  vs book avg P {100*np.mean([t['pb'] for t in d2]):.0f}%  model avg P {100*np.mean([t['pm'] for t in d2]):.0f}%")
        for lo, hi in ((0.05, 0.10), (0.10, 0.20), (0.20, 1)):
            d2 = [t for t in tds if lo <= abs(t["pm"] - t["pb"]) < hi]
            if len(d2) >= 6:
                right = sum(1 for t in d2 if (t["pm"] > t["pb"]) == bool(t["y"]))
                print(f"    |ΔP| [{lo:.2f},{hi:.2f}) n={len(d2):3d} model right {100*right/len(d2):.0f}%")

    # ---- 4. fantasy mean: model vs market
    if means:
        print("\n=== 4. fantasy points: JS model vs market-implied mean ===")
        js = np.array([m["js"] for m in means]); mk = np.array([m["mkt"] for m in means]); ac = np.array([m["act"] for m in means])
        print(f"  n={len(means)}  MAE model {np.mean(np.abs(js-ac)):.3f}  market {np.mean(np.abs(mk-ac)):.3f} | bias model {np.mean(js-ac):+.2f} market {np.mean(mk-ac):+.2f}")
        closer = np.abs(js - ac) < np.abs(mk - ac)
        print(f"  model closer on {closer.sum()}/{len(means)} rows ({100*closer.mean():.0f}%, p {binom_p(int(closer.sum()), len(means)):.3f})")
        print("  by |model − market| bucket: who was closer, and did the actual land on the model's side of the market?")
        print("  (a) ABSOLUTE gap, half-PPR fantasy points")
        for lo, hi in ((0, 1), (1, 2), (2, 3), (3, 99)):
            m = (np.abs(js - mk) >= lo) & (np.abs(js - mk) < hi)
            if m.sum() < 8:
                continue
            side = ((js[m] > mk[m]) == (ac[m] > mk[m])).mean()
            print(f"    Δ [{lo},{hi}) pts  n={m.sum():3d}  model closer {100*closer[m].mean():4.0f}%  actual on model's side {100*side:4.0f}%  MAE model {np.mean(np.abs(js[m]-ac[m])):.2f} mkt {np.mean(np.abs(mk[m]-ac[m])):.2f}")
        print("  (b) RELATIVE gap, |model − market| / market")
        rel = np.abs(js - mk) / np.maximum(mk, 1.0)
        for lo, hi in ((0, .05), (.05, .10), (.10, .20), (.20, .30), (.30, 9)):
            m = (rel >= lo) & (rel < hi)
            if m.sum() < 8:
                continue
            side = ((js[m] > mk[m]) == (ac[m] > mk[m])).mean()
            print(f"    Δ [{100*lo:3.0f}%,{100*hi:3.0f}%) n={m.sum():3d}  model closer {100*closer[m].mean():4.0f}%  actual on model's side {100*side:4.0f}%  MAE model {np.mean(np.abs(js[m]-ac[m])):.2f} mkt {np.mean(np.abs(mk[m]-ac[m])):.2f}  avg mkt {mk[m].mean():.1f}")
        # direction split (base-rate check): model ABOVE vs BELOW market, each scale's tail
        for lab, msk in (("abs >=3 pts", np.abs(js - mk) >= 3), ("rel >=30%", rel >= 0.30)):
            for dl, dm in (("model ABOVE market", js > mk), ("model BELOW market", js < mk)):
                m = msk & dm
                if m.sum() >= 4:
                    side = ((js[m] > mk[m]) == (ac[m] > mk[m])).mean()
                    print(f"    {lab:12s} {dl}: n={m.sum():3d}  actual on model's side {100*side:4.0f}%  avg model {js[m].mean():5.1f} mkt {mk[m].mean():5.1f} actual {ac[m].mean():5.1f}")
        # the tail rows, both scales
        tail = [i for i in range(len(means)) if abs(js[i] - mk[i]) >= 3 or rel[i] >= 0.30]
        if tail:
            print("  players in either tail (>=3 pts or >=30%):")
            for i in sorted(tail, key=lambda i: -rel[i]):
                r = means[i]; s_ = 'model side' if (js[i] > mk[i]) == (ac[i] > mk[i]) else 'market side'
                print(f"    {r['name']:22s} {r['pos']}  model {js[i]:5.1f}  market {mk[i]:5.1f} ({100*(js[i]-mk[i])/max(mk[i],1):+4.0f}%)  actual {ac[i]:5.1f}  -> {s_}")

    # ---- 5. randomness
    print("\n=== 5. randomness of the stat-prop outcomes (median-adjusted) ===")
    seq = np.array([1 if r["hit"] else 0 for r in ga])
    rng = np.random.default_rng(7); base = [rng.integers(0, 2, len(seq)).mean() for _ in range(5000)]
    print(f"  observed hit {100*seq.mean():.1f}% | coin-flip 90% band [{100*np.percentile(base,5):.1f}, {100*np.percentile(base,95):.1f}] (n={len(seq)})")
    # per-player clustering: are hits concentrated in a few players (model 'knew' something) or spread?
    byp = {}
    for r in ga:
        byp.setdefault(r["name"], []).append(r["hit"])
    multi = [v for v in byp.values() if len(v) >= 3]
    if multi:
        allhit = sum(1 for v in multi if all(v)); allmiss = sum(1 for v in multi if not any(v))
        exp_all = np.mean([0.5 ** len(v) for v in multi]) * len(multi)
        print(f"  players with >=3 calls: {len(multi)}; all-hit {allhit}, all-miss {allmiss} (coin-flip expectation ~{exp_all:.1f} each)")

if __name__ == "__main__":
    main()
