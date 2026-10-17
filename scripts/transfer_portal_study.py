"""transfer_portal_study.py - who transfers, where they go, and what happens to them (portal / NIL era vs before).

Jack 2026-10-17: "running a study on the nil & transfer portal era - we dont have a large sample to actually
apply but could have some interesting takeaways on players that transfer and where they transfer".

Inputs (cached by the pull step, git-excluded scratch caches in scripts/):
  scripts/_cfb_pstats_<yr>.json   CFBD /stats/player/season (passing, rushing, receiving), 2016-2025, every FBS+FCS player
  scripts/_portal_<yr>.json       CFBD /player/portal 2021-2026 (origin, destination, stars, rating)
  scripts/_sp_ratings.json        SP+ off/def by team-season (jm_sos_analysis cache)
  scripts/_cfb_games.json         CFBD schedules (team games per season)
  E:/MyFantasyFootball/pbp_cache/draft_picks.parquet   nflverse draft picks through 2026
  data/jm_career_grades.js        graded NFL careers for the 2017-2024 classes

A transfer = the same CFBD player id plays for a different team in his next season (gap <= 1 skipped year).
CFBD ids persist across schools, so pre-portal transfers (2017-2020) are found the same way.
Era: destination season 2021+ = portal / NIL (one-time transfer rule + NIL both arrived in 2021).

  python scripts/transfer_portal_study.py [--pull]   (--pull re-downloads the CFBD caches)
Writes scripts/transfer_portal_study_<date>.txt (all output) and scripts/transfer_portal_rows.json.
"""
import json, os, re, sys, math, datetime, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
S = os.path.join(ROOT, 'scripts')
YEARS = range(2016, 2027)   # 2026 = season in progress (used only for the current-movers list)
SKILL = ('QB', 'RB', 'WR', 'TE')

if '--pull' in sys.argv:
    import requests
    from cfbd_config import CFBD_API_KEY
    H = {'Authorization': 'Bearer ' + CFBD_API_KEY, 'Accept': 'application/json'}
    B = 'https://apinext.collegefootballdata.com'
    for y in YEARS:
        out = []
        for c in ('passing', 'rushing', 'receiving'):
            r = requests.get(B + '/stats/player/season', params={'year': y, 'category': c}, headers=H, timeout=120)
            r.raise_for_status(); out += r.json()
        json.dump(out, open(os.path.join(S, f'_cfb_pstats_{y}.json'), 'w'))
    for y in range(2021, 2027):
        r = requests.get(B + '/player/portal', params={'year': y}, headers=H, timeout=120)
        r.raise_for_status(); json.dump(r.json(), open(os.path.join(S, f'_portal_{y}.json'), 'w'))

LOG = []
def say(*a):
    s = ' '.join(str(x) for x in a); print(s); LOG.append(s)

def norm(n):
    n = n.lower().replace('.', '').replace("'", '').replace('-', ' ')
    n = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', n)
    return re.sub(r'\s+', ' ', n).strip()

P4 = {'SEC', 'Big Ten', 'Big 12', 'ACC', 'Pac-12'}
G5 = {'American Athletic', 'Conference USA', 'Mid-American', 'Mountain West', 'Sun Belt', 'FBS Independents'}
def tier(conf, team, yr):
    if team == 'Notre Dame': return 'P4'
    if conf == 'Pac-12' and yr >= 2024: return 'G5'   # Oregon State / Washington State leftovers
    if conf in P4: return 'P4'
    if conf in G5: return 'G5'
    return 'FCS'
TIER_N = {'FCS': 0, 'G5': 1, 'P4': 2}

# ---------- team games + SP+ ----------
games = json.load(open(os.path.join(S, '_cfb_games.json')))
TG = collections.Counter()
for y, gl in games.items():
    for g in gl:
        yy = int(str(y).rstrip('p')); TG[(yy, g[2])] += 1; TG[(yy, g[3])] += 1
for g in json.load(open(os.path.join(S, '_cfb_games_2026.json'))):
    TG[(2026, g[2])] += 1; TG[(2026, g[3])] += 1
