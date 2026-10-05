#!/usr/bin/env python3
"""
PFF Pro history for backtesting (2026-10-05, Jack: "look at the new stats ... see if there is any good correlation
in backtesting to help with sims").

For every season 2019-2025 and every regular-season week N >= 2, the SEASON-TO-DATE table ENTERING week N
(weeks 1..N-1) from the official PFF Developer API (key: pbp_cache/pff/api_key.txt, see
scripts/pull_pff_weekly.py), plus each prior season's full regular-season table (2018-2024) for shrinkage:

  player reports  /v2/nfl/positions/reports/{report}?season=Y&weekGroup=REG&week=1&weekTo=N-1
                  receiving, passing, rushing, pass-blocking
  team stats      /v2/nfl/teams/stats?season=Y&weekIds=1,..,N-1&category=C   (7 categories)

-> pbp_cache/pff/pro_hist/<kind>_<name>_<Y>_thru<N-1>.json   (rows only; thru0 = never written)
   pbp_cache/pff/pro_hist/<kind>_<name>_<Y>_season.json
Existing files are skipped, so a rerun only fills gaps. The API's per-minute read budget is honoured by
pull_pff_weekly._api_fetch.
"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, r"E:\MyFantasyFootball\MyFantasyFootball Files\scripts")
import pull_pff_weekly as P

OUT = os.path.join(P.PFF_DIR, "pro_hist")
REPORTS = ["receiving", "passing", "rushing", "pass-blocking"]
TEAM_CATS = ["offense-overall-success", "offense-passing", "offense-rushing", "defense-overall-success",
             "defense-passing", "defense-rushing", "defense-opponent-tendencies"]
SEASONS = range(2019, 2026)


def nweeks(y):
    return 17 if y <= 2020 else 18


def fetch_json(url):
    for attempt in range(3):
        st, body = P._api_fetch(KEY, url)
        if st == 200:
            try:
                return json.loads(body)
            except ValueError:
                return None
        if st in (502, 504) and attempt < 2:
            time.sleep(5 * (attempt + 1)); continue
        print(f"    HTTP {st} {P._err(body)} {url.split('api.pff.com')[1][:110]}", flush=True)
        return None
    return None


def save(path, j):
    rows = j.get("rows") or []
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"columns": [c.get("key") for c in (j.get("columns") or [])], "rows": rows}, f)
    os.replace(tmp, path)
    return len(rows)


def main():
    global KEY
    KEY = P._load_key()
    if not KEY:
        print("no PFF API key"); return 2
    os.makedirs(OUT, exist_ok=True)
    B = P.API_BASE
    jobs = []
    for y in list(SEASONS) + [2018]:
        if y in range(2018, 2025):   # prior-season full tables (shrinkage)
            for r in REPORTS:
                jobs.append((f"rep_{r}_{y}_season.json", f"{B}/v2/nfl/positions/reports/{r}?season={y}&weekGroup=REG"))
            for c in TEAM_CATS:
                jobs.append((f"team_{c}_{y}_season.json", f"{B}/v2/nfl/teams/stats?season={y}&weekGroup=REG&category={c}"))
        if y not in SEASONS:
            continue
        for n in range(2, nweeks(y) + 1):
            t = n - 1
            for r in REPORTS:
                jobs.append((f"rep_{r}_{y}_thru{t}.json", f"{B}/v2/nfl/positions/reports/{r}?season={y}&weekGroup=REG&week=1&weekTo={t}"))
            ids = ",".join(str(w) for w in range(1, t + 1))
            for c in TEAM_CATS:
                jobs.append((f"team_{c}_{y}_thru{t}.json", f"{B}/v2/nfl/teams/stats?season={y}&weekIds={ids}&category={c}"))
    todo = [(f, u) for f, u in jobs if not os.path.exists(os.path.join(OUT, f))]
    print(f"PFF Pro history: {len(jobs)} tables, {len(todo)} to fetch -> {OUT}", flush=True)
    t0, done, empty = time.time(), 0, 0

    def one(job):
        f, u = job
        j = fetch_json(u)
        return f, (None if j is None else save(os.path.join(OUT, f), j))

    # ~5 s per report server-side; 6 in flight stays under the 100 reads / minute budget
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, (f, n) in enumerate(ex.map(one, todo), 1):
            if n is None:
                continue
            done += 1; empty += int(n == 0)
            if i % 50 == 0:
                print(f"  {i}/{len(todo)} ({time.time() - t0:.0f}s) last {f} rows={n}", flush=True)
    print(f"done: {done} written ({empty} empty), {len(todo) - done} failed, {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
