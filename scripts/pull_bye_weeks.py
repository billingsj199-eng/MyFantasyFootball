# pull_bye_weeks.py — generate data/bye_weeks.js from the ESPN scoreboard API.
#
# For each regular-season week (1-18) we ask ESPN who is PLAYING; the teams
# missing from a week's slate are on bye. Abbreviations are normalized to the
# site's TEAM_ABBR_MAP convention (ESPN says WSH, the site says WAS).
#
# Usage:  python scripts/pull_bye_weeks.py [--year 2026]
# Re-run whenever the NFL reschedules games (rare mid-season flexing doesn't
# move byes, so realistically this runs once per season after the May release).

import argparse
import datetime
import json
import sys
import time

import requests

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

# ESPN abbr -> site abbr (everything else matches TEAM_ABBR_MAP already)
ABBR_FIX = {"WSH": "WAS"}

ALL_TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA",
    "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB",
    "TEN", "WAS",
}


def teams_playing(year, week):
    r = requests.get(
        SCOREBOARD,
        params={"dates": str(year), "seasontype": "2", "week": str(week)},
        timeout=20,
    )
    r.raise_for_status()
    playing = set()
    for ev in r.json().get("events", []):
        for comp in ev.get("competitions", [{}])[0].get("competitors", []):
            ab = comp.get("team", {}).get("abbreviation", "")
            ab = ABBR_FIX.get(ab, ab)
            if ab:
                playing.add(ab)
    return playing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    args = ap.parse_args()

    byes = {}
    for wk in range(1, 19):
        playing = teams_playing(args.year, wk)
        if not playing:
            print(f"week {wk}: no events returned — schedule not published? aborting")
            sys.exit(1)
        for team in ALL_TEAMS - playing:
            if team in byes:
                print(f"week {wk}: {team} already had bye week {byes[team]} — double bye?!")
                sys.exit(1)
            byes[team] = wk
        time.sleep(0.3)

    missing = ALL_TEAMS - set(byes)
    if missing:
        print(f"teams with no bye found: {sorted(missing)} — aborting")
        sys.exit(1)

    stamp = datetime.date.today().isoformat()
    ordered = {t: byes[t] for t in sorted(byes)}
    body = json.dumps(ordered, separators=(",", ":"))
    out = (
        f"/* bye_weeks.js — {args.year} NFL bye weeks, generated {stamp} by "
        f"scripts/pull_bye_weeks.py (ESPN scoreboard API). */\n"
        f"window.BYE_WEEKS = {body};\n"
    )
    with open("data/bye_weeks.js", "w", encoding="utf-8") as f:
        f.write(out)

    by_week = {}
    for t, w in ordered.items():
        by_week.setdefault(w, []).append(t)
    for w in sorted(by_week):
        print(f"week {w:2d}: {' '.join(sorted(by_week[w]))}")
    print(f"\nwrote data/bye_weeks.js ({len(ordered)} teams)")


if __name__ == "__main__":
    main()
