#!/usr/bin/env python3
"""
OPPONENT LAYER: would a different read of the defense predict PLAYER points better? (2026-10-05, backtest only)

The live layer (engine.js jsOppMult):
    actual = 1 + 0.25 * (clamp(fpa[pos] / leagueAvg, 0.8, 1.25) - 1)
    w      = min(1, defenseGames / 8)
    mult   = w * actual + (1 - w) * clayMult
fpa = raw half-PPR points the defense has allowed per game to the position this season (touchdowns as they
happened, no schedule adjustment). Historically there is no Clay unit grade, and the house harness
(bt_common / backtest_noclay_weekly) has no stand-in, so the baseline's prior is "no adjustment" (clayMult = 1).

A team-level study in the website repo (scripts/research_opp_grade_schemes.py) found a defense's later points
allowed are better predicted by a number that is (a) schedule-adjusted, (b) touchdown-neutral and (c) blended
with the same defense's prior-season number, weight on this season = games / (games + k). This script asks
whether any of that survives on PLAYER projections, which is what the layer does.

Harness = the house whole-board harness (research_clay_vs_shadow.build_harness: 2019-25 Clay-pool player-weeks,
half-PPR; shipped = P=5 blend(Clay per game, season-to-date PPG) x Vegas x FPA). The harness FPA multiplier is
divided out and replaced by each variant. The defense numbers come from nflverse player-week stats (complete
league, the per-game position totals cached by the team-level research under the system temp dir).

Variants (each alone and stacked):
  a  schedule-adjusted number (additive defense / offense effects, one-game prior - app.js _wkSchedAdjust port)
  b  touchdown-neutral number: pts - 4 passTD - 6 (rushTD + recTD) + 4 x .00626 passYd + 6 x (.00759 rushYd + .00623 recYd)
  c  prior-season number as the prior:  linear 8-game trust (the engine form with last season where Clay sits)
     or  w = games / (games + k)  with k = team-level (QB 3 / RB 4 / WR 6 / TE 2) or picked leave-one-season-out
  d  elasticity re-fit for every variant (global and per position), leave-one-season-out

Grading (house rules): every fitted setting picked LEAVE-ONE-SEASON-OUT; final week dropped; % change vs the
current layer and seasons better out of 7 on (1) all rows, plain squared error, (2) top-150 importance-weighted
squared error (the selection objective), (3) weekly within-position rank order; by position; non-overlapping ADP
bands; week bands; and only the rows a variant moves by 1%+ of the projection. Also a FORWARD pass (settings picked
on earlier seasons only, graded 2022-25) and a season-week resampling interval for the headline variants. Next game
is the main target; rest-of-season per game is the secondary. The Clay-free shadow base is a robustness check.
Section 6 (tight ends left on the current layer) was added AFTER seeing the tight-end column - post-hoc, not a clean test.

RESULT 2026-10-05: nothing clears the house bar (-0.30%, 5+ of 7 seasons). Schedule adjustment: no gain. Touchdown-
neutral alone: -0.04%. Last season as the prior: -0.10% to -0.14% (5-6 of 7), all of it in weeks 1-4. Elasticity .25
confirmed for the live input. Best stack (TD-neutral + prior, e about .35) -0.18%; tight ends get worse with all of it.

Writes backtest_opp_layer_tdn.log only (plus a harness pickle under the system temp dir; --rebuild refreshes it).
Usage: python backtest_opp_layer_tdn.py [--rebuild]
"""
import itertools, os, pickle, sys, tempfile, time
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
SCRIPT_DIRS = [r"E:\MyFantasyFootball\MyFantasyFootball Files\.claude\worktrees\dst-sos-inseason\scripts", r"E:\MyFantasyFootball\MyFantasyFootball Files\scripts"]
TMP = os.path.join(tempfile.gettempdir(), "mff_opp_layer_cache")
WIDE = os.path.join(tempfile.gettempdir(), "mff_preseason_fade_cache")
YEARS = list(range(2019, 2026)); POS4 = ("QB", "RB", "WR", "TE"); FWD = [2022, 2023, 2024, 2025]
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
tm = lambda t: ALIAS.get(t, t)
R_PASS, R_RUSH, R_REC = 0.00626, 0.00759, 0.00623          # league TD per yard (the site constants)
LIVE_E, LIVE_TRUST, CLAMP = 0.25, 8.0, (0.8, 1.25)
TEAM_K = {"QB": 3.0, "RB": 4.0, "WR": 6.0, "TE": 2.0}       # the team-level study's k
EG = [0.0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60, 0.75, 1.00]
KG = [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 20.0]
FMS = [("raw", "pts"), ("adj", "pts"), ("raw", "tdn"), ("adj", "tdn")]
FM_LAB = {("raw", "pts"): "raw actual (live)", ("adj", "pts"): "a sched-adj", ("raw", "tdn"): "b TD-neutral", ("adj", "tdn"): "a+b sched-adj TD-neutral"}
MOVE = 0.01

_LOG = None
def P(s=""):
    print(s); sys.stdout.flush()
    if _LOG: _LOG.write(s + "\n"); _LOG.flush()


