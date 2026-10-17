"""pull_draft_boards.py - keep the NEXT draft class's projected draft capital current.

Sources (all refreshed on every run):
  * NFL Mock Draft Database CONSENSUS MOCK DRAFT (default 1-week window). Round 1
    is public; rounds 2+ need Jack's Mock+ login, read through scripts/fetch_mockdb.js
    (dedicated Chrome profile E:\\MyFantasyFootball\\mockdb_chrome_profile; re-sign-in
    with `node scripts/fetch_mockdb.js --login` when the log says SIGNED OUT):
    https://www.nflmockdraftdatabase.com/mock-drafts/<yr>/consensus-mock-draft-<yr>
    Jack (2026-10-17): the mock pick is the projected pick - more accurate for
    draft slot than the big board rank.
  * NFL Mock Draft Database consensus BIG BOARD (daily). Public page = top 100;
    signed in (Mock+) it runs ~1000 deep:
    https://www.nflmockdraftdatabase.com/big-boards/<yr>/consensus-big-board-<yr>
  Jack (2026-10-17): ONLY nflmockdraftdatabase - PFF big board and NFL Draft Buzz
  are no longer draftProj sources (NFLMDD is more up to date).
  Mock+ pages the headless fetch can't see (signed out) come from CSVs Jack's
  Chrome pulls by hand (Claude in Chrome): Site Rankings/mock_draft_<yr>.csv and
  Site Rankings/big_board_<yr>.csv - used for 10 days while deeper than the live page.

Writes scripts/draft_boards_<yr>.json (per-player ranks from each source,
for the audit) and patches data/combine_data.js:

  * draftProj for every skill-position (QB/RB/WR/TE) entry in the class
    (yr == <draft year>): consensus MOCK pick when the player is in the mock;
    otherwise max(last mock pick + 1, big-board rank) while the big-board rank is
    a draftable slot (<= 262); otherwise projected UDFA.
    If the mock page can't be read, the big-board rank is used unfloored.
    Entries with a real `draft` pick are never touched.
  * Universe = the RUNTIME devy board (combine_data.js + the stubs/overrides in
   data/combine_d_patches.js, via refresh_devy_stats.load_combine()). Stub entries
   get their draftProj through data/draft_proj.js (self-applying, loaded after the
   patches); combine_data.js entries are edited in place.
 * A class player on no NFLMDD board (or ranked past 262) becomes a projected UDFA
   (draftProj 'U' -> pick 300), so stale April projections go away but every class
   player still carries draft capital. eligYr > draft year (2028+) is always cleared.
 * --add: any skill player in the public big-board top 100 who is not in
    COMBINE_DATA gets a devy entry {yr, devy:true, eligYr, school, pos, draftProj}.
    The weekly devy stats refresh then backfills their college seasons + ht/wt.

Only the NEXT class is touched (Jack: "anything beyond that is too far out").
Bumps combine_data.js ?v= (both index.html tags) only when the file changed.

Usage:
    python scripts/pull_draft_boards.py [--year 2027] [--add] [--dry-run] [--no-bump]
"""
import argparse
import datetime
import hashlib
import html as htmlmod
import json
import os
import re
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

COMBINE_JS = "data/combine_data.js"
DRAFT_PROJ_JS = "data/draft_proj.js"
INDEX_HTML = "index.html"
SKILL = {"QB", "RB", "HB", "WR", "TE"}
CONS_URL = "https://www.nflmockdraftdatabase.com/big-boards/%d/consensus-big-board-%d"
MOCK_URL = "https://www.nflmockdraftdatabase.com/mock-drafts/%d/consensus-mock-draft-%d"
# Primary window first. The page shows one player per pick and each player once, so a
# round-1 player can vanish when he loses a slot (10-17: Moore/Mensah both at pick 6 -
# Moore only shows in the 2-week window). Players missing from the primary window take
# their pick from the next window that has them.
MOCK_PERIODS = ["1_week", "2_weeks", "1_month", "all_time"]
LAST_PICK = 262   # big-board rank past the last draft slot -> projected UDFA

