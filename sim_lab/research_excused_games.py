#!/usr/bin/env python3
"""
Do injury exits and blowouts drag a player's snap / usage numbers down unfairly? (Jack 2026-10-02: "make sure we dont
hurt players snap and target share for injuries and blowouts".) Next-game harness, RB / WR / TE.

Each past game of a player is tagged:
    injury exit    he played under 60% of the snap share he had before it (50%+ before) AND he is on the injury report
                   (Questionable / missed or limited practice) for his next game, or misses 1+ games after it
    blowout rest   the game finished 21+ apart and he played under 85% of his prior snap share (not an injury exit)
    role loss      under 60% of his prior share with neither excuse
    normal         everything else
  1  what he does the NEXT game after each kind, against the number with no snap-level dock and with it
  2  the snap-level layer reading the last NORMAL game instead of an excused one
  3  the evidence (points + usage per game) with excused games left out, for every later checkpoint that season
Log excused_games.log.
"""
import os, sys
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
import bt_common as B
YEARS = SN.YEARS

def margins():
    out = {}
    for Y in YEARS:
        d = pd.read_csv(os.path.join(B.CACHE, f"play_by_play_{Y}.csv.gz"), usecols=["game_id", "season_type", "week", "home_team", "away_team", "home_score", "away_score"], low_memory=False)
        d = d[d.season_type == "REG"].dropna(subset=["home_team"]).groupby("game_id").first()
        for r in d.itertuples():
            m = abs(float(r.home_score) - float(r.away_score))
            out[(Y, B.tm(r.home_team), int(r.week))] = m; out[(Y, B.tm(r.away_team), int(r.week))] = m
    return out

