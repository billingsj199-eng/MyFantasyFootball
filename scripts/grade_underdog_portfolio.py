#!/usr/bin/env python3
"""
grade_underdog_portfolio.py — grade every team in an Underdog best ball
portfolio the way My Teams does, off Jack's REDRAFT (rest-of-season) board.

Reproduces the site's My Teams → Underdog scoring path exactly:
  * _udMatchPlayer      — Underdog name -> d.js player (exact / suffix-stripped /
                          case-insensitive / first-initial+last-name tiers)
  * _mtGetPlayerRank    — rank on the chosen board (999 off-board; OUT-for-season
                          IR flag => 999 in single-season modes)
  * _getTradeValue      — win-now value: max(500 − rank, 0) × 0.5 × 0.85^tierIdx
                          (+ (1000 − rank)/1000 strict-order epsilon), tierIdx from
                          the board's own ALL tiers when it has ≥ 8 boundaries,
                          else the 20-break pseudo-ladder (window._WINNOW_VAL)
  * _udScoreTeam        — team total = Σ player values, QB/RB/WR/TE breakdown
  * _mtGrade            — letter grade off the roster's AVERAGE board rank
                          (A+ ≤ 40 … F > 300; redraft shift 0)

Inputs
  --csv FILE [FILE ...]   Underdog "My Drafts → Download CSV" exports. Several
                          files merge into one portfolio (dedupe by Draft id,
                          later file wins — same as the site's uploader).
                          Append ":pre" / ":nfl" / ":superflex" to tag the phase
                          (e.g. bbm_post_draft.csv:nfl). Default phase: pre.
  --board FILE            Jack's board, any of:
                            * rankings doc JSON — the Firestore rankings/jacks-official
                              document (REST shape, or the raw `data` string, or the
                              parsed {"jacks":{"redraft":{"_order":[...],"_posTiers":{...}}}})
                            * the site's UNDERDOG CSV export of the REDRAFT board
                              (rows are board order; firstName/lastName columns)
                            * a plain text file, one player name per line in board order
                          Without --board the script falls back to the public
                          rankings/jacks-public slice (top 36, live) and fills
                          ranks 37+ from d.js `a` (Jack's PRESEASON board) — and
                          says so loudly, because that is NOT the live ROS board.
  --mode redraft|bestball|superflex   which board inside a rankings doc (default
                          redraft — the rest-of-season board My Teams scores on).
  --tournament TEXT       only drafts whose Tournament Title contains TEXT
                          (case-insensitive), e.g. "Best Ball Mania".
  --top N                 how many teams to print in full (default 10).
  --out FILE              also write a Markdown report.
  --json FILE             also dump every graded team as JSON.

Example
  python scripts/grade_underdog_portfolio.py \
      --csv ~/Downloads/underdog_bbm.csv:nfl --board ~/Downloads/jacks_redraft.json \
      --tournament "Best Ball Mania" --top 15 --out bbm_grades.md
"""
import argparse, csv, io, json, os, re, sys, urllib.request
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# ---- site constants (app.js window._WINNOW_VAL / _mtGrade) -------------------
WN_ZERO = 500
WN_SLOPE = 0.5
WN_TIER_DROP = 0.15
WN_PSEUDO_TIERS = [1, 5, 9, 13, 19, 26, 30, 34, 46, 59, 67, 76, 86, 96, 109, 118, 137, 157, 175, 192]
WN_MIN_TIERS = 8          # board tiers drive the ladder only when this dense
GRADE_STEPS = [(40, 'A+'), (60, 'A'), (80, 'A-'), (100, 'B+'), (120, 'B'), (150, 'B-'),
               (180, 'C+'), (210, 'C'), (250, 'C-'), (300, 'D')]
PUBLIC_DOC = ('https://firestore.googleapis.com/v1/projects/jackb933-website/'
              'databases/(default)/documents/rankings/jacks-public'
              '?key=AIzaSyD9D_Rhb5hEpz2cBWqQr7hcFCDoluwq6uY')
SUFFIX_RE = re.compile(r'\s+(Jr\.?|Sr\.?|III|II|IV|V)$', re.I)


