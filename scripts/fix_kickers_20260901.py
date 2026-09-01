# fix_kickers_20260901.py — NYJ kicker swap for data/d.js (post-cutdown day 2).
#
# 2026-09-01 afternoon: the Jets released Jason Sanders to the practice squad
# and signed Blake Grupe (cut by IND this morning) as the active kicker.
# ESPN roster API: Grupe "Active", Sanders "Practice Squad"; ESPN depth chart
# lists Grupe as the ONLY NYJ pk. The daily roster sync already set both "t"
# fields to New York Jets; this fixes the editorial ranks, which don't sync:
#
#   Blake Grupe    K38 -> NYJ starter; takes Sanders' slot (after Cairo
#                  Santos) and Sanders' p (111.6, the NYJ-job number).
#   Jason Sanders  K22 -> NYJ practice squad; drops to Grupe's old slot
#                  (after Michael Badgley) with Grupe's old p (50.4).
#
# Same slot+p swap treatment Shrader/Grupe got in fix_kickers_20260831.py
# when the IND job flipped. Jake Moody (BAL per Sleeper, not yet on ESPN's
# roster) stays buried at K36 behind starter Tyler Loop — deliberate.
#
# DEPTH-CHART AUTHORITY (Jack's rule): pre-flight verifies Grupe is ESPN's
# rank-1 NYJ pk and ABORTS otherwise. LESSON KEPT: the K board is editorial,
# NOT p-sorted — splice movers after named anchors and renumber sequentially,
# never p-sort.
#
# Re-runnable: exits cleanly if the swap has already been applied.

import argparse
import datetime
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D_PATH = os.path.join(ROOT, "data", "d.js")
INDEX_PATH = os.path.join(ROOT, "index.html")

# mover -> (anchor kicker to insert after, old p literal, new p) ; anchors are
# non-movers so insertion order is irrelevant.
MOVES = {
    "Blake Grupe":   ("Cairo Santos",    "50.4",  "111.6"),  # promotion
    "Jason Sanders": ("Michael Badgley", "111.6", "50.4"),   # demotion
}

ESPN_DC_URL = ("https://sports.core.api.espn.com/v2/sports/football/leagues/"
               "nfl/seasons/{yr}/teams/{tid}/depthcharts")


def verify_espn_depth_chart(year):
    """Abort (SystemExit) unless ESPN's rank-1 NYJ placekicker is Grupe.
    Network/shape errors also abort — never edit the board on unverified
    assumptions."""
    import requests
    dc = requests.get(ESPN_DC_URL.format(yr=year, tid=20), timeout=20).json()
    starter = None
    for grp in dc.get("items", []):
        pk = grp.get("positions", {}).get("pk")
        if not pk:
            continue
        for a in pk.get("athletes", []):
            if a.get("rank") == 1:
                starter = requests.get(a["athlete"]["$ref"], timeout=20
                                       ).json().get("displayName")
    if starter != "Blake Grupe":
        sys.exit(f"ABORT: ESPN lists {starter!r} as NYJ's starting K, "
                 f"expected 'Blake Grupe' — depth chart changed, re-audit "
                 f"before running (or --skip-verify to override).")
    print(f"  ESPN NYJ: {starter} confirmed rank-1 pk")


ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
ap.add_argument("--skip-verify", action="store_true",
                help="skip the ESPN depth-chart pre-flight (offline runs)")
args = ap.parse_args()

if args.skip_verify:
    print("ESPN depth-chart verification SKIPPED (--skip-verify)")
else:
    print("Verifying mover against ESPN depth chart...")
    verify_espn_depth_chart(2026)

src = open(D_PATH, encoding="utf-8").read()

# --- 0. already applied? (all new p values in place, no old ones left) ---
def p_pat(name, p_lit):
    return r'"n":"' + re.escape(name) + r'","a":\d+,"p":' + re.escape(p_lit) + r',"s":"K"'

movers_p = [(n, o, p) for n, (_, o, p) in MOVES.items() if o is not None]
if (all(re.search(p_pat(n, new), src) for n, _, new in movers_p)
        and not any(re.search(p_pat(n, old), src) for n, old, _ in movers_p)):
    print("Moves already applied — nothing to do.")
    sys.exit(0)

# --- 1. splice new p values (compact JSON: "n":"Name","a":240,"p":<old>) ---
for name, (_, old_p, new_p) in MOVES.items():
    if old_p is None:
        continue
    pat = re.compile(r'("n":"' + re.escape(name) + r'","a":\d+,"p":)' + re.escape(old_p) + r'(,"s":"K")')
    src, n = pat.subn(r"\g<1>" + new_p + r"\g<2>", src, count=1)
    assert n == 1, f"could not update p for {name} (partially applied state?)"

# --- 2. rebuild the board order: current r order, movers re-anchored ---
data = json.loads(src[src.index("["): src.rindex("]") + 1])
kickers = sorted((d for d in data if d.get("s") == "K"), key=lambda d: int(d["r"][1:]))
board = [d for d in kickers if d["n"] not in MOVES]
by_name = {d["n"]: d for d in kickers}
for name, (after, _, _) in MOVES.items():
    idx = next(i for i, d in enumerate(board) if d["n"] == after)
    board.insert(idx + 1, by_name[name])

# --- 3. renumber via surgical regex, exactly like the 08-31 script ---
changes = []
for rank, d in enumerate(board, 1):
    new_r = f"K{rank}"
    if d["r"] == new_r:
        continue
    pat = re.compile(
        r'("n":\s*"' + re.escape(d["n"]) + r'",\s*"a":[^{]*?"s":\s*"K",\s*"r":\s*")K\d+(")'
    )
    src, n = pat.subn(r"\g<1>" + new_r + r"\g<2>", src, count=1)
    assert n == 1, f"could not re-rank {d['n']}"
    changes.append(f"{d['n']:22s} {d['r']} -> {new_r}")

open(D_PATH, "w", encoding="utf-8", newline="").write(src)

# --- 4. sanity: parses, ranks 1..N unique, movers landed with new p ---
data = json.loads(src[src.index("["): src.rindex("]") + 1])
ks = [d for d in data if d.get("s") == "K"]
ranks = sorted(int(d["r"][1:]) for d in ks)
assert ranks == list(range(1, len(ks) + 1)), "rank sequence broken"
for name, (_, _, new_p) in MOVES.items():
    if new_p is not None:
        got = next(d["p"] for d in ks if d["n"] == name)
        assert got == float(new_p), f"p splice failed for {name}: {got}"
print(f"{len(ks)} kickers, ranks 1..{len(ks)} OK. {len(changes)} rank changes:")
for c in changes:
    print(" ", c)

# --- 5. bump d.js ?v= in index.html (fresh read; hits preload AND tag) ---
html = open(INDEX_PATH, encoding="utf-8").read()
pat = re.compile(r"(data/d\.js\?v=)([\w.-]+)")
vals = set(m.group(2) for m in pat.finditer(html))
assert len(vals) == 1, f"mixed d.js ?v= values in index.html: {vals}"
old = vals.pop()
today = datetime.date.today().isoformat()
if old.startswith(today):
    suffix = old[len(today):]
    new = today + ("b" if not suffix else chr(ord(suffix[-1]) + 1))
else:
    new = today
html, n = pat.subn(r"\g<1>" + new, html)
open(INDEX_PATH, "w", encoding="utf-8").write(html)
print(f"index.html: d.js ?v={old} -> ?v={new} ({n} occurrences)")
