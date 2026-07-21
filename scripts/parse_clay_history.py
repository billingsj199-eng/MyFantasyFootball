#!/usr/bin/env python3
"""
parse_clay_history.py — Extract historical Mike Clay projections from ESPN
draft-kit PDFs into data/clay_history.json for the backtest harness.

PDFs come from ESPN's draft kit CDN (predictable URLs):
  2021-2026: https://g.espncdn.com/s/ffldraftkit/{YY}/NFLDK20{YY}_CS_ClayProjections20{YY}.pdf
  2019-2020: https://g.espncdn.com/s/ffldraftkit/{YY}/NFLDK20{YY}_CS_ClayProjections.pdf
  (2018 and earlier: not hosted)

Team pages have offense rows like:
  QB Kyler Murray 10 345 228 2368 13 8 23 59 350 3 0 0 0 0 178 30 <defense cols...>
i.e. Pos Name then 16 numbers: Gm PassAtt Comp PassYds PassTD INT Sk
RushAtt RushYds RushTD Tgt Rec RecYds RecTD PtsPPR PosRk. We keep
{pos, gm, pts (PPR), rec} per player-year — enough to convert to any
rec-scoring format (half = pts - 0.5*rec, std = pts - rec).

Usage: python scripts/parse_clay_history.py <pdf_dir>
"""

import json
import os
import re
import sys

import pdfplumber

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(os.path.dirname(SCRIPT_DIR), 'data', 'clay_history.json')
POS = {'QB', 'RB', 'WR', 'TE'}


SECTION_POS = {'QUARTERBACK': 'QB', 'RUNNING': 'RB', 'WIDE': 'WR', 'TIGHT': 'TE'}


def _split_row(toks):
    """Name tokens, then the run of numeric tokens (stops at defense text)."""
    name_toks, nums = [], []
    for t in toks:
        tt = t.replace(',', '').rstrip('%')
        if re.fullmatch(r'-?\d+(\.\d+)?', tt):
            nums.append(float(tt))
        elif not nums:
            name_toks.append(t)
        else:
            break
    return ' '.join(name_toks), nums


def parse_pdf(path, year):
    out = {}

    def keep(name, pos, gm, pts, rec):
        if gm < 1 or not name or name in ('Total', 'Player'):
            return
        # keep the higher-pts row on duplicate names (traded players can
        # appear on two team pages)
        prev = out.get(name)
        if prev and prev['pts'] >= pts:
            return
        out[name] = {'pos': pos, 'gm': gm, 'pts': pts, 'rec': rec}

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            if 'Projections' not in text.split('\n', 1)[0]:
                continue
            section = None  # 2019-2020 layout: position section headers
            for line in text.split('\n'):
                toks = line.split()
                if not toks:
                    continue
                if toks[0] in SECTION_POS:
                    section = SECTION_POS[toks[0]]
                    continue
                if toks[0] in POS:
                    # 2021+ layout: "QB Name <16 numbers> <defense...>"
                    if toks[1] == 'Total':
                        continue
                    name, nums = _split_row(toks[1:])
                    if len(nums) >= 16:
                        keep(name, toks[0], nums[0], nums[14], nums[11])
                elif section:
                    # 2019-2020 layout: "Name <QB:12 / RB,WR,TE:10 numbers>"
                    name, nums = _split_row(toks)
                    if section == 'QB' and len(nums) >= 12:
                        keep(name, 'QB', nums[0], nums[10], 0.0)
                    elif section != 'QB' and len(nums) >= 10:
                        keep(name, section, nums[0], nums[8], nums[5])
    return out


def main():
    pdf_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    history = {}
    for fn in sorted(os.listdir(pdf_dir)):
        m = re.match(r'clay(20\d\d)\.pdf$', fn)
        if not m:
            continue
        year = int(m.group(1))
        players = parse_pdf(os.path.join(pdf_dir, fn), year)
        history[str(year)] = players
        qbs = sum(1 for p in players.values() if p['pos'] == 'QB')
        print(f'{year}: {len(players)} players ({qbs} QBs)')
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(history, f, separators=(',', ':'))
    print(f'Wrote {OUT_PATH} ({os.path.getsize(OUT_PATH) // 1024} KB)')


if __name__ == '__main__':
    sys.exit(main())
