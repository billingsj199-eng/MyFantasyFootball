#!/usr/bin/env python3
"""
How much does in-season USAGE (xFP) matter once injury-driven usage is factored out? (Jack 2026-10-02: "how important
is usage or xfp in season with factoring out usage because of injuries")

Per-game xFP is rebuilt from the season-to-date average in ctx_features (difference of running totals). Each past
game of a player is tagged:
    teammate out   a teammate at his position holding a real share was out that week
                   (RB: 20%+ of team carries out; WR: 15%+ of targets out at WR; TE: 15%+ of team targets out)
    left early     he played under 60% of the snap share he had before that game (50%+ before)
    normal         neither
At every checkpoint with 3+ games played (RB / WR / TE):
  1  how predictive usage is, all games vs normal games only (next game and rest-of-season PPG), and what usage adds
     on top of points + past seasons
  2  how big the teammate-out bump is and how much of it carries forward (teammate back vs still out)
  3  the model: the Clay-free number on players whose usage was inflated by a teammate's absence, and the same number
     with the evidence built from normal games only
Log usage_injury.log.
"""
import os, sys
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
YEARS = SN.YEARS

def main():
    log = open(os.path.join(HERE, "usage_injury.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n"); log.flush()
    X = SN.setup(); n = X["n"]; F = X["F"]; A = X["A"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = A["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    xpg, vcs, vts, vt, sl1, sstd = colv("xfp_pg"), colv("vac_car_same"), colv("vac_tgt_same"), colv("vac_tgt"), colv("snap_l1"), colv("snap_std")
    SH = SN.shadow(X); finw = np.where(year <= 2020, 17, 18); final = wk == finw; allr = ~final & (SH >= 3); top150 = adp <= 150
    out_now = np.where(pos == "RB", vcs >= 0.20, np.where(pos == "WR", vts >= 0.15, np.where(pos == "TE", vt >= 0.15, False)))   # a teammate out THIS game
    seq = defaultdict(list)
    for i in range(n): seq[(name[i], pos[i], int(year[i]))].append(i)
    gx = np.full(n, np.nan); tag = np.zeros(n, int)          # per-game xFP; 0 normal, 1 teammate out, 2 left early
    xa, xn, xo, pa, pn, po = (np.full(n, np.nan) for _ in range(6)); n_n = np.zeros(n, int); n_o = np.zeros(n, int); T = np.full(n, np.nan)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i])
        for a in range(len(ix) - 1):
            i, j = ix[a], ix[a + 1]
            if g[j] - g[i] == 1 and not np.isnan(xpg[j]):
                gx[i] = xpg[j] * g[j] - (xpg[i] * g[i] if g[i] > 0 and not np.isnan(xpg[i]) else 0.0)
            if not np.isnan(sstd[i]) and sstd[i] >= 50 and not np.isnan(sl1[j]) and sl1[j] < 0.6 * sstd[i]: tag[i] = 2
            elif out_now[i]: tag[i] = 1
        nf = [i for i in ix if not final[i]]; af = act[nf] if nf else None
        for a, j in enumerate(ix):
            past = ix[:a]; past = [i for i in past if not np.isnan(gx[i])]
            if past:
                P_ = np.array(past); xa[j] = gx[P_].mean(); pa[j] = act[P_].mean()
                nm = P_[tag[P_] == 0]; om = P_[tag[P_] == 1]; n_n[j], n_o[j] = len(nm), len(om)
                if len(nm): xn[j] = gx[nm].mean(); pn[j] = act[nm].mean()
                if len(om): xo[j] = gx[om].mean(); po[j] = act[om].mean()
            if j in nf:
                k = nf.index(j)
                if len(nf) - k >= 3: T[j] = af[k:].mean()
    sk = np.isin(pos, ["RB", "WR", "TE"]); ok = allr & sk & (g >= 3) & ~np.isnan(xa)
    chk = ok & (np.abs(xa - xpg) < 0.75)
    P(f"=== usage and injuries: {int(ok.sum()):,} checkpoints (RB / WR / TE, 3+ games played); per-game xFP rebuilt cleanly on {100*chk.sum()/ok.sum():.0f}% ===")
    tg = sk & ~np.isnan(gx)
    for ps in ("RB", "WR", "TE"):
        m = tg & (pos == ps)
        P(f"  {ps}: games tagged normal {100*(tag[m]==0).mean():.0f}%, teammate out {100*(tag[m]==1).mean():.0f}%, left early {100*(tag[m]==2).mean():.0f}%;  xFP a game: normal {gx[m & (tag==0)].mean():.2f}, teammate out {gx[m & (tag==1)].mean():.2f}, left early {gx[m & (tag==2)].mean():.2f}")
    hist = F["hist"]
    def r(a, b, m):
        m = m & ~np.isnan(a) & ~np.isnan(b)
        return np.corrcoef(a[m], b[m])[0, 1] if m.sum() >= 80 else np.nan
    def r2(cols, y, m):
        m = m & ~np.isnan(y)
        for c in cols: m = m & ~np.isnan(c)
        if m.sum() < 150: return np.nan, 0
        Xd = np.column_stack([np.ones(m.sum())] + [c[m] for c in cols]); b = np.linalg.lstsq(Xd, y[m], rcond=None)[0]; res = y[m] - Xd @ b
        return 1 - res.var() / y[m].var(), int(m.sum())

    P("\n--- 1  HOW PREDICTIVE USAGE IS, all games vs normal games only ---")
    for ps in ("RB", "WR", "TE"):
        m = ok & (pos == ps) & ~np.isnan(xn) & (n_n >= 2) & ~np.isnan(hist)
        P(f"  {ps} ({int(m.sum()):,} checkpoints with 2+ normal games):")
        for tl, y in (("next game", act), ("rest of season", T)):
            base, nn = r2([hist, pa], y, m); wa, _ = r2([hist, pa, xa], y, m); wn_, _ = r2([hist, pa, xn], y, m); wb, _ = r2([hist, pn, xn], y, m)
            P(f"    {tl:15s} correlation: points per game {r(pa, y, m):.3f} | usage, all games {r(xa, y, m):.3f} | usage, normal games only {r(xn, y, m):.3f} | points, normal games only {r(pn, y, m):.3f}")
            P(f"    {'':15s} explained (R-squared): history + points {100*base:.1f}% | + usage, all games {100*wa:.1f}% (+{100*(wa-base):.2f}) | + usage, normal games {100*wn_:.1f}% (+{100*(wn_-base):.2f}) | history + normal-game points + normal-game usage {100*wb:.1f}%")
        mh = m & (n_o >= 1)
        for tl, y in (("next game", act), ("rest of season", T)):
            P(f"    players who also had a teammate-out game ({int((mh & ~np.isnan(y)).sum())}), {tl}: usage all games r {r(xa, y, mh):.3f} | normal games only r {r(xn, y, mh):.3f} | teammate-out games only r {r(xo, y, mh):.3f}")

    P("\n--- 2  THE TEAMMATE-OUT BUMP: how big, and how much carries forward ---")
    for ps in ("RB", "WR", "TE"):
        m = ok & (pos == ps) & (n_n >= 2) & (n_o >= 1) & ~np.isnan(xn) & ~np.isnan(xo)
        if m.sum() < 150: continue
        bump = xo - xn; pb = po - pn
        P(f"  {ps}: {int(m.sum())} checkpoints with both kinds of game. Usage in teammate-out games {xo[m].mean():.2f} vs normal {xn[m].mean():.2f} xFP ({100*(xo[m].mean()/xn[m].mean()-1):+.0f}%); points {po[m].mean():.2f} vs {pn[m].mean():.2f} ({100*(po[m].mean()/pn[m].mean()-1):+.0f}%)")
        for lab, mm in (("teammate BACK for the next game", m & ~out_now), ("teammate still OUT for the next game", m & out_now)):
            if mm.sum() < 100: continue
            Xd = np.column_stack([np.ones(mm.sum()), xn[mm], bump[mm]]); b = np.linalg.lstsq(Xd, act[mm], rcond=None)[0]
            P(f"    {lab:38s} n {int(mm.sum()):4d}: next game = {b[0]:.2f} + {b[1]:.2f} x normal usage + {b[2]:.2f} x bump  ->  {100*b[2]/b[1]:.0f}% of the bump carries; actual {act[mm].mean():.2f} vs normal-game points {pn[mm].mean():.2f} / all-game points {pa[mm].mean():.2f}")
        mm = m & ~np.isnan(T)
        if mm.sum() >= 100:
            Xd = np.column_stack([np.ones(mm.sum()), xn[mm], bump[mm]]); b = np.linalg.lstsq(Xd, T[mm], rcond=None)[0]
            P(f"    {'rest of season':38s} n {int(mm.sum()):4d}: {b[0]:.2f} + {b[1]:.2f} x normal usage + {b[2]:.2f} x bump  ->  {100*b[2]/b[1]:.0f}% of the bump carries")

    P("\n--- 3  THE MODEL: evidence from every game (shipped) vs from normal games only ---")
    wt_lv = F["adp_curve"].copy()
    for ps in ("QB", "RB", "WR", "TE"):
        m = pos == ps; wt_lv[m & np.isnan(wt_lv)] = np.nanmin(wt_lv[m]); wt_lv[m] = wt_lv[m] / wt_lv[m & top150].mean()
    wt = np.maximum(0.05, wt_lv) ** 2; base = top150 & ~final
    ms = lambda q, m: float(np.mean((q[m] - act[m]) ** 2)) if m.any() else np.nan
    wm = lambda q, m: float(np.average((q[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    def rho(p_, m):
        gr = defaultdict(list)
        for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        return float(np.mean([np.corrcoef(rankdata(act[ix]), rankdata(p_[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]))
    can = sk & (g >= 3) & (n_n >= 2) & (n_o >= 1) & ~np.isnan(xn) & ~np.isnan(pn) & (pa > 0)
    infl = can & (xa >= xn + 0.5)
    P(f"  players whose all-game usage runs 0.5+ xFP above their normal-game usage: {int((infl & allr).sum())} rows")
    for lab, m in (("teammate back", infl & allr & ~out_now), ("teammate still out", infl & allr & out_now)):
        if m.sum() >= 60: P(f"    {lab:20s} n {int(m.sum()):4d}  actual {act[m].mean():.2f}  Clay-free {SH[m].mean():.2f}  -> actual / projected {act[m].sum()/SH[m].sum():.3f}  ({sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and act[m & (year == y)].sum() < SH[m & (year == y)].sum())}/7 seasons under)")
    X2 = dict(X); X2["xf"] = np.where(can & X["has_x"], xn, X["xf"]); V1 = SN.shadow(X2)
    X3 = dict(X2); X3["ppg_v"] = np.where(can, X["ppg_v"] * pn / np.maximum(pa, 1e-9), X["ppg_v"]); V2 = SN.shadow(X3)
    X4 = dict(X); X4["ppg_v"] = X3["ppg_v"]; X4["xf"] = X2["xf"]
    for lab, V in (("usage from normal games only", V1), ("usage AND points from normal games only", V2)):
        tm = allr & (np.abs(V - SH) > 1e-9)
        P(f"  {lab}: rows changed {int(tm.sum())}")
        for sl, m in (("all changed rows", tm), ("teammate back", tm & ~out_now), ("teammate still out", tm & out_now), ("RB", tm & (pos == "RB")), ("WR", tm & (pos == "WR")), ("TE", tm & (pos == "TE"))):
            if m.sum() < 60: continue
            sb = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and ms(V, m & (year == y)) < ms(SH, m & (year == y)))
            P(f"    {sl:20s} n {int(m.sum()):5d}  error {100*(ms(V, m)/ms(SH, m)-1):+.2f}% ({sb}/7)   actual {act[m].mean():.2f}  shipped {SH[m].mean():.2f}  normal-games {V[m].mean():.2f}")
        P(f"    whole board: all rows {100*(ms(V, allr)/ms(SH, allr)-1):+.3f}%  top-150 weighted {100*(wm(V, base)/wm(SH, base)-1):+.3f}%  rank order {rho(V, base) - rho(SH, base):+.4f}")
    log.close()

if __name__ == "__main__":
    main()
