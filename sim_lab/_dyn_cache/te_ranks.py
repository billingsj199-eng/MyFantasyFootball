import json
import sys


def load(p):
    raw = open(p, encoding='utf-8').read()
    return json.JSONDecoder().raw_decode(raw, raw.index('{"'))[0]


new = load(sys.argv[1])
old = load(sys.argv[2])
for fmt in ('1qb', 'sf'):
    print('---', fmt, '(old preseason -> new)')
    te = sorted((e for e in new['players'].values() if e['pos'] == (sys.argv[3] if len(sys.argv) > 3 else 'TE') and fmt in e), key=lambda e: e[fmt]['rk'])[:12]
    for e in te:
        o = next((x for x in old['players'].values() if x['n'] == e['n'] and x['pos'] == e['pos']), None)
        print(f"{e['n']:<22} age{e['age']} g26 {e.get('g26')} #{e[fmt]['rk']:<4} val {e[fmt]['val']:5.0f}   "
              f"old #{o[fmt]['rk'] if o and fmt in o else '-'}")
