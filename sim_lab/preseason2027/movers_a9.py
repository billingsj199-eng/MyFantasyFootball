#!/usr/bin/env python3
"""v1 -> v2 movers for the 2026 in-house check (A9). Appends a movers section to output/2026_inhouse_check.md and writes
output/2026_movers_v1_to_v2.csv. Log: output/movers_a9.log."""
import os
import numpy as np
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "output")


def main():
    log = open(os.path.join(OUT, "movers_a9.log"), "w", encoding="utf-8")
    def P(s=""):
        print(s); log.write(s + "\n")
    a = pd.read_csv(os.path.join(OUT, "2026_inhouse_check_v1.csv")); b = pd.read_csv(os.path.join(OUT, "2026_inhouse_check.csv"))
    m = b.merge(a, on=["name"], how="outer", suffixes=("", "_v1"))
    m["d_rank"] = m.rank_v1 - m["rank"]; m["d_pos"] = m.pos_rank_v1 - m.pos_rank
    mv = m[(m.d_rank.abs() >= 10) & ((m["rank"] <= 150) | (m.rank_v1 <= 150)) | (m.d_pos.abs() >= 3) & ((m.pos_rank <= 36) | (m.pos_rank_v1 <= 36)) | m.rank_v1.isna() & (m["rank"] <= 150)].copy()
    def why(r):
        if np.isnan(r.rank_v1): return "new to the list (position override)"
        parts = []
        if abs(r.games - r.games_v1) >= 0.5: parts.append(f"games {r.games_v1:.1f} -> {r.games:.1f}")
        if abs(r.ppg - r.ppg_v1) >= 0.2: parts.append(f"PPG {r.ppg_v1:.1f} -> {r.ppg:.1f}")
        return "; ".join(parts) if parts else "others moved around him (replacement level / neighbours)"
    mv["why"] = [why(r) for r in mv.itertuples(index=False)]
    mv = mv.sort_values("d_rank", key=lambda s: -s.abs())
    mv[["name", "pos", "team", "rank_v1", "rank", "pos_rank_v1", "pos_rank", "games_v1", "games", "ppg_v1", "ppg", "why"]].to_csv(os.path.join(OUT, "2026_movers_v1_to_v2.csv"), index=False)
    P(f"movers (10+ overall spots inside the top 150, or 3+ position spots inside the top 36): {len(mv)}")
    for r in mv.head(60).itertuples(index=False):
        P(f"  {r.name:24s} {r.pos} overall {r.rank_v1 if r.rank_v1 == r.rank_v1 else '-'} -> {r.rank:.0f} | pos {r.pos_rank_v1 if r.pos_rank_v1 == r.pos_rank_v1 else '-'} -> {r.pos_rank:.0f} | {r.why}")
    lines = ["", "## Movers v1 -> v2 (A9 fixes)", "",
             f"Players who moved 10+ overall spots inside the top 150, or 3+ position spots inside the top 36: {len(mv)}. Full list: 2026_movers_v1_to_v2.csv.", "",
             "| Player | Pos | Overall v1 -> v2 | Pos v1 -> v2 | Why |", "|---|---|---|---|---|"]
    for r in mv.head(60).itertuples(index=False):
        lines.append(f"| {r.name} | {r.pos} | {'-' if r.rank_v1 != r.rank_v1 else int(r.rank_v1)} -> {int(r.rank)} | {'-' if r.pos_rank_v1 != r.pos_rank_v1 else int(r.pos_rank_v1)} -> {int(r.pos_rank)} | {r.why} |")
    open(os.path.join(OUT, "2026_inhouse_check.md"), "a", encoding="utf-8").write("\n".join(lines) + "\n")
    for n in ("Joe Burrow", "Saquon Barkley", "Travis Hunter", "Blake Corum", "Tyler Allgeier", "Keaton Mitchell", "Jordan Mason", "Jeremiyah Love"):
        x = m[m.name == n]
        if len(x): r = x.iloc[0]; P(f"  CHECK {n}: overall {r.rank_v1} -> {r['rank']} | pos {r.pos_rank_v1} -> {r.pos_rank} | games {r.games_v1} -> {r.games} | total p10-p90 v1 {r.tot_p10_v1:.0f}-{r.tot_p90_v1:.0f} -> {r.tot_p10:.0f}-{r.tot_p90:.0f}")
    log.close()


if __name__ == "__main__":
    main()
