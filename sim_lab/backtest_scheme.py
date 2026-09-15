#!/usr/bin/env python3
"""
SCHEME MATCHUP BACKTEST (2026-09-15) - Jack: "backtest the whole algo or look for
correlation with everything we are building in 2025 and even previous years ...
we could really be on to something and get a massive edge".

Every scheme/alignment interaction the ZONES cards now show, graded the same way
as every shipped layer: multiplier on top of the shipped weekly base (P=5 blend x
Vegas x in-season FPA, bt_common.iter_samples) on QB/RB/WR/TE player-weeks
2019-2025, leave-one-year-out MSE. Inputs are the PFF Premium weekly facets
(pbp_cache/pff/weekly/pff_<facet>_<yr>_w<N>.csv, pulled once for 2019-2025),
aggregated WALK-FORWARD: for week W only weeks < W of that season count, blended
with the prior season's full profile (defense K=4 games, player K=200 routes /
100 carries / 200 dropbacks - the same blend build_scheme.py ships).

Candidates (each = one multiplier family, flagged rows or continuous):
  R1  receiver coverage fit: expected YPRR vs THIS opponent's man/zone mix
      (opp man% x own man YPRR + zone% x own zone YPRR) over the receiver's own
      overall YPRR -> ratio^k
  R2  man-beater flag x man-heavy D / zone-beater x zone-heavy D (GOOD SPOT rows)
      and the TOUGH SPOT rows
  R3  slot receiver x D that bleeds slot yards
  B1  RB lane fit: player lane mix x D per-lane ypc allowed ratio (PFF lanes)
  B2  RB yards-after-contact style x D yco allowed; MTF back x D missed-tackle rate
  B3  gap back x D gap-run ypc allowed? (not available - PFF has no gap/zone
      yardage split for defenses) -> gap share faced only, as a funnel
  Q1  QB pressure fit: expected grade vs THIS D's pressure rate (p x pGr +
      (1-p) x nGr) relative to own mix -> k
  Q2  QB vs blitz-heavy D: own blitz YPA split x D blitz rate
  D1  defense identity levels as direct docks/boosts for the position (man rate
      on WR/TE, blitz rate on RB receiving, pressure on QB - the shipped soft-rush
      boost is already in the base as pbp proxy, so this tests PFF pressure)
  P   persistence table: early-season (weeks 1-4) vs rest-of-season and YoY r
      for every defense metric, so the cards' "identity vs noise" labels are
      data, not opinion.

Ship bar (README): <= -0.3% LOYO MSE with >= 5/7 years better, or a flagged-row
effect on a rare flag. Log: scheme_backtest.log.
"""
import io, json, os, re, sys, math
from collections import defaultdict
import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B
from bt_common import iter_samples, to_arrays, bucket_table, loyo_flag, POS4
from backtest_target_area import loyo, mse
import build_scheme as BS

YEARS = list(range(2019, 2026))
K_DEF_G, K_REC, K_RB, K_QB = 4, 200, 100, 200
LOG = open(os.path.join(HERE, "scheme_backtest.log"), "w", encoding="utf-8")
def P(*a):
    s = " ".join(str(x) for x in a); print(s); LOG.write(s + "\n"); LOG.flush()


# ---------------------------------------------------------------- weekly frames
def frames(Y):
    F = BS.load_all(Y, "receiving_summary" if Y != 2026 else "receiving")
    return F, BS.opp_map(Y)


def season_profiles(Y):
    """Full-season profiles (the prior for Y+1)."""
    F, opp = frames(Y)
    agg = BS.aggregate(F, opp)
    if agg is None: return None
    DEF, OFF, REC, RB, QB, LG, weeks = agg
    return {"def": DEF, "rec": REC, "rb": RB, "qb": QB, "lg": LG}


