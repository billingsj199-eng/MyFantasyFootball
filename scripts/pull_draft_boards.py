"""pull_draft_boards.py - keep the NEXT draft class's projected draft capital current.

Sources (both refreshed on every run):
  * NFL Mock Draft Database consensus big board (49 boards + 185 mocks, daily):
    https://www.nflmockdraftdatabase.com/big-boards/<yr>/consensus-big-board-<yr>
    The site 403s plain HTTP clients, so it is read through the PFF Chrome
    profile (scripts/pull_pff_weekly.py._make_driver) - no login needed there.
  * PFF big board JSON (150 players, ranks + height/weight/class):
    https://www.pff.com/api/college/big_board?season=<yr>&version=2

Writes scripts/draft_boards_<yr>.json (per-player ranks from each source,
for the audit) and patches data/combine_data.js:

  * draftProj for every skill-position (QB/RB/WR/TE) entry in the class
    (yr == <draft year>): consensus rank when inside the consensus top 100,
    otherwise max(101, PFF rank) - i.e. "outside the first ~3 rounds".
    Entries with a real `draft` pick are never touched.
  * Universe = the RUNTIME devy board (combine_data.js + the stubs/overrides in
   data/combine_d_patches.js, via refresh_devy_stats.load_combine()). Stub entries
   get their draftProj through data/draft_proj.js (self-applying, loaded after the
   patches); combine_data.js entries are edited in place.
 * Third source: Site Rankings/projected_dc_<year>.csv (name,rank,...) - NFL Draft
   Buzz average overall rank, read by hand through Jack's Chrome (the site's bot
   check blocks scripts) -> max(101, rank) when consensus and PFF have nothing.
 * A class player on no source becomes a projected UDFA (draftProj 'U' -> pick 300),
   so stale April projections go away but every class player still carries draft
   capital. eligYr > draft year (2028+) is always cleared - too far out.
 * --add: any skill player in the consensus top 100 or PFF top 100 who is
    not in COMBINE_DATA gets a devy entry {yr, devy:true, eligYr, school,
    pos, ht, wt, draftProj} (school/ht/wt from PFF). The weekly devy stats
    refresh then backfills their college seasons.

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
MANUAL_DC = "Site Rankings/projected_dc_%d.csv"
INDEX_HTML = "index.html"
SKILL = {"QB", "RB", "HB", "WR", "TE"}
PFF_API = "https://www.pff.com/api/college/big_board?season=%d&version=2"
CONS_URL = "https://www.nflmockdraftdatabase.com/big-boards/%d/consensus-big-board-%d"
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# PFF / mock-site school spelling -> combine_data.js spelling
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


def pull_pff(year):
    r = requests.get(PFF_API % year, headers=UA, timeout=40)
    r.raise_for_status()
    j = r.json()
    out = {}
    for x in j.get("players", []):
        pos = x.get("position")
        if pos not in SKILL:
            continue
        team = x.get("team") or {}
        out[x["name"]] = {
            "rank": x.get("pff_rank"), "pos": "RB" if pos == "HB" else pos,
            "school": x.get("college") or team.get("city") or "",
            "ht": x.get("height"), "wt": x.get("weight"), "cls": x.get("class"),
            "age": x.get("age"), "g1": x.get("grade_1"), "g2": x.get("grade_2"), "g3": x.get("grade_3"),
        }
    return out, j.get("last_updated_at")


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


def ht_str(h):
    """PFF "6' 4\"" -> "6-4"."""
    m = re.match(r"(\d)'\s*(\d{1,2})", str(h or ""))
    return "%s-%s" % (m.group(1), m.group(2)) if m else None


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

    pff, pff_upd = pull_pff(year)
    log("PFF big board: %d skill players (updated %s)" % (len(pff), pff_upd))
    cons, cons_upd = {}, None
    for attempt in range(3):
        try:
            cons, cons_upd = pull_consensus(year)
            if cons:
                break
        except Exception as e:  # noqa: BLE001
            log("consensus board attempt %d failed: %s" % (attempt + 1, e))
            time.sleep(5)
    log("consensus board: %d skill players in top 100 (updated %s)" % (len(cons), cons_upd))
    if len(cons) < 10:
        # The consensus rank is the anchor for draftProj; PFF alone would demote
        # every top-100 player to 101+. Snapshot nothing, change nothing.
        log("consensus board unavailable - no draftProj changes this run (exit 3)")
        return 3

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
    # Manual third source (NFL Draft Buzz avg overall rank, by hand through Jack's Chrome)
    manual = {}
    mpath = MANUAL_DC % year
    if os.path.exists(mpath):
        import csv
        with open(mpath, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    manual[row["name"].strip()] = float(row["rank"])
                except (KeyError, ValueError):
                    continue
        log("manual DC rows (%s): %d" % (mpath, len(manual)))

    def site_name(n):
        return n if n in cb else by_norm.get(norm(n))

    snapshot = {"year": year, "pulled": today.isoformat(), "pff_updated": pff_upd, "consensus_updated": cons_upd, "players": {}}
    for n in set(pff) | set(cons):
        snapshot["players"][n] = {"consensus": cons.get(n, {}).get("rank"), "pff": pff.get(n, {}).get("rank"),
                                  "pos": (cons.get(n) or pff.get(n))["pos"], "school": (pff.get(n) or cons.get(n))["school"],
                                  "site": site_name(n)}

    changes, added = [], []

    def proj_for(n):
        c = cons.get(n, {}).get("rank")
        p = pff.get(n, {}).get("rank")
        if c:
            return c
        if p:
            return max(101, p)
        return None

    def proj_site(name):
        """consensus -> PFF -> manual (Draft Buzz) -> None, for one site name."""
        src = next((n for n in list(cons) + list(pff) if site_name(n) == name), None)
        v = proj_for(src) if src else None
        if v is None and name in manual:
            v = min(262, max(101, int(round(manual[name]))))   # Draft Buzz ranks run past 600; 262 = last pick
        return v

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
        for n in sorted(set(cons) | set(pff), key=lambda x: proj_for(x) or 999):
            if site_name(n):
                continue
            c, p = cons.get(n, {}).get("rank"), pff.get(n, {}).get("rank")
            if not ((c and c <= 100) or (p and p <= 100)):
                continue
            info = pff.get(n) or cons.get(n)
            school = SCHOOL_FIX.get(info["school"], info["school"])
            ent = {"yr": year, "devy": True, "eligYr": year, "school": school, "pos": info["pos"]}
            if pff.get(n):
                if ht_str(pff[n]["ht"]):
                    ent["ht"] = ht_str(pff[n]["ht"])
                if pff[n].get("wt"):
                    ent["wt"] = int(pff[n]["wt"])
            ent["draftProj"] = proj_for(n)
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
                "// sources: NFL Mock Draft Database consensus (top 100) -> PFF big board (101+) -> NFL Draft Buzz avg overall rank (101+)",
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
