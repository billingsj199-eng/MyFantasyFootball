#!/usr/bin/env python3
"""
2026-11-21 review - decision-level backtests (read-only on every live file; writes only preseason2027/decisions_backtest.log).

  A  START/SIT pairs 2019-25: when the model says start A over B (same position, or RB/WR/TE flex), how often A outscored B,
     calibration of P(A > B) from a fitted spread model, and the head-to-head vs ESPN's weekly projection and season-to-date PPG.
     Model = the harness 'live' number (metric_atlas_rows: shipped base x the wired multipliers; the best historical stand-in
     for the live engine; it cannot replay the 2026 book anchor).
  B  ROS RANKINGS by week 2019-25: Spearman / top-12 / top-24 of the week-k number vs actual per-game rest of season, against
     season-to-date PPG, preseason ADP and ESPN's week-k projection; crossover weeks; reaction to the last game.
  C  DISTRIBUTION SHAPE for best ball / DFS: CV and spike / dud rates by projection band, real vs a moment-matched gamma, half-PPR
     and DraftKings scoring; weekly residual correlations of teammates / opponents.
  D  FORMAT VALUE (superflex, 2QB, TE premium 1.5 / 1.75 / 2.0, league size): season VOR 2015-25 by format.
  E  KEEPER surplus 2016-25: keep-at-last-year's-round cost vs this year's value, market-implied vs realized.
  F  DYNASTY: age curves (delta method, survivors only, with a survivorship note) and 1-3 year value persistence.
  G  DEVY / PROSPECT: JM score vs draft capital for NFL years 1-3 (hindsight caveat: JM weights were tuned on these classes).
  H  LEAGUE matchup odds 2026: the stored newspaper moneylines (weeks 5, 6, 10) vs the real results in the ESPN pulls.
"""
import glob, json, os, re, sys, time, traceback, warnings
import numpy as np
import pandas as pd
from scipy.stats import norm as N, spearmanr, gamma as GAM

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(HERE, "data"); SIM = os.path.dirname(HERE)
CACHE = r"E:\MyFantasyFootball\pbp_cache"; LE = r"E:\MyFantasyFootball\league_exports\newspaper\cache"
LOG = None   # opened by main(); importing this module never truncates decisions_backtest.log
LOG_NAME = "decisions_backtest.log"
POS4 = ("QB", "RB", "WR", "TE")


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def nrm(s):
    s = str(s).lower().replace(".", "").replace("'", "").replace("-", " "); s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def final_week(Y): return 17 if Y <= 2020 else 18


def espn_half(s):
    g = lambda k: float(s.get(k, 0) or 0)
    return 0.04 * g("3") + 4 * g("4") - 1 * g("20") + 0.1 * g("24") + 6 * g("25") + 0.1 * g("42") + 6 * g("43") + 0.5 * g("53") - 2 * g("72")


def load_rows():
    M = pd.read_parquet(os.path.join(SIM, "data", "metric_atlas_rows.parquet"), columns=["year", "name", "pos", "team", "opp", "pid", "wk", "act", "live", "g", "ppg"])
    M = M[M.wk < M.year.map(final_week)].copy(); M["key"] = M.name.map(nrm)
    E = {}
    for Y in range(2019, 2026):
        d = json.load(open(os.path.join(CACHE, "espn_proj", f"espn_proj_{Y}.json"), encoding="utf-8"))
        for w, rows in d["weeks"].items():
            for k, v in rows.items():
                nm, ps = k.rsplit("|", 1); E[(Y, int(w), nrm(nm), ps)] = espn_half(v.get("s") or {})
    M["espn"] = [E.get((y, w, k, p), np.nan) for y, w, k, p in zip(M.year, M.wk, M.key, M.pos)]
    M.loc[M.espn <= 0.3, "espn"] = np.nan
    A = json.load(open(os.path.join(SIM, "data", "ffc_adp_hist.json"), encoding="utf-8"))
    adp = {(int(y), nrm(p["name"]), p["pos"]): p["adp"] for y, v in A.items() for p in v["players"]}
    M["adp"] = [adp.get((y, k, p), np.nan) for y, k, p in zip(M.year, M.key, M.pos)]
    W = pd.read_parquet(os.path.join(DATA, "player_weeks.parquet"), columns=["season", "week", "pid", "dk", "ppr", "half", "rec"])
    M = M.merge(W.rename(columns={"season": "year", "week": "wk"}), on=["year", "wk", "pid"], how="left")
    return M


