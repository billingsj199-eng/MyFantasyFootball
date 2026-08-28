"""COMBINE<->ALL name-collision audit + fix (the 151 from the 2026-07-21 audit).

A D-array ACTIVE player whose COMBINE_DATA draft-class year is Y cannot have
NFL seasons before Y — any such rows under his name in ALL_PLAYERS_DB /
LEGEND_CAREERS / his own d.js career belong to a DIFFERENT (usually retired)
player with the same name, and the runtime _bestCareer merge grafts them onto
the active player's card, Fantasy Game entry and stats surfaces.

Audit (default, no writes): for every D player with a COMBINE_DATA entry
(combine_d_patches.js applied), flag pre-draft rows per source and classify:

  WHOLE  - every row in the source entry predates the draft year -> the whole
           entry is the other player: rename its key/name to
           "<Name> (<POS> <first>-<last>)" so the active player's lookup
           misses it cleanly. The retired player keeps his data under the
           disambiguated key (same convention as PLAYER_TEAM_HISTORY's
           "David Johnson (TE)").
  SPLIT  - mixed entry (Franken-career): pre-draft rows move to the renamed
           sibling entry, post-draft rows stay on the bare name. Only done
           when the entry's own `debut` anchors to the OLD player
           (debut <= draftYr - 2) or positions differ; otherwise REVIEW.
  DJS    - d.js career/s25 rows before the draft year: deleted (the boot
           aggregation grafted the old player's seasons).
  REVIEW - ambiguous (eras overlap with same position) - listed, untouched.

--write applies fixes with .bak_pre_collision backups. Re-runnable/idempotent:
a second audit pass after --write must report zero WHOLE/SPLIT/DJS.

Run:  python scripts/fix_combine_all_collisions.py [--write]
"""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DJS = ROOT / 'data' / 'd.js'
ALL = ROOT / 'data' / 'all_players.js'
LEG = ROOT / 'data' / 'legend_careers.js'
COMBINE = ROOT / 'data' / 'combine_data.js'
PATCHES = ROOT / 'data' / 'combine_d_patches.js'


def extract_json(path, prefix_re):
    """raw_decode from the prefix: returns (text, start, end, obj) where
    text[start:end] is exactly the JSON payload — robust to trailing code."""
    text = path.read_text(encoding='utf-8')
    m = re.search(prefix_re, text)
    start = m.end()
    obj, consumed = json.JSONDecoder().raw_decode(text[start:])
    return text, start, start + consumed, obj


def load_combine_years():
    """name -> draft-class year, with combine_d_patches.js overrides applied."""
    text = COMBINE.read_text(encoding='utf-8')
    years = {}
    for m in re.finditer(r'"((?:[^"\\]|\\.)+)":\{([^{}]*)\}', text):
        name = m.group(1).replace('\\"', '"')
        ym = re.search(r'"yr":(\d{4})', m.group(2))
        if ym:
            years[name] = int(ym.group(1))
    if PATCHES.exists():
        pt = PATCHES.read_text(encoding='utf-8')
        # COMBINE_DATA["Name"] = {...yr:2025...} style force-overwrites
        for m in re.finditer(r'COMBINE_DATA\[["\']((?:[^"\'\\]|\\.)+)["\']\]\s*=\s*\{([^{}]*)\}', pt):
            ym = re.search(r'yr\s*:\s*(\d{4})', m.group(2))
            if ym:
                years[m.group(1)] = int(ym.group(1))
    return years


