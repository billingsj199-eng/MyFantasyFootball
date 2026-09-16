#!/usr/bin/env python3
"""
OPPORTUNITY PRIOR, WEEKLY IN-SEASON TEST (2026-09-16).

backtest_opp_prior.py showed Clay + OPP beats calibrated Clay as a PRESEASON season-PPG prior (7.05 vs 7.15, 5/7).
That changes the live base, so before Jack decides: does it help the weekly projection we actually ship?

bt_common samples 2019-25 (QB excluded - no opportunity prior; RB/WR/TE player-weeks from week 2 on):
  shipped = P=5 blend(Clay per-game, season-to-date PPG) x Vegas x FPA
The Clay per-game number inside the blend is swapped for
  clay' = clay x clip(1 + k x (CLAY+OPP / CLAYCAL - 1), .7, 1.4)
where CLAY+OPP and CLAYCAL are the OUT-OF-SAMPLE season predictions (refit without the test season) from
opp_prior_preds.json - the ratio keeps Clay's scale and only moves the relative level. Graded on
  shipped' = shipped x base' / base
k grid 0 (shipped) .25 .5 .75 1 1.5, LOYO. Variants: all, vets only, rookies only, per position, early weeks
only (adjustment used through week 8, graded on all weeks), team-changers only.
Ship bar (README): <= -0.3% LOYO MSE with >= 5/7 years better. Log opp_weekly_backtest.log;
results -> data/opp_weekly_backtest.js (SIM_OPPWEEKLY_BT), ZONES tab.
"""
import json, os, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bt_common import iter_samples, to_arrays
from backtest_target_area import mse, P as _P0

LOG = open(os.path.join(HERE, "opp_weekly_backtest.log"), "w", encoding="utf-8")


class _Tee:
    def __init__(self, a, b): self.a, self.b = a, b
    def write(self, t): self.a.write(t); self.b.write(t); self.a.flush(); self.b.flush()
    def flush(self): self.a.flush(); self.b.flush()


sys.stdout = _Tee(sys.stdout, LOG)
def P(*a): print(" ".join(str(x) for x in a))

YEARS = list(range(2019, 2026))
PRIOR_P = _P0
SHIP_PCT, SHIP_WINS = -0.30, 5
GRID = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]
RES = {"loyo": [], "n": 0}


def loyo2(S, grid, predfn, label, family, pos):
    act = S["act"]; per = {}
    ys = [y for y in YEARS if (S["year"] == y).any()]
    for v in grid:
        pred = predfn(v)
        per[v] = {y: mse(pred[S["year"] == y], act[S["year"] == y]) for y in ys}
    ship = per[grid[0]]; tot = n = wins = 0; picks = []
    for y in ys:
        m = S["year"] == y
        best = min(grid, key=lambda v: sum(per[v][yy] for yy in ys if yy != y))
        picks.append(best); e = mse(predfn(best)[m], act[m])
        tot += e * m.sum(); n += m.sum(); wins += e < ship[y]
    pooled_best = min(grid, key=lambda v: sum(per[v].values()))
    base_mse = sum(ship[y] * (S["year"] == y).sum() for y in ys) / n
    pct = (tot / n / base_mse - 1) * 100
    P(f"  {label}")
    P("    grid pooled MSE: " + "  ".join(f"{v:+.2f}:{sum(per[v].values())/len(ys):.3f}" for v in grid))
    P(f"    pooled best {pooled_best:+.2f} | LOYO MSE {tot/n:.4f} vs shipped {base_mse:.4f} ({pct:+.2f}%), years better {wins}/{len(ys)}, picks {picks}")
    RES["loyo"].append({"label": label, "family": family, "pos": pos, "n": int(n), "best": float(pooled_best), "pct": round(pct, 3),
                        "wins": int(wins), "years": len(ys), "picks": [float(p) for p in picks],
                        "verdict": "PASS" if (pct <= SHIP_PCT and wins >= SHIP_WINS) else ("lean" if (pct <= -0.1 and wins >= 4) else "FAIL")})


