"""Supplementary stack stats:

  1. Total same-team-as-any-QB pass-catcher count distribution (0..N).
  2. Round of QB1's first same-team mate ("how early did you start stacking").
  3. Top specific QB↔WR1 pairs (player names) ranked by:
     - Frequency (most-drafted pairings)
     - Advance rate (best pairings, min n=500)
"""
from __future__ import annotations
import json, re, unicodedata
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "Best Ball Mania Files"
ROSTER_DIR = ROOT / "scripts" / "_nflverse_rosters"
OUT = ROOT / "scripts" / "_bbm_stack_extra.json"

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
    if not isinstance(name, str): return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii","ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\.?$", "", s)
    s = _NAME_PUNCT.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def build_name_team_map(roster):
    m = {}
    for _, r in roster.iterrows():
        k = (norm_name(r["full_name"]), r["position"])
        if k not in m: m[k] = r["team"]
    return m


def process(spec, name_team):
    name = spec["name"]
    print(f"[stack-extra] {name}: rd2 ...", flush=True)
    rd2 = pd.read_csv(spec["rd2"], usecols=["tournament_entry_id"])
    advanced = set(rd2["tournament_entry_id"].unique())
    print(f"[stack-extra] {name}: rd1 ...", flush=True)
    df = pd.read_csv(spec["rd1"], usecols=[
        "tournament_entry_id","tournament_round_draft_entry_id",
        "team_pick_number","position_name","player_name",
    ])
    keys = list(zip(df["player_name"].map(norm_name), df["position_name"]))
    df["nfl_team"] = [name_team.get(k) for k in keys]

    team_key = "tournament_round_draft_entry_id"
    df = df.sort_values([team_key,"team_pick_number"], kind="stable").reset_index(drop=True)

    # QB-team set per team
    qb_picks = df[(df["position_name"]=="QB") & df["nfl_team"].notna()][[team_key,"nfl_team","team_pick_number"]]
    # QB1 = first QB drafted per team
    qb1 = qb_picks.drop_duplicates(team_key, keep="first").rename(
        columns={"nfl_team":"qb1_team","team_pick_number":"qb1_pick"})[[team_key,"qb1_team","qb1_pick"]]
    df = df.merge(qb1, on=team_key, how="left")

    # Set of QB-teams per team (for total stack count across all QBs)
    qb_team_set = qb_picks.groupby(team_key)["nfl_team"].apply(set).rename("qb_teams")
    df = df.merge(qb_team_set, on=team_key, how="left")

    # is_stacked_any = pass-catcher whose nfl_team is in any of the team's QB teams
    skill = df["position_name"].isin(["WR","TE","RB"])
    def in_set(row):
        s = row["qb_teams"]
        if s is None or not isinstance(s, set): return False
        return row["nfl_team"] in s if pd.notna(row["nfl_team"]) else False
    # Vectorize: build boolean via apply on the small subset of skill picks
    df["is_stack_any"] = False
    sk_idx = df.index[skill & df["nfl_team"].notna() & df["qb_teams"].notna()]
    if len(sk_idx):
        # build per-team membership lookup more efficiently: explode qb_teams into rows
        qbexp = qb_team_set.reset_index().explode("qb_teams")
        qbexp.columns = [team_key,"qbteam"]
        qbexp = qbexp.dropna()
        # Mark any (team_key, nfl_team) pair that exists in qbexp (where qbteam == nfl_team)
        pairs = set(zip(qbexp[team_key], qbexp["qbteam"]))
        sub = df.loc[sk_idx]
        df.loc[sk_idx, "is_stack_any"] = [(t, n) in pairs for t, n in zip(sub[team_key], sub["nfl_team"])]

    # is_stack_qb1 = pass-catcher same NFL team as QB1
    df["is_stack_qb1"] = (
        skill & df["nfl_team"].notna() & df["qb1_team"].notna()
        & (df["nfl_team"] == df["qb1_team"])
    )

    # Total stack count per team (any QB)
    total_stack = df.groupby(team_key)["is_stack_any"].sum().rename("total_stack").astype("int8")

    # Round of QB1's first same-team mate (NaN if naked QB)
    qb1_mates = df[df["is_stack_qb1"]].sort_values([team_key,"team_pick_number"])
    first_mate_round = qb1_mates.drop_duplicates(team_key, keep="first")[[team_key,"team_pick_number"]]
    first_mate_round.columns = [team_key,"qb1_first_mate_pick"]
    # team_pick_number is 1..18. Convert to draft "round" the same way: round = pick.
    # In BBM round = team_pick_number directly.

    # Specific QB1 + WR1 pair (when WR1 is same-team as QB1)
    # WR1 = first WR drafted per team
    wr1 = (df[df["position_name"]=="WR"]
           .drop_duplicates(team_key, keep="first")
           [[team_key,"player_name","nfl_team"]]
           .rename(columns={"player_name":"wr1_name","nfl_team":"wr1_team"}))
    qb1_name = (df[df["position_name"]=="QB"]
                .drop_duplicates(team_key, keep="first")
                [[team_key,"player_name"]]
                .rename(columns={"player_name":"qb1_name"}))

    teams = (df.drop_duplicates(team_key)[[team_key,"tournament_entry_id","qb1_team"]]
             .merge(total_stack, on=team_key)
             .merge(first_mate_round, on=team_key, how="left")
             .merge(qb1_name, on=team_key, how="left")
             .merge(wr1, on=team_key, how="left"))
    teams["adv"] = teams["tournament_entry_id"].isin(advanced).astype(int)
    teams["bbm"] = name
    print(f"[stack-extra] {name}:   teams: {len(teams):,}", flush=True)
    return teams


