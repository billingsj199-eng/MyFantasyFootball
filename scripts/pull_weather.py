"""Game-day weather -> data/weather_2026.js (+ .json mirror).

Feeds the Start/Sit cards' WEATHER box and the player card's WEEKLY tab.
Two keyless public sources:

  * ESPN scoreboard (site.api.espn.com) — every game's kickoff (UTC), venue,
    roof (venue.indoor) and AccuWeather's headline condition + temperature.
  * Open-Meteo forecast (api.open-meteo.com, no key) — wind / gusts / precip
    probability / condition at the kickoff hour for outdoor stadiums we have
    coordinates for (STADIUMS below). 16-day horizon; games further out keep
    ESPN's headline only.

Indoor venues (domes + retractables ESPN reports as indoor) are tagged
indoor:true and carry no forecast — the site prints DOME for them.

Covers the current week and the next one; earlier weeks already in the file
are kept as-is (last forecast before kickoff). Non-fatal per game.

Output shape:
  window.WEATHER_2026 = {updated, season, weeks: {wk: {HOME_ABBR: game}}}
  game = {away, home, kick, venue, city, indoor, cond, temp, wind, gust, pop, src}
    temp °F · wind/gust mph · pop = precip probability % · src 'meteo' | 'espn'
    Team abbreviations follow the site (WAS not WSH).

Usage: python scripts/pull_weather.py [--dry] [--week N] [--all]
"""
import datetime as dt
import json
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'weather_2026.js')
OUT_JSON = os.path.join(ROOT, 'data', 'weather_2026.json')
SCOREBOARD = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'
METEO = 'https://api.open-meteo.com/v1/forecast'
# ESPN's scoreboard 403s browser-looking UAs from scripts (2026-08-28 onward) but
# still answers a plain curl UA — keep it curl-like.
UA = {'User-Agent': 'curl/8.4.0', 'Accept': '*/*'}

# ESPN -> site abbreviations (only the ones that differ).
ABBR_FIX = {'WSH': 'WAS', 'JAC': 'JAX', 'LA': 'LAR', 'OAK': 'LV', 'SD': 'LAC'}

# Home-stadium coordinates (2026 season). Shared venues listed per team.
STADIUMS = {
    'ARI': (33.5276, -112.2626), 'ATL': (33.7554, -84.4010), 'BAL': (39.2780, -76.6227),
    'BUF': (42.7738, -78.7870), 'CAR': (35.2258, -80.8528), 'CHI': (41.8623, -87.6167),
    'CIN': (39.0955, -84.5161), 'CLE': (41.5061, -81.6995), 'DAL': (32.7473, -97.0945),
    'DEN': (39.7439, -105.0201), 'DET': (42.3400, -83.0456), 'GB': (44.5013, -88.0622),
    'HOU': (29.6847, -95.4107), 'IND': (39.7601, -86.1639), 'JAX': (30.3239, -81.6373),
    'KC': (39.0489, -94.4839), 'LAC': (33.9535, -118.3392), 'LAR': (33.9535, -118.3392),
    'LV': (36.0909, -115.1833), 'MIA': (25.9580, -80.2389), 'MIN': (44.9735, -93.2575),
    'NE': (42.0909, -71.2643), 'NO': (29.9511, -90.0812), 'NYG': (40.8135, -74.0745),
    'NYJ': (40.8135, -74.0745), 'PHI': (39.9008, -75.1675), 'PIT': (40.4468, -80.0158),
    'SF': (37.4033, -121.9694), 'SEA': (47.5952, -122.3316), 'TB': (27.9759, -82.5033),
    'TEN': (36.1665, -86.7713), 'WAS': (38.9076, -76.8645),
}

# Expected home city per team (ESPN venue.address.city). When a "home" game is
# somewhere else (Melbourne, London, Frankfurt, a neutral site) the stadium
# coordinates above are wrong — geocode ESPN's venue city instead.
HOME_CITY = {
    'ARI': 'glendale', 'ATL': 'atlanta', 'BAL': 'baltimore', 'BUF': 'orchard park',
    'CAR': 'charlotte', 'CHI': 'chicago', 'CIN': 'cincinnati', 'CLE': 'cleveland',
    'DAL': 'arlington', 'DEN': 'denver', 'DET': 'detroit', 'GB': 'green bay',
    'HOU': 'houston', 'IND': 'indianapolis', 'JAX': 'jacksonville', 'KC': 'kansas city',
    'LAC': 'inglewood', 'LAR': 'inglewood', 'LV': 'las vegas', 'MIA': 'miami gardens',
    'MIN': 'minneapolis', 'NE': 'foxborough', 'NO': 'new orleans', 'NYG': 'east rutherford',
    'NYJ': 'east rutherford', 'PHI': 'philadelphia', 'PIT': 'pittsburgh', 'SF': 'santa clara',
    'SEA': 'seattle', 'TB': 'tampa', 'TEN': 'nashville', 'WAS': 'landover',
}
GEOCODE = 'https://geocoding-api.open-meteo.com/v1/search'
_geo_cache = {}


