#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
make_legend_headshots.py — sort + cut the photos Jack saves under
E:/Sports/All Time Players/<AFC|NFC>/<Division>/<Nickname>/<Player Name>.jpg into
ESPN-style trivia headshots, and keep data/legend_hs_local.js in step.

For every image under the root:
  * player  = file name (" PNG", digits, "(1)" stripped), fuzzy-matched to a
              legend_careers.js name (typos like "emmitt sith" resolve);
  * team    = the folder it sits in (Cowboys -> DAL);
  * cut     = background removed (rembg) unless the PNG is already transparent;
              crop from the detected face when OpenCV finds one inside the
              subject, else from the matte's crown; 2.05 head-widths tall at
              ESPN's 350:254, torso faded, saved as data/legend_hs/<slug>.png
              (700x508, optimized);
  * map     = data/legend_hs_local.js  {name: {url, source, byTeam{ABBR: url}}}
              — the newest photo in the player's primary-team folder is the
              default; photos in other team folders become byTeam entries.
  Active players (a season in 2024 or later) are skipped: their ESPN/Sleeper
  headshot comes from the site's D[] array.

Only players WITHOUT an ESPN headshot are cut by default (names missing from the
four ESPN id files, or on scripts/_suspect_espn_ids.json); the folder also holds
video b-roll of active players whose ESPN headshot should stay. --all cuts everyone.

Output also includes <root>/_preview.jpg — every cut on a white trivia-style card
with the team outline — so bad crops can be spotted and the source photo replaced.

Usage: python -I scripts/make_legend_headshots.py [--all] [--force] [--bump] [--names ...]
  --force  re-cut files whose source has not changed
  --bump   bump the legend_hs_local.js ?v= tag in index.html (read from disk first)
