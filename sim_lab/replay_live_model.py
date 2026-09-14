"""
Two tests of the live remaining model (data/live_model.json) on a season the
model was NOT fitted on by the holdout run (2025):

1. CALIBRATION — bucket every player-game by predicted remaining points and
   compare to what was actually still scored. A good model's buckets sit
   on the diagonal (predicted 6 -> actual ~6). Reported per f and per
   position class, fitted vs the v1 heuristic.
2. REPLAY — one real game, play-by-play: the top players' live number
   (scored + remaining) at every 10% of the game, fitted vs v1 vs naive,
   against the final. Same arithmetic the helpers run.

usage: python replay_live_model.py [game_id]   (default: highest-scoring 2025 game)
       python replay_live_model.py --week 1     (every player-game of that week, graded)
       add --clay to use Clay's PRESEASON per-game projection x Vegas as the pregame number (what the helpers start from)
"""
import json, os, sys
import numpy as np
import pandas as pd
import backtest_live_remaining as B

HERE = os.path.dirname(os.path.abspath(__file__))
LM = json.load(open(os.path.join(HERE, "data", "live_model.json")))
GRID = LM["grid"]
YEAR = 2025


def coefs(pos, f):
    rows = LM["pos"][pos]
    g = GRID
    if f <= g[0]: return rows[0]
    if f >= g[-1]: return rows[-1]
    i = 0
    while i < len(g) - 2 and g[i + 1] < f: i += 1
    t = (f - g[i]) / (g[i + 1] - g[i])
    return [rows[i][k] + (rows[i + 1][k] - rows[i][k]) * t for k in range(3)]


def rem_fit(pos, f, E, cum, margin):
    a, b, m = coefs(pos, f)
    return max(0.0, (1 - f) * (a * E + b * (cum / max(f, 0.1)) + m * E * margin / 10.0))


def rem_v1(f, E, cum):
    pace = cum / f if f >= 0.15 else E
    w = 0.25 * f
    return max(0.0, (1 - f) * ((1 - w) * E + w * pace))


def calibration(samples):
    print("\n=== CALIBRATION 2025 (predicted remaining -> actual remaining; n) ===")
    edges = [0, 2, 4, 6, 8, 11, 15, 99]
    for pos in ["QB", "RB", "REC"]:
        s = samples[samples.pos == pos]
        pf = np.array([rem_fit(pos, f, E, c, m) for f, E, c, m in zip(s.f0, s.E, s.cum, s.margin)])
        pv = np.array([rem_v1(f, E, c) for f, E, c in zip(s.f0, s.E, s.cum)])
        act = (s.total - s.cum).values
        print(f"\n{pos}   bucket(pred)   fitted: pred->actual     v1: pred->actual")
        for lo, hi in zip(edges[:-1], edges[1:]):
            mf = (pf >= lo) & (pf < hi); mv = (pv >= lo) & (pv < hi)
            fa = f"{pf[mf].mean():5.2f} -> {act[mf].mean():5.2f} (n={mf.sum():5d})" if mf.sum() else "      -"
            va = f"{pv[mv].mean():5.2f} -> {act[mv].mean():5.2f} (n={mv.sum():5d})" if mv.sum() else "      -"
            print(f"     {lo:2d}-{hi:2d}          {fa}     {va}")
        # bias by game fraction (mean predicted - actual); 0 = unbiased
        print(f"   bias by f  (fitted | v1):  " + "  ".join(
            f"{f0:.1f}: {pf[s.f0.values == f0].mean() - act[s.f0.values == f0].mean():+.2f}|{pv[s.f0.values == f0].mean() - act[s.f0.values == f0].mean():+.2f}"
            for f0 in GRID))


