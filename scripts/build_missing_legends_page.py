#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_missing_legends_page.py — a checklist page of legends the Trivia board still
shows as initials (or only in a post-career photo), with image-search links and
the exact team folder to save into, so Jack can pick photos by hand. Nothing is
downloaded by this script (Google Images forbids scripted fetching and the hits
are rights-reserved press photos — the choice is Jack's, one photo at a time).

Writes <All Time Players>/_missing_legends.html (outside the repo). Open it in a
browser, click a search link, save the photo as "<Name>.jpg" into the folder the
row names, then run scripts/make_legend_headshots.py.

Usage: python -I scripts/build_missing_legends_page.py [--all]
  default: notable legends (3+ seasons >= 150 fpts) without any photo, then the
           notable ones whose only photo is post-career (no jersey match)
  --all:   every legend without a photo
"""
import argparse
import html
import json
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_legend_headshots as blh  # noqa: E402
import legend_teams as lt             # noqa: E402

OUT = os.path.join(lt.ROOT_DIR, '_missing_legends.html')


def primary_team(seasons):
    by = blh.team_by_year(seasons)
    if not by:
        return None
    counts = {}
    for t in by.values():
        counts[t] = counts.get(t, 0) + 1
    return max(counts, key=counts.get)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true')
    args = ap.parse_args()
    careers = blh.load_careers()
    espn = blh.load_espn_names()
    commons = blh.load_existing()
    local = {}
    lp = os.path.join(blh.DATA, 'legend_hs_local.js')
    if os.path.exists(lp):
        import re
        m = re.search(r'LEGEND_HEADSHOTS_LOCAL\s*=\s*(\{.*\})\s*;', open(lp, encoding='utf-8').read(), re.S)
        if m:
            local = json.loads(m.group(1))
    suspects = set()
    sp = os.path.join(blh.ROOT, 'scripts', '_suspect_espn_ids.json')
    if os.path.exists(sp):
        suspects = {r['name'] for r in json.load(open(sp, encoding='utf-8')).get('suspects', [])}

    def fpts(n):
        return round(sum(s.get('fpts') or 0 for s in careers[n]))

    def span(n):
        ys = [s['yr'] for s in careers[n] if s.get('yr')]
        return '%d-%d' % (min(ys), max(ys)) if ys else ''

    rows_none, rows_suit = [], []
    for n, s in careers.items():
        if n in local:
            continue
        has_espn = n in espn and n not in suspects
        notable = blh.is_notable(s)
        if not notable and not args.all:
            continue
        if has_espn:
            continue
        if n not in commons:
            rows_none.append(n)
        elif not commons[n].get('byTeam') and notable:
            rows_suit.append(n)
    rows_none.sort(key=lambda n: -fpts(n))
    rows_suit.sort(key=lambda n: -fpts(n))

    def row(n):
        t = primary_team(careers[n])
        tf = lt.TEAM_FOLDERS.get(t)
        folder = os.path.join(*tf) if tf else '(team unknown — put it anywhere under the root)'
        nick = tf[2] if tf else ''
        q = urllib.parse.quote_plus('%s %s football' % (n, nick))
        links = ' · '.join([
            '<a href="https://www.google.com/search?tbm=isch&q=%s" target="_blank">Google</a>' % q,
            '<a href="https://www.bing.com/images/search?q=%s" target="_blank">Bing</a>' % q,
            '<a href="https://www.gettyimages.com/photos/%s" target="_blank">Getty</a>' % urllib.parse.quote(n),
            '<a href="https://commons.wikimedia.org/w/index.php?search=%s&ns6=1" target="_blank">Commons</a>' % urllib.parse.quote_plus(n),
        ])
        return ('<tr><td><label><input type="checkbox"> <b>%s</b></label></td><td>%s</td><td>%s</td><td>%s</td>'
                '<td><code>%s</code></td><td>%s</td></tr>' % (
                    html.escape(n), blh.legend_group(careers[n]), span(n), fpts(n),
                    html.escape(folder), links))

    def table(rows, title, note):
        if not rows:
            return ''
        return ('<h2>%s <small>(%d)</small></h2><p>%s</p><table><tr><th>Player</th><th>Pos</th><th>Years</th>'
                '<th>Fpts</th><th>Save into (under %s)</th><th>Search</th></tr>%s</table>' % (
                    title, len(rows), note, html.escape(lt.ROOT_DIR), ''.join(row(n) for n in rows)))

    page = '''<!doctype html><meta charset="utf-8"><title>Missing legend photos</title>
<style>body{font-family:system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#111}
table{border-collapse:collapse;width:100%%;font-size:14px}td,th{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top}
code{font-size:12px;background:#f3f3f3;padding:2px 4px}small{color:#777;font-weight:normal}h2{margin-top:32px}
tr:has(input:checked){opacity:.45;text-decoration:line-through}</style>
<h1>Legends still without a trivia photo</h1>
<p>Generated %s. Pick a photo in uniform (face visible, head not cut off, ideally a clean background),
save it as <code>&lt;Player Name&gt;.jpg</code> into the folder on the row, then run
<code>python -I scripts/make_legend_headshots.py</code>. Tick the box when done (the tick is not saved).
Rights note: anything Google/Bing shows is a press photo; Commons results are the only free-to-publish ones.</p>
%s%s''' % (time.strftime('%Y-%m-%d %H:%M'),
           table(rows_none, 'No photo at all', 'These reveal as initials today.'),
           table(rows_suit, 'Photo exists but not in uniform', 'Optional: today these show a post-career Commons photo (suit, event). A jersey shot would replace it.'))
    os.makedirs(lt.ROOT_DIR, exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(page)
    print('no photo: %d · not in uniform: %d -> %s' % (len(rows_none), len(rows_suit), OUT))


if __name__ == '__main__':
    main()
