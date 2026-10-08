#!/usr/bin/env python3
"""
NEXT GEN STATS SCREEN (Jack 2026-10-08: "what stats or analytics have we not tested for all positions, separation score?").
The tracking family is the one not in the metric atlas (108) or the PFF Pro screen (127): nflverse nextgen_stats weekly,
2019-25 (REG), pbp_cache/ngs/ngs_{receiving,rushing,passing}.parquet.
  receiving (WR / TE / RB)  avg_separation, avg_cushion, avg_intended_air_yards, percent_share_of_intended_air_yards,
                            avg_yac_above_expectation, avg_expected_yac, catch_percentage
  rushing   (RB / QB)       efficiency, percent_attempts_gte_eight_defenders, avg_time_to_los,
                            rush_yards_over_expected_per_att, rush_pct_over_expected
  passing   (QB)            avg_time_to_throw, aggressiveness, avg_air_yards_differential, avg_air_yards_to_sticks,
                            completion_percentage_above_expectation, avg_intended_air_yards, max_completed_air_distance
  team      (QB)            targets-weighted separation / cushion of his receivers (what the QB throws into)
Two readings per metric: SEASON TO DATE (weeks before this one, volume-weighted, 2+ weeks, minimum volume) and PRIOR SEASON
(the week-0 season row of year - 1). Base = blend as wired on the honest replica. Screen = Spearman of actual / base with the
within-week z by position, quintiles, rest-of-season residual; then multipliers 1 + e x z (sign from the correlation) with the
ship bar (LOYO 5/7 + forward 3/4, whole-board guard) and the rank line. Log ngs_screen.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
NGS = r"E:\MyFantasyFootball\pbp_cache\ngs"
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "ngs_screen.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
BBW = {"QB": 0.5, "RB": 0.8, "WR": 0.7, "TE": 0.0}
TM_ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI"}
FAM = {"receiving": (("avg_separation", "avg_cushion", "avg_intended_air_yards", "percent_share_of_intended_air_yards", "avg_yac_above_expectation", "avg_expected_yac", "catch_percentage"), "targets", 10, ("WR", "TE", "RB")),
       "rushing": (("efficiency", "percent_attempts_gte_eight_defenders", "avg_time_to_los", "rush_yards_over_expected_per_att", "rush_pct_over_expected"), "rush_attempts", 15, ("RB", "QB")),
       "passing": (("avg_time_to_throw", "aggressiveness", "avg_air_yards_differential", "avg_air_yards_to_sticks", "completion_percentage_above_expectation", "avg_intended_air_yards", "max_completed_air_distance"), "attempts", 30, ("QB",))}


def load():
    W = {}; S0 = {}; TEAM = defaultdict(lambda: defaultdict(float))   # W[(fam)][(Y, gsis, wk)] = (metrics tuple, weight); S0[(fam)][(Y, gsis)] = season row metrics; TEAM[(Y, tm, wk)] = {sep_sum, cush_sum, tgt}
    for fam, (mets, wcol, _, _) in FAM.items():
        d = pd.read_parquet(os.path.join(NGS, f"ngs_{fam}.parquet")); d = d[(d.season_type == "REG") & d.player_gsis_id.notna()]
        W[fam] = {}; S0[fam] = {}
        for r in d.itertuples(index=False):
            Y, w, gid = int(r.season), int(r.week), str(r.player_gsis_id); vals = tuple(float(getattr(r, m)) if pd.notna(getattr(r, m)) else np.nan for m in mets); wv = float(getattr(r, wcol) or 0)
            if w == 0: S0[fam][(Y, gid)] = vals
            else:
                W[fam][(Y, gid, w)] = (vals, wv)
                if fam == "receiving" and wv > 0 and pd.notna(r.avg_separation):
                    t = TEAM[(Y, TM_ALIAS.get(str(r.team_abbr), str(r.team_abbr)), w)]; t["sep"] += r.avg_separation * wv; t["cush"] += (r.avg_cushion if pd.notna(r.avg_cushion) else 0) * wv; t["tgt"] += wv
        P(f"  {fam}: {len(W[fam]):,} player-weeks, {len(S0[fam]):,} season rows, seasons {sorted(d.season.unique())}")
    return W, S0, TEAM


def main():
    W, S0, TEAM = load()
    X = SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, g, adp, name, pid, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], A["pid"], X["team"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    bw = np.array([BBW[p_] for p_ in pos]); BASE = bw * SHADOW + (1 - bw) * TODAY
    ok = (g >= 1) & ~final & ~LV["inh"] & top150 & (BASE >= 3); ok0 = ~final & ~LV["inh"] & top150 & (BASE >= 3)
    # rest-of-season target / context
    seqn = defaultdict(list)
    for i in range(n):
        if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ix in seqn.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(X["layers"][ix], 0.5, 1.8)
        for a, i in enumerate(ix): nfut[i] = len(ix) - a; Tr[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    ctx0 = np.nan_to_num(ctx, nan=1.0); BASE_R = BASE / np.maximum(X["layers"], 0.3) * ctx0; okR = ok & ~np.isnan(Tr) & (nfut >= 4) & (g <= 10)
    # ---- metric columns
    M = {}   # (label) -> array
    for fam, (mets, wcol, wmin, poss) in FAM.items():
        for k, mname in enumerate(mets):
            std = np.full(n, np.nan); py = np.full(n, np.nan)
            for i in range(n):
                if pos[i] not in poss or not isinstance(pid[i], str): continue
                Y = int(year[i])
                if ok[i]:
                    num = den = 0.0; nw = 0
                    for w in range(1, int(wk[i])):
                        r = W[fam].get((Y, pid[i], w))
                        if r is None or np.isnan(r[0][k]) or r[1] <= 0: continue
                        num += r[0][k] * r[1]; den += r[1]; nw += 1
                    if nw >= 2 and den >= wmin: std[i] = num / den
                if ok0[i]:
                    s = S0[fam].get((Y - 1, pid[i]))
                    if s is not None and not np.isnan(s[k]): py[i] = s[k]
            M[f"{mname} [std]"] = (std, poss); M[f"{mname} [prior season]"] = (py, poss)
    # team-level: receivers' separation / cushion the QB throws into (season to date)
    for lab, key in (("team receiver separation [std]", "sep"), ("team receiver cushion [std]", "cush")):
        v = np.full(n, np.nan)
        for i in np.where(ok & (pos == "QB"))[0]:
            Y = int(year[i]); num = den = 0.0; nw = 0
            for w in range(1, int(wk[i])):
                t = TEAM.get((Y, team[i], w))
                if not t or t["tgt"] <= 0: continue
                num += t[key]; den += t["tgt"]; nw += 1
            if nw >= 2 and den >= 40: v[i] = num / den
        M[lab] = (v, ("QB",))
    def zweek(v, grp):
        z = np.full(n, np.nan)
        for y in YEARS:
            for w in range(1, 19):
                m = ok0 & (year == y) & (wk == w) & ~np.isnan(v) & grp
                if m.sum() >= 12 and np.nanstd(v[m]) > 0: z[m] = np.clip((v[m] - np.nanmean(v[m])) / np.nanstd(v[m]), -2.5, 2.5)
        return z
    ratio = np.where(BASE > 0, act / BASE, np.nan); ratioR = np.where(BASE_R > 0, Tr / BASE_R, np.nan)
    wm = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    P(f"\n=== NEXT GEN STATS SCREEN: {int(ok.sum()):,} top-150 player-weeks 2019-25 (in-season rows), base = blend as wired (honest replica) ===")
    P("\n--- 1  Spearman of actual / base with each metric's within-week z (next game | rest of season), by position; |rho| >= .05 flagged ---")
    P(f"    {'metric':48s} " + " ".join(f"{ps:>24s}" for ps in POS4))
    leads = []
    for lab, (v, poss) in M.items():
        cells = []
        for ps in POS4:
            if ps not in poss: cells.append(f"{'':>24s}"); continue
            z = zweek(v, pos == ps); m = ok0 & (pos == ps) & ~np.isnan(z) & ~np.isnan(ratio); mR = okR & (pos == ps) & ~np.isnan(z) & ~np.isnan(ratioR)
            if m.sum() < 150: cells.append(f"{'n' + str(int(m.sum())):>24s}"); continue
            r = spearmanr(z[m], ratio[m]).correlation; rR = spearmanr(z[mR], ratioR[mR]).correlation if mR.sum() >= 150 else np.nan
            cells.append(f"{r:+.3f}{'*' if abs(r) >= 0.05 else ' '}|{rR:+.3f}{'*' if abs(rR) >= 0.05 else ' '} n{int(m.sum()):<5d}")
            if abs(r) >= 0.04 or abs(rR) >= 0.06: leads.append((lab, ps, r, rR, int(m.sum())))
        P(f"    {lab:48s} " + " ".join(cells))
    P("\n--- 2  QUINTILES (actual / base low -> high) for the flagged leads ---")
    for lab, ps, r, rR, nn in leads:
        v, _ = M[lab]; z = zweek(v, pos == ps); m = ok0 & (pos == ps) & ~np.isnan(z); q = np.nanpercentile(z[m], [20, 40, 60, 80]); e = [-9] + list(q) + [9]
        cells = [f"{act[m & (z >= e[a]) & (z < e[a+1])].sum()/BASE[m & (z >= e[a]) & (z < e[a+1])].sum():.3f}" for a in range(5)]
        P(f"    {lab:48s} {ps} rho {r:+.3f} ros {rR:+.3f} | {' '.join(cells)} | metric {np.nanmean(v[m & (z < e[1])]):.2f} -> {np.nanmean(v[m & (z >= e[4])]):.2f}")
    P("\n--- 3  MULTIPLIERS 1 + e x z (sign from the correlation) on the flagged leads; LOYO + forward; bar 5/7 + 3/4, whole-board guard; rank line ---")
    for lab, ps, r, rR, nn in leads:
        v, _ = M[lab]; z = zweek(v, pos == ps); m = ok0 & (pos == ps) & ~np.isnan(z); sgn = 1.0 if r > 0 else -1.0
        preds = {"off": BASE}
        for e_ in (0.01, 0.02, 0.03, 0.04, 0.06): p = BASE.copy(); p[m] = BASE[m] * np.clip(1 + sgn * e_ * z[m], 0.85, 1.15); preds[f"e {e_}"] = p
        names = list(preds); pick = lambda yrs: min(names, key=lambda kk: wm(preds[kk], m & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = BASE.copy()
            for tr_, te in folds:
                kk = pick(tr_); picks.append(kk); mm = year == te; pr[mm] = preds[kk][mm]; wins += wm(preds[kk], m & mm) < wm(BASE, m & mm) - 1e-12
            tem = np.isin(year, [te for _, te in folds]); return 100 * (wm(pr, m & tem) / wm(BASE, m & tem) - 1), 100 * (wm(pr, ok0 & tem) / wm(BASE, ok0 & tem) - 1), wins, picks
        lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
        fixed = "  ".join(f"{kk}: {100*(wm(preds[kk], m)/wm(BASE, m)-1):+.2f}% ({sum(1 for y in YEARS if wm(preds[kk], m & (year == y)) < wm(BASE, m & (year == y)) - 1e-12)}/7)" for kk in names[1:])
        okk = best != "off" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
        P(f"\n  {lab} | {ps} (rho {r:+.3f}, sign {'+' if sgn > 0 else '-'}, rows {int(m.sum()):,})")
        P(f"    fixed: {fixed}")
        P("    " + RG.rank_line(preds, m, act, year, wk, pos))
        P(f"    LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | picks {lo[3]}"); P(f"    FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}"); P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
    P("\nLimitations: NGS weekly rows exist only for players over the weekly minimums (the std read needs 2+ qualifying weeks); prior-season = the week-0 season row; the blend already carries Vegas / FPA / usage; book anchor / docks not replayed.")
    LOG.close()


if __name__ == "__main__":
    main()
