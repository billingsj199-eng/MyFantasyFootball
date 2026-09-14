"""
Live-projection remaining model — what should a player still score once
his game is under way?

The helpers (Sleeper 0.29.24 / ESPN 0.20.31 / Yahoo 0.9.23) show
  live = actual_so_far + remaining
with the v1 heuristic  remaining = (1-f) * ((1-w)*proj + w*pace),  w = 0.25*f,
pace = actual/f, f = fraction of the game played. This script fits that
shape on real games so the number is calibrated instead of guessed:

  remaining = a(f)*E*(1-f) + b(f)*(cum/f)*(1-f) + m(f)*E*(1-f)*(margin/10)

per position class (QB / RB / REC=WR+TE) and f bin, least squares with no
intercept, where E = the player's expectation for the game (leave-one-out
season mean of his PPR game totals — the best pregame-projection proxy the
history offers), cum = PPR points through fraction f, margin = his team's
score minus the opponent's at f (positive = leading). Fit on 2019-2023,
hold out 2024-2025; report MAE vs the naive rule (remaining = E*(1-f)) and
the shipped v1 heuristic.

Output: data/live_model.json -> export_site_proj.js folds it into
sim_proj_2026.json as `liveModel` so all three helpers pick it up.

Data: E:/MyFantasyFootball/pbp_cache/play_by_play_<yr>.csv.gz (nflverse).
PPR credit per play: passer 0.04/yd, 4/TD, -2 INT; rusher 0.1/yd, 6/TD;
receiver 1/rec, 0.1/yd, 6/TD; fumble lost -2; 2-pt +2. Positions are
inferred from usage (pass attempts -> QB; rush att vs targets -> RB/REC).
"""
import gzip, json, os, sys
import numpy as np
import pandas as pd

CACHE = r"E:\MyFantasyFootball\pbp_cache"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "live_model.json")
FIT_YEARS = [2019, 2020, 2021, 2022, 2023]
HOLD_YEARS = [2024, 2025]
GRID = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
USECOLS = ["game_id", "season_type", "week", "posteam", "defteam", "home_team", "away_team", "qtr",
           "game_seconds_remaining", "total_home_score", "total_away_score", "play_type",
           "passer_player_id", "passer_player_name", "rusher_player_id", "rusher_player_name",
           "receiver_player_id", "receiver_player_name", "passing_yards", "rushing_yards",
           "receiving_yards", "pass_touchdown", "rush_touchdown", "complete_pass", "interception",
           "fumble_lost", "fumbled_1_player_id", "fumbled_1_player_name", "two_point_conv_result",
           "pass_attempt", "rush_attempt"]


def load_year(year):
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{year}.csv.gz"), usecols=USECOLS, low_memory=False)
    df = df[df.season_type == "REG"].copy()
    gsr = df.game_seconds_remaining.fillna(0).astype(float)
    f = (3600.0 - gsr) / 3600.0
    f = f.where(df.qtr.fillna(1) <= 4, 1.0).clip(0.0, 1.0)
    df["f"] = f
    df["season"] = year
    return df


