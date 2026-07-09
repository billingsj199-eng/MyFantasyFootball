"""Round-by-round advance-rate analysis across BBM II-VI.

For every team, captures their structural roster features (stack composition,
RB cannibalization, WR-no-QB cannibalization, bye concentration, n_qb_stacks,
total_stack) and four advance flags:

  adv_qf   = made the Quarterfinals (top 2 of 12 from regular season)   ~17%
  adv_sf   = made the Semifinals    (top 2 of 12 from quarterfinals)    ~3%
  adv_fin  = made the Finals        (top 2 of 12 from semifinals)       ~0.5%
  won      = won the Finals         (1 winner per finals contest)       <0.01%

Each feature is then aggregated separately at each round level so we can see
how the same structural rule (e.g. "QB+WR1 stack") affects advance rate at
each progressively harder cut.

Outputs scripts/_bbm_round_levels.json.

2020 (BBM I) is omitted because its CSV has no position column, which we
need for stack composition. 2021/2022 use the data-bowl repo schemas;
2023/2024/2025 use the standalone BBM IV/V/VI files.
"""
from __future__ import annotations
import json
import re
import unicodedata
import urllib.request
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "Best Ball Mania Files"
DBOWL = BASE / "best-ball-data-bowl-master" / "best-ball-data-bowl-master" / "data"
ROSTER_DIR = ROOT / "scripts" / "_nflverse_rosters"
OUT = ROOT / "scripts" / "_bbm_round_levels.json"


def _glob(pat: Path) -> list[Path]:
    return sorted(pat.parent.glob(pat.name))


# Each spec lists rd1 + rd2 (qfinals) + rd3 (semifinals) + rd4 (finals)
# CSV file paths. The team's tournament_entry_id present in each round file
# = they advanced through the previous level.
INPUTS = [
    {
        "name": "II", "season": 2021, "team_key": "tournament_entry_id",
        "rd1": _glob(DBOWL/"2021"/"regular_season"/"part_*.csv"),
        "rd2": [DBOWL/"2021"/"post_season"/"quarterfinals.csv"],
        "rd3": [DBOWL/"2021"/"post_season"/"semifinals.csv"],
        "rd4": [DBOWL/"2021"/"post_season"/"finals.csv"],
    },
    {
        "name": "III", "season": 2022, "team_key": "tournament_round_draft_entry_id",
        "rd1": (_glob(DBOWL/"2022"/"regular_season"/"fast"/"part_*.csv") +
                _glob(DBOWL/"2022"/"regular_season"/"mixed"/"part_*.csv")),
        "rd2": _glob(DBOWL/"2022"/"post_season"/"quarterfinals"/"part_*.csv"),
        "rd3": _glob(DBOWL/"2022"/"post_season"/"semifinals"/"part_*.csv"),
        "rd4": _glob(DBOWL/"2022"/"post_season"/"finals"/"part_*.csv"),
    },
    {
        "name": "IV", "season": 2023, "team_key": "tournament_round_draft_entry_id",
        "rd1": [BASE/"BBM IV"/"best_ball_mania_iv_2023_r1_results_pick_by_pick.csv"],
        "rd2": [BASE/"BBM IV"/"best_ball_mania_iv_2023_r2_results_pick_by_pick.csv"],
        "rd3": [BASE/"BBM IV"/"best_ball_mania_iv_2023_r3_results_pick_by_pick.csv"],
        "rd4": [BASE/"BBM IV"/"best_ball_mania_iv_2023_r4_results_pick_by_pick.csv"],
    },
    {
        "name": "V", "season": 2024, "team_key": "tournament_round_draft_entry_id",
        "rd1": [BASE/"BBM V"/"best_ball_mania_v_rd1.csv"],
        "rd2": [BASE/"BBM V"/"best_ball_mania_v_rd2.csv"],
        "rd3": [BASE/"BBM V"/"best_ball_mania_v_rd3.csv"],
        "rd4": [BASE/"BBM V"/"best_ball_mania_v_rd4.csv"],
    },
    {
        "name": "VI", "season": 2025, "team_key": "tournament_round_draft_entry_id",
        "rd1": [BASE/"BBM VI"/"best_ball_mania_vi_rd1.csv"],
        "rd2": [BASE/"BBM VI"/"best_ball_mania_vi_rd2.csv"],
        "rd3": [BASE/"BBM VI"/"best_ball_mania_vi_rd3.csv"],
        "rd4": [BASE/"BBM VI"/"best_ball_mania_vi_rd4.csv"],
    },
]

ROSTER_URLS = {
    2021: "https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2021.csv",
    2022: "https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2022.csv",
    2023: "https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2023.csv",
    2024: "https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2024.csv",
    2025: "https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2025.csv",
}

_NAME_PUNCT = re.compile(r"[^\w\s]")


