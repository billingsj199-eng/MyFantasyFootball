"""
Pull exact birthdates, team histories, height, weight, draft round, college,
and jersey number from nflfastR roster data.

Run: python build_birth_years.py
Requirements: pip install pandas

Updates index.html and data/player_team_history.js
"""

import pandas as pd
import json
import re
import os
import math

ROSTER_URL = "https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_{}.csv"

TEAM_ABBR_MAP = {
    'ARI':'ARI','ATL':'ATL','BAL':'BAL','BUF':'BUF','CAR':'CAR','CHI':'CHI',
    'CIN':'CIN','CLE':'CLE','DAL':'DAL','DEN':'DEN','DET':'DET','GB':'GB',
    'HOU':'HOU','IND':'IND','JAX':'JAX','KC':'KC','LA':'LAR','LAC':'LAC',
    'LAR':'LAR','LV':'LV','MIA':'MIA','MIN':'MIN','NE':'NE','NO':'NO',
    'NYG':'NYG','NYJ':'NYJ','PHI':'PHI','PIT':'PIT','SEA':'SEA','SF':'SF',
    'TB':'TB','TEN':'TEN','WAS':'WAS',
    'OAK':'LV','SD':'LAC','STL':'LAR','SL':'LAR',
}
TEAM_ABBR_FULL = {
    'Arizona Cardinals':'ARI','Atlanta Falcons':'ATL','Baltimore Ravens':'BAL','Buffalo Bills':'BUF',
    'Carolina Panthers':'CAR','Chicago Bears':'CHI','Cincinnati Bengals':'CIN','Cleveland Browns':'CLE',
    'Dallas Cowboys':'DAL','Denver Broncos':'DEN','Detroit Lions':'DET','Green Bay Packers':'GB',
    'Houston Texans':'HOU','Indianapolis Colts':'IND','Jacksonville Jaguars':'JAX','Kansas City Chiefs':'KC',
    'Los Angeles Chargers':'LAC','Los Angeles Rams':'LAR','Las Vegas Raiders':'LV','Miami Dolphins':'MIA',
    'Minnesota Vikings':'MIN','New England Patriots':'NE','New Orleans Saints':'NO','New York Giants':'NYG',
    'New York Jets':'NYJ','Philadelphia Eagles':'PHI','Pittsburgh Steelers':'PIT','San Francisco 49ers':'SF',
    'Seattle Seahawks':'SEA','Tampa Bay Buccaneers':'TB','Tennessee Titans':'TEN','Washington Commanders':'WAS',
    'St. Louis Rams':'LAR','San Diego Chargers':'LAC','Oakland Raiders':'LV',
    'Houston Oilers':'TEN','Washington Redskins':'WAS','Baltimore Colts':'IND',
    'Los Angeles Raiders':'LV','Boston Patriots':'NE','St. Louis Cardinals':'ARI','Phoenix Cardinals':'ARI',
}

