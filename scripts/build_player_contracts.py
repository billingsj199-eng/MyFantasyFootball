"""Refresh the player-card CONTRACT fields in data/d.js from OverTheCap (via nflverse).

Source: https://github.com/nflverse/nflverse-data/releases/download/contracts/historical_contracts.parquet
(refreshed daily by nflverse from overthecap.com; money in MILLIONS). Same file the Research
page's build_contracts.py reads - this script only touches the D[] card fields.

Fields written on every QB/RB/WR/TE/K player object in D (DST skipped, never touched):
  sal   APY in $M (card "AAV")                          null when no active contract
  cyr   final league year of the current contract       "FA" when OTC lists the player with
                                                          no active contract; null when unknown
  out   first league year the team could cut/trade and  computed, see potential_out(); null
        come out ahead on the cap ("Potential Out")       when the deal has no such year / FA
  cv    total contract value $M                          new 2026-10-08
  cn    contract years (as OTC lists them)               new 2026-10-08
  cg    guaranteed $M                                    new 2026-10-08
  cs    year signed                                      new 2026-10-08
  dr    draft round - backfilled from OTC ONLY where d.js has null (pool additions)
  cdead dead-money $M at the `out` year                  new 2026-10-08 (card tooltip)
  csav  cap savings $M at the `out` year                 new 2026-10-08 (card tooltip)

Final year (cyr): last cap-table year that pays real cash (>= 10% of APY, min $0.5M) - OTC
pads deals with void / dummy years that carry proration but no cash. Rookies with no cap
table yet: year_signed + years - 1.

Potential Out rule (calibrated 2026-10-08 against the hand-entered values that were in d.js:
savings_pos agreed 16/26, the stricter rules 8/17): for each league year Y > current season
up to the final year, dead(Y) = remaining signing-bonus proration from Y on + option-bonus
proration already on the books (options not yet exercised never accelerate) + guaranteed
salary from Y on; savings(Y) = cap number(Y) - dead(Y). out = first Y with savings(Y) > 0,
i.e. the first offseason a cut or trade frees cap. Fully guaranteed deals (rookie R1) or
deals with no such year -> null (card shows "None"). Current season = calendar year from
March on, previous year in Jan/Feb (the league year rolls in mid-March, so a January cut
saves next year's cap).

Safety rails (mirrors update_rosters.py):
  * aborts (exit 3, nothing written) if fewer than 80% of the non-DST players match an OTC row
  * aborts (exit 3) if more than --max-changes players would change cyr/sal (default 400;
    the first run touches most of the file, after that a handful a day)
  * splices values surgically into the raw d.js text (no re-serialize), re-parses the result
    and verifies every change landed before writing
  * unmatched players are logged and left untouched (their old manual values stay)

Usage:
  python scripts/build_player_contracts.py            # fetch, diff, write, print summary
  python scripts/build_player_contracts.py --dry-run  # print the diff only
  python scripts/build_player_contracts.py --calibrate  # score out-year rules vs existing values
Exit 0 = written (or nothing changed), 3 = guard tripped, 1 = error.
(scheduled by scripts/daily_contracts.ps1, Task Scheduler "MFF Player Contracts")
"""
import argparse, datetime, io, json, math, os, re, sys
import requests
import pyarrow.parquet as pq

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DJS = os.path.join(ROOT, "data", "d.js")
URL = "https://github.com/nflverse/nflverse-data/releases/download/contracts/historical_contracts.parquet"
CACHE = r"E:\MyFantasyFootball\pbp_cache\otc"
POS = {"QB", "RB", "WR", "TE", "K", "FB"}
NEW_KEYS = ["cv", "cn", "cg", "cs", "cdead", "csav"]
dr_fill = {}  # name -> draft round to write where d.js has dr null (filled by build())
TEAM_NICK = {"Football Team": "Commanders", "Redskins": "Commanders", "Washington": "Commanders"}


def norm(n):
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\.?$", "", n.lower().strip())
    return re.sub(r"[^a-z]", "", n)


def nick(team_full):
    if not team_full or team_full == "FA":
        return None
    t = team_full.split()[-1]
    return TEAM_NICK.get(t, t)


def current_season(today=None):
    today = today or datetime.date.today()
    return today.year if today.month >= 3 else today.year - 1


def m(v):
    """millions -> rounded millions (2dp), None for NaN/None."""
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, 2)


def f(v):
    try:
        v = float(v)
        return 0.0 if math.isnan(v) else v
    except (TypeError, ValueError):
        return 0.0