def norm_name(name):
    if not isinstance(name, str): return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii","ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\.?$", "", s)
    s = _NAME_PUNCT.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def fetch_roster(season: int) -> pd.DataFrame:
    cache = ROSTER_DIR / f"roster_{season}.csv"
    if not cache.exists():
        ROSTER_DIR.mkdir(parents=True, exist_ok=True)
        url = ROSTER_URLS[season]
        print(f"[lvl] downloading roster_{season}.csv ...", flush=True)
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r, cache.open("wb") as f:
            f.write(r.read())
    df = pd.read_csv(cache, usecols=["season","team","position","full_name"])
    df = df[df["position"].isin(["QB","RB","WR","TE","FB","HB"])].copy()
    df["position"] = df["position"].replace({"FB":"RB","HB":"RB"})
    return df


def build_name_team(roster: pd.DataFrame) -> dict:
    m = {}
    for _, r in roster.iterrows():
        k = (norm_name(r["full_name"]), r["position"])
        if k not in m: m[k] = r["team"]
    return m


def read_advance_set(files: list[Path]) -> set:
    """Read the union of tournament_entry_ids across the given list of
    post-season CSVs. Membership = the team advanced into that round."""
    if not files:
        return set()
    frames = []
    for f in files:
        if not Path(f).exists():
            print(f"[lvl]   WARN missing {f}", flush=True)
            continue
        frames.append(pd.read_csv(f, usecols=["tournament_entry_id"]))
    if not frames: return set()
    df = pd.concat(frames, ignore_index=True)
    return set(df["tournament_entry_id"].unique())


def read_finals_winners(files: list[Path]) -> set:
    """Per finals contest pool, the team with the highest roster_points wins.
    Returns the set of tournament_entry_ids that finished #1 in their pool.
    For BBM, we identify pools by draft_id."""
    if not files: return set()
    cols = ["tournament_entry_id", "draft_id", "roster_points"]
    frames = []
    for f in files:
        if not Path(f).exists(): continue
        first = pd.read_csv(f, nrows=0).columns.tolist()
        use = [c for c in cols if c in first]
        if "tournament_entry_id" not in use or "draft_id" not in use: continue
        frames.append(pd.read_csv(f, usecols=use))
    if not frames: return set()
    df = pd.concat(frames, ignore_index=True)
    if "roster_points" not in df.columns:
        return set()
    # Aggregate roster_points per (draft_id, tournament_entry_id) since each
    # team has 18 picks => 18 rows per team in the finals roster.
    teams = df.groupby(["draft_id","tournament_entry_id"]).agg(
        pts=("roster_points","first")  # roster_points is constant per team
    ).reset_index()
    # Pool = draft_id (each finals contest is a draft pool of teams).
    teams["rank"] = teams.groupby("draft_id")["pts"].rank(method="min", ascending=False)
    winners = teams[teams["rank"] == 1.0]["tournament_entry_id"]
    return set(winners.unique())


def read_rd1(spec: dict) -> pd.DataFrame:
    base_cols = [
        "tournament_entry_id", "team_pick_number",
        "position_name", "player_name",
    ]
    if spec["team_key"] == "tournament_round_draft_entry_id":
        wanted = base_cols + [spec["team_key"]]
    else:
        wanted = base_cols
    frames = []
    for f in spec["rd1"]:
        first = pd.read_csv(f, nrows=0).columns.tolist()
        cols = [c for c in wanted if c in first]
        frames.append(pd.read_csv(f, usecols=cols))
    df = pd.concat(frames, ignore_index=True)
    if "tournament_round_draft_entry_id" not in df.columns:
        df["tournament_round_draft_entry_id"] = df[spec["team_key"]]
    return df


