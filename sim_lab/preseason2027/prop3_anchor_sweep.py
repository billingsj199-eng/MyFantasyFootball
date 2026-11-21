#!/usr/bin/env python3
"""
Proposal 3 (2026-11-21 review, Jack "look at proposals 3-5"): re-tune the BOOK-ANCHOR weight.

Data: 2026 is the ONLY season with stored prop lines (data/snapshots/simlab_snapshot_w1..w10.json, kickoff-frozen locks;
no pre-2026 prop history exists on disk or free online - see the data-pull scoping). So every result is PROVISIONAL.
Market mean per row is backed out of the lock with the weight the engine actually used that week:
   propMean = w_used x market + (1 - w_used) x jsMean   ->   market = (propMean - (1 - w_used) jsMean) / w_used
(w_used = tun.w, the tuned per-position weight; .70 before the tuner existed). Rows where aboveW / belowW / BOOK_CAP moved
the effective weight make the backed-out market approximate - stated in the report.
Candidate = w x market + (1 - w) x base, base = jsMean (= the shadow weekly base since 10-08), w swept 0..1 by .1, per position.
Honest split: pick w on weeks 1-6, score weeks 7-10 (and the reverse). MAE, MSE and within position-week Spearman.
Read-only: no engine / export change. Writes prop3_anchor_sweep.log.
"""
import glob, json, os, re, sys
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__)); SIM = os.path.dirname(HERE)
sys.path.insert(0, SIM)
from score_week import norm
from diagnose_week import load_rows
LOG = None   # opened by main(); importing this module never truncates prop3_anchor_sweep.log
LOG_NAME = "prop3_anchor_sweep.log"
GRID = [round(x, 1) for x in np.arange(0, 1.01, 0.1)]
POS4 = ("QB", "RB", "WR", "TE")


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def main():
    global LOG
    LOG = open(os.path.join(HERE, LOG_NAME), "w", encoding="utf-8")
    rows = []
    for f in sorted(glob.glob(os.path.join(SIM, "data", "snapshots", "simlab_snapshot_w*.json"))):
        wk = int(re.search(r"_w(\d+)\.json$", f).group(1)); act = load_rows(wk)
        if not act: continue
        snap = json.load(open(f, encoding="utf-8"))
        for p in snap["players"]:
            if p.get("pos") not in POS4 or p.get("propSrc") != "line" or p.get("propMean") is None or p.get("jsMean") is None: continue
            a = act.get(norm(p["name"]))
            if a is None: continue
            w_used = (p.get("tun") or {}).get("w") or 0.70
            if w_used < 0.05: continue
            mkt = (p["propMean"] - (1 - w_used) * p["jsMean"]) / w_used
            rows.append({"wk": wk, "pos": p["pos"], "name": p["name"], "act": a["fpts"], "base": p["jsMean"], "nc": p.get("ncMean"), "mkt": max(0.0, mkt),
                         "prop": p["propMean"], "shipped": p.get("mean"), "w_used": w_used})
    D = pd.DataFrame(rows)
    P(f"=== Proposal 3: book-anchor weight sweep, 2026 weeks {sorted(D.wk.unique())} (the only season with prop lines) ===")
    P(f"  lined QB/RB/WR/TE rows with actuals: {len(D)} | by pos " + " ".join(f"{k}:{v}" for k, v in D.pos.value_counts().items()))
    P(f"  weights the engine actually used (tun.w), median by pos: " + " ".join(f"{ps} {D[D.pos == ps].w_used.median():.2f}" for ps in POS4))

    def score(sub, w):
        pr = w * sub.mkt + (1 - w) * sub.base
        rh = [spearmanr(g_pr, g.act).correlation for (_, _), g in sub.assign(pr=pr).groupby(["wk", "pos"]) for g_pr in [g.pr] if len(g) >= 8]
        return float(np.mean(np.abs(pr - sub.act))), float(np.mean((pr - sub.act) ** 2)), float(np.nanmean(rh))

    P("\n  full sweep (all 2026 weeks; in-sample, for the SHAPE of the curve): MAE / rank rho by w")
    for ps in POS4 + ("ALL",):
        sub = D if ps == "ALL" else D[D.pos == ps]
        res = [score(sub, w) for w in GRID]
        best = int(np.argmin([r[0] for r in res]))
        used = sub.w_used.median()
        P(f"  {ps:3s} n {len(sub):4d}: " + " ".join(f"{w:.1f}:{r[0]:.3f}/{r[2]:.3f}" for w, r in zip(GRID, res)) +
          f" | best MAE w {GRID[best]} ({res[best][0]:.3f}); flatness: MAE range over w 0.3-0.8 = {max(r[0] for w, r in zip(GRID, res) if .3 <= w <= .8) - min(r[0] for w, r in zip(GRID, res) if .3 <= w <= .8):.3f}")
    P("\n  week bands (MAE at w = 0 / .3 / .5 / .7 / 1, all positions):")
    for lab, mk in (("weeks 1-4", D.wk <= 4), ("weeks 5-10", D.wk >= 5)):
        sub = D[mk]; P(f"    {lab:10s} n {len(sub)}: " + " ".join(f"{w}:{score(sub, w)[0]:.3f}" for w in (0, .3, .5, .7, 1.0)))
    P("  (weeks 13-17 have not been played yet in 2026 - no lines + results to grade)")

    P("\n  HONEST SPLIT: pick w per position on one half, score on the other (MAE / rho)")
    for lab, tr_m, te_m in (("pick 1-6 -> score 7-10", D.wk <= 6, D.wk >= 7), ("pick 7-10 -> score 1-6", D.wk >= 7, D.wk <= 6)):
        tot_new = tot_used = 0.0; n = 0; parts = []
        for ps in POS4:
            tr = D[tr_m & (D.pos == ps)]; te = D[te_m & (D.pos == ps)]
            wb = GRID[int(np.argmin([score(tr, w)[0] for w in GRID]))]
            new = score(te, wb); cur = (float(np.mean(np.abs(te.prop - te.act))), 0, float(np.nanmean([spearmanr(g.prop, g.act).correlation for _, g in te.groupby("wk") if len(g) >= 8])))
            parts.append(f"{ps} w {wb}: {new[0]:.3f}/{new[2]:.3f} vs shipped anchor {cur[0]:.3f}/{cur[2]:.3f}")
            tot_new += new[0] * len(te); tot_used += cur[0] * len(te); n += len(te)
        P(f"  {lab}: " + " | ".join(parts))
        P(f"     pooled MAE re-tuned {tot_new/n:.3f} vs shipped anchor {tot_used/n:.3f} ({(tot_new/tot_used - 1)*100:+.2f}%)")
    # week-to-week stability of the best weight
    P("\n  best w by week (all positions): " + " ".join(f"W{w}:{GRID[int(np.argmin([score(D[D.wk == w], x)[0] for x in GRID]))]}" for w in sorted(D.wk.unique())))
    # bootstrap the gain of the in-sample best pooled w vs the shipped anchor (by week clusters)
    rng = np.random.default_rng(1); wks = sorted(D.wk.unique()); gains = []
    for _ in range(500):
        bs = rng.choice(wks, len(wks)); sub = pd.concat([D[D.wk == w] for w in bs])
        b = min(GRID, key=lambda w: score(sub, w)[0])
        gains.append(score(sub, b)[0] - float(np.mean(np.abs(sub.prop - sub.act))))
    P(f"  week-cluster bootstrap of (best-w MAE - shipped MAE), in-sample upper bound: median {np.median(gains):+.3f}, 90% [{np.quantile(gains, .05):+.3f}, {np.quantile(gains, .95):+.3f}]")


if __name__ == "__main__":
    main()
