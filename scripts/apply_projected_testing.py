"""apply_projected_testing.py - projected athletic testing for next-class prospects.

Reads Site Rankings/projected_testing_<yr>.csv (name, forty, vert, broad, source)
and writes `fortyProj` / `fortyProjSrc` (+ `vertProj` / `broadProj` when given)
onto the matching data/combine_data.js entries. Never touches an entry that has
an official `forty` or `ras`, and drops the projections once official testing
lands (re-run after the combine).

The site's prospect build already synthesizes a RAS from forty + height + weight
for non-QBs with no official RAS (app.js, size-adjusted forty fallback); since
2026-09-30 it also accepts `fortyProj`, flags the result `rasProjected`, and the
player card shows it as "RAS · Projected". Official numbers always win.

CSV columns: name, forty, vert, broad, source   (vert/broad optional)

    python scripts/apply_projected_testing.py [--year 2027] [--dry-run] [--no-bump]
"""
import argparse
import csv
import datetime
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
COMBINE_JS = "data/combine_data.js"
INDEX_HTML = "index.html"


HITS = "scripts/projected_testing_hits.json"


def load_hits():
    try:
        with open(HITS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_hits(h):
    with open(HITS, "w", encoding="utf-8") as f:
        json.dump(h, f, indent=1, sort_keys=True)


def norm(n):
    n = (n or "").lower().strip()
    n = re.sub(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", "", n)
    return re.sub(r"[.'’\-\s]", "", n)


def digest(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()
    except OSError:
        return None


def bump_tag(html, fname):
    today = datetime.date.today().isoformat()
    pat = re.compile(r"(%s\?v=)([\w.-]+)" % re.escape(fname))
    m = pat.search(html)
    if not m:
        return html
    cur = m.group(2)
    m2 = re.match(r"%spt(\d+)$" % re.escape(today), cur)
    new = today if not cur.startswith(today) else today + "pt%d" % ((int(m2.group(1)) + 1) if m2 else 2)
    return pat.sub(lambda mm: mm.group(1) + new, html) if cur != new else html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-bump", action="store_true")
    a = ap.parse_args()
    today = datetime.date.today()
    year = a.year or (today.year + 1 if today.month >= 5 else today.year)
    src = os.path.join("Site Rankings", "projected_testing_%d.csv" % year)
    if not os.path.exists(src):
        print("no", src, "- nothing to apply")
        return 0

    with open(COMBINE_JS, encoding="utf-8", newline="") as f:
        raw = f.read()
    head, body = raw.split("=", 1)
    cb = json.loads(body.strip().rstrip(";"))
    by_norm = {norm(n): n for n in cb}

    applied, skipped, cleared = [], [], []
    seen = set()
    runtime = {}   # every usable CSV row -> data/projected_testing.js (covers runtime-only stubs)
    with open(src, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            try:
                _f = float(row.get("forty") or 0) or None
            except ValueError:
                _f = None
            if _f and 4.2 <= _f <= 5.4:
                runtime[name] = {"forty": round(_f, 2), "src": (row.get("source") or "projection").strip()[:40]}
            key = by_norm.get(norm(name))
            if not key:
                skipped.append((name, "not in COMBINE_DATA (runtime stub -> projected_testing.js only)"))
                continue
            e = cb[key]
            seen.add(key)
            if e.get("forty") or e.get("ras"):
                # official testing exists: drop any stale projection, but LOG projected vs actual so
                # the projection sources can be graded (scripts/projected_testing_hits.json)
                if e.get("fortyProj") is not None and e.get("forty"):
                    hits = load_hits()
                    hits.setdefault(str(year), {})[key] = {"proj": e["fortyProj"], "actual": e["forty"], "src": e.get("fortyProjSrc"),
                                                          "err": round(float(e["forty"]) - float(e["fortyProj"]), 3), "logged": today.isoformat()}
                    save_hits(hits)
                if e.pop("fortyProj", None) is not None or e.pop("fortyProjSrc", None) is not None:
                    cleared.append(key)
                e.pop("vertProj", None); e.pop("broadProj", None)
                skipped.append((name, "official testing on file"))
                continue
            try:
                forty = float(row.get("forty") or 0) or None
            except ValueError:
                forty = None
            if not forty or not (4.2 <= forty <= 5.4):
                skipped.append((name, "no usable forty"))
                continue
            e["fortyProj"] = round(forty, 2)
            e["fortyProjSrc"] = (row.get("source") or "projection").strip()[:40]
            for col, k in (("vert", "vertProj"), ("broad", "broadProj")):
                try:
                    v = float(row.get(col) or 0)
                    if v:
                        e[k] = v
                    else:
                        e.pop(k, None)
                except ValueError:
                    e.pop(k, None)
            applied.append((key, forty, e["fortyProjSrc"]))
    for n, forty, srcname in applied:
        print("  %-24s fortyProj %.2f  (%s)" % (n, forty, srcname))
    for n, why in skipped:
        print("  skip %-24s %s" % (n, why))
    print("applied %d, skipped %d, cleared %d" % (len(applied), len(skipped), len(cleared)))
    hits = load_hits()
    errs = [v["err"] for yr in hits.values() for v in yr.values()]
    if errs:
        print("projection accuracy so far: n %d, mean error %+.3f s (actual - projected), MAE %.3f s, within .05 s: %d%%" % (
            len(errs), sum(errs) / len(errs), sum(abs(x) for x in errs) / len(errs), round(100 * sum(1 for x in errs if abs(x) <= 0.05) / len(errs))))
    if a.dry_run:
        return 0
    # self-applying runtime file: fills fortyProj on any COMBINE_DATA entry (incl. combine_d_patches.js
    # stubs) that has no official forty/RAS and no fortyProj yet; official data always wins.
    js = ["// projected_testing.js - AUTO-GENERATED by scripts/apply_projected_testing.py (%s)" % today.isoformat(),
          "// Pre-draft projected forties (Site Rankings/projected_testing_%d.csv) -> fortyProj on entries" % year,
          "// without official testing. Loaded after combine_d_patches.js so runtime devy stubs are covered.",
          "window.PROJECTED_TESTING = " + json.dumps(runtime, ensure_ascii=False, separators=(",", ":")) + ";",
          "(function () {",
          "  if (typeof COMBINE_DATA === 'undefined') return;",
          "  Object.keys(window.PROJECTED_TESTING).forEach(function (n) {",
          "    var c = COMBINE_DATA[n], v = window.PROJECTED_TESTING[n];",
          "    if (!c || c.forty || c.ras || c.fortyProj) return;",
          "    c.fortyProj = v.forty; c.fortyProjSrc = v.src;",
          "  });",
          "})();", ""]
    pj = "data/projected_testing.js"
    pj_before = digest(pj)
    with open(pj, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(js))
    if digest(pj) != pj_before:
        print("wrote %s (%d projections)" % (pj, len(runtime)))
        with open(INDEX_HTML, encoding="utf-8", newline="") as f:
            html = f.read()
        m = re.search(r"projected_testing\.js\?v=([\w.-]+)", html)
        if m:
            cur = m.group(1)
            m2 = re.match(r"%spj(\d+)$" % re.escape(today.isoformat()), cur)
            new_tag = today.isoformat() if not cur.startswith(today.isoformat()) else today.isoformat() + "pj%d" % ((int(m2.group(1)) + 1) if m2 else 2)
            if new_tag != cur:
                with open(INDEX_HTML, "w", encoding="utf-8", newline="") as f:
                    f.write(html.replace("projected_testing.js?v=" + cur, "projected_testing.js?v=" + new_tag))
                print("bumped projected_testing.js ?v= %s -> %s" % (cur, new_tag))
    before = digest(COMBINE_JS)
    with open(COMBINE_JS, "w", encoding="utf-8", newline="") as f:
        f.write(head + "= " + json.dumps(cb, ensure_ascii=False, separators=(",", ":")) + ";")
    if digest(COMBINE_JS) == before:
        print("combine_data.js unchanged")
        return 0
    print("wrote", COMBINE_JS)
    if a.no_bump:
        return 0
    with open(INDEX_HTML, encoding="utf-8", newline="") as f:
        html = f.read()
    new_html = bump_tag(html, "combine_data.js")
    if new_html != html:
        with open(INDEX_HTML, "w", encoding="utf-8", newline="") as f:
            f.write(new_html)
        print("bumped combine_data.js ?v=")
    return 0


if __name__ == "__main__":
    sys.exit(main())