def cap_rows(hist, season):
    """season_history -> {year: row} for the current season on (the 'Total' row and rows
    without a year are dropped)."""
    yrs = {}
    for r in hist or []:
        y = str(r.get("year") or "")
        if y.isdigit() and int(y) >= season:
            yrs[int(y)] = r
    return yrs


def real_years(yrs, apy):
    """OTC pads deals with void / dummy years that carry proration (or a placeholder base)
    but no cash. A real contract year pays at least ~10% of APY (min $0.5M) in cash."""
    thresh = max(0.5, 0.1 * f(apy))
    return [y for y, r in yrs.items() if f(r.get("cash_paid")) >= thresh]


def potential_out(yrs, season, thru, rule="savings_ge_dead"):
    """yrs = cap_rows(); thru = final real year. For each Y in season+1..thru:
    dead(Y)   = remaining signing-bonus + option-bonus proration from Y on (void years too)
                + guaranteed salary from Y on
    savings(Y) = cap number(Y) - dead(Y)
    Returns (first qualifying Y or None, dead at that Y or None)."""
    for Y in range(season + 1, thru + 1):
        r = yrs.get(Y)
        if not r:
            continue
        # option bonuses not yet exercised (Y and later) never accelerate: cap each later
        # year's option proration at the level already on the books in Y-1
        opt_prev = f(yrs[Y - 1].get("option_bonus")) if (Y - 1) in yrs else 0.0
        dead = sum(f(yrs[y].get("prorated_bonus")) + min(f(yrs[y].get("option_bonus")), opt_prev)
                   + f(yrs[y].get("guaranteed_salary")) for y in yrs if y >= Y)
        cap = f(r.get("cap_number"))
        sav = cap - dead
        if rule == "savings_pos":
            ok = sav > 0
        elif rule == "savings_ge_half_cap":
            ok = sav > 0 and dead <= cap * 0.5
        else:
            ok = sav > 0 and sav >= dead
        if ok:
            return Y, round(dead, 2), round(sav, 2)
    return None, None, None


def load_otc():
    os.makedirs(CACHE, exist_ok=True)
    raw = requests.get(URL, timeout=180)
    raw.raise_for_status()
    with open(os.path.join(CACHE, "historical_contracts.parquet"), "wb") as fh:
        fh.write(raw.content)
    t = pq.read_table(io.BytesIO(raw.content))
    meta = t.schema.metadata or {}
    stamp = meta.get(b"nflverse_timestamp", b"?").decode("utf-8", "replace")
    rows = t.to_pylist()
    by, loose = {}, {}
    for r in rows:
        if r["position"] not in POS or not r["player"]:
            continue
        pos = "RB" if r["position"] == "FB" else r["position"]
        by.setdefault((norm(r["player"]), pos), []).append(r)
        loose.setdefault((loose_key(r["player"]), pos), []).append(r)
    by["__loose__"] = loose
    return by, stamp, len(rows)


# d.js spelling -> OTC spelling (only when the loose last-name match is ambiguous or fails)
ALIASES = {"Matthew Stafford": "Matt Stafford", "Chig Okonkwo": "Chigoziem Okonkwo", "Nicholas Singleton": "Nick Singleton"}


def loose_key(name):
    """'first-initial + last name' for nickname mismatches (Matt/Matthew, Chig/Chigoziem)."""
    parts = re.sub(r"\b(jr|sr|ii|iii|iv|v)\.?$", "", name.lower().strip()).split()
    if not parts:
        return ""
    return parts[0][0] + re.sub(r"[^a-z]", "", parts[-1])


def find_cands(by, d):
    pos = d["s"]
    for nm in (ALIASES.get(d["n"], d["n"]), d["n"]):
        c = by.get((norm(nm), pos)) or (by.get((norm(nm), "FB")) if pos == "RB" else None)
        if c:
            return c
    # loose fallback: unique player (by OTC id) with the same first initial + last name + position
    c = by["__loose__"].get((loose_key(d["n"]), pos)) or []
    ids = {r.get("otc_id") for r in c}
    if len(ids) == 1:
        return c
    if len(ids) > 1:
        # several players share the key: keep the one on the same team with an active deal
        same = [r for r in c if r.get("is_active") and r.get("team") == nick(d.get("t"))]
        if len({r.get("otc_id") for r in same}) == 1:
            return [r for r in c if r.get("otc_id") == same[0].get("otc_id")]
    return None


