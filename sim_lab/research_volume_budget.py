#!/usr/bin/env python3
"""
POSITION-GROUP VOLUME BUDGET + VOLUME FORECAST STUDY (Jack 2026-10-13: "have sims project out volume for each positional
group, then run replacements or efficiency based off it"; "the most important thing is overall usage, carry %, routes, xFP").

Per team-game (2019-25, REG, final week out) the model forecasts each RB / WR / TE's targets and carries:
  TEAM VOLUME   team targets / g and non-QB carries / g, recency-weighted over this season's team games, shrunk to the league
                (K_TEAM team games), optional game-script tilt from THIS game's spread / total (fit on training seasons only)
  SHARE         each body's share of team targets / carries per game (optionally on COMPETITIVE plays only - garbage = Q4 |m| >= 17,
                Q3 >= 28, the engine ctxShare rule), recency-weighted (decay d per team game), each history game NORMALISED to
                full availability and the forecast RE-NORMALISED to the next game's actual availability:
                    s_j(A) = u_j x (1 + rho_s x M_same(A) / U_same(A) + rho_o x M_other(A) / U_all(A))
                u = full-strength share, M = share mass of absent members (same / other position group), U = present mass.
                rho = how much of an absent body's volume his group / the other groups absorb (fit, LOYO). History games played
                WITHOUT a teammate are divided by their own factor, so an absence already observed is never paid twice.
                Every body with a snap is a member (depth bodies included). Optional: down-weight history games with a different
                starting QB than next game's (q), and a faster decay for rookies / 2nd-year players (d_young).
  VALUE         xFP per target / per carry: own season-to-date, shrunk to the position mean (25 opportunities)
  -> budget xFP. Baseline = the engine's implicit volume read: season-to-date xFP/g (the shadow usage evidence, ctx xfp_pg).

Grades (house rules: top-150 ADP importance weight, final week out, LOYO picks + forward 2022-25, by week bucket = walk-forward):
  A  volume forecasting: next-game xFP / targets / carries, rest-of-season xFP/g
  B  points: (1) budget points alone (budget xFP x own shrunk pts/xFP x layers); (2) VOLUME LAYER shadow x (budget / baseline)^e;
     (3) ALLOCATION LAYER replacing the pool (iA) boost: shadow-without-pool x (budget(A) / baseline)^e
  C  situations: where the shadow misses (teammate out, blowout last game, QB change, return from absence, traded, role change,
     rookies) + biggest misses; KAMARA case: pool boost by games ALREADY played without the absent teammate.
Log volume_budget.log. Research only; nothing wired.
"""
import os, sys, pickle, warnings, itertools, time
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import bt_common as B
import rank_grade as RG
warnings.filterwarnings("ignore")
YEARS = list(range(2019, 2026)); FWD = (2022, 2023, 2024, 2025); SK = ("RB", "WR", "TE")
LOG = open(os.path.join(HERE, "volume_budget.log"), "w", encoding="utf-8")
def P(s=""):
    print(s, flush=True); LOG.write(s + "\n"); LOG.flush()

H = pickle.load(open(os.path.join(HERE, "_tmp", "vb_harness.pkl"), "rb")); n = H["n"]
act, year, wk, pos, g, adp, name, pid, team = H["act"], H["year"], H["wk"], H["pos"], H["g"], H["adp"], H["name"], H["pid"], H["team"]
team = np.array([B.tm(str(t)) for t in team])
finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
lv = H["adp_curve"].copy()
for ps in ("QB", "RB", "WR", "TE"):
    m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
WT = np.maximum(0.05, lv) ** 2
S, S0, TODAY, L = H["S"], H["S_nopool"], H["TODAY"], H["layers"]

