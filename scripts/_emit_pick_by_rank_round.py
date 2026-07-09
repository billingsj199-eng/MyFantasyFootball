"""Convert _bbm_pos_rank_round.json -> data/bbm_pick_by_rank_round.js for site use."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "_bbm_pos_rank_round.json"
OUT = ROOT / "data" / "bbm_pick_by_rank_round.js"

raw = json.loads(SRC.read_text())
base_qf  = raw["baselines"]["qf"]
base_sf  = raw["baselines"]["sf"]
base_fin = raw["baselines"]["fin"]
by = raw["by_position_rank"]
skip = raw["didnt_take"]

# Build rates table: pos -> rank -> round -> {qf, sf, fin, n} per cell
rates = {"qb": {}, "rb": {}, "wr": {}, "te": {}}
for col, info in by.items():
    pos = info["pos"].lower()
    rank = info["rank"]
    rates[pos][rank] = {}
    for rnd_str, cell in info["rounds"].items():
        rates[pos][rank][int(rnd_str)] = {
            "qf":  cell["qf_rate"],
            "sf":  cell["sf_rate"],
            "fin": cell["fin_rate"],
            "n":   cell["n"],
        }

# Skip rates: rates when that pick is missing — keep all 3 levels
skip_rates = {}
for k, info in skip.items():
    parts = k.replace("no_", "").split("_r")
    pos, rank = parts[0], int(parts[1])
    skip_rates[f"{pos}_{rank}"] = {
        "qf":  info["qf_rate"],
        "sf_lift":  info.get("sf_lift"),
        "fin_lift": info.get("fin_lift"),
    }

# Emit pretty JS
def to_js(obj, indent=0):
    pad = "  " * indent
    if isinstance(obj, dict):
        lines = []
        for k, v in obj.items():
            key = f'"{k}"' if isinstance(k, str) else str(k)
            lines.append(f"{pad}  {key}: {to_js(v, indent+1)}")
        return "{\n" + ",\n".join(lines) + "\n" + pad + "}"
    if isinstance(obj, float):
        return f"{obj:.5f}"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, str):
        return f'"{obj}"'
    if obj is None:
        return "null"
    return str(obj)

js = f"""// Auto-generated from scripts/_bbm_pos_rank_round.json
// Source: 5 BBMs (II-VI = 2021-2025), n=2,629,295 teams
// Baselines: QF={base_qf:.5f}  SF={base_sf:.5f}  Fin={base_fin:.5f}
// Cell value = {{qf, sf, fin, n}} for that (pos, rank, round).
// Use lift = rate / baseline for relative effect.

const BBM_BASELINE_QF_RATE  = {base_qf:.5f};
const BBM_BASELINE_SF_RATE  = {base_sf:.5f};
const BBM_BASELINE_FIN_RATE = {base_fin:.5f};

// Per-pick rates by (position, positional rank, round drafted).
// Each cell has {{qf, sf, fin, n}}. Rounds with insufficient sample (<200
// teams) are absent — fall back to baseline. Note that finals rates per
// cell are noisy (cells need >=60K teams for >=50 finals advancers).
const BBM_PICK_BY_RANK_ROUND = {to_js(rates)};

// Rates when a given (position, rank) pick is NOT taken at all on the team.
// {{ qf, sf_lift, fin_lift }} per slot. Used as skip penalty.
// QF below baseline penalizes skipping; AT-OR-ABOVE means skip is fine or better.
const BBM_PICK_SKIP_RATES = {to_js(skip_rates)};
"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(js, encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)}  ({len(js):,} bytes)")