# ------------------------------------------------------------------ A
def part_a(M):
    P("=== A. START/SIT pairs 2019-25 (both projected >= 7 half-PPR, |gap| <= 5, different NFL teams) ===")
    # spread model: sd of (act - proj) = a + b * proj per position, fit on the other seasons (LOYO)
    M = M[M.live >= 7].copy()
    sdcoef = {}
    for Y in range(2019, 2026):
        for ps in POS4:
            tr = M[(M.year != Y) & (M.pos == ps)]
            b = np.polyfit(tr.live, np.abs(tr.act - tr.live) * np.sqrt(np.pi / 2), 1)
            sdcoef[(Y, ps)] = b
    M["sd"] = [np.polyval(sdcoef[(y, p)], v) for y, p, v in zip(M.year, M.pos, M.live)]
    recs = []
    for (y, w), g in M.groupby(["year", "wk"]):
        g = g.reset_index(drop=True)
        v = g.live.values; a = g.act.values; s = g.sd.values; e = g.espn.values; pp = g.ppg.values; pos = g.pos.values; tmv = g.team.values
        i, j = np.triu_indices(len(g), 1)
        same = pos[i] == pos[j]; flex = np.isin(pos[i], ("RB", "WR", "TE")) & np.isin(pos[j], ("RB", "WR", "TE")) & ~same
        keep = (same | flex) & (np.abs(v[i] - v[j]) <= 5) & (tmv[i] != tmv[j])
        i, j = i[keep], j[keep]
        recs.append(pd.DataFrame({"year": y, "gap": v[i] - v[j], "pA": N.cdf((v[i] - v[j]) / np.sqrt(s[i] ** 2 + s[j] ** 2)),
                                  "win": (a[i] > a[j]).astype(float) + 0.5 * (a[i] == a[j]), "diff": a[i] - a[j],
                                  "egap": e[i] - e[j], "pgap": pp[i] - pp[j], "same": same[keep], "posA": pos[i]}))
    R = pd.concat(recs, ignore_index=True)
    P(f"  pairs {len(R):,} (same-position {int(R.same.sum()):,}, flex {int((~R.same).sum()):,})")
    # orient so model favourite is A
    flip = R.gap < 0
    pf = np.where(flip, 1 - R.pA, R.pA); wf = np.where(flip, 1 - R.win, R.win); df = np.where(flip, -R["diff"], R["diff"])
    R["pf"], R["wf"], R["df"] = pf, wf, df
    P(f"  model favourite wins {R.wf.mean()*100:.1f}% of pairs; predicted {R.pf.mean()*100:.1f}% | Brier {np.mean((R.pf - R.wf)**2):.4f} vs coin .2500")
    R["bin"] = pd.cut(R.pf, [.5, .55, .6, .65, .7, .8, 1.0], include_lowest=True)
    t = R.groupby("bin", observed=True).agg(n=("wf", "size"), pred=("pf", "mean"), act=("wf", "mean"), pts=("df", "mean"))
    P("  calibration (pred -> actual, avg points edge): " + " | ".join(f"{r.pred:.2f}->{r.act:.2f} {r.pts:+.2f} (n{r.n:,})" for r in t.itertuples()))
    for lab, mk in (("same position", R.same), ("flex RB/WR/TE", ~R.same)):
        x = R[mk]; P(f"  {lab:14s}: favourite wins {x.wf.mean()*100:.1f}% (pred {x.pf.mean()*100:.1f}%), close calls |gap|<1: {x[np.abs(x.gap) < 1].wf.mean()*100:.1f}%, clear calls |gap|>=3: {x[np.abs(x.gap) >= 3].wf.mean()*100:.1f}%")
    for ps in POS4:
        x = R[R.same & (R.posA == ps)]; P(f"    {ps}: n {len(x):,}, favourite wins {x.wf.mean()*100:.1f}% (pred {x.pf.mean()*100:.1f}%)")
    # head to head with ESPN and season-to-date PPG where they disagree
    for lab, col in (("ESPN weekly projection", "egap"), ("season-to-date PPG", "pgap")):
        x = R[R[col].notna() & (R[col] != 0) & (R.gap != 0)]
        agree = np.sign(x[col]) == np.sign(x.gap)
        hit_m = np.where(x.gap > 0, x.win, 1 - x.win); hit_o = np.where(x[col] > 0, x.win, 1 - x.win)
        dis = ~agree
        gain = np.where(x.gap[dis] > 0, x["diff"][dis], -x["diff"][dis])
        P(f"  vs {lab}: pairs {len(x):,} | model hit {hit_m.mean()*100:.1f}% vs {hit_o.mean()*100:.1f}% | they disagree on {dis.mean()*100:.1f}%; there the model's pick wins {hit_m[dis.values].mean()*100:.1f}%, +{gain.mean():.2f} pts per decision")
        for Y in range(2019, 2026):
            mm = (x.year == Y).values & dis.values
            if mm.sum(): pass
        yrs = [np.mean(hit_m[(x.year == Y).values & dis.values]) > 0.5 for Y in range(2019, 2026)]
        P(f"      model wins the disagreements in {sum(yrs)}/7 seasons")