G = pd.read_parquet(os.path.join(HERE, "_tmp", "vf_games.parquet")); T = pd.read_parquet(os.path.join(HERE, "_tmp", "vf_teams.parquet"))
G = G[G.pos.isin(["QB", "RB", "WR", "TE"])]
GW = defaultdict(dict)   # (Y, team, wk) -> pid -> row
for r in G.itertuples(index=False): GW[(r.year, r.team, r.wk)][r.pid] = r
TW = {(r.year, r.team, r.wk): r for r in T.itertuples(index=False)}
TWEEKS = defaultdict(list)
for (Y, t, w) in TW: TWEEKS[(Y, t)].append(w)
for k in TWEEKS: TWEEKS[k].sort()
PGAMES = defaultdict(list)   # (Y, pid) -> [(wk, team)]
for r in G.itertuples(index=False): PGAMES[(r.year, r.pid)].append((r.wk, r.team))
for k in PGAMES: PGAMES[k].sort()
# league means per season (team targets / carries per game)
LG = {Y: (T[T.year == Y].tg.mean(), T[T.year == Y].car.mean()) for Y in range(2018, 2026)}
# position xFP per target / carry
XPT = {ps: G[G.pos == ps].xfp_rec.sum() / max(1, G[G.pos == ps].tg.sum()) for ps in SK}
XPC = {ps: G[G.pos == ps].xfp_rush.sum() / max(1, G[G.pos == ps].car.sum()) for ps in SK}
POSOF = dict(zip(G.pid, G.pos))
# actual per player-game xFP / tg / car (targets of the grade)
AX = np.full(n, np.nan); ATG = np.full(n, np.nan); ACAR = np.full(n, np.nan)
for i in range(n):
    r = GW.get((int(year[i]), team[i], int(wk[i])), {}).get(pid[i])
    if r is None:
        for (w_, t_) in PGAMES.get((int(year[i]), pid[i]), []):
            if w_ == int(wk[i]): r = GW[(int(year[i]), t_, w_)].get(pid[i]); break
    if r is not None: AX[i], ATG[i], ACAR[i] = r.xfp, r.tg, r.car
P(f"harness rows {n:,}; rows with a game-table match {int((~np.isnan(AX)).sum()):,}; xFP/target {XPT}; xFP/carry {XPC}")


