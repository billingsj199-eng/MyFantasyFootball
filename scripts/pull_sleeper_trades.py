#!/usr/bin/env python3
"""Crawl real REDRAFT trades from public Sleeper leagues -> data/real_trades_redraft.json

Sleeper has no "all leagues" endpoint, so leagues are found by snowball:
seed username(s) -> their 2026 leagues -> each league's members -> those
members' other 2026 leagues -> ... until --target redraft leagues are known.
The league pool is cached OUTSIDE the repo (--cache) so later runs only top
it up and spend their calls on transactions.

Only settings.type == 0 (redraft) leagues that are in_season are kept, and
only completed two-team trades. Output carries no league ids or usernames:
each trade is {id, date, qbs, ppr, tep, teams, s1, s2} where s1 = what
roster A gave and s2 = what roster B gave (same shape as the FantasyCalc
pool entries the Trade Calc's RECENT REAL TRADES panel already renders).

Sleeper asks callers to stay under 1000 requests/minute; this runs ~12/s.

Usage:
  python scripts/pull_sleeper_trades.py                    # top up to 10000 leagues, last 8 days
  python scripts/pull_sleeper_trades.py --target 5000 --days 8
"""
import argparse, concurrent.futures as cf, hashlib, json, os, sys, threading, time
from datetime import datetime, timezone

import requests

API = "https://api.sleeper.app/v1"
SEASON = "2026"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "real_trades_redraft.json")
DEFAULT_CACHE = r"E:\MyFantasyFootball\sleeper_trades_cache\league_pool.json"
RATE = 12.0  # requests per second, all threads combined (720/min)

_sess = threading.local()
_lock = threading.Lock()
_next_at = [0.0]
_calls = [0]


def get(path):
    with _lock:
        now = time.time()
        wait = _next_at[0] - now
        _next_at[0] = max(now, _next_at[0]) + 1.0 / RATE
        _calls[0] += 1
    if wait > 0:
        time.sleep(wait)
    s = getattr(_sess, "s", None)
    if s is None:
        s = _sess.s = requests.Session()
    for attempt in range(3):
        try:
            r = s.get(API + path, timeout=20)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code != 200:
                return None
            return r.json()
        except (requests.RequestException, ValueError):
            time.sleep(1 + attempt)
    return None


def league_fmt(lg):
    pos = lg.get("roster_positions") or []
    sc = lg.get("scoring_settings") or {}
    qbs = 2 if ("SUPER_FLEX" in pos or pos.count("QB") >= 2) else 1
    return {
        "qbs": qbs,
        "ppr": sc.get("rec", 0) or 0,
        "tep": sc.get("bonus_rec_te", 0) or 0,
        "teams": lg.get("total_rosters") or 12,
    }


def load_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
        if j.get("season") == SEASON:
            return j
    except (OSError, ValueError):
        pass
    return {"season": SEASON, "leagues": {}, "seen_users": [], "seen_leagues": []}


def save_cache(path, cache):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    os.replace(tmp, path)


def discover(cache, seeds, target, max_calls):
    """Snowball until `target` redraft leagues are in cache['leagues']."""
    leagues = cache["leagues"]
    seen_users = set(cache["seen_users"])
    seen_leagues = set(cache["seen_leagues"])
    user_q = []
    for name in seeds:
        u = get(f"/user/{name}")
        if u and u.get("user_id") and u["user_id"] not in seen_users:
            user_q.append(u["user_id"])
    queued = set(user_q)
    league_q = [lid for lid in list(leagues)]  # re-expand known leagues' members when seeds are spent
    budget_start = _calls[0]

    def user_leagues(uid):
        return uid, get(f"/user/{uid}/leagues/nfl/{SEASON}") or []

    def league_users(lid):
        return lid, get(f"/league/{lid}/users") or []

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        while len(leagues) < target and _calls[0] - budget_start < max_calls:
            if user_q:
                batch, user_q = user_q[:40], user_q[40:]
                for uid, lst in ex.map(user_leagues, batch):
                    seen_users.add(uid)
                    for lg in lst:
                        lid = lg.get("league_id")
                        if not lid or lid in seen_leagues:
                            continue
                        seen_leagues.add(lid)
                        league_q.append(lid)
                        st = lg.get("settings") or {}
                        if len(leagues) < target and st.get("type", 0) == 0 and lg.get("status") == "in_season":
                            leagues[lid] = league_fmt(lg)
            elif league_q:
                batch, league_q = league_q[:40], league_q[40:]
                for lid, users in ex.map(league_users, batch):
                    for u in users:
                        uid = u.get("user_id")
                        if uid and uid not in seen_users and uid not in queued:
                            queued.add(uid)
                            user_q.append(uid)
            else:
                break
            print(f"  discover: {len(leagues)} redraft leagues · {len(seen_leagues)} seen · {_calls[0]} calls", flush=True)

    cache["seen_users"] = sorted(seen_users)
    cache["seen_leagues"] = sorted(seen_leagues)


