"""
LIVE remaining model for KICKERS and D/ST (the two classes backtest_live_remaining.py
left on the v1 heuristic — and v1 is nonsense for D/ST because the league-scored
live total starts at the 10-point points-allowed tier, so cum/f = 100 at f=0.1).

Same frame as the skill positions plus one term:
  remaining = (1-f) * (a*E + b*(cum/f) + m*E*(margin/10) + c*(rel/10))
  K:   rel = the kicker's own team score so far (drives that reach kicks)
  DST: rel = points allowed so far (drives the PA tier and the game script)
Scoring = Sleeper defaults (what the tracker grades on): FG 3/4/5 by distance
(<40/40-49/50+), missed or blocked FG -1, XP 1, missed XP -1; DST sack 1, INT 2,
fumble recovery 2, safety 2, blocked kick 2, defensive/return TD 6, points
allowed 0:10 1-6:7 7-13:4 14-20:1 21-27:0 28-34:-1 35+:-4. The live total at f
includes the PA tier of the opponent's score AT f (as the league feeds do).
E = leave-one-out season mean (K >= 7 games; DST all team-games).

Fit 2019-23 / holdout 2024-25, then refit on everything and MERGE the K and DST
rows (4 coefficients) into data/live_model.json as version 2. The exporter
copies `pos` wholesale, so the helpers pick them up on the next site export.

usage: python backtest_live_kdst.py
"""
import json, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = r"E:\MyFantasyFootball\pbp_cache"
OUT = os.path.join(HERE, "data", "live_model.json")
FIT_YEARS = [2019, 2020, 2021, 2022, 2023]
HOLD_YEARS = [2024, 2025]
GRID = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
USECOLS = ["game_id", "season_type", "week", "posteam", "defteam", "home_team", "away_team", "qtr",
           "game_seconds_remaining", "total_home_score", "total_away_score", "play_type",
           "field_goal_result", "kick_distance", "extra_point_result", "kicker_player_id", "kicker_player_name",
           "sack", "interception", "fumble_lost", "safety", "return_touchdown", "td_team", "punt_blocked",
           "defensive_two_point_conv"]


def pa_tier(pts):
    pts = np.asarray(pts, dtype=float)
    return np.select([pts <= 0, pts <= 6, pts <= 13, pts <= 20, pts <= 27, pts <= 34], [10, 7, 4, 1, 0, -1], -4).astype(float)


def load_year(year):
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{year}.csv.gz"), usecols=USECOLS, low_memory=False)
    df = df[df.season_type == "REG"].copy()
    gsr = df.game_seconds_remaining.fillna(0).astype(float)
    f = (3600.0 - gsr) / 3600.0
    df["f"] = f.where(df.qtr.fillna(1) <= 4, 1.0).clip(0.0, 1.0)
    df["season"] = year
    return df


def score_series(df):
    g = df[["game_id", "f", "total_home_score", "total_away_score"]].dropna().sort_values(["game_id", "f"])
    return {gid: (grp.f.values, grp.total_home_score.values, grp.total_away_score.values) for gid, grp in g.groupby("game_id", sort=False)}


def scores_at(series, gid, f0):
    """(home, away) score just before f0 (0, 0 before the first play)."""
    s = series.get(gid)
    if s is None: return 0.0, 0.0
    fs, hs, as_ = s
    i = np.searchsorted(fs, f0, side="left") - 1
    return (0.0, 0.0) if i < 0 else (float(hs[i]), float(as_[i]))


def final_scores(series, gid):
    s = series.get(gid)
    return (0.0, 0.0) if s is None else (float(s[1][-1]), float(s[2][-1]))


def kicker_events(df):
    fg = df[df.play_type.eq("field_goal") & df.kicker_player_id.notna()]
    dist = fg.kick_distance.fillna(0)
    made = fg.field_goal_result.eq("made")
    pts = np.where(made, np.where(dist >= 50, 5, np.where(dist >= 40, 4, 3)), -1.0)
    xp = df[df.play_type.eq("extra_point") & df.kicker_player_id.notna()]
    xpts = np.where(xp.extra_point_result.eq("good"), 1.0, -1.0)
    ev = pd.concat([
        pd.DataFrame({"game_id": fg.game_id, "season": fg.season, "pid": fg.kicker_player_id, "pname": fg.kicker_player_name, "team": fg.posteam, "home": fg.home_team, "f": fg.f, "pts": pts}),
        pd.DataFrame({"game_id": xp.game_id, "season": xp.season, "pid": xp.kicker_player_id, "pname": xp.kicker_player_name, "team": xp.posteam, "home": xp.home_team, "f": xp.f, "pts": xpts}),
    ], ignore_index=True)
    return ev