def team_fc(Y, t, w, cfg, cache):
    """-> {pid: (tg_hat, car_hat, tg_base, car_base, u_t, u_c)} for every member, next game = week w; None if no history"""
    key = (Y, t, w)
    if key in cache: return cache[key]
    weeks = [k for k in TWEEKS.get((Y, t), []) if k < w]
    if not weeks or (Y, t, w) not in TW: cache[key] = None; return None
    d, comp, rs_t, ro_t, rs_c, ro_c, q, dy = cfg["d"], cfg["comp"], cfg["rs_t"], cfg["ro_t"], cfg["rs_c"], cfg["ro_c"], cfg["q"], cfg["dy"]
    qb_next = TW[(Y, t, w)].qb
    nk = len(weeks); age = {k: nk - 1 - i for i, k in enumerate(weeks)}
    qw = {k: (1.0 if (q >= 1 or TW[(Y, t, k)].qb == qb_next) else q) for k in weeks}
    # shares per game
    sh_t, sh_c, first = defaultdict(dict), defaultdict(dict), {}
    for k in weeks:
        Tk = TW[(Y, t, k)]; tt = Tk.tg_c if comp else Tk.tg; tc = Tk.car_c if comp else Tk.car
        for p_, r in GW[(Y, t, k)].items():
            if r.pos not in SK: continue
            first.setdefault(p_, k)
            sh_t[p_][k] = ((r.tg_c if comp else r.tg) / tt) if tt > 0 else 0.0
            sh_c[p_][k] = ((r.car_c if comp else r.car) / tc) if tc > 0 else 0.0
    mem = list(sh_t.keys())
    young = cfg.get("young", set())
    def wts(p_, k): return (dy if p_ in young else d) ** age[k] * qw[k]
    def est(sh, rs, ro, u):
        # one normalisation pass given current u
        new = {}
        for p_ in mem:
            num = den = 0.0
            for k, s in sh[p_].items():
                present = set(x for x in GW[(Y, t, k)] if x in sh)   # members with a row in game k
                fac = factor(p_, present, k, u, rs, ro)
                wk_ = wts(p_, k); num += wk_ * s / fac; den += wk_
            new[p_] = num / den if den > 0 else 0.0
        return new
    def factor(p_, present, k, u, rs, ro):
        if rs == 0 and ro == 0: return 1.0
        ps = POSOF.get(p_); ms = mo = us = ua = 0.0
        for x in mem:
            if first[x] > k: continue   # not yet a member at game k
            ux = u.get(x, 0.0)
            if x in present:
                ua += ux
                if POSOF.get(x) == ps: us += ux
            else:
                if POSOF.get(x) == ps: ms += ux
                else: mo += ux
        return 1.0 + (rs * ms / us if us > 1e-9 else 0.0) + (ro * mo / ua if ua > 1e-9 else 0.0)
    u_t = {p_: np.mean(list(v.values())) for p_, v in sh_t.items()}; u_c = {p_: np.mean(list(v.values())) for p_, v in sh_c.items()}
    for _ in range(2):
        u_t = est(sh_t, rs_t, ro_t, u_t); u_c = est(sh_c, rs_c, ro_c, u_c)
    # raw (un-normalised) recency shares = what the history says without availability context
    raw_t = {p_: sum(wts(p_, k) * s for k, s in v.items()) / sum(wts(p_, k) for k in v) for p_, v in sh_t.items()}
    raw_c = {p_: sum(wts(p_, k) * s for k, s in v.items()) / sum(wts(p_, k) for k in v) for p_, v in sh_c.items()}
    # team volume
    vt = np.array([TW[(Y, t, k)].tg for k in weeks]); vc = np.array([TW[(Y, t, k)].car for k in weeks]); ww = np.array([qw[k] for k in weeks])
    Kt = cfg["Kt"]; Vt = (np.sum(ww * vt) + Kt * LG[Y][0]) / (ww.sum() + Kt); Vc = (np.sum(ww * vc) + Kt * LG[Y][1]) / (ww.sum() + Kt)
    sp = TW[(Y, t, w)].spread; tot = TW[(Y, t, w)].total
    if cfg.get("script") and not np.isnan(sp) and not np.isnan(tot):
        bt, bc = cfg["script"]
        Vt *= np.exp(bt[0] * np.clip(sp, -14, 14) + bt[1] * (tot - 45)); Vc *= np.exp(bc[0] * np.clip(sp, -14, 14) + bc[1] * (tot - 45))
    present_w = set(x for x in GW[(Y, t, w)] if x in sh_t)
    out = {}
    for p_ in mem:
        ft = factor(p_, present_w, w, u_t, rs_t, ro_t); fc = factor(p_, present_w, w, u_c, rs_c, ro_c)
        st = u_t[p_] * ft if (rs_t or ro_t) else raw_t[p_]; sc = u_c[p_] * fc if (rs_c or ro_c) else raw_c[p_]
        out[p_] = (Vt * st, Vc * sc, ft, fc)
    cache[key] = out
    return out


def player_vals(i):
    """own xFP per target / carry (season to date, shrunk 25 opps), std mean tg / car / xfp per game"""
    Y, p_, w = int(year[i]), pid[i], int(wk[i])
    rows = [GW[(Y, t_, w_)][p_] for (w_, t_) in PGAMES.get((Y, p_), []) if w_ < w]
    if not rows: return None
    tg = sum(r.tg for r in rows); car = sum(r.car for r in rows); xr = sum(r.xfp_rec for r in rows); xc = sum(r.xfp_rush for r in rows)
    ps = pos[i]; xpt = (xr + 25 * XPT[ps]) / (tg + 25); xpc = (xc + 25 * XPC[ps]) / (car + 25)
    return xpt, xpc, tg / len(rows), car / len(rows), (xr + xc) / len(rows), len(rows)


