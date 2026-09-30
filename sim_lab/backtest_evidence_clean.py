#!/usr/bin/env python3
"""
CLEANING THE IN-SEASON EVIDENCE (2026-09-17). Jack: "lets build the in season evidence test".
After a few games the shadow is mostly "what has he done this season" = a flat mean of his games (plus xFP usage early).
Three things make that mean dirty; each is tested on its own and then together, inside the full shadow:
  A. OPPONENT-ADJUSTED: every past game is divided by the matchup multiplier the model itself applied to that game
     (Vegas x fantasy-points-allowed) ^ k, so 20 points against a soft defense counts for less. k = 0.5 / 1; FPA-only, Vegas-only.
  B. PARTIAL GAMES: a game whose snap share is below thr x his median share in his other games this season (injury exit,
     eased back in, blowout rest). Dropped (games count falls too) or rescaled to a full game.
  C. TEAMMATE CONTEXT: a past game played in a different context from THIS week (lead star teammate in/out - WR/TE with
     ADP <= 60 for pass catchers, RB with ADP <= 100 for backs - and the primary QB in/out) counts at weight w.
     Caveat: this week's context uses who actually played (known ~90 min before kickoff). Rows where this week is the
     NORMAL context (everyone in) are reported separately = pure evidence cleaning, no inactives knowledge needed.
Grading (Jack's rules): final week dropped; top 150 importance-weighted error vs the current shadow, seasons better of 7,
weekly within-position rank; by stage incl. the fantasy playoffs; on the rows each fix actually touches. No fitted numbers.
Log evidence_clean.log; results -> data/evidence_clean.js (SIM_EVCLEAN_BT).
"""
import json, os, sys, time, warnings
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy.stats import rankdata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import research_clay_vs_shadow as CS
import backtest_season_long as SL
cal = NW.cal
warnings.filterwarnings("ignore")
CACHE = r"E:\MyFantasyFootball\pbp_cache"

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "evidence_clean.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
YEARS, POS4 = NW.YEARS, NW.POS4
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "rows": [], "touched": [], "notes": {}}


