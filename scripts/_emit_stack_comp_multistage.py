"""Emit data/bbm_stack_comp_multistage.js — stack composition rates with
QF/SF/Finals per cell. Sources rank_pairs and per_rank from
_bbm_stack_x_round.json (which includes all 3 stages, n=2.6M teams)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "_bbm_stack_x_round.json"
OUT = ROOT / "data" / "bbm_stack_comp_multistage.js"

raw = json.loads(SRC.read_text())
base_qf  = raw["baselines"]["qf"]
base_sf  = raw["baselines"]["sf"]
base_fin = raw["baselines"]["fin"]

# Find a row in a section by label (looking up rank_pairs or per_rank)
def find_row(section, label_key, label):
    for r in raw[section]:
        if r[label_key] == label:
            return r
    return None

# Map compKey buckets to data rows. The first 4 + naked map to rank_pairs;
# the remaining 3 (wr2_no_wr1, te1_only, rb1_only) approximate to per_rank
# QB+pos cohorts since rank_pairs doesn't have them as standalones.
cells = {}

def cell_from_row(r):
    return {"qf": r["qf_rate"], "sf": r["sf_rate"], "fin": r["fin_rate"], "n": r["n"]}

map_rank_pairs = {
    "wr1_only":     "WR1 only (no WR2/3/4/TE1/RB1)",
    "wr1_and_wr2":  "WR1+WR2",
    "wr1_and_rb1":  "WR1+RB1",
    "wr1_and_te1":  "WR1+TE1",
    "no_stack":     "Naked QB",
}
for ckey, label in map_rank_pairs.items():
    r = find_row("rank_pairs", "pattern", label)
    if r:
        cells[ckey] = cell_from_row(r)

# Approximate cohorts: te1_only / rb1_only / wr2_no_wr1 from per_rank flags.
map_per_rank = {
    "te1_only":   "QB+TE1",
    "rb1_only":   "QB+RB1",
    "wr2_no_wr1": "QB+WR2",
}
for ckey, label in map_per_rank.items():
    r = find_row("per_rank", "flag", label)
    if r:
        cells[ckey] = cell_from_row(r)

# Stack-size buckets (used as fallback when compKey is unknown).
size_cells = {}
for r in raw["stack_size"]:
    try:
        sz = int(r["size"].rstrip("+"))
    except ValueError:
        continue
    size_cells[sz] = cell_from_row(r)

def to_js(obj, indent=2):
    pad = "  " * indent
    if isinstance(obj, dict):
        lines = []
        for k, v in obj.items():
            key = f'"{k}"' if isinstance(k, str) else str(k)
            lines.append(f"{pad}  {key}: {to_js(v, indent+1)}")
        return "{\n" + ",\n".join(lines) + "\n" + pad + "}"
    if obj is None: return "null"
    if isinstance(obj, float): return f"{obj:.5f}"
    if isinstance(obj, int): return str(obj)
    return str(obj)

js = f"""// Auto-generated from scripts/_bbm_stack_x_round.json
// Stack composition rates with QF/SF/Finals per cell.
// Source: 5 BBMs (II-VI), n={raw['n_total']:,} teams.
// Baselines: QF={base_qf:.5f}  SF={base_sf:.5f}  Fin={base_fin:.5f}.

// compKey -> {{qf, sf, fin, n}} for primary stacking patterns.
// Cohort definitions are same-team-as-QB1 patterns in draft order:
//   wr1_only      = QB1's same-team WR1 stacked, no other mate
//   wr1_and_wr2   = QB1's WR1 + WR2 same team (over-concentration)
//   wr1_and_rb1   = QB1's WR1 + RB1 same team (diversified)
//   wr1_and_te1   = QB1's WR1 + TE1 same team
//   wr2_no_wr1    = QB1's WR2 stacked but not WR1 (skipped primary)
//   te1_only      = TE1 stacked, no other mate
//   rb1_only      = RB1 stacked, no other mate
//   no_stack      = naked QB (no same-team mate)
const BBM_STACK_COMP_MULTI = {to_js(cells, 1)};

// Stack-size fallback (count of QB1 same-team mates) -> {{qf, sf, fin, n}}.
// Used when compKey is unavailable (e.g. team has no QB drafted yet).
const BBM_MAX_STACK_MULTI = {to_js(size_cells, 1)};
"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(js, encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)}  ({len(js):,} bytes)")
