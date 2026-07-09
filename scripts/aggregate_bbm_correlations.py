"""Comprehensive correlation-play research across BBM IV/V/VI (2.0M teams).

Per team, derives:
  - Stack composition + multi-QB stack count (already in production score)
  - Total stack-player count across all QBs
  - Round of QB1's first same-team mate
  - Top specific QB+WR1 pairs (frequency / advance rate)
  - Bye-week concentration (max # players sharing a bye week)
  - RB cannibalization (max # RBs from one NFL team, no QB context)
  - WR cannibalization (max # WRs from one NFL team WITHOUT a QB on that team)
  - Rookie vs veteran stack mate (years_exp on QB1's first stack mate)
  - Game stacks / bringbacks (QB1 + opposing-team WR/TE who plays QB1's team
    at some point in the regular-season schedule)
  - Stack timing × ADP (was the stack mate taken early or late)

Outputs: scripts/_bbm_correlations.json with each dimension's q_rate buckets
and per-year stability where space allows.
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
DBOWL = (BASE / "best-ball-data-bowl-master" / "best-ball-data-bowl-master" / "data")
ROSTER_DIR = ROOT / "scripts" / "_nflverse_rosters"
SCHED_PATH = ROOT / "scripts" / "_nflverse_schedules.csv"
OUT = ROOT / "scripts" / "_bbm_correlations.json"


def _glob(pat: Path) -> list[Path]:
    return sorted(pat.parent.glob(pat.name))


# Per-tournament spec. The `team_key` field is the column we group by to get
# one row per team (varies because BBM II 2021 doesn't have
# tournament_round_draft_entry_id — falls back to tournament_entry_id).
# advance is determined by either:
#   - rd2_files: list of post-season CSV(s); membership of tournament_entry_id
#                 in the union = advanced
#   - else playoff_team column in rd1 with sum > 0
# 2020 (BBM I) is intentionally omitted — its CSV has no position column.
INPUTS = [
    {
        "name": "II", "season": 2021, "team_key": "tournament_entry_id",
        "rd1_files": _glob(DBOWL/"2021"/"regular_season"/"part_*.csv"),
        "rd2_files": None,  # use playoff_team inline (already filled in 2021)
    },
    {
        "name": "III", "season": 2022, "team_key": "tournament_round_draft_entry_id",
        "rd1_files": (
            _glob(DBOWL/"2022"/"regular_season"/"fast"/"part_*.csv") +
            _glob(DBOWL/"2022"/"regular_season"/"mixed"/"part_*.csv")
        ),
        "rd2_files": _glob(DBOWL/"2022"/"post_season"/"quarterfinals"/"part_*.csv"),
    },
    {
        "name": "IV", "season": 2023, "team_key": "tournament_round_draft_entry_id",
        "rd1_files": [BASE/"BBM IV"/"best_ball_mania_iv_2023_r1_results_pick_by_pick.csv"],
        "rd2_files": [BASE/"BBM IV"/"best_ball_mania_iv_2023_r2_results_pick_by_pick.csv"],
    },
    {
        "name": "V", "season": 2024, "team_key": "tournament_round_draft_entry_id",
        "rd1_files": [BASE/"BBM V"/"best_ball_mania_v_rd1.csv"],
        "rd2_files": [BASE/"BBM V"/"best_ball_mania_v_rd2.csv"],
    },
    {
        "name": "VI", "season": 2025, "team_key": "tournament_round_draft_entry_id",
        "rd1_files": [BASE/"BBM VI"/"best_ball_mania_vi_rd1.csv"],
        "rd2_files": [BASE/"BBM VI"/"best_ball_mania_vi_rd2.csv"],
    },
]

_NAME_PUNCT = re.compile(r"[^\w\s]")


def norm_name(name):
    if not isinstance(name, str): return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii","ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\.?$", "", s)
    s = _NAME_PUNCT.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def fetch_schedules():
    if not SCHED_PATH.exists():
        print("[corr] downloading nflverse schedules ...", flush=True)
        url = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r, SCHED_PATH.open("wb") as f:
            f.write(r.read())
    df = pd.read_csv(SCHED_PATH, usecols=["season","game_type","home_team","away_team"])
    return df[df["game_type"]=="REG"].copy()


def opponents_by_team(sched_year: pd.DataFrame) -> dict:
    """Return dict: nfl_team -> set of teams it plays in the regular season."""
    out = {}
    for _, r in sched_year.iterrows():
        h, a = r["home_team"], r["away_team"]
        out.setdefault(h, set()).add(a)
        out.setdefault(a, set()).add(h)
    return out


def build_name_meta(roster):
    """Returns dict (norm_name, position) -> {team, exp}."""
    m = {}
    for _, r in roster.iterrows():
        k = (norm_name(r["full_name"]), r["position"])
        if k in m: continue
        exp = r.get("years_exp")
        if pd.isna(exp): exp = None
        m[k] = {"team": r["team"], "exp": int(exp) if exp is not None else None}
    return m


def process(spec, name_meta, opp_map):
    name = spec["name"]
    src_team_key = spec["team_key"]

    print(f"[corr] {name}: rd1 ({len(spec['rd1_files'])} files) ...", flush=True)
    base_cols = [
        "tournament_entry_id", "team_pick_number",
        "position_name", "player_name", "projection_adp",
    ]
    if spec.get("rd2_files") is None:
        wanted_cols = base_cols + ["playoff_team"]
    else:
        wanted_cols = base_cols
    if src_team_key == "tournament_round_draft_entry_id":
        wanted_cols = wanted_cols + [src_team_key]

    frames = []
    for f in spec["rd1_files"]:
        first = pd.read_csv(f, nrows=0).columns.tolist()
        cols = [c for c in wanted_cols if c in first]
        frames.append(pd.read_csv(f, usecols=cols))
    df = pd.concat(frames, ignore_index=True)

    # Canonicalize the team key to "tournament_round_draft_entry_id" so the
    # downstream pipeline (per_team_features etc.) doesn't need schema
    # awareness. For 2021 the source key is tournament_entry_id, so we
    # duplicate that column under the canonical name.
    if "tournament_round_draft_entry_id" not in df.columns:
        df["tournament_round_draft_entry_id"] = df[src_team_key]
    team_key = "tournament_round_draft_entry_id"
    print(f"[corr] {name}:   rows {len(df):,}", flush=True)

    # Determine advanced set.
    if spec.get("rd2_files"):
        rd2_frames = []
        for f in spec["rd2_files"]:
            rd2_frames.append(pd.read_csv(f, usecols=["tournament_entry_id"]))
        rd2 = pd.concat(rd2_frames, ignore_index=True)
        advanced = set(rd2["tournament_entry_id"].unique())
    else:
        adv_df = df[df["playoff_team"] == 1][["tournament_entry_id"]].drop_duplicates()
        advanced = set(adv_df["tournament_entry_id"].unique())
    print(f"[corr] {name}:   advanced: {len(advanced):,}", flush=True)

    # Look up nfl_team and years_exp by (norm_name, position)
    keys = list(zip(df["player_name"].map(norm_name), df["position_name"]))
    df["nfl_team"] = [name_meta.get(k, {}).get("team") for k in keys]
    df["yrs_exp"] = [name_meta.get(k, {}).get("exp") for k in keys]

    team_key = "tournament_round_draft_entry_id"
    df = df.sort_values([team_key,"team_pick_number"], kind="stable").reset_index(drop=True)

    # ---------- QB / Stack metadata ----------
    qbs = df[(df["position_name"]=="QB") & df["nfl_team"].notna()][[team_key,"nfl_team","team_pick_number","player_name"]]
    qb1 = qbs.drop_duplicates(team_key, keep="first").rename(
        columns={"nfl_team":"qb1_team","team_pick_number":"qb1_pick","player_name":"qb1_name"})[
        [team_key,"qb1_team","qb1_pick","qb1_name"]]
    df = df.merge(qb1, on=team_key, how="left")

    qb_team_set = qbs.groupby(team_key)["nfl_team"].apply(set).rename("qb_teams")
    df = df.merge(qb_team_set, on=team_key, how="left")

    skill = df["position_name"].isin(["WR","TE","RB"])
    # Vectorized any-QB stack flag via (team_key, nfl_team) pair set
    qbexp = qbs[[team_key,"nfl_team"]].drop_duplicates()
    pairs = set(zip(qbexp[team_key], qbexp["nfl_team"]))
    sk_idx = df.index[skill & df["nfl_team"].notna()]
    df["is_stack_any"] = False
    if len(sk_idx):
        sub = df.loc[sk_idx]
        df.loc[sk_idx,"is_stack_any"] = [(t,n) in pairs for t,n in zip(sub[team_key], sub["nfl_team"])]

    # QB1 stack flag
    df["is_stack_qb1"] = (
        skill & df["nfl_team"].notna() & df["qb1_team"].notna()
        & (df["nfl_team"] == df["qb1_team"])
    )

    # Return df + advance set so main doesn't need to re-read rd2.
    return df, advanced


def per_team_features(df, bye_by_team, opp_map, advanced):
    team_key = "tournament_round_draft_entry_id"
    skill = df["position_name"].isin(["WR","TE","RB"])

    # Pre-compute group indexes to iterate in C
    g = df.groupby(team_key, sort=False)
    print(f"[corr]   computing per-team features for {g.ngroups:,} teams ...", flush=True)

    # Vectorized features that don't need group iteration:
    # max bye-week count: groupby team_key with bye column
    bye_series = df["nfl_team"].map(bye_by_team).fillna(-1).astype("int8")
    df["bye"] = bye_series
    # For each (team_key, bye), count picks. Then take max over byes per team.
    bye_counts = (df[df["bye"]>=0].groupby([team_key,"bye"]).size())
    max_bye = bye_counts.groupby(level=0).max().rename("max_bye_concentration")

    # max RBs from same team (any QB context)
    rb_counts = (df[df["position_name"]=="RB"]
                 .groupby([team_key,"nfl_team"]).size())
    rb_max = rb_counts.groupby(level=0).max().rename("max_rb_same_team")

    # max WRs from same team (any context)
    wr_counts = (df[df["position_name"]=="WR"]
                 .groupby([team_key,"nfl_team"]).size())
    wr_max = wr_counts.groupby(level=0).max().rename("max_wr_same_team")

    # WRs from same team but NOT same-team-as-any-QB (cannibalization without QB)
    nonstack_wr = df[(df["position_name"]=="WR") & (~df["is_stack_any"]) & df["nfl_team"].notna()]
    nonstack_wr_counts = nonstack_wr.groupby([team_key,"nfl_team"]).size()
    nonstack_wr_max = nonstack_wr_counts.groupby(level=0).max().rename("max_wr_no_qb")

    # Bringback: any pass-catcher whose nfl_team is an OPPONENT of QB1's team.
    # Vectorized: precompute the set of (qb_team, opp_team) pairs from opp_map,
    # then test row pairs against it via list comprehension (faster than apply).
    qb1_team_per = df.drop_duplicates(team_key)[[team_key,"qb1_team"]].set_index(team_key)["qb1_team"]
    df_pc = df[(df["position_name"].isin(["WR","TE"])) & df["nfl_team"].notna()].copy()
    df_pc["qb1_team"] = df_pc[team_key].map(qb1_team_per)
    opp_pairs = set()
    for qt, opps in opp_map.items():
        if qt is None: continue
        for pt in opps:
            if pt is not None:
                opp_pairs.add((qt, pt))
    qts = df_pc["qb1_team"].to_numpy()
    pts = df_pc["nfl_team"].to_numpy()
    df_pc["is_bringback"] = [
        (isinstance(q, str) and isinstance(p, str) and q != p and (q, p) in opp_pairs)
        for q, p in zip(qts, pts)
    ]
    bringback_any = df_pc.groupby(team_key)["is_bringback"].any().rename("any_bringback")

    # Years_exp on QB1's first same-team mate
    qb1_mates = df[df["is_stack_qb1"]].sort_values([team_key,"team_pick_number"])
    first_mate = qb1_mates.drop_duplicates(team_key, keep="first")[[team_key,"team_pick_number","yrs_exp","player_name"]]
    first_mate.columns = [team_key,"first_mate_pick","first_mate_exp","first_mate_name"]

    # Composition flag (reuse logic from earlier script)
    # WR1/WR2 stacked, RB1/TE1 stacked
    wr_sk = df[df["position_name"]=="WR"].copy()
    wr_sk["pos_rank"] = wr_sk.groupby(team_key).cumcount()+1
    has_wr1 = wr_sk[(wr_sk["pos_rank"]==1) & wr_sk["is_stack_qb1"]][team_key]
    has_wr2 = wr_sk[(wr_sk["pos_rank"]==2) & wr_sk["is_stack_qb1"]][team_key]
    te_sk = df[df["position_name"]=="TE"].copy()
    te_sk["pos_rank"] = te_sk.groupby(team_key).cumcount()+1
    has_te1 = te_sk[(te_sk["pos_rank"]==1) & te_sk["is_stack_qb1"]][team_key]
    rb_sk = df[df["position_name"]=="RB"].copy()
    rb_sk["pos_rank"] = rb_sk.groupby(team_key).cumcount()+1
    has_rb1 = rb_sk[(rb_sk["pos_rank"]==1) & rb_sk["is_stack_qb1"]][team_key]

    # Total stack count
    total_stack = df.groupby(team_key)["is_stack_any"].sum().astype("int8").rename("total_stack")

    # n distinct QB stacks
    qbexp = df[(df["position_name"]=="QB") & df["nfl_team"].notna()][[team_key,"nfl_team"]]
    pcexp = df[skill & df["nfl_team"].notna()][[team_key,"nfl_team"]]
    overlap = qbexp.merge(pcexp, on=[team_key,"nfl_team"]).drop_duplicates([team_key,"nfl_team"])
    n_qb_stacks = overlap.groupby(team_key).size().rename("n_qb_stacks")

    # WR1 specific stack pair (qb1_name, wr1_name) where wr1 is same team
    wr1_row = (df[df["position_name"]=="WR"]
               .drop_duplicates(team_key, keep="first")
               [[team_key,"player_name","nfl_team"]]
               .rename(columns={"player_name":"wr1_name","nfl_team":"wr1_team"}))

    teams = df.drop_duplicates(team_key)[[team_key,"tournament_entry_id","qb1_team","qb1_name"]].copy()
    teams = (teams
             .merge(max_bye, on=team_key, how="left")
             .merge(rb_max, on=team_key, how="left")
             .merge(wr_max, on=team_key, how="left")
             .merge(nonstack_wr_max, on=team_key, how="left")
             .merge(bringback_any, on=team_key, how="left")
             .merge(first_mate, on=team_key, how="left")
             .merge(total_stack, on=team_key, how="left")
             .merge(n_qb_stacks, on=team_key, how="left")
             .merge(wr1_row, on=team_key, how="left"))

    teams["has_wr1"] = teams[team_key].isin(set(has_wr1))
    teams["has_wr2"] = teams[team_key].isin(set(has_wr2))
    teams["has_te1"] = teams[team_key].isin(set(has_te1))
    teams["has_rb1"] = teams[team_key].isin(set(has_rb1))
    teams["any_bringback"] = teams["any_bringback"].fillna(False).astype(bool)
    teams["max_bye_concentration"] = teams["max_bye_concentration"].fillna(0).astype("int8")
    teams["max_rb_same_team"] = teams["max_rb_same_team"].fillna(0).astype("int8")
    teams["max_wr_same_team"] = teams["max_wr_same_team"].fillna(0).astype("int8")
    teams["max_wr_no_qb"] = teams["max_wr_no_qb"].fillna(0).astype("int8")
    teams["total_stack"] = teams["total_stack"].fillna(0).astype("int8")
    teams["n_qb_stacks"] = teams["n_qb_stacks"].fillna(0).astype("int8")
    teams["adv"] = teams["tournament_entry_id"].isin(advanced).astype(int)
    return teams


def main():
    # Load rosters
    print("[corr] loading rosters ...", flush=True)
    rosters = {}
    for season in (2023,2024,2025):
        rosters[season] = pd.read_csv(
            ROSTER_DIR / f"roster_{season}.csv",
            usecols=["season","team","position","full_name","years_exp"],
        )
        rosters[season] = rosters[season][
            rosters[season]["position"].isin(["QB","RB","WR","TE","FB","HB"])
        ].copy()
        rosters[season]["position"] = rosters[season]["position"].replace({"FB":"RB","HB":"RB"})
    name_meta = {s: build_name_meta(r) for s,r in rosters.items()}

    # Bye weeks per team per season
    sched = fetch_schedules()
    bye_by_season = {}
    opp_by_season = {}
    for yr in (2023,2024,2025):
        sy = sched[sched["season"]==yr]
        # For each team, find weeks present, then identify the bye = first
        # missing week in 1..18 inclusive of week 14 historically being bye-heavy.
        weeks_by_team = {}
        for _, r in sy.iterrows():
            for t in (r["home_team"], r["away_team"]):
                weeks_by_team.setdefault(t, set()).add(r.get("week", 0))
        # We don't have `week` in usecols above — refetch with week
        opp_by_season[yr] = opponents_by_team(sy)

    # Refetch schedule with week column
    sched_full = pd.read_csv(SCHED_PATH, usecols=["season","game_type","week","home_team","away_team"])
    sched_full = sched_full[sched_full["game_type"]=="REG"].copy()
    for yr in (2023,2024,2025):
        sy = sched_full[sched_full["season"]==yr]
        wks = {}
        for _, r in sy.iterrows():
            for t in (r["home_team"], r["away_team"]):
                wks.setdefault(t, set()).add(int(r["week"]))
        # bye = first week in [1..18] not in wks
        bye = {}
        for t, w in wks.items():
            mx = max(w) if w else 0
            for cand in range(1, mx+1):
                if cand not in w:
                    bye[t] = cand; break
        bye_by_season[yr] = bye
        print(f"[corr]   {yr}: {len(bye)} teams, byes set", flush=True)

    frames = []
    for spec in INPUTS:
        df, advanced = process(spec, name_meta[spec["season"]], opp_by_season[spec["season"]])
        teams = per_team_features(df, bye_by_season[spec["season"]], opp_by_season[spec["season"]], advanced)
        teams["bbm"] = spec["name"]
        frames.append(teams)
        print(f"[corr] {spec['name']}: features built for {len(teams):,} teams", flush=True)

    teams = pd.concat(frames, ignore_index=True)
    base = teams["adv"].mean()
    print(f"\n[corr] combined teams: {len(teams):,}, baseline {base:.4f}\n", flush=True)

    out = {"overall_baseline": round(float(base),4), "total_teams": int(len(teams))}

    def bucket(label, series_filter, name=None):
        sub = teams[series_filter]
        if len(sub) < 200: return None
        q = sub["adv"].mean()
        return {"label": label, "n": int(len(sub)), "q_rate": round(float(q),4), "lift": round(float(q/base),3)}

    def show_dist(title, col, label_fn=str, max_buckets=10):
        print(f"=== {title} ===", flush=True)
        out_dim = []
        for v in sorted(teams[col].dropna().unique())[:max_buckets+5]:
            sub = teams[teams[col]==v]
            if len(sub) < 200: continue
            q = sub["adv"].mean()
            row = {"key": label_fn(v), "n": int(len(sub)), "q_rate": round(float(q),4),
                   "lift": round(float(q/base),3)}
            out_dim.append(row)
            print(f"  {label_fn(v):>8}: n={int(len(sub)):>9,}  q_rate={q:.4f}  lift={q/base:.2f}", flush=True)
        print()
        return out_dim

    out["total_stack_count"] = show_dist(
        "TOTAL stack player count (across all QBs)", "total_stack", lambda v:str(int(v)))
    out["n_qb_stacks"] = show_dist(
        "Number of distinct QB-stacks", "n_qb_stacks", lambda v:str(int(v)))
    out["max_bye_concentration"] = show_dist(
        "Max # of players sharing a bye week", "max_bye_concentration", lambda v:str(int(v)))
    out["max_rb_same_team"] = show_dist(
        "Max # of RBs from the same NFL team (cannibalization)", "max_rb_same_team", lambda v:str(int(v)))
    out["max_wr_no_qb"] = show_dist(
        "Max # of WRs from one team WITHOUT a QB stack (no-QB cannibalization)",
        "max_wr_no_qb", lambda v:str(int(v)))

    # Bringback (boolean)
    print("=== Bringback (any opposing-team WR/TE who plays QB1's team) ===", flush=True)
    out["bringback"] = []
    for v, label in [(True,"yes"), (False,"no")]:
        sub = teams[teams["any_bringback"]==v]
        if len(sub) < 200: continue
        q = sub["adv"].mean()
        out["bringback"].append({"key": label, "n": int(len(sub)),
                                 "q_rate": round(float(q),4),
                                 "lift": round(float(q/base),3)})
        print(f"  {label:>4}: n={int(len(sub)):>9,}  q_rate={q:.4f}  lift={q/base:.2f}", flush=True)
    print()

    # Stack mate years_exp buckets
    print("=== QB1's first same-team mate by years_exp ===", flush=True)
    out["mate_years_exp"] = []
    sub_mate = teams.dropna(subset=["first_mate_exp"]).copy()
    sub_mate["exp_bucket"] = pd.cut(sub_mate["first_mate_exp"],
                                     bins=[-1,0,1,3,5,99],
                                     labels=["rookie","2nd_yr","3-4yr","5-6yr","7+yr"])
    for b, ss in sub_mate.groupby("exp_bucket", observed=True):
        if len(ss) < 200: continue
        q = ss["adv"].mean()
        out["mate_years_exp"].append({"key": str(b), "n": int(len(ss)),
                                      "q_rate": round(float(q),4),
                                      "lift": round(float(q/base),3)})
        print(f"  {str(b):>8}: n={int(len(ss)):>9,}  q_rate={q:.4f}  lift={q/base:.2f}", flush=True)
    print()

    # Round of first stack mate (1..18)
    print("=== Round of QB1's first same-team mate ===", flush=True)
    sub = teams.dropna(subset=["first_mate_pick"]).copy()
    sub["round_bucket"] = pd.cut(sub["first_mate_pick"], bins=[0,3,6,9,12,18],
                                  labels=["1-3","4-6","7-9","10-12","13-18"])
    out["mate_round_bucket"] = []
    for b, ss in sub.groupby("round_bucket", observed=True):
        if len(ss) < 200: continue
        q = ss["adv"].mean()
        out["mate_round_bucket"].append({"key": str(b), "n": int(len(ss)),
                                          "q_rate": round(float(q),4),
                                          "lift": round(float(q/base),3)})
        print(f"  {str(b):>8}: n={int(len(ss)):>9,}  q_rate={q:.4f}  lift={q/base:.2f}", flush=True)
    naked = teams[teams["first_mate_pick"].isna()]
    if len(naked) >= 200:
        q = naked["adv"].mean()
        out["mate_round_bucket"].append({"key":"naked", "n": int(len(naked)),
                                          "q_rate": round(float(q),4),
                                          "lift": round(float(q/base),3)})
        print(f"  {'naked':>8}: n={int(len(naked)):>9,}  q_rate={q:.4f}  lift={q/base:.2f}", flush=True)
    print()

    # Top specific QB+WR1 same-team pairs
    paired = teams[teams["wr1_team"].notna() & teams["qb1_team"].notna()
                   & (teams["wr1_team"]==teams["qb1_team"])]
    pair_stats = (paired.groupby(["bbm","qb1_name","wr1_name"])
                  .agg(n=("adv","count"), q=("adv","sum")).reset_index())
    pair_stats["q_rate"] = pair_stats["q"]/pair_stats["n"]
    out["top_pairs_freq"] = {}
    out["top_pairs_advance"] = {}
    print("=== TOP 12 MOST-DRAFTED QB+WR1 same-team pairs per year ===", flush=True)
    for yr in sorted(paired["bbm"].unique()):
        ys = pair_stats[pair_stats["bbm"]==yr].sort_values("n", ascending=False).head(12)
        print(f"\n  -- BBM {yr} --", flush=True)
        out["top_pairs_freq"][yr] = []
        for _, r in ys.iterrows():
            out["top_pairs_freq"][yr].append({
                "qb": r["qb1_name"], "wr1": r["wr1_name"], "n": int(r["n"]),
                "q_rate": round(float(r["q_rate"]),4),
                "lift": round(float(r["q_rate"]/base),3),
            })
            print(f"  {r['qb1_name']:<22} + {r['wr1_name']:<22}  n={int(r['n']):>6,}  q_rate={r['q_rate']:.4f}  lift={r['q_rate']/base:.2f}", flush=True)
    print()
    print("=== BEST QB+WR1 pairs by advance rate (min n=500) ===", flush=True)
    for yr in sorted(paired["bbm"].unique()):
        ys = (pair_stats[(pair_stats["bbm"]==yr) & (pair_stats["n"]>=500)]
              .sort_values("q_rate", ascending=False).head(8))
        print(f"\n  -- BBM {yr} --", flush=True)
        out["top_pairs_advance"][yr] = []
        for _, r in ys.iterrows():
            out["top_pairs_advance"][yr].append({
                "qb": r["qb1_name"], "wr1": r["wr1_name"], "n": int(r["n"]),
                "q_rate": round(float(r["q_rate"]),4),
                "lift": round(float(r["q_rate"]/base),3),
            })
            print(f"  {r['qb1_name']:<22} + {r['wr1_name']:<22}  n={int(r['n']):>6,}  q_rate={r['q_rate']:.4f}  lift={r['q_rate']/base:.2f}", flush=True)

    with OUT.open("w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[corr] wrote {OUT.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
