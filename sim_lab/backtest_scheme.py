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

# (stdout re-wrapped by backtest_target_area on import - do not wrap here)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B
from bt_common import iter_samples, to_arrays, bucket_table, loyo_flag, POS4
from backtest_target_area import loyo, mse
import build_scheme as BS

YEARS = list(range(2019, 2026))
K_DEF_G, K_REC, K_RB, K_QB = 4, 200, 100, 200
LOG = open(os.path.join(HERE, "scheme_backtest.log"), "w", encoding="utf-8")


class _Tee:
    """stdout -> console + scheme_backtest.log, line-flushed (the harness's loyo() prints
    with plain print, and a redirected stdout is block-buffered otherwise)."""
    def __init__(self, a, b): self.a, self.b = a, b
    def write(self, t):
        self.a.write(t); self.b.write(t); self.a.flush(); self.b.flush()
    def flush(self):
        self.a.flush(); self.b.flush()


sys.stdout = _Tee(sys.stdout, LOG)
def P(*a):
    print(" ".join(str(x) for x in a))

RES = {"loyo": [], "persist": [], "buckets": [], "flags": {}, "coverage": {}, "n": 0}
BT_OUT = os.path.join(HERE, "data", "scheme_backtest.js")
SHIP_PCT, SHIP_WINS = -0.30, 5


