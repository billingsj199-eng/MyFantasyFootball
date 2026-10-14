#!/usr/bin/env python3
"""
BOOK GUARDRAIL (Jack 2026-10-08: "realistically as a check for our weekly rankings our projections should never be very far off the
sportsbooks projections for the players that have them all filled out").

Data: the locked W1-4 snapshots (sim_lab/data/snapshots/simlab_snapshot_w{1-4}.json - the shipped mean, the books' lines per book)
and actual half-PPR points (weekly_stats_active via diagnose_week.load_rows). Prop lines only exist for 2026, so this is 4 weeks.
Market = consensus (median across DK/FD/MGM/UD/PP) lines at FACE VALUE in half-PPR: py/25 + 4 ptd - 2 int + ry/10 + rcy/10 + .5 rec
+ 6 x TD rate from the anytime-TD odds (devig 1.06, lambda = -ln(1 - p)). "Full" lines: QB py + ptd + ry; RB ry + rec + rcy + atd;
WR / TE rec + rcy + atd.
Guardrails on the SHIPPED mean: clamp to market x (1 +/- c) for c in .10/.15/.20/.30, or market +/- g points; by side (above only /
below only) and by position. Graded: MAE and within-position-week Spearman rank vs actual, per week (leave-one-week-out pick).
Log book_guardrail.log.
"""
import json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from score_week import norm
from diagnose_week import load_rows
LOG = open(os.path.join(HERE, "book_guardrail.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()
BOOKS = ("DK", "FD", "MGM", "UD", "PP")
NEED = {"QB": ("py", "ptd", "ry"), "RB": ("ry", "rec", "rcy", "atd"), "WR": ("rec", "rcy", "atd"), "TE": ("rec", "rcy", "atd")}


def cons(lines, k):
    v = [lines[b][k] for b in BOOKS if isinstance(lines.get(b), dict) and isinstance(lines[b].get(k), (int, float))]
    return float(np.median(v)) if v else None


def atd_p(lines):
    ps = []
    for b in BOOKS:
        o = lines.get(b, {}).get("atd") if isinstance(lines.get(b), dict) else None
        if not isinstance(o, (int, float)) or o == 0: continue
        ps.append(100 / (o + 100) if o > 0 else -o / (-o + 100))
    return min(0.95, float(np.mean(ps)) / 1.06) if ps else None


def market(p):
    L = p.get("lines") or {}
    need = NEED.get(p["pos"])
    if not need: return None
    vals = {k: (atd_p(L) if k == "atd" else cons(L, k)) for k in need}
    if any(v is None for v in vals.values()): return None
    fp = 0.0
    if p["pos"] == "QB":
        fp += vals["py"] / 25 + 4 * vals["ptd"] + vals["ry"] / 10
        it = cons(L, "int"); fp -= 2 * (it if it is not None else 0.75)
        a = atd_p(L)
        if a: fp += 6 * -math.log(1 - a)
        return fp
    fp += (vals.get("ry") or cons(L, "ry") or 0) / 10 + vals["rcy"] / 10 + 0.5 * vals["rec"] + 6 * -math.log(1 - vals["atd"])
    return fp


def spearman(a, b):
    if len(a) < 4: return None
    ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def main():
    rows = []
    for wk in (1, 2, 3, 4):
        S = json.load(open(os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{wk}.json"), encoding="utf-8"))
        act = load_rows(wk)
        for p in S["players"]:
            if p.get("pos") not in NEED: continue
            a = act.get(norm(p["name"]))
            if not a or not isinstance(p.get("mean"), (int, float)): continue
            m = market(p)
            if m is None or m <= 0: continue
            rows.append(dict(wk=wk, pos=p["pos"], name=p["name"], ship=float(p["mean"]), mkt=m, act=float(a["fpts"])))
    P(f"rows {len(rows)} player-weeks with full lines, W1-4 (preset {S.get('preset')})")
    ship = np.array([r["ship"] for r in rows]); mkt = np.array([r["mkt"] for r in rows]); act = np.array([r["act"] for r in rows])
    wk = np.array([r["wk"] for r in rows]); pos = np.array([r["pos"] for r in rows])
    gap = (ship - mkt) / mkt
    P(f"shipped vs market: median |gap| {100*np.median(np.abs(gap)):.1f}%, >15% off {100*np.mean(np.abs(gap) > .15):.0f}%, >25% off {100*np.mean(np.abs(gap) > .25):.0f}%")
    def score(pred, m):
        mae = float(np.mean(np.abs(pred[m] - act[m])))
        rhos = [spearman(pred[m & (wk == w) & (pos == ps)], act[m & (wk == w) & (pos == ps)]) for w in (1, 2, 3, 4) for ps in NEED]
        rhos = [r for r in rhos if r is not None]
        return mae, float(np.mean(rhos)) if rhos else float("nan")
    allm = np.ones(len(rows), bool)
    preds = {"shipped": ship, "market": mkt}
    for c in (0.10, 0.15, 0.20, 0.30):
        preds[f"clamp{int(c*100)}%"] = np.clip(ship, mkt * (1 - c), mkt * (1 + c))
        preds[f"cap-above{int(c*100)}%"] = np.minimum(ship, mkt * (1 + c))
        preds[f"cap-below{int(c*100)}%"] = np.maximum(ship, mkt * (1 - c))
    for g in (2.0, 3.0):
        preds[f"clamp+-{g:g}pt"] = np.clip(ship, mkt - g, mkt + g)
    P("\n  variant           MAE     rank rho  | by position MAE (QB RB WR TE) | per-week MAE vs shipped")
    b_mae, b_rho = score(ship, allm)
    for k, pr in preds.items():
        mae, rho = score(pr, allm)
        posm = " ".join(f"{float(np.mean(np.abs(pr[pos == ps] - act[pos == ps]))):5.2f}" for ps in NEED)
        wkb = sum(1 for w in (1, 2, 3, 4) if np.mean(np.abs(pr[wk == w] - act[wk == w])) < np.mean(np.abs(ship[wk == w] - act[wk == w])) - 1e-9)
        P(f"  {k:16s} {mae:6.3f} ({mae-b_mae:+.3f})  {rho:.4f} ({rho-b_rho:+.4f}) | {posm} | better in {wkb}/4 weeks")
    # where the shipped number sits far from the market: who was closer?
    P("\n  far-off rows: who was closer to the actual?")
    for lab, m in (("ship > mkt +15%", gap > .15), ("ship < mkt -15%", gap < -.15)):
        for ps in NEED:
            mm = m & (pos == ps)
            if mm.sum() >= 5:
                closer = np.mean(np.abs(ship[mm] - act[mm]) < np.abs(mkt[mm] - act[mm]))
                P(f"    {lab:16s} {ps} n{int(mm.sum()):3d}  ours closer {100*closer:3.0f}%  | mean act {act[mm].mean():5.2f} ours {ship[mm].mean():5.2f} mkt {mkt[mm].mean():5.2f}")
    LOG.close()


if __name__ == "__main__":
    main()
