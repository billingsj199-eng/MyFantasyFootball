#!/usr/bin/env python3
"""
MARKET-PROXY backtest for the prop anchor: does blending a weekly
market-priced signal into the P5 base improve next-week MAE?

No free archive of historical weekly PROP lines exists (The Odds API sells
2023+), so this uses the closest free proxy: DraftKings DFS SALARIES
(RotoGuru archive, 2019-2021 — the site stopped updating after 2021).
Salaries are the market's weekly per-player pricing — same information
family as props (matchup, role, news) but blunter and priced days earlier.
If salary blends help, that's a LOWER BOUND on what real props would do;
if they don't, the prop anchor's historical case weakens.

Method (no hindsight):
  base   = P5 blend (5*clayPg + g*ppgSoFar)/(5+g)   [the shipped JS base]
  salPred = per-position linear fit  fpts ~ a + b*salary, trained ONLY on
            weeks < W of the same season plus all of the prior season.
  blends = (1-w)*base + w*salPred, w swept.
Graded on played player-weeks (weeks 2+) with a posted salary, vs actual
half-PPR points — the same population rule as backtest_blend_weekly.py,
restricted to salaried rows so every model sees the identical sample.
"""
import numpy as np
import json, os, re, time, urllib.request
from backtest_sim_calibration import (norm, played, weekly_rec, POS_KEEP, POOL_MIN_PTS)
import backtest_sim_calibration as cal

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "salary_cache")
YEARS = {2019: 17, 2020: 17, 2021: 18}   # weeks with games
WEIGHTS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.7]
BUCKETS = [(1, 1), (2, 5), (6, 10), (11, 18)]  # (1,1) = the Week-1 case: base is pure Clay, fit is prior-season
MIN_FIT = 150   # fitted (salary, fpts) samples per position before salPred activates
# Grade only rows priced at/above this salary (env SALARY_MIN). The prop
# anchor only applies to players the books actually LINE — the priced-up
# segment — so 0 (everyone) understates the anchored population's signal.
SALARY_MIN = int(os.environ.get("SALARY_MIN", "0"))


def fetch_week(year, wk):
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, f"dk_{year}_w{wk}.txt")
    if os.path.exists(fn):
        return open(fn, encoding="utf-8").read()
    url = f"http://rotoguru1.com/cgi-bin/fyday.pl?week={wk}&year={year}&game=dk&scsv=1"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    body = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    m = re.search(r"(Week;Year;GID;Name[^\n]*\n(?:[^\n<]*\n)*)", body)
    block = m.group(1) if m else ""
    open(fn, "w", encoding="utf-8").write(block)
    time.sleep(1.0)
    return block


def load_salaries():
    """sal[(year, wk, normname, pos)] = salary"""
    sal = {}
    for year, wmax in YEARS.items():
        for wk in range(1, wmax + 1):
            block = fetch_week(year, wk)
            rows = [r for r in block.strip().split("\n") if r.count(";") >= 9]
            for r in rows[1:]:
                p = r.split(";")
                name, pos, salary = p[3], p[4], p[9]
                if pos not in POS_KEEP or not salary.strip().isdigit():
                    continue
                if "," in name:
                    last, first = name.split(",", 1)
                    name = f"{first.strip()} {last.strip()}"
                sal[(year, wk, norm(name), pos)] = int(salary)
        print(f"  {year}: salaries loaded")
    return sal