SKM = np.isin(pos, SK) & (g >= 1) & ~final & np.array([bool(p_) for p_ in pid])
PV = [player_vals(i) if SKM[i] else None for i in range(n)]
B0 = np.full(n, np.nan); B0m = np.full(n, np.nan)
for i in range(n):
    if PV[i] is not None:
        xpt, xpc, tgm, carm, xm, gm = PV[i]; B0[i] = xm; B0m[i] = tgm * xpt + carm * xpc
young = set(pid[i] for i in range(n) if H["rookie"][i])
P(f"skill rows (RB/WR/TE, g>=1, final week out) {int(SKM.sum()):,}; with own history {int((~np.isnan(B0)).sum()):,}; top-150 {int((SKM & top150 & ~np.isnan(B0)).sum()):,}")


def run(cfg):
    cache = {}; BUD = np.full(n, np.nan); BTG = np.full(n, np.nan); BCAR = np.full(n, np.nan); FT = np.ones(n); FC = np.ones(n)
    cfg = dict(cfg); cfg["young"] = young
    for i in np.where(SKM & ~np.isnan(B0))[0]:
        fc_ = team_fc(int(year[i]), team[i], int(wk[i]), cfg, cache)
        if not fc_ or pid[i] not in fc_: continue
        th, ch, ft, fcc = fc_[pid[i]]; xpt, xpc = PV[i][0], PV[i][1]
        BUD[i] = th * xpt + ch * xpc; BTG[i] = th; BCAR[i] = ch; FT[i] = ft; FC[i] = fcc
    return BUD, BTG, BCAR, FT, FC


def wmse(p, T_, m): return float(np.average((p[m] - T_[m]) ** 2, weights=WT[m])) if m.any() else np.nan
def mae(p, T_, m): return float(np.average(np.abs(p[m] - T_[m]), weights=WT[m])) if m.any() else np.nan


# ---------------- ROS targets ----------------
seqn = defaultdict(list)
for i in range(n):
    if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
TR = np.full(n, np.nan); TRX = np.full(n, np.nan); CTX = np.full(n, np.nan); NFUT = np.zeros(n, int)
for ix in seqn.values():
    ix.sort(key=lambda i: wk[i]); a_ = act[ix]; x_ = AX[ix]; l_ = np.clip(L[ix], 0.5, 1.8)
    for a, i in enumerate(ix): NFUT[i] = len(ix) - a; TR[i] = a_[a:].mean(); TRX[i] = np.nanmean(x_[a:]) if np.any(~np.isnan(x_[a:])) else np.nan; CTX[i] = l_[a:].mean()
ros = lambda p: p / np.maximum(L, 0.3) * np.nan_to_num(CTX, nan=1.0)
NEXT = SKM & top150 & ~np.isnan(B0) & ~np.isnan(AX)
ROSM = NEXT & (g >= 3) & (g <= 10) & (NFUT >= 4) & ~np.isnan(TRX)


def fold_table(lab, base, cand, T_, m, tf=lambda p: p):
    b, c = tf(base), tf(cand); rows = []; better = 0
    for Y in YEARS:
        mm = m & (year == Y)
        if not mm.any(): continue
        e0, e1 = wmse(b, T_, mm), wmse(c, T_, mm); better += e1 < e0 - 1e-12; rows.append(f"{Y} {100*(e1/e0-1):+.2f}%")
    fb = sum(1 for Y in FWD if wmse(c, T_, m & (year == Y)) < wmse(b, T_, m & (year == Y)))
    r0 = RG.rank_stats(b, m, T_, year, wk, pos)[0]; r1 = RG.rank_stats(c, m, T_, year, wk, pos)[0]
    P(f"  {lab:58s} n{int(m.sum()):6d} MSE {100*(wmse(c, T_, m)/wmse(b, T_, m)-1):+6.2f}% ({better}/7, fwd {fb}/4) MAE {100*(mae(c, T_, m)/mae(b, T_, m)-1):+6.2f}% rho {r0:.4f}->{r1:.4f} | {' '.join(rows)}")
    return better, fb