# mock-site school spelling -> combine_data.js spelling
SCHOOL_FIX = {
    "Ohio State": "Ohio St.", "Penn State": "Penn St.", "Michigan State": "Michigan St.",
    "Arizona State": "Arizona St.", "Kansas State": "Kansas St.", "Oklahoma State": "Oklahoma St.",
    "Florida State": "Florida St.", "Iowa State": "Iowa St.", "Oregon State": "Oregon St.",
    "Mississippi State": "Mississippi St.", "Boise State": "Boise St.", "Washington State": "Washington St.",
    "Ole Miss": "Mississippi", "Miami": "Miami (FL)", "UCF": "Central Florida", "USC": "USC",
    "Louisiana Tech": "Louisiana Tech", "Notre Dame": "Notre Dame",
}


def log(*a):
    print(*a, flush=True)


def norm(n):
    n = (n or "").lower().strip()
    n = re.sub(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", "", n)
    return re.sub(r"[.'’\-\s]", "", n)



BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
              "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-US,en;q=0.9"}


def pull_consensus(year):
    """-> ({name: {rank,pos,school}}, updated_text). Plain HTTP with a browser UA
    (the site 403s bare clients). Each prospect card: rank span, /players/ link,
    position pill, /colleges/ link."""
    r = requests.get(CONS_URL % (year, year), headers=BROWSER_UA, timeout=40)
    r.raise_for_status()
    html = r.text
    m = re.search(r"Updated\W+(?:<[^>]*>\W*)*([A-Z][a-z]+ \d{1,2}, \d{4})", html)
    updated = m.group(1) if m else None
    card = re.compile(
        r'font-black[^>]*>\s*(\d{1,3})\s*</span>.*?href="/players/%d/[^"]+"[^>]*>\s*([^<]+?)\s*</a>'
        r'.*?rounded">\s*([A-Z]{1,4})\s*</span>.*?href="/colleges/%d/[^"]+"[^>]*>\s*([^<]+?)\s*</a>' % (year, year), re.S)
    out = {}
    for rank, name, pos, school in card.findall(html):
        name = htmlmod.unescape(re.sub(r"\s+", " ", name))
        if pos in SKILL and name not in out:
            out[name] = {"rank": int(rank), "pos": pos, "school": htmlmod.unescape(re.sub(r"\s+", " ", school))}
    return out, updated


MOCK_LOCK_WARNED = []
# Full mock (every unlocked round) pulled by hand through Jack's Chrome (Claude in Chrome,
# same-origin fetch of each ?period= page) when the headless profile is signed out.
# period,n_mocks,picks,pick,name,pos,pct,pulled - skill rows only; picks = page depth.
MOCK_CSV = "Site Rankings/mock_draft_%d.csv"
MOCK_CSV_MAX_AGE = 10   # days; older -> ignored (the live page wins)


def load_mock_csv(year, today):
    """-> {period: (skill rows {name: {...}}, picks, n_mocks, pulled)} when fresh, else {}."""
    import csv
    path = MOCK_CSV % year
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                pulled = datetime.date.fromisoformat(row["pulled"])
                if (today - pulled).days > MOCK_CSV_MAX_AGE:
                    continue
                rows, picks, n, _ = out.setdefault(row["period"], ({}, int(row["picks"]), row["n_mocks"], pulled))
                rows.setdefault(row["name"].strip(), {"pick": int(row["pick"]), "pos": row["pos"], "school": "", "pct": int(row["pct"] or 0)})
            except (KeyError, ValueError):
                continue
    return out