def pick(cands, team_nick):
    """Choose the OTC row for a D player: active contract on the same team > any active >
    (no active) most recent row."""
    act = [c for c in cands if c.get("is_active")]
    if act:
        same = [c for c in act if c.get("team") == team_nick]
        pool = same or act
        return max(pool, key=lambda c: (c.get("year_signed") or 0, f(c.get("apy")))), True
    return max(cands, key=lambda c: (c.get("year_signed") or 0)), False


def build(D, by, season, rule):
    """Returns (updates dict name->fields, unmatched list, matched count, fa count)."""
    updates, unmatched = {}, []
    matched = fa = 0
    dr_fill.clear()
    for d in D:
        if d.get("s") not in ("QB", "RB", "WR", "TE", "K"):
            continue
        cands = find_cands(by, d)
        if not cands:
            unmatched.append(d["n"])
            continue
        matched += 1
        row, active = pick(cands, nick(d.get("t")))
        if not active:
            fa += 1
            updates[d["n"]] = {"sal": None, "cyr": "FA", "out": None, "cv": None, "cn": None, "cg": None, "cs": None, "cdead": None, "csav": None}
            continue
        yrs = cap_rows(row.get("season_history"), season)
        real = real_years(yrs, row.get("apy"))
        if real:
            thru = max(real)
            out, dead, sav = potential_out(yrs, season, thru, rule)
        else:
            # no cap table yet (2026 rookies / just-signed deals): final year from the headline
            # terms; a fully guaranteed deal has no cheap out, anything else is cuttable next year
            thru = max(season, (row.get("year_signed") or season) + (row.get("years") or 1) - 1)
            fully = f(row.get("guaranteed")) >= 0.9 * f(row.get("value")) and f(row.get("value")) > 0
            out = None if (fully or thru <= season) else season + 1
            dead = sav = None
        updates[d["n"]] = {
            "sal": m(row.get("apy")), "cyr": thru, "out": out,
            "cv": m(row.get("value")), "cn": row.get("years"), "cg": m(row.get("guaranteed")),
            "cs": row.get("year_signed"), "cdead": dead, "csav": sav,
        }
        # draft round backfill (card "Draft Capital"): pool additions arrive with dr null;
        # OTC carries draft_round for every drafted player. Existing values are never changed.
        if d.get("dr") is None and row.get("draft_round"):
            dr_fill[d["n"]] = int(row["draft_round"])
    return updates, unmatched, matched, fa


def jsv(v):
    return "null" if v is None else json.dumps(v)


