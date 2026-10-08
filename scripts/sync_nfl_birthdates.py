"""sync_nfl_birthdates.py - birth dates for DRAFTED / signed players from NFL data.

Rule (Jack, 2026-09-30): a player who is in the NFL gets his birth date from NFL
data, not from recruiting sites or wikis. Source = nflverse `players.csv`
(github.com/nflverse/nflverse-data, release `players`), which mirrors the league's
own player file (gsis ids, birth_date, draft year/pick, rookie season).

Why this exists: the bundled data/legend_birth_years.js had hand/LLM-entered dates
for the 2020-2026 classes that were wrong for ~80% of the players checked (mean
error half a year, 33 off by a year or more), and several hundred graded players
had no date under the name the model uses. The JM age and breakout-age components
read these dates, so the backtest itself was running on bad ages.

What it does
  * Universe: every COMBINE_DATA entry with yr >= 2017 that is not devy, plus any
    name passed in --names-json (the headless model dump, optional).
  * Match to nflverse on normalized name + (draft year AND pick)  -> certain, or
    name + rookie season within [yr, yr+1] + skill position       -> accepted,
    never on name alone (two Lamar Jacksons, two Josh Allens...).
  * Corrects a bundled date that differs, adds one that is missing. Devy players
    are never touched (scripts/pull_devy_birthdays.py owns those: Firestore bio ->
    Wikidata -> Wikipedia -> On3).
  * Rebuilds the lookups bundle and bumps its ?v= only when something changed.

    python scripts/sync_nfl_birthdates.py [--dry-run] [--no-bump] [--names-json path]
"""
import argparse
import collections
import csv
import datetime
import io
import json
import os
import re
import subprocess
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

LBY = "data/legend_birth_years.js"
COMBINE_JS = "data/combine_data.js"
INDEX_HTML = "index.html"
PLAYERS_URL = "https://github.com/nflverse/nflverse-data/releases/download/players/players.csv"
SKILL = {"QB", "RB", "WR", "TE", "FB", "HB"}
NICK = {"mitch": "mitchell", "mike": "michael", "chris": "christopher", "josh": "joshua", "matt": "matthew",
        "zach": "zachary", "zack": "zachary", "cam": "cameron", "ben": "benjamin", "will": "william",
        "nick": "nicholas", "joe": "joseph", "dan": "daniel", "sam": "samuel", "tony": "anthony",
        "drew": "andrew", "jake": "jacob", "alex": "alexander", "pat": "patrick", "gabe": "gabriel",
        "ken": "kenneth", "kenny": "kenneth"}


def log(*a):
    print(*a, flush=True)


def nz(s):
    s = (s or "").lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)


def num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def norm_date(d):
    y, m, dd = d.split("-")
    return "%04d-%02d-%02d" % (int(y), int(m), int(dd))


def load_nflverse():
    r = requests.get(PLAYERS_URL, timeout=180)
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8", errors="replace"))))
    idx = collections.defaultdict(list)
    for x in rows:
        if not re.match(r"\d{4}-\d{2}-\d{2}", x.get("birth_date") or ""):
            continue
        first = x.get("football_name") or x.get("common_first_name") or x.get("first_name") or ""
        for k in {nz(x.get("display_name")), nz(first + " " + (x.get("last_name") or "")),
                  nz((x.get("first_name") or "") + " " + (x.get("last_name") or ""))}:
            if k:
                idx[k].append(x)
    return idx, len(rows)