def walk_forward(Y):
    """{wk: aggregate of weeks < wk} for wk 2..18 (wk 1 -> None = prior only)."""
    F, opp = frames(Y)
    if all(v is None for v in F.values()): return {}
    out = {}
    wks = sorted(set().union(*[set(int(w) for w in d.week.unique()) for d in F.values() if d is not None]))
    for wk in range(2, max(wks) + 2):
        Fw = {k: (None if d is None else d[d.week < wk]) for k, d in F.items()}
        agg = BS.aggregate(Fw, opp)
        if agg is None: continue
        DEF, OFF, REC, RB, QB, LG, _ = agg
        out[wk] = {"def": DEF, "rec": REC, "rb": RB, "qb": QB, "lg": LG}
    return out


# ---------------------------------------------------------------- blends (mirror app.js)
def blend_def(cur, pri, key, sub=None):
    def g(d):
        if not d: return None
        v = d.get(sub, {}).get(key) if sub else d.get(key)
        return v
    c, p = g(cur), g(pri)
    if c is None and p is None: return None
    if c is None: return p
    if p is None: return c
    n = cur.get("g", 0)
    return (n * c + K_DEF_G * p) / (n + K_DEF_G)


def blend_counts(cur, pri, keys, volkey, K):
    if not cur and not pri: return None
    out = {}
    pr = pri.get(volkey, 0) if pri else 0
    f = min(1.0, K / pr) if pr else 0.0
    for k in keys:
        out[k] = (cur.get(k, 0) if cur else 0) + (pri.get(k, 0) if pri else 0) * f
    out["_f"] = f; out["_cur"] = cur.get(volkey, 0) if cur else 0
    return out


REC_KEYS = ["mR", "zR", "mT", "zT", "mY", "zY", "sl", "wd", "il", "scT"]
RB_KEYS = ["att", "yds", "gap", "zone", "yco", "exp", "mtf"]
QB_KEYS = ["db", "bDb", "pDb", "pAtt", "pY", "nAtt", "nY", "bAtt", "bY", "nbAtt", "nbY"]


def rec_prof(cur, pri):
    b = blend_counts(cur, pri, REC_KEYS, "routes", K_REC) if (cur or pri) else None
    if not b: return None
    # volkey for receivers = mR+zR
    pr = (pri["mR"] + pri["zR"]) if pri else 0
    f = min(1.0, K_REC / pr) if pr else 0.0
    out = {k: (cur.get(k, 0) if cur else 0) + (pri.get(k, 0) if pri else 0) * f for k in REC_KEYS}
    R = out["mR"] + out["zR"]
    if R < 30: return None
    out["routes"] = R; out["manSeen"] = out["mR"] / R
    out["mYprr"] = out["mY"] / out["mR"] if out["mR"] >= 20 else None
    out["zYprr"] = out["zY"] / out["zR"] if out["zR"] >= 20 else None
    out["yprr"] = (out["mY"] + out["zY"]) / R
    al = out["sl"] + out["wd"] + out["il"]; out["slot"] = out["sl"] / al if al else None
    return out


def rb_prof(cur, pri, lanes_cur, lanes_pri):
    pr = pri["att"] if pri else 0
    f = min(1.0, K_RB / pr) if pr else 0.0
    out = {k: (cur.get(k, 0) if cur else 0) + (pri.get(k, 0) if pri else 0) * f for k in RB_KEYS}
    if out["att"] < 20: return None
    out["ypc"] = out["yds"] / out["att"]; out["ycoA"] = out["yco"] / out["att"]; out["mtfA"] = out["mtf"] / out["att"]
    gz = out["gap"] + out["zone"]; out["gapS"] = out["gap"] / gz if gz else None
    ln = {l: [0.0, 0.0] for l in BS.LANES}
    for src, w in ((lanes_cur, 1.0), (lanes_pri, f)):
        if src:
            for l in BS.LANES:
                v = src.get(l, [0, 0]); ln[l][0] += v[0] * w; ln[l][1] += v[1] * w
    la = sum(v[0] for v in ln.values())
    out["lanes"] = {l: v[0] / la for l, v in ln.items()} if la >= 20 else None
    return out


