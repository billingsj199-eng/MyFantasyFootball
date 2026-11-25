#!/usr/bin/env python3
"""A14 v5 -> v7 RB comparison: RB top 36 before/after, 3+ spot movers, named backs across versions, team backfield table.
Log: output/rb_movers_a14.log (opened in main())."""
import os
import numpy as np, pandas as pd
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
NAMED = ["Saquon Barkley", "Jeremiyah Love", "De'Von Achane", "Blake Corum", "Tyler Allgeier", "Keaton Mitchell", "Jordan Mason"]


def f(v, d=1):
    if v is None or (isinstance(v, float) and np.isnan(v)): return ""
    return f"{v:.{d}f}" if isinstance(v, float) else str(v)


def main():
    log = open(os.path.join(OUT, "rb_movers_a14.log"), "w", encoding="utf-8")
    def P(s=""):
        print(s); log.write(s + "\n")
    for base in ("2026_inhouse_check", "2027_inhouse_early"):
        a = pd.read_csv(os.path.join(OUT, f"{base}_v5.csv")); b = pd.read_csv(os.path.join(OUT, f"{base}.csv"))
        a = a[a.pos == "RB"]; b = b[b.pos == "RB"]
        m = b.merge(a[["name", "team", "pos_rank", "ppg", "games", "total", "rank", "tot_p10", "tot_p90"]], on=["name", "team"], suffixes=("", "_5"), how="left")
        m["move"] = m.pos_rank_5 - m.pos_rank
        has26 = "act_pos_rank" in m
        P(f"\n=== {base}: RB top 36, v5 -> v7 ===")
        P("| v7 RB rk | v5 RB rk | back | team | tier | PPG v5 -> v7 | games | carries/g | targets/g | total v5 -> v7 | range v7 |" + (" ADP RB rk | 2026 PPG | 2026 G | 2026 RB rk |" if has26 else " 2026 PPG |"))
        P("|---|---|---|---|---|---|---|---|---|---|---|" + ("---|---|---|---|" if has26 else "---|"))
        for r in m.sort_values("pos_rank").head(36).itertuples(index=False):
            ext = f" {f(r.adp_pos_rank,0)} | {f(r.ppg26)} | {f(r.g26,0)} | {f(r.act_pos_rank,0)} |" if has26 else f" {f(r.ppg26)} |"
            P(f"| {r.pos_rank} | {f(r.pos_rank_5,0)} | {r.name} | {r.team} | {r.rb_tier} | {r.ppg_5:.1f} -> {r.ppg:.1f} | {r.games:.1f} | {f(r.rb_car_pg)} | {f(r.rb_tgt_pg)} | {r.total_5:.0f} -> {r.total:.0f} | {r.tot_p10:.0f}-{r.tot_p90:.0f} |" + ext)
        mv = m[(m.move.abs() >= 3) & ((m.pos_rank <= 60) | (m.pos_rank_5 <= 60))].sort_values("move")
        P(f"\n  RBs (top 60 either version) that moved 3+ spots: {len(mv)}")
        P("| back | team | tier | RB rk v5 -> v7 | PPG v5 -> v7 | carries/g (v5 volume) | targets/g (v5 volume) | team RB carries/g (model) |" + (" ADP RB rk | 2026 RB rk |" if has26 else ""))
        P("|---|---|---|---|---|---|---|---|" + ("---|---|" if has26 else ""))
        for r in mv.itertuples(index=False):
            P(f"| {r.name} | {r.team} | {r.rb_tier} | {f(r.pos_rank_5,0)} -> {r.pos_rank} | {r.ppg_5:.1f} -> {r.ppg:.1f} | {f(r.rb_car_pg)} | {f(r.rb_tgt_pg)} | {f(r.T_car_hat)} |" + (f" {f(r.adp_pos_rank,0)} | {f(r.act_pos_rank,0)} |" if has26 else ""))
        P(f"  RB moves: mean |change in RB rank| top 36 = {m[m.pos_rank <= 36].move.abs().mean():.1f}; top-36 overlap v5/v7 {len(set(m[m.pos_rank <= 36].name) & set(m[m.pos_rank_5 <= 36].name))}/36")
        if has26:
            vs = {}
            for v in ("v1", "v2", "v3", "v4", "v5", "v6"):
                p_ = os.path.join(OUT, f"{base}_{v}.csv")
                if os.path.exists(p_): x = pd.read_csv(p_); vs[v] = x[x.pos == "RB"].set_index("name").pos_rank
            P("\n  backs that looked wrong in the first list: RB rank by version, ADP, 2026 so far")
            P("| back | " + " | ".join(vs) + " | v7 | ADP RB rk | 2026 PPG | 2026 G | 2026 RB rk |")
            P("|---|" + "---|" * (len(vs) + 5))
            for n in NAMED:
                r = m[m.name == n]
                if not len(r): P(f"| {n} | not in list |"); continue
                r = r.iloc[0]
                P(f"| {n} | " + " | ".join(f(vs[v].get(n, np.nan), 0) if not isinstance(vs[v].get(n, np.nan), pd.Series) else str(vs[v].get(n).iloc[0]) for v in vs) + f" | {r.pos_rank} | {f(r.adp_pos_rank,0)} | {f(r.ppg26)} | {f(r.g26,0)} | {f(r.act_pos_rank,0)} |")
        # team backfield table
        P(f"\n  team backfields ({base}): each listed back's carries and targets per TEAM game (= per game played x games/17); listed backs' sum vs the team-total model. Built from v7 = v5 RB volumes; the team-total model is information only (the rescale is off)")
        P("| team | backs (car / tgt per team game) | sum car | model car | sum tgt | model tgt |")
        P("|---|---|---|---|---|---|")
        b2 = m[m.rb_car_pg.notna()].copy(); b2["c_tg"] = b2.rb_car_pg * b2.games / 17; b2["t_tg"] = b2.rb_tgt_pg * b2.games / 17
        for t, g in b2.sort_values("c_tg", ascending=False).groupby("team"):
            g = g[(g.c_tg >= .5) | (g.t_tg >= .3)]
            if not len(g): continue
            P(f"| {t} | " + "; ".join(f"{r.name} {r.c_tg:.1f} / {r.t_tg:.1f}" for r in g.itertuples(index=False)) + f" | {g.c_tg.sum():.1f} | {g.T_car_hat.iloc[0]:.1f} | {g.t_tg.sum():.1f} | {g.T_tgt_hat.iloc[0]:.1f} |")
    log.close()


if __name__ == "__main__":
    main()