def events_from(df):
    """One row per (game, player, f, pts, kind) fantasy credit."""
    ev = []
    n0 = df[["game_id", "season", "week", "f", "posteam", "home_team", "away_team"]]
    two = (df.two_point_conv_result == "success")
    # passer
    m = df.passer_player_id.notna() & df.pass_attempt.eq(1)
    pts = (0.04 * df.passing_yards.fillna(0) + 4 * df.pass_touchdown.fillna(0) - 2 * df.interception.fillna(0) + 2 * two).where(m, 0)
    ev.append(pd.DataFrame({"pid": df.passer_player_id, "pname": df.passer_player_name, "pts": pts,
                            "patt": df.pass_attempt.fillna(0), "ratt": 0.0, "tgt": 0.0}).join(n0)[m.values])
    # rusher
    m = df.rusher_player_id.notna() & df.rush_attempt.eq(1)
    pts = (0.1 * df.rushing_yards.fillna(0) + 6 * df.rush_touchdown.fillna(0) + 2 * two).where(m, 0)
    ev.append(pd.DataFrame({"pid": df.rusher_player_id, "pname": df.rusher_player_name, "pts": pts,
                            "patt": 0.0, "ratt": df.rush_attempt.fillna(0), "tgt": 0.0}).join(n0)[m.values])
    # receiver (target)
    m = df.receiver_player_id.notna() & df.pass_attempt.eq(1)
    pts = (1.0 * df.complete_pass.fillna(0) + 0.1 * df.receiving_yards.fillna(0) + 6 * df.pass_touchdown.fillna(0) * df.complete_pass.fillna(0) + 2 * two).where(m, 0)
    ev.append(pd.DataFrame({"pid": df.receiver_player_id, "pname": df.receiver_player_name, "pts": pts,
                            "patt": 0.0, "ratt": 0.0, "tgt": 1.0}).join(n0)[m.values])
    # fumbles lost
    m = df.fumble_lost.eq(1) & df.fumbled_1_player_id.notna()
    ev.append(pd.DataFrame({"pid": df.fumbled_1_player_id, "pname": df.fumbled_1_player_name, "pts": -2.0,
                            "patt": 0.0, "ratt": 0.0, "tgt": 0.0}).join(n0)[m.values])
    out = pd.concat(ev, ignore_index=True)
    out["pts"] = out.pts.astype(float)
    return out


def score_series(df):
    """Per game: sorted (f, home_score, away_score) steps for margin lookups."""
    g = df[["game_id", "f", "total_home_score", "total_away_score"]].dropna().sort_values(["game_id", "f"])
    return {gid: (grp.f.values, grp.total_home_score.values, grp.total_away_score.values)
            for gid, grp in g.groupby("game_id", sort=False)}


def margin_at(series, gid, f0, is_home):
    s = series.get(gid)
    if s is None:
        return 0.0
    fs, hs, as_ = s
    i = np.searchsorted(fs, f0, side="left") - 1
    if i < 0:
        return 0.0
    d = hs[i] - as_[i]
    return float(d if is_home else -d)


def build_samples(years):
    rows = []
    for y in years:
        df = load_year(y)
        ev = events_from(df)
        series = score_series(df)
        # player-game totals + usage
        pg = ev.groupby(["game_id", "pid"], sort=False).agg(
            pname=("pname", "first"), season=("season", "first"), week=("week", "first"),
            team=("posteam", "first"), home=("home_team", "first"), total=("pts", "sum"),
            patt=("patt", "sum"), ratt=("ratt", "sum"), tgt=("tgt", "sum")).reset_index()
        # season usage -> position class
        su = pg.groupby("pid").agg(patt=("patt", "sum"), ratt=("ratt", "sum"), tgt=("tgt", "sum"), games=("game_id", "count"), tot=("total", "sum"))
        pos = np.where(su.patt >= 0.5 * (su.patt + su.ratt + su.tgt), "QB",
                       np.where(su.ratt >= 0.5 * (su.ratt + su.tgt), "RB", "REC"))
        su["pos"] = pos
        # leave-one-out season expectation
        pg = pg.join(su[["pos", "games", "tot"]], on="pid")
        pg["E"] = (pg.tot - pg.total) / (pg.games - 1).clip(lower=1)
        pg = pg[(pg.games >= 7) & (pg.E >= 5.0)]
        pg["is_home"] = pg.team == pg.home
        # cumulative points at each grid f
        ev2 = ev.merge(pg[["game_id", "pid"]], on=["game_id", "pid"])
        for f0 in GRID:
            cum = ev2[ev2.f < f0].groupby(["game_id", "pid"]).pts.sum()
            sub = pg.set_index(["game_id", "pid"]).join(cum.rename("cum")).reset_index()
            sub["cum"] = sub.cum.fillna(0.0)
            sub["f0"] = f0
            sub["margin"] = [margin_at(series, g, f0, h) for g, h in zip(sub.game_id, sub.is_home)]
            sub["pid"] = sub.pid.astype(str)
            rows.append(sub[["season", "pos", "E", "cum", "f0", "margin", "total", "game_id", "team", "pid"]])
        print(f"  {y}: {len(pg)} player-games", flush=True)
    return pd.concat(rows, ignore_index=True)