def main():
    print("Loading RotoGuru DK salaries (cached after first run)...")
    sal = load_salaries()
    print(f"  {len(sal)} salaried player-weeks (QB/RB/WR/TE)")
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))

    # -- pass 1: joined samples (year, wk, pos, salary, fpts) + per-player rows
    samples = []          # for the salary->pts fits
    graded_rows = []      # (year, wk, pos, salary, base_pred, fpts)
    n_join = 0
    for Y, wmax in YEARS.items():
        if str(Y) not in clay_hist:
            continue
        G = 16 if Y <= 2020 else 17   # games that season (per-game divisor)
        for name, c in clay_hist[str(Y)].items():
            pos = c.get("pos")
            if pos not in POS_KEEP:
                continue
            pts, gm, rec_n = c.get("pts") or 0, c.get("gm") or 0, c.get("rec") or 0
            if pts < POOL_MIN_PTS or gm < 2:
                continue
            wrec = weekly_rec(name, pos)
            if wrec is None:
                continue
            rows = sorted([(w["wk"], w["fpts"]) for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, pts - rec_n / 2.0) / G
            nn = norm(name)
            hist = []
            for wk, fpts in rows:
                s = sal.get((Y, wk, nn, pos))
                if s is not None:
                    samples.append((Y, wk, pos, s, fpts))
                    n_join += 1
                if s is not None and (wk == 1 or hist):
                    g = len(hist)
                    ppg = (sum(hist) / g) if g else 0.0
                    base = (5 * clay_pg + g * ppg) / (5 + g)  # g=0 -> pure Clay (the W1 case)
                    graded_rows.append((Y, wk, pos, s, base, fpts))
                hist.append(fpts)
    print(f"  joined {n_join} salary<->actual samples; grading {len(graded_rows)} player-weeks")

    # -- pass 2: per (year, wk, pos) linear fits on PAST data only
    by_fit = {}
    for (Y, wk, pos, s, fpts) in samples:
        by_fit.setdefault((Y, wk, pos), []).append((s, fpts))
    years = sorted(YEARS)

    def fit_for(Y, wk, pos):
        train = []
        prev = years[years.index(Y) - 1] if years.index(Y) > 0 else None
        for (fy, fw, fp), rows in by_fit.items():
            if fp != pos:
                continue
            if (fy == Y and fw < wk) or (prev is not None and fy == prev):
                train.extend(rows)
        if len(train) < MIN_FIT:
            return None
        xs = np.array([t[0] for t in train], float)
        ys = np.array([t[1] for t in train], float)
        b, a = np.polyfit(xs, ys, 1)
        return (a, b)

    fits = {}
    errs = {}
    n_graded = 0
    corr_x, corr_y = [], []
    for (Y, wk, pos, s, base, fpts) in graded_rows:
        key = (Y, wk, pos)
        if key not in fits:
            fits[key] = fit_for(Y, wk, pos)
        f = fits[key]
        if f is None:
            continue
        if s < SALARY_MIN:
            continue
        sal_pred = max(0.0, f[0] + f[1] * s)
        bucket = next((b for b in BUCKETS if b[0] <= wk <= b[1]), None)
        if bucket is None:
            continue
        n_graded += 1
        corr_x.append(s); corr_y.append(fpts)
        preds = {"base(P5)": base, "salary": sal_pred}
        for w in WEIGHTS:
            preds[f"w={w}"] = (1 - w) * base + w * sal_pred
        for k, v in preds.items():
            errs.setdefault((bucket, k), []).append(abs(v - fpts))

    models = ["base(P5)", "salary"] + [f"w={w}" for w in WEIGHTS]
    print(f"\n=== Salary-proxy blend sweep, 2019-21, {n_graded} played+salaried player-weeks ===")
    print(f"(salary vs actual fpts corr: {np.corrcoef(corr_x, corr_y)[0,1]:+.3f})")
    print(f"{'weeks':<8}" + "".join(f"{m:>10}" for m in models))
    overall = {m: [] for m in models}
    for b in BUCKETS:
        if (b, models[0]) not in errs:
            continue
        line = f"{b[0]}-{b[1]:<6}"
        best = min(models, key=lambda m: np.mean(errs[(b, m)]))
        for m in models:
            v = np.mean(errs[(b, m)])
            overall[m].extend(errs[(b, m)])
            line += ("%9.3f%s" % (v, "*" if m == best else " "))
        print(line)
    best = min(models, key=lambda m: np.mean(overall[m]))
    print(f"{'ALL':<8}" + "".join("%9.3f%s" % (np.mean(overall[m]), "*" if m == best else " ") for m in models))
    base_all = np.mean(overall["base(P5)"])
    best_all = np.mean(overall[best])
    print(f"\nbest = {best}: {100 * (best_all - base_all) / base_all:+.2f}% vs the shipped P5 base")
    # head-to-head at the shipped-analog weight
    hh_w = "w=0.5"
    wins = sum(1 for e_b, e_w in zip(overall["base(P5)"], overall[hh_w]) if e_w < e_b)
    losses = sum(1 for e_b, e_w in zip(overall["base(P5)"], overall[hh_w]) if e_w > e_b)
    print(f"head-to-head {hh_w} vs base: {wins}-{losses} ({100 * wins / max(1, wins + losses):.1f}%)")
    print("\nCaveats: salaries are Tuesday-priced (staler than Sunday props), blunter")
    print("than stat-level lines, and 'salary' here rides a 2-param linear map — so a")
    print("positive result is a LOWER BOUND on what true weekly props would add.")


if __name__ == "__main__":
    main()