# ------------------------------------------------------------------ harness
def load_harness(rebuild=False):
    os.makedirs(TMP, exist_ok=True); path = os.path.join(TMP, "harness.pkl")
    if os.path.exists(path) and not rebuild and time.time() - os.path.getmtime(path) < 86400:
        return pickle.load(open(path, "rb")), "cached"
    import research_clay_vs_shadow as CS
    import bt_common as B
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    opp = np.empty(n, dtype=object); veg = np.ones(n)
    for Y in YEARS:
        games = B.load_games(Y); avg = float(np.mean([v["implied"] for v in games.values() if v["implied"] is not None]))
        for i in np.where(A["year"] == Y)[0]:
            gm = games[(A["team"][i], int(A["wk"][i]))]; opp[i] = gm["opp"]
            veg[i] = min(1.35, max(0.7, 1 + B.VEG[A["pos"][i]] * (gm["implied"] - avg) / avg))
    H = dict(n=n, shipped=F["shipped"], shadow=F["shadow"], adp=F["adp"], adp_curve=F["adp_curve"], layers=F["layers"], opp=opp, veg=veg,
             **{k: A[k] for k in ("year", "name", "pos", "team", "wk", "act", "g", "ppg", "clay")})
    pickle.dump(H, open(path, "wb"))
    return H, "built"


# ------------------------------------------------------------------ defense numbers
def sched_adjust_np(di, oi, v, nT, K=1.0):
    """numpy port of research_preseason_fade.sched_adjust -> mu + defense effect per team index (nan = no games)."""
    mu = v.mean(); dE = np.zeros(nT); oE = np.zeros(nT)
    dN = np.bincount(di, minlength=nT).astype(float); oN = np.bincount(oi, minlength=nT).astype(float)
    for _ in range(50):
        dE = np.bincount(di, weights=v - mu - oE[oi], minlength=nT) / (dN + K)
        oE = np.bincount(oi, weights=v - mu - dE[di], minlength=nT) / (oN + K)
    out = mu + dE; out[dN == 0] = np.nan
    return out


def load_def_games():
    frames = []
    for y in range(YEARS[0] - 1, YEARS[-1] + 1):
        path = os.path.join(WIDE, "pos_games_wide_%d.csv" % y)
        if not os.path.exists(path):
            for d in SCRIPT_DIRS:
                if os.path.isdir(d) and d not in sys.path: sys.path.insert(0, d)
            from research_opp_grade_schemes import player_games
            player_games(y)
        df = pd.read_csv(path); df["season"] = y; frames.append(df)
    g = pd.concat(frames, ignore_index=True)
    g["d"] = g["d"].map(tm); g["o"] = g["o"].map(tm)
    g["pts"] = g["v"]
    g["tdn"] = g["v"] - 4 * g["ptd"] - 6 * (g["rtd"] + g["rectd"]) + 4 * R_PASS * g["pyd"] + 6 * (R_RUSH * g["ryd"] + R_REC * g["recyd"])
    games = g[["season", "week", "d", "o"]].drop_duplicates()
    out = []
    for ps in POS4:   # a game where a position scored nothing still counts as a game
        m = games.merge(g[g["pos"] == ps][["season", "week", "d", "o", "pts", "tdn"]], on=["season", "week", "d", "o"], how="left").fillna({"pts": 0.0, "tdn": 0.0}); m["pos"] = ps; out.append(m)
    return pd.concat(out, ignore_index=True)


def build_tables(G):
    """IN[(Y, pos, wk)] = (games[32], {fm: ratio[32]}) from games before wk;  PR[(Y, pos)] = {fm: ratio[32]} for the whole season Y, final week dropped.
    ratio = the defense's number / the league mean of that number."""
    teams = sorted(set(G["d"])); tix = {t: i for i, t in enumerate(teams)}; nT = len(teams)
    IN, PR, RAWPTS = {}, {}, {}
    def numbers(sub):
        di = sub["di"].values; oi = sub["oi"].values; dN = np.bincount(di, minlength=nT).astype(float); res = {}
        for mt in ("pts", "tdn"):
            v = sub[mt].values.astype(float)
            raw = np.where(dN > 0, np.bincount(di, weights=v, minlength=nT) / np.maximum(dN, 1), np.nan)
            adj = sched_adjust_np(di, oi, v, nT)
            res[("raw", mt)] = raw / np.nanmean(raw); res[("adj", mt)] = adj / np.nanmean(adj)
        return dN, res
    G = G.assign(di=G["d"].map(tix), oi=G["o"].map(tix))
    for (Y, ps), f in G.groupby(["season", "pos"]):
        fin = int(f["week"].max())
        PR[(Y, ps)] = numbers(f[f["week"] < fin])[1]
        for r in f.itertuples(index=False): RAWPTS[(Y, ps, int(r.week), r.d)] = float(r.pts)
        if Y < YEARS[0]: continue
        for wk in range(1, fin + 1):
            sub = f[f["week"] < wk]
            IN[(Y, ps, wk)] = numbers(sub) if len(sub) else (np.zeros(nT), {fm: np.full(nT, np.nan) for fm in FMS})
    return teams, tix, IN, PR, RAWPTS