# ------------------------------------------------------------------ B
def part_b(M):
    P("\n=== B. ROS RANKINGS by week 2019-25 (per-game level from week k on, players with 3+ games left; top-150 ADP or live >= 8) ===")
    M = M.sort_values(["year", "pid", "wk"]).copy()
    ros = []
    for (y, p), g in M.groupby(["year", "pid"], sort=False):
        a = g.act.values; n = len(a)
        ros.append(pd.Series([a[i:].mean() if n - i >= 3 else np.nan for i in range(n)], index=g.index))
    M["rosk"] = pd.concat(ros)
    M["adp_r"] = -M.adp
    out = []
    for wk in range(2, 16):
        for (y, ps), g in M[(M.wk == wk) & M.rosk.notna()].groupby(["year", "pos"]):
            g = g[(g.adp <= 150) | (g.live >= 8)]
            if len(g) < 24: continue
            row = {"wk": wk, "year": y, "pos": ps}
            for c in ("live", "ppg", "adp_r", "espn"):
                gg = g[g[c].notna()] if c != "adp_r" else g[g.adp.notna()]
                if len(gg) < 15: row[c] = np.nan; row[c + "_h"] = np.nan; continue
                row[c] = spearmanr(gg[c], gg.rosk).correlation
                k = 12 if ps in ("QB", "TE") else 24
                row[c + "_h"] = len(set(gg.nlargest(k, c).pid) & set(gg.nlargest(k, "rosk").pid)) / k
            out.append(row)
    O = pd.DataFrame(out)
    T = O.groupby("wk")[["live", "ppg", "adp_r", "espn", "live_h", "ppg_h", "adp_r_h", "espn_h"]].mean()
    P("  week | Spearman: model  stdPPG  ADP   ESPNwk | top-12/24 hit: model stdPPG ADP ESPN")
    for wk, r in T.iterrows():
        P(f"  {wk:4d} |        {r.live:.3f}  {r.ppg:.3f}  {r.adp_r:.3f}  {r.espn:.3f} |        {r.live_h:.3f} {r.ppg_h:.3f} {r.adp_r_h:.3f} {r.espn_h:.3f}")
    cross = next((wk for wk, r in T.iterrows() if r.ppg > r.adp_r), None)
    P(f"  season-to-date PPG passes preseason ADP at week {cross}; model beats ADP from week {next((wk for wk, r in T.iterrows() if r.live > r.adp_r), None)}")
    for ps in POS4:
        t = O[O.pos == ps].groupby("wk")[["live", "ppg", "adp_r", "espn"]].mean()
        P(f"    {ps}: " + " | ".join(f"wk{w} model {t.loc[w].live:.3f} ppg {t.loc[w].ppg:.3f} adp {t.loc[w].adp_r:.3f} espn {t.loc[w].espn:.3f}" for w in (2, 5, 8, 12) if w in t.index))
    # reaction to the last game: does the model under/over react?
    M["res"] = M.act - M.live
    M["last_res"] = M.groupby(["year", "pid"]).res.shift(1)
    x = M[M.last_res.notna() & M.rosk.notna() & (M.wk >= 3)]
    b = np.polyfit(x.last_res, x.rosk - x.live, 1)[0]
    P(f"  ROS miss vs last game's surprise: slope {b:+.3f} (0 = reacts right; >0 = under-reacts, <0 = over-reacts), n {len(x):,}")
    for ps in POS4:
        xx = x[x.pos == ps]; P(f"    {ps}: slope {np.polyfit(xx.last_res, xx.rosk - xx.live, 1)[0]:+.3f}")
    # week-to-week rank churn
    M["rk"] = M.groupby(["year", "wk", "pos"]).live.rank(ascending=False)
    M["rk_prev"] = M.groupby(["year", "pid"]).rk.shift(1)
    z = M[M.rk_prev.notna() & (M.rk <= 36)]
    P(f"  week-to-week rank churn (top 36 at position): median |move| {np.median(np.abs(z.rk - z.rk_prev)):.1f} spots, 90th pct {np.quantile(np.abs(z.rk - z.rk_prev), .9):.1f}")
    return O