"""
import argparse
import difflib
import json
import os
import re
import sys
import time

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_legend_headshots as blh  # noqa: E402
import legend_teams as lt             # noqa: E402

MAP = os.path.join(blh.DATA, 'legend_hs_local.js')
OUT_DIR = os.path.join(blh.DATA, 'legend_hs')
PREVIEW = os.path.join(lt.ROOT_DIR, '_preview.jpg')
EXTS = ('.jpg', '.jpeg', '.jfif', '.png', '.webp', '.bmp')
W, H = 700, 508


# ------------------------------------------------------------- naming ----
def name_from_file(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r'\b(png|jpg|jpeg|cutout|headshot|hs)\b', ' ', stem, flags=re.I)
    stem = re.sub(r'\(\d+\)|\b\d+\b', ' ', stem)
    stem = re.sub(r'[_\-]+', ' ', stem)
    return re.sub(r'\s+', ' ', stem).strip()


def match_name(raw, careers):
    key = blh._name_key(raw)
    by_key = {blh._name_key(n): n for n in careers}
    if key in by_key:
        return by_key[key], 1.0
    cands = difflib.get_close_matches(key, list(by_key), n=1, cutoff=0.82)
    if cands:
        return by_key[cands[0]], difflib.SequenceMatcher(None, key, cands[0]).ratio()
    return ' '.join(w.capitalize() if w.islower() else w for w in raw.split()), 0.0


# ------------------------------------------------------------ cutting ----
def load_rgba(path):
    im = Image.open(path)
    im.load()
    if im.mode in ('RGBA', 'LA') and np.array(im.split()[-1]).min() < 10:
        return im.convert('RGBA'), True          # already a cutout (Jack's video PNGs)
    return im.convert('RGB'), False


def cut(path, out):
    im, is_cut = load_rgba(path)
    if max(im.size) < 1000:
        f = 2 if max(im.size) >= 500 else 3
        im = im.resize((im.width * f, im.height * f), Image.LANCZOS)
    if is_cut:
        rgba = im
    else:
        from rembg import remove
        rgba = remove(im)
    a = np.array(rgba.split()[-1])
    Hh, Ww = a.shape
    rows = np.where(a.max(axis=1) > 128)[0]
    cols = np.where(a.max(axis=0) > 128)[0]
    if len(rows) == 0:
        raise RuntimeError('empty matte')
    top, bottom, left, right = rows.min(), rows.max(), cols.min(), cols.max()

    # 1. face-based crop when OpenCV finds a face inside the subject's upper half
    rgb = np.array(rgba.convert('RGB'))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    cas = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    faces = cas.detectMultiScale(gray, 1.1, 6, minSize=(max(24, (right - left) // 12),) * 2)
    face = None
    for (fx, fy, fw, fh) in sorted(faces, key=lambda f: -f[2] * f[3]):
        inside = a[fy:fy + fh, fx:fx + fw].mean() > 100
        upper = fy + fh / 2 < top + (bottom - top) * 0.6
        if inside and upper:
            face = (fx, fy, fw, fh)
            break
    if face:
        fx, fy, fw, fh = face
        cx = fx + fw / 2
        box_h = fh * 2.7
        y0 = fy - fh * 0.75                       # room for the helmet / hair above the face box
        how = 'face'
    else:
        # 2. crown-based crop. Follow the body's centre column (the column with the most
        # subject pixels) upward: the first row it hits is the crown, and the run of
        # pixels around it there is the head — raised arms and a held ball sit off
        # that column, so they no longer get measured as the head.
        colsum = cv2.GaussianBlur((a > 128).astype(np.float32).sum(axis=0).reshape(1, -1), (0, 0), max(3, Ww / 60))[0]
        cx0 = int(colsum.argmax())
        hit = np.where(a[:, cx0] > 128)[0]
        crown = int(hit.min()) if len(hit) else int(top)

        def run_at(y):
            r = a[y] > 128
            if not r[cx0]:
                return None
            lft = cx0
            while lft > 0 and r[lft - 1]:
                lft -= 1
            rgt = cx0
            while rgt < Ww - 1 and r[rgt + 1]:
                rgt += 1
            return lft, rgt
        y = min(Hh - 1, crown + int((bottom - crown) * 0.12))
        run = run_at(y) or run_at(min(Hh - 1, crown + int((bottom - crown) * 0.2))) or (left, right)
        head_w = max(run[1] - run[0], 10)
        cx = (run[0] + run[1]) / 2
        box_h = head_w * 2.05
        y0 = crown - head_w * 0.10
        how = 'crown'
    box_w = box_h * W / H
    x0 = cx - box_w / 2
    canvas = Image.new('RGBA', (int(box_w), int(box_h)), (0, 0, 0, 0))
    canvas.paste(rgba, (int(-x0), int(-y0)), rgba)
    ca = np.array(canvas.split()[-1]).astype(np.float32)
    hh = ca.shape[0]
    st = int(hh * 0.80)
    ca[st:] *= np.linspace(1, 0, hh - st)[:, None]
    ca = cv2.GaussianBlur(ca, (0, 0), 1.0)
    canvas.putalpha(Image.fromarray(ca.clip(0, 255).astype(np.uint8)))
    canvas = canvas.resize((W, H), Image.LANCZOS)
    canvas.save(out, optimize=True)
    return how


def outlined(img, color, px=3):
    a = np.array(img.split()[-1])
    k = np.ones((px * 2 + 1, px * 2 + 1), np.uint8)
    m = (a > 20).astype(np.uint8)
    ring = cv2.dilate(m, k) - m
    base = np.zeros((img.height, img.width, 4), np.uint8)
    base[..., :3] = color
    base[..., 3] = ring * 255
    return Image.alpha_composite(Image.fromarray(base), img)


# ---------------------------------------------------------------- map ----
def load_map():
    if not os.path.exists(MAP):
        return {}
    m = re.search(r'LEGEND_HEADSHOTS_LOCAL\s*=\s*(\{.*\})\s*;', open(MAP, encoding='utf-8').read(), re.S)
    return json.loads(m.group(1)) if m else {}


def write_map(table):
    lines = ['/* LEGEND_HEADSHOTS_LOCAL — hand-picked headshots kept in the repo (data/legend_hs/),',
             '   cut to ESPN framing (transparent PNG, 700x508) by scripts/make_legend_headshots.py',
             '   from the photos under E:/Sports/All Time Players/<conf>/<div>/<team>/. The Trivia',
             '   reveal checks this map FIRST, before FALLBACK_IDS / RETIRED_ESPN_IDS / LEGEND_HEADSHOTS;',
             '   byTeam[ABBR] = the cut from that team\'s folder. "source" records where each photo came',
             '   from so the usage rights are answerable. Generated %s. */' % time.strftime('%Y-%m-%d'),
             'window.LEGEND_HEADSHOTS_LOCAL = {']
    keys = sorted(table)
    for i, k in enumerate(keys):
        v = table[k]
        rec = {'url': v['url'], 'source': v.get('source', '')}
        if v.get('byTeam'):
            rec['byTeam'] = v['byTeam']
        if v.get('src'):
            rec['src'] = v['src']
        lines.append('  %s: %s%s' % (json.dumps(k, ensure_ascii=False), json.dumps(rec, ensure_ascii=False, separators=(',', ':')),
                                     ',' if i < len(keys) - 1 else ''))
    lines.append('};')
    with open(MAP, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')


def bump_index():
    p = os.path.join(blh.ROOT, 'index.html')
    s = open(p, encoding='utf-8').read()                 # read right before the bump: other sessions bump too
    new = 'legend_hs_local.js?v=%s' % time.strftime('%Y-%m-%d-%H%M')
    s2, n = re.subn(r'legend_hs_local\.js\?v=[^\'"]+', new, s)
    if n:
        open(p, 'w', encoding='utf-8', newline='').write(s2)
    print('index.html: %s (%d tag%s)' % (new, n, '' if n == 1 else 's'))


# --------------------------------------------------------------- main ----
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--all', action='store_true', help='cut players that already have an ESPN headshot too')
    ap.add_argument('--force', action='store_true', help='re-cut unchanged sources')
    ap.add_argument('--bump', action='store_true', help='bump the legend_hs_local.js ?v= in index.html')
    ap.add_argument('--names', nargs='*', help='only these players')
    args = ap.parse_args()

    careers = blh.load_careers()
    espn = blh.load_espn_names()
    suspects = set()
    sp = os.path.join(blh.ROOT, 'scripts', '_suspect_espn_ids.json')
    if os.path.exists(sp):
        suspects = {r['name'] for r in json.load(open(sp, encoding='utf-8')).get('suspects', [])}
    table = load_map()
    os.makedirs(OUT_DIR, exist_ok=True)

    # gather files per player
    files = {}      # name -> [(path, team, size)]
    skipped, fuzzy = [], []
    for dp, dn, fn in os.walk(lt.ROOT_DIR):
        dn[:] = [d for d in dn if not d.startswith('_')]
        for f in fn:
            if not f.lower().endswith(EXTS) or f.startswith('_'):
                continue
            path = os.path.join(dp, f)
            raw = name_from_file(path)
            name, score = match_name(raw, careers)
            if args.names and name not in args.names:
                continue
            if 0 < score < 1:
                fuzzy.append((raw, name))
            last = max((x.get('yr') or 0) for x in careers.get(name, [])) if name in careers else 0
            if not args.all and (name not in careers or (name in espn and name not in suspects) or last >= 2024):
                skipped.append((name, 'has ESPN headshot' if name in espn else ('active' if last >= 2024 else 'not in legend_careers')))
                continue
            team = lt.folder_team(dp)
            files.setdefault(name, []).append((path, team, os.path.getmtime(path)))

    def prim_team(n):
        by = blh.team_by_year(careers.get(n, []))
        if not by:
            return None
        cnt = {}
        for t in by.values():
            cnt[t] = cnt.get(t, 0) + 1
        return max(cnt, key=cnt.get)

    cards = []
    changed = 0
    for name in sorted(files):
        lst = files[name]
        pt = prim_team(name)
        lst.sort(key=lambda r: (0 if r[1] == pt else 1, -r[2]))   # primary team folder first, then newest save wins
        entry = table.get(name, {})
        by_team = {}
        for i, (path, team, mtime) in enumerate(lst):
            rel = os.path.relpath(path, lt.ROOT_DIR).replace('\\', '/')
            if i > 0 and (not team or team == lst[0][1]):
                print('  %-22s %-4s %-6s %s' % (name, team or '?', 'extra', rel + '  (same folder: newest save wins)'))
                continue
            stamp = '%s|%d|%d' % (rel, os.path.getsize(path), int(mtime))
            tag = '' if i == 0 else '-' + (team or 'alt%d' % i).lower()
            out = os.path.join(OUT_DIR, lt.slug(name) + tag + '.png')
            url = 'data/legend_hs/' + os.path.basename(out)
            prev = entry.get('src', '') if i == 0 else (entry.get('byTeam', {}).get(team, {}) or {}).get('src', '')
            if prev == stamp and os.path.exists(out) and not args.force:
                how = 'kept'
            else:
                try:
                    how = cut(path, out)
                    changed += 1
                except Exception as e:
                    print('  ! %s: %s' % (rel, e))
                    continue
            print('  %-22s %-4s %-6s %s' % (name, team or '?', how, rel))
            if i == 0:
                entry = {'url': url, 'source': 'Jack, %s (%s)' % (time.strftime('%Y-%m-%d'), rel), 'src': stamp}
            elif team and team != lst[0][1]:
                by_team[team] = {'url': url, 'src': stamp}
            cards.append((name, team, out))
        if by_team:
            entry['byTeam'] = by_team
        table[name] = entry

    if not args.names:
        # a full scan is the source of truth: drop players whose photos are gone (or now
        # skipped) and delete PNGs the map no longer points at
        table = {n: v for n, v in table.items() if n in files}
        keep = {os.path.basename(v['url']) for v in table.values()}
        keep |= {os.path.basename(b['url']) for v in table.values() for b in (v.get('byTeam') or {}).values()}
        for f in os.listdir(OUT_DIR):
            if f.endswith('.png') and f not in keep:
                os.remove(os.path.join(OUT_DIR, f))
                print('  removed stale %s' % f)
    write_map(table)
    print('map: %d players -> %s' % (len(table), os.path.relpath(MAP, blh.ROOT)))

    # preview sheet
    if cards:
        cols = 4
        cw, ch = 360, 300
        rows_n = (len(cards) + cols - 1) // cols
        sheet = Image.new('RGB', (cols * cw + 20, rows_n * ch + 20), (24, 24, 32))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(sheet)
        for i, (name, team, out) in enumerate(cards):
            img = Image.open(out).convert('RGBA').resize((340, 247), Image.LANCZOS)
            card = Image.new('RGB', (340, 280), (255, 255, 255))
            o = outlined(img, (34, 197, 94))
            card.paste(o, (0, 0), o)
            x = 10 + (i % cols) * cw
            y = 10 + (i // cols) * ch
            sheet.paste(card, (x, y))
            draw.text((x + 6, y + 252), '%s  %s' % (name, team or ''), fill=(15, 23, 42))
        sheet.save(PREVIEW, quality=88)
        print('preview: %s' % PREVIEW)

    if fuzzy:
        print('fuzzy name matches (rename the file if wrong): ' + '; '.join('%s -> %s' % p for p in fuzzy))
    if skipped:
        print('skipped %d file(s) (have an ESPN headshot or are not legends; --all to include): %s' % (
            len(skipped), ', '.join(sorted({n for n, _ in skipped}))))
    print('cut/updated: %d' % changed)
    if args.bump:
        bump_index()


if __name__ == '__main__':
    main()