def qb_prof(cur, pri):
    pr = pri["db"] if pri else 0
    f = min(1.0, K_QB / pr) if pr else 0.0
    out = {k: (cur.get(k, 0) if cur else 0) + (pri.get(k, 0) if pri else 0) * f for k in QB_KEYS}
    if out["db"] < 60: return None
    def wg(k, wk_):
        wc = cur.get(wk_, 0) if cur else 0; wp = (pri.get(wk_, 0) if pri else 0) * f
        vc = cur.get(k) if cur else None; vp = pri.get(k) if pri else None
        if vc is not None and vp is not None and wc + wp: return (vc * wc + vp * wp) / (wc + wp)
        return vc if vc is not None else vp
    out["pGr"] = wg("pGr", "pDb"); out["nGr"] = wg("nGr", "db")
    out["prs"] = out["pDb"] / out["db"]; out["blitz"] = out["bDb"] / out["db"]
    out["pYpa"] = out["pY"] / out["pAtt"] if out["pAtt"] >= 20 else None
    out["nYpa"] = out["nY"] / out["nAtt"] if out["nAtt"] >= 20 else None
    out["bYpa"] = out["bY"] / out["bAtt"] if out["bAtt"] >= 20 else None
    out["nbYpa"] = out["nbY"] / out["nbAtt"] if out["nbAtt"] >= 20 else None
    return out


def lg_of(cur, pri, key, sub=None):
    for src in (cur, pri):
        if src and src.get("lg"):
            v = src["lg"].get(sub, {}).get(key) if sub else src["lg"].get(key)
            if v is not None: return v
    return None


