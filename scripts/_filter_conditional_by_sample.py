"""Re-print conditional construction tables with sample-size confidence flags.

Per cell we compute the implied count of advancers at each round
(rate * n). We then bucket cells by confidence:
  HIGH:   >= 100 advancers (very stable signal)
  MED:    30 - 99 advancers (cohort-level signal)
  LOW:    <30 advancers (single-year-noise risk)

For each table we print only cells in HIGH/MED for SF and Finals stages.
QF stage almost always has plenty of sample, no filtering needed.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "_bbm_conditional_construction.json"

raw = json.loads(SRC.read_text())
base = raw["baselines"]

def conf(n_advancers):
    if n_advancers >= 100: return "HI"
    if n_advancers >= 30:  return "med"
    return "LO"

def annot(cell, stage):
    """Return formatted lift + confidence flag for a cell."""
    n = cell["n"]
    if stage == "qf":
        rate, lift = cell["qf_rate"], cell["qf_lift"]
    elif stage == "sf":
        rate, lift = cell["sf_rate"], cell["sf_lift"]
    else:
        rate, lift = cell["fin_rate"], cell["fin_lift"]
    if rate is None or lift is None: return None
    advancers = int(round(rate * n))
    c = conf(advancers)
    return {"lift": lift, "n": n, "adv": advancers, "conf": c}

def print_table(key, title, target_order):
    rows = raw["tables"].get(key, [])
    if not rows: return
    conds = sorted(set(r["cond"] for r in rows))
    print(f"\n=== {title} ===")
    for stage_label, stage_key, base_label in (("QF", "qf", "qf"), ("SF", "sf", "sf"), ("Finals", "fin", "fin")):
        print(f"\n  -> {stage_label} (baseline {base[base_label]:.4%})")
        hdr = f"{'cohort':>26} | " + " | ".join(f"{t:>16}" for t in target_order)
        print(hdr)
        print("-" * len(hdr))
        for c in conds:
            line = f"{c:>26} | "
            for t in target_order:
                cell = next((r for r in rows if r["cond"]==c and r["target"]==t), None)
                if not cell:
                    line += " " * 18
                    continue
                a = annot(cell, stage_key)
                if a is None:
                    line += " " * 18; continue
                # Hide very small samples for SF/Finals
                if stage_key in ("sf","fin") and a["conf"] == "LO":
                    line += f"  ({a['adv']:>3}adv)        "[:18] + " | "
                else:
                    flag = {"HI":"", "med":"~", "LO":"?"}[a["conf"]]
                    line += f"{flag}{a['lift']:>4.2f} ({a['adv']:>4}adv)  "[:18] + " | "
            print(line.rstrip(" |"))

print_table("qb_round_x_final_qb",  "First QB round x final QB count",
            ["=1 QB","=2 QB","=3 QB","=4 QB"])
print_table("qb_round_x_final_rb",  "First QB round x final RB count",
            ["=3 RB","=4 RB","=5 RB","=6 RB","=7 RB"])
print_table("qb_round_x_final_wr",  "First QB round x final WR count",
            ["=4 WR","=5 WR","=6 WR","=7 WR","=8 WR"])
print_table("rb_r4_x_final_rb",     "RBs by r4 x final RB count",
            ["=3 RB","=4 RB","=5 RB","=6 RB","=7 RB"])
print_table("rb_r4_x_final_wr",     "RBs by r4 x final WR count",
            ["=4 WR","=5 WR","=6 WR","=7 WR","=8 WR"])
print_table("te_round_x_final_te",  "First TE round x final TE count",
            ["=1 TE","=2 TE","=3 TE","=4 TE"])
print_table("wr_r6_x_final_wr",     "WRs by r6 x final WR count",
            ["=4 WR","=5 WR","=6 WR","=7 WR","=8 WR"])
print_table("wr_r6_x_final_rb",     "WRs by r6 x final RB count",
            ["=3 RB","=4 RB","=5 RB","=6 RB","=7 RB"])

print("\nLegend:  blank flag = HI confidence (>=100 advancers)")
print("         ~ = medium (30-99)")
print("         (Nadv) shown alone = low confidence (<30) — value hidden")