def main():
    write = '--write' in sys.argv
    combine_yr = load_combine_years()

    d_text, d_start, d_end, d_arr = extract_json(DJS, r'const D\s*=\s*')
    # Active board players only (skip devy/future-pick pseudo rows)
    actives = {}
    for p in d_arr:
        n = p.get('n')
        if not n or n not in combine_yr:
            continue
        actives[n] = {'pos': p.get('s'), 'draftYr': combine_yr[n], 'd': p}

    _, a_start, a_end, all_db = extract_json(ALL, r'const ALL_PLAYERS_DB\s*=\s*')
    all_by_name = {}
    for e in all_db:
        all_by_name.setdefault(e.get('name'), e)  # dupNames audit said 0

    _, l_start, l_end, leg = extract_json(LEG, r'const LEGEND_CAREERS\s*=\s*')

    whole, split, review, djs_rows = [], [], [], []

    def suffix_key(name, entry_rows, pos):
        yrs = [r['yr'] for r in entry_rows if isinstance(r.get('yr'), int)]
        era = f"{min(yrs)}-{max(yrs)}" if yrs else 'era'
        return f"{name} ({pos or '??'} {era})"

    for name, info in sorted(actives.items()):
        dy = info['draftYr']
        # --- ALL_PLAYERS_DB ---
        e = all_by_name.get(name)
        if e:
            rows = e.get('career') or []
            pre = [r for r in rows if isinstance(r.get('yr'), int) and r['yr'] < dy]
            if pre:
                post = [r for r in rows if r not in pre]
                pos_mismatch = e.get('pos') and info['pos'] and e['pos'] != info['pos']
                debut_old = isinstance(e.get('debut'), int) and e['debut'] <= dy - 2
                if not post:
                    whole.append(('ALL', name, dy, e['pos'], len(pre), suffix_key(name, pre, e.get('pos'))))
                elif pos_mismatch or debut_old:
                    # Same-era overlap with same pos would be ambiguous — but a
                    # different pos or an old debut anchors the pre rows to the
                    # other player; post rows keep the bare name.
                    split.append(('ALL', name, dy, e['pos'], len(pre), len(post), suffix_key(name, pre, e.get('pos'))))
                else:
                    review.append(('ALL', name, dy, e.get('pos'), len(pre), len(post),
                                   sorted({r['yr'] for r in pre})))
        # --- LEGEND_CAREERS ---
        lrows = leg.get(name)
        if lrows:
            pre = [r for r in lrows if isinstance(r.get('yr'), int) and r['yr'] < dy]
            if pre:
                post = [r for r in lrows if r not in pre]
                if not post:
                    whole.append(('LEG', name, dy, '?', len(pre), suffix_key(name, pre, info['pos'])))
                else:
                    review.append(('LEG', name, dy, '?', len(pre), len(post),
                                   sorted({r['yr'] for r in pre})))
        # --- d.js own career/s25 ---
        for r in (info['d'].get('career') or []):
            if isinstance(r.get('yr'), int) and r['yr'] < dy:
                djs_rows.append((name, dy, r['yr']))
        s25 = info['d'].get('s25')
        if s25 and isinstance(s25.get('yr'), int) and s25['yr'] < dy:
            djs_rows.append((name, dy, f"s25:{s25['yr']}"))

    print(f"actives with combine yr: {len(actives)}")
    print(f"WHOLE-entry renames: {len(whole)}")
    for t in whole:
        print('  WHOLE', t)
    print(f"SPLIT entries: {len(split)}")
    for t in split:
        print('  SPLIT', t)
    print(f"d.js pre-draft rows: {len(djs_rows)}")
    for t in djs_rows[:20]:
        print('  DJS', t)
    print(f"REVIEW (ambiguous, untouched): {len(review)}")
    for t in review:
        print('  REVIEW', t)

    if not write:
        print('\nDRY RUN — pass --write to apply (backups: .bak_pre_collision)')
        return

    # ---- apply ----
    for p, s in [(ALL, '.bak_pre_collision'), (LEG, '.bak_pre_collision'), (DJS, '.bak_pre_collision')]:
        bak = Path(str(p) + s)
        if not bak.exists():
            shutil.copyfile(p, bak)

    # ALL_PLAYERS_DB: rename whole entries; split mixed ones
    for kind, name, dy, pos, *rest in [t for t in whole if t[0] == 'ALL']:
        e = all_by_name[name]
        e['name'] = rest[-1]
    for kind, name, dy, pos, npre, npost, newkey in [t for t in split if t[0] == 'ALL']:
        e = all_by_name[name]
        rows = e.get('career') or []
        pre = [r for r in rows if isinstance(r.get('yr'), int) and r['yr'] < dy]
        post = [r for r in rows if r not in pre]
        e['career'] = post
        e['debut'] = min(r['yr'] for r in post)
        old = {k: v for k, v in e.items() if k not in ('career', 'debut', 'last')}
        old['name'] = newkey
        old['career'] = pre
        old['debut'] = min(r['yr'] for r in pre)
        old['last'] = max(r['yr'] for r in pre)
        all_db.append(old)
    a_text = ALL.read_text(encoding='utf-8')
    a_m = re.search(r'const ALL_PLAYERS_DB\s*=\s*', a_text)
    ALL.write_text(a_text[:a_m.end()] + json.dumps(all_db, ensure_ascii=False, separators=(',', ':'))
                   + a_text[a_text.rindex(';'):], encoding='utf-8', newline='\n')

    # LEGEND_CAREERS: rename whole entries
    for kind, name, dy, pos, npre, newkey in [t for t in whole if t[0] == 'LEG']:
        leg[newkey] = leg.pop(name)
    l_text = LEG.read_text(encoding='utf-8')
    l_m = re.search(r'const LEGEND_CAREERS\s*=\s*', l_text)
    LEG.write_text(l_text[:l_m.end()] + json.dumps(leg, ensure_ascii=False, separators=(',', ':'))
                   + l_text[l_text.rindex(';'):], encoding='utf-8', newline='\n')

    # d.js: drop pre-draft career rows
    for p in d_arr:
        n = p.get('n')
        if n in actives:
            dy = actives[n]['draftYr']
            if p.get('career'):
                p['career'] = [r for r in p['career'] if not (isinstance(r.get('yr'), int) and r['yr'] < dy)]
            if p.get('s25') and isinstance(p['s25'].get('yr'), int) and p['s25']['yr'] < dy:
                p['s25'] = None
    d_m = re.search(r'const D\s*=\s*', d_text)
    DJS.write_text(d_text[:d_m.end()] + json.dumps(d_arr, ensure_ascii=False, separators=(',', ':'))
                   + d_text[d_text.rindex(';'):], encoding='utf-8', newline='\n')

    print('\nWROTE fixes. Re-run without --write to confirm zero WHOLE/SPLIT/DJS.')


if __name__ == '__main__':
    main()
