#!/usr/bin/env python3
"""
Pull ESPN's historical WEEKLY fantasy projections (2019-2025) -> pbp_cache/espn_proj/espn_proj_<year>.json

Jack (2026-09-17): "is it possible to see how we do historically vs a fantasy site like espn" / "build the ESPN
comparison". ESPN's fantasy API keeps the projection it showed for every past scoring period:
  lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/<Y>/segments/0/leaguedefaults/3?view=kona_player_info
  &scoringPeriodId=<W>   with X-Fantasy-Filter limiting stats to "11<Y><W>" (projected, weekly) and "01<Y><W>" (actual).
Each player carries stats[] entries: statSourceId 1 = projected, 0 = actual; statSplitTypeId 1 = weekly; appliedTotal is
in ESPN standard PPR; stats{} is the projected stat line by ESPN stat id (3 pass yd, 4 pass TD, 20 INT, 24 rush yd,
25 rush TD, 42 rec yd, 43 rec TD, 53 receptions, 72 fumbles lost, 19 / 26 / 44 two-point conversions).
Saved compact: { "year": Y, "weeks": { "<W>": { "<name>|<pos>": {"ppr": x, "s": {statid: v}, "team": id, "aPpr": y} } } }
Read-only, ~125 requests, polite 0.4 s sleep. Re-run safe (skips seasons already complete unless --force).
"""
import json, os, sys, time, urllib.request

OUT_DIR = r"E:\MyFantasyFootball\pbp_cache\espn_proj"
POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE"}
KEEP = ("3", "4", "19", "20", "24", "25", "26", "42", "43", "44", "53", "72")
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def fetch(Y, W, limit=600):
    flt = {"players": {"limit": limit, "sortPercOwned": {"sortPriority": 1, "sortAsc": False}, "filterSlotIds": {"value": [0, 2, 4, 6]},
                       "filterStatsForTopScoringPeriodIds": {"value": 1, "additionalValue": [f"11{Y}{W}", f"01{Y}{W}"]}}}
    url = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{Y}/segments/0/leaguedefaults/3?view=kona_player_info&scoringPeriodId={W}"
    req = urllib.request.Request(url, headers={**UA, "X-Fantasy-Filter": json.dumps(flt)})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read().decode("utf-8"))
        except Exception as ex:
            if attempt == 2: raise
            time.sleep(2 + 2 * attempt)


def main():
    os.makedirs(OUT_DIR, exist_ok=True); force = "--force" in sys.argv
    years = [int(a) for a in sys.argv[1:] if a.isdigit()] or list(range(2019, 2026))
    for Y in years:
        out_path = os.path.join(OUT_DIR, f"espn_proj_{Y}.json"); nweeks = 17 if Y <= 2020 else 18
        if os.path.exists(out_path) and not force:
            d = json.load(open(out_path, encoding="utf-8"))
            if len(d.get("weeks", {})) >= nweeks: print(f"{Y}: already complete ({len(d['weeks'])} weeks) - skip"); continue
        weeks = {}
        for W in range(1, nweeks + 1):
            d = fetch(Y, W); rows = {}
            for p in d.get("players", []):
                pi = p.get("player", {}); ps = POS.get(pi.get("defaultPositionId"))
                if not ps: continue
                proj = act = None
                for s in pi.get("stats", []):
                    if s.get("statSplitTypeId") != 1 or s.get("scoringPeriodId") != W or s.get("seasonId") != Y: continue
                    if s.get("statSourceId") == 1: proj = s
                    elif s.get("statSourceId") == 0: act = s
                if proj is None: continue
                st = proj.get("stats") or {}
                rows[f"{pi.get('fullName')}|{ps}"] = {"ppr": round(float(proj.get("appliedTotal") or 0), 3), "s": {k: round(float(st[k]), 3) for k in KEEP if k in st},
                                                       "team": pi.get("proTeamId"), "aPpr": (round(float(act.get("appliedTotal") or 0), 2) if act else None)}
            weeks[str(W)] = rows; print(f"  {Y} week {W:2d}: {len(rows)} projected players"); time.sleep(0.4)
        with open(out_path, "w", encoding="utf-8") as f: json.dump({"year": Y, "pulled": time.strftime("%Y-%m-%d %H:%M"), "weeks": weeks}, f, separators=(",", ":"))
        print(f"{Y}: wrote {out_path} ({os.path.getsize(out_path)/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
