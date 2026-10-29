#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_player_cutouts.py — era-correct transparent player cutouts for the Trivia page.

For every player who can appear on a board (LEGEND_CAREERS + ALL_PLAYERS_DB) and
every team he played for, find the best FREE photo of him in that team's uniform on
Wikimedia Commons (Category:<Name> files + File-namespace search + the photo the
legend builder already picked), download it, remove the background, crop to ESPN
head-and-shoulders framing with the drop-folder cutter (scripts/make_legend_headshots.cut)
and save a 350x254 transparent WebP under img/cutouts/<slug>/<TEAM>.webp with a
credits.json sidecar. data/player_cutouts.js indexes them:

  window.PLAYER_CUTOUTS = {
    "Emmitt Smith": { "byTeam": { "DAL": {"src": "img/cutouts/emmitt-smith/DAL.webp",
                                          "credit": "Artist · License", "yr": 1993,
                                          "file": "File:…" } },
                      "default": "DAL" } }

The reveal (_triviaGetHeadshotInfo in app.js) takes byTeam[cell team] first, then the
team the player had in the board's year, then the entry nearest the board's year.

Free sources only (Jack's rule for the public site): Commons files only, and Flickr
only through the API with a free licence filter (CC BY / CC BY-SA / CC0 / PDM /
no known restrictions) when --flickr-key is given. Getty / AP / team-site photos are
never fetched; a player with no free in-uniform photo stays uncovered and shows up
in the coverage report.

Guards (same spirit as build_legend_headshots.py): the file must name the player
(full name in loose search hits, surname for category files), no relatives /
memorials / other sports, a team word or a date inside the player's career with
that team; group photos (2+ faces or a matte split across people), tiny subjects and
headless crops are rejected and the next candidate is tried.

Resumable: every candidate list and cut result lives in
<cache>/search_state.json + cut_state.json (cache default E:/MyFantasyFootball/cutout_cache, override
MFF_CUTOUT_CACHE); source photos and PNG masters are cached there too, outside the
repo. Players are processed best-season-first so the top-150 seasons get covered
before the long tail.

Usage:
  python -I scripts/build_player_cutouts.py                  # search + cut everything pending
  python -I scripts/build_player_cutouts.py --names "Emmitt Smith" "Marshall Faulk"
  python -I scripts/build_player_cutouts.py --limit 300      # first 300 players by peak season
  python -I scripts/build_player_cutouts.py --search-only / --cut-only
  python -I scripts/build_player_cutouts.py --write          # only rewrite index + credits + report
  python -I scripts/build_player_cutouts.py --report         # coverage report only
  python -I scripts/build_player_cutouts.py --flickr-key KEY # add Flickr CC candidates
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_legend_headshots as blh  # noqa: E402
import legend_teams as lt             # noqa: E402

ROOT = blh.ROOT
DATA = blh.DATA
IMG_DIR = os.path.join(ROOT, 'img', 'cutouts')
INDEX = os.path.join(DATA, 'player_cutouts.js')
REPORT = os.path.join(ROOT, 'scripts', 'cutout_coverage_report.md')
CREDITS_PAGE = os.path.join(IMG_DIR, 'credits.html')
CACHE = os.environ.get('MFF_CUTOUT_CACHE', r'E:\MyFantasyFootball\cutout_cache')
# state lives in search_state.json + cut_state.json (see load_state)
SRC_DIR = os.path.join(CACHE, 'src')
PNG_DIR = os.path.join(CACHE, 'png')
ALL_PLAYERS = os.path.join(DATA, 'all_players.js')
LEGEND_HS = os.path.join(DATA, 'legend_headshots.js')

SRC_WIDTH = 1200          # Commons thumb width fetched for cutting
OUT_W, OUT_H = 300, 218   # repo WebP size (ESPN 350:254 framing; cells render ≤150px)
WEBP_Q = 76
SEARCH_LIMIT = 25
CAT_LIMIT = 150
TRIES_PER_TEAM = 3
FLICKR_FREE_LICENSES = '4,5,7,9,10'   # CC BY 2.0, CC BY-SA 2.0, no known restrictions, CC0, PDM

PORTRAIT_RE = re.compile(r'\b(portrait|headshot|head shot|close[- ]?up|poses|posing|smiles|smiling|press conference|media day|interview|sideline|warm[- ]?ups?|pregame|pre-game|training camp|minicamp|practice|signing autographs|topps|fleer|bowman|card)\b', re.I)
CROWD_RE = re.compile(r'\b(team photo|group|teammates|celebrat\w*|huddle|line of scrimmage|pile|crowd|fans|parade|ceremony|banquet|dinner|gala|wedding)\b', re.I)
COLLEGE_RE = re.compile(r'\b(college|university|ncaa|bowl game|high school|combine|pro day|senior bowl)\b', re.I)


# ------------------------------------------------------------- players ----
def load_all_players():
    src = open(ALL_PLAYERS, encoding='utf-8').read()
    m = re.search(r'ALL_PLAYERS_DB\s*=\s*(\[.*\])\s*;?\s*$', src, re.S)
    if not m:
        raise SystemExit('could not parse ' + ALL_PLAYERS)
    return json.loads(m.group(1))


def load_legend_headshots():
    if not os.path.exists(LEGEND_HS):
        return {}
    src = open(LEGEND_HS, encoding='utf-8').read()
    m = re.search(r'LEGEND_HEADSHOTS\s*=\s*(\{.*\})\s*;?\s*$', src, re.S)
    return json.loads(m.group(1)) if m else {}


def stints(seasons):
    """[{tm, y1, y2, mid}] contiguous team runs from the per-season tm (canonical)."""
    by = blh.team_by_year(seasons)
    out = []
    for yr in sorted(by):
        t = by[yr]
        if out and out[-1]['tm'] == t and yr - out[-1]['y2'] <= 1:
            out[-1]['y2'] = yr
        else:
            out.append({'tm': t, 'y1': yr, 'y2': yr})
    for s in out:
        s['mid'] = (s['y1'] + s['y2']) // 2
    return out


def build_players(careers, allp):
    """name -> {seasons, stints, teams, peak, notable, last}"""
    players = {}
    for name, se in careers.items():
        players[name] = se
    for p in allp:
        n = p.get('name')
        if n and n not in players and p.get('career'):
            players[n] = p['career']
    out = {}
    for name, se in players.items():
        st = stints(se)
        if not st:
            continue
        peak = max((s.get('fpts') or 0) for s in se)
        out[name] = {
            'seasons': se, 'stints': st, 'teams': sorted({s['tm'] for s in st}),
            'peak': peak, 'notable': blh.is_notable(se),
            'last': max(s.get('yr') or 0 for s in se),
            'primary': max((s['tm'] for s in st), key=lambda t: sum(1 for s in se if blh.canon_tm(s.get('tm'), s.get('yr')) == t)),
        }
    return out


# --------------------------------------------------------------- state ----
SEARCH_STATE = os.path.join(CACHE, 'search_state.json')   # searched / cands / flickr / done
CUT_STATE = os.path.join(CACHE, 'cut_state.json')         # cuts
# (two files so a --search-only and a --cut-only process can run side by side)


def _read_json(path, default):
    for attempt in range(5):
        try:
            if os.path.exists(path):
                return json.load(open(path, encoding='utf-8'))
            return default
        except (ValueError, OSError):
            time.sleep(0.5)     # the other process is mid-replace
    return default


def load_state():
    st = {'searched': {}, 'cands': {}, 'flickr': {}, 'done': False}
    st.update(_read_json(SEARCH_STATE, {}))
    st.update(_read_json(CUT_STATE, {'cuts': {}}))
    st.setdefault('cuts', {})
    return st


def reload_search(state):
    """Pick up what a concurrent --search-only process has added."""
    fresh = _read_json(SEARCH_STATE, {})
    for k in ('searched', 'cands', 'flickr', 'done'):
        if k in fresh:
            state[k] = fresh[k]


def _write_json(path, obj):
    os.makedirs(CACHE, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


def save_state(state, which='both'):
    if which in ('both', 'search'):
        _write_json(SEARCH_STATE, {k: state[k] for k in ('searched', 'cands', 'flickr', 'done')})
    if which in ('both', 'cut'):
        _write_json(CUT_STATE, {'cuts': state['cuts']})


# -------------------------------------------------------------- search ----
def commons_file_from_url(url):
    """upload.wikimedia.org (thumb or original) -> 'File:Name.jpg'."""
    f = blh.file_from_thumb(url)
    if f:
        return f
    m = re.search(r'/wikipedia/commons/[0-9a-f]/[0-9a-f]{2}/([^/?]+)$', url or '')
    return 'File:' + urllib.parse.unquote(m.group(1)).replace('_', ' ') if m else None


def score_file(name, info, ft, fi, for_search):
    """Accept/score one Commons file for a player. Returns None or
    {file, url, credit, year, teams:{T:score}, text, portrait}."""
    if not fi or not fi.get('thumb') or not fi.get('shared'):
        return None
    if not fi['mime'].startswith('image/') or 'svg' in fi['mime'] or 'gif' in fi['mime']:
        return None
    fname = ft[5:].replace('_', ' ')
    if blh.JUNK_FILE_RE.search(fname):
        return None
    text = (fname + ' ' + fi['desc']).lower()
    full = name.lower()
    fl = fname.lower()
    # The player must be named in the FILE NAME (a description that merely mentions him —
    # "Derek Smith tackles Steven Jackson" — is a photo of someone else). Loose search
    # hits need the full name; files from his own Commons category need the surname.
    if for_search:
        if full not in fl and blh._name_key(name) not in blh._name_key(fl):
            return None
    else:
        if blh.surname(name) not in fl and blh._name_key(name) not in blh._name_key(fl):
            return None
    if blh.RELATIVE_RE.search(text) or blh.MEMORIAL_RE.search(text):
        return None
    if blh.OTHER_SPORT_RE.search(text) and not blh.FOOTBALL_WORD_RE.search(text):
        return None
    by_year = info['by_year']
    my_teams = set(by_year.values())
    years = set(by_year)
    tags = {}
    for m in blh.TEAM_WORD_RE.finditer(text):
        t = blh.TEAM_WORDS[m.group(1).lower()]
        if t in my_teams:
            tags[t] = tags.get(t, 0) + 2
    yr = fi.get('year')
    if not yr:
        # undated upload: a year in the title / description is the next best thing
        # ("1986 Jeno's Pizza ad" is an ad, not a 1973 Bills photo)
        ym = re.search(r'(19[2-9]\d|20[0-2]\d)', text)
        yr = int(ym.group(1)) if ym else None
    in_career = bool(yr and yr in years)
    if yr and yr not in years:
        return None                         # dated outside the career (Hall of Fame nights, alumni
                                            # events, Ring of Honor) → never a jersey shot, team word or not
    if for_search and not tags and not blh.FOOTBALL_WORD_RE.search(text):
        return None                         # loose hit: namesake with a date inside the career (drummers, actors)
    if COLLEGE_RE.search(text) and not tags:
        return None                         # college / combine photo: not an NFL uniform
    if in_career and by_year.get(yr):
        # a dated in-career photo belongs to THAT season's team; other team words are the
        # opponent ("Titans vs Ravens 2020" is Henry in a Titans jersey, not a Raven)
        tags = {by_year[yr]: 3 + (2 if by_year[yr] in tags else 0)}
    elif len(tags) > 1:
        return None                         # undated and two of his own teams named: can't tell the jersey
    if not tags:
        return None                         # cannot place it on a team → useless for a jersey cutout
    portrait = bool(PORTRAIT_RE.search(text))
    crowd = bool(CROWD_RE.search(text))
    base = (2 if portrait else 0) - (3 if crowd else 0) + (1 if in_career else 0)
    return {'file': ft, 'url': fi['thumb'], 'credit': fi['credit'], 'year': yr,
            'teams': {t: sc + base for t, sc in tags.items()}, 'portrait': portrait}


def search_players(names, players, legend_hs, state, log):
    """Stage S for a chunk of names: gather + score Commons candidates into state['cands']."""
    trusted = {n: set() for n in names}     # files tied to the player by the legend builder / his Commons category
    loose = {n: set() for n in names}       # loose File-namespace search hits (full name required)
    # 1. what the legend builder already picked (lead photo + jersey photos)
    for n in names:
        lh = legend_hs.get(n)
        if not lh:
            continue
        for u in [lh.get('url')] + [b.get('url') for b in (lh.get('byTeam') or {}).values()]:
            f = commons_file_from_url(u)
            if f:
                trusted[n].add(f)
    # 2. Commons category files
    have_cat = blh.commons_categories(list(names))
    for n in names:
        if n in have_cat:
            try:
                trusted[n] |= set(blh.commons_category_files(n, CAT_LIMIT))
            except Exception as e:
                log('  ! category %s: %s' % (n, str(e)[:80]))
    # 3. loose file search (full name phrase)
    for n in names:
        try:
            loose[n] = set(blh.commons_file_search(n, SEARCH_LIMIT)) - trusted[n]
        except Exception as e:
            log('  ! search %s: %s' % (n, str(e)[:80]))
    # 4. imageinfo for everything, scored per player
    all_files = sorted({f for n in names for f in trusted[n] | loose[n]})
    info = blh.image_info(all_files) if all_files else {}
    today = time.strftime('%Y-%m-%d')
    for n in names:
        p = players[n]
        pinfo = {'by_year': blh.team_by_year(p['seasons'])}
        cands = []
        for ft in sorted(trusted[n] | loose[n]):
            sc = score_file(n, pinfo, ft, info.get(ft), for_search=(ft in loose[n]))
            if sc:
                cands.append(sc)
        state['cands'][n] = cands
        state['searched'][n] = today


# -------------------------------------------------------------- flickr ----
def flickr_search(name, players_entry, key, log):
    """Flickr CC candidates (free licences only). Returns cands like score_file's."""
    import requests
    base = 'https://www.flickr.com/services/rest/'
    out = []
    try:
        r = requests.get(base, params={'method': 'flickr.photos.search', 'api_key': key, 'text': '"%s"' % name,
                                       'license': FLICKR_FREE_LICENSES, 'content_type': 1, 'media': 'photos',
                                       'extras': 'license,owner_name,date_taken,url_l,url_c,description,tags',
                                       'per_page': 30, 'format': 'json', 'nojsoncallback': 1}, timeout=60)
        r.raise_for_status()
        photos = (r.json().get('photos') or {}).get('photo') or []
    except Exception as e:
        log('  ! flickr %s: %s' % (name, str(e)[:80]))
        return out
    lic_names = {'4': 'CC BY 2.0', '5': 'CC BY-SA 2.0', '7': 'No known copyright restrictions', '9': 'CC0', '10': 'Public Domain Mark'}
    by_year = blh.team_by_year(players_entry['seasons'])
    my_teams = set(by_year.values())
    for ph in photos:
        url = ph.get('url_l') or ph.get('url_c')
        if not url:
            continue
        text = ' '.join([ph.get('title') or '', (ph.get('description') or {}).get('_content') or '', ph.get('tags') or '']).lower()
        if name.lower() not in text and blh._name_key(name) not in blh._name_key(text):
            continue
        if blh.RELATIVE_RE.search(text) or blh.MEMORIAL_RE.search(text):
            continue
        if blh.OTHER_SPORT_RE.search(text) and not blh.FOOTBALL_WORD_RE.search(text):
            continue
        ym = re.search(r'\b(19[2-9]\d|20[0-2]\d)\b', ph.get('datetaken') or '')
        yr = int(ym.group(1)) if ym else None
        tags = {}
        for m in blh.TEAM_WORD_RE.finditer(text):
            t = blh.TEAM_WORDS[m.group(1).lower()]
            if t in my_teams:
                tags[t] = tags.get(t, 0) + 2
        if yr and yr in by_year:
            tags[by_year[yr]] = tags.get(by_year[yr], 0) + 1
        elif yr and not tags:
            continue
        if not tags:
            continue
        credit = '%s · %s (Flickr)' % ((ph.get('ownername') or 'Flickr user')[:60], lic_names.get(str(ph.get('license')), 'CC'))
        out.append({'file': 'flickr:%s' % ph['id'], 'url': url, 'credit': credit, 'year': yr,
                    'teams': {t: sc + (2 if PORTRAIT_RE.search(text) else 0) - (3 if CROWD_RE.search(text) else 0) for t, sc in tags.items()},
                    'portrait': bool(PORTRAIT_RE.search(text)),
                    'page': 'https://www.flickr.com/photos/%s/%s' % (ph.get('owner'), ph['id'])})
    return out


# ---------------------------------------------------------- download ----
def cache_path(url, sub=SRC_DIR):
    h = hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower() or '.jpg'
    if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff'):
        ext = '.jpg'
    return os.path.join(sub, h + ext)


def download(url, log):
    import requests
    p = cache_path(url)
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return p
    os.makedirs(SRC_DIR, exist_ok=True)
    for attempt in range(3):
        try:
            r = requests.get(url, headers={'User-Agent': blh.UA}, timeout=90)
            if r.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            r.raise_for_status()
            with open(p, 'wb') as f:
                f.write(r.content)
            time.sleep(0.4)
            return p
        except Exception as e:
            log('  ! download %s: %s' % (url[-60:], str(e)[:80]))
            time.sleep(3 * (attempt + 1))
    return None


# ------------------------------------------------------------- cutting ----
_rembg_session = None


def rembg_session():
    global _rembg_session
    if _rembg_session is None:
        from rembg import new_session
        try:
            _rembg_session = new_session('u2net_human_seg')
        except Exception:
            _rembg_session = new_session('u2net')
    return _rembg_session


def segment(src_path, log):
    """Background removal + group/tiny gates. Returns (rgba PIL image, reason-or-None)."""
    import cv2
    import numpy as np
    from PIL import Image
    from rembg import remove
    im = Image.open(src_path)
    im.load()
    im = im.convert('RGB')
    if max(im.size) < 320:
        return None, 'small-source'
    if max(im.size) > 1600:
        f = 1600 / max(im.size)
        im = im.resize((int(im.width * f), int(im.height * f)), Image.LANCZOS)
    elif max(im.size) < 700:
        f = 2
        im = im.resize((im.width * f, im.height * f), Image.LANCZOS)
    rgba = remove(im, session=rembg_session())
    a = np.array(rgba.split()[-1])
    mask = (a > 128).astype(np.uint8)
    total = int(mask.sum())
    if total < 0.04 * mask.size:
        return None, 'tiny-subject'
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return None, 'empty-matte'
    areas = stats[1:, cv2.CC_STAT_AREA]
    big = int(areas.argmax()) + 1
    if areas.max() < 0.6 * total:
        return None, 'multi-subject'
    # faces inside the matte: 2+ comparable faces = group photo
    rgb = np.array(rgba.convert('RGB'))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    cas = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    faces = [f for f in cas.detectMultiScale(gray, 1.1, 6, minSize=(24, 24))
             if a[f[1]:f[1] + f[3], f[0]:f[0] + f[2]].mean() > 100]
    if len(faces) >= 2:
        faces.sort(key=lambda f: -f[2] * f[3])
        if faces[1][2] * faces[1][3] >= 0.3 * faces[0][2] * faces[0][3]:
            return None, 'group-faces'
    # keep the main component only (stray limbs of other players vanish)
    keep = (labels == big)
    a2 = np.where(keep, a, 0).astype(np.uint8)
    rgba.putalpha(Image.fromarray(a2))
    # subject should be upright-ish: its bounding box taller than ~0.55 of its width
    ys, xs = np.where(a2 > 128)
    bh, bw = ys.max() - ys.min(), xs.max() - xs.min()
    if bh < 0.55 * bw:
        return None, 'lying-subject'
    if bh < 0.9 * bw:
        return None, 'wide-subject'    # a pile of players / a sitting figure read as one matte
    if not profile_ok(a2, 0.04, 0.14, 0.20, 0.65):
        return None, 'no-head-profile'   # a limb / ball / torso fragment, not a head on shoulders
    return rgba, None


def profile_ok(a, h0, h1, s0, s1, ratio=1.3):
    """Head-on-shoulders test: matte width in the head band (h0..h1 of the subject's
    height from its top) must be clearly narrower than in the shoulder band (s0..s1).
    Arms, gloves and torso fragments have a flat or widening-upward profile."""
    import numpy as np
    m = a > 128
    rows = np.where(m.any(axis=1))[0]
    if len(rows) < 20:
        return False
    top, bot = int(rows[0]), int(rows[-1])
    H = max(bot - top, 1)
    w = m.sum(axis=1)
    head = w[top + int(H * h0): top + int(H * h1) + 1]
    sh = w[top + int(H * s0): top + int(H * s1) + 1]
    if not len(head) or not len(sh):
        return False
    hw = float(np.median(head))
    return hw > 0 and float(sh.max()) >= ratio * hw


def seg_ok(seg_png):
    """Gates that can be re-run on a cached segmentation (no rembg): the kept matte
    must be taller than it is wide (a pile of helmets or a sitting figure is not a head)."""
    import numpy as np
    from PIL import Image
    a = np.array(Image.open(seg_png).convert('RGBA').split()[-1])
    ys, xs = np.where(a > 128)
    if not len(ys):
        return 'empty-matte'
    bh, bw = ys.max() - ys.min(), xs.max() - xs.min()
    if bh < 0.9 * bw:
        return 'wide-subject'
    return None


def check_cut(png_path):
    """Post-crop sanity: coverage 8-92 %, something in the centre column (the cutter centres
    on the head, so an off-centre blob is a limb / jersey fragment), nothing running off the
    top, and shoulders wider than the head once the head band is measured where the cutter
    puts it (crown at ~10 %, shoulders from ~55 %; the bottom 20 % is faded)."""
    import numpy as np
    from PIL import Image
    im = Image.open(png_path).convert('RGBA')
    a8 = np.array(im.split()[-1])
    a = a8.astype(np.float32) / 255.0
    cov = a.mean()
    if cov < 0.08 or cov > 0.92:
        return 'coverage-%.2f' % cov
    h, w = a.shape
    centre = a[int(h * 0.10):int(h * 0.60), int(w * 0.40):int(w * 0.60)].mean()
    if centre < 0.30:
        return 'off-centre-%.2f' % centre
    top_edge = a[:int(h * 0.02)].mean()
    if top_edge > 0.6:
        return 'cropped-top'   # subject runs off the top: crown not found
    if not profile_ok(a8, 0.08, 0.30, 0.55, 0.79, ratio=1.2):
        return 'no-shoulders'
    return None


def make_cutout(name, team, cand, log):
    """Download + segment + cut + webp. Returns (ok, info-or-reason)."""
    import make_legend_headshots as mlh
    from PIL import Image
    src = download(cand['url'], log)
    if not src:
        return False, 'download-failed'
    os.makedirs(PNG_DIR, exist_ok=True)
    key = hashlib.sha1((cand['url']).encode('utf-8')).hexdigest()[:16]
    seg_png = os.path.join(PNG_DIR, key + '_seg.png')
    master = os.path.join(PNG_DIR, key + '_cut.png')
    try:
        if not os.path.exists(master):
            if not os.path.exists(seg_png):
                rgba, why = segment(src, log)
                if why:
                    return False, why
                rgba.save(seg_png)
            how = mlh.cut(seg_png, master)        # already transparent → the cutter skips rembg
        else:
            how = 'cached'
        if os.path.exists(seg_png):
            bad = seg_ok(seg_png)
            if bad:
                return False, bad
    except Exception as e:
        return False, 'cut-error:%s' % str(e)[:60]
    bad = check_cut(master)
    if bad:
        return False, bad
    out_dir = os.path.join(IMG_DIR, lt.slug(name))
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, team + '.webp')
    Image.open(master).convert('RGBA').resize((OUT_W, OUT_H), Image.LANCZOS).save(out, 'WEBP', quality=WEBP_Q, method=6)
    return True, {'src': 'img/cutouts/%s/%s.webp' % (lt.slug(name), team), 'file': cand['file'], 'credit': cand['credit'],
                  'yr': cand.get('year'), 'how': how, 'page': cand.get('page') or ('https://commons.wikimedia.org/wiki/' + urllib.parse.quote(cand['file'].replace(' ', '_'))),
                  'bytes': os.path.getsize(out)}


def cut_player(name, p, cands, cuts, log):
    """Try every pending team stint of one player. `cuts` (this player's {team: rec}) is
    updated in place and returned (worker-pool friendly)."""
    for st in p['stints']:
        team = st['tm']
        done = cuts.get(team)
        if done and done.get('ok'):
            continue
        tried = set((done or {}).get('tried') or [])
        if cuts.get('_skip_' + team):
            tried.add(cuts.pop('_skip_' + team))
        pool = [c for c in cands if team in c['teams'] and c['file'] not in tried]
        # closest era to the stint wins ties; portraits first
        pool.sort(key=lambda c: (-c['teams'][team], abs((c.get('year') or st['mid']) - st['mid'])))
        rec = done or {'ok': False, 'tried': []}
        for c in pool[:TRIES_PER_TEAM]:
            ok, info = make_cutout(name, team, c, log)
            rec['tried'].append(c['file'])
            if ok:
                rec.update(info)
                rec['ok'] = True
                rec.pop('why', None)
                log('  %-24s %-3s ok  %s  (%s, %s)' % (name, team, info['src'], info['how'], info.get('yr') or '?'))
                break
            rec['why'] = info
            log('  %-24s %-3s --  %s  %s' % (name, team, info, c['file'][5:60]))
        if not rec.get('ok') and not pool:
            rec['why'] = rec.get('why') or 'no-candidate'
        cuts[team] = rec
    return cuts


def _worker_log(s):
    print(s, flush=True)


def _cut_job(job):
    """Pool worker: (name, player, cands, cuts) -> (name, cuts)."""
    name, p, cands, cuts = job
    try:
        return name, cut_player(name, p, cands, cuts, _worker_log)
    except Exception as e:
        _worker_log('  ! %s: %s' % (name, str(e)[:120]))
        return name, cuts


def pending_teams(name, p, state):
    cuts = state['cuts'].get(name) or {}
    return [s['tm'] for s in p['stints'] if s['tm'] not in cuts]


def player_cands(name, p, state, flickr_key, log):
    cands = list(state['cands'].get(name) or [])
    if flickr_key:
        fk = state.setdefault('flickr', {})
        if name not in fk:
            fk[name] = flickr_search(name, p, flickr_key, log)
        cands += fk[name]
    return cands


# --------------------------------------------------------------- write ----
def write_index(players, state):
    table = {}
    total_bytes = 0
    n_files = 0
    for name in sorted(players):
        cuts = state['cuts'].get(name) or {}
        by = {}
        for team, rec in cuts.items():
            if team.startswith('_') or not isinstance(rec, dict):
                continue
            if rec.get('ok') and os.path.exists(os.path.join(ROOT, rec['src'])):
                by[team] = {'src': rec['src'], 'credit': rec['credit'], 'yr': rec.get('yr'), 'file': rec['file']}
                total_bytes += rec.get('bytes') or os.path.getsize(os.path.join(ROOT, rec['src']))
                n_files += 1
        if not by:
            continue
        prim = players[name]['primary']
        default = prim if prim in by else max(by, key=lambda t: sum(1 for s in players[name]['stints'] if s['tm'] == t))
        table[name] = {'byTeam': by, 'default': default}
        # sidecar credits next to the images
        with open(os.path.join(IMG_DIR, lt.slug(name), 'credits.json'), 'w', encoding='utf-8') as f:
            json.dump({t: {'file': b['file'], 'credit': b['credit'], 'yr': b['yr'],
                           'page': (cuts[t].get('page') or '')} for t, b in by.items()}, f, ensure_ascii=False, indent=1)
    lines = ['/* PLAYER_CUTOUTS — era-correct transparent player cutouts for the Trivia reveal',
             '   (img/cutouts/<slug>/<TEAM>.webp, 350x254, ESPN framing). Generated %s by' % time.strftime('%Y-%m-%d'),
             '   scripts/build_player_cutouts.py from Wikimedia Commons photos (free licences only;',
             '   "credit" = Artist · License, shown as the image tooltip; img/cutouts/credits.html lists all).',
             '   byTeam[ABBR] = cutout in that team\'s uniform, yr = photo year (null = undated, placed by',
             '   team word); default = the team to use when the board gives none. %d players, %d files, %.1f MB.' % (len(table), n_files, total_bytes / 1e6),
             '   Lazy-loaded with legend_headshots.js by index.html _loadLegendHeadshots; read by',
             '   _triviaGetHeadshotInfo(answer, team, yr) BEFORE the ESPN / Commons-lead sources. */',
             'window.PLAYER_CUTOUTS = {']
    keys = sorted(table)
    for i, k in enumerate(keys):
        lines.append('%s:%s%s' % (json.dumps(k, ensure_ascii=False), json.dumps(table[k], ensure_ascii=False, separators=(',', ':')),
                                  ',' if i < len(keys) - 1 else ''))
    lines.append('};')
    with open(INDEX, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    write_credits_page(table, state)
    return table, n_files, total_bytes


def write_credits_page(table, state):
    rows = []
    for name in sorted(table):
        for t, b in sorted(table[name]['byTeam'].items()):
            page = (state['cuts'].get(name, {}).get(t) or {}).get('page') or ''
            rows.append('<tr><td>%s</td><td>%s</td><td>%s</td><td><a href="%s" rel="noopener" target="_blank">%s</a></td></tr>' % (
                blh.html.escape(name), t, b['yr'] or '', blh.html.escape(page), blh.html.escape(b['credit'])))
    doc = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
           '<title>Trivia photo credits · MyFantasyFootball</title>',
           '<style>body{font:14px/1.4 system-ui,sans-serif;margin:16px;background:#0f1117;color:#e5e7eb}a{color:#a78bfa}table{border-collapse:collapse;width:100%}td,th{padding:4px 8px;border-bottom:1px solid #27272a;text-align:left;font-size:13px}h1{font-size:20px}p{color:#a1a1aa}</style></head><body>',
           '<h1>Trivia player photo credits</h1>',
           '<p>The transparent player cutouts on the <a href="../../#trivia">Trivia page</a> are cropped from free-licensed photographs on '
           '<a href="https://commons.wikimedia.org/" rel="noopener">Wikimedia Commons</a> (CC BY / CC BY-SA / public domain, as listed). '
           'Each row links to the original file and its full licence. %d cutouts · generated %s.</p>' % (len(rows), time.strftime('%Y-%m-%d')),
           '<table><tr><th>Player</th><th>Team</th><th>Year</th><th>Photo credit · licence (link = source)</th></tr>'] + rows + ['</table></body></html>']
    os.makedirs(IMG_DIR, exist_ok=True)
    with open(CREDITS_PAGE, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(doc) + '\n')


# -------------------------------------------------------------- report ----
def coverage_report(players, table, espn_names, state):
    """Per decade: % of top-150 fantasy seasons with a cutout in that season's team;
    notable misses listed for Jack."""
    by_year = {}
    for name, p in players.items():
        tb = blh.team_by_year(p['seasons'])
        for s in p['seasons']:
            yr = s.get('yr')
            if not yr or (s.get('fpts') or 0) <= 0:
                continue
            by_year.setdefault(yr, []).append((s['fpts'], name, tb.get(yr)))
    decades = {}
    misses = {}
    for yr, rows in by_year.items():
        rows.sort(reverse=True)
        top = rows[:150]
        dec = (yr // 10) * 10
        d = decades.setdefault(dec, {'n': 0, 'team': 0, 'any': 0, 'espn': 0})
        for fp, name, tm in top:
            d['n'] += 1
            ent = table.get(name)
            if ent and tm in ent['byTeam']:
                d['team'] += 1
            elif ent:
                d['any'] += 1
            elif name in espn_names or players[name]['last'] >= 2024:
                d['espn'] += 1          # id files, or an active roster headshot (D._slImg)
            else:
                m = misses.setdefault(name, {'best': 0, 'seasons': 0, 'teams': set(), 'why': None, 'yr': yr})
                m['best'] = max(m['best'], fp)
                m['seasons'] += 1
                if tm:
                    m['teams'].add(tm)
    lines = ['# Trivia cutout coverage — %s' % time.strftime('%Y-%m-%d'), '',
             'Top-150 fantasy seasons per year (LEGEND_CAREERS + ALL_PLAYERS_DB, fpts), per decade:',
             '', '| Decade | seasons | in-uniform cutout | cutout, other team | ESPN headshot only | nothing |',
             '|---|---|---|---|---|---|']
    for dec in sorted(decades):
        d = decades[dec]
        none = d['n'] - d['team'] - d['any'] - d['espn']
        lines.append('| %ds | %d | %d (%.0f%%) | %d (%.0f%%) | %d (%.0f%%) | %d (%.0f%%) |' % (
            dec, d['n'], d['team'], 100.0 * d['team'] / d['n'], d['any'], 100.0 * d['any'] / d['n'],
            d['espn'], 100.0 * d['espn'] / d['n'], none, 100.0 * none / d['n']))
    lines += ['', '"in-uniform cutout" = img/cutouts/<player>/<that season\'s team>.webp exists. "ESPN headshot only" = the',
              'reveal still shows the (current-team, era-agnostic) ESPN cutout (id files, or an active roster photo).',
              '"nothing" = initials.', '']
    # why the misses missed
    for name, m in misses.items():
        cuts = state['cuts'].get(name) or {}
        whys = sorted({(r.get('why') or 'no-candidate') for k, r in cuts.items() if not k.startswith('_') and not r.get('ok')})
        m['why'] = ', '.join(w.split(':')[0] for w in whys)[:80] if whys else ('not searched' if name not in state['searched'] else 'no-candidate')
    lines += ['## Notable players with NO free in-uniform photo (top-150 seasons, best season first)', '',
              'No Commons file could be placed on a team (or every candidate failed the cutter). These need',
              'either a free photo uploaded to Commons, Flickr CC (needs an API key), or Jack\'s own scans',
              '(E:/Sports/All Time Players — rights to confirm before shipping).', '',
              '| Player | best fpts | top-150 seasons | teams | why |', '|---|---|---|---|---|']
    for name, m in sorted(misses.items(), key=lambda kv: -kv[1]['best'])[:250]:
        lines.append('| %s | %.0f | %d | %s | %s |' % (name, m['best'], m['seasons'], ' '.join(sorted(m['teams'])), m['why']))
    lines += ['', '%d players listed; %d notable (3+ seasons ≥ 150 fpts) among them.' % (
        len(misses), sum(1 for n in misses if players[n]['notable']))]
    with open(REPORT, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    return lines


# ---------------------------------------------------------------- main ----
def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')   # cp1252 console vs · → in the log lines
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--names', nargs='*', help='only these players')
    ap.add_argument('--limit', type=int, default=0, help='first N players by peak season')
    ap.add_argument('--min-peak', type=float, default=0, help='skip players whose best season is below this fpts')
    ap.add_argument('--search-only', action='store_true')
    ap.add_argument('--cut-only', action='store_true')
    ap.add_argument('--write', action='store_true', help='rewrite index/credits/report only')
    ap.add_argument('--report', action='store_true', help='coverage report only')
    ap.add_argument('--refresh', action='store_true', help='re-search the selected names')
    ap.add_argument('--retry-failed', action='store_true', help='re-try teams whose cut failed')
    ap.add_argument('--recheck', action='store_true', help='re-run the gates on accepted cuts (cached masters); failures are re-tried')
    ap.add_argument('--flickr-key', default=os.environ.get('FLICKR_API_KEY') or None)
    ap.add_argument('--sleep', type=float, default=0.5, help='seconds between Commons API calls')
    ap.add_argument('--chunk', type=int, default=40, help='players per search batch (state saved after each)')
    ap.add_argument('--workers', type=int, default=1, help='cutter processes (rembg is CPU-bound)')
    ap.add_argument('--follow', action='store_true', help='with --cut-only: keep polling the search state until it says done')
    args = ap.parse_args()
    blh.SLEEP = args.sleep
    blh.THUMB = SRC_WIDTH

    log_path = os.path.join(CACHE, 'build_log.txt')
    os.makedirs(CACHE, exist_ok=True)
    logf = open(log_path, 'a', encoding='utf-8')

    def log(s):
        print(s, flush=True)
        logf.write(time.strftime('%H:%M:%S ') + s + '\n')
        logf.flush()

    careers = blh.load_careers()
    allp = load_all_players()
    players = build_players(careers, allp)
    espn_names = blh.load_espn_names()
    legend_hs = load_legend_headshots()
    state = load_state()
    log('players %d · stints %d · legend photos %d · state: %d searched, %d with cuts' % (
        len(players), sum(len(p['stints']) for p in players.values()), len(legend_hs), len(state['searched']), len(state['cuts'])))

    if args.report or args.write:
        table, n_files, total_bytes = write_index(players, state)
        lines = coverage_report(players, table, espn_names, state)
        log('\n'.join(lines[:14]))
        log('index: %d players · %d files · %.1f MB → %s' % (len(table), n_files, total_bytes / 1e6, os.path.relpath(INDEX, ROOT)))
        return

    order = sorted(players, key=lambda n: -players[n]['peak'])
    if args.names:
        order = [n for n in args.names if n in players]
        missing = [n for n in args.names if n not in players]
        if missing:
            log('not in the player tables: ' + ', '.join(missing))
        if args.refresh:
            for n in order:
                state['searched'].pop(n, None)
                state['cands'].pop(n, None)
                state['cuts'].pop(n, None)
    if args.min_peak:
        order = [n for n in order if players[n]['peak'] >= args.min_peak]
    if args.limit:
        order = order[:args.limit]
    if args.retry_failed:
        for n in order:
            for t, r in list((state['cuts'].get(n) or {}).items()):
                if not r.get('ok'):
                    state['cuts'][n].pop(t)
    if args.recheck:
        dropped = 0
        for n in order:
            cands = {c['file']: c for c in (state['cands'].get(n) or [])}
            for t, r in list((state['cuts'].get(n) or {}).items()):
                if not r.get('ok') or r.get('file') not in cands:
                    continue
                key = hashlib.sha1(cands[r['file']]['url'].encode('utf-8')).hexdigest()[:16]
                seg_png = os.path.join(PNG_DIR, key + '_seg.png')
                master = os.path.join(PNG_DIR, key + '_cut.png')
                bad = (seg_ok(seg_png) if os.path.exists(seg_png) else None) or (check_cut(master) if os.path.exists(master) else None)
                if bad:
                    dropped += 1
                    log('  recheck %-22s %-3s drop %s  %s' % (n, t, bad, r['file'][5:60]))
                    out = os.path.join(ROOT, r['src'])
                    if os.path.exists(out):
                        os.remove(out)
                    state['cuts'][n][t] = {'ok': False, 'tried': [r['file']], 'why': bad}
                    state['cuts'][n].pop(t)      # re-tried below with the next candidates
                    state['cuts'][n]['_skip_' + t] = r['file']
        log('recheck: dropped %d cuts' % dropped)
        save_state(state, 'cut')

    # ---- stage S: search
    if not args.cut_only:
        todo = [n for n in order if n not in state['searched']]
        log('search: %d players to query' % len(todo))
        if todo:
            state['done'] = False
        for i in range(0, len(todo), args.chunk):
            chunk = todo[i:i + args.chunk]
            t0 = time.time()
            search_players(chunk, players, legend_hs, state, log)
            save_state(state, 'search')
            nc = sum(len(state['cands'].get(n) or []) for n in chunk)
            log('  searched %d/%d (+%d candidates, %.0fs) … %s' % (min(i + args.chunk, len(todo)), len(todo), nc, time.time() - t0, chunk[-1]))
        if not args.names and not args.limit:
            state['done'] = True            # full sweep finished: a --follow cutter may stop
        save_state(state, 'search')

    # ---- stage C: cut
    if not args.search_only:
        pool = None
        if args.workers > 1:
            import multiprocessing as mp
            pool = mp.Pool(args.workers)
        done_total = 0
        while True:
            if args.cut_only:
                reload_search(state)
            todo = [n for n in order if n in state['searched'] and pending_teams(n, players[n], state)]
            if not todo:
                if args.cut_only and args.follow and not state.get('done'):
                    log('cut: nothing pending, search still running — waiting 60s')
                    time.sleep(60)
                    continue
                break
            log('cut: %d players with pending teams' % len(todo))
            jobs = ((n, players[n], player_cands(n, players[n], state, args.flickr_key, log), state['cuts'].get(n) or {}) for n in todo)
            it = pool.imap_unordered(_cut_job, jobs, chunksize=1) if pool else (_cut_job(j) for j in jobs)
            for i, (n, cuts) in enumerate(it):
                state['cuts'][n] = cuts
                done_total += 1
                if i % 10 == 9 or i == len(todo) - 1:
                    save_state(state, 'cut')
                    if args.flickr_key:
                        save_state(state, 'search')
                    if i % 50 == 49:
                        write_index(players, state)
                        log('  cut progress %d/%d (%s)' % (i + 1, len(todo), n))
            save_state(state, 'cut')
            if not (args.cut_only and args.follow):
                break
        if pool:
            pool.close()
            pool.join()

    table, n_files, total_bytes = write_index(players, state)
    lines = coverage_report(players, table, espn_names, state)
    log('\n'.join(lines[:14]))
    log('index: %d players · %d files · %.1f MB → %s' % (len(table), n_files, total_bytes / 1e6, os.path.relpath(INDEX, ROOT)))
    log('report: ' + os.path.relpath(REPORT, ROOT))


if __name__ == '__main__':
    main()
