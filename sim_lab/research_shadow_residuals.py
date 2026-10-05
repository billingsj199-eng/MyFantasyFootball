#!/usr/bin/env python3
"""
WHAT THE CLAY-FREE MODEL STILL MISSES IN SEASON (Jack 2026-10-02: "continue on our clay free model - what more
info do we need or what outliers / correlation with types of players overperforming or underperforming once we
are in season right now").

The Clay-free shadow in its v2.24 form (history + market prior + chart docks + learned season prior, usage and
Vegas-adjusted evidence, x Vegas x FPA; built exactly as backtest_live_candidate.py builds it) on 2019-25, half-PPR,
final week out. Residual = actual - shadow on IN-SEASON rows (2+ games played).
  1  TYPES    actual / projected by player type, with a t-stat on the per-row residual and how many of the seven
              seasons land on the same side; all in-season rows and the EARLY window (games 2-5 = where 2026 is now)
  2  SIGNALS  correlation of the residual with every pre-kickoff metric in the atlas (pbp, PFF weekly, context),
              by position; kept when |r| >= .05 and the sign repeats in 6+ of 7 seasons
Log shadow_residuals.log.
"""
import json, os, sys, warnings
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import research_clay_vs_shadow as CS
import backtest_season_long as SL
cal = NW.cal; YEARS = NW.YEARS
warnings.filterwarnings("ignore")

def build():
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, layers, adp, pid, name = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["layers"], F["adp"], A["pid"], A["name"]
    T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]
    v = SL.loyo(T, LIVE, "ridge", 10.0); key = {(int(y), nm, ps): x for y, nm, ps, x in zip(T.year, T.name, T.pos, v)}
    ridge = np.array([key.get((year[i], name[i], pos[i]), np.nan) for i in range(n)])
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    xfp = colv("xfp_pg"); ev = has & (g >= 1) & ~np.isnan(xfp); xf = np.where(ev, xfp, ppg); veg = colv("veg")
    lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    gt = colv("game_total"); z = np.zeros(n)
    for y in YEARS:
        for w_ in range(1, 19):
            m = (year == y) & (wk == w_) & ~np.isnan(gt)
            if m.sum() > 20 and gt[m].std() > 0: z[m] = np.clip((gt[m] - gt[m].mean()) / gt[m].std(), -2.5, 2.5)
    qbo = colv("qb_out") == 1
    rowof = {(name[i], pos[i], int(year[i]), int(wk[i])): i for i in range(n)}; logs = {}; ppg_v = ppg.copy()
    for i in range(n):
        if g[i] < 1: continue
        k = (name[i], pos[i], int(year[i]))
        if k not in logs:
            wrec = cal.weekly_rec(name[i], pos[i]); logs[k] = sorted((int(w["wk"]), float(w["fpts"])) for w in (wrec or {}).get("seasons", {}).get(str(int(year[i])), []) if cal.played(w) and isinstance(w.get("fpts"), (int, float)))
        L = [x for x in logs[k] if x[0] < wk[i]]
        if not L: continue
        tot = 0.0
        for w_, p_ in L:
            ri = rowof.get((name[i], pos[i], int(year[i]), w_)); vv = veg[ri] if ri is not None and not np.isnan(veg[ri]) else (layers[ri] if ri is not None else 1.0)
            tot += p_ / float(np.clip(vv, 0.6, 1.6))
        raw = sum(p_ for _, p_ in L)
        if raw > 0: ppg_v[i] = ppg[i] * float(np.clip(tot / raw, 0.75, 1.35))
    dock = lambda p: np.where((pos == "WR") & qbo, p * np.where(adp <= 60, 0.85, 0.95), p)
    tilt = lambda p: np.where(pos == "QB", p * np.exp(0.03 * z), p)
    def finish(rate):
        out = rate * layers
        for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
        return np.where(F["on"], out * np.power(F["pm"], 0.75), out)
    early = np.where((pos == "WR") & (g == 1), 5.0, 1.0)
    bl = lambda pr, evd, Pw: (Pw * pr + g * evd) / np.maximum(Pw + g, 1e-9)
    evid_v = lam * xf + (1 - lam) * ppg_v
    prior = np.where(np.isnan(ridge) | (pos == "QB"), F["prior"], 0.5 * ridge + 0.5 * F["prior"])
    SH = dock(tilt(finish(bl(prior, evid_v, F["Pvec"] * early))))
    D = pd.DataFrame({"year": year, "wk": wk, "name": name, "pos": pos, "g": g, "ppg": ppg, "act": act, "sh": SH, "prior": prior, "adp": adp, "team": A["team"],
                      "exp": A["exp"], "age": A["age"], "rookie": A["rookie"], "mover": A["mover"], "strb": F["strb"], "vac": F["on"], "layers": layers})
    for c in ("xfp_pg", "pts_over_xfp", "tgt_sh", "car_sh", "snap_std", "snap_l1", "snap_trend", "tgt_trend", "car_trend", "new_pc", "new_hc", "implied", "spread", "game_total", "ol_out_n", "rep_q", "prac_dnp", "prac_lim", "rz_tgt_sh", "gl_car_sh", "wopr", "ay_sh", "att_pg", "team_change", "ppg_py", "g_py", "draft_pick"):
        D[c] = colv(c)
    return D

