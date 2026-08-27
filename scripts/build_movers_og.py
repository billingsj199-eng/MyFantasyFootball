"""ADP MOVERS share card: og/movers.png + movers.html.

Renders a 1200x630 Open Graph image of the current top Underdog BBM ADP
movers (same math as the site's _adpMovers ticker: latest snapshot vs the
day closest to 7 days back, |delta| >= 3, drafted range only, ordered by
percent magnitude) and writes the static movers.html share page whose OG
tags point at it. The MOVERS share button links to /movers.html, so
Discord/Twitter/Slack unfurl a real card showing today's movers instead
of the generic site preview.

Runs as a phase of the daily consensus job (daily_consensus_adp.ps1)
right after pull_consensus_adp.py refreshes ud_adp_history.json.
Standalone: python scripts/build_movers_og.py

Fonts: Windows Arial family (the pipeline box). Falls back to Pillow's
default if unavailable (uglier but never fatal).
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, 'data', 'ud_adp_history.json')
DJS = os.path.join(ROOT, 'data', 'd.js')
OUT_PNG = os.path.join(ROOT, 'og', 'movers.png')
OUT_HTML = os.path.join(ROOT, 'movers.html')

W, H = 1200, 630
BG = (11, 15, 26)
PANEL = (17, 23, 38)
BORDER = (44, 51, 80)
TEXT = (223, 228, 242)
MUTED = (139, 148, 179)
ACCENT = (245, 158, 11)
GREEN = (34, 197, 94)
RED = (239, 68, 68)

POS_COLORS = {'QB': (236, 72, 153), 'RB': (34, 197, 94), 'WR': (59, 130, 246), 'TE': (245, 158, 11)}


def font(size, bold=False):
    names = ['arialbd.ttf' if bold else 'arial.ttf', 'segoeuib.ttf' if bold else 'segoeui.ttf']
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def load_positions():
    """Name -> pos from data/d.js ({n:"...",s:"QB",...} entries)."""
    try:
        txt = open(DJS, encoding='utf-8').read()
    except OSError:
        return {}
    out = {}
    for m in re.finditer(r'"n":"([^"]+)"[^{}]*?"s":"(QB|RB|WR|TE|K|DST)"', txt):
        name, pos = m.group(1), m.group(2)
        out[name] = pos
        # Suffix-stripped alias (history names often lack Jr./II/III),
        # mirroring the site's _campNewsNorm matching.
        stripped = re.sub(r'\s+(Jr\.?|Sr\.?|II|III|IV|V)$', '', name)
        if stripped != name:
            out.setdefault(stripped, pos)
    return out


def compute_movers():
    hist = json.load(open(HIST, encoding='utf-8'))
    days = sorted((d for d in hist.get('days', []) if d.get('date') and d.get('adps')),
                  key=lambda d: d['date'])
    if len(days) < 2:
        raise SystemExit('not enough snapshot days')
    latest = days[-1]
    tgt = datetime.strptime(latest['date'], '%Y-%m-%d') - timedelta(days=7)
    base = min(days[:-1], key=lambda d: abs(datetime.strptime(d['date'], '%Y-%m-%d') - tgt))
    span = (datetime.strptime(latest['date'], '%Y-%m-%d') - datetime.strptime(base['date'], '%Y-%m-%d')).days
    movers = []
    for name, now_e in latest['adps'].items():
        old_e = base['adps'].get(name)
        if not now_e or not old_e:
            continue
        nb, ob = now_e.get('bbm'), old_e.get('bbm')
        if not isinstance(nb, (int, float)) or not isinstance(ob, (int, float)):
            continue
        if min(nb, ob) > 250:
            continue
        delta = nb - ob
        if abs(delta) < 3:
            continue
        pct = abs(delta) / ob if ob > 0 else 0
        movers.append({'name': name, 'from': ob, 'to': nb, 'delta': delta, 'pct': pct})
    movers.sort(key=lambda m: -m['pct'])
    return movers[:10], span, latest['date']


def fmt(v):
    s = f'{v:.1f}'
    return s[:-2] if s.endswith('.0') else s


def render(movers, span, date_str):
    pos_of = load_positions()
    img = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(img)

    # Header
    d.rectangle([0, 0, W, 6], fill=ACCENT)
    d.text((48, 36), 'ADP MOVERS', font=font(56, True), fill=TEXT)
    d.text((48, 104), f'Underdog Best Ball ADP · last {span} day{"s" if span != 1 else ""}', font=font(26), fill=MUTED)
    site = 'myfantasyfootball.co'
    sw = d.textlength(site, font=font(30, True))
    d.text((W - 48 - sw, 44), site, font=font(30, True), fill=ACCENT)
    nice = datetime.strptime(date_str, '%Y-%m-%d').strftime('%b %d, %Y')
    dw = d.textlength(nice, font=font(24))
    d.text((W - 48 - dw, 88), nice, font=font(24), fill=MUTED)

    # Two columns x 5 rows of mover panels
    top, row_h, gap, col_w = 160, 84, 10, (W - 96 - 24) // 2
    f_name, f_meta, f_pct, f_pos = font(28, True), font(23), font(30, True), font(20, True)
    for i, m in enumerate(movers):
        col, row = i % 2, i // 2
        x = 48 + col * (col_w + 24)
        y = top + row * (row_h + gap)
        up = m['delta'] < 0  # ADP number falling = drafted earlier = riser
        color = GREEN if up else RED
        d.rounded_rectangle([x, y, x + col_w, y + row_h], radius=10, fill=PANEL, outline=BORDER, width=1)
        d.rectangle([x, y + 10, x + 5, y + row_h - 10], fill=color)
        arrow = '▲' if up else '▼'
        d.text((x + 20, y + 14), arrow, font=f_name, fill=color)
        name = m['name']
        if d.textlength(name, font=f_name) > col_w - 250:
            while name and d.textlength(name + '…', font=f_name) > col_w - 250:
                name = name[:-1]
            name += '…'
        d.text((x + 60, y + 12), name, font=f_name, fill=TEXT)
        pos = pos_of.get(m['name'], '')
        if pos:
            pw = d.textlength(pos, font=f_pos)
            px = x + 60 + d.textlength(name, font=f_name) + 12
            pc = POS_COLORS.get(pos, MUTED)
            d.rounded_rectangle([px, y + 15, px + pw + 14, y + 41], radius=6,
                                fill=(pc[0] // 5 + 10, pc[1] // 5 + 12, pc[2] // 5 + 18))
            d.text((px + 7, y + 17), pos, font=f_pos, fill=pc)
        d.text((x + 60, y + 48), f'{fmt(m["from"])} → {fmt(m["to"])}', font=f_meta, fill=MUTED)
        pct_s = ('+' if up else '−') + str(round(m['pct'] * 100)) + '%'
        pw = d.textlength(pct_s, font=f_pct)
        d.text((x + col_w - 20 - pw, y + 26), pct_s, font=f_pct, fill=color)

    os.makedirs(os.path.dirname(OUT_PNG), exist_ok=True)
    img.save(OUT_PNG, optimize=True)
    return os.path.getsize(OUT_PNG)


def write_html(movers, span, date_str):
    stamp = date_str.replace('-', '')
    ups = sum(1 for m in movers if m['delta'] < 0)
    desc = (f'Top Underdog BBM ADP movers over the last {span} days — '
            f'{ups} risers, {len(movers) - ups} fallers. Updated daily.')
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ADP Movers · MyFantasyFootball</title>
<meta name="description" content="{desc}">
<meta property="og:type" content="website">
<meta property="og:url" content="https://www.myfantasyfootball.co/movers.html">
<meta property="og:title" content="ADP Movers · MyFantasyFootball">
<meta property="og:description" content="{desc}">
<meta property="og:site_name" content="MyFantasyFootball">
<meta property="og:image" content="https://www.myfantasyfootball.co/og/movers.png?d={stamp}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="ADP Movers · MyFantasyFootball">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="https://www.myfantasyfootball.co/og/movers.png?d={stamp}">

<link rel="canonical" href="https://www.myfantasyfootball.co/movers.html">
<meta http-equiv="refresh" content="0; url=/">
<script>window.location.replace("/");</script>
<style>body{{font-family:system-ui,sans-serif;background:#0a0e17;color:#e2e8f0;margin:0;padding:2rem;text-align:center}}a{{color:#f59e0b}}</style>
</head>
<body>
<p>Redirecting to <a href="/">the live ADP movers on MyFantasyFootball</a>...</p>
</body>
</html>
"""
    open(OUT_HTML, 'w', encoding='utf-8', newline='\n').write(html)


def main():
    movers, span, date_str = compute_movers()
    if len(movers) < 4:
        raise SystemExit(f'only {len(movers)} movers - refusing to render a sparse card')
    size = render(movers, span, date_str)
    write_html(movers, span, date_str)
    print(f'og/movers.png written ({size:,} bytes, {len(movers)} movers, '
          f'span {span}d, {date_str}) + movers.html')


if __name__ == '__main__':
    main()
