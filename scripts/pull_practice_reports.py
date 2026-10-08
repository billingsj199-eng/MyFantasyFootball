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

DAY LOG (2026-10-08, Jack: "add the practice report to the weekly card ... showing
each day"): data/practice_days_2026.js = window.PRACTICE_DAYS_2026 = {updated,
weeks: {wk: {games: {TM: 'YYYY-MM-DD'}, players: {name: {tm, pos, inj, gs,
d: {'YYYY-MM-DD': 'DNP'|'LP'|'FP'}}}}}} for QB/RB/WR/TE/K, last two weeks. The
page only shows the LATEST practice day, so each pull files that status under
the team's latest report day already released: report days are the three days
ending two days before a Sunday / Monday game (Wed-Thu-Fri, Thu-Fri-Sat) and the
three days ending the day before any other game (Thursday game = Mon-Tue-Wed),
a day counting as released from 16:00 ET. Game dates come from the page's own
date headings. A later pull the same day overwrites that day, so the evening
pulls settle it.

  python scripts/pull_practice_reports.py --backfill-git   # rebuild this week's
      day log from the git history of data/practice_2026.js (commit time = pull time)
"""
import html as _html
import json
import os
import re
import sys
import subprocess
from datetime import date, datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'practice_2026.js')
OUT_JSON = os.path.join(ROOT, 'data', 'practice_2026.json')
DAYS_OUT = os.path.join(ROOT, 'data', 'practice_days_2026.js')
DAYS_POS = ('QB', 'RB', 'WR', 'TE', 'K')
MONTHS = {m: i + 1 for i, m in enumerate(('JANUARY', 'FEBRUARY', 'MARCH', 'APRIL', 'MAY', 'JUNE', 'JULY',
                                         'AUGUST', 'SEPTEMBER', 'OCTOBER', 'NOVEMBER', 'DECEMBER'))}
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


def _et(now_utc):
    """US Eastern wall clock for a UTC datetime (DST: 2nd Sunday of March 07:00 UTC to 1st Sunday of November 06:00 UTC)."""
    y = now_utc.year
    mar = datetime(y, 3, 8, 7, tzinfo=timezone.utc)
    mar += timedelta(days=(6 - mar.weekday()) % 7)
    nov = datetime(y, 11, 1, 6, tzinfo=timezone.utc)
    nov += timedelta(days=(6 - nov.weekday()) % 7)
    off = -4 if mar <= now_utc < nov else -5
    return (now_utc + timedelta(hours=off)).replace(tzinfo=None)


def game_dates(html, now_et):
    """{TM: date} from the page's date headings ("SUNDAY, OCTOBER 11TH") that precede each matchup's team blocks."""
    out, cur = {}, None
    pat = (r'(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY), ([A-Z]+) (\d{1,2})(?:ST|ND|RD|TH)'
           r'|<div class="d3-o-section-sub-title"><span>([^<]+)</span>')
    for m in re.finditer(pat, html):
        if m.group(1):
            mo = MONTHS.get(m.group(1))
            if not mo:
                continue
            y = now_et.year
            if mo <= 2 and now_et.month >= 8:
                y += 1
            elif mo >= 8 and now_et.month <= 2:
                y -= 1
            cur = date(y, mo, int(m.group(2)))
        elif cur is not None:
            abbr = NICK_TO_ABBR.get(_text(m.group(3)))
            if abbr:
                out[abbr] = cur
    return out


def report_days(g):
    """The three injury-report days for a game on date g (Sun/Mon game: Wed-Thu-Fri / Thu-Fri-Sat; else the 3 days before)."""
    back = (4, 3, 2) if g.weekday() in (6, 0) else (3, 2, 1)
    return [g - timedelta(days=b) for b in back]


def latest_report_day(g, now_et):
    """Newest of the team's report days already released at now_et (a day counts from 16:00 ET), else None."""
    today = now_et.date()
    best = None
    for d in report_days(g):
        if d < today or (d == today and now_et.hour >= 16):
            best = d
    return best


def read_days():
    if not os.path.exists(DAYS_OUT):
        return {'weeks': {}}
    txt = open(DAYS_OUT, encoding='utf-8').read()
    try:
        return json.loads(txt[txt.index('{'):txt.rstrip().rstrip(';').rindex('}') + 1])
    except Exception:
        return {'weeks': {}}


