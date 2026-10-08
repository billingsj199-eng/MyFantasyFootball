"""pull_devy_birthdays.py - birth dates for devy prospects missing from LEGEND_BIRTH_YEARS.

The JM model's age and breakout-age components (~15% of the grade) read exact birth
dates from data/legend_birth_years.js (window.LEGEND_BIRTH_YEARS, "Name":"YYYY-MM-DD")
plus Firestore prospect_bio `birth` overrides. ESPN and CFBD rosters no longer expose
dates of birth (checked 2026-09-30), so this tries, per missing player, in order:

  1. Wikidata: entity search (description mentions football) -> P569 date of birth
  2. Wikipedia: article search -> infobox {{birth date and age|Y|M|D}} in the wikitext
  3. On3 database search (on3.com/db/search/?searchText=) -> list entry dateOfBirth,
     matched on name + position (+ school when several share the name)
  (Sports Reference 403s scripts as of 2026-09-30 - not used. Jack can also enter a
   birth date in the admin bio editor, which lands in Firestore prospect_bio.birth.)

Found dates are appended to data/legend_birth_years.js, the lookups bundle is rebuilt
(scripts/bundle_lookups.py) and data/_bundle_lookups.js ?v= bumped; misses are
cached in scripts/devy_birthdays_cache.json for 30 days so the weekly job only
retries occasionally. Devy universe = refresh_devy_stats.load_combine().

    python scripts/pull_devy_birthdays.py [--dry-run] [--retry-misses] [--no-bump]
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import refresh_devy_stats as rds  # noqa: E402

LBY = "data/legend_birth_years.js"
CACHE = "scripts/devy_birthdays_cache.json"
INDEX_HTML = "index.html"
UA = {"User-Agent": "MyFantasyFootball devy audit (billingsj199@gmail.com)"}
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"}
YEAR_LO, YEAR_HI = 1998, 2010

# On3 lists schools as "Oklahoma State Cowboys"; COMBINE_DATA uses "Oklahoma St." etc.
_SCHOOL_WORDS = {"st.": "state", "(fl)": "", "miami (fl)": "miami"}


def log(*a):
    print(*a, flush=True)


def _plausible(iso):
    return bool(iso) and YEAR_LO <= int(iso[:4]) <= YEAR_HI


def _norm_name(s):
    s = (s or "").lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)


def _school_key(s):
    s = (s or "").lower().replace("(fl)", "").replace("st.", "state")
    return re.sub(r"[^a-z]", "", s)


def load_births():
    txt = open(LBY, encoding="utf-8").read()
    return {m.group(1): m.group(2) for m in re.finditer(r'"([^"]+)"\s*:\s*"(\d{4}-\d{1,2}-\d{1,2})"', txt)}, txt


def bio_births():
    out = {}
    base = "https://firestore.googleapis.com/v1/projects/jackb933-website/databases/(default)/documents/prospect_bio"
    pt = None
    try:
        while True:
            j = requests.get(base, params={"pageSize": 300, **({"pageToken": pt} if pt else {})}, timeout=40).json()
            for d in j.get("documents", []):
                f = d.get("fields", {})
                if "birth" in f:
                    out[d["name"].rsplit("/", 1)[1].replace("%20", " ")] = list(f["birth"].values())[0]
            pt = j.get("nextPageToken")
            if not pt:
                break
    except requests.RequestException:
        pass
    return out


def wikidata(name, pos):
    try:
        s = requests.get("https://www.wikidata.org/w/api.php", params={"action": "wbsearchentities", "search": name, "language": "en", "format": "json", "limit": 6}, headers=UA, timeout=30).json()
    except (requests.RequestException, ValueError):
        return None
    for e in s.get("search", []):
        d = (e.get("description") or "").lower()
        if "football" not in d:
            continue
        try:
            ent = requests.get("https://www.wikidata.org/wiki/Special:EntityData/%s.json" % e["id"], headers=UA, timeout=30).json()["entities"][e["id"]]
        except (requests.RequestException, ValueError, KeyError):
            continue
        cl = ent.get("claims", {}).get("P569") or []
        for c in cl:
            t = c.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if t.get("time") and t.get("precision", 11) >= 11:
                m = re.match(r"\+(\d{4})-(\d{2})-(\d{2})", t["time"])
                if m and _plausible(m.group(1)):
                    return "%s-%s-%s" % m.groups(), "wikidata:" + e["id"]
    return None


def wikipedia(name, pos):
    """Article search (name + football) -> wikitext infobox birth date template."""
    api = "https://en.wikipedia.org/w/api.php"
    try:
        s = requests.get(api, params={"action": "query", "list": "search", "srsearch": "%s American football" % name, "srlimit": 5, "format": "json"}, headers=UA, timeout=30).json()
    except (requests.RequestException, ValueError):
        return None
    want = _norm_name(name)
    for hit in s.get("query", {}).get("search", []):
        title = hit.get("title", "")
        if _norm_name(re.sub(r"\s*\(.*?\)\s*$", "", title)) != want:
            continue
        try:
            j = requests.get(api, params={"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main", "titles": title, "format": "json", "formatversion": 2}, headers=UA, timeout=30).json()
            wt = j["query"]["pages"][0]["revisions"][0]["slots"]["main"]["content"]
        except (requests.RequestException, ValueError, KeyError, IndexError):
            continue
        if "football" not in wt.lower():
            continue
        m = re.search(r"\{\{\s*[Bb]irth[ _]date(?:[ _]and[ _]age)?\s*\|\s*(?:mf=\w+\s*\|\s*|df=\w+\s*\|\s*)?(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})", wt)
        if m:
            iso = "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
            if _plausible(iso):
                return iso, "wikipedia:" + title.replace(" ", "_")
    return None


def on3(name, pos, school):
    """on3.com/db/search/?searchText=<name> ships its result list (with dateOfBirth,
    position, current organization) in __NEXT_DATA__; no bot wall as of 2026-09-30."""
    try:
        r = requests.get("https://www.on3.com/db/search/", params={"searchText": name}, headers=BROWSER_UA, timeout=30)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        return None
    try:
        lst = json.loads(m.group(1))["props"]["pageProps"]["searchData"]["list"]
    except (ValueError, KeyError, TypeError):
        return None
    want = _norm_name(name)
    sk = _school_key(school)
    cands = []
    for it in lst:
        if _norm_name(it.get("name")) != want:
            continue
        dob = it.get("dateOfBirth") or ""
        if not _plausible(dob[:10]):
            continue
        p = it.get("positionAbbreviation") or ""
        org = _school_key((it.get("currentOrganization") or {}).get("name"))
        score = (2 if (sk and sk in org) else 0) + (1 if p == pos else 0)
        cands.append((score, dob[:10], it.get("slug")))
    if not cands:
        return None
    cands.sort(reverse=True)
    score, dob, slug = cands[0]
    if score == 0 and len(cands) > 1:
        return None  # ambiguous: several same-name people, none at this school/position
    return dob, "on3:" + str(slug)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--retry-misses", action="store_true")
    ap.add_argument("--no-bump", action="store_true")
    a = ap.parse_args()
    today = datetime.date.today()
    rds._CUR_SEASON = today.year if today.month >= 8 else today.year - 1
    cb = rds.load_combine()
    devy = {n: e for n, e in cb.items() if e.get("devy")}
    births, txt = load_births()
    bio = bio_births()
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    missing = [n for n in sorted(devy) if n not in births and n not in bio]
    log("devy %d | with birthday %d | missing %d" % (len(devy), len(devy) - len(missing), len(missing)))

    found = {}
    for n in missing:
        c = cache.get(n)
        if c and not a.retry_misses and c.get("miss") and (today - datetime.date.fromisoformat(c["miss"])).days < 30:
            continue
        pos, school = devy[n].get("pos"), devy[n].get("school")
        hit = wikidata(n, pos)
        time.sleep(0.5)
        if not hit:
            hit = wikipedia(n, pos)
            time.sleep(0.5)
        if not hit:
            hit = on3(n, pos, school)
            time.sleep(0.7)
        if hit:
            found[n] = hit
            cache[n] = {"birth": hit[0], "src": hit[1], "at": today.isoformat()}
            log("  %-26s %s  (%s)" % (n, hit[0], hit[1]))
        else:
            cache[n] = {"miss": today.isoformat()}
            log("  %-26s not found" % n)
    log("found %d / %d" % (len(found), len(missing)))
    if a.dry_run:
        return 0
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=1, sort_keys=True)
    if not found:
        return 0
    add = ",".join('"%s":"%s"' % (n.replace('"', '\\"'), v[0]) for n, v in sorted(found.items()))
    assert txt.rstrip().endswith("};")
    new_txt = txt.rstrip()[:-2] + "," + add + "};\n"
    with open(LBY, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_txt)
    log("appended %d birth dates to %s" % (len(found), LBY))
    # legend_birth_years.js ships inside data/_bundle_lookups.js (scripts/bundle_lookups.py) -
    # rebuild the bundle and bump ITS tag (index.html has no tag for the source file).
    import subprocess
    r = subprocess.run([sys.executable, os.path.join("scripts", "bundle_lookups.py")], capture_output=True, text=True, timeout=300)
    log("bundle_lookups.py exit %d %s" % (r.returncode, (r.stdout or "").strip().splitlines()[-1:] ))
    if a.no_bump or r.returncode != 0:
        return 0 if r.returncode == 0 else 1
    with open(INDEX_HTML, encoding="utf-8", newline="") as f:
        html = f.read()
    m = re.search(r"_bundle_lookups\.js\?v=([\w.-]+)", html)
    if m:
        cur = m.group(1)
        m2 = re.match(r"%s-bd(\d+)$" % re.escape(today.isoformat()), cur)
        new = today.isoformat() + "-bd" if not cur.startswith(today.isoformat() + "-bd") else today.isoformat() + "-bd%d" % ((int(m2.group(1)) + 1) if m2 else 2)
        if new != cur:
            with open(INDEX_HTML, "w", encoding="utf-8", newline="") as f:
                f.write(html.replace("_bundle_lookups.js?v=" + cur, "_bundle_lookups.js?v=" + new))
            log("bumped _bundle_lookups.js ?v= %s -> %s" % (cur, new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