# ------------------------------------------------------------------ C
def part_c(M):
    P("\n=== C. DISTRIBUTION SHAPE (spike / dud weeks) 2019-25, real vs moment-matched gamma ===")
    M = M[M.live >= 3].copy()
    M["band"] = pd.cut(M.live, [3, 8, 12, 16, 20, 40])
    P("  scoring pos band      n    CV   P(>=2x) gamma  P(>=proj+10) gamma  P(<.25x) gamma | p90/mean real gamma")
    for sc, col, k in (("half", "act", None), ("DK", "dk", None)):
        for ps in POS4:
            for b, g in M[M.pos == ps].groupby("band", observed=True):
                if len(g) < 200: continue
                y = g[col].dropna().values; proj = g.live.values[: len(y)] if col == "act" else g.live[g[col].notna()].values
                if sc == "DK":
                    proj = proj * (np.nanmean(y) / np.nanmean(proj))
                r = y / proj
                cv = np.std(y - proj) / np.mean(proj)
                kshape = 1 / cv ** 2
                pg2 = GAM.sf(2, kshape, scale=1 / kshape); pd10 = np.mean(GAM.sf((proj + 10) / proj, kshape, scale=1 / kshape))
                pg25 = GAM.cdf(.25, kshape, scale=1 / kshape)
                p90r = np.quantile(r, .9); p90g = GAM.ppf(.9, kshape, scale=1 / kshape)
                P(f"  {sc:4s}  {ps}  {str(b):9s} {len(y):6d} {cv:5.2f}   {np.mean(r >= 2):.3f} {pg2:.3f}    {np.mean(y >= proj + 10):.3f} {pd10:.3f}    {np.mean(r < .25):.3f} {pg25:.3f}  |  {p90r:.2f} {p90g:.2f}")
    # teammate / opponent residual correlations
    P("\n  weekly residual correlations (act - live), half-PPR vs DK:")
    M = M.copy(); M["res"] = M.act - M.live
    M["dres"] = M.dk - M.live * (M.dk.mean() / M.act.mean())
    M["prk"] = M.groupby(["year", "wk", "team", "pos"]).live.rank(ascending=False, method="first")
    def role(r): return f"{r.pos}{int(r.prk)}"
    M["role"] = M.pos + M.prk.astype(int).astype(str)
    piv = M.pivot_table(index=["year", "wk", "team"], columns="role", values="res", aggfunc="first")
    pivd = M.pivot_table(index=["year", "wk", "team"], columns="role", values="dres", aggfunc="first")
    opp = M.groupby(["year", "wk", "team"]).opp.first()
    for a, b in (("QB1", "WR1"), ("QB1", "WR2"), ("QB1", "TE1"), ("QB1", "RB1"), ("WR1", "WR2"), ("RB1", "RB2"), ("WR1", "TE1"), ("RB1", "WR1")):
        if a in piv and b in piv:
            m = piv[[a, b]].dropna(); md = pivd[[a, b]].dropna()
            P(f"    same team {a}-{b}: half {m[a].corr(m[b]):+.3f} (n {len(m)}) | DK {md[a].corr(md[b]):+.3f}")
    q = piv[["QB1"]].copy(); q["opp"] = opp.reindex(q.index).values
    q2 = q.reset_index().merge(q.reset_index().rename(columns={"team": "opp", "opp": "team", "QB1": "oQB1"})[["year", "wk", "opp", "oQB1"]], on=["year", "wk", "opp"])
    P(f"    opposing QB1-QB1: half {q2.QB1.corr(q2.oQB1):+.3f} (n {len(q2.dropna())})")
    r1 = piv[["RB1"]].copy(); r1["opp"] = opp.reindex(r1.index).values
    r2 = r1.reset_index().merge(r1.reset_index().rename(columns={"team": "opp", "opp": "team", "RB1": "oRB1"})[["year", "wk", "opp", "oRB1"]], on=["year", "wk", "opp"])
    P(f"    opposing RB1-RB1: half {r2.RB1.corr(r2.oRB1):+.3f}")


# ------------------------------------------------------------------ D
def season_points():
    W = pd.read_parquet(os.path.join(DATA, "player_weeks.parquet"))
    W = W[W.week < W.season.map(final_week)]
    W["half_tep15"] = np.where(W.position == "TE", W.half + 1.0 * W.rec, W.half + 0.5 * W.rec)  # PPR base, TE 1.5
    S = W.groupby(["season", "pid", "position", "display_name"]).agg(
        half=("half", "sum"), ppr=("ppr", "sum"), rec=("rec", "sum"), ptd=("ptd", "sum"), g=("half", "size")).reset_index()
    return S, W


def vor(S, col, teams, slots, flex_pos=("RB", "WR", "TE"), nflex=1, sflex=0):
    """season VOR: starters per position by greedy allocation of the season totals (simple, season-level)."""
    S = S.copy(); S["v"] = S[col]
    base = {}
    taken = set(); counts = {}
    for ps, k in slots.items():
        top = S[S.position == ps].nlargest(teams * k, "v"); taken |= set(top.index); counts[ps] = teams * k
    rest = S[~S.index.isin(taken)]
    if nflex:
        fl = rest[rest.position.isin(flex_pos)].nlargest(teams * nflex, "v"); taken |= set(fl.index)
        for ps in flex_pos: counts[ps] += int((fl.position == ps).sum())
    rest = S[~S.index.isin(taken)]
    if sflex:
        sf = rest[rest.position.isin(("QB", "RB", "WR", "TE"))].nlargest(teams * sflex, "v"); taken |= set(sf.index)
        for ps in POS4: counts[ps] += int((sf.position == ps).sum())
    for ps in POS4:
        srt = S[S.position == ps].sort_values("v", ascending=False).v.values
        base[ps] = srt[min(counts.get(ps, 0), len(srt) - 1)]
    S["vor"] = S.v - S.position.map(base)
    return S, base, counts


