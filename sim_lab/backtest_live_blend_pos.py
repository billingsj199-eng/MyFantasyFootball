#!/usr/bin/env python3
"""
LIVE BLEND: how strongly should this season's games count against the preseason number, by position?
(2026-10-05; research only - nothing in the engine is changed by this script.)

The live per-game base is  (P x Clay per game + g x evidence) / (P + g)  with P = JS_PRIOR_STRENGTH = 5 for every
position (engine.js jsBasePg). Two earlier findings were never applied: 09-17 (backtest_clay_blend_fix.py /
backtest_clay_tier.py: stronger prior only for ADP <= 60) and the 10-01 audit (tight ends react about twice too
fast). The engine has gained layers since, so both are re-tested here on a rebuild of the CURRENT live form:

  evidence   points per game; WR (game 1+) and TE (game 4+) mix in the usage level exactly as LIVE_USAGE does
             (c0 + c1 x xFP/g + c2 x route rate + c3 x snap share, weights .8/.8/.6/.6/.5/.3 and 0/.3)
  base       P blend with Clay per projected game, x rookie level (QB / RB 1.08), QB starter floor (k .70 under the
             top-32 mean), RB snap-volume mix (15% after 3 snap weeks)
  chain      Vegas x opponent (harness layers) x snap trend x banged-up x weather x vacated pool   [next game]
             mean of the Vegas x opponent layers over the games left, x the weeks-ahead QB attempt / TE pass-rate
             tilt (approximated: z of attempts per game / of team pass rate over expected)          [rest of season]
  td luck    + k x tdPts x (xTD - TD) / g x g / (5 + g) x (1 - usage weight)   (additive)
  NOT replayable: the player-prop anchor (lined players, current week only), the pecking-order dock, the
  availability curves, backup-QB inheritance (those rows are dropped).

Targets, both graded:  NEXT GAME (every player-week with 1+ games played, final week dropped) and REST OF SEASON
per game (checkpoint = entering a game with 1-10 games played; target = his average from that game on, final week
dropped) - with the "4+ games left" survivor filter AND without it. A rule is kept only if it passes all three.

Rules tested (P grid 2 / 3 / 4 / 5 / 6 / 8 / 12 / 16 / 24 / 40; every pick leave-one-season-out, plus forward 2022-25):
  a  per-position P for ADP <= 60 only (the 09-17 rule)
  b  a tight-end P for ALL tight ends
  c  per-position P for everyone
  d  what the fixed-setting scan points to: other ADP cuts, a + b, QB ADP <= 60 alone, a weaker prior for
     receivers drafted after pick 60
Every result is re-cut by non-overlapping ADP bands and by position, with seasons better out of 7.
Log live_blend_pos.log.
"""
import json, os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import research_clay_vs_shadow as CS
from backtest_inseason_usage import route_features
warnings.filterwarnings("ignore")