def grade_letter(avg_rank):
    for cut, g in GRADE_STEPS:
        if avg_rank <= cut:
            return g
    return 'F'


# ---- d.js ---------------------------------------------------------------------
def load_d():
    src = open(os.path.join(ROOT, 'data', 'd.js'), encoding='utf-8').read()
    return json.loads(src[src.index('['):src.rindex(']') + 1])


class Matcher:
    """Port of _udMatchPlayerUncached: active players first, then retired."""
    def __init__(self, D):
        self.D = D
        self.cache = {}

    def _try(self, name, allow_retired):
        filt = (lambda p: allow_retired or not p.get('_retired'))
        for p in self.D:
            if filt(p) and p.get('n') == name:
                return p
        stripped = SUFFIX_RE.sub('', name).strip()
        for p in self.D:
            n = p.get('n')
            if filt(p) and n and (n == stripped or SUFFIX_RE.sub('', n).strip() == stripped):
                return p
        lower = name.lower()
        for p in self.D:
            if filt(p) and p.get('n') and p['n'].lower() == lower:
                return p
        parts = name.split(' ')
        if len(parts) >= 2:
            fi = parts[0][0].lower()
            last = parts[-1].lower().replace('.', '')
            for p in self.D:
                if not filt(p) or not p.get('n'):
                    continue
                pp = p['n'].split(' ')
                if len(pp) >= 2 and pp[0][0].lower() == fi and pp[-1].lower().replace('.', '') == last:
                    return p
        return None

    def match(self, name):
        if not name:
            return None
        if name in self.cache:
            return self.cache[name]
        m = self._try(name, False) or self._try(name, True)
        self.cache[name] = m
        return m


# ---- board loading ------------------------------------------------------------
class Board:
    def __init__(self, order, tiers=None, label='', ir=None, notes=None):
        self.order = list(order)
        self.rank = {n: i + 1 for i, n in enumerate(self.order)}
        self.tiers = sorted(tiers or [], key=lambda t: t['afterRank'])
        self.label = label
        self.ir = ir or {}
        self.notes = notes or []
        self.use_board_tiers = len(self.tiers) >= WN_MIN_TIERS

    def rank_of(self, site_name):
        if site_name in self.ir:
            return 999
        return self.rank.get(site_name, 999)

    def tier_index(self, rank):
        if rank >= 999:
            return None
        if self.use_board_tiers:
            idx = -1
            for i, t in enumerate(self.tiers):
                if t['afterRank'] <= rank:
                    idx = i
            return idx if idx >= 0 else None
        idx = 0
        for i, start in enumerate(WN_PSEUDO_TIERS):
            if start <= rank:
                idx = i
            else:
                break
        return idx

    def value(self, rank):
        """_getTradeValue single-season branch (float, display rounds later)."""
        if rank >= 999:
            return 1.0
        ti = self.tier_index(rank)
        tf = 1.0 if ti is None else (1 - WN_TIER_DROP) ** ti
        val = max(WN_ZERO - rank, 0) * WN_SLOPE * tf
        val += (1000 - rank) * 0.001
        return max(val, 1.0)


def fetch_public_doc():
    try:
        with urllib.request.urlopen(PUBLIC_DOC, timeout=20) as r:
            return json.load(r)
    except Exception as e:  # noqa
        print(f'  ! could not fetch rankings/jacks-public: {e}', file=sys.stderr)
        return None


def _parse_rankings_doc(obj, mode):
    """Accept the REST doc, {data:'...'}, the raw data string, or the parsed data."""
    ir = {}
    if isinstance(obj, dict) and 'fields' in obj:              # Firestore REST shape
        f = obj['fields']
        if 'ir' in f:
            try:
                ir = json.loads(f['ir'].get('stringValue') or '{}')
            except Exception:
                ir = {}
        obj = f['data']['stringValue']
    if isinstance(obj, dict) and 'data' in obj and isinstance(obj['data'], str):
        if isinstance(obj.get('ir'), str):
            try:
                ir = json.loads(obj['ir'])
            except Exception:
                pass
        obj = obj['data']
    if isinstance(obj, str):
        obj = json.loads(obj)
    boards = obj.get('jacks', obj)
    if mode not in boards:
        raise SystemExit(f'board JSON has no "{mode}" board (has: {", ".join(boards.keys())})')
    b = boards[mode]
    order = b.get('_order') or []
    tiers = ((b.get('_posTiers') or {}).get('ALL')) or []
    return order, tiers, ir


