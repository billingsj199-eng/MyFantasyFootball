"""Emit data/bbm_structural_multistage.js from _bbm_structural_multistage.json.
Provides BBM_STRUCT_MULTI = { bye: {k: {qf,sf,fin,n}}, rb: {...}, wr: {...} }."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "_bbm_structural_multistage.json"
OUT = ROOT / "data" / "bbm_structural_multistage.js"

raw = json.loads(SRC.read_text())
b = raw["baselines"]

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

groups = {
    "bye": raw["bye_concentration"],
    "rb":  raw["rb_same_team"],
    "wr":  raw["wr_no_qb_cannib"],
}

js = f"""// Auto-generated from scripts/_bbm_structural_multistage.json
// Bye-concentration + RB cannib + WR-no-QB cannib at QF/SF/Finals.
// Source: 5 BBMs (II-VI), n={raw['n_total']:,} teams.
// Baselines: QF={b['qf']:.5f}  SF={b['sf']:.5f}  Fin={b['fin']:.5f}.
//
// BBM_STRUCT_MULTI[group][k] = {{qf, sf, fin, n}} where:
//   group = 'bye' (max same-bye-week count, k=0..12)
//   group = 'rb'  (max same-NFL-team RB count, k=0..3)
//   group = 'wr'  (max same-NFL-team WR-without-QB count, k=0..4)
const BBM_STRUCT_MULTI = {to_js(groups, 1)};
"""

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(js, encoding="utf-8")
print(f"wrote {OUT.relative_to(ROOT)}  ({len(js):,} bytes)")
