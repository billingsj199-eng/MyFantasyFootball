#!/usr/bin/env python3
"""
2026-11-21 review follow-up (Jack: "look at proposals 2-5"): proposals 2, 4, 5 on the 2019-25 harness rows. Read-only.
Rows: sim_lab/data/metric_atlas_rows.parquet (Clay-pool player-weeks 2019-25 that were PLAYED; 'live' = shipped base x the wired
multipliers = the best historical stand-in for the engine's weekly number; it cannot replay the 2026 book anchor).
Final week of each season excluded.

P4  QB dud component: real dud rate (act < .25 x proj) by QB tier and cause (injury exit / benching / blowout / weather) vs
    RB/WR/TE; a mixture sampler (prob q of a dud draw ~ U(0, .25) x proj, gamma rescaled so the MEAN is unchanged), q fit on
    2019-22, scored 2023-25: dud calibration, p10-p90 coverage, CRPS, QB start/sit pair calibration, team-score effect.
P5  opposing-QB correlation: residual corr with season / game-total splits + bootstrap CI; engine latent structure replicated
    (CORR fV QB .63, gV .50; QB-oppQB latent = fV^2 x gV) at gV .48 / .554 / .63 -> output corr .19 / .22 / .25, other pairs.
P2  late-season consensus weight: ESPN weekly projection blended into 'live' for weeks 14-17 (and 15-17), w swept 0..1,
    leave-one-season-out; error breakdown by case (clinched team, eliminated team, weather, late usage change) and in-house
    multipliers per case fit the same way (Test B).
Writes prop245_tests.log.
"""
import json, os, re, sys, time, warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, gamma as GAM, norm as N

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); SIM = os.path.dirname(HERE); DATA = os.path.join(HERE, "data")
CACHE = r"E:\MyFantasyFootball\pbp_cache"
LOG = None   # opened by main(); importing this module never truncates prop245_tests.log
LOG_NAME = "prop245_tests.log"
RNG = np.random.default_rng(23)
POS4 = ("QB", "RB", "WR", "TE")
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX"}


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def nrm(s):
    s = str(s).lower().replace(".", "").replace("'", "").replace("-", " "); s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def fw(Y): return 17 if Y <= 2020 else 18


def espn_half(s):
    g = lambda k: float(s.get(k, 0) or 0)
    return 0.04 * g("3") + 4 * g("4") - 1 * g("20") + 0.1 * g("24") + 6 * g("25") + 0.1 * g("42") + 6 * g("43") + 0.5 * g("53") - 2 * g("72")


def load():
    M = pd.read_parquet(os.path.join(SIM, "data", "metric_atlas_rows.parquet"),
                        columns=["year", "name", "pos", "team", "opp", "pid", "wk", "act", "live", "g", "ppg", "snap_l1", "snap_std", "game_total", "implied", "spread"])
    M = M[M.wk < M.year.map(fw)].copy(); M["key"] = M.name.map(nrm)
    E = {}
    for Y in range(2019, 2026):
        d = json.load(open(os.path.join(CACHE, "espn_proj", f"espn_proj_{Y}.json"), encoding="utf-8"))
        for w, rows in d["weeks"].items():
            for k, v in rows.items():
                nm, ps = k.rsplit("|", 1); E[(Y, int(w), nrm(nm), ps)] = espn_half(v.get("s") or {})
    M["espn"] = [E.get((y, w, k, p), np.nan) for y, w, k, p in zip(M.year, M.wk, M.key, M.pos)]
    M.loc[M.espn <= 0.3, "espn"] = np.nan
    G = pd.read_parquet(os.path.join(DATA, "team_games.parquet"))
    M = M.merge(G[["season", "week", "team", "pf", "pa", "wind", "temp", "roof", "dropbacks"]].rename(columns={"season": "year", "week": "wk"}), on=["year", "wk", "team"], how="left")
    # QB share of team dropbacks (pbp) for causes
    W = pd.read_parquet(os.path.join(DATA, "player_weeks.parquet"), columns=["season", "week", "pid", "att", "car", "tgt"])
    M = M.merge(W.rename(columns={"season": "year", "week": "wk"}), on=["year", "wk", "pid"], how="left")
    # injury report next week
    inj = []
    for Y in range(2019, 2026):
        d = pd.read_parquet(os.path.join(CACHE, f"injuries_{Y}.parquet"), columns=["season", "game_type", "week", "gsis_id", "report_status"])
        inj.append(d[d.game_type == "REG"])
    I = pd.concat(inj); I = I[I.gsis_id.notna()]
    nxt = set(zip(I.season, I.week - 1, I.gsis_id))
    M["inj_next"] = [float((y, w, p) in nxt) for y, w, p in zip(M.year, M.wk, M.pid)]
    # standings before the week (wins after week-1 games)
    G = G.sort_values(["season", "team", "week"])
    G["w"] = (G.pf > G.pa).astype(float) + 0.5 * (G.pf == G.pa)
    G["wins_before"] = G.groupby(["season", "team"]).w.cumsum() - G.w
    G["gp_before"] = G.groupby(["season", "team"]).cumcount()
    M = M.merge(G[["season", "week", "team", "wins_before", "gp_before"]].rename(columns={"season": "year", "week": "wk"}), on=["year", "wk", "team"], how="left")
    return M