def main():
    log = open(os.path.join(HERE, "shadow_residuals.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n")
    D = build()
    last = np.where(D.year <= 2020, 17, 18)
    D = D[(D.wk < last) & (D.sh >= 4)].copy(); D["res"] = D.act - D.sh
    S = D[D.g >= 2].copy()
    P(f"=== what the Clay-free model misses in season: {len(S)} player-weeks (2+ games played, shadow 4+), 2019-25 ===")
    P(f"  overall actual / projected {S.act.sum()/S.sh.sum():.3f}; by position: " + "  ".join(f"{p} {x.act.sum()/x.sh.sum():.3f}" for p, x in S.groupby("pos")))
    def line(lab, x, ref):
        if len(x) < 120: return
        r = x.act.sum() / x.sh.sum(); t = x.res.mean() / (x.res.std() / np.sqrt(len(x)))
        per = [(x[x.year == y].act.sum() / x[x.year == y].sh.sum()) for y in YEARS if (x.year == y).sum() >= 20]
        up = sum(v > ref for v in per); flag = "  <<<" if abs(t) >= 3 and (up >= len(per) - 1 or up <= 1) else ""
        P(f"    {lab:44s} n {len(x):5d}  actual / projected {r:.3f}  ({x.res.mean():+.2f} pts, t {t:+5.1f})  seasons above the position's level {up}/{len(per)}  avg proj {x.sh.mean():4.1f}{flag}")
    def cuts(title, W):
        P(f"\n--- {title} ('<<<' = |t| >= 3 and 6+ of 7 seasons on one side of the position's own level) ---")
        for pos in ("QB", "RB", "WR", "TE"):
            x = W[W.pos == pos]; ref = x.act.sum() / x.sh.sum()
            P(f"  {pos} (position level {ref:.3f}, n {len(x)})")
            start = x.ppg / x.prior.clip(lower=1)
            line("hot start: 130%+ of his prior so far", x[start >= 1.3], ref); line("cold start: under 70% of his prior", x[start < 0.7], ref)
            if pos != "QB":
                line("scoring 3+ a game ABOVE usage (xFP)", x[x.pts_over_xfp >= 3], ref); line("scoring 3+ a game BELOW usage", x[x.pts_over_xfp <= -3], ref)
                line("snap share rising (last game +8 vs season)", x[(x.snap_l1 - x.snap_std) >= 8], ref); line("snap share falling (-8)", x[(x.snap_l1 - x.snap_std) <= -8], ref)
            if pos in ("WR", "TE"):
                line("target share 24%+", x[x.tgt_sh >= .24], ref); line("target share under 12%", x[x.tgt_sh < .12], ref)
                line("target share trending up (last 3 vs season +4)", x[x.tgt_trend >= .04], ref); line("target share trending down (-4)", x[x.tgt_trend <= -.04], ref)
                line("deep role: air-yard share 35%+", x[x.ay_sh >= .35], ref)
            if pos == "RB":
                line("carry share 60%+", x[x.car_sh >= .60], ref); line("carry share under 30%", x[x.car_sh < .30], ref)
                line("pass-catching back: target share 12%+", x[x.tgt_sh >= .12], ref); line("goal-line share 60%+", x[x.gl_car_sh >= .60], ref)
                line("carry share trending up (+8)", x[x.car_trend >= .08], ref); line("carry share trending down (-8)", x[x.car_trend <= -.08], ref)
            line("rookie", x[x.rookie == True], ref); line("2nd year", x[x.exp == 1], ref); line("years 3-6", x[(x.exp >= 2) & (x.exp <= 5)], ref); line("year 8+", x[x.exp >= 7], ref)
            line("age 30+", x[x.age >= 30], ref); line("age 23 or younger", x[x.age < 24], ref)
            line("ADP top 36", x[x.adp <= 36], ref); line("ADP 37-100", x[(x.adp > 36) & (x.adp <= 100)], ref); line("ADP 101-180", x[(x.adp > 100) & (x.adp <= 180)], ref); line("no ADP", x[x.adp.isna() | (x.adp > 180)], ref)
            line("changed teams", x[x.mover == True], ref); line("new play-caller", x[x.new_pc == 1], ref)
            line("2nd string or lower on the chart", x[x.strb >= 2], ref); line("vacated-role week (teammate out)", x[x.vac == True], ref)
            line("team implied 26+", x[x.implied >= 26], ref); line("team implied under 19", x[x.implied < 19], ref)
            line("favorite by 6+", x[x.spread <= -6] if pos else x, ref); line("underdog by 6+", x[x.spread >= 6], ref)
            line("a starting lineman out (2+)", x[x.ol_out_n >= 2], ref)
    cuts("ALL in-season weeks (2+ games played)", S)
    cuts("EARLY window: games 2-5 played (where 2026 is now)", S[(S.g >= 2) & (S.g <= 5)])
    # ---- signals: residual vs every atlas metric ----
    M = pd.read_parquet(os.path.join(HERE, "data", "metric_atlas_rows.parquet"))
    skip = {"year", "name", "pos", "team", "opp", "pid", "wk", "act", "shipped", "pos_qb", "pos_rb", "pos_wr", "pos_te", "live", "res", "ros", "resRos", "base2", "clay", "ppg_over_clay"}
    mets = [c for c in M.columns if c not in skip and pd.api.types.is_numeric_dtype(M[c])]
    J = S[["year", "name", "pos", "wk", "act", "sh", "res", "g"]].rename(columns={"g": "gp"}).merge(M[["year", "name", "pos", "wk"] + mets], on=["year", "name", "pos", "wk"], how="inner")
    P(f"\n--- SIGNALS: residual (actual - shadow) vs {len(mets)} pre-kickoff metrics, {len(J)} matched in-season rows ---")
    P("    kept: |r| >= .05, same sign in 6+ of 7 seasons; '+' = players high on it BEAT the shadow, '-' = fall short; early = games 2-5")
    for pos in ("QB", "RB", "WR", "TE"):
        x = J[J.pos == pos]; out = []
        for c in mets:
            v = x[[c, "res", "year", "gp"]].dropna()
            if len(v) < 400 or v[c].std() == 0: continue
            r = np.corrcoef(v[c], v.res)[0, 1]
            if abs(r) < 0.05: continue
            per = [np.corrcoef(v[v.year == y][c], v[v.year == y].res)[0, 1] for y in YEARS if (v.year == y).sum() >= 40 and v[v.year == y][c].std() > 0]
            same = sum(np.sign(p) == np.sign(r) for p in per)
            if same < len(per) - 1: continue
            e = v[(v.gp >= 2) & (v.gp <= 5)]; re_ = np.corrcoef(e[c], e.res)[0, 1] if len(e) >= 200 and e[c].std() > 0 else np.nan
            out.append((abs(r), f"    {c:26s} r {r:+.3f}  ({same}/{len(per)} seasons)  early {re_:+.3f}  n {len(v)}"))
        P(f"  {pos} (n {len(x)}): " + ("" if out else "nothing clears the bar"))
        for _, l in sorted(out, reverse=True)[:14]: P(l)
    log.close()

if __name__ == "__main__":
    main()
