"""Multi-QB stack analysis. Counts, per team:

  n_qb_stacks = number of distinct QBs that have at least one same-NFL-team
                pass-catcher (WR/TE/RB) on the roster.

So a team that drafts Hurts + Brown (PHI) + Mahomes + Kelce (KC) has
n_qb_stacks = 2 (both QBs are stacked with their own team-mate).

Reuses cached nflverse rosters from aggregate_bbm_stack_composition.py.
"""
from __future__ import annotations
import json
import re
import unicodedata
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "Best Ball Mania Files"
ROSTER_DIR = ROOT / "scripts" / "_nflverse_rosters"
OUT = ROOT / "scripts" / "_bbm_multi_qb_stacks.json"

INPUTS = [
    {"name": "IV",  "season": 2023,
     "rd1": BASE/"BBM IV"/"best_ball_mania_iv_2023_r1_results_pick_by_pick.csv",
     "rd2": BASE/"BBM IV"/"best_ball_mania_iv_2023_r2_results_pick_by_pick.csv"},
    {"name": "V",   "season": 2024,
     "rd1": BASE/"BBM V"/"best_ball_mania_v_rd1.csv",
     "rd2": BASE/"BBM V"/"best_ball_mania_v_rd2.csv"},
    {"name": "VI",  "season": 2025,
     "rd1": BASE/"BBM VI"/"best_ball_mania_vi_rd1.csv",
     "rd2": BASE/"BBM VI"/"best_ball_mania_vi_rd2.csv"},
]

_NAME_PUNCT = re.compile(r"[^\w\s]")


def norm_name(name):
    if not isinstance(name, str):
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\.?$", "", s)
    s = _NAME_PUNCT.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def build_name_team_map(roster):
    m = {}
    for _, r in roster.iterrows():
        k = (norm_name(r["full_name"]), r["position"])
        if k not in m:
            m[k] = r["team"]
    return m


def process(spec, name_team):
    name = spec["name"]
    print(f"[multi-qb] {name}: rd2 ...", flush=True)
    rd2 = pd.read_csv(spec["rd2"], usecols=["tournament_entry_id"])
    advanced = set(rd2["tournament_entry_id"].unique())

    print(f"[multi-qb] {name}: rd1 ...", flush=True)
    df = pd.read_csv(spec["rd1"], usecols=[
        "tournament_entry_id", "tournament_round_draft_entry_id",
        "team_pick_number", "position_name", "player_name",
    ])
    keys = list(zip(df["player_name"].map(norm_name), df["position_name"]))
    df["nfl_team"] = [name_team.get(k) for k in keys]

    team_key = "tournament_round_draft_entry_id"
    df = df.sort_values([team_key, "team_pick_number"], kind="stable").reset_index(drop=True)

    # For each pick, lookup of (team_id, nfl_team) tells us if a pass-catcher
    # at nfl_team has any QB on this team at the same NFL team. Two passes:
    # 1. Build per-team set of QB nfl_teams (drop NAs).
    # 2. For each pass-catcher, check membership; flag is_stacked True if its
    #    nfl_team appears in the team's QB-team set.
    is_qb = df["position_name"] == "QB"
    qb_picks = df[is_qb & df["nfl_team"].notna()][[team_key, "nfl_team"]]

    # Per-team count of distinct QB-teams that overlap a pass-catcher's team.
    skill = df["position_name"].isin(["WR", "TE", "RB"])
    pc_picks = df[skill & df["nfl_team"].notna()][[team_key, "nfl_team"]]

    # For each (team_id, nfl_team), is there both a QB at that team and a
    # pass-catcher at that team? Inner join on (team_id, nfl_team).
    overlap = qb_picks.merge(
        pc_picks, on=[team_key, "nfl_team"], how="inner"
    )[[team_key, "nfl_team"]].drop_duplicates()
    # `overlap` now has one row per (team_id, nfl_team) where the team has
    # both a QB and a same-team pass-catcher. Count rows per team_id =
    # number of distinct QB-stacks.
    n_qb_stacks = overlap.groupby(team_key).size().rename("n_qb_stacks")

    teams = df.drop_duplicates(team_key)[[team_key, "tournament_entry_id"]]
    teams = teams.merge(n_qb_stacks, on=team_key, how="left").fillna({"n_qb_stacks": 0})
    teams["n_qb_stacks"] = teams["n_qb_stacks"].astype("int8")
    teams["adv"] = teams["tournament_entry_id"].isin(advanced).astype(int)
    teams["bbm"] = name

    print(
        f"[multi-qb] {name}:   teams: {len(teams):,}  "
        f"distribution: " + ", ".join(
            f"{int(k)}={v:,}" for k, v in
            teams["n_qb_stacks"].value_counts().sort_index().items()
        ),
        flush=True,
    )
    return teams


def main():
    rosters = {}
    for season in (2023, 2024, 2025):
        rosters[season] = pd.read_csv(
            ROSTER_DIR / f"roster_{season}.csv",
            usecols=["season", "team", "position", "full_name"],
        )
        rosters[season] = rosters[season][
            rosters[season]["position"].isin(["QB", "RB", "WR", "TE", "FB", "HB"])
        ].copy()
        rosters[season]["position"] = rosters[season]["position"].replace(
            {"FB": "RB", "HB": "RB"}
        )

    name_team_by_season = {s: build_name_team_map(r) for s, r in rosters.items()}

    frames = []
    for spec in INPUTS:
        nt = name_team_by_season[spec["season"]]
        frames.append(process(spec, nt))

    teams = pd.concat(frames, ignore_index=True)
    print(f"\n[multi-qb] combined teams: {len(teams):,}", flush=True)
    base = teams["adv"].mean()
    print(f"[multi-qb] overall baseline q_rate: {base:.4f}\n", flush=True)

    print("=== ADVANCE RATE BY # OF DISTINCT QB STACKS ===", flush=True)
    print(f"{'n_qb_stacks':>13} | {'n':>10} | {'q_rate':>7} | {'lift':>5} | {'+/-pp':>6}", flush=True)
    print("-" * 60, flush=True)
    out = {}
    for n in sorted(teams["n_qb_stacks"].unique()):
        sub = teams[teams["n_qb_stacks"] == n]
        if len(sub) < 200:
            continue
        q = sub["adv"].mean()
        out[int(n)] = {"n": int(len(sub)), "q_rate": round(float(q), 4), "lift": round(float(q / base), 3)}
        print(
            f"{int(n):>13} | {len(sub):>10,} | {q:>7.4f} | {q / base:>5.2f} | "
            f"{(q - base) * 100:>+6.2f}",
            flush=True,
        )

    # Per-year stability
    print("\n=== YEAR-OVER-YEAR STABILITY ===", flush=True)
    per_year = {}
    for yr in sorted(teams["bbm"].unique()):
        sy = teams[teams["bbm"] == yr]
        b = sy["adv"].mean()
        per_year[yr] = {}
        line = f"  {yr}:"
        for n in sorted(sy["n_qb_stacks"].unique()):
            ss = sy[sy["n_qb_stacks"] == n]
            if len(ss) < 100:
                continue
            q = ss["adv"].mean()
            per_year[yr][int(n)] = round(float(q / b), 3)
            line += f"  n_qb={int(n)}: lift={q/b:.3f} (n={len(ss):,})"
        print(line, flush=True)

    obj = {
        "by_n_qb_stacks": out,
        "per_year": per_year,
        "overall_baseline": round(float(base), 4),
        "total_teams": int(len(teams)),
    }
    with OUT.open("w") as f:
        json.dump(obj, f, indent=2)
    print(f"\n[multi-qb] wrote {OUT.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