# ------------------------------------------------------------------ P4
def p4(M):
    P("=== Proposal 4: QB dud component (2019-25, played games) ===")
    X = M[M.live >= 3].copy()
    X["dud"] = (X.act < 0.25 * X.live).astype(float)
    X["share"] = X.att / X.dropbacks.replace(0, np.nan)
    X["band"] = pd.cut(X.live, [3, 8, 12, 16, 20, 40])
    # gamma dud rate with the band CV from TRAIN seasons (2019-22)
    def cv_of(d): return np.std(d.act - d.live) / np.mean(d.live)
    P("  real dud rate (act < .25 x projection) vs moment-matched gamma, by position / band:")
    for ps in POS4:
        parts = []
        for b, g in X[X.pos == ps].groupby("band", observed=True):
            if len(g) < 200: continue
            k = 1 / cv_of(g) ** 2; parts.append(f"{b}: real {g.dud.mean()*100:.1f}% gamma {GAM.cdf(.25, k, scale=1/k)*100:.1f}% (n{len(g)})")
        P(f"    {ps}: " + " | ".join(parts))
    Q = X[(X.pos == "QB") & (X.live >= 12)].copy()
    Q["tier"] = pd.cut(Q.live, [12, 16, 20, 40], labels=["QB 12-16", "QB 16-20", "QB 20+"])
    P("  QB duds by tier: " + " | ".join(f"{t} {g.dud.mean()*100:.1f}% (n{len(g)})" for t, g in Q.groupby("tier", observed=True)))
    d = Q[Q.dud == 1]
    blow = (d.pf - d.pa).abs() >= 21; wx = (d.wind.fillna(0) >= 15) & (d.roof.isin(["outdoors", "open"]))
    exit_ = d.share < 0.6
    P(f"  QB dud causes (n {len(d)}; not exclusive): left early / shared snaps (<60% of team dropbacks) {exit_.mean()*100:.0f}% "
      f"[of which on next week's injury report {((exit_) & (d.inj_next == 1)).mean()*100:.0f}% = injury exit, not on it {((exit_) & (d.inj_next == 0)).mean()*100:.0f}% = benching/other] | "
      f"blowout (|margin| >= 21) {blow.mean()*100:.0f}% | wind 15+ outdoors {wx.mean()*100:.0f}% | none of these {(~exit_ & ~blow & ~wx).mean()*100:.0f}%")
    P(f"  base rates in all QB12+ games: <60% share {np.mean(Q.share < .6)*100:.1f}%, blowout {np.mean((Q.pf - Q.pa).abs() >= 21)*100:.1f}%, wind 15+ {np.mean((Q.wind.fillna(0) >= 15) & Q.roof.isin(['outdoors','open']))*100:.1f}%")
    # mixture sampler test (QB rows, live >= 10), q fit on 2019-22, scored 2023-25
    Z = X[(X.pos == "QB") & (X.live >= 10)].copy()
    tr = Z[Z.year <= 2022]; te = Z[Z.year >= 2023]
    cvb = {}
    for b, g in tr.groupby("band", observed=True): cvb[b] = cv_of(g)
    def sample(df, q, n=400):
        mu = df.live.values; cv = np.array([cvb.get(b, .45) for b in df.band]); k = 1 / cv ** 2
        dud = RNG.random((n, len(df))) < q
        dv = RNG.uniform(0, .25, (n, len(df))) * mu
        mg = (mu - q * 0.125 * mu) / (1 - q)       # keeps E[X] = mu
        g = RNG.gamma(k, mg / k, (n, len(df)))
        return np.where(dud, dv, g)
    def crps(S, y):
        # sample CRPS: E|X - y| - .5 E|X - X'|
        a = np.mean(np.abs(S - y), 0); b = 0.5 * np.mean(np.abs(S[: S.shape[0] // 2] - S[S.shape[0] // 2:]), 0)
        return float(np.mean(a - b))
    best = None
    for q in (0, .01, .02, .03, .04, .05):
        S = sample(tr, q); c = crps(S, tr.act.values)
        if best is None or c < best[0]: best = (c, q)
    P(f"  mixture q picked on 2019-22 by CRPS: q = {best[1]}")
    for q in sorted(set([0, best[1], .03])):
        S = sample(te, q); lo, hi = np.quantile(S, [.1, .9], axis=0); y = te.act.values
        P(f"   2023-25 QB10+ (n {len(te)}) q {q:.2f}: dud rate real {np.mean(y < .25*te.live)*100:.1f}% sim {np.mean(S < .25*te.live.values)*100:.1f}% | p10-p90 cover {np.mean((y >= lo) & (y <= hi))*100:.1f}% (below {np.mean(y < lo)*100:.1f}) | CRPS {crps(S, y):.3f} | sim p10 avg {lo.mean():.2f}")
    # QB start/sit pairs (different games), same week, |gap| <= 5: calibration with/without
    pairs = []
    for (y, w), g in te.groupby(["year", "wk"]):
        g = g.reset_index(drop=True)
        if len(g) < 2: continue
        i, j = np.triu_indices(len(g), 1); keep = (np.abs(g.live[i].values - g.live[j].values) <= 5) & (g.team[i].values != g.opp[j].values)
        pairs.append((g, i[keep], j[keep]))
    for q in (0, best[1]):
        pp, ww = [], []
        for g, i, j in pairs:
            S = sample(g, q, 600)
            pp += list(np.mean(S[:, i] > S[:, j], 0)); ww += list((g.act.values[i] > g.act.values[j]).astype(float))
        pp, ww = np.array(pp), np.array(ww)
        fav = np.where(pp >= .5, ww, 1 - ww); pf = np.maximum(pp, 1 - pp)
        P(f"   QB start/sit pairs 2023-25 q {q:.2f}: n {len(pp)}, favourite wins {fav.mean()*100:.1f}% vs predicted {pf.mean()*100:.1f}%, Brier {np.mean((pp - ww)**2):.4f}")
    # team-score effect: extra variance a dud component adds to one QB slot
    mu = 18.0; k = 1 / .40 ** 2
    v0 = (mu / k ** .5) ** 2
    for q in (best[1], .03):
        S = sample(pd.DataFrame({"live": [mu] * 20000, "band": pd.Categorical([pd.Interval(16, 20)] * 20000)}), q, 1)[0]
        P(f"   one 18-pt QB: sd gamma {v0**.5:.2f} vs mixture q {q:.2f} {np.std(S):.2f}; P(<4.5 pts) {GAM.cdf(4.5, k, scale=mu/k)*100:.1f}% -> {np.mean(S < 4.5)*100:.1f}%; "
          f"effect on a 25-sd fantasy team score: sd {25:.1f} -> {np.sqrt(25**2 - v0 + np.var(S)):.2f}")


# ------------------------------------------------------------------ P5
def p5(M):
    P("\n=== Proposal 5: opposing-QB correlation ===")
    X = M[M.live >= 3].copy(); X["res"] = X.act - X.live
    X["prk"] = X.groupby(["year", "wk", "team", "pos"]).live.rank(ascending=False, method="first")
    q = X[(X.pos == "QB") & (X.prk == 1)][["year", "wk", "team", "opp", "res", "game_total"]]
    w1 = X[(X.pos == "WR") & (X.prk == 1)][["year", "wk", "team", "res"]].rename(columns={"res": "wr1"})
    pr = q.merge(q.rename(columns={"team": "opp", "opp": "team", "res": "ores", "game_total": "gt2"})[["year", "wk", "team", "opp", "ores"]], on=["year", "wk", "team", "opp"])
    pr = pr[pr.team < pr.opp]   # one row per game
    r = pr.res.corr(pr.ores)
    bs = [pr.sample(len(pr), replace=True, random_state=i).pipe(lambda d: d.res.corr(d.ores)) for i in range(1000)]
    P(f"  QB1-oppQB1 residual r {r:+.3f} (n {len(pr)} games), bootstrap 90% [{np.quantile(bs, .05):+.3f}, {np.quantile(bs, .95):+.3f}]")
    P("  by season: " + " ".join(f"{y}:{g.res.corr(g.ores):+.2f}(n{len(g)})" for y, g in pr.groupby("year")))
    pr["gt_t"] = pd.qcut(pr.game_total, 3, labels=["low total", "mid total", "high total"])
    P("  by game total tercile: " + " | ".join(f"{t} {g.res.corr(g.ores):+.3f} (n{len(g)})" for t, g in pr.groupby("gt_t", observed=True)))
    # QB vs opposing WR1 and WR1 vs opposing WR1
    a = q.merge(w1.rename(columns={"team": "opp", "wr1": "owr1"}), on=["year", "wk", "opp"])
    b = w1.merge(q[["year", "wk", "team", "opp"]], on=["year", "wk", "team"]).merge(w1.rename(columns={"team": "opp", "wr1": "owr1"}), on=["year", "wk", "opp"])
    P(f"  real QB1-oppWR1 r {a.res.corr(a.owr1):+.3f} (n {len(a)}) | WR1-oppWR1 r {b.wr1.corr(b.owr1):+.3f} (n {len(b)//2})")
    # engine structure replicated (playerLoading / samplePlayerScore): latent L = fV v + fH hub (QB) / fV v + fG g (WR)
    fVQ, fVW, fH, fG = .63, .24, .65, .58
    relQ = np.sqrt((.9 * .42) ** 2 + .04); relW = np.sqrt((.9 * .62 * 1.15) ** 2 + .04)
    n = 400000
    P("  engine replica (QB mean 18, WR1 mean 13, gamma marginals, 400k games):  gV | QB-oppQB | QB-oppWR1 | WR1-oppWR1 | QB-ownWR1 | sd(QB+oppWR1 stack)")
    for gV in (.48, .50, .554, .63):
        a_, b_ = np.sqrt(gV), np.sqrt(1 - gV)
        z = RNG.normal(size=n); vA = a_ * z + b_ * RNG.normal(size=n); vB = a_ * z + b_ * RNG.normal(size=n)
        gA, gB = RNG.normal(size=n), RNG.normal(size=n)      # WR1 receiver draws; hub = weight .6 on WR1 + rest
        hA = .6 * gA + .8 * RNG.normal(size=n); hB = .6 * gB + .8 * RNG.normal(size=n)
        def draw(mu, rel, L, f2):
            m = mu * np.maximum(.25, 1 + rel * L); sd = mu * rel * np.sqrt(max(.06, 1 - f2))
            k = m * m / (sd * sd); return RNG.gamma(k, (sd * sd) / m)
        QA = draw(18, relQ, fVQ * vA + fH * hA, fVQ ** 2 + fH ** 2); QB_ = draw(18, relQ, fVQ * vB + fH * hB, fVQ ** 2 + fH ** 2)
        WA = draw(13, relW, fVW * vA + fG * gA, fVW ** 2 + fG ** 2); WB = draw(13, relW, fVW * vB + fG * gB, fVW ** 2 + fG ** 2)
        c = lambda x, y: np.corrcoef(x, y)[0, 1]
        P(f"    {gV:.3f} |  {c(QA, QB_):+.3f}  |  {c(QA, WB):+.3f}   |  {c(WA, WB):+.3f}   |  {c(QA, WA):+.3f}  | {np.std(QA + WB):.2f}")
    P("  matrix validity: the loadings model is a factor model, so any gV in [0, 1] gives a valid (PSD) correlation matrix; QB f2 = .82 < 1 unchanged.")


# ------------------------------------------------------------------ P2
def p2(M):
    P("\n=== Proposal 2: late-season consensus weight (ESPN weekly projection), 2019-25 played games ===")
    X = M[(M.live >= 3) & M.espn.notna()].copy()
    years = sorted(X.year.unique())
    def mae(p, a): return float(np.mean(np.abs(p - a)))
    def rho(df, col):
        return float(np.nanmean([spearmanr(g[col], g.act).correlation for _, g in df.groupby(["year", "wk", "pos"]) if len(g) >= 12]))
    for lab, wks in (("weeks 14-17", (14, 17)), ("weeks 15-17", (15, 17))):
        L = X[X.wk.between(*wks)].copy()
        P(f"\n  {lab}: n {len(L)} ({', '.join(f'{y}:{int((L.year == y).sum())}' for y in years)})")
        grid = [0, .1, .2, .3, .4, .5, .6, .7, .8, 1.0]
        P("   in-sample sweep MAE/rho by w (share of ESPN): " + " ".join(f"{w}:{mae((1-w)*L.live + w*L.espn, L.act):.3f}/{rho(L.assign(b=(1-w)*L.live + w*L.espn), 'b'):.3f}" for w in grid))
        for ps in POS4:
            S = L[L.pos == ps]
            P(f"     {ps}: " + " ".join(f"{w}:{mae((1-w)*S.live + w*S.espn, S.act):.3f}" for w in (0, .3, .5, .7, 1.0)))
        # leave-one-season-out
        oos, base, wins, picks = [], [], 0, []
        for y in years:
            tr, te = L[L.year != y], L[L.year == y]
            wb = min(grid, key=lambda w: mae((1 - w) * tr.live + w * tr.espn, tr.act)); picks.append(wb)
            e1, e0 = mae((1 - wb) * te.live + wb * te.espn, te.act), mae(te.live, te.act)
            oos.append(e1 * len(te)); base.append(e0 * len(te)); wins += e1 < e0
        P(f"   LOYO: picked w {picks}; MAE {sum(oos)/len(L):.3f} vs engine alone {sum(base)/len(L):.3f} ({(sum(oos)/sum(base)-1)*100:+.2f}%), better in {wins}/{len(years)} seasons")
        # same comparison for weeks 5-13 (is it really a late-season effect?)
    E = X[X.wk.between(5, 13)]
    P(f"  control weeks 5-13: engine MAE {mae(E.live, E.act):.3f}, ESPN {mae(E.espn, E.act):.3f}, 50/50 {mae(.5*E.live+.5*E.espn, E.act):.3f} | weeks 14-17: engine {mae(X[X.wk>=14].live, X[X.wk>=14].act):.3f}, ESPN {mae(X[X.wk>=14].espn, X[X.wk>=14].act):.3f}")
    # where does the late gap come from? cases (weeks 15-17)
    L = X[X.wk.between(15, 17)].copy()
    sc_ = 100.0 if L.snap_std.max() > 1.5 else 1.0
    L["snap_l1"] = L.snap_l1 / sc_; L["snap_std"] = L.snap_std / sc_
    P(f"  (snap share units: /{sc_:.0f}; median season snap share {L.snap_std.median():.2f})")
    games_left = L.year.map(lambda y: fw(y) - 1) - L.gp_before
    L["clinched"] = (L.wins_before >= 11) & (L.wk >= 15)
    L["elim"] = (L.wins_before <= L.gp_before * 0.36)
    L["weather"] = (L.wind.fillna(0) >= 15) | ((L.temp.fillna(60) <= 32) & L.roof.isin(["outdoors", "open"]))
    L["usage_chg"] = (L.snap_l1 - L.snap_std).abs() >= 0.15
    L["none"] = ~(L.clinched | L.elim | L.weather | L.usage_chg)
    P("\n  weeks 15-17 by case: n | engine MAE | ESPN MAE | engine bias (act/proj) | ESPN bias")
    for c in ("clinched", "elim", "weather", "usage_chg", "none"):
        S = L[L[c]]
        if len(S) < 30: P(f"    {c:10s} n {len(S)} (too few)"); continue
        P(f"    {c:10s} n {len(S):4d} | {mae(S.live, S.act):.3f} | {mae(S.espn, S.act):.3f} | {S.act.sum()/S.live.sum():.3f} | {S.act.sum()/S.espn.sum():.3f}")
    # Test B: in-house multipliers per case + a faster usage reaction, LOYO, vs the LOYO consensus blend
    def fit_mult(tr, mask_col):
        m = tr[tr[mask_col].astype(bool)]; return float(np.clip(m.act.sum() / m.live.sum(), .85, 1.15)) if len(m) else 1.0
    tot_b, tot_0, tot_a = 0.0, 0.0, 0.0
    for y in years:
        tr, te = L[L.year != y], L[L.year == y].copy()
        adj = te.live.copy()
        for c in ("clinched", "elim", "weather"):
            k = fit_mult(tr.assign(**{c: tr[c]}), c) if tr[c].sum() >= 30 else 1.0
            adj = np.where(te[c], adj * k, adj)
        # usage reaction: shift by b x (snap_l1 - snap_std) x live, b fit on train
        tt = tr.dropna(subset=["snap_l1", "snap_std"]); xx = ((tt.snap_l1 - tt.snap_std) * tt.live).values; yy = (tt.act - tt.live).values
        bu = float(np.clip(np.sum(xx * yy) / max(np.sum(xx * xx), 1e-9), -1, 1))
        du = ((te.snap_l1 - te.snap_std) * te.live).fillna(0).values
        adj = np.maximum(0.2, adj + bu * du)
        wb = min([0, .1, .2, .3, .4, .5, .6, .7, .8, 1.0], key=lambda w: mae((1 - w) * tr.live + w * tr.espn, tr.act))
        tot_b += np.sum(np.abs(adj - te.act)); tot_0 += np.sum(np.abs(te.live - te.act)); tot_a += np.sum(np.abs((1 - wb) * te.live + wb * te.espn - te.act))
    n = len(L)
    P(f"\n  Test A vs Test B, weeks 15-17, LOYO: engine alone {tot_0/n:.3f} | (1) consensus weight {tot_a/n:.3f} ({(tot_a/tot_0-1)*100:+.2f}%) | (2) in-house case multipliers + usage reaction {tot_b/n:.3f} ({(tot_b/tot_0-1)*100:+.2f}%)")
    P("  caveat: the harness has PLAYED games only - inactives / shutdowns (where a pre-kickoff consensus 0 would score) are invisible here.")


def main():
    global LOG
    LOG = open(os.path.join(HERE, LOG_NAME), "w", encoding="utf-8")
    t0 = time.time()
    M = load()
    P(f"rows {len(M):,}; ESPN matched {M.espn.notna().mean()*100:.0f}%")
    p4(M); p5(M); p2(M); p2_level(M)
    P(f"\ndone ({time.time()-t0:.0f}s)")


def p2_level(M):
    """Test B2: an in-house LEVEL recalibration for weeks 15-17 (engine runs low late), LOYO, per position."""
    X = M[(M.live >= 3) & M.espn.notna() & M.wk.between(15, 17)].copy()
    years = sorted(X.year.unique()); tot0 = tot1 = 0.0; wins = 0; ks = []
    for y in years:
        tr, te = X[X.year != y], X[X.year == y]
        adj = te.live.copy()
        for ps in POS4:
            t = tr[tr.pos == ps]; k = float(np.clip(np.median(t.act / t.live) if False else t.act.sum() / t.live.sum(), .9, 1.1)); ks.append((y, ps, round(k, 3)))
            adj = np.where(te.pos == ps, adj * k, adj)
        e1 = np.sum(np.abs(adj - te.act)); e0 = np.sum(np.abs(te.live - te.act)); tot0 += e0; tot1 += e1; wins += e1 < e0
    P(f"\n  Test B2 (in-house late-season level per position, LOYO, weeks 15-17): {tot1/len(X):.3f} vs engine {tot0/len(X):.3f} ({(tot1/tot0-1)*100:+.2f}%), better in {wins}/{len(years)} seasons")
    P("   fitted k (season held out, pos): " + " ".join(f"{y}{p}:{k}" for y, p, k in ks if p in ('QB', 'RB')))
    # and the same multiplier on weeks 5-13 (is late low-bias special?)
    E = M[(M.live >= 3) & M.wk.between(5, 13)]
    P("   act/proj by week band, engine: " + " | ".join(f"{lab} {S.act.sum()/S.live.sum():.3f}" for lab, S in (("wk 2-4", M[(M.live>=3)&M.wk.between(2,4)]), ("wk 5-13", E), ("wk 14", M[(M.live>=3)&(M.wk==14)]), ("wk 15-17", X))))


if __name__ == "__main__":
    main()