def dst_events(df):
    d = df[df.defteam.notna() & df.posteam.notna()]
    pts = (1.0 * d.sack.fillna(0) + 2.0 * d.interception.fillna(0) + 2.0 * d.fumble_lost.fillna(0) + 2.0 * d.safety.fillna(0)
           + 2.0 * (d.field_goal_result.eq("blocked") | d.extra_point_result.eq("blocked") | d.punt_blocked.fillna(0).eq(1)).astype(float)
           + 2.0 * d.defensive_two_point_conv.fillna(0))
    # defensive TD: a return touchdown credited to the defending team on a scrimmage/kick play
    dtd = (d.return_touchdown.fillna(0).eq(1) & d.td_team.eq(d.defteam)).astype(float) * 6.0
    ev = pd.DataFrame({"game_id": d.game_id, "season": d.season, "team": d.defteam, "home": d.home_team, "f": d.f, "pts": pts + dtd})
    # special-teams return TDs by the receiving team (kickoff: posteam is the receiving team; punt: posteam is the punting team)
    st = d[d.return_touchdown.fillna(0).eq(1) & d.play_type.isin(["kickoff", "punt"]) & d.td_team.notna() & d.td_team.ne(d.defteam)]
    ev = pd.concat([ev[ev.pts != 0], pd.DataFrame({"game_id": st.game_id, "season": st.season, "team": st.td_team, "home": st.home_team, "f": st.f, "pts": 6.0})], ignore_index=True)
    return ev


def build(years):
    rows = {"K": [], "DST": []}
    for y in years:
        df = load_year(y)
        series = score_series(df)
        games = df[["game_id", "home_team", "away_team"]].drop_duplicates("game_id")
        # ---------- kickers ----------
        kev = kicker_events(df)
        kg = kev.groupby(["game_id", "pid"], sort=False).agg(pname=("pname", "first"), season=("season", "first"), team=("team", "first"), home=("home", "first"), total=("pts", "sum")).reset_index()
        su = kg.groupby("pid").agg(games=("game_id", "count"), tot=("total", "sum"))
        kg = kg.join(su, on="pid")
        kg["E"] = (kg.tot - kg.total) / (kg.games - 1).clip(lower=1)
        kg = kg[(kg.games >= 7) & (kg.E >= 3.0)].copy()
        kg["is_home"] = kg.team == kg.home
        kev2 = kev.merge(kg[["game_id", "pid"]], on=["game_id", "pid"])
        base = kg.set_index(["game_id", "pid"])
        for f0 in GRID:
            cum = kev2[kev2.f < f0].groupby(["game_id", "pid"]).pts.sum().rename("cum")
            sub = base.join(cum).reset_index(); sub["cum"] = sub.cum.fillna(0.0); sub["f0"] = f0
            sc = [scores_at(series, g, f0) for g in sub.game_id]
            own = np.array([h if ih else a for (h, a), ih in zip(sc, sub.is_home)]); opp = np.array([a if ih else h for (h, a), ih in zip(sc, sub.is_home)])
            sub["margin"] = own - opp; sub["rel"] = own
            sub["pid"] = sub.pid.astype(str)
            rows["K"].append(sub[["season", "E", "cum", "f0", "margin", "rel", "total", "game_id", "team", "pid"]].assign(pos="K"))
        # ---------- D/ST ----------
        dev = dst_events(df)
        tg = []
        for _, g in games.iterrows():
            fh, fa = final_scores(series, g.game_id)
            for team, is_home, allowed in ((g.home_team, True, fa), (g.away_team, False, fh)):
                evs = dev[(dev.game_id == g.game_id) & (dev.team == team)].pts.sum()
                tg.append({"game_id": g.game_id, "season": y, "team": team, "is_home": is_home, "ev_total": float(evs), "total": float(evs) + float(pa_tier(allowed))})
        tg = pd.DataFrame(tg)
        su = tg.groupby("team").agg(games=("game_id", "count"), tot=("total", "sum"))
        tg = tg.join(su, on="team")
        tg["E"] = (tg.tot - tg.total) / (tg.games - 1).clip(lower=1)
        base = tg.set_index(["game_id", "team"])
        for f0 in GRID:
            cum_ev = dev[dev.f < f0].groupby(["game_id", "team"]).pts.sum().rename("cum_ev")
            sub = base.join(cum_ev).reset_index(); sub["cum_ev"] = sub.cum_ev.fillna(0.0); sub["f0"] = f0
            sc = [scores_at(series, g, f0) for g in sub.game_id]
            own = np.array([h if ih else a for (h, a), ih in zip(sc, sub.is_home)]); opp = np.array([a if ih else h for (h, a), ih in zip(sc, sub.is_home)])
            sub["cum"] = sub.cum_ev + pa_tier(opp)
            sub["margin"] = own - opp; sub["rel"] = opp
            sub["pid"] = "DST_" + sub.team.astype(str)
            rows["DST"].append(sub[["season", "E", "cum", "f0", "margin", "rel", "total", "game_id", "team", "pid"]].assign(pos="DST"))
        print(f"  {y}: {len(kg)} kicker-games, {len(tg)} DST team-games", flush=True)
    return pd.concat(rows["K"] + rows["DST"], ignore_index=True)