def part_d():
    P("\n=== D. FORMAT VALUE 2015-25: season VOR by format (12-team, 1QB/2RB/3WR/1TE/1FLEX base; season totals, final week out) ===")
    S, W = season_points(); S = S[S.season >= 2015]
    fmts = {
        "1QB half":       ("half", {"QB": 1, "RB": 2, "WR": 3, "TE": 1}, 1, 0),
        "1QB PPR":        ("ppr", {"QB": 1, "RB": 2, "WR": 3, "TE": 1}, 1, 0),
        "SF PPR":         ("ppr", {"QB": 1, "RB": 2, "WR": 3, "TE": 1}, 1, 1),
        "2QB PPR":        ("ppr", {"QB": 2, "RB": 2, "WR": 3, "TE": 1}, 1, 0),
        "TEP1.5 PPR":     ("tep15", {"QB": 1, "RB": 2, "WR": 3, "TE": 1}, 1, 0),
        "TEP1.75 PPR":    ("tep175", {"QB": 1, "RB": 2, "WR": 3, "TE": 1}, 1, 0),
        "TEP2.0 PPR":     ("tep20", {"QB": 1, "RB": 2, "WR": 3, "TE": 1}, 1, 0),
        "SF+TEP1.5":      ("tep15", {"QB": 1, "RB": 2, "WR": 3, "TE": 1}, 1, 1),
        "2TE TEP1.5":     ("tep15", {"QB": 1, "RB": 2, "WR": 3, "TE": 2}, 1, 0),
    }
    S["tep15"] = np.where(S.position == "TE", S.ppr + 0.5 * S.rec, S.ppr)
    S["tep175"] = np.where(S.position == "TE", S.ppr + 0.75 * S.rec, S.ppr)
    S["tep20"] = np.where(S.position == "TE", S.ppr + 1.0 * S.rec, S.ppr)
    P("  format        | starters QB/RB/WR/TE | repl QB RB WR TE (pts) | share of top-36 VOR: QB RB WR TE | TE1-3 VOR / TE4-12 VOR")
    for lab, (col, slots, nf, sf) in fmts.items():
        agg = []
        for Y, g in S.groupby("season"):
            V, base, counts = vor(g, col, 12, slots, nflex=nf, sflex=sf)
            top = V.nlargest(36, "vor")
            te = V[V.position == "TE"].sort_values("vor", ascending=False).vor.values
            agg.append([counts["QB"], counts["RB"], counts["WR"], counts["TE"], base["QB"], base["RB"], base["WR"], base["TE"],
                        *(np.mean(top.position == p) for p in POS4), te[:3].clip(0).sum() / max(te[3:12].clip(0).sum(), 1)])
        a = np.mean(agg, axis=0)
        P(f"  {lab:13s} | {a[0]:4.1f} {a[1]:4.1f} {a[2]:4.1f} {a[3]:4.1f}      | {a[4]:5.0f} {a[5]:4.0f} {a[6]:4.0f} {a[7]:4.0f}      | {a[8]:.2f} {a[9]:.2f} {a[10]:.2f} {a[11]:.2f}            | {a[12]:.2f}")
    # superflex QB replacement by league size
    P("  superflex QB replacement (PPR season pts of the last starting QB): " + " | ".join(
        f"{t} teams {np.mean([vor(g, 'ppr', t, {'QB': 1, 'RB': 2, 'WR': 3, 'TE': 1}, nflex=1, sflex=1)[1]['QB'] for _, g in S.groupby('season')]):.0f}" for t in (10, 12, 14)))
    # weekly flex: TE ranked 13-18 vs RB 25-30 / WR 37-42 in the same week (does a TE2 win the flex?)
    W = W[W.season >= 2015].copy()
    W["tep15"] = np.where(W.position == "TE", W.ppr + 0.5 * W.rec, W.ppr)
    for col in ("half", "ppr", "tep15"):
        W["wr"] = W.groupby(["season", "week", "position"])[col].rank(ascending=False, method="first")
        te2 = W[(W.position == "TE") & W.wr.between(13, 18)].groupby(["season", "week"])[col].mean()
        rb3 = W[(W.position == "RB") & W.wr.between(25, 30)].groupby(["season", "week"])[col].mean()
        wr3 = W[(W.position == "WR") & W.wr.between(37, 42)].groupby(["season", "week"])[col].mean()
        P(f"    weekly {col:6s}: TE13-18 avg {te2.mean():.1f} vs RB25-30 {rb3.mean():.1f} vs WR37-42 {wr3.mean():.1f} (actual-rank slices; ex post)")
    # TE target-driven vs TD-driven under TEP
    te = S[(S.position == "TE") & (S.g >= 8)].copy()
    te["rec_pg"] = te.rec / te.g
    P(f"  TE seasons 8+ games: corr(rec/g, PPR->TEP1.5 gain) {np.corrcoef(te.rec_pg, (te.tep15 - te.ppr) / te.g)[0,1]:.2f}; TEP1.5 adds {np.mean(0.5*te.rec_pg):.2f} pts/g on average, {np.mean(0.5*te.rec_pg[te.rec_pg>=5]):.2f} for 5+ rec/g TEs")