def replay(samples, ev, series, pg, game_id):
    g = pg[pg.game_id == game_id].sort_values("total", ascending=False).head(8)
    print(f"\n=== REPLAY {game_id}: live number (scored + remaining) at each game fraction ===")
    print("cols: f=0.1 .. 0.9 -> fitted | v1 | naive   (final in last col)")
    for r in g.itertuples():
        e = ev[(ev.game_id == game_id) & (ev.pid == r.pid)]
        cells = []
        for f0 in GRID:
            cum = float(e[e.f < f0].pts.sum())
            margin = B.margin_at(series, game_id, f0, r.is_home)
            lf = cum + rem_fit(r.pos, f0, r.E, cum, margin)
            lv = cum + rem_v1(f0, r.E, cum)
            ln = cum + r.E * (1 - f0)
            cells.append(f"{lf:4.1f}|{lv:4.1f}|{ln:4.1f}")
        print(f"{r.pname:<14}{r.pos:<4}E={r.E:4.1f}  " + " ".join(cells) + f"   final {r.total:4.1f}")


def week_test(ev, series, pg, week):
    """Every player-game of one week: live number at each f vs the final,
    fitted | v1 | naive. Per-game lines + the week aggregate by game fraction."""
    pre = f"{YEAR}_{week:02d}_"
    wk = pg[pg.game_id.str.startswith(pre)]
    print(f"\n=== WEEK {week} {YEAR}: |live number - final| over every player-game (fitted | v1 | naive) ===")
    agg = {f0: [[], [], []] for f0 in GRID}
    wins = [0, 0, 0]
    per_game = []
    for gid, g in wk.groupby("game_id"):
        ge = [[], [], []]
        for r in g.itertuples():
            e = ev[(ev.game_id == gid) & (ev.pid == r.pid)]
            errs = [[], [], []]
            for f0 in GRID:
                cum = float(e[e.f < f0].pts.sum())
                margin = B.margin_at(series, gid, f0, r.is_home)
                lf = cum + rem_fit(r.pos, f0, r.E, cum, margin)
                lv = cum + rem_v1(f0, r.E, cum)
                ln = cum + r.E * (1 - f0)
                for k, v in enumerate((lf, lv, ln)):
                    err = abs(v - r.total)
                    agg[f0][k].append(err); errs[k].append(err); ge[k].append(err)
            m = [np.mean(x) for x in errs]
            wins[int(np.argmin(m))] += 1
        per_game.append((gid, len(g), [np.mean(x) for x in ge]))
    for gid, n, m in sorted(per_game):
        print(f"  {gid:<20} {n:2d} players   {m[0]:.2f} | {m[1]:.2f} | {m[2]:.2f}")
    print("  by game fraction:")
    for f0 in GRID:
        a = [np.mean(x) for x in agg[f0]]
        print(f"    f={f0:.1f}   {a[0]:.2f} | {a[1]:.2f} | {a[2]:.2f}   (n={len(agg[f0][0])})")
    tot = [np.mean(sum(agg[f0][k] for f0 in GRID)) if False else np.mean(np.concatenate([agg[f0][k] for f0 in GRID])) for k in range(3)]
    n = sum(wins)
    print(f"  WEEK MAE        {tot[0]:.3f} | {tot[1]:.3f} | {tot[2]:.3f}")
    print(f"  closest model per player-game: fitted {wins[0]}/{n} ({100*wins[0]/n:.0f}%)  v1 {wins[1]}  naive {wins[2]}")


def _nkey(name):
    """'Jalen Hurts' / 'J.Hurts' -> 'j.hurts' (suffixes + punctuation stripped)."""
    n = str(name).lower().replace("'", "").replace("-", " ")
    for suf in (" jr.", " jr", " sr.", " sr", " iii", " ii", " iv"):
        if n.endswith(suf): n = n[: -len(suf)]
    parts = n.replace(".", " ").split()
    if len(parts) < 2: return None
    return parts[0][0] + "." + parts[-1]


