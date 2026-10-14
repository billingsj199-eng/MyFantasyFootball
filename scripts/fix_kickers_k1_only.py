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
# is untouched. Aborts if the chart has fewer than 32 K1s.
#
# 2026-10-14 (Jack: "make sure to run depth chart runs everyday, Mevis got
# cut"): now DAILY from scripts/daily_betting_pull.ps1 right after the depth
# pull, and self-sufficient - a chart K1 missing from the board is ADDED via
# scripts/add_pool_players.js (ESPN roster bio + headshot id, lands last in
# editorial order until Jack ranks him), a K1 whose "t" lags the chart (Sleeper
# keeps a cut kicker on his old team for days) is moved to his chart team, and
# the d.js / headshot_espn_ids.js ?v= tags are bumped when those files changed
# (read from disk right before, minute-stamped: the two-?v=-writers rule).
#
# Re-runnable: exits cleanly when the board is already K1-only.
#   python scripts/fix_kickers_k1_only.py [--dry-run] [--no-add]

import argparse
import json
import os
import re
import sys

import datetime
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D_PATH = os.path.join(ROOT, "data", "d.js")
DC_PATH = os.path.join(ROOT, "data", "depth_charts_2026.json")
HS_PATH = os.path.join(ROOT, "data", "headshot_espn_ids.js")
INDEX_PATH = os.path.join(ROOT, "index.html")
ADD_SCRIPT = os.path.join(ROOT, "scripts", "add_pool_players.js")
NODE = r"E:\node\node.exe" if os.path.exists(r"E:\node\node.exe") else (shutil.which("node") or "node")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update_rosters import TEAM_FULL  # abbr -> the full team name d.js uses  # noqa: E402


def k1_by_name():
    """{chart K1 name: team abbr} from ESPN depth charts (WSH/JAC-style abbrs already fixed by the puller)."""
    teams = json.load(open(DC_PATH, encoding="utf-8"))["teams"]
    out = {}
    for abbr, v in teams.items():
        k = (v.get("K") or [None])[0]
        if k:
            out[k] = abbr
    return out


def k1_names():
    return set(k1_by_name())


def read_file(path):
    return open(path, encoding="utf-8").read()


def write_file(path, text):
    with open(path, "r+b") as f:  # r+b: Windows open(w) EINVAL on d.js (see reference memory)
        f.seek(0)
        f.write(text.encode("utf-8"))
        f.truncate()


def bump_tag(html, fname):
    """Set every data/<fname> ?v= to a minute stamp (both the preload and the tag)."""
    pat = re.compile(r"(data/%s\?v=)([\w.-]+)" % re.escape(fname))   # data/ anchor: bare d.js also matched ep_retired.js
    if not pat.search(html):
        print("  WARN: no ?v= tag found for", fname)
        return html
    new = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    cur = pat.search(html).group(2)
    if cur == new:
        return html
    print("  bump %s ?v= %s -> %s" % (fname, cur, new))
    return pat.sub(lambda mm: mm.group(1) + new, html)


def add_missing(missing, dry_run):
    """Append the missing chart K1s to d.js (+ headshot ids) through add_pool_players.js."""
    cmd = [NODE, ADD_SCRIPT] + missing + (["--dry-run"] if dry_run else [])
    print("adding %d chart K1s not on the board via add_pool_players.js: %s" % (len(missing), ", ".join(missing)))
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
    for line in (r.stdout or "").strip().splitlines():
        print("  | " + line)
    if r.returncode != 0:
        print((r.stderr or "").strip()[-800:])
        sys.exit("ABORT: add_pool_players.js failed (exit %d)" % r.returncode)


def sync_teams(src, ks, k1):
    """A K1 whose "t" lags the chart team (Sleeper lag after a cut/signing) moves to his chart team."""
    moves = []
    for n, r, s, e in ks:
        if n not in k1:
            continue
        want = TEAM_FULL.get(k1[n])
        if not want:
            continue
        body = src[s:e]
        m = re.search(r'"t":"((?:[^"\\]|\\.)*)"', body)
        if m and m.group(1) != want:
            moves.append((n, m.group(1), want, s + m.start(1), s + m.end(1)))
    for n, old, new, a, b in sorted(moves, key=lambda x: -x[3]):
        print("  team %s: %s -> %s" % (n, old, new))
        src = src[:a] + new + src[b:]
    return src, bool(moves)


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
    ap.add_argument("--no-add", action="store_true", help="abort instead of adding chart K1s missing from the board")
    args = ap.parse_args()

    k1 = k1_by_name()
    if len(k1) < 32:
        sys.exit("ABORT: depth chart has only %d K1s (expected 32)" % len(k1))
    d_before, hs_before = read_file(D_PATH), read_file(HS_PATH)
    src = d_before
    ks = kicker_objects(src)
    on_board = {k[0] for k in ks}
    missing = sorted(set(k1) - on_board)
    if missing:
        if args.no_add:
            sys.exit("ABORT: K1s not on the board (add them first): %s" % ", ".join(missing))
        add_missing(missing, args.dry_run)
        if not args.dry_run:
            src = read_file(D_PATH)
            ks = kicker_objects(src)
            still = sorted(set(k1) - {k[0] for k in ks})
            if still:
                sys.exit("ABORT: still not on the board after add (name not on an ESPN roster?): %s" % ", ".join(still))
    drop = [k for k in ks if k[0] not in k1]
    src, moved = sync_teams(src, ks, k1)
    if drop:
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
    if not (missing and args.dry_run):
        assert {k[0] for k in after} == set(k1), "post-check: board != K1 set"
        assert sorted(k[1] for k in after) == list(range(1, len(k1) + 1)), "post-check: ranks not 1..N"
    if src == d_before:
        print("board already K1-only (%d kickers) - nothing to do" % len(after))
        return
    print("board now %d kickers, K1..K%d" % (len(after), len(after)))
    if args.dry_run:
        print("(dry run - d.js not written)")
        return
    write_file(D_PATH, src)
    print("wrote", D_PATH)
    html = read_file(INDEX_PATH)
    html2 = bump_tag(html, "d.js")
    if read_file(HS_PATH) != hs_before:
        html2 = bump_tag(html2, "headshot_espn_ids.js")
    if html2 != html:
        write_file(INDEX_PATH, html2)
        print("wrote", INDEX_PATH)


if __name__ == "__main__":
    main()
