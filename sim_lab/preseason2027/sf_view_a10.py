#!/usr/bin/env python3
"""A10 output step: v3 lists = v2 numbers (no QB change earned its place on history) + a SUPERFLEX view.
Superflex replacement (review part 21): the last starting QB at 10 / 12 / 14 teams = QB20 / QB24 / QB28; other positions as
12-team half-PPR (RB31 / WR41 / TE12). Keeps v2 files as *_v2.*. Log: output/sf_view_a10.log."""
import os, shutil
import numpy as np
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "output")
REPL_1QB = {"QB": 12, "RB": 31, "WR": 41, "TE": 12}
SF_QB = {10: 20, 12: 24, 14: 28}


def sf_cols(R):
    R = R.copy()
    for t, nq in SF_QB.items():
        q = R[R.pos == "QB"].sort_values("total", ascending=False).total.values
        R[f"qb_vor_sf{t}"] = np.where(R.pos == "QB", R.total - q[min(nq, len(q) - 1)], np.nan)
    repl = {ps: R[R.pos == ps].sort_values("total", ascending=False).total.values[min((SF_QB[12] if ps == "QB" else REPL_1QB[ps]), (R.pos == ps).sum() - 1)] for ps in ("QB", "RB", "WR", "TE")}
    R["vor_sf12"] = R.total - R.pos.map(repl)
    R["sf12_rank"] = R.vor_sf12.rank(ascending=False, method="first").astype(int)
    return R


FMT_RANKS = ["rank_ppr", "pos_rank_ppr", "rank_std", "pos_rank_std"]


def format_ranks(R):
    """PPR / STD overall + position ranks, built exactly like the half-PPR rank in a15_rookies.rank_all: position rank by
    that format's season total (ties by name); overall by VOR over the same 1QB replacement levels (QB12 / RB31 / WR41 /
    TE12), ties by total then name. No-op when the format totals are not present (e.g. the 2026 check)."""
    if "total_ppr" not in R: return R
    R = R.copy()
    for f in ("ppr", "std"):
        t = R[f"total_{f}"].astype(float)
        has = t.notna()
        R[f"pos_rank_{f}"] = np.nan; R[f"rank_{f}"] = np.nan
        X = R[has].assign(_t=t[has])
        X["_pr"] = X.sort_values(["_t", "name"], ascending=[False, True]).groupby("pos").cumcount().reindex(X.index) + 1
        repl = {ps: X[X.pos == ps].sort_values("_t", ascending=False)._t.values[min(REPL_1QB[ps], (X.pos == ps).sum() - 1)] for ps in REPL_1QB if (X.pos == ps).any()}
        X["_v"] = X._t - X.pos.map(repl)
        X = X.sort_values(["_v", "_t", "name"], ascending=[False, False, True]); X["_r"] = np.arange(1, len(X) + 1)
        R.loc[X.index, f"pos_rank_{f}"] = X._pr; R.loc[X.index, f"rank_{f}"] = X._r
        R[f"pos_rank_{f}"] = R[f"pos_rank_{f}"].astype("Int64"); R[f"rank_{f}"] = R[f"rank_{f}"].astype("Int64")
    return R


def md(df, cols, heads):
    L = ["| " + " | ".join(heads) + " |", "|" + "---|" * len(heads)]
    for r in df[cols].itertuples(index=False):
        L.append("| " + " | ".join("" if (isinstance(v, float) and np.isnan(v)) else (f"{v:.1f}" if isinstance(v, float) else str(v)) for v in r) + " |")
    return "\n".join(L)


def main():
    log = open(os.path.join(OUT, "sf_view_a10.log"), "w", encoding="utf-8")
    for base in ("2026_inhouse_check", "2027_inhouse_early"):
        for ext in ("md", "csv"):
            src = os.path.join(OUT, f"{base}.{ext}"); dst = os.path.join(OUT, f"{base}_v2.{ext}")
            if not os.path.exists(dst): shutil.copy(src, dst)
        R = pd.read_csv(os.path.join(OUT, f"{base}.csv"))
        R = format_ranks(sf_cols(R))
        R.to_csv(os.path.join(OUT, f"{base}.csv"), index=False)
        txt = open(os.path.join(OUT, f"{base}.md"), encoding="utf-8").read()
        txt = txt.replace("(no ADP input)", "(no ADP input) - v7", 1)
        Q = R[R.pos == "QB"].sort_values("total", ascending=False).head(32).copy()
        Q["qb_rank"] = range(1, len(Q) + 1)
        cols = ["qb_rank", "name", "team", "ppg", "games", "total", "qb_vor_sf10", "qb_vor_sf12", "qb_vor_sf14", "sf12_rank", "rank"]
        heads = ["QB rk", "Player", "Team", "Proj PPG", "Proj G", "Proj total", "VOR SF 10-tm (QB20)", "VOR SF 12-tm (QB24)", "VOR SF 14-tm (QB28)", "Overall rk, SF 12-tm", "Overall rk, 1QB"]
        if "p_bench" in R:
            cols += ["p_bench"]; heads += ["P(loses job while healthy)"]
        if "adp_rank" in R:
            cols += ["adp_pos_rank", "ppg26", "act_pos_rank"]; heads += ["ADP QB rk", "2026 PPG", "2026 QB rk"]
        top = R.sort_values("sf12_rank").head(24)
        sf = ["", "## Superflex view (v7, A10 + A11 job security + A13 rookie-deal fix; v7 = v5 averages + A14 RB ranges by tier)", "",
              "- QB games include job security (report A11). v5: P(loses job) uses the larger of cap share and draft capital (draft capital fades out over 5 years), so a rookie deal's small cap share no longer reads as a weak hold (report A13).",
              "- Replacement level = the last starting QB: QB20 at 10 teams, QB24 at 12, QB28 at 14.",
              "- The overall superflex rank uses 12 teams, with RB31 / WR41 / TE12 as the other replacement levels.", "",
              md(Q, cols, heads), "", "### Superflex 12-team overall top 24", "",
              md(top, ["sf12_rank", "name", "pos", "team", "total", "vor_sf12", "rank"], ["SF rk", "Player", "Pos", "Team", "Proj total", "VOR (SF 12)", "1QB rk"]), ""]
        open(os.path.join(OUT, f"{base}.md"), "w", encoding="utf-8").write(txt + "\n".join(sf) + "\n")
        log.write(f"{base}: QB top 12 SF12 VOR " + ", ".join(f"{r.name} {r.qb_vor_sf12:.0f}" for r in Q.head(12).itertuples()) + "\n")
        log.write(f"{base}: SF12 overall top 24 " + ", ".join(f"{r.sf12_rank} {r.name} ({r.pos})" for r in top.itertuples()) + "\n")
    log.close()
    print(open(os.path.join(OUT, "sf_view_a10.log"), encoding="utf-8").read())


if __name__ == "__main__":
    main()