# ------------------------------------------------------------------ E
def part_e():
    P("\n=== E. KEEPER surplus 2016-25 (12-team half-PPR, keep at last year's draft round; pick value curve fit walk-forward) ===")
    S, _ = season_points()
    A = json.load(open(os.path.join(SIM, "data", "ffc_adp_hist.json"), encoding="utf-8"))
    rows = []
    for y, v in A.items():
        for p in v["players"]:
            if p["pos"] in POS4: rows.append({"season": int(y), "key": nrm(p["name"]), "pos": p["pos"], "adp": p["adp"]})
    AD = pd.DataFrame(rows).sort_values("adp").drop_duplicates(["season", "key", "pos"])
    S["key"] = S.display_name.map(nrm)
    out = []
    for Y in range(2014, 2026):
        g = S[S.season == Y]
        V, base, _ = vor(g, "half", 12, {"QB": 1, "RB": 2, "WR": 3, "TE": 1})
        V = V.merge(AD[AD.season == Y][["key", "pos", "adp"]].rename(columns={"pos": "position"}), on=["key", "position"], how="right")
        V["vor"] = V.vor.fillna(-50).clip(lower=0)
        V["season"] = Y
        out.append(V)
    V = pd.concat(out)
    from sklearn.isotonic import IsotonicRegression
    res = []
    for Y in range(2016, 2026):
        tr = V[V.season < Y]
        iso = IsotonicRegression(increasing=False, out_of_bounds="clip").fit(np.log(tr.adp), tr.vor)
        cur = V[V.season == Y].copy(); prev = V[V.season == Y - 1][["key", "position", "adp"]].rename(columns={"adp": "adp_prev"})
        k = cur.merge(prev, on=["key", "position"], how="inner")
        k["rd_prev"] = np.ceil(k.adp_prev / 12)
        for pen in (0, 1):
            cost_pick = ((k.rd_prev - pen).clip(lower=1) - 1) * 12 + 6.5
            k[f"cost{pen}"] = iso.predict(np.log(cost_pick))
        k["mkt_val"] = iso.predict(np.log(k.adp))
        k["surplus_mkt"] = k.mkt_val - k.cost0; k["surplus_real"] = k.vor - k.cost0
        k["surplus_mkt1"] = k.mkt_val - k.cost1; k["surplus_real1"] = k.vor - k.cost1
        k["season"] = Y; res.append(k)
    K = pd.concat(res)
    P(f"  kept-candidate rows {len(K)} (players with FFC ADP in both Y-1 and Y)")
    P(f"  corr(market-implied surplus, realized surplus): {K.surplus_mkt.corr(K.surplus_real):.3f}; Spearman {spearmanr(K.surplus_mkt, K.surplus_real).correlation:.3f}")
    K["q"] = pd.qcut(K.surplus_mkt.rank(method="first"), 5, labels=False)
    t = K.groupby("q").agg(pred=("surplus_mkt", "mean"), real=("surplus_real", "mean"), pos_rate=("surplus_real", lambda s: (s > 0).mean()))
    P("  quintiles of predicted surplus (pts VOR): " + " | ".join(f"pred {r.pred:+.0f} real {r.real:+.0f} ({r.pos_rate*100:.0f}% >0)" for r in t.itertuples()))
    late = K[K.rd_prev >= 10]
    P(f"  late-round keepers (round 10+ last year): n {len(late)}, realized surplus mean {late.surplus_real.mean():+.0f}, share > 0 {np.mean(late.surplus_real > 0)*100:.0f}%; with a 1-round penalty: {late.surplus_real1.mean():+.0f}")
    top = K[K.rd_prev <= 2]
    P(f"  round 1-2 players kept at cost: mean realized surplus {top.surplus_real.mean():+.0f} (market said {top.surplus_mkt.mean():+.0f})")


# ------------------------------------------------------------------ F
def part_f():
    P("\n=== F. DYNASTY: age curves (delta method, half-PPR PPG, players with 8+ games in both seasons, 2013-25) ===")
    S, _ = season_points()
    pl = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "birth_date"]).rename(columns={"gsis_id": "pid"})
    S = S.merge(pl.drop_duplicates("pid"), on="pid", how="left")
    S["age"] = [(pd.Timestamp(f"{y}-09-01") - pd.Timestamp(b)).days / 365.25 if isinstance(b, str) else np.nan for y, b in zip(S.season, S.birth_date)]
    S["ppg"] = S.half / S.g
    nxt = S[["season", "pid", "ppg", "g"]].copy(); nxt["season"] -= 1
    D = S.merge(nxt, on=["season", "pid"], suffixes=("", "_n"))
    D = D[(D.g >= 8) & (D.g_n >= 8) & (D.ppg >= 6)]
    D["ai"] = D.age.round()
    for ps in POS4:
        d = D[D.position == ps]
        t = d.groupby("ai").apply(lambda x: pd.Series({"n": len(x), "chg": np.median(x.ppg_n / x.ppg - 1)})).query("n >= 15")
        P(f"  {ps}: " + " ".join(f"{int(a)}:{r.chg*100:+.0f}%" for a, r in t.iterrows()))
    # survival: share of 8+-game, 10+ ppg players at age a who are still 8+ games / 8+ ppg next year
    S2 = S.merge(nxt.rename(columns={"ppg": "ppg_n", "g": "g_n"}), on=["season", "pid"], how="left")
    S2 = S2[(S2.g >= 8) & (S2.ppg >= 10) & (S2.season <= 2024)]
    S2["alive"] = (S2.g_n.fillna(0) >= 8) & (S2.ppg_n.fillna(0) >= 8)
    S2["ai"] = S2.age.round()
    for ps in ("RB", "WR"):
        t = S2[S2.position == ps].groupby("ai").alive.agg(["size", "mean"]).query("size >= 15")
        P(f"  {ps} still a starter-level player next year (8+ g, 8+ ppg) given 10+ ppg now: " + " ".join(f"{int(a)}:{r['mean']*100:.0f}%" for a, r in t.iterrows()))
    # persistence of value 1/2/3 years out
    piv = S[(S.g >= 6)].pivot_table(index="pid", columns="season", values="ppg")
    for lag in (1, 2, 3):
        a, b = [], []
        for y in range(2013, 2026 - lag):
            if y in piv and y + lag in piv:
                m = piv[[y, y + lag]].dropna(); a += list(m[y]); b += list(m[y + lag])
        P(f"  PPG persistence {lag} yr: r {np.corrcoef(a, b)[0,1]:.3f} (n {len(a)}, survivors only)")


