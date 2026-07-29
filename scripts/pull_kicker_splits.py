#!/usr/bin/env python3
"""Pull per-kicker FG distance splits (makes/attempts by range) from ESPN.

Feeds kicker "tendencies" — e.g. Brandon Aubrey attempts far more 50+ yard
kicks than anyone else, which matters in leagues with FG distance bonuses.

Flow: Clay's 32 projected starting kickers (data/mike_clay_projections.js)
→ ESPN team rosters resolve athlete ids → season statistics endpoint gives
fieldGoalsMade1_19 / 20_29 / 30_39 / 40_49 / 50 (50 = all 50+) and the
matching attempt buckets. 2025 season first, 2024 fallback for kickers who
missed 2025. Output: data/kicker_splits.js (window.KICKER_SPLITS), consumed
by export_sleeper_extension_data.py (bakes per-kicker distance shares into
players.json as `kD`).

Run from the project root: python scripts/pull_kicker_splits.py
"""
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

CLAY_JS = "data/mike_clay_projections.js"
OUT_JS = "data/kicker_splits.js"

# Clay team abbr → ESPN roster slug (default: lowercase)
ESPN_SLUG = {"ARZ": "ari", "WAS": "wsh", "WSH": "wsh"}

BUCKETS = ["1_19", "20_29", "30_39", "40_49", "50"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def norm(n):
    s = (n or "").lower().strip()
    for suf in (" jr.", " jr", " sr.", " sr", " iii", " ii", " iv", " v"):
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
    s = re.sub(r"['’`\.,]", "", s).replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def clay_kickers():
    src = open(CLAY_JS, encoding="utf-8").read()
    out = []
    for m in re.finditer(r'"([^"]+)":\s*\{([^}]*)\}', src):
        body = m.group(2)
        if 'pos:"K"' not in body:
            continue
        tm = re.search(r'tm:"([A-Z]+)"', body)
        out.append({"name": m.group(1), "tm": tm.group(1) if tm else None})
    return out


def roster_kicker_ids():
    """norm-name -> espn athlete id, from every team's roster PK group."""
    ids = {}
    teams = sorted({ESPN_SLUG.get(k["tm"], (k["tm"] or "").lower()) for k in clay_kickers() if k["tm"]})
    for slug in teams:
        try:
            ros = get(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{slug}/roster")
        except Exception as e:
            print(f"WARN roster {slug}: {e}")
            continue
        for grp in ros.get("athletes", []):
            for a in grp.get("items", []):
                if a.get("position", {}).get("abbreviation") == "PK":
                    ids[norm(a.get("fullName", ""))] = a.get("id")
        time.sleep(0.25)
    return ids


def fg_splits(athlete_id, season):
    url = (f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
           f"seasons/{season}/types/2/athletes/{athlete_id}/statistics")
    try:
        d = get(url)
    except Exception:
        return None
    for cat in d.get("splits", {}).get("categories", []):
        if cat.get("name") != "kicking":
            continue
        stats = {s["name"]: s.get("value") for s in cat.get("stats", [])}
        fgm = [int(stats.get(f"fieldGoalsMade{b}", 0) or 0) for b in BUCKETS]
        fga = [int(stats.get(f"fieldGoalAttempts{b}", 0) or 0) for b in BUCKETS]
        if sum(fga) == 0:
            return None
        return {"yr": season, "fgm": fgm, "fga": fga,
                "long": stats.get("longFieldGoalMade")}
    return None


def main():
    kickers = clay_kickers()
    print(f"{len(kickers)} Clay kickers")
    ids = roster_kicker_ids()
    print(f"{len(ids)} PKs found on ESPN rosters")
    out = {}
    for k in kickers:
        nk = norm(k["name"])
        aid = ids.get(nk)
        if not aid:
            # loose match: last name + first initial
            parts = nk.split()
            for cand, cid in ids.items():
                cp = cand.split()
                if cp[-1] == parts[-1] and cp[0][0] == parts[0][0]:
                    aid = cid
                    break
        if not aid:
            print(f"  NO ESPN ID: {k['name']}")
            continue
        rec = fg_splits(aid, 2025) or fg_splits(aid, 2024)
        if not rec:
            print(f"  NO SPLITS: {k['name']} (rookie / no NFL kicks)")
            continue
        out[k["name"]] = rec
        share50 = rec["fga"][4] / max(1, sum(rec["fga"]))
        print(f"  {k['name']:<22} {rec['yr']}  FGM {sum(rec['fgm'])}/{sum(rec['fga'])}"
              f"  50+ att share {share50:.0%}  long {rec.get('long')}")
        time.sleep(0.3)

    body = json.dumps(out, separators=(",", ":"))
    with open(OUT_JS, "w", encoding="utf-8") as f:
        f.write("// Per-kicker FG distance splits (makes/attempts per range bucket\n")
        f.write("// [1-19, 20-29, 30-39, 40-49, 50+]) from ESPN season statistics.\n")
        f.write("// Regenerate: python scripts/pull_kicker_splits.py\n")
        f.write("window.KICKER_SPLITS = " + body + ";\n")
    print(f"Wrote {len(out)} kickers -> {OUT_JS}")


if __name__ == "__main__":
    main()
