#!/usr/bin/env python3
"""
WR side of the shadow-corner effect: is anyone IMMUNE? 2019-2025.

1. SLOT SHIELD — shadow corners play outside; slot receivers should be
   shielded. Bucket by same-season PFF slot_rate, dock size per bucket =
   (act/base vs elite-CB-active) / (act/base vs control defenses), so each
   bucket is normalized against its own baseline.
2. aDOT + PROJECTION TIER moderators, same normalized design.
3. PER-WR table — most/least affected across 2019-25 (n>=12 active weeks),
   normalized by each player's own control ratio. Caveat printed with it:
   CB-season suppression itself persists at r=.10, so treat names as
   descriptive, not predictive.
"""
import numpy as np
import pandas as pd
import os
from collections import defaultdict
from backtest_cb_shadow import build_wr_samples, load_cb_status, YEARS
import backtest_sim_calibration as cal

PFF = r"E:\MyFantasyFootball\pbp_cache\pff"

def load_slot():
    """(Y, norm) -> {slot, adot} from PFF receiving (same season, WRs)."""
    out = {}
    for y in YEARS:
        p = os.path.join(PFF, f"pff_receiving_{y}.csv")
        if not os.path.exists(p):
            continue
        df = pd.read_csv(p)
        df = df[(df.position == "WR") & (df.routes >= 100)]
        for r in df.itertuples(index=False):
            out[(y, cal.norm(r.player))] = {"slot": r.slot_rate, "adot": r.avg_depth_of_target}
    return out

def ratio(sub):
    b = sum(s["base"] for s in sub)
    return (sum(s["act"] for s in sub) / b if b else None), len(sub)

def main():
    active, out, employs, _ = load_cb_status()
    S = build_wr_samples()
    slot = load_slot()
    for s in S:
        k = (s["Y"], s["opp"], s["wk"])
        s["b"] = "ACTIVE" if active.get(k) else ("OUT" if out.get(k) else
                 ("E?" if employs.get((s["Y"], s["opp"])) else "CONTROL"))
        s["pf"] = slot.get((s["Y"], cal.norm(s["name"])))
    A = [s for s in S if s["b"] == "ACTIVE"]
    C = [s for s in S if s["b"] == "CONTROL"]

    print("=== 1. SLOT SHIELD (same-season PFF slot_rate) ===")
    print("  bucket           active-ratio      control-ratio     normalized dock")
    for lab, lo, hi in [("outside  <30%", -1, 30), ("mixed  30-60%", 30, 60),
                        ("slot     >60%", 60, 200)]:
        a = [s for s in A if s["pf"] and lo <= s["pf"]["slot"] < hi]
        c = [s for s in C if s["pf"] and lo <= s["pf"]["slot"] < hi]
        ra, na = ratio(a); rc, nc = ratio(c)
        print(f"  {lab}   {ra:.3f} (n={na:4d})   {rc:.3f} (n={nc:5d})   x{ra/rc:.3f}")

    print("\n=== 2. aDOT + projection-tier moderators (normalized) ===")
    for lab, key, cuts in [("aDOT", lambda s: s["pf"]["adot"] if s["pf"] else None,
                            [("short <10", -99, 10), ("mid 10-13", 10, 13), ("deep >13", 13, 99)]),
                           ("proj tier", lambda s: s["base"],
                            [("stud >=12", 12, 99), ("mid 8-12", 8, 12), ("depth <8", -99, 8)])]:
        for blab, lo, hi in cuts:
            a = [s for s in A if key(s) is not None and lo <= key(s) < hi]
            c = [s for s in C if key(s) is not None and lo <= key(s) < hi]
            if not a or not c:
                continue
            ra, na = ratio(a); rc, nc = ratio(c)
            print(f"  {lab:9s} {blab:11s}  active {ra:.3f} (n={na:4d})  control {rc:.3f}  x{ra/rc:.3f}")

    print("\n=== 3. PER-WR (career 2019-25, >=12 elite-CB-active weeks) ===")
    print("  rel = own active-ratio / own control-ratio  (1.00 = unaffected)")
    byWr = defaultdict(lambda: {"a": [], "c": []})
    for s in A:
        byWr[s["name"]]["a"].append(s)
    for s in C:
        byWr[s["name"]]["c"].append(s)
    rows = []
    for nm, d in byWr.items():
        if len(d["a"]) < 12 or len(d["c"]) < 30:
            continue
        ra, na = ratio(d["a"]); rc, _ = ratio(d["c"])
        rows.append((ra / rc, ra, rc, na, nm))
    rows.sort()
    print("  MOST affected:")
    for rel, ra, rc, na, nm in rows[:10]:
        print(f"    {nm:22s} rel x{rel:.3f}  (active {ra:.3f} n={na}, control {rc:.3f})")
    print("  LEAST affected (the 'immune' names):")
    for rel, ra, rc, na, nm in rows[-10:][::-1]:
        print(f"    {nm:22s} rel x{rel:.3f}  (active {ra:.3f} n={na}, control {rc:.3f})")
    rels = np.array([r[0] for r in rows])
    print(f"  spread: {len(rows)} WRs, mean {rels.mean():.3f}, sd {rels.std():.3f} — "
          f"n~15-25/WR means sd~0.15+ is pure sampling noise at zero true spread")

if __name__ == "__main__":
    main()
