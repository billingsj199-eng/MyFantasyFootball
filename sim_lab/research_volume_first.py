#!/usr/bin/env python3
"""
VOLUME FIRST (Jack 2026-10-08: "how do we get the expected volume for each player/team then fill in actual production").
Build the projection the way he describes - expected TEAM volume x the player's SHARE = expected opportunities, then
production from efficiency - and grade it against the shadow, Clay's form and the blend on 2019-25.
  team volume    pass attempts / g and rush attempts / g season to date (2+ games), shrunk toward the league mean with a
                 prior worth K team games; optional game-script tilt from this week's spread
  player share   target share / carry share season to date (ctx tgt_sh, car_sh), shrunk toward last season's share with
                 a prior worth KS games; QB: team pass attempts + own rush attempts / g
  efficiency     half-PPR points per target / per carry / per pass attempt - (a) position mean (pooled), (b) the player's
                 own season-to-date efficiency shrunk toward the position mean (prior worth KE opportunities)
  oracle         ACTUAL volume this game x position-mean efficiency (the ceiling if volume were known)
Reads: the volume-first number alone; as the shadow's usage evidence in place of xFP (the shadow's lam schedule); and
averaged with the shadow. Next game + rest of season, error + rank, LOYO + forward where a weight is picked.
Log volume_first.log. Research; nothing wired.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import backtest_volume_context as VC
import rank_grade as RG
SN = BR.SN; cal = SN.NW.cal; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "volume_first.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
BBW = {"QB": 0.5, "RB": 0.8, "WR": 0.7, "TE": 0.0}
TM_ALIAS = VC.TM_ALIAS


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, g, adp, name, pid, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], A["pid"], X["team"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X); L = X["layers"]
    bw = np.array([BBW[p_] for p_ in pos]); BLEND = bw * SHADOW + (1 - bw) * TODAY
    base = top150 & ~final & ~LV["inh"]
    # ---- per player-week volume + production from the weekly logs (half-PPR pieces)
    games = {}; tcache = {}
    def wteam(Y, w, opp):
        k = (Y, w, opp)
        if k not in tcache:
            o = cal.OPP_ALIAS.get(opp, opp); t = None
            for tm_, s in cal.SCHEDULES.get(Y, {}).items():
                if s.get(str(w)) == o: t = tm_; break
            tcache[k] = t
        return tcache[k]
    keys = set((name[i], pos[i], int(year[i])) for i in range(n))
    for (nm, ps, Y) in keys:
        rec = cal.weekly_rec(nm, ps)
        if rec is None: continue
        gl = {}
        for w in rec.get("seasons", {}).get(str(Y), []):
            if not (cal.played(w) and isinstance(w.get("fpts"), (int, float))): continue
            tg, ra, pa = float(w.get("tgt") or 0), float(w.get("ra") or 0), float(w.get("pa") or 0)
            recp = 0.5 * float(w.get("rec") or 0) + 0.1 * float(w.get("rcy") or 0) + 6 * float(w.get("rctd") or 0)
            rushp = 0.1 * float(w.get("ry") or 0) + 6 * float(w.get("rtd") or 0)
            passp = 0.04 * float(w.get("py") or 0) + 4 * float(w.get("ptd") or 0) - 1 * float(w.get("int") or 0)
            gl[int(w["wk"])] = (tg, ra, pa, recp, rushp, passp, wteam(Y, int(w["wk"]), w.get("opp")))
        games[(nm, ps, Y)] = gl
    # position-mean efficiency (pooled, per opportunity)
    eff = {}
    for ps in POS4:
        tg = ra = pa = rp = up = pp = 0.0
        for (nm, p_, Y), gl in games.items():
            if p_ != ps: continue
            for v in gl.values(): tg += v[0]; ra += v[1]; pa += v[2]; rp += v[3]; up += v[4]; pp += v[5]
        eff[ps] = (rp / max(tg, 1), up / max(ra, 1), pp / max(pa, 1))
        P(f"  {ps} pooled efficiency: {eff[ps][0]:.3f} pts/target, {eff[ps][1]:.3f} pts/carry, {eff[ps][2]:.3f} pts/pass attempt")
    # team volume season to date
    TW = VC.load_team_weeks(YEARS)
    lg = {}
    for Y in YEARS:
        rows = [v for (y, t, w), v in TW.items() if y == Y]; a = np.sum(rows, axis=0); gms = len(rows)
        lg[Y] = (a[1] / gms, (a[0] - a[1]) / gms)   # league pass att / g, rush att / g per team-game
    def team_vol(i, K):
        Y = int(year[i]); rows = [TW[(Y, team[i], w)] for w in range(1, int(wk[i])) if (Y, team[i], w) in TW]
        if len(rows) < 2: return np.nan, np.nan
        a = np.sum(rows, axis=0); gms = len(rows); pa_, ra_ = a[1] / gms, (a[0] - a[1]) / gms
        return (gms * pa_ + K * lg[Y][0]) / (gms + K), (gms * ra_ + K * lg[Y][1]) / (gms + K)
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    tsh, csh, tsh_py, csh_py, spread = colv("tgt_sh"), colv("car_sh"), colv("tgt_sh_py"), colv("car_sh_py"), colv("spread")
    # own volume season to date (per game) and own efficiency
    own = {k: np.full(n, np.nan) for k in ("tg", "ra", "pa", "ptg", "pra", "ppa")}
    for i in range(n):
        gl = games.get((name[i], pos[i], int(year[i])))
        if not gl: continue
        rows = [gl[w] for w in gl if w < wk[i]]
        if not rows: continue
        a = np.sum([r[:6] for r in rows], axis=0); gm = len(rows)
        own["tg"][i], own["ra"][i], own["pa"][i] = a[0] / gm, a[1] / gm, a[2] / gm
        own["ptg"][i] = a[3] / a[0] if a[0] > 0 else np.nan; own["pra"][i] = a[4] / a[1] if a[1] > 0 else np.nan; own["ppa"][i] = a[5] / a[2] if a[2] > 0 else np.nan
    def build(K=4.0, KS=4.0, KE=None, script=0.0, use_own_vol=False):
        V = np.full(n, np.nan)
        for i in np.where(base & (g >= 1))[0]:
            ps = pos[i]; tpa, tra = team_vol(i, K)
            if np.isnan(tpa): continue
            if script and not np.isnan(spread[i]): tpa *= 1 + script * np.clip(spread[i], -10, 10) / 10.0; tra *= 1 - script * np.clip(spread[i], -10, 10) / 10.0
            e_t, e_c, e_p = eff[ps]
            if KE is not None:
                gi = max(g[i], 1)
                if not np.isnan(own["ptg"][i]): e_t = (own["tg"][i] * gi * own["ptg"][i] + KE * e_t) / (own["tg"][i] * gi + KE)
                if not np.isnan(own["pra"][i]): e_c = (own["ra"][i] * gi * own["pra"][i] + KE * e_c) / (own["ra"][i] * gi + KE)
                if not np.isnan(own["ppa"][i]): e_p = (own["pa"][i] * gi * own["ppa"][i] + KE * e_p) / (own["pa"][i] * gi + KE)
            if ps == "QB":
                V[i] = tpa * e_p + (own["ra"][i] if not np.isnan(own["ra"][i]) else 0) * e_c
            else:
                if use_own_vol:
                    tg_, ra_ = own["tg"][i], own["ra"][i]
                else:
                    s_t = tsh[i] if not np.isnan(tsh[i]) else np.nan; s_c = csh[i] if not np.isnan(csh[i]) else np.nan
                    if not np.isnan(s_t) and not np.isnan(tsh_py[i]): s_t = (g[i] * s_t + KS * tsh_py[i]) / (g[i] + KS)
                    if not np.isnan(s_c) and not np.isnan(csh_py[i]): s_c = (g[i] * s_c + KS * csh_py[i]) / (g[i] + KS)
                    tg_ = tpa * s_t if not np.isnan(s_t) else np.nan; ra_ = tra * s_c if not np.isnan(s_c) else 0.0
                if np.isnan(tg_): continue
                V[i] = tg_ * e_t + (ra_ if not np.isnan(ra_) else 0.0) * e_c
        return V
    # oracle: actual volume this game x position mean efficiency
    OR = np.full(n, np.nan)
    for i in np.where(base)[0]:
        gl = games.get((name[i], pos[i], int(year[i]))); r = gl.get(int(wk[i])) if gl else None
        if r is None: continue
        e_t, e_c, e_p = eff[pos[i]]; OR[i] = r[0] * e_t + r[1] * e_c + (r[2] * e_p if pos[i] == "QB" else 0)
    VARS = {"volume-first (team shrunk K4, share shrunk KS4, position efficiency)": build(), "+ own efficiency shrunk (KE 60)": build(KE=60.0), "+ game-script tilt .05 x spread/10": build(script=0.05),
            "own volume per game x position efficiency (no team/share model)": build(use_own_vol=True), "own volume x own efficiency shrunk": build(use_own_vol=True, KE=60.0)}
    seqn = defaultdict(list)
    for i in range(n):
        if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ix in seqn.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(L[ix], 0.5, 1.8)
        for a, i in enumerate(ix): nfut[i] = len(ix) - a; Tr[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    ctx0 = np.nan_to_num(ctx, nan=1.0); ros = lambda p: p / np.maximum(L, 0.3) * ctx0
    P(f"\n=== VOLUME FIRST: {int((base & (g >= 1)).sum()):,} top-150 in-season player-weeks 2019-25 ===")
    for hlab, T, m0, tf in (("NEXT GAME", act, base & (g >= 1), lambda p: p), ("REST OF SEASON (4+ left)", Tr, base & (g >= 1) & (g <= 10) & ~np.isnan(Tr) & (nfut >= 4), ros)):
        wm = lambda p, mm: float(np.average((p[mm] - T[mm]) ** 2, weights=wt[mm])) if mm.any() else np.nan
        RS = lambda p, mm: RG.rank_stats(p, mm, T, year, wk, pos)
        S, Cf, B = tf(SHADOW), tf(TODAY), tf(BLEND)
        P(f"\n--- {hlab} ---")
        for lab, V in list(VARS.items()) + [("ORACLE: actual volume this game x position efficiency", OR)]:
            VL = tf(np.nan_to_num(V, nan=0.0) * L); m = m0 & ~np.isnan(V) & (V > 0)
            if m.sum() < 200: P(f"  {lab}: n{int(m.sum())}"); continue
            r, pr = RS(VL, m); rs, _ = RS(S, m); rb, _ = RS(B, m)
            P(f"  {lab:66s} n{int(m.sum()):5d} | vs shadow {100*(wm(VL, m)/wm(S, m)-1):+7.2f}% | vs Clay {100*(wm(VL, m)/wm(Cf, m)-1):+7.2f}% | vs blend {100*(wm(VL, m)/wm(B, m)-1):+7.2f}% | rho {r:.3f} (shadow {rs:.3f}, blend {rb:.3f}) | level {T[m].sum()/VL[m].sum():.3f}")
            if lab.startswith("volume-first"):
                for ps in POS4:
                    mm = m & (pos == ps)
                    if mm.sum() >= 100: P(f"      {ps}: vs shadow {100*(wm(VL, mm)/wm(S, mm)-1):+7.2f}% | vs blend {100*(wm(VL, mm)/wm(B, mm)-1):+7.2f}% | rho {RS(VL, mm)[0]:.3f} (shadow {RS(S, mm)[0]:.3f}) | level {T[mm].sum()/VL[mm].sum():.3f}")
        # as the shadow's usage evidence / averaged with the shadow
        V0 = VARS["volume-first (team shrunk K4, share shrunk KS4, position efficiency)"]
        X2 = dict(X); X2["xf"] = np.where(~np.isnan(V0) & (V0 > 0), V0, X["xf"]); SV = tf(BR.shadow_current(X2)[0]); m = m0 & ~np.isnan(V0) & (V0 > 0)
        P(f"  shadow with volume-first as its usage evidence (xFP replaced): vs shadow {100*(wm(SV, m)/wm(S, m)-1):+.2f}% ({sum(1 for y in YEARS if wm(SV, m & (year == y)) < wm(S, m & (year == y)) - 1e-12)}/7) | rho {RS(SV, m)[0] - RS(S, m)[0]:+.4f}")
        VL0 = tf(np.nan_to_num(V0, nan=0.0) * L)
        for w in (0.2, 0.35, 0.5):
            E = np.where(m, (1 - w) * S + w * VL0, S)
            P(f"  shadow x volume-first average w {w:.2f}: vs shadow {100*(wm(E, m)/wm(S, m)-1):+.2f}% ({sum(1 for y in YEARS if wm(E, m & (year == y)) < wm(S, m & (year == y)) - 1e-12)}/7) | vs blend {100*(wm(E, m)/wm(B, m)-1):+.2f}% | rho {RS(E, m)[0] - RS(S, m)[0]:+.4f}")
    P("\nLimitations: efficiency pooled over all seasons (not held out); shares from ctx (season to date / prior season); team volume from pbp; layers (Vegas / FPA) multiplied on afterwards for every candidate alike; rookies / no prior-season share fall back to the season-to-date share.")
    LOG.close()


if __name__ == "__main__":
    main()