def loyo_pick(preds, base, T_, m, lab, tf=lambda p: p):
    """preds: {label: array}; per held-out season pick the label with the lowest training error; also forward"""
    keys = list(preds); out = np.array(base, dtype=float).copy(); outf = np.array(base, dtype=float).copy(); picks = []
    E = {k: {Y: wmse(tf(preds[k]), T_, m & (year == Y)) * (WT[m & (year == Y)].sum()) for Y in YEARS} for k in keys}
    for Y in YEARS:
        best = min(keys, key=lambda k: sum(E[k][y] for y in YEARS if y != Y)); picks.append(best)
        out[year == Y] = preds[best][year == Y]
        if Y in FWD:
            bf = min(keys, key=lambda k: sum(E[k][y] for y in YEARS if y < Y)); outf[year == Y] = preds[bf][year == Y]
    P(f"  LOYO picks {lab}: {picks}")
    b_, fb = 0, 0
    for Y in YEARS:
        mm = m & (year == Y); b_ += wmse(tf(out), T_, mm) < wmse(tf(base), T_, mm) - 1e-12
    for Y in FWD:
        mm = m & (year == Y); fb += wmse(tf(outf), T_, mm) < wmse(tf(base), T_, mm) - 1e-12
    mf = m & np.isin(year, FWD)
    P(f"  LOYO {lab}: MSE {100*(wmse(tf(out), T_, m)/wmse(tf(base), T_, m)-1):+.2f}% ({b_}/7) | forward 2022-25 {100*(wmse(tf(outf), T_, mf)/wmse(tf(base), T_, mf)-1):+.2f}% ({fb}/4)"
      f" | MAE {100*(mae(tf(out), T_, m)/mae(tf(base), T_, m)-1):+.2f}% | rho {RG.rank_stats(tf(base), m, T_, year, wk, pos)[0]:.4f}->{RG.rank_stats(tf(out), m, T_, year, wk, pos)[0]:.4f}")
    return out, outf


def fit_script(train_years):
    """log(team volume / season-to-date mean) ~ spread + (total - 45): targets and carries"""
    rows_t, rows_c, Xs = [], [], []
    for (Y, t), ws in TWEEKS.items():
        if Y not in train_years: continue
        for j, w in enumerate(ws):
            if j < 2: continue
            prev = [TW[(Y, t, k)] for k in ws[:j]]; r = TW[(Y, t, w)]
            if np.isnan(r.spread) or np.isnan(r.total): continue
            mt = np.mean([x.tg for x in prev]); mc = np.mean([x.car for x in prev])
            if mt <= 0 or mc <= 0 or r.tg <= 0 or r.car <= 0: continue
            Xs.append([np.clip(r.spread, -14, 14), r.total - 45]); rows_t.append(np.log(r.tg / mt)); rows_c.append(np.log(r.car / mc))
    Xs = np.array(Xs); Xs1 = np.c_[np.ones(len(Xs)), Xs]
    bt = np.linalg.lstsq(Xs1, np.array(rows_t), rcond=None)[0]; bc = np.linalg.lstsq(Xs1, np.array(rows_c), rcond=None)[0]
    return (bt[1], bt[2]), (bc[1], bc[2])


