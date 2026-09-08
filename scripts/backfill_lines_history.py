"""Seed data/lines_history_2026.json from the git history of
data/betting_lines_2026.json (one commit per betting pull since 2026-07-21).

Re-runnable: rebuilds the file from scratch so the "opened" point of every
line is the first commit that carried it. Only weeks present in the CURRENT
JSON are recorded (old commits carried preseason-game lines under wrong
weeks before the kickoff validation landed). Run from the repo root:

    python scripts/backfill_lines_history.py
"""
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pull_betting_lines as pbl  # noqa: E402

ROOT = pbl.ROOT
REL = 'data/betting_lines_2026.json'


def git(*args):
    return subprocess.run(['git', '-C', ROOT] + list(args), capture_output=True,
                          text=True, encoding='utf-8', errors='replace').stdout


def main():
    current = json.load(open(pbl.JSON_FILE, encoding='utf-8'))
    weeks_now = set(str(w) for w in (current.get('weeklyProps') or {}))
    log = git('log', '--reverse', '--format=%H|%cI', '--', REL).strip().splitlines()
    print(f'{len(log)} commits touch {REL}; recording weeks {sorted(weeks_now)} + season')
    hist = {'updated': None, 'weeks': {}, 'season': {}}
    total = 0
    for line in log:
        sha, iso = line.split('|', 1)
        body = git('show', f'{sha}:{REL}')
        if not body.strip():
            continue
        try:
            data = json.loads(body)
        except ValueError:
            print(f'  {sha[:7]} unparseable — skipped')
            continue
        stamp = pbl._hist_stamp(datetime.datetime.fromisoformat(iso))
        added = pbl.record_lines_into(hist, data, stamp, weeks_only=weeks_now)
        total += added
        if added:
            print(f'  {sha[:7]} {stamp}: +{added}')
    # the working-copy file may be newer than the last commit
    added = pbl.record_lines_into(hist, current, pbl._hist_stamp(), weeks_only=weeks_now)
    total += added
    size = pbl.save_lines_history(hist)
    n_players = sum(len(v) for v in hist['weeks'].values()) + len(hist['season'])
    print(f'wrote {os.path.relpath(pbl.HISTORY_FILE, ROOT)}: {total} points, '
          f'{n_players} player entries, {size // 1024} KB')


if __name__ == '__main__':
    main()
