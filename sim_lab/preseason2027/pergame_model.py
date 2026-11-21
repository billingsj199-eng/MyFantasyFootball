#!/usr/bin/env python3
"""
2027 PRESEASON (IN-HOUSE) - per-game model v1: diagnosis + structural rebuild. Jack 2026-11-21: "have it work on the per-game model".

In-house rules: no outside projections. ADP is the benchmark (it defines the ADP top-150 grading pool only). An ADP-ANCHORED
variant is reported separately and labelled. Vegas win totals stay. Walk-forward 2015-25 (fit on seasons < Y only); design
decisions are made on 2015-22 ("dev"); 2023-25 is the untouched final check. Pre-2018 FFC ADP is mixed-format (PPR/standard).

Structure (per game, half-PPR):  points = sum over stats of  VOLUME/g x EFFICIENCY  + small position constants
  volume (ridge per position):  targets/g, carries/g, pass attempts/g
  efficiency (empirical-Bayes shrink of the player's opportunity-weighted 3-season history toward a prior rate; the shrink
       strength k is fit per stat on the training seasons):  rec/tgt, rec yds/tgt, rec TD/tgt, rush yds/car, rush TD/car,
       pass yds/att, pass TD/att, INT/att  (TD rates get the biggest k = regressed hardest, as the fit decides)
  constants: fumbles lost / 2-pt per game by position (train mean)
Stages (ablation, each adds one piece): S1 structure + basic volume features | S2 + team context | S3 + roster changes |
  S4 + experience curves (rookie / yr2 / yr3 priors, JM) | S5 + RB specifics | S6 blend with the old in-house ridge.
Writes pergame_model.log (log of record; opened only by main()), data/pergame_rows.parquet.
"""
import json, os, re, sys, time, warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM

DATA = PM.DATA; CACHE = PM.CACHE; POS4 = PM.POS4; SIM = PM.SIM
LOG = None
LOG_NAME = "pergame_model.log"
DEV = list(range(2015, 2023)); FINAL = [2023, 2024, 2025]


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


# ------------------------------------------------------------------ stat history
def stat_seasons():
    W = pd.read_parquet(os.path.join(DATA, "player_weeks.parquet"))
    W = W[W.week < W.season.map(PM.final_week)]
    S = W.groupby(["season", "pid"]).agg(g=("half", "size"), half=("half", "sum"), tgt=("tgt", "sum"), rec=("rec", "sum"), cyd=("cyd", "sum"),
                                          ctd=("ctd", "sum"), car=("car", "sum"), ryd=("ryd", "sum"), rtd=("rtd", "sum"), att=("att", "sum"),
                                          pyd=("pyd", "sum"), ptd=("ptd", "sum"), int_=("int_", "sum"), fl=("fl", "sum"), tp=("tp", "sum"),
                                          team=("team", lambda s: s.value_counts().index[0]), pos=("position", "first")).reset_index()
    return S


EFF = {  # stat: (numerator, denominator)
    "rec_t": ("rec", "tgt"), "cyd_t": ("cyd", "tgt"), "ctd_t": ("ctd", "tgt"),
    "ryd_c": ("ryd", "car"), "rtd_c": ("rtd", "car"),
    "pyd_a": ("pyd", "att"), "ptd_a": ("ptd", "att"), "int_a": ("int_", "att"),
}
VOL = ("tgt", "car", "att")


