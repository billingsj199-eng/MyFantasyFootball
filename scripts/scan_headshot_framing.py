#!/usr/bin/env python3
"""Scan every ESPN headshot referenced by d.js and bake a framing map.

ESPN headshots are transparent PNG cutouts, but two newer templates render
badly on every surface (ours and ESPN's own pages):

  * SQUARE files (1024x1024 / 600x600) — player in the top ~68%, bottom ~32%
    fully transparent, so bottom-anchored renderers show a "floating head".
  * TIGHT files (600x436) — the 2026 rookie shoots are zoomed in: the face
    fills ~45-50% of the frame height (veterans ~40-43%), the shoulders run
    off both sides, and the result is a big head on a sliver of jersey next
    to normally framed teammates.

Runtime (app.js window._HS_NORM) repairs both from pixels, but it can only
read pixels after a CORS re-fetch, so it must know WHICH ids need work
without downloading all ~500 headshots every session — and it cannot run a
face detector. This script measures each file once (OpenCV Haar cascade)
and emits data/headshot_framing.js:

    window.HS_FRAMING = { "<espnId>": {"sq":1} | {"k":0.86} | {"sq":1,"k":..}, ... }

  sq  square template (runtime crops the transparent band)
  k   scale factor to bring the face down to the normal size; runtime draws
      the cutout at k× anchored bottom-centre and fades the clipped shoulder
      edges. Only ids with face height >= TIGHT_FACE get a k.

Usage:  python scripts/scan_headshot_framing.py [--dry] [--ids 123,456]
Requires: pip install "opencv-python-headless<5" pillow requests
Re-run after roster churn / new ESPN photoshoots, then bump the ?v= on
data/headshot_framing.js in index.html.
"""
import argparse
import io
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import requests
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D_PATH = os.path.join(ROOT, 'data', 'd.js')
OUT_PATH = os.path.join(ROOT, 'data', 'headshot_framing.js')
RAW = 'https://a.espncdn.com/i/headshots/nfl/players/full/{id}.png'
RATIO = 600 / 436
TARGET_FACE = 0.41     # median face-height fraction of normally framed files
TIGHT_FACE = 0.44      # at/above this the crop reads as "tight" (2026 template ~0.50)
K_MIN = 0.82
MAX_SPREAD = 0.05      # detector settings must agree this closely or we skip the id

# Haar cascades are NOT thread-safe — downloads run in a pool, detection is
# serial on the main thread. One detection is ±10% noisy (Mariota's box once
# swallowed his hair), so we take the median over several detector settings.
_casc = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
_PARAMS = [(1.03, 4), (1.05, 5), (1.08, 5), (1.1, 6), (1.05, 8)]


def load_ids():
    src = open(D_PATH, encoding='utf-8').read()
    return sorted(set(re.findall(r'/full/(\d+)\.png', src)))


def face_height(rgba):
    """Median largest-face height across detector settings, plus the spread.
    Returns (fh_px, spread_px) or None when fewer than 3 settings find a face."""
    bg = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
    bg.alpha_composite(rgba)
    g = cv2.cvtColor(np.array(bg.convert('RGB')), cv2.COLOR_RGB2GRAY)
    w = rgba.size[0]
    hs = []
    for sf, mn in _PARAMS:
        faces = _casc.detectMultiScale(g, sf, mn, minSize=(int(w * 0.15), int(w * 0.15)))
        if len(faces):
            hs.append(int(sorted(faces, key=lambda f: -f[2] * f[3])[0][3]))
    if len(hs) < 3:
        return None
    hs.sort()
    return hs[len(hs) // 2], hs[-1] - hs[0]


def fetch(eid):
    for attempt in range(3):
        try:
            r = requests.get(RAW.format(id=eid), timeout=20)
            if r.status_code != 200:
                return eid, None
            return eid, r.content
        except Exception:
            time.sleep(1 + attempt)
    return eid, None


def measure(eid, content):
    try:
        im = Image.open(io.BytesIO(content)).convert('RGBA')
    except Exception:
        return None
    w, h = im.size
    bb = im.split()[3].getbbox()
    if not bb:
        return None
    square = (w == h)
    bottom = bb[3]
    # height the runtime normalizes to (square: crop band, pad to 600:436)
    norm_h = max(bottom, round(w / RATIO)) if square else h
    fh = face_height(im)
    face = round(fh[0] / norm_h, 3) if fh else None
    spread = round(fh[1] / norm_h, 3) if fh else None
    return {'w': w, 'h': h, 'square': square, 'face': face, 'spread': spread}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--ids', help='comma-separated subset for a quick check')
    args = ap.parse_args()
    ids = args.ids.split(',') if args.ids else load_ids()
    print(f'{len(ids)} headshot ids')
    results = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        blobs = [(eid, c) for eid, c in ex.map(fetch, ids) if c]
    print(f'downloaded {len(blobs)}; detecting faces (serial)…')
    for eid, c in blobs:
        m = measure(eid, c)
        if m:
            results[eid] = m
    faces = sorted(m['face'] for m in results.values() if m['face'])
    print(f'measured {len(results)}, faces found {len(faces)}')
    if faces:
        q = lambda p: faces[min(len(faces) - 1, int(p * len(faces)))]
        print(f'face height: p10 {q(.1)} p50 {q(.5)} p90 {q(.9)} max {faces[-1]}')
    out, unsure = {}, []
    for eid, m in results.items():
        rec = {}
        if m['square']:
            rec['sq'] = 1
        if m['face'] and m['face'] >= TIGHT_FACE:
            if m['spread'] is not None and m['spread'] > MAX_SPREAD:
                unsure.append((eid, m['face'], m['spread']))
            else:
                rec['k'] = round(max(K_MIN, min(1.0, TARGET_FACE / m['face'])), 3)
        if rec:
            out[eid] = rec
    tight = sum(1 for v in out.values() if 'k' in v)
    print(f'flagged {len(out)} ({tight} tight, {sum(1 for v in out.values() if "sq" in v)} square); '
          f'{len(unsure)} tight-looking but detector disagreed (skipped)')
    for eid, v in sorted(out.items(), key=lambda kv: kv[1].get('k', 9)):
        print(f'  {eid:<8} {v}  face={results[eid]["face"]} spread={results[eid]["spread"]}')
    for eid, f, sp in unsure:
        print(f'  ? {eid:<8} face={f} spread={sp}')
    if args.ids:
        for eid in ids:
            m = results.get(eid)
            print(f'  {eid:<8} {m}')
    if args.dry or args.ids:
        return
    stamp = time.strftime('%Y-%m-%d')
    body = ('/* Generated ' + stamp + ' by scripts/scan_headshot_framing.py — ESPN headshot ids that\n'
            '   need pixel normalizing at runtime (app.js window._HS_NORM): sq = square\n'
            '   template with a transparent bottom band; k = scale to bring a tight\n'
            '   2026-style crop down to normal face size. Regenerate after roster churn\n'
            '   (needs opencv-python-headless<5), then bump ?v= in index.html. */\n'
            'window.HS_FRAMING = ' + json.dumps(out, separators=(',', ':'), sort_keys=True) + ';\n')
    open(OUT_PATH, 'w', encoding='utf-8', newline='').write(body)
    print(f'wrote {OUT_PATH}')


if __name__ == '__main__':
    sys.exit(main())
