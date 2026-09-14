"""
Calibrate the live-projection PLAYER-EXITED ramps, the BACKUP-QB share and the
teammate-QB rule on nflverse play-by-play 2019-25 (same data/credit rules as
backtest_live_remaining.py; the fitted live model from data/live_model.json).

1. EXIT RAMPS. For every player-game (E >= 5, >= 7 games) and every f0 on a
   fine grid: cum = points before f0, stale = f0 - f of the last play that
   CHANGED his total (0 if none yet), rem_actual = total - cum, rem_fit = the
   fitted model's remaining. ratio = sum(rem_actual) / sum(rem_fit) by
   position class x stale bucket = the empirical multiplier the ramp should
   reproduce. Then a grid search over ramp [start, full, floor] per class on
   2019-23 (min MAE of cum + rem_fit*mult vs total), scored on 2024-25 against
   no-ramp and the shipped hand-set ramps.
2. BACKUP SHARE. Team-games where the primary QB's last play comes before
   f=0.85 and another QB has plays after it: backup points from his entry vs
   starter_E * (1 - f_in) -> share. Split by |margin| at the starter's exit
   (< 17 = injury-like, >= 17 = blowout pull).
3. TEAMMATE RULE. Moments where a second QB reaches >= 2 pts while the
   starter's total has been stale >= 0.10: false positive if the starter
   scores again afterwards.

usage: python backtest_exit_rule.py [--years 2019-2025] [--quick]   (quick = 2023-25)
"""
import argparse, itertools, json, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from backtest_live_remaining import load_year, events_from, score_series, margin_at  # noqa: E402

MODEL = json.load(open(os.path.join(HERE, "data", "live_model.json")))
GRID_F = [round(x, 2) for x in np.arange(0.10, 0.96, 0.05)]
STALE_BINS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.80, 1.01]
SHIPPED = {"QB": (0.15, 0.30, 0.0), "RB": (0.25, 0.50, 0.15), "REC": (0.30, 0.60, 0.15)}


def coefs(cls, f):
    grid, rows = MODEL["grid"], MODEL["pos"][cls]
    if f <= grid[0]: return rows[0]
    if f >= grid[-1]: return rows[-1]
    i = 0
    while i < len(grid) - 2 and grid[i + 1] < f: i += 1
    t = (f - grid[i]) / (grid[i + 1] - grid[i])
    return [rows[i][k] + (rows[i + 1][k] - rows[i][k]) * t for k in range(3)]


def rem_fit(cls, f, E, cum, margin):
    a, b, m = coefs(cls, f)
    return np.maximum(0.0, (1 - f) * (a * E + b * (cum / max(f, 0.1)) + m * E * (margin / 10.0)))


def ramp_mult(stale, ramp):
    lo, hi, floor = ramp
    t = np.clip((stale - lo) / (hi - lo), 0, 1)
    return np.where(stale <= lo, 1.0, 1.0 - (1.0 - floor) * t)