def top_level_objects(txt):
    """[(start, end)] of every depth-1 object inside the D array literal (string-aware scan;
    player objects do NOT always start with "n" - pool additions start with "_slImg")."""
    a = txt.index("[", txt.index("="))
    spans, depth, i, n, in_str, start = [], 0, a, len(txt), False, None
    while i < n:
        ch = txt[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
            if depth == 2 and ch == "{":
                start = i
        elif ch in "}]":
            if depth == 2 and ch == "}":
                spans.append((start, i + 1))
            depth -= 1
            if depth == 0:
                break
        i += 1
    return spans


FIELD_RE = {k: re.compile(r',"%s":(?:null|"(?:[^"\\]|\\.)*"|-?[0-9.]+)' % k) for k in ("cyr", "out", "sal") + tuple(NEW_KEYS)}
NAME_RE = re.compile(r'"n":("(?:[^"\\]|\\.)*")')


def splice(txt, updates):
    """Rewrite sal/cyr/out and the new keys inside each player object: every existing copy of
    those keys is removed (d.js carries a few duplicate keys) and one clean run is inserted
    right after "n". Returns (new text, number of objects changed)."""
    out, prev, changed = [], 0, 0
    for s, e in top_level_objects(txt):
        seg = txt[s:e]
        mm = NAME_RE.search(seg)
        u = updates.get(json.loads(mm.group(1))) if mm else None
        if u:
            seg2 = seg
            for k, rx in FIELD_RE.items():
                seg2 = rx.sub("", seg2)
            run = "".join(',"%s":%s' % (k, jsv(u[k])) for k in ("cyr", "out", "sal") + tuple(NEW_KEYS))
            m2 = NAME_RE.search(seg2)
            seg2 = seg2[:m2.end()] + run + seg2[m2.end():]
            if json.loads(mm.group(1)) in dr_fill:
                seg2 = re.sub(r'"dr":null', '"dr":%d' % dr_fill[json.loads(mm.group(1))], seg2, count=1)
            if seg2 != seg:
                changed += 1
            seg = seg2
        out.append(txt[prev:s])
        out.append(seg)
        prev = e
    out.append(txt[prev:])
    return "".join(out), changed


def parse_d(txt):
    body = txt[txt.index("=") + 1:txt.rindex("];") + 1].strip()
    return json.loads(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--max-changes", type=int, default=400)
    ap.add_argument("--rule", default="savings_pos", help="savings_pos (default, matches the hand-entered values best) | savings_ge_dead | savings_ge_half_cap")
    args = ap.parse_args()

    txt = open(DJS, encoding="utf-8").read()
    D = parse_d(txt)
    season = current_season()
    by, stamp, nrows = load_otc()
    print("OTC parquet %s rows, nflverse stamp %s, season %d" % (nrows, stamp, season))

    if args.calibrate:
        for rule in ("savings_pos", "savings_ge_half_cap", "savings_ge_dead"):
            ups, _, _, _ = build(D, by, season, rule)
            hits = tot = 0
            for d in D:
                u = ups.get(d["n"])
                if u and d.get("out") and isinstance(d["out"], int) and d["out"] >= season + 1 and u["out"]:
                    tot += 1
                    hits += (u["out"] == d["out"])
            print("rule %-22s agrees with existing out-year %d/%d" % (rule, hits, tot))
        return 0

    updates, unmatched, matched, fa = build(D, by, season, args.rule)
    eligible = sum(1 for d in D if d.get("s") in ("QB", "RB", "WR", "TE", "K"))
    print("matched %d / %d eligible (%d FA, %d unmatched)" % (matched, eligible, fa, len(unmatched)))
    if unmatched:
        print("unmatched (left as is): " + ", ".join(unmatched[:60]) + (" ..." if len(unmatched) > 60 else ""))
    if matched < 0.8 * eligible:
        print("GUARD: match rate below 80% - nothing written")
        return 3

    byname = {d["n"]: d for d in D}
    diffs = []
    for name, u in updates.items():
        d = byname[name]
        cur = {k: d.get(k) for k in ("sal", "cyr", "out")}
        if any(cur[k] != u[k] for k in cur) or any(d.get(k) != u[k] for k in NEW_KEYS):
            diffs.append((name, d.get("s"), cur, u))
    big = [x for x in diffs if x[2]["cyr"] != x[3]["cyr"] or x[2]["sal"] != x[3]["sal"]]
    print("%d players change (%d with a new AAV/final year); %d draft rounds backfilled" % (len(diffs), len(big), len(dr_fill)))
    if dr_fill:
        print("  dr backfill: " + ", ".join("%s R%d" % kv for kv in sorted(dr_fill.items())[:40]) + (" ..." if len(dr_fill) > 40 else ""))
    for name, s, cur, u in big[:40]:
        print("  %-24s %-2s  %s/%s/%s -> %s yr $%sM (AAV $%sM, gtd $%sM) thru %s, out %s" % (
            name, s, cur["sal"], cur["cyr"], cur["out"], u["cn"], u["cv"], u["sal"], u["cg"], u["cyr"], u["out"]))
    if len(big) > 40:
        print("  ... %d more" % (len(big) - 40))
    if len(big) > args.max_changes:
        print("GUARD: %d AAV/year changes > --max-changes %d - nothing written" % (len(big), args.max_changes))
        return 3
    if not diffs and not dr_fill:
        print("no changes")
        return 0
    if args.dry_run:
        print("dry run - nothing written")
        return 0

    new_txt, changed = splice(txt, updates)
    D2 = parse_d(new_txt)
    if len(D2) != len(D):
        print("ERROR: player count changed after splice (%d -> %d) - nothing written" % (len(D), len(D2)))
        return 1
    by2 = {d["n"]: d for d in D2}
    for name, u in updates.items():
        d2 = by2[name]
        for k in ("sal", "cyr", "out") + tuple(NEW_KEYS):
            if d2.get(k) != u[k]:
                print("ERROR: verify failed for %s.%s (%r != %r) - nothing written" % (name, k, d2.get(k), u[k]))
                return 1
        if name in dr_fill and d2.get("dr") != dr_fill[name]:
            print("ERROR: verify failed for %s.dr (%r != %r) - nothing written" % (name, d2.get("dr"), dr_fill[name]))
            return 1
    with open(DJS, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new_txt)
    print("wrote data/d.js: %d player objects updated (OTC %s)" % (changed, stamp))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa
        print("ERROR: %s" % e)
        sys.exit(1)
