# fix_kickers_20260831.py — post-cutdown kicker board fix for data/d.js.
#
# Audit of the 10 "stale backup" kickers flagged in BACKLOG.md against
# Sleeper depth charts (2026-08-31, post 53-man cutdown; season starts 09-10):
# the daily roster sync (update_rosters.py, Phase H) already fixed every "t"
# field, but the editorial K ranks ("r") were never revisited, leaving four
# CURRENT STARTERS buried in scrub territory and one new backup in a starter
# slot:
#
#   Spencer Shrader  K36 -> IND starter (dc=1); Blake Grupe K24 is now the
#                    IND backup — their board slots (and p values) swap.
#   Matt Gay         K32 -> LV starter (dc=1), was tagged as SF backup.
#   Dominic Zvada    K46 -> NYG starter (dc=1), rookie; had p:null which
#                    breaks the d.p/17 projection fallback.
#   Drew Stevens     K47 -> WAS starter (dc=1); added 2026-08-25 (58d4215)
#                    as "K47" pending a real rank.
#
# The other eight flagged names are genuinely FA/backup and stay where they
# are: Romo, Badgley, Havrisik, Wright, Karty, Gano, McAtamney (all FA) and
# Sauls (NYG backup behind Zvada, Questionable).
#
# LESSON FROM fix_kickers_20260722.py, KEPT HERE: the K board is editorial,
# NOT p-sorted (Butker p=148 at K11, buried-FA Koo/Moody are deliberate).
# We splice movers in after named anchors and renumber sequentially; the
# relative order of every other kicker is unchanged. Never p-sort.
#
# p hand-estimates (17-game season points, same style as the 07-22 inserts):
# Shrader takes Grupe's old IND-job number and vice versa; Gay 105.3 (LV
# job, weak offense); Zvada 99.9 (NYG job, rookie). Stevens keeps his 139.4.
#
# MIA is deliberately NOT touched: Riley Patterson stays (Sleeper now lists
# him as the MIA starter and Zane Gonzalez is teamless/Inactive) — Jack's
# call, see the session report.
#
# Re-runnable: no-ops (asserts) if the moves have already been applied.

import datetime
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D_PATH = os.path.join(ROOT, "data", "d.js")
INDEX_PATH = os.path.join(ROOT, "index.html")

# mover -> (anchor kicker to insert after, old p literal, new p) ; anchors are
# non-movers so insertion order is irrelevant.
MOVES = {
    "Drew Stevens":    ("Tyler Bass",      None,    None),   # p 139.4 kept
    "Matt Gay":        ("Nick Folk",       "76.5",  "105.3"),
    "Spencer Shrader": ("Chad Ryland",     "50.4",  "108.9"),
    "Blake Grupe":     ("Michael Badgley", "108.9", "50.4"),  # demotion
    "Dominic Zvada":   ("Daniel Carlson",  "null",  "99.9"),
}

src = open(D_PATH, encoding="utf-8").read()

# --- 1. splice new p values (compact JSON: "n":"Name","a":240,"p":<old>) ---
for name, (_, old_p, new_p) in MOVES.items():
    if old_p is None:
        continue
    pat = re.compile(r'("n":"' + re.escape(name) + r'","a":\d+,"p":)' + re.escape(old_p) + r'(,"s":"K")')
    src, n = pat.subn(r"\g<1>" + new_p + r"\g<2>", src, count=1)
    assert n == 1, f"could not update p for {name} (already applied?)"

# --- 2. rebuild the board order: current r order, movers re-anchored ---
data = json.loads(src[src.index("["): src.rindex("]") + 1])
kickers = sorted((d for d in data if d.get("s") == "K"), key=lambda d: int(d["r"][1:]))
board = [d for d in kickers if d["n"] not in MOVES]
by_name = {d["n"]: d for d in kickers}
for name, (after, _, _) in MOVES.items():
    idx = next(i for i, d in enumerate(board) if d["n"] == after)
    board.insert(idx + 1, by_name[name])

# --- 3. renumber via surgical regex, exactly like the 07-22 script ---
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
