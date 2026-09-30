"""pull_devy_headshots.py - ESPN college headshots + team logo ids for the devy board.

For every runtime devy prospect (combine_data.js + combine_d_patches.js stubs, same
universe as refresh_devy_stats.py) this looks the player up on his school's ESPN
college-football roster and writes data/devy_headshots.js:

    window.DEVY_HEADSHOTS  = { "Arch Manning": { id: 4870906, tid: 251 }, ... }
    window.COLLEGE_TEAM_IDS = { "Texas": 251, "Ohio St.": 194, ... }   (combine_data.js school spelling)

app.js uses them for the DEVY rows/cards (headshot) and tier cards / graphics
(college logo https://a.espncdn.com/i/teamlogos/ncaa/500/<tid>.png), mirroring the
NFL _slImg / TEAM_LOGO_IDS path. ESPN athlete ids are cached in
scripts/devy_headshots_cache.json so a weekly run only fetches rosters for players
still missing an id (transfers get re-looked-up when the school changes).

    python scripts/pull_devy_headshots.py [--dry-run] [--force]
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
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import refresh_devy_stats as rds  # noqa: E402  (load_combine incl. runtime stubs)

OUT = "data/devy_headshots.js"
CACHE = "scripts/devy_headshots_cache.json"
INDEX_HTML = "index.html"
TEAMS_API = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams"
ROSTER_API = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/%s/roster"
UA = {"User-Agent": "Mozilla/5.0"}
# combine_data.js school spelling -> ESPN location / display name
SCHOOL_FIX = {
    "Ohio St.": "Ohio State", "Penn St.": "Penn State", "Michigan St.": "Michigan State", "Arizona St.": "Arizona State",
    "Kansas St.": "Kansas State", "Oklahoma St.": "Oklahoma State", "Florida St.": "Florida State", "Iowa St.": "Iowa State",
    "Oregon St.": "Oregon State", "Washington St.": "Washington State", "Mississippi St.": "Mississippi State",
    "Boise St.": "Boise State", "Fresno St.": "Fresno State", "San Diego St.": "San Diego State", "Colorado St.": "Colorado State",
    "Utah St.": "Utah State", "Appalachian St.": "Appalachian State", "Georgia St.": "Georgia State",
    "North Dakota St.": "North Dakota State", "Miami (FL)": "Miami", "Mississippi": "Ole Miss", "Southern California": "USC",
    "Brigham Young": "BYU", "Texas Christian": "TCU", "Louisiana St.": "LSU", "Central Florida": "UCF",
    "Texas-San Antonio": "UTSA", "Southern Methodist": "SMU", "Louisiana-Monroe": "UL Monroe", "Louisiana-Lafayette": "Louisiana",
}


def log(*a):
    print(*a, flush=True)


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def tnorm(s):
    return re.sub(r"[^a-z]", "", (s or "").lower().replace("state", "st"))


def load_json(p, d):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return d


def espn_teams():
    r = requests.get(TEAMS_API, params={"limit": 1000}, headers=UA, timeout=40)
    r.raise_for_status()
    out = {}
    for t in r.json()["sports"][0]["leagues"][0]["teams"]:
        tm = t["team"]
        for k in (tm.get("location"), tm.get("displayName"), tm.get("abbreviation"), tm.get("nickname")):
            if k:
                out.setdefault(tnorm(k), int(tm["id"]))
    return out


def digest(p):
    try:
        with open(p, "rb") as f:
            return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()
    except OSError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-look-up every player")
    ap.add_argument("--no-bump", action="store_true")
    a = ap.parse_args()
    today = datetime.date.today()
    rds._CUR_SEASON = today.year if today.month >= 8 else today.year - 1
    cb = rds.load_combine()
    devy = {n: e for n, e in cb.items() if e.get("devy") and e.get("school")}
    log("devy prospects: %d" % len(devy))

    teams = espn_teams()
    team_ids = {}
    for school in sorted({e["school"] for e in devy.values()}):
        q = SCHOOL_FIX.get(school, school)
        tid = teams.get(tnorm(q)) or teams.get(tnorm(school))
        if tid:
            team_ids[school] = tid
        else:
            log("  no ESPN team id for school: %s" % school)
    log("schools: %d, mapped %d" % (len({e["school"] for e in devy.values()}), len(team_ids)))

    cache = load_json(CACHE, {})
    _rc = load_json("scripts/devy_refresh_cache.json", {}).get("ids", {})
    cfbd_ids = {k.split("|")[0]: v.get("id") for k, v in _rc.items() if k.endswith("|%d" % rds._CUR_SEASON) and v.get("id")}
    rosters = {}
    found, missing = {}, []
    for name, e in sorted(devy.items()):
        tid = team_ids.get(e["school"])
        c = cache.get(name)
        if c and not a.force and c.get("tid") == tid and c.get("id"):
            found[name] = {"id": c["id"], "tid": tid}
            continue
        if not tid:
            missing.append((name, e["school"], "no team id"))
            continue
        if tid not in rosters:
            try:
                r = requests.get(ROSTER_API % tid, headers=UA, timeout=40)
                rosters[tid] = r.json() if r.status_code == 200 else {}
            except (requests.RequestException, ValueError):
                rosters[tid] = {}
            time.sleep(0.3)
        athletes = []
        for grp in rosters[tid].get("athletes", []):
            if isinstance(grp, dict) and "items" in grp:
                athletes.extend(grp.get("items", []))
            elif isinstance(grp, dict) and grp.get("fullName"):
                athletes.append(grp)          # flat roster shape
        target = norm(name)
        hit = next((x for x in athletes if norm(x.get("fullName")) == target), None)
        if not hit:
            last, first = target[-6:], target[:3]
            cand = [x for x in athletes if norm(x.get("fullName")).endswith(norm((x.get("lastName") or ""))) and norm(x.get("lastName")) and target.endswith(norm(x.get("lastName")))
                    and norm(x.get("firstName") or "")[:2] == target[:2] and (x.get("position") or {}).get("abbreviation", "") in (e.get("pos"), "")]
            hit = cand[0] if len(cand) == 1 else None
        if not hit:
            # CFBD athlete ids ARE ESPN athlete ids: fall back to the weekly stats refresh cache
            cf = cfbd_ids.get(name)
            if cf:
                found[name] = {"id": int(cf), "tid": tid}
                cache[name] = {"id": int(cf), "tid": tid, "espn_name": None, "src": "cfbd", "at": today.isoformat()}
                continue
        if hit:
            found[name] = {"id": int(hit["id"]), "tid": tid}
            cache[name] = {"id": int(hit["id"]), "tid": tid, "espn_name": hit.get("fullName"), "at": today.isoformat()}
        else:
            missing.append((name, e["school"], "not on ESPN roster"))
    log("headshots: %d found, %d missing" % (len(found), len(missing)))
    for m in missing:
        log("  missing: %s (%s) - %s" % m)

    js = ["// devy_headshots.js - AUTO-GENERATED by scripts/pull_devy_headshots.py (%s)" % today.isoformat(),
          "// ESPN college-football athlete ids (headshot: a.espncdn.com/i/headshots/college-football/players/full/<id>.png)",
          "// + ESPN team ids per combine_data.js school (logo: a.espncdn.com/i/teamlogos/ncaa/500/<tid>.png).",
          "window.DEVY_HEADSHOTS = " + json.dumps({n: found[n] for n in sorted(found)}, separators=(",", ":"), ensure_ascii=False) + ";",
          "window.COLLEGE_TEAM_IDS = " + json.dumps(dict(sorted(team_ids.items())), separators=(",", ":"), ensure_ascii=False) + ";", ""]
    if a.dry_run:
        log("DRY RUN")
        return 0
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, separators=(",", ":"))
    before = digest(OUT)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(js))
    if digest(OUT) == before:
        log("%s unchanged" % OUT)
        return 0
    log("wrote %s" % OUT)
    if a.no_bump:
        return 0
    with open(INDEX_HTML, encoding="utf-8", newline="") as f:
        html = f.read()
    m = re.search(r"devy_headshots\.js\?v=([\w.-]+)", html)
    if m:
        cur = m.group(1)
        m2 = re.match(r"%shs(\d+)$" % re.escape(today.isoformat()), cur)
        new = today.isoformat() if not cur.startswith(today.isoformat()) else today.isoformat() + "hs%d" % ((int(m2.group(1)) + 1) if m2 else 2)
        if new != cur:
            with open(INDEX_HTML, "w", encoding="utf-8", newline="") as f:
                f.write(html.replace("devy_headshots.js?v=" + cur, "devy_headshots.js?v=" + new))
            log("bumped devy_headshots.js ?v= %s -> %s" % (cur, new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
