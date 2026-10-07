#!/usr/bin/env python3
"""
FILL-IN USAGE: does the live number over-project a back-up after the starter he filled in for comes back?
(Jack 2026-10-05: "make sure it is aware that players were only used because the starter was out ... we need
context around usage so far". QBs already handled in the engine; this tests RB / WR / TE.  RESEARCH ONLY.)

Live form replicated from backtest_live_blend_pos.py (setup() / live_parts() copied, not imported - importing that
module truncates its log): base = (5 x Clay per game + g x evidence) / (5 + g), WR / TE usage mix, RB snap mix,
rookie level, TD luck, chain (next game) / mean context x tilt (rest of season).

Definitions
  regulars of X      same-team (season team) same-position players whose Clay per-game projection (half PPR, per
                     projected game) is above X's and >= 5.0 a game
  fill-in game       a game X played for his team while 1+ regular did NOT play for that team that week
  stale fill-in      for a target row j: a fill-in game in X's evidence where at least one of that game's absent
                     regulars IS playing in week wk[j] (starter back)
  rows that matter   rows with 1+ stale fill-in game in the evidence
  flip side          rows with fill-in evidence but none stale (the absentees are still out at the target)
Rules (applied to the stale games only; usage evidence xFP / snap per game is reweighted the same way where the
per-game value is known, route rate is not):
  a  exclude stale games (w = 0)       b  down-weight stale games by w in (.25 .5 .75)  (g' = sum of weights)
  c  rescale stale games' points (and xFP) by 1 / boost: fixed RB 1.26 WR 1.08 TE 1.15, or a fitted divisor
  d  scopes: RB only, lead absent only, ADP bands, 2+ stale games; plus "all fill-in games regardless" (control)
Log fillin_usage.log.
"""
import json, os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import research_clay_vs_shadow as CS
from backtest_inseason_usage import route_features
cal = NW.cal
warnings.filterwarnings("ignore")

YEARS = list(NW.YEARS); POS4 = ("QB", "RB", "WR", "TE"); SK = ("RB", "WR", "TE"); FWD = (2022, 2023, 2024, 2025)
LIVE_P = 5
TDK = {"QB": 0.5 * 4.0, "RB": 0.75 * 6.0, "WR": 1.0 * 6.0, "TE": 1.0 * 6.0}
USE_C = {"WR": (0.37, 0.53, 0.005, 0.050), "TE": (-1.87, 0.47, 0.023, 0.057)}
ROS_TILT = {"QB": 0.06, "TE": 0.08}
BOOST = {"RB": 1.26, "WR": 1.08, "TE": 1.15}
REG_MIN = 5.0
WGRID = (0.0, 0.25, 0.5, 0.75, 1.0)
DGRID = (1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.7)
BANDS_ONLY = "--bands" in sys.argv
LOG = open(os.path.join(HERE, "fillin_usage.log"), "a" if BANDS_ONLY else "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + "\n"); LOG.flush()


# ------------------------------------------------------------------ live form (copied from backtest_live_blend_pos.setup)
def setup():
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, clay, layers, adp, pid, name = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"], F["adp"], A["pid"], A["name"]
    ch = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, name)], dtype=float)
    W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay)
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
    ppg0 = np.maximum(0.0, ppg)
    tdl = np.nan_to_num(lv_("td_luck_pg", 0.0), nan=0.0); tdk = np.array([TDK[p_] for p_ in pos])
    rook = np.nan_to_num(lv_("rookie_mult", 1.0), nan=1.0); cond = np.nan_to_num(lv_("cond_mult", 1.0), nan=1.0)
    wx = np.nan_to_num(lv_("weather_mult", 1.0), nan=1.0); pool = np.nan_to_num(lv_("pool_mult", 1.0), nan=1.0)
    inh = np.nan_to_num(lv_("qb_inherit_mult", 1.0), nan=1.0) > 1.0
    rbu = lv_("usage_half"); rbu = np.where(pos == "RB", rbu, np.nan)
    snapm = np.nan_to_num(cv("snapmult", 1.0), nan=1.0)
    chain = layers * snapm * cond * wx * pool
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
    return dict(F=F, A=A, n=n, act=act, year=year, wk=wk, pos=pos, g=g, ppg=ppg0, clay_gm=clay_gm, layers=layers, adp=adp, pid=pid, name=name, mu=mu, lam=lam,
                tdl=tdl, tdk=tdk, rook=rook, inh=inh, rbu=rbu, chain=chain, z=z, tilt_e=tilt_e, hasC=hasC, useok=useok, xfp=xfp, snap=snap, rt=rt, team=team,
                snap_l1=cv("snap_l1"), ch=ch)


