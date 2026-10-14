#!/usr/bin/env python3
"""
TAIL-MARKET BACKTEST (2026-10-14) — do the new betting-pull fields earn a
place in the projection?  Grades, on every played week that carries them:

  1. TD count: Poisson from devigged anytime odds (what the engine does)
     vs a TWO-POINT read that also uses the 2+ TD market (atd2, and atd3
     where posted): E[TD] = P(1+) + P(2+) + P(3+).  Bias / MAE on 6 x TD
     points, by implied-probability band and position, paired bootstrap on
     the MAE difference.  Heavy favorites (P >= .55) called out separately —
     W1-5 showed them scoring 1.06 TD/g vs a 0.83 Poisson mean.
  2. Reception / yardage juice: each stat line at FACE VALUE vs a mean
     skewed by the two-sided prices (reco/recu, rcyo/rcyu, ryo/ryu,
     pyo/pyu).  Receptions solve a Poisson mean for P(X > line); yards use
     line + z(p_over) x sigma, sigma = residual spread of (actual - line)
     from the earlier weeks.  Also: does the juiced side land more than 50%?

Lines come from data/betting_lines_2026.json weeklyProps (kickoff-frozen
pregame boards), actuals from weekly_stats_active.js via diagnose_week,
positions from the Sim Lab lock snapshots.  Prints a report; writes
data/tail_backtest_latest.txt.  Fixed entry point for the scheduled run:

    python backtest_tail_markets.py            (all played weeks)
    python backtest_tail_markets.py --weeks 6 7
"""
import argparse, glob, json, math, os, random, re, sys
import numpy as np
from score_week import HERE, norm
from diagnose_week import load_rows, REPO

BOOKS = ("DK", "FD", "MGM", "UD", "PP")
JUICE = {"RB": 1.108, "WR": 1.133}          # engine SIM_TUNING.atdJuice (10-07); else 1.06
JUICE_DEFAULT = 1.06
PRICE = {"rec": ("reco", "recu"), "rcy": ("rcyo", "rcyu"), "ry": ("ryo", "ryu"), "py": ("pyo", "pyu")}
SC = {"rec": 0.5, "rcy": 0.1, "ry": 0.1, "py": 0.04}   # half-PPR points per unit
OUT_TXT = os.path.join(HERE, "data", "tail_backtest_latest.txt")

_lines = []
def say(s=""):
    print(s); _lines.append(s)

def am_prob(o):
    o = float(o)
    return (-o / (-o + 100)) if o < 0 else (100 / (o + 100))

def mean_prob(entry, key):
    ps = [am_prob(entry[b][key]) for b in BOOKS
          if isinstance(entry.get(b), dict) and isinstance(entry[b].get(key), (int, float)) and entry[b][key] != 0]
    return (float(np.mean(ps)), len(ps)) if ps else (None, 0)

def consensus_line(entry, key):
    vals = [entry[b][key] for b in BOOKS if isinstance(entry.get(b), dict) and isinstance(entry[b].get(key), (int, float))]
    return float(np.median(vals)) if vals else None

def two_sided_p(entry, key):
    """no-vig P(over) averaged across books that price both sides of this stat."""
    ko, ku = PRICE[key]
    ps = []
    for b in BOOKS:
        s = entry.get(b)
        if not isinstance(s, dict): continue
        o, u = s.get(ko), s.get(ku)
        if isinstance(o, (int, float)) and isinstance(u, (int, float)):
            po, pu = am_prob(o), am_prob(u)
            ps.append(po / (po + pu))
    return (float(np.mean(ps)), len(ps)) if ps else (None, 0)

def pois_over(lam, line):
    L = int(math.floor(line)); term = math.exp(-lam); cdf = term
    for i in range(1, L + 1):
        term *= lam / i; cdf += term
    return 1 - cdf
def pois_mean_for(line, p):
    p = min(0.98, max(0.02, p)); lo, hi = 1e-3, 30.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if pois_over(mid, line) < p: lo = mid
        else: hi = mid
    return (lo + hi) / 2
def z_of(p):
    p = min(0.98, max(0.02, p))
    lo, hi = -3.0, 3.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if 0.5 * (1 + math.erf(mid / math.sqrt(2))) < p: lo = mid
        else: hi = mid
    return (lo + hi) / 2