def design(s):
    f = s.f0.values
    E = s.E.values
    cum = s.cum.values
    rem_scale = (1 - f)
    X = np.column_stack([E * rem_scale, (cum / f) * rem_scale, E * rem_scale * (s.margin.values / 10.0)])
    y = s.total.values - cum
    return X, y


def fit(samples):
    model = {}
    for pos in ["QB", "RB", "REC"]:
        model[pos] = []
        for f0 in GRID:
            s = samples[(samples.pos == pos) & (samples.f0 == f0)]
            X, y = design(s)
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            model[pos].append([round(float(c), 4) for c in coef])
    return model


def evaluate(samples, model, label):
    print(f"\n=== {label}: MAE of remaining points (naive | v1 heuristic | fitted) ===")
    out = {}
    for pos in ["QB", "RB", "REC"]:
        line = []
        tot = {"naive": 0.0, "v1": 0.0, "fit": 0.0, "n": 0}
        for i, f0 in enumerate(GRID):
            s = samples[(samples.pos == pos) & (samples.f0 == f0)]
            if not len(s):
                continue
            X, y = design(s)
            naive = X[:, 0]
            w = 0.25 * f0
            v1 = (1 - w) * X[:, 0] + w * X[:, 1]
            a, b, m = model[pos][i]
            ft = a * X[:, 0] + b * X[:, 1] + m * X[:, 2]
            e = [np.mean(np.abs(y - naive)), np.mean(np.abs(y - v1)), np.mean(np.abs(y - ft))]
            for k, v in zip(("naive", "v1", "fit"), e):
                tot[k] += v * len(s)
            tot["n"] += len(s)
            line.append(f"f={f0:.1f} {e[0]:.2f}|{e[1]:.2f}|{e[2]:.2f}")
        n = max(tot["n"], 1)
        out[pos] = {k: round(tot[k] / n, 3) for k in ("naive", "v1", "fit")}
        print(f"{pos}: " + "  ".join(line))
        print(f"{pos} overall: naive {out[pos]['naive']:.3f} | v1 {out[pos]['v1']:.3f} | fit {out[pos]['fit']:.3f}")
    return out


def main():
    print("building fit samples", FIT_YEARS, flush=True)
    fit_s = build_samples(FIT_YEARS)
    print("building holdout samples", HOLD_YEARS, flush=True)
    hold_s = build_samples(HOLD_YEARS)
    model = fit(fit_s)
    print("\nfitted coefficients [a, b, m] per f bin", GRID)
    for pos in model:
        print(pos, model[pos])
    ev_fit = evaluate(fit_s, model, "in-sample 2019-2023")
    ev_hold = evaluate(hold_s, model, "HOLDOUT 2024-2025")
    # ship the model refit on everything (the holdout only guards the shape)
    all_s = pd.concat([fit_s, hold_s], ignore_index=True)
    final = fit(all_s)
    # keep the K / DST rows written by backtest_live_kdst.py (a separate fit) across reruns
    try:
        prev = json.load(open(OUT))
        for k in ("K", "DST"):
            if k in prev.get("pos", {}): final[k] = prev["pos"][k]
    except Exception:
        pass
    payload = {
        "version": 2,
        "built": pd.Timestamp.now("UTC").strftime("%Y-%m-%dT%H:%MZ"),
        "grid": GRID,
        "form": "remaining = a*E*(1-f) + b*(cum/f)*(1-f) + m*E*(1-f)*(margin/10); pos class TE/WR -> REC; K/DST unmodeled (helpers keep v1)",
        "pos": final,
        "mae_holdout_2024_25": ev_hold,
        "mae_fit_2019_23": ev_fit,
        "samples": {"fit": int(len(fit_s) / len(GRID)), "holdout": int(len(hold_s) / len(GRID))},
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(payload, fh, indent=1)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