SP = {int(y): v for y, v in json.load(open(os.path.join(S, '_sp_ratings.json'))).items()}
def sp(y, t):
    v = SP.get(y, {}).get(t); return None if not v else (v['off'] - v['def'], v['off'])

# ---------- player seasons ----------
PS = {}            # (id, yr) -> dict
for y in YEARS:
    for r in json.load(open(os.path.join(S, f'_cfb_pstats_{y}.json'))):
        k = (r['playerId'], y)
        d = PS.setdefault(k, {'id': r['playerId'], 'yr': y, 'name': r['player'], 'team': r['team'], 'conf': r['conference'],
                              'posc': collections.Counter()})
        if r['team'] != d['team']: continue                       # rare mid-season dupes: keep first team
        try: v = float(r['stat'])
        except (TypeError, ValueError): continue
        d[r['category'][:3] + '_' + r['statType']] = v
        if r.get('position'): d['posc'][r['position']] += 1
TEAM = collections.defaultdict(lambda: collections.Counter())
for d in PS.values():
    t = TEAM[(d['team'], d['yr'])]
    t['rus'] += d.get('rus_YDS', 0); t['car'] += d.get('rus_CAR', 0); t['rec'] += d.get('rec_YDS', 0); t['att'] += d.get('pas_ATT', 0)
# player position = most common across his seasons
POS = collections.defaultdict(collections.Counter)
for d in PS.values(): POS[d['id']].update(d['posc'])
for d in PS.values():
    d['pos'] = POS[d['id']].most_common(1)[0][0] if POS[d['id']] else None
    t = TEAM[(d['team'], d['yr'])]
    py, ptd, pint = d.get('pas_YDS', 0), d.get('pas_TD', 0), d.get('pas_INT', 0)
    ry, rtd = d.get('rus_YDS', 0), d.get('rus_TD', 0)
    rc, rcy, rctd = d.get('rec_REC', 0), d.get('rec_YDS', 0), d.get('rec_TD', 0)
    d['fpts'] = .04 * py + 4 * ptd - 2 * pint + .1 * ry + 6 * rtd + .5 * rc + .1 * rcy + 6 * rctd
    g = TG.get((d['yr'], d['team'])) or 12
    d['fppg'] = d['fpts'] / g
    if d['pos'] == 'QB': d['share'] = d.get('pas_ATT', 0) / t['att'] if t['att'] else 0
    elif d['pos'] == 'RB': d['share'] = (ry + rcy) / (t['rus'] + t['rec']) if (t['rus'] + t['rec']) else 0
    else: d['share'] = rcy / t['rec'] if t['rec'] else 0
    d['tier'] = tier(d['conf'], d['team'], d['yr'])
ROLE = {'QB': .5, 'RB': .20, 'WR': .15, 'TE': .08}

by_id = collections.defaultdict(dict)
for d in PS.values():
    if d['pos'] in SKILL: by_id[d['id']][d['yr']] = d

# ---------- portal list ----------
PORTAL = {}
for y in range(2021, 2027):
    for r in json.load(open(os.path.join(S, f'_portal_{y}.json'))):
        if r.get('position') not in SKILL: continue
        PORTAL.setdefault((norm(f"{r['firstName']} {r['lastName']}"), r['origin']), r)
portal_entries = [r for y in range(2021, 2027) for r in json.load(open(os.path.join(S, f'_portal_{y}.json'))) if r.get('position') in SKILL]

# ---------- transitions ----------
T = []   # every consecutive played pair
for pid, seas in by_id.items():
    ys = sorted(seas)
    for a, b in zip(ys, ys[1:]):
        if b - a > 2: continue
        A, Bd = seas[a], seas[b]
        moved = A['team'] != Bd['team']
        pr = PORTAL.get((norm(A['name']), A['team'])) if moved else None
        spa, spb = sp(a, A['team']), sp(a, Bd['team'])     # both teams rated on the PRE season
        T.append({'id': pid, 'name': A['name'], 'pos': A['pos'], 'y0': a, 'y1': b, 'from': A['team'], 'to': Bd['team'],
                  'moved': moved, 'era': 'portal' if b >= 2021 else 'pre', 'skip': b - a - 1,
                  't0': A['tier'], 't1': Bd['tier'], 'share0': A['share'], 'share1': Bd['share'],
                  'fppg0': A['fppg'], 'fppg1': Bd['fppg'], 'sp0': spa[0] if spa else None, 'sp1': spb[0] if spb else None,
                  'off1': spb[1] if spb else None, 'stars': pr.get('stars') if pr else None})
