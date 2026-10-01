#!/usr/bin/env python3
"""
bbm_advance_sim.py — Monte Carlo the rest of the Best Ball Mania regular
season (through week 14) for every synced 12-team pool in Jack's Underdog
portfolio and report each team's expected ADVANCE rate (top 2 of 12).

Per pool, per sim:
  * weeks already FINAL use real half-PPR points from data/weekly_stats_active.js
    (the postgame importer's 2026 rows — the same feed the site's live
    standings read);
  * every remaining week through week 14 draws a score for each player from
    the Sim Lab weekly projection (data/sim_proj_2026.json, row =
    [half, ppr, std, boom%, bust%]): a split log-normal around the half-PPR
    median whose upper/lower spread is solved from the sim's own boom%
    (P > 1.5x median) and bust% (P < 0.5x median); a missing row that week =
    bye / ruled out = 0; players the Sim Lab never projects fall back to
    seasonPpg (minus their bye) and then to 0;
  * each team's weekly best-ball lineup is QB / RB RB / WR WR WR / TE / FLEX
    (site's BB_LINEUP), scores are summed over weeks 1-14, the pool is ranked
    and the top 2 advance.
Player weeks are drawn independently (no QB-stack correlation yet).

Data sources for the portfolio (Jack's drafts + the 11 opponents per draft):
  --portfolio FILE   JSON: the shared/jacks_portfolio document (Firestore REST
                     shape or the raw payload), or a browser dump of
                     window._udPortfolio (drafts carry allTeams).
  (no flag)          fetch shared/jacks_portfolio from Firestore with the
                     credential in the environment:
                       MFF_FIREBASE_SA_JSON        — service-account key JSON (content)
                       GOOGLE_APPLICATION_CREDENTIALS — path to that key file
                       MFF_FIREBASE_REFRESH_TOKEN  — a Firebase refresh token for
                                                     Jack's (or any premium) login
Opponent rosters reach Firestore through the site: the cloud save now carries
each draft's compact `field` (added 2026-10-01 alongside this script); drafts
without a synced field are listed as skipped.

Usage
  python scripts/bbm_advance_sim.py [--portfolio FILE] [--sims 1000]
        [--tournament "best ball mania"] [--through 14] [--out report.md]
        [--json out.json] [--seed 1]
"""
import argparse, base64, json, math, os, random, re, subprocess, sys, tempfile, time, urllib.parse, urllib.request
from collections import OrderedDict
from statistics import NormalDist

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from grade_underdog_portfolio import Matcher, load_d  # noqa: E402

PROJECT = 'jackb933-website'
API_KEY = 'AIzaSyD9D_Rhb5hEpz2cBWqQr7hcFCDoluwq6uY'   # public web API key (see pull_consensus_adp.py)
FS_BASE = f'https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents'
PORTFOLIO_DOC = 'shared/jacks_portfolio'

BB_LINEUP = {'QB': 1, 'RB': 2, 'WR': 3, 'TE': 1, 'FLEX': 1}
BYE_2026 = {'ARI': 14, 'ATL': 11, 'BAL': 13, 'BUF': 7, 'CAR': 5, 'CHI': 10, 'CIN': 6, 'CLE': 11,
            'DAL': 14, 'DEN': 10, 'DET': 6, 'GB': 11, 'HOU': 8, 'IND': 13, 'JAX': 7, 'KC': 5,
            'LAC': 7, 'LAR': 11, 'LV': 13, 'MIA': 6, 'MIN': 6, 'NE': 11, 'NO': 8, 'NYG': 8,
            'NYJ': 13, 'PHI': 10, 'PIT': 9, 'SEA': 11, 'SF': 8, 'TB': 10, 'TEN': 9, 'WAS': 7}
# Contest rules mirrored from app.js _UD_CONTEST_RULES (regular-season round only).
CONTEST_RULES = [
    (re.compile(r'best\s*ball\s*mania', re.I), {'adv': 2, 'weeks': 14, 'advPrize': 25}),
    (re.compile(r'puppy', re.I), {'adv': 2, 'weeks': 14, 'advPrize': 5}),
]
DEFAULT_RULE = {'adv': 2, 'weeks': 14, 'advPrize': None}      # None = entry fee back
FINAL_WEEK_MIN_ROWS = 150        # a week with this many non-zero stat rows is in the books
DEFAULT_BOOM, DEFAULT_BUST = 25.0, 25.0
ND = NormalDist()


