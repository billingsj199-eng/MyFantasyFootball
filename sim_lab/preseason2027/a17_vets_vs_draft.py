#!/usr/bin/env python3
"""
A17 (research only, 2026-11-24) - do veterans get over-projected when their team drafts a high pick at their position?

Rows = the existing walk-forward backtest (data/rb_a14_D.parquet: pg = v5 per-game = .75 x S7 lean + .25 x ridge, g_use = games
share, seasons 2015-2025 out of sample, each season trained on earlier seasons only). Veterans only (rookie = 0).
Draft picks = pbp_cache/draft_picks.parquet (QB/RB/WR/TE picks of that April).

The backtest projection ALREADY carries a 'drafted_comp' input (team took a top-64 pick at the position), so three states are graded:
  AS-IS      the stored backtest projection (knows the draft through drafted_comp and the week-1 depth chart)
  BLIND      same model, drafted_comp forced to 0 for the season being predicted = what the 2027 early list does today
             (there is no 2027 draft yet). Training rows keep the input, exactly as in the live build.
  NOV        BLIND + the depth-chart inputs taken from the FINAL chart of the previous season instead of week 1
             (closest on-disk emulation of a November look; movers stay on last season's chart).
and three pre-draft repairs are tested, all walk-forward:
  EXPECTED   drafted_comp = its training-set mean (a league-wide expected haircut)
  NEED       drafted_comp = P(team takes a top-64 pick at the position), a walk-forward logit on November-knowable
             team-need inputs (last season's room production, lead's age, expiring contract, recent high pick already
             in the room, last season's win share)
  FIXED      (post-draft only) drafted_comp rebuilt with the team-code bug repaired, see section 1.

  python a17_vets_vs_draft.py   -> a17_vets_vs_draft.log, data/a17_vet_rows.parquet
Read-only on every existing file.
"""
import os, sys, warnings
import numpy as np, pandas as pd
from scipy.stats import spearmanr
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM
import pergame_model as G

POS4 = PM.POS4
LEAN = G.BASIC + G.ROSTER + ["lp_rook"]
CANON = {"GNB": "GB", "KAN": "KC", "NWE": "NE", "NOR": "NO", "SFO": "SF", "TAM": "TB", "LVR": "LV", "OAK": "LV", "SDG": "LAC", "SD": "LAC",
         "STL": "LAR", "SL": "LAR", "LA": "LAR", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "ARZ": "ARI", "JAC": "JAX", "WSH": "WAS"}
YEARS = list(range(2015, 2026))
LOG = None
NB = 2000


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def canon(s): return s.map(lambda t: CANON.get(t, t) if isinstance(t, str) else t)


def walk_override(D, fn):
    """S7 walk-forward where the rows of the season being predicted are modified by fn(DY, Y) (training rows untouched)."""
    out = pd.Series(np.nan, index=D.index); keep = PM.TEST_YEARS
    try:
        for Y in YEARS:
            DY = D.copy(); fn(DY, Y); PM.TEST_YEARS = [Y]
            o = G.walk(DY, LEAN, "S7", use_role_prior=True)[0]
            out.loc[D.season == Y] = o[D.season == Y]
    finally:
        PM.TEST_YEARS = keep
    return out


def prev_final_depth():
    """{(Y, gsis): rank at his position in the final regular-season chart of Y-1} (nflverse weekly charts 2014-2024)."""
    out = {}
    for Y in YEARS:
        d = pd.read_parquet(os.path.join(PM.CACHE, f"depth_charts_{Y-1}.parquet"))
        if "week" not in d.columns: continue
        d = d[(d.game_type == "REG") & d.position.isin(POS4) & (d.formation == "Offense")]
        d = d[d.week == d.groupby("club_code").week.transform("max")]
        d = d.assign(rk=pd.to_numeric(d.depth_team, errors="coerce")).sort_values("rk").drop_duplicates("gsis_id")
        for g, r in zip(d.gsis_id, d.rk): out[(Y, g)] = r
    return out


