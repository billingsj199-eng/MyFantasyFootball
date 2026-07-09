"""Bringback effect on Finals SCORE (not just advance).

The advance-rate framing ignores that the championship is one finalist
beating the others on week-17 score. This script:
  - Loads each finalist's roster_points (week-17 score)
  - Computes their week-17 bringback features (count, max game total)
  - Ranks finalists within season (percentile)
  - Bins by: top 5% / top 25% / middle / bottom 25% / bottom 5% / decile

Outputs scripts/_bbm_finals_bringback.json + console tables.
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
OUT = ROOT / "scripts" / "_bbm_finals_bringback.json"


def _glob(pat: Path) -> list[Path]:
    return sorted(pat.parent.glob(pat.name))


INPUTS = [
    {"name": "II", "season": 2021, "team_key": "tournament_entry_id",
     "rd1": _glob(DBOWL/"2021"/"regular_season"/"part_*.csv"),
     "rd4": [DBOWL/"2021"/"post_season"/"finals.csv"]},
    {"name": "III", "season": 2022, "team_key": "tournament_round_draft_entry_id",
     "rd1": (_glob(DBOWL/"2022"/"regular_season"/"fast"/"part_*.csv") +
             _glob(DBOWL/"2022"/"regular_season"/"mixed"/"part_*.csv")),
     "rd4": _glob(DBOWL/"2022"/"post_season"/"finals"/"part_*.csv")},
    {"name": "IV", "season": 2023, "team_key": "tournament_round_draft_entry_id",
     "rd1": [BASE/"BBM IV"/"best_ball_mania_iv_2023_r1_results_pick_by_pick.csv"],
     "rd4": [BASE/"BBM IV"/"best_ball_mania_iv_2023_r4_results_pick_by_pick.csv"]},
    {"name": "V", "season": 2024, "team_key": "tournament_round_draft_entry_id",
     "rd1": [BASE/"BBM V"/"best_ball_mania_v_rd1.csv"],
     "rd4": [BASE/"BBM V"/"best_ball_mania_v_rd4.csv"]},
    {"name": "VI", "season": 2025, "team_key": "tournament_round_draft_entry_id",
     "rd1": [BASE/"BBM VI"/"best_ball_mania_vi_rd1.csv"],
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


def read_finalists(spec: dict) -> pd.DataFrame:
    """Returns one row per finalist team with tournament_entry_id + roster_points."""
    frames = []
    for f in spec["rd4"]:
        if not Path(f).exists(): continue
        first = pd.read_csv(f, nrows=0).columns.tolist()
        cols = [c for c in ("tournament_entry_id","roster_points") if c in first]
        frames.append(pd.read_csv(f, usecols=cols))
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["roster_points"]).drop_duplicates("tournament_entry_id")
    return df.reset_index(drop=True)


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
    sched = pd.read_csv(SCHED_FILE, usecols=["season","week","game_type","away_team","home_team","total"])
    sched = sched[(sched["season"]==season) & (sched["week"]==week) & (sched["game_type"]=="REG")].copy()
    sched["total"] = pd.to_numeric(sched["total"], errors="coerce")
    return sched.reset_index(drop=True)


def team_nfl_table(df: pd.DataFrame, name_team: dict, tk: str):
    keys = list(zip(df["player_name"].map(norm_name), df["position_name"]))
    df = df.copy()
    df["nfl_team"] = [name_team.get(k) for k in keys]
    df = df[df["nfl_team"].notna()]
    tab = pd.crosstab(df[tk], df["nfl_team"]) > 0
    eid = df.drop_duplicates(tk).set_index(tk)["tournament_entry_id"]
    return tab, eid


def bringback_features_vec(tab: pd.DataFrame, games: pd.DataFrame):
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
    print("[fb] loading rosters ...", flush=True)
    rosters = {y: load_name_team(y) for y in (2021,2022,2023,2024,2025)}

    all_finalists = []
    for spec in INPUTS:
        print(f"\n[fb] === BBM {spec['name']} (season {spec['season']}) ===", flush=True)
        finals = read_finalists(spec)
        print(f"[fb]   finalists {len(finals):,}  pts mean={finals['roster_points'].mean():.1f}  "
              f"min={finals['roster_points'].min():.1f}  max={finals['roster_points'].max():.1f}", flush=True)

        # Read rd1 picks for these finalists ONLY
        df = read_rd1(spec)
        df = df[df["tournament_entry_id"].isin(set(finals["tournament_entry_id"]))]
        print(f"[fb]   rd1 picks for finalists: {len(df):,}", flush=True)

        tk = "tournament_round_draft_entry_id"
        tab, eid = team_nfl_table(df, rosters[spec["season"]], tk)

        sched_w17 = load_schedule_week(spec["season"], 17)
        cnt, mx = bringback_features_vec(tab, sched_w17)
        feats = pd.DataFrame({
            tk: tab.index,
            "bb_w17_count": cnt,
            "bb_w17_max_total": mx,
        })
        feats["tournament_entry_id"] = feats[tk].map(eid).values
        feats = feats[["tournament_entry_id","bb_w17_count","bb_w17_max_total"]]

        merged = finals.merge(feats, on="tournament_entry_id", how="left")
        merged["bb_w17_count"] = merged["bb_w17_count"].fillna(0).astype(int)
        merged["season"] = spec["season"]
        merged["bbm"] = spec["name"]
        merged["pct_rank"] = merged["roster_points"].rank(method="first", pct=True, ascending=True)
        all_finalists.append(merged)

    fin = pd.concat(all_finalists, ignore_index=True)
    n = len(fin)
    print(f"\n[fb] combined finalists: {n:,}", flush=True)

    out = {"n_total": int(n)}

    def stats_row(sub: pd.DataFrame, label: str):
        if len(sub) == 0:
            return None
        return {
            "bucket": label,
            "n": int(len(sub)),
            "mean_bb": round(float(sub["bb_w17_count"].mean()), 3),
            "mean_max_total": round(float(sub["bb_w17_max_total"].dropna().mean()) if sub["bb_w17_max_total"].notna().any() else 0.0, 2),
            "pct_high_total": round(float((sub["bb_w17_max_total"] >= 47).mean()), 3),
            "pct_low_total":  round(float((sub["bb_w17_max_total"] <= 42).mean()), 3),
            "pct_no_bb":      round(float((sub["bb_w17_count"] == 0).mean()), 3),
        }

    def print_table(title, rows):
        print(f"\n=== {title} ===", flush=True)
        print(f"{'bucket':>20} | {'n':>5} | {'mean_bb':>8} | {'mean_top':>8} | {'%high':>6} | {'%low':>6} | {'%no_bb':>7}", flush=True)
        print("-" * 90, flush=True)
        for r in rows:
            print(f"{r['bucket']:>20} | {r['n']:>5,} | {r['mean_bb']:>8.2f} | "
                  f"{r['mean_max_total']:>8.2f} | {r['pct_high_total']*100:>5.1f}% | "
                  f"{r['pct_low_total']*100:>5.1f}% | {r['pct_no_bb']*100:>6.1f}%", flush=True)

    # ---- Top 5% / Top 25% / Middle 50% / Bottom 25% / Bottom 5% (within season) ----
    bucket_rows = []
    for label, mask in [
        ("Top 5%",       fin["pct_rank"] >= 0.95),
        ("Top 6-25%",    (fin["pct_rank"] >= 0.75) & (fin["pct_rank"] < 0.95)),
        ("Middle 26-74%",(fin["pct_rank"] >= 0.25) & (fin["pct_rank"] < 0.75)),
        ("Bottom 6-25%", (fin["pct_rank"] >= 0.05) & (fin["pct_rank"] < 0.25)),
        ("Bottom 5%",    fin["pct_rank"] < 0.05),
    ]:
        r = stats_row(fin[mask], label)
        if r: bucket_rows.append(r)
    out["percentile_buckets"] = bucket_rows
    print_table("Finals score percentile buckets (within-season)", bucket_rows)

    # ---- Decile gradient ----
    decile_rows = []
    for d in range(10):
        lo, hi = d/10, (d+1)/10
        mask = (fin["pct_rank"] >= lo) & (fin["pct_rank"] < hi)
        if d == 9:
            mask = fin["pct_rank"] >= 0.9
        r = stats_row(fin[mask], f"D{d+1} ({int(lo*100)}-{int(hi*100)}%)")
        if r: decile_rows.append(r)
    out["deciles"] = decile_rows
    print_table("Decile gradient (D1 lowest, D10 highest)", decile_rows)

    # ---- Top 100 vs Bottom 100 (raw count, cross-season) ----
    top100 = fin.nlargest(100, "roster_points")
    bot100 = fin.nsmallest(100, "roster_points")
    extreme_rows = [stats_row(top100, "Top 100 overall"),
                    stats_row(bot100, "Bottom 100 overall")]
    out["extremes_raw"] = extreme_rows
    print_table("Raw extremes: Top 100 vs Bottom 100 finalists (cross-season)", extreme_rows)

    # ---- Top 100 vs Bottom 100 within EACH BBM ----
    print("\n=== Top 100 vs Bottom 100 within each BBM ===", flush=True)
    per_bbm = []
    for bbm_name in fin["bbm"].unique():
        sub = fin[fin["bbm"] == bbm_name]
        n_take = min(100, len(sub) // 2)
        if n_take < 20: continue
        top = sub.nlargest(n_take, "roster_points")
        bot = sub.nsmallest(n_take, "roster_points")
        per_bbm.append({
            "bbm": bbm_name,
            "n_per_side": int(n_take),
            "top_mean_bb": round(float(top["bb_w17_count"].mean()), 3),
            "bot_mean_bb": round(float(bot["bb_w17_count"].mean()), 3),
            "top_pct_high": round(float((top["bb_w17_max_total"] >= 47).mean()), 3),
            "bot_pct_high": round(float((bot["bb_w17_max_total"] >= 47).mean()), 3),
            "top_pct_low":  round(float((top["bb_w17_max_total"] <= 42).mean()), 3),
            "bot_pct_low":  round(float((bot["bb_w17_max_total"] <= 42).mean()), 3),
            "top_mean_pts": round(float(top["roster_points"].mean()), 2),
            "bot_mean_pts": round(float(bot["roster_points"].mean()), 2),
        })
    print(f"{'BBM':>4} | {'n':>3} | {'top_bb':>7} {'bot_bb':>7} | "
          f"{'top_hi%':>7} {'bot_hi%':>7} | {'top_lo%':>7} {'bot_lo%':>7} | "
          f"{'top_pts':>7} {'bot_pts':>7}", flush=True)
    print("-" * 100, flush=True)
    for r in per_bbm:
        print(f"{r['bbm']:>4} | {r['n_per_side']:>3} | "
              f"{r['top_mean_bb']:>7.2f} {r['bot_mean_bb']:>7.2f} | "
              f"{r['top_pct_high']*100:>6.1f}% {r['bot_pct_high']*100:>6.1f}% | "
              f"{r['top_pct_low']*100:>6.1f}% {r['bot_pct_low']*100:>6.1f}% | "
              f"{r['top_mean_pts']:>7.1f} {r['bot_mean_pts']:>7.1f}", flush=True)
    out["per_bbm_extremes"] = per_bbm

    # ---- Pearson correlation between bb_w17_count and roster_points ----
    # And between bb_w17_max_total and roster_points (controlling for bb presence)
    overall_corr_count = fin[["bb_w17_count","roster_points"]].corr().iloc[0,1]
    fin_with_bb = fin[fin["bb_w17_count"] >= 1].copy()
    overall_corr_total = fin_with_bb[["bb_w17_max_total","roster_points"]].corr().iloc[0,1]
    print(f"\n[fb] correlations (within finalists):", flush=True)
    print(f"  bb_count -> roster_points     : r = {overall_corr_count:+.3f}  (n={len(fin):,})", flush=True)
    print(f"  bb_max_total -> roster_points : r = {overall_corr_total:+.3f}  (n={len(fin_with_bb):,})", flush=True)
    out["correlations"] = {
        "bb_count_vs_pts": round(float(overall_corr_count), 4),
        "bb_max_total_vs_pts_given_bb": round(float(overall_corr_total), 4),
    }

    # Per-season correlation (to test stability)
    print(f"\n[fb] per-BBM correlations:", flush=True)
    per_bbm_corr = []
    for bbm_name in sorted(fin["bbm"].unique()):
        sub = fin[fin["bbm"] == bbm_name]
        sub_bb = sub[sub["bb_w17_count"] >= 1]
        c1 = sub[["bb_w17_count","roster_points"]].corr().iloc[0,1]
        c2 = sub_bb[["bb_w17_max_total","roster_points"]].corr().iloc[0,1] if len(sub_bb) > 5 else float("nan")
        print(f"  BBM {bbm_name:>3}  bb_cnt:{c1:+.3f}  bb_max_tot:{c2:+.3f}  (n={len(sub):,}, n_bb={len(sub_bb):,})", flush=True)
        per_bbm_corr.append({
            "bbm": bbm_name,
            "bb_count_vs_pts": round(float(c1), 4) if pd.notna(c1) else None,
            "bb_max_total_vs_pts_given_bb": round(float(c2), 4) if pd.notna(c2) else None,
            "n": int(len(sub)),
            "n_with_bb": int(len(sub_bb)),
        })
    out["per_bbm_correlations"] = per_bbm_corr

    with OUT.open("w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[fb] wrote {OUT.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
