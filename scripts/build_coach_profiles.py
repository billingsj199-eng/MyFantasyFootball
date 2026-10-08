#!/usr/bin/env python3
"""
Coach playcalling profiles -> data/coach_profiles.js

  window.COACH_PROFILES = {f: [field keys], r: [[row values], ...]}   one row per team-season 2019-2026

Row identity: yr, tm, hc (head coach), op (offensive playcaller), dp (defensive playcaller).
Playcallers are the OC / DC from pbp_cache/coaches.json (Pro Football Reference) unless
E:\\MyFantasyFootball\\sim_lab\\coach_overrides.json names a head-coach playcaller
({season: {team: {oc_play, dc_play}}}, the file build_scheme.py reads). Seasons that list two
coordinators (mid-season change) get "A / B" - PFR has no dates to split them.

Every rate ships with its denominator (trailing hidden fields) so the page combines seasons
into a career profile exactly - keep F in sync with the coach module in app.js.

Sources
  nflverse pbp           tendency (neutral pass rate, early-down pass rate, PROE), pace, no-huddle,
                         shotgun, 4th-down go rates, aDOT / deep rate, outside-run rate, results
  nflverse participation formation, personnel, coverage shells, box counts (published after each
                         season, so 2026 stays blank until then)
  FTN charting (nflverse, 2022+)  play action, motion, RPO, screens, out of pocket, empty
  PFF weekly             target share by position; defense blitz / man / pressure = what that
                         team's opponents' QBs and receivers saw

  python scripts/build_coach_profiles.py              # every season
  python scripts/build_coach_profiles.py --years 2026 # refresh one season, keep the rest
"""
import argparse, collections, io, json, os, re, sys
import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
# build_adv_stats already re-wraps sys.stdout as UTF-8; wrapping it here too would close the stream
from build_adv_stats import CACHE, TEAM_FIX, TEAM_NAMES, team, fnum, div, weekly, weekly_weeks  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'coach_profiles.js')
COACHES = os.path.join(CACHE, 'coaches.json')
OVERRIDES = r'E:\MyFantasyFootball\sim_lab\coach_overrides.json'
FTN_URL = 'https://github.com/nflverse/nflverse-data/releases/download/ftn_charting/ftn_charting_{yr}.parquet'
YEARS = list(range(2019, 2027))
TEAM_ALIAS = {'GNB': 'GB', 'KAN': 'KC', 'NWE': 'NE', 'NOR': 'NO', 'SFO': 'SF', 'TAM': 'TB', 'LVR': 'LV',
              'SDG': 'LAC', 'RAM': 'LAR', 'CRD': 'ARI', 'RAV': 'BAL', 'CLT': 'IND', 'HTX': 'HOU', 'OTI': 'TEN'}

F = ['yr', 'tm', 'hc', 'op', 'dp', 'g',
     'npr', 'edpr', 'proe', 'npace', 'nh', 'sg', 'uc', 'pis',
     'p11', 'p12', 'p13', 'p21', 'p22', 'p10',
     'pa', 'mot', 'rpo', 'scr', 'oop', 'emp',
     'adot', 'deep', 'rbt', 'tet', 'wrt', 'outr',
     'go4', 'go4s',
     'epa', 'sr',
     'dblz', 'dman', 'dprs', 'c0', 'c1', 'c2', 'c3', 'c4', 'c6', 'hi2', 'box', 'box8', 'depa', 'dsr', 'dskp',
     # hidden denominators
     'pl', 'npl', 'edn', 'pon', 'pcn', 'fmn', 'prn', 'ftpl', 'ftdb', 'ayn', 'tgn', 'rln', 'f4n', 'f4sn',
     'dpl', 'dpa', 'dpdbt', 'dmzr', 'covn', 'boxn']
DEN = F[F.index('pl'):]