YEARS = list(NW.YEARS); POS4 = ("QB", "RB", "WR", "TE"); FWD = (2022, 2023, 2024, 2025)
GRID = (2, 3, 4, 5, 6, 8, 12, 16, 24, 40)
LIVE_P = 5
TDK = {"QB": 0.5 * 4.0, "RB": 0.75 * 6.0, "WR": 1.0 * 6.0, "TE": 1.0 * 6.0}
USE_C = {"WR": (0.37, 0.53, 0.005, 0.050), "TE": (-1.87, 0.47, 0.023, 0.057)}
ROS_TILT = {"QB": 0.06, "TE": 0.08}
FULL = frozenset(("use", "luck", "rb", "lvl"))
LOG = open(os.path.join(HERE, "live_blend_pos.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + "\n"); LOG.flush()


def setup():
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, clay, layers, adp, pid, name = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"], F["adp"], A["pid"], A["name"]
    ch = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, name)], dtype=float)
    W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay)
    # QB floor level: mean per-game level (season / schedule length) of the top-32 Clay quarterbacks that season
    mu_y = {}
    for y in YEARS:
        wy = 16.0 if y <= 2020 else 17.0
        lv = sorted([max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0) / wy for c in ch[str(y)].values() if c.get("pos") == "QB"], reverse=True)[:32]
        mu_y[y] = float(np.mean(lv))
    mu = np.array([mu_y[int(y)] for y in year])
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet"))
    def joiner(D):
        k = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(D.year, D.pid, D.wk)) if isinstance(b, str)}
        ix = np.array([k.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)])
        return lambda c, d=np.nan: np.where(ix >= 0, D[c].values[np.maximum(ix, 0)].astype(float), d), ix >= 0
    cv, hasC = joiner(C); lv_, hasL = joiner(L)
    xfp, snap = cv("xfp_pg"), cv("snap_std"); rt, _ = route_features(year, pid, wk)
    useok = hasC & (g >= 1) & ~np.isnan(xfp) & ~np.isnan(snap) & ~np.isnan(rt)
    lam_wr = np.select([g <= 2, g <= 5, g <= 8], [0.8, 0.6, 0.5], 0.3); lam_te = np.where(g <= 3, 0.0, 0.3)
    lam = np.where(useok & (pos == "WR"), lam_wr, np.where(useok & (pos == "TE"), lam_te, 0.0))
    cw, ct = USE_C["WR"], USE_C["TE"]
    uimp = np.where(pos == "WR", cw[0] + cw[1] * xfp + cw[2] * rt + cw[3] * snap, ct[0] + ct[1] * xfp + ct[2] * rt + ct[3] * snap)
    uimp = np.maximum(0.0, np.nan_to_num(uimp, nan=0.0))
    ppg0 = np.maximum(0.0, ppg)
    evid = np.where(lam > 0, lam * uimp + (1 - lam) * ppg0, ppg0)
    tdl = np.nan_to_num(lv_("td_luck_pg", 0.0), nan=0.0); tdk = np.array([TDK[p_] for p_ in pos])
    rook = np.nan_to_num(lv_("rookie_mult", 1.0), nan=1.0); cond = np.nan_to_num(lv_("cond_mult", 1.0), nan=1.0)
    wx = np.nan_to_num(lv_("weather_mult", 1.0), nan=1.0); pool = np.nan_to_num(lv_("pool_mult", 1.0), nan=1.0)
    inh = np.nan_to_num(lv_("qb_inherit_mult", 1.0), nan=1.0) > 1.0
    rbu = lv_("usage_half"); rbu = np.where(pos == "RB", rbu, np.nan)
    snapm = np.nan_to_num(cv("snapmult", 1.0), nan=1.0)
    chain = layers * snapm * cond * wx * pool
    # weeks-ahead tilt z (approximation of rosTiltZ): QB attempts per game, TE team pass rate over expected
    att, proe = cv("att_pg"), cv("proe_std"); team = A["team"]; z = np.zeros(n)
    for y in YEARS:
        for w_ in range(2, 19):
            m = (year == y) & (wk == w_)
            q = m & (pos == "QB") & (g >= 2) & (att >= 10)
            if q.sum() >= 8 and att[q].std() > 0: z[q] = np.clip((att[q] - att[q].mean()) / att[q].std(), -2, 2)
            tm = m & (g >= 2) & ~np.isnan(proe)
            if tm.sum():
                tv = {}
                for i in np.where(tm)[0]: tv.setdefault(team[i], proe[i])
                v = np.array(list(tv.values()))
                if len(v) >= 8 and v.std() > 0:
                    t_ = m & (pos == "TE") & (g >= 2) & ~np.isnan(proe)
                    z[t_] = np.clip((proe[t_] - v.mean()) / v.std(), -2, 2)
    tilt_e = np.array([ROS_TILT.get(p_, 0.0) for p_ in pos])
    X = dict(F=F, A=A, n=n, act=act, year=year, wk=wk, pos=pos, g=g, ppg=ppg0, clay_gm=clay_gm, layers=layers, adp=adp, pid=pid, name=name, mu=mu, evid=evid, lam=lam,
             tdl=tdl, tdk=tdk, rook=rook, inh=inh, rbu=rbu, chain=chain, z=z, tilt_e=tilt_e, hasC=hasC, useok=useok)
    return X