def pick_name(p):
    rnd = int(p.get("round") or 0)
    lbl = {1: "1st", 2: "2nd", 3: "3rd"}.get(rnd, f"{rnd}th")
    return f"{p.get('season')} {lbl}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", nargs="*", default=["jackb933"])
    ap.add_argument("--target", type=int, default=10000, help="redraft leagues to keep in the pool")
    ap.add_argument("--days", type=float, default=8.0, help="keep trades completed in the last N days")
    ap.add_argument("--max-discovery-calls", type=int, default=6000)
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    t0 = time.time()
    state = get("/state/nfl") or {}
    week = int(state.get("leg") or state.get("week") or 1)
    cache = load_cache(a.cache)
    print(f"week {week} · cached redraft leagues {len(cache['leagues'])}", flush=True)
    discover(cache, a.seed, a.target, a.max_discovery_calls)
    save_cache(a.cache, cache)

    names = {}
    pl = get("/players/nfl") or {}
    for pid, p in pl.items():
        nm = p.get("full_name") or (" ".join(x for x in (p.get("first_name"), p.get("last_name")) if x)) or pid
        pos = p.get("position") or ("DEF" if p.get("fantasy_positions") == ["DEF"] else "")
        names[pid] = (nm, pos)

    cutoff_ms = (time.time() - a.days * 86400) * 1000
    # A trade lands in the leg Sleeper's state shows when it happens; the
    # current leg covers "since MNF", the previous one fills out --days > 3.
    # The previous leg is closed, so its trades are cached per league and
    # only leagues new to the pool get fetched for it again.
    prev = week - 1 if a.days > 3 and week > 1 else None
    closed = cache.get("closed") or {}
    if closed.get("leg") != prev:
        closed = {"leg": prev, "scanned": [], "trades": []}
    closed_scanned = set(closed["scanned"])
    jobs = [(lid, week) for lid in cache["leagues"]]
    if prev:
        jobs += [(lid, prev) for lid in cache["leagues"] if lid not in closed_scanned]

    def txs(job):
        lid, leg = job
        return lid, leg, get(f"/league/{lid}/transactions/{leg}")

    trades, seen_tx, leagues_ok = [], set(), set()
    for t in closed["trades"]:
        if t["id"] not in seen_tx:
            seen_tx.add(t["id"])
            trades.append(t)
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for i, (lid, leg, rows) in enumerate(ex.map(txs, jobs), 1):
            if rows is not None and leg == prev:
                closed_scanned.add(lid)
            rows = rows or []
            if rows:
                leagues_ok.add(lid)
            fmt = cache["leagues"][lid]
            for tx in rows:
                if tx.get("type") != "trade" or tx.get("status") != "complete":
                    continue
                ts = tx.get("status_updated") or tx.get("created") or 0
                rids = tx.get("roster_ids") or []
                if ts < cutoff_ms or len(rids) != 2:
                    continue
                txid = tx.get("transaction_id")
                tid = "sl" + hashlib.sha1(str(txid).encode()).hexdigest()[:12]
                if not txid or tid in seen_tx:
                    continue
                seen_tx.add(tid)
                side = {r: [] for r in rids}
                for pid, r in (tx.get("drops") or {}).items():
                    if r in side:
                        nm, pos = names.get(pid, (pid, ""))
                        side[r].append({"n": nm, "p": pos, "sid": pid})
                for pk in tx.get("draft_picks") or []:
                    r = pk.get("previous_owner_id")
                    if r in side:
                        side[r].append({"n": pick_name(pk), "p": "PICK", "sid": None})
                for wb in tx.get("waiver_budget") or []:
                    r = wb.get("sender")
                    if r in side and wb.get("amount"):
                        side[r].append({"n": f"${wb['amount']}", "p": "FAAB", "sid": None})
                s1, s2 = side[rids[0]], side[rids[1]]
                if not s1 or not s2:
                    continue
                t = {
                    "id": tid,
                    "date": datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "qbs": fmt["qbs"], "ppr": fmt["ppr"], "tep": fmt["tep"], "teams": fmt["teams"],
                    "s1": s1, "s2": s2,
                }
                trades.append(t)
                if leg == prev:
                    closed["trades"].append(t)
            if i % 2000 == 0:
                print(f"  transactions: {i}/{len(jobs)} · {len(trades)} trades", flush=True)

    closed["scanned"] = sorted(closed_scanned)
    cache["closed"] = closed
    save_cache(a.cache, cache)
    trades = [t for t in trades if t["date"] >= datetime.fromtimestamp(cutoff_ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")]
    trades.sort(key=lambda t: t["date"], reverse=True)
    out = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Sleeper public redraft leagues",
        "week": week,
        "days": a.days,
        "leagues": len(cache["leagues"]),
        "trades": trades,
    }
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    os.replace(tmp, a.out)
    print(f"wrote {len(trades)} trades from {len(cache['leagues'])} leagues "
          f"({len(leagues_ok)} with activity) · {_calls[0]} calls · {time.time() - t0:.0f}s -> {a.out}")


if __name__ == "__main__":
    sys.exit(main())
