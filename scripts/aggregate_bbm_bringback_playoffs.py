"""Bringback stacks in BBM playoff weeks (15/16/17).

For each BBM team, identify "bringback" games in NFL playoff weeks:
  - Week 15 -> affects QF -> SF advance (rd2)
  - Week 16 -> affects SF -> Finals advance (rd3)
  - Week 17 -> affects Finals win (rd4)

A bringback for game G = team has >=1 player on home_team AND >=1 player
on away_team of G.

Cohorts are conditional on having reached that round. So:
  - Among teams that made QF, bringback_w15 -> SF rate
  - Among teams that made SF, bringback_w16 -> Finals rate
Plus high-total vs low-total game conditional.

Outputs scripts/_bbm_bringback_playoffs.json + console tables.
"""
from __future__ import annotations
import json
import re
import unicodedata
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "Best Ball Mania Files"
DBOWL = BASE / "best-ball-data-bowl-master" / "best-ball-data-bowl-master" / "data"
ROSTER_DIR = ROOT / "scripts" / "_nflverse_rosters"
SCHED_FILE = ROOT / "scripts" / "_nflverse_schedules.csv"
OUT = ROOT / "scripts" / "_bbm_bringback_playoffs.json"


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


def load_schedule_week(season: int, week: int) -> pd.DataFrame:
    """Returns games for that NFL season+week with columns home_team, away_team, total."""
    sched = pd.read_csv(SCHED_FILE, usecols=["season","week","game_type","away_team","home_team","total"])
    sched = sched[(sched["season"]==season) & (sched["week"]==week) & (sched["game_type"]=="REG")].copy()
    sched["total"] = pd.to_numeric(sched["total"], errors="coerce")
    return sched.reset_index(drop=True)


def team_nfl_table(df: pd.DataFrame, name_team: dict, tk: str):
    """Returns (tab, eid_map) where:
       tab = bool DataFrame indexed by tk, columns=NFL team abbrev
       eid_map = DataFrame with [tk, tournament_entry_id]
    """
    keys = list(zip(df["player_name"].map(norm_name), df["position_name"]))
    df = df.copy()
    df["nfl_team"] = [name_team.get(k) for k in keys]
    df = df[df["nfl_team"].notna()]
    tab = pd.crosstab(df[tk], df["nfl_team"]) > 0
    eid = df.drop_duplicates(tk).set_index(tk)["tournament_entry_id"]
    return tab, eid


def bringback_features_vec(tab: pd.DataFrame, games: pd.DataFrame):
    """Vectorized: returns (bb_count, bb_max_total) numpy arrays aligned to tab.index."""
    n = len(tab)
    bb_count = np.zeros(n, dtype=np.int16)
    bb_max = np.full(n, -np.inf, dtype=np.float32)
    for _, row in games.iterrows():
        h, a, tot = str(row["home_team"]), str(row["away_team"]), row["total"]
        if h not in tab.columns or a not in tab.columns:
            continue
        mask = (tab[h] & tab[a]).values
        bb_count += mask.astype(np.int16)
        if pd.notna(tot):
            t = float(tot)
            bb_max = np.where(mask & (t > bb_max), t, bb_max)
    bb_max_out = np.where(bb_max == -np.inf, np.nan, bb_max)
    return bb_count, bb_max_out