T_NOW = [t for t in T if t['y1'] == 2026]
T = [t for t in T if t['y1'] <= 2025]
say(f'transitions: {len(T)}  moves: {sum(t["moved"] for t in T)}  (pre {sum(t["moved"] and t["era"]=="pre" for t in T)}, portal {sum(t["moved"] and t["era"]=="portal" for t in T)})')

# vacated share at the destination: prior-year same-position share of players who are NOT on that team next season
nxt_team = {(d['id'], d['yr']): d['team'] for d in PS.values()}
VAC = collections.Counter()
for d in PS.values():
    if d['pos'] not in SKILL: continue
    if nxt_team.get((d['id'], d['yr'] + 1)) != d['team']:
        VAC[(d['team'], d['yr'], d['pos'])] += d['share']
for t in T: t['vac'] = min(1.0, VAC[(t['to'], t['y0'], t['pos'])] if t['moved'] else VAC[(t['from'], t['y0'], t['pos'])])

# ---------- expected change: stayers with same position, era, tier, pre-share bin ----------
def sbin(s, pos):
    r = ROLE[pos]; return 0 if s < .25 * r else 1 if s < .6 * r else 2 if s < r else 3 if s < 1.6 * r else 4
EXP = collections.defaultdict(list)
for t in T:
    if not t['moved'] and t['skip'] == 0:
        EXP[(t['pos'], t['era'], t['t0'], sbin(t['share0'], t['pos']))].append((t['share1'] - t['share0'], t['fppg1'] - t['fppg0']))
def mean(a): return sum(a) / len(a) if a else float('nan')
def sd(a):
    m = mean(a); return math.sqrt(sum((x - m) ** 2 for x in a) / (len(a) - 1)) if len(a) > 1 else float('nan')
def tstat(a): return mean(a) / (sd(a) / math.sqrt(len(a))) if len(a) > 2 and sd(a) > 0 else float('nan')
for t in T:
    e = EXP.get((t['pos'], t['era'], t['t0'], sbin(t['share0'], t['pos'])))
    t['ex_share'] = (t['share1'] - t['share0']) - mean([x[0] for x in e]) if e and len(e) >= 10 else None
    t['ex_fppg'] = (t['fppg1'] - t['fppg0']) - mean([x[1] for x in e]) if e and len(e) >= 10 else None
    t['role0'] = t['share0'] >= ROLE[t['pos']]
    t['role1'] = t['share1'] >= ROLE[t['pos']]
    t['path'] = 'up' if TIER_N[t['t1']] > TIER_N[t['t0']] else 'down' if TIER_N[t['t1']] < TIER_N[t['t0']] else 'same'

MV = [t for t in T if t['moved']]
def line(lbl, rows, extra=''):
    xs = [r['ex_share'] for r in rows if r['ex_share'] is not None]; xf = [r['ex_fppg'] for r in rows if r['ex_fppg'] is not None]
    rr = [r for r in rows]
    say(f'  {lbl:34} n {len(rr):5}  role after {100*mean([r["role1"] for r in rr]):5.1f}%  share vs stayers {100*mean(xs):+5.1f} pts (t {tstat(xs):+5.1f})  ppg vs stayers {mean(xf):+5.2f} (t {tstat(xf):+5.1f}) {extra}')