def make_ctx(year, pos, asof, opp, tix, IN, PR):
    n = len(year); g = np.zeros(n); rin = {fm: np.full(n, np.nan) for fm in FMS}; rpr = {fm: np.full(n, np.nan) for fm in FMS}
    for i in range(n):
        j = tix[opp[i]]; dN, res = IN[(int(year[i]), pos[i], int(asof[i]))]; pr = PR[(int(year[i]) - 1, pos[i])]; g[i] = dN[j]
        for fm in FMS: rin[fm][i] = res[fm][j]; rpr[fm][i] = pr[fm][j]
    return dict(g=g, rin=rin, rpr=rpr, pos=np.asarray(pos, dtype=object))


def _per_pos(v, pos):
    return np.array([v[p] for p in pos], dtype=float) if isinstance(v, dict) else v


def mult(c, fm, mode, e, k=None):
    """the opponent multiplier. mode: none8 = live trust min(1, g/8), nothing before it; prior8 = same trust, last season where Clay sits;
    gk = games / (games + k) with last season as the prior; none_gk = that trust shape with no prior."""
    lo, hi = CLAMP
    a = np.nan_to_num(np.clip(c["rin"][fm], lo, hi) - 1.0, nan=0.0); b = np.nan_to_num(np.clip(c["rpr"][fm], lo, hi) - 1.0, nan=0.0)
    g = c["g"]; e = _per_pos(e, c["pos"])
    if mode in ("none8", "prior8"): w = np.minimum(1.0, g / LIVE_TRUST)
    else:
        kk = _per_pos(k, c["pos"]); w = np.where(g + kk > 0, g / np.maximum(g + kk, 1e-9), 0.0)
    dev = w * a + ((1 - w) * b if mode in ("prior8", "gk") else 0.0)
    return 1.0 + e * dev


# ------------------------------------------------------------------ targets + scoring
class Target:
    def __init__(s, name, ctx, combine, act, year, pos, wk, adp, wt, valid):
        s.name, s.ctx, s.combine, s.act, s.year, s.pos, s.wk, s.adp, s.wt = name, ctx, combine, act, year, pos, wk, adp, wt
        s.pB = s.pred(("raw", "pts"), "none8", LIVE_E)
        s.allm = valid & (s.pB >= 3); s.b150 = valid & (adp <= 150)
        groups = defaultdict(list)
        for i in np.where(s.b150)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
        s.groups = [(k[0], np.array(v)) for k, v in groups.items() if len(v) >= 8]
        s.ract = [rankdata(act[ix]) for _, ix in s.groups]
    def pred(s, fm, mode, e, k=None): return s.combine(mult(s.ctx, fm, mode, e, k))
    def ms(s, q, m): return float(np.mean((q[m] - s.act[m]) ** 2)) if m.any() else np.nan
    def wm(s, q, m): return float(np.average((q[m] - s.act[m]) ** 2, weights=s.wt[m])) if m.any() else np.nan
    def rho(s, q):
        by = defaultdict(list)
        for (y, ix), ra in zip(s.groups, s.ract): by[y].append(np.corrcoef(ra, rankdata(q[ix]))[0, 1])
        return float(np.mean([x for v in by.values() for x in v])), {y: float(np.mean(v)) for y, v in by.items()}


def pct(a, b): return 100.0 * (a / b - 1.0) if b else np.nan


def loyo(T, cands, build, scope, obj):
    """cands -> out-of-season prediction; scope 'global' or 'pos' (setting picked per position); obj 'w150' or 'all'."""
    preds = [build(c) for c in cands]
    m = T.b150 if obj == "w150" else T.allm; w = T.wt if obj == "w150" else np.ones(len(T.act))
    SE = np.zeros((len(cands), len(YEARS), 4))
    for ci, q in enumerate(preds):
        se = w * (q - T.act) ** 2
        for yi, y in enumerate(YEARS):
            for pi, ps in enumerate(POS4): SE[ci, yi, pi] = se[m & (T.year == y) & (T.pos == ps)].sum()
    def run(folds, start):
        out = start.copy(); picks = []
        for tr_years, y in folds:
            tr = [YEARS.index(yy) for yy in tr_years]
            if scope == "global":
                best = int(np.argmin(SE[:, tr, :].sum(axis=(1, 2)))); out[T.year == y] = preds[best][T.year == y]; picks.append(cands[best])
            else:
                row = []
                for pi, ps in enumerate(POS4):
                    best = int(np.argmin(SE[:, tr, pi].sum(axis=1))); mm = (T.year == y) & (T.pos == ps); out[mm] = preds[best][mm]; row.append(cands[best])
                picks.append(tuple(row))
        return out, picks
    out, picks = run([([yy for yy in YEARS if yy != y], y) for y in YEARS], preds[0])
    fwd, _ = run([([yy for yy in YEARS if yy < y], y) for y in FWD], T.pB)     # forward: earlier seasons only
    pooled = cands[int(np.argmin(SE.sum(axis=(1, 2))))] if scope == "global" else tuple(cands[int(np.argmin(SE[:, :, pi].sum(axis=1)))] for pi in range(4))
    return out, fwd, picks, pooled


