#!/usr/bin/env python3
"""
CONTEXTUALIZE QB PLAY FOR A RECEIVER (Jack 2026-10-07: "can we figure out a way to contextualize the qb play for a guy
like london" + "when vegas is giving teams more points based on a personnel change and they have had success with that
change can we assume going forward they will be better than the weeks without that change").  RESEARCH.

The 10-07 morning test DOWN-WEIGHTED a receiver's games thrown by a different QB and lost (WR +4-18% worse). These
keep every game and RESCALE it instead:
  V1  QB-quality ratio      game points x (Q_now / Q_then)^b, Q = the QB's Clay per-game number (what the market thought
                            of each passer before the season); b in .25 .5 .75 1
  V2  team-total ratio      game points x (team implied total now / implied total in that game)^b - Vegas's own re-rating
                            of the offense; on off-QB games only, or on every game (the shadow's Vegas-cleaned evidence
                            at b = elasticity .25 is the mild version); plus "re-rated up 10%+" only
  V3  same-QB history       the receiver's prior-season games WITH the QB who starts this week (4+ games) join the
                            evidence at weight k per game (k .5 / 1) - London with Penix in 2025
  V4  V2 + V3 together
Live form (Clay blend P 5, usage mix, TD luck, chain), 2019-25, next game / rest of season; rows graded = WR/TE whose
evidence includes a game thrown by a different QB than this week's expected starter (last game's starter; 'actual'
starter as the oracle check). LOYO + forward picks, ship bar 5/7 + 3/4, whole-board guard. Log qb_context.log.
"""
import json, os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_qb_injury_usage as QI
NW = QI.NW; cal = QI.cal; YEARS = QI.YEARS; SK = QI.SK; FWD = QI.FWD; POS4 = QI.POS4
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "qb_context.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    X = QI.setup(); n = X["n"]
    act, year, wk, pos, g, adp, name, pid, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["pid"], X["team"]
    F = X["F"]; finw = np.where(year <= 2020, 17, 18); final = wk == finw
    adpx = np.where(np.isnan(adp), 999.0, adp); top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    games, roster, starter, team_weeks = QI.build_games(X)
    ch = X["ch"]
    # QB quality = Clay per-game number that season (fallback: league backup level 8)
    def qclay(Y, qb):
        c = (ch.get(str(Y)) or {}).get(qb)
        if not c: return 8.0
        gm = c.get("gm") or 0; W = 16 if Y <= 2020 else 17
        return max(4.0, (c.get("pts") or 0) / (gm if gm >= 4 else W))
    # team implied total per row (context features)
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    implied = np.where(has, C["implied"].values[np.maximum(idx, 0)], np.nan).astype(float)
    xfp, snl1 = X["xfp"], X["snap_l1"]
    seq = defaultdict(list)
    for i in range(n): seq[(name[i], pos[i], int(year[i]))].append(i)
    gx, gsn, rowof = {}, {}, {}
    for (nm, ps, Y), ix in seq.items():
        ix.sort(key=lambda i: wk[i])
        for i in ix: rowof[(nm, ps, Y, int(wk[i]))] = i
        for a in range(len(ix) - 1):
            i, j = ix[a], ix[a + 1]
            if g[j] - g[i] == 1 and not np.isnan(xfp[j]):
                prevx = xfp[i] * g[i] if (g[i] > 0 and not np.isnan(xfp[i])) else (0.0 if g[i] == 0 else np.nan)
                if not np.isnan(prevx): gx[(nm, ps, Y, int(wk[i]))] = xfp[j] * g[j] - prevx
            if g[j] - g[i] == 1 and not np.isnan(snl1[j]): gsn[(nm, ps, Y, int(wk[i]))] = snl1[j]
    # per-row evidence with QB and implied total per game; same-QB prior-season games
    EV = [None] * n; covered = np.zeros(n, bool); off_r = np.zeros(n, bool); off_act = np.zeros(n, bool); new_qb = np.zeros(n, bool); same_hist = np.zeros(n, bool)
    for i in range(n):
        if pos[i] not in SK or g[i] < 1: continue
        key = (name[i], pos[i], int(year[i])); Y = int(year[i])
        if key not in games: continue
        tm_, cpg, gl = games[key]
        evw = [w for w in sorted(gl) if w < wk[i]]
        if len(evw) != int(g[i]) or not tm_: continue
        prior_w = [w for w in team_weeks.get((Y, tm_), []) if w < wk[i]]
        s_last = starter.get((Y, tm_, prior_w[-1])) if prior_w else None
        s_act = starter.get((Y, tm_, int(wk[i])))
        if s_last is None: continue
        covered[i] = True
        f_, x_, s_, qb_, imp_ = [], [], [], [], []
        for w in evw:
            f, tw = gl[w]; qb = starter.get((Y, tw, w)) if tw else None
            ri = rowof.get((name[i], pos[i], Y, w)); imp_.append(implied[ri] if ri is not None else np.nan)
            f_.append(f); x_.append(gx.get((name[i], pos[i], Y, w), np.nan)); s_.append(gsn.get((name[i], pos[i], Y, w), np.nan)); qb_.append(qb)
        offL = np.array([q is not None and q != s_last for q in qb_]); offA = np.array([q is not None and s_act is not None and q != s_act for q in qb_])
        off_r[i] = offL.any(); off_act[i] = offA.any()
        new_qb[i] = sum(1 for q in qb_ if q == s_last) <= 1
        # same-QB games last season (and two seasons back) for the expected starter
        hp = []
        for Yp in (Y - 1, Y - 2):
            pk = (name[i], pos[i], Yp)
            if pk in games:
                for w, (f, tw) in games[pk][2].items():
                    if tw and starter.get((Yp, tw, w)) == s_last: hp.append(f)
        same_hist[i] = len(hp) >= 4
        qn = qclay(Y, s_last); qg = np.array([qclay(Y, q) if q else qn for q in qb_])
        EV[i] = dict(f=np.array(f_), x=np.array(x_, float), s=np.array(s_, float), offL=offL, offA=offA, qratio=qn / qg, imp=np.array(imp_, float), imp_now=implied[i], same=np.array(hp, float))
    P(f"rows covered {int(covered.sum()):,}; WR/TE with 1+ off-QB game {int((covered & off_r & np.isin(pos, ('WR','TE'))).sum()):,}; new starter (<= 1 prior start) {int((covered & new_qb & np.isin(pos, ('WR','TE'))).sum()):,}; with 4+ same-QB games in the prior two seasons {int((covered & same_hist & np.isin(pos, ('WR','TE'))).sum()):,}; off-QB rows that also have same-QB history {int((covered & off_r & same_hist & np.isin(pos, ('WR','TE'))).sum()):,}")

    # targets / grading (as the fill-in harness)
    seqn = defaultdict(list)
    for i in range(n):
        if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ix in seqn.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(X["layers"][ix], 0.5, 1.8)
        for a, i in enumerate(ix): nfut[i] = len(ix) - a; Tr[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    ramp = np.clip((nfut - 1.5) / np.maximum(nfut, 1), 0, 1); tilt = 1 - X["tilt_e"] * ramp * X["z"]; ctx0 = np.nan_to_num(ctx, nan=1.0)
    okN = (g >= 1) & ~final & ~X["inh"]; okR1 = (g >= 1) & (g <= 10) & ~np.isnan(Tr) & ~X["inh"]; okR4 = okR1 & (nfut >= 4)
    TG = {"next": ("NEXT GAME", act, okN, X["chain"]), "ros4": ("REST OF SEASON, 4+ games left", Tr, okR4, ctx0 * tilt), "ros1": ("REST OF SEASON, no survivor filter", Tr, okR1, ctx0 * tilt)}
    KEYS = ("next", "ros4", "ros1")
    def predict(key, ppg=None, ge=None, xf=None, sn=None):
        _, T, ok, mult = TG[key]
        b, lk = QI.live_base(X, X["ppg"] if ppg is None else ppg, g.astype(float) if ge is None else ge, X["xfp"] if xf is None else xf, X["snap"] if sn is None else sn)
        return np.maximum(0.0, b * mult + lk)
    BASE = {k: predict(k) for k in KEYS}
    RECV = np.isin(pos, ("WR", "TE"))
    def mse(pred, T, m):
        d_ = pred[m] - T[m]; return float(np.mean(d_ * d_)) if m.any() else np.nan
    def wmse(pred, T, m): return float(np.average((pred[m] - T[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    def cell(key, pred, m, yrs=YEARS, minrows=8):
        _, T, ok, _ = TG[key]; base = BASE[key]; m = m & ok & np.isin(year, list(yrs))
        if m.sum() < 30: return f"{'n/a (n' + str(int(m.sum())) + ')':>18s}"
        if np.abs(pred[m] - base[m]).max() < 1e-12: return f"{'no change n' + str(int(m.sum())):>18s}"
        ys = [y for y in yrs if (m & (year == y)).sum() >= minrows]
        wins = sum(1 for y in ys if mse(pred, T, m & (year == y)) < mse(base, T, m & (year == y)) - 1e-12)
        return f"{100*(mse(pred, T, m)/mse(base, T, m)-1):+6.2f}% ({wins}/{len(ys)}) n{int(m.sum())}"
    def board(key, pred, yrs=YEARS):
        _, T, ok, _ = TG[key]; base = BASE[key]; m = ok & top150 & np.isin(year, list(yrs))
        return f"board {100*(wmse(pred, T, m)/wmse(base, T, m)-1):+.3f}%"

    # ---------------- variants
    def rescale(scope, fn, usage=True):
        """fn(e) -> per-game multiplier array on the points (and xFP) of the evidence games"""
        ppg = X["ppg"].copy(); xf = X["xfp"].copy()
        for i in np.where(scope & covered)[0]:
            e = EV[i]; mlt = fn(e)
            if mlt is None or np.allclose(mlt, 1.0): continue
            ppg[i] = max(0.0, float((e["f"] * mlt).mean()))
            if usage:
                v = e["x"]; k = ~np.isnan(v)
                if k.sum() and not np.isnan(xf[i]) and xf[i] > 1e-9: xf[i] = xf[i] * float((v[k] * mlt[k]).mean() / max(v[k].mean(), 1e-9))
        return dict(ppg=ppg, xf=xf)
    def add_hist(scope, kgame, with_v=None):
        """same-QB prior-season games join the evidence at weight kgame each (points only; game count grows)"""
        base_ = with_v or {}
        ppg = base_.get("ppg", X["ppg"]).copy(); ge = g.astype(float).copy(); xf = base_.get("xf", X["xfp"]).copy()
        for i in np.where(scope & covered & same_hist)[0]:
            e = EV[i]; hp = e["same"]; k = kgame * len(hp)
            ppg[i] = max(0.0, (ppg[i] * g[i] + kgame * hp.sum()) / (g[i] + k)); ge[i] = g[i] + k
        return dict(ppg=ppg, ge=ge, xf=xf)
    def qfn(b, which):
        def f(e):
            r = np.clip(e["qratio"], 0.6, 1.6) ** b
            return np.where(e[which], r, 1.0) if which else r
        return f
    def vfn(b, which, up_only=False):
        def f(e):
            if np.isnan(e["imp_now"]): return None
            r = np.where(np.isnan(e["imp"]), 1.0, e["imp_now"] / np.maximum(e["imp"], 10.0)); r = np.clip(r, 0.6, 1.6)
            if up_only: r = np.where(r >= 1.10, r, 1.0)
            r = r ** b
            return np.where(e[which], r, 1.0) if which else r
        return f
    offR = covered & off_r & RECV; offRA = covered & off_act & RECV; allR = covered & RECV & (g >= 1); histR = covered & same_hist & RECV
    FAMS = [("V1 QB-quality ratio (Clay QB pts/g), off-QB games", offR, {f"b {b}": lambda b=b: rescale(RECV, qfn(b, "offL")) for b in (0.25, 0.5, 0.75, 1.0)}),
            ("V1 QB-quality ratio, ACTUAL starter (oracle)", offRA, {f"b {b}": lambda b=b: rescale(RECV, qfn(b, "offA")) for b in (0.5, 1.0)}),
            ("V2 team implied-total ratio, off-QB games", offR, {f"b {b}": lambda b=b: rescale(RECV, vfn(b, "offL")) for b in (0.25, 0.5, 0.75, 1.0)}),
            ("V2 team implied-total ratio, EVERY game (Vegas-cleaned evidence)", allR, {f"b {b}": lambda b=b: rescale(RECV, vfn(b, None)) for b in (0.25, 0.5, 1.0)}),
            ("V2 team re-rated UP 10%+ since the game, every game", allR, {f"b {b}": lambda b=b: rescale(RECV, vfn(b, None, up_only=True)) for b in (0.5, 1.0)}),
            ("V2 team re-rated UP 10%+, off-QB games only", offR, {f"b {b}": lambda b=b: rescale(RECV, vfn(b, "offL", up_only=True)) for b in (0.5, 1.0)}),
            ("V3 same-QB prior-season games join the evidence", histR, {f"k {k}": lambda k=k: add_hist(RECV, k) for k in (0.25, 0.5, 1.0)}),
            ("V3 same-QB history, off-QB rows only", offR & histR, {f"k {k}": lambda k=k: add_hist(RECV & off_r, k) for k in (0.5, 1.0)}),
            ("V3 same-QB history, NEW starter rows only (<= 1 prior start)", covered & new_qb & same_hist & RECV, {f"k {k}": lambda k=k: add_hist(RECV & new_qb, k) for k in (0.5, 1.0)}),
            ("V4 team-total ratio b .5 on off-QB games + same-QB history k .5", offR, {"both": lambda: add_hist(RECV & off_r, 0.5, rescale(RECV, vfn(0.5, "offL")))})]
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    for title, rows_m, fam in FAMS:
        P(f"\n=== {title} ===")
        V = {k: f() for k, f in fam.items()}
        for key in KEYS:
            _, T, ok, _ = TG[key]; b0 = BASE[key]; tm = rows_m & ok
            if tm.sum() < 60: P(f"  {TG[key][0]}: too few rows ({int(tm.sum())})"); continue
            preds = {"off": b0, **{k: predict(key, **v) for k, v in V.items()}}; names = list(preds)
            pick = lambda yrs: min(names, key=lambda k: mse(preds[k], T, tm & np.isin(year, yrs)))
            def run(folds):
                wins = 0; picks = []; pr = b0.copy()
                for tr_, te in folds:
                    k = pick(tr_); picks.append(k); m = year == te; pr[m] = preds[k][m]; wins += mse(preds[k], T, tm & m) < mse(b0, T, tm & m) - 1e-12
                tem = np.isin(year, [te for _, te in folds])
                return pr, 100 * (mse(pr, T, tm & tem) / mse(b0, T, tm & tem) - 1), 100 * (wmse(pr, T, ok & top150 & tem) / wmse(b0, T, ok & top150 & tem) - 1), wins, picks
            lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
            okk = best != "off" and lo[1] < -0.3 and lo[3] >= 5 and fw[1] < 0 and fw[3] >= 3 and lo[2] <= 0.02
            P(f"  {TG[key][0]}  rows {int(tm.sum()):,}  actual/live {T[tm].sum()/b0[tm].sum():.3f}")
            P("    fixed: " + "  ".join(f"{k}: {cell(key, preds[k], tm).strip()}" for k in names[1:]))
            P(f"    WR {cell(key, preds[best], tm & (pos == 'WR')).strip()} | TE {cell(key, preds[best], tm & (pos == 'TE')).strip()} | ADP<=60 {cell(key, preds[best], tm & (adpx <= 60)).strip()} | 61-150 {cell(key, preds[best], tm & (adpx > 60) & (adpx <= 150)).strip()}  (best fixed {best})")
            P(f"    LOYO {lo[1]:+.2f}% {lo[3]}/7 | {board(key, lo[0])} | picks {lo[4]}")
            P(f"    FWD  {fw[1]:+.2f}% {fw[3]}/4 | picks {fw[4]}")
            P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
    # the London-type rows: new starter with same-QB history - what did the actual do vs the live number?
    P("\n=== LONDON-TYPE ROWS: WR/TE whose expected starter has <= 1 start this season AND 4+ games with him in the prior two seasons ===")
    m = covered & new_qb & same_hist & RECV & okN
    if m.sum():
        sh = np.array([EV[i]["same"].mean() if EV[i] is not None and len(EV[i]["same"]) else np.nan for i in range(n)])
        P(f"    n {int(m.sum())} | actual {act[m].mean():.2f} | live {BASE['next'][m].mean():.2f} | this-season ppg {X['ppg'][m].mean():.2f} | same-QB history ppg {np.nanmean(sh[m]):.2f} | act/live {act[m].sum()/BASE['next'][m].sum():.3f}")
        hi = m & (sh > X["ppg"] * 1.2); lo_ = m & (sh < X["ppg"] * 0.8)
        for lab, mm in (("same-QB history 20%+ ABOVE this season", hi), ("same-QB history 20%+ BELOW this season", lo_)):
            if mm.sum() >= 10: P(f"    {lab}: n {int(mm.sum())} actual {act[mm].mean():.2f} live {BASE['next'][mm].mean():.2f} history {np.nanmean(sh[mm]):.2f} -> act/live {act[mm].sum()/BASE['next'][mm].sum():.3f}")
    P("\nLimitations: QB quality = Clay's preseason QB number (not his play this season); team implied totals only where the context row exists; starter = top passer of the game.")
    LOG.close()


if __name__ == "__main__":
    main()