say('\n=== 1. VOLUME: how many skill players move, by era ===')
for era in ('pre', 'portal'):
    for y1 in sorted({t['y1'] for t in T if t['era'] == era}):
        al = [t for t in T if t['y1'] == y1]; m = [t for t in al if t['moved']]
        rl = [t for t in al if t['role0']]; rm = [t for t in rl if t['moved']]
        say(f'  {y1}: {len(m):4} of {len(al):5} moved ({100*len(m)/len(al):4.1f}%)  | of last-year STARTERS: {len(rm):3} of {len(rl):4} ({100*len(rm)/max(1,len(rl)):4.1f}%)')

say('\n=== 2. WHERE THEY GO: tier paths (portal era, players with a role before vs not) ===')
for era in ('pre', 'portal'):
    for lab, f in (('had a role', lambda t: t['role0']), ('no role', lambda t: not t['role0'])):
        rows = [t for t in MV if t['era'] == era and f(t)]
        c = collections.Counter(f"{t['t0']}->{t['t1']}" for t in rows)
        say(f'  {era:6} {lab:10} n {len(rows):4}: ' + ', '.join(f'{k} {100*v/len(rows):.0f}%' for k, v in c.most_common(9)))

say('\n=== 3. WHAT HAPPENS: production change vs matched stayers (same pos, era, tier, starting share) ===')
for era in ('pre', 'portal'):
    say(f' {era.upper()}')
    for pos in SKILL:
        line(pos, [t for t in MV if t['era'] == era and t['pos'] == pos])
say(' PORTAL era by path and prior role')
for role in (True, False):
    for path in ('up', 'same', 'down'):
        line(f'{"role" if role else "no role"} / {path}', [t for t in MV if t['era'] == 'portal' and t['role0'] == role and t['path'] == path])
say(' PORTAL era, transfers with a role who moved UP to P4, by position')
for pos in SKILL:
    line(f'{pos} G5/FCS -> P4 starters', [t for t in MV if t['era'] == 'portal' and t['role0'] and t['t1'] == 'P4' and t['t0'] != 'P4' and t['pos'] == pos])
say(' PRE era same split (comparison)')
for role in (True, False):
    for path in ('up', 'same', 'down'):
        line(f'{"role" if role else "no role"} / {path}', [t for t in MV if t['era'] == 'pre' and t['role0'] == role and t['path'] == path])

say('\n=== 4. WHICH DESTINATIONS WORK: destination features (portal era, all moves) ===')
pm = [t for t in MV if t['era'] == 'portal' and t['ex_share'] is not None]
def bucket(lbl, key, cuts):
    for lo, hi in zip(cuts, cuts[1:]):
        line(f'{lbl} {lo}-{hi}', [t for t in pm if t[key] is not None and lo <= t[key] < hi])
bucket('vacated share at pos', 'vac', [0, .15, .35, .6, 1.01])
for t in pm: t['spd'] = (t['sp1'] - t['sp0']) if (t['sp1'] is not None and t['sp0'] is not None) else None
bucket('team-strength jump (SP+)', 'spd', [-99, -10, -3, 3, 10, 99])
bucket('dest offense SP+', 'off1', [0, 25, 32, 38, 99])
say(' portal recruit stars (portal entries matched)')
for s in (2, 3, 4, 5):
    line(f'{s}-star', [t for t in pm if t['stars'] == s])
line('stars unknown / not matched', [t for t in pm if t['stars'] is None])
# simple multivariable read: share change vs prior share, vacated, sp jump, path (OLS)
try:
    import numpy as np
    X, y = [], []
    for t in pm:
        if t['spd'] is None: continue
        X.append([1, t['share0'] / ROLE[t['pos']], t['vac'], t['spd'] / 10, t['path'] == 'up', t['path'] == 'down', t['skip']])
        y.append(t['ex_share'] / ROLE[t['pos']])
    X, y = np.array(X, float), np.array(y)
    b, *_ = np.linalg.lstsq(X, y, rcond=None); res = y - X @ b
    se = np.sqrt(np.diag(np.linalg.inv(X.T @ X)) * (res @ res) / (len(y) - X.shape[1]))
    say(' OLS: share change vs stayers (in units of a starter-level share) on destination features, n', len(y))
    for nm, bb, ss in zip(['const', 'prior share', 'vacated share', 'SP+ jump /10', 'tier up', 'tier down', 'sat a year'], b, se):
        say(f'   {nm:14} {bb:+.3f}  (t {bb/ss:+.1f})')