def score(T, q, qf=None):
    pB = T.pB; yb = lambda fn, m: sum(1 for y in YEARS if fn(q, m & (T.year == y)) < fn(pB, m & (T.year == y)) - 1e-12)
    r, ry = T.rho(q); rB, rBy = T.rho(pB)
    d = dict(all=pct(T.ms(q, T.allm), T.ms(pB, T.allm)), all_s=yb(T.ms, T.allm), w=pct(T.wm(q, T.b150), T.wm(pB, T.b150)), w_s=yb(T.wm, T.b150),
             rho=r - rB, rho_s=sum(1 for y in YEARS if ry.get(y, 0) > rBy.get(y, 0) + 1e-12))
    qf = q if qf is None else qf; fy = np.isin(T.year, FWD)
    d["f_all"] = pct(T.ms(qf, T.allm & fy), T.ms(pB, T.allm & fy)); d["f_all_s"] = sum(1 for y in FWD if T.ms(qf, T.allm & (T.year == y)) < T.ms(pB, T.allm & (T.year == y)) - 1e-12)
    d["f_w"] = pct(T.wm(qf, T.b150 & fy), T.wm(pB, T.b150 & fy)); d["f_w_s"] = sum(1 for y in FWD if T.wm(qf, T.b150 & (T.year == y)) < T.wm(pB, T.b150 & (T.year == y)) - 1e-12)
    for ps in POS4:
        d["w_" + ps] = pct(T.wm(q, T.b150 & (T.pos == ps)), T.wm(pB, T.b150 & (T.pos == ps))); d["ws_" + ps] = yb(T.wm, T.b150 & (T.pos == ps))
        d["a_" + ps] = pct(T.ms(q, T.allm & (T.pos == ps)), T.ms(pB, T.allm & (T.pos == ps))); d["as_" + ps] = yb(T.ms, T.allm & (T.pos == ps))
    mv = T.allm & (np.abs(q - pB) >= MOVE * pB); d["mv_n"] = int(mv.sum())
    d["mv"] = pct(T.ms(q, mv), T.ms(pB, mv)) if mv.any() else 0.0; d["mv_s"] = yb(T.ms, mv) if mv.any() else 0
    mv150 = mv & T.b150; d["mvw"] = pct(T.wm(q, mv150), T.wm(pB, mv150)) if mv150.any() else 0.0
    dx = (q - pB)[mv]; dy = (T.act - pB)[mv]; d["slope"] = float((dx * dy).sum() / max(1e-12, (dx * dx).sum())) if mv.any() else np.nan
    return d


HEAD = ("    %-58s | all rows       | top-150 wtd    | rank order     | forward 2022-25: all, wtd    | top-150 wtd by position (seasons)                 | rows moved 1%%+: n, error (seasons), top-150 wtd, slope"
        % "variant")
def fmt_pick(p):
    if isinstance(p, tuple) and len(p) == 4 and isinstance(p[0], tuple): return "/".join(fmt_pick(x) for x in p)
    if isinstance(p, tuple): return "(" + ",".join(fmt_pick(x) for x in p) + ")"
    if isinstance(p, dict): return "team-k"
    return ("%.2f" % p).rstrip("0").rstrip(".") if isinstance(p, float) else str(p)
def line(label, d, extra=""):
    P("    %-58s | %+6.2f%% (%d/7) | %+6.2f%% (%d/7) | %+.4f (%d/7) | %+6.2f%% (%d/4) %+6.2f%% (%d/4) | " % (
        label, d["all"], d["all_s"], d["w"], d["w_s"], d["rho"], d["rho_s"], d["f_all"], d["f_all_s"], d["f_w"], d["f_w_s"])
      + " ".join("%s %+5.2f%% (%d)" % (ps, d["w_" + ps], d["ws_" + ps]) for ps in POS4)
      + " | %5d  %+6.2f%% (%d/7)  %+6.2f%%  %+.2f" % (d["mv_n"], d["mv"], d["mv_s"], d["mvw"], d["slope"]) + (("  | " + extra) if extra else ""))


def run_variant(T, fm, mode, e_spec, k_spec, obj="w150"):
    """e_spec / k_spec: a number (or per-position dict) = fixed; 'loyo' = one setting for the board; 'loyo_pos' = per position."""
    fit_e, fit_k = isinstance(e_spec, str), isinstance(k_spec, str)
    if not fit_e and not fit_k: return T.pred(fm, mode, e_spec, k_spec), None, ""
    scope = "pos" if "loyo_pos" in (e_spec, k_spec) else "global"
    cands = list(itertools.product(EG if fit_e else [e_spec], KG if fit_k else [k_spec]))
    q, qf, picks, pooled = loyo(T, cands, lambda c: T.pred(fm, mode, c[0], c[1]), scope, obj)
    show = lambda c: (("e " + fmt_pick(c[0])) if fit_e else "") + (" " if fit_e and fit_k else "") + (("k " + fmt_pick(c[1])) if fit_k else "")
    if scope == "global": txt = "all-season pick " + show(pooled) + "; held-out picks " + ", ".join(sorted({show(p) for p in picks}))
    else: txt = "all-season picks " + " | ".join("%s %s" % (ps, show(pooled[i])) for i, ps in enumerate(POS4)) + "; held-out range " + " | ".join(
        "%s %s" % (ps, ", ".join(sorted({show(p[i]) for p in picks}))) for i, ps in enumerate(POS4))
    return q, qf, txt


