#!/usr/bin/env python3
"""
DORMANT LAYERS ON THE SHADOW (Jack 2026-10-09: "test the dormant layers on the shadow base"). Since 10-08 the shipped number
is the Clay-free shadow alone; five layers validated on the old live / Clay-blend chain touch nothing now
(project_layer_effects_live). Two were already graded on the shadow: banged-up prior lift (shadow_healthy_prior.log V4: FAIL;
V3 healthy history wired instead) and the ROS volume tilt (shadow_ros.log 5c TE PASS -> shadow TE tilt wired, 5d QB attempts
FAIL). This script grades the other three on the shadow replica (BR.shadow_current, 2019-25):
  A  PECKING-ORDER DOCK  WR rank >= 3 x m, RB rank >= 2 x m on the team-week (rank by the shadow number, pool >= .5 half),
                         fading in between 4 and 5 half (live rule: WR .92, RB .97)
  B  QB FLOOR            QB rows 5+ half below the week's top-32 mean: mu + k (x - mu), inheriting backups skipped (live k .70)
  C  HURT-GAMES USAGE    xFP evidence with hurt games (listed Questionable, final practice LP/DNP, snap share < 75% of his
                         season median) weighted w (live .5) - the shadow uses xFP for WR and RB (TE lam is 0)
Grading (house): next game - touched rows squared error, LOYO + forward pick-best incl. 'off', bar LOYO < -0.3% 5/7, forward
3/4, board not worse; rest-of-season read (target = mean of his remaining games, 4+ left; pred = shadow x the layer).
Log dormant_shadow.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import backtest_qb_injury_usage as QI
cal = BR.cal; YEARS = BR.YEARS; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "dormant_shadow.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()


def main():
    X = BR.SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, g, name, adp, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["name"], X["adp"], X["team"]
    pid = A["pid"]
    finw = np.where(year <= 2020, 17, 18)
    SH, _ = BR.shadow_current(X)
    TODAY, LV = BR.live_today(X)
    adpx = np.where(np.isnan(adp), 999.0, adp)
    ok = (wk != finw) & np.isfinite(act) & (SH >= 1)
    # rest-of-season target
    seq = defaultdict(list)
    for i in range(n):
        if wk[i] != finw[i]: seq[(name[i], pos[i], int(year[i]))].append(i)
    T = np.full(n, np.nan)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]
        for a, i in enumerate(ix):
            if len(ix) - a >= 4: T[i] = a_[a:].mean()
    okR = ok & np.isfinite(T)
    mse = lambda p, m, tgt=act: float(np.mean((p[m] - tgt[m]) ** 2))

    def grade(label, preds, touched, posmask=None):
        names = list(preds); base = preds["off"]; dom = ok if posmask is None else ok & posmask
        def pick(yrs): return min(names, key=lambda k: mse(preds[k], dom & np.isin(year, yrs)))
        P(f"\n{label}   touched next-game rows {int((touched & ok).sum()):,} | actual/shadow on them {act[touched & ok].sum()/base[touched & ok].sum():.3f}")
        res = {}
        for lab, folds in (("LOYO", [(tuple(y for y in YEARS if y != t), t) for t in YEARS]), ("FORWARD", [(tuple(y for y in YEARS if y < t), t) for t in FWD])):
            wins = 0; a0 = a1 = b0 = b1 = 0.0; picks = []
            for tr, te in folds:
                kk = pick(tr); picks.append(kk); r = touched & ok & (year == te); w_ = ok & (year == te)
                if not r.sum(): continue
                e0, e1 = mse(base, r), mse(preds[kk], r); wins += int(e1 < e0)
                a0 += e0 * r.sum(); a1 += e1 * r.sum(); b0 += mse(base, w_) * w_.sum(); b1 += mse(preds[kk], w_) * w_.sum()
            res[lab] = (100 * (a1 / a0 - 1), wins, len(folds), 100 * (b1 / b0 - 1))
            P(f"  {lab:8s} touched {res[lab][0]:+.2f}% ({wins}/{len(folds)}), board {res[lab][3]:+.3f}% | picks {picks}")
        P("  fixed, all seasons (touched next game | touched rest of season):")
        for k in names[1:]:
            tr_ = touched & okR
            per = sum(1 for y in YEARS if (touched & ok & (year == y)).sum() and mse(preds[k], touched & ok & (year == y)) < mse(base, touched & ok & (year == y)))
            P(f"    {k:22s} next {100*(mse(preds[k], touched & ok)/mse(base, touched & ok)-1):+6.2f}% ({per}/7)  ROS {100*(mse(preds[k], tr_, T)/mse(base, tr_, T)-1):+6.2f}%  top-150 next {100*(mse(preds[k], touched & ok & (adpx <= 150))/max(1e-9, mse(base, touched & ok & (adpx <= 150)))-1):+6.2f}%")
        trR = touched & okR
        if trR.sum():
            def pickR(yrs): return min(names, key=lambda k: mse(preds[k], trR & np.isin(year, yrs), T))
            for lab, folds in (("ROS LOYO", [(tuple(y for y in YEARS if y != t), t) for t in YEARS]), ("ROS FWD", [(tuple(y for y in YEARS if y < t), t) for t in FWD])):
                wins = 0; a0 = a1 = 0.0; picks = []
                for tr, te in folds:
                    kk = pickR(tr); picks.append(kk); r = trR & (year == te)
                    if not r.sum(): continue
                    e0, e1 = mse(base, r, T), mse(preds[kk], r, T); wins += int(e1 < e0); a0 += e0 * r.sum(); a1 += e1 * r.sum()
                P(f"  {lab:8s} touched {100*(a1/a0-1):+.2f}% ({wins}/{len(folds)}) | picks {picks}")
        L, F_ = res["LOYO"], res["FORWARD"]
        verdict = "PASS" if (L[0] < -0.3 and L[1] >= 5 and F_[1] >= 3 and L[3] <= 0) else "FAIL"
        P(f"  -> {verdict}")
        return verdict

    # ---------------- A pecking order ----------------
    grp = defaultdict(list)
    for i in range(n):
        if ok[i] and pos[i] in ("WR", "RB") and team[i] and SH[i] >= 0.5: grp[(int(year[i]), team[i], int(wk[i]), pos[i])].append(i)
    rank = np.zeros(n, int)
    for ix in grp.values():
        for r_, i in enumerate(sorted(ix, key=lambda i: -SH[i]), start=1): rank[i] = r_
    fade = np.clip(SH - 4.0, 0, 1)
    wr3 = (pos == "WR") & (rank >= 3); rb2 = (pos == "RB") & (rank >= 2)
    for lab, msk, grid in (("A1 PECKING DOCK - WR rank 3+", wr3, (0.86, 0.89, 0.92, 0.95, 0.98)), ("A2 PECKING DOCK - RB rank 2+", rb2, (0.91, 0.94, 0.97, 1.03))):
        preds = {"off": SH}
        for m in grid: preds[f"x{m:.2f}"] = SH * np.where(msk, 1 - (1 - m) * fade, 1.0)
        grade(lab, preds, msk & (fade > 0), pos == ("WR" if "WR" in lab else "RB"))

    # ---------------- B QB floor ----------------
    mu = np.full(n, np.nan)
    qb_by = defaultdict(list)
    for i in range(n):
        if pos[i] == "QB" and ok[i]: qb_by[(int(year[i]), int(wk[i]))].append(SH[i])
    for i in range(n):
        v = qb_by.get((int(year[i]), int(wk[i])))
        if v: mu[i] = float(np.mean(sorted(v, reverse=True)[:32]))
    flo = (pos == "QB") & ~LV["inh"] & (SH >= 5) & (SH < mu)
    preds = {"off": SH}
    for k in (0.6, 0.7, 0.8, 0.9):
        preds[f"k{k:.2f}"] = np.where(flo, mu + k * (SH - mu), SH)
    grade("B  QB FLOOR (toward the week's top-32 mean, below it only)", preds, flo, pos == "QB")
    for lab, m in (("bottom third", flo & (SH < np.nanpercentile(SH[flo & ok], 33))), ("rest", flo & (SH >= np.nanpercentile(SH[flo & ok], 33)))):
        P(f"    floor rows {lab}: n {int((m & ok).sum())} actual/shadow {act[m & ok].sum()/SH[m & ok].sum():.3f}")

    if os.environ.get("DORMANT_SKIP_C") == "1": LOG.close(); return
    # ---------------- C hurt-games usage ----------------
    inj = QI.load_injuries(); snaps = QI.load_snaps()
    xfp = X["xf"]; has_x = X["has_x"]
    seq2 = defaultdict(list)
    for i in range(n): seq2[(name[i], pos[i], int(year[i]))].append(i)
    gx = {}; hurt = {}
    for (nm, ps, Y), ix in seq2.items():
        ix.sort(key=lambda i: wk[i])
        sy = snaps.get(cal.norm(nm), {}).get(Y, {}); pos_s = [v for v in sy.values() if v > 0]
        med = np.median(pos_s) if len(pos_s) >= 4 else None
        for a in range(len(ix) - 1):
            i, j = ix[a], ix[a + 1]
            if g[j] - g[i] == 1 and has_x[j] and (g[i] == 0 or has_x[i]):
                gx[(nm, ps, Y, int(wk[i]))] = xfp[j] * g[j] - (xfp[i] * g[i] if g[i] > 0 else 0.0)
                rs, pr = inj.get((Y, team[i], int(wk[i]), pid[i]), ("", "")) if (pid[i] and team[i]) else ("", "")
                w0 = int(wk[i]); low = med is not None and w0 in sy and 0 < sy[w0] < 0.75 * med
                hurt[(nm, ps, Y, w0)] = (rs == "Questionable") or ("Limited" in pr) or ("Did Not" in pr) or low
    XH = {w: xfp.copy() for w in (0.0, 0.25, 0.5, 0.75)}; nh = np.zeros(n, int); full = np.zeros(n, bool)
    for (nm, ps, Y), ix in seq2.items():
        if ps not in ("WR", "RB"): continue
        ix.sort(key=lambda i: wk[i])
        for i in ix:
            if not has_x[i] or g[i] < 1: continue
            evw = [int(wk[j]) for j in ix if wk[j] < wk[i]]
            ks = [(nm, ps, Y, w0) for w0 in evw]
            if len(ks) != int(g[i]) or not all(k in gx for k in ks): continue
            full[i] = True; hs = [hurt.get(k, False) for k in ks]; nh[i] = sum(hs)
            if not nh[i]: continue
            xs = np.array([gx[k] for k in ks]); hw = np.array(hs)
            for w in XH:
                wt_ = np.where(hw, w, 1.0)
                if wt_.sum() > 0: XH[w][i] = float((xs * wt_).sum() / wt_.sum())
    P(f"\nC  per-game xFP rebuilt on {int(full.sum()):,} WR/RB rows; rows with 1+ hurt evidence game {int((nh > 0).sum()):,}")
    for ps in ("WR", "RB"):
        preds = {"off": SH}
        for w, xv in XH.items():
            X2 = dict(X); X2["xf"] = np.where(pos == ps, xv, xfp)
            preds[f"w{w:.2f}"], _ = BR.shadow_current(X2)
        grade(f"C  HURT-GAMES USAGE - {ps} (hurt evidence games weighted w in the xFP evidence)", preds, (pos == ps) & (nh > 0), pos == ps)
    LOG.close()


if __name__ == "__main__":
    main()
