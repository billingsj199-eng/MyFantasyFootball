# Extract a user's REAL pods from an Underdog BBM full-field pick-by-pick CSV
# (the official data drop on underdognetwork.com/football/best-ball-research —
# BBM VI landed Sep 12 2025, right at contest close; BBM VII expected ~mid-Sep
# 2026) and emit ONE full-board CSV that Sim Lab's BEST BALL tab imports
# directly: every pod the user is in, all 12 real rosters per pod, teams
# grouped by the Draft column, drafters in a Username column so the tab spots
# the user's slot automatically.
#
#   python ingest_bbm_field.py "<rd1.csv>" --user jackb933 \
#          --title "Best Ball Mania VII" --fee 25 --out my_bbm_pods.csv
#
# Two streaming passes (the rd1 file is ~5GB): pass 1 finds the user's
# draft_ids from just (draft_id, username); pass 2 collects every pick in
# those drafts. Peak memory stays at one chunk.
import argparse
import csv
import sys

import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv_path')
    ap.add_argument('--user', required=True, help='Underdog username (case-insensitive)')
    ap.add_argument('--title', default='Best Ball Mania VII')
    ap.add_argument('--fee', type=float, default=25)
    ap.add_argument('--size', type=int, default=12)
    ap.add_argument('--out', default='my_bbm_pods.csv')
    ap.add_argument('--chunk', type=int, default=1_000_000)
    args = ap.parse_args()
    user = args.user.lower().strip().lstrip('@')

    # pass 1: which drafts is the user in?
    my_drafts = set()
    seen_rows = 0
    for ch in pd.read_csv(args.csv_path, usecols=['draft_id', 'username'],
                          chunksize=args.chunk, dtype=str):
        seen_rows += len(ch)
        hit = ch[ch.username.str.lower().str.strip() == user]
        my_drafts.update(hit.draft_id.unique())
        print(f'\r  pass 1: {seen_rows:,} rows, {len(my_drafts)} drafts found', end='', file=sys.stderr)
    print(file=sys.stderr)
    if not my_drafts:
        print(f'no drafts found for username "{args.user}" — check the spelling '
              f'(pass 1 scanned {seen_rows:,} rows)', file=sys.stderr)
        sys.exit(1)

    # pass 2: pull every pick in those drafts
    cols = ['draft_id', 'username', 'player_name', 'position_name',
            'overall_pick_number', 'draft_time']
    rows = []
    for ch in pd.read_csv(args.csv_path, usecols=cols, chunksize=args.chunk, dtype=str):
        rows.append(ch[ch.draft_id.isin(my_drafts)])
    df = pd.concat(rows, ignore_index=True)
    df['overall_pick_number'] = pd.to_numeric(df.overall_pick_number, errors='coerce')
    df = df.dropna(subset=['overall_pick_number', 'player_name'])
    df = df.sort_values(['draft_id', 'overall_pick_number'])

    with open(args.out, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(['Pick Number', 'Player', 'Position', 'Team', 'Draft',
                    'Tournament Title', 'Tournament Entry Fee', 'Draft Size',
                    'Picked At', 'Username'])
        for r in df.itertuples(index=False):
            w.writerow([int(r.overall_pick_number), r.player_name,
                        r.position_name or '', '', r.draft_id, args.title,
                        args.fee, args.size, str(r.draft_time or '')[:10],
                        r.username or ''])

    n_picks = len(df)
    print(f'wrote {args.out}: {len(my_drafts)} pods x full boards, {n_picks:,} picks '
          f'({n_picks / len(my_drafts):.0f}/pod). Import it on the BEST BALL tab '
          f'(username box = {args.user}) — every pod arrives with its REAL opponents.')


if __name__ == '__main__':
    main()