def boot(T, q, reps=4000, seed=7):
    """90% interval for the % change, resampling whole season-weeks (rows in one week share games)."""
    cl = T.year * 100 + T.wk; ids = np.unique(cl[T.allm]); ix = np.searchsorted(ids, cl); ok = np.isin(cl, ids)
    def sums(m, w):
        a = np.bincount(ix[m & ok], weights=(w * (q - T.act) ** 2)[m & ok], minlength=len(ids)); b = np.bincount(ix[m & ok], weights=(w * (T.pB - T.act) ** 2)[m & ok], minlength=len(ids)); return a, b
    rng = np.random.default_rng(seed); C = rng.multinomial(len(ids), np.ones(len(ids)) / len(ids), size=reps).astype(float); out = []
    for m, w in ((T.allm, np.ones(len(q))), (T.b150, T.wt)):
        a, b = sums(m, w); r = 100 * ((C @ a) / (C @ b) - 1); out.append((np.percentile(r, 5), np.percentile(r, 95), float((r < 0).mean())))
    return out


def detail(T, label, q):
    pB = T.pB; adp = T.adp
    (a5, a95, ap), (w5, w95, wp) = boot(T, q)
    yb = lambda m: sum(1 for y in YEARS if (m & (T.year == y)).sum() >= 20 and T.ms(q, m & (T.year == y)) < T.ms(pB, m & (T.year == y)) - 1e-12)
    cell = lambda m: "%+6.2f%% (%d/7, n %d)" % (pct(T.ms(q, m), T.ms(pB, m)), yb(m), int(m.sum())) if m.sum() >= 50 else "   -   (n %d)" % int(m.sum())
    P("    " + label)
    P("       resampling season-weeks, 90%% interval: all rows %+.2f%% to %+.2f%% (better in %.0f%% of resamples); top-150 weighted %+.2f%% to %+.2f%% (%.0f%%)" % (a5, a95, 100 * ap, w5, w95, 100 * wp))
    P("       by position, all rows:   " + "  ".join("%s %s" % (ps, cell(T.allm & (T.pos == ps))) for ps in POS4))
    bands = (("ADP 1-30", adp <= 30), ("31-60", (adp > 30) & (adp <= 60)), ("61-100", (adp > 60) & (adp <= 100)), ("101-150", (adp > 100) & (adp <= 150)), ("151+ / none", ~(adp <= 150)))
    P("       ADP bands, all rows:     " + "  ".join("%s %s" % (lab, cell(T.allm & m)) for lab, m in bands))
    for ps in POS4:
        P("         %s by ADP band:       " % ps + "  ".join("%s %s" % (lab, cell(T.allm & m & (T.pos == ps))) for lab, m in bands))
    wb = (("wk 1", T.wk == 1), ("wk 2-4", (T.wk >= 2) & (T.wk <= 4)), ("wk 5-8", (T.wk >= 5) & (T.wk <= 8)), ("wk 9-13", (T.wk >= 9) & (T.wk <= 13)), ("wk 14+", T.wk >= 14))
    P("       week bands, all rows:    " + "  ".join("%s %s" % (lab, cell(T.allm & m)) for lab, m in wb))
    P("       by season, all rows / top-150 wtd:  " + "  ".join("%d %+5.2f%% / %+5.2f%%" % (y, pct(T.ms(q, T.allm & (T.year == y)), T.ms(pB, T.allm & (T.year == y))),
                                                                                         pct(T.wm(q, T.b150 & (T.year == y)), T.wm(pB, T.b150 & (T.year == y)))) for y in YEARS))