def main():
    t0 = time.time()
    P("=" * 110); P("PART A - VOLUME FORECASTING (next-game xFP, targets, carries; rest-of-season xFP/g) vs the engine's read (season-to-date xFP/g)")
    P("=" * 110)
    cur = np.where(np.isnan(H["xf"]), B0, H["xf"])
    P(f"  check: engine evidence (ctx xfp_pg) vs this table's season-to-date xFP/g: corr {np.corrcoef(cur[NEXT], B0[NEXT])[0,1]:.4f}, mean {cur[NEXT].mean():.2f} vs {B0[NEXT].mean():.2f}")
    base_cfg = dict(d=1.0, comp=0, rs_t=0, ro_t=0, rs_c=0, ro_c=0, q=1.0, dy=1.0, Kt=4.0, script=None)
    variants = {}
    def V(lab, **kw):
        c = dict(base_cfg); c.update(kw); r = run(c); variants[lab] = (c, r); return r
    # baseline equivalents
    P(f"  [{time.time()-t0:.0f}s] building variants ...")
    V("team x share, plain (d 1)")
    for d in (0.9, 0.8, 0.7): V(f"recency d {d}", d=d)
    V("competitive-play shares (d 1)", comp=1)
    for rs, ro in ((0.5, 0.0), (0.7, 0.0), (0.9, 0.0), (0.7, 0.3), (1.0, 0.3)):
        V(f"availability renorm rho_s {rs} rho_o {ro}", rs_t=rs, ro_t=ro, rs_c=rs, ro_c=0.0)
    V("QB-change weight .5", q=0.5)
    V("young decay .7", dy=0.7)
    P(f"  [{time.time()-t0:.0f}s] variants built")
    m = NEXT
    P("\n--- next-game xFP: each variant vs the engine read (season-to-date xFP/g) ---")
    for lab, (c, r) in variants.items(): fold_table(lab, B0, r[0], AX, m & ~np.isnan(r[0]))
    P("\n--- next-game targets / carries vs season-to-date mean ---")
    TGm = np.array([PV[i][2] if PV[i] else np.nan for i in range(n)]); CAm = np.array([PV[i][3] if PV[i] else np.nan for i in range(n)])
    for lab in ("team x share, plain (d 1)", "recency d 0.8", "competitive-play shares (d 1)", "availability renorm rho_s 0.7 rho_o 0.0", "availability renorm rho_s 0.7 rho_o 0.3"):
        r = variants[lab][1]; mm = m & ~np.isnan(r[1])
        fold_table("TARGETS " + lab, TGm, r[1], ATG, mm & (pos != "RB") | (mm & (pos == "RB")))
        fold_table("CARRIES " + lab, CAm, r[2], ACAR, mm & (pos == "RB"))
    pickle.dump({k: (v[0], v[1]) for k, v in variants.items()}, open(os.path.join(HERE, "_tmp", "vb_variants.pkl"), "wb"))
    P(f"  [{time.time()-t0:.0f}s] part A1 done")


def grid():
    t0 = time.time(); P(chr(10) + "=" * 110); P("PART A2 - grid on recency x availability rho (targets / carries separately), LOYO-picked on next-game xFP"); P("=" * 110)
    base_cfg = dict(d=0.9, comp=0, q=1.0, dy=0.9, Kt=4.0, script=None)
    G_ = {}
    for rs_t, ro_t, rs_c in itertools.product((0.0, 0.25, 0.5), (0.0, 0.2), (0.0, 0.6, 0.8)):
        c = dict(base_cfg, rs_t=rs_t, ro_t=ro_t, rs_c=rs_c, ro_c=0.0); G_[f"d.9 rs_t {rs_t} ro_t {ro_t} rs_c {rs_c}"] = (c, run(c))
    P(f"  [{time.time()-t0:.0f}s] grid built")
    m = NEXT
    for lab, (c, r) in G_.items(): fold_table(lab, B0, r[0], AX, m & ~np.isnan(r[0]))
    pickle.dump(G_, open(os.path.join(HERE, "_tmp", "vb_grid.pkl"), "wb"))
    preds = {k: np.where(np.isnan(v[1][0]), B0, v[1][0]) for k, v in G_.items()}
    loyo_pick(preds, B0, AX, m, "next-game xFP (grid)")


BEST = dict(d=0.9, comp=0, q=1.0, dy=0.9, Kt=4.0, script=None, rs_t=0.25, ro_t=0.0, rs_c=0.6, ro_c=0.0)
NOAV = dict(BEST, rs_t=0.0, rs_c=0.0)


