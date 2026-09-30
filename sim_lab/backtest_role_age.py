#!/usr/bin/env python3
"""
PECKING ORDER x AGE backtest (Jack 2026-09-29, after the W1-3 2026 segment read).

Live W1-3 said: 2nd/3rd options on a team and young players score UNDER our
projection, established lead options and 9+-year veterans score OVER it.
Question: is that true 2019-25 on the same grading base every Sim Lab layer
uses (bt_common: P=5 blend x Vegas x FPA), and does a correction help?

Flags are all known before kickoff:
  role   rank of the player's projection among teammates at his position who
         play that week (1 = lead, 2, 3+)
  young  age on Sept 1: RB/WR <= 23, TE <= 24, QB <= 25
  vet    season >= rookie season + 8 (9th season or later)
Unlike bt_common.iter_samples this keeps each player's FIRST game (base = Clay
per game), because the live read was weeks 1-3.

Parts: A measurement (actual / projected, seasons agreeing), B same inside
projection tiers (is it role, or just low projections regressing?), C joint
regression per season, D leave-one-season-out multipliers, E stacked fix graded
on MSE / MAE / weekly within-position rank.
"""
import numpy as np, pandas as pd, json, os, sys
from collections import defaultdict
from bt_common import load_games, VEG, POS4, tm, player_ids
from backtest_sim_calibration import played, weekly_rec, infer_team, POOL_MIN_PTS, OPP_ALIAS
import backtest_sim_calibration as cal
from backtest_snap_defense import build_fpa
from backtest_target_area import YEARS, FPA_E, FPA_TRUST_G, P, CACHE

MIN_PROJ = 5.0
YOUNG = {"RB": 23, "WR": 23, "TE": 24, "QB": 25}
GRID = [round(x, 2) for x in np.arange(0.80, 1.2001, 0.02)]