# ------------------------------------------------------------------ G
def part_g():
    P("\n=== G. DEVY / PROSPECT: JM score vs draft capital, NFL years 1-3 (drafted QB/RB/WR/TE 2014-2023) ===")
    s = open(os.path.join(SIM, "data", "jm_scores.js"), encoding="utf-8").read(); jm = json.loads(s[s.index("{"): s.rindex("}") + 1])
    S, _ = season_points()
    pl = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "display_name", "position", "draft_year", "draft_pick"])
    pl = pl[pl.position.isin(POS4) & pl.draft_year.between(2014, 2023) & pl.draft_pick.notna()].rename(columns={"gsis_id": "pid"})
    pl["jm"] = pl.display_name.map(lambda n: jm.get(nrm(n)))
    pts = S.groupby(["pid", "season"]).agg(half=("half", "sum"), g=("g", "sum")).reset_index()
    rows = []
    for r in pl.itertuples(index=False):
        x = pts[(pts.pid == r.pid) & pts.season.between(r.draft_year, r.draft_year + 2)]
        best = (x.half / x.g.clip(lower=1)).where(x.g >= 6).max() if len(x) else np.nan
        tot = x.half.sum() if len(x) else 0.0
        rows.append({"pid": r.pid, "pos": r.position, "year": r.draft_year, "pick": r.draft_pick, "jm": r.jm, "best_ppg": best if best == best else 0.0, "tot3": tot})
    D = pd.DataFrame(rows); D = D[D.jm.notna()]
    P(f"  prospects with a JM score: {len(D)} of {len(pl)} drafted")
    from sklearn.linear_model import Ridge
    for ps in POS4:
        d = D[D.pos == ps].copy()
        if len(d) < 40: continue
        d["lp"] = -np.log(d.pick)
        rp = spearmanr(d.lp, d.tot3).correlation; rj = spearmanr(d.jm, d.tot3).correlation
        # LOYO by draft class: ridge on lp alone vs lp + jm
        pr0, pr1 = np.full(len(d), np.nan), np.full(len(d), np.nan)
        for Y in sorted(d.year.unique()):
            tr, te = (d.year != Y).values, (d.year == Y).values
            for cols, outv in ((["lp"], pr0), (["lp", "jm"], pr1)):
                X = d[cols].values; mu, sd = X[tr].mean(0), X[tr].std(0)
                m = Ridge(alpha=1.0).fit((X[tr] - mu) / sd, d.tot3.values[tr]); outv[te] = m.predict((X[te] - mu) / sd)
        r0 = spearmanr(pr0, d.tot3).correlation; r1 = spearmanr(pr1, d.tot3).correlation
        mae0 = np.mean(np.abs(pr0 - d.tot3)); mae1 = np.mean(np.abs(pr1 - d.tot3))
        # hit rates by pick round
        d["rd"] = pd.cut(d.pick, [0, 32, 64, 100, 300], labels=["R1", "R2", "R3", "R4+"])
        thr = {"QB": 16, "RB": 12, "WR": 11, "TE": 9}[ps]
        hr = d.groupby("rd", observed=True).best_ppg.apply(lambda s: (s >= thr).mean())
        P(f"  {ps} n {len(d)}: Spearman(yrs1-3 pts) draft capital {rp:.3f} | JM {rj:.3f} | LOYO by class: capital-only rho {r0:.3f} MAE {mae0:.0f} vs capital+JM rho {r1:.3f} MAE {mae1:.0f}")
        P(f"     'starter' season in yrs 1-3 (best PPG >= {thr}) by round: " + " ".join(f"{k} {v*100:.0f}%" for k, v in hr.items()))