def cuts(lab, base, cand, T_, m, tf=lambda p: p):
    b, c = tf(base), tf(cand)
    def one(cl, mm):
        if mm.sum() < 60: return
        P(f"      {cl:22s} n{int(mm.sum()):5d} MSE {100*(wmse(c, T_, mm)/wmse(b, T_, mm)-1):+6.2f}% ({sum(1 for Y in YEARS if (mm & (year == Y)).any() and wmse(c, T_, mm & (year == Y)) < wmse(b, T_, mm & (year == Y)))}/7) act/base {T_[mm].sum()/b[mm].sum():.3f} act/cand {T_[mm].sum()/c[mm].sum():.3f}")
    P(f"    cuts: {lab}")
    for ps in SK: one(ps, m & (pos == ps))
    for lo, hi in ((1, 2), (3, 5), (6, 8), (9, 20)): one(f"games {lo}-{hi}", m & (g >= lo) & (g <= hi))
    a_ = np.where(np.isnan(adp), 999, adp)
    for lo, hi in ((1, 30), (31, 60), (61, 100), (101, 150)): one(f"ADP {lo}-{hi}", m & (a_ >= lo) & (a_ <= hi))
    for lo, hi in ((2, 4), (5, 8), (9, 13), (14, 18)): one(f"week {lo}-{hi}", m & (wk >= lo) & (wk <= hi))
    one("teammate out (pool on)", m & H["on"]); one("nobody out", m & ~H["on"])


