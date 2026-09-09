"""Official NFL injury report (practice participation + game status) ->
data/practice_2026.js / .json.

Source: https://www.nfl.com/injuries/ — the league-wide report for the current
week, plain HTML (no JS rendering needed). Per team it lists every player on
the report with Injuries, the LATEST practice-day participation
("Did Not Participate In Practice" / "Limited Participation in Practice" /
"Full Participation in Practice") and the Game Status (Out / Doubtful /
Questionable / blank). This is the one public feed that carries practice
status, which Sleeper's designations lack — a Questionable player who did
not practice is a different bet from one who practiced in full.

  python scripts/pull_practice_reports.py        # write data/practice_2026.js(.json)
  python scripts/pull_practice_reports.py --dry  # print summary, write nothing

Consumers: sim_lab/refresh_data.py copies the JSON into sim_lab/data/
sim_practice.js (window.SIM_PRACTICE_2026) for the engine's in-season
injury layer (Questionable + DNP -> x0.75, NFL Out/Doubtful when Sleeper
lags). Names are the NFL's display names; the engine matches on its own
norm() (suffix/punctuation-insensitive).

Output: window.PRACTICE_2026 = {updated, week, src, players: {name: {tm, pos,
inj, pr: 'DNP'|'LP'|'FP'|'', gs: 'Out'|'Doubtful'|'Questionable'|''}}}
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'practice_2026.js')
OUT_JSON = os.path.join(ROOT, 'data', 'practice_2026.json')
URL = 'https://www.nfl.com/injuries/'
STATE_URL = 'https://api.sleeper.app/v1/state/nfl'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/128.0 Safari/537.36'}

NICK_TO_ABBR = {
    'Cardinals': 'ARI', 'Falcons': 'ATL', 'Ravens': 'BAL', 'Bills': 'BUF', 'Panthers': 'CAR',
    'Bears': 'CHI', 'Bengals': 'CIN', 'Browns': 'CLE', 'Cowboys': 'DAL', 'Broncos': 'DEN',
    'Lions': 'DET', 'Packers': 'GB', 'Texans': 'HOU', 'Colts': 'IND', 'Jaguars': 'JAX',
    'Chiefs': 'KC', 'Raiders': 'LV', 'Chargers': 'LAC', 'Rams': 'LAR', 'Dolphins': 'MIA',
    'Vikings': 'MIN', 'Patriots': 'NE', 'Saints': 'NO', 'Giants': 'NYG', 'Jets': 'NYJ',
    'Eagles': 'PHI', 'Steelers': 'PIT', '49ers': 'SF', 'Seahawks': 'SEA', 'Buccaneers': 'TB',
    'Titans': 'TEN', 'Commanders': 'WAS',
}
PRACTICE = [
    ('did not participate', 'DNP'),
    ('limited participation', 'LP'),
    ('full participation', 'FP'),
]


def _text(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html)).strip()


def parse(html):
    """{name: {tm, pos, inj, pr, gs}} from the league page."""
    players = {}
    # Each team block: <span>Nickname</span> ... <table ...> rows </table>
    blocks = re.split(r'<div class="d3-o-section-sub-title"><span>', html)
    for blk in blocks[1:]:
        nick = _text(blk[:blk.find('</span>')])
        abbr = NICK_TO_ABBR.get(nick)
        if not abbr:
            continue
        tbl = blk.find('<table')
        tend = blk.find('</table>', tbl)
        if tbl < 0 or tend < 0:
            continue
        rows = re.findall(r'<tr>(.*?)</tr>', blk[tbl:tend], re.S)
        for row in rows:
            cells = [_text(c) for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
            if len(cells) < 5:
                continue
            name, pos, inj, pr_txt, gs = cells[:5]
            if not name:
                continue
            pr = ''
            low = pr_txt.lower()
            for needle, code in PRACTICE:
                if needle in low:
                    pr = code
                    break
            gs = gs.strip()
            if gs and gs not in ('Out', 'Doubtful', 'Questionable'):
                gs = gs.split()[0]
            players[name] = {'tm': abbr, 'pos': pos, 'inj': inj, 'pr': pr, 'gs': gs}
    return players


def main():
    dry = '--dry' in sys.argv
    r = requests.get(URL, headers=UA, timeout=45)
    r.raise_for_status()
    players = parse(r.text)
    if len(players) < 20:
        sys.exit(f'!! only {len(players)} rows parsed from {URL} — page layout changed? nothing written')
    week = None
    try:
        st = requests.get(STATE_URL, timeout=20).json()
        week = int(st.get('week') or 0) if st.get('season_type') == 'regular' else 1
    except Exception:
        pass
    m = re.search(r'/injuries/league/(\d{4})/reg(\d+)', r.text)
    if m:
        week = int(m.group(2))
    skill = {n: v for n, v in players.items() if v['pos'] in ('QB', 'RB', 'WR', 'TE', 'K')}
    dnp_q = [n for n, v in skill.items() if v['gs'] == 'Questionable' and v['pr'] == 'DNP']
    outs = [n for n, v in skill.items() if v['gs'] in ('Out', 'Doubtful')]
    print(f'{len(players)} players on the report (week {week}); {len(skill)} skill players; '
          f'{len(outs)} Out/Doubtful; {len(dnp_q)} Questionable+DNP: {", ".join(dnp_q[:8])}')
    if dry:
        return
    payload = {
        'updated': datetime.now(timezone.utc).isoformat(),
        'week': week,
        'src': 'nfl.com/injuries',
        'players': players,
    }
    body = ('// Auto-generated by scripts/pull_practice_reports.py — do not hand-edit.\n'
            '// Official NFL injury report: latest practice participation (pr: DNP/LP/FP) + game\n'
            '// status (gs: Out/Doubtful/Questionable) per player, keyed by NFL display name.\n'
            'window.PRACTICE_2026 = ' + json.dumps(payload, separators=(',', ':'), ensure_ascii=False) + ';\n')
    old = open(OUT, encoding='utf-8').read() if os.path.exists(OUT) else ''
    open(OUT, 'w', encoding='utf-8', newline='\n').write(body)
    open(OUT_JSON, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(payload, separators=(',', ':'), ensure_ascii=False))
    print(f'data/practice_2026.js written ({len(body):,} bytes, {"changed" if body != old else "no change"})')


if __name__ == '__main__':
    main()