def load_board(path, mode, D):
    public = fetch_public_doc()
    ir = {}
    if public:
        try:
            ir = json.loads(public['fields'].get('ir', {}).get('stringValue') or '{}')
        except Exception:
            ir = {}
    notes = []
    if path:
        text = open(path, encoding='utf-8-sig').read()
        stripped = text.lstrip()
        if stripped.startswith('{'):
            order, tiers, ir2 = _parse_rankings_doc(json.loads(text), mode)
            ir = ir2 or ir
            label = f'{os.path.basename(path)} ({mode} board, {len(order)} names, {len(tiers)} tier breaks)'
        elif stripped.lower().startswith('"id"') or stripped.lower().startswith('id,'):
            rows = list(csv.DictReader(io.StringIO(text)))
            order = [((r.get('firstName') or '') + ' ' + (r.get('lastName') or '')).strip() for r in rows]
            tiers = []
            label = f'{os.path.basename(path)} (site Underdog CSV export, {len(order)} rows)'
            notes.append('Tiers are not in the CSV export — the pseudo-ladder prices tiers (the site would use the live board tiers).')
        else:
            order = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith('#')]
            order = [re.sub(r'^\d+[.)]?\s+', '', n) for n in order]
            tiers = []
            label = f'{os.path.basename(path)} (plain list, {len(order)} names)'
            notes.append('Tiers unknown for a plain list — the pseudo-ladder prices tiers.')
        # Names in an export may be Underdog spellings — resolve to site names.
        m = Matcher(D)
        resolved = []
        seen = set()
        for n in order:
            p = m.match(n)
            site = p['n'] if p else n
            if site not in seen:
                seen.add(site)
                resolved.append(site)
        return Board(resolved, tiers, label, ir, notes)

    # ---- fallback: public top slice + d.js preseason `a` ----
    order, tiers = [], []
    if public:
        try:
            order, tiers, _ = _parse_rankings_doc(public, mode)
        except SystemExit as e:
            print(f'  ! {e}', file=sys.stderr)
    pre = sorted([p for p in D if isinstance(p.get('a'), (int, float)) and p.get('s') not in ('K', 'DST')],
                 key=lambda p: p['a'])
    seen = set(order)
    filled = 0
    for p in pre:
        if p['n'] not in seen:
            order.append(p['n'])
            seen.add(p['n'])
            filled += 1
    notes.append(f'FALLBACK BOARD: live public slice = top {len(order) - filled} only; ranks '
                 f'{len(order) - filled + 1}+ come from d.js `a` (Jack\'s PRESEASON board). '
                 'Pass --board with an export of rankings/jacks-official for the real ROS grades.')
    return Board(order, tiers, f'jacks-public top {len(order) - filled} + d.js preseason', ir, notes)


# ---- Underdog CSV ---------------------------------------------------------------
REQ = ['Pick Number', 'First Name', 'Last Name', 'Position', 'Draft', 'Tournament Title',
       'Tournament Entry Fee', 'Draft Size']


