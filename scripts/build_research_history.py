"""Build data/research_history.js — historical preseason ADP/rank per player per year.

Sources:
  - MyFantasyLeague ADP pages via the Wayback Machine: 1999-2007 (MFL's live API
    only retains the current ~2 seasons; a July-2017 crawl archived every yearly
    /adp page). Depth: top 32 for 1999-2005, top 100 for 2006, top 200 for 2007.
    MFL ADP averages ALL MFL leagues (mixed sizes, mostly 12-team).
  - Fantasy Football Calculator archive (12-team): standard 2008+, ppr 2010+, half-ppr 2018+
  - ESPN kona_player_info: ADP + preseason positional rank, 2018 and 2020-2024 only
    (2019/2025 are zeroed server-side; <=2017 404s — see memory reference_espn_historical_adp_api)

Output shape (window.RESEARCH_HIST):
  { "Player Name": { "pos": "RB",
      "y": { "2018": { "f": 5.3, "fm": "h", "e": 5.1, "er": 4 } } } }
  f  = primary ADP for that year
  fm = its source/format: m=MFL, h=FFC half-ppr, p=FFC ppr, s=FFC standard
  e  = ESPN platform ADP   er = ESPN preseason PPR overall rank
Names are canonicalized to ALL_PLAYERS_DB names where a match exists.

Usage: python scripts/build_research_history.py
"""
import json, re, time, sys, io, os
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFC_YEARS = range(2008, 2026)
ESPN_YEARS = [2018, 2020, 2021, 2022, 2023, 2024]
# Exact Wayback snapshots of MFL's yearly ADP pages (deepest capture per year).
MFL_SNAPSHOTS = {yr: f"http://web.archive.org/web/20170705/http://www03.myfantasyleague.com/{yr}/adp"
                 for yr in range(1999, 2006)}
MFL_SNAPSHOTS[2006] = ("http://web.archive.org/web/20180817113803/http://www03.myfantasyleague.com/2006/adp"
                       "?COUNT=100&POS=Coach%2BQB%2BTMQB%2BTMRB%2BRB%2BFB%2BWR%2BTMWR%2BTE%2BTMTE%2BWR%2BTE%2BRB"
                       "%2BWR%2BTE%2BKR%2BPK%2BTMPK%2BPN%2BTMPN%2BDef%2BST%2BOff&INJURED=0&CUTOFF=5&FRANCHISES=-1"
                       "&IS_PPR=-1&IS_KEEPER=0&IS_MOCK=0&TIME=")
MFL_SNAPSHOTS[2007] = ("http://web.archive.org/web/20171114012739/http://www03.myfantasyleague.com/2007/adp"
                       "?COUNT=200&POS=*&CUTOFF=5&FRANCHISES=-1&IS_PPR=-1&IS_KEEPER=0&IS_MOCK=-1&TIME=")
MFL_POS = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "PK": "K", "Def": "DEF"}


def load_js_obj(path, marker="="):
    txt = open(path, encoding="utf-8").read()
    txt = txt[txt.index(marker) + len(marker):].strip().rstrip(";")
    return json.loads(txt)


def norm(n):
    n = n.lower()
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\.?$", "", n.strip())
    return re.sub(r"[^a-z]", "", n)