def build(years):
    samples, qb_games = [], []
    for y in years:
        df = load_year(y)
        ev = events_from(df)
        series = score_series(df)
        pg = ev.groupby(["game_id", "pid"], sort=False).agg(
            pname=("pname", "first"), season=("season", "first"), week=("week", "first"),
            team=("posteam", "first"), home=("home_team", "first"), total=("pts", "sum"),
            patt=("patt", "sum"), ratt=("ratt", "sum"), tgt=("tgt", "sum"),
            f_last=("f", "max")).reset_index()
        su = pg.groupby("pid").agg(patt=("patt", "sum"), ratt=("ratt", "sum"), tgt=("tgt", "sum"), games=("game_id", "count"), tot=("total", "sum"))
        su["pos"] = np.where(su.patt >= 0.5 * (su.patt + su.ratt + su.tgt), "QB",
                             np.where(su.ratt >= 0.5 * (su.ratt + su.tgt), "RB", "REC"))
        pg = pg.join(su[["pos", "games", "tot", "patt"]].rename(columns={"patt": "s_patt"}), on="pid")
        pg["E"] = (pg.tot - pg.total) / (pg.games - 1).clip(lower=1)
        pg["is_home"] = pg.team == pg.home
        # ---- QB team-games for the backup / teammate analyses (all QBs, E optional)
        qb = pg[pg.pos == "QB"].copy()
        qb_ev = ev.merge(qb[["game_id", "pid"]], on=["game_id", "pid"])
        qb_games.append((qb, qb_ev, series))
        # ---- exit-ramp samples (E-qualified)
        pq = pg[(pg.games >= 7) & (pg.E >= 5.0)].copy()
        ev2 = ev.merge(pq[["game_id", "pid"]], on=["game_id", "pid"])
        evc = ev2[ev2.pts != 0]  # plays that moved the total
        base = pq.set_index(["game_id", "pid"])
        for f0 in GRID_F:
            cum = ev2[ev2.f < f0].groupby(["game_id", "pid"]).pts.sum().rename("cum")
            fch = evc[evc.f < f0].groupby(["game_id", "pid"]).f.max().rename("f_change")
            sub = base.join(cum).join(fch).reset_index()
            sub["cum"] = sub.cum.fillna(0.0); sub["f_change"] = sub.f_change.fillna(0.0)
            sub["f0"] = f0
            sub["stale"] = f0 - sub.f_change
            sub["margin"] = [margin_at(series, g, f0, h) for g, h in zip(sub.game_id, sub.is_home)]
            samples.append(sub[["season", "pos", "E", "cum", "f0", "stale", "margin", "total", "f_last"]])
        print(f"  {y}: {len(pq)} qualified player-games, {len(qb)} QB games", flush=True)
    s = pd.concat(samples, ignore_index=True)
    s["rem_actual"] = s.total - s.cum
    s["rem_fit"] = 0.0
    for (cls, f0), idx in s.groupby(["pos", "f0"]).groups.items():  # coefs are per scalar f
        sub = s.loc[idx]
        s.loc[idx, "rem_fit"] = rem_fit(cls, float(f0), sub.E.values, sub.cum.values, sub.margin.values)
    return s, qb_games


def ratio_table(s, label):
    print(f"\n=== EXIT RAMP: empirical multiplier = sum(rem_actual)/sum(rem_fit) by stale bucket ({label}) ===")
    print("also: share of samples whose player never touches the ball again (exit-like)")
    s = s.copy()
    s["sb"] = pd.cut(s.stale, STALE_BINS, right=False)
    s["exit_like"] = s.f_last < s.f0
    out = {}
    for cls in ("QB", "RB", "REC"):
        print(f"\n  {cls}:  stale-bucket   n      mult   mean rem_act  mean rem_fit  exit-like%   (cum>0 only: mult)")
        d = s[s.pos == cls]
        for b, grp in d.groupby("sb", observed=True):
            if len(grp) < 200: continue
            g2 = grp[grp.cum > 0]
            r = grp.rem_actual.sum() / max(grp.rem_fit.sum(), 1e-9)
            r2 = g2.rem_actual.sum() / max(g2.rem_fit.sum(), 1e-9) if len(g2) > 100 else float("nan")
            print(f"    {str(b):<14}{len(grp):>7}   {r:5.2f}   {grp.rem_actual.mean():7.2f}      {grp.rem_fit.mean():7.2f}      {100*grp.exit_like.mean():5.1f}      {r2:5.2f}")
            out.setdefault(cls, []).append({"bucket": str(b), "n": int(len(grp)), "mult": round(r, 3), "mult_cum_pos": (None if np.isnan(r2) else round(r2, 3)), "exit_like": round(float(grp.exit_like.mean()), 3)})
    return out


def apply_ramps(s, ramps, gate):
    """mult per sample; gate = ramp only applies once the player has scored (cum != 0)."""
    mult = np.ones(len(s))
    if ramps is None: return mult
    for cls, r in ramps.items():
        m = (s.pos == cls).values
        mm = ramp_mult(s.stale.values[m], r)
        if gate: mm = np.where(s.cum.values[m] != 0, mm, 1.0)
        mult[m] = mm
    return mult


