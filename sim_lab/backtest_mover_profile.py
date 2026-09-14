#!/usr/bin/env python3
"""
Does AGE or CONTRACT SIZE moderate how team-changers perform vs their
history? (Follow-up to backtest_role_layer.py's mover discount: RB -7%,
WR -13%, TE -16% below the 3-yr core.)

Movers 2019-2025 joined to nflverse/OTC contracts (age from date_of_birth,
new-deal size = the contract signed in year Y as % of that year's cap —
apy_cap_pct, era-neutral). Hypothesis: big-money movers were bought for a
ROLE (small discount); cheap veteran movers are depth (big discount); age
should steepen it.

Residual = actual season-Y PPG / 3-yr recency core (>=6 games in Y).
"""
import numpy as np
import pandas as pd
import os
from collections import defaultdict
from backtest_sim_calibration import played, WEEKLY, infer_team, POS_KEEP
import backtest_sim_calibration as cal

CACHE = r"E:\MyFantasyFootball\pbp_cache"
W3 = [0.5, 0.3, 0.2]

def season_rows(rec, Y):
    return [w for w in rec.get("seasons", {}).get(str(Y), []) if played(w)]

def ppg_of(rows):
    pts = [w["fpts"] for w in rows if isinstance(w.get("fpts"), (int, float))]
    return (sum(pts) / len(pts), len(pts)) if pts else (None, 0)

def main():
    con = pd.read_parquet(os.path.join(CACHE, "historical_contracts.parquet"),
                          columns=["player", "position", "year_signed", "apy_cap_pct", "date_of_birth"])
    con["norm"] = con.player.map(cal.norm)
    birth = {}
    for _, r in con.dropna(subset=["date_of_birth"]).iterrows():
        m = pd.Series([str(r.date_of_birth)]).str.extract(r"(\d{4})")[0][0]
        if isinstance(m, str) and m.isdigit():
            birth[(r.norm, r.position)] = int(m)
    deals = defaultdict(list)   # (norm,pos,year_signed) -> [apy_cap_pct]
    for _, r in con.dropna(subset=["apy_cap_pct"]).iterrows():
        deals[(r.norm, r.position, int(r.year_signed))].append(float(r.apy_cap_pct))

    recs = []
    for lst in WEEKLY.values():
        for rec in lst:
            if rec.get("pos") in POS_KEEP:
                recs.append(rec)

    movers, stayers = [], []
    for Y in range(2019, 2026):
        for rec in recs:
            pos = rec["pos"]
            act, g = ppg_of(season_rows(rec, Y))
            if act is None or g < 6:
                continue
            num = den = 0.0
            for i, yr in enumerate([Y - 1, Y - 2, Y - 3]):
                p, gg = ppg_of(season_rows(rec, yr))
                if p is not None and gg >= 4:
                    num += W3[i] * p; den += W3[i]
            if den == 0:
                continue
            core = num / den
            if core < 3:
                continue
            tn, tp = infer_team(rec, Y), infer_team(rec, Y - 1)
            if not tn or not tp:
                continue
            nk = None
            for name_norm, lst in WEEKLY.items():
                pass  # rec's own norm key unknown; recover via name-less join below
            # recover norm key from the record's identity: store during load instead
            movers_entry = {"pos": pos, "resid": act / core, "Y": Y, "rec": rec}
            (movers if tn != tp else stayers).append(movers_entry)
        print(f"  {Y} done")

    # attach norm names (rec objects -> find their key once)
    rec2norm = {}
    for name_norm, lst in WEEKLY.items():
        for rec in lst:
            rec2norm[id(rec)] = name_norm
    for e in movers + stayers:
        e["norm"] = rec2norm[id(e["rec"])]
        e["age"] = None
        by = birth.get((e["norm"], e["pos"]))
        if by:
            e["age"] = e["Y"] - by
        ds = deals.get((e["norm"], e["pos"], e["Y"])) or deals.get((e["norm"], e["pos"], e["Y"] - 1))
        e["cap_pct"] = max(ds) if ds else None

    stay_base = {p: np.mean([e["resid"] for e in stayers if e["pos"] == p]) for p in POS_KEEP}
    print(f"\n{len(movers)} mover-seasons, {len(stayers)} stayer-seasons")
    print("stayer residual baseline by pos:", {k: round(v, 3) for k, v in stay_base.items()})

    def show(tag, buckets, keyfn):
        print(f"\n=== Mover residual by {tag} (actual / 3yr core; stayers ~1.0) ===")
        for lo, hi, label in buckets:
            sel = [e for e in movers if keyfn(e) is not None and lo <= keyfn(e) < hi]
            if len(sel) < 15:
                print(f"  {label}: n={len(sel)} (too few)")
                continue
            r = np.mean([e["resid"] for e in sel])
            comp = ", ".join(f"{p}{sum(1 for e in sel if e['pos']==p)}" for p in ("QB","RB","WR","TE"))
            print(f"  {label}: {r:.3f}  (n={len(sel)}: {comp})")

    show("AGE", [(0, 26, "under 26"), (26, 29, "26-28"), (29, 32, "29-31"), (32, 50, "32+")],
         lambda e: e["age"])
    show("NEW-CONTRACT SIZE (% of cap, year signed = move year)",
         [(0.04, 1.0, ">=4% of cap (bought a role)"), (0.015, 0.04, "1.5-4%"),
          (0.0, 0.015, "<1.5% (depth deal)")],
         lambda e: e["cap_pct"])
    # interaction: old + cheap vs young + paid
    print("\n=== Interaction ===")
    for label, cond in [
        ("young (<27) + paid (>=2%)", lambda e: e["age"] and e["age"] < 27 and e["cap_pct"] and e["cap_pct"] >= 0.02),
        ("young (<27) + cheap (<2%)", lambda e: e["age"] and e["age"] < 27 and e["cap_pct"] is not None and e["cap_pct"] < 0.02),
        ("old (29+) + paid (>=2%)", lambda e: e["age"] and e["age"] >= 29 and e["cap_pct"] and e["cap_pct"] >= 0.02),
        ("old (29+) + cheap (<2%)", lambda e: e["age"] and e["age"] >= 29 and e["cap_pct"] is not None and e["cap_pct"] < 0.02),
    ]:
        sel = [e for e in movers if cond(e)]
        if len(sel) >= 12:
            print(f"  {label}: {np.mean([e['resid'] for e in sel]):.3f} (n={len(sel)})")
        else:
            print(f"  {label}: n={len(sel)} (too few)")
    matched_age = sum(1 for e in movers if e["age"] is not None)
    matched_cap = sum(1 for e in movers if e["cap_pct"] is not None)
    print(f"\ncoverage: age matched {matched_age}/{len(movers)}, contract matched {matched_cap}/{len(movers)}")

if __name__ == "__main__":
    main()