def fetch_mock_html(url):
    """Signed-in fetch through scripts/fetch_mockdb.js (Jack's Mock+ session in a
    dedicated Chrome profile -> every round); plain HTTP (round 1 only) when that
    fails. A signed-out profile still returns round 1 and logs a one-time warning."""
    import subprocess
    import tempfile
    fd, out = tempfile.mkstemp(suffix=".html")
    os.close(fd)
    try:
        p = subprocess.run(["node", os.path.join("scripts", "fetch_mockdb.js"), url, out],
                           capture_output=True, text=True, timeout=150)
        if p.returncode in (0, 4) and os.path.getsize(out) > 10000:
            if p.returncode == 4 and not MOCK_LOCK_WARNED:
                MOCK_LOCK_WARNED.append(1)
                log("MOCK+ SIGNED OUT - round 1 only; run: node scripts/fetch_mockdb.js --login")
            with open(out, encoding="utf-8") as f:
                return f.read()
        log("signed-in mock fetch failed (exit %s): %s" % (p.returncode, (p.stderr or p.stdout).strip()[-300:]))
    except Exception as e:  # noqa: BLE001
        log("signed-in mock fetch failed: %s" % e)
    finally:
        try:
            os.remove(out)
        except OSError:
            pass
    r = requests.get(url, headers=BROWSER_UA, timeout=40)
    r.raise_for_status()
    return r.text


BOARD_CSV = "Site Rankings/big_board_%d.csv"   # signed-in big board (Jack's Chrome), skill rows through 300


def load_board_csv(year, today):
    """-> ({name: {rank,pos}}, depth, updated, pulled) when <= MOCK_CSV_MAX_AGE days old, else ({}, 0, ...)."""
    import csv
    path = BOARD_CSV % year
    out, depth, upd, pulled = {}, 0, None, None
    if not os.path.exists(path):
        return out, depth, upd, pulled
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                pulled = datetime.date.fromisoformat(row["pulled"])
                if (today - pulled).days > MOCK_CSV_MAX_AGE:
                    return {}, 0, None, pulled
                depth, upd = int(row["depth"]), row["updated"]
                out.setdefault(row["name"].strip(), {"rank": int(row["rank"]), "pos": row["pos"]})
            except (KeyError, ValueError):
                continue
    return out, depth, upd, pulled

def pull_mock(year, period=None):
    """-> ({name: {pick,pos,school,pct}} for skill players, picks_shown, n_mocks).
    Consensus mock draft page; each pick card: pick-number span, /players/ link,
    position pill, optional /colleges/ link, share bar 'NN%'. Only round 1 is
    public (round 2+ cards are locked placeholders with no player link)."""
    url = MOCK_URL % (year, year) + ("?period=%s" % period if period else "")
    html = fetch_mock_html(url)
    m = re.search(r"Aggregated from\s*<strong>\s*(\d+)\s*mock", html)
    n_mocks = int(m.group(1)) if m else None
    card = re.compile(
        r'font-black leading-none"[^>]*>\s*(\d{1,3})\s*</span>.*?href="/players/%d/[^"]+">\s*([^<]+?)\s*</a>'
        r'\s*<div[^>]*>\s*<span[^>]*>\s*([A-Z]{1,4})\s*</span>'
        r'(?:(?:(?!font-black leading-none).)*?href="/colleges/%d/[^"]+".*?<span[^>]*>\s*([^<]+?)\s*</span>)?'
        r'.*?(\d{1,3})%%</span>' % (year, year), re.S)
    out, picks = {}, 0
    for pick, name, pos, school, pct in card.findall(html):
        picks = max(picks, int(pick))
        name = htmlmod.unescape(re.sub(r"\s+", " ", name))
        pos = "RB" if pos == "HB" else pos
        if pos in SKILL and name not in out:
            out[name] = {"pick": int(pick), "pos": pos, "school": htmlmod.unescape(school or ""), "pct": int(pct)}
    return out, picks, n_mocks



def digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()