def add_history(D, S):
    s = S.set_index(["season", "pid"])
    for k, w in ((1, 5.0), (2, 3.0), (3, 2.0)):
        sub = s.reindex(list(zip(D.season - k, D.pid)))
        for c in ("g", "tgt", "rec", "cyd", "ctd", "car", "ryd", "rtd", "att", "pyd", "ptd", "int_", "fl", "tp"):
            D[f"h{k}_{c}"] = sub[c].values
    for c in ("tgt", "car", "att"):
        g1 = D.h1_g.replace(0, np.nan)
        D[f"{c}pg1"] = D[f"h1_{c}"] / g1
        D[f"{c}pg2"] = D[f"h2_{c}"] / D.h2_g.replace(0, np.nan)
        num = sum(w * D[f"h{k}_{c}"].fillna(0) for k, w in ((1, 5), (2, 3), (3, 2)))
        den = sum(w * D[f"h{k}_g"].fillna(0) for k, w in ((1, 5), (2, 3), (3, 2)))
        D[f"{c}pgw"] = num / den.replace(0, np.nan)
    # weighted efficiency history (numerator / denominator sums, recency 5/3/2) for the EB shrink
    for e, (n_, d_) in EFF.items():
        D[f"num_{e}"] = sum(w * D[f"h{k}_{n_}"].fillna(0) for k, w in ((1, 1.0), (2, .7), (3, .5)))
        D[f"den_{e}"] = sum(w * D[f"h{k}_{d_}"].fillna(0) for k, w in ((1, 1.0), (2, .7), (3, .5)))
    # actual targets for season Y
    sy = s.reindex(list(zip(D.season, D.pid)))
    for c in ("g", "tgt", "rec", "cyd", "ctd", "car", "ryd", "rtd", "att", "pyd", "ptd", "int_", "fl", "tp"):
        D[f"y_{c}"] = sy[c].values
    for c in VOL: D[f"y_{c}pg"] = D[f"y_{c}"] / D.y_g.replace(0, np.nan)
    for e, (n_, d_) in EFF.items(): D[f"y_{e}"] = D[f"y_{n_}"] / D[f"y_{d_}"].replace(0, np.nan)
    return D


def add_context(D, S):
    """roster changes (position-specific vacated / arrived volume, drafted competition), new head coach, injury return,
    backup -> starter, experience flags, JM, RB specifics."""
    w1t = PM.week1_team()
    rost = {}
    for (Y, pid), t in w1t.items(): rost.setdefault((Y, t), set()).add(pid)
    posmap = dict(zip(S.pid, S.pos))
    vac, arr = {}, {}
    for (Y, t), grp in S.groupby(["season", "team"]):
        stay = rost.get((Y + 1, t), set())
        for ps, col in (("RB", "car"), ("WR", "tgt"), ("TE", "tgt"), ("QB", "att")):
            g = grp[grp.pos == ps]; tot = g[col].sum()
            if tot <= 0: continue
            vac[(Y + 1, t, ps)] = g[~g.pid.isin(stay)][col].sum() / tot
    # arrivals: players on team t's week-1 roster in Y whose Y-1 team was different, their Y-1 volume / team t's Y-1 pos volume
    s1 = S.set_index(["season", "pid"])
    team_pos_vol = S.groupby(["season", "team", "pos"]).agg(tgt=("tgt", "sum"), car=("car", "sum"), att=("att", "sum"))
    for (Y, t), pids in rost.items():
        for ps, col in (("RB", "car"), ("WR", "tgt"), ("TE", "tgt"), ("QB", "att")):
            try: base = team_pos_vol.loc[(Y - 1, t, ps), col]
            except KeyError: continue
            if base <= 0: continue
            a = 0.0
            for p in pids:
                if posmap.get(p) != ps or (Y - 1, p) not in s1.index: continue
                r = s1.loc[(Y - 1, p)]
                if r.team != t: a += r[col]
            arr[(Y, t, ps)] = a / base
    D["vac_pos"] = [vac.get((y, t, p), np.nan) for y, t, p in zip(D.season, D.team, D.pos)]
    D["arr_pos"] = [arr.get((y, t, p), np.nan) for y, t, p in zip(D.season, D.team, D.pos)]
    dp = pd.read_parquet(os.path.join(CACHE, "draft_picks.parquet"), columns=["season", "pick", "team", "position", "gsis_id"])
    dp["team"] = dp.team.map(PM.tm)
    comp = {}
    for r in dp[dp.pick <= 64].itertuples(index=False): comp.setdefault((r.season, r.team, r.position), []).append(r.gsis_id)
    D["drafted_comp"] = [float(any(g != pid for g in comp.get((y, t, p), []))) for y, t, p, pid in zip(D.season, D.team, D.pos, D.pid)]
    sch = pd.read_csv(os.path.join(CACHE, "schedules_games.csv"))
    sch = sch[sch.game_type == "REG"]
    hc = {}
    for r in sch.itertuples(index=False):
        hc.setdefault((r.season, PM.tm(r.home_team)), r.home_coach); hc.setdefault((r.season, PM.tm(r.away_team)), r.away_coach)
    D["new_hc"] = [float(hc.get((y, t)) is not None and hc.get((y - 1, t)) is not None and hc.get((y, t)) != hc.get((y - 1, t))) for y, t in zip(D.season, D.team)]
    D["inj_return"] = ((D.h1_g.fillna(0) < 7) & (D.h2_g.fillna(0) >= 10)).astype(float)
    low = np.where(D.pos == "RB", D.csh1 < .35, np.where(D.pos == "QB", D.apg1.fillna(0) < 15, D.tsh1 < .12))
    D["to_starter"] = ((D.rookie == 0) & (D.dc == 1) & low).astype(float)
    D["yr2"] = (D.exp == 1).astype(float); D["yr3"] = (D.exp == 2).astype(float)
    s = open(os.path.join(SIM, "data", "jm_scores.js"), encoding="utf-8").read(); jm = json.loads(s[s.index("{"): s.rindex("}") + 1])
    D["jm"] = D.key.map(lambda k: jm.get(k, np.nan)); D["jm_young"] = np.where(D.exp <= 2, D.jm, np.nan)
    D["rb_old"] = ((D.pos == "RB") & (D.age >= 28)).astype(float)
    D["rb_heavy"] = (D.cpg1.fillna(0) >= 15).astype(float) * (D.pos == "RB")
    D["rb_recv"] = np.where(D.pos == "RB", D.tpg1, np.nan)
    D["lp_rook"] = np.where(D.rookie == 1, D.lpick, np.nan)
    return D


