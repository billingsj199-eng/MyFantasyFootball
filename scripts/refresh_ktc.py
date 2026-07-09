"""
Refresh the inline KTC_1QB and KTC_SF maps in index.html with the latest
KeepTradeCut dynasty values.

Usage (from MyFantasyFootball Files/):
    python3 scripts/refresh_ktc.py

How it works:
    1. Fetches https://keeptradecut.com/dynasty-rankings (the public HTML page)
    2. Extracts the `playersArray` JS variable embedded in the page
    3. Builds {playerName: value} maps for 1QB and Superflex
    4. Rewrites the two KTC lines in index.html (lines starting with var KTC_1QB / var KTC_SF)
    5. Updates the comment timestamp

Notes:
    - The dynasty-rankings page already includes rookie draft picks (position: "RDP"),
      so they're carried through automatically.
    - Player names from KTC may differ from d.js (e.g. "Cameron Skattebo" vs "Cam Skattebo").
      We apply a small alias map so KTC entries land under the d.js-canonical name.
"""
import json
import re
import sys
import urllib.request
from datetime import date

KTC_URL = "https://keeptradecut.com/dynasty-rankings"
INDEX_HTML = "index.html"

# KTC name → d.js canonical name. Add new entries as we find more mismatches.
ALIASES = {
    "Cameron Skattebo":    "Cam Skattebo",
    "D.K. Metcalf":        "DK Metcalf",
    "AJ Barner":           "A.J. Barner",
    "Tre Harris":          "Tre' Harris",
    "Chigoziem Okonkwo":   "Chig Okonkwo",
    "Nathaniel Dell":      "Tank Dell",
    "Cameron Ward":        "Cam Ward",
    "Jamarion Miller":     "Jam Miller",
}

def fetch_page():
    req = urllib.request.Request(
        KTC_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")

def extract_players(html):
    """Find `var playersArray = [...];` and parse it as JSON."""
    # Match up to and including the closing `];` — KTC always emits this on a single line
    m = re.search(r"var\s+playersArray\s*=\s*(\[.*?\])\s*;", html, re.DOTALL)
    if not m:
        raise RuntimeError("Could not find playersArray in page HTML — KTC likely changed their template")
    arr = json.loads(m.group(1))
    if not arr:
        raise RuntimeError("playersArray is empty")
    return arr

def build_maps(players):
    """Return (one_qb_map, sf_map) sorted descending by value (matches existing format)."""
    one_qb = {}
    sf = {}
    for p in players:
        name = p.get("playerName", "")
        if not name:
            continue
        canonical = ALIASES.get(name, name)
        oqb = (p.get("oneQBValues") or {}).get("value")
        sfv = (p.get("superflexValues") or {}).get("value")
        if oqb is not None:
            one_qb[canonical] = oqb
        if sfv is not None:
            sf[canonical] = sfv
    # Sort by value desc to keep the file diff minimal vs. existing format
    one_qb = dict(sorted(one_qb.items(), key=lambda kv: -kv[1]))
    sf     = dict(sorted(sf.items(),     key=lambda kv: -kv[1]))
    return one_qb, sf

def to_js_object_literal(d):
    """Render a Python dict as a compact JS object literal (matches the existing format)."""
    parts = []
    for k, v in d.items():
        # JSON-quote the key so embedded apostrophes etc. are handled
        parts.append(f"{json.dumps(k, ensure_ascii=False)}:{int(v)}")
    return "{" + ",".join(parts) + "}"

def update_index_html(one_qb, sf):
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        content = f.read()

    today = date.today().strftime("%m/%d/%y")
    new_comment = f"/* KeepTradeCut Dynasty Values (1QB + Superflex) — updated {today} */"
    new_one = "var KTC_1QB=" + to_js_object_literal(one_qb) + ";"
    new_sf  = "var KTC_SF="  + to_js_object_literal(sf)     + ";"

    # Replace the comment line
    content, n_c = re.subn(
        r"/\*\s*KeepTradeCut Dynasty Values[^*]*\*/",
        new_comment,
        content, count=1
    )
    # Replace KTC_1QB and KTC_SF lines (greedy on the value because the line is long)
    content, n_1 = re.subn(r"var KTC_1QB=\{[^\n]*?\};", new_one, content, count=1)
    content, n_2 = re.subn(r"var KTC_SF=\{[^\n]*?\};",  new_sf,  content, count=1)

    if not (n_c and n_1 and n_2):
        raise RuntimeError(f"Replacement failed: comment={n_c}, KTC_1QB={n_1}, KTC_SF={n_2}")

    # Backup before writing
    backup = INDEX_HTML + f".bak_pre_ktc_refresh_{date.today().strftime('%Y%m%d')}"
    with open(backup, "w", encoding="utf-8") as f:
        with open(INDEX_HTML, "r", encoding="utf-8") as src:
            f.write(src.read())
    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(content)
    return backup

def main():
    print("Fetching KTC dynasty-rankings page...")
    html = fetch_page()
    print(f"  got {len(html)} chars")
    players = extract_players(html)
    print(f"Parsed {len(players)} players from playersArray")
    one_qb, sf = build_maps(players)
    print(f"  KTC_1QB: {len(one_qb)} entries (top: {next(iter(one_qb.items()))})")
    print(f"  KTC_SF:  {len(sf)} entries (top: {next(iter(sf.items()))})")
    backup = update_index_html(one_qb, sf)
    print(f"\nUpdated {INDEX_HTML} (backup at {backup})")
    print("Done. Commit and push to publish.")

if __name__ == "__main__":
    sys.exit(main() or 0)