def main():
    print("[bb] loading rosters ...", flush=True)
    rosters = {y: load_name_team(y) for y in (2021,2022,2023,2024,2025)}

    all_team_records = []  # one row per BBM team across all seasons
    for spec in INPUTS:
        print(f"\n[bb] === BBM {spec['name']} (season {spec['season']}) ===", flush=True)
        df = read_rd1(spec)
        print(f"[bb]   rd1 rows {len(df):,}", flush=True)

        tk = "tournament_round_draft_entry_id"
        tab, eid = team_nfl_table(df, rosters[spec["season"]], tk)
        print(f"[bb]   teams {len(tab):,}  nfl_teams {tab.shape[1]}", flush=True)

        # Load schedules for the three playoff weeks
        sched_w15 = load_schedule_week(spec["season"], 15)
        sched_w16 = load_schedule_week(spec["season"], 16)
        sched_w17 = load_schedule_week(spec["season"], 17)
        print(f"[bb]   week15 games {len(sched_w15)}  week16 games {len(sched_w16)}  week17 games {len(sched_w17)}", flush=True)

        teams = pd.DataFrame({"_tk": tab.index})
        teams["tournament_entry_id"] = teams["_tk"].map(eid).values
        for wk_label, sched in (("w15", sched_w15), ("w16", sched_w16), ("w17", sched_w17)):
            cnt, mx = bringback_features_vec(tab, sched)
            teams[f"bb_{wk_label}_count"] = cnt
            teams[f"bb_{wk_label}_max_total"] = mx

        # Advance flags
        adv_qf  = read_advance_set(spec["rd2"])
        adv_sf  = read_advance_set(spec["rd3"])
        adv_fin = read_advance_set(spec["rd4"])
        teams["adv_qf"]  = teams["tournament_entry_id"].isin(adv_qf).astype(int)
        teams["adv_sf"]  = teams["tournament_entry_id"].isin(adv_sf).astype(int)
        teams["adv_fin"] = teams["tournament_entry_id"].isin(adv_fin).astype(int)
        teams["bbm"] = spec["name"]
        teams["season"] = spec["season"]
        print(f"[bb]   qf:{teams['adv_qf'].sum():,}  sf:{teams['adv_sf'].sum():,}  fin:{teams['adv_fin'].sum():,}", flush=True)
        all_team_records.append(teams.drop(columns=["_tk"]))

    teams = pd.concat(all_team_records, ignore_index=True)
    n = len(teams)
    print(f"\n[bb] combined: {n:,} teams across {len(INPUTS)} BBMs", flush=True)

    # Conditional cohorts
    qf_cohort  = teams[teams["adv_qf"] == 1].copy()
    sf_cohort  = teams[teams["adv_sf"] == 1].copy()
    fin_cohort = teams[teams["adv_fin"] == 1].copy()
    print(f"[bb]   QF cohort {len(qf_cohort):,}  SF cohort {len(sf_cohort):,}  Fin cohort {len(fin_cohort):,}", flush=True)

    out = {
        "n_total": int(n),
        "n_qf": int(len(qf_cohort)),
        "n_sf": int(len(sf_cohort)),
        "n_fin": int(len(fin_cohort)),
        "qf_to_sf": [],         # bringback_w15 -> SF advance rate (cohort: made QF)
        "sf_to_fin": [],        # bringback_w16 -> Fin advance rate (cohort: made SF)
        "fin_to_won": [],       # bringback_w17 -> won (cohort: made Finals; tiny sample)
        "qf_to_sf_by_total": [],  # bringback_w15 + game_total tier
        "sf_to_fin_by_total": [], # bringback_w16 + game_total tier
    }

    def emit(cohort: pd.DataFrame, mask, target_col: str, label: str, key="bucket"):
        sub = cohort[mask]
        if len(sub) == 0: return None
        rate = sub[target_col].mean()
        return {key: label, "n": int(len(sub)),
                "rate": round(float(rate),5),
                "lift": round(float(rate / cohort[target_col].mean()), 3) if cohort[target_col].mean() else None}

    def print_table(title, rows, key="bucket"):
        print(f"\n=== {title} ===", flush=True)
        print(f"{'bucket':>30} | {'n':>8} | {'rate':>9} {'lift':>6}", flush=True)
        print("-" * 70, flush=True)
        for r in rows:
            print(f"{r[key]:>30} | {r['n']:>8,} | {r['rate']*100:>8.3f}% {r['lift']:>6.2f}", flush=True)

    # --- QF -> SF by week-15 bringback count ---
    print(f"\n[bb] QF cohort baseline SF rate: {qf_cohort['adv_sf'].mean():.4%}", flush=True)
    for cnt in (0, 1, 2, 3):
        if cnt == 3:
            mask = qf_cohort["bb_w15_count"] >= 3
            lbl = "3+"
        else:
            mask = qf_cohort["bb_w15_count"] == cnt
            lbl = str(cnt)
        row = emit(qf_cohort, mask, "adv_sf", lbl)
        if row: out["qf_to_sf"].append(row)
    print_table("QF -> SF by week-15 bringback count", out["qf_to_sf"])

    # --- SF -> Finals by week-16 bringback count ---
    print(f"\n[bb] SF cohort baseline Fin rate: {sf_cohort['adv_fin'].mean():.4%}", flush=True)
    for cnt in (0, 1, 2, 3):
        if cnt == 3:
            mask = sf_cohort["bb_w16_count"] >= 3
            lbl = "3+"
        else:
            mask = sf_cohort["bb_w16_count"] == cnt
            lbl = str(cnt)
        row = emit(sf_cohort, mask, "adv_fin", lbl)
        if row: out["sf_to_fin"].append(row)
    print_table("SF -> Finals by week-16 bringback count", out["sf_to_fin"])

    # --- Finals -> Won by week-17 bringback count (tiny sample) ---
    if len(fin_cohort) > 0:
        # winners are top scorer per BBM season; we don't have winner data structured here
        # so just show distribution of bringbacks among finalists
        print(f"\n[bb] Finalists: {len(fin_cohort)}  (winner data not in this output)", flush=True)
        dist = fin_cohort["bb_w17_count"].value_counts().sort_index()
        print("[bb] week-17 bringback count distribution among finalists:", flush=True)
        for k, v in dist.items():
            print(f"    bb_w17={k}: {v}", flush=True)

    # --- QF -> SF: bringback x game total tier ---
    # Tier high if max_total >= 47 (typical NFL high), low if <= 42, mid otherwise.
    # 47 / 42 are based on league-wide medians (~44.5).
    print(f"\n[bb] Game-total tiers: high >= 47, low <= 42, mid in between", flush=True)
    for tier_name, tier_mask in (
        ("no_bb",   qf_cohort["bb_w15_count"] == 0),
        ("bb_low",  (qf_cohort["bb_w15_count"] >= 1) & (qf_cohort["bb_w15_max_total"] <= 42)),
        ("bb_mid",  (qf_cohort["bb_w15_count"] >= 1) & (qf_cohort["bb_w15_max_total"] > 42) & (qf_cohort["bb_w15_max_total"] < 47)),
        ("bb_high", (qf_cohort["bb_w15_count"] >= 1) & (qf_cohort["bb_w15_max_total"] >= 47)),
    ):
        row = emit(qf_cohort, tier_mask, "adv_sf", tier_name)
        if row: out["qf_to_sf_by_total"].append(row)
    print_table("QF -> SF by week-15 bringback x game total", out["qf_to_sf_by_total"])

    for tier_name, tier_mask in (
        ("no_bb",   sf_cohort["bb_w16_count"] == 0),
        ("bb_low",  (sf_cohort["bb_w16_count"] >= 1) & (sf_cohort["bb_w16_max_total"] <= 42)),
        ("bb_mid",  (sf_cohort["bb_w16_count"] >= 1) & (sf_cohort["bb_w16_max_total"] > 42) & (sf_cohort["bb_w16_max_total"] < 47)),
        ("bb_high", (sf_cohort["bb_w16_count"] >= 1) & (sf_cohort["bb_w16_max_total"] >= 47)),
    ):
        row = emit(sf_cohort, tier_mask, "adv_fin", tier_name)
        if row: out["sf_to_fin_by_total"].append(row)
    print_table("SF -> Finals by week-16 bringback x game total", out["sf_to_fin_by_total"])

    with OUT.open("w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[bb] wrote {OUT.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