def apply_days(store, players, games, week, now_et):
    """File each listed skill player's practice status under his team's latest released report day."""
    if not week:
        return 0
    W = store.setdefault('weeks', {}).setdefault(str(week), {'games': {}, 'players': {}})
    for tm, g in games.items():
        W['games'][tm] = g.isoformat()
    n = 0
    for name, v in players.items():
        if v.get('pos') not in DAYS_POS or not v.get('pr'):
            continue
        g = games.get(v.get('tm'))
        day = latest_report_day(g, now_et) if g else None
        if not day:
            continue
        rec = W['players'].setdefault(name, {'tm': v['tm'], 'pos': v['pos'], 'inj': '', 'gs': '', 'd': {}})
        rec['tm'], rec['pos'] = v['tm'], v['pos']
        if v.get('inj'):
            rec['inj'] = v['inj']
        rec['gs'] = v.get('gs', '')
        rec['d'][day.isoformat()] = v['pr']
        n += 1
    keep = sorted(store['weeks'], key=int)[-2:]
    store['weeks'] = {k: store['weeks'][k] for k in keep}
    return n


def write_days(store, stamp):
    store['updated'] = stamp
    body = ('// Auto-generated by scripts/pull_practice_reports.py - do not hand-edit.\n'
            '// Official NFL injury report, day by day: weeks[wk].players[name].d = {date: DNP|LP|FP}\n'
            '// filed under the team\'s report day; games[TM] = game date. QB/RB/WR/TE/K, last two weeks.\n'
            'window.PRACTICE_DAYS_2026 = ' + json.dumps(store, separators=(',', ':'), ensure_ascii=False, sort_keys=True) + ';\n')
    old = open(DAYS_OUT, encoding='utf-8').read() if os.path.exists(DAYS_OUT) else ''
    if body != old:
        open(DAYS_OUT, 'w', encoding='utf-8', newline='\n').write(body)
    return body != old


def backfill_git(games, week, store):
    """Replay this week's commits of data/practice_2026.js (commit time stands in for the pull time)."""
    if not games:
        return 0
    first = min(report_days(g)[0] for g in games.values()) - timedelta(days=1)
    log = subprocess.run(['git', 'log', '--reverse', '--format=%H %ct', '--since=' + first.isoformat(), '--', 'data/practice_2026.js'],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    n = 0
    for h, ct in zip(log[0::2], log[1::2]):
        txt = subprocess.run(['git', 'show', h + ':data/practice_2026.js'], cwd=ROOT, capture_output=True,
                             text=True, encoding='utf-8').stdout
        try:
            pay = json.loads(txt[txt.index('{'):txt.rstrip().rstrip(';').rindex('}') + 1])
        except Exception:
            continue
        if int(pay.get('week') or 0) != int(week):
            continue
        apply_days(store, pay.get('players') or {}, games, week, _et(datetime.fromtimestamp(int(ct), timezone.utc)))
        n += 1
    return n


def _text(html):
    # unescape entities: the page writes apostrophes as &#x27; ("D&#x27;Andre Swift")
    return _html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))).strip()


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
    # Layout check = team section headers, not row count: the page rolls to the
    # new week Tue/Wed with only the Thursday teams posted (19 rows on W5 Wed
    # morning), and a partial current-week report beats last week's (the engine
    # ignores a report whose week != the sim week anyway).
    teams = sum(1 for n in re.findall(r'<div class="d3-o-section-sub-title"><span>([^<]*)', r.text)
                if n.strip() in NICK_TO_ABBR)
    if teams < 20:
        sys.exit(f'!! only {teams} team sections on {URL} — page layout changed? nothing written')
    if not players:
        print(f'no reports posted yet ({teams} teams listed) — nothing written')
        return
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
    now_utc = datetime.now(timezone.utc)
    now_et = _et(now_utc)
    games = game_dates(r.text, now_et)
    store = read_days()
    if '--backfill-git' in sys.argv:
        print(f'backfill: replayed {backfill_git(games, week, store)} commits of data/practice_2026.js for week {week}')
    filed = apply_days(store, players, games, week, now_et)
    wk = store.get('weeks', {}).get(str(week), {})
    print(f'day log: {len(games)} game dates, {filed} statuses filed this pull, '
          f'{len(wk.get("players", {}))} skill players logged for week {week}')
    if dry:
        return
    if write_days(store, now_utc.isoformat()):
        print('data/practice_days_2026.js written (changed)')
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