PBP_COLS = ['season_type', 'week', 'game_id', 'play_id', 'posteam', 'defteam', 'pass', 'rush', 'two_point_attempt',
            'epa', 'success', 'wp', 'half_seconds_remaining', 'game_seconds_remaining', 'fixed_drive', 'down',
            'ydstogo', 'pass_oe', 'shotgun', 'no_huddle', 'air_yards', 'pass_attempt', 'sack', 'play_type',
            'run_gap', 'run_location', 'qb_kneel']
FLAGS = ['pass', 'rush', 'two_point_attempt', 'success', 'shotgun', 'no_huddle', 'pass_attempt', 'sack', 'qb_kneel']


def load_pbp(yr):
    p = os.path.join(CACHE, f'play_by_play_{yr}.csv.gz')
    if not os.path.exists(p):
        return None
    hdr = set(pd.read_csv(p, nrows=0).columns)
    df = pd.read_csv(p, usecols=[c for c in PBP_COLS if c in hdr], low_memory=False)
    df = df[df.season_type == 'REG'].copy()
    for c in PBP_COLS:
        if c not in df.columns:
            df[c] = 0 if c in FLAGS else float('nan')
    for c in FLAGS:
        df[c] = df[c].fillna(0)
    for c in ('posteam', 'defteam'):
        df[c] = df[c].map(lambda t: TEAM_FIX.get(t, t) if isinstance(t, str) else t)
    df['week'] = df.week.astype(int)
    return df


def load_part(yr):
    p = os.path.join(CACHE, f'pbp_participation_{yr}.parquet')
    if not os.path.exists(p):
        return None
    return pd.read_parquet(p, columns=['nflverse_game_id', 'play_id', 'offense_formation', 'offense_personnel',
                                       'defenders_in_box', 'defense_coverage_type'])


def load_ftn(yr):
    if yr < 2022:
        return None
    p = os.path.join(CACHE, f'ftn_charting_{yr}.parquet')
    if yr == YEARS[-1] or not os.path.exists(p):
        try:
            r = requests.get(FTN_URL.format(yr=yr), timeout=120)
            if r.status_code == 200 and len(r.content) > 1000:
                with open(p, 'wb') as fh:
                    fh.write(r.content)
        except Exception as e:  # noqa: BLE001
            print(f'  {yr}: FTN download failed ({e}) - using cache if any')
    if not os.path.exists(p):
        return None
    cols = ['nflverse_game_id', 'nflverse_play_id', 'is_play_action', 'is_motion', 'is_rpo', 'is_screen_pass',
            'is_qb_out_of_pocket', 'n_offense_backfield']
    df = pd.read_parquet(p, columns=cols)
    for c in cols[2:7]:
        df[c] = df[c].fillna(False).astype(bool).astype(int)
    return df


def pers_code(s):
    """'1 C, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 3 WR' -> '11' (backs incl. FB, then TEs)."""
    if not isinstance(s, str) or not s:
        return None
    cnt = collections.Counter()
    for part in s.split(','):
        m = re.match(r'\s*(\d+)\s+([A-Z]+)', part)
        if m:
            cnt[m.group(2)] += int(m.group(1))
    backs, tes = cnt['RB'] + cnt['FB'], cnt['TE']
    if cnt['WR'] + backs + tes == 0:
        return None
    return f'{backs}{tes}'


def staff(coaches, overrides, yr, tm):
    def by_team(src):
        return {TEAM_ALIAS.get(k, team(k)): v for k, v in (src.get(str(yr)) or {}).items() if isinstance(v, dict)}

    def nm(s):
        return ' / '.join(x.strip() for x in str(s or '').split(',') if x.strip()) or '(unknown)'

    c = by_team(coaches).get(tm, {})
    ov = by_team(overrides).get(tm, {})
    hc = nm(c.get('hc'))
    # no coordinator listed = the head coach runs that side (Shanahan / McVay offense, Belichick defense)
    op = ov.get('oc_play') or (nm(c.get('oc')) if (c.get('oc') or '').strip() else hc)
    dp = ov.get('dc_play') or (nm(c.get('dc')) if (c.get('dc') or '').strip() else hc)
    return hc, op, dp


