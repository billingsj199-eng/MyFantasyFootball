#!/usr/bin/env python3
"""Pull team D/ST history (season stats + fantasy finishes + game logs) from nflverse.

Gives D/ST player cards a real profile: every franchise season since 1999 with
sacks, INTs, fumble recoveries, def/ST TDs, safeties, blocks, points allowed,
fantasy points, PPG and the season-end positional finish (DST1, DST2, ...) —
plus per-game logs for recent seasons.

Sources (public nflverse-data release CSVs, no auth):
  stats_team_week_{yr}.csv   team-game rows w/ opponent + all def columns (1999+)
  nfldata games.csv          final scores (points allowed) + home/away

Scoring (classic Yahoo/Sleeper default; raw stats kept so any scheme can be
recomputed downstream): sack 1, INT 2, fumble recovery 2, def/ST TD 6,
safety 2, blocked kick 2, points allowed 0=10 / 1-6=7 / 7-13=4 / 14-20=1 /
21-27=0 / 28-34=-1 / 35+=-4.

Outputs:
  data/dst_history.js  window.DST_HISTORY — { "JAX": [ {yr,tm,gp,sck,itc,fr,
                       td,sfty,blk,pa,fpts,ppg,fin}, ... ] } keyed by the
                       site's TEAM_ABBR_MAP codes (franchise moves folded in:
                       SD->LAC, OAK->LV, STL/LA->LAR); each row's tm keeps the
                       historical code.
  data/dst_weekly.js   window.DST_WEEKLY — { "JAX": { "2024": [ {wk,opp,sck,
                       itc,fr,td,sfty,blk,pa,fpts}, ... ] } }, seasons >=
                       FIRST_WEEKLY_YEAR only (file size).

Run from the project root: python scripts/pull_dst_history.py
"""
import csv
import io
import json
import os
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

OUT_HISTORY = "data/dst_history.js"
OUT_WEEKLY = "data/dst_weekly.js"
TEAM_WEEK_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
                 "stats_team/stats_team_week_{yr}.csv")
GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
FIRST_YEAR = 1999
FIRST_WEEKLY_YEAR = 2020  # game logs only for recent seasons (file size)

# nflverse code -> site TEAM_ABBR_MAP code (franchise moves fold into the
# current franchise so e.g. the Chargers card shows its San Diego seasons)
SITE_KEY = {"LA": "LAR", "SD": "LAC", "OAK": "LV", "STL": "LAR"}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8")


def num(row, col):
    v = row.get(col)
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def pa_pts(pa):
    if pa == 0:
        return 10
    if pa <= 6:
        return 7
    if pa <= 13:
        return 4
    if pa <= 20:
        return 1
    if pa <= 27:
        return 0
    if pa <= 34:
        return -1
    return -4