def parse_underdog_csv(path, phase):
    text = open(path, encoding='utf-8-sig').read()
    rdr = csv.DictReader(io.StringIO(text))
    heads = [h.strip() for h in (rdr.fieldnames or [])]
    missing = [c for c in REQ if c not in heads]
    if missing:
        raise SystemExit(f'{path}: missing column(s) {missing} — is this an Underdog My Drafts export?')
    drafts = OrderedDict()
    for row in rdr:
        row = {(k or '').strip(): (v or '').strip() for k, v in row.items()}
        did = row.get('Draft', '')
        if not did:
            continue
        name = (row.get('First Name', '') + ' ' + row.get('Last Name', '')).strip()
        if not name:
            continue
        d = drafts.get(did)
        if d is None:
            try:
                fee = float(row.get('Tournament Entry Fee') or 0)
            except ValueError:
                fee = 0.0
            d = drafts[did] = {
                'id': did, 'tournament': row.get('Tournament Title', ''), 'fee': fee,
                'size': int(row.get('Draft Size') or 12), 'date': row.get('Picked At', ''),
                'phase': phase, 'entry': row.get('Draft Entry', ''), 'picks': []}
        try:
            pick = int(row.get('Pick Number') or 0)
        except ValueError:
            pick = 0
        d['picks'].append({'name': name, 'pos': row.get('Position', ''), 'team': row.get('Team', ''), 'pick': pick})
    for d in drafts.values():
        d['picks'].sort(key=lambda p: p['pick'])
    return drafts


# ---- scoring --------------------------------------------------------------------
def score_team(draft, board, matcher):
    players = []
    for pk in draft['picks']:
        m = matcher.match(pk['name'])
        site = m['n'] if m else pk['name']
        rank = board.rank_of(site) if m else 999
        val = board.value(rank) if m else 1.0
        players.append({'name': site, 'ud_name': pk['name'], 'rank': rank, 'val': val,
                        'pos': (m.get('s') if m else pk['pos']) or pk['pos'],
                        'team': (m.get('t') if m else pk['team']) or pk['team'],
                        'pick': pk['pick'], 'matched': bool(m),
                        'out': site in board.ir})
    players.sort(key=lambda p: (-p['val'], p['rank']))
    total = sum(p['val'] for p in players)
    pos = {}
    for ps in ('QB', 'RB', 'WR', 'TE'):
        g = [p for p in players if p['pos'] == ps]
        pos[ps] = {'pts': round(sum(p['val'] for p in g)), 'count': len(g)}
    ranked = [p['rank'] for p in players if p['rank'] < 999]
    avg_rank = (sum(ranked) + 999 * (len(players) - len(ranked))) / len(players) if players else 999
    avg_rank_ranked = sum(ranked) / len(ranked) if ranked else 999
    return {'total': round(total), 'players': players, 'pos': pos,
            'avg_rank': avg_rank, 'avg_rank_ranked': avg_rank_ranked,
            'grade': grade_letter(avg_rank), 'unranked': len(players) - len(ranked)}


def fmt_player(p):
    tag = ' OUT' if p['out'] else ('' if p['matched'] else ' ?')
    r = '—' if p['rank'] >= 999 else str(p['rank'])
    return f"{p['name']} ({p['pos']} #{r}, {round(p['val'])}){tag}"