def per_team_features(df: pd.DataFrame, name_team: dict) -> pd.DataFrame:
    """Vectorized version of the feature build. Returns one row per team
    with all the structural-stack features attached."""
    keys = list(zip(df["player_name"].map(norm_name), df["position_name"]))
    df = df.copy()
    df["nfl_team"] = [name_team.get(k) for k in keys]

    team_key = "tournament_round_draft_entry_id"
    df = df.sort_values([team_key, "team_pick_number"], kind="stable").reset_index(drop=True)

    # QB1 team
    qbs = df[(df["position_name"]=="QB") & df["nfl_team"].notna()]
    qb1 = qbs.drop_duplicates(team_key, keep="first")[[team_key,"nfl_team"]].rename(
        columns={"nfl_team":"qb1_team"})
    df = df.merge(qb1, on=team_key, how="left")

    # is_stack_qb1 = same NFL team as QB1
    skill = df["position_name"].isin(["WR","TE","RB"])
    df["is_stack_qb1"] = (
        skill & df["nfl_team"].notna() & df["qb1_team"].notna()
        & (df["nfl_team"] == df["qb1_team"])
    )

    # Pos rank within team (1 = first WR drafted, etc.)
    for pos in ("WR","TE","RB"):
        m = df["position_name"] == pos
        df.loc[m, "_pr"] = df[m].groupby(team_key).cumcount() + 1

    # Composition flags
    df["f_wr1"] = df["is_stack_qb1"] & (df["position_name"]=="WR") & (df["_pr"]==1)
    df["f_wr2"] = df["is_stack_qb1"] & (df["position_name"]=="WR") & (df["_pr"]==2)
    df["f_te1"] = df["is_stack_qb1"] & (df["position_name"]=="TE") & (df["_pr"]==1)
    df["f_rb1"] = df["is_stack_qb1"] & (df["position_name"]=="RB") & (df["_pr"]==1)

    # n_qb_stacks: distinct (team_key, qb_team) pairs that have ≥1 same-team mate
    qb_pairs = qbs[[team_key,"nfl_team"]].drop_duplicates()
    pc_pairs = df[skill & df["nfl_team"].notna()][[team_key,"nfl_team"]].drop_duplicates()
    overlap = qb_pairs.merge(pc_pairs, on=[team_key,"nfl_team"]).drop_duplicates([team_key,"nfl_team"])
    n_qb_stacks = overlap.groupby(team_key).size().rename("n_qb_stacks")

    # RB cannibalization
    rb_counts = df[df["position_name"]=="RB"].groupby([team_key,"nfl_team"]).size()
    rb_max = rb_counts.groupby(level=0).max().rename("max_rb_same_team").astype("int8")

    # WR-no-QB cannibalization. Vectorized: build the set of (team_key, qb_team)
    # pairs once, then check WR rows for membership via list comprehension. This
    # replaces a row-level .apply that was the script's main bottleneck for the
    # 12M-row BBM IV+ files (would otherwise take 20+ min per year).
    qb_pair_set = set(zip(qb_pairs[team_key], qb_pairs["nfl_team"]))
    df_wr = df[(df["position_name"]=="WR") & df["nfl_team"].notna()][[team_key,"nfl_team"]].copy()
    tks = df_wr[team_key].to_numpy()
    nts = df_wr["nfl_team"].to_numpy()
    df_wr["no_qb"] = [(t, n) not in qb_pair_set for t, n in zip(tks, nts)]
    nonstack_wr = df_wr[df_wr["no_qb"]].groupby([team_key,"nfl_team"]).size()
    nonstack_wr_max = (nonstack_wr.groupby(level=0).max()
                       .rename("max_wr_no_qb").astype("int8"))

    # Total stacked players (across ALL QBs)
    df["is_stack_any"] = False
    qb_set_pairs = set(zip(qb_pairs[team_key], qb_pairs["nfl_team"]))
    sk_idx = df.index[skill & df["nfl_team"].notna()]
    if len(sk_idx):
        sub = df.loc[sk_idx]
        df.loc[sk_idx, "is_stack_any"] = [
            (t,n) in qb_set_pairs for t,n in zip(sub[team_key], sub["nfl_team"])
        ]
    total_stack = df.groupby(team_key)["is_stack_any"].sum().astype("int8").rename("total_stack")

    teams = df.drop_duplicates(team_key)[[team_key,"tournament_entry_id","qb1_team"]].copy()
    flag_aggs = (df.groupby(team_key)
                 .agg(has_wr1=("f_wr1","any"), has_wr2=("f_wr2","any"),
                      has_te1=("f_te1","any"), has_rb1=("f_rb1","any"))
                 .reset_index())
    teams = (teams
             .merge(flag_aggs, on=team_key)
             .merge(rb_max, on=team_key, how="left")
             .merge(nonstack_wr_max, on=team_key, how="left")
             .merge(total_stack, on=team_key, how="left")
             .merge(n_qb_stacks, on=team_key, how="left"))
    teams["max_rb_same_team"] = teams["max_rb_same_team"].fillna(0).astype("int8")
    teams["max_wr_no_qb"] = teams["max_wr_no_qb"].fillna(0).astype("int8")
    teams["total_stack"] = teams["total_stack"].fillna(0).astype("int8")
    teams["n_qb_stacks"] = teams["n_qb_stacks"].fillna(0).astype("int8")
    teams["wr1_and_wr2"] = teams["has_wr1"] & teams["has_wr2"]

    # Composition bucket
    def bucket(r):
        if not isinstance(r["qb1_team"], str): return "no_qb"
        if r["has_wr1"] and r["has_wr2"]:    return "wr1_and_wr2"
        if r["has_wr1"] and r["has_rb1"]:    return "wr1_and_rb1"
        if r["has_wr1"] and r["has_te1"]:    return "wr1_and_te1"
        if r["has_wr1"]:                     return "wr1_only"
        if r["has_wr2"]:                     return "wr2_no_wr1"
        if r["has_te1"]:                     return "te1_only"
        if r["has_rb1"]:                     return "rb1_only"
        return "no_stack"
    teams["comp_key"] = teams.apply(bucket, axis=1)
    return teams


