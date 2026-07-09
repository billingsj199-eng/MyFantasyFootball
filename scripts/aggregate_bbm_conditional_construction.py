"""Conditional roster construction: does the optimal shape shift based
on early-draft commits?

For each BBM team, computes:
  - qb1_round, te1_round, rb1_round, wr1_round (when each position started)
  - rb_count_r4 / rb_count_r6 (how many RBs by end of rd 4 / 6)
  - wr_count_r6 (how many WRs by end of rd 6)
  - final_qb / final_rb / final_wr / final_te counts (entire roster)

Then cross-tabs each conditioning variable against the FINAL count of
each position, with QF advance rate per cell. Surfaces the optimal
final shape per starting commit.

Outputs scripts/_bbm_conditional_construction.json + console tables.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "Best Ball Mania Files"
DBOWL = BASE / "best-ball-data-bowl-master" / "best-ball-data-bowl-master" / "data"
OUT = ROOT / "scripts" / "_bbm_conditional_construction.json"


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


def read_rd1(spec):
    cols_base = ["tournament_entry_id","team_pick_number","position_name"]
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


def read_advance_set(files):
    if not files: return set()
    frames = []
    for f in files:
        if not Path(f).exists(): continue
        frames.append(pd.read_csv(f, usecols=["tournament_entry_id"]))
    if not frames: return set()
    return set(pd.concat(frames, ignore_index=True)["tournament_entry_id"].unique())


def per_team_features(df: pd.DataFrame) -> pd.DataFrame:
    tk = "tournament_round_draft_entry_id"
    df = df[df["position_name"].isin(["QB","RB","WR","TE"])].copy()
    df = df.sort_values([tk, "team_pick_number"], kind="stable").reset_index(drop=True)

    # First-of-position rounds
    first = df.drop_duplicates([tk, "position_name"], keep="first")
    pivot = first.pivot(index=tk, columns="position_name", values="team_pick_number")
    pivot.columns = [f"{c.lower()}1_round" for c in pivot.columns]
    pivot = pivot.reset_index()

    # Final position counts
    counts = df.groupby([tk, "position_name"]).size().unstack(fill_value=0)
    counts.columns = [f"final_{c.lower()}" for c in counts.columns]
    counts = counts.reset_index()

    # Counts by end of round X (per team, per position)
    by_round_lim = {}
    for lim in (4, 6, 8):
        sub = df[df["team_pick_number"] <= lim]
        c = sub.groupby([tk, "position_name"]).size().unstack(fill_value=0)
        c.columns = [f"{p.lower()}_r{lim}" for p in c.columns]
        by_round_lim[lim] = c.reset_index()

    out = pivot.merge(counts, on=tk)
    for lim, frame in by_round_lim.items():
        out = out.merge(frame, on=tk, how="left")
    return out


def main():
    all_rows = []
    for spec in INPUTS:
        print(f"\n[cc] === BBM {spec['name']} ===", flush=True)
        df = read_rd1(spec)
        print(f"[cc]   rd1 rows {len(df):,}", flush=True)
        feats = per_team_features(df)

        tk = "tournament_round_draft_entry_id"
        eid = df.drop_duplicates(tk)[[tk,"tournament_entry_id"]]
        feats = feats.merge(eid, on=tk, how="left")

        adv_qf  = read_advance_set(spec["rd2"])
        adv_sf  = read_advance_set(spec["rd3"])
        adv_fin = read_advance_set(spec["rd4"])
        feats["adv_qf"]  = feats["tournament_entry_id"].isin(adv_qf).astype(int)
        feats["adv_sf"]  = feats["tournament_entry_id"].isin(adv_sf).astype(int)
        feats["adv_fin"] = feats["tournament_entry_id"].isin(adv_fin).astype(int)
        feats["bbm"] = spec["name"]
        all_rows.append(feats)
        print(f"[cc]   teams {len(feats):,}  qf {feats['adv_qf'].sum():,}  sf {feats['adv_sf'].sum():,}  fin {feats['adv_fin'].sum():,}", flush=True)

    teams = pd.concat(all_rows, ignore_index=True)
    n = len(teams)
    base_qf  = teams["adv_qf"].mean()
    base_sf  = teams["adv_sf"].mean()
    base_fin = teams["adv_fin"].mean()
    # Fill missing position-count columns (e.g. team drafted 0 of a position)
    for col in ["final_qb","final_rb","final_wr","final_te",
                "qb_r4","rb_r4","wr_r4","te_r4",
                "qb_r6","rb_r6","wr_r6","te_r6",
                "qb_r8","rb_r8","wr_r8","te_r8"]:
        if col not in teams.columns: teams[col] = 0
        teams[col] = teams[col].fillna(0).astype(int)
    print(f"\n[cc] combined: {n:,} teams  qf {base_qf:.4%}  sf {base_sf:.4%}  fin {base_fin:.4%}", flush=True)

    out = {"n_total": int(n),
           "baselines": {"qf": round(float(base_qf),5), "sf": round(float(base_sf),5), "fin": round(float(base_fin),5)},
           "tables": {}}

    def cross_tab(title, cond_label, cond_buckets, target_col, target_buckets, key):
        """cond_buckets = [(label, mask_fn), ...]
           target_buckets = [(label, mask_fn), ...]"""
        rows = []
        for c_lbl, c_mask in cond_buckets:
            cond = teams[c_mask]
            if len(cond) < 200: continue
            for t_lbl, t_mask in target_buckets:
                sub = cond[t_mask(cond)]
                if len(sub) < 100: continue
                qf  = sub["adv_qf"].mean()
                sf  = sub["adv_sf"].mean()
                fin = sub["adv_fin"].mean()
                rows.append({
                    "cond": c_lbl, "target": t_lbl, "n": int(len(sub)),
                    "qf_rate": round(float(qf),5),
                    "qf_lift": round(float(qf/base_qf),3) if base_qf else None,
                    "sf_rate": round(float(sf),5),
                    "sf_lift": round(float(sf/base_sf),3) if base_sf else None,
                    "fin_rate": round(float(fin),5),
                    "fin_lift": round(float(fin/base_fin),3) if base_fin else None,
                })
        out["tables"][key] = rows
        if not rows: return
        # Print three sub-tables: QF lift, SF lift, Fin lift
        conds = sorted(set(r["cond"] for r in rows))
        tgts  = [t[0] for t in target_buckets]
        for stage, key_lift in (("QF", "qf_lift"), ("SF", "sf_lift"), ("Finals", "fin_lift")):
            print(f"\n=== {title}  ->  {stage} ===", flush=True)
            hdr = f"{cond_label:>22} | " + " | ".join(f"{t:>9}" for t in tgts)
            print(hdr, flush=True)
            print("-" * len(hdr), flush=True)
            for c in conds:
                row = f"{c:>22} | "
                for t in tgts:
                    m = next((r for r in rows if r["cond"]==c and r["target"]==t), None)
                    if m and m[key_lift] is not None:
                        row += f"{m[key_lift]:>9.2f} | "
                    else:
                        row += " " * 12
                print(row.rstrip(" |"), flush=True)

    # ---- 1. First QB round bucket × final QB count ----
    qb_round_buckets = [
        ("QB1 r1-3 (early)",  (teams["qb1_round"] >= 1) & (teams["qb1_round"] <= 3)),
        ("QB1 r4-6",          (teams["qb1_round"] >= 4) & (teams["qb1_round"] <= 6)),
        ("QB1 r7-9",          (teams["qb1_round"] >= 7) & (teams["qb1_round"] <= 9)),
        ("QB1 r10-12",        (teams["qb1_round"] >= 10) & (teams["qb1_round"] <= 12)),
        ("QB1 r13+ (late)",   teams["qb1_round"] >= 13),
    ]
    final_qb_buckets = [(f"={k} QB", lambda d, k=k: d["final_qb"] == k) for k in (1,2,3,4)]
    cross_tab("First QB round × final QB count (lift vs overall baseline)",
              "first QB round", qb_round_buckets, "final_qb", final_qb_buckets, "qb_round_x_final_qb")

    # Same conditioning, but cross with final RB / WR / TE (does early QB shift other allocations?)
    rb_buckets_full = [(f"={k} RB", lambda d, k=k: d["final_rb"] == k) for k in (3,4,5,6,7)]
    cross_tab("First QB round × final RB count",
              "first QB round", qb_round_buckets, "final_rb", rb_buckets_full, "qb_round_x_final_rb")

    wr_buckets_full = [(f"={k} WR", lambda d, k=k: d["final_wr"] == k) for k in (4,5,6,7,8)]
    cross_tab("First QB round × final WR count",
              "first QB round", qb_round_buckets, "final_wr", wr_buckets_full, "qb_round_x_final_wr")

    # ---- 2. RB count after round 4 × final RB count (Hero/Robust/Zero RB analysis) ----
    rb_r4_buckets = [
        ("0 RB by r4 (Zero RB)",  teams["rb_r4"] == 0),
        ("1 RB by r4 (Hero RB)",  teams["rb_r4"] == 1),
        ("2 RBs by r4 (Balanced)", teams["rb_r4"] == 2),
        ("3 RBs by r4 (Heavy)",   teams["rb_r4"] == 3),
        ("4 RBs by r4 (Robust)",  teams["rb_r4"] == 4),
    ]
    cross_tab("RBs by end of r4 × final RB count",
              "by r4", rb_r4_buckets, "final_rb", rb_buckets_full, "rb_r4_x_final_rb")

    # Conditioning RB-r4 with final WR (does Zero RB demand more WRs?)
    cross_tab("RBs by end of r4 × final WR count",
              "by r4", rb_r4_buckets, "final_wr", wr_buckets_full, "rb_r4_x_final_wr")

    # ---- 3. First TE round × final TE count ----
    te_round_buckets = [
        ("TE1 r1-4 (early TE)",  (teams["te1_round"] >= 1) & (teams["te1_round"] <= 4)),
        ("TE1 r5-8",             (teams["te1_round"] >= 5) & (teams["te1_round"] <= 8)),
        ("TE1 r9-12",            (teams["te1_round"] >= 9) & (teams["te1_round"] <= 12)),
        ("TE1 r13+ (late TE)",   teams["te1_round"] >= 13),
    ]
    te_buckets_full = [(f"={k} TE", lambda d, k=k: d["final_te"] == k) for k in (1,2,3,4)]
    cross_tab("First TE round × final TE count",
              "first TE round", te_round_buckets, "final_te", te_buckets_full, "te_round_x_final_te")

    # ---- 4. WRs by end of r6 × final RB / WR ----
    wr_r6_buckets = [
        ("0-1 WR by r6", teams["wr_r6"] <= 1),
        ("2 WRs by r6",  teams["wr_r6"] == 2),
        ("3 WRs by r6",  teams["wr_r6"] == 3),
        ("4 WRs by r6",  teams["wr_r6"] == 4),
        ("5 WRs by r6",  teams["wr_r6"] == 5),
        ("6 WRs by r6",  teams["wr_r6"] == 6),
    ]
    cross_tab("WRs by end of r6 × final WR count",
              "WRs by r6", wr_r6_buckets, "final_wr", wr_buckets_full, "wr_r6_x_final_wr")
    cross_tab("WRs by end of r6 × final RB count",
              "WRs by r6", wr_r6_buckets, "final_rb", rb_buckets_full, "wr_r6_x_final_rb")

    with OUT.open("w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[cc] wrote {OUT.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
