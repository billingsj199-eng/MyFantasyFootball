"""Per-position, per-rank, per-round advance rate analysis.

For each BBM team, identifies the ROUND in which they took:
  QB1, QB2, QB3, QB4
  RB1, RB2, RB3, ... RB7
  WR1, WR2, WR3, ... WR9
  TE1, TE2, TE3, TE4

Then computes advance rate (-> QF, -> SF, -> Finals) for each
(position, positional_rank, round) bucket across all 5 BBMs.

Also identifies "didn't take" cohorts (e.g., teams that drafted only 4 WRs).

Outputs scripts/_bbm_pos_rank_round.json + console tables.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "Best Ball Mania Files"
DBOWL = BASE / "best-ball-data-bowl-master" / "best-ball-data-bowl-master" / "data"
OUT = ROOT / "scripts" / "_bbm_pos_rank_round.json"


def _glob(pat: Path) -> list[Path]:
    return sorted(pat.parent.glob(pat.name))


INPUTS = [
    {"name": "II", "season": 2021, "team_key": "tournament_entry_id",
     "rd1": _glob(DBOWL/"2021"/"regular_season"/"part_*.csv"),
     "rd2": [DBOWL/"2021"/"post_season"/"quarterfinals.csv"],
     "rd3": [DBOWL/"2021"/"post_season"/"semifinals.csv"],
     "rd4": [DBOWL/"2021"/"post_season"/"finals.csv"]},
    {"name": "III", "season": 2022, "team_key": "tournament_round_draft_entry_id",
     "rd1": (_glob(DBOWL/"2022"/"regular_season"/"fast"/"part_*.csv") +
             _glob(DBOWL/"2022"/"regular_season"/"mixed"/"part_*.csv")),
     "rd2": _glob(DBOWL/"2022"/"post_season"/"quarterfinals"/"part_*.csv"),
     "rd3": _glob(DBOWL/"2022"/"post_season"/"semifinals"/"part_*.csv"),
     "rd4": _glob(DBOWL/"2022"/"post_season"/"finals"/"part_*.csv")},
    {"name": "IV", "season": 2023, "team_key": "tournament_round_draft_entry_id",
     "rd1": [BASE/"BBM IV"/"best_ball_mania_iv_2023_r1_results_pick_by_pick.csv"],
     "rd2": [BASE/"BBM IV"/"best_ball_mania_iv_2023_r2_results_pick_by_pick.csv"],
     "rd3": [BASE/"BBM IV"/"best_ball_mania_iv_2023_r3_results_pick_by_pick.csv"],
     "rd4": [BASE/"BBM IV"/"best_ball_mania_iv_2023_r4_results_pick_by_pick.csv"]},
    {"name": "V", "season": 2024, "team_key": "tournament_round_draft_entry_id",
     "rd1": [BASE/"BBM V"/"best_ball_mania_v_rd1.csv"],
     "rd2": [BASE/"BBM V"/"best_ball_mania_v_rd2.csv"],
     "rd3": [BASE/"BBM V"/"best_ball_mania_v_rd3.csv"],
     "rd4": [BASE/"BBM V"/"best_ball_mania_v_rd4.csv"]},
    {"name": "VI", "season": 2025, "team_key": "tournament_round_draft_entry_id",
     "rd1": [BASE/"BBM VI"/"best_ball_mania_vi_rd1.csv"],
     "rd2": [BASE/"BBM VI"/"best_ball_mania_vi_rd2.csv"],
     "rd3": [BASE/"BBM VI"/"best_ball_mania_vi_rd3.csv"],
     "rd4": [BASE/"BBM VI"/"best_ball_mania_vi_rd4.csv"]},
]


def read_rd1(spec):
    cols_base = ["tournament_entry_id","team_pick_number","position_name"]
    cols = cols_base + ([spec["team_key"]] if spec["team_key"] == "tournament_round_draft_entry_id" else [])
    frames = []
    for f in spec["rd1"]:
        first = pd.read_csv(f, nrows=0).columns.tolist()
        use = [c for c in cols if c in first]
        frames.append(pd.read_csv(f, usecols=use))
    df = pd.concat(frames, ignore_index=True)
    if "tournament_round_draft_entry_id" not in df.columns:
        df["tournament_round_draft_entry_id"] = df[spec["team_key"]]
    return df


def read_advance_set(files):
    if not files: return set()
    frames = []
    for f in files:
        if not Path(f).exists(): continue
        frames.append(pd.read_csv(f, usecols=["tournament_entry_id"]))
    if not frames: return set()
    return set(pd.concat(frames, ignore_index=True)["tournament_entry_id"].unique())


def per_team_pos_rounds(df: pd.DataFrame) -> pd.DataFrame:
    """For each team, returns one row with columns
    qb_r1, qb_r2, qb_r3, qb_r4, rb_r1..rb_r7, wr_r1..wr_r9, te_r1..te_r4 = round drafted (NaN if not drafted)."""
    tk = "tournament_round_draft_entry_id"
    df = df[df["position_name"].isin(["QB","RB","WR","TE"])].copy()
    df = df.sort_values([tk, "team_pick_number"], kind="stable").reset_index(drop=True)
    df["pos_rank"] = df.groupby([tk, "position_name"]).cumcount() + 1

    max_ranks = {"QB": 4, "RB": 7, "WR": 9, "TE": 4}
    cap = df["position_name"].map(max_ranks)
    df = df[df["pos_rank"] <= cap]

    df["col"] = df["position_name"].str.lower() + "_r" + df["pos_rank"].astype(str)
    pivot = df.pivot_table(index=tk, columns="col", values="team_pick_number", aggfunc="first")
    pivot = pivot.reset_index()
    return pivot


def main():
    all_rows = []
    for spec in INPUTS:
        print(f"\n[prr] === BBM {spec['name']} (season {spec['season']}) ===", flush=True)
        df = read_rd1(spec)
        print(f"[prr]   rd1 rows {len(df):,}", flush=True)

        per_team = per_team_pos_rounds(df)

        # Map back tournament_entry_id (advance flag join key)
        tk = "tournament_round_draft_entry_id"
        eid = df.drop_duplicates(tk)[[tk, "tournament_entry_id"]]
        per_team = per_team.merge(eid, on=tk, how="left")

        adv_qf  = read_advance_set(spec["rd2"])
        adv_sf  = read_advance_set(spec["rd3"])
        adv_fin = read_advance_set(spec["rd4"])
        per_team["adv_qf"]  = per_team["tournament_entry_id"].isin(adv_qf).astype(int)
        per_team["adv_sf"]  = per_team["tournament_entry_id"].isin(adv_sf).astype(int)
        per_team["adv_fin"] = per_team["tournament_entry_id"].isin(adv_fin).astype(int)
        per_team["bbm"] = spec["name"]
        per_team["season"] = spec["season"]

        print(f"[prr]   teams {len(per_team):,}  qf:{per_team['adv_qf'].sum():,}  sf:{per_team['adv_sf'].sum():,}  fin:{per_team['adv_fin'].sum():,}", flush=True)
        all_rows.append(per_team)

    teams = pd.concat(all_rows, ignore_index=True)
    n = len(teams)
    base_qf  = teams["adv_qf"].mean()
    base_sf  = teams["adv_sf"].mean()
    base_fin = teams["adv_fin"].mean()
    print(f"\n[prr] combined: {n:,} teams", flush=True)
    print(f"[prr]   baselines  qf {base_qf:.4%}  sf {base_sf:.4%}  fin {base_fin:.4%}", flush=True)

    out = {
        "n_total": int(n),
        "baselines": {"qf": round(float(base_qf),5), "sf": round(float(base_sf),5), "fin": round(float(base_fin),5)},
        "by_position_rank": {},
        "didnt_take": {},
    }

    # ---- Per (position, rank, round) ----
    cohort_specs = [
        ("QB", 1, 1, 18), ("QB", 2, 2, 18), ("QB", 3, 4, 18), ("QB", 4, 6, 18),
        ("RB", 1, 1, 18), ("RB", 2, 1, 18), ("RB", 3, 2, 18), ("RB", 4, 4, 18),
        ("RB", 5, 6, 18), ("RB", 6, 8, 18), ("RB", 7, 10, 18),
        ("WR", 1, 1, 18), ("WR", 2, 1, 18), ("WR", 3, 2, 18), ("WR", 4, 3, 18),
        ("WR", 5, 5, 18), ("WR", 6, 7, 18), ("WR", 7, 9, 18), ("WR", 8, 11, 18),
        ("TE", 1, 1, 18), ("TE", 2, 4, 18), ("TE", 3, 8, 18),
    ]

    for pos, rank, lo_r, hi_r in cohort_specs:
        col = f"{pos.lower()}_r{rank}"
        if col not in teams.columns: continue
        bucket = {}
        # Build per-round sub-rates
        for rnd in range(lo_r, hi_r + 1):
            sub = teams[teams[col] == rnd]
            n_sub = len(sub)
            if n_sub < 200: continue
            qf, sf, fin = sub["adv_qf"].mean(), sub["adv_sf"].mean(), sub["adv_fin"].mean()
            bucket[str(rnd)] = {
                "n": int(n_sub),
                "qf_rate": round(float(qf), 5),
                "qf_lift": round(float(qf/base_qf), 3) if base_qf else None,
                "sf_rate": round(float(sf), 5),
                "sf_lift": round(float(sf/base_sf), 3) if base_sf else None,
                "fin_rate": round(float(fin), 5),
                "fin_lift": round(float(fin/base_fin), 3) if base_fin else None,
            }
        if bucket:
            # Find best window by qf_lift
            best_round = max(bucket.items(), key=lambda kv: kv[1]["qf_lift"] or 0)
            out["by_position_rank"][col] = {
                "pos": pos, "rank": rank,
                "rounds": bucket,
                "best_round": int(best_round[0]),
                "best_qf_lift": best_round[1]["qf_lift"],
            }

    # ---- "Didn't take" cohorts ----
    didnt_specs = [
        ("QB", 2), ("QB", 3),
        ("RB", 4), ("RB", 5), ("RB", 6),
        ("WR", 5), ("WR", 6), ("WR", 7), ("WR", 8),
        ("TE", 2), ("TE", 3),
    ]
    for pos, rank in didnt_specs:
        col = f"{pos.lower()}_r{rank}"
        if col not in teams.columns: continue
        sub = teams[teams[col].isna()]
        if len(sub) < 200: continue
        qf, sf, fin = sub["adv_qf"].mean(), sub["adv_sf"].mean(), sub["adv_fin"].mean()
        out["didnt_take"][f"no_{col}"] = {
            "pos": pos, "rank": rank,
            "n": int(len(sub)),
            "qf_rate": round(float(qf), 5),
            "qf_lift": round(float(qf/base_qf), 3) if base_qf else None,
            "sf_lift": round(float(sf/base_sf), 3) if base_sf else None,
            "fin_lift": round(float(fin/base_fin), 3) if base_fin else None,
        }

    # ---- Print top tables ----
    def print_pos_table(pos: str, ranks: list[int]):
        print(f"\n=== {pos} per-rank-per-round advance rates (lift vs baseline QF) ===", flush=True)
        # Header
        rounds_to_show = list(range(1, 19))
        hdr = f"{'pick':>6} | " + " ".join(f"r{r:<2}" for r in rounds_to_show)
        print(hdr, flush=True)
        print("-" * len(hdr), flush=True)
        for rnk in ranks:
            col = f"{pos.lower()}_r{rnk}"
            if col not in out["by_position_rank"]: continue
            data = out["by_position_rank"][col]["rounds"]
            row = f"{pos}{rnk:>2}".rjust(6) + " | "
            for r in rounds_to_show:
                if str(r) in data:
                    lift = data[str(r)]["qf_lift"]
                    row += f"{lift:>3.2f} "
                else:
                    row += "  -  "
            # show didnt-take if applicable
            no_key = f"no_{col}"
            if no_key in out["didnt_take"]:
                lift = out["didnt_take"][no_key]["qf_lift"]
                row += f"  none={lift:>4.2f}"
            print(row, flush=True)

    print_pos_table("QB", [1,2,3,4])
    print_pos_table("RB", [1,2,3,4,5,6,7])
    print_pos_table("WR", [1,2,3,4,5,6,7,8])
    print_pos_table("TE", [1,2,3])

    # ---- Construction-score helper: best-round windows + lift gradient ----
    print("\n=== Sweet-spot rounds (best QF lift per pick) ===", flush=True)
    print(f"{'pick':>6} | {'best_round':>10} | {'best_lift':>9} | {'didnt_take_lift':>16}", flush=True)
    print("-" * 60, flush=True)
    for col, info in out["by_position_rank"].items():
        no_key = f"no_{col}"
        no_lift = out["didnt_take"][no_key]["qf_lift"] if no_key in out["didnt_take"] else None
        no_str = f"{no_lift:.2f}" if no_lift is not None else "always taken"
        print(f"{info['pos']}{info['rank']:>2}".rjust(6) + f" | {info['best_round']:>10} | {info['best_qf_lift']:>9.3f} | {no_str:>16}", flush=True)

    with OUT.open("w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[prr] wrote {OUT.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
