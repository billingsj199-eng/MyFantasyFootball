#!/usr/bin/env python3
"""Pull kicker game logs from nflverse for the player-card GAME LOGS section.

Companion to pull_kicker_history.py (season history): this emits per-game rows
for recent seasons so kicker cards get real weekly logs.

Sources (public nflverse-data release CSVs, no auth):
  <=2024  player_stats/player_stats_kicking.csv     (weekly rows, no opponent —
          joined against nfldata games.csv for opp + home/away)
  2025+   stats_player/stats_player_week_{yr}.csv   (weekly, has opponent_team;
          auto-discovers new seasons until 404)

Scoring matches kicker_history.js: FG 0-39 = 3, 40-49 = 4, 50+ = 5, XP = 1.

Output: data/kicker_weekly.js (window.KICKER_WEEKLY) —
  { "Player Name": { "2024": [ {wk,opp,fgm,fga,m40,m50,lng,xpm,xpa,fpts} ] } }
seasons >= FIRST_WEEKLY_YEAR only (file size).

Run from the project root: python scripts/pull_kicker_weekly.py
"""
import csv
import io
import json
import os
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

OUT_JS = "data/kicker_weekly.js"
LEGACY_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
              "player_stats/player_stats_kicking.csv")
WEEK_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
            "stats_player/stats_player_week_{yr}.csv")
GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
FIRST_WEEKLY_YEAR = 2020
FIRST_NEW_LAYOUT_YEAR = 2025  # seasons >= this come from stats_player files


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8")


def num(row, col):
    v = row.get(col)
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def game_row(row, opp):
    fgm = num(row, "fg_made")
    m40 = num(row, "fg_made_40_49")
    m50 = num(row, "fg_made_50_59") + num(row, "fg_made_60_")
    xpm = num(row, "pat_made")
    return {
        "wk": num(row, "week"), "opp": opp, "fgm": fgm,
        "fga": num(row, "fg_att"), "m40": m40, "m50": m50,
        "lng": num(row, "fg_long"), "xpm": xpm, "xpa": num(row, "pat_att"),
        "fpts": 3 * (fgm - m40 - m50) + 4 * m40 + 5 * m50 + xpm,
    }


def main():
    print("fetching games.csv (opponents)...")
    sched = {}  # (season, week, team) -> "OPP" / "@OPP"
    for g in csv.DictReader(io.StringIO(fetch(GAMES_URL))):
        try:
            key = (int(g["season"]), int(g["week"]))
        except ValueError:
            continue
        sched[key + (g["home_team"],)] = g["away_team"]
        sched[key + (g["away_team"],)] = "@" + g["home_team"]

    out = {}  # name -> {yr: [rows]}
    print("fetching legacy weekly kicking file...")
    n = 0
    for row in csv.DictReader(io.StringIO(fetch(LEGACY_URL))):
        if row.get("season_type") != "REG":
            continue
        yr = int(row["season"])
        if yr < FIRST_WEEKLY_YEAR or yr >= FIRST_NEW_LAYOUT_YEAR:
            continue
        if num(row, "fg_att") + num(row, "pat_att") == 0:
            continue
        tm = row.get("team") or row.get("recent_team") or ""
        opp = sched.get((yr, num(row, "week"), tm), "")
        out.setdefault(row["player_display_name"], {}).setdefault(yr, []).append(
            game_row(row, opp))
        n += 1
    print(f"  {n} weekly rows ({FIRST_WEEKLY_YEAR}-{FIRST_NEW_LAYOUT_YEAR - 1})")

    yr = FIRST_NEW_LAYOUT_YEAR
    while True:
        try:
            text = fetch(WEEK_URL.format(yr=yr))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                break
            raise
        cnt = 0
        for row in csv.DictReader(io.StringIO(text)):
            if row.get("position") != "K" or row.get("season_type") != "REG":
                continue
            if num(row, "fg_att") + num(row, "pat_att") == 0:
                continue
            tm = row.get("team") or ""
            opp = sched.get((yr, num(row, "week"), tm),
                            row.get("opponent_team") or "")
            out.setdefault(row["player_display_name"], {}).setdefault(yr, []).append(
                game_row(row, opp))
            cnt += 1
        print(f"  {yr}: {cnt} kicker game rows")
        yr += 1

    final = {name: {str(y): sorted(rows, key=lambda r: r["wk"])
                    for y, rows in sorted(seasons.items())}
             for name, seasons in sorted(out.items())}

    with open(OUT_JS, "w", encoding="utf-8") as f:
        f.write("// Kicker game logs (seasons %d+): FG 3/4/5 + XP 1 scoring,\n" % FIRST_WEEKLY_YEAR)
        f.write("// same as kicker_history.js. Regenerate: python scripts/pull_kicker_weekly.py\n")
        f.write("window.KICKER_WEEKLY = " + json.dumps(final, separators=(",", ":")) + ";\n")

    n_games = sum(len(r) for s in final.values() for r in s.values())
    print(f"Wrote {len(final)} kickers, {n_games} game rows -> {OUT_JS}")


if __name__ == "__main__":
    main()