def main():
    allp = load_js_obj(os.path.join(ROOT, "data", "all_players.js"))
    canon = {}
    for p in allp:
        canon.setdefault(norm(p["name"]), p["name"])
    pos_by_name = {p["name"]: p.get("pos") for p in allp}

    out = {}  # canonical name -> {pos, y:{yr:{...}}}

    def rec(name, pos, yr):
        cname = canon.get(norm(name), name)
        entry = out.setdefault(cname, {"pos": pos_by_name.get(cname) or pos or "?", "y": {}})
        if entry["pos"] == "?" and pos:
            entry["pos"] = pos
        return entry["y"].setdefault(str(yr), {})

    # ---- MFL 1999-2007 via Wayback ----
    for yr, url in sorted(MFL_SNAPSHOTS.items()):
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=90)
            r.raise_for_status()
            txt = re.sub(r"\s+", " ", r.text)
        except Exception as e:
            print(f"MFL {yr} failed: {e}")
            continue
        # rows: <a href="player?P=123">Last, First TEAM POS</a></td><td class="rank">3.10</td>
        found = re.findall(r'player\?P=\d+">([^<]+)</a></td>\s*<td class="rank">([\d.]+)</td>', txt)
        filled = 0
        for raw, adp in found:
            toks = raw.split()
            if len(toks) < 3:
                continue
            pos = MFL_POS.get(toks[-1])
            if not pos:
                continue  # Coach/ST/Off/PN/KR etc.
            nm = " ".join(toks[:-2])  # drop TEAM + POS
            if "," in nm:
                last, first = nm.split(",", 1)
                nm = (first.strip() + " " + last.strip()).strip()
            row = rec(nm, pos, yr)
            if "f" not in row:
                row["f"] = round(float(adp), 1)
                row["fm"] = "m"
                filled += 1
        print(f"MFL {yr}: {len(found)} rows parsed ({filled} kept)")
        time.sleep(1.5)

    # ---- FFC ----
    fmt_order = [("half-ppr", "h"), ("ppr", "p"), ("standard", "s")]
    for yr in FFC_YEARS:
        got = False
        for fmt, code in fmt_order:
            try:
                r = requests.get(
                    f"https://fantasyfootballcalculator.com/api/v1/adp/{fmt}?teams=12&year={yr}",
                    timeout=30)
                players = r.json().get("players", [])
            except Exception as e:
                print(f"FFC {fmt} {yr} failed: {e}")
                players = []
            if len(players) < 50:
                continue
            filled = 0
            for p in players:
                row = rec(p["name"], p.get("position"), yr)
                if "f" not in row:  # first (most preferred) format wins
                    row["f"] = round(float(p["adp"]), 1)
                    row["fm"] = code
                    filled += 1
            print(f"FFC {yr} {fmt}: {len(players)} players ({filled} new)")
            got = True
            time.sleep(0.4)
        if not got:
            print(f"FFC {yr}: no data in any format")

    # ---- ESPN ----
    espn_url = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/"
                "{yr}/segments/0/leaguedefaults/3?view=kona_player_info")
    flt = {"players": {"limit": 3000, "sortDraftRanks": {
        "sortPriority": 100, "sortAsc": True, "value": "STANDARD"}}}
    pos_map = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}
    for yr in ESPN_YEARS:
        try:
            r = requests.get(espn_url.format(yr=yr),
                             headers={"x-fantasy-filter": json.dumps(flt)}, timeout=60)
            r.raise_for_status()
            players = r.json()["players"]
        except Exception as e:
            print(f"ESPN {yr} failed: {e}")
            continue
        filled = 0
        for pl in players:
            p = pl.get("player", {})
            adp = (p.get("ownership") or {}).get("averageDraftPosition", 0)
            if not (0 < adp < 169.5):  # 170 = undrafted pile-up cap
                continue
            name = p.get("fullName", "")
            if not name:
                continue
            row = rec(name, pos_map.get(p.get("defaultPositionId")), yr)
            row["e"] = round(adp, 1)
            ranks = p.get("draftRanksByRankType") or {}
            rk = (ranks.get("PPR") or ranks.get("STANDARD") or {}).get("rank")
            if rk:
                row["er"] = rk
            filled += 1
        print(f"ESPN {yr}: {filled} players with real ADP")
        time.sleep(0.5)

    # prune players that ended up with no data
    out = {k: v for k, v in out.items() if v["y"]}
    n_rows = sum(len(v["y"]) for v in out.values())
    body = json.dumps(out, separators=(",", ":"), ensure_ascii=False)
    js = ("// Generated by scripts/build_research_history.py — historical preseason ADP/ranks\n"
          "// MFL via Wayback 1999-2007 (fm: m); FFC 12-team 2008+ (fm: h=half-ppr p=ppr s=standard);\n"
          "// ESPN ADP+preseason rank 2018,2020-2024\n"
          "window.RESEARCH_HIST=" + body + ";\n")
    dest = os.path.join(ROOT, "data", "research_history.js")
    open(dest, "w", encoding="utf-8").write(js)
    print(f"\nWrote {dest}: {len(out)} players, {n_rows} player-seasons, {len(js)//1024} KB")


if __name__ == "__main__":
    main()
