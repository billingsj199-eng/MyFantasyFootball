#!/usr/bin/env python3
"""
Coach play-calling tendencies from nflverse play-by-play (2019-2025).

Per team-season (regular season, offensive snaps):
  plays_gm  - offensive plays per game (volume)
  npr       - neutral-script pass rate (wp 20-80%, Q1-Q3)
  proe      - pass rate over expected (nflfastR pass_oe mean, pct points)
  epa_db    - EPA per dropback (pass efficiency)
  epa_ru    - EPA per designed rush (run efficiency)
  huddle    - no-huddle rate (pace proxy)
  te2       - 2+ TE personnel rate (12/22/13...) from participation data
  coach     - head coach (from pbp home_coach/away_coach; play-caller isn't
              in public data, so HC is the attribution unit)

Then answers: WHEN A COACH MOVES TEAMS, DO HIS TENDENCIES MOVE WITH HIM?
  * stability: year-over-year correlation, same coach same team
  * team-change baseline: same team, DIFFERENT coach (does the roster/org
    carry the tendency?)
  * coach-move transfer: same coach, different team (the causal signal)

Outputs pbp_cache/coach_research.json with team-season metrics, the per-season
new-HC change list, and team schedules (wk->opp) used by the sim backtest to
map historical players to teams via their opponent sequences.
"""
import gzip, json, os
import numpy as np
import pandas as pd