def main():
    print("[lvl] loading rosters ...", flush=True)
    name_team = {y: build_name_team(fetch_roster(y)) for y in (2021,2022,2023,2024,2025)}

    all_frames = []
    for spec in INPUTS:
        name = spec["name"]
        print(f"\n[lvl] === BBM {name} ===", flush=True)
        print(f"[lvl] reading rd1 ({len(spec['rd1'])} files) ...", flush=True)
        df = read_rd1(spec)
        print(f"[lvl]   rows {len(df):,}", flush=True)
        teams = per_team_features(df, name_team[spec["season"]])
        # Advance flags
        adv_qf = read_advance_set(spec["rd2"])
        adv_sf = read_advance_set(spec["rd3"])
        adv_fin = read_advance_set(spec["rd4"])
        winners = read_finals_winners(spec["rd4"])
        teams["adv_qf"]  = teams["tournament_entry_id"].isin(adv_qf).astype(int)
        teams["adv_sf"]  = teams["tournament_entry_id"].isin(adv_sf).astype(int)
        teams["adv_fin"] = teams["tournament_entry_id"].isin(adv_fin).astype(int)
        teams["won"]     = teams["tournament_entry_id"].isin(winners).astype(int)
        teams["bbm"] = name
        print(f"[lvl]   teams: {len(teams):,}  qf:{teams['adv_qf'].sum():,}  "
              f"sf:{teams['adv_sf'].sum():,}  fin:{teams['adv_fin'].sum():,}  "
              f"won:{teams['won'].sum():,}", flush=True)
        all_frames.append(teams)

    teams = pd.concat(all_frames, ignore_index=True)
    print(f"\n[lvl] combined teams: {len(teams):,}", flush=True)
    levels = [("adv_qf","-> QFinals"), ("adv_sf","-> SFinals"),
              ("adv_fin","-> Finals"), ("won","Won")]
    for col, label in levels:
        rate = teams[col].mean()
        print(f"  baseline {label}: {rate:.4%} ({teams[col].sum():,} of {len(teams):,})",
              flush=True)

    out = {
        "total_teams": int(len(teams)),
        "baselines": {col: float(round(teams[col].mean(),6)) for col, _ in levels},
        "by_dimension": {},
    }

    def section(title, col, label_fn=str, max_buckets=12, min_n=200):
        print(f"\n=== {title} ===", flush=True)
        # Header
        hdr = f"{'val':>14} | {'n':>10}"
        for _, lbl in levels:
            hdr += f" | {lbl[:8]:>8}"
        print(hdr, flush=True)
        print("-" * len(hdr), flush=True)
        rows = []
        if col in ("comp_key",):
            vals = sorted(teams[col].dropna().unique())
        else:
            vals = sorted(teams[col].dropna().unique())[:max_buckets]
        for v in vals:
            sub = teams[teams[col]==v]
            if len(sub) < min_n: continue
            row = {"key": label_fn(v), "n": int(len(sub))}
            line = f"{label_fn(v):>14} | {len(sub):>10,}"
            for c, _ in levels:
                rate = sub[c].mean()
                base = teams[c].mean()
                row[c] = round(float(rate),6)
                row[c+"_lift"] = round(float(rate/base) if base else 0, 3)
                line += f" | {rate*100:>7.3f}%"
            rows.append(row)
            print(line, flush=True)
        return rows

    out["by_dimension"]["comp_key"] = section(
        "STACK COMPOSITION (QB1's same-team pattern)", "comp_key",
        max_buckets=20)
    out["by_dimension"]["n_qb_stacks"] = section(
        "DISTINCT QB STACKS", "n_qb_stacks", lambda v: str(int(v)))
    out["by_dimension"]["max_rb_same_team"] = section(
        "MAX RBs FROM ONE NFL TEAM", "max_rb_same_team", lambda v: str(int(v)))
    out["by_dimension"]["max_wr_no_qb"] = section(
        "MAX WRs SAME-TEAM WITHOUT QB", "max_wr_no_qb", lambda v: str(int(v)))
    out["by_dimension"]["total_stack"] = section(
        "TOTAL STACKED PLAYERS (across all QBs)", "total_stack", lambda v: str(int(v)))
    out["by_dimension"]["wr1_and_wr2"] = section(
        "WR1 AND WR2 same team (over-concentration)", "wr1_and_wr2",
        lambda v: "yes" if v else "no")

    with OUT.open("w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[lvl] wrote {OUT.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