def points():
    t0 = time.time(); P(chr(10) + "=" * 110); P("PART B - POINTS: budget alone / volume layer on the shadow / allocation layer replacing the pool boost"); P("=" * 110)
    BUD, BTG, BCAR, FT, FC = run(BEST); BUDn = run(NOAV)[0]
    # own points per xFP (season to date), shrunk K xFP to the position ratio
    rowof = defaultdict(list)
    for i in range(n): rowof[(name[i], pos[i], int(year[i]))].append(i)
    ratio = {}
    for ps in SK:
        mm = NEXT & (pos == ps); ratio[ps] = act[mm].sum() / AX[mm].sum()
    P(f"  pooled top-150 pts / xFP: {ratio}  [{time.time()-t0:.0f}s]")
    def eff(K):
        E_ = np.full(n, np.nan)
        for k, ix in rowof.items():
            ix = sorted(ix, key=lambda i: wk[i])
            for a, i in enumerate(ix):
                if not SKM[i]: continue
                pts = sum(act[j] for j in ix[:a]); xs = sum(AX[j] for j in ix[:a] if not np.isnan(AX[j]))
                E_[i] = (pts + K * ratio[pos[i]]) / (xs + K)
        return E_
    m = NEXT & ~np.isnan(BUD); mr = ROSM & ~np.isnan(BUD)
    P(chr(10) + "--- B1 budget points ALONE (budget xFP x own pts/xFP shrunk K x Vegas/FPA layers) vs the shadow ---")
    for K in (20, 60, 150):
        BP = np.where(m | mr, BUD * eff(K) * L, S)
        fold_table(f"budget alone, eff K {K} (next game)", S, BP, act, m)
        fold_table(f"budget alone, eff K {K} (rest of season)", S, BP, TR, mr, ros)
    P(chr(10) + "--- B2 VOLUME LAYER: shadow x clip((budget / season-to-date xFP)^e, .7, 1.4), RB/WR/TE ---")
    R = np.where(np.isnan(BUD) | ~(B0m > 0), 1.0, BUD / np.maximum(B0m, 1e-6)); Rn = np.where(np.isnan(BUDn) | ~(B0m > 0), 1.0, BUDn / np.maximum(B0m, 1e-6))
    Ra = np.where(np.isnan(BUD) | np.isnan(BUDn) | ~(BUDn > 0), 1.0, BUD / np.maximum(BUDn, 1e-6))
    P(f"  ratio budget/STD: mean {R[m].mean():.3f} sd {R[m].std():.3f}; availability-only ratio sd {Ra[m].std():.3f}, rows moved > 5%: {int((np.abs(Ra[m]-1) > .05).sum())}")
    predsN, predsR = {"e 0": S}, {"e 0": S}
    for e in (0.15, 0.3, 0.5, 0.75):
        C = S * np.clip(R ** e, 0.7, 1.4); predsN[f"e {e}"] = C; predsR[f"e {e}"] = C
        fold_table(f"volume layer e {e} (next game)", S, C, act, m); fold_table(f"volume layer e {e} (rest of season)", S, C, TR, mr, ros)
    Ve, Vf = loyo_pick(predsN, S, act, m, "volume layer, next game")
    loyo_pick(predsR, S, TR, mr, "volume layer, rest of season", ros)
    cuts("volume layer LOYO-picked, next game", S, Ve, act, m)
    P(chr(10) + "--- B2b volume layer WITHOUT the availability renorm (recency + team x share + shrink only) ---")
    for e in (0.3, 0.5):
        C = S * np.clip(Rn ** e, 0.7, 1.4); fold_table(f"no-renorm layer e {e} (next)", S, C, act, m); fold_table(f"no-renorm layer e {e} (ROS)", S, C, TR, mr, ros)
    P(chr(10) + "--- B3 ALLOCATION LAYER: shadow WITHOUT the pool boost x (budget(avail) / budget(no renorm))^e  vs the shadow WITH the pool (k .75) ---")
    P(f"  reference: pool boost itself (shadow vs shadow-no-pool) next game:")
    fold_table("pool boost as wired (S) vs no pool (S0)", S0, S, act, m)
    fold_table("pool boost as wired (S) vs no pool (S0), ROS", S0, S, TR, mr, ros)
    predsA, predsAR = {"pool .75 (wired)": S}, {"pool .75 (wired)": S}
    for e in (0.5, 0.75, 1.0, 1.25):
        C = S0 * np.clip(Ra ** e, 0.6, 1.8); predsA[f"alloc e {e}"] = C; predsAR[f"alloc e {e}"] = C
        fold_table(f"allocation e {e} replacing pool (next)", S, C, act, m); fold_table(f"allocation e {e} replacing pool (ROS)", S, C, TR, mr, ros)
        fold_table(f"  same, pool-on rows only (next)", S, C, act, m & H["on"])
    Ae, _ = loyo_pick(predsA, S, act, m, "allocation vs pool, next")
    loyo_pick(predsAR, S, TR, mr, "allocation vs pool, ROS", ros)
    cuts("allocation LOYO-picked, next game", S, Ae, act, m)
    P(chr(10) + "--- B4 FULL: shadow WITHOUT pool x clip((budget(avail) / season-to-date)^e) (volume + allocation in one) ---")
    predsF, predsFR = {"wired": S}, {"wired": S}
    for e in (0.3, 0.5, 0.75, 1.0):
        C = S0 * np.clip(R ** e, 0.6, 1.8); predsF[f"full e {e}"] = C; predsFR[f"full e {e}"] = C
        fold_table(f"full e {e} (next)", S, C, act, m); fold_table(f"full e {e} (ROS)", S, C, TR, mr, ros)
    Fe, _ = loyo_pick(predsF, S, act, m, "full, next"); FeR, _ = loyo_pick(predsFR, S, TR, mr, "full, ROS", ros)
    cuts("full LOYO-picked, next game", S, Fe, act, m); cuts("full LOYO-picked, ROS", S, FeR, TR, mr, ros)
    P(chr(10) + "--- vs the LIVE form (TODAY) on the same rows ---")
    fold_table("shadow vs live (next)", TODAY, S, act, m); fold_table("full LOYO vs live (next)", TODAY, Fe, act, m)
    pickle.dump(dict(BUD=BUD, BUDn=BUDn, R=R, Ra=Ra, FT=FT, FC=FC, Ve=Ve, Ae=Ae, Fe=Fe, FeR=FeR), open(os.path.join(HERE, "_tmp", "vb_points.pkl"), "wb"))
    P(f"  [{time.time()-t0:.0f}s] part B done")


if __name__ == "__main__":
    if "points" in sys.argv: points()
    elif "grid" in sys.argv: grid()
    else: main()