def bump_tag(html, fname):
    today = datetime.date.today().isoformat()
    pat = re.compile(r"(%s\?v=)([\w.-]+)" % re.escape(fname))
    m = pat.search(html)
    if not m:
        log("  WARN: no ?v= tag for", fname)
        return html
    cur = m.group(2)
    m2 = re.match(r"%sdb(\d+)$" % re.escape(today), cur)
    new = today if not cur.startswith(today) else today + "db%d" % ((int(m2.group(1)) + 1) if m2 else 2)
    if cur == new:
        return html
    log("  bump %s ?v= %s -> %s" % (fname, cur, new))
    return pat.sub(lambda mm: mm.group(1) + new, html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, help="draft class year (default: next April's draft)")
    ap.add_argument("--add", action="store_true", help="add missing consensus/PFF top-100 skill players")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-bump", action="store_true")
    a = ap.parse_args()
    today = datetime.date.today()
    year = a.year or (today.year + 1 if today.month >= 5 else today.year)
    log("=== draft boards %d (%s) ===" % (year, today))

    cons_live, cons_upd = {}, None
    for attempt in range(3):
        try:
            cons_live, cons_upd = pull_consensus(year)
            if cons_live:
                break
        except Exception as e:  # noqa: BLE001
            log("consensus board attempt %d failed: %s" % (attempt + 1, e))
            time.sleep(5)
    live_depth = max((v["rank"] for v in cons_live.values()), default=0)
    log("consensus board (live): %d skill players through rank %d (updated %s)" % (len(cons_live), live_depth, cons_upd))
    cons = dict(cons_live)
    bb, bb_depth, bb_upd, bb_pulled = load_board_csv(year, today)
    if bb and bb_depth > live_depth:
        # Signed-in board from Jack's Chrome: ranks from the CSV, school from the live page.
        cons = {n: dict(v, school=cons_live.get(n, {}).get("school", "")) for n, v in bb.items()}
        cons_upd = bb_upd
        log("  big board: CSV from Jack's Chrome (%s, %d deep, %d skill through 300) beats live page" % (bb_pulled, bb_depth, len(bb)))
    if len(cons) < 10:
        # The consensus rank is the anchor for draftProj; without it every player
        # would go UDFA. Snapshot nothing, change nothing.
        log("consensus board unavailable - no draftProj changes this run (exit 3)")
        return 3
    mock_csv = load_mock_csv(year, today)

    def mock_window(per, attempts=1):
        """Live page vs the hand-pulled CSV: whichever shows more picks (rounds) wins."""
        live = ({}, 0, None)
        for attempt in range(attempts):
            try:
                live = pull_mock(year, per)
                if live[1] >= 20:
                    break
            except Exception as e:  # noqa: BLE001
                log("consensus mock %s attempt %d failed: %s" % (per, attempt + 1, e))
                time.sleep(5)
        if per in mock_csv and mock_csv[per][1] > live[1]:
            rows, picks, n, pulled = mock_csv[per]
            log("  mock %s: CSV from Jack's Chrome (%s, %d picks) beats live page (%d picks)" % (per, pulled, picks, live[1]))
            return dict(rows), picks, n
        return live

    mock, mock_picks, n_mocks = mock_window(MOCK_PERIODS[0], attempts=3)
    if mock_picks < 20:
        # Without the mock, keep the old big-board behaviour rather than flooring
        # every big-board player to pick 33.
        log("consensus mock unavailable (%d picks parsed) - big-board ranks only this run" % mock_picks)
        mock, mock_picks = {}, 0
    else:
        log("consensus mock (%s): %d picks from %s mocks, %d skill players" % (MOCK_PERIODS[0], mock_picks, n_mocks, len(mock)))
        for per in MOCK_PERIODS[1:]:
            extra, _, n_ex = mock_window(per)
            for n, v in extra.items():
                if n not in mock:
                    mock[n] = dict(v, window=per)
                    log("  mock fill-in (%s, %s mocks): %s pick %d (%d%%)" % (per, n_ex, n, v["pick"], v["pct"]))

    with open(COMBINE_JS, encoding="utf-8", newline="") as f:
        raw = f.read()
    head, body = raw.split("=", 1)
    cb = json.loads(body.strip().rstrip(";"))
    # Runtime devy board: combine_data.js + the stubs/overrides in combine_d_patches.js.
    import refresh_devy_stats as rds
    rds._CUR_SEASON = today.year if today.month >= 8 else today.year - 1
    rt = rds.load_combine()
    by_norm = {norm(n): n for n in cb}
    for n in rt:
        by_norm.setdefault(norm(n), n)
    def site_name(n):
        return n if n in cb else by_norm.get(norm(n))

    snapshot = {"year": year, "pulled": today.isoformat(), "consensus_updated": cons_upd,
                "mock_picks": mock_picks, "mock_n": n_mocks, "players": {}}
    for n in set(cons) | set(mock):
        info = cons.get(n) or mock.get(n)
        snapshot["players"][n] = {"mock": mock.get(n, {}).get("pick"), "mock_pct": mock.get(n, {}).get("pct"),
                                  "mock_window": mock.get(n, {}).get("window", MOCK_PERIODS[0]) if n in mock else None,
                                  "consensus": cons.get(n, {}).get("rank"),
                                  "pos": info["pos"], "school": info.get("school", ""), "site": site_name(n)}

    changes, added = [], []

    def proj_for(n):
        k = mock.get(n, {}).get("pick")
        c = cons.get(n, {}).get("rank")
        if k:
            return k
        if c and c <= LAST_PICK:
            # Not in the mock's rounds -> no earlier than the next pick.
            return max(mock_picks + 1, c) if mock_picks else c
        return None   # ranked past the last pick -> projected UDFA

    def proj_site(name):
        """mock -> consensus big board -> None (UDFA), for one site name."""
        src = next((n for n in list(mock) + list(cons) if site_name(n) == name), None)
        return proj_for(src) if src else None

    # 1) draftProj for the whole runtime class (combine_data.js entries edited in
    #    place, stub entries through data/draft_proj.js). No source -> CLEAR.
    #    eligYr beyond the draft year (2028+) -> CLEAR (too far out).
    proj_map = {}      # site name -> rank, 'U' (projected UDFA) or None (remove draftProj)
    cleared = []
    # Last run's map: the "old" value for stub players (their on-disk value is the
    # April guard in combine_d_patches.js, which draft_proj.js overrides at runtime).
    prev = {}
    if os.path.exists(DRAFT_PROJ_JS):
        m = re.search(r"window\.DRAFT_PROJ = (\{.*?\});", open(DRAFT_PROJ_JS, encoding="utf-8").read(), re.S)
        if m:
            try:
                prev = json.loads(m.group(1))
            except ValueError:
                prev = {}
    for name, e in rt.items():
        if not e.get("devy") or e.get("pos") not in SKILL or e.get("draft") is not None:
            continue
        elig = e.get("eligYr") or e.get("yr")
        if elig == year:
            # On no board at all -> projected UDFA ('U' scores as pick 300, shows "UDFA").
            # Jack (2026-09-30): every player in the draft class carries draft capital.
            new = proj_site(name) or "U"
        elif elig and elig > year:
            new = None
        else:
            continue
        old = e.get("draftProj") if name in cb else prev.get(name, e.get("draftProj"))
        proj_map[name] = new
        if old == new:
            continue
        if new is None:
            cleared.append((name, old))
        else:
            changes.append((name, old, new))
        if name in cb:
            if new is None:
                cb[name].pop("draftProj", None)
                cb[name].pop("draftProjSrc", None)
            else:
                cb[name]["draftProj"] = new
    # 2) new names
    if a.add:
        # Public top 100 only - those cards carry the school.
        for n in sorted(cons_live, key=lambda x: proj_for(x) or 999):
            if site_name(n) or cons_live[n]["rank"] > 100:
                continue
            info = cons_live[n]
            school = SCHOOL_FIX.get(info["school"], info["school"])
            ent = {"yr": year, "devy": True, "eligYr": year, "school": school, "pos": info["pos"]}
            ent["draftProj"] = proj_for(n) or "U"
            cb[n] = ent
            added.append((n, ent))

    for name, old, new in changes:
        log("  draftProj %-24s %s -> %s" % (name, old, new))
    for name, old in cleared:
        log("  CLEAR     %-24s %s -> (none)" % (name, old))
    for n, ent in added:
        log("  ADD %-24s %s" % (n, json.dumps(ent)))
    n_src = sum(1 for v in proj_map.values() if v is not None and v != "U")
    log("draftProj changes: %d, cleared: %d, added: %d | class %d: %d of %d with a board pick, rest projected UDFA" % (
        len(changes), len(cleared), len(added), year, n_src, sum(1 for n, e in rt.items() if e.get("devy") and (e.get("eligYr") or e.get("yr")) == year and e.get("pos") in SKILL)))
    if a.dry_run:
        return 0
    # data/draft_proj.js - self-applying map for the runtime board (covers the stubs).
    # Loaded after combine_d_patches.js; never touches a real `draft`.
    dp_lines = ["// GENERATED by scripts/pull_draft_boards.py - projected draft capital for the runtime devy board",
                "// source: NFL Mock Draft Database only - consensus mock pick -> consensus big board rank (after the last mock pick, <= 262) -> projected UDFA",
                "// 'U' = on no board (projected UDFA, scores as pick 300); null = beyond the draft year (draftProj removed). Generated %s for the %d class." % (today.isoformat(), year),
                "window.DRAFT_PROJ = " + json.dumps(dict(sorted(proj_map.items())), ensure_ascii=False, separators=(",", ":")) + ";",
                "(function () {",
                "  if (typeof COMBINE_DATA === 'undefined') return;",
                "  Object.keys(window.DRAFT_PROJ).forEach(function (n) {",
                "    var c = COMBINE_DATA[n], v = window.DRAFT_PROJ[n];",
                "    if (!c || c.draft != null) return;",
                "    if (v == null) { delete c.draftProj; delete c.draftProjSrc; } else { c.draftProj = v; }",
                "  });",
                "})();", ""]
    dp_before = digest(DRAFT_PROJ_JS) if os.path.exists(DRAFT_PROJ_JS) else None
    with open(DRAFT_PROJ_JS, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(dp_lines))
    dp_changed = digest(DRAFT_PROJ_JS) != dp_before
    with open("scripts/draft_boards_%d.json" % year, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=1, sort_keys=True)
    if not changes and not cleared and not added and not dp_changed:
        return 0

    # Surgical rewrite: keep the single-line JSON style of combine_data.js.
    before = digest(COMBINE_JS)
    out = head + "= " + json.dumps(cb, ensure_ascii=False, separators=(",", ":")) + ";"
    with open(COMBINE_JS, "w", encoding="utf-8", newline="") as f:
        f.write(out)
    cd_changed = digest(COMBINE_JS) != before
    if a.no_bump or not (cd_changed or dp_changed):
        return 0
    with open(INDEX_HTML, encoding="utf-8", newline="") as f:
        html = f.read()
    new_html = html
    if cd_changed:
        new_html = bump_tag(new_html, "combine_data.js")
    if dp_changed:
        if "draft_proj.js?v=" not in new_html:
            # first run: add the tag right after projected_testing.js (after the patches)
            m = re.search(r"<script[^>]*data/projected_testing\.js\?v=[^>]*></script>", new_html)
            assert m, "projected_testing.js tag not found in index.html"
            nl = "\r\n" if "\r\n" in new_html else "\n"
            new_html = new_html[:m.end()] + nl + '<script defer src="data/draft_proj.js?v=%s"></script>' % today.isoformat() + new_html[m.end():]
            log("  added draft_proj.js tag to index.html")
        else:
            new_html = bump_tag(new_html, "draft_proj.js")
    if new_html != html:
        with open(INDEX_HTML, "w", encoding="utf-8", newline="") as f:
            f.write(new_html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