def geocode(city):
    """City centroid via Open-Meteo's geocoder (no key). None when unknown."""
    if not city:
        return None
    key = city.strip().lower()
    if key in _geo_cache:
        return _geo_cache[key]
    try:
        r = requests.get(GEOCODE, params={'name': city, 'count': 1, 'language': 'en', 'format': 'json'},
                         headers=UA, timeout=30)
        r.raise_for_status()
        res = (r.json().get('results') or [None])[0]
        _geo_cache[key] = (res['latitude'], res['longitude']) if res else None
    except Exception as e:  # noqa: BLE001
        print(f'  !! geocode {city}: {e}')
        _geo_cache[key] = None
    return _geo_cache[key]


def coords_for(game):
    """Stadium coords when the game is at the home team's own stadium, else the
    venue city's centroid (international / neutral sites), else None."""
    home = game['home']
    city = (game.get('city') or '').strip().lower()
    exp = HOME_CITY.get(home)
    if home in STADIUMS and (not city or not exp or city == exp):
        return STADIUMS[home]
    return geocode(game.get('city'))


# WMO weather codes -> short label.
WMO = {
    0: 'Clear', 1: 'Mostly clear', 2: 'Partly cloudy', 3: 'Overcast',
    45: 'Fog', 48: 'Fog', 51: 'Drizzle', 53: 'Drizzle', 55: 'Drizzle',
    56: 'Freezing drizzle', 57: 'Freezing drizzle',
    61: 'Light rain', 63: 'Rain', 65: 'Heavy rain', 66: 'Freezing rain', 67: 'Freezing rain',
    71: 'Light snow', 73: 'Snow', 75: 'Heavy snow', 77: 'Snow grains',
    80: 'Showers', 81: 'Showers', 82: 'Heavy showers', 85: 'Snow showers', 86: 'Snow showers',
    95: 'Thunderstorm', 96: 'Thunderstorm', 99: 'Thunderstorm',
}


def espn_week(season, week):
    r = requests.get(SCOREBOARD, params={'seasontype': 2, 'week': week, 'dates': season},
                     headers=UA, timeout=60)
    r.raise_for_status()
    return r.json()


def espn_current():
    r = requests.get(SCOREBOARD, headers=UA, timeout=60)
    r.raise_for_status()
    j = r.json()
    season = (j.get('season') or {}).get('year')
    stype = (j.get('season') or {}).get('type')
    week = (j.get('week') or {}).get('number')
    return season, stype, week


def parse_games(j):
    games = {}
    for ev in j.get('events') or []:
        try:
            comp = ev['competitions'][0]
            home = away = None
            for c in comp.get('competitors') or []:
                ab = (c.get('team') or {}).get('abbreviation') or ''
                ab = ABBR_FIX.get(ab, ab)
                if c.get('homeAway') == 'home':
                    home = ab
                else:
                    away = ab
            if not home or not away:
                continue
            venue = comp.get('venue') or {}
            addr = venue.get('address') or {}
            w = ev.get('weather') or comp.get('weather') or {}
            games[home] = {
                'away': away, 'home': home,
                'kick': ev.get('date'),
                'venue': venue.get('fullName'),
                'city': addr.get('city'),
                'indoor': bool(venue.get('indoor')),
                'cond': w.get('displayValue'),
                'temp': w.get('temperature'),
                'wind': None, 'gust': None, 'pop': None,
                'src': 'espn' if w else None,
            }
        except Exception as e:  # noqa: BLE001 — one bad event never kills the pull
            print(f'  !! skipped event: {e}')
    return games


def kickoff_utc(iso):
    # ESPN dates look like 2026-09-13T17:00Z
    s = iso.replace('Z', '+00:00')
    return dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc)