def uimp_of(X, xfp, snap):
    pos = X["pos"]; cw, ct = USE_C["WR"], USE_C["TE"]; rt = X["rt"]
    u = np.where(pos == "WR", cw[0] + cw[1] * xfp + cw[2] * rt + cw[3] * snap, ct[0] + ct[1] * xfp + ct[2] * rt + ct[3] * snap)
    return np.maximum(0.0, np.nan_to_num(u, nan=0.0))


def live_base(X, ppg, ge, xfp, snap):
    """live per-game base + TD-luck term (backtest_live_blend_pos.live_parts, FULL flags, P 5) with the points evidence,
    the evidence game count and the WR/TE usage inputs swappable. TD luck and lam keep the real game count."""
    g, pos, lam = X["g"], X["pos"], X["lam"]
    ev = np.where(lam > 0, lam * uimp_of(X, xfp, snap) + (1 - lam) * ppg, ppg)
    base = np.where(ge > 1e-9, (LIVE_P * X["clay_gm"] + ge * ev) / (LIVE_P + ge), X["clay_gm"])
    base = base * X["rook"]
    fl = (pos == "QB") & ~X["inh"] & (base >= 5) & (base < X["mu"])
    base = np.where(fl, X["mu"] + 0.70 * (base - X["mu"]), base)
    base = np.where(~np.isnan(X["rbu"]), 0.85 * base + 0.15 * np.nan_to_num(X["rbu"], nan=0.0), base)
    luck = np.where(g > 0, X["tdk"] * X["tdl"] * g / (LIVE_P + g) * (1 - lam), 0.0)
    return base, luck


# ------------------------------------------------------------------ fill-in tagging
def week_team(Y, w, opp):
    o = cal.OPP_ALIAS.get(opp, opp)
    for t, s in cal.SCHEDULES.get(Y, {}).items():
        if s.get(str(w)) == o: return t
    return None


def build_fillin(X):
    ch = X["ch"]; tcache = {}
    roster = defaultdict(list)          # (Y, team, pos) -> [(name, clay pg)]
    games = {}                          # (name, pos, Y) -> {wk: (fpts, team_that_week)}
    for Y in YEARS:
        W = 16 if Y <= 2020 else 17
        for nm, c in ch[str(Y)].items():
            ps = c.get("pos")
            if ps not in SK: continue
            rec = cal.weekly_rec(nm, ps)
            if rec is None: continue
            team = cal.infer_team(rec, Y)
            gmv = (c.get("gm") or 0); half = max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0)
            cpg = half / gmv if gmv >= 4 else half / W
            gl = {}
            for w in rec.get("seasons", {}).get(str(Y), []):
                if cal.played(w) and isinstance(w.get("fpts"), (int, float)) and w.get("opp"):
                    k = (Y, int(w["wk"]), w["opp"])
                    if k not in tcache: tcache[k] = week_team(Y, int(w["wk"]), w["opp"])
                    gl[int(w["wk"])] = (float(w["fpts"]), tcache[k])
            games[(nm, ps, Y)] = (team, cpg, gl)
            if team: roster[(Y, team, ps)].append((nm, cpg))
    lead = {k: max(v, key=lambda t: t[1])[0] for k, v in roster.items() if v}
    # per player-season: list of evidence games with their absent regulars
    info = {}
    for (nm, ps, Y), (team, cpg, gl) in games.items():
        if not team: continue
        regs = [(r, rc) for r, rc in roster[(Y, team, ps)] if r != nm and rc > cpg and rc >= REG_MIN]
        rplay = {r: {w for w, (f, t) in games[(r, ps, Y)][2].items() if t == team} for r, _ in regs}
        rows = []
        for w in sorted(gl):
            f, t = gl[w]
            ab = tuple(r for r, _ in regs if t == team and w not in rplay[r])
            rows.append((w, f, ab))
        info[(nm, ps, Y)] = (rows, rplay, lead.get((Y, team, ps)), team)
    return info