except Exception as e:
    say('OLS skipped', e)

say('\n=== 5. TOP DESTINATIONS (portal era, skill transfers IN; n>=10) ===')
dst = collections.defaultdict(list)
for t in MV:
    if t['era'] == 'portal': dst[t['to']].append(t)
rows = sorted(((k, v) for k, v in dst.items() if len(v) >= 10), key=lambda kv: -len(kv[1]))
for k, v in rows[:20]:
    xs = [r['ex_share'] for r in v if r['ex_share'] is not None]
    say(f'  {k:22} in {len(v):3}  had a role before {100*mean([r["role0"] for r in v]):3.0f}%  role after {100*mean([r["role1"] for r in v]):3.0f}%  share vs stayers {100*mean(xs):+5.1f}')
say(' best / worst landing spots for skill transfers (n>=10, share vs stayers)')
sc = sorted(((k, mean([r['ex_share'] for r in v if r['ex_share'] is not None]), len(v)) for k, v in dst.items() if len(v) >= 10), key=lambda x: -x[1])
say('   best : ' + ', '.join(f'{k} {100*m:+.1f} (n {n})' for k, m, n in sc[:8]))
say('   worst: ' + ', '.join(f'{k} {100*m:+.1f} (n {n})' for k, m, n in sc[-8:]))

# ---------- 6. DRAFT + NFL ----------
import pandas as pd
dp = pd.read_parquet('E:/MyFantasyFootball/pbp_cache/draft_picks.parquet')
dp = dp[dp.position.isin(SKILL)]
DRAFT = {}
for r in dp.itertuples():
    DRAFT.setdefault(norm(r.pfr_player_name), []).append((int(r.season), int(r.pick), r.college))
grades = json.loads(re.search(r'=\s*(\{.*\})', open('data/jm_career_grades.js', encoding='utf-8').read(), re.S).group(1))
G = {}
for k, v in grades.items():
    n, y = k.rsplit('|', 1); G[(norm(n), int(y))] = v[0]

say('\n=== 6. DRAFT: final college season -> drafted within 1 yr, transfers vs one-school (final seasons 2017-2024) ===')
careers = []
for pid, seas in by_id.items():
    ys = sorted(seas); last = seas[ys[-1]]
    if ys[-1] > 2024 or ys[-1] < 2017: continue
    teams = [seas[y]['team'] for y in ys]
    moved_yrs = [ys[i] for i in range(1, len(ys)) if teams[i] != teams[i - 1]]
    dr = [x for x in DRAFT.get(norm(last['name']), []) if ys[-1] + 1 <= x[0] <= ys[-1] + 2]
    careers.append({'id': pid, 'name': last['name'], 'pos': last['pos'], 'last': ys[-1], 'tier': last['tier'], 'share': last['share'],
                    'role': last['share'] >= ROLE[last['pos']], 'fppg': last['fppg'],
                    'xfer': bool(moved_yrs), 'xfer_portal': any(y >= 2021 for y in moved_yrs), 'teams': teams,
                    'drafted': bool(dr), 'pick': dr[0][1] if dr else None, 'dyr': dr[0][0] if dr else None})
for era_lbl, f in (('final season 2017-2020', lambda c: c['last'] <= 2020), ('final season 2021-2024', lambda c: c['last'] >= 2021)):
    say(f' {era_lbl}')
    for tr in ('P4', 'G5', 'FCS'):
        for role in (True,):
            a = [c for c in careers if f(c) and c['tier'] == tr and c['role'] == role]
            x = [c for c in a if c['xfer']]; o = [c for c in a if not c['xfer']]
            px = [c['pick'] for c in x if c['drafted']]; po = [c['pick'] for c in o if c['drafted']]
            say(f'  {tr} final-yr starters: transfers {len(x):4} drafted {100*mean([c["drafted"] for c in x]) if x else 0:4.1f}% (avg pick {mean(px):5.0f})'
                f'  | one school {len(o):4} drafted {100*mean([c["drafted"] for c in o]) if o else 0:4.1f}% (avg pick {mean(po):5.0f})')
