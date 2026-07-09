"""Emit data/bbm_path_optimal.js — path-conditional QF rates.

For each path-bucket × final-count cell, take the QF rate (huge sample,
no need to filter) and emit it as a JS lookup table. The construction
score uses these to adjust target counts based on what the user has
already drafted (e.g. Robust RB path -> stop at 4 RBs, Balanced ->
target 5, Zero RB -> nothing recovers).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "_bbm_conditional_construction.json"
OUT = ROOT / "data" / "bbm_path_optimal.js"

raw = json.loads(SRC.read_text())
base_qf  = raw["baselines"]["qf"]
base_sf  = raw["baselines"]["sf"]
base_fin = raw["baselines"]["fin"]
tables = raw["tables"]

def cells_to_dict(cells, target_label_to_count):
    """Convert list of {cond, target, qf_rate, sf_rate, fin_rate, n} into
       nested dict {cond: {count: {qf, sf, fin, n}}}."""
    out = {}
    for c in cells:
        cond = c["cond"]
        tgt = c["target"]
        try:
            count = target_label_to_count(tgt)
        except Exception:
            continue
        out.setdefault(cond, {})[count] = {
            "qf":  c["qf_rate"],
            "sf":  c.get("sf_rate"),
            "fin": c.get("fin_rate"),
            "n":   c["n"],
        }
    return out

def parse_pos_count(label):
    # "=5 RB", "=2 QB", etc.
    return int(label.split()[0].lstrip("="))

# RB-path: rb_count_by_r4 -> {final_rb: qf_rate}
rb_path = cells_to_dict(tables["rb_r4_x_final_rb"], parse_pos_count)
# Re-key by integer rb_r4 count
rb_path_int = {}
for cond, sub in rb_path.items():
    # cond like "0 RB by r4 (Zero RB)"
    n = int(cond.split()[0])
    rb_path_int[n] = sub

# QB-timing: qb1_round bucket -> {final_qb: rate}
qb_timing_full = cells_to_dict(tables["qb_round_x_final_qb"], parse_pos_count)
# Map cond strings to short keys
qb_key_map = {
    "QB1 r1-3 (early)": "early",
    "QB1 r4-6": "mid",
    "QB1 r7-9": "late",
    "QB1 r10-12": "late2",
    "QB1 r13+ (late)": "verylate",
}
qb_timing = {qb_key_map.get(k, k): v for k, v in qb_timing_full.items()}

# TE-timing
te_timing_full = cells_to_dict(tables["te_round_x_final_te"], parse_pos_count)
te_key_map = {
    "TE1 r1-4 (early TE)": "early",
    "TE1 r5-8": "mid",
    "TE1 r9-12": "late",
    "TE1 r13+ (late TE)": "verylate",
}
te_timing = {te_key_map.get(k, k): v for k, v in te_timing_full.items()}

# WR-pacing: wr_count_by_r6 bucket -> {final_wr: rate}
wr_pacing_full = cells_to_dict(tables["wr_r6_x_final_wr"], parse_pos_count)
wr_key_map = {
    "0-1 WR by r6": "slow",
    "2 WRs by r6":  "slow",   # bucket 2 with slow
    "3 WRs by r6":  "med",
    "4 WRs by r6":  "med",
    "5 WRs by r6":  "heavy",
    "6 WRs by r6":  "heavy",
}
# Aggregate by mapped key — when two source buckets merge into one
# (e.g. 0-1 WR + 2 WR -> "slow"), keep the cell with the higher QF rate
# (the more representative cohort for that count).
wr_pacing = {}
for cond, sub in wr_pacing_full.items():
    k = wr_key_map.get(cond, cond)
    if k not in wr_pacing:
        wr_pacing[k] = {}
    for cnt, cell in sub.items():
        existing = wr_pacing[k].get(cnt)
        if not existing or (cell["qf"] or 0) > (existing.get("qf") or 0):
            wr_pacing[k][cnt] = cell

def to_js_dict(d, indent=2):
    pad = "  " * indent
    parts = []
    for k, v in d.items():
        key = f'"{k}"' if isinstance(k, str) else str(k)
        if isinstance(v, dict):
            parts.append(f"{pad}{key}: {to_js_dict(v, indent+1)}")
        elif v is None:
            parts.append(f"{pad}{key}: null")
        elif isinstance(v, float):
            parts.append(f"{pad}{key}: {v:.5f}")
        else:
            parts.append(f"{pad}{key}: {v}")
    return "{\n" + ",\n".join(parts) + "\n" + ("  " * (indent-1)) + "}"

js = f"""// Auto-generated from scripts/_bbm_conditional_construction.json
// Path-conditional advance rates from 2.6M BBM teams (II-VI).
// Used by _udPathFitScore: detects user's build path then scores
// their final counts against the conditional optimal.
// Each cell now contains {{qf, sf, fin, n}} (was qf-only).
// Baselines: QF={base_qf:.5f}  SF={base_sf:.5f}  Fin={base_fin:.5f}.

// rb_count_by_r4 -> {{ final_rb_count: {{qf, sf, fin, n}} }}
const BBM_RB_PATH_LIFT = {to_js_dict(rb_path_int, 1)};

// qb1_round bucket -> {{ final_qb_count: {{qf, sf, fin, n}} }}
//   early=r1-3, mid=r4-6, late=r7-9, late2=r10-12, verylate=r13+
const BBM_QB_TIMING_LIFT = {to_js_dict(qb_timing, 1)};

// te1_round bucket -> {{ final_te_count: {{qf, sf, fin, n}} }}
//   early=r1-4, mid=r5-8, late=r9-12, verylate=r13+
const BBM_TE_TIMING_LIFT = {to_js_dict(te_timing, 1)};

// wr_count_by_r6 bucket -> {{ final_wr_count: {{qf, sf, fin, n}} }}
//   slow=0-2, med=3-4, heavy=5+
const BBM_WR_PACING_LIFT = {to_js_dict(wr_pacing, 1)};
"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(js, encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)}  ({len(js):,} bytes)")