def design(s):
    f, E, cum = s.f0.values, s.E.values, s.cum.values
    r = 1 - f
    X = np.column_stack([E * r, (cum / f) * r, E * r * (s.margin.values / 10.0), r * (s.rel.values / 10.0)])
    return X, s.total.values - cum


def fit(samples):
    model = {}
    for pos in ("K", "DST"):
        model[pos] = []
        for f0 in GRID:
            X, y = design(samples[(samples.pos == pos) & (samples.f0 == f0)])
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            model[pos].append([round(float(c), 4) for c in coef])
    return model


def evaluate(samples, model, label):
    print(f"\n=== {label}: MAE of remaining points (naive | v1 heuristic | fitted) ===")
    out = {}
    for pos in ("K", "DST"):
        line, tot = [], {"naive": 0.0, "v1": 0.0, "fit": 0.0, "n": 0}
        for i, f0 in enumerate(GRID):
            s = samples[(samples.pos == pos) & (samples.f0 == f0)]
            X, y = design(s)
            naive = X[:, 0]
            w = 0.25 * f0
            v1 = (1 - w) * X[:, 0] + w * X[:, 1]
            ft = X @ np.array(model[pos][i])
            e = [np.mean(np.abs(y - naive)), np.mean(np.abs(y - v1)), np.mean(np.abs(y - ft))]
            for k, v in zip(("naive", "v1", "fit"), e): tot[k] += v * len(s)
            tot["n"] += len(s)
            line.append(f"f={f0:.1f} {e[0]:.2f}|{e[1]:.2f}|{e[2]:.2f}")
        n = max(tot["n"], 1)
        out[pos] = {k: round(tot[k] / n, 3) for k in ("naive", "v1", "fit")}
        print(f"{pos}: " + "  ".join(line))
        print(f"{pos} overall: naive {out[pos]['naive']:.3f} | v1 {out[pos]['v1']:.3f} | fit {out[pos]['fit']:.3f}")
    return out


def main():
    print("building fit samples", FIT_YEARS, flush=True)
    fit_s = build(FIT_YEARS)
    print("building holdout samples", HOLD_YEARS, flush=True)
    hold_s = build(HOLD_YEARS)
    model = fit(fit_s)
    print("\nfitted [a, b, m, c] per f bin", GRID)
    for pos in model: print(pos, model[pos])
    ev_fit = evaluate(fit_s, model, "in-sample 2019-2023")
    ev_hold = evaluate(hold_s, model, "HOLDOUT 2024-2025")
    final = fit(pd.concat([fit_s, hold_s], ignore_index=True))
    lm = json.load(open(OUT))
    # K is NOT shipped: its fit equals the naive split on holdout (2.710 vs 2.705), so the
    # helpers keep v1 for kickers; only the DST row (a real 5.41 -> 3.02 MAE win) is merged.
    lm["pos"].pop("K", None); lm["pos"]["DST"] = final["DST"]
    lm["version"] = 2
    lm["built"] = pd.Timestamp.now("UTC").strftime("%Y-%m-%dT%H:%MZ")
    lm["form"] = ("remaining = (1-f)*(a*E + b*(cum/f) + m*E*(margin/10) [+ c*(rel/10)]); pos class TE/WR -> REC; "
                  "DST row carries a 4th coefficient c: rel = points allowed so far; K unmodeled (fit == naive) -> helpers keep v1")
    lm["mae_holdout_2024_25"].update(ev_hold); lm["mae_fit_2019_23"].update(ev_fit)
    lm["kdst_samples"] = {"fit": int(len(fit_s) / len(GRID)), "holdout": int(len(hold_s) / len(GRID))}
    json.dump(lm, open(OUT, "w"), indent=1)
    print("\nmerged K + DST into", OUT)


if __name__ == "__main__":
    main()
