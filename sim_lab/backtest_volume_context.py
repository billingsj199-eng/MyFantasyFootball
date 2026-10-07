#!/usr/bin/env python3
"""
VOLUME CONTEXT (Jack 2026-10-07: "run the volume context test").  research_qb_situation.py found receivers on the
highest-attempt offenses score .925 of the live number and the lowest-attempt 1.034 - the live blend over-credits pass
volume. This splits volume into its parts and tests what the number should do about it.  RESEARCH.

Per team-week from the nflverse play-by-play 2019-25: plays, pass attempts, dropbacks, NEUTRAL-script plays and
attempts (quarters 1-3, score within 8), so season to date (weeks before this one):
   att/g              pass attempts per game               (the raw volume that correlated with the miss)
   neutral pass rate  attempts / plays when the score is close (the offense's intent)
   plays/g            pace
   script excess/g    att/g - neutral pass rate x plays/g   (attempts that came from trailing / garbage time)
Tests on the live number (WR / TE, RB as a check), 2019-25, top-150 weighted, LOYO + forward, ship bar 5/7 + 3/4:
   A  multiplier 1 - e x z(att/g)                      B  1 - e x z(script excess/g)      C  1 - e x z(neutral pass rate)
   D  1 - e x z(plays/g)                               E  expected-volume ratio this week (neutral rate x plays/g / att/g)^b
   F  A only for teams that have been trailing (negative season point differential) / only underdogs this week
   G  game-level VOLUME-CLEANED EVIDENCE: each past game's points x (team att/g / that game's team attempts)^b
Log volume_context.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_qb_injury_usage as QI
NW = QI.NW; cal = QI.cal; YEARS = QI.YEARS; POS4 = QI.POS4; FWD = QI.FWD
CACHE = r"E:\MyFantasyFootball\pbp_cache"
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "volume_context.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
TM_ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI"}


def load_team_weeks(years):
    """(Y, team, wk) -> [plays, att, neutral plays, neutral att, points for, points against]"""
    out = {}
    for Y in years:
        p = os.path.join(CACHE, f"play_by_play_{Y}.csv.gz")
        if not os.path.exists(p): continue
        d = pd.read_csv(p, compression="gzip", usecols=["week", "posteam", "defteam", "pass_attempt", "qb_dropback", "play_type", "qtr", "score_differential", "season_type", "posteam_score_post", "defteam_score_post", "game_id"], low_memory=False)
        d = d[(d.season_type == "REG") & d.posteam.notna() & d.play_type.isin(["pass", "run"])]
        d["neutral"] = (d.qtr <= 3) & (d.score_differential.abs() <= 8)
        for (tm, wk), grp in d.groupby(["posteam", "week"]):
            nt = grp[grp.neutral]; last = grp.sort_values("game_id").iloc[-1]
            out[(Y, TM_ALIAS.get(str(tm), str(tm)), int(wk))] = np.array([len(grp), grp.pass_attempt.sum(), len(nt), nt.pass_attempt.sum(), float(grp.posteam_score_post.max() if grp.posteam_score_post.notna().any() else 0), float(grp.defteam_score_post.max() if grp.defteam_score_post.notna().any() else 0)])
        P(f"  pbp {Y}: {len(d):,} plays")
    return out


def main():
    TW = load_team_weeks(YEARS)
    X = QI.setup(); n = X["n"]
    act, year, wk, pos, g, adp, name, team, pid = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["team"], X["pid"]
    F = X["F"]; finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    games, roster, starter, team_weeks = QI.build_games(X)
    b_, lk_ = QI.live_base(X, X["ppg"], g.astype(float), X["xfp"], X["snap"]); BASE = np.maximum(0.0, b_ * X["chain"] + lk_)
    okN = (g >= 1) & ~final & ~X["inh"] & (BASE >= 3)
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    spread = np.where(has, C["spread"].values[np.maximum(idx, 0)], np.nan).astype(float)
    # season-to-date team volume parts per row
    MET = ("attpg", "neutral_rate", "playspg", "excess", "ptdiff", "exp_ratio")
    M = {k: np.full(n, np.nan) for k in MET}
    for i in range(n):
        if not okN[i] or not team[i]: continue
        Y = int(year[i]); rows = [TW[(Y, team[i], w)] for w in range(1, int(wk[i])) if (Y, team[i], w) in TW]
        if len(rows) < 2: continue
        a = np.sum(rows, axis=0); gms = len(rows)
        attpg = a[1] / gms; playspg = a[0] / gms; nrate = a[3] / max(a[2], 1)
        M["attpg"][i] = attpg; M["playspg"][i] = playspg; M["neutral_rate"][i] = nrate; M["excess"][i] = attpg - nrate * playspg
        M["ptdiff"][i] = (a[4] - a[5]) / gms; M["exp_ratio"][i] = (nrate * playspg) / max(attpg, 1)
    RECV = np.isin(pos, ("WR", "TE"))
    Z = {k: np.full(n, np.nan) for k in MET}
    for k in MET:
        for y in YEARS:
            for w in range(1, 19):
                m = okN & (year == y) & (wk == w) & ~np.isnan(M[k]) & RECV
                if m.sum() >= 20 and np.nanstd(M[k][m]) > 0: Z[k][m] = np.clip((M[k][m] - np.nanmean(M[k][m])) / np.nanstd(M[k][m]), -2.5, 2.5)
    ratio = np.where(BASE > 0, act / BASE, np.nan)
    base_m = okN & RECV & top150 & ~np.isnan(M["attpg"])
    P(f"\n=== VOLUME CONTEXT: {int(base_m.sum()):,} WR/TE top-150 player-weeks with 2+ prior team games (week 1-2 rows excluded by construction) ===")
    P("\n--- 1  Spearman of actual / live with each volume part (WR, TE, RB; top 150) and quintile read ---")
    for k in MET:
        cells = []
        for ps in ("WR", "TE", "RB"):
            m = okN & (pos == ps) & top150 & ~np.isnan(M[k])
            cells.append(f"{ps} {spearmanr(M[k][m], ratio[m]).correlation:+.3f} (n{int(m.sum())})")
        m = base_m & ~np.isnan(Z[k]); q = np.nanpercentile(Z[k][m], [20, 40, 60, 80]); edges = [-9] + list(q) + [9]; qs = []
        for a in range(5):
            mm = m & (Z[k] >= edges[a]) & (Z[k] < edges[a + 1]); qs.append(f"{act[mm].sum()/BASE[mm].sum():.3f}")
        P(f"    {k:13s} " + " | ".join(cells) + f" | WR+TE act/live by quintile low->high: {' '.join(qs)} | metric Q1 {np.nanmean(M[k][m & (Z[k] < edges[1])]):.2f} -> Q5 {np.nanmean(M[k][m & (Z[k] >= edges[4])]):.2f}")
    P("    cross-cut: att/g quintile x point differential (trailing teams throw more): act/live")
    m = base_m & ~np.isnan(Z["attpg"]) & ~np.isnan(M["ptdiff"])
    for lab, mm0 in (("trailing teams (pt diff < -3/g)", M["ptdiff"] < -3), ("even (-3..+3)", (M["ptdiff"] >= -3) & (M["ptdiff"] <= 3)), ("leading teams (> +3/g)", M["ptdiff"] > 3)):
        cells = []
        for ql, qm in (("low att", Z["attpg"] < -0.5), ("mid", (Z["attpg"] >= -0.5) & (Z["attpg"] <= 0.5)), ("high att", Z["attpg"] > 0.5)):
            mm = m & mm0 & qm; cells.append(f"{ql}: {act[mm].sum()/BASE[mm].sum():.3f} (n{int(mm.sum())})" if mm.sum() >= 40 else f"{ql}: n{int(mm.sum())}")
        P(f"      {lab:32s} " + " | ".join(cells))
    # ---------------- multiplier tests
    wm = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    def test(title, preds, m):
        names = list(preds); pick = lambda yrs: min(names, key=lambda kk: wm(preds[kk], m & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = BASE.copy()
            for tr_, te in folds:
                kk = pick(tr_); picks.append(kk); mm = year == te; pr[mm] = preds[kk][mm]; wins += wm(preds[kk], m & mm) < wm(BASE, m & mm) - 1e-12
            tem = np.isin(year, [te for _, te in folds]); return pr, 100 * (wm(pr, m & tem) / wm(BASE, m & tem) - 1), wins, picks
        lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
        fixed = "  ".join(f"{kk}: {100*(wm(preds[kk], m)/wm(BASE, m)-1):+.2f}% ({sum(1 for y in YEARS if wm(preds[kk], m & (year == y)) < wm(BASE, m & (year == y)) - 1e-12)}/7)" for kk in names[1:])
        okk = best != "off" and lo[2] >= 5 and lo[1] < -0.3 and fw[2] >= 3 and fw[1] < 0
        P(f"\n  {title}  (rows {int(m.sum()):,}, actual/live {act[m].sum()/BASE[m].sum():.3f})")
        P(f"    fixed: {fixed}")
        pb = preds[best]
        P(f"    best fixed {best}: WR {100*(wm(pb, m & (pos == 'WR'))/wm(BASE, m & (pos == 'WR'))-1):+.2f}% | TE {100*(wm(pb, m & (pos == 'TE'))/wm(BASE, m & (pos == 'TE'))-1):+.2f}% | ADP<=60 {100*(wm(pb, m & (adpx <= 60))/wm(BASE, m & (adpx <= 60))-1):+.2f}% | 61-150 {100*(wm(pb, m & (adpx > 60))/wm(BASE, m & (adpx > 60))-1):+.2f}% | weeks 3-6 {100*(wm(pb, m & (wk <= 6))/wm(BASE, m & (wk <= 6))-1):+.2f}% | 7+ {100*(wm(pb, m & (wk >= 7))/wm(BASE, m & (wk >= 7))-1):+.2f}%")
        P(f"    LOYO {lo[1]:+.2f}% {lo[2]}/7 picks {lo[3]}")
        P(f"    FWD  {fw[1]:+.2f}% {fw[2]}/4 picks {fw[3]}")
        P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
        return best
    def zmult(k, grid, sign=-1.0, scope=None):
        m = base_m & ~np.isnan(Z[k]) if scope is None else scope & ~np.isnan(Z[k])
        preds = {"off": BASE}
        for e in grid:
            p = BASE.copy(); p[m] = BASE[m] * np.clip(1 + sign * e * Z[k][m], 0.8, 1.2); preds[f"e {e}"] = p
        return preds, m
    G = (0.02, 0.03, 0.04, 0.06)
    for title, k in (("A  1 - e x z(team pass attempts per game)", "attpg"), ("B  1 - e x z(script excess attempts per game)", "excess"), ("C  1 - e x z(neutral pass rate)", "neutral_rate"), ("D  1 - e x z(plays per game)", "playspg")):
        preds, m = zmult(k, G); test(title, preds, m)
    # E expected-volume ratio this week
    m = base_m & ~np.isnan(M["exp_ratio"]); preds = {"off": BASE}
    for b in (0.25, 0.5, 1.0):
        p = BASE.copy(); p[m] = BASE[m] * np.clip(M["exp_ratio"][m], 0.7, 1.3) ** b; preds[f"b {b}"] = p
    test("E  x (neutral pass rate x plays/g / att/g)^b  = replace realized volume with intent x pace", preds, m)
    # F conditional
    preds, m = zmult("attpg", G, scope=base_m & (M["ptdiff"] < -3)); test("F1 A on TRAILING teams only (season point diff < -3/g)", preds, m)
    preds, m = zmult("attpg", G, scope=base_m & (M["ptdiff"] >= -3)); test("F2 A on even / leading teams only", preds, m)
    preds, m = zmult("attpg", G, scope=base_m & ~np.isnan(spread) & (spread > 0)); test("F3 A on this week's UNDERDOGS only", preds, m)
    preds, m = zmult("attpg", G, scope=base_m & ~np.isnan(spread) & (spread <= 0)); test("F4 A on this week's FAVORITES only", preds, m)
    preds, m = zmult("excess", G, scope=base_m & ~np.isnan(spread) & (spread <= 0)); test("F5 B (script excess) on FAVORITES only", preds, m)
    # G game-level volume-cleaned evidence
    P("\n--- G  VOLUME-CLEANED EVIDENCE: each past game's points x (team att/g to date / team attempts in that game)^b, WR + TE ---")
    seq = defaultdict(list)
    for i in range(n): seq[(name[i], pos[i], int(year[i]))].append(i)
    def cleaned(b):
        ppg = X["ppg"].copy()
        for i in np.where(okN & RECV & (g >= 2))[0]:
            key = (name[i], pos[i], int(year[i])); Y = int(year[i])
            if key not in games: continue
            tm_, cpg, gl = games[key]; evw = [w for w in sorted(gl) if w < wk[i]]
            if len(evw) != int(g[i]): continue
            atts = [TW[(Y, gl[w][1], w)][1] if gl[w][1] and (Y, gl[w][1], w) in TW else np.nan for w in evw]
            if any(np.isnan(atts)): continue
            avg = np.mean(atts); fs = np.array([gl[w][0] for w in evw])
            ppg[i] = max(0.0, float(np.mean(fs * np.clip(avg / np.maximum(np.array(atts), 10.0), 0.6, 1.6) ** b)))
        return ppg
    m = base_m & (g >= 2); preds = {"off": BASE}
    for b in (0.25, 0.5, 0.75):
        pp = cleaned(b); bb, ll = QI.live_base(X, pp, g.astype(float), X["xfp"], X["snap"]); preds[f"b {b}"] = np.maximum(0.0, bb * X["chain"] + ll)
    test("G  volume-cleaned evidence (points regressed for the game's team attempts)", preds, m)
    # ---------------- H  the two passes together, whole board, by season
    P(chr(10) + "--- H  STACK CHECK: B (script excess e .04, all WR/TE) and F3 (att/g e .06, underdogs only), alone and together; whole top-150 board and by season ---")
    zb, za = Z["excess"], Z["attpg"]; und = ~np.isnan(spread) & (spread > 0)
    def mk(useB, useF, eb=0.04, ef=0.06):
        p = BASE.copy(); m = base_m
        if useB: mm = m & ~np.isnan(zb); p[mm] = p[mm] * np.clip(1 - eb * zb[mm], 0.8, 1.2)
        if useF: mm = m & und & ~np.isnan(za); p[mm] = p[mm] * np.clip(1 - ef * za[mm], 0.8, 1.2)
        return p
    allb = okN & top150
    for lab, p in (("B only", mk(True, False)), ("F3 only", mk(False, True)), ("B + F3", mk(True, True)), ("F3 at e .04", mk(False, True, ef=0.04)), ("B .03 + F3 .04", mk(True, True, 0.03, 0.04))):
        d = 100 * (wm(p, allb) / wm(BASE, allb) - 1); wins = sum(1 for y in YEARS if wm(p, allb & (year == y)) < wm(BASE, allb & (year == y)) - 1e-12)
        dr = 100 * (wm(p, base_m) / wm(BASE, base_m) - 1); wr = sum(1 for y in YEARS if wm(p, base_m & (year == y)) < wm(BASE, base_m & (year == y)) - 1e-12)
        fw = 100 * (wm(p, base_m & (year >= 2022)) / wm(BASE, base_m & (year >= 2022)) - 1); fwins = sum(1 for y in FWD if wm(p, base_m & (year == y)) < wm(BASE, base_m & (year == y)) - 1e-12)
        mv = np.abs(p - BASE) > 1e-9
        P(f"    {lab:16s} whole board {d:+.3f}% ({wins}/7) | WR/TE rows {dr:+.2f}% ({wr}/7) | 2022-25 {fw:+.2f}% ({fwins}/4) | by season " + " ".join(f"{y}:{100*(wm(p, base_m & (year == y))/wm(BASE, base_m & (year == y))-1):+.1f}" for y in YEARS) + f" | moved {int(mv.sum())} rows, mean |d| {np.mean(np.abs(p - BASE)[mv]):.2f}, max {np.max(np.abs(p - BASE)):.2f}")
    P("\nLimitations: team volume parts from the play-by-play, season to date (2+ team games); neutral = quarters 1-3 within 8 points; the live number's Vegas / FPA layers are inside BASE; RB rows only in the correlation table.")
    LOG.close()


if __name__ == "__main__":
    main()