def main():
    print("fetching games.csv (scores)...")
    games = {}  # game_id -> row
    for g in csv.DictReader(io.StringIO(fetch(GAMES_URL))):
        games[g["game_id"]] = g

    history = {}  # site key -> {yr: season record}
    weekly = {}   # site key -> {yr: [game rows]}
    by_year = {}  # yr -> [season records] for finish ranks

    yr = FIRST_YEAR
    while True:
        try:
            text = fetch(TEAM_WEEK_URL.format(yr=yr))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                break
            raise
        cnt = 0
        for row in csv.DictReader(io.StringIO(text)):
            if row.get("season_type") != "REG":
                continue
            g = games.get(row.get("game_id"))
            if not g or g.get("home_score") in (None, "", "NA"):
                continue
            # stats_team_week uses modern franchise codes (LAC/LV/LA) even for
            # historical seasons while games.csv keeps the era codes (SD/OAK/
            # STL) — canonicalize both sides before matching home/away.
            tm = row["team"]
            key = SITE_KEY.get(tm, tm)
            g_away = SITE_KEY.get(g["away_team"], g["away_team"])
            g_home = SITE_KEY.get(g["home_team"], g["home_team"])
            if not tm or key not in (g_home, g_away):
                continue
            away = key == g_away
            pa = int(float(g["home_score" if away else "away_score"]))
            sck = num(row, "def_sacks")
            itc = int(num(row, "def_interceptions"))
            fr = int(num(row, "fumble_recovery_opp"))
            td = int(num(row, "def_tds") + num(row, "special_teams_tds"))
            sfty = int(num(row, "def_safeties"))
            blk = int(num(row, "def_punt_blocks") + num(row, "def_pat_blocks")
                      + num(row, "def_fg_blocks"))
            fpts = round(sck + 2 * itc + 2 * fr + 6 * td + 2 * sfty + 2 * blk
                         + pa_pts(pa), 1)
            era_tm = g["away_team" if away else "home_team"]  # SD not LAC in 2005

            s = history.setdefault(key, {}).setdefault(yr, {
                "yr": yr, "tm": era_tm, "gp": 0, "sck": 0.0, "itc": 0, "fr": 0,
                "td": 0, "sfty": 0, "blk": 0, "pa": 0, "fpts": 0.0})
            s["gp"] += 1
            s["sck"] += sck
            s["itc"] += itc
            s["fr"] += fr
            s["td"] += td
            s["sfty"] += sfty
            s["blk"] += blk
            s["pa"] += pa
            s["fpts"] = round(s["fpts"] + fpts, 1)

            if yr >= FIRST_WEEKLY_YEAR:
                opp = row.get("opponent_team") or (g["home_team"] if away else g["away_team"])
                weekly.setdefault(key, {}).setdefault(yr, []).append({
                    "wk": int(float(row["week"])), "opp": ("@" if away else "") + opp,
                    "sck": round(sck, 1), "itc": itc, "fr": fr, "td": td,
                    "sfty": sfty, "blk": blk, "pa": pa, "fpts": fpts})
            cnt += 1
        print(f"  {yr}: {cnt} team-game rows")
        yr += 1

    # season-end positional finishes + rounding
    for key, seasons in history.items():
        for rec in seasons.values():
            rec["sck"] = round(rec["sck"], 1)
            rec["ppg"] = round(rec["fpts"] / rec["gp"], 1) if rec["gp"] else 0
            by_year.setdefault(rec["yr"], []).append(rec)
    for yr_, rows in by_year.items():
        rows.sort(key=lambda r: -r["fpts"])
        for fin, rec in enumerate(rows, 1):
            rec["fin"] = fin

    hist_out = {k: [seasons[y] for y in sorted(seasons)]
                for k, seasons in sorted(history.items())}
    wk_out = {k: {str(y): sorted(rows, key=lambda r: r["wk"])
                  for y, rows in sorted(seasons.items())}
              for k, seasons in sorted(weekly.items())}

    with open(OUT_HISTORY, "w", encoding="utf-8") as f:
        f.write("// D/ST season history: sacks/INT/FR/TD/safety/blocks/points-allowed,\n")
        f.write("// fantasy pts (sack 1, INT/FR/safety/block 2, TD 6 + PA tiers) and finish.\n")
        f.write("// Source: nflverse-data. Regenerate: python scripts/pull_dst_history.py\n")
        f.write("window.DST_HISTORY = " + json.dumps(hist_out, separators=(",", ":")) + ";\n")
    with open(OUT_WEEKLY, "w", encoding="utf-8") as f:
        f.write("// D/ST game logs (seasons %d+), same scoring as dst_history.js.\n" % FIRST_WEEKLY_YEAR)
        f.write("// Source: nflverse-data. Regenerate: python scripts/pull_dst_history.py\n")
        f.write("window.DST_WEEKLY = " + json.dumps(wk_out, separators=(",", ":")) + ";\n")

    yrs = sorted(by_year)
    n_seasons = sum(len(s) for s in history.values())
    n_games = sum(len(r) for s in weekly.values() for r in s.values())
    print(f"Wrote {len(hist_out)} teams, {n_seasons} seasons ({yrs[0]}-{yrs[-1]}) -> {OUT_HISTORY}")
    print(f"Wrote {n_games} game logs ({FIRST_WEEKLY_YEAR}+) -> {OUT_WEEKLY}")


if __name__ == "__main__":
    main()
