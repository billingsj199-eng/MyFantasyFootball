#!/usr/bin/env python3
"""Pull full kicker season history (stats + fantasy finishes) from nflverse.

Expands the site's kicker data beyond the two PPG columns in d.js and the
single-season distance splits in kicker_splits.js: every kicker season since
1999 with FG makes/attempts per distance bucket, XP, longs, game-winners,
fantasy points, PPG, and the season-end positional finish (K1, K2, ...).

Sources (public nflverse-data release CSVs, no auth):
  1999-2024  player_stats/player_stats_kicking.csv   (weekly; aggregated here)
  2025+      stats_player/stats_player_reg_{year}.csv (season-level, new layout)

Scoring for fpts/finish: FG 0-39 = 3, 40-49 = 4, 50+ = 5, XP = 1, no miss
penalties. Raw makes/attempts per bucket are kept so any other scheme can be
recomputed downstream.

Output: data/kicker_history.js (window.KICKER_HISTORY) —
  { "Player Name": [ {yr,tm,gp,fgm:[5],fga:[5],xpm,xpa,long,gw,fpts,ppg,fin}, ... ] }
bucket order matches KICKER_SPLITS: [1-19, 20-29, 30-39, 40-49, 50+].

Run from the project root: python scripts/pull_kicker_history.py
"""
import csv
import io
import json
import os
import re
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

OUT_JS = "data/kicker_history.js"
LEGACY_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
              "player_stats/player_stats_kicking.csv")
SEASON_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
              "stats_player/stats_player_reg_{yr}.csv")
FIRST_NEW_LAYOUT_YEAR = 2025  # seasons >= this come from stats_player files

MADE_COLS = ["fg_made_0_19", "fg_made_20_29", "fg_made_30_39", "fg_made_40_49"]
MISS_COLS = ["fg_missed_0_19", "fg_missed_20_29", "fg_missed_30_39", "fg_missed_40_49"]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read().decode("utf-8")


def num(row, col):
    v = row.get(col)
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def bucket_idx(dist):
    if dist <= 19:
        return 0
    if dist <= 29:
        return 1
    if dist <= 39:
        return 2
    if dist <= 49:
        return 3
    return 4


def add_row(acc, row):
    """Accumulate one weekly or season row into a per-player-season record."""
    a = acc
    a["gp"] += num(row, "games") or 1  # weekly rows count as 1 game each
    a["tm"] = row.get("team") or row.get("recent_team") or a["tm"]
    for i in range(4):
        a["fgm"][i] += num(row, MADE_COLS[i])
        a["fga"][i] += num(row, MADE_COLS[i]) + num(row, MISS_COLS[i])
    m50 = num(row, "fg_made_50_59") + num(row, "fg_made_60_")
    a["fgm"][4] += m50
    a["fga"][4] += m50 + num(row, "fg_missed_50_59") + num(row, "fg_missed_60_")
    # blocked kicks carry no bucket columns; fold their distances into attempts
    for d in re.findall(r"\d+", row.get("fg_blocked_list") or ""):
        a["fga"][bucket_idx(int(d))] += 1
    a["xpm"] += num(row, "pat_made")
    a["xpa"] += num(row, "pat_att")
    a["gw"] += num(row, "gwfg_made")
    a["long"] = max(a["long"], num(row, "fg_long"))


def blank(yr):
    return {"yr": yr, "tm": "", "gp": 0, "fgm": [0] * 5, "fga": [0] * 5,
            "xpm": 0, "xpa": 0, "gw": 0, "long": 0}


def main():
    seasons = {}  # (name, yr) -> record

    print("fetching legacy weekly file (1999-2024)...")
    legacy = csv.DictReader(io.StringIO(fetch(LEGACY_URL)))
    n = 0
    for row in legacy:
        if row.get("season_type") != "REG":
            continue
        yr = int(row["season"])
        if yr >= FIRST_NEW_LAYOUT_YEAR:
            continue
        key = (row["player_display_name"], yr)
        seasons.setdefault(key, blank(yr))
        add_row(seasons[key], row)
        n += 1
    print(f"  {n} weekly rows")

    yr = FIRST_NEW_LAYOUT_YEAR
    while True:
        try:
            text = fetch(SEASON_URL.format(yr=yr))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                break
            raise
        cnt = 0
        for row in csv.DictReader(io.StringIO(text)):
            if row.get("position") != "K":
                continue
            if num(row, "fg_att") + num(row, "pat_att") == 0:
                continue
            key = (row["player_display_name"], yr)
            seasons.setdefault(key, blank(yr))
            add_row(seasons[key], row)
            cnt += 1
        print(f"  {yr}: {cnt} kicker season rows")
        yr += 1

    # fantasy points + per-season finish
    for rec in seasons.values():
        rec["fpts"] = (3 * sum(rec["fgm"][:3]) + 4 * rec["fgm"][3]
                       + 5 * rec["fgm"][4] + rec["xpm"])
        rec["ppg"] = round(rec["fpts"] / rec["gp"], 1) if rec["gp"] else 0
    by_year = {}
    for (name, yr), rec in seasons.items():
        by_year.setdefault(yr, []).append((name, rec))
    for yr, rows in by_year.items():
        rows.sort(key=lambda r: -r[1]["fpts"])
        for fin, (_, rec) in enumerate(rows, 1):
            rec["fin"] = fin

    out = {}
    for (name, yr), rec in sorted(seasons.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if sum(rec["fga"]) + rec["xpa"] == 0:
            continue
        out.setdefault(name, []).append(rec)

    body = json.dumps(out, separators=(",", ":"))
    with open(OUT_JS, "w", encoding="utf-8") as f:
        f.write("// Kicker season history: per-season FG buckets [1-19,20-29,30-39,40-49,50+],\n")
        f.write("// XP, long, game-winners, fantasy pts (FG 3/4/5 + XP 1) and positional finish.\n")
        f.write("// Source: nflverse-data release CSVs. Regenerate: python scripts/pull_kicker_history.py\n")
        f.write("window.KICKER_HISTORY = " + body + ";\n")
    yrs = sorted(by_year)
    print(f"Wrote {len(out)} kickers, {len(seasons)} seasons ({yrs[0]}-{yrs[-1]}) -> {OUT_JS}")


if __name__ == "__main__":
    main()