BASIC = ["tgtpg1", "tgtpg2", "tgtpgw", "carpg1", "carpg2", "carpgw", "attpg1", "attpgw", "g1", "gsh1", "age", "age2", "exp", "rookie", "lpick", "rd1", "rd2", "undrafted", "dc1", "dc2", "dcna"]
TEAM = ["team_pa1", "team_ra1", "team_pf1", "exp_w", "moved", "new_hc", "new_qb", "qb1_ppg1", "is_qb1", "tsh1", "csh1"]
ROSTER = ["vac_pos", "arr_pos", "drafted_comp", "inj_return", "to_starter"]
EXPER = ["yr2", "yr3", "jm_young", "lp_rook"]
RBX = ["rb_old", "rb_heavy", "rb_recv"]
STAGES = [("S1 structure+basic", BASIC), ("S2 +team context", BASIC + TEAM), ("S3 +roster changes", BASIC + TEAM + ROSTER),
          ("S4 +experience/JM", BASIC + TEAM + ROSTER + EXPER), ("S5 +RB specifics", BASIC + TEAM + ROSTER + EXPER + RBX),
          # S7 = what the leave-one-out ablation (pergame_ablation.log) kept ON DEV 2015-22 ONLY: drop team context, JM, yr2/yr3 flags, RB extras
          ("S7 lean (dev-picked)", BASIC + ROSTER + ["lp_rook"])]
VOL_OF = {"QB": ("att", "car"), "RB": ("car", "tgt"), "WR": ("tgt", "car"), "TE": ("tgt",)}


def fit_k(train, e, prior):
    """EB shrink strength for one efficiency stat: pick k minimising opportunity-weighted squared error of next-season rate."""
    m = train[f"y_{e}"].notna() & (train[f"y_{EFF[e][1]}"] >= 10)
    if m.sum() < 30: return 50.0
    num, den, y, w = train[f"num_{e}"][m].values, train[f"den_{e}"][m].values, train[f"y_{e}"][m].values, train[f"y_{EFF[e][1]}"][m].values
    pr = prior[m.values] if hasattr(prior, "__len__") else prior
    best = None
    for k in (5, 10, 20, 40, 80, 160, 320, 640, 1280, 2560):
        est = (num + k * pr) / (den + k)
        err = np.sum(w * (est - y) ** 2)
        if best is None or err < best[0]: best = (err, k)
    return float(best[1])


