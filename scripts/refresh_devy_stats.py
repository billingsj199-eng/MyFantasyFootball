"""refresh_devy_stats.py - weekly in-season college stats for devy / future-class prospects.

Pulls the CURRENT college season's game-by-game stats off CFBD for every
prospect the site treats as a devy (COMBINE_DATA entries flagged devy:true,
plus any entry whose draft class year is later than the current season) and
writes data/college_stats_devy.js:

    window._DEVY_SEASON_ROWS  - one season row per player (college_stats.js
                                 format: yr/tm/conf/gp/pa/pc/py/...), spliced
                                 into COLLEGE_STATS by window._csPatchDevy()
                                 after the college_stats patch chain loads
                                 (index.html _ensureCollegeStatsData).
    COLLEGE_WEEKLY[name][yr]  - the game log for the player card.

The JM prospect model scores off COLLEGE_STATS in the browser, so a fresh
season row is all it takes for devy grades to move week to week: production,
breakout age and the improvement curve are per-game rates with a 3-game
floor, so a partial season is safe to feed in.

Player -> CFBD id resolution (cached in scripts/devy_refresh_cache.json):
  1. cached id for this season
  2. devy_weekly.json seed id (verified against the school roster)
  3. the school's roster for this season, matched by name
  4. /player/search for this season (exact name, school preferred)
Transfers: the roster check uses the COMBINE_DATA school; if the player is
not on it, /player/search finds the new team.

Box scores are cached per (team, week); weeks that ended more than 8 days
ago are never re-fetched, recent weeks are (stat corrections).

Bumps the college_stats_devy.js ?v= in index.html only when the data file's
bytes actually change (CRLF-normalized), reading the current tag from disk
at bump time (repo rule: tags collide across sessions).

Usage:
    python scripts/refresh_devy_stats.py            # write + bump
    python scripts/refresh_devy_stats.py --dry-run  # pull, report, write nothing
    python scripts/refresh_devy_stats.py --no-bump  # write data, leave index.html
    python scripts/refresh_devy_stats.py --season 2026
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
from cfbd_config import CFBD_API_KEY  # noqa: E402  (local only, gitignored)

BASE = "https://apinext.collegefootballdata.com"
HEADERS = {"Authorization": "Bearer " + CFBD_API_KEY, "Accept": "application/json"}
COMBINE_JS = "data/combine_data.js"
SEED_JSON = "devy_weekly.json"
CACHE_JSON = "scripts/devy_refresh_cache.json"
OUT_JS = "data/college_stats_devy.js"
INDEX_HTML = "index.html"
MAX_WEEK = 15          # regular season incl. conference championships
RECENT_DAYS = 8        # re-fetch weeks that ended within this many days
SLEEP = 0.25

# combine_data.js school spelling -> CFBD team name
SCHOOL_TO_CFBD = {
    "Ohio St.": "Ohio State", "Penn St.": "Penn State", "Michigan St.": "Michigan State",
    "Arizona St.": "Arizona State", "Kansas St.": "Kansas State", "Oklahoma St.": "Oklahoma State",
    "Florida St.": "Florida State", "Iowa St.": "Iowa State", "Oregon St.": "Oregon State",
    "Washington St.": "Washington State", "Mississippi St.": "Mississippi State",
    "Boise St.": "Boise State", "Fresno St.": "Fresno State", "San Diego St.": "San Diego State",
    "San Jose St.": "San José State", "Colorado St.": "Colorado State", "Utah St.": "Utah State",
    "Appalachian St.": "Appalachian State", "Georgia St.": "Georgia State",
    "North Dakota St.": "North Dakota State", "South Dakota St.": "South Dakota State",
    "NC State": "NC State", "Miami (FL)": "Miami", "Miami (OH)": "Miami (OH)",
    "Mississippi": "Ole Miss", "Texas-San Antonio": "UTSA", "Texas-El Paso": "UTEP",
    "Central Florida": "UCF", "Southern California": "USC", "Brigham Young": "BYU",
    "Louisiana St.": "LSU", "Southern Methodist": "SMU", "Pittsburgh": "Pittsburgh",
    "Connecticut": "Connecticut", "Massachusetts": "Massachusetts", "Hawaii": "Hawai'i",
    "Louisiana-Monroe": "UL Monroe", "Louisiana-Lafayette": "Louisiana",
    "Texas Christian": "TCU", "Nevada-Las Vegas": "UNLV", "Alabama-Birmingham": "UAB",
}

calls = 0


def log(*a):
    print(*a, flush=True)


def api_get(endpoint, params):
    global calls
    for attempt in range(3):
        try:
            r = requests.get(BASE + endpoint, headers=HEADERS, params=params, timeout=25)
            calls += 1
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    return None
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 + 2 * attempt)
                continue
            log("  HTTP %d %s %s" % (r.status_code, endpoint, params))
            return None
        except requests.RequestException as e:
            log("  ERROR %s %s: %s" % (endpoint, params, e))
            time.sleep(2)
    return None


def cfbd_school(s):
    s = (s or "").strip()
    return SCHOOL_TO_CFBD.get(s, s)


def norm_name(n):
    n = (n or "").lower().strip()
    n = re.sub(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", "", n)
    n = n.replace(".", "").replace("'", "").replace("’", "").replace("-", " ")
    return re.sub(r"\s+", " ", n).strip()


def roster_name(r):
    return ((r.get("firstName") or "") + " " + (r.get("lastName") or "")).strip() or (r.get("name") or "")


def current_season(today):
    # College season = calendar year from August on; Jan-Jul still belongs to the prior fall.
    return today.year if today.month >= 8 else today.year - 1


def load_combine():
    with open(COMBINE_JS, encoding="utf-8") as f:
        txt = f.read()
    body = txt.split("=", 1)[1].strip().rstrip(";")
    return json.loads(body)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def digest(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()
    except OSError:
        return None


def bump_tag(html, fname):
    """Set data/<fname> ?v= to today (suffix if today's tag is already taken)."""
    today = datetime.date.today().isoformat()
    pat = re.compile(r"(%s\?v=)([\w.-]+)" % re.escape(fname))
    m = pat.search(html)
    if not m:
        log("  WARN: no ?v= tag found for", fname)
        return html
    cur = m.group(2)
    new = today if not cur.startswith(today) else today + "dv2"
    if cur == new:
        return html
    log("  bump %s ?v= %s -> %s" % (fname, cur, new))
    return pat.sub(lambda mm: mm.group(1) + new, html)


# ---------------------------------------------------------------- resolution
def resolve_player(name, entry, season, seed, cache_ids, roster_cache):
    """Return {'id','team'} for this season or None."""
    key = "%s|%d" % (name, season)
    if key in cache_ids and cache_ids[key].get("id") and cache_ids[key].get("team"):
        return cache_ids[key]

    school = cfbd_school(entry.get("school"))
    seed_info = seed.get(name) or {}
    seed_id = str(seed_info.get("id") or "") or None

    def roster(team):
        if not team:
            return []
        if team not in roster_cache:
            roster_cache[team] = api_get("/roster", {"team": team, "year": season}) or []
            time.sleep(SLEEP)
        return roster_cache[team]

    # 1) seed id on the expected school's roster
    if seed_id:
        for r in roster(school):
            if str(r.get("id")) == seed_id:
                return {"id": seed_id, "team": r.get("team") or school}
    # 2) name match on the expected school's roster
    target = norm_name(name)
    last, first = target.split()[-1], target.split()[0]
    for r in roster(school):
        if norm_name(roster_name(r)) == target:
            return {"id": str(r.get("id")), "team": r.get("team") or school}
    for r in roster(school):
        rn = norm_name(roster_name(r)).split()
        if rn and rn[-1] == last and rn[0][:1] == first[:1] and (r.get("position") or "") == (entry.get("pos") or r.get("position")):
            return {"id": str(r.get("id")), "team": r.get("team") or school}
    # 3) search this season (transfer / roster miss)
    res = api_get("/player/search", {"searchTerm": name, "year": season}) or []
    time.sleep(SLEEP)
    exact = [x for x in res if norm_name(x.get("name") or roster_name(x)) == target]
    if seed_id:
        for x in res:
            if str(x.get("id")) == seed_id and x.get("team"):
                return {"id": seed_id, "team": x["team"]}
    if exact:
        pref = [x for x in exact if cfbd_school(x.get("team")) == school] or exact
        x = pref[0]
        if x.get("team"):
            return {"id": str(x.get("id")), "team": x["team"]}
    return None


# ---------------------------------------------------------------- box scores
STAT_MAP = {
    ("passing", "YDS"): "py", ("passing", "TD"): "ptd", ("passing", "INT"): "int",
    ("rushing", "YDS"): "ry", ("rushing", "TD"): "rtd", ("rushing", "CAR"): "ra", ("rushing", "ATT"): "ra",
    ("receiving", "YDS"): "rcy", ("receiving", "TD"): "rctd", ("receiving", "REC"): "rec",
    ("fumbles", "LOST"): "fl",
}


def extract_team_week(games, team, wanted_ids):
    """-> {athlete_id: {stat fields..., '_opp', '_conf'}} for one team-week."""
    out = {}
    for game in games or []:
        teams = game.get("teams") or []
        mine = next((t for t in teams if (t.get("team") or "").lower() == team.lower()), None)
        if not mine:
            continue
        opp = next(((t.get("team") or "") for t in teams if t is not mine), "")
        conf = mine.get("conference") or ""
        for cat in mine.get("categories") or []:
            cname = (cat.get("name") or "").lower()
            for typ in cat.get("types") or []:
                sname = (typ.get("name") or "").upper()
                for ath in typ.get("athletes") or []:
                    aid = str(ath.get("id") or "")
                    if aid not in wanted_ids:
                        continue
                    row = out.setdefault(aid, {"_opp": opp, "_conf": conf})
                    val = ath.get("stat")
                    if cname == "passing" and sname == "C/ATT" and "/" in str(val):
                        pc, pa = str(val).split("/", 1)
                        try:
                            row["pc"] = int(pc); row["pa"] = int(pa)
                        except ValueError:
                            pass
                        continue
                    field = STAT_MAP.get((cname, sname))
                    if not field:
                        continue
                    try:
                        row[field] = int(float(val))
                    except (TypeError, ValueError):
                        pass
    return out


def week_is_settled(week_end, today):
    return (today - week_end).days > RECENT_DAYS


def fetch_team_weeks(team, wanted_ids, season, calendar, today, cache_games):
    """Return {week: {aid: row}} using + updating the (team, week) cache."""
    weeks = {}
    for wk in range(1, MAX_WEEK + 1):
        cal = calendar.get(wk)
        if cal and cal["start"] > today:
            break
        ckey = "%d|%s|%d" % (season, team, wk)
        c = cache_games.get(ckey)
        settled = bool(cal) and week_is_settled(cal["end"], today)
        if c and set(wanted_ids) <= set(c.get("ids", [])) and (settled or c.get("fetched") == today.isoformat()):
            weeks[wk] = c["rows"]
            continue
        games = api_get("/games/players", {"year": season, "team": team, "week": wk, "classification": "fbs"})
        if not games:
            games = api_get("/games/players", {"year": season, "team": team, "week": wk})
        time.sleep(SLEEP)
        rows = extract_team_week(games, team, wanted_ids)
        cache_games[ckey] = {"fetched": today.isoformat(), "ids": sorted(wanted_ids), "rows": rows,
                             "n_games": len(games or [])}
        weeks[wk] = rows
    return weeks


# ---------------------------------------------------------------- output
STAT_KEYS = ["pa", "pc", "py", "ptd", "int", "ra", "ry", "rtd", "rec", "rcy", "rctd", "fl"]
SEASON_ORDER = ["yr", "tm", "conf", "gp", "pa", "pc", "py", "ptd", "int", "ra", "ry", "rtd", "rypc", "rec", "rcy", "rctd", "rypr", "fl"]
WEEK_ORDER = ["wk", "tm", "opp", "pa", "pc", "py", "ptd", "int", "ra", "ry", "rtd", "rec", "rcy", "rctd", "fl"]


def js_obj(d, order):
    parts = []
    for k in order:
        if k not in d:
            continue
        v = d[k]
        if v is None or v == "" or (v == 0 and k not in ("yr", "wk")):
            continue
        parts.append("%s:%s" % (k, json.dumps(v, ensure_ascii=False) if isinstance(v, str) else v))
    return "{" + ",".join(parts) + "}"


def build_season_row(season, team, weeks_rows):
    games = [(wk, r) for wk, r in sorted(weeks_rows.items()) if r]
    if not games:
        return None, []
    tot = {"yr": season, "tm": team, "conf": games[-1][1].get("_conf") or games[0][1].get("_conf") or "", "gp": len(games)}
    for _, r in games:
        for k in STAT_KEYS:
            if r.get(k):
                tot[k] = tot.get(k, 0) + r[k]
    if tot.get("ra"):
        tot["rypc"] = round(tot.get("ry", 0) / tot["ra"], 1)
    if tot.get("rec"):
        tot["rypr"] = round(tot.get("rcy", 0) / tot["rec"], 1)
    log_rows = []
    for wk, r in games:
        w = {"wk": wk, "tm": team, "opp": r.get("_opp") or ""}
        for k in STAT_KEYS:
            if r.get(k):
                w[k] = r[k]
        log_rows.append(w)
    return tot, log_rows


def write_output(season, results, today):
    lines = [
        "// college_stats_devy.js - AUTO-GENERATED by scripts/refresh_devy_stats.py (%s)" % today.isoformat(),
        "// In-season %d college rows for devy / future-class prospects (COMBINE_DATA devy:true or yr > %d)." % (season, season),
        "// Loaded by window._ensureCollegeStatsData (index.html); _csPatchDevy() splices the season rows",
        "// into COLLEGE_STATS after the college_stats patch chain, so JM prospect grades pick them up.",
        "// Regenerated weekly by Task Scheduler \"MFF Devy Weekly Refresh\" - do not hand-edit.",
        "window._DEVY_SEASON_ROWS = {",
    ]
    for name in sorted(results):
        row = results[name]["season"]
        lines.append("  %s:%s," % (json.dumps(name, ensure_ascii=False), js_obj(row, SEASON_ORDER)))
    lines += [
        "};",
        "window._csPatchDevy = function () {",
        "  if (typeof COLLEGE_STATS === 'undefined') return;",
        "  var R = window._DEVY_SEASON_ROWS || {};",
        "  Object.keys(R).forEach(function (n) {",
        "    var row = R[n], arr = COLLEGE_STATS[n];",
        "    if (!Array.isArray(arr)) { arr = COLLEGE_STATS[n] = []; }",
        "    var i = -1;",
        "    for (var k = 0; k < arr.length; k++) { if (arr[k] && arr[k].yr === row.yr) { i = k; break; } }",
        "    if (i >= 0) arr[i] = row; else arr.push(row);",
        "    arr.sort(function (a, b) { return (a.yr || 0) - (b.yr || 0); });",
        "  });",
        "};",
        "if (typeof COLLEGE_WEEKLY === 'undefined') var COLLEGE_WEEKLY = {};",
    ]
    for name in sorted(results):
        q = json.dumps(name, ensure_ascii=False)
        lines.append("if (!COLLEGE_WEEKLY[%s]) COLLEGE_WEEKLY[%s] = {};" % (q, q))
        lines.append("COLLEGE_WEEKLY[%s][%d] = [%s];" % (
            q, season, ",".join(js_obj(w, WEEK_ORDER) for w in results[name]["log"])))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-bump", action="store_true")
    args = ap.parse_args()

    today = datetime.date.today()
    season = args.season or current_season(today)
    log("=== devy stats refresh: season %d, %s ===" % (season, today))

    combine = load_combine()
    universe = {n: e for n, e in combine.items()
                if e.get("devy") or (isinstance(e.get("yr"), int) and e["yr"] > season)}
    log("universe: %d prospects (devy:true or yr > %d)" % (len(universe), season))

    seed = load_json(SEED_JSON, {}).get("player_info", {})
    cache = load_json(CACHE_JSON, {})
    cache_ids = cache.setdefault("ids", {})
    cache_games = cache.setdefault("games", {})

    cal_raw = api_get("/calendar", {"year": season}) or []
    calendar = {}
    for c in cal_raw:
        try:
            wk = int(c.get("week"))
            if c.get("seasonType", "regular") != "regular":
                continue
            calendar[wk] = {"start": datetime.date.fromisoformat(c["startDate"][:10]),
                            "end": datetime.date.fromisoformat(c["endDate"][:10])}
        except (TypeError, ValueError, KeyError):
            pass
    started = [wk for wk, c in calendar.items() if c["start"] <= today]
    log("calendar: %d regular weeks, %d started" % (len(calendar), len(started)))
    if not started:
        log("season has not started - nothing to do")
        return 0

    roster_cache = {}
    resolved, unresolved = {}, []
    for name, entry in sorted(universe.items()):
        info = resolve_player(name, entry, season, seed, cache_ids, roster_cache)
        if info:
            resolved[name] = info
            cache_ids["%s|%d" % (name, season)] = info
        else:
            unresolved.append(name)
    log("resolved %d / %d" % (len(resolved), len(universe)))
    for n in unresolved:
        log("  UNRESOLVED (no %d roster/search hit): %s [%s %s]" % (season, n, universe[n].get("school"), universe[n].get("pos")))

    by_team = {}
    for name, info in resolved.items():
        by_team.setdefault(info["team"], {})[info["id"]] = name

    results = {}
    for team in sorted(by_team):
        ids = by_team[team]
        weeks = fetch_team_weeks(team, set(ids), season, calendar, today, cache_games)
        for aid, name in ids.items():
            per_week = {wk: rows.get(aid) for wk, rows in weeks.items() if rows.get(aid)}
            row, log_rows = build_season_row(season, team, per_week)
            if row:
                results[name] = {"season": row, "log": log_rows}
        log("  %-22s %2d weeks fetched, %s" % (team, len(weeks), ", ".join(
            "%s %dg" % (ids[a], len([1 for r in weeks.values() if r.get(a)])) for a in ids)))
    no_games = [n for n in resolved if n not in results]
    if no_games:
        log("no %d games yet: %s" % (season, ", ".join(no_games)))
    log("API calls: %d" % calls)

    out = write_output(season, results, today)
    if args.dry_run:
        log("DRY RUN - %d season rows, not writing" % len(results))
        return 0

    with open(CACHE_JSON, "w", encoding="utf-8") as f:
        json.dump(cache, f, separators=(",", ":"))

    if not results:
        log("no rows built - leaving %s untouched" % OUT_JS)
        return 0
    before = digest(OUT_JS)
    with open(OUT_JS, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    after = digest(OUT_JS)
    if before == after:
        log("%s unchanged (%d rows)" % (OUT_JS, len(results)))
        return 0
    log("wrote %s (%d season rows)" % (OUT_JS, len(results)))
    if args.no_bump:
        return 0
    with open(INDEX_HTML, encoding="utf-8", newline="") as f:
        html = f.read()
    new_html = bump_tag(html, os.path.basename(OUT_JS))
    if new_html != html:
        with open(INDEX_HTML, "w", encoding="utf-8", newline="") as f:
            f.write(new_html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