# matched on production: logistic-free version - draft rate by fppg tercile within tier
say(' drafted rate within production terciles (P4 final-yr starters, 2021-2024 finals)')
a = [c for c in careers if c['last'] >= 2021 and c['tier'] == 'P4' and c['role']]
for pos in SKILL:
    b = sorted([c for c in a if c['pos'] == pos], key=lambda c: c['fppg'])
    if len(b) < 30: continue
    k = len(b) // 3
    for i, part in enumerate((b[:k], b[k:2 * k], b[2 * k:])):
        x = [c for c in part if c['xfer']]; o = [c for c in part if not c['xfer']]
        say(f'  {pos} ppg tercile {i+1}: transfer {len(x):3} -> {100*mean([c["drafted"] for c in x]) if x else 0:4.1f}% drafted | one school {len(o):3} -> {100*mean([c["drafted"] for c in o]) if o else 0:4.1f}%')

say('\n=== 7. NFL: graded career vs draft slot, college transfers vs one-school (2017-2024 classes) ===')
import numpy as np
dr_rows = []
for c in careers:
    if not c['drafted']: continue
    g = G.get((norm(c['name']), c['dyr']))
    if g is None: continue
    dr_rows.append({**c, 'grade': g})
# grade ~ position x log(pick) + draft-class dummies (younger classes are graded on fewer seasons)
CL = sorted({r['dyr'] for r in dr_rows})
X = np.array([[r['pos'] == p for p in SKILL] + [(r['pos'] == p) * math.log(r['pick']) for p in SKILL] + [r['dyr'] == c for c in CL[1:]] for r in dr_rows], float)
y = np.array([r['grade'] for r in dr_rows])
b, *_ = np.linalg.lstsq(X, y, rcond=None)
for r, e in zip(dr_rows, y - X @ b): r['resid'] = e
for lbl, f in (('transferred (any era)', lambda r: r['xfer']), ('transferred in portal era', lambda r: r['xfer_portal']),
               ('one school', lambda r: not r['xfer'])):
    rr = [r for r in dr_rows if 'resid' in r and f(r)]
    say(f'  {lbl:28} n {len(rr):3}  career grade vs pick {mean([r["resid"] for r in rr]):+5.1f} (t {tstat([r["resid"] for r in rr]):+4.1f})')
say(' notable drafted transfers (portal era), best and worst vs their draft slot:')
pr = sorted([r for r in dr_rows if 'resid' in r and r['xfer_portal']], key=lambda r: -r['resid'])
fmt = lambda r: f"{r['name']} ({r['pos']} {r['dyr']} #{r['pick']}, {'->'.join(dict.fromkeys(r['teams']))}) {r['resid']:+.0f}"
say('   over : ' + '; '.join(fmt(r) for r in pr[:8]))
say('   under: ' + '; '.join(fmt(r) for r in pr[-8:]))

# ---------- 8. what drives a good move: prior-year signals of the movers who broke out ----------
say('\n=== 8. BREAKOUT AFTER A MOVE: portal-era movers with no role before -> a role after ===')
nb = [t for t in MV if t['era'] == 'portal' and not t['role0']]
hit = [t for t in nb if t['role1']]
say(f'  {len(hit)} of {len(nb)} ({100*len(hit)/max(1,len(nb)):.1f}%) earned a role; stayers with no role: {100*mean([t["role1"] for t in T if not t["moved"] and t["era"]=="portal" and not t["role0"]]):.1f}%')
for lbl, f in (('down a tier', lambda t: t['path'] == 'down'), ('same tier', lambda t: t['path'] == 'same'), ('up a tier', lambda t: t['path'] == 'up'),
               ('vacated >= .35', lambda t: t['vac'] >= .35), ('vacated < .15', lambda t: t['vac'] < .15)):
    g = [t for t in nb if f(t)]
    say(f'  {lbl:16} {100*mean([t["role1"] for t in g]) if g else 0:5.1f}% earn a role (n {len(g)})')

