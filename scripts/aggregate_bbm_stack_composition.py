"""Compositional stack analysis for BBM IV / V / VI.

For each team in BBM IV/V/VI round 1 (regular season), identify the
team's QB1 (first QB drafted), then look at every same-NFL-team
pass-catcher / RB on the roster and classify them by position rank
within the team (e.g. team's WR1 = first WR drafted, WR2 = second WR,
etc.).

Outputs per-composition advance rates for stack mates:

  - Position+rank stake: QB+WR1, QB+WR2, QB+WR3+, QB+TE1, QB+TE2, QB+RB1, QB+RB2
  - Marginal lift of each by toggling its presence
  - Pair effects: QB+WR1+WR2, QB+WR1+TE1, etc.

Also runs a year-stability test (BBM IV vs V vs VI Pearson correlation
of lift) so we don't fool ourselves a second time after the slot×build
flop.

Joins BBM player_name to NFL team via nflverse rosters (year-matched):
  BBM IV  -> 2023 season
  BBM V   -> 2024 season
  BBM VI  -> 2025 season
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
ROSTER_DIR = ROOT / "scripts" / "_nflverse_rosters"
OUT = ROOT / "scripts" / "_bbm_stack_composition.json"

ROSTER_URLS = {
    2023: "https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2023.csv",
    2024: "https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2024.csv",
    2025: "https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_2025.csv",
}

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


def fetch_rosters() -> dict[int, pd.DataFrame]:
    """Download (and cache) nflverse roster CSVs."""
    ROSTER_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[int, pd.DataFrame] = {}
    for season, url in ROSTER_URLS.items():
        cache = ROSTER_DIR / f"roster_{season}.csv"
        if not cache.exists():
            print(f"[stack-comp] downloading roster_{season}.csv ...", flush=True)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r, cache.open("wb") as f:
                f.write(r.read())
        df = pd.read_csv(cache, usecols=["season", "team", "position", "full_name"])
        # Skill positions only — that's all we'll match against
        df = df[df["position"].isin(["QB", "RB", "WR", "TE", "FB", "HB"])].copy()
        df["position"] = df["position"].replace({"FB": "RB", "HB": "RB"})
        out[season] = df
        print(f"[stack-comp]   roster_{season}: {len(df):,} skill players", flush=True)
    return out


_NAME_PUNCT = re.compile(r"[^\w\s]")


def norm_name(name: str) -> str:
    """Aggressive normalization for cross-source name matching:
    lowercase, strip suffixes (Jr/Sr/II/III/IV/V), strip punctuation,
    fold accents."""
    if not isinstance(name, str):
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\.?$", "", s)
    s = _NAME_PUNCT.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def build_name_team_map(roster: pd.DataFrame) -> dict[tuple[str, str], str]:
    """Returns (norm_name, position) -> team. If the same name+pos appears
    on multiple teams in a season (mid-season trade), we keep the first
    listed entry — for stack analysis the player's draft-day team is what
    drafters reasoned about, and nflverse rosters are sorted by week so
    earliest weeks come first."""
    m: dict[tuple[str, str], str] = {}
    for _, r in roster.iterrows():
        k = (norm_name(r["full_name"]), r["position"])
        if k not in m:
            m[k] = r["team"]
    return m


def annotate_picks_with_team(picks: pd.DataFrame, name_team: dict) -> pd.DataFrame:
    """Add an `nfl_team` column to picks via name+position lookup. Picks
    that don't match (rookies missing from earliest roster snapshot, name
    spelling drift) get nfl_team=None and are excluded from stack
    analysis but still count toward team rosters."""
    keys = list(zip(picks["player_name"].map(norm_name), picks["position_name"]))
    picks = picks.copy()
    picks["nfl_team"] = [name_team.get(k) for k in keys]
    return picks


def process_tournament(spec, name_team) -> pd.DataFrame:
    """Vectorized version. Returns one row per team with stack-composition
    boolean columns ready for aggregation."""
    name = spec["name"]
    print(f"[stack-comp] {name}: reading rd2 advance set ...", flush=True)
    rd2 = pd.read_csv(spec["rd2"], usecols=["tournament_entry_id"])
    advanced = set(rd2["tournament_entry_id"].unique())
    print(f"[stack-comp] {name}:   advanced: {len(advanced):,}", flush=True)

    print(f"[stack-comp] {name}: reading rd1 ...", flush=True)
    df = pd.read_csv(
        spec["rd1"],
        usecols=[
            "tournament_entry_id", "tournament_round_draft_entry_id",
            "team_pick_number", "position_name", "player_name",
        ],
    )
    print(f"[stack-comp] {name}:   rows: {len(df):,}", flush=True)
    df = annotate_picks_with_team(df, name_team)
    matched = df["nfl_team"].notna().mean()
    print(f"[stack-comp] {name}:   name->team match rate: {matched:.3%}", flush=True)

    # Sort once so position-rank assignments are deterministic.
    df = df.sort_values(
        ["tournament_round_draft_entry_id", "team_pick_number"], kind="stable"
    ).reset_index(drop=True)

    team_key = "tournament_round_draft_entry_id"

    # Each team's QB1 = first row in the team where position_name == 'QB'.
    qbs = df[df["position_name"] == "QB"]
    qb1 = qbs.drop_duplicates(team_key, keep="first")[[team_key, "nfl_team"]]
    qb1 = qb1.rename(columns={"nfl_team": "qb1_team"})
    df = df.merge(qb1, on=team_key, how="left")

    # is_stacked = pick is non-QB skill AND its NFL team matches qb1_team.
    df["is_stacked"] = (
        df["position_name"].isin(["WR", "TE", "RB"])
        & df["nfl_team"].notna()
        & df["qb1_team"].notna()
        & (df["nfl_team"] == df["qb1_team"])
    )

    # Position rank within team — 1 = first WR/TE/RB drafted by that team.
    df["pos_rank"] = (
        df[df["position_name"].isin(["WR", "TE", "RB"])]
        .groupby([team_key, "position_name"])
        .cumcount()
        + 1
    )
    df["pos_rank"] = df["pos_rank"].fillna(0).astype("int8")

    # Per-pick boolean flags (only for stacked picks; otherwise False).
    # Pre-compute everything as columns on df so the groupby below uses
    # only built-in aggregators (any/sum), which run in C — no Python lambdas.
    s = df["is_stacked"]
    pos = df["position_name"]
    rk = df["pos_rank"]
    df["f_wr1"] = s & (pos == "WR") & (rk == 1)
    df["f_wr2"] = s & (pos == "WR") & (rk == 2)
    df["f_wr3plus"] = s & (pos == "WR") & (rk >= 3)
    df["f_te1"] = s & (pos == "TE") & (rk == 1)
    df["f_te2"] = s & (pos == "TE") & (rk == 2)
    df["f_rb1"] = s & (pos == "RB") & (rk == 1)
    df["f_rb2"] = s & (pos == "RB") & (rk == 2)
    df["c_wr_stack"] = (s & (pos == "WR")).astype("int8")
    df["c_te_stack"] = (s & (pos == "TE")).astype("int8")
    df["c_rb_stack"] = (s & (pos == "RB")).astype("int8")

    flag_cols = ["f_wr1", "f_wr2", "f_wr3plus", "f_te1", "f_te2", "f_rb1", "f_rb2"]
    teams = df.groupby(team_key, sort=False).agg(
        tournament_entry_id=("tournament_entry_id", "first"),
        n_wr_stack=("c_wr_stack", "sum"),
        n_te_stack=("c_te_stack", "sum"),
        n_rb_stack=("c_rb_stack", "sum"),
        **{c: (c, "any") for c in flag_cols},
    ).reset_index()

    # Rename to match downstream code.
    teams = teams.rename(columns={
        "f_wr1": "has_wr1", "f_wr2": "has_wr2", "f_wr3plus": "has_wr3plus",
        "f_te1": "has_te1", "f_te2": "has_te2",
        "f_rb1": "has_rb1", "f_rb2": "has_rb2",
    })
    teams["any_stack"] = (
        teams["n_wr_stack"] + teams["n_te_stack"] + teams["n_rb_stack"] > 0
    )
    teams["wr1_and_wr2"] = teams["has_wr1"] & teams["has_wr2"]
    teams["wr1_and_te1"] = teams["has_wr1"] & teams["has_te1"]
    teams["wr1_and_rb1"] = teams["has_wr1"] & teams["has_rb1"]
    teams["te1_and_wr2"] = teams["has_te1"] & teams["has_wr2"]

    teams["adv"] = teams["tournament_entry_id"].isin(advanced).astype(int)
    teams["bbm"] = name
    print(
        f"[stack-comp] {name}:   teams: {len(teams):,} "
        f"(any_stack rate {teams['any_stack'].mean():.3%}, "
        f"baseline adv {teams['adv'].mean():.4f})",
        flush=True,
    )
    return teams


def per_year_lifts(teams: pd.DataFrame, flag: str) -> dict:
    """Return per-year q_rate + lift (vs year baseline) for teams matching `flag`."""
    out = {}
    for yr in teams["bbm"].unique():
        sub = teams[teams["bbm"] == yr]
        baseline = sub["adv"].mean()
        match = sub[sub[flag]]
        n = len(match)
        if n < 200:
            continue
        q = match["adv"].mean()
        out[yr] = {"n": n, "q_rate": round(q, 4), "lift": round(q / baseline, 3)}
    return out


def stability_corr(per_year_a: dict, per_year_b: dict) -> tuple[float, list]:
    shared = set(per_year_a) & set(per_year_b)
    pairs = []
    for k in sorted(shared):
        pairs.append((k, per_year_a[k]["lift"], per_year_b[k]["lift"]))
    if len(pairs) < 3:
        return float("nan"), pairs
    ax = [p[1] for p in pairs]
    bx = [p[2] for p in pairs]
    ma, mb = sum(ax) / len(ax), sum(bx) / len(bx)
    num = sum((ax[i] - ma) * (bx[i] - mb) for i in range(len(ax)))
    da = (sum((x - ma) ** 2 for x in ax)) ** 0.5
    db = (sum((x - mb) ** 2 for x in bx)) ** 0.5
    r = num / (da * db) if da * db > 0 else 0
    return round(r, 3), pairs


def main():
    rosters = fetch_rosters()
    name_team_by_season = {s: build_name_team_map(r) for s, r in rosters.items()}

    frames = []
    for spec in INPUTS:
        if not spec["rd1"].exists() or not spec["rd2"].exists():
            print(f"[stack-comp] missing files for {spec['name']}, skipping", flush=True)
            continue
        nt = name_team_by_season[spec["season"]]
        frames.append(process_tournament(spec, nt))
    if not frames:
        raise SystemExit("[stack-comp] no inputs")

    teams = pd.concat(frames, ignore_index=True)
    print(f"[stack-comp] combined teams: {len(teams):,}", flush=True)
    overall_baseline = teams["adv"].mean()
    print(f"[stack-comp] overall baseline q_rate: {overall_baseline:.4f}", flush=True)

    # Aggregate flags we care about.
    flags = [
        "any_stack",
        "has_wr1", "has_wr2", "has_wr3plus",
        "has_te1", "has_te2",
        "has_rb1", "has_rb2",
        "wr1_and_wr2", "wr1_and_te1", "wr1_and_rb1", "te1_and_wr2",
    ]
    print()
    print("=== STACK COMPOSITION ADVANCE RATES ===", flush=True)
    print(f"{'flag':<14} | {'n':>8} | {'q_rate':>7} | {'lift':>5} | {'+/-pp':>6}", flush=True)
    print("-" * 60, flush=True)
    summary = {}
    # Negative cohort: no stack at all
    no_stack = teams[~teams["any_stack"]]
    summary["no_stack"] = {
        "n": int(len(no_stack)),
        "q_rate": round(no_stack["adv"].mean(), 4),
        "lift": round(no_stack["adv"].mean() / overall_baseline, 3),
    }
    print(
        f"{'no_stack':<14} | {len(no_stack):>8,} | "
        f"{summary['no_stack']['q_rate']:>7.4f} | "
        f"{summary['no_stack']['lift']:>5.2f} | "
        f"{(summary['no_stack']['q_rate']-overall_baseline)*100:>+6.2f}",
        flush=True,
    )
    for f in flags:
        sub = teams[teams[f]]
        if len(sub) < 500:
            continue
        q = sub["adv"].mean()
        summary[f] = {
            "n": int(len(sub)),
            "q_rate": round(q, 4),
            "lift": round(q / overall_baseline, 3),
        }
        print(
            f"{f:<14} | {len(sub):>8,} | {q:>7.4f} | {q / overall_baseline:>5.2f} | "
            f"{(q - overall_baseline) * 100:>+6.2f}",
            flush=True,
        )

    # Per-year stability for the most actionable flags.
    print()
    print("=== YEAR-OVER-YEAR STABILITY (lift per year) ===", flush=True)
    actionable = ["has_wr1", "has_wr2", "has_te1", "has_rb1", "wr1_and_wr2"]
    per_year = {f: per_year_lifts(teams, f) for f in actionable}
    for f, v in per_year.items():
        print(f"  {f}: {v}", flush=True)

    out_obj = {
        "meta": {
            "total_teams": int(len(teams)),
            "overall_baseline": round(float(overall_baseline), 4),
            "sources": ["BBM IV (2023)", "BBM V (2024)", "BBM VI (2025)"],
        },
        "by_flag": summary,
        "per_year": per_year,
    }
    with OUT.open("w") as f:
        json.dump(out_obj, f, indent=2)
    print(f"[stack-comp] wrote {OUT.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