def clay_expectations(pg, year):
    """E = Clay's PRESEASON per-game projection (clay_history.json, ESPN full-PPR
    basis = the same STD+rec frame as the pbp credit here) x the engine's
    Vegas layer clamp(1 + 0.5*(implied - lgAvg)/lgAvg, 0.7, 1.35) from the
    closing lines in the pbp file. This is the number the helpers actually
    start from (Sim Lab weekly mean = Clay per-game x Vegas x matchup layers),
    instead of the leave-one-out season mean used by the fit."""
    clay = json.load(open(os.path.join(r"E:/MyFantasyFootball/MyFantasyFootball Files/data", "clay_history.json"), encoding="utf-8"))[str(year)]
    CLS = {"QB": "QB", "RB": "RB", "WR": "REC", "TE": "REC"}
    by_key = {}
    for name, c in clay.items():
        k = _nkey(name)
        cls = CLS.get(c.get("pos"))
        if not k or not cls or not c.get("gm"): continue
        by_key.setdefault((k, cls), []).append(c["pts"] / c["gm"])
    lines = pd.read_csv(os.path.join(B.CACHE, f"play_by_play_{year}.csv.gz"),
                        usecols=["game_id", "home_team", "away_team", "spread_line", "total_line", "total_home_score", "total_away_score"], low_memory=False)
    g = lines.groupby("game_id").agg(home=("home_team", "first"), away=("away_team", "first"), spread=("spread_line", "first"),
                                     total=("total_line", "first"), hs=("total_home_score", "max"), as_=("total_away_score", "max"))
    g["imp_home"] = (g.total + g.spread) / 2   # nflverse: spread_line > 0 = home favored
    g["imp_away"] = (g.total - g.spread) / 2
    corr = np.corrcoef(np.r_[g.imp_home, g.imp_away], np.r_[g.hs, g.as_])[0, 1]
    lg = float(np.nanmean(np.r_[g.imp_home, g.imp_away]))
    print(f"  Vegas sign check: implied-vs-score corr {corr:+.3f} (must be positive), lgAvg implied {lg:.1f}")
    E, matched, dropped = [], 0, 0
    for r in pg.itertuples():
        cands = by_key.get((_nkey(r.pname), r.pos))
        gi = g.loc[r.game_id] if r.game_id in g.index else None
        if not cands or len(cands) != 1 or gi is None or not np.isfinite(gi.total):
            E.append(np.nan); dropped += 1; continue
        imp = gi.imp_home if r.is_home else gi.imp_away
        mult = min(1.35, max(0.7, 1 + 0.5 * (imp - lg) / lg))
        E.append(cands[0] * mult); matched += 1
    out = pg.copy(); out["E"] = E
    out = out[np.isfinite(out.E) & (out.E >= 5.0)]
    print(f"  Clay pregame expectations: {matched} matched, {dropped} dropped (no unique Clay row / no line)")
    return out


def main():
    game_arg = sys.argv[1] if len(sys.argv) > 1 else None
    week_arg = None
    use_clay = "--clay" in sys.argv
    if game_arg and game_arg.startswith('--week'):
        week_arg = int(sys.argv[2]); game_arg = None
    df = B.load_year(YEAR)
    ev = B.events_from(df)
    series = B.score_series(df)
    samples = None
    if week_arg is None:
        samples = B.build_samples([YEAR])
        calibration(samples)
    # player-game table again (build_samples keeps it internal) for the replay
    pg = ev.groupby(["game_id", "pid"], sort=False).agg(
        pname=("pname", "first"), team=("posteam", "first"), home=("home_team", "first"), total=("pts", "sum"),
        patt=("patt", "sum"), ratt=("ratt", "sum"), tgt=("tgt", "sum")).reset_index()
    su = pg.groupby("pid").agg(patt=("patt", "sum"), ratt=("ratt", "sum"), tgt=("tgt", "sum"), games=("game_id", "count"), tot=("total", "sum"))
    su["pos"] = np.where(su.patt >= 0.5 * (su.patt + su.ratt + su.tgt), "QB", np.where(su.ratt >= 0.5 * (su.ratt + su.tgt), "RB", "REC"))
    pg = pg.join(su[["pos", "games", "tot"]], on="pid")
    pg["E"] = (pg.tot - pg.total) / (pg.games - 1).clip(lower=1)
    pg = pg[(pg.games >= 7) & (pg.E >= 5.0)]
    pg["is_home"] = pg.team == pg.home
    if use_clay:
        print("\n[E = Clay preseason per-game x Vegas closing line]")
        pg = clay_expectations(pg, YEAR)
    if week_arg is not None:
        week_test(ev, series, pg, week_arg)
        return
    if not game_arg:
        tot = df.groupby("game_id").agg(h=("total_home_score", "max"), a=("total_away_score", "max"))
        game_arg = (tot.h + tot.a).idxmax()
    replay(samples, ev, series, pg, game_arg)


if __name__ == "__main__":
    main()