def pos_map():
    pm = {}
    for f in sorted(glob.glob(os.path.join(HERE, "data", "snapshots", "simlab_snapshot_w*.json"))):
        try:
            for p in json.load(open(f, encoding="utf-8")).get("players", []):
                if p.get("pos") in ("QB", "RB", "WR", "TE"): pm[norm(p["name"])] = p["pos"]
        except (OSError, ValueError):
            pass
    return pm

def boot_diff(a, b, n=2000, seed=7):
    """paired bootstrap: mean(a - b) with 90% CI (a, b = per-row abs errors)."""
    d = np.array(a) - np.array(b)
    if not len(d): return (float("nan"),) * 3
    rng = random.Random(seed); ms = []
    for _ in range(n):
        idx = [rng.randrange(len(d)) for _ in range(len(d))]
        ms.append(float(np.mean(d[idx])))
    ms.sort()
    return float(np.mean(d)), ms[int(0.05 * n)], ms[int(0.95 * n)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, nargs="*", help="weeks to grade (default: every week with actuals)")
    a = ap.parse_args()
    data = json.load(open(os.path.join(REPO, "data", "betting_lines_2026.json"), encoding="utf-8"))
    wp = data.get("weeklyProps") or {}
    pm = pos_map()
    weeks = a.weeks or sorted(int(w) for w in wp)
    rows = []
    for wk in weeks:
        act = load_rows(wk)
        if not act:
            say(f"W{wk}: no actuals yet — skipped"); continue
        for name, entry in (wp.get(str(wk)) or {}).items():
            w = act.get(norm(name))
            if not w: continue
            pos = pm.get(norm(name))
            if pos not in ("QB", "RB", "WR", "TE"): continue
            rows.append(dict(wk=wk, name=name, pos=pos, e=entry, act=w,
                             tds=(w.get("rtd") or 0) + (w.get("rctd") or 0)))
    if not rows:
        say("no graded rows"); return
    say(f"Tail-market backtest: {len(rows)} player-weeks with a prop board and a box score, weeks {sorted(set(r['wk'] for r in rows))}")

    # ------------------------------------------------------------ 1. TD count
    td = []
    for r in rows:
        p1, n1 = mean_prob(r["e"], "atd")
        if p1 is None: continue
        j = JUICE.get(r["pos"], JUICE_DEFAULT)
        q1 = min(0.85, max(0.01, p1 / j))
        lam = -math.log(1 - q1)
        p2, n2 = mean_prob(r["e"], "atd2")
        p3, n3 = mean_prob(r["e"], "atd3")
        rec = dict(r, p1=p1, lam=lam, has2=p2 is not None)
        if p2 is not None:
            q2 = min(q1, max(0.0, p2 / j))
            q3 = min(q2, max(0.0, p3 / j)) if p3 is not None else min(q2, (q2 * q2 / q1) if q1 > 0 else 0)
            tail4 = min(q3, (q3 * q3 / q2) if q2 > 0 else 0)
            rec["e2"] = q1 + q2 + q3 + tail4          # E[N] = sum P(N >= k)
            rec["q2"] = q2
            rec["pois2"] = 1 - math.exp(-lam) * (1 + lam)   # Poisson P(2+)
        td.append(rec)
    with2 = [r for r in td if r["has2"]]
    say(f"\n=== 1. TD COUNT — anytime-only Poisson vs two-point (anytime + 2+ market) ===")
    say(f"rows with anytime odds {len(td)}; with a 2+ market {len(with2)} (weeks {sorted(set(r['wk'] for r in with2))})")
    if with2:
        def line(lbl, rs):
            if len(rs) < 8: return
            act = np.mean([r["tds"] for r in rs]); l0 = np.mean([r["lam"] for r in rs]); e2 = np.mean([r["e2"] for r in rs])
            a0 = [abs(6 * r["lam"] - 6 * r["tds"]) for r in rs]; a2 = [abs(6 * r["e2"] - 6 * r["tds"]) for r in rs]
            m, lo, hi = boot_diff(a2, a0)
            p2a = np.mean([1 if r["tds"] >= 2 else 0 for r in rs]); p2p = np.mean([r["pois2"] for r in rs]); p2m = np.mean([r["q2"] for r in rs])
            say(f"  {lbl:22s} n {len(rs):4d}  actual TD/g {act:.3f} | Poisson {l0:.3f}  two-pt {e2:.3f} | MAE pts Poisson {np.mean(a0):.3f} two-pt {np.mean(a2):.3f} (diff {m:+.3f} [{lo:+.3f},{hi:+.3f}]) | 2+ rate actual {p2a:.3f} Poisson {p2p:.3f} market {p2m:.3f}")
        line("ALL", with2)
        for lo_, hi_ in ((0, .3), (.3, .45), (.45, .55), (.55, 1.01)):
            line(f"implied {lo_:.2f}-{hi_:.2f}", [r for r in with2 if lo_ <= r["p1"] < hi_])
        for pos in ("QB", "RB", "WR", "TE"):
            line(pos, [r for r in with2 if r["pos"] == pos])
        say("  (two-pt diff < 0 = the 2+ market read beat Poisson; CI excluding 0 = trust it)")
    hv = [r for r in td if r["p1"] >= 0.55]
    if hv:
        say(f"  heavy favorites (P>=.55, all weeks) n {len(hv)}: actual {np.mean([r['tds'] for r in hv]):.3f} TD/g vs Poisson {np.mean([r['lam'] for r in hv]):.3f}")

    # ------------------------------------------------------------ 2. juice on stat lines
    say(f"\n=== 2. STAT-LINE JUICE — face value vs price-skewed mean ===")
    # sigma per stat from all weeks (actual - consensus line), robust-ish
    sig = {}
    for k in PRICE:
        res = []
        for r in rows:
            L = consensus_line(r["e"], k); av = r["act"].get(k)
            if L is not None and isinstance(av, (int, float)) and L > 0: res.append(av - L)
        if len(res) > 30:
            res = np.array(res); sig[k] = float(np.sqrt(np.mean((res - np.median(res)) ** 2)))
    say("  residual sigma (actual - line): " + ", ".join(f"{k} {v:.1f}" for k, v in sig.items()))
    for k in PRICE:
        pr = []
        for r in rows:
            L = consensus_line(r["e"], k); av = r["act"].get(k)
            if L is None or not isinstance(av, (int, float)) or L <= 0: continue
            p, nb = two_sided_p(r["e"], k)
            if p is None: continue
            if k == "rec": adj = pois_mean_for(L, p)
            else:
                if k not in sig: continue
                adj = L + z_of(p) * sig[k]
            pr.append(dict(r, L=L, p=p, adj=adj, av=av))
        if len(pr) < 10:
            say(f"  {k}: {len(pr)} priced rows — not enough yet"); continue
        aF = [abs(x["L"] - x["av"]) for x in pr]; aA = [abs(x["adj"] - x["av"]) for x in pr]
        m, lo, hi = boot_diff(aA, aF)
        skew = [x for x in pr if abs(x["p"] - 0.5) >= 0.04]
        hit = np.mean([1 if ((x["av"] > x["L"]) == (x["p"] > 0.5)) else 0 for x in skew]) if skew else float("nan")
        say(f"  {k:3s} n {len(pr):4d}  bias face {np.mean([x['L'] - x['av'] for x in pr]):+.2f} adj {np.mean([x['adj'] - x['av'] for x in pr]):+.2f} | MAE face {np.mean(aF):.2f} adj {np.mean(aA):.2f} (diff {m:+.3f} [{lo:+.3f},{hi:+.3f}]) | juiced side (|p-.5|>=.04, n {len(skew)}) landed {hit:.3f} | pts/g swing {np.mean([abs(x['adj'] - x['L']) for x in pr]) * SC[k]:.2f}")
        for pos in ("QB", "RB", "WR", "TE"):
            ps_ = [x for x in pr if x["pos"] == pos]
            if len(ps_) >= 15:
                aF = [abs(x["L"] - x["av"]) for x in ps_]; aA = [abs(x["adj"] - x["av"]) for x in ps_]
                say(f"      {pos}: n {len(ps_)} MAE face {np.mean(aF):.2f} adj {np.mean(aA):.2f}")
    say("\n  (adj diff < 0 with the CI below 0 = wire it; juiced-side rate near .50 = the price carries no extra information)")
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(_lines) + "\n")
    print(f"\nwrote {os.path.relpath(OUT_TXT, HERE)}")

if __name__ == "__main__":
    main()
