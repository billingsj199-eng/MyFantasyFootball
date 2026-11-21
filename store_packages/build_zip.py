"""Build a Chrome Web Store zip for one MFF helper from its manifest (allowlist, never "zip the folder").

usage:  python -I store_packages/build_zip.py <sleeper|espn|yahoo|underdog> [--force]

Members = manifest.json + every file the manifest references (content_scripts js/css, background service
worker, web_accessible_resources, icons). Nothing else can get in, so mock*.html, mock_*data.js, _mock*,
*.md, *.bak*, sidebar.html and probes that the manifest drops stay out by construction.
Checks before writing: every member exists, jackSlice == 36 in data/players.json (premium gating),
no member name looks like a dev file, raw bytes have no c3 a2 mojibake in text members.
Output: store_packages/mff-<platform>-helper-<version>.zip (UD: mff-underdog-draft-helper-<version>.zip).
Building is not uploading: store_upload.py --publish still needs Jack's OK per build.
"""
import json, os, re, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NAMES = {'sleeper': 'mff-sleeper-helper', 'espn': 'mff-espn-helper', 'yahoo': 'mff-yahoo-helper',
         'underdog': 'mff-underdog-draft-helper'}
DEV = re.compile(r'(^|/)(mock[^/]*|_mock[^/]*|[^/]*\.md|[^/]*\.bak[^/]*|sidebar\.html)$', re.I)


def members(manifest):
    out = ['manifest.json']
    for cs in manifest.get('content_scripts', []):
        out += cs.get('js', []) + cs.get('css', [])
    bg = manifest.get('background', {})
    if bg.get('service_worker'):
        out.append(bg['service_worker'])
    for war in manifest.get('web_accessible_resources', []):
        out += war.get('resources', [])
    out += list(manifest.get('icons', {}).values())
    act = manifest.get('action', {})
    out += list((act.get('default_icon') or {}).values()) if isinstance(act.get('default_icon'), dict) else []
    if act.get('default_popup'):
        out.append(act['default_popup'])
    seen, res = set(), []
    for m in out:
        if '*' in m:
            raise SystemExit(f'wildcard resource {m!r}: list files explicitly')
        if m not in seen:
            seen.add(m); res.append(m)
    return res


def main():
    helper = sys.argv[1]
    force = '--force' in sys.argv
    src = os.path.join(ROOT, helper + '-extension')
    manifest = json.load(open(os.path.join(src, 'manifest.json'), encoding='utf-8'))
    ver = manifest['version']
    files = members(manifest)
    for m in files:
        if not os.path.isfile(os.path.join(src, m)):
            raise SystemExit(f'missing member {m}')
        if DEV.search(m):
            raise SystemExit(f'dev-looking member {m}')
    pj = os.path.join(src, 'data', 'players.json')
    if 'data/players.json' in files:
        js = json.load(open(pj, encoding='utf-8'))
        if js.get('jackSlice') != 36:
            raise SystemExit(f'players.json jackSlice is {js.get("jackSlice")!r}, expected 36 (premium gating)')
    for m in files:
        if m.endswith(('.js', '.css', '.json', '.html')):
            if b'\xc3\xa2\xc2\x80' in open(os.path.join(src, m), 'rb').read():
                raise SystemExit(f'mojibake (c3 a2 c2 80) in {m}')
    out = os.path.join(HERE, f'{NAMES[helper]}-{ver}.zip')
    if os.path.exists(out) and not force:
        raise SystemExit(f'{out} exists (use --force to rebuild)')
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for m in files:
            z.write(os.path.join(src, m), m)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        bad = [n for n in names if DEV.search(n)]
        assert not bad, bad
        assert z.testzip() is None
    print(f'OK {os.path.basename(out)}  {os.path.getsize(out):,} bytes  {len(names)} members')
    for n in names:
        print('   ', n)


if __name__ == '__main__':
    main()
