"""Sync the CURRENT-season team in data/active_team_history.js to d.js.

Why (2026-09-24): ACTIVE_TEAM_HISTORY is built by build_active_team_history.py
from nflverse roster CSVs + d.js, but that full rebuild hasn't run since the
offseason (and the CSVs are no longer on disk), so every player who moved
after it ran still had his old team open-ended (y2=2099) — e.g. Kaleb Johnson
PIT 2025-2099 while d.js (daily roster refresh) has him in Green Bay. Team-by-
year lookups (_getTeamForPlayerYear, Compare splits, Fantasy Game team pools)
read this file first.

This touches ONLY the 2026 end of each history — past seasons are left
exactly as they are. Per d.js fantasy player (QB/RB/WR/TE/FB), mirroring what
the full builder would emit:
  - d.js team is a real team and differs from the range covering 2026:
      range started 2026  -> retarget it to the d.js team
      range started <2026 -> close it at 2025, append {d.js team, 2026, 2099}
  - no range covers 2026 (history ends 2025 or earlier) -> append 2026-2099
  - d.js team is FA / blank -> cap an open-ended range at 2025 (a history
    that only had a 2026 range is removed)
  - no history at all -> {d.js team, 2026, 2099}
Adjacent same-team ranges are folded back together.

Edits the file line by line (the builder's parse/emit drops the double-quoted
apostrophe keys like "Ja'Marr Chase"), so untouched lines stay byte-identical.
Dry run by default; --write rewrites the file. Safe to re-run any time.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_active_team_history import D_JS, OUT_FILE, TEAM_FULL, FANTASY_POS, load_d_players  # noqa: E402

SEASON = 2026
OPEN = 2099
VALID = set(TEAM_FULL.values())
LINE_RE = re.compile(r"""^(\s*)(?:'((?:[^'\\]|\\.)+)'|"([^"]+)"):\s*\[(.*)\](,?)\s*$""")
RANGE_RE = re.compile(r"\{t:'((?:[^'\\]|\\.)+)',y1:(\d+),y2:(\d+)\}")


def parse_lines(text):
    """[(line, name|None, ranges|None)] for every line of the file."""
    out = []
    for ln in text.split('\n'):
        m = LINE_RE.match(ln)
        if not m:
            out.append([ln, None, None])
            continue
        name = (m.group(2) or '').replace("\\'", "'") or m.group(3)
        ranges = [{'t': r.group(1).replace("\\'", "'"), 'y1': int(r.group(2)), 'y2': int(r.group(3))}
                  for r in RANGE_RE.finditer(m.group(4))]
        out.append([ln, name, ranges])
    return out


def fmt_line(name, ranges, comma):
    key = f'"{name}"' if "'" in name else f"'{name}'"
    body = ','.join(f"{{t:'{r['t']}',y1:{r['y1']},y2:{r['y2']}}}" for r in ranges)
    return f'    {key}: [{body}]{comma}'


def fold(ranges):
    out = []
    for r in ranges:
        if out and out[-1]['t'] == r['t'] and out[-1]['y2'] == r['y1'] - 1:
            out[-1]['y2'] = r['y2']
        else:
            out.append(dict(r))
    return out


def sync_one(ranges, team):
    """Return the corrected range list (new list) for one player."""
    ranges = [dict(r) for r in ranges]
    cur = [r for r in ranges if r['y1'] <= SEASON <= r['y2']]
    if team not in VALID:
        # free agent / unknown: nothing open-ended into 2026
        for r in cur:
            if r['y1'] < SEASON:
                r['y2'] = SEASON - 1
        return [r for r in ranges if r['y1'] < SEASON]
    if len(cur) == 1 and cur[0]['t'] == team:
        cur[0]['y2'] = OPEN
        return fold(ranges)
    kept = []
    for r in ranges:
        if r['y1'] >= SEASON:
            continue                       # 2026+ ranges are rebuilt below
        if r['y2'] >= SEASON:
            r['y2'] = SEASON - 1           # close the stale open-ended team
        kept.append(r)
    kept.append({'t': team, 'y1': SEASON, 'y2': OPEN})
    return fold(kept)


def main():
    write = '--write' in sys.argv
    d_players = load_d_players(D_JS.read_text(encoding='utf-8'))
    text = OUT_FILE.read_text(encoding='utf-8')
    rows = parse_lines(text)
    idx = {r[1]: i for i, r in enumerate(rows) if r[1]}
    fmt = lambda rs: ' -> '.join(f"{r['t']} {r['y1']}-{r['y2']}" for r in rs) if rs else '(removed)'

    moved, added = [], []
    for name, info in d_players.items():
        if info['s'] not in FANTASY_POS:
            continue
        team = info['t'] or ''
        if name not in idx:
            if team in VALID:
                added.append((name, [{'t': team, 'y1': SEASON, 'y2': OPEN}]))
            continue
        row = rows[idx[name]]
        new = sync_one(row[2], team)
        if new != row[2]:
            moved.append((name, row[2], new))
            row[2] = new
            row[0] = None                  # re-emit

    print(f'{len(idx)} entries; {len(moved)} corrected, {len(added)} added')
    for name, old, new in sorted(moved):
        print(f'  {name}: {fmt(old[-2:])}  =>  {fmt(new[-2:])}')
    for name, rs in sorted(added):
        print(f'  + {name}: {fmt(rs)}')
    if not write:
        print('(dry run - pass --write to rewrite data/active_team_history.js)')
        return
    if not moved and not added:
        return

    # entries = (name, ranges) in file order, new ones inserted alphabetically
    entries = [(r[1], r[2], r[0]) for r in rows if r[1] and r[2]]
    for name, rs in added:
        pos = next((i for i, e in enumerate(entries) if e[0].lower() > name.lower()), len(entries))
        entries.insert(pos, (name, rs, None))
    head = [r[0] for r in rows[:next(i for i, r in enumerate(rows) if r[1])]]
    tail = [r[0] for r in rows[max(i for i, r in enumerate(rows) if r[1]) + 1:]]
    body = []
    for i, (name, rs, orig) in enumerate(entries):
        comma = ',' if i < len(entries) - 1 else ''
        if orig is not None and orig.rstrip().endswith(',') == bool(comma):
            body.append(orig)
        else:
            body.append(fmt_line(name, rs, comma))
    OUT_FILE.write_text('\n'.join(head + body + tail), encoding='utf-8')
    print(f'Wrote {OUT_FILE}')


if __name__ == '__main__':
    main()