def find(idx, name, yr, pick, pos=None):
    cands = list(idx.get(nz(name), []))
    if not cands:
        parts = name.split()
        f = parts[0].lower().strip(".") if parts else ""
        if f in NICK:
            cands = list(idx.get(nz(NICK[f] + " " + " ".join(parts[1:])), []))
    # same name + draft year + pick = the same person, whatever position is listed
    if isinstance(pick, int):
        for x in cands:
            if num(x.get("draft_year")) == yr and num(x.get("draft_pick")) == pick:
                return x
    ok = []
    for x in cands:
        ry, dy, p = num(x.get("rookie_season")), num(x.get("draft_year")), x.get("position")
        yr_ok = (dy == yr) or (ry is not None and 0 <= ry - yr <= 1)
        if not yr_ok or p not in SKILL:
            continue
        if pos and p != pos and not ({p, pos} <= {"RB", "FB", "HB"}):
            continue
        ok.append(x)
    return ok[0] if len(ok) == 1 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-bump", action="store_true")
    ap.add_argument("--names-json", help="optional [[name,pos,draftYr,pick],...] from the headless model dump")
    a = ap.parse_args()
    today = datetime.date.today()

    idx, n_rows = load_nflverse()
    log("nflverse players: %d rows" % n_rows)
    raw = open(COMBINE_JS, encoding="utf-8").read()
    cb = json.loads(raw.split("=", 1)[1].strip().rstrip(";"))
    universe = {}
    for n, e in cb.items():
        if e.get("devy") or (e.get("yr") or 0) < 2017:
            continue
        d = e.get("draft")
        universe[n] = (e.get("yr"), d if isinstance(d, int) else num(d), e.get("pos"))
    if a.names_json and os.path.exists(a.names_json):
        for row in json.load(open(a.names_json)):
            n, pos, yr, pick = row[0], row[1], row[2], row[3]
            if yr and 2017 <= yr <= today.year and n not in universe:
                universe[n] = (yr, pick if isinstance(pick, int) else None, pos)

    txt = open(LBY, encoding="utf-8").read()
    legend = {m.group(1): m.group(2) for m in re.finditer(r'"([^"]+)"\s*:\s*"(\d{4}-\d{1,2}-\d{1,2})"', txt)}
    fixes, adds, same = [], [], 0
    for n, (yr, pick, pos) in sorted(universe.items()):
        x = find(idx, n, yr, pick, pos)
        if not x:
            continue
        b = x["birth_date"][:10]
        cur = legend.get(n)
        if cur is None and x.get("position") not in SKILL:
            continue   # linemen / defenders: the model never grades them, keep the bundle small
        if cur is None:
            adds.append((n, b))
        elif norm_date(cur) != b:
            fixes.append((n, norm_date(cur), b))
        else:
            same += 1
    log("drafted/signed universe %d | matched: same %d, corrected %d, added %d" % (len(universe), same, len(fixes), len(adds)))
    for n, o, b in fixes[:60]:
        log("  FIX %-26s %s -> %s" % (n, o, b))
    for n, b in adds[:60]:
        log("  ADD %-26s %s" % (n, b))
    if a.dry_run or not (fixes or adds):
        return 0

    for n, o, b in fixes:
        m = re.search(r'"%s":"(\d{4}-\d{1,2}-\d{1,2})"' % re.escape(n), txt)
        txt = txt[:m.start(1)] + b + txt[m.end(1):]
    assert txt.rstrip().endswith("};")
    if adds:
        txt = txt.rstrip()[:-2] + "," + ",".join('"%s":"%s"' % (n.replace('"', '\\"'), b) for n, b in adds) + "};\n"
    with open(LBY, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
    r = subprocess.run([sys.executable, os.path.join("scripts", "bundle_lookups.py")], capture_output=True, text=True, timeout=300)
    log("bundle_lookups.py exit %d" % r.returncode)
    if a.no_bump or r.returncode != 0:
        return 0 if r.returncode == 0 else 1
    with open(INDEX_HTML, encoding="utf-8", newline="") as f:
        html = f.read()
    m = re.search(r"_bundle_lookups\.js\?v=([\w.-]+)", html)
    if m:
        cur = m.group(1)
        base = today.isoformat() + "-bd"
        m2 = re.match(re.escape(base) + r"(\d+)$", cur)
        new = base if not cur.startswith(base) else base + str((int(m2.group(1)) + 1) if m2 else 2)
        if new != cur:
            with open(INDEX_HTML, "w", encoding="utf-8", newline="") as f:
                f.write(html.replace("_bundle_lookups.js?v=" + cur, "_bundle_lookups.js?v=" + new))
            log("bumped _bundle_lookups.js ?v= %s -> %s" % (cur, new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
