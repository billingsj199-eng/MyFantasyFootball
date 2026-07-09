"""Stack composition x round-level advance rates.

For each team across BBM II-VI (2.6M teams):
  - Stack size = count of pass-catchers (WR/TE/RB) on QB1's NFL team
  - Per-rank flags for QB1's same-team mates: WR1, WR2, WR3, WR4, TE1, TE2,
    RB1, RB2 (positional rank within team draft order)

Then compute advance rate at each level (-> Quarterfinals, -> Semifinals,
-> Finals) for each cohort.

Outputs scripts/_bbm_stack_x_round.json + a clean text table.

2020 (BBM I) intentionally omitted (no position column in CSV).
"""
from __future__ import annotations
import json
import re
import unicodedata
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "Best Ball Mania Files"
DBOWL = BASE / "best-ball-data-bowl-master" / "best-ball-data-bowl-master" / "data"
ROSTER_DIR = ROOT / "scripts" / "_nflverse_rosters"
OUT = ROOT / "scripts" / "_bbm_stack_x_round.json"


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

_NAME_PUNCT = re.compile(r"[^\w\s]")


def norm_name(name):
    if not isinstance(name, str): return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii","ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\.?$", "", s)
    s = _NAME_PUNCT.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_name_team(season: int) -> dict:
    df = pd.read_csv(ROSTER_DIR / f"roster_{season}.csv",
                     usecols=["season","team","position","full_name"])
    df = df[df["position"].isin(["QB","RB","WR","TE","FB","HB"])].copy()
    df["position"] = df["position"].replace({"FB":"RB","HB":"RB"})
    m = {}
    for _, r in df.iterrows():
        k = (norm_name(r["full_name"]), r["position"])
        if k not in m: m[k] = r["team"]
    return m


def read_advance_set(files: list[Path]) -> set:
    if not files: return set()
    frames = []
    for f in files:
        if not Path(f).exists(): continue
        frames.append(pd.read_csv(f, usecols=["tournament_entry_id"]))
    if not frames: return set()
    return set(pd.concat(frames, ignore_index=True)["tournament_entry_id"].unique())


def read_rd1(spec: dict) -> pd.DataFrame:
    cols_base = ["tournament_entry_id","team_pick_number","position_name","player_name"]
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


def per_team(df: pd.DataFrame, name_team: dict) -> pd.DataFrame:
    """One row per team with stack-size + per-rank flags."""
    keys = list(zip(df["player_name"].map(norm_name), df["position_name"]))
    df = df.copy()
    df["nfl_team"] = [name_team.get(k) for k in keys]

    tk = "tournament_round_draft_entry_id"
    df = df.sort_values([tk, "team_pick_number"], kind="stable").reset_index(drop=True)

    qbs = df[(df["position_name"]=="QB") & df["nfl_team"].notna()]
    qb1 = qbs.drop_duplicates(tk, keep="first")[[tk,"nfl_team"]].rename(columns={"nfl_team":"qb1_team"})
    df = df.merge(qb1, on=tk, how="left")

    skill = df["position_name"].isin(["WR","TE","RB"])
    df["is_stack_qb1"] = (
        skill & df["nfl_team"].notna() & df["qb1_team"].notna()
        & (df["nfl_team"] == df["qb1_team"])
    )

    # Position rank within team for WR/TE/RB
    df["_pr"] = 0
    for pos in ("WR","TE","RB"):
        m = df["position_name"] == pos
        df.loc[m, "_pr"] = df[m].groupby(tk).cumcount() + 1

    # Per-rank flags (all booleans on stacked picks)
    df["f_wr1"] = df["is_stack_qb1"] & (df["position_name"]=="WR") & (df["_pr"]==1)
    df["f_wr2"] = df["is_stack_qb1"] & (df["position_name"]=="WR") & (df["_pr"]==2)
    df["f_wr3"] = df["is_stack_qb1"] & (df["position_name"]=="WR") & (df["_pr"]==3)
    df["f_wr4"] = df["is_stack_qb1"] & (df["position_name"]=="WR") & (df["_pr"]==4)
    df["f_te1"] = df["is_stack_qb1"] & (df["position_name"]=="TE") & (df["_pr"]==1)
    df["f_te2"] = df["is_stack_qb1"] & (df["position_name"]=="TE") & (df["_pr"]==2)
    df["f_rb1"] = df["is_stack_qb1"] & (df["position_name"]=="RB") & (df["_pr"]==1)
    df["f_rb2"] = df["is_stack_qb1"] & (df["position_name"]=="RB") & (df["_pr"]==2)

    flag_cols = ["f_wr1","f_wr2","f_wr3","f_wr4","f_te1","f_te2","f_rb1","f_rb2"]
    flags = df.groupby(tk).agg(**{c: (c, "any") for c in flag_cols}).reset_index()
    # Stack size on QB1 (same-team mates count)
    stack_size = df.groupby(tk)["is_stack_qb1"].sum().rename("qb1_stack").astype("int8")

    teams = df.drop_duplicates(tk)[[tk,"tournament_entry_id","qb1_team"]].copy()
    teams = teams.merge(flags, on=tk).merge(stack_size, on=tk)
    teams = teams.rename(columns={c: c.replace("f_","has_") for c in flag_cols})
    return teams


