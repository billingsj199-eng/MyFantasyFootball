"""Aggregate BBM IV / V / VI round-1 (regular season) results into a
slot-aware build table. Output is a JSON map shaped:

    {
      "<slot>|<Q>/<R>/<W>/<T>": { "n": int, "q": int, "q_rate": float },
      ...
    }

Where slot is the user's draft slot (1-12), build is the QB/RB/WR/TE count
tuple, n is the number of historical teams matching that (slot, build),
q is how many advanced to the playoff bracket, q_rate = q / n.

Round 1 of each tournament is the regular season; advance is captured by
`made_playoffs`. We intentionally skip rounds 2-4 since those are bracket
rounds with different team-count and outcome semantics.

Outputs to: underdog-extension/data/bbm_slot_build.json
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent.parent / "Best Ball Mania Files"
OUT = Path(__file__).resolve().parent.parent / "underdog-extension" / "data" / "bbm_slot_build.json"

# `made_playoffs` is unfilled (always 0) in the round-1 CSVs. Instead we
# derive advance from the round-2 file: any tournament_entry_id present in
# round 2 advanced from round 1.
INPUTS = [
    {
        "name": "BBM IV",
        "rd1": BASE / "BBM IV" / "best_ball_mania_iv_2023_r1_results_pick_by_pick.csv",
        "rd2": BASE / "BBM IV" / "best_ball_mania_iv_2023_r2_results_pick_by_pick.csv",
    },
    {
        "name": "BBM V",
        "rd1": BASE / "BBM V" / "best_ball_mania_v_rd1.csv",
        "rd2": BASE / "BBM V" / "best_ball_mania_v_rd2.csv",
    },
    {
        "name": "BBM VI",
        "rd1": BASE / "BBM VI" / "best_ball_mania_vi_rd1.csv",
        "rd2": BASE / "BBM VI" / "best_ball_mania_vi_rd2.csv",
    },
]

USECOLS_RD1 = [
    "draft_id",
    "tournament_entry_id",
    "tournament_round_draft_entry_id",
    "pick_order",
    "position_name",
]
USECOLS_RD2 = ["tournament_entry_id"]


def process_tournament(spec: dict) -> pd.DataFrame:
    name = spec["name"]
    print(f"[bbm-slot-build] {name}: reading rd2 advance set ...", flush=True)
    rd2 = pd.read_csv(spec["rd2"], usecols=USECOLS_RD2)
    advanced = set(rd2["tournament_entry_id"].unique())
    print(f"[bbm-slot-build] {name}:   advanced teams: {len(advanced):,}", flush=True)

    print(f"[bbm-slot-build] {name}: reading rd1 ...", flush=True)
    df = pd.read_csv(spec["rd1"], usecols=USECOLS_RD1)
    print(f"[bbm-slot-build] {name}:   rows: {len(df):,}", flush=True)

    # One row per team, with slot. Advance derived by membership in rd2 set.
    team_meta = (
        df.groupby(["draft_id", "tournament_round_draft_entry_id"])
        .agg(
            slot=("pick_order", "first"),
            tournament_entry_id=("tournament_entry_id", "first"),
        )
        .reset_index()
    )
    team_meta["made_playoffs"] = team_meta["tournament_entry_id"].isin(advanced).astype(int)

    # Position counts per team — pivot positions into columns.
    counts = (
        df.groupby(["draft_id", "tournament_round_draft_entry_id", "position_name"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )
    for col in ("QB", "RB", "WR", "TE"):
        if col not in counts.columns:
            counts[col] = 0
    teams = team_meta.merge(
        counts[["draft_id", "tournament_round_draft_entry_id", "QB", "RB", "WR", "TE"]],
        on=["draft_id", "tournament_round_draft_entry_id"],
    )
    advance_rate = teams["made_playoffs"].mean()
    print(
        f"[bbm-slot-build] {name}:   teams: {len(teams):,} "
        f"(advance rate: {advance_rate:.4f})",
        flush=True,
    )
    return teams


def main() -> None:
    frames: list[pd.DataFrame] = []
    for spec in INPUTS:
        if not spec["rd1"].exists() or not spec["rd2"].exists():
            print(f"[bbm-slot-build] WARN: missing files for {spec['name']}", flush=True)
            continue
        frames.append(process_tournament(spec))
    if not frames:
        raise SystemExit("[bbm-slot-build] no inputs found")

    teams = pd.concat(frames, ignore_index=True)
    print(f"[bbm-slot-build] combined teams: {len(teams):,}", flush=True)

    # Build composite key: "<slot>|<Q>/<R>/<W>/<T>"
    teams["build"] = (
        teams["QB"].astype(str)
        + "/"
        + teams["RB"].astype(str)
        + "/"
        + teams["WR"].astype(str)
        + "/"
        + teams["TE"].astype(str)
    )
    grp = (
        teams.groupby(["slot", "build"])
        .agg(n=("made_playoffs", "count"), q=("made_playoffs", "sum"))
        .reset_index()
    )
    grp["q_rate"] = (grp["q"] / grp["n"]).round(4)
    grp = grp[grp["n"] >= 100]  # drop tiny cells (>=100 teams ≈ stable rate)
    print(f"[bbm-slot-build] (slot, build) cells with n>=100: {len(grp):,}", flush=True)

    # Also compute per-slot baselines for unknown builds.
    slot_baselines = (
        teams.groupby("slot")
        .agg(n=("made_playoffs", "count"), q=("made_playoffs", "sum"))
        .reset_index()
    )
    slot_baselines["q_rate"] = (slot_baselines["q"] / slot_baselines["n"]).round(4)
    print("[bbm-slot-build] per-slot baseline q_rates:", flush=True)
    for _, r in slot_baselines.iterrows():
        print(f"  slot {int(r['slot']):>2}: n={int(r['n']):>7,} q_rate={r['q_rate']:.4f}", flush=True)

    # Emit JSON.
    out = {
        "by_slot_build": {
            f"{int(r['slot'])}|{r['build']}": {
                "n": int(r["n"]),
                "q": int(r["q"]),
                "q_rate": float(r["q_rate"]),
            }
            for _, r in grp.iterrows()
        },
        "by_slot_baseline": {
            int(r["slot"]): {
                "n": int(r["n"]),
                "q": int(r["q"]),
                "q_rate": float(r["q_rate"]),
            }
            for _, r in slot_baselines.iterrows()
        },
        "meta": {
            "total_teams": int(len(teams)),
            "tournaments": ["BBM IV", "BBM V", "BBM VI"],
            "min_cell_n": 100,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        json.dump(out, f, separators=(",", ":"))
    size_kb = OUT.stat().st_size / 1024
    print(f"[bbm-slot-build] wrote {OUT.relative_to(OUT.parent.parent.parent)} ({size_kb:.1f} KB)", flush=True)


if __name__ == "__main__":
    main()
