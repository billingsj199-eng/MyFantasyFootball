#!/usr/bin/env python3
"""
PRACTICE-DAY PLAY RATES for the site's weekly player card (Jack 2026-10-08: "add the practice report to the weekly
card ... each day along with the historical rate of playing").

Same population as backtest_injury_type_play.py minus the final regular-season week (resting starters) (nflverse injuries x snap counts 2019-25, QB/RB/WR/TE averaging 40%+
of offensive snaps over 2+ prior games that season), same recency weights (half-life 3 seasons) and the same
K=50 shrink of each position toward the class rate. History only carries each week's FINAL report, so the classes are
"his last practice of the week read X":

  any-X    last practice X, whatever the game designation (the card's rate for a day before the designation posts:
           "players whose last practice was limited went on to play N%")
  none-X   last practice X and NO designation on the final report (listed, not tagged)

Questionable / Doubtful / Out on the final report use the engine's own play table (SIM_PROJ_2026.injRes.play), so
the card's last number matches the projection's dock.

Writes data/practice_day_rates.json and prints the table for app.js (_PRAC_DAY_RATES).
"""
import json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_common as B
POS4 = ("QB", "RB", "WR", "TE"); YEARS = list(range(2019, 2026)); K_POS, HALF = 50, 3


def prac(s):
    s = str(s or "")
    return "DNP" if s.startswith("Did Not") else "LP" if s.startswith("Limited") else "FP" if s.startswith("Full") else ""


def load():
    rows = []
    for Y in YEARS:
        inj = pd.read_parquet(os.path.join(B.CACHE, f"injuries_{Y}.parquet"))
        inj = inj[(inj.game_type == "REG") & inj.position.isin(POS4)].drop_duplicates(["team", "week", "gsis_id"])
        inj = inj[inj.week < (17 if Y <= 2020 else 18)]   # final week dropped (starters rest; Jack 09-17 rule)
        sn = pd.read_parquet(os.path.join(B.CACHE, f"snap_counts_{Y}.parquet"), columns=["week", "game_type", "player", "position", "team", "offense_snaps", "offense_pct"])
        sn = sn[(sn.game_type == "REG") & sn.position.isin(POS4) & (sn.offense_snaps > 0)]
        hist = defaultdict(dict)
        for r in sn.itertuples(index=False): hist[B.cal.norm(str(r.player))][int(r.week)] = float(r.offense_pct)
        for r in inj.itertuples(index=False):
            p = prac(r.practice_status)
            if not p: continue
            k = B.cal.norm(str(r.full_name)); W = int(r.week)
            prev = [v for w, v in hist.get(k, {}).items() if w < W]
            if len(prev) < 2 or np.mean(prev) < .40: continue
            rs = str(r.report_status or "")
            des = "none" if rs in ("", "nan", "None") else rs
            rows.append(dict(year=Y, pos=r.position, p=p, des=des, played=int(W in hist.get(k, {}))))
    return pd.DataFrame(rows)


def rates(A):
    w = 0.5 ** ((A.year.max() - A.year.values) / HALF)
    A = A.assign(w=w, wp=w * A.played.values)
    out, n = {}, {}
    for cls, sub in (("any", A), ("none", A[A.des == "none"])):
        for p in ("FP", "LP", "DNP"):
            s = sub[sub.p == p]
            if not len(s): continue
            cr = s.wp.sum() / s.w.sum()
            key = cls + "-" + p
            out[key] = {"all": round(float(cr), 3)}
            n[key] = {"all": int(len(s))}
            for pos in POS4:
                q = s[s.pos == pos]
                out[key][pos] = round(float((q.wp.sum() + K_POS * cr) / (q.w.sum() + K_POS)), 3)
                n[key][pos] = int(len(q))
    return out, n


def main():
    A = load()
    out, n = rates(A)
    print(f"{len(A)} report rows (regular starters), 2019-25, half-life {HALF}, K={K_POS}")
    for k in out:
        print(f"  {k:9s} " + "  ".join(f"{p} {100*out[k][p]:4.1f}% (n {n[k][p]})" for p in ("all",) + POS4))
    # raw (unweighted) rates for the record
    for p in ("FP", "LP", "DNP"):
        s = A[A.p == p]
        print(f"  raw any-{p}: {100*s.played.mean():.1f}% of {len(s)}; by designation: " + ", ".join(f"{d} {100*g.played.mean():.0f}% (n {len(g)})" for d, g in s.groupby("des")))
    json.dump({"asOf": "2019-25", "half": HALF, "k": K_POS, "rates": out, "n": n}, open(os.path.join(HERE, "data", "practice_day_rates.json"), "w"), indent=1)
    print("JS:", json.dumps(out, separators=(",", ":")))


if __name__ == "__main__":
    main()