def board(T, title, full=True):
    P("\n" + "=" * 150); P("=== %s: %s rows (%s top-150); baseline error all rows %.3f, top-150 weighted %.3f, rank order %.4f ===" % (
        title, format(int(T.allm.sum()), ","), format(int(T.b150.sum()), ","), T.ms(T.pB, T.allm), T.wm(T.pB, T.b150), T.rho(T.pB)[0]))
    P("    negative = better than the current layer (raw actual points, e .25, trust min(1, g/8), no prior). Fitted settings picked leave-one-season-out on the top-150 weighted error.")
    P("    forward = settings picked on EARLIER seasons only, graded 2022-25. House ship bar: -0.30% or better leave-one-season-out in 5+ of 7 seasons.")
    keep = {}
    def go(label, fm, mode, e, k=None, obj="w150"):
        q, qf, txt = run_variant(T, fm, mode, e, k, obj); d = score(T, q, qf); line(label, d, txt); keep[label] = (q, d, qf); return q
    def te_live(label, src):
        """the source variant on QB / RB / WR, tight ends left on the current layer"""
        q, _, qf = keep[src]; te = T.pos == "TE"; q2 = np.where(te, T.pB, q); qf2 = None if qf is None else np.where(te, T.pB, qf)
        d = score(T, q2, qf2); line(label, d); keep[label] = (q2, d, qf2)
    P(HEAD)
    go("no opponent layer at all (e 0)", ("raw", "pts"), "none8", 0.0)
    P("  -- 1. the read of the defense, live elasticity .25 and live trust min(1, g/8), no prior")
    for fm in FMS[1:]: go(FM_LAB[fm], fm, "none8", LIVE_E)
    P("  -- 2. c: last season as the prior (elasticity .25)")
    for fm in FMS:
        go(FM_LAB[fm] + " + prior, 8-game linear", fm, "prior8", LIVE_E)
        go(FM_LAB[fm] + " + prior, g/(g+k) team k", fm, "gk", LIVE_E, TEAM_K)
        if full:
            go(FM_LAB[fm] + " + prior, g/(g+k) k fitted", fm, "gk", LIVE_E, "loyo")
            go(FM_LAB[fm] + " + prior, g/(g+k) k fitted by pos", fm, "gk", LIVE_E, "loyo_pos")
            go(FM_LAB[fm] + " NO prior, g/(g+k) k fitted", fm, "none_gk", LIVE_E, "loyo")
    P("  -- 3. d: elasticity re-fit")
    for fm in FMS:
        go(FM_LAB[fm] + ", live trust, e fitted", fm, "none8", "loyo")
        go(FM_LAB[fm] + ", live trust, e fitted by pos", fm, "none8", "loyo_pos")
        if full:
            go(FM_LAB[fm] + " + prior 8-game, e fitted", fm, "prior8", "loyo")
            go(FM_LAB[fm] + " + prior team k, e fitted", fm, "gk", "loyo", TEAM_K)
            go(FM_LAB[fm] + " + prior team k, e fitted by pos", fm, "gk", "loyo_pos", TEAM_K)
    P("  -- 4. everything fitted together: elasticity and k")
    for fm in FMS:
        go(FM_LAB[fm] + " + prior, e and k fitted", fm, "gk", "loyo", "loyo")
        if full: go(FM_LAB[fm] + " + prior, e and k fitted by pos", fm, "gk", "loyo_pos", "loyo_pos")
    if full:
        P("  -- 5. same fits, settings picked on the plain all-rows error instead (sensitivity)")
        for fm in (("raw", "pts"), ("adj", "tdn")):
            go(FM_LAB[fm] + ", live trust, e fitted [plain]", fm, "none8", "loyo", None, "all")
            go(FM_LAB[fm] + " + prior, e and k fitted [plain]", fm, "gk", "loyo", "loyo", "all")
    P("  -- 6. POST-HOC (chosen after seeing the tight-end column above, so not a clean test): QB / RB / WR changed, tight ends left on the current layer")
    for lab, src in (("raw + prior 8-game linear, TE as is", "raw actual (live) + prior, 8-game linear"), ("raw + prior team k, TE as is", "raw actual (live) + prior, g/(g+k) team k"),
                     ("TD-neutral + prior 8-game linear, TE as is", "b TD-neutral + prior, 8-game linear"), ("TD-neutral + prior team k, TE as is", "b TD-neutral + prior, g/(g+k) team k"),
                     ("TD-neutral + prior team k, e fitted, TE as is", "b TD-neutral + prior team k, e fitted")):
        if src in keep: te_live(lab, src)
    return keep