def main():
    print("[stk-rd] loading rosters ...", flush=True)
    rosters = {y: load_name_team(y) for y in (2021,2022,2023,2024,2025)}

    all_teams = []
    for spec in INPUTS:
        print(f"\n[stk-rd] === BBM {spec['name']} ===", flush=True)
        print(f"[stk-rd] reading rd1 ...", flush=True)
        df = read_rd1(spec)
        print(f"[stk-rd]   rows {len(df):,}", flush=True)
        teams = per_team(df, rosters[spec["season"]])
        adv_qf  = read_advance_set(spec["rd2"])
        adv_sf  = read_advance_set(spec["rd3"])
        adv_fin = read_advance_set(spec["rd4"])
        teams["adv_qf"]  = teams["tournament_entry_id"].isin(adv_qf).astype(int)
        teams["adv_sf"]  = teams["tournament_entry_id"].isin(adv_sf).astype(int)
        teams["adv_fin"] = teams["tournament_entry_id"].isin(adv_fin).astype(int)
        teams["bbm"] = spec["name"]
        print(f"[stk-rd]   teams {len(teams):,}  qf:{teams['adv_qf'].sum():,}  "
              f"sf:{teams['adv_sf'].sum():,}  fin:{teams['adv_fin'].sum():,}", flush=True)
        all_teams.append(teams)

    teams = pd.concat(all_teams, ignore_index=True)
    n = len(teams)
    base_qf  = teams["adv_qf"].mean()
    base_sf  = teams["adv_sf"].mean()
    base_fin = teams["adv_fin"].mean()
    print(f"\n[stk-rd] combined: {n:,} teams", flush=True)
    print(f"[stk-rd]   baselines  qf {base_qf:.4%}  sf {base_sf:.4%}  fin {base_fin:.4%}", flush=True)

    out = {
        "n_total": int(n),
        "baselines": {"qf": round(float(base_qf),5),
                      "sf": round(float(base_sf),5),
                      "fin": round(float(base_fin),5)},
        "stack_size": [],
        "per_rank": [],
        "rank_pairs": [],
    }

    def emit(label, sub, key="key"):
        if len(sub) < 200: return None
        qf, sf, fin = sub["adv_qf"].mean(), sub["adv_sf"].mean(), sub["adv_fin"].mean()
        return {
            key: label,
            "n": int(len(sub)),
            "qf_rate": round(float(qf),5),
            "qf_lift": round(float(qf/base_qf),3) if base_qf else None,
            "sf_rate": round(float(sf),5),
            "sf_lift": round(float(sf/base_sf),3) if base_sf else None,
            "fin_rate": round(float(fin),5),
            "fin_lift": round(float(fin/base_fin),3) if base_fin else None,
        }

    # ---------- Stack-size buckets ----------
    print("\n=== Stack size (QB+N same-team mates) ===", flush=True)
    print(f"{'size':>6} | {'n':>10} | {'-> QF':>9} {'lift':>6} | {'-> SF':>9} {'lift':>6} | {'-> Fin':>9} {'lift':>6}", flush=True)
    print("-" * 90, flush=True)
    for sz in sorted(teams["qb1_stack"].unique()):
        # bucket label: 0, 1, 2, 3, 4+
        lbl = f"{sz}+" if sz >= 4 else str(int(sz))
        if sz >= 4:
            sub = teams[teams["qb1_stack"] >= 4]
        else:
            sub = teams[teams["qb1_stack"] == sz]
        if len(sub) < 200: continue
        row = emit(lbl, sub, key="size")
        if row is None: continue
        if any(r["size"] == lbl for r in out["stack_size"]): continue  # dedupe 4+
        out["stack_size"].append(row)
        print(
            f"{lbl:>6} | {row['n']:>10,} | "
            f"{row['qf_rate']*100:>8.3f}% {row['qf_lift']:>6.2f} | "
            f"{row['sf_rate']*100:>8.3f}% {row['sf_lift']:>6.2f} | "
            f"{row['fin_rate']*100:>8.3f}% {row['fin_lift']:>6.2f}",
            flush=True,
        )
        if sz >= 4: break

    # ---------- Per-rank flags ----------
    flag_labels = [
        ("has_wr1","QB+WR1"), ("has_wr2","QB+WR2"),
        ("has_wr3","QB+WR3"), ("has_wr4","QB+WR4"),
        ("has_te1","QB+TE1"), ("has_te2","QB+TE2"),
        ("has_rb1","QB+RB1"), ("has_rb2","QB+RB2"),
    ]
    print("\n=== Per-rank stack mate (cohort = team has this AS A SAME-TEAM PIECE) ===", flush=True)
    print(f"{'flag':>10} | {'n':>10} | {'-> QF':>9} {'lift':>6} | {'-> SF':>9} {'lift':>6} | {'-> Fin':>9} {'lift':>6}", flush=True)
    print("-" * 95, flush=True)
    for col, lbl in flag_labels:
        sub = teams[teams[col]]
        row = emit(lbl, sub, key="flag")
        if row is None: continue
        out["per_rank"].append(row)
        print(
            f"{lbl:>10} | {row['n']:>10,} | "
            f"{row['qf_rate']*100:>8.3f}% {row['qf_lift']:>6.2f} | "
            f"{row['sf_rate']*100:>8.3f}% {row['sf_lift']:>6.2f} | "
            f"{row['fin_rate']*100:>8.3f}% {row['fin_lift']:>6.2f}",
            flush=True,
        )

    # ---------- Composite pair flags ----------
    print("\n=== Notable pair compositions ===", flush=True)
    print(f"{'pattern':>16} | {'n':>10} | {'-> QF':>9} {'lift':>6} | {'-> SF':>9} {'lift':>6} | {'-> Fin':>9} {'lift':>6}", flush=True)
    print("-" * 100, flush=True)
    pair_specs = [
        ("WR1+WR2",    teams["has_wr1"] & teams["has_wr2"]),
        ("WR1+WR3",    teams["has_wr1"] & teams["has_wr3"]),
        ("WR1+TE1",    teams["has_wr1"] & teams["has_te1"]),
        ("WR1+RB1",    teams["has_wr1"] & teams["has_rb1"]),
        ("TE1+WR2",    teams["has_te1"] & teams["has_wr2"]),
        ("WR1 only (no WR2/3/4/TE1/RB1)",
            teams["has_wr1"] & ~teams["has_wr2"] & ~teams["has_wr3"]
            & ~teams["has_wr4"] & ~teams["has_te1"] & ~teams["has_rb1"]),
        ("Naked QB",
            ~teams["has_wr1"] & ~teams["has_wr2"] & ~teams["has_wr3"]
            & ~teams["has_wr4"] & ~teams["has_te1"] & ~teams["has_te2"]
            & ~teams["has_rb1"] & ~teams["has_rb2"]),
    ]
    for lbl, mask in pair_specs:
        sub = teams[mask]
        row = emit(lbl, sub, key="pattern")
        if row is None: continue
        out["rank_pairs"].append(row)
        print(
            f"{lbl:>16} | {row['n']:>10,} | "
            f"{row['qf_rate']*100:>8.3f}% {row['qf_lift']:>6.2f} | "
            f"{row['sf_rate']*100:>8.3f}% {row['sf_lift']:>6.2f} | "
            f"{row['fin_rate']*100:>8.3f}% {row['fin_lift']:>6.2f}",
            flush=True,
        )

    with OUT.open("w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[stk-rd] wrote {OUT.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