say('\n=== 9. MOVED UP AS A STARTER (G5/FCS -> P4, portal era, moves 2021-2023): did keeping the role get them drafted? ===')
for pos in SKILL + ('ALL',):
    g = [t for t in MV if t['era'] == 'portal' and t['role0'] and t['t0'] != 'P4' and t['t1'] == 'P4' and t['y1'] <= 2023 and (pos == 'ALL' or t['pos'] == pos)]
    def drafted(t): return any(t['y1'] + 1 <= x[0] <= t['y1'] + 4 for x in DRAFT.get(norm(t['name']), []))
    kept = [t for t in g if t['role1']]; lost = [t for t in g if not t['role1']]
    say(f'  {pos:3} n {len(g):3}: kept a role {len(kept):3} -> {100*mean([drafted(t) for t in kept]) if kept else 0:4.1f}% drafted | lost it {len(lost):3} -> {100*mean([drafted(t) for t in lost]) if lost else 0:4.1f}% drafted')
say(' compare: G5 one-school starters (final yr 2021-24) drafted ' + f"{100*mean([c['drafted'] for c in careers if c['last']>=2021 and c['tier']=='G5' and c['role'] and not c['xfer']]):.1f}%")

say('\n=== 10. 2026 SO FAR (through week 7): this year\'s movers vs what the history says ===')
for t in T_NOW:
    e = EXP.get((t['pos'], 'portal', t['t0'], sbin(t['share0'], t['pos'])))
    t['ex_share'] = (t['share1'] - t['share0']) - mean([x[0] for x in e]) if e and len(e) >= 10 else None
    t['ex_fppg'] = None   # partial season: shares only
    t['role0'] = t['share0'] >= ROLE[t['pos']]; t['role1'] = t['share1'] >= ROLE[t['pos']]
    t['path'] = 'up' if TIER_N[t['t1']] > TIER_N[t['t0']] else 'down' if TIER_N[t['t1']] < TIER_N[t['t0']] else 'same'
NM = [t for t in T_NOW if t['moved']]
for role in (True, False):
    for path in ('up', 'same', 'down'):
        line(f'2026 {"role" if role else "no role"} / {path}', [t for t in NM if t['role0'] == role and t['path'] == path])
try:
    devy = set(norm(n) for n in re.findall(r'"([^"]+)":\s*\[', open('data/college_stats_devy.js', encoding='utf-8').read()))
except Exception:
    devy = set()
say(f' devy-board players who transferred for 2026 ({len(devy)} names on the board):')
for t in sorted([t for t in NM if norm(t['name']) in devy], key=lambda t: -(t['share1'] / ROLE[t['pos']])):
    say(f"   {t['name']:24} {t['pos']} {t['from']} ({t['t0']}) -> {t['to']} ({t['t1']})  share {100*t['share0']:4.1f}% -> {100*t['share1']:4.1f}%  {'ROLE' if t['role1'] else 'no role'}")
say(' G5/FCS starters who moved up to P4 for 2026 and are HOLDING a role (history: these get drafted most):')
for t in sorted([t for t in NM if t['role0'] and t['path'] == 'up' and t['t1'] == 'P4' and t['role1']], key=lambda t: -(t['share1'] / ROLE[t['pos']]))[:25]:
    say(f"   {t['name']:24} {t['pos']} {t['from']} -> {t['to']}  share {100*t['share0']:4.1f}% -> {100*t['share1']:4.1f}%")

json.dump({'transitions': [t for t in MV if t['era'] == 'portal'], 'careers': careers}, open(os.path.join(S, 'transfer_portal_rows.json'), 'w'), default=str)
out = os.path.join(S, f'transfer_portal_study_{datetime.date.today().isoformat()}.txt')
open(out, 'w', encoding='utf-8').write('\n'.join(LOG) + '\n')
print('wrote', out)