def loyo2(S, years, grid, predfn, label, family, pos):
    """Same LOYO as backtest_target_area.loyo, but returns {best, pct, wins, picks} and records it."""
    act = S["act"]; per = {}
    for v in grid:
        pred = predfn(v)
        per[v] = {y: mse(pred[S["year"] == y], act[S["year"] == y]) for y in years if (S["year"] == y).any()}
    ys = [y for y in years if (S["year"] == y).any()]
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
    rec = {"label": label, "family": family, "pos": pos, "n": int(n), "best": float(pooled_best), "pct": round(pct, 3),
           "wins": int(wins), "years": len(ys), "picks": [float(p) for p in picks],
           "verdict": "PASS" if (pct <= SHIP_PCT and wins >= SHIP_WINS) else ("lean" if (pct <= -0.1 and wins >= 4) else "FAIL")}
    RES["loyo"].append(rec)
    return pooled_best, tot / n - base_mse


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
    season_of = {}
    for Y in range(2018, 2026):
        sp = season_profiles(Y)
        season_of[Y] = sp
        prior_of[Y + 1] = sp
        P(f"  {Y}: season profiles {'ok' if sp else 'MISSING'}" + (f" ({len(sp['def'])} D, {len(sp['rec'])} rec, {len(sp['rb'])} rb, {len(sp['qb'])} qb)" if sp else ""))
    # coach-aware DEFENSE priors: the prior for team T entering Y = last season under Y's
    # defensive playcaller (his previous team when he moved), per build_scheme.coach_prior
    coaches = BS.load_coaches()
    if coaches:
        modes = defaultdict(int)
        for Y in YEARS:
            if prior_of.get(Y) is None: continue
            newdef = {}
            for T in list(prior_of[Y]["def"].keys()) + [t for t in coaches.get(Y, {}) if t not in prior_of[Y]["def"]]:
                dp, src = BS.coach_prior("def", T, Y, season_of, coaches)
                if dp: newdef[T] = dict(dp, _src=src)
                modes[src.get("mode")] += 1
            prior_of[Y] = dict(prior_of[Y], **{"def": newdef, "defTeam": prior_of[Y]["def"]})
        P(f"  coach-aware defense priors: {dict(modes)} (coaches.json seasons {sorted(coaches)[0]}-{sorted(coaches)[-1]})")
    else:
        P("  coaches.json missing - team priors only")
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

    # ---- broad scan: every blended defense metric + player feature + cross terms ----
    DKEYS = [("man", None), ("blitz", None), ("prs", None), ("prwr", None), ("sBox", None), ("dbRush", None), ("mtRate", None),
             ("slotYd", None), ("screenTg", None), ("grCov", None), ("grRun", None), ("grPrsh", None), ("grDef", None),
             ("ypc", "run"), ("yco", "run"), ("gap", "run"), ("edge", "run"), ("exp", "run"), ("mtf", "run"), ("brk", "run")]
    for i, s_ in enumerate(S):
        Y, wk, pos, opp, nm = s_["year"], s_["wk"], s_["pos"], s_["opp"], B.cal.norm(s_["name"])
        cur = wf.get(Y, {}).get(wk); pri = prior_of.get(Y)
        dcur = cur["def"].get(opp) if cur else None; dpri = pri["def"].get(opp) if pri else None
        if dcur is None and dpri is None: continue
        for key, sub in DKEYS:
            v = blend_def(dcur, dpri, key, sub)
            lg = lg_of(cur, pri, key, sub)
            if v is not None and lg not in (None, 0):
                feat["D:" + (sub + "." if sub else "") + key][i] = v - lg if key.startswith("gr") or sub is None else v - lg
        if pos in ("WR", "TE", "RB"):
            rp = rec_prof(cur["rec"].get(nm) if cur else None, pri["rec"].get(nm) if pri else None)
            if rp:
                for k in ("manSeen", "mYprr", "zYprr", "yprr", "slot"):
                    if rp.get(k) is not None: feat["P:" + k][i] = rp[k]
                if rp.get("mYprr") is not None and rp.get("zYprr") is not None: feat["P:manMinusZoneYprr"][i] = rp["mYprr"] - rp["zYprr"]
        if pos == "RB":
            lc = cur["rb"].get(nm, {}).get("lanes") if cur and nm in cur["rb"] else None
            lp = pri["rb"].get(nm, {}).get("lanes") if pri and nm in pri["rb"] else None
            bp = rb_prof(cur["rb"].get(nm) if cur else None, pri["rb"].get(nm) if pri else None, lc, lp)
            if bp:
                for k in ("gapS", "ycoA", "mtfA", "ypc"):
                    if bp.get(k) is not None: feat["P:" + k][i] = bp[k]
                if bp.get("lanes"): feat["P:edge"][i] = bp["lanes"]["LE"] + bp["lanes"]["RE"]
        if pos == "QB":
            qp = qb_prof(cur["qb"].get(nm) if cur else None, pri["qb"].get(nm) if pri else None)
            if qp:
                for k in ("pGr", "nGr", "prs", "blitz", "pYpa", "nYpa", "bYpa", "nbYpa"):
                    if qp.get(k) is not None: feat["P:" + k][i] = qp[k]
                if qp.get("pGr") is not None and qp.get("nGr") is not None: feat["P:cleanMinusPrsGrade"][i] = qp["nGr"] - qp["pGr"]
                if qp.get("bYpa") is not None and qp.get("nbYpa") is not None: feat["P:blitzMinusNoBlitzYpa"][i] = qp["bYpa"] - qp["nbYpa"]
    years = YEARS
    resid = A["act"] / A["shipped"]
    RES["scan"] = []
    P("\n=== correlation scan: feature vs actual/shipped (per position; |r| ranked; cross = D metric x player feature) ===")
    for pos in POS4:
        pm = A["pos"] == pos
        rows = []
        dk = [k for k in feat if k.startswith("D:")]; pk = [k for k in feat if k.startswith("P:")]
        for k in dk + pk:
            v = feat[k]; m = pm & np.isfinite(v)
            if m.sum() < 300 or np.nanstd(v[m]) == 0: continue
            r = float(np.corrcoef(v[m], resid[m])[0, 1]); rows.append((k, r, int(m.sum())))
        for a in dk:
            for b in pk:
                v = feat[a] * feat[b]; m = pm & np.isfinite(v)
                if m.sum() < 300 or np.nanstd(v[m]) == 0: continue
                # partial: cross term residualised on its parts (so it is not just a proxy for either)
                X = np.column_stack([np.ones(m.sum()), feat[a][m], feat[b][m]])
                beta, *_ = np.linalg.lstsq(X, v[m], rcond=None); vx = v[m] - X @ beta
                if np.std(vx) == 0: continue
                r = float(np.corrcoef(vx, resid[m])[0, 1]); rows.append((a + " x " + b, r, int(m.sum())))
        rows.sort(key=lambda t: -abs(t[1]))
        P(f"  {pos}: {len(rows)} features/cross terms scanned; top 12 by |r|:")
        for k, r, n_ in rows[:12]:
            P(f"    {k:40s} r {r:+.3f}  n {n_}")
        RES["scan"].append({"pos": pos, "scanned": len(rows), "top": [{"k": k, "r": round(r, 3), "n": n_} for k, r, n_ in rows[:12]]})
    # LOYO on the top-3 cross/plain terms per position as linear slopes (the honest check on a scan)
    P("\n=== LOYO on the scan's top 3 per position (shipped x (1 + k x z), z = standardized feature) ===")
    for sc in RES["scan"]:
        pos = sc["pos"]; pm = A["pos"] == pos
        for t in sc["top"][:3]:
            k = t["k"]
            if " x " in k:
                a, b = k.split(" x "); v = feat[a] * feat[b]
            else:
                v = feat[k]
            m = pm & np.isfinite(v); z = np.zeros(pm.sum())
            zz = (v[pm] - np.nanmean(v[m])) / (np.nanstd(v[m]) or 1.0); z = np.where(np.isfinite(zz), np.clip(zz, -3, 3), 0.0)
            Ssub = {"year": A["year"][pm], "act": A["act"][pm]}; ship = A["shipped"][pm]
            sign = 1.0 if t["r"] >= 0 else -1.0
            loyo2(Ssub, years, [0.0, 0.01, 0.02, 0.04, -0.01, -0.02], lambda kk: ship * np.clip(1 + kk * sign * z, 0.7, 1.3), f"scan {pos} {k} (n={m.sum()})", "scan top (1 + k x z)", pos + " " + k)

    years = YEARS
    cover = {k: int(np.isfinite(v).sum()) for k, v in feat.items() if not k.startswith(("D:", "P:"))}
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
        RES["buckets"].append({"name": name, "n": int(m.sum()), "corr": round(float(r), 3),
                               "terciles": [round(float(A["act"][mm].mean() / A["shipped"][mm].mean()), 3) if mm.sum() else None for _, mm in sets]})
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
        loyo2(Ssub, years, list(grid), lambda k: ship * vv ** k, f"{name} (n={m.sum()} of {pm.sum()})", "continuous ratio^k", name)
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
        loyo2(Ssub, years, list(grid), lambda k: ship * np.clip(1 + k * vv, 0.7, 1.3), f"{name} (n={m.sum()})", "defense level (1 + k x rel)", name)
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
    def flag2(mask, label, pos=None, grid=(1.0, 0.97, 0.94, 0.91, 1.03, 1.06, 1.10)):
        if pos is not None:
            pm = A["pos"] == pos; Ssub = {"year": A["year"][pm], "act": A["act"][pm]}; ship = A["shipped"][pm]; mk = mask[pm]
        else:
            Ssub = {"year": A["year"], "act": A["act"]}; ship = A["shipped"]; mk = mask
        if mk.sum() < 60:
            P(f"  {label}: too few flagged rows ({mk.sum()})")
            RES["flags"][label] = {"n": int(mk.sum()), "ratio": round(float(A["act"][mask].mean() / A["shipped"][mask].mean()), 3) if mask.sum() else None, "verdict": "too few"}
            return
        loyo2(Ssub, years, list(grid), lambda m: np.where(mk, ship * m, ship), f"{label} (flagged n={mk.sum()})", "flagged rows x m", label)
        RES["flags"][label] = {"n": int(mk.sum()), "ratio": round(float(A["act"][mask].mean() / A["shipped"][mask].mean()), 3), "verdict": RES["loyo"][-1]["verdict"], "pct": RES["loyo"][-1]["pct"], "best": RES["loyo"][-1]["best"]}
    for k, v in flags.items():
        pos = "QB" if k.startswith("q") else ("RB" if k.startswith("b") else None)
        if pos: flag2(v, k, pos=pos)
        else:
            flag2(v & recm, k + " WR/TE")
            if (v & rbm).sum() >= 60: flag2(v & rbm, k + " RB")

    # ---- persistence of defense metrics: weeks 1-4 vs 5+ (same season) and YoY ----
    P("\n=== defense metric persistence (identity vs noise) ===")
    keys = BS.PERSIST_KEYS
    for key, sub in keys:
        e2l, yoy, yoy_same, yoy_new, yoy_moved = [], [], [], [], []
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
            sp, sq = season_of.get(Y - 1), season_of.get(Y)   # Y-1 full vs Y full, same franchise
            if sp and sq:
                for t, d in sq["def"].items():
                    p = sp["def"].get(t)
                    a = (d.get(sub) or {}).get(key) if sub else d.get(key)
                    b = ((p.get(sub) or {}).get(key) if sub else p.get(key)) if p else None
                    if a is not None and b is not None:
                        yoy.append((a, b))
                        if coaches:
                            same = coaches.get(Y, {}).get(t, {}).get("dcPlay") and coaches.get(Y, {}).get(t, {}).get("dcPlay") == coaches.get(Y - 1, {}).get(t, {}).get("dcPlay")
                            (yoy_same if same else yoy_new).append((a, b))
                            # coach-aware: the DC's own previous defense (wherever it was)
                            cp, src = BS.coach_prior("def", t, Y, season_of, coaches)
                            if cp and src.get("mode") == "coach":
                                c = (cp.get(sub) or {}).get(key) if sub else cp.get(key)
                                if c is not None: yoy_moved.append((a, c))
        extra = ""
        if coaches:
            extra = f" | same-DC r {BS.pearson(yoy_same)} (n={len(yoy_same)}) | new-DC vs old team r {BS.pearson(yoy_new)} (n={len(yoy_new)}) | new-DC vs HIS last D r {BS.pearson(yoy_moved)} (n={len(yoy_moved)})"
        P(f"  {(sub + '.' if sub else '') + key:12s} early(1-4)->late r {BS.pearson(e2l) if e2l else None} (n={len(e2l)}) | YoY r {BS.pearson(yoy) if yoy else None} (n={len(yoy)})" + extra)
        RES["persist"].append({"key": (sub + "." if sub else "") + key, "e2l": BS.pearson(e2l) if e2l else None, "nE2l": len(e2l),
                               "yoy": BS.pearson(yoy) if yoy else None, "nYoy": len(yoy),
                               "same": BS.pearson(yoy_same) if yoy_same else None, "nSame": len(yoy_same),
                               "newOld": BS.pearson(yoy_new) if yoy_new else None, "nNew": len(yoy_new),
                               "newHis": BS.pearson(yoy_moved) if yoy_moved else None, "nMoved": len(yoy_moved)})
    RES["n"] = int(n); RES["coverage"] = cover; RES["years"] = years
    RES["updated"] = __import__("time").strftime("%Y-%m-%d %H:%M")
    RES["bar"] = {"pct": SHIP_PCT, "wins": SHIP_WINS}
    passed = [r for r in RES["loyo"] if r["verdict"] == "PASS"]
    RES["summary"] = (f"{len(RES['loyo'])} interactions graded LOYO 2019-25 on {n} player-weeks; " +
                      (f"{len(passed)} pass the ship bar: " + ", ".join(r["pos"] for r in passed) if passed else "none pass the ship bar (<= -0.3% MSE with >= 5/7 years better)"))
    with open(BT_OUT, "w", encoding="utf-8") as f:
        f.write("// built by backtest_scheme.py - LOYO verdicts for every scheme interaction + defense metric persistence; shown on the ZONES tab\n")
        f.write("window.SIM_SCHEME_BT = "); json.dump(RES, f, separators=(",", ":")); f.write(";\n")
    P(f"wrote {BT_OUT}: {RES['summary']}")
    P("\ndone")


if __name__ == "__main__":
    main()
