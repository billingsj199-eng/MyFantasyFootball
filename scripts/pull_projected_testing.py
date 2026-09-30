"""pull_projected_testing.py - harvest published pre-draft forty times for the next class.

Source today: Stick to the Model's big board (server-rendered rows carry
data-f40 / data-ht / data-wt for the prospects they have numbers for; 16 skill
players on 2026-09-30). NFL Draft Buzz publishes far more projected forties but
sits behind a bot check, so Jack pastes those by hand into the same CSV.

Merges into Site Rankings/projected_testing_<yr>.csv (name, forty, vert, broad,
source): rows already in the CSV with a non-"Stick to the Model" source are
manual and always win; harvested rows are added/refreshed with source
"Stick to the Model". scripts/apply_projected_testing.py then pushes them onto
the site (fortyProj -> projected RAS).

    python scripts/pull_projected_testing.py [--year 2027] [--dry-run]
"""
import argparse
import csv
import datetime
import html
import os
import re
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
BOARD = "https://sticktothemodel.com/draft/prospect-overview/big-board"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"}
SRC = "Stick to the Model"
SKILL = {"QB", "RB", "HB", "WR", "WRS", "TE"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    today = datetime.date.today()
    year = a.year or (today.year + 1 if today.month >= 5 else today.year)
    csv_path = os.path.join("Site Rankings", "projected_testing_%d.csv" % year)

    r = requests.get(BOARD, headers=UA, timeout=40)
    r.raise_for_status()
    rows = re.findall(r'<tr data-rank="(\d+)" data-pos="([A-Z]+)"([^>]*)>.*?aria-label="Select (.+?) to compare"', r.text, re.S)
    harvested = {}
    for rank, pos, attrs, name in rows:
        if pos not in SKILL:
            continue
        at = dict(re.findall(r'data-(\w+)="([^"]*)"', attrs))
        f40 = at.get("f40")
        if not f40:
            continue
        try:
            f40 = float(f40)
        except ValueError:
            continue
        if not (4.2 <= f40 <= 5.4):
            continue
        harvested[html.unescape(name).strip()] = f40
    print("%s: %d skill prospects with a forty" % (SRC, len(harvested)))

    existing = []
    if os.path.exists(csv_path):
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            existing = list(csv.DictReader(f))
    manual = {r["name"].strip(): r for r in existing if (r.get("source") or "").strip() and (r.get("source") or "").strip() != SRC}
    out = dict(manual)
    added = updated = 0
    for name, f40 in harvested.items():
        if name in manual:
            continue                      # Jack's number wins
        prev = next((r for r in existing if r["name"].strip() == name), None)
        if prev is None:
            added += 1
        elif str(prev.get("forty")) != str(f40):
            updated += 1
        out[name] = {"name": name, "forty": f40, "vert": prev.get("vert", "") if prev else "", "broad": prev.get("broad", "") if prev else "", "source": SRC}
    # keep old rows from other harvested sources that are no longer on the board (e.g. DraftBuzz manual)
    for r in existing:
        out.setdefault(r["name"].strip(), r)
    print("csv: %d rows (%d manual, %d harvested; +%d new, %d changed)" % (len(out), len(manual), len(out) - len(manual), added, updated))
    if a.dry_run:
        return 0
    os.makedirs("Site Rankings", exist_ok=True)
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "forty", "vert", "broad", "source"])
        w.writeheader()
        for name in sorted(out):
            row = out[name]
            w.writerow({k: row.get(k, "") for k in ["name", "forty", "vert", "broad", "source"]})
    print("wrote", csv_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