def meteo(lat, lon, kick):
    """Hourly Open-Meteo forecast at the kickoff hour; None past the horizon."""
    now = dt.datetime.now(dt.timezone.utc)
    if kick < now - dt.timedelta(hours=4) or kick > now + dt.timedelta(days=15, hours=20):
        return None
    r = requests.get(METEO, params={
        'latitude': lat, 'longitude': lon,
        'hourly': 'temperature_2m,precipitation_probability,wind_speed_10m,wind_gusts_10m,weather_code',
        'temperature_unit': 'fahrenheit', 'wind_speed_unit': 'mph',
        'timezone': 'UTC', 'forecast_days': 16,
    }, headers=UA, timeout=60)
    r.raise_for_status()
    h = r.json().get('hourly') or {}
    times = h.get('time') or []
    key = kick.strftime('%Y-%m-%dT%H:00')
    if key not in times:
        return None
    i = times.index(key)
    pick = lambda k: (h.get(k) or [None])[i] if i < len(h.get(k) or []) else None  # noqa: E731
    code = pick('weather_code')
    return {
        'temp': None if pick('temperature_2m') is None else int(round(pick('temperature_2m'))),
        'wind': None if pick('wind_speed_10m') is None else int(round(pick('wind_speed_10m'))),
        'gust': None if pick('wind_gusts_10m') is None else int(round(pick('wind_gusts_10m'))),
        'pop': None if pick('precipitation_probability') is None else int(round(pick('precipitation_probability'))),
        'cond': WMO.get(int(code)) if code is not None else None,
    }


def enrich(games):
    for home, g in games.items():
        if g['indoor'] or not g.get('kick'):
            continue
        coords = coords_for(g)
        if not coords:
            continue  # unknown venue: ESPN headline only
        try:
            m = meteo(coords[0], coords[1], kickoff_utc(g['kick']))
        except Exception as e:  # noqa: BLE001
            print(f'  !! open-meteo {g["away"]}@{home}: {e}')
            m = None
        if not m:
            continue
        for k in ('temp', 'wind', 'gust', 'pop'):
            if m.get(k) is not None:
                g[k] = m[k]
        if m.get('cond'):
            g['cond'] = m['cond']
        g['src'] = 'meteo'


def load_existing():
    try:
        with open(OUT_JSON, encoding='utf-8') as f:
            j = json.load(f)
        return j if isinstance(j, dict) and isinstance(j.get('weeks'), dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def main():
    dry = '--dry' in sys.argv
    season, stype, cur = espn_current()
    if '--week' in sys.argv:
        cur = int(sys.argv[sys.argv.index('--week') + 1])
    if not season or not cur:
        sys.exit(f'!! bad ESPN state: season={season} type={stype} week={cur}')
    if stype != 2 and '--week' not in sys.argv:
        print(f'ESPN says season type {stype} (not regular season) — defaulting to week 1')
        cur = 1
    weeks = list(range(1, 19)) if '--all' in sys.argv else [w for w in (cur, cur + 1) if 1 <= w <= 18]

    prev = load_existing()
    out_weeks = dict(prev.get('weeks') or {})
    n_games = n_meteo = 0
    for wk in weeks:
        try:
            games = parse_games(espn_week(season, wk))
        except Exception as e:  # noqa: BLE001
            print(f'!! ESPN week {wk} failed ({e}) — previous rows kept')
            continue
        enrich(games)
        out_weeks[str(wk)] = games
        n_games += len(games)
        n_meteo += sum(1 for g in games.values() if g['src'] == 'meteo')
        print(f'week {wk}: {len(games)} games, '
              f'{sum(1 for g in games.values() if g["indoor"])} indoor, '
              f'{sum(1 for g in games.values() if g["src"] == "meteo")} with Open-Meteo forecast')
        for g in sorted(games.values(), key=lambda x: x['kick'] or ''):
            tag = 'DOME' if g['indoor'] else (
                f'{g["cond"] or "?"} {g["temp"] if g["temp"] is not None else "?"}F'
                + (f' wind {g["wind"]} (g {g["gust"]}) pop {g["pop"]}%' if g['src'] == 'meteo' else ''))
            print(f'   {g["away"]:>3} @ {g["home"]:<3} {g["kick"]}  {tag}')

    payload = {
        'updated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
        'season': season,
        'src': 'espn-scoreboard + open-meteo',
        'weeks': out_weeks,
    }
    if dry:
        print(f'--dry: {n_games} games parsed ({n_meteo} forecasts); nothing written')
        return
    body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write('// Auto-generated by scripts/pull_weather.py — do not hand-edit.\n'
                '// Game weather per week (ESPN scoreboard roof/headline + Open-Meteo kickoff-hour forecast).\n'
                '// weeks[wk][HOME_ABBR] = {away, home, kick, venue, city, indoor, cond, temp, wind, gust, pop, src}\n'
                'window.WEATHER_2026 = ' + body + ';\n')
    with open(OUT_JSON, 'w', encoding='utf-8', newline='\n') as f:
        f.write(body)
    print(f'data/weather_2026.js written ({len(body):,} bytes, {n_games} games this run)')


if __name__ == '__main__':
    main()