def walk(D, feats, tag, use_role_prior=False, td_team=False):
    from sklearn.linear_model import Ridge
    out = pd.Series(np.nan, index=D.index); comp = {}
    ks = []
    for Y in PM.TEST_YEARS:
        for ps in POS4:
            tr = (D.season < Y) & (D.pos == ps) & (D.y_g >= 4); te = (D.season == Y) & (D.pos == ps)
            if tr.sum() < 100 or te.sum() == 0: continue
            w = D.y_g[tr].values * 0.5 ** ((Y - 1 - D.season[tr].values) / 4.0)
            Xtr = D.loc[tr, feats].values.astype(float); Xte = D.loc[te, feats].values.astype(float)
            A, B = PM.prep(Xtr, Xte); mu, sd = A.mean(0), A.std(0); sd[sd == 0] = 1; A = (A - mu) / sd; B = (B - mu) / sd
            vol = {}
            for v in ("tgt", "car", "att"):
                y = D[f"y_{v}pg"][tr].fillna(0).values
                vol[v] = np.maximum(0, Ridge(alpha=10.0).fit(A, y, sample_weight=w).predict(B)) if (v in VOL_OF[ps] or y.mean() > .3) else np.zeros(te.sum())
            eff = {}
            trD = D[tr]; teD = D[te]
            for e, (n_, d_) in EFF.items():
                yy = trD[f"y_{e}"]; ww = trD[f"y_{d_}"].fillna(0)
                if ww.sum() < 50: eff[e] = np.zeros(te.sum()); continue
                pm = float(np.nansum(trD[f"y_{n_}"]) / max(np.nansum(trD[f"y_{d_}"]), 1))   # position prior rate (pooled)
                if use_role_prior:   # rookies / no-history players: prior from rookies of the same position (train)
                    rk = trD[trD.rookie == 1]; prk = float(np.nansum(rk[f"y_{n_}"]) / max(np.nansum(rk[f"y_{d_}"]), 1)) if np.nansum(rk[f"y_{d_}"]) > 30 else pm
                    pr_tr = np.where(trD.rookie == 1, prk, pm); pr_te = np.where(teD.rookie == 1, prk, pm)
                else:
                    pr_tr = pm; pr_te = pm
                k = fit_k(trD, e, pr_tr); ks.append((Y, ps, e, k))
                eff[e] = (teD[f"num_{e}"].values + k * pr_te) / (teD[f"den_{e}"].values + k)
            if td_team:   # team scoring environment scales TD rates (exp wins), fit on train as a ratio slope
                pass
            fl = float(np.nansum(trD.y_fl) / max(np.nansum(trD.y_g), 1)); tp = float(np.nansum(trD.y_tp) / max(np.nansum(trD.y_g), 1))
            ppg = (vol["tgt"] * (0.5 * eff["rec_t"] + 0.1 * eff["cyd_t"] + 6 * eff["ctd_t"]) + vol["car"] * (0.1 * eff["ryd_c"] + 6 * eff["rtd_c"])
                   + vol["att"] * (0.04 * eff["pyd_a"] + 4 * eff["ptd_a"] - eff["int_a"]) - 2 * fl + 2 * tp)
            out.loc[te] = np.maximum(0.3, ppg)
            for v in vol: comp.setdefault(f"{tag}_v_{v}", pd.Series(np.nan, index=D.index)).loc[te] = vol[v]
            for e in eff: comp.setdefault(f"{tag}_e_{e}", pd.Series(np.nan, index=D.index)).loc[te] = eff[e]
    return out, comp, ks


# ------------------------------------------------------------------ grading
def wmae(p, a, w): return float(np.sum(w * np.abs(p - a)) / np.sum(w))