def live_parts(X, Pn, tdP, flags=FULL):
    """per-game base + additive TD-luck term for a prior strength Pn (scalar); tdP = the strength inside the TD-luck weight.
    flags switch the newer layers on: use = WR/TE usage evidence, lvl = rookie level + QB floor, rb = RB snap mix, luck = TD luck"""
    g, pos = X["g"], X["pos"]
    ev = X["evid"] if "use" in flags else X["ppg"]; lam = X["lam"] if "use" in flags else 0.0
    base = np.where(g > 0, (Pn * X["clay_gm"] + g * ev) / (Pn + g), X["clay_gm"])
    if "lvl" in flags:
        base = base * X["rook"]
        fl = (pos == "QB") & ~X["inh"] & (base >= 5) & (base < X["mu"])
        base = np.where(fl, X["mu"] + 0.70 * (base - X["mu"]), base)
    if "rb" in flags:
        base = np.where(~np.isnan(X["rbu"]), 0.85 * base + 0.15 * np.nan_to_num(X["rbu"], nan=0.0), base)
    luck = np.where(g > 0, X["tdk"] * X["tdl"] * g / (tdP + g) * (1 - lam), 0.0) if "luck" in flags else np.zeros(X["n"])
    return base, luck


class Tgt:
    def __init__(s, label, X, T, ok, mult, flags=FULL):
        s.label, s.T, s.ok, s.X = label, T, ok, X
        s.PR = {}
        for p_ in GRID:
            for tied in (False, True):
                b, lk = live_parts(X, float(p_), float(p_) if tied else float(LIVE_P), flags)
                s.PR[(p_, tied)] = np.maximum(0.0, b * mult + lk)
        s.base = s.PR[(LIVE_P, False)]
        year, wk, pos, adp = X["year"], X["wk"], X["pos"], X["adp"]
        gr = defaultdict(list)
        for i in np.where(ok & (adp <= 150))[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        s.groups = [np.array(v) for v in gr.values() if len(v) >= 8]
    def compose(s, Pv, tied=False):
        out = s.base.copy()
        for p_ in GRID:
            if p_ == LIVE_P and not tied: continue
            m = Pv == p_
            if m.any(): out[m] = s.PR[(p_, tied)][m]
        return out
    def mse(s, pred, m):
        d = pred[m] - s.T[m]; return float(np.mean(d * d)) if m.any() else np.nan
    def wmse(s, pred, m, wt):
        return float(np.average((pred[m] - s.T[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    def rho(s, pred, yrs=None, ps=None):
        out = [np.corrcoef(rankdata(s.T[ix]), rankdata(pred[ix]))[0, 1] for ix in s.groups
               if (yrs is None or int(s.X["year"][ix[0]]) in yrs) and (ps is None or s.X["pos"][ix[0]] == ps)]
        return float(np.nanmean(out)) if out else np.nan


def main():
    X = setup(); n = X["n"]
    act, year, wk, pos, g, adp, layers, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["layers"], X["name"]
    F = X["F"]; finw = np.where(year <= 2020, 17, 18); final = wk == finw
    top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    band = lambda lo, hi: (adpx > lo) & (adpx <= hi)
    BANDS = (("ADP 1-30", band(0, 30)), ("31-60", band(30, 60)), ("61-100", band(60, 100)), ("101-150", band(100, 150)), ("151+", band(150, 9999)))
    ALL = np.ones(n, bool)
    # rest-of-season target
    seq = defaultdict(list)
    for i in range(n):
        if not final[i]: seq[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(layers[ix], 0.5, 1.8)
        for a, i in enumerate(ix): nfut[i] = len(ix) - a; Tr[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    ramp = np.clip((nfut - 1.5) / np.maximum(nfut, 1), 0, 1)           # this week 0, next week half, then full
    tilt = 1 - X["tilt_e"] * ramp * X["z"]; ctx0 = np.nan_to_num(ctx, nan=1.0)
    okN = (g >= 1) & ~final & ~X["inh"]
    okR1 = (g >= 1) & (g <= 10) & ~np.isnan(Tr) & ~X["inh"]; okR4 = okR1 & (nfut >= 4)
    TG = {"next": Tgt("NEXT GAME", X, act, okN, X["chain"]),
          "ros4": Tgt("REST OF SEASON, 4+ games left", X, Tr, okR4, ctx0 * tilt),
          "ros1": Tgt("REST OF SEASON, no survivor filter", X, Tr, okR1, ctx0 * tilt)}
    KEYS = ("next", "ros4", "ros1")
    PLAIN = Tgt("NEXT GAME, plain 09-17 form (points evidence, Vegas x opponent only)", X, act, okN, layers, flags=frozenset())
    P(f"=== live blend by position: {n:,} Clay-pool player-weeks 2019-25; next game {int(okN.sum()):,} rows; rest of season {int(okR4.sum()):,} checkpoints with 4+ games left, {int(okR1.sum()):,} without the filter ===")
    P(f"    context rows joined {int(X['hasC'].sum()):,}; WR/TE usage evidence on {int((X['lam'] > 0).sum()):,} rows; RB snap mix on {int((~np.isnan(X['rbu'])).sum()):,}; backup-QB inheritance rows dropped {int((X['inh'] & (g >= 1)).sum())}")
    tn = TG["next"]
    P(f"    replica check, next game, everyone: live form vs the plain 09-17 form at P 5: {100*(tn.mse(tn.base, okN)/PLAIN.mse(PLAIN.base, okN)-1):+.2f}% error, rank order {tn.rho(tn.base):.4f} vs {PLAIN.rho(PLAIN.base):.4f}")
    for ps in POS4:
        m = okN & (pos == ps); P(f"      {ps}: n {int(m.sum()):5d}  actual {act[m].mean():5.2f}  live form {tn.base[m].mean():5.2f}  plain {PLAIN.base[m].mean():5.2f}  | live form vs plain {100*(tn.mse(tn.base, m)/PLAIN.mse(PLAIN.base, m)-1):+.2f}%")

    def cell(tg, pred, m, yrs=YEARS, base=None, minrows=10):
        base = tg.base if base is None else base
        m = m & tg.ok & np.isin(year, yrs)
        if m.sum() < 30: return f"{'n/a':>14s}"
        if np.abs(pred[m] - base[m]).max() < 1e-9: return f"{'--':>14s}"
        ys = [y for y in yrs if (m & (year == y)).sum() >= minrows]
        wins = sum(1 for y in ys if tg.mse(pred, m & (year == y)) < tg.mse(base, m & (year == y)) - 1e-12)
        return f"{100*(tg.mse(pred, m)/tg.mse(base, m)-1):+6.2f}% ({wins}/{len(ys)})"
    HDR = f"    {'rule':46s} {'EVERYONE':>14s} {'top150 wtd':>10s} {'rank':>8s} | " + " ".join(f"{b:>14s}" for b, _ in BANDS) + " | " + " ".join(f"{ps:>14s}" for ps in POS4)
    def row(tg, label, pred, yrs=YEARS, base=None):
        b = tg.base if base is None else base
        m150 = tg.ok & top150 & np.isin(year, yrs)
        w = 100 * (tg.wmse(pred, m150, wt) / tg.wmse(b, m150, wt) - 1)
        r = tg.rho(pred, set(yrs)) - tg.rho(b, set(yrs))
        P(f"    {label:46s} {cell(tg, pred, ALL, yrs, b)} {w:+9.2f}% {r:+8.4f} | " + " ".join(cell(tg, pred, bm, yrs, b) for _, bm in BANDS) + " | " + " ".join(cell(tg, pred, pos == ps, yrs, b) for ps in POS4))

    # ---------------- 0 the direct answer: best weight on this season by position and games played ----------------
    P("\n--- 0  HOW MUCH THIS SEASON SHOULD COUNT: best single prior strength by position and games played (pooled, live form) ---")
    P("       weight on this season = g / (P + g); live P 5 gives 17% after 1 game, 38% after 3, 50% after 5, 62% after 8")
    STG = (("1 game", 1, 1), ("2-3", 2, 3), ("4-5", 4, 5), ("6-8", 6, 8), ("9+", 9, 99))
    for key in KEYS:
        tg = TG[key]; P(f"  {tg.label}")
        for ps in POS4:
            for sl, sm in (("everyone", ALL), ("ADP <= 60", adpx <= 60), ("ADP 61+", adpx > 60)):
                cells = []
                for lab, lo, hi in STG:
                    m = tg.ok & (pos == ps) & sm & (g >= lo) & (g <= hi)
                    if m.sum() < 60: cells.append(f"{lab}: n/a"); continue
                    bp = min(GRID, key=lambda p_: tg.mse(tg.PR[(p_, False)], m)); gb = float(g[m].mean())
                    cells.append(f"{lab}: P {bp:>2d} = {100*gb/(bp+gb):3.0f}% (live {100*gb/(5+gb):2.0f}%) {100*(tg.mse(tg.PR[(bp, False)], m)/tg.mse(tg.base, m)-1):+5.1f}%")
                P(f"    {ps} {sl:10s} " + " | ".join(cells))
            m = tg.ok & (pos == ps); bp = min(GRID, key=lambda p_: tg.mse(tg.PR[(p_, False)], m))
            m6 = m & (adpx <= 60); b6 = min(GRID, key=lambda p_: tg.mse(tg.PR[(p_, False)], m6)); m7 = m & (adpx > 60); b7 = min(GRID, key=lambda p_: tg.mse(tg.PR[(p_, False)], m7))
            P(f"    {ps} one number, all games: everyone P {bp}, ADP <= 60 P {b6}, ADP 61+ P {b7}")

    # ---------------- 1 fixed-setting scan ----------------
    P("\n--- 1  FIXED SETTINGS: error vs live (P 5) on the rows of each position x ADP band, seasons better of 7 ---")
    SCOPES = BANDS + (("ADP <= 60", adpx <= 60), ("ADP 61+", adpx > 60), ("all", ALL))
    for key in KEYS:
        tg = TG[key]; P(f"  {tg.label}")
        for ps in POS4:
            for sl, sm in SCOPES:
                m = tg.ok & (pos == ps) & sm
                if m.sum() < 120: continue
                cells = []
                for p_ in GRID:
                    if p_ == LIVE_P: continue
                    pr = tg.PR[(p_, False)]; wins = sum(1 for y in YEARS if (m & (year == y)).sum() >= 10 and tg.mse(pr, m & (year == y)) < tg.mse(tg.base, m & (year == y)) - 1e-12)
                    cells.append(f"P{p_}: {100*(tg.mse(pr, m)/tg.mse(tg.base, m)-1):+5.2f}% ({wins})")
                P(f"    {ps} {sl:9s} n {int(m.sum()):5d}  " + "  ".join(cells))

    # ---------------- 2 rule families, picked leave-one-season-out and forward ----------------
    def fit(tg, scopes, folds, tied=False):
        """scopes: list of (position, row mask); the P of each is picked on the training seasons, plain squared error on its own rows"""
        Pv = np.full(n, float(LIVE_P)); picks = [[] for _ in scopes]
        for tr, te in folds:
            trm = np.isin(year, tr)
            for k, (ps, sm) in enumerate(scopes):
                m = sm & (pos == ps) & tg.ok
                best = min(GRID, key=lambda p_: tg.mse(tg.PR[(p_, tied)], m & trm)); picks[k].append(best)
                Pv[sm & (pos == ps) & (year == te)] = best
        return tg.compose(Pv, tied), picks
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    le = lambda c: adpx <= c; gt = lambda c: adpx > c
    FAMS = [("a  per-position P, ADP <= 60 only", [(ps, le(60)) for ps in POS4]),
            ("b  tight-end P, ALL tight ends", [("TE", ALL)]),
            ("c  per-position P, everyone", [(ps, ALL) for ps in POS4]),
            ("d1 per-position P, ADP <= 30 only", [(ps, le(30)) for ps in POS4]),
            ("d2 per-position P, ADP <= 100 only", [(ps, le(100)) for ps in POS4]),
            ("d3 per-position P, ADP <= 150 only", [(ps, le(150)) for ps in POS4]),
            ("d4 a + b: ADP <= 60 QB/RB/WR, every TE", [("QB", le(60)), ("RB", le(60)), ("WR", le(60)), ("TE", ALL)]),
            ("d5 QB only, ADP <= 60", [("QB", le(60))]),
            ("d6 TE only, ADP <= 60", [("TE", le(60))]),
            ("d7 WR only, ADP 61+", [("WR", gt(60))]),
            ("d8 TE only, ADP 151+ / undrafted", [("TE", gt(150))]),
            ("d9 two-sided: <= 60 and 61+ for each position", [(ps, le(60)) for ps in POS4] + [(ps, gt(60)) for ps in POS4]),
            ("d10 QB <= 60 + WR 61+", [("QB", le(60)), ("WR", gt(60))])]
    P("\n--- 2  RULES, every setting picked LEAVE-ONE-SEASON-OUT (error vs the live blend; seasons better) and FORWARD (fit on earlier seasons, graded 2022-25) ---")
    for key in KEYS:
        tg = TG[key]; P(f"\n  {tg.label}"); P(HDR)
        for lab, sc in FAMS:
            pr, pk = fit(tg, sc, LOSO); row(tg, lab, pr)
            P(f"        picks by held-out season: " + " | ".join(f"{sc[k][0]} {pk[k]}" for k in range(len(sc))))
            prf, pkf = fit(tg, sc, FORW); row(tg, "   forward 2022-25", prf, FWD)
            P(f"        forward picks: " + " | ".join(f"{sc[k][0]} {pkf[k]}" for k in range(len(sc))))

    # ---------------- 3 fixed candidate rules on all three targets ----------------
    def rule(spec):
        Pv = np.full(n, float(LIVE_P))
        for ps, lo, hi, p_ in spec: Pv[(pos == ps) & (adpx > lo) & (adpx <= hi)] = p_
        return Pv
    TOP, LATE, EV = (0, 60), (60, 9999), (0, 9999)
    CANDS = [("09-17 rule: QB16 RB8 WR12 TE12, ADP <= 60", [("QB", *TOP, 16), ("RB", *TOP, 8), ("WR", *TOP, 12), ("TE", *TOP, 12)]),
             ("same four, everyone", [("QB", *EV, 16), ("RB", *EV, 8), ("WR", *EV, 12), ("TE", *EV, 12)]),
             ("TE 8, every tight end", [("TE", *EV, 8)]),
             ("TE 12, every tight end", [("TE", *EV, 12)]),
             ("TE 12, ADP <= 60 only", [("TE", *TOP, 12)]),
             ("TE 16, ADP <= 60 only", [("TE", *TOP, 16)]),
             ("QB 8, every quarterback", [("QB", *EV, 8)]),
             ("QB 8, ADP <= 60 only", [("QB", *TOP, 8)]),
             ("QB 12, ADP <= 60 only", [("QB", *TOP, 12)]),
             ("QB 16, ADP <= 60 only", [("QB", *TOP, 16)]),
             ("QB 24, ADP <= 60 only", [("QB", *TOP, 24)]),
             ("RB 8, ADP <= 60 only", [("RB", *TOP, 8)]),
             ("WR 12, ADP <= 60 only", [("WR", *TOP, 12)]),
             ("WR 4, ADP 61+", [("WR", *LATE, 4)]),
             ("WR 3, ADP 61+", [("WR", *LATE, 3)]),
             ("WR 2, ADP 61+", [("WR", *LATE, 2)]),
             ("WR 3, ADP 61-150", [("WR", 60, 150, 3)]),
             ("WR 3, ADP 151+ / undrafted", [("WR", 150, 9999, 3)]),
             ("TE 3, ADP 151+ / undrafted", [("TE", 150, 9999, 3)]),
             ("QB 12 <= 60 + TE 12 <= 60", [("QB", *TOP, 12), ("TE", *TOP, 12)]),
             ("QB 12 <= 60 + WR 3 61+", [("QB", *TOP, 12), ("WR", *LATE, 3)]),
             ("QB 12 + TE 12 <= 60, WR 3 61+, TE 3 151+", [("QB", *TOP, 12), ("TE", *TOP, 12), ("WR", *LATE, 3), ("TE", 150, 9999, 3)])]
    P("\n--- 3  FIXED CANDIDATE RULES (no fitting; the same setting on all three targets) ---")
    for key in KEYS:
        tg = TG[key]; P(f"\n  {tg.label}"); P(HDR)
        for lab, spec in CANDS: row(tg, lab, tg.compose(rule(spec)))
        P("    -- seasons 2022-25 only (forward view of the fixed settings) --")
        for lab, spec in CANDS: row(tg, lab, tg.compose(rule(spec)), FWD)
    P("\n  same candidates with the TD-luck weight tied to the new prior strength (g / (P + g) instead of g / (5 + g))")
    for key in KEYS:
        tg = TG[key]; P(f"  {tg.label}"); P(HDR)
        for lab, spec in CANDS: row(tg, lab, tg.compose(rule(spec), tied=True))
    P("\n  rest of season with the weeks-ahead QB / TE tilt switched OFF (the tilt is an approximation here)")
    for key, okm in (("ros4", okR4), ("ros1", okR1)):
        tg = Tgt(TG[key].label + ", no tilt", X, Tr, okm, ctx0); P(f"  {tg.label}"); P(HDR)
        for lab, spec in CANDS: row(tg, lab, tg.compose(rule(spec)))

    # ---------------- 4 by games played, by season, rank inside the position ----------------
    P("\n--- 4  FIXED CANDIDATES ON THE ROWS THEY TOUCH: by games played, by season, 2022-25, and rank order inside the position (top 150) ---")
    for key in KEYS:
        tg = TG[key]; P(f"  {tg.label}")
        for lab, spec in CANDS:
            pr = tg.compose(rule(spec)); touched = np.abs(pr - tg.base) > 1e-9
            cells = [f"{sl}: {cell(tg, pr, touched & (g >= lo) & (g <= hi), minrows=5).strip()}" for sl, lo, hi in STG]
            ys = [f"{y}: {100*(tg.mse(pr, touched & tg.ok & (year == y))/tg.mse(tg.base, touched & tg.ok & (year == y))-1):+.1f}%" for y in YEARS if (touched & tg.ok & (year == y)).sum() >= 10]
            m = touched & tg.ok
            P(f"    {lab:46s} touched {int(m.sum()):5d}  actual {tg.T[m].mean():5.2f}  live {tg.base[m].mean():5.2f}  rule {pr[m].mean():5.2f} | all: {cell(tg, pr, touched).strip()} | 2022-25: {cell(tg, pr, touched, FWD).strip()} | " + " | ".join(cells))
            P(f"    {'':46s} by season: " + "  ".join(ys) + "  | rank order by position: " + "  ".join(f"{ps} {tg.rho(pr, None, ps) - tg.rho(tg.base, None, ps):+.4f}" for ps in sorted({s_[0] for s_ in spec})))
            if lab == "WR 3, ADP 61+":
                uo = X["lam"] > 0
                P(f"    {'':46s} WR rows with the usage evidence on: {cell(tg, pr, touched & uo).strip()} (n {int((touched & uo & tg.ok).sum())})  | without it (no route / snap data): {cell(tg, pr, touched & ~uo).strip()} (n {int((touched & ~uo & tg.ok).sum())})")

    # ---------------- 5 which newer layer absorbed the 09-17 gain (next game) ----------------
    P("\n--- 5  WHAT CHANGED SINCE 09-17: the same fixed rules on the next-game target as the newer live layers are added to the plain form ---")
    FORMS = [("plain 09-17 form (points, Vegas x opponent)", frozenset(), layers),
             ("+ TD luck only", frozenset(("luck",)), layers),
             ("+ WR / TE usage evidence only", frozenset(("use",)), layers),
             ("+ RB snap mix, rookie level, QB floor only", frozenset(("rb", "lvl")), layers),
             ("+ snap trend / banged-up / weather / pool only", frozenset(), X["chain"]),
             ("all of them (the live form)", FULL, X["chain"])]
    SUB = [c for c in CANDS if c[0] in ("09-17 rule: QB16 RB8 WR12 TE12, ADP <= 60", "QB 16, ADP <= 60 only", "RB 8, ADP <= 60 only", "WR 12, ADP <= 60 only", "TE 12, ADP <= 60 only", "WR 3, ADP 61+")]
    for fl, flags, mult in FORMS:
        tg = Tgt(fl, X, act, okN, mult, flags=flags); cells = []
        for lab, spec in SUB:
            pr = tg.compose(rule(spec)); touched = np.abs(pr - tg.base) > 1e-9
            cells.append(f"{lab.split(',')[0].replace('09-17 rule: ', '')}: {cell(tg, pr, touched).strip()}")
        pr = tg.compose(rule(SUB[0][1]))
        P(f"    {fl:48s} 09-17 rule, everyone {cell(tg, pr, ALL).strip()} | on the rows touched -> " + " | ".join(cells))
    LOG.close()


if __name__ == "__main__":
    main()