def main():
    rosters = {}
    for season in (2023,2024,2025):
        rosters[season] = pd.read_csv(
            ROSTER_DIR / f"roster_{season}.csv",
            usecols=["season","team","position","full_name"],
        )
        rosters[season] = rosters[season][
            rosters[season]["position"].isin(["QB","RB","WR","TE","FB","HB"])
        ].copy()
        rosters[season]["position"] = rosters[season]["position"].replace({"FB":"RB","HB":"RB"})
    name_team = {s: build_name_team_map(r) for s,r in rosters.items()}

    frames = []
    for spec in INPUTS:
        frames.append(process(spec, name_team[spec["season"]]))
    teams = pd.concat(frames, ignore_index=True)
    base = teams["adv"].mean()
    print(f"\n[stack-extra] combined teams: {len(teams):,}, baseline {base:.4f}", flush=True)

    # 1. Total stack count distribution
    print("\n=== TOTAL STACK PLAYER COUNT (across all QBs) ===", flush=True)
    print(f"{'n_total_stack':>14} | {'n':>10} | {'q_rate':>7} | {'lift':>5}", flush=True)
    print("-"*50, flush=True)
    out_total = {}
    for n in sorted(teams["total_stack"].unique()):
        sub = teams[teams["total_stack"]==n]
        if len(sub) < 200: continue
        q = sub["adv"].mean()
        out_total[int(n)] = {"n":int(len(sub)),"q_rate":round(float(q),4),"lift":round(float(q/base),3)}
        print(f"{int(n):>14} | {len(sub):>10,} | {q:>7.4f} | {q/base:>5.2f}", flush=True)

    # 2. Round of first stack mate
    print("\n=== ROUND OF QB1'S FIRST SAME-TEAM MATE ===", flush=True)
    sub = teams.dropna(subset=["qb1_first_mate_pick"]).copy()
    sub["round_bucket"] = pd.cut(
        sub["qb1_first_mate_pick"],
        bins=[0,3,6,9,12,18],
        labels=["1-3","4-6","7-9","10-12","13-18"],
    )
    out_round = {}
    print(f"{'rd_bucket':>10} | {'n':>10} | {'q_rate':>7} | {'lift':>5}", flush=True)
    print("-"*50, flush=True)
    for b, ss in sub.groupby("round_bucket", observed=True):
        if len(ss) < 200: continue
        q = ss["adv"].mean()
        out_round[str(b)] = {"n":int(len(ss)),"q_rate":round(float(q),4),"lift":round(float(q/base),3)}
        print(f"{str(b):>10} | {len(ss):>10,} | {q:>7.4f} | {q/base:>5.2f}", flush=True)
    naked = teams[teams["qb1_first_mate_pick"].isna()]
    if len(naked) >= 200:
        q = naked["adv"].mean()
        out_round["naked"] = {"n":int(len(naked)),"q_rate":round(float(q),4),"lift":round(float(q/base),3)}
        print(f"{'naked':>10} | {len(naked):>10,} | {q:>7.4f} | {q/base:>5.2f}", flush=True)

    # 3. Top specific QB↔WR1 same-team pairs.
    paired = teams[
        teams["wr1_team"].notna() & teams["qb1_team"].notna() &
        (teams["wr1_team"] == teams["qb1_team"])
    ]
    print(f"\n[stack-extra] teams with QB1+WR1 same-team pair: {len(paired):,}", flush=True)
    pair_stats = (paired.groupby(["bbm","qb1_name","wr1_name"])
                  .agg(n=("adv","count"), q=("adv","sum"))
                  .reset_index())
    pair_stats["q_rate"] = pair_stats["q"]/pair_stats["n"]

    # By frequency (within each year so we don't blur identities across years)
    print("\n=== TOP 15 MOST-DRAFTED QB+WR1 SAME-TEAM PAIRS PER YEAR ===", flush=True)
    out_top_freq = {}
    for yr in sorted(paired["bbm"].unique()):
        ys = pair_stats[pair_stats["bbm"]==yr].sort_values("n", ascending=False).head(15)
        print(f"\n  -- BBM {yr} --", flush=True)
        print(f"  {'QB':<22} {'WR1':<22} {'n':>7} {'q_rate':>7} {'lift':>5}", flush=True)
        out_top_freq[yr] = []
        for _, r in ys.iterrows():
            print(f"  {r['qb1_name']:<22} {r['wr1_name']:<22} {int(r['n']):>7,} {r['q_rate']:>7.4f} {r['q_rate']/base:>5.2f}", flush=True)
            out_top_freq[yr].append({
                "qb": r["qb1_name"], "wr1": r["wr1_name"],
                "n": int(r["n"]), "q_rate": round(float(r["q_rate"]),4),
                "lift": round(float(r["q_rate"]/base),3),
            })

    # By advance rate (min n=500 within a year)
    print("\n=== BEST QB+WR1 PAIRS BY ADVANCE RATE (min n=500) ===", flush=True)
    out_top_adv = {}
    for yr in sorted(paired["bbm"].unique()):
        ys = (pair_stats[(pair_stats["bbm"]==yr) & (pair_stats["n"]>=500)]
              .sort_values("q_rate", ascending=False).head(10))
        print(f"\n  -- BBM {yr} --", flush=True)
        print(f"  {'QB':<22} {'WR1':<22} {'n':>7} {'q_rate':>7} {'lift':>5}", flush=True)
        out_top_adv[yr] = []
        for _, r in ys.iterrows():
            print(f"  {r['qb1_name']:<22} {r['wr1_name']:<22} {int(r['n']):>7,} {r['q_rate']:>7.4f} {r['q_rate']/base:>5.2f}", flush=True)
            out_top_adv[yr].append({
                "qb": r["qb1_name"], "wr1": r["wr1_name"],
                "n": int(r["n"]), "q_rate": round(float(r["q_rate"]),4),
                "lift": round(float(r["q_rate"]/base),3),
            })

    obj = {
        "overall_baseline": round(float(base),4),
        "by_total_stack": out_total,
        "by_first_mate_round": out_round,
        "top_pairs_by_freq": out_top_freq,
        "top_pairs_by_advance": out_top_adv,
    }
    with OUT.open("w") as f:
        json.dump(obj, f, indent=2)
    print(f"\n[stack-extra] wrote {OUT.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