def grade(R, cols, mask, label, base="adp_curve_f", years=None):
    m = mask & (R.act_games >= 4)
    for c in cols: m &= R[c].notna()
    ys = years or sorted(R[m].season.unique())
    P(f"\n  {label} (n {int(m.sum())}): model | MAE | rho (pos-season) | seasons beating ADP on MAE")
    out = {}
    for c in cols:
        a, p, w = R.act_ppg[m], R[c][m], R.act_games[m].astype(float)
        rh = [spearmanr(g[c], g.act_ppg).correlation for _, g in R[m].groupby(["season", "pos"]) if len(g) >= 12]
        wins = sum(wmae(R[c][m & (R.season == y)], R.act_ppg[m & (R.season == y)], R.act_games[m & (R.season == y)]) <
                   wmae(R[base][m & (R.season == y)], R.act_ppg[m & (R.season == y)], R.act_games[m & (R.season == y)]) for y in ys if (m & (R.season == y)).sum() >= 15)
        ny = sum(1 for y in ys if (m & (R.season == y)).sum() >= 15)
        out[c] = (wmae(p, a, w), float(np.nanmean(rh)))
        P(f"    {c:22s} {out[c][0]:6.3f} {out[c][1]:6.3f}   {wins}/{ny}" if c != base else f"    {c:22s} {out[c][0]:6.3f} {out[c][1]:6.3f}   (benchmark)")
    return out