# ---------------------------------------------------------------- main
def main():
    P("loading PFF weekly facets 2018-2025 (walk-forward per week)...")
    prior_of = {}
    wf = {}
    for Y in range(2018, 2026):
        sp = season_profiles(Y)
        prior_of[Y + 1] = sp
        P(f"  {Y}: season profiles {'ok' if sp else 'MISSING'}" + (f" ({len(sp['def'])} D, {len(sp['rec'])} rec, {len(sp['rb'])} rb, {len(sp['qb'])} qb)" if sp else ""))
    for Y in YEARS:
        wf[Y] = walk_forward(Y)
        P(f"  {Y}: walk-forward weeks {min(wf[Y]) if wf[Y] else '-'}..{max(wf[Y]) if wf[Y] else '-'}")

    P("\nloading base samples (bt_common)...")
    S = iter_samples(POS4)
    A = to_arrays(S)
    n = len(S)
    P(f"  {n} player-weeks")

    # per-sample features
    feat = defaultdict(lambda: np.full(n, np.nan))
    flags = defaultdict(lambda: np.zeros(n, dtype=bool))
    for i, s in enumerate(S):
        Y, wk, pos, opp, team, nm = s["year"], s["wk"], s["pos"], s["opp"], s["team"], B.cal.norm(s["name"])
        cur = wf.get(Y, {}).get(wk); pri = prior_of.get(Y)
        if cur is None and pri is None: continue
        dcur = cur["def"].get(opp) if cur else None; dpri = pri["def"].get(opp) if pri else None
        if dcur is None and dpri is None: continue
        man = blend_def(dcur, dpri, "man"); blitz = blend_def(dcur, dpri, "blitz"); prs = blend_def(dcur, dpri, "prs")
        slotYd = blend_def(dcur, dpri, "slotYd"); mtRate = blend_def(dcur, dpri, "mtRate")
        yco_d = blend_def(dcur, dpri, "yco", "run"); ypc_d = blend_def(dcur, dpri, "ypc", "run")
        lg_man = lg_of(cur, pri, "man"); lg_blitz = lg_of(cur, pri, "blitz"); lg_prs = lg_of(cur, pri, "prs")
        lg_slot = lg_of(cur, pri, "slotYd"); lg_mt = lg_of(cur, pri, "mtRate"); lg_yco = lg_of(cur, pri, "yco", "run"); lg_ypc = lg_of(cur, pri, "ypc", "run")
        if man is not None: feat["dman"][i] = man
        if blitz is not None: feat["dblitz"][i] = blitz
        if prs is not None: feat["dprs"][i] = prs
        if man is not None and lg_man: feat["dman_rel"][i] = man - lg_man
        if blitz is not None and lg_blitz: feat["dblitz_rel"][i] = blitz - lg_blitz
        if prs is not None and lg_prs: feat["dprs_rel"][i] = prs - lg_prs
        if pos in ("WR", "TE", "RB"):
            rp = rec_prof(cur["rec"].get(nm) if cur else None, pri["rec"].get(nm) if pri else None)
            if rp and man is not None and rp["mYprr"] is not None and rp["zYprr"] is not None and rp["yprr"] > 0:
                exp_yprr = man * rp["mYprr"] + (1 - man) * rp["zYprr"]
                own_mix = rp["manSeen"] * rp["mYprr"] + (1 - rp["manSeen"]) * rp["zYprr"]
                feat["r1"][i] = exp_yprr / own_mix if own_mix > 0 else np.nan
                beater = "man" if rp["mYprr"] >= rp["zYprr"] * 1.35 else ("zone" if rp["zYprr"] >= rp["mYprr"] * 1.35 else None)
                if beater and lg_man is not None:
                    hi = man >= lg_man + 0.10; lo = man <= lg_man - 0.10
                    flags["r2_good"][i] = (beater == "man" and hi) or (beater == "zone" and lo)
                    flags["r2_bad"][i] = (beater == "man" and lo) or (beater == "zone" and hi)
            if rp and rp["slot"] is not None and slotYd is not None and lg_slot:
                flags["r3_slot_leak"][i] = rp["slot"] >= 0.55 and slotYd >= lg_slot + 0.10
                flags["r3_slot_tight"][i] = rp["slot"] >= 0.55 and slotYd <= lg_slot - 0.10
        if pos == "RB":
            lc = cur["rb"].get(nm, {}).get("lanes") if cur and nm in cur["rb"] else None
            lp = pri["rb"].get(nm, {}).get("lanes") if pri and nm in pri["rb"] else None
            bp = rb_prof(cur["rb"].get(nm) if cur else None, pri["rb"].get(nm) if pri else None, lc, lp)
            if bp:
                drun_c = dcur.get("run") if dcur else None; drun_p = dpri.get("run") if dpri else None
                # lane fit: sum_l share_l x (D ypc_l / lg ypc_l), D lanes blended by carries
                lanes_d = {l: [0.0, 0.0] for l in BS.LANES}
                for src, w in ((drun_c, 1.0), (drun_p, 1.0)):
                    if src and src.get("lanes"):
                        for l in BS.LANES:
                            v = src["lanes"].get(l, [0, 0]); lanes_d[l][0] += v[0] * w; lanes_d[l][1] += v[1] * w
                lgl = lg_of(cur, pri, "laneYpc")
                if bp["lanes"] and lgl and sum(v[0] for v in lanes_d.values()) >= 60:
                    fit = 0.0; tot = 0.0
                    for l in BS.LANES:
                        a, y = lanes_d[l]
                        if a >= 8 and lgl.get(l):
                            ratio = (y / a) / lgl[l]; ratio = (a * ratio + 40) / (a + 40)   # shrink K=40
                            fit += bp["lanes"][l] * ratio; tot += bp["lanes"][l]
                    if tot > 0.5: feat["b1"][i] = fit / tot
                if yco_d is not None and lg_yco:
                    flags["b2_yco_good"][i] = bp["ycoA"] >= 3.4 and yco_d >= lg_yco + 0.4
                    flags["b2_yco_bad"][i] = bp["ycoA"] >= 3.4 and yco_d <= lg_yco - 0.4
                if mtRate is not None and lg_mt:
                    flags["b2_mtf_good"][i] = bp["mtfA"] >= 0.24 and mtRate >= lg_mt + 0.03
                if ypc_d is not None and lg_ypc:
                    feat["dypc_rel"][i] = ypc_d / lg_ypc
        if pos == "QB":
            qp = qb_prof(cur["qb"].get(nm) if cur else None, pri["qb"].get(nm) if pri else None)
            if qp and prs is not None and qp["pGr"] is not None and qp["nGr"] is not None:
                exp_gr = prs * qp["pGr"] + (1 - prs) * qp["nGr"]
                own = qp["prs"] * qp["pGr"] + (1 - qp["prs"]) * qp["nGr"]
                feat["q1"][i] = exp_gr / own if own > 0 else np.nan
                if lg_prs is not None:
                    fragile = (qp["nGr"] - qp["pGr"]) >= 30
                    flags["q1_bad"][i] = fragile and prs >= lg_prs + 0.06
                    flags["q1_good"][i] = fragile and prs <= lg_prs - 0.06
            if qp and blitz is not None and qp["bYpa"] is not None and qp["nbYpa"] is not None and lg_blitz is not None:
                flags["q2_good"][i] = qp["bYpa"] >= qp["nbYpa"] + 1.0 and blitz >= lg_blitz + 0.08
                flags["q2_bad"][i] = qp["bYpa"] <= qp["nbYpa"] - 1.0 and blitz >= lg_blitz + 0.08
                feat["q2"][i] = (qp["bYpa"] - qp["nbYpa"]) * (blitz - lg_blitz)

    years = YEARS
    cover = {k: int(np.isfinite(v).sum()) for k, v in feat.items()}
    P(f"\nfeature coverage: {cover}")
    P("flag counts: " + ", ".join(f"{k} {int(v.sum())}" for k, v in flags.items()))

    # ---- bucket tables (actual / shipped by feature tercile) ----
    def terciles(name, v, posmask=None):
        m = np.isfinite(v) if posmask is None else (np.isfinite(v) & posmask)
        if m.sum() < 300: P(f"  {name}: n={m.sum()} too few"); return
        q = np.nanquantile(v[m], [1 / 3, 2 / 3])
        sets = [(f"{name} low (<{q[0]:.3f})", m & (v <= q[0])), (f"{name} mid", m & (v > q[0]) & (v < q[1])), (f"{name} high (>{q[1]:.3f})", m & (v >= q[1]))]
        bucket_table(A, sets, name)
        r = np.corrcoef(v[m], (A["act"] / A["shipped"])[m])[0, 1]
        P(f"  corr({name}, act/shipped) = {r:+.3f} (n={m.sum()})")
    recm = np.isin(A["pos"], ["WR", "TE"]); rbm = A["pos"] == "RB"; qbm = A["pos"] == "QB"
    terciles("R1 coverage-fit ratio (WR/TE)", feat["r1"], recm)
    terciles("R1 coverage-fit ratio (RB)", feat["r1"], rbm)
    terciles("B1 lane fit (RB)", feat["b1"], rbm)
    terciles("D run ypc allowed rel (RB)", feat["dypc_rel"], rbm)
    terciles("Q1 pressure-fit ratio (QB)", feat["q1"], qbm)
    terciles("Q2 blitz split x D blitz (QB)", feat["q2"], qbm)
    terciles("D man rate (WR/TE)", feat["dman_rel"], recm)
    terciles("D man rate (RB)", feat["dman_rel"], rbm)
    terciles("D blitz rate (RB)", feat["dblitz_rel"], rbm)
    terciles("D blitz rate (WR/TE)", feat["dblitz_rel"], recm)
    terciles("D pressure rate PFF (QB)", feat["dprs_rel"], qbm)
    terciles("D pressure rate PFF (WR/TE)", feat["dprs_rel"], recm)
    bucket_table(A, [(k, v) for k, v in flags.items()], "flagged rows")

    # ---- LOYO: continuous multipliers ----
    P("\n=== LOYO continuous multipliers (shipped x ratio^k, missing -> 1) ===")
    def cont(name, v, posmask, grid=(0.0, 0.25, 0.5, 0.75, 1.0, -0.25)):
        m = np.isfinite(v) & posmask
        if m.sum() < 300: P(f"  {name}: too few ({m.sum()})"); return
        pm = posmask
        Ssub = {"year": A["year"][pm], "act": A["act"][pm]}; ship = A["shipped"][pm]; vv = np.where(np.isfinite(v[pm]), v[pm], 1.0)
        vv = np.clip(vv, 0.5, 2.0)
        loyo(Ssub, years, list(grid), lambda k: ship * vv ** k, f"{name} (n={m.sum()} of {pm.sum()})")
    cont("R1 coverage fit WR/TE", feat["r1"], recm)
    cont("R1 coverage fit RB", feat["r1"], rbm)
    cont("B1 lane fit RB", feat["b1"], rbm)
    cont("D ypc allowed rel RB", feat["dypc_rel"], rbm)
    cont("Q1 pressure fit QB", feat["q1"], qbm)
    # defense identity levels as linear docks: shipped x (1 + k x rel)
    def lin(name, v, posmask, grid=(0.0, 0.25, 0.5, 1.0, -0.25, -0.5, -1.0)):
        m = np.isfinite(v) & posmask
        if m.sum() < 300: P(f"  {name}: too few ({m.sum()})"); return
        pm = posmask
        Ssub = {"year": A["year"][pm], "act": A["act"][pm]}; ship = A["shipped"][pm]; vv = np.where(np.isfinite(v[pm]), v[pm], 0.0)
        loyo(Ssub, years, list(grid), lambda k: ship * np.clip(1 + k * vv, 0.7, 1.3), f"{name} (n={m.sum()})")
    P("\n=== LOYO defense identity levels (shipped x (1 + k x (rate - lg))) ===")
    lin("D man rate -> WR/TE", feat["dman_rel"], recm)
    lin("D man rate -> RB", feat["dman_rel"], rbm)
    lin("D blitz rate -> RB", feat["dblitz_rel"], rbm)
    lin("D blitz rate -> WR/TE", feat["dblitz_rel"], recm)
    lin("D blitz rate -> QB", feat["dblitz_rel"], qbm)
    lin("D PFF pressure rate -> QB", feat["dprs_rel"], qbm)
    lin("D PFF pressure rate -> WR/TE", feat["dprs_rel"], recm)
    lin("Q2 blitz split x D blitz -> QB", feat["q2"], qbm, grid=(0.0, 0.5, 1.0, 2.0, -0.5))

    P("\n=== LOYO flagged-row multipliers ===")
    for k, v in flags.items():
        pos = "QB" if k.startswith("q") else ("RB" if k.startswith("b") else None)
        if pos: loyo_flag(A, years, v, k, pos=pos)
        else:
            loyo_flag(A, years, v & recm, k + " WR/TE", pos=None)
            if (v & rbm).sum() >= 60: loyo_flag(A, years, v & rbm, k + " RB", pos=None)

    # ---- persistence of defense metrics: weeks 1-4 vs 5+ (same season) and YoY ----
    P("\n=== defense metric persistence (identity vs noise) ===")
    keys = BS.PERSIST_KEYS
    for key, sub in keys:
        e2l, yoy = [], []
        for Y in YEARS:
            F, opp = frames(Y)
            if all(v is None for v in F.values()): continue
            early = BS.aggregate({k: (None if d is None else d[d.week <= 4]) for k, d in F.items()}, opp)
            late = BS.aggregate({k: (None if d is None else d[d.week >= 5]) for k, d in F.items()}, opp)
            if early and late:
                for t, d in early[0].items():
                    a = (d.get(sub) or {}).get(key) if sub else d.get(key); l = late[0].get(t)
                    b = ((l.get(sub) or {}).get(key) if sub else l.get(key)) if l else None
                    if a is not None and b is not None: e2l.append((a, b))
            sp, sq = prior_of.get(Y), prior_of.get(Y + 1)   # Y-1 full vs Y full
            if sp and sq:
                for t, d in sq["def"].items():
                    p = sp["def"].get(t)
                    a = (d.get(sub) or {}).get(key) if sub else d.get(key)
                    b = ((p.get(sub) or {}).get(key) if sub else p.get(key)) if p else None
                    if a is not None and b is not None: yoy.append((a, b))
        P(f"  {(sub + '.' if sub else '') + key:12s} early(1-4)->late r {BS.pearson(e2l) if e2l else None} (n={len(e2l)}) | YoY r {BS.pearson(yoy) if yoy else None} (n={len(yoy)})")
    P("\ndone")


if __name__ == "__main__":
    main()