def main():
    t0 = time.time()
    P("=== Cleaning the in-season evidence: opponent-adjusted, partial games, teammate context ===")
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, layers, adp, pid, name, team = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["layers"], F["adp"], A["pid"], A["name"], A["team"]
    T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]; lo = SL.loyo(T, LIVE, "ridge", 10.0)
    key = {(int(y), nm, ps): v for y, nm, ps, v in zip(T.year, T.name, T.pos, lo)}; r = np.array([key.get((year[i], name[i], pos[i]), np.nan) for i in range(n)])
    prior = np.where(np.isnan(r) | (pos == "QB"), F["prior"], 0.5 * r + 0.5 * F["prior"])
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    def colv(c): return np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    xfp = colv("xfp_pg"); ev = has & (g >= 1) & ~np.isnan(xfp); xf = np.where(ev, xfp, ppg)
    veg = colv("veg"); fpa = colv("fpa_mult")
    mm = ~np.isnan(veg) & ~np.isnan(fpa); P(f"  sanity: Vegas x FPA from the context file vs the harness matchup multiplier: corr {np.corrcoef((veg*fpa)[mm], layers[mm])[0,1]:.4f}, mean abs diff {np.mean(np.abs((veg*fpa)[mm]-layers[mm])):.4f}")
    lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    gt = colv("game_total"); z = np.zeros(n)
    for y in YEARS:
        for w_ in range(1, 19):
            m = (year == y) & (wk == w_) & ~np.isnan(gt)
            if m.sum() > 20 and gt[m].std() > 0: z[m] = np.clip((gt[m] - gt[m].mean()) / gt[m].std(), -2.5, 2.5)
    qbo = colv("qb_out") == 1
    def extras(p): p = np.where(pos == "QB", p * np.exp(0.03 * z), p); return np.where((pos == "WR") & qbo, p * np.where(adp <= 60, 0.85, 0.95), p)
    def finish(rate):
        out = rate * layers
        for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
        return np.where(F["on"], out * np.power(F["pm"], 0.75), out)
    PW = np.where((pos == "WR") & (g == 1), F["Pvec"] * 5, F["Pvec"])
    def shadow(pts_ev=None, g_eff=None, xf_ev=None):
        pe = ppg if pts_ev is None else pts_ev; ge = g if g_eff is None else g_eff; xe = xf if xf_ev is None else xf_ev
        evid = lam * xe + (1 - lam) * pe; return extras(finish((PW * prior + ge * evid) / np.maximum(PW + ge, 1e-9)))
    SH = shadow(); chk = extras(finish(NW.blend(prior, g, lam * xf + (1 - lam) * ppg, PW))); P(f"  sanity: manual blend == NW.blend: max abs diff {np.nanmax(np.abs(SH - chk)):.6f}")
    # ---- per-game records ----
    rowof = {(name[i], pos[i], int(year[i]), int(wk[i])): i for i in range(n)}
    snaps = defaultdict(dict); sched = {}
    for Y in YEARS:
        d = pd.read_parquet(os.path.join(CACHE, f"snap_counts_{Y}.parquet"), columns=["week", "game_type", "player", "position", "team", "opponent", "offense_pct"]); d = d[d.game_type == "REG"]
        for r_ in d[d.position.isin(["QB", "RB", "WR", "TE", "FB"])].itertuples(index=False): snaps[(Y, cal.norm(r_.player))][int(r_.week)] = 100.0 * float(r_.offense_pct)
    logs = {}
    def log_of(i):
        k = (name[i], pos[i], int(year[i]))
        if k not in logs:
            wrec = cal.weekly_rec(name[i], pos[i]); logs[k] = sorted((int(w["wk"]), float(w["fpts"])) for w in (wrec or {}).get("seasons", {}).get(str(int(year[i])), []) if cal.played(w) and isinstance(w.get("fpts"), (int, float)))
        return [x for x in logs[k] if x[0] < wk[i]]
    # ---- teammate context ----
    roster = defaultdict(set)
    for i in range(n): roster[(int(year[i]), team[i])].add((name[i], pos[i], float(adp[i]) if not np.isnan(adp[i]) else 999.0))
    def lead_star(i):
        fam = ("WR", "TE") if pos[i] in ("WR", "TE") else (("RB",) if pos[i] == "RB" else ()); cut = 60 if pos[i] in ("WR", "TE") else 100
        c = [x for x in roster[(int(year[i]), team[i])] if x[1] in fam and x[0] != name[i] and x[2] <= cut]
        return min(c, key=lambda x: x[2])[0] if c else None
    def lead_qb(i):
        c = [x for x in roster[(int(year[i]), team[i])] if x[1] == "QB" and x[0] != name[i]]
        return min(c, key=lambda x: x[2])[0] if c else None
    def played(Y, nm, w_, thr): return snaps.get((Y, cal.norm(nm)), {}).get(w_, 0.0) >= thr
    # ---- build adjusted evidence ----
    V = {}; names = []
    def add(nm): names.append(nm); V[nm] = {"pts": ppg.copy(), "g": g.astype(float).copy(), "xs": np.ones(n)}
    for nm in ("A opp-adjusted k=0.5", "A opp-adjusted k=1", "A FPA-only k=1", "A Vegas-only k=1", "B drop partial < 0.50", "B drop partial < 0.65", "B rescale partial < 0.65", "B drop partial < 0.50 (RB/WR/TE only)",
               "C context w=0.5", "C context w=0.25", "C context w=0", "C star-only w=0.5", "C QB-only w=0.5", "A k=0.5 + B drop 0.50", "A k=0.5 + B drop 0.50 + C w=0.5", "A Vegas-only k=1.5", "A Vegas-only k=2", "A Vegas-only k=3", "A Vegas-only k=1, 4+ games only"): add(nm)
    n_part = defaultdict(int); n_ctx = 0; normal_now = np.ones(n, bool); n_games = 0
    for i in range(n):
        if g[i] < 1: continue
        L = log_of(i)
        if not L: continue
        Y = int(year[i]); wks = [w_ for w_, _ in L]; pts = np.array([p_ for _, p_ in L]); ng = len(L); n_games += ng
        lay = np.ones(ng); fp_ = np.ones(ng); vg_ = np.ones(ng)
        for j, w_ in enumerate(wks):
            ri = rowof.get((name[i], pos[i], Y, w_))
            if ri is not None:
                lay[j] = np.clip(layers[ri], 0.6, 1.6)
                if not np.isnan(fpa[ri]): fp_[j] = np.clip(fpa[ri], 0.6, 1.6)
                if not np.isnan(veg[ri]): vg_[j] = np.clip(veg[ri], 0.6, 1.6)
                elif np.isnan(fpa[ri]): vg_[j] = lay[j]
        sn = np.array([snaps.get((Y, cal.norm(name[i])), {}).get(w_, np.nan) for w_ in wks])
        def partial(thr):
            out = np.zeros(ng, bool)
            for j in range(ng):
                oth = np.delete(sn, j); oth = oth[~np.isnan(oth)]
                if len(oth) >= 2 and not np.isnan(sn[j]) and np.median(oth) >= 30 and sn[j] < thr * np.median(oth): out[j] = True
            return out
        p50, p65 = partial(0.50), partial(0.65)
        star, qb = lead_star(i), (lead_qb(i) if pos[i] != "QB" else None); wnow = int(wk[i])
        s_now = played(Y, star, wnow, 20) if star else True; q_now = played(Y, qb, wnow, 50) if qb else True
        s_g = np.array([played(Y, star, w_, 20) if star else True for w_ in wks]); q_g = np.array([played(Y, qb, w_, 50) if qb else True for w_ in wks])
        normal_now[i] = bool(s_now and q_now)
        def setv(nm, w_, p_):
            sw = float(np.sum(w_))
            if sw <= 0.25: return    # nothing usable left: keep today's evidence
            v = V[nm]; v["pts"][i] = float(np.sum(w_ * p_) / sw); v["g"][i] = sw
        one = np.ones(ng)
        setv("A opp-adjusted k=0.5", one, pts / lay ** 0.5); setv("A opp-adjusted k=1", one, pts / lay); setv("A FPA-only k=1", one, pts / fp_); setv("A Vegas-only k=1", one, pts / vg_)
        for k_ in (1.5, 2, 3): setv(f"A Vegas-only k={k_:g}", one, pts / vg_ ** k_)
        if ng >= 4: setv("A Vegas-only k=1, 4+ games only", one, pts / vg_)
        setv("B drop partial < 0.50", (~p50).astype(float), pts); setv("B drop partial < 0.65", (~p65).astype(float), pts)
        if pos[i] != "QB": setv("B drop partial < 0.50 (RB/WR/TE only)", (~p50).astype(float), pts)
        med = np.nanmedian(sn) if np.any(~np.isnan(sn)) else np.nan
        setv("B rescale partial < 0.65", one, np.where(p65 & ~np.isnan(sn) & (sn > 5), pts * np.clip(med / np.maximum(sn, 1), 1, 2), pts))
        mis_s, mis_q = s_g != s_now, q_g != q_now; mis = mis_s | mis_q
        for w_c in (0.5, 0.25, 0.0): setv(f"C context w={w_c:g}", np.where(mis, w_c, 1.0), pts)
        setv("C star-only w=0.5", np.where(mis_s, 0.5, 1.0), pts); setv("C QB-only w=0.5", np.where(mis_q, 0.5, 1.0), pts)
        setv("A k=0.5 + B drop 0.50", (~p50).astype(float), pts / lay ** 0.5); setv("A k=0.5 + B drop 0.50 + C w=0.5", (~p50).astype(float) * np.where(mis, 0.5, 1.0), pts / lay ** 0.5)
        n_part["p50"] += int(p50.sum()); n_part["p65"] += int(p65.sum()); n_ctx += int(mis.sum())
    P(f"  past games scanned {n_games:,} | partial at 0.50: {n_part['p50']:,} ({100*n_part['p50']/n_games:.1f}%) | at 0.65: {n_part['p65']:,} ({100*n_part['p65']/n_games:.1f}%) | games in a different teammate context from the week being projected: {n_ctx:,} ({100*n_ctx/n_games:.1f}%)")
    RES["notes"] = {"games": n_games, "p50": n_part["p50"], "p65": n_part["p65"], "ctx": n_ctx}
    # usage evidence follows the points correction for the partial-game variants (a partial game drags xFP per game the same way)
    PRED = {}
    for nm in names:
        v = V[nm]; src = nm if nm.startswith("B drop") else "B drop partial < 0.50"
        xs = np.clip(np.where(ppg > 1, V[src]["pts"] / np.maximum(ppg, 1e-9), 1.0), 0.8, 1.5) if "B drop" in nm else np.ones(n)
        PRED[nm] = shadow(v["pts"], v["g"], xf * xs)
    # ---- grading ----
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; po = (wk >= finw - 3) & (wk < finw); top150 = adp <= 150; live = ~final & (g >= 1)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    wm = lambda q, mm_: float(np.average((q[mm_] - act[mm_]) ** 2, weights=wt[mm_]))
    def rho(p, m):
        groups = defaultdict(list)
        for i in np.where(m)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
        v = [np.corrcoef(rankdata(act[ix]), rankdata(p[ix]))[0, 1] for ix in (np.array(x) for x in groups.values()) if len(ix) >= 8]
        return float(np.mean(v)) if v else np.nan
    cuts = (("ALL weeks 2+ (no final)", live), ("weeks 2-4", live & (wk <= 4)), ("weeks 5-9", live & (wk >= 5) & (wk <= 9)), ("10 to playoffs", live & (wk >= 10) & ~po), ("PLAYOFFS", live & po), ("ADP 1-60", live & (adp <= 60)), ("ADP 61-150", live & (adp > 60)))
    base_rho = {lab: rho(SH, m & top150) for lab, m in cuts}
    P("\n=== Top 150, importance-weighted error vs the current shadow (seasons better of 7) and change in weekly rank rho; final week dropped ===")
    for nm in names:
        p = PRED[nm]; row = {"variant": nm}; cells = []
        for lab, m in cuts:
            m = m & top150; d = (wm(p, m) / wm(SH, m) - 1) * 100; wins = sum(1 for y in YEARS if wm(p, m & (year == y)) < wm(SH, m & (year == y)) - 1e-12); dr = rho(p, m) - base_rho[lab]
            row[lab] = {"d": round(d, 2), "wins": wins, "drho": round(dr, 4)}; cells.append(f"{lab}: {d:+.2f}% ({wins}/7) rho {dr:+.4f}")
        RES["rows"].append(row); P(f"  {nm:40s} " + " | ".join(cells))
    P("=== Vegas-adjusted evidence by position (top 150 weighted, weeks 2+, final week dropped) ===")
    RES["pos"] = []
    for nm in ("A Vegas-only k=1", "A Vegas-only k=2"):
        cells = []
        for ps in POS4:
            m = live & top150 & (pos == ps); p = PRED[nm]; d = (wm(p, m) / wm(SH, m) - 1) * 100; wins = sum(1 for y in YEARS if wm(p, m & (year == y)) < wm(SH, m & (year == y)) - 1e-12); dr = rho(p, m) - rho(SH, m)
            RES["pos"].append({"variant": nm, "pos": ps, "d": round(d, 2), "wins": wins, "drho": round(dr, 4)}); cells.append(f"{ps} {d:+.2f}% ({wins}/7) rho {dr:+.4f}")
        P(f"  {nm:24s} " + " | ".join(cells))
    P("\n=== On the rows each fix actually moves (projection changes by 0.3+ points), top 150: error vs the shadow on those rows, mean move, were we too high or too low before ===")
    for nm in names:
        p = PRED[nm]; m = live & top150 & (np.abs(p - SH) >= 0.3)
        if m.sum() < 50: P(f"  {nm:40s} touched {int(m.sum())} rows - too few"); continue
        d = (wm(p, m) / wm(SH, m) - 1) * 100; wins = sum(1 for y in YEARS if (m & (year == y)).sum() >= 10 and wm(p, m & (year == y)) < wm(SH, m & (year == y)))
        up = m & (p > SH); dn = m & (p < SH)
        t = {"variant": nm, "n": int(m.sum()), "pct": round(100.0 * m.sum() / (live & top150).sum(), 1), "d": round(d, 2), "wins": wins,
             "up": {"n": int(up.sum()), "act": round(float(act[up].mean()), 2), "old": round(float(SH[up].mean()), 2), "new": round(float(p[up].mean()), 2)} if up.sum() >= 20 else None,
             "dn": {"n": int(dn.sum()), "act": round(float(act[dn].mean()), 2), "old": round(float(SH[dn].mean()), 2), "new": round(float(p[dn].mean()), 2)} if dn.sum() >= 20 else None}
        RES["touched"].append(t)
        P(f"  {nm:40s} touched {t['n']:5d} ({t['pct']:4.1f}%) | {d:+.2f}% ({wins}/7) | moved UP n={up.sum()}: actual {act[up].mean() if up.any() else float('nan'):5.2f} old {SH[up].mean() if up.any() else float('nan'):5.2f} new {p[up].mean() if up.any() else float('nan'):5.2f} | moved DOWN n={dn.sum()}: actual {act[dn].mean() if dn.any() else float('nan'):5.2f} old {SH[dn].mean() if dn.any() else float('nan'):5.2f} new {p[dn].mean() if dn.any() else float('nan'):5.2f}")
    P("\n=== Teammate context, split by THIS week's situation (top 150) ===")
    for nm in ("C context w=0.5", "C context w=0", "C star-only w=0.5", "C QB-only w=0.5"):
        p = PRED[nm]
        for lab, m in (("this week NORMAL (pure evidence cleaning)", live & top150 & normal_now), ("this week a star / QB is OUT", live & top150 & ~normal_now)):
            mt = m & (np.abs(p - SH) >= 0.3); d = (wm(p, m) / wm(SH, m) - 1) * 100; wins = sum(1 for y in YEARS if wm(p, m & (year == y)) < wm(SH, m & (year == y)) - 1e-12)
            dt = (wm(p, mt) / wm(SH, mt) - 1) * 100 if mt.sum() >= 30 else float("nan")
            RES["touched"].append({"variant": nm + " | " + lab, "n": int(mt.sum()), "d": round(d, 2), "wins": wins, "dTouched": None if np.isnan(dt) else round(dt, 2)})
            P(f"  {nm:22s} {lab:42s} rows {int(m.sum()):5d} | {d:+.2f}% ({wins}/7) | touched {int(mt.sum()):4d}: {dt:+.2f}% | actual {act[mt].mean() if mt.any() else float('nan'):5.2f} old {SH[mt].mean() if mt.any() else float('nan'):5.2f} new {p[mt].mean() if mt.any() else float('nan'):5.2f}")
    P("=== Same fix on the LIVE Clay blend (Clay per-game prior, P = 5, points evidence): error vs today's Clay blend ===")
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8")); clay = A["clay"]
    gm = np.array([(ch[str(y)].get(nm_) or {}).get("gm") or 0 for y, nm_ in zip(year, name)], dtype=float)
    Wk = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * Wk / np.maximum(gm, 1), clay); CUR = NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers
    RES["live"] = []
    for nm in ("A Vegas-only k=1", "A Vegas-only k=1.5"):
        pv = NW.blend(clay_gm, g, V[nm]["pts"], NW.PRIOR_P) * layers; cells = []
        for lab, m in cuts:
            m = m & top150; d = (wm(pv, m) / wm(CUR, m) - 1) * 100; wins = sum(1 for y in YEARS if wm(pv, m & (year == y)) < wm(CUR, m & (year == y)) - 1e-12); dr = rho(pv, m) - rho(CUR, m)
            RES["live"].append({"variant": nm, "cut": lab, "d": round(d, 2), "wins": wins, "drho": round(dr, 4)}); cells.append(f"{lab}: {d:+.2f}% ({wins}/7) rho {dr:+.4f}")
        P(f"  {nm:24s} " + " | ".join(cells))
    best = min(RES["rows"], key=lambda r_: r_["ALL weeks 2+ (no final)"]["d"]); b = best["ALL weeks 2+ (no final)"]
    RES["summary"] = f"Evidence cleaning, top 150 weighted, weeks 2+ with the final week dropped: best = {best['variant']} {b['d']:+.2f}% vs the current shadow ({b['wins']}/7), rank rho {b['drho']:+.4f}; playoffs {best['PLAYOFFS']['d']:+.2f}% ({best['PLAYOFFS']['wins']}/7)."
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "evidence_clean.js"), "w", encoding="utf-8") as fh:
        fh.write("window.SIM_EVCLEAN_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/evidence_clean.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
