"""refresh_devy_stats.py - college stats + PFF grades for devy / future-class prospects.

For every prospect the site treats as a devy (COMBINE_DATA entries flagged
devy:true, plus any entry whose draft-class year is later than the current
college season) this builds data/college_stats_devy.js:

    window._DEVY_SEASON_ROWS  - {name: [season rows]} in college_stats.js
                                 format (yr/tm/conf/gp/pa/pc/py/... + pff /
                                 pffRush season film grades), spliced into
                                 COLLEGE_STATS by window._csPatchDevy() after
                                 the college_stats patch chain (index.html
                                 _ensureCollegeStatsData). Rows for a year
                                 replace the on-disk row for that year.
    COLLEGE_WEEKLY[name][yr]  - game logs (CFBD box score + PFF per-game
                                 grade / analytics fields when available).
    COMBINE_DATA bio patches  - ht/wt from the CFBD roster for entries that
                                 lack them (never overwrites).

Seasons: the CURRENT college season is refreshed every run (new weeks +
stat corrections for weeks that ended < 8 days ago). Prior seasons are
BACKFILLED once for any player whose on-disk college_stats.js entry lacks
them (new 2027-class adds), going back --backfill-years (default 3).

CFBD: /roster + /player/search resolve ids per season (handles transfers),
/games/players per (team, week) gives the box scores (cached per team-week
in scripts/devy_refresh_cache.json; settled weeks are never re-fetched).

PFF (optional, no browser here): reads the CSVs written by
scripts/pull_pff_ncaa.py (pbp_cache/pff/ncaa). Weekly files add per-game
fields to the game log; season files (or the sum of weekly files for the
current season) add `pff` / `pffRush` to the season row using the site's
qualification floors (QB 100 att, RB 30 att, WR/TE 15 tgt). The JM model
takes the best qualified season grade, so these feed the Film Grade
component directly.

Team audit: scripts/devy_audit.json + console lines flag any prospect
whose COMBINE_DATA school differs from the CFBD roster team this season.

Bumps the college_stats_devy.js ?v= in index.html only when the data file's
bytes change (current tag read from disk at bump time).

Usage:
    python scripts/refresh_devy_stats.py            # write + bump
    python scripts/refresh_devy_stats.py --dry-run
    python scripts/refresh_devy_stats.py --no-bump --backfill-years 3
"""
import argparse
import csv
import datetime
import glob
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
COLLEGE_JS = "data/college_stats.js"
SEED_JSON = "devy_weekly.json"
CACHE_JSON = "scripts/devy_refresh_cache.json"
AUDIT_JSON = "scripts/devy_audit.json"
OUT_JS = "data/college_stats_devy.js"
INDEX_HTML = "index.html"
PFF_NCAA = r"E:\MyFantasyFootball\pbp_cache\pff\ncaa"
MAX_WEEK = 15          # regular season incl. conference championships
RECENT_DAYS = 8        # re-fetch weeks that ended within this many days
SLEEP = 0.25
PFF_MIN = {"QB": ("attempts", 100), "RB": ("attempts", 30), "WR": ("targets", 15), "TE": ("targets", 15)}

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
    "Louisiana St.": "LSU", "Southern Methodist": "SMU", "Hawaii": "Hawai'i",
    "Louisiana-Monroe": "UL Monroe", "Louisiana-Lafayette": "Louisiana",
    "Texas Christian": "TCU", "Nevada-Las Vegas": "UNLV", "Alabama-Birmingham": "UAB",
}
# CFBD team -> PFF team_name (uppercase) where a plain uppercase compare fails
PFF_TEAM_ALIAS = {
    "OLE MISS": {"MISSISSIPPI", "OLE MISS"}, "MIAMI": {"MIAMI FL", "MIAMI (FL)", "MIAMI"},
    "UL MONROE": {"LA MONROE", "UL MONROE", "LOUISIANA MONROE"}, "LOUISIANA": {"LOUISIANA", "LA LAFAYETTE"},
    "TEXAS A&M": {"TEXAS A&M", "TEXAS AM"}, "HAWAI'I": {"HAWAII"}, "SAN JOSÉ STATE": {"SAN JOSE ST", "SAN JOSE STATE"},
    "APPALACHIAN STATE": {"APP STATE", "APPALACHIAN ST"}, "PITTSBURGH": {"PITT", "PITTSBURGH"},
    "SOUTHERN MISS": {"SOUTHERN MISS", "S MISSISSIPPI"}, "WESTERN KENTUCKY": {"W KENTUCKY", "WESTERN KENTUCKY"},
    "MIDDLE TENNESSEE": {"MID TENNESSEE", "MIDDLE TENN"}, "NC STATE": {"NC STATE", "N CAROLINA ST"},
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
    n = n.replace(".", "").replace("'", "").replace("\u2019", "").replace("-", " ")
    return re.sub(r"\s+", " ", n).strip()


def roster_name(r):
    return ((r.get("firstName") or "") + " " + (r.get("lastName") or "")).strip() or (r.get("name") or "")


def current_season(today):
    return today.year if today.month >= 8 else today.year - 1


PATCH_JS = "data/combine_d_patches.js"
_CUR_SEASON = 0  # set in main() before load_combine()


def load_combine():
    """COMBINE_DATA on disk + the devy stubs data/combine_d_patches.js adds at
    runtime (`if (!COMBINE_DATA[n]) COMBINE_DATA[n] = { school, pos, devy: true, eligYr }`)
    so the universe matches the site's DEVY board, not just the JSON file."""
    with open(COMBINE_JS, encoding="utf-8") as f:
        txt = f.read()
    cb = json.loads(txt.split("=", 1)[1].strip().rstrip(";"))
    try:
        with open(PATCH_JS, encoding="utf-8") as f:
            ptxt = f.read()
    except OSError:
        return cb
    added = 0
    stale = []
    for m in re.finditer(r"""COMBINE_DATA\[(['"])((?:\\.|(?!\1)[^\\])+?)\1\]\s*=\s*\{([^}]*devy:\s*true[^}]*)\}""", ptxt):
        name, body = m.group(2).replace("\\'", "'"), m.group(3)
        if name in cb:
            continue
        ent = {"devy": True, "_patch": True}
        for k in ("school", "pos"):
            mm = re.search(r"""\b%s:\s*(['"])(.+?)\1""" % k, body)
            if mm:
                ent[k] = mm.group(2)
        mm = re.search(r"\beligYr:\s*(\d{4})", body)
        if mm:
            ent["eligYr"] = int(mm.group(1)); ent["yr"] = int(mm.group(1))
        # eligYr <= current season usually means the stub is stale (player returned to
        # school or was drafted); keep it - the roster lookup decides - but flag it.
        if ent.get("eligYr") and ent["eligYr"] <= _CUR_SEASON:
            stale.append(name)
        cb[name] = ent
        added += 1
    if added:
        log("combine_d_patches.js: +%d runtime devy entries (%d with eligYr<=%d, check combine_d_patches.js: %s)" % (added, len(stale), _CUR_SEASON, ", ".join(sorted(stale))))
    return cb


def ondisk_years(name):
    """Years already present for this player in data/college_stats.js (regex on the single-line file)."""
    m = re.search(r'"%s":\[(.*?)\]' % re.escape(name), _COLLEGE_TXT)
    return {int(y) for y in re.findall(r"yr:(\d{4})", m.group(1))} if m else set()


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
    today = datetime.date.today().isoformat()
    pat = re.compile(r"(%s\?v=)([\w.-]+)" % re.escape(fname))
    m = pat.search(html)
    if not m:
        log("  WARN: no ?v= tag found for", fname)
        return html
    cur = m.group(2)
    m2 = re.match(r"%sdv(\d+)$" % re.escape(today), cur)
    new = today if not cur.startswith(today) else today + "dv%d" % ((int(m2.group(1)) + 1) if m2 else 2)
    if cur == new:
        return html
    log("  bump %s ?v= %s -> %s" % (fname, cur, new))
    return pat.sub(lambda mm: mm.group(1) + new, html)


# ---------------------------------------------------------------- resolution
def resolve_player(name, entry, season, seed, cache_ids, roster_cache, current, year_map=None):
    """Return {'id','team','ht','wt'} for this season or None.
    current=True uses the COMBINE_DATA school as the first guess. Prior seasons
    use year_map (id -> team from the year-wide /roster?year=) because
    /player/search?year= only ever returns the player's CURRENT team, which
    sent transfers (Mensah Tulane->Duke->Miami) to the wrong box scores."""
    key = "%s|%d" % (name, season)
    c = cache_ids.get(key)
    if c and c.get("id") and c.get("team"):
        return c

    school = cfbd_school(entry.get("school"))
    seed_info = seed.get(name) or {}
    seed_id = str(seed_info.get("id") or "") or None
    known_id = seed_id or next((cache_ids[k]["id"] for k in cache_ids if k.startswith(name + "|") and cache_ids[k].get("id")), None)
    target = norm_name(name)
    last, first = target.split()[-1], target.split()[0]

    def roster(team):
        if not team:
            return []
        ck = "%s|%d" % (team, season)
        if ck not in roster_cache:
            roster_cache[ck] = api_get("/roster", {"team": team, "year": season}) or []
            time.sleep(SLEEP)
        return roster_cache[ck]

    def hit(r, team):
        h = r.get("height")
        return {"id": str(r.get("id")), "team": r.get("team") or team,
                "ht": ("%d-%d" % (h // 12, h % 12)) if isinstance(h, (int, float)) and h else None,
                "wt": int(r["weight"]) if r.get("weight") else None}

    if not current:
        if known_id and year_map is not None:
            team = year_map.get(known_id)
            return {"id": known_id, "team": team, "ht": None, "wt": None} if team else None
        return None
    if True:
        # 1) known id on the expected school's roster
        if known_id:
            for r in roster(school):
                if str(r.get("id")) == known_id:
                    return hit(r, school)
        # 2) name match on the expected school's roster
        for r in roster(school):
            if norm_name(roster_name(r)) == target:
                return hit(r, school)
        for r in roster(school):
            rn = norm_name(roster_name(r)).split()
            if rn and rn[-1] == last and rn[0][:1] == first[:1] and (r.get("position") or "") == (entry.get("pos") or ""):
                return hit(r, school)
    # 3) search this season (transfer / prior season / roster miss)
    res = api_get("/player/search", {"searchTerm": name, "year": season}) or []
    time.sleep(SLEEP)
    if known_id:
        for x in res:
            if str(x.get("id")) == known_id and x.get("team"):
                return {"id": known_id, "team": x["team"], "ht": None, "wt": None}
    exact = [x for x in res if norm_name(x.get("name") or roster_name(x)) == target]
    if exact:
        pref = [x for x in exact if cfbd_school(x.get("team")) == school] or exact
        x = pref[0]
        if x.get("team"):
            return {"id": str(x.get("id")), "team": x["team"], "ht": None, "wt": None}
    return None


# ---------------------------------------------------------------- box scores
STAT_MAP = {
    ("passing", "YDS"): "py", ("passing", "TD"): "ptd", ("passing", "INT"): "int",
    ("rushing", "YDS"): "ry", ("rushing", "TD"): "rtd", ("rushing", "CAR"): "ra", ("rushing", "ATT"): "ra",
    ("receiving", "YDS"): "rcy", ("receiving", "TD"): "rctd", ("receiving", "REC"): "rec",
    ("fumbles", "LOST"): "fl",
}


def extract_team_week(games, team, wanted_ids):
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


def fetch_team_weeks(team, wanted_ids, season, calendar, today, cache_games, settled_all):
    weeks = {}
    for wk in range(1, MAX_WEEK + 1):
        cal = calendar.get(wk)
        if cal and cal["start"] > today:
            break
        ckey = "%d|%s|%d" % (season, team, wk)
        c = cache_games.get(ckey)
        settled = settled_all or (bool(cal) and (today - cal["end"]).days > RECENT_DAYS)
        if c and set(wanted_ids) <= set(c.get("ids", [])) and (settled or c.get("fetched") == today.isoformat()):
            weeks[wk] = c["rows"]
            continue
        games = api_get("/games/players", {"year": season, "team": team, "week": wk, "classification": "fbs"})
        if not games:
            games = api_get("/games/players", {"year": season, "team": team, "week": wk})
        time.sleep(SLEEP)
        rows = extract_team_week(games, team, wanted_ids)
        cache_games[ckey] = {"fetched": today.isoformat(), "ids": sorted(set(wanted_ids) | set(c.get("ids", []) if c else [])),
                             "rows": {**(c["rows"] if c else {}), **rows}, "n_games": len(games or [])}
        weeks[wk] = cache_games[ckey]["rows"]
    return weeks


# ---------------------------------------------------------------- PFF files
def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pff_team_ok(pff_team, cfbd_team):
    a = re.sub(r"[^A-Z0-9&]", "", (pff_team or "").upper())
    b = (cfbd_team or "").upper()
    bb = re.sub(r"[^A-Z0-9&]", "", b)
    if a == bb:
        return True
    for k, v in PFF_TEAM_ALIAS.items():
        if re.sub(r"[^A-Z0-9&]", "", k) == bb and a in {re.sub(r"[^A-Z0-9&]", "", x) for x in v}:
            return True
    return a.replace("ST", "STATE") == bb or bb.replace("STATE", "ST") == a


def load_pff(season):
    """-> {(facet, week): {norm_name: [rows]}} for weekly files + week 0 season files."""
    out = {}
    for path in glob.glob(os.path.join(PFF_NCAA, "pff_ncaa_*_%d*.csv" % season)):
        base = os.path.basename(path)[:-4]
        m = re.match(r"pff_ncaa_(\w+?)_%d(?:_w(\d+))?$" % season, base)
        if not m:
            continue
        facet, wk = m.group(1), int(m.group(2) or 0)
        idx = {}
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                idx.setdefault(norm_name(row.get("player")), []).append(row)
        out[(facet, wk)] = idx
    return out


def pff_row(pff, facet, wk, name, team, pos=None):
    rows = pff.get((facet, wk), {}).get(norm_name(name)) or []
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    tm = [r for r in rows if _pff_team_ok(r.get("team_name"), team)]
    if len(tm) == 1:
        return tm[0]
    if pos:
        pp = [r for r in (tm or rows) if (r.get("position") or "").replace("HB", "RB") == pos]
        if len(pp) == 1:
            return pp[0]
    return (tm or rows)[0]


WEEK_PFF_FIELDS = {
    "QB": [("passing", "grades_pass", "pffP"), ("passing", "big_time_throws", "btt"), ("passing", "turnover_worthy_plays", "twp"),
           ("passing", "accuracy_percent", "acc"), ("passing", "avg_depth_of_target", "adot"), ("passing", "avg_time_to_throw", "ttt"),
           ("passing", "def_gen_pressures", "prs"), ("passing", "pressure_to_sack_rate", "p2s"), ("passing", "dropbacks", "db"),
           ("rushing", "grades_run", "pffR")],
    "RB": [("rushing", "grades_run", "pffR"), ("rushing", "yco_attempt", "yco"), ("rushing", "elusive_rating", "elu"),
           ("rushing", "breakaway_percent", "brk"), ("rushing", "avoided_tackles", "mtf"), ("rushing", "explosive", "exp"),
           ("rushing", "gap_attempts", "gap"), ("rushing", "zone_attempts", "zone"),
           ("receiving", "grades_pass_route", "pffRt"), ("receiving", "routes", "rts"), ("receiving", "targets", "tgt"), ("receiving", "yprr", "yprr")],
    "WR": [("receiving", "grades_pass_route", "pffRt"), ("receiving", "routes", "rts"), ("receiving", "targets", "tgt"), ("receiving", "yprr", "yprr"),
           ("receiving", "avg_depth_of_target", "adot"), ("receiving", "slot_rate", "slot"), ("receiving", "contested_catch_rate", "cc"),
           ("receiving", "drops", "drp"), ("receiving", "yards_after_catch_per_reception", "yac"), ("receiving", "grades_hands_drop", "pffH"),
           ("receiving", "wide_rate", "wide"), ("receiving", "inline_rate", "inl")],
}
WEEK_PFF_FIELDS["TE"] = WEEK_PFF_FIELDS["WR"]


def enrich_week(w, pff, wk, name, team, pos):
    off = pff_row(pff, "offense", wk, name, team, pos)
    if off and _f(off.get("grades_offense")) is not None:
        w["pff"] = round(_f(off["grades_offense"]), 1)
        sn = _f(off.get("snap_counts_total"))
        if sn:
            w["snp"] = int(sn)
    for facet, col, key in WEEK_PFF_FIELDS.get(pos, []):
        r = pff_row(pff, facet, wk, name, team, pos)
        v = _f(r.get(col)) if r else None
        if v is None:
            continue
        w[key] = int(v) if key in ("btt", "twp", "prs", "db", "mtf", "rts", "tgt", "drp", "exp", "gap", "zone") else round(v, 1)


def season_pff(pff, name, team, pos, weeks_played):
    """(pff, pffRush) for the season row from the season file (week 0) or, when
    that file is absent/stale, an attempt-weighted mean of the weekly files."""
    def qualified(r, col, floor):
        v = _f(r.get(col)) if r else None
        return v is not None and v >= floor

    col, floor = PFF_MIN[pos]
    facet = {"QB": "passing", "RB": "rushing", "WR": "receiving", "TE": "receiving"}[pos]
    grade_col = {"QB": "grades_pass", "RB": "grades_pass_route", "WR": "grades_offense", "TE": "grades_offense"}[pos]
    rush_col = "grades_run"
    r = pff_row(pff, facet, 0, name, team, pos)
    if r and _f(r.get("player_game_count")) and _f(r["player_game_count"]) >= len(weeks_played):
        if qualified(r, col, floor):
            g = _f(r.get(grade_col)); ru = _f(r.get(rush_col)) if pos == "RB" else None
            return (round(g, 1) if g else None, round(ru, 1) if ru else None)
        return (None, None)
    # weekly aggregate (in-season): weight by attempts/targets
    tot_w, g_sum, ru_sum, vol = 0.0, 0.0, 0.0, 0.0
    for wk in weeks_played:
        rr = pff_row(pff, facet, wk, name, team, pos)
        if not rr:
            continue
        wgt = _f(rr.get(col)) or 0
        g = _f(rr.get(grade_col)); ru = _f(rr.get(rush_col))
        vol += wgt
        if g is not None and wgt:
            g_sum += g * wgt; tot_w += wgt
        if pos == "RB" and ru is not None and wgt:
            ru_sum += ru * wgt
    if vol < floor or not tot_w:
        return (None, None)
    return (round(g_sum / tot_w, 1), round(ru_sum / tot_w, 1) if pos == "RB" else None)


# ---------------------------------------------------------------- output
STAT_KEYS = ["pa", "pc", "py", "ptd", "int", "ra", "ry", "rtd", "rec", "rcy", "rctd", "fl"]
SEASON_ORDER = ["yr", "tm", "conf", "gp", "pa", "pc", "py", "ptd", "int", "ra", "ry", "rtd", "rypc", "rec", "rcy", "rctd", "rypr", "fl", "pff", "pffRush"]
WEEK_ORDER = ["wk", "tm", "opp", "pa", "pc", "py", "ptd", "int", "ra", "ry", "rtd", "rec", "rcy", "rctd", "fl",
              "pff", "snp", "pffP", "pffR", "pffRt", "pffH", "btt", "twp", "acc", "adot", "ttt", "prs", "p2s", "db",
              "yco", "elu", "brk", "mtf", "exp", "gap", "zone", "rts", "tgt", "yprr", "slot", "wide", "inl", "cc", "drp", "yac"]


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


def write_output(season, results, bios, today):
    q = lambda s: json.dumps(s, ensure_ascii=False)  # noqa: E731
    lines = [
        "// college_stats_devy.js - AUTO-GENERATED by scripts/refresh_devy_stats.py (%s)" % today.isoformat(),
        "// College rows for devy / future-class prospects (COMBINE_DATA devy:true or yr > %d):" % season,
        "// season rows (CFBD box scores + PFF season film grade) spliced into COLLEGE_STATS by _csPatchDevy(),",
        "// game logs (CFBD + PFF per-game grades/analytics) into COLLEGE_WEEKLY, ht/wt patches into COMBINE_DATA.",
        "// Regenerated weekly by Task Scheduler \"MFF Devy Weekly Refresh\" - do not hand-edit.",
        "window._DEVY_SEASON_ROWS = {",
    ]
    for name in sorted(results):
        rows = [r["season"] for r in sorted(results[name].values(), key=lambda x: x["season"]["yr"])]
        lines.append("  %s:[%s]," % (q(name), ",".join(js_obj(r, SEASON_ORDER) for r in rows)))
    lines += [
        "};",
        "window._csPatchDevy = function () {",
        "  if (typeof COLLEGE_STATS === 'undefined') return;",
        "  var R = window._DEVY_SEASON_ROWS || {};",
        "  Object.keys(R).forEach(function (n) {",
        "    var arr = COLLEGE_STATS[n];",
        "    if (!Array.isArray(arr)) { arr = COLLEGE_STATS[n] = []; }",
        "    R[n].forEach(function (row) {",
        "      var i = -1;",
        "      for (var k = 0; k < arr.length; k++) { if (arr[k] && arr[k].yr === row.yr) { i = k; break; } }",
        "      if (i >= 0) arr[i] = row; else arr.push(row);",
        "    });",
        "    arr.sort(function (a, b) { return (a.yr || 0) - (b.yr || 0); });",
        "  });",
        "};",
        "if (typeof COLLEGE_WEEKLY === 'undefined') var COLLEGE_WEEKLY = {};",
    ]
    for name in sorted(results):
        lines.append("if (!COLLEGE_WEEKLY[%s]) COLLEGE_WEEKLY[%s] = {};" % (q(name), q(name)))
        for yr in sorted(results[name]):
            lines.append("COLLEGE_WEEKLY[%s][%d] = [%s];" % (
                q(name), yr, ",".join(js_obj(w, WEEK_ORDER) for w in results[name][yr]["log"])))
    lines.append("// ht/wt from the CFBD roster for prospects whose COMBINE_DATA entry lacks them")
    for name in sorted(bios):
        b = bios[name]
        parts = []
        if b.get("ht"):
            parts.append("if(!c.ht)c.ht=%s" % q(b["ht"]))
        if b.get("wt"):
            parts.append("if(!c.wt)c.wt=%d" % b["wt"])
        if parts:
            lines.append("if (typeof COMBINE_DATA !== 'undefined' && COMBINE_DATA[%s]) { var c = COMBINE_DATA[%s]; %s; }" % (q(name), q(name), "; ".join(parts)))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- main
def main():
    global _COLLEGE_TXT
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--backfill-years", type=int, default=3, help="prior seasons to backfill for players missing them on disk")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-bump", action="store_true")
    ap.add_argument("--no-pff", action="store_true")
    args = ap.parse_args()

    today = datetime.date.today()
    season = args.season or current_season(today)
    log("=== devy stats refresh: season %d, %s ===" % (season, today))

    global _CUR_SEASON
    _CUR_SEASON = season
    combine = load_combine()
    with open(COLLEGE_JS, encoding="utf-8") as f:
        _COLLEGE_TXT = f.read()
    universe = {n: e for n, e in combine.items()
                if e.get("devy") or (isinstance(e.get("yr"), int) and e["yr"] > season)}
    log("universe: %d prospects (devy:true or yr > %d)" % (len(universe), season))

    seed = load_json(SEED_JSON, {}).get("player_info", {})
    cache = load_json(CACHE_JSON, {})
    cache_ids = cache.setdefault("ids", {})
    cache_games = cache.setdefault("games", {})
    cache_cal = cache.setdefault("calendar", {})

    def calendar_for(s):
        if str(s) in cache_cal and s != season:
            raw = cache_cal[str(s)]
        else:
            raw = api_get("/calendar", {"year": s}) or []
            cache_cal[str(s)] = raw
        cal = {}
        for c in raw:
            try:
                if c.get("seasonType", "regular") != "regular":
                    continue
                cal[int(c.get("week"))] = {"start": datetime.date.fromisoformat(c["startDate"][:10]),
                                           "end": datetime.date.fromisoformat(c["endDate"][:10])}
            except (TypeError, ValueError, KeyError):
                pass
        return cal

    calendar = calendar_for(season)
    if not [wk for wk, c in calendar.items() if c["start"] <= today]:
        log("season has not started - nothing to do")
        return 0

    # ---- which seasons per player -------------------------------------------
    plan = {}  # name -> [seasons]
    for name in universe:
        have = ondisk_years(name)
        prior = [y for y in range(season - args.backfill_years, season) if y not in have]
        plan[name] = prior + [season]
    n_backfill = sum(1 for n in plan if len(plan[n]) > 1)
    log("backfill: %d players need prior seasons" % n_backfill)

    # ---- resolve ids per (player, season) ------------------------------------
    roster_cache = {}
    resolved = {}    # (name, season) -> info
    unresolved = []
    audit = {}
    year_maps = {}   # prior season -> {id: team} from /roster?year= (one call per season, only if needed)

    def year_map_for(s):
        if s not in year_maps:
            rows = api_get("/roster", {"year": s}) or []
            year_maps[s] = {str(r.get("id")): r.get("team") for r in rows if r.get("id") and r.get("team")}
            log("  roster map %d: %d players" % (s, len(year_maps[s])))
        return year_maps[s]

    for name, entry in sorted(universe.items()):
        for s in sorted(plan[name], reverse=True):   # current season first: it establishes the CFBD id
            cached = cache_ids.get("%s|%d" % (name, s))
            ym = None if (s == season or cached) else year_map_for(s)
            info = resolve_player(name, entry, s, seed, cache_ids, roster_cache, current=(s == season), year_map=ym)
            if info:
                resolved[(name, s)] = info
                cache_ids["%s|%d" % (name, s)] = info
            elif s == season:
                unresolved.append(name)
        cur = resolved.get((name, season)) or {}
        audit[name] = {"pos": entry.get("pos"), "combine_school": entry.get("school"), "cfbd_team": cur.get("team"),
                       "cfbd_id": cur.get("id"), "seasons": {str(s): resolved[(name, s)]["team"] for s in plan[name] if (name, s) in resolved},
                       "draftProj": entry.get("draftProj"), "eligYr": entry.get("eligYr")}
        audit[name]["school_mismatch"] = bool(cur.get("team")) and cfbd_school(entry.get("school")).lower() != cur["team"].lower()
    log("resolved %d / %d for %d" % (sum(1 for k in resolved if k[1] == season), len(universe), season))
    for n in unresolved:
        log("  UNRESOLVED (no %d roster/search hit): %s [%s %s]" % (season, n, universe[n].get("school"), universe[n].get("pos")))
    for n, a in audit.items():
        if a["school_mismatch"]:
            log("  SCHOOL MISMATCH: %s combine=%s cfbd=%s" % (n, a["combine_school"], a["cfbd_team"]))

    # ---- box scores per (team, season) ---------------------------------------
    by_team = {}
    for (name, s), info in resolved.items():
        by_team.setdefault((info["team"], s), {})[info["id"]] = name
    results = {}   # name -> {yr: {season, log}}
    for (team, s) in sorted(by_team, key=lambda x: (x[1], x[0])):
        ids = by_team[(team, s)]
        cal = calendar if s == season else calendar_for(s)
        weeks = fetch_team_weeks(team, set(ids), s, cal, today if s == season else datetime.date(s, 12, 31), cache_games, settled_all=(s != season))
        for aid, name in ids.items():
            per_week = {wk: rows.get(aid) for wk, rows in weeks.items() if rows.get(aid)}
            row, log_rows = build_season_row(s, team, per_week)
            if row:
                results.setdefault(name, {})[s] = {"season": row, "log": log_rows}
        if s == season:
            log("  %-22s %2d weeks, %s" % (team, len(weeks), ", ".join(
                "%s %dg" % (ids[a], len([1 for r in weeks.values() if r.get(a)])) for a in ids)))
    no_games = [n for n in universe if n in {k[0] for k in resolved if k[1] == season} and season not in results.get(n, {})]
    if no_games:
        log("no %d games yet: %s" % (season, ", ".join(no_games)))
    log("CFBD API calls: %d" % calls)

    # ---- PFF enrichment -------------------------------------------------------
    if not args.no_pff and os.path.isdir(PFF_NCAA):
        pff_by_season = {}
        n_pff_rows = n_pff_weeks = 0
        for name, seasons in results.items():
            pos = (universe[name].get("pos") or "WR").upper()
            if pos not in PFF_MIN:
                continue
            for s, r in seasons.items():
                if s not in pff_by_season:
                    pff_by_season[s] = load_pff(s)
                pff = pff_by_season[s]
                if not pff:
                    continue
                team = r["season"]["tm"]
                for w in r["log"]:
                    before = len(w)
                    enrich_week(w, pff, w["wk"], name, team, pos)
                    n_pff_weeks += len(w) > before
                g, ru = season_pff(pff, name, team, pos, [w["wk"] for w in r["log"]])
                if g:
                    r["season"]["pff"] = g
                    n_pff_rows += 1
                if ru:
                    r["season"]["pffRush"] = ru
                audit[name].setdefault("pff", {})[str(s)] = {"pff": g, "pffRush": ru}
        log("PFF: %d season grades, %d game logs enriched (files for seasons %s)" % (
            n_pff_rows, n_pff_weeks, sorted(s for s, v in pff_by_season.items() if v)))
    else:
        log("PFF: skipped (%s)" % ("--no-pff" if args.no_pff else "no " + PFF_NCAA))

    # ---- bios for entries missing ht/wt ---------------------------------------
    bios = {}
    for name, e in universe.items():
        info = resolved.get((name, season)) or {}
        if (not e.get("ht") and info.get("ht")) or (not e.get("wt") and info.get("wt")):
            bios[name] = {"ht": None if e.get("ht") else info.get("ht"), "wt": None if e.get("wt") else info.get("wt")}
    if bios:
        log("bio patches (ht/wt from CFBD roster): %s" % ", ".join(sorted(bios)))

    out = write_output(season, results, bios, today)
    if args.dry_run:
        log("DRY RUN - %d players, %d season rows, not writing" % (len(results), sum(len(v) for v in results.values())))
        return 0

    with open(CACHE_JSON, "w", encoding="utf-8") as f:
        json.dump(cache, f, separators=(",", ":"))
    with open(AUDIT_JSON, "w", encoding="utf-8") as f:
        json.dump({"season": season, "run": today.isoformat(), "players": audit}, f, indent=1, sort_keys=True)

    if not results:
        log("no rows built - leaving %s untouched" % OUT_JS)
        return 0
    before = digest(OUT_JS)
    with open(OUT_JS, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    if before == digest(OUT_JS):
        log("%s unchanged (%d players)" % (OUT_JS, len(results)))
        return 0
    log("wrote %s (%d players, %d season rows)" % (OUT_JS, len(results), sum(len(v) for v in results.values())))
    if args.no_bump:
        return 0
    with open(INDEX_HTML, encoding="utf-8", newline="") as f:
        html = f.read()
    new_html = bump_tag(html, os.path.basename(OUT_JS))
    if new_html != html:
        with open(INDEX_HTML, "w", encoding="utf-8", newline="") as f:
            f.write(new_html)
    return 0


_COLLEGE_TXT = ""

if __name__ == "__main__":
    sys.exit(main())