def main():
    log = open(os.path.join(HERE, "excused_games.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n"); log.flush()
    X = SN.setup(); n = X["n"]; F = X["F"]; A = X["A"]
    act, year, wk, pos, g, adp, name, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["team"]
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = A["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    xpg, sl1, sstd, smx = colv("xfp_pg"), colv("snap_l1"), colv("snap_std"), colv("snapmult")
    listed = (colv("rep_q") == 1) | (colv("prac_dnp") > 0) | (colv("prac_lim") > 0)
    smx = np.where(np.isnan(smx), 1.0, smx)
    MG = margins(); marg = np.array([MG.get((int(year[i]), B.tm(str(team[i])), int(wk[i])), np.nan) for i in range(n)])
    SH = SN.shadow(X); finw = np.where(year <= 2020, 17, 18); final = wk == finw; allr = ~final & (SH >= 3); top150 = adp <= 150
    sk = np.isin(pos, ["RB", "WR", "TE"])
    seq = defaultdict(list)
    for i in range(n): seq[(name[i], pos[i], int(year[i]))].append(i)
    gx = np.full(n, np.nan); gsnap = np.full(n, np.nan); tag = np.zeros(n, int)     # per-game xFP, per-game snap share; 0 normal 1 injury exit 2 blowout rest 3 role loss
    prev = np.full(n, -1)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i])
        for a in range(len(ix) - 1):
            i, j = ix[a], ix[a + 1]; prev[j] = i
            if g[j] - g[i] == 1 and not np.isnan(xpg[j]): gx[i] = xpg[j] * g[j] - (xpg[i] * g[i] if g[i] > 0 and not np.isnan(xpg[i]) else 0.0)
            gsnap[i] = sl1[j]
            if np.isnan(sstd[i]) or sstd[i] < 50 or np.isnan(sl1[j]): continue
            ratio = sl1[j] / sstd[i]; gap = wk[j] - wk[i]
            if ratio < 0.6 and (listed[j] or gap >= 3): tag[i] = 1
            elif ratio < 0.85 and not np.isnan(marg[i]) and marg[i] >= 21: tag[i] = 2
            elif ratio < 0.6: tag[i] = 3
    hasp = prev >= 0; pv = np.maximum(prev, 0); ptag = np.where(hasp, tag[pv], 0)     # the kind of game he is coming off
    tg = sk & ~np.isnan(gsnap)
    P(f"=== excused games: {int(tg.sum()):,} RB / WR / TE games with a snap share; injury exit {int((tag[tg]==1).sum())}, blowout rest {int((tag[tg]==2).sum())}, role loss {int((tag[tg]==3).sum())} ===")
    for k, lab in ((1, "injury exit"), (2, "blowout rest"), (3, "role loss")):
        m = tg & (tag == k); P(f"  {lab:13s}: snap share that game {np.nanmean(gsnap[m]):.0f}% vs {np.nanmean(sstd[m]):.0f}% before; usage (xFP) {np.nanmean(gx[m]):.2f} vs his average {np.nanmean(xpg[m]):.2f}; points {act[m].mean():.2f} vs {X['ppg'][m].mean():.2f}")
    # snap-level layer, last game as-is
    l1 = X["snap_l1"]
    def level_dev(share):
        dev = np.zeros(n)
        for ps in ("WR", "TE"):
            m = (pos == ps) & (g >= 1) & ~np.isnan(l1) & allr; q = np.quantile(SH[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, SH, side="right") - 1, 0, 7)
            for k in range(8):
                mk = m & (b_ == k)
                if mk.sum() >= 30: dev[mk] = np.where(np.isnan(share[mk]), 0.0, share[mk] - np.nanmean(l1[mk]))
        return dev
    lvl = np.where(np.isin(pos, ["WR", "TE"]) & ~(adp <= 30), np.clip(1 + 0.3 * level_dev(l1) / 100.0, 0.7, 1.4), 1.0)
    lvl = np.where(np.isin(pos, ["WR", "TE"]) & (adp <= 30), np.maximum(1.0, np.clip(1 + 0.3 * level_dev(l1) / 100.0, 0.7, 1.4)), lvl)   # v2.31: no dock for the top 30
    trend = np.where(np.isin(pos, ["RB", "TE"]), smx, 1.0)
    NO = SH * trend; WITH = NO * lvl
    ms = lambda q, m: float(np.mean((q[m] - act[m]) ** 2)) if m.any() else np.nan

    P("\n--- 1  THE NEXT GAME after each kind of game (he played it) ---")
    for k, lab in ((1, "injury exit"), (2, "blowout rest"), (3, "role loss")):
        for bl, bm in (("top 150", top150), ("later / undrafted", ~top150)):
            for ps in ("RB", "WR + TE"):
                m = allr & sk & (ptag == k) & bm & ((pos == "RB") if ps == "RB" else (pos != "RB"))
                if m.sum() < 30: continue
                ys = [act[m & (year == y)].sum() / NO[m & (year == y)].sum() for y in YEARS if (m & (year == y)).sum() >= 5]
                P(f"    {lab:13s} {bl:18s} {ps:8s} n {int(m.sum()):4d}  actual {act[m].mean():5.2f} | no level dock {NO[m].mean():5.2f} -> {act[m].sum()/NO[m].sum():.3f} (under {sum(1 for v in ys if v < 1)}/{len(ys)})"
                  + (f" | with the level layer {WITH[m].mean():5.2f} -> {act[m].sum()/WITH[m].sum():.3f}, error {100*(ms(WITH, m)/ms(NO, m)-1):+.1f}%" if ps != "RB" else f" | (RB: trend only; snap-trend multiplier {trend[m].mean():.3f})"))

    P("\n--- 2  SNAP-LEVEL LAYER reading the last NORMAL game when the last game is excused (WR + TE) ---")
    last_norm = l1.copy()
    for ix in seq.values():
        for a, j in enumerate(ix):
            if a and tag[ix[a - 1]] in (1, 2):
                back = [i for i in ix[:a] if tag[i] == 0 and not np.isnan(gsnap[i])]
                last_norm[j] = gsnap[back[-1]] if back else np.nan
    lv2 = np.where(np.isin(pos, ["WR", "TE"]), np.clip(1 + 0.3 * level_dev(last_norm) / 100.0, 0.7, 1.4), 1.0)
    lv2 = np.where((adp <= 30), np.maximum(1.0, lv2), lv2); V2 = NO * lv2
    for lab, kk in (("coming off an injury exit", (1,)), ("coming off a blowout rest", (2,)), ("either", (1, 2))):
        m = allr & (pos != "RB") & sk & np.isin(ptag, kk) & (np.abs(V2 - WITH) > 1e-9)
        if m.sum() < 30: P(f"    {lab:28s} n {int(m.sum())} (too few)"); continue
        sb = sum(1 for y in YEARS if (m & (year == y)).sum() >= 5 and ms(V2, m & (year == y)) < ms(WITH, m & (year == y))); ny = sum(1 for y in YEARS if (m & (year == y)).sum() >= 5)
        P(f"    {lab:28s} n {int(m.sum()):4d}  actual {act[m].mean():5.2f}  last game as-is {WITH[m].mean():5.2f} ({act[m].sum()/WITH[m].sum():.3f})  last normal game {V2[m].mean():5.2f} ({act[m].sum()/V2[m].sum():.3f})  error {100*(ms(V2, m)/ms(WITH, m)-1):+.1f}% ({sb}/{ny})")

    P("\n--- 3  EVIDENCE (points + usage per game) with excused games left out, every later checkpoint ---")
    def evid(excuse):
        pp = X["ppg"].copy(); xx = X["xf"].copy(); ge = g.astype(float).copy(); ch = np.zeros(n, bool)
        for ix in seq.values():
            for a, j in enumerate(ix):
                past = ix[:a]
                if not past or not any(tag[i] in excuse for i in past): continue
                keep = [i for i in past if tag[i] not in excuse]
                if len(keep) < 1 or len(past) != g[j]: continue
                pp[j] = act[keep].mean(); ge[j] = len(keep); ch[j] = True
                kx = [i for i in keep if not np.isnan(gx[i])]
                if kx and X["has_x"][j]: xx[j] = gx[kx].mean()
        X2 = dict(X); X2["ppg_v"] = np.where(ch & (X["ppg"] > 0), X["ppg_v"] * pp / np.maximum(X["ppg"], 1e-9), X["ppg_v"]); X2["xf"] = xx; X2["g"] = ge
        return SN.shadow(X2) * trend * lvl, ch
    base_pred = WITH
    lvw = F["adp_curve"].copy()
    for ps in ("QB", "RB", "WR", "TE"):
        m = pos == ps; lvw[m & np.isnan(lvw)] = np.nanmin(lvw[m]); lvw[m] = lvw[m] / lvw[m & top150].mean()
    wt = np.maximum(0.05, lvw) ** 2; bs = top150 & ~final
    wm = lambda q, m: float(np.average((q[m] - act[m]) ** 2, weights=wt[m]))
    def rho(p_, m):
        gr = defaultdict(list)
        for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        return float(np.mean([np.corrcoef(rankdata(act[ix]), rankdata(p_[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]))
    for lab, ex in (("injury exits left out", (1,)), ("blowout rests left out", (2,)), ("both left out", (1, 2)), ("role-loss games left out (control - should hurt)", (3,))):
        V, ch = evid(ex); tm = allr & sk & ch & (np.abs(V - base_pred) > 1e-9)
        if tm.sum() < 60: P(f"  {lab}: too few rows"); continue
        P(f"  {lab}: rows changed {int(tm.sum())}")
        for sl, m in (("all", tm), ("top 150", tm & top150), ("ADP 1-60", tm & (adp <= 60)), ("RB", tm & (pos == "RB")), ("WR", tm & (pos == "WR")), ("TE", tm & (pos == "TE")), ("the very next game", tm & np.isin(ptag, ex)), ("two or more games later", tm & ~np.isin(ptag, ex))):
            if m.sum() < 40: continue
            sb = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and ms(V, m & (year == y)) < ms(base_pred, m & (year == y))); ny = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8)
            P(f"    {sl:26s} n {int(m.sum()):5d}  error {100*(ms(V, m)/ms(base_pred, m)-1):+.2f}% ({sb}/{ny})  actual {act[m].mean():5.2f}  shipped {base_pred[m].mean():5.2f}  excused {V[m].mean():5.2f}")
        P(f"    whole board: all rows {100*(ms(V, allr)/ms(base_pred, allr)-1):+.3f}%  top-150 weighted {100*(wm(V, bs)/wm(base_pred, bs)-1):+.3f}%  rank order {rho(V, bs) - rho(base_pred, bs):+.4f}")
    P(); P("--- 4  REST OF SEASON: the snap trend carried forward (v2.26, RBs) when the last game was excused ---")
    layers = X["layers"]; T = np.full(n, np.nan); cx = np.full(n, np.nan)
    for ix in seq.values():
        nf = [i for i in ix if not final[i]]
        for a, i in enumerate(nf):
            if len(nf) - a >= 2: T[i] = act[nf[a:]].mean(); cx[i] = np.clip(layers[nf[a:]], 0.5, 1.8).mean()
    R = SH / np.where(layers > 0, layers, 1.0) * cx
    msT = lambda q, m: float(np.mean((q[m] - T[m]) ** 2))
    for k, lab in ((1, "injury exit"), (2, "blowout rest"), (3, "role loss"), (0, "normal game")):
        for bl, bm in (("top 150", top150), ("later", ~top150)):
            m = allr & (pos == "RB") & (ptag == k) & bm & ~np.isnan(T) & (g >= 3) & hasp
            if m.sum() < 30: continue
            V = R * smx; sb = sum(1 for y in YEARS if (m & (year == y)).sum() >= 5 and msT(V, m & (year == y)) < msT(R, m & (year == y))); ny = sum(1 for y in YEARS if (m & (year == y)).sum() >= 5)
            P(f"    RB coming off a {lab:13s} {bl:8s} n {int(m.sum()):4d}  rest-of-season actual {T[m].mean():5.2f} | no trend {R[m].mean():5.2f} ({T[m].sum()/R[m].sum():.3f}) | trend carried {V[m].mean():5.2f} ({T[m].sum()/V[m].sum():.3f}), trend avg {smx[m].mean():.3f}, error {100*(msT(V, m)/msT(R, m)-1):+.1f}% ({sb}/{ny})")
    log.close()

if __name__ == "__main__":
    main()