def safe_str(val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ''
    return str(val).strip()

def safe_int(val):
    try:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return None
        return int(val)
    except (ValueError, TypeError):
        return None

def normalize_team(team):
    t = safe_str(team).upper().strip()
    return TEAM_ABBR_MAP.get(t, t)

def main():
    hp_path = 'data/hp.js'
    if not os.path.exists(hp_path):
        print(f"Error: {hp_path} not found. Run from repo root.")
        return
    with open(hp_path, encoding='utf-8') as f:
        hp = json.loads(f.read().strip().replace('const HP = ', '').rstrip(';'))

    ldb_path = 'data/ldb.js'
    with open(ldb_path, encoding='utf-8') as f:
        ldb = json.loads(f.read().strip().replace('const LDB=', '').rstrip(';'))

    pth_path = 'data/player_team_history.js'
    with open(pth_path, encoding='utf-8') as f:
        pth_text = f.read().strip()
    existing_pth_names = set(re.findall(r"'([^']+)':\s*\[", pth_text))

    target_names = set()
    hp_info = {}
    for p in hp:
        target_names.add(p['n'])
        hp_info[p['n']] = p
    for p in ldb:
        target_names.add(p['n'])

    print(f"Looking up data for {len(target_names)} players")

    all_rosters = []
    for year in range(1999, 2025):
        print(f"  Downloading {year} rosters...")
        try:
            df = pd.read_csv(ROSTER_URL.format(year), low_memory=False)
            all_rosters.append(df)
        except Exception as e:
            print(f"    Error: {e}")

    if not all_rosters:
        print("No roster data downloaded!")
        return

    rosters = pd.concat(all_rosters, ignore_index=True)
    rosters['full_name'] = rosters['full_name'].apply(safe_str)
    rosters = rosters[rosters['full_name'] != '']
    print(f"Total roster rows: {len(rosters):,}")

    name_variants = {}
    for name in target_names:
        variants = set()
        variants.add(name.lower())
        variants.add(name.replace(' Jr.', '').replace(' Sr.', '').replace(' III', '').replace(' II', '').strip().lower())
        variants.add(re.sub(r'([A-Z])\.([A-Z])', r'\1\2', name).lower())
        clean = re.sub(r"[.'']", '', name).lower()
        variants.add(clean)
        for v in variants:
            if v:
                name_variants[v] = name

    # =====================
    # 1. BIRTHDATES + BIO
    # =====================
    print("\n=== Building birthdates + bio data ===")
    # Store full birthdate strings "YYYY-MM-DD" for exact age calculation
    birth_dates = {}  # name -> "YYYY-MM-DD" string
    birth_years = {}  # name -> year int (fallback)
    bio_data = {}

    for _, row in rosters.iterrows():
        lookup = safe_str(row['full_name']).lower()
        if lookup not in name_variants:
            continue
        target = name_variants[lookup]

        # Birthdate
        if target not in birth_dates:
            try:
                bd = pd.to_datetime(row.get('birth_date'))
                if pd.notna(bd):
                    birth_dates[target] = bd.strftime('%Y-%m-%d')
                    birth_years[target] = bd.year
            except:
                pass

        # Bio data
        if target not in bio_data:
            bio_data[target] = {}
        bio = bio_data[target]
        h = safe_int(row.get('height'))
        if h and h > 60 and 'height' not in bio: bio['height'] = h
        w = safe_int(row.get('weight'))
        if w and w > 100 and 'weight' not in bio: bio['weight'] = w
        dr = safe_int(row.get('draft_number'))
        if dr and 'draft_number' not in bio: bio['draft_number'] = dr
        c = safe_str(row.get('college'))
        if c and 'college' not in bio: bio['college'] = c
        j = safe_int(row.get('jersey_number'))
        if j is not None and 'jersey' not in bio: bio['jersey'] = j

    exact_count = len(birth_dates)
    print(f"Matched {exact_count} players with exact birthdates")
    print(f"Matched {len(bio_data)} players with bio data")

    # Fallback: birth year estimate for players not in roster data
    for p in hp:
        if p['n'] not in birth_dates and p['n'] not in birth_years:
            m = re.match(r'(\d{4})', p.get('_yrs', ''))
            if m:
                birth_years[p['n']] = int(m.group(1)) - 22
    for p in ldb:
        if p['n'] not in birth_dates and p['n'] not in birth_years:
            m = re.match(r'(\d{4})', p.get('yrs', ''))
            if m:
                birth_years[p['n']] = int(m.group(1)) - 22

    total = len(set(list(birth_dates.keys()) + list(birth_years.keys())))
    est_count = total - exact_count
    print(f"Total: {total} ({exact_count} exact birthdates, {est_count} year-only estimates)")

    for name in ['Tom Brady', 'Ben Watson', 'Rudi Johnson', 'Jerry Rice']:
        if name in birth_dates:
            print(f"  {name}: {birth_dates[name]} (exact)")
        elif name in birth_years:
            print(f"  {name}: {birth_years[name]} (year only)")

    # =====================
    # 2. TEAM HISTORIES
    # =====================
    print("\n=== Building team histories ===")
    roster_lookup = {}
    for _, row in rosters.iterrows():
        lookup = safe_str(row['full_name']).lower()
        if lookup not in name_variants: continue
        target = name_variants[lookup]
        season = row.get('season')
        team = normalize_team(row.get('team'))
        if not season or not team or team == '': continue
        season = int(season)
        if target not in roster_lookup: roster_lookup[target] = {}
        if season not in roster_lookup[target]: roster_lookup[target][season] = {}
        roster_lookup[target][season][team] = roster_lookup[target][season].get(team, 0) + 1

    new_pth = {}
    for name, seasons in roster_lookup.items():
        if name in existing_pth_names: continue
        season_team = {}
        for yr in sorted(seasons.keys()):
            teams = seasons[yr]
            best_team = max(teams, key=teams.get)
            if best_team and len(best_team) >= 2: season_team[yr] = best_team
        if not season_team: continue
        entries = []
        sorted_years = sorted(season_team.keys())
        current_team = season_team[sorted_years[0]]
        start_yr = sorted_years[0]
        for i in range(1, len(sorted_years)):
            yr = sorted_years[i]
            tm = season_team[yr]
            if tm != current_team:
                entries.append({'t': current_team, 'y1': start_yr, 'y2': sorted_years[i-1]})
                current_team = tm
                start_yr = yr
        entries.append({'t': current_team, 'y1': start_yr, 'y2': sorted_years[-1]})
        new_pth[name] = entries

    print(f"Built exact team histories for {len(new_pth)} players")

    fallback_count = 0
    for p in hp:
        name = p['n']
        if name in existing_pth_names or name in new_pth: continue
        teams = p.get('_teams', [])
        bbt = p.get('_bestByTeam', {})
        yrs_str = p.get('_yrs', '')
        yr_match = re.match(r'(\d{4})-(\d{4})', yrs_str)
        if not yr_match or not teams: continue
        cs, ce = int(yr_match.group(1)), int(yr_match.group(2))
        if len(teams) == 1:
            abbr = TEAM_ABBR_FULL.get(teams[0], teams[0][:3].upper())
            new_pth[name] = [{'t': abbr, 'y1': cs, 'y2': ce}]
            fallback_count += 1
        else:
            def get_yr(tm):
                if tm in bbt: return bbt[tm].get('yr', 0)
                abbr = TEAM_ABBR_FULL.get(tm, tm[:3].upper())
                for k, v in bbt.items():
                    if TEAM_ABBR_FULL.get(k, k[:3].upper()) == abbr: return v.get('yr', 0)
                return 0
            td = [(TEAM_ABBR_FULL.get(tm, tm[:3].upper()), get_yr(tm)) for tm in teams]
            td.sort(key=lambda x: x[1] if x[1] > 0 else 9999)
            entries = []
            for i, (abbr, by) in enumerate(td):
                y1 = cs if i == 0 else (td[i-1][1] + by) // 2 + 1
                y2 = ce if i == len(td) - 1 else (by + td[i+1][1]) // 2
                y1, y2 = max(y1, cs), min(y2, ce)
                if y1 > y2: y2 = y1
                entries.append({'t': abbr, 'y1': y1, 'y2': y2})
            new_pth[name] = entries
            fallback_count += 1

    for name, entries in {
        'Adam Vinatieri': [{'t':'NE','y1':1996,'y2':2005},{'t':'IND','y1':2006,'y2':2019}],
        'Morten Andersen': [{'t':'NO','y1':1982,'y2':1994},{'t':'ATL','y1':1995,'y2':2007}],
        'Stephen Gostkowski': [{'t':'NE','y1':2006,'y2':2019},{'t':'TEN','y1':2020,'y2':2020}],
    }.items():
        if name not in existing_pth_names and name not in new_pth:
            new_pth[name] = entries

    print(f"Fallback: {fallback_count}. Total new: {len(new_pth)}")

    # =====================
    # 3. WRITE OUTPUTS
    # =====================
    print("\n=== Writing outputs ===")

    # player_team_history.js
    js_lines = []
    for name, entries in new_pth.items():
        escaped = name.replace("'", "\\'")
        entry_strs = ["{t:'%s',y1:%d,y2:%d}" % (e['t'], e['y1'], e['y2']) for e in entries]
        js_lines.append("  '%s': [%s]," % (escaped, ','.join(entry_strs)))
    with open(pth_path, encoding='utf-8') as f:
        original = f.read().strip()
    insert_point = original.rfind('};')
    new_pth_content = original[:insert_point] + "\n" + "\n".join(js_lines) + "\n};\n"
    with open(pth_path, 'w', encoding='utf-8') as f:
        f.write(new_pth_content)
    print(f"Updated {pth_path}: {len(new_pth)} new entries")

    # index.html
    idx_path = 'index.html'
    with open(idx_path, encoding='utf-8') as f:
        content = f.read()

    # Build LEGEND_BIRTH_YEARS: use "YYYY-MM-DD" for exact dates, integer for year-only
    all_entries = []
    for name in sorted(set(list(birth_dates.keys()) + list(birth_years.keys()))):
        if name in birth_dates:
            all_entries.append('"%s":"%s"' % (name.replace('"', '\\"'), birth_dates[name]))
        elif name in birth_years:
            all_entries.append('"%s":%d' % (name.replace('"', '\\"'), birth_years[name]))
    new_birth_line = 'const LEGEND_BIRTH_YEARS={' + ','.join(all_entries) + '};'
    content = re.sub(r'const LEGEND_BIRTH_YEARS=\{[^}]+\};', new_birth_line, content)

    # LEGEND_BIO
    bio_entries = []
    for name, bio in bio_data.items():
        if not bio: continue
        parts = []
        if 'height' in bio: parts.append('h:%d' % bio['height'])
        if 'weight' in bio: parts.append('w:%d' % bio['weight'])
        if 'draft_number' in bio: parts.append('dr:%d' % bio['draft_number'])
        if 'college' in bio: parts.append('c:"%s"' % bio['college'].replace('"', '\\"'))
        if 'jersey' in bio: parts.append('j:%d' % bio['jersey'])
        if parts: bio_entries.append('"%s":{%s}' % (name.replace('"', '\\"'), ','.join(parts)))
    bio_js = 'const LEGEND_BIO={' + ','.join(bio_entries) + '};'

    if 'const LEGEND_BIO=' in content:
        content = re.sub(r'const LEGEND_BIO=\{[^}]*\};', bio_js, content)
    else:
        insert_after = 'LDB.forEach(p => { if (LEGEND_BIRTH_YEARS[p.n]) p.birthYear = typeof LEGEND_BIRTH_YEARS[p.n] === \'string\' ? parseInt(LEGEND_BIRTH_YEARS[p.n]) : LEGEND_BIRTH_YEARS[p.n]; });'
        if insert_after in content:
            content = content.replace(insert_after, insert_after + '\n' + bio_js)
        else:
            # Fallback: insert after any LDB.forEach birth year line
            old_insert = 'LDB.forEach(p => { if (LEGEND_BIRTH_YEARS[p.n]) p.birthYear = LEGEND_BIRTH_YEARS[p.n]; });'
            if old_insert in content:
                content = content.replace(old_insert, old_insert + '\n' + bio_js)

    # Add bio apply code if not present
    bio_apply = """// Apply bio data (height, weight, draft, college, jersey) to retired D entries
D.forEach(d => {
  if (!d._retired) return;
  const bio = LEGEND_BIO[d.n];
  if (!bio) return;
  if (bio.h && d._height == null) d._height = bio.h;
  if (bio.w && d._weight == null) d._weight = bio.w;
  if (bio.dr && d.dr == null) d.dr = bio.dr;
  if (bio.c && !d._college) d._college = bio.c;
  if (bio.j != null && d._number == null) d._number = bio.j;
});"""
    if 'LEGEND_BIO[d.n]' not in content:
        target_line = 'D.forEach(d => { if (d._retired && d.age == null && LEGEND_BIRTH_YEARS[d.n]) d.age = _calcAge(LEGEND_BIRTH_YEARS[d.n]); });'
        if target_line in content:
            content = content.replace(target_line, target_line + '\n' + bio_apply)

    with open(idx_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Updated {idx_path} with {len(birth_dates)} exact birthdates + {est_count} year estimates + {len(bio_data)} bios")

    print("\nDone! Upload index.html and data/player_team_history.js to your site.")

if __name__ == '__main__':
    main()
