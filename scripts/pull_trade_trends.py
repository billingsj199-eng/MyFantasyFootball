"""Trade trends for the Trade Calc (Task Scheduler "MFF Real Trades", every 3 h 08-23).

Replaces the Sleeper snowball crawl (scripts/pull_sleeper_trades.py, kept for reference)
as the writer of data/real_trades_redraft.json (2026-11-04, Jack):

  * MOST TRADED SINCE MNF chips = Yahoo Buzz Index trade counts (one page per ET day since
    the MNF cutoff, top 50 per day) + CBS Sports "most traded" (top 100, CBS doesn't label
    its window). Written to `hot`.
  * RECENT REAL TRADES list = trades the site detected in users' synced My Teams leagues,
    read server-side by the key-gated Cloud Function exportLeagueTrades (player names +
    league format only). Written to `trades` in the same shape the old crawl used, so the
    site keeps working with or without `hot`.

A source that fails is skipped (its counts just drop out); the run fails only if BOTH
Yahoo and CBS return nothing, leaving the previous file in place.

usage: python scripts/pull_trade_trends.py [--days 8] [--out data/real_trades_redraft.json]
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "real_trades_redraft.json")
KEY_FILE = r"E:\MyFantasyFootball\secrets\export_feed_key.txt"
FN_URL = "https://us-central1-jackb933-website.cloudfunctions.net/exportLeagueTrades"
YAHOO = ("https://football.fantasysports.yahoo.com/f1/buzzindex?date={d}&pos=ALL&sort=BI_T"
         "&src=combined&bimtab=ALL&trendtab=O&count=50")
CBS = "https://www.cbssports.com/fantasy/football/trends/traded/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
ET = ZoneInfo("America/New_York")


def fetch(url, headers=None, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001 - network/HTTP errors all retry the same way
            last = e
            time.sleep(2 * (i + 1))
    raise last


def mnf_cutoff(now):
    """Most recent Tuesday 04:00 UTC — same rule as the site's mnfCutoff()."""
    t = now.replace(hour=4, minute=0, second=0, microsecond=0)
    t -= dt.timedelta(days=(t.weekday() - 1) % 7)  # weekday(): Mon=0, Tue=1
    if t > now:
        t -= dt.timedelta(days=7)
    return t


def key_of(name):
    s = re.sub(r"[^a-z ]", "", name.lower().replace("-", " "))
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def strip_tags(s):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def trades_table(page):
    for m in re.finditer(r"<table.*?</table>", page, re.S):
        if "Trades" in m.group(0):
            return m.group(0)
    return ""


def pull_yahoo(day):
    """[(name, team, pos, trades)] for one ET day (top 50 by trades)."""
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", trades_table(fetch(YAHOO.format(d=day))), re.S):
        nm = re.search(r'class="Nowrap name F-link[^"]*"[^>]*>([^<]+)</a>', row)
        tds = [strip_tags(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if not nm or len(tds) < 7:
            continue
        tp = re.search(r'<span class="Fz-xxs">\s*([A-Za-z]{2,3}) - ([A-Z,]+)\s*</span>', row)
        try:
            n_tr = int(tds[5].replace(",", ""))  # Player, %Ros, %Start, Drops, Adds, Trades, Total
        except ValueError:
            continue
        out.append((html.unescape(nm.group(1)).strip(), tp.group(1).upper() if tp else "",
                    tp.group(2).split(",")[0] if tp else "", n_tr))
    return out


def pull_cbs():
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", trades_table(fetch(CBS)), re.S):
        long_ = re.search(r'CellPlayerName--long">.*?<a [^>]*>([^<]+)</a>'
                          r'<span class="CellPlayerName-position">\s*(\w+)\s*</span>'
                          r'<span class="CellPlayerName-team">\s*(\w+)\s*</span>', row, re.S)
        num = re.search(r'TableBase-bodyTd--number[^>]*>\s*([\d,]+)\s*<', row)
        if long_ and num:
            out.append((html.unescape(long_.group(1)).strip(), long_.group(3).upper(), long_.group(2).upper(),
                        int(num.group(1).replace(",", ""))))
    return out


def pull_league_trades(days):
    try:
        key = open(KEY_FILE, encoding="utf-8").read().strip()
    except OSError:
        return None, "no export key file"
    try:
        j = json.loads(fetch(f"{FN_URL}?days={days:g}", headers={"x-export-key": key}, tries=2))
    except Exception as e:  # noqa: BLE001
        return None, f"exportLeagueTrades unavailable ({e})"
    return j, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=8.0, help="synced-league trades from the last N days")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    cut = mnf_cutoff(now)
    first = (cut + dt.timedelta(hours=1)).astimezone(ET).date()
    today = now.astimezone(ET).date()
    days = [first + dt.timedelta(days=i) for i in range((today - first).days + 1)]

    players, notes = {}, []

    def add(name, team, pos, n, src):
        p = players.setdefault(key_of(name), {"n": name, "t": team, "p": pos, "y": 0, "c": 0})
        p[src] += n
        if src == "c":  # CBS long names carry suffixes the way our board does
            p["n"] = name
        p["t"] = p["t"] or team
        p["p"] = p["p"] or pos

    y_days = []
    for d in days:
        try:
            rows = pull_yahoo(d.isoformat())
        except Exception as e:  # noqa: BLE001
            notes.append(f"yahoo {d}: {e}")
            continue
        if rows:
            y_days.append({"date": d.isoformat(), "players": len(rows), "trades": sum(r[3] for r in rows),
                           "floor": min(r[3] for r in rows)})
        for r in rows:
            add(*r, "y")
    try:
        cbs = pull_cbs()
    except Exception as e:  # noqa: BLE001
        cbs = []
        notes.append(f"cbs: {e}")
    for r in cbs:
        add(*r, "c")
    if not y_days and not cbs:
        print("FAILED: Yahoo and CBS both empty;", "; ".join(notes))
        return 1

    hot = sorted(players.values(), key=lambda p: -(p["y"] + p["c"]))[:40]

    lg, err = pull_league_trades(a.days)
    trades, n_leagues, n_users = [], 0, 0
    if err:
        notes.append(err)
    elif lg:
        n_leagues, n_users = int(lg.get("leagues") or 0), int(lg.get("users") or 0)
        for t in lg.get("trades") or []:
            if t.get("type") == "dynasty":
                continue
            trades.append({"id": t["id"], "date": t["date"], "qbs": t.get("qbs", 1), "ppr": t.get("ppr", 1),
                           "tep": 0, "teams": t.get("teams", 12), "src": t.get("src", ""),
                           "s1": [{"n": n, "p": ""} for n in t.get("s1", [])],
                           "s2": [{"n": n, "p": ""} for n in t.get("s2", [])]})

    doc = {
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Synced MFF leagues + Yahoo Buzz Index + CBS Sports",
        "days": a.days,
        "leagues": n_leagues,
        "users": n_users,
        "trades": trades,
        "hot": {"since": cut.strftime("%Y-%m-%dT%H:%M:%SZ"), "yahooDays": y_days, "cbsPlayers": len(cbs),
                "players": [{"n": p["n"], "p": p["p"], "t": p["t"], "y": p["y"], "c": p["c"]} for p in hot]},
    }
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    tot_y = sum(d["trades"] for d in y_days)
    print(f"yahoo {len(y_days)} day(s) {tot_y} player-trades · cbs {len(cbs)} players · "
          f"league trades {len(trades)} from {n_leagues} synced leagues"
          + (f" · notes: {'; '.join(notes)}" if notes else "") + f" -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