# ------------------------------------------------------------------ main
def main():
    global _LOG
    t0 = time.time()
    H, how = load_harness("--rebuild" in sys.argv)
    _LOG = open(os.path.join(HERE, "backtest_opp_layer_tdn.log"), "w", encoding="utf-8")
    P("OPPONENT LAYER: a different read of the defense (schedule-adjusted / touchdown-neutral / last season as the prior), 2019-25 player-weeks")
    P("harness %s: %s player-weeks (research_clay_vs_shadow.build_harness)" % (how, format(H["n"], ",")))
    n = H["n"]; year, pos, wk, act, opp, adp = H["year"], H["pos"], H["wk"].astype(int), H["act"], H["opp"], H["adp"]
    fpa_h = H["layers"] / H["veg"]
    G = load_def_games(); teams, tix, IN, PR, RAWPTS = build_tables(G)
    P("defense games: %s position-games %d-%d, %d teams; touchdown-neutral league mean %.2f vs actual %.2f (QB) / %.2f vs %.2f (WR)" % (
        format(len(G), ","), G["season"].min(), G["season"].max(), len(teams), G[G.pos == "QB"]["tdn"].mean(), G[G.pos == "QB"]["pts"].mean(), G[G.pos == "WR"]["tdn"].mean(), G[G.pos == "WR"]["pts"].mean()))
    # the numpy schedule fit against the website repo's own function
    try:
        for d in SCRIPT_DIRS:
            if os.path.isdir(d) and d not in sys.path: sys.path.insert(0, d)
        from research_preseason_fade import sched_adjust
        f = G[(G.season == 2023) & (G.pos == "WR") & (G.week < 9)]
        ref = sched_adjust(list(zip(f["d"], f["o"], f["pts"]))); mine = sched_adjust_np(f["d"].map(tix).values, f["o"].map(tix).values, f["pts"].values.astype(float), len(teams))
        P("schedule fit check vs research_preseason_fade.sched_adjust (2023 WR through week 8): max difference %.2e" % max(abs(ref[t] - mine[tix[t]]) for t in ref))
    except Exception as ex:
        P("schedule fit check skipped (%s)" % ex)
    miss = sum(1 for i in range(n) if (int(year[i]), pos[i], int(wk[i]), opp[i]) not in RAWPTS)
    P("harness player-weeks whose game is missing from the nflverse defense table: %d" % miss)

    ctx = make_ctx(year, pos, wk, opp, tix, IN, PR)
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
    lv = H["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2

    # ---- team-level sanity: does each number line up with what the defense allows NEXT game (the website finding)?
    P("\n=== sanity, team level: correlation of each defense number (through week N) with the raw points it allows in week N+1, 2019-25, weeks 2-17 ===")
    P("    %-34s %s" % ("number", "   ".join("%-6s" % ps for ps in POS4)))
    rowsT = []
    for (Y, ps, w_), (dN, res) in IN.items():
        if w_ < 2 or w_ >= (17 if Y <= 2020 else 18): continue
        for t, j in tix.items():
            v = RAWPTS.get((Y, ps, w_, t))
            if v is None or dN[j] == 0: continue
            rowsT.append((Y, ps, w_, dN[j], v) + tuple(res[fm][j] for fm in FMS) + tuple(PR[(Y - 1, ps)][fm][j] for fm in FMS))
    TT = pd.DataFrame(rowsT, columns=["Y", "pos", "wk", "g", "v"] + ["in_%s_%s" % fm for fm in FMS] + ["pr_%s_%s" % fm for fm in FMS])
    def tcorr(col_fn):
        out = []
        for ps in POS4:
            f = TT[TT.pos == ps]; rs = []
            for (_, _w), ff in f.groupby(["Y", "wk"]):
                x = col_fn(ff, ps)
                if len(ff) >= 20 and np.std(x) > 0: rs.append(np.corrcoef(x, ff["v"])[0, 1])
            out.append("%.3f " % np.mean(rs))
        return "   ".join(out)
    for fm in FMS: P("    %-34s %s" % ("in-season " + FM_LAB[fm], tcorr(lambda ff, ps, fm=fm: ff["in_%s_%s" % fm].values)))
    for fm in FMS: P("    %-34s %s" % ("last season " + FM_LAB[fm], tcorr(lambda ff, ps, fm=fm: ff["pr_%s_%s" % fm].values)))
    for fm in FMS:
        P("    %-34s %s" % ("blend team k " + FM_LAB[fm], tcorr(lambda ff, ps, fm=fm: (ff["g"] / (ff["g"] + TEAM_K[ps]) * (ff["in_%s_%s" % fm] - 1) + TEAM_K[ps] / (ff["g"] + TEAM_K[ps]) * (ff["pr_%s_%s" % fm] - 1)).values)))

    # ---- next game, Clay base (the live base)
    noopp = H["shipped"] / fpa_h
    T = Target("next game, live (Clay) base", ctx, lambda m: noopp * m, act, year, pos, wk, adp, wt, ~final)
    mB = mult(ctx, ("raw", "pts"), "none8", LIVE_E); hasg = ctx["g"] >= 1
    P("\n=== baseline reproduction: the live layer rebuilt from nflverse complete-league points vs the house harness's own FPA multiplier (site weekly DB) ===")
    P("    rows with at least one defense game: %s; multiplier correlation %.3f; mean absolute difference %.4f; harness multiplier range %.3f-%.3f, rebuilt %.3f-%.3f" % (
        format(int(hasg.sum()), ","), np.corrcoef(fpa_h[hasg], mB[hasg])[0, 1], np.abs(fpa_h - mB)[hasg].mean(), fpa_h.min(), fpa_h.max(), mB.min(), mB.max()))
    for lab, m_ in (("all rows", T.allm), ("top-150 rows", T.b150)):
        fn = T.ms if lab == "all rows" else T.wm
        P("    %-13s error: house harness shipped %.4f | rebuilt baseline %.4f (%+.3f%%) | no opponent layer %.4f (%+.3f%% vs rebuilt)" % (
            lab, fn(H["shipped"], m_), fn(T.pB, m_), pct(fn(T.pB, m_), fn(H["shipped"], m_)), fn(noopp, m_), pct(fn(noopp, m_), fn(T.pB, m_))))
    P("    harness plain MSE on every row incl. final week (the number the older logs quote): shipped %.4f, rebuilt %.4f" % (float(np.mean((H["shipped"] - act) ** 2)), float(np.mean((T.pB - act) ** 2))))

    # ---- what elasticity does the data ask for? pooled least-squares slope of (actual - base) on base x deviation
    P("\n=== the elasticity the data asks for: least-squares e in  actual = base x (1 + e x deviation), no trust schedule, by defense games (all rows, final week out) ===")
    P("    %-30s %s" % ("number", "   ".join("%-34s" % ("%s: g1-3 | g4-7 | g8+ | all" % ps) for ps in POS4)))
    def ls_e(dev, m):
        x = (noopp * dev)[m]; y = (act - noopp)[m]; return float((x * y).sum() / max(1e-12, (x * x).sum()))
    for src, lab0 in (("rin", "in-season "), ("rpr", "last season ")):
        for fm in FMS:
            dev = np.nan_to_num(np.clip(ctx[src][fm], *CLAMP) - 1.0, nan=0.0); cells = []
            for ps in POS4:
                mp = (~final) & (noopp >= 3) & (pos == ps)
                bs = [mp & (ctx["g"] >= 1) & (ctx["g"] <= 3), mp & (ctx["g"] >= 4) & (ctx["g"] <= 7), mp & (ctx["g"] >= 8), mp & (ctx["g"] >= 1)] if src == "rin" else [mp & (ctx["g"] <= 3), mp & (ctx["g"] >= 4) & (ctx["g"] <= 7), mp & (ctx["g"] >= 8), mp]
                cells.append("%-34s" % " | ".join("%+.2f" % ls_e(dev, b) for b in bs))
            P("    %-30s %s" % (lab0 + FM_LAB[fm], "   ".join(cells)))
    P("    (last-season rows are bucketed by THIS season's defense games: g0-3 | g4-7 | g8+ | all)")
    P("    spread of the deviation (sd of clamp(ratio) - 1 on rows with 4+ defense games): " + "  ".join(
        "%s %s" % (FM_LAB[fm], "/".join("%.3f" % np.nanstd((np.clip(ctx["rin"][fm], *CLAMP) - 1)[(pos == ps) & (ctx["g"] >= 4)]) for ps in POS4)) for fm in FMS))

    K1 = board(T, "NEXT GAME, live (Clay) base")
    P("\n=== NEXT GAME, live base: where the change lands (plain error vs the current layer; seasons better need 20+ rows) ===")
    want = ["a sched-adj", "b TD-neutral", "a+b sched-adj TD-neutral", "raw actual (live) + prior, 8-game linear", "raw actual (live) + prior, g/(g+k) team k",
            "b TD-neutral + prior, 8-game linear", "a+b sched-adj TD-neutral + prior, g/(g+k) team k", "raw actual (live), live trust, e fitted by pos",
            "b TD-neutral + prior team k, e fitted", "b TD-neutral + prior team k, e fitted by pos", "a+b sched-adj TD-neutral + prior, e and k fitted",
            "raw + prior 8-game linear, TE as is", "TD-neutral + prior 8-game linear, TE as is", "TD-neutral + prior team k, e fitted, TE as is"]
    for k in want:
        if k in K1: detail(T, k, K1[k][0])

    # ---- next game, Clay-free shadow base
    noopp_s = H["shadow"] / fpa_h
    Ts = Target("next game, shadow base", ctx, lambda m: noopp_s * m, act, year, pos, wk, adp, wt, ~final)
    board(Ts, "NEXT GAME, Clay-free shadow base (robustness check; harness v2.11 form)", full=False)

    # ---- rest of season per game: the defense numbers as of this week applied to every remaining opponent
    seq = defaultdict(list)
    for i in range(n): seq[(H["name"][i], pos[i], int(year[i]))].append(i)
    pi, pj = [], []
    for ix in seq.values():
        ix = sorted(ix, key=lambda i: wk[i])
        for a_, i in enumerate(ix):
            if final[i]: continue
            for j in ix[a_:]:
                if not final[j]: pi.append(i); pj.append(j)
    pi, pj = np.array(pi), np.array(pj)
    cnt = np.bincount(pi, minlength=n).astype(float)
    ctxp = make_ctx(year[pi], pos[pi], wk[pi], opp[pj], tix, IN, PR)
    rate = H["shipped"] / H["layers"]; core = rate[pi] * H["veg"][pj]
    act_ros = np.bincount(pi, weights=act[pj], minlength=n) / np.maximum(cnt, 1)
    Tr = Target("rest of season", ctxp, lambda m: np.bincount(pi, weights=core * m, minlength=n) / np.maximum(cnt, 1), act_ros, year, pos, wk, adp, wt, (~final) & (cnt >= 3))
    P("\n(rest of season: %s player-week x remaining-game pairs; target = the player's points per game over his remaining games (3+ left, final week out);"
      "\n projection = this week's Clay / season-to-date rate x each remaining game's Vegas multiplier x the opponent multiplier from the defense numbers AS OF this week)" % format(len(pi), ","))
    board(Tr, "REST OF SEASON per game, live (Clay) base", full=False)
    P("\ndone in %.0fs" % (time.time() - t0)); _LOG.close()


if __name__ == "__main__":
    main()
