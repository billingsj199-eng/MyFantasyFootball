#!/usr/bin/env python3
"""In-season K/DST data refresh — orchestrates the four K/DST pullers and
bumps the ?v= cache-bust tags for whichever data files actually changed.

Keeps the kicker/D-ST card features honest through the season:
  pull_kicker_history.py  -> data/kicker_history.js   (career table + model FG%)
  pull_kicker_weekly.py   -> data/kicker_weekly.js    (game logs + L4 PPG)
  pull_dst_history.py     -> data/dst_history.js + data/dst_weekly.js
  pull_kicker_splits.py   -> data/kicker_splits.js    (FG distance splits card)

Each puller auto-discovers new nflverse season files (2026 rows appear as the
season starts), so this needs no per-season edits. A puller failing (nflverse
outage, ESPN change) skips just its files — the rest still refresh.

?v= bumps follow the repo collision rule: the CURRENT value is read from
disk right before bumping; today's date is used, with a "k2" suffix if some
other job already claimed today's date for that tag.

Run from the project root (the Tuesday Task Scheduler job does):
  python scripts/refresh_kdst_data.py
Exit code 0 = ran (even if some pullers failed); 1 = nothing could run.
"""
import datetime
import hashlib
import io
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

PULLS = [
    ("pull_kicker_history.py", ["data/kicker_history.js"]),
    ("pull_kicker_weekly.py", ["data/kicker_weekly.js"]),
    ("pull_dst_history.py", ["data/dst_history.js", "data/dst_weekly.js"]),
    ("pull_kicker_splits.py", ["data/kicker_splits.js"]),
]


def digest(path):
    # Normalize CRLF: git checkouts carry \r\n while the pullers write \n —
    # comparing raw bytes would flag every file as "changed" on every run.
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()
    except OSError:
        return None


def bump_tag(html, fname):
    """Set the ?v= for data/<fname> to today (suffix if today is taken)."""
    today = datetime.date.today().isoformat()
    pat = re.compile(r"(%s\?v=)([\w.-]+)" % re.escape(fname))
    m = pat.search(html)
    if not m:
        print("  WARN: no ?v= tag found for", fname)
        return html
    cur = m.group(2)
    new = today if cur != today and not cur.startswith(today) else today + "k2"
    if cur == new:
        return html
    print("  bump %s ?v= %s -> %s" % (fname, cur, new))
    return pat.sub(lambda mm: mm.group(1) + new, html)


def main():
    before = {f: digest(f) for _, files in PULLS for f in files}
    ran = 0
    changed = []
    for script, files in PULLS:
        try:
            r = subprocess.run([sys.executable, os.path.join("scripts", script)],
                               capture_output=True, text=True, timeout=900)
            tail = (r.stdout or "").strip().splitlines()
            print("[%s] exit %d%s" % (script, r.returncode,
                                      (" | " + tail[-1]) if tail else ""))
            if r.returncode != 0:
                print((r.stderr or "").strip()[-500:])
                continue
            ran += 1
            for f in files:
                if digest(f) != before.get(f):
                    changed.append(f)
        except Exception as e:
            print("[%s] FAILED: %s" % (script, e))

    if not ran:
        print("no puller succeeded")
        return 1
    if not changed:
        print("no data changes — index.html untouched")
        return 0

    idx = io.open("index.html", encoding="utf-8", newline="").read()
    for f in changed:
        idx = bump_tag(idx, os.path.basename(f))
    io.open("index.html", "w", encoding="utf-8", newline="").write(idx)
    print("changed:", ", ".join(changed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