def score(s, ramps, gate=False):
    """(RMSE, MAE, bias = sum(live)/sum(final)) of cum + rem_fit x mult vs final."""
    live = s.cum.values + s.rem_fit.values * apply_ramps(s, ramps, gate)
    err = live - s.total.values
    return float(np.sqrt(np.mean(err ** 2))), float(np.abs(err).mean()), float(live.sum() / max(s.total.sum(), 1e-9))


def fit_ramps(train, test):
    """Grid search per class, objective = RMSE (mean-calibrated; MAE would chase the median),
    with and without the scored-gate; report holdout RMSE / MAE / bias for none, shipped, fitted."""
    print("\n=== RAMP GRID SEARCH (objective RMSE on train; holdout = 2024-25)  RMSE | MAE | bias(sum live/sum final) ===")
    starts = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
    fulls = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
    floors = [0.0, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    best = {}
    for cls in ("QB", "RB", "REC"):
        tr, te = train[train.pos == cls], test[test.pos == cls]
        res = {}
        for gate in (False, True):
            bb, brm = None, score(tr, None)[0]
            for lo, hi, fl in itertools.product(starts, fulls, floors):
                if hi <= lo: continue
                rm = score(tr, {cls: (lo, hi, fl)}, gate)[0]
                if rm < brm - 1e-6: bb, brm = (lo, hi, fl), rm
            res[gate] = (bb, brm)
        fmt = lambda t: f"{t[0]:.3f} | {t[1]:.3f} | {t[2]:.3f}"
        print(f"  {cls}: train no-ramp RMSE {score(tr, None)[0]:.3f}; fitted ungated {res[False][0]} -> {res[False][1]:.3f}; fitted gated {res[True][0]} -> {res[True][1]:.3f}")
        print(f"       holdout  none {fmt(score(te, None))}   shipped {fmt(score(te, {cls: SHIPPED[cls]}))}   shipped+gate {fmt(score(te, {cls: SHIPPED[cls]}, True))}")
        for gate in (False, True):
            if res[gate][0]: print(f"       holdout  fitted{' gated' if gate else '      '} {res[gate][0]}: {fmt(score(te, {cls: res[gate][0]}, gate))}")
        best[cls] = {"ungated": res[False][0], "gated": res[True][0]}
    return best


def backup_and_teammate(qb_games):
    print("\n=== BACKUP QB SHARE + TEAMMATE RULE ===")
    shares, rows_fp = [], []
    for qb, qb_ev, series in qb_games:
        for (gid, team), grp in qb.groupby(["game_id", "team"]):
            if len(grp) < 2: continue
            grp = grp.sort_values("s_patt", ascending=False)
            st = grp.iloc[0]
            if st.games < 7 or st.E < 5: continue
            evs = qb_ev[(qb_ev.game_id == gid) & (qb_ev.posteam == team)]
            st_ev = evs[evs.pid == st.pid]
            f_exit = st_ev.f.max()
            for _, bk in grp.iloc[1:].iterrows():
                bk_ev = evs[evs.pid == bk.pid].sort_values("f")
                # teammate rule: first moment the backup's cum reaches 2 while starter stale >= 0.10
                cum = bk_ev.pts.cumsum().values
                for thr in (2.0, 3.0, 4.0, 6.0):
                    hit = np.where(cum >= thr)[0]
                    if not len(hit): continue
                    f_b = float(bk_ev.f.values[hit[0]])
                    st_change = st_ev[(st_ev.pts != 0) & (st_ev.f <= f_b)].f.max()
                    st_change = 0.0 if pd.isna(st_change) else float(st_change)
                    later = st_ev[(st_ev.f > f_b) & (st_ev.pts != 0)]
                    rows_fp.append({"thr": thr, "stale": f_b - st_change, "fp": len(later) > 0, "starter_pts_after": float(later.pts.sum()),
                                    "starter_rem_fit": float(rem_fit("QB", f_b, st.E, float(st_ev[st_ev.f <= f_b].pts.sum()), 0.0)), "f_b": f_b})
                # backup share: starter done before 0.85, backup plays after
                if f_exit < 0.85:
                    after = bk_ev[bk_ev.f > f_exit]
                    if len(after) == 0: continue
                    f_in = float(after.f.min())
                    pts_after = float(after.pts.sum())
                    mg = margin_at(series, gid, f_exit, st.is_home)
                    shares.append({"season": int(st.season), "starter": st.pname, "backup": bk.pname, "f_in": f_in,
                                   "E": float(st.E), "pts_after": pts_after, "expect": float(st.E) * (1 - f_in), "margin": mg})
    sh = pd.DataFrame(shares)
    if len(sh):
        for lbl, d in (("all starter exits < 0.85", sh), ("|margin| < 17 at exit (injury-like)", sh[sh.margin.abs() < 17]), ("|margin| >= 17 (blowout pull)", sh[sh.margin.abs() >= 17])):
            if len(d) == 0: continue
            print(f"  {lbl}: n={len(d)}  share = sum(backup pts after)/sum(E x (1-f_in)) = {d.pts_after.sum()/max(d.expect.sum(),1e-9):.2f}   median per-case {np.median(d.pts_after/np.maximum(d.expect,0.1)):.2f}   mean f_in {d.f_in.mean():.2f}")
        early = sh[(sh.margin.abs() < 17) & (sh.f_in < 0.5)]
        if len(early): print(f"  injury-like AND entered before halftime: n={len(early)} share {early.pts_after.sum()/early.expect.sum():.2f}")
    fp = pd.DataFrame(rows_fp)
    if len(fp):
        print("  teammate rule threshold scan (backup pts >= thr while starter stale >= s): triggers, FP% (starter scored again),")
        print("  mean starter pts after a false trigger (what zeroing him costs) vs mean fitted remaining at a true trigger (what it saves)")
        for thr in (2.0, 3.0, 4.0, 6.0):
            for st_min in (0.10, 0.15, 0.20):
                d = fp[(fp.thr == thr) & (fp.stale >= st_min)]
                if not len(d): continue
                tp = d[~d.fp]
                print(f"    thr {thr:.0f} stale>={st_min:.2f}: n={len(d):>3}  FP {100*d.fp.mean():4.1f}%  cost/FP {d[d.fp].starter_pts_after.mean() if d.fp.any() else 0:.2f}  saves/TP {tp.starter_rem_fit.mean() if len(tp) else 0:.2f}  net/trigger {(tp.starter_rem_fit.sum() - d[d.fp].starter_pts_after.sum())/len(d):.2f}")
    return sh, fp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2019-2025")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    y0, y1 = (2023, 2025) if a.quick else tuple(int(x) for x in a.years.split("-"))
    years = list(range(y0, y1 + 1))
    print("loading", years, flush=True)
    s, qb_games = build(years)
    train = s[s.season <= 2023]; test = s[s.season >= 2024]
    tab = ratio_table(s, f"{y0}-{y1}")
    best = fit_ramps(train if len(train) else s, test if len(test) else s)
    sh, fp = backup_and_teammate(qb_games)
    out = {"years": years, "ratio": tab, "fitted_ramps": best, "shipped": SHIPPED,
           "backup": ({"n": int(len(sh)), "share_all": round(float(sh.pts_after.sum() / sh.expect.sum()), 3),
                       "share_injury_like": round(float(sh[sh.margin.abs() < 17].pts_after.sum() / max(sh[sh.margin.abs() < 17].expect.sum(), 1e-9)), 3)} if len(sh) else None),
           "teammate": ({"triggers_thr2_stale010": int(((fp.thr == 2.0) & (fp.stale >= 0.10)).sum()), "false_pos": int(fp[(fp.thr == 2.0) & (fp.stale >= 0.10)].fp.sum())} if len(fp) else None)}
    path = os.path.join(HERE, "data", "exit_rule_backtest.json")
    json.dump(out, open(path, "w"), indent=1)
    print("\nwrote", path)


if __name__ == "__main__":
    main()