# ------------------------------------------------------------------ H
def part_h():
    P("\n=== H. LEAGUE matchup odds 2026 (stored newspaper moneylines vs real results, 4 leagues) ===")
    def ml_p(s):
        s = str(s).replace("\u2212", "-").strip()
        if s.upper() in ("EVEN", "EV"): s = "+100"
        if s in ("PK", ""): return None
        o = float(s); return 100 / (o + 100) if o > 0 else -o / (-o + 100)
    recs = []
    for lg in ("clitphen", "robbinsville", "rville", "superdyno"):
        E = json.load(open(os.path.join(LE, f"{lg}_espn.json"), encoding="utf-8"))
        names = {t["name"]: t["id"] for t in E["teams"]}
        res = {}
        for g in E["sched"]:
            if g.get("hp") is None or g.get("ap") is None or (g["hp"] == 0 and g["ap"] == 0): continue
            res[(g["week"], frozenset((g["home"], g["away"])))] = {g["home"]: g["hp"], g["away"]: g["ap"]}
        files = []
        for f in glob.glob(os.path.join(LE, f"{lg}_lines_w*.json")):
            d = json.load(open(f, encoding="utf-8")); files.append((d["week"], d["rows"]))
        for f in glob.glob(os.path.join(LE, f"{lg}_simlab_w*.json")):
            d = json.load(open(f, encoding="utf-8"))
            if "week5" in d and d["week5"]: files.append((d["week5"]["week"], d["week5"]["rows"]))
        seen = set()
        for wk, rows in files:
            for r in rows:
                a, b = names.get(r[0]), names.get(r[3])
                if a is None or b is None: continue
                k = (wk, frozenset((a, b)))
                if k in seen or k not in res: continue
                seen.add(k)
                pa, pb = ml_p(r[2]), ml_p(r[5])
                if pa is None or pb is None: pa, pb = 0.5, 0.5
                p = pa / (pa + pb); sc = res[k]
                spread = str(r[1]).replace("\u2212", "-"); sp = 0.0 if spread == "PK" else -float(spread)
                recs.append({"lg": lg, "wk": wk, "p": p, "win": float(sc[a] > sc[b]), "margin": sc[a] - sc[b], "sp": sp, "a": a, "b": b})
    R = pd.DataFrame(recs)
    if len(R) == 0: P("  no gradable rows"); return
    P(f"  graded matchups {len(R)} (weeks {sorted(R.wk.unique())}); favourite (sim) won {np.mean(np.where(R.p >= .5, R.win, 1 - R.win))*100:.1f}%, predicted {np.mean(np.maximum(R.p, 1 - R.p))*100:.1f}%")
    P(f"  Brier sim {np.mean((R.p - R.win)**2):.4f} vs coin .2500 | log loss {-np.mean(R.win*np.log(R.p.clip(.01,.99)) + (1-R.win)*np.log((1-R.p).clip(.01,.99))):.4f}")
    P(f"  margin vs sim spread: MAE {np.mean(np.abs(R.margin - R.sp)):.1f}, sd of miss {np.std(R.margin - R.sp):.1f} (implied sd of the sim's line: {np.std(R.sp):.1f})")
    # baseline: points-for to date
    base = []
    for r in R.itertuples(index=False):
        E = json.load(open(os.path.join(LE, f"{r.lg}_espn.json"), encoding="utf-8"))
        pf = {}
        for g in E["sched"]:
            if g["week"] < r.wk and g.get("hp") is not None:
                pf.setdefault(g["home"], []).append(g["hp"]); pf.setdefault(g["away"], []).append(g["ap"])
        da = np.mean(pf.get(r.a, [100])) - np.mean(pf.get(r.b, [100]))
        base.append(N.cdf(da / 30.0))
    R["pbase"] = base
    P(f"  baseline P from points-for per game to date (sd 30): Brier {np.mean((R.pbase - R.win)**2):.4f}")
    R["bin"] = pd.cut(np.maximum(R.p, 1 - R.p), [.5, .6, .7, .8, 1.0], include_lowest=True)
    R["fw"] = np.where(R.p >= .5, R.win, 1 - R.win)
    t = R.groupby("bin", observed=True).agg(n=("fw", "size"), pred=("p", lambda s: np.mean(np.maximum(s, 1 - s))), act=("fw", "mean"))
    P("  calibration: " + " | ".join(f"{r.pred:.2f}->{r.act:.2f} (n{r.n})" for r in t.itertuples()))


def main():
    global LOG
    LOG = open(os.path.join(HERE, LOG_NAME), "w", encoding="utf-8")
    t0 = time.time()
    M = load_rows()
    P(f"rows {len(M):,} player-weeks 2019-25 (final week out); ESPN matched {M.espn.notna().mean()*100:.0f}%, ADP {M.adp.notna().mean()*100:.0f}%, DK {M.dk.notna().mean()*100:.0f}%")
    for f, arg in ((part_a, M), (part_b, M), (part_c, M), (part_d, None), (part_e, None), (part_f, None), (part_g, None), (part_h, None)):
        try:
            f(arg) if arg is not None else f()
        except Exception:
            P("  !! section failed: " + traceback.format_exc().splitlines()[-1]); traceback.print_exc()
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