def main():
    preds = json.load(open(os.path.join(HERE, "opp_prior_preds.json"), encoding="utf-8"))
    S = iter_samples(("RB", "WR", "TE"))
    A = to_arrays(S); n = len(S)
    ratio = np.ones(n); seg = np.array([""] * n, dtype=object); have = np.zeros(n, dtype=bool)
    for i, s in enumerate(S):
        pr = preds.get(f"{s['year']}|{s['pid']}") if s["pid"] else None
        if pr and pr.get("CLAY+OPP") and pr.get("CLAYCAL") and pr["CLAYCAL"] > 0.5:
            ratio[i] = pr["CLAY+OPP"] / pr["CLAYCAL"]; seg[i] = pr["seg"]; have[i] = True
    act, ship, base, clay, g, ppg, wk = A["act"], A["shipped"], A["base"], A["clay"], A["g"], A["ppg"], A["wk"]
    RES["n"] = int(n)
    P(f"  {n} RB/WR/TE player-weeks; opportunity prior matched {int(have.sum())} ({have.mean()*100:.1f}%): "
      f"stay {int((seg == 'stay').sum())}, mover {int((seg == 'mover').sum())}, rookie {int((seg == 'rookie').sum())}")
    P(f"  ratio CLAY+OPP / CLAYCAL on matched rows: p10 {np.percentile(ratio[have], 10):.3f} median {np.median(ratio[have]):.3f} p90 {np.percentile(ratio[have], 90):.3f}")

    def make(mask, early=False):
        def f(k):
            r = np.clip(1 + k * (ratio - 1), 0.7, 1.4)
            use = mask & ((wk <= 8) if early else True)
            c2 = np.where(use, clay * r, clay)
            b2 = (PRIOR_P * c2 + g * ppg) / (PRIOR_P + g)
            return ship * np.where(base > 0, b2 / base, 1.0)
        return f

    def run(m_rows, m_adj, label, family, pos, early=False):
        Ssub = {"year": A["year"][m_rows], "act": act[m_rows]}
        f = make(m_adj, early)
        loyo2(Ssub, GRID, lambda k: f(k)[m_rows], label + f" (rows {int(m_rows.sum())})", family, pos)

    allm = np.ones(n, dtype=bool); vets = have & (seg != "rookie"); rook = have & (seg == "rookie"); mov = have & (seg == "mover")
    P("\n=== Clay + OPP ratio on the weekly Clay prior, graded vs shipped ===")
    run(allm, have, "ALL RB/WR/TE, every matched player", "clay x (CLAY+OPP/CLAYCAL)^k", "ALL")
    run(allm, vets, "ALL RB/WR/TE, veterans only adjusted", "vets only", "ALL vets")
    run(have, have, "matched rows only", "matched rows", "ALL matched")
    run(rook, rook, "rookies only", "rookies", "rookies")
    run(mov, mov, "team-changers only", "movers", "movers")
    run(allm, have, "ALL, adjustment only through week 8", "early weeks", "ALL wk<=8", early=True)
    for p in ("RB", "WR", "TE"):
        pm = A["pos"] == p
        run(pm, have, f"{p} every matched player", "per position", p)
        run(pm, vets, f"{p} veterans only adjusted", "per position vets", f"{p} vets")
    P("\n=== by week band (pooled k=1 vs shipped, all matched rows) ===")
    f1 = make(have)(1.0)
    RES["bands"] = []
    for lo, hi, lab in ((2, 4, "wk2-4"), (5, 8, "wk5-8"), (9, 13, "wk9-13"), (14, 18, "wk14-18")):
        m = have & (wk >= lo) & (wk <= hi)
        a, b = mse(ship[m], act[m]), mse(f1[m], act[m])
        RES["bands"].append({"band": lab, "n": int(m.sum()), "ship": round(a, 3), "opp": round(b, 3), "pct": round((b / a - 1) * 100, 2)})
        P(f"  {lab}: n {int(m.sum())} shipped {a:.3f} k=1 {b:.3f} ({(b/a-1)*100:+.2f}%)")
    RES["updated"] = time.strftime("%Y-%m-%d %H:%M"); RES["years"] = YEARS; RES["bar"] = {"pct": SHIP_PCT, "wins": SHIP_WINS}
    passed = [r for r in RES["loyo"] if r["verdict"] == "PASS"]
    RES["summary"] = (f"Opportunity prior weekly: {len(RES['loyo'])} LOYO tests on {n} RB/WR/TE player-weeks; " +
                      (f"{len(passed)} pass: " + "; ".join(f"{r['pos']} {r['pct']:+.2f}% ({r['wins']}/{r['years']})" for r in passed) if passed else "none pass the ship bar"))
    with open(os.path.join(HERE, "data", "opp_weekly_backtest.js"), "w", encoding="utf-8") as fh:
        fh.write("// built by backtest_opp_weekly.py - Clay + opportunity prior on the weekly in-season projection; shown on the ZONES tab\n")
        fh.write("window.SIM_OPPWEEKLY_BT = "); json.dump(RES, fh, separators=(",", ":")); fh.write(";\n")
    P(f"\nwrote data/opp_weekly_backtest.js: {RES['summary']}")
    P("done")


if __name__ == "__main__":
    main()