# ---------------------------------------------------------------- Firestore ----
def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode()


def _sa_access_token(sa):
    """OAuth2 access token from a service-account key via the JWT bearer flow
    (RS256 signed with the openssl CLI — no third-party Python packages)."""
    now = int(time.time())
    header = _b64url(json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode())
    claims = _b64url(json.dumps({
        'iss': sa['client_email'], 'scope': 'https://www.googleapis.com/auth/datastore',
        'aud': 'https://oauth2.googleapis.com/token', 'iat': now, 'exp': now + 3600}).encode())
    signing_input = f'{header}.{claims}'.encode()
    with tempfile.NamedTemporaryFile('w', suffix='.pem', delete=False) as kf:
        kf.write(sa['private_key'])
        key_path = kf.name
    try:
        sig = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', key_path],
                             input=signing_input, capture_output=True, check=True).stdout
    finally:
        os.unlink(key_path)
    jwt = f'{header}.{claims}.{_b64url(sig)}'
    body = urllib.parse.urlencode({'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                                   'assertion': jwt}).encode()
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=body,
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)['access_token'], ''


def _refresh_id_token(refresh_token):
    body = urllib.parse.urlencode({'grant_type': 'refresh_token', 'refresh_token': refresh_token}).encode()
    req = urllib.request.Request(f'https://securetoken.googleapis.com/v1/token?key={API_KEY}', data=body,
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)['id_token'], f'?key={API_KEY}'


def firestore_credential():
    sa_json = os.environ.get('MFF_FIREBASE_SA_JSON')
    sa_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if sa_json:
        return _sa_access_token(json.loads(sa_json)), 'service account (MFF_FIREBASE_SA_JSON)'
    if sa_path and os.path.exists(sa_path):
        return _sa_access_token(json.load(open(sa_path))), f'service account ({sa_path})'
    rt = os.environ.get('MFF_FIREBASE_REFRESH_TOKEN')
    if rt:
        return _refresh_id_token(rt), 'refresh token (MFF_FIREBASE_REFRESH_TOKEN)'
    return None, None


def fs_decode(v):
    """Firestore REST value -> plain Python."""
    if 'mapValue' in v:
        return {k: fs_decode(x) for k, x in (v['mapValue'].get('fields') or {}).items()}
    if 'arrayValue' in v:
        return [fs_decode(x) for x in (v['arrayValue'].get('values') or [])]
    for k in ('stringValue', 'booleanValue', 'doubleValue', 'referenceValue', 'timestampValue'):
        if k in v:
            return v[k]
    if 'integerValue' in v:
        return int(v['integerValue'])
    if 'nullValue' in v:
        return None
    return None


def fetch_portfolio_doc():
    res, label = firestore_credential()
    if not res:
        raise SystemExit('No Firestore credential in the environment (MFF_FIREBASE_SA_JSON, '
                         'GOOGLE_APPLICATION_CREDENTIALS or MFF_FIREBASE_REFRESH_TOKEN) and no --portfolio file.')
    cred, key_suffix = res
    req = urllib.request.Request(f'{FS_BASE}/{PORTFOLIO_DOC}{key_suffix}',
                                 headers={'Authorization': f'Bearer {cred}'})
    with urllib.request.urlopen(req, timeout=60) as r:
        doc = json.load(r)
    print(f'  fetched {PORTFOLIO_DOC} with {label}')
    return doc


# --------------------------------------------------------------- portfolio ----
def _norm_payload(obj):
    """Return {'drafts': [...], 'savedAt': ...} from any of the accepted shapes."""
    if isinstance(obj, dict) and 'fields' in obj and 'name' in obj:        # REST doc
        obj = fs_decode({'mapValue': {'fields': obj['fields']}})
    if isinstance(obj, dict) and 'underdogPortfolio' in obj:                # user_game_data doc
        obj = obj['underdogPortfolio']
    if isinstance(obj, dict) and isinstance(obj.get('drafts'), dict):       # window._udPortfolio dump
        return {'drafts': list(obj['drafts'].values()), 'savedAt': obj.get('savedAt')}
    if isinstance(obj, dict) and isinstance(obj.get('drafts'), list):
        return {'drafts': obj['drafts'], 'savedAt': obj.get('savedAt')}
    raise SystemExit('Unrecognised portfolio JSON shape (expected drafts list/object).')


def _pick_from_str(s, i):
    parts = str(s).split('|')
    name = parts[0]
    pos = parts[1] if len(parts) > 1 else ''
    team = parts[2] if len(parts) > 2 else ''
    try:
        pick = int(parts[3]) if len(parts) > 3 and parts[3] else i + 1
    except ValueError:
        pick = i + 1
    return {'name': name, 'pos': pos, 'team': team, 'pick': pick}


def field_teams(d):
    """List of {entryId, isMine, username, picks[]} for a draft, or None."""
    at = d.get('allTeams')
    if isinstance(at, dict) and len(at) >= 2:
        out = []
        for eid, t in at.items():
            picks = [{'name': p.get('name'), 'pos': p.get('pos', ''), 'team': p.get('team', ''),
                      'pick': p.get('pick', i + 1)} for i, p in enumerate(t.get('picks') or []) if p and p.get('name')]
            out.append({'entryId': str(t.get('entryId') or eid), 'isMine': bool(t.get('isMine')),
                        'username': t.get('username'), 'picks': picks})
        return out
    fld = d.get('field')
    if isinstance(fld, list) and len(fld) >= 2:
        out = []
        for t in fld:
            picks = [_pick_from_str(s, i) for i, s in enumerate(t.get('p') or [])]
            out.append({'entryId': str(t.get('e')), 'isMine': bool(t.get('m')), 'username': t.get('u'), 'picks': picks})
        return out
    return None


def rule_for(tournament):
    for rx, r in CONTEST_RULES:
        if rx.search(tournament or ''):
            return dict(r)
    return dict(DEFAULT_RULE)


# ----------------------------------------------------------------- scoring ----
class Scorer:
    def __init__(self, D, through):
        self.matcher = Matcher(D)
        src = open(os.path.join(ROOT, 'data', 'weekly_stats_active.js'), encoding='utf-8').read()
        self.W = json.loads(src[src.index('{'):src.rindex('}') + 1])
        self.SP = json.load(open(os.path.join(ROOT, 'data', 'sim_proj_2026.json'), encoding='utf-8'))
        self.through = through
        # weeks in the books: enough non-zero rows in the postgame feed
        counts = {}
        for v in self.W.values():
            for r in (v.get('seasons', {}).get('2026') or []):
                if (r.get('fpts') or 0) > 0:
                    counts[r['wk']] = counts.get(r['wk'], 0) + 1
        self.final_weeks = sorted(w for w, c in counts.items() if c >= FINAL_WEEK_MIN_ROWS and w <= through)
        self.sim_weeks = [w for w in range(1, through + 1) if w not in self.final_weeks]
        self._actual = {}
        self._dist = {}
        self.unmatched = set()

    # --- actual half-PPR points for a final week (0 if no row) ---
    def actual(self, site_name, wk):
        key = (site_name, wk)
        if key in self._actual:
            return self._actual[key]
        v = 0.0
        rows = (self.W.get(site_name) or {}).get('seasons', {}).get('2026')
        if rows:
            for r in rows:
                if r.get('wk') == wk and r.get('fpts') is not None:
                    v = float(r['fpts'])
                    break
        self._actual[key] = v
        return v

    # --- sampling distribution for a future week: (median, sigma_hi, sigma_lo) or None (=0) ---
    def dist(self, site_name, team, wk):
        key = (site_name, wk)
        if key in self._dist:
            return self._dist[key]
        row = (self.SP['weeks'].get(str(wk)) or {}).get(site_name)
        d = None
        if row is not None:
            med = float(row[0] or 0)
            boom, bust = row[3], row[4]
            if boom is None or bust is None or med <= 0:
                d = None                                   # ruled out / bye / zero projection
            else:
                d = (med,) + self._sigmas(boom, bust)
        else:
            in_any_week = any(site_name in (self.SP['weeks'].get(str(w)) or {}) for w in range(1, 19))
            if not in_any_week:
                sp = self.SP.get('seasonPpg', {}).get(site_name)
                if sp and float(sp[0] or 0) > 0 and BYE_2026.get((team or '').upper()) != wk:
                    d = (float(sp[0]),) + self._sigmas(DEFAULT_BOOM, DEFAULT_BUST)
        self._dist[key] = d
        return d

    @staticmethod
    def _sigmas(boom, bust):
        b = min(max(float(boom), 0.5), 49.0) / 100.0
        u = min(max(float(bust), 0.5), 49.0) / 100.0
        s_hi = math.log(1.5) / ND.inv_cdf(1 - b)
        s_lo = math.log(2.0) / ND.inv_cdf(1 - u)
        return (s_hi, s_lo)

    def resolve(self, pick):
        m = self.matcher.match(pick['name'])
        if not m:
            self.unmatched.add(pick['name'])
        name = m['n'] if m else pick['name']
        pos = (pick.get('pos') or (m.get('s') if m else '') or '').upper()
        team = (pick.get('team') or (m.get('t') if m else '') or '').upper()
        return name, pos, team


def best_ball(scores_by_pos):
    """scores_by_pos: {'QB': [..], 'RB': [..], 'WR': [..], 'TE': [..]} (unsorted)."""
    tot = 0.0
    rest = []
    for pos, n in (('QB', 1), ('RB', 2), ('WR', 3), ('TE', 1)):
        arr = sorted(scores_by_pos.get(pos, ()), reverse=True)
        tot += sum(arr[:n])
        if pos != 'QB':
            rest.extend(arr[n:])
    if rest:
        tot += max(rest)
    return tot


def simulate_pool(teams, scorer, rule, sims, rng):
    """teams: [{picks:[{name,pos,team}], isMine}] -> per-team stats."""
    through = min(rule['weeks'], scorer.through)
    final_weeks = [w for w in scorer.final_weeks if w <= through]
    sim_weeks = [w for w in scorer.sim_weeks if w <= through]
    prepared = []
    for t in teams:
        plist = []
        for pk in t['picks']:
            name, pos, team = scorer.resolve(pk)
            if pos not in ('QB', 'RB', 'WR', 'TE'):
                continue
            plist.append((name, pos, team))
        # points in the books
        base = 0.0
        for w in final_weeks:
            by = {'QB': [], 'RB': [], 'WR': [], 'TE': []}
            for name, pos, team in plist:
                by[pos].append(scorer.actual(name, w))
            base += best_ball(by)
        # per-week sampling table: list of (pos, dist) per player
        week_tabs = []
        for w in sim_weeks:
            tab = [(pos, scorer.dist(name, team, w)) for name, pos, team in plist]
            week_tabs.append(tab)
        prepared.append({'base': base, 'tabs': week_tabs})
    n = len(prepared)
    adv_n = rule['adv']
    adv_ct = [0] * n
    first_ct = [0] * n
    rank_sum = [0] * n
    ros_sum = [0.0] * n
    gauss = rng.gauss
    for _ in range(sims):
        totals = []
        for i, P in enumerate(prepared):
            tot = P['base']
            ros = 0.0
            for tab in P['tabs']:
                by = {'QB': [], 'RB': [], 'WR': [], 'TE': []}
                for pos, d in tab:
                    if d is None:
                        by[pos].append(0.0)
                        continue
                    z = gauss(0.0, 1.0)
                    med, s_hi, s_lo = d
                    by[pos].append(med * math.exp((s_hi if z >= 0 else s_lo) * z))
                ros += best_ball(by)
            ros_sum[i] += ros
            totals.append((tot + ros, rng.random(), i))
        totals.sort(reverse=True)
        for r, (_, _, i) in enumerate(totals):
            rank_sum[i] += r + 1
            if r < adv_n:
                adv_ct[i] += 1
            if r == 0:
                first_ct[i] += 1
    # current standings
    cur = sorted(range(n), key=lambda i: -prepared[i]['base'])
    cur_rank = {i: r + 1 for r, i in enumerate(cur)}
    cutoff_pts = prepared[cur[adv_n - 1]]['base'] if n >= adv_n else 0.0
    out = []
    for i, t in enumerate(teams):
        out.append({
            'entryId': t['entryId'], 'isMine': t['isMine'], 'username': t.get('username'),
            'pts': round(prepared[i]['base'], 1), 'rank': cur_rank[i],
            'ros_mean': round(ros_sum[i] / sims, 1),
            'p_adv': adv_ct[i] / sims, 'p_first': first_ct[i] / sims,
            'exp_rank': rank_sum[i] / sims,
            'gap_to_cut': round(prepared[i]['base'] - cutoff_pts, 1),
        })
    return out, final_weeks, sim_weeks


def poisson_binomial(ps):
    dist = [1.0]
    for p in ps:
        nxt = [0.0] * (len(dist) + 1)
        for k, v in enumerate(dist):
            nxt[k] += v * (1 - p)
            nxt[k + 1] += v * p
        dist = nxt
    return dist


# ------------------------------------------------------------------ report ----
def build_report(results, skipped, scorer, args, saved_at, sims):
    lines = []
    final = scorer.final_weeks
    lines.append(f'# BBM advance sim — {time.strftime("%Y-%m-%d")} · weeks {final[-1] if final else 0} final, '
                 f'simulating W{(final[-1] + 1) if final else 1}-W{args.through} · {sims:,} sims per pool')
    lines.append('')
    if saved_at:
        lines.append(f'Portfolio snapshot saved {saved_at}. ')
    lines.append(f'Sim Lab projections updated {scorer.SP.get("updated", "?")}. Scores drawn per player per week from the '
                 f'Sim Lab median with boom/bust-fitted spread; lineup QB/2RB/3WR/TE/FLEX; top {results[0]["rule"]["adv"] if results else 2} of each pool advance.')
    lines.append('')
    if not results:
        lines.append('**No pools could be simulated.** ' + (f'{len(skipped)} drafts had no synced field (open My Teams with the '
                     'Underdog Draft Helper extension running so the 11 opponents per draft reach the cloud).' if skipped else ''))
        return '\n'.join(lines)
    ps = [r['me']['p_adv'] for r in results]
    exp_adv = sum(ps)
    dist = poisson_binomial(ps)
    cum = []
    acc = 0.0
    for k in range(len(dist) - 1, -1, -1):
        acc += dist[k]
        cum.append((k, acc))
    cum = dict(cum)
    n = len(results)
    base_adv = n * results[0]['rule']['adv'] / 12.0
    money = sum(r['me']['p_adv'] * (r['rule']['advPrize'] if r['rule']['advPrize'] is not None else (r['fee'] or 0)) for r in results)
    lines.append('## Portfolio')
    lines.append('')
    lines.append(f'- **Pools simulated:** {n}' + (f' ({len(skipped)} skipped, no synced field)' if skipped else ''))
    lines.append(f'- **Expected advances:** {exp_adv:.1f} of {n} ({100 * exp_adv / n:.1f}% per team; field baseline {100 * results[0]["rule"]["adv"] / 12:.1f}% → {base_adv:.1f} teams)')
    lines.append(f'- **Currently in an advance spot:** {sum(1 for r in results if r["me"]["rank"] <= r["rule"]["adv"])} of {n}')
    lines.append(f'- **Expected min-cash from advancing:** ${money:,.0f}')
    ks = sorted(set([max(0, int(round(exp_adv)) - 3), max(0, int(round(exp_adv))), int(round(exp_adv)) + 3, int(round(base_adv))]))
    lines.append('- **P(at least k advance):** ' + ' · '.join(f'{k}: {100 * cum.get(k, 0):.0f}%' for k in ks if k <= n))
    lines.append('')
    lines.append('## Teams, best advance odds first')
    lines.append('')
    lines.append('| # | P(adv) | P(1st) | Now | Pts | Gap to cut | ROS proj | Exp finish | Tournament | Draft date | Draft |')
    lines.append('|---|---|---|---|---|---|---|---|---|---|---|')
    for i, r in enumerate(sorted(results, key=lambda r: -r['me']['p_adv']), 1):
        m = r['me']
        gap = f"+{m['gap_to_cut']}" if m['gap_to_cut'] > 0 else f"{m['gap_to_cut']}"
        lines.append(f"| {i} | {100 * m['p_adv']:.0f}% | {100 * m['p_first']:.0f}% | {m['rank']}/{r['n']} | {m['pts']} | {gap} | {m['ros_mean']} "
                     f"| {m['exp_rank']:.1f} | {r['tournament']} | {r['date'][:10]} | {r['id'][:8]} |")
    lines.append('')
    lines.append('Gap to cut = my points minus the current 2nd-place total (positive = inside the line). ROS proj = mean of simulated points from the next week through W14.')
    if scorer.unmatched:
        lines.append('')
        lines.append(f'Unmatched names scored as 0 ({len(scorer.unmatched)}): ' + ', '.join(sorted(scorer.unmatched)[:40]) +
                     (' …' if len(scorer.unmatched) > 40 else ''))
    if skipped:
        lines.append('')
        lines.append('Skipped (no opponent rosters synced): ' + ', '.join(f"{d['tournament']} {d['date'][:10]} {d['id'][:8]}" for d in skipped[:30]) +
                     (' …' if len(skipped) > 30 else ''))
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--portfolio', help='portfolio JSON (else fetched from Firestore with the env credential)')
    ap.add_argument('--sims', type=int, default=1000)
    ap.add_argument('--tournament', default='best ball mania', help='substring filter on tournament title ("" = all)')
    ap.add_argument('--through', type=int, default=14, help='last regular-season week of the round')
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--out', help='write the Markdown report here')
    ap.add_argument('--json', help='dump per-pool results here')
    ap.add_argument('--include-opponents', action='store_true', help='keep every pool team in the JSON dump')
    args = ap.parse_args()

    if args.portfolio:
        payload = _norm_payload(json.load(open(args.portfolio, encoding='utf-8')))
        print(f'  portfolio from {args.portfolio}: {len(payload["drafts"])} drafts')
    else:
        payload = _norm_payload(fetch_portfolio_doc())
        print(f'  portfolio: {len(payload["drafts"])} drafts, saved {payload.get("savedAt")}')

    D = load_d()
    scorer = Scorer(D, args.through)
    print(f'  final weeks: {scorer.final_weeks}  sim weeks: {scorer.sim_weeks}')
    rng = random.Random(args.seed)

    results, skipped = [], []
    filt = (args.tournament or '').lower()
    t0 = time.time()
    for d in payload['drafts']:
        if filt and filt not in (d.get('tournament') or '').lower():
            continue
        if (d.get('phase') or 'pre') == 'superflex':
            continue
        teams = field_teams(d)
        if not teams:
            skipped.append(d)
            continue
        my_names = {p.get('name') for p in (d.get('picks') or []) if p}
        mine = [t for t in teams if t['isMine']]
        if not mine and d.get('myEntryId') is not None:
            mine = [t for t in teams if t['entryId'] == str(d['myEntryId'])]
        if not mine and my_names:
            mine = [max(teams, key=lambda t: len(my_names & {p['name'] for p in t['picks']}))]
        if not mine:
            skipped.append(d)
            continue
        for t in teams:
            t['isMine'] = (t is mine[0])
        rule = rule_for(d.get('tournament'))
        stats, fw, sw = simulate_pool(teams, scorer, rule, args.sims, rng)
        me = next(s for s in stats if s['isMine'])
        results.append({'id': d.get('id', ''), 'tournament': d.get('tournament', ''), 'date': d.get('date') or '',
                        'fee': d.get('fee'), 'rule': rule, 'n': len(stats), 'me': me,
                        'teams': stats if args.include_opponents else None})
    print(f'  simulated {len(results)} pools in {time.time() - t0:.0f}s; skipped {len(skipped)}')

    report = build_report(results, skipped, scorer, args, payload.get('savedAt'), args.sims)
    print()
    print(report)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        open(args.out, 'w', encoding='utf-8').write(report + '\n')
        print(f'\nwrote {args.out}')
    if args.json:
        json.dump({'generated': time.strftime('%Y-%m-%dT%H:%M:%S'), 'final_weeks': scorer.final_weeks,
                   'sim_weeks': scorer.sim_weeks, 'sims': args.sims, 'pools': results,
                   'skipped': [d.get('id') for d in skipped]},
                  open(args.json, 'w', encoding='utf-8'), indent=1)
        print(f'wrote {args.json}')
    if not results:
        sys.exit(2)


if __name__ == '__main__':
    main()
