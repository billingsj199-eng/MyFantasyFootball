# fix_kickers_20260722.py — one-shot kicker roster fix for data/d.js.
#
# Sleeper depth charts (2026-07-22) showed three starting kickers missing from
# d.js entirely: Tyler Bass (BUF), Jason Sanders (NYJ), Trey Smack (GB, rookie
# ahead of Havrisik). Neither Bass nor Sanders has 2025 stats (ESPN confirms
# no 2025 rows — injury/out of league), so their entries carry no s25 line and
# the `p` season projections are hand-estimates, not model output.
#
# Inserts the three entries, then re-ranks ALL kicker `r` values by `p`
# descending via surgical string edits (no whole-file JSON round-trip, so the
# other ~3800 entries keep their exact bytes).

import json
import re

PATH = "data/d.js"

NEW_KICKERS = [
    # (fields follow the existing kicker entry order: n,a,p,s,r,t,...)
    {"n": "Tyler Bass", "a": 240, "p": 129.6, "s": "K", "r": "K99", "t": "Buffalo Bills",
     "p25": None, "p24": None, "p23": None, "age": None, "cyr": None, "out": None,
     "sal": None, "dr": None, "exp": None, "role": None, "inj": None,
     "s25": None, "career": [], "da": None, "sa": None, "slDy": None, "slDsf": None},
    {"n": "Jason Sanders", "a": 240, "p": 111.6, "s": "K", "r": "K99", "t": "New York Jets",
     "p25": None, "p24": None, "p23": None, "age": None, "cyr": None, "out": None,
     "sal": None, "dr": None, "exp": None, "role": None, "inj": None,
     "s25": None, "career": [], "da": None, "sa": None, "slDy": None, "slDsf": None},
    {"n": "Trey Smack", "a": 240, "p": 118.8, "s": "K", "r": "K99", "t": "Green Bay Packers",
     "p25": None, "p24": None, "p23": None, "age": None, "cyr": None, "out": None,
     "sal": None, "dr": None, "exp": None, "role": None, "inj": None,
     "s25": None, "career": [], "da": None, "sa": None, "slDy": None, "slDsf": None},
]

src = open(PATH, encoding="utf-8").read()

for k in NEW_KICKERS:
    assert f'"n":"{k["n"]}"' not in src.replace(": ", ":"), f"{k['n']} already present"

# Insert compact-JSON entries next to the other kickers (before Jake Moody).
anchor = '{"n": "Jake Moody"' if '{"n": "Jake Moody"' in src else '{"n":"Jake Moody"'
i = src.index(anchor)
# d.js is compact JSON (no spaces) — match it so the entries don't stand out.
blob = "".join(json.dumps(k, separators=(",", ":")) + "," for k in NEW_KICKERS)
src = src[:i] + blob + src[i:]

# Re-rank while PRESERVING the existing editorial order (the old r values are
# NOT p-sorted — Myers K1 / Fairbairn K2 / FA Koo buried at K39 are deliberate
# calls, so a p-sort would clobber the board). We splice the three new kickers
# in after named anchors and renumber sequentially; relative order of every
# existing kicker is unchanged.
INSERT_AFTER = {
    "Tyler Bass": "Tyler Loop",        # mid-tier starter, ~K13
    "Trey Smack": "Riley Patterson",   # GB rookie starter, ~K18
    "Jason Sanders": "Cairo Santos",   # NYJ starter, ~K21
}
data = json.loads(src[src.index("["): src.rindex("]") + 1])
existing = [d for d in data if d.get("s") == "K" and d["r"] != "K99"]
existing.sort(key=lambda d: int(d["r"][1:]))
kickers = existing
new_by_name = {d["n"]: d for d in data if d.get("s") == "K" and d["r"] == "K99"}
for name, after in INSERT_AFTER.items():
    idx = next(i for i, d in enumerate(kickers) if d["n"] == after)
    kickers.insert(idx + 1, new_by_name[name])

changes = []
for rank, d in enumerate(kickers, 1):
    new_r = f"K{rank}"
    if d.get("r") == new_r:
        continue
    # Locate this kicker's object: the '"n": "Name"' occurrence followed
    # shortly by '"s": "K"' (guards against same-name non-kickers).
    pat = re.compile(
        r'("n":\s*"' + re.escape(d["n"]) + r'",\s*"a":[^{]*?"s":\s*"K",\s*"r":\s*")K\d+(")'
    )
    src, n = pat.subn(r"\g<1>" + new_r + r"\g<2>", src, count=1)
    assert n == 1, f"could not re-rank {d['n']}"
    changes.append(f"{d['n']:22s} {d.get('r')} -> {new_r}")

open(PATH, "w", encoding="utf-8", newline="").write(src)

# Final sanity: file still parses, ranks are 1..N unique.
data = json.loads(src[src.index("["): src.rindex("]") + 1])
ks = [d for d in data if d.get("s") == "K"]
ranks = sorted(int(d["r"][1:]) for d in ks)
assert ranks == list(range(1, len(ks) + 1)), "rank sequence broken"
print(f"{len(ks)} kickers, ranks 1..{len(ks)} OK. {len(changes)} rank changes:")
for c in changes:
    print(" ", c)
