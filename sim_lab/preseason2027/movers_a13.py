#!/usr/bin/env python3
"""A13 movers: every QB whose P(bench), projected games or rank moved from v4 to v5 (2026 check and 2027 early look).
Log: output/movers_a13.log (opened in main())."""
import os
import numpy as np, pandas as pd
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def main():
    log = open(os.path.join(OUT, "movers_a13.log"), "w", encoding="utf-8")
    def P(s=""):
        print(s); log.write(s + "\n")
    for base in ("2026_inhouse_check", "2027_inhouse_early"):
        a = pd.read_csv(os.path.join(OUT, f"{base}_v4.csv")); b = pd.read_csv(os.path.join(OUT, f"{base}.csv"))
        a = a[a.pos == "QB"]; b = b[b.pos == "QB"]
        m = a.merge(b, on=["name", "team"], suffixes=("_4", "_5"))
        m["dp"] = m.p_bench_5 - m.p_bench_4; m["dg"] = m.games_5 - m.games_4
        mv = m[(m.dp.abs() >= .005) | (m.dg.abs() >= .05) | (m.pos_rank_4 != m.pos_rank_5) | (m["rank_4"] != m["rank_5"])].sort_values("pos_rank_5")
        extra = ["ppg26_5", "g26_5", "act_pos_rank_5"] if "g26_5" in m else ["ppg26_5"]
        P(f"\n=== {base}: QBs that moved v4 -> v5 ({len(mv)} of {len(m)}) ===")
        P("| QB | team | P(bench) v4 | v5 | games v4 | v5 | total v4 | v5 | QB rk v4 | v5 | overall v4 | v5 | SF12 rk v4 | v5 |" + (" 2026 PPG | 2026 G | 2026 QB rk |" if "g26_5" in m else " 2026 PPG |"))
        P("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|" + ("---|" * len(extra)))
        f = lambda v, d=2: "" if pd.isna(v) else (f"{v:.{d}f}" if isinstance(v, float) else str(v))
        for r in mv.itertuples(index=False):
            P(f"| {r.name} | {r.team} | {f(r.p_bench_4)} | {f(r.p_bench_5)} | {f(r.games_4,1)} | {f(r.games_5,1)} | {f(r.total_4,0)} | {f(r.total_5,0)} | {r.pos_rank_4} | {r.pos_rank_5} | {r.rank_4} | {r.rank_5} | {r.sf12_rank_4} | {r.sf12_rank_5} | "
              + " | ".join(f(getattr(r, c), 1 if c == "ppg26_5" else 0) for c in extra) + " |")
        P(f"  mean P(bench) of week-1 starters: v4 {m.p_bench_4.mean():.3f} -> v5 {m.p_bench_5.mean():.3f}")
    log.close()


if __name__ == "__main__":
    main()
