#!/usr/bin/env python3
"""A14 / v7 RB range coverage by backfield tier on v5's per-game numbers (2015-22 and 2023-25), per game and season totals.
Ratios (act+1)/(pred+1) come from earlier seasons only (pool rows, chart 1-3); season totals draw games from the games
model's 4-bin distribution (pre-isotonic g_pb0..3 from the walk; the lists also apply the A9 isotonic fix, so totals coverage
here is approximate). Log: rb_ranges_a14.log (opened in main())."""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM, qb_a10 as Q
BINS = [(0, 1), (2, 3), (4, 7), (8, 99)]
TIERS = ("lead back", "committee", "backup", "rookie")


def main():
    log = open(os.path.join(HERE, "rb_ranges_a14.log"), "w", encoding="utf-8")
    def P(s=""):
        print(s); log.write(s + "\n")
    D = pd.read_parquet(os.path.join(HERE, "data", "rb_a14_rows.parquet"))
    D["tier"] = np.select([D.rookie == 1, D.dc.isin([1, 2]) & (D.moved == 0) & D.q_car1.between(.25, .5), (D.dc == 1)], ["rookie", "committee", "lead back"], "backup")
    pool = (D.pos == "RB") & D.season.isin(PM.TEST_YEARS) & D.pg.notna() & (D.act_games >= 4) & D.dc.isin([1, 2, 3])
    rng = np.random.default_rng(7)
    res = {}
    for Y in PM.TEST_YEARS:
        past = pool & (D.season < Y) & (D.season >= 2015)
        if past.sum() < 60: continue
        rp = ((D.act_ppg[past] + 1) / (D.pg[past] + 1)).values
        for t in TIERS:
            pt = past & (D.tier == t); rt = ((D.act_ppg[pt] + 1) / (D.pg[pt] + 1)).values
            for way, ra in (("pooled", rp), ("by tier", rt if len(rt) >= 30 else rp)):
                q10, q90 = np.quantile(ra, [.1, .9])
                for i in np.where((pool & (D.season == Y) & (D.tier == t)).values)[0]:
                    r = D.iloc[i]; p = (r.pg + 1)
                    hit_pg = p * q10 <= r.act_ppg + 1 <= p * q90
                    pb = np.array([r.g_pb0, r.g_pb1, r.g_pb2, r.g_pb3], dtype=float)
                    hit_t = np.nan
                    if not np.isnan(pb).any():
                        k = rng.choice(4, 2000, p=pb / pb.sum()); lo = np.array([BINS[j][0] for j in k]); hi = np.array([min(BINS[j][1], r.G) for j in k])
                        gm = np.clip(r.G - np.floor(lo + rng.random(2000) * (hi - lo + 1)), 0, r.G)
                        tot = np.maximum(0, p * rng.choice(ra, 2000) - 1) * gm
                        a, b = np.quantile(tot, [.1, .9]); hit_t = float(a <= r.act_total <= b)
                    per = "dev" if Y <= 2022 else "holdout"
                    res.setdefault((t, way, per), []).append((hit_pg, hit_t))
    P("=== RB p10-p90 coverage by backfield tier on v5 per-game numbers (target 80%) ===")
    P("| tier | period | n | per-game pooled | per-game by tier | totals pooled | totals by tier |")
    P("|---|---|---|---|---|---|---|")
    for t in TIERS:
        for per in ("dev", "holdout"):
            a = np.array(res[(t, "pooled", per)], dtype=float); b = np.array(res[(t, "by tier", per)], dtype=float)
            P(f"| {t} | {per} | {len(a)} | {np.nanmean(a[:,0])*100:.0f}% | {np.nanmean(b[:,0])*100:.0f}% | {np.nanmean(a[:,1])*100:.0f}% | {np.nanmean(b[:,1])*100:.0f}% |")
    log.close()


if __name__ == "__main__":
    main()