CACHE = r"E:\MyFantasyFootball\pbp_cache"
SEASONS = [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS"}
def tm(t): return ALIAS.get(t, t)

def te2_rates(year):
    """2+ TE personnel share per team, from participation data."""
    path = os.path.join(CACHE, f"pbp_participation_{year}.parquet")
    if not os.path.exists(path):
        return {}
    df = pd.read_parquet(path, columns=["possession_team", "offense_personnel"])
    df = df.dropna(subset=["possession_team", "offense_personnel"])
    df = df[df.possession_team != ""]
    te_n = df.offense_personnel.str.extract(r"(\d+)\s*TE")[0].astype(float)
    df = df.assign(te2=(te_n >= 2))
    g = df.groupby("possession_team").te2.mean()
    return {tm(k): round(float(v), 4) for k, v in g.items()}

def season_metrics(year):
    path = os.path.join(CACHE, f"play_by_play_{year}.csv.gz")
    cols = ["season_type", "week", "posteam", "home_coach", "away_coach",
            "home_team", "away_team", "defteam", "game_id",
            "play_type", "pass", "rush", "qb_dropback", "pass_oe",
            "wp", "qtr", "no_huddle", "epa", "qb_kneel", "qb_spike"]
    df = pd.read_csv(path, usecols=cols, low_memory=False)
    df = df[df.season_type == "REG"]
    df["posteam"] = df.posteam.map(lambda t: tm(t) if isinstance(t, str) else t)
    df["defteam"] = df.defteam.map(lambda t: tm(t) if isinstance(t, str) else t)

    # schedules: team -> {week: opp}
    sched = {}
    for _, g in df.dropna(subset=["posteam"]).groupby(["game_id"]):
        wk = int(g.week.iloc[0])
        h, a = tm(g.home_team.iloc[0]), tm(g.away_team.iloc[0])
        sched.setdefault(h, {})[wk] = a
        sched.setdefault(a, {})[wk] = h

    # head coach per team (mode across games)
    coach = {}
    per_game = df.dropna(subset=["posteam"]).groupby(["game_id"]).first()
    for _, r in per_game.iterrows():
        h, a = tm(r.home_team), tm(r.away_team)
        coach.setdefault(h, []).append(r.home_coach)
        coach.setdefault(a, []).append(r.away_coach)
    coach = {t: pd.Series(v).mode().iloc[0] for t, v in coach.items()}

    plays = df[(df["pass"] == 1) | (df["rush"] == 1)]
    plays = plays[(plays.play_type != "no_play") & (plays.qb_kneel != 1) & (plays.qb_spike != 1)]
    te2 = te2_rates(year)
    out = {}
    for t, g in plays.groupby("posteam"):
        n_games = g.game_id.nunique()
        neutral = g[(g.wp >= 0.2) & (g.wp <= 0.8) & (g.qtr <= 3)]
        db = g[g.qb_dropback == 1]
        ru = g[(g.rush == 1) & (g.qb_dropback != 1)]
        out[t] = {
            "coach": coach.get(t, "?"),
            "plays_gm": round(len(g) / n_games, 1),
            "npr": round(float(neutral["pass"].mean()), 4),
            "proe": round(float(g.pass_oe.mean()), 2),
            "epa_db": round(float(db.epa.mean()), 4),
            "epa_ru": round(float(ru.epa.mean()), 4),
            "huddle": round(float(g.no_huddle.mean()), 4),
            "te2": te2.get(t),
        }
    return out, sched

METRICS = ["plays_gm", "npr", "proe", "epa_db", "epa_ru", "huddle", "te2"]

def corr(pairs):
    a = np.array([p[0] for p in pairs], float)
    b = np.array([p[1] for p in pairs], float)
    ok = ~(np.isnan(a) | np.isnan(b))
    if ok.sum() < 5:
        return None, int(ok.sum())
    return float(np.corrcoef(a[ok], b[ok])[0, 1]), int(ok.sum())

def main():
    data, scheds = {}, {}
    for y in SEASONS:
        data[y], scheds[y] = season_metrics(y)
        print(f"{y}: {len(data[y])} teams")

    # year-over-year pairs bucketed by continuity type
    same_cc, new_coach, moves = {m: [] for m in METRICS}, {m: [] for m in METRICS}, {m: [] for m in METRICS}
    changes = {}   # year -> [teams with a new HC vs prior season]
    move_log = []
    coach_last = {}  # coach -> (year, team, metrics) most recent season coached
    for y in SEASONS:
        if y - 1 in data:
            changes[y] = sorted(t for t in data[y]
                                if t in data[y - 1] and data[y][t]["coach"] != data[y - 1][t]["coach"])
        for t, cur in data[y].items():
            prev = data.get(y - 1, {}).get(t)
            if prev:
                bucket = same_cc if cur["coach"] == prev["coach"] else new_coach
                for m in METRICS:
                    bucket[m].append((prev[m], cur[m]))
            # coach moved here from another team (any gap)
            last = coach_last.get(cur["coach"])
            if last and last[1] != t:
                for m in METRICS:
                    moves[m].append((last[2][m], cur[m]))
                move_log.append(f"{cur['coach']}: {last[1]} {last[0]} -> {t} {y}")
        for t, cur in data[y].items():
            coach_last[cur["coach"]] = (y, t, cur)

    print("\n=== Year-over-year correlation of team tendencies ===")
    print(f"{'metric':<9}{'same coach':>16}{'NEW coach (team keeps?)':>26}{'coach MOVES (follows him?)':>29}")
    for m in METRICS:
        r1, n1 = corr(same_cc[m]); r2, n2 = corr(new_coach[m]); r3, n3 = corr(moves[m])
        f = lambda r, n: (f"{r:+.2f} (n={n})" if r is not None else f"  —  (n={n})")
        print(f"{m:<9}{f(r1,n1):>16}{f(r2,n2):>26}{f(r3,n3):>29}")

    print(f"\n=== Coach moves observed ({len(move_log)}) ===")
    for s in move_log:
        print("  " + s)
    print("\n=== New-HC team-seasons ===")
    for y, ts in changes.items():
        print(f"  {y}: {', '.join(ts)}")

    # tendency spread magnitude: how much does a coach change actually move a team?
    print("\n=== Mean |year-over-year change| by continuity ===")
    for m in METRICS:
        d1 = np.nanmean([abs(b - a) for a, b in same_cc[m]]) if same_cc[m] else float("nan")
        d2 = np.nanmean([abs(b - a) for a, b in new_coach[m]]) if new_coach[m] else float("nan")
        print(f"  {m:<9} same coach {d1:7.3f}   new coach {d2:7.3f}   ratio {d2/d1 if d1 else float('nan'):.2f}x")

    out = {"metrics": data, "changes": {str(k): v for k, v in changes.items()},
           "schedules": {str(y): scheds[y] for y in SEASONS}}
    path = os.path.join(CACHE, "coach_research.json")
    json.dump(out, open(path, "w"), indent=0)
    print(f"\nwrote {path}")

if __name__ == "__main__":
    main()
