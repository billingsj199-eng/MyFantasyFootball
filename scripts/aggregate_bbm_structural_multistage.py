"""Bye-concentration + RB cannibalization + WR-no-QB cannib at all 3 BBM stages.

Existing _bbm_correlations.json was QF-only. This script re-aggregates
the same three structural features but tracks adv_qf / adv_sf / adv_fin
so we can blend across tournament stages in the construction score.

Outputs scripts/_bbm_structural_multistage.json.
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "Best Ball Mania Files"
DBOWL = BASE / "best-ball-data-bowl-master" / "best-ball-data-bowl-master" / "data"
OUT = ROOT / "scripts" / "_bbm_structural_multistage.json"

NFL_BYE_BY_TEAM = None  # we don't strictly need it — bye-week tracking via roster bye_week column

def _glob(pat: Path) -> list[Path]:
    return sorted(pat.parent.glob(pat.name))

INPUTS = [
    {"name":"II","season":2021,"team_key":"tournament_entry_id",
     "rd1":_glob(DBOWL/"2021"/"regular_season"/"part_*.csv"),
     "rd2":[DBOWL/"2021"/"post_season"/"quarterfinals.csv"],
     "rd3":[DBOWL/"2021"/"post_season"/"semifinals.csv"],
     "rd4":[DBOWL/"2021"/"post_season"/"finals.csv"]},
    {"name":"III","season":2022,"team_key":"tournament_round_draft_entry_id",
     "rd1":(_glob(DBOWL/"2022"/"regular_season"/"fast"/"part_*.csv")+
            _glob(DBOWL/"2022"/"regular_season"/"mixed"/"part_*.csv")),
     "rd2":_glob(DBOWL/"2022"/"post_season"/"quarterfinals"/"part_*.csv"),
     "rd3":_glob(DBOWL/"2022"/"post_season"/"semifinals"/"part_*.csv"),
     "rd4":_glob(DBOWL/"2022"/"post_season"/"finals"/"part_*.csv")},
    {"name":"IV","season":2023,"team_key":"tournament_round_draft_entry_id",
     "rd1":[BASE/"BBM IV"/"best_ball_mania_iv_2023_r1_results_pick_by_pick.csv"],
     "rd2":[BASE/"BBM IV"/"best_ball_mania_iv_2023_r2_results_pick_by_pick.csv"],
     "rd3":[BASE/"BBM IV"/"best_ball_mania_iv_2023_r3_results_pick_by_pick.csv"],
     "rd4":[BASE/"BBM IV"/"best_ball_mania_iv_2023_r4_results_pick_by_pick.csv"]},
    {"name":"V","season":2024,"team_key":"tournament_round_draft_entry_id",
     "rd1":[BASE/"BBM V"/"best_ball_mania_v_rd1.csv"],
     "rd2":[BASE/"BBM V"/"best_ball_mania_v_rd2.csv"],
     "rd3":[BASE/"BBM V"/"best_ball_mania_v_rd3.csv"],
     "rd4":[BASE/"BBM V"/"best_ball_mania_v_rd4.csv"]},
    {"name":"VI","season":2025,"team_key":"tournament_round_draft_entry_id",
     "rd1":[BASE/"BBM VI"/"best_ball_mania_vi_rd1.csv"],
     "rd2":[BASE/"BBM VI"/"best_ball_mania_vi_rd2.csv"],
     "rd3":[BASE/"BBM VI"/"best_ball_mania_vi_rd3.csv"],
     "rd4":[BASE/"BBM VI"/"best_ball_mania_vi_rd4.csv"]},
]

ROSTER_DIR = ROOT / "scripts" / "_nflverse_rosters"
import re, unicodedata
_PUNCT = re.compile(r"[^\w\s]")
def norm_name(name):
    if not isinstance(name, str): return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii","ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\.?$", "", s)
    s = _PUNCT.sub("", s)
    return re.sub(r"\s+", " ", s).strip()

def load_name_team(season):
    df = pd.read_csv(ROSTER_DIR / f"roster_{season}.csv",
                     usecols=["season","team","position","full_name"])
    df = df[df["position"].isin(["QB","RB","WR","TE","FB","HB"])].copy()
    df["position"] = df["position"].replace({"FB":"RB","HB":"RB"})
    m = {}
    for _,r in df.iterrows():
        k = (norm_name(r["full_name"]), r["position"])
        if k not in m: m[k] = r["team"]
    return m

# nflverse schedule for bye weeks. Bye = team's NOT playing in a given week.
SCHED_FILE = ROOT / "scripts" / "_nflverse_schedules.csv"
def load_byes(season):
    s = pd.read_csv(SCHED_FILE, usecols=["season","week","game_type","home_team","away_team"])
    s = s[(s["season"]==season) & (s["game_type"]=="REG")]
    teams = set(s["home_team"]).union(set(s["away_team"]))
    bye = {t: None for t in teams}
    for t in teams:
        weeks_played = set(s.loc[(s["home_team"]==t)|(s["away_team"]==t), "week"])
        for wk in range(1, 19):
            if wk not in weeks_played:
                bye[t] = wk; break
    return bye

def read_advance_set(files):
    if not files: return set()
    frames=[]
    for f in files:
        if not Path(f).exists(): continue
        frames.append(pd.read_csv(f, usecols=["tournament_entry_id"]))
    if not frames: return set()
    return set(pd.concat(frames, ignore_index=True)["tournament_entry_id"].unique())

def read_rd1(spec):
    cols_base = ["tournament_entry_id","team_pick_number","position_name","player_name"]
    cols = cols_base + ([spec["team_key"]] if spec["team_key"]=="tournament_round_draft_entry_id" else [])
    frames=[]
    for f in spec["rd1"]:
        first = pd.read_csv(f, nrows=0).columns.tolist()
        use = [c for c in cols if c in first]
        frames.append(pd.read_csv(f, usecols=use))
    df = pd.concat(frames, ignore_index=True)
    if "tournament_round_draft_entry_id" not in df.columns:
        df["tournament_round_draft_entry_id"] = df[spec["team_key"]]
    return df

def per_team_struct(df, name_team, byes):
    tk = "tournament_round_draft_entry_id"
    df = df[df["position_name"].isin(["QB","RB","WR","TE"])].copy()
    keys = list(zip(df["player_name"].map(norm_name), df["position_name"]))
    df["nfl_team"] = [name_team.get(k) for k in keys]
    df["bye"] = df["nfl_team"].map(lambda t: byes.get(t) if t else None)

    # Bye max concentration per team
    bye_count = df[df["bye"].notna()].groupby([tk,"bye"]).size().reset_index(name="cnt")
    max_bye = bye_count.groupby(tk)["cnt"].max().rename("max_bye")
    # RB same-team max
    rb_team = df[(df["position_name"]=="RB") & df["nfl_team"].notna()].groupby([tk,"nfl_team"]).size().reset_index(name="cnt")
    max_rb_same = rb_team.groupby(tk)["cnt"].max().rename("max_rb_same")
    # WR no-QB cannib (vectorized via set of (tk, nfl_team) pairs from QBs).
    qb_pairs = set(zip(
        df.loc[(df["position_name"]=="QB") & df["nfl_team"].notna(), tk],
        df.loc[(df["position_name"]=="QB") & df["nfl_team"].notna(), "nfl_team"],
    ))
    wr_rows = df[(df["position_name"]=="WR") & df["nfl_team"].notna()][[tk,"nfl_team"]].copy()
    wr_rows["has_qb"] = list(map(lambda x: x in qb_pairs, zip(wr_rows[tk], wr_rows["nfl_team"])))
    wr_no_qb = wr_rows[~wr_rows["has_qb"]].groupby([tk,"nfl_team"]).size().reset_index(name="cnt")
    max_wr_no_qb = wr_no_qb.groupby(tk)["cnt"].max().rename("max_wr_no_qb")

    teams = df.drop_duplicates(tk)[[tk,"tournament_entry_id"]].copy()
    teams = teams.merge(max_bye, on=tk, how="left").merge(max_rb_same, on=tk, how="left").merge(max_wr_no_qb, on=tk, how="left")
    for c in ["max_bye","max_rb_same","max_wr_no_qb"]:
        teams[c] = teams[c].fillna(0).astype(int)
    return teams

def main():
    rosters = {y: load_name_team(y) for y in (2021,2022,2023,2024,2025)}
    byes_by_year = {y: load_byes(y) for y in (2021,2022,2023,2024,2025)}

    all_rows = []
    for spec in INPUTS:
        print(f"\n[struct] === BBM {spec['name']} ===", flush=True)
        df = read_rd1(spec)
        feats = per_team_struct(df, rosters[spec["season"]], byes_by_year[spec["season"]])
        adv_qf = read_advance_set(spec["rd2"])
        adv_sf = read_advance_set(spec["rd3"])
        adv_fin = read_advance_set(spec["rd4"])
        feats["adv_qf"]  = feats["tournament_entry_id"].isin(adv_qf).astype(int)
        feats["adv_sf"]  = feats["tournament_entry_id"].isin(adv_sf).astype(int)
        feats["adv_fin"] = feats["tournament_entry_id"].isin(adv_fin).astype(int)
        all_rows.append(feats)
        print(f"[struct]   teams {len(feats):,}", flush=True)

    teams = pd.concat(all_rows, ignore_index=True)
    n = len(teams)
    base_qf = teams["adv_qf"].mean()
    base_sf = teams["adv_sf"].mean()
    base_fin = teams["adv_fin"].mean()
    print(f"\n[struct] combined: {n:,}  qf {base_qf:.4%}  sf {base_sf:.4%}  fin {base_fin:.4%}", flush=True)

    out = {
        "n_total": int(n),
        "baselines": {"qf": round(float(base_qf),5), "sf": round(float(base_sf),5), "fin": round(float(base_fin),5)},
    }

    def cells_by_bucket(col, max_bucket):
        result = {}
        for k in range(0, max_bucket+1):
            if k == max_bucket:
                sub = teams[teams[col] >= k]
            else:
                sub = teams[teams[col] == k]
            if len(sub) < 200: continue
            result[k] = {
                "qf":  round(float(sub["adv_qf"].mean()),5),
                "sf":  round(float(sub["adv_sf"].mean()),5),
                "fin": round(float(sub["adv_fin"].mean()),5),
                "n":   int(len(sub)),
            }
        return result

    out["bye_concentration"]      = cells_by_bucket("max_bye", 12)
    out["rb_same_team"]           = cells_by_bucket("max_rb_same", 3)
    out["wr_no_qb_cannib"]        = cells_by_bucket("max_wr_no_qb", 4)

    print("\n=== Bye concentration ===", flush=True)
    print(f"{'k':>3} | {'n':>9} | {'qf':>7} | {'sf':>7} | {'fin':>7}", flush=True)
    for k,v in out["bye_concentration"].items():
        print(f"{k:>3} | {v['n']:>9,} | {v['qf']*100:>6.2f}% | {v['sf']*100:>6.3f}% | {v['fin']*100:>6.4f}%", flush=True)
    print("\n=== RB same-team ===", flush=True)
    for k,v in out["rb_same_team"].items():
        print(f"{k:>3} | {v['n']:>9,} | {v['qf']*100:>6.2f}% | {v['sf']*100:>6.3f}% | {v['fin']*100:>6.4f}%", flush=True)
    print("\n=== WR same-team no-QB ===", flush=True)
    for k,v in out["wr_no_qb_cannib"].items():
        print(f"{k:>3} | {v['n']:>9,} | {v['qf']*100:>6.2f}% | {v['sf']*100:>6.3f}% | {v['fin']*100:>6.4f}%", flush=True)

    with OUT.open("w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[struct] wrote {OUT.relative_to(ROOT)}", flush=True)

if __name__ == "__main__":
    main()
