#!/usr/bin/env python3
"""
The RB-signal test surfaced three "winners" (raw TDs, carries, target share)
that are all proxies for ONE thing: high prior usage/production regresses.
The 3-yr recency core does no shrinkage at all — it extrapolates the weighted
average as-is. So test the general fix directly:

    pred = m_pos + k * (core - m_pos)

sweeping k per position (k=1 is the current core; k<1 shrinks toward the
positional mean of projectable players). LOYO by season. Then check whether
RB target share still adds anything ON TOP of shrinkage, which would mean it
carries real role information rather than just level.
"""
import numpy as np
import pandas as pd
from collections import defaultdict
from backtest_sim_calibration import played, WEEKLY, infer_team, POS_KEEP
import backtest_sim_calibration as cal

W3 = [0.5, 0.3, 0.2]
YEARS = range(2019, 2026)
KS = [1.00, 0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30]

def rows_of(rec, Y):
    return [w for w in rec.get("seasons", {}).get(str(Y), []) if played(w)]

def ppg_of(rec, Y):
    pts = [w["fpts"] for w in rows_of(rec, Y) if isinstance(w.get("fpts"), (int, float))]
    return (sum(pts) / len(pts), len(pts)) if pts else (None, 0)

def main():
    pool = defaultdict(float)
    per = {}
    for nk, lst in WEEKLY.items():
        for rec in lst:
            if rec.get("pos") not in POS_KEEP:
                continue
            for Ys in rec.get("seasons", {}):
                Y = int(Ys)
                rws = rows_of(rec, Y)
                if not rws:
                    continue
                t = infer_team(rec, Y)
                per[(id(rec), Y)] = {"team": t, "tgt": sum(w.get("tgt") or 0 for w in rws), "g": len(rws)}
                if t:
                    pool[(t, Y)] += per[(id(rec), Y)]["tgt"]

    rows = []
    for nk, lst in WEEKLY.items():
        for rec in lst:
            pos = rec.get("pos")
            if pos not in POS_KEEP:
                continue
            for Y in YEARS:
                act, g = ppg_of(rec, Y)
                if act is None or g < 6:
                    continue
                n = d = 0.0
                for i, yy in enumerate((Y - 1, Y - 2, Y - 3)):
                    p, gg = ppg_of(rec, yy)
                    if p is not None and gg >= 4:
                        n += W3[i] * p; d += W3[i]
                if d == 0:
                    continue
                core = n / d
                if core < 3:
                    continue
                prev = per.get((id(rec), Y - 1))
                ts = None
                if prev and prev["team"] and pool.get((prev["team"], Y - 1)):
                    ts = prev["tgt"] / pool[(prev["team"], Y - 1)]
                rows.append({"pos": pos, "Y": Y, "core": core, "act": act, "ts": ts})
    df = pd.DataFrame(rows)

    print("=== Shrink the core toward the positional mean: pred = m + k*(core - m) ===")
    print(f"{'pos':<5}{'n':>6}" + "".join(f"{('k=%.2f' % k):>10}" for k in KS))
    best = {}
    for pos in ("QB", "RB", "WR", "TE"):
        sel = df[df.pos == pos]
        line = f"{pos:<5}{len(sel):>6}"
        scores = {}
        for k in KS:
            errs = []
            for Y in YEARS:
                tr, te = sel[sel.Y != Y], sel[sel.Y == Y]
                if len(te) < 5 or len(tr) < 40:
                    continue
                m = tr.core.mean()
                for _, t in te.iterrows():
                    errs.append(abs((m + k * (t.core - m)) - t.act))
            scores[k] = np.mean(errs)
            line += f"{np.mean(errs):>10.3f}"
        bk = min(scores, key=scores.get)
        best[pos] = (bk, scores[bk], scores[1.00])
        print(line + f"   <- best k={bk} ({(scores[bk]-scores[1.00])/scores[1.00]*100:+.2f}%)")

    print("\n=== Does RB target share add ON TOP of shrinkage? ===")
    sel = df[(df.pos == "RB") & df.ts.notna()]
    k = best["RB"][0]
    for use_ts in (False, True):
        errs = []
        for Y in YEARS:
            tr, te = sel[sel.Y != Y], sel[sel.Y == Y]
            if len(te) < 5 or len(tr) < 40:
                continue
            m = tr.core.mean()
            b = 0.0
            if use_ts:
                shr = m + k * (tr.core - m)
                b = np.polyfit(tr.ts, np.log(tr.act.clip(lower=0.2) / shr), 1)[0]
                mu = tr.ts.mean()
            for _, t in te.iterrows():
                p = m + k * (t.core - m)
                if use_ts:
                    p *= np.exp(np.clip(b * (t.ts - mu), -0.2, 0.2))
                errs.append(abs(p - t.act))
        print(f"  shrink k={k}{' + target share' if use_ts else '':<16}: MAE {np.mean(errs):.3f}")

if __name__ == "__main__":
    main()
