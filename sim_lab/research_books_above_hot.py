#!/usr/bin/env python3
"""
BOOKS ABOVE US on hot + heavy-usage players (Jack 2026-10-20, Nabers / Hubbard: "still too low"). No historical prop archive exists,
so the "books above us" half can only be graded on the 2026 locked snapshots (W1-6, sim_lab/data/snapshots). For every player-week
with full lines: market = face-value consensus (research_book_guardrail.market), ours = the shipped mean (anchored) and the model
before the anchor (ncMean). Hot = season-to-date half PPG (weeks before) >= 1.25 x the preseason Clay per-game level (clayMean / chain
proxy is too noisy, so the Clay season sheet / 17 via the snapshot's clayMean); heavy usage = WR 8+ targets/g, TE 6+, RB 15+ carries/g
(weeks before, 2+ games). Who was closer, and what blend of ours / market fits, when the market sits 10%+ above us. Log books_above_hot.log.
"""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from score_week import norm
from diagnose_week import load_rows
from research_book_guardrail import market, NEED
LOG = open(os.path.join(HERE, "books_above_hot.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()

def main():
    weeks = [w for w in range(1, 7) if os.path.exists(os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{w}.json"))]
    acts = {w: load_rows(w) for w in range(1, 8)}
    rows = []
    for wk in weeks:
        S = json.load(open(os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{wk}.json"), encoding="utf-8"))
        for p in S["players"]:
            if p.get("pos") not in ("RB", "WR", "TE"): continue
            nk = norm(p["name"]); a = acts[wk].get(nk)
            if not a or not isinstance(p.get("mean"), (int, float)): continue
            m = market(p)
            if m is None or m <= 0: continue
            past = [acts[w][nk] for w in range(1, wk) if nk in acts[w]]
            if len(past) < 2: continue
            ppg = float(np.mean([q["fpts"] for q in past])); tg = float(np.mean([q.get("tgt") or 0 for q in past])); ca = float(np.mean([q.get("ra") or 0 for q in past]))
            heavy = (p["pos"] == "WR" and tg >= 8) or (p["pos"] == "TE" and tg >= 6) or (p["pos"] == "RB" and ca >= 15)
            base = p.get("clayMean") or p.get("jsPre") or p["mean"]
            rows.append(dict(wk=wk, pos=p["pos"], name=p["name"], ship=float(p["mean"]), nc=float(p.get("ncMean") or p["mean"]), mkt=m, act=float(a["fpts"]), ppg=ppg, hot=ppg >= 1.25 * float(base), heavy=heavy))
    P(f"rows {len(rows)} RB/WR/TE player-weeks with full lines and 2+ prior games, weeks {weeks}")
    ship = np.array([r["ship"] for r in rows]); nc = np.array([r["nc"] for r in rows]); mkt = np.array([r["mkt"] for r in rows]); act = np.array([r["act"] for r in rows])
    pos = np.array([r["pos"] for r in rows]); hot = np.array([r["hot"] for r in rows]); hv = np.array([r["heavy"] for r in rows]); wk = np.array([r["wk"] for r in rows])
    gap = mkt / np.maximum(ship, 0.1) - 1
    def show(lab, m):
        if m.sum() < 5: P(f"  {lab:52s} n {int(m.sum())}"); return
        closer = np.mean(np.abs(ship[m] - act[m]) < np.abs(mkt[m] - act[m]))
        w = np.linspace(0, 1, 11); mae = [np.mean(np.abs((1 - x) * ship[m] + x * mkt[m] - act[m])) for x in w]; bw = w[int(np.argmin(mae))]
        P(f"  {lab:52s} n {int(m.sum()):3d}  actual {act[m].mean():5.2f}  ours {ship[m].mean():5.2f} (model {nc[m].mean():5.2f})  market {mkt[m].mean():5.2f}  | act/ours {act[m].sum()/ship[m].sum():.3f}  act/mkt {act[m].sum()/mkt[m].sum():.3f}"
          f"  | ours closer {100*closer:3.0f}%  MAE ours {np.mean(np.abs(ship[m]-act[m])):.2f} mkt {np.mean(np.abs(mkt[m]-act[m])):.2f}  best blend w_mkt {bw:.1f}  weeks act>ours {sum(1 for w_ in weeks if (m & (wk == w_)).sum() and act[m & (wk == w_)].sum() > ship[m & (wk == w_)].sum())}/{len(set(wk[m]))}")
    above = gap >= 0.10
    for lab, m in (("ALL", np.ones(len(rows), bool)), ("market 10%+ above ours", above), ("hot", hot), ("heavy usage", hv), ("hot + heavy usage", hot & hv),
                   ("hot + heavy usage, market 10%+ above ours", hot & hv & above), ("heavy usage, market 10%+ above ours", hv & above), ("hot, market 10%+ above ours", hot & above)):
        show(lab, m)
        for ps in ("RB", "WR", "TE"): show(f"   {ps}", m & (pos == ps))
    P("\n  rows: hot + heavy usage with the market 10%+ above us")
    for r in sorted([r for r, f in zip(rows, hot & hv & above) if f], key=lambda r: (r["wk"], r["name"])):
        P(f"    W{r['wk']} {r['pos']} {r['name']:24s} so far {r['ppg']:5.1f} | ours {r['ship']:5.1f} model {r['nc']:5.1f} mkt {r['mkt']:5.1f} | actual {r['act']:5.1f}")
    LOG.close()

if __name__ == "__main__":
    main()