def season_rows(yr, coaches, overrides):
    pbp = load_pbp(yr)
    if pbp is None:
        print(f'{yr}: no pbp - skipped')
        return []
    S = collections.defaultdict(lambda: collections.defaultdict(float))

    def add(series, key):
        for tm, v in series.items():
            if isinstance(tm, str) and pd.notna(v):
                S[tm][key] += float(v)

    df = pbp[(pbp.two_point_attempt != 1) & pbp.posteam.notna() & pbp.defteam.notna()]
    plays = df[((df['pass'] == 1) | (df.rush == 1)) & df.epa.notna()].copy()
    plays['neu'] = (plays.wp >= 0.2) & (plays.wp <= 0.8) & (plays.half_seconds_remaining > 120)
    go = plays.groupby('posteam')
    add(go.size(), 'pl'); add(go.epa.sum(), 'epa_s'); add(go.success.sum(), 'suc_s')
    add(go.shotgun.sum(), 'sg'); add(go.no_huddle.sum(), 'nh')
    add(df.groupby('posteam').game_id.nunique(), 'g')
    neu = plays[plays.neu]
    add(neu.groupby('posteam').size(), 'npl'); add(neu.groupby('posteam')['pass'].sum(), 'npass')
    po = neu[neu.pass_oe.notna()]
    add(po.groupby('posteam').size(), 'pon'); add(po.groupby('posteam').pass_oe.sum(), 'poe')
    ed = neu[neu.down <= 2]
    add(ed.groupby('posteam').size(), 'edn'); add(ed.groupby('posteam')['pass'].sum(), 'edp')
    pc = plays.sort_values(['game_id', 'fixed_drive', 'game_seconds_remaining'], ascending=[True, True, False]).copy()
    pc['gap'] = pc.groupby(['game_id', 'fixed_drive']).game_seconds_remaining.shift(1) - pc.game_seconds_remaining
    pc = pc[pc.neu & (pc.gap > 0) & (pc.gap <= 60)]
    add(pc.groupby('posteam').gap.sum(), 'pace'); add(pc.groupby('posteam').size(), 'pcn')
    att = df[(df.pass_attempt == 1) & (df.sack != 1) & df.air_yards.notna()]
    add(att.groupby('posteam').size(), 'ayn'); add(att.groupby('posteam').air_yards.sum(), 'ay')
    add(att[att.air_yards >= 20].groupby('posteam').size(), 'deep')
    runs = plays[(plays.rush == 1) & plays.run_location.notna()]
    add(runs.groupby('posteam').size(), 'rln'); add(runs[runs.run_gap == 'end'].groupby('posteam').size(), 'outc')
    f4 = df[(df.down == 4) & df.play_type.isin(['pass', 'run', 'punt', 'field_goal']) & (df.qb_kneel != 1)
            & (df.wp >= 0.1) & (df.wp <= 0.9)].copy()
    f4['go'] = f4.play_type.isin(['pass', 'run']).astype(int)
    add(f4.groupby('posteam').size(), 'f4n'); add(f4.groupby('posteam').go.sum(), 'go')
    f4s = f4[f4.ydstogo <= 2]
    add(f4s.groupby('posteam').size(), 'f4sn'); add(f4s.groupby('posteam').go.sum(), 'gos')
    gd = plays.groupby('defteam')
    add(gd.size(), 'dpl'); add(gd.epa.sum(), 'depa_s'); add(gd.success.sum(), 'dsuc_s')
    gdp = plays[plays['pass'] == 1].groupby('defteam')
    add(gdp.size(), 'dpa'); add(gdp.sack.sum(), 'dsk')

    part = load_part(yr)
    if part is not None:
        m = plays.merge(part, left_on=['game_id', 'play_id'], right_on=['nflverse_game_id', 'play_id'], how='inner')
        fm = m[m.offense_formation.notna() & (m.offense_formation.astype(str) != '')]
        add(fm.groupby('posteam').size(), 'fmn')
        # 2023+ labels UNDER CENTER; 2016-2022 name the under-center sets (SINGLEBACK / I_FORM / JUMBO)
        add(fm[fm.offense_formation.isin(['UNDER CENTER', 'SINGLEBACK', 'I_FORM', 'JUMBO'])].groupby('posteam').size(), 'uc')
        add(fm[fm.offense_formation == 'PISTOL'].groupby('posteam').size(), 'pis')
        m['pers'] = m.offense_personnel.map(pers_code)
        pr = m[m.pers.notna()]
        add(pr.groupby('posteam').size(), 'prn')
        for code in ('11', '12', '13', '21', '22', '10'):
            add(pr[pr.pers == code].groupby('posteam').size(), 'p' + code)
        cv = m[(m['pass'] == 1) & m.defense_coverage_type.notna() & (m.defense_coverage_type.astype(str) != '')]
        add(cv.groupby('defteam').size(), 'covn')
        for key, types in (('c0', ['COVER_0']), ('c1', ['COVER_1']), ('c2', ['COVER_2']), ('c3', ['COVER_3']),
                           ('c4', ['COVER_4']), ('c6', ['COVER_6']), ('hi2', ['COVER_2', 'COVER_4', 'COVER_6', '2_MAN'])):
            add(cv[cv.defense_coverage_type.isin(types)].groupby('defteam').size(), key)
        bx = m[(m.rush == 1) & m.defenders_in_box.notna() & (m.defenders_in_box > 0)]
        add(bx.groupby('defteam').size(), 'boxn'); add(bx.groupby('defteam').defenders_in_box.sum(), 'box_s')
        add(bx[bx.defenders_in_box >= 8].groupby('defteam').size(), 'box8')

    ftn = load_ftn(yr)
    if ftn is not None:
        m = plays.merge(ftn, left_on=['game_id', 'play_id'], right_on=['nflverse_game_id', 'nflverse_play_id'], how='inner')
        g = m.groupby('posteam')
        add(g.size(), 'ftpl'); add(g.is_motion.sum(), 'mot'); add(g.is_rpo.sum(), 'rpo')
        add(m[m.n_offense_backfield == 0].groupby('posteam').size(), 'emp')
        d = m[m['pass'] == 1].groupby('posteam')
        add(d.size(), 'ftdb'); add(d.is_play_action.sum(), 'pa'); add(d.is_screen_pass.sum(), 'scr'); add(d.is_qb_out_of_pocket.sum(), 'oop')

    # PFF: target share by position (offense); blitz / man / pressure the opponent faced (defense)
    opp = {(tm, int(wk)): dt for (tm, wk), dt in df.groupby(['posteam', 'week']).defteam.first().items()}
    facet = 'receiving' if weekly_weeks('receiving', yr) else 'receiving_summary'
    for wk, _pid, row in weekly(facet, yr):
        tm = team(row.get('team_name'))
        tg = fnum(row.get('targets')) or 0
        ps = (row.get('position') or '').strip()
        S[tm]['tgn'] += tg
        key = 'rbt_c' if ps in ('HB', 'FB') else 'tet_c' if ps == 'TE' else 'wrt_c' if ps == 'WR' else None
        if key:
            S[tm][key] += tg
    for wk, _pid, row in weekly('passing_pressure', yr):
        dt = opp.get((team(row.get('team_name')), wk))
        if dt:
            pdb, cdb, bdb = (fnum(row.get(k)) or 0 for k in ('pressure_dropbacks', 'no_pressure_dropbacks', 'blitz_dropbacks'))
            S[dt]['dpdbt'] += pdb + cdb
            S[dt]['dppdb'] += pdb
            S[dt]['dpbdb'] += bdb
    for wk, _pid, row in weekly('receiving_scheme', yr):
        dt = opp.get((team(row.get('team_name')), wk))
        if dt:
            mr, zr = fnum(row.get('man_routes')) or 0, fnum(row.get('zone_routes')) or 0
            S[dt]['dman'] += mr
            S[dt]['dmzr'] += mr + zr

    rows = []
    for tm in sorted(t for t in list(S) if t in TEAM_NAMES and S[t]['pl'] > 0):
        o = S[tm]
        hc, op, dp = staff(coaches, overrides, yr, tm)
        row = [yr, tm, hc, op, dp, int(o['g']),
               div(o['npass'], o['npl'], 100), div(o['edp'], o['edn'], 100), div(o['poe'], o['pon'], 1, 1),
               div(o['pace'], o['pcn'], 1, 1), div(o['nh'], o['pl'], 100), div(o['sg'], o['pl'], 100),
               div(o['uc'], o['fmn'], 100), div(o['pis'], o['fmn'], 100)]
        row += [div(o['p' + k], o['prn'], 100) for k in ('11', '12', '13', '21', '22', '10')]
        row += [div(o['pa'], o['ftdb'], 100), div(o['mot'], o['ftpl'], 100), div(o['rpo'], o['ftpl'], 100),
                div(o['scr'], o['ftdb'], 100), div(o['oop'], o['ftdb'], 100), div(o['emp'], o['ftpl'], 100),
                div(o['ay'], o['ayn'], 1, 1), div(o['deep'], o['ayn'], 100), div(o['rbt_c'], o['tgn'], 100),
                div(o['tet_c'], o['tgn'], 100), div(o['wrt_c'], o['tgn'], 100), div(o['outc'], o['rln'], 100),
                div(o['go'], o['f4n'], 100), div(o['gos'], o['f4sn'], 100),
                div(o['epa_s'], o['pl'], 1, 3), div(o['suc_s'], o['pl'], 100),
                div(o['dpbdb'], o['dpdbt'], 100), div(o['dman'], o['dmzr'], 100), div(o['dppdb'], o['dpdbt'], 100)]
        row += [div(o[k], o['covn'], 100) for k in ('c0', 'c1', 'c2', 'c3', 'c4', 'c6', 'hi2')]
        row += [div(o['box_s'], o['boxn'], 1, 2), div(o['box8'], o['boxn'], 100),
                div(o['depa_s'], o['dpl'], 1, 3), div(o['dsuc_s'], o['dpl'], 100), div(o['dsk'], o['dpa'], 100)]
        row += [int(round(o[k])) for k in DEN]
        assert len(row) == len(F), (len(row), len(F))
        rows.append(row)
    print(f'{yr}: {len(rows)} team-seasons | participation {"yes" if part is not None else "no"} | FTN {"yes" if ftn is not None else "no"}')
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', default=None, help='comma list; other seasons are kept from the existing file')
    args = ap.parse_args()
    years = [int(y) for y in args.years.split(',')] if args.years else YEARS
    coaches = json.load(open(COACHES, encoding='utf-8'))
    overrides = json.load(open(OVERRIDES, encoding='utf-8')) if os.path.exists(OVERRIDES) else {}
    keep = []
    if args.years and os.path.exists(OUT):
        old = open(OUT, encoding='utf-8').read()
        prev = json.loads(old[old.index('=') + 1:].rstrip().rstrip(';'))
        if prev.get('f') == F:
            keep = [r for r in prev['r'] if r[0] not in years]
    rows = keep + [r for y in years for r in season_rows(y, coaches, overrides)]
    rows.sort(key=lambda r: (-r[0], r[1]))
    text = 'window.COACH_PROFILES=' + json.dumps({'f': F, 'r': rows}, separators=(',', ':'), ensure_ascii=False, allow_nan=False) + ';\n'
    old = open(OUT, encoding='utf-8').read() if os.path.exists(OUT) else None
    if old != text:
        with open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
    print(f'{len(rows)} team-seasons -> {os.path.relpath(OUT, ROOT)} ({len(text) // 1024} KB, {"unchanged" if old == text else "written"})')


if __name__ == '__main__':
    main()