def main():
    global LOG
    LOG = open(os.path.join(HERE, LOG_NAME), "w", encoding="utf-8")
    t0 = time.time()
    P("=== In-house per-game model v1 (walk-forward 2015-25; dev 2015-22, final check 2023-25) ===")
    D = PM.build()
    S = stat_seasons()
    D = add_history(D, S); D = add_context(D, S)
    R0 = PM.walk_forward(D)     # old in-house ridge_stats + ADP curve benchmark + naive
    for c in ("ridge_stats", "adp_curve_f", "naive_f", "adp_curve", "anchor_mix"): D[c] = R0[c].values
    pool = D.season.isin(PM.TEST_YEARS) & D.adp.notna() & (D.adp <= 150)

    # ---------------- STEP 1: diagnosis on the old in-house model
    P("\n=== STEP 1. Diagnosis: old in-house (ridge_stats) vs ADP curve, ADP top 150, games-weighted PPG MAE ===")
    X = D[pool & (D.act_games >= 4) & D.adp_curve_f.notna()].copy()
    X["e_old"] = (X.ridge_stats - X.act_ppg).abs(); X["e_adp"] = (X.adp_curve_f - X.act_ppg).abs(); X["w"] = X.act_games
    X["expg"] = np.select([X.rookie == 1, X.exp == 1, X.exp.between(2, 4)], ["rookie", "year 2", "years 3-5"], "veteran")
    X["band"] = pd.cut(X.adp, [0, 30, 100, 150], labels=["ADP 1-30", "31-100", "101-150"])
    groups = [("all", np.ones(len(X), bool))]
    for ps in POS4: groups.append((ps, (X.pos == ps).values))
    for b in ("ADP 1-30", "31-100", "101-150"): groups.append((b, (X.band == b).values))
    for e in ("rookie", "year 2", "years 3-5", "veteran"): groups.append((e, (X.expg == e).values))
    for lab, c in (("changed team", "moved"), ("new QB1", "new_qb"), ("new head coach", "new_hc"), ("drafted competition (rd 1-2)", "drafted_comp"),
                   ("back from a short season", "inj_return"), ("backup -> week-1 starter", "to_starter")):
        groups.append((lab, (X[c] == 1).values))
    groups.append(("RB rookies", ((X.pos == "RB") & (X.rookie == 1)).values)); groups.append(("RB vets 28+", ((X.pos == "RB") & (X.age >= 28)).values))
    P("  group                          n   MAE old  MAE ADP   gap   gap x n (pts) | bias old (act/pred) | bias ADP")
    rows = []
    for lab, mk in groups:
        g = X[mk]
        if len(g) < 15: continue
        eo, ea = np.average(g.e_old, weights=g.w), np.average(g.e_adp, weights=g.w)
        rows.append((lab, len(g), eo, ea, eo - ea, (eo - ea) * len(g), g.act_ppg.mul(g.w).sum() / g.ridge_stats.mul(g.w).sum(), g.act_ppg.mul(g.w).sum() / g.adp_curve_f.mul(g.w).sum()))
    for r in rows: P(f"  {r[0]:30s} {r[1]:4d}  {r[2]:6.3f}   {r[3]:6.3f}  {r[4]:+6.3f}   {r[5]:+7.1f}       | {r[6]:.3f} | {r[7]:.3f}")

    # ---------------- STEP 2: structural stages (ablation)
    P("\n=== STEP 2. Structural model stages (volume x efficiency), out of sample ===")
    preds = {}; comps = {}
    for lab, feats in STAGES:
        rp = lab.startswith("S4") or lab.startswith("S5") or lab.startswith("S7")
        pr, cp, ks = walk(D, feats, lab.split()[0], use_role_prior=rp)
        preds[lab] = pr; comps[lab] = cp
        D[lab] = pr.values
        if lab.startswith("S1"):
            kk = pd.DataFrame(ks, columns=["Y", "pos", "e", "k"]).groupby(["pos", "e"]).k.median()
            P("  efficiency shrink strength k (median over folds; opportunities of prior-rate weight): " + " ".join(f"{p}-{e}:{int(v)}" for (p, e), v in kk.items()))
    # S6: blend of the best stage with the old ridge (weight picked on dev years only)
    best_stage = None
    for lab, _ in STAGES:
        m = pool & D.season.isin(DEV) & (D.act_games >= 4) & D[lab].notna()
        e = wmae(D[lab][m], D.act_ppg[m], D.act_games[m])
        if best_stage is None or e < best_stage[0]: best_stage = (e, lab)
    bl = best_stage[1]
    mdev = pool & D.season.isin(DEV) & (D.act_games >= 4) & D[bl].notna() & D.ridge_stats.notna()
    wbest = min((wmae((wv * D[bl] + (1 - wv) * D.ridge_stats)[mdev], D.act_ppg[mdev], D.act_games[mdev]), wv) for wv in (0, .25, .5, .75, 1))[1]
    D["S6 blend"] = wbest * D[bl] + (1 - wbest) * D.ridge_stats
    P(f"  best stage on dev = {bl}; S6 = {wbest} x {bl} + {1-wbest} x old ridge (weight picked on 2015-22)")
    # ADP-anchored variant (comparison only): w x in-house + (1 - w) x ADP curve, w picked on dev
    md2 = pool & D.season.isin(DEV) & (D.act_games >= 4) & D["S6 blend"].notna() & D.adp_curve_f.notna()
    wa = min((wmae((wv * D["S6 blend"] + (1 - wv) * D.adp_curve_f)[md2], D.act_ppg[md2], D.act_games[md2]), wv) for wv in (0, .2, .35, .5, .65, .8, 1))[1]
    D["ADP-anchored (comparison)"] = np.where(D.adp_curve.notna(), wa * D["S6 blend"] + (1 - wa) * D.adp_curve_f, D["S6 blend"])
    P(f"  ADP-ANCHORED variant (comparison only, ADP is an input): {wa} x in-house + {1-wa} x ADP curve (picked on 2015-22)")
    cols = ["ridge_stats"] + [l for l, _ in STAGES] + ["S6 blend", "ADP-anchored (comparison)", "naive_f", "adp_curve_f"]
    P("\n  --- dev 2015-22 ---")
    grade(D, cols, pool & D.season.isin(DEV), "ADP top 150, dev 2015-22")
    P("\n  --- FINAL CHECK 2023-25 (not used for any choice) ---")
    grade(D, cols, pool & D.season.isin(FINAL), "ADP top 150, final 2023-25")
    P("\n  --- all 11 seasons ---")
    key = ["ridge_stats", "S6 blend", "ADP-anchored (comparison)", "naive_f", "adp_curve_f"]
    grade(D, key + [bl], pool, "ADP top 150, 2015-25")
    for ps in POS4: grade(D, key, pool & (D.pos == ps), f"{ps}")
    for lab, mk in (("ADP 1-30", D.adp <= 30), ("ADP 31-100", (D.adp > 30) & (D.adp <= 100)), ("ADP 101-150", (D.adp > 100) & (D.adp <= 150))): grade(D, key, pool & mk, lab)
    grade(D, key, pool & (D.rookie == 1), "rookies")
    grade(D, key, pool & (D.exp == 1), "year-2 players")
    grade(D, key, pool & (D.pos == "RB") & (D.rookie == 0), "RB veterans")
    # season-by-season MAE
    P("\n  season-by-season MAE (ADP top 150): season | old | S6 | ADP-anchored | ADP")
    for y in PM.TEST_YEARS:
        m = pool & (D.season == y) & (D.act_games >= 4) & D["S6 blend"].notna() & D.adp_curve_f.notna()
        P(f"    {y}: {wmae(D.ridge_stats[m], D.act_ppg[m], D.act_games[m]):.3f} | {wmae(D['S6 blend'][m], D.act_ppg[m], D.act_games[m]):.3f} | {wmae(D['ADP-anchored (comparison)'][m], D.act_ppg[m], D.act_games[m]):.3f} | {wmae(D.adp_curve_f[m], D.act_ppg[m], D.act_games[m]):.3f}")

    # ---------------- volume vs efficiency split (oracle swaps on the S5 structure)
    P("\n=== Volume vs efficiency: how much of the S5 miss each part explains (oracle swaps, ADP top 150) ===")
    cp = comps["S5 +RB specifics"]; m = pool & (D.act_games >= 4) & D["S5 +RB specifics"].notna()
    def assemble(vol_src, eff_src):
        v = {x: (D[f"y_{x}pg"].fillna(0) if vol_src == "act" else cp[f"S5_v_{x}"]) for x in ("tgt", "car", "att")}
        e = {x: (D[f"y_{x}"].fillna(cp[f"S5_e_{x}"]) if eff_src == "act" else cp[f"S5_e_{x}"]) for x in EFF}
        return (v["tgt"] * (0.5 * e["rec_t"] + 0.1 * e["cyd_t"] + 6 * e["ctd_t"]) + v["car"] * (0.1 * e["ryd_c"] + 6 * e["rtd_c"]) + v["att"] * (0.04 * e["pyd_a"] + 4 * e["ptd_a"] - e["int_a"]))
    for lab, vs, es in (("model volume x model efficiency", "m", "m"), ("ACTUAL volume x model efficiency", "act", "m"), ("model volume x ACTUAL efficiency", "m", "act")):
        p = assemble(vs, es)
        P(f"    {lab:36s} MAE {wmae(p[m], D.act_ppg[m], D.act_games[m]):.3f}")
    for ps in POS4:
        mm = m & (D.pos == ps)
        a, b, c_ = (wmae(assemble(*x)[mm], D.act_ppg[mm], D.act_games[mm]) for x in (("m", "m"), ("act", "m"), ("m", "act")))
        P(f"      {ps}: base {a:.3f} | fix volume -> {b:.3f} ({(b/a-1)*100:+.0f}%) | fix efficiency -> {c_:.3f} ({(c_/a-1)*100:+.0f}%)")
    P("  TD share of the efficiency miss: fixing only TD rates (act TD rates, model yards / catch rates):")
    def td_only():
        v = {x: cp[f"S5_v_{x}"] for x in ("tgt", "car", "att")}
        e = {x: cp[f"S5_e_{x}"] for x in EFF}
        for x in ("ctd_t", "rtd_c", "ptd_a"): e[x] = D[f"y_{x}"].fillna(cp[f"S5_e_{x}"])
        return (v["tgt"] * (0.5 * e["rec_t"] + 0.1 * e["cyd_t"] + 6 * e["ctd_t"]) + v["car"] * (0.1 * e["ryd_c"] + 6 * e["rtd_c"]) + v["att"] * (0.04 * e["pyd_a"] + 4 * e["ptd_a"] - e["int_a"]))
    P(f"    MAE {wmae(td_only()[m], D.act_ppg[m], D.act_games[m]):.3f}")

    # ---------------- end to end: season totals with the new games model
    P("\n=== End to end: season totals = per-game x games-played model (ADP top 150, 2015-25) ===")
    G = pd.read_parquet(os.path.join(DATA, "games_model_rows.parquet"), columns=["season", "pid", "g_main", "g_pb0", "g_pb1", "g_pb2", "g_pb3", "G"])
    D = D.merge(G.rename(columns={"G": "G2"}), on=["season", "pid"], how="left")
    D["tot_old"] = D.ridge_stats * D.g_main * D.G; D["tot_new"] = D["S6 blend"] * D.g_main * D.G
    D["tot_anchor"] = D["ADP-anchored (comparison)"] * D.g_main * D.G
    adp_tot = R0.set_index(["season", "pid"]).adp_total
    D["adp_total"] = adp_tot.reindex(list(zip(D.season, D.pid))).values
    pool2 = D.season.isin(PM.TEST_YEARS) & D.adp.notna() & (D.adp <= 150)
    m = pool2 & D.tot_new.notna() & D.adp_total.notna() & D.tot_old.notna()
    P("  model | MAE | Spearman (pos-season) | top-24")
    for c in ("tot_old", "tot_new", "tot_anchor", "adp_total"):
        rh, h24 = [], []
        for _, g in D[m].groupby(["season", "pos"]):
            if len(g) < 24: continue
            rh.append(spearmanr(g[c], g.act_total).correlation); h24.append(len(set(g.nlargest(24, c).pid) & set(g.nlargest(24, "act_total").pid)) / 24)
        lab = {"tot_old": "old in-house PPG x new games", "tot_new": "NEW in-house PPG x new games", "tot_anchor": "ADP-anchored PPG x new games (comparison)", "adp_total": "ADP (benchmark)"}[c]
        P(f"    {lab:44s} {np.mean(np.abs(D[c][m] - D.act_total[m])):6.2f} {np.mean(rh):6.3f} {np.mean(h24):6.3f}")
    # coverage: games distribution x walk-forward PPG ratio draws
    rng = np.random.default_rng(5); cov = []; BINS = [(0, 1), (2, 3), (4, 7), (8, 99)]
    for Y in PM.TEST_YEARS[2:]:
        for ps in POS4:
            past = (D.season < Y) & (D.season >= 2015) & (D.pos == ps) & (D.act_games >= 4) & D["S6 blend"].notna()
            te = pool2 & (D.season == Y) & (D.pos == ps) & D.g_pb0.notna() & D["S6 blend"].notna()
            if past.sum() < 50 or te.sum() == 0: continue
            ratio = ((D.act_ppg[past] + 1) / (D["S6 blend"][past] + 1)).values
            for i in np.where(te.values)[0]:
                r = D.iloc[i]; Gm = r.G; pb = np.array([r.g_pb0, r.g_pb1, r.g_pb2, r.g_pb3]); pb = pb / pb.sum()
                k = rng.choice(4, 2000, p=pb); lo = np.array([BINS[j][0] for j in k]); hi = np.array([min(BINS[j][1], Gm) for j in k])
                gm = np.clip(Gm - np.floor(lo + rng.random(2000) * (hi - lo + 1)), 0, Gm)
                tot = np.maximum(0, (r["S6 blend"] + 1) * rng.choice(ratio, 2000) - 1) * gm
                q10, q90 = np.quantile(tot, [.1, .9]); cov.append((r.act_total >= q10) & (r.act_total <= q90))
    P(f"  season-total p10-p90 coverage (2017-25): {np.mean(cov)*100:.1f}% (n {len(cov)}; target 80)")
    D.to_parquet(os.path.join(DATA, "pergame_rows.parquet"), index=False)
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
