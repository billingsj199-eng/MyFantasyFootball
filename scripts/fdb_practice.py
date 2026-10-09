"""FootballDB injury report parser: the official practice report with EVERY day kept.

https://www.footballdb.com/transactions/injuries.html (current week) and
...injuries.html?yr=YYYY&wk=N&type=reg (archive back to 2016) list, per team, each
player's participation on every report day (Wed 10/07: DNP | Thu 10/08: Limited | ...)
plus the game status. nfl.com/injuries only shows the latest day, so this is the
source for the card's day-by-day PRACTICE REPORT and for the trajectory play rates
(sim_lab/build_practice_trajectory.py).

parse(html, season) -> [{team, name, pos, inj, days: [(label, 'YYYY-MM-DD', 'DNP'|'LP'|'FP'|None)], gs}]
  gs = 'Out' | 'Doubtful' | 'Questionable' | '' ; a day not reported ('--') is None.
"""
import html as _html
import re
from datetime import date

URL = 'https://www.footballdb.com/transactions/injuries.html'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/128.0 Safari/537.36'}

TEAM_ABBR = {
    'Arizona Cardinals': 'ARI', 'Atlanta Falcons': 'ATL', 'Baltimore Ravens': 'BAL', 'Buffalo Bills': 'BUF',
    'Carolina Panthers': 'CAR', 'Chicago Bears': 'CHI', 'Cincinnati Bengals': 'CIN', 'Cleveland Browns': 'CLE',
    'Dallas Cowboys': 'DAL', 'Denver Broncos': 'DEN', 'Detroit Lions': 'DET', 'Green Bay Packers': 'GB',
    'Houston Texans': 'HOU', 'Indianapolis Colts': 'IND', 'Jacksonville Jaguars': 'JAX', 'Kansas City Chiefs': 'KC',
    'Las Vegas Raiders': 'LV', 'Oakland Raiders': 'LV', 'Los Angeles Chargers': 'LAC', 'San Diego Chargers': 'LAC',
    'Los Angeles Rams': 'LAR', 'St. Louis Rams': 'LAR', 'Miami Dolphins': 'MIA', 'Minnesota Vikings': 'MIN',
    'New England Patriots': 'NE', 'New Orleans Saints': 'NO', 'New York Giants': 'NYG', 'New York Jets': 'NYJ',
    'Philadelphia Eagles': 'PHI', 'Pittsburgh Steelers': 'PIT', 'San Francisco 49ers': 'SF', 'Seattle Seahawks': 'SEA',
    'Tampa Bay Buccaneers': 'TB', 'Tennessee Titans': 'TEN', 'Washington Commanders': 'WAS',
    'Washington Football Team': 'WAS', 'Washington Redskins': 'WAS',
}
_LVL = {'dnp': 'DNP', 'limited': 'LP', 'full': 'FP'}


def _txt(s):
    return _html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s))).strip()


def _day(label, season):
    """'Wed 10/07' -> ('Wed', 'YYYY-MM-DD'); January/February belong to season + 1."""
    m = re.match(r'([A-Za-z]{3})\s+(\d{1,2})/(\d{1,2})', label.strip())
    if not m:
        return None
    mo, dd = int(m.group(2)), int(m.group(3))
    y = season + 1 if mo <= 2 else season
    try:
        return m.group(1), date(y, mo, dd).isoformat()
    except ValueError:
        return None


def parse(html, season):
    out = []
    parts = re.split(r'<div class="teamsectlabel"><b>', html)
    for part in parts[1:]:
        team = _txt(part[:part.find('</b>')])
        head = re.findall(r'<div class="th center w15">([^<]*)</div>', part[:part.find('<div class="tr">') if '<div class="tr">' in part else len(part)])
        days = [_day(h, season) for h in head]
        if not days or any(d is None for d in days):
            continue
        for row in re.split(r'<div class="tr">', part)[1:]:
            m = re.search(r'title="([^"]+?) Stats">', row)
            pm = re.search(r'</a>\s*\(([A-Z]{1,3})\)', row)
            if not m:
                continue
            cells = re.findall(r'<div class="td center w15 d-none d-md-table-cell">([^<]*)</div>', row)
            inj = re.search(r'<div class="td w15 d-none d-md-table-cell">([^<]*)</div>', row)
            gsm = re.search(r'<div class="td w20 d-none d-md-table-cell">(.*?)</div>', row, re.S)
            gs_txt = _txt(gsm.group(1)) if gsm else ''
            gs = next((g for g in ('Questionable', 'Doubtful', 'Out') if re.search(r'\b' + g + r'\b', gs_txt)), '')
            lv = [_LVL.get(_txt(c).lower()) for c in cells[:len(days)]]
            out.append({
                'team': team, 'tm': TEAM_ABBR.get(team, ''), 'name': _html.unescape(m.group(1)),
                'pos': pm.group(1) if pm else '', 'inj': _txt(inj.group(1)) if inj else '',
                'days': [(d[0], d[1], lv[i] if i < len(lv) else None) for i, d in enumerate(days)],
                'gs': gs,
            })
    return out


def week_of(html):
    m = re.search(r'<title>NFL Injury Report - Week (\d+)', html)
    return int(m.group(1)) if m else None
