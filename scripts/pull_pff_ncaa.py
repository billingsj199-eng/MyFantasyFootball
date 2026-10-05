"""pull_pff_ncaa.py - PFF Premium COLLEGE (league=ncaa) grades + analytics.

Same mechanism as pull_pff_weekly.py (the official PFF Developer API with the
PFF Pro API key from pbp_cache/pff/api_key.txt), but for the NCAA league:

  weekly  : api.pff.com/v1/facet/<facet>?league=ncaa&season=<S>&week=<N>
            -> pbp_cache/pff/ncaa/pff_ncaa_<key>_<S>_w<N>.csv
  season  : api.pff.com/v1/facet/<facet>?league=ncaa&season=<S>
            -> pbp_cache/pff/ncaa/pff_ncaa_<key>_<S>.csv   (--seasons)

Facets: passing/summary, rushing/summary, receiving/summary, offense/summary
(every FBS+FCS player, ~7k rows/week for offense). Consumed by
scripts/refresh_devy_stats.py, which lifts per-game grades/analytics for the
devy prospects into data/college_stats_devy.js. Full files are kept so any
new prospect added later is already covered.

Weekly: weeks with no rows yet stop the loop; the newest --refetch existing
weeks are re-pulled for grade corrections. Exit 2 = no API key / key refused
(nothing written) - see pull_pff_weekly.py for where the key lives.

Usage:
    python scripts/pull_pff_ncaa.py                 # current season, new weeks
    python scripts/pull_pff_ncaa.py --seasons 2023,2024,2025   # season files
    python scripts/pull_pff_ncaa.py --weeks 1,2,3 --refetch 0
"""
import argparse
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pull_pff_weekly as P  # noqa: E402  (key, fetch, csv helpers)

NCAA_DIR = os.path.join(P.PFF_DIR, "ncaa")
API = P.API_BASE + "/v1/facet/{facet}?league=ncaa&season={season}"
FACETS = [
    ("passing", "passing/summary"),
    ("rushing", "rushing/summary"),
    ("receiving", "receiving/summary"),
    ("offense", "offense/summary"),
]
LEAD = ["season", "week", "player", "player_id", "position", "team_name", "franchise_id", "player_game_count"]


def path_for(key, season, week=None):
    return os.path.join(NCAA_DIR, "pff_ncaa_%s_%d%s.csv" % (key, season, ("_w%d" % week) if week else ""))


def fetch_rows(key, facet, season, week=None):
    url = API.format(facet=facet, season=season) + ("&week=%d" % week if week else "")
    status, body = P._api_fetch(key, url)
    if status != 200:
        return None, ("%s %s" % (status, P._err(body))).strip()
    rows = P._rows(body)
    if not isinstance(rows, list):
        return None, "unreadable"
    return [P._flatten(r) for r in rows if isinstance(r, dict)], status


def entitled(key, season):
    """-> (ok, status). ok = week 1 passing carries the premium grade fields."""
    rows, st = fetch_rows(key, "passing/summary", season, 1)
    return bool(rows) and any("grades_pass" in r for r in rows), st


def pull_week(key, season, week, force):
    written = []
    for fkey, facet in FACETS:
        path = path_for(fkey, season, week)
        if os.path.exists(path) and not force:
            continue
        rows, st = fetch_rows(key, facet, season, week)
        if rows is None:
            print("  %d w%d %s: %s - skipped" % (season, week, facet, st), flush=True)
            continue
        if not rows:
            return written, True  # week not played yet
        P._write_csv(path, season, week, rows, lead=LEAD)
        written.append((fkey, len(rows)))
        time.sleep(0.6)
    return written, False


def pull_season(key, season, force):
    written = []
    for fkey, facet in FACETS:
        path = path_for(fkey, season)
        if os.path.exists(path) and not force:
            continue
        rows, st = fetch_rows(key, facet, season)
        if not rows:
            print("  %d %s season: %s - skipped" % (season, facet, st), flush=True)
            continue
        P._write_csv(path, season, 0, rows, lead=LEAD)
        written.append((fkey, len(rows)))
        time.sleep(0.6)
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--weeks", default="auto", help="auto | comma list")
    ap.add_argument("--refetch", type=int, default=1, help="re-pull this many newest existing weeks")
    ap.add_argument("--seasons", default="", help="comma list of seasons to pull SEASON-level files for")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--login-wait", type=int, default=300, help="ignored (old job command lines still parse)")
    a = ap.parse_args()
    today = dt.date.today()
    season = a.season or (today.year if today.month >= 8 else today.year - 1)
    os.makedirs(NCAA_DIR, exist_ok=True)

    existing = sorted({int(f.rsplit("_w", 1)[1][:-4]) for f in os.listdir(NCAA_DIR)
                       if f.startswith("pff_ncaa_offense_%d_w" % season)})
    print("PFF NCAA %d: existing weeks %s" % (season, existing), flush=True)

    key = P._load_key()
    if not key:
        print("PFF API KEY MISSING - save a key to %s - nothing written (exit 2)" % P.KEY_FILE, flush=True)
        return 2
    ok, st = entitled(key, season)
    if not ok:
        print("PFF API REFUSED (%s) - nothing written (exit 2)" % st, flush=True)
        return 2

    # Season-level files: requested prior seasons once, the CURRENT season on every
    # run (PFF season grades are not averages of game grades - the season row's
    # film grade must come from the season table, refreshed as the season grows).
    seasons = [int(x) for x in a.seasons.split(",") if x.strip()]
    for s in seasons:
        w = pull_season(key, s, a.force)
        print("  season %d: %s" % (s, ", ".join("%s %d" % x for x in w) or "nothing new"), flush=True)
    if season not in seasons:
        w = pull_season(key, season, True)
        print("  season %d (current, refreshed): %s" % (season, ", ".join("%s %d" % x for x in w) or "nothing"), flush=True)

    if a.weeks == "auto":
        refetch = set(existing[-a.refetch:]) if a.refetch else set()
        weeks = list(range(1, 17))
    else:
        weeks = [int(x) for x in a.weeks.split(",")]
        refetch = set(weeks)
    done = []
    for wk in weeks:
        force = a.force or wk in refetch
        if os.path.exists(path_for("offense", season, wk)) and not force:
            continue
        written, unplayed = pull_week(key, season, wk, force)
        if written:
            done.append(wk)
            print("  week %d: %s" % (wk, ", ".join("%s %d" % x for x in written)), flush=True)
        if unplayed:
            print("  week %d: no rows yet - stop" % wk, flush=True)
            break
    print("done: weeks written %s" % done, flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print("FAILED:", e, flush=True)
        sys.exit(1)