def build_report(graded, board, args, num_drafts_all):
    lines = []
    lines.append(f'# Underdog portfolio grades — {board.label}')
    lines.append('')
    lines.append(f'Scoring: My Teams win-now curve (500−rank × 0.5 × 0.85^tier), grade = avg board rank. '
                 f'{len(graded)} drafts graded' + (f' of {num_drafts_all} in the files' if num_drafts_all != len(graded) else '') + '.')
    for n in board.notes:
        lines.append(f'> **Note:** {n}')
    lines.append('')
    lines.append('| # | Grade | Total | Avg rank | QB | RB | WR | TE | Tournament | Date | Draft |')
    lines.append('|---|---|---|---|---|---|---|---|---|---|---|')
    for i, g in enumerate(graded, 1):
        d, s = g['draft'], g['score']
        lines.append(f"| {i} | {s['grade']} | {s['total']} | {s['avg_rank']:.1f} | {s['pos']['QB']['pts']} ({s['pos']['QB']['count']}) "
                     f"| {s['pos']['RB']['pts']} ({s['pos']['RB']['count']}) | {s['pos']['WR']['pts']} ({s['pos']['WR']['count']}) "
                     f"| {s['pos']['TE']['pts']} ({s['pos']['TE']['count']}) | {d['tournament']} | {d['date'][:10]} | {d['id'][:8]} |")
    lines.append('')
    lines.append(f'## Top {min(args.top, len(graded))} teams in full')
    for i, g in enumerate(graded[:args.top], 1):
        d, s = g['draft'], g['score']
        lines.append('')
        lines.append(f"### {i}. {s['grade']} · {s['total']} pts · avg rank {s['avg_rank']:.1f} — {d['tournament']} ({d['date'][:10]}, draft {d['id'][:8]})")
        by_pos = {}
        for p in s['players']:
            by_pos.setdefault(p['pos'], []).append(p)
        for ps in ('QB', 'RB', 'WR', 'TE'):
            if by_pos.get(ps):
                lines.append(f"- **{ps} ({s['pos'][ps]['pts']})**: " + ', '.join(fmt_player(p) for p in by_pos[ps]))
        others = [p for ps, lst in by_pos.items() if ps not in ('QB', 'RB', 'WR', 'TE') for p in lst]
        if others:
            lines.append('- **Other**: ' + ', '.join(fmt_player(p) for p in others))
    # portfolio summary
    if graded:
        grades = {}
        for g in graded:
            grades[g['score']['grade']] = grades.get(g['score']['grade'], 0) + 1
        order = [g for _, g in GRADE_STEPS] + ['F']
        lines.append('')
        lines.append('## Portfolio grade mix')
        lines.append(', '.join(f'{k}: {grades[k]}' for k in order if k in grades))
        avg_total = sum(g['score']['total'] for g in graded) / len(graded)
        lines.append(f'Average team total {avg_total:.0f}; best {graded[0]["score"]["total"]}, worst {graded[-1]["score"]["total"]}.')
    unmatched = sorted({p['ud_name'] for g in graded for p in g['score']['players'] if not p['matched']})
    if unmatched:
        lines.append('')
        lines.append('## Unmatched Underdog names (scored as 1 pt, rank 999)')
        lines.append(', '.join(unmatched))
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--csv', nargs='+', required=True, help='Underdog export CSV(s), optionally FILE:phase')
    ap.add_argument('--board', help="Jack's board export (rankings doc JSON / site Underdog CSV / name list)")
    ap.add_argument('--mode', default='redraft', choices=['redraft', 'bestball', 'superflex'])
    ap.add_argument('--tournament', help='only drafts whose tournament title contains this text')
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--out', help='write Markdown report here')
    ap.add_argument('--json', help='dump graded teams as JSON here')
    args = ap.parse_args()

    D = load_d()
    matcher = Matcher(D)
    board = load_board(args.board, args.mode, D)
    print(f'Board: {board.label}; tiers: ' + ('board ALL tiers' if board.use_board_tiers else 'pseudo-ladder') +
          f'; IR-out flags: {len(board.ir)}')
    for n in board.notes:
        print('  ! ' + n)

    drafts = OrderedDict()
    for spec in args.csv:
        path, _, phase = spec.rpartition(':')
        if not path or not os.path.exists(path):      # no ":phase" suffix (or Windows drive colon)
            path, phase = spec, 'pre'
        if phase not in ('pre', 'nfl', 'superflex'):
            phase = 'pre'
        got = parse_underdog_csv(path, phase)
        drafts.update(got)                             # later file wins on the same draft id
        print(f'  {os.path.basename(path)}: {len(got)} drafts ({phase})')
    num_all = len(drafts)
    if args.tournament:
        t = args.tournament.lower()
        drafts = OrderedDict((k, v) for k, v in drafts.items() if t in v['tournament'].lower())

    graded = [{'draft': d, 'score': score_team(d, board, matcher)} for d in drafts.values()]
    graded.sort(key=lambda g: -g['score']['total'])
    if not graded:
        raise SystemExit('No drafts to grade (check --tournament filter).')

    report = build_report(graded, board, args, num_all)
    print()
    print(report)
    if args.out:
        open(args.out, 'w', encoding='utf-8').write(report + '\n')
        print(f'\nwrote {args.out}')
    if args.json:
        json.dump([{'draft': g['draft'], 'score': g['score']} for g in graded],
                  open(args.json, 'w', encoding='utf-8'), indent=1)
        print(f'wrote {args.json}')


if __name__ == '__main__':
    main()