def boot(e, tr, ct, cl, n=NB, seed=11):
    """mean(e | treated) - mean(e | control), cluster bootstrap over cl; returns diff, 90% lo, hi, treated mean, se of treated mean."""
    ok = np.isfinite(e); e, tr, ct, cl = e[ok], tr[ok], ct[ok], cl[ok]
    if tr.sum() < 3 or ct.sum() < 3: return (np.nan,) * 5
    ids, inv = np.unique(cl, return_inverse=True); k = len(ids)
    st = np.bincount(inv, e * tr, k); nt = np.bincount(inv, tr.astype(float), k); sc = np.bincount(inv, e * ct, k); nc = np.bincount(inv, ct.astype(float), k)
    rng = np.random.default_rng(seed); dd = []; mm = []
    for _ in range(n):
        i = rng.integers(0, k, k)
        a, b, c, d = st[i].sum(), nt[i].sum(), sc[i].sum(), nc[i].sum()
        if b == 0 or d == 0: continue
        dd.append(a / b - c / d); mm.append(a / b)
    return e[tr].mean() - e[ct].mean(), np.percentile(dd, 5), np.percentile(dd, 95), e[tr].mean(), np.std(mm)


def main():
    global LOG
    LOG = open(os.path.join(HERE, "a17_vets_vs_draft.log"), "w", encoding="utf-8")
    D = pd.read_parquet(os.path.join(HERE, "data", "rb_a14_D.parquet")).reset_index(drop=True)
    D["tc"] = canon(D.team); D["t1c"] = canon(D.team1).fillna(D.tc)
    dp = pd.read_parquet(os.path.join(PM.CACHE, "draft_picks.parquet"), columns=["season", "round", "pick", "team", "position", "gsis_id"])
    dp = dp[dp.position.isin(POS4) & dp.season.between(2013, 2025)].copy(); dp["tc"] = canon(dp.team)

    # ------------------------------------------------------------ 1. the team-code bug in the existing input
    P("=== A17: veterans vs incoming draft picks at their position (walk-forward backtest rows 2015-2025, veterans only) ===")
    P("\n## 1. Finding: the model's existing 'drafted competition' input misses seven franchises")
    old = dp.assign(t_old=dp.team.map(PM.tm)); top = old[old.pick <= 64]
    keys = set(zip(D.season, D.team, D.pos))
    hit = np.array([(s, t, p) in keys for s, t, p in zip(top.season, top.t_old, top.position)])
    P(f"  draft_picks.parquet uses PFR team codes (GNB KAN NWE NOR SFO TAM LVR SDG); preseason_model.ALIAS does not map them, so")
    P(f"  pergame_model.add_context never matches those teams: {int((~hit).sum())} of {len(top)} top-64 skill picks 2013-25 ({(~hit).mean()*100:.0f}%) reach no veteran.")
    P(f"  teams whose picks are lost: {top[~hit].t_old.value_counts().to_dict()}")
    comp = {}
    for r in dp[dp.pick <= 64].itertuples(index=False): comp.setdefault((r.season, r.tc, r.position), []).append(r.gsis_id)
    D["dcomp_fix"] = [float(any(g != pid for g in comp.get((y, t, p), []))) for y, t, p, pid in zip(D.season, D.tc, D.pos, D.pid)]
    v = (D.rookie == 0) & D.season.isin(YEARS)
    P(f"  veteran rows 2015-25 flagged: stored input {int(D.drafted_comp[v].sum())}, rebuilt with the codes mapped {int(D.dcomp_fix[v].sum())} (of {int(v.sum())})")
    qb = dp[(dp.position == "QB") & (dp.pick <= 64)]; lostqb = qb[qb.team.isin(["GNB", "KAN", "NWE", "NOR", "SFO", "TAM", "LVR", "SDG"])]
    P(f"  the same mapping feeds qb_a11.py 'comp_hi' (rd 1-2 QB behind the starter): {len(lostqb)} of {len(qb)} top-64 QB picks 2013-25 are on the unmapped codes")
    P(f"  (e.g. {', '.join(f'{r.team} {r.season}' for r in lostqb.sort_values('season').tail(8).itertuples())}). NOT changed here - research only.")

    # ------------------------------------------------------------ projections
    s7 = G.walk(D, LEAN, "S7", use_role_prior=True)[0]
    P(f"\n  check: S7 recomputed here vs the stored column, max |diff| = {np.nanmax(np.abs(s7.values - D.s7.values)):.6f}")
    Df = D.copy(); Df["drafted_comp"] = Df.dcomp_fix
    s7_fix = G.walk(Df, LEAN, "S7", use_role_prior=True)[0]

    def zero(DY, Y): DY.loc[DY.season == Y, "drafted_comp"] = 0.0
    s7_blind = walk_override(D, zero)

    def expected(DY, Y):
        for ps in POS4:
            tr = (DY.season < Y) & (DY.pos == ps) & (DY.y_g >= 4)
            DY.loc[(DY.season == Y) & (DY.pos == ps), "drafted_comp"] = DY.drafted_comp[tr].mean()
    s7_exp = walk_override(D, expected)
    def expected_fix(DY, Y):
        DY["drafted_comp"] = Df.drafted_comp.values
        for ps in POS4:
            tr = (DY.season < Y) & (DY.pos == ps) & (DY.y_g >= 4)
            DY.loc[(DY.season == Y) & (DY.pos == ps), "drafted_comp"] = DY.drafted_comp[tr].mean()
    s7_expf = walk_override(D, expected_fix)
    def zero_fix(DY, Y):
        DY["drafted_comp"] = Df.drafted_comp.values; DY.loc[DY.season == Y, "drafted_comp"] = 0.0
    s7_blindf = walk_override(D, zero_fix)

    pfd = prev_final_depth()
    D["dc_prev"] = [pfd.get((y, p), np.nan) for y, p in zip(D.season, D.pid)]
    def nov(DY, Y):
        m = DY.season == Y
        DY.loc[m, "drafted_comp"] = 0.0
        DY.loc[m, "dc1"] = (DY.dc_prev[m] == 1).astype(float); DY.loc[m, "dc2"] = (DY.dc_prev[m] == 2).astype(float); DY.loc[m, "dcna"] = DY.dc_prev[m].isna().astype(float)
    s7_nov = walk_override(D, nov)

    # ------------------------------------------------------------ November team-need model
    S = G.stat_seasons(); S["tc"] = canon(S.team)
    pl = pd.read_csv(os.path.join(PM.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "birth_date"]).drop_duplicates("gsis_id").set_index("gsis_id").birth_date
    c = pd.read_parquet(os.path.join(PM.CACHE, "otc", "historical_contracts.parquet"), columns=["gsis_id", "year_signed", "years", "apy_cap_pct"])
    c = c[c.gsis_id.notna() & c.year_signed.notna()]
    dpk = dp.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id").set_index("gsis_id")
    tg = pd.read_parquet(os.path.join(HERE, "data", "team_games.parquet"))
    wcol = [x for x in tg.columns if x in ("win", "won", "w")]
    need = []
    for Y in range(2014, 2026):
        s1 = S[S.season == Y - 1]
        cy = c[c.year_signed <= Y - 1].sort_values("year_signed").groupby("gsis_id").tail(1).set_index("gsis_id")
        for (t, ps), g in s1.groupby(["tc", "pos"]):
            g = g.sort_values("half", ascending=False); lead = g.iloc[0]
            b = pl.get(lead.pid); age = (pd.Timestamp(f"{Y}-09-01") - pd.Timestamp(b)).days / 365.25 if isinstance(b, str) else np.nan
            exp_ = np.nan
            if lead.pid in cy.index:
                r = cy.loc[lead.pid]; exp_ = float((r.year_signed + (r.years or 1) - 1) <= Y - 1)
            hi_recent = 0.0
            for pid in g.pid:
                if pid in dpk.index and dpk.loc[pid, "pick"] <= 64 and Y - dpk.loc[pid, "season"] <= 3: hi_recent = 1.0
            picks = dp[(dp.season == Y) & (dp.tc == t) & (dp.position == ps)]
            need.append({"season": Y, "tc": t, "pos": ps, "lead_half": lead.half, "lead_ppg": lead.half / max(lead.g, 1), "room_half": g.half.sum(),
                         "second_half": g.half.iloc[1] if len(g) > 1 else 0.0, "lead_age": age, "lead_expiring": exp_, "hi_recent": hi_recent,
                         "e12": float((picks.pick <= 64).any()), "e1": float((picks["round"] == 1).any()), "e3": float((picks["round"] <= 3).any())})
    T = pd.DataFrame(need)
    if {"season", "team"} <= set(tg.columns) and ("pf" in tg.columns or "points_for" in tg.columns or "pts" in tg.columns):
        pfc = [x for x in ("pf", "points_for", "pts") if x in tg.columns][0]; pac = [x for x in ("pa", "points_against", "opp_pts") if x in tg.columns]
        if pac:
            w = tg.assign(tc=canon(tg.team), win=(tg[pfc] > tg[pac[0]]).astype(float)).groupby(["season", "tc"]).win.mean()
            T["win1"] = [w.get((y - 1, t), np.nan) for y, t in zip(T.season, T.tc)]
    if "win1" not in T: T["win1"] = np.nan
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    NF = ["lead_half", "lead_ppg", "room_half", "second_half", "lead_age", "lead_expiring", "hi_recent", "win1"]
    T["p12"] = np.nan
    for Y in YEARS:
        for ps in POS4:
            tr = T[(T.season < Y) & (T.pos == ps)]; te = (T.season == Y) & (T.pos == ps)
            if len(tr) < 30 or tr.e12.sum() < 3: T.loc[te, "p12"] = tr.e12.mean() if len(tr) else np.nan; continue
            A, B = PM.prep(tr[NF].values.astype(float), T.loc[te, NF].values.astype(float)); mu, sd = A.mean(0), A.std(0); sd[sd == 0] = 1
            T.loc[te, "p12"] = LogisticRegression(C=0.3, max_iter=500).fit((A - mu) / sd, tr.e12.values).predict_proba((B - mu) / sd)[:, 1]
    pmap = T.set_index(["season", "tc", "pos"]).p12
    D["p_need"] = [pmap.get((y, t, p), np.nan) for y, t, p in zip(D.season, D.t1c, D.pos)]
    def needfn(DY, Y):
        m = DY.season == Y
        DY.loc[m, "drafted_comp"] = DY.p_need[m].fillna(DY.drafted_comp[(DY.season < Y)].mean())
    s7_need = walk_override(D, needfn)

    for nm, s in (("asis", D.s7), ("fix", s7_fix), ("blind", s7_blind), ("exp", s7_exp), ("nov", s7_nov), ("need", s7_need), ("blindf", s7_blindf), ("expf", s7_expf)):
        D["pg_" + nm] = 0.75 * s.values + 0.25 * D.ridge_stats
        D["tot_" + nm] = D["pg_" + nm] * D.g_use * D.G
    P(f"  check: pg rebuilt from the stored S7 vs the stored pg, max |diff| = {np.nanmax(np.abs(D.pg_asis - D.pg)):.6f}")

    # ------------------------------------------------------------ groups + roles
    best = dp.groupby(["season", "tc", "position"])["round"].min()
    def grp(col):
        r = np.array([best.get((y, t, p), 99) for y, t, p in zip(D.season, D[col], D.pos)])
        return np.select([r == 1, r == 2, r == 3, r <= 7], ["R1", "R2", "R3", "R4-7"], "none")
    D["g_w1"] = grp("tc"); D["g_nov"] = grp("t1c")
    rk = S.assign(rk=S.groupby(["season", "tc", "pos"]).half.rank(ascending=False, method="first")).set_index(["season", "pid"])
    D["rk1"] = [rk.rk.get((y - 1, p), np.nan) for y, p in zip(D.season, D.pid)]; D["gprev"] = [rk.g.get((y - 1, p), 0) for y, p in zip(D.season, D.pid)]
    prk = S.assign(prk=S.groupby(["season", "pos"]).half.rank(ascending=False, method="first")).set_index(["season", "pid"]).prk
    D["prk1"] = [prk.get((y - 1, p), np.nan) for y, p in zip(D.season, D.pid)]
    D["role"] = np.where((D.rk1 <= np.where(D.pos == "WR", 2, 1)) & (D.gprev >= 6), "lead", "depth")
    V = D[(D.rookie == 0) & D.season.isin(YEARS) & D.pg.notna() & D.pos.isin(POS4)].copy()
    bad = V[V.pg > 30]
    P(f"\n  dropped from the group tables: {len(bad)} rows with a per-game projection above 30 (position-switch artefacts already flagged in A9: "
      + ", ".join(f"{r.name} {r.season} {r.pos} {r.pg:.0f}" for r in bad.itertuples()) + ")")
    V = V[V.pg <= 30].copy()
    V["cl"] = V.season.astype(str) + V.tc
    V["proj_games"] = V.g_use * V.G
    P(f"\n  veterans graded: {len(V)} player-seasons ({V.pos.value_counts().to_dict()}); 4+ games played: {int((V.act_games >= 4).sum())}")
    P("  role = last season's rank on his team at the position by half-PPR points: lead = #1 (QB/RB/TE) or top 2 (WR) with 6+ games; depth = the rest")
    P("  errors are projected minus actual (positive = OVER-projected). per-game: players with 4+ games. totals: everyone (0 games = 0 points).")
    P("  'vs none' = that group's mean error minus the same position/role's mean error when the team took NO pick at the position;")
    P(f"  90% interval from a cluster bootstrap over team-seasons ({NB} draws). Cells under 20 player-seasons are marked SMALL.")

    P("\n  how often it happens (team-seasons 2015-25, 352 per position): share of teams taking a pick at the position")
    P("| pos | round 1 | round 2 | round 3 | any of rounds 1-3 |"); P("|---|---|---|---|---|")
    for ps in POS4:
        b = best[best.index.get_level_values(0) >= 2015]; b = b[b.index.get_level_values(2) == ps]
        P(f"| {ps} | {(b == 1).sum() / 352 * 100:.0f}% | {(b == 2).sum() / 352 * 100:.0f}% | {(b == 3).sum() / 352 * 100:.0f}% | {(b <= 3).sum() / 352 * 100:.0f}% |")

    def cell(x, gcol, g, ctl, pgcol, totcol):
        m = (x[gcol] == g).values if isinstance(g, str) else x[gcol].isin(g).values
        c0 = (x[gcol] == ctl).values if isinstance(ctl, str) else x[gcol].isin(ctl).values
        pgm = (x.act_games >= 4).values
        epg = np.where(pgm, x[pgcol] - x.act_ppg, np.nan); et = (x[totcol] - x.act_total).values
        d1 = boot(epg, m, c0, x.cl.values); d2 = boot(et, m, c0, x.cl.values)
        n = int(m.sum()); npg = int((m & pgm).sum())
        ratio = x.act_total[m].sum() / max(x[totcol][m].sum(), 1e-9)
        return n, npg, d1, d2, ratio

    def block(title, gcol, pgcol, totcol, roles=("lead", "depth")):
        P(f"\n### {title}")
        P("| pos | role | group | n (4+ g) | per-game error | vs none [90%] | totals error | vs none [90%] | actual / projected total |"); P("|---|---|---|---|---|---|---|---|---|")
        for ps in POS4:
            for ro in roles:
                x = V[(V.pos == ps) & ((V.role == ro) if ro != "all" else True)]
                for g, lab in (("R1", "R1"), ("R2", "R2"), (["R1", "R2"], "R1-2"), ("R3", "R3"), ("R4-7", "R4-7"), ("none", "none")):
                    n, npg, d1, d2, ratio = cell(x, gcol, g, "none", pgcol, totcol)
                    if n == 0: continue
                    sm = " SMALL" if n < 20 else ""
                    if lab == "none":
                        P(f"| {ps} | {ro} | none | {n} ({npg}) | {d1[3]:+.2f} | - | {d2[3]:+.1f} | - | {ratio:.2f} |")
                    else:
                        P(f"| {ps} | {ro} | {lab}{sm} | {n} ({npg}) | {d1[3]:+.2f} | {d1[0]:+.2f} [{d1[1]:+.2f}, {d1[2]:+.2f}] | {d2[3]:+.1f} | {d2[0]:+.1f} [{d2[1]:+.1f}, {d2[2]:+.1f}] | {ratio:.2f} |")

    P("\n## 2. Post-draft view: the stored backtest projection, grouped by the WEEK-1 team's draft")
    block("2a. AS-IS model (drafted_comp as stored, week-1 chart)", "g_w1", "pg_asis", "tot_asis")
    P("\n## 3. Pre-draft view: what the 2027 early list does (no draft knowledge), grouped by LAST SEASON's team's draft")
    block("3a. BLIND (drafted_comp = 0 for the predicted season)", "g_nov", "pg_blind", "tot_blind")
    block("3b. NOV (BLIND + last season's final depth chart instead of week 1)", "g_nov", "pg_nov", "tot_nov")
    block("3c. NOV, all veterans at the position pooled (lead + depth)", "g_nov", "pg_nov", "tot_nov", roles=("all",))

    P("\n### 3c2. reconciling 2a and 3a: the same BLIND projection grouped by the WEEK-1 team instead (lead veterans)")
    P("| pos | group | n (4+ g) | per-game error | vs none [90%] | totals error | vs none [90%] |"); P("|---|---|---|---|---|---|---|")
    for ps in POS4:
        x = V[(V.pos == ps) & (V.role == "lead")]
        for g, lab in (("R1", "R1"), (["R1", "R2"], "R1-2"), ("R3", "R3"), ("none", "none")):
            n, npg, d1, d2, ratio = cell(x, "g_w1", g, "none", "pg_blind", "tot_blind")
            if n == 0: continue
            if lab == "none": P(f"| {ps} | none | {n} ({npg}) | {d1[3]:+.2f} | - | {d2[3]:+.1f} | - |")
            else: P(f"| {ps} | {lab}{' SMALL' if n < 20 else ''} | {n} ({npg}) | {d1[3]:+.2f} | {d1[0]:+.2f} [{d1[1]:+.2f}, {d1[2]:+.2f}] | {d2[3]:+.1f} | {d2[0]:+.1f} [{d2[1]:+.1f}, {d2[2]:+.1f}] |")
    P("  (week-1 grouping drops veterans who left after the pick and adds free agents who joined; the last-team grouping is what is knowable in November)")

    # where it comes from: games vs per-game
    P("\n### 3d. where the totals miss comes from (NOV projection, lead veterans): games vs per-game, mean projected - actual")
    P("| pos | group | n | projected games - actual games | per-game error (4+ g) | share finishing under 60% of projected total |"); P("|---|---|---|---|---|---|")
    for ps in POS4:
        x = V[(V.pos == ps) & (V.role == "lead")]
        for g in ("R1", "R2", "R3", "none"):
            y = x[x.g_nov == g]
            if len(y) == 0: continue
            pgm = y.act_games >= 4
            P(f"| {ps} | {g}{' SMALL' if len(y) < 20 else ''} | {len(y)} | {(y.proj_games - y.act_games).mean():+.1f} | {(y.pg_nov - y.act_ppg)[pgm].mean():+.2f} | {(y.act_total < .6 * y.tot_nov).mean()*100:.0f}% |")

    # ADP top-150
    P("\n### 3e. draftable veterans only (FFC ADP top 150), NOV projection, lead + depth pooled")
    P("| pos | group | n (4+ g) | per-game error | vs none [90%] | totals error | vs none [90%] |"); P("|---|---|---|---|---|---|---|")
    for ps in POS4:
        x = V[(V.pos == ps) & (V.adp <= 150)]
        for g, lab in ((["R1", "R2"], "R1-2"), ("R3", "R3"), ("none", "none")):
            n, npg, d1, d2, ratio = cell(x, "g_nov", g, "none", "pg_nov", "tot_nov")
            if n == 0: continue
            if lab == "none": P(f"| {ps} | none | {n} ({npg}) | {d1[3]:+.2f} | - | {d2[3]:+.1f} | - |")
            else: P(f"| {ps} | {lab}{' SMALL' if n < 20 else ''} | {n} ({npg}) | {d1[3]:+.2f} | {d1[0]:+.2f} [{d1[1]:+.2f}, {d1[2]:+.2f}] | {d2[3]:+.1f} | {d2[0]:+.1f} [{d2[1]:+.1f}, {d2[2]:+.1f}] |")

    P("\n### 3f. LAST season's fantasy starters (position rank by half-PPR total: QB top 18, RB top 30, WR top 42, TE top 15), NOV projection, by last team's draft")
    P("  (a pre-draft-knowable cut; 3e uses week-1 ADP, which already dropped the veterans the market wrote off after the draft)")
    P("| pos | group | n (4+ g) | per-game error | vs none [90%] | totals error | vs none [90%] | actual / projected total | finished under 60% of projection |"); P("|---|---|---|---|---|---|---|---|---|")
    for ps in POS4:
        x = V[(V.pos == ps) & (V.prk1 <= {"QB": 18, "RB": 30, "WR": 42, "TE": 15}[ps])]
        for g, lab in (("R1", "R1"), ("R2", "R2"), (["R1", "R2"], "R1-2"), ("R3", "R3"), ("R4-7", "R4-7"), ("none", "none")):
            n, npg, d1, d2, ratio = cell(x, "g_nov", g, "none", "pg_nov", "tot_nov")
            if n == 0: continue
            mm = (x.g_nov == g) if isinstance(g, str) else x.g_nov.isin(g)
            bust = (x.act_total[mm] < .6 * x.tot_nov[mm]).mean() * 100
            if lab == "none": P(f"| {ps} | none | {n} ({npg}) | {d1[3]:+.2f} | - | {d2[3]:+.1f} | - | {ratio:.2f} | {bust:.0f}% |")
            else: P(f"| {ps} | {lab}{' SMALL' if n < 20 else ''} | {n} ({npg}) | {d1[3]:+.2f} | {d1[0]:+.2f} [{d1[1]:+.2f}, {d1[2]:+.2f}] | {d2[3]:+.1f} | {d2[0]:+.1f} [{d2[1]:+.1f}, {d2[2]:+.1f}] | {ratio:.2f} | {bust:.0f}% |")
    for ps in ("QB", "RB", "TE"):
        y = V[(V.pos == ps) & (V.prk1 <= {"QB": 18, "RB": 30, "TE": 15}[ps]) & V.g_nov.isin(["R1", "R2"])].sort_values(["season", "name"])
        P(f"  {ps} R1-2 cases: " + "; ".join(f"{r.season} {r.name} {r.t1c} {r.tot_nov:.0f} -> {r.act_total:.0f}" for r in y.itertuples()))

    # ------------------------------------------------------------ 4. repairs
    P("\n## 4. Can it be repaired BEFORE the draft? (all veterans 2015-25, walk-forward)")
    P("  November team-need model: P(team takes a top-64 pick at the position), walk-forward logit")
    P("| pos | team-seasons | base rate | AUC (out of sample) | hit rate in the top fifth by P | hit rate in the bottom half |"); P("|---|---|---|---|---|---|")
    for ps in POS4:
        x = T[(T.pos == ps) & T.season.isin(YEARS) & T.p12.notna()]
        q = x.p12.rank(pct=True)
        P(f"| {ps} | {len(x)} | {x.e12.mean()*100:.0f}% | {roc_auc_score(x.e12, x.p12):.2f} | {x.e12[q >= .8].mean()*100:.0f}% | {x.e12[q < .5].mean()*100:.0f}% |")

    def grade(x, pgcol, totcol):
        m = x.act_games >= 4
        mae = float(np.sum(x.act_games[m] * np.abs(x[pgcol] - x.act_ppg)[m]) / x.act_games[m].sum())
        bias = float(np.sum(x.act_games[m] * (x[pgcol] - x.act_ppg)[m]) / x.act_games[m].sum())
        rho = float(np.nanmean([spearmanr(g[pgcol], g.act_ppg).correlation for _, g in x[m].groupby("season") if len(g) >= 12]))
        return mae, bias, rho, float(np.mean(np.abs(x[totcol] - x.act_total))), float(np.mean(x[totcol] - x.act_total))
    VAR = (("BLIND (today)", "blind"), ("EXPECTED haircut", "exp"), ("NEED proxy", "need"), ("AS-IS post-draft", "asis"), ("FIXED codes post-draft", "fix"))
    for lab, sub in (("all veterans", V), ("ADP top 150", V[V.adp <= 150]), ("lead veterans whose last team took a R1-2 pick", V[(V.role == "lead") & V.g_nov.isin(["R1", "R2"])])):
        P(f"\n  {lab}: per-game MAE / signed bias / rank corr within season; totals MAE / bias")
        P("| pos | n | " + " | ".join(a for a, _ in VAR) + " |"); P("|---|---|" + "---|" * len(VAR))
        for ps in POS4:
            x = sub[sub.pos == ps]
            if len(x) < 5: continue
            o = []
            for _, k in VAR:
                g = grade(x, "pg_" + k, "tot_" + k); o.append(f"{g[0]:.3f} / {g[1]:+.2f} / {g[2]:.3f}; {g[3]:.1f} / {g[4]:+.1f}")
            P(f"| {ps} | {len(x)} | " + " | ".join(o) + " |")
    P("\n  per-season wins on per-game MAE (all veterans, seasons 2015-25): candidate better than BLIND in how many of 11 seasons")
    P("| pos | EXPECTED | NEED | AS-IS post-draft | FIXED codes vs AS-IS |"); P("|---|---|---|---|---|")
    for ps in POS4:
        w = {k: 0 for k in ("exp", "need", "asis", "fixasis")}
        for Y in YEARS:
            x = V[(V.pos == ps) & (V.season == Y)]
            b = grade(x, "pg_blind", "tot_blind")[0]
            for k in ("exp", "need", "asis"): w[k] += grade(x, "pg_" + k, "tot_" + k)[0] < b
            w["fixasis"] += grade(x, "pg_fix", "tot_fix")[0] < grade(x, "pg_asis", "tot_asis")[0]
        P(f"| {ps} | {w['exp']}/11 | {w['need']}/11 | {w['asis']}/11 | {w['fixasis']}/11 |")
    P("\n  size of the model's own draft adjustment (AS-IS minus BLIND, veterans flagged by the stored input): mean per-game change")
    for ps in POS4:
        x = V[(V.pos == ps) & (V.drafted_comp == 1)]
        P(f"   {ps}: n {len(x)}, {(x.pg_asis - x.pg_blind).mean():+.2f} per game ({((x.pg_asis - x.pg_blind) / x.pg_blind).mean()*100:+.1f}%); lead only {(x.pg_asis - x.pg_blind)[x.role == 'lead'].mean():+.2f}")
    P("\n## 5. The lead veterans behind the small round-1 cells (season, player, last team: NOV projected total -> actual)")
    for ps in ("QB", "RB", "TE"):
        y = V[(V.pos == ps) & (V.role == "lead") & (V.g_nov == "R1")].sort_values(["season", "name"])
        P(f"  {ps}: " + "; ".join(f"{r.season} {r.name} {r.t1c} {r.tot_nov:.0f} -> {r.act_total:.0f}" for r in y.itertuples()))
    keep = ["season", "pid", "name", "pos", "team", "tc", "t1c", "role", "g_w1", "g_nov", "adp", "act_games", "act_ppg", "act_total", "g_use", "G", "drafted_comp", "dcomp_fix", "p_need", "dc", "dc_prev"] + [c for c in V.columns if c.startswith(("pg_", "tot_"))]
    V[keep].to_parquet(os.path.join(HERE, "data", "a17_vet_rows.parquet"), index=False)
    T.to_parquet(os.path.join(HERE, "data", "a17_team_need.parquet"), index=False)
    P("\n  rows -> data/a17_vet_rows.parquet, data/a17_team_need.parquet")


if __name__ == "__main__":
    main()