def main():
    X = setup(); n = X["n"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    F = X["F"]; finw = np.where(year <= 2020, 17, 18); final = wk == finw
    adpx = np.where(np.isnan(adp), 999.0, adp); top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2

    # per-game xFP / snap share from the cumulative context columns (as research_excused_games.py)
    xfp, snl1 = X["xfp"], X["snap_l1"]
    seq = defaultdict(list)
    for i in range(n): seq[(name[i], pos[i], int(year[i]))].append(i)
    gx, gsn = {}, {}
    for (nm, ps, Y), ix in seq.items():
        ix.sort(key=lambda i: wk[i])
        for a in range(len(ix) - 1):
            i, j = ix[a], ix[a + 1]
            if g[j] - g[i] == 1 and not np.isnan(xfp[j]):
                prevx = xfp[i] * g[i] if (g[i] > 0 and not np.isnan(xfp[i])) else (0.0 if g[i] == 0 else np.nan)
                if not np.isnan(prevx): gx[(nm, ps, Y, int(wk[i]))] = xfp[j] * g[j] - prevx
            if g[j] - g[i] == 1 and not np.isnan(snl1[j]): gsn[(nm, ps, Y, int(wk[i]))] = snl1[j]

    info = build_fillin(X)
    # per-row evidence summaries
    Z = lambda: np.zeros(n)
    nev, s_all, n_st, s_st, n_fi, s_fi = Z(), Z(), Z(), Z(), Z(), Z()
    xk = {k: Z() for k in ("xs", "xn", "xss", "xsn", "xfs", "xfn", "ss", "sn", "sss", "ssn", "sfs", "sfn")}
    lead_st = np.zeros(n, bool); covered = np.zeros(n, bool); ppg_chk = np.full(n, np.nan)
    fillin_game_pts = defaultdict(list); normal_game_pts = defaultdict(list)
    examples = defaultdict(list)
    for i in range(n):
        if pos[i] not in SK or g[i] < 1: continue
        key = (name[i], pos[i], int(year[i]))
        if key not in info: continue
        rows, rplay, ld, team = info[key]
        ev = [r for r in rows if r[0] < wk[i]]
        if len(ev) != int(g[i]): continue        # evidence list must match the harness game count
        covered[i] = True
        ppg_chk[i] = np.mean([r[1] for r in ev])
        for (w, f, ab) in ev:
            stale = any(wk[i] in rplay[r] for r in ab)
            nev[i] += 1; s_all[i] += f
            if ab: n_fi[i] += 1; s_fi[i] += f
            if stale:
                n_st[i] += 1; s_st[i] += f
                if ld in ab: lead_st[i] = True
            gk = (name[i], pos[i], int(year[i]), w)
            for src, pre in ((gx, "x"), (gsn, "s")):
                if gk in src:
                    v = src[gk]; xk[pre + "s"][i] += v; xk[pre + "n"][i] += 1
                    if stale: xk[pre + "ss"][i] += v; xk[pre + "sn"][i] += 1
                    if ab: xk[pre + "fs"][i] += v; xk[pre + "fn"][i] += 1
    # raw fill-in boost: points in fill-in games vs his normal games, same player-season (each game once)
    for (nm, ps, Y), (rows, rplay, ld, team) in info.items():
        fi = [f for w, f, ab in rows if ab]; no = [f for w, f, ab in rows if not ab]
        if len(fi) >= 1 and len(no) >= 2:
            fillin_game_pts[ps].append((Y, np.mean(fi), np.mean(no), len(fi)))

    has_fi = covered & (n_fi > 0); stale_r = covered & (n_st > 0); flip = has_fi & (n_st == 0); clean = covered & (n_fi == 0)

    # ---------------- targets
    seqn = defaultdict(list)
    for i in range(n):
        if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ix in seqn.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(X["layers"][ix], 0.5, 1.8)
        for a, i in enumerate(ix): nfut[i] = len(ix) - a; Tr[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    ramp = np.clip((nfut - 1.5) / np.maximum(nfut, 1), 0, 1)
    tilt = 1 - X["tilt_e"] * ramp * X["z"]; ctx0 = np.nan_to_num(ctx, nan=1.0)
    okN = (g >= 1) & ~final & ~X["inh"]
    okR1 = (g >= 1) & (g <= 10) & ~np.isnan(Tr) & ~X["inh"]; okR4 = okR1 & (nfut >= 4)
    TG = {"next": ("NEXT GAME", act, okN, X["chain"]), "ros4": ("REST OF SEASON, 4+ games left", Tr, okR4, ctx0 * tilt),
          "ros1": ("REST OF SEASON, no survivor filter", Tr, okR1, ctx0 * tilt)}
    KEYS = ("next", "ros4", "ros1")

    def predict(key, ppg, ge, xf, sn):
        _, T, ok, mult = TG[key]; b, lk = live_base(X, ppg, ge, xf, sn)
        return np.maximum(0.0, b * mult + lk)
    BASE = {k: predict(k, X["ppg"], g.astype(float), X["xfp"], X["snap"]) for k in KEYS}

    def variant(w=None, d=None, scope=None, which="stale"):
        """new evidence for rows in scope: stale (or all fill-in) games weighted w, or points / xFP divided by d"""
        nn, ss = (n_st, s_st) if which == "stale" else (n_fi, s_fi)
        xs_, xn_ = (xk["xss"], xk["xsn"]) if which == "stale" else (xk["xfs"], xk["xfn"])
        ss_, sn_ = (xk["sss"], xk["ssn"]) if which == "stale" else (xk["sfs"], xk["sfn"])
        sc = scope & covered & (nn > 0)
        ppg = X["ppg"].copy(); ge = g.astype(float).copy(); xf = X["xfp"].copy(); sp = X["snap"].copy()
        if w is not None:
            den = nev - (1 - w) * nn
            newp = np.where(den > 1e-9, (s_all - (1 - w) * ss) / np.maximum(den, 1e-9), 0.0)
            ppg[sc] = np.maximum(0.0, newp[sc]); ge[sc] = den[sc]
            for (S, N, SS, SN, arr) in ((xk["xs"], xk["xn"], xs_, xn_, xf), (xk["ss"], xk["sn"], ss_, sn_, sp)):
                d0 = N - (1 - w) * SN; ok = sc & (N > 0) & (d0 > 1e-9) & (S > 1e-9)
                r = ((S - (1 - w) * SS) / np.maximum(d0, 1e-9)) / np.maximum(S / np.maximum(N, 1), 1e-9)
                arr[ok] = arr[ok] * r[ok]
        else:
            dv = d if np.ndim(d) else np.full(n, d)
            newp = (s_all - ss + ss / dv) / np.maximum(nev, 1)
            ppg[sc] = np.maximum(0.0, newp[sc])
            ok = sc & (xk["xn"] > 0) & (xk["xs"] > 1e-9)
            r = (xk["xs"] - xs_ + xs_ / dv) / xk["xs"]
            xf[ok] = xf[ok] * r[ok]
        return ppg, ge, xf, sp

    def mse(pred, T, m):
        d_ = pred[m] - T[m]; return float(np.mean(d_ * d_)) if m.any() else np.nan

    def rho(pred, T, ok, yrs):
        gr = defaultdict(list)
        for i in np.where(ok & top150 & np.isin(year, list(yrs)))[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        out = [np.corrcoef(rankdata(T[ix]), rankdata(pred[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]
        return float(np.nanmean(out))

    def cell(key, pred, m, yrs=YEARS, minrows=8):
        _, T, ok, _ = TG[key]; base = BASE[key]; m = m & ok & np.isin(year, list(yrs))
        if m.sum() < 30: return f"{'n/a (n' + str(int(m.sum())) + ')':>17s}"
        ys = [y for y in yrs if (m & (year == y)).sum() >= minrows]
        wins = sum(1 for y in ys if mse(pred, T, m & (year == y)) < mse(base, T, m & (year == y)) - 1e-12)
        return f"{100*(mse(pred, T, m)/mse(base, T, m)-1):+6.2f}% ({wins}/{len(ys)}) n{int(m.sum())}"

    def board(key, pred, yrs=YEARS):
        _, T, ok, _ = TG[key]; base = BASE[key]; m = ok & np.isin(year, list(yrs)); m150 = m & top150
        a = 100 * (mse(pred, T, m) / mse(base, T, m) - 1)
        w_ = 100 * (np.average((pred[m150] - T[m150]) ** 2, weights=wt[m150]) / np.average((base[m150] - T[m150]) ** 2, weights=wt[m150]) - 1)
        return f"all {a:+.3f}%  top150-wtd {w_:+.3f}%  rank {rho(pred, T, ok, yrs) - rho(base, T, ok, yrs):+.4f}"

    if BANDS_ONLY:
        bands_section(locals()); LOG.close(); return
    # ================================================================ 0 descriptive
    P(f"=== FILL-IN USAGE backtest: {n:,} Clay-pool player-weeks 2019-25 (live form replicated, P 5) ===")
    sk = np.isin(pos, SK) & (g >= 1)
    P(f"    RB/WR/TE rows with 1+ games: {int(sk.sum()):,}; evidence rebuilt for {int(covered.sum()):,} (rest: game count mismatch / team unknown)")
    chk = covered & ~np.isnan(ppg_chk); P(f"    replica check: rebuilt points-per-game vs harness ppg, max abs diff {np.nanmax(np.abs(ppg_chk[chk] - X['ppg'][chk])):.4f}")
    P(f"    regulars = same-team same-position players with a higher Clay per-game projection, >= {REG_MIN} half-PPR a game")
    P("\n--- 0a  RAW FILL-IN BOOST: a player's points in his fill-in games vs his own normal games, same season (2+ normal games) ---")
    for ps in SK:
        L_ = fillin_game_pts[ps]
        if not L_: continue
        fi = np.array([t[1] for t in L_]); no = np.array([t[2] for t in L_]); nw = np.array([t[3] for t in L_])
        per = [np.average(fi[[t[0] == y for t in L_]], weights=nw[[t[0] == y for t in L_]]) / np.average(no[[t[0] == y for t in L_]], weights=nw[[t[0] == y for t in L_]]) for y in YEARS]
        P(f"    {ps}: {len(L_)} player-seasons, {int(nw.sum())} fill-in games | fill-in ppg {np.average(fi, weights=nw):5.2f} vs normal {np.average(no, weights=nw):5.2f} -> ratio {np.average(fi, weights=nw)/np.average(no, weights=nw):.3f} | by season " + " ".join(f"{v:.2f}" for v in per))

    P("\n--- 0b  ROW COUNTS and LIVE-FORM BIAS (mean actual / mean projected) ---")
    P("    'starter back' = 1+ stale fill-in game in the evidence (an absentee from that game plays in the target week)")
    for key in KEYS:
        lab, T, ok, _ = TG[key]; P(f"  {lab}")
        for ps in SK:
            mp = ok & (pos == ps)
            def b(m):
                if m.sum() < 10: return f"n {int(m.sum()):5d}"
                ys = [T[m & (year == y)].sum() / BASE[key][m & (year == y)].sum() for y in YEARS if (m & (year == y)).sum() >= 8]
                return f"n {int(m.sum()):5d} act {T[m].mean():5.2f} proj {BASE[key][m].mean():5.2f} -> {T[m].mean()/BASE[key][m].mean():.3f} (under in {sum(1 for v in ys if v < 1)}/{len(ys)})"
            P(f"    {ps}  no fill-in evidence: {b(mp & clean)}")
            P(f"        starter BACK (stale): {b(mp & stale_r)}")
            P(f"        starter still OUT   : {b(mp & flip)}")
            P(f"        back, ADP<=60 {b(mp & stale_r & (adpx <= 60))} | 61-150 {b(mp & stale_r & (adpx > 60) & (adpx <= 150))} | 151+ {b(mp & stale_r & (adpx > 150))}")
            P(f"        back, lead was the absentee {b(mp & stale_r & lead_st)} | back, 2+ stale games {b(mp & stale_r & (n_st >= 2))} | stale share >= 50% {b(mp & stale_r & (n_st >= 0.5 * nev))}")

    P("\n--- 0c  NAMED EXAMPLES (next game, starter back): biggest over-projections summed over the player-season ---")
    _, T, ok, _ = TG["next"]; m = ok & stale_r
    agg = defaultdict(lambda: [0, 0.0, 0.0, 0, 0.0, 0.0])
    for i in np.where(m)[0]:
        k = (name[i], pos[i], int(year[i])); a = agg[k]; a[0] += 1; a[1] += act[i]; a[2] += BASE["next"][i]
    for k, a in agg.items():
        rows, rplay, ld, team = info[k]
        fi = [f for w, f, ab in rows if ab]; no = [f for w, f, ab in rows if not ab]
        a[3] = len(fi); a[4] = np.mean(fi) if fi else 0; a[5] = np.mean(no) if no else np.nan
    top = sorted(agg.items(), key=lambda kv: -(kv[1][2] - kv[1][1]))[:12]
    for (nm, ps, Y), a in top:
        rows, rplay, ld, team = info[(nm, ps, Y)]
        absn = sorted({r for w, f, ab in rows for r in ab})
        P(f"    {Y} {nm:22s} {ps} {team:3s}  fill-in games {a[3]} at {a[4]:5.1f} ppg vs {a[5]:5.1f} otherwise (absent: {', '.join(absn[:3])}) | after return {a[0]} games: proj {a[2]/a[0]:5.1f} actual {a[1]/a[0]:5.1f}")
    bot = sorted(agg.items(), key=lambda kv: (kv[1][2] - kv[1][1]))[:5]
    P("    ...and the other side (kept producing after the starter returned):")
    for (nm, ps, Y), a in bot:
        P(f"    {Y} {nm:22s} {ps}  fill-in games {a[3]} at {a[4]:5.1f} ppg vs {a[5]:5.1f} otherwise | after return {a[0]} games: proj {a[2]/a[0]:5.1f} actual {a[1]/a[0]:5.1f}")

    # ================================================================ 1 fixed settings
    ALLSK = np.isin(pos, SK)
    HDR = f"    {'rule':44s} {'starter-back rows':>24s} | " + " ".join(f"{ps + ' back':>24s}" for ps in SK) + f" | {'flip (still out)':>24s} | overall board"
    def line(key, lab, pred, yrs=YEARS):
        P(f"    {lab:44s} {cell(key, pred, stale_r, yrs):>24s} | " + " ".join(f"{cell(key, pred, stale_r & (pos == ps), yrs):>24s}" for ps in SK)
          + f" | {cell(key, pred, flip, yrs):>24s} | {board(key, pred, yrs)}")
    FIXED = [(f"b  w {w:.2f} (stale only){'  = rule a (exclude)' if w == 0 else ''}", dict(w=w)) for w in (0.0, 0.25, 0.5, 0.75)]
    FIXED += [("c  rescale 1/boost RB1.26 WR1.08 TE1.15", dict(d=np.array([BOOST.get(p_, 1.0) for p_ in pos])))]
    FIXED += [(f"c  rescale 1/{d_:.1f} every position", dict(d=d_)) for d_ in (1.2, 1.4)]
    FIXED += [(f"ctl w {w:.2f} ALL fill-in games, any target", dict(w=w, which="all")) for w in (0.0, 0.5)]
    P("\n--- 1  FIXED SETTINGS, every RB/WR/TE (error vs live; seasons better of 7) ---")
    for key in KEYS:
        P(f"\n  {TG[key][0]}"); P(HDR)
        for lab, kw in FIXED:
            which = kw.pop("which", "stale"); pr = predict(key, *variant(scope=ALLSK, which=which, **kw)); kw["which"] = which
            line(key, lab, pr)
        P("    -- 2022-25 only --")
        for lab, kw in FIXED:
            which = kw.pop("which", "stale"); pr = predict(key, *variant(scope=ALLSK, which=which, **kw)); kw["which"] = which
            line(key, lab, pr, FWD)

    # ================================================================ 2 scopes (d)
    SCOPES = [("RB only", pos == "RB"), ("WR only", pos == "WR"), ("TE only", pos == "TE"),
              ("lead absentee only", ALLSK & lead_st), ("2+ stale games", ALLSK & (n_st >= 2)), ("stale share >= 50%", ALLSK & (n_st >= 0.5 * np.maximum(nev, 1))),
              ("ADP <= 60", ALLSK & (adpx <= 60)), ("ADP 61-150", ALLSK & (adpx > 60) & (adpx <= 150)), ("ADP 151+", ALLSK & (adpx > 150)),
              ("RB lead absentee", (pos == "RB") & lead_st), ("RB ADP 61+", (pos == "RB") & (adpx > 60))]
    P("\n--- 2  SCOPES: fixed w 0 / 0.5 and rescale-by-boost restricted to one cut; graded on that cut's starter-back rows ---")
    for key in KEYS:
        P(f"\n  {TG[key][0]}")
        for sl, sm in SCOPES:
            cells = []
            for lab, kw in (("w0", dict(w=0.0)), ("w.5", dict(w=0.5)), ("boost", dict(d=np.array([BOOST.get(p_, 1.0) for p_ in pos])))):
                pr = predict(key, *variant(scope=sm, **kw))
                cells.append(f"{lab}: {cell(key, pr, stale_r & sm).strip()} fwd {cell(key, pr, stale_r & sm, FWD).strip()}")
            P(f"    {sl:22s} " + " | ".join(cells))

    # ================================================================ 3 LOYO / forward fits
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    def fit(key, fam, scopes, folds):
        _, T, ok, _ = TG[key]
        grid = WGRID if fam == "w" else DGRID
        preds = {v: predict(key, *variant(scope=ALLSK, **({"w": v} if fam == "w" else {"d": v}))) for v in grid}
        out = BASE[key].copy(); picks = [[] for _ in scopes]
        for tr, te in folds:
            trm = np.isin(year, tr)
            for k, sm in enumerate(scopes):
                m = sm & stale_r & ok
                best = min(grid, key=lambda v: mse(preds[v], T, m & trm)); picks[k].append(best)
                sel = sm & (year == te); out[sel] = preds[best][sel]
        return out, picks
    FAMS = [("a/b  w per position (grid 0 .25 .5 .75 1)", "w", [pos == ps for ps in SK], SK),
            ("b    one w for RB/WR/TE", "w", [ALLSK], ("all",)),
            ("c    divisor per position (grid 1.0-1.7)", "d", [pos == ps for ps in SK], SK),
            ("d    w, RB only", "w", [pos == "RB"], ("RB",)),
            ("d    w, lead absentee only, per position", "w", [(pos == ps) & lead_st for ps in SK], SK),
            ("d    w, ADP <= 60 / 61+ per position", "w", [(pos == ps) & (adpx <= 60) for ps in SK] + [(pos == ps) & (adpx > 60) for ps in SK], tuple(f"{p_}<=60" for p_ in SK) + tuple(f"{p_}61+" for p_ in SK))]
    P("\n--- 3  RULES PICKED LEAVE-ONE-SEASON-OUT (fit on the starter-back rows of the other six seasons) and FORWARD (fit on earlier seasons, graded 2022-25) ---")
    for key in KEYS:
        P(f"\n  {TG[key][0]}"); P(HDR)
        for lab, fam, scopes, names in FAMS:
            pr, pk = fit(key, fam, scopes, LOSO); line(key, lab, pr)
            P(f"        LOYO picks: " + " | ".join(f"{names[k]} {pk[k]}" for k in range(len(scopes))))
            prf, pkf = fit(key, fam, scopes, FORW); line(key, "   forward 2022-25", prf, FWD)
            P(f"        forward picks: " + " | ".join(f"{names[k]} {pkf[k]}" for k in range(len(scopes))))
    # ================================================================ 4 candidates the scans point to (fixed, no fitting)
    BV = np.array([BOOST.get(p_, 1.0) for p_ in pos])
    two = ALLSK & (n_st >= 2); half_ = ALLSK & (n_st >= 0.5 * np.maximum(nev, 1))
    CANDS = [("c+d boost rescale, 2+ stale games", dict(d=BV), two),
             ("c+d boost rescale, stale share >= 50%", dict(d=BV), half_),
             ("c+d boost rescale, 2+ stale OR share >= 50%", dict(d=BV), two | half_),
             ("c   boost rescale, RB only (1.26)", dict(d=BV), pos == "RB"),
             ("c+d RB 1.26 all + WR/TE 2+ stale games", dict(d=BV), (pos == "RB") | two),
             ("c+d 1/1.2 every pos, 2+ stale games", dict(d=1.2), two)]
    P("\n--- 4  FIXED CANDIDATES the scans point to: all starter-back rows, by position, flip side, overall board; then by season ---")
    for key in KEYS:
        P(f"\n  {TG[key][0]}"); P(HDR)
        for lab, kw, sm in CANDS: line(key, lab, predict(key, *variant(scope=sm, **kw)))
        P("    -- 2022-25 only --")
        for lab, kw, sm in CANDS: line(key, lab, predict(key, *variant(scope=sm, **kw)), FWD)
        _, T, ok, _ = TG[key]
        for lab, kw, sm in CANDS:
            pr = predict(key, *variant(scope=sm, **kw)); tm = ok & stale_r & sm
            ys = [f"{y}: {100*(mse(pr, T, tm & (year == y))/mse(BASE[key], T, tm & (year == y))-1):+.1f}% n{int((tm & (year == y)).sum())}" for y in YEARS if (tm & (year == y)).sum() >= 5]
            P(f"    {lab:44s} touched {int(tm.sum())}: actual {T[tm].mean():.2f} live {BASE[key][tm].mean():.2f} rule {pr[tm].mean():.2f} | " + "  ".join(ys))
    P(f"\n    replica rows with rebuilt ppg off by > 0.05: {int((chk & (np.abs(ppg_chk - X['ppg']) > 0.05)).sum())} of {int(chk.sum())}")
    P("\nLimitations: route rate per game not reweighted (season-to-date kept); RB snap-volume mix (usage_half), TD-luck and the usage mix weight keep the")
    P("real game count; regulars ranked by Clay per-game projection (ADP missing for many non-pool backups); team = season team (mid-season")
    P("trades: games for another team never tagged); prop anchor / pecking-order dock / availability curves are not replayable (as in live_blend_pos).")
    LOG.close()


def bands_section(V):
    """5  shipped rule (rescale RB 1.26 / WR 1.08, rows with 2+ stale fill-in games, TE untouched) re-cut by ADP band."""
    X, TG, BASE, KEYS, predict, variant, mse = V["X"], V["TG"], V["BASE"], V["KEYS"], V["predict"], V["variant"], V["mse"]
    pos, year, wk, adpx, n_st, stale_r, nev = X["pos"], X["year"], X["wk"], V["adpx"], V["n_st"], V["stale_r"], V["nev"]
    n = X["n"]
    BV = np.array([{"RB": 1.26, "WR": 1.08}.get(p_, 1.0) for p_ in pos])
    rbwr = np.isin(pos, ("RB", "WR")); two = rbwr & (n_st >= 2)
    BANDS = [("ADP 1-30", (adpx <= 30)), ("ADP 31-60", (adpx > 30) & (adpx <= 60)), ("ADP 61-100", (adpx > 60) & (adpx <= 100)),
             ("top 30", adpx <= 30), ("top 60", adpx <= 60), ("top 100", adpx <= 100), ("ADP 101+ / none", adpx > 100), ("everyone", np.ones(n, bool))]
    RULES = [("shipped (all ADP)", two), ("restricted ADP > 30", two & (adpx > 30)), ("restricted ADP > 60", two & (adpx > 60))]
    def rho(pred, T, m):
        gr = defaultdict(list)
        for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        out = [np.corrcoef(rankdata(T[ix]), rankdata(pred[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 5]
        return float(np.nanmean(out)) if out else np.nan, len(out)
    def cell(pred, base, T, m, yrs=YEARS, minrows=5):
        m = m & np.isin(year, list(yrs))
        if m.sum() == 0: return "n 0"
        if np.abs(pred[m] - base[m]).max() < 1e-12: return f"no change (n{int(m.sum())})"
        ys = [y for y in yrs if (m & (year == y)).sum() >= minrows]
        wins = sum(1 for y in ys if mse(pred, T, m & (year == y)) < mse(base, T, m & (year == y)) - 1e-12)
        return f"{100*(mse(pred, T, m)/mse(base, T, m)-1):+6.2f}% ({wins}/{len(ys)}) n{int(m.sum())}"
    P("\n--- 5  SHIPPED RULE BY ADP BAND (rescale RB 1.26 / WR 1.08, rows with 2+ stale fill-in games; TE untouched) ---")
    P("    touched = rows the rule changes; 'band all' = every row of that position in the band; seasons better counted where a season has 5+ rows;")
    P("    rank = change in within-position Spearman (actual vs projected) over week groups of 5+ rows inside the band (groups counted)")
    for key in KEYS:
        lab, T, ok, _ = TG[key]; base = BASE[key]
        P(f"\n  {lab}")
        P("    descriptive, starter back (1+ stale game) and 2+ stale games: actual / projected")
        for ps in ("RB", "WR"):
            cells = []
            for bl, bm in BANDS[:7]:
                m1 = ok & stale_r & (pos == ps) & bm; m2 = m1 & (n_st >= 2)
                f = lambda m: (f"{T[m].mean()/base[m].mean():.3f} n{int(m.sum())}" if m.sum() >= 5 else f"n{int(m.sum())}")
                cells.append(f"{bl}: {f(m1)} / {f(m2)}")
            P(f"    {ps} " + " | ".join(cells))
        for rl, sc in RULES:
            pr = predict(key, *variant(scope=sc, d=BV))
            P(f"    rule: {rl}")
            for ps in ("RB", "WR"):
                for bl, bm in BANDS:
                    mb = ok & (pos == ps) & bm; tm = mb & (np.abs(pr - base) > 1e-12)
                    r0, ng = rho(base, T, mb); r1, _ = rho(pr, T, mb)
                    P(f"      {ps} {bl:16s} touched {int(tm.sum()):4d} | touched: {cell(pr, base, T, tm):>28s} fwd {cell(pr, base, T, tm, FWD):>26s} | band all: {cell(pr, base, T, mb):>28s} fwd {cell(pr, base, T, mb, FWD):>26s} | rank {r1 - r0:+.4f} ({ng} groups)")
    LOG.flush()


if __name__ == "__main__":
    main()