def build():
    pl = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "birth_date", "rookie_season"])
    pl = pl[pl.gsis_id.notna()].drop_duplicates("gsis_id").set_index("gsis_id")
    resolve = player_ids()
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    weekly_fpa, season_fpa, lg_fpa = build_fpa()
    out = []
    for Y in YEARS:
        if str(Y) not in clay_hist: continue
        games = load_games(Y)
        avg = float(np.mean([v["implied"] for v in games.values() if v["implied"] is not None]))
        W = 16 if Y <= 2020 else 17
        sn = pd.read_parquet(os.path.join(CACHE, f"snap_counts_{Y}.parquet"), columns=["game_type", "week", "player", "offense_pct"])
        sn = sn[sn.game_type == "REG"]
        snap = defaultdict(dict)
        for r in sn.itertuples(index=False):
            snap[cal.norm(str(r.player))][int(r.week)] = float(r.offense_pct or 0)
        for name, c in clay_hist[str(Y)].items():
            pos = c.get("pos")
            if pos not in POS4 or (c.get("pts") or 0) < POOL_MIN_PTS: continue
            wrec = weekly_rec(name, pos)
            if wrec is None: continue
            team = infer_team(wrec, Y)
            if not team: continue
            pid = resolve(name, pos, Y)
            age = exp = None
            if pid is not None and pid in pl.index:
                b = pl.at[pid, "birth_date"]; rs = pl.at[pid, "rookie_season"]
                if isinstance(b, str) and len(b) >= 10: age = (pd.Timestamp(f"{Y}-09-01") - pd.Timestamp(b[:10])).days / 365.25
                if pd.notna(rs) and rs > 1990: exp = Y - int(rs)
            rows = sorted([(w["wk"], w["fpts"], OPP_ALIAS.get(w.get("opp"), w.get("opp"))) for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            sw = snap.get(cal.norm(name), {})
            hist = []
            for wk, fpts, opp in rows:
                gm = games.get((team, wk))
                if gm and gm["implied"] is not None and opp:
                    g = len(hist); ppg = (sum(hist) / g) if g else clay_pg
                    base = (P * clay_pg + g * ppg) / (P + g)
                    veg = min(1.35, max(0.7, 1 + VEG[pos] * (gm["implied"] - avg) / avg))
                    cur = weekly_fpa.get((Y, opp, pos), {}); past = [w for w in cur if w < wk]
                    fpa = 1.0
                    if past and lg_fpa.get((Y, pos)):
                        ratio = min(1.25, max(0.8, (sum(cur[w] for w in past) / len(past)) / lg_fpa[(Y, pos)]))
                        fpa = 1 + FPA_E * (ratio - 1) * min(1, len(past) / FPA_TRUST_G)
                    this = sw.get(wk); oth = [v for k, v in sw.items() if k != wk]
                    lim = (this < 0.6 * max(oth)) if (this is not None and oth and max(oth) > 0) else None
                    out.append({"year": Y, "name": name, "pos": pos, "team": team, "wk": wk, "act": float(fpts), "g": g,
                                "proj": base * veg * fpa, "age": age, "exp": exp, "lim": lim, "imp": gm["implied"]})
                hist.append(fpts)
        print(f"  {Y}: rows so far {len(out)}", flush=True)
    df = pd.DataFrame(out)
    df["rank"] = df.groupby(["year", "team", "pos", "wk"])["proj"].rank(ascending=False, method="first").astype(int)
    df = df[df.proj >= MIN_PROJ].copy()
    df["role"] = np.where(df["rank"] == 1, "lead", np.where(df["rank"] == 2, "2nd", "3rd+"))
    df["second"] = (df.pos != "QB") & (df["rank"] >= 2)
    df["young"] = df.apply(lambda r: bool(r.age is not None and not np.isnan(r.age) and r.age <= YOUNG[r.pos] + 0.999), axis=1)
    df["vet"] = df.exp.fillna(-1) >= 8
    df["known"] = df.age.notna() & df.exp.notna()
    df["healthy"] = df.lim != True
    df["err"] = df.proj - df.act
    return df

def ratio_line(label, d, years):
    if len(d) < 60:
        print(f"  {label:40s} n={len(d):5d}  (too few)"); return
    per = [(d[d.year == y].act.sum() / d[d.year == y].proj.sum()) for y in years if (d.year == y).sum() >= 8]
    r = d.act.sum() / d.proj.sum()
    h = d[d.healthy]; rh = h.act.sum() / h.proj.sum()
    e = d.err.values; t = e.mean() / (e.std() / np.sqrt(len(e)))
    under = sum(1 for x in per if x < 1)
    print(f"  {label:40s} n={len(d):5d}  actual/projected {r:.3f}  healthy-only {rh:.3f}  bias {e.mean():+5.2f} pts (t {t:+5.1f})  "
          f"seasons under projection {under}/{len(per)}  range {min(per):.2f}-{max(per):.2f}")

def part_a(df, years, title, d0):
    print(f"\n=== A. {title} ===")
    ratio_line("ALL", d0, years)
    for pos in ("RB", "WR", "TE"):
        for role in ("lead", "2nd", "3rd+"):
            ratio_line(f"{pos} {role}", d0[(d0.pos == pos) & (d0.role == role)], years)
    k = d0[d0.known]
    for pos in POS4:
        ratio_line(f"{pos} young (<= {YOUNG[pos]})", k[(k.pos == pos) & k.young], years)
        ratio_line(f"{pos} prime", k[(k.pos == pos) & ~k.young & ~k.vet], years)
        ratio_line(f"{pos} veteran (9th season +)", k[(k.pos == pos) & k.vet], years)
    for pos in ("RB", "WR"):
        for lab, m in (("lead", k["rank"] == 1), ("2nd/3rd", k["rank"] >= 2)):
            ratio_line(f"{pos} {lab} + young", k[(k.pos == pos) & m & k.young], years)
            ratio_line(f"{pos} {lab} + not young", k[(k.pos == pos) & m & ~k.young], years)

def part_b(df, years):
    print("\n=== B. is it ROLE or just low projections? actual/projected inside projection tiers (RB/WR/TE, all weeks) ===")
    d = df[df.pos != "QB"]
    for lo, hi in ((5, 8), (8, 11), (11, 15), (15, 99)):
        t = d[(d.proj >= lo) & (d.proj < hi)]
        parts = []
        for role in ("lead", "2nd", "3rd+"):
            x = t[t.role == role]
            parts.append(f"{role} {x.act.sum()/x.proj.sum():.3f} (n={len(x)})" if len(x) >= 60 else f"{role} - (n={len(x)})")
        k = t[t.known]
        for lab, m in (("young", k.young), ("prime", ~k.young & ~k.vet), ("vet", k.vet)):
            x = k[m]
            parts.append(f"{lab} {x.act.sum()/x.proj.sum():.3f} (n={len(x)})" if len(x) >= 60 else f"{lab} - (n={len(x)})")
        print(f"  proj [{lo:2d},{hi:2d})  " + " | ".join(parts))

def ols(X, y):
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ b; s2 = res @ res / (len(y) - X.shape[1])
    return b, np.sqrt(np.diag(s2 * np.linalg.pinv(X.T @ X)))

def part_c(df, years, d0, title):
    print(f"\n=== C. traits tested together, controlling for projection level ({title}; points we were too HIGH) ===")
    d = d0[d0.known]
    names = ["2nd/3rd option", "young", "veteran 9th season+", "proj 5-8", "proj 8-11", "proj 15+"]
    def X(d):
        return np.column_stack([np.ones(len(d)), d.second, d.young, d.vet, (d.proj < 8), (d.proj >= 8) & (d.proj < 11), d.proj >= 15]).astype(float)
    b, se = ols(X(d), d.err.values)
    per = {y: ols(X(d[d.year == y]), d[d.year == y].err.values)[0] for y in years}
    print(f"  baseline (lead, prime, proj 11-15): {b[0]:+.2f}")
    for i, n in enumerate(names, 1):
        sg = [per[y][i] for y in years]
        print(f"  {n:22s} {b[i]:+5.2f} pts (t {b[i]/se[i]:+5.1f})   seasons same sign {sum(1 for v in sg if np.sign(v) == np.sign(b[i]))}/{len(sg)}   per season " + " ".join(f"{v:+.1f}" for v in sg))

def loyo_mult(d, years, flag, label):
    """multiplier on flagged rows, chosen leave-one-season-out by MSE; returns per-row multiplier series."""
    f = d[flag]
    if len(f) < 150:
        print(f"  {label:34s} flagged n={len(f):5d}  (too few)"); return pd.Series(1.0, index=d.index), None
    sse = {v: {y: float((((f.proj * v) - f.act)[f.year == y] ** 2).sum()) for y in years} for v in GRID}
    mult = pd.Series(1.0, index=d.index); picks = []; wins = 0; tot0 = tot1 = 0.0
    for y in years:
        best = min(GRID, key=lambda v: sum(sse[v][yy] for yy in years if yy != y))
        picks.append(best); mult[flag & (d.year == y)] = best
        tot0 += sse[1.0][y]; tot1 += sse[best][y]; wins += sse[best][y] < sse[1.0][y]
    pooled = min(GRID, key=lambda v: sum(sse[v].values()))
    print(f"  {label:34s} flagged n={len(f):5d}  pooled best x{pooled:.2f}  held-out picks {' '.join(f'{p:.2f}' for p in picks)}  "
          f"MSE on flagged rows {100*(tot1/tot0-1):+.2f}%  seasons better {wins}/{len(years)}")
    return mult, pooled

def spear_weekly(d, col):
    v = []
    for _, g in d.groupby(["year", "wk", "pos"]):
        if len(g) >= 8:
            v.append(np.corrcoef(g[col].rank(), g.act.rank())[0, 1])
    return float(np.mean(v))

def grade(d, years, col, label, base="proj"):
    m0 = ((d[base] - d.act) ** 2).mean(); m1 = ((d[col] - d.act) ** 2).mean()
    a0 = (d[base] - d.act).abs().mean(); a1 = (d[col] - d.act).abs().mean()
    wm = sum(1 for y in years if ((d[col] - d.act)[d.year == y] ** 2).mean() < ((d[base] - d.act)[d.year == y] ** 2).mean())
    wa = sum(1 for y in years if (d[col] - d.act)[d.year == y].abs().mean() < (d[base] - d.act)[d.year == y].abs().mean())
    print(f"  {label:40s} MSE {100*(m1/m0-1):+.2f}% ({wm}/{len(years)})  MAE {100*(a1/a0-1):+.2f}% ({wa}/{len(years)})  "
          f"bias {(d[base]-d.act).mean():+.2f} -> {(d[col]-d.act).mean():+.2f}  weekly rank corr {spear_weekly(d, base):.4f} -> {spear_weekly(d, col):.4f}")

def part_de(df, years, d0, title):
    print(f"\n=== D. held-out multipliers ({title}) ===")
    d = d0[d0.known].copy()
    flags = {}
    for pos in ("RB", "WR", "TE"):
        flags[f"{pos} 2nd"] = (d.pos == pos) & (d["rank"] == 2)
        flags[f"{pos} 3rd+"] = (d.pos == pos) & (d["rank"] >= 3)
        flags[f"{pos} lead, not young"] = (d.pos == pos) & (d["rank"] == 1) & ~d.young
    for pos in POS4:
        flags[f"{pos} young"] = (d.pos == pos) & d.young
        flags[f"{pos} veteran"] = (d.pos == pos) & d.vet
    mults = {}
    for k, f in flags.items():
        mults[k], _ = loyo_mult(d, years, f, k)
    # control: the same treatment for a projection TIER (no role/age information)
    print("  -- control: multiplier by projection tier only --")
    tier = {}
    for lo, hi in ((5, 8), (8, 11), (11, 15), (15, 99)):
        tier[(lo, hi)], _ = loyo_mult(d, years, (d.proj >= lo) & (d.proj < hi), f"tier [{lo},{hi})")
    print(f"\n=== E. stacked, every multiplier chosen without the graded season ({title}) ===")
    d["p_tier"] = d.proj * np.prod([tier[k] for k in tier], axis=0)
    d["p_role"] = d.proj * np.prod([mults[k] for k in mults if "2nd" in k or "3rd" in k or "lead" in k], axis=0)
    d["p_age"] = d.proj * np.prod([mults[k] for k in mults if "young" in k or "veteran" in k], axis=0)
    d["p_both"] = d.proj * np.prod([mults[k] for k in mults], axis=0)
    grade(d, years, "p_tier", "control: projection tier only")
    grade(d, years, "p_role", "pecking order only")
    grade(d, years, "p_age", "age only")
    grade(d, years, "p_both", "pecking order + age")
    for pos in POS4:
        grade(d[d.pos == pos], years, "p_both", f"   {pos}: pecking order + age")
    e = d[d.wk <= 4]
    grade(e, years, "p_both", "   weeks 1-4 only: pecking order + age")
    return d

def main():
    years = list(YEARS)
    df = build()
    print(f"\nrows: {len(df)} player-weeks 2019-25, projection >= {MIN_PROJ} half-PPR, played; age/experience known on {df.known.mean():.0%}; "
          f"limited/exit weeks {(df.lim == True).mean():.1%} (snap data on {df.lim.notna().mean():.0%})")
    part_a(df, years, "all weeks", df)
    part_a(df, years, "WEEKS 1-3 only (the live window)", df[df.wk <= 3])
    part_b(df, years)
    part_c(df, years, df, "all weeks")
    part_c(df, years, df[df.healthy], "healthy weeks only")
    part_c(df, years, df[df.wk <= 3], "weeks 1-3 only")
    part_de(df, years, df, "all weeks")
    df.to_pickle(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "role_age_backtest.pkl"))

if __name__ == "__main__":
    main()
