"""save_nflmdd_csv.py - write the Mock+ CSVs pull_draft_boards.py reads.

Input: the pipe text scripts/nflmdd_extract_chrome.js builds in Jack's Chrome
(P|period|n_mocks|picks + M|pick|name|pos|pct lines, D|depth|updated + B|rank|name|pos|school lines).
Output (git-excluded, 10-day life in pull_draft_boards.py):
    Site Rankings/mock_draft_<yr>.csv   period,n_mocks,picks,pick,name,pos,pct,pulled
    Site Rankings/big_board_<yr>.csv    rank,name,pos,school,depth,updated,pulled

Refuses to write (exit 2) when the text looks signed out or cut short:
every mock window must reach pick 64 with >= 10 skill rows, and the big board
must run past 300 with >= 60 skill rows - a signed-out Chrome shows round 1 /
top 100 only, and a short CSV would beat nothing but still look fresh.

Usage: python scripts/save_nflmdd_csv.py <raw.txt> [--year 2027]
"""
import argparse
import csv
import datetime
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERIODS = ["1_week", "2_weeks", "1_month", "all_time"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("--year", type=int)
    a = ap.parse_args()
    today = datetime.date.today()
    year = a.year or (today.year + 1 if today.month >= 5 else today.year)

    mock, board = [], []
    hdr, dep, upd = None, "0", ""
    with open(a.raw, encoding="utf-8") as f:
        for ln in f:
            p = ln.rstrip("\r\n").split("|")
            if p[0] == "P" and len(p) == 4:
                hdr = p[1:]
            elif p[0] == "M" and len(p) == 5 and hdr:
                mock.append(hdr + p[1:])
            elif p[0] == "D" and len(p) == 3:
                dep, upd = p[1], p[2]
            elif p[0] == "B" and len(p) == 5:
                board.append(p[1:] + [dep, upd])

    bad = []
    for per in PERIODS:
        rows = [r for r in mock if r[0] == per]
        picks = max((int(r[2]) for r in rows), default=0)
        if picks < 64 or len(rows) < 10:
            bad.append("mock %s: %d picks, %d skill rows" % (per, picks, len(rows)))
    depth = max((int(r[4]) for r in board), default=0)
    if depth <= 300 or len(board) < 60:
        bad.append("big board: %d deep, %d skill rows" % (depth, len(board)))
    if bad:
        print("REFUSED (signed out or cut short):\n  " + "\n  ".join(bad))
        return 2

    sr = os.path.join(ROOT, "Site Rankings")
    with open(os.path.join(sr, "mock_draft_%d.csv" % year), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["period", "n_mocks", "picks", "pick", "name", "pos", "pct", "pulled"])
        for per, n, picks, pick, name, pos, pct in mock:
            w.writerow([per, n, picks, pick, name, pos, pct, today.isoformat()])
    with open(os.path.join(sr, "big_board_%d.csv" % year), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "name", "pos", "school", "depth", "updated", "pulled"])
        for rank, name, pos, school, dep, upd in board:
            w.writerow([rank, name, pos, school, dep, upd, today.isoformat()])
    for per in PERIODS:
        rows = [r for r in mock if r[0] == per]
        print("mock %-8s %s mocks, %s picks, %d skill" % (per, rows[0][1], rows[0][2], len(rows)))
    print("big board %d deep, %d skill through 300 (updated %s)" % (depth, len(board), board[0][5]))
    print("wrote Site Rankings/mock_draft_%d.csv + big_board_%d.csv (pulled %s)" % (year, year, today))
    return 0


if __name__ == "__main__":
    sys.exit(main())
