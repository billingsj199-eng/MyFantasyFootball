# fix_kickers_k1_only.py — keep only depth-chart K1 kickers on the data/d.js board.
#
# Jack 2026-10-12: "for kicker rankings only do kickers that are on the depth
# chart as the first kicker — remove all free agent or 2nd kickers from
# rankings and projections". Until now the board deliberately BURIED FA vets
# and backups (Koo, Moody, McManus, Prater, ...) instead of removing them, and
# stale backups could sit high (Blake Grupe K22 after NYJ flipped back to
# Jason Sanders).
#
# What it does: drops every "s":"K" entry whose name is not rank 1 under K for
# some team in data/depth_charts_2026.json (ESPN depth charts — Jack's
# authority), then renumbers the survivors K1..N in their CURRENT editorial
# order (never p-sorts — the board is editorial). Surgical: removed objects are
# cut by brace matching, ranks rewritten by one regex pass; every other byte
# is untouched. Aborts if any K1 is missing from the board (a new starter
# needs adding by hand first) or the chart has fewer than 32 K1s.
#
# Re-runnable: exits cleanly when the board is already K1-only.
#   python scripts/fix_kickers_k1_only.py [--dry-run]

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D_PATH = os.path.join(ROOT, "data", "d.js")
DC_PATH = os.path.join(ROOT, "data", "depth_charts_2026.json")


def k1_names():
    teams = json.load(open(DC_PATH, encoding="utf-8"))["teams"]
    names = {(v.get("K") or [None])[0] for v in teams.values()}
    names.discard(None)
    return names


def object_span(src, start):
    """[start, end) of the JSON object opening at src[start] == '{' (string-aware)."""
    depth, i, in_str = 0, start, False
    while i < len(src):
        c = src[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return start, i + 1
        i += 1
    raise ValueError("unbalanced object at %d" % start)


def kicker_objects(src):
    """[(name, rank_int, start, end)] for every "s":"K" entry, in file order."""
    out = []
    for m in re.finditer(r'\{"n":"((?:[^"\\]|\\.)*)"', src):
        s, e = object_span(src, m.start())
        body = src[s:e]
        if '"s":"K"' not in body:
            continue
        r = re.search(r'"r":"K(\d+)"', body)
        out.append((json.loads('"%s"' % m.group(1)), int(r.group(1)) if r else 10**6, s, e))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    k1 = k1_names()
    if len(k1) < 32:
        sys.exit("ABORT: depth chart has only %d K1s (expected 32)" % len(k1))
    src = open(D_PATH, encoding="utf-8").read()
    ks = kicker_objects(src)
    on_board = {k[0] for k in ks}
    missing = sorted(k1 - on_board)
    if missing:
        sys.exit("ABORT: K1s not on the board (add them first): %s" % ", ".join(missing))
    drop = [k for k in ks if k[0] not in k1]
    if not drop and [k[1] for k in sorted(ks, key=lambda k: k[1])] == list(range(1, len(ks) + 1)):
        print("board already K1-only (%d kickers) — nothing to do" % len(ks))
        return

    print("removing %d non-K1 kickers:" % len(drop))
    for n, r, _, _ in sorted(drop, key=lambda k: k[1]):
        print("  K%d %s" % (r, n))

    # cut removed objects back-to-front, taking one adjacent comma with each
    for n, r, s, e in sorted(drop, key=lambda k: -k[2]):
        if src[e:e + 1] == ",":
            e += 1
        elif src[s - 1:s] == ",":
            s -= 1
        src = src[:s] + src[e:]

    # renumber survivors by their current editorial order (one regex pass)
    keep = sorted((k for k in ks if k[0] in k1), key=lambda k: k[1])
    remap = {old: new for new, (_, old, _, _) in enumerate(keep, 1)}
    src = re.sub(r'"r":"K(\d+)"', lambda m: '"r":"K%d"' % remap.get(int(m.group(1)), int(m.group(1))), src)

    after = kicker_objects(src)
    assert {k[0] for k in after} == k1, "post-check: board != K1 set"
    assert sorted(k[1] for k in after) == list(range(1, len(k1) + 1)), "post-check: ranks not 1..N"
    print("board now %d kickers, K1..K%d" % (len(after), len(after)))
    if args.dry_run:
        print("(dry run — d.js not written)")
        return
    with open(D_PATH, "r+b") as f:  # r+b: Windows open(w) EINVAL on this file (see reference memory)
        data = src.encode("utf-8")
        f.seek(0)
        f.write(data)
        f.truncate()
    print("wrote", D_PATH)


if __name__ == "__main__":
    main()
