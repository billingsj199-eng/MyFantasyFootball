"""
LIVE TRACKER — grades the helpers' live-projection layer on a real game as it
happens, end to end on the real data path:

  pregame proj  = site sim_proj_2026.json week row (PPR frame)       [Sim Lab]
  scored so far = Sleeper /v1/stats/nfl/regular/<season>/<week> pts_ppr
  game clock    = ESPN public scoreboard (period + clock + score)
  remaining     = data/live_model.json (fitted)  vs  v1 heuristic  vs  naive

Every POLL seconds while any tracked game is in progress it appends one row
per tracked player to a CSV (ts, game state, actual, and the live number under
all three models). When every tracked game is final it grades every snapshot
against the finals (|live - final| by game fraction and by player) and writes
a summary JSON next to the CSV. Re-grade any log later with --grade.

usage:
  python live_tracker.py --all                     # every game kicking off within WINDOW_H (2h) of now,
                                                   # or already in progress; exits at once when there is none.
                                                   # Overlapping windows: games are CLAIMED in data/live_claims.json
                                                   # so a second process skips what the first is tracking.
  python live_tracker.py --teams NE,SEA            # explicit teams: wait for kickoff, track, grade
  python live_tracker.py --teams NE,SEA --once     # one tick, print, exit (dry run)
  python live_tracker.py --grade data/live_track_*.csv     # re-grade one or many logs together
"""
import argparse, csv, json, os, sys, time, datetime as dt
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = r"E:/MyFantasyFootball/MyFantasyFootball Files"
SIM_PROJ = os.path.join(REPO, "data", "sim_proj_2026.json")
PLAYERS = os.path.join(REPO, "sleeper-extension", "data", "players.json")
LIVE_MODEL = os.path.join(HERE, "data", "live_model.json")
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
SLEEPER_STATE = "https://api.sleeper.app/v1/state/nfl"
SLEEPER_PLAYERS = "https://api.sleeper.app/v1/players/nfl"
SLEEPER_STATS = "https://api.sleeper.app/v1/stats/nfl/regular/{season}/{week}"
ESPN_FIX = {"WSH": "WAS", "JAC": "JAX", "LA": "LAR", "OAK": "LV", "SD": "LAC"}
POLL = 60
MAX_HOURS = 5.5
WINDOW_H = 2.0          # --all: games kicking off within this many hours
CLAIMS = os.path.join(HERE, "data", "live_claims.json")
UA = {}  # ESPN (Akamai) 403s a browser UA from a non-browser client; the default requests UA is fine


def norm(n):
    s = (n or "").lower().strip()
    for suf in (" jr.", " jr", " sr.", " sr", " iii", " ii", " iv", " v"):
        if s.endswith(suf): s = s[: -len(suf)].strip()
    for ch in "'’`.,": s = s.replace(ch, "")
    return " ".join(s.replace("-", " ").split())


def get_json(url):
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    return r.json()


# ---------------- game clock ----------------
def parse_scoreboard(sb):
    out = {}
    for ev in sb.get("events", []):
        c = (ev.get("competitions") or [{}])[0]
        st = (c.get("status") or {}).get("type") or {}
        nm = str(st.get("name") or "")
        s = "in" if st.get("state") == "in" else ("post" if st.get("state") == "post" or st.get("completed") else "pre")
        period = int((c.get("status") or {}).get("period") or 0)
        clock = str((c.get("status") or {}).get("displayClock") or "0:00")
        half = "HALFTIME" in nm.upper()
        f = 0.0
        if s == "post": f = 1.0
        elif s == "in":
            if half: f = 0.5
            elif period >= 5: f = 0.97
            else:
                try:
                    mm, ss = clock.split(":"); left = int(mm) * 60 + int(ss)
                except Exception:
                    left = 0
                f = min(0.99, max(0.01, ((max(1, period) - 1) * 900 + (900 - left)) / 3600.0))
        comps = c.get("competitors") or []
        home = next((x for x in comps if x.get("homeAway") == "home"), None)
        away = next((x for x in comps if x.get("homeAway") == "away"), None)
        ab = lambda x: ESPN_FIX.get(str(((x or {}).get("team") or {}).get("abbreviation") or "").upper(),
                                    str(((x or {}).get("team") or {}).get("abbreviation") or "").upper())
        sc = lambda x: float(x.get("score")) if x and x.get("score") not in (None, "") else None
        h, a = ab(home), ab(away)
        tag = ("HALF" if half else ("OT " + clock if period >= 5 else f"Q{period} {clock}")) if s == "in" else ("FINAL" if s == "post" else "PRE")
        gid = str(ev.get("id") or (a + "@" + h))
        if h: out[h] = {"st": s, "f": f, "tag": tag, "opp": a, "pts": sc(home), "oppPts": sc(away), "kick": ev.get("date"), "gid": gid}
        if a: out[a] = {"st": s, "f": f, "tag": tag, "opp": h, "pts": sc(away), "oppPts": sc(home), "kick": ev.get("date"), "gid": gid}
    return out


# ---------------- remaining models ----------------
def load_model():
    lm = json.load(open(LIVE_MODEL))
    return lm["grid"], lm["pos"]


def coefs(grid, rows, f):
    if f <= grid[0]: return rows[0]
    if f >= grid[-1]: return rows[-1]
    i = 0
    while i < len(grid) - 2 and grid[i + 1] < f: i += 1
    t = (f - grid[i]) / (grid[i + 1] - grid[i])
    return [rows[i][k] + (rows[i + 1][k] - rows[i][k]) * t for k in range(len(rows[i]))]


def remaining(model, pos, f, proj, actual, margin, f_in=0.0, rel=None):
    """(fitted, v1, naive) remaining points — same arithmetic as the helpers.
    f_in = game fraction at which the player entered (backup QB); pace runs
    over the span he has actually been in, so span == f for everyone else.
    rel = own team score (K) / points allowed (DST) so far — the 4th coefficient
    of the K and DST rows (live model v2); None when the model lacks them."""
    grid, table = model
    cls = "QB" if pos == "QB" else "RB" if pos == "RB" else "REC" if pos in ("WR", "TE") else pos if pos in ("K", "DST") else None
    span = max(f - f_in, 0.1)
    naive = max(0.0, proj * (1 - f))
    pace_v1 = actual / span if span >= 0.15 else proj
    w = 0.25 * f
    v1 = max(0.0, (1 - f) * ((1 - w) * proj + w * pace_v1))
    if cls and cls in table:
        co = coefs(grid, table[cls], f)
        extra = co[3] * (rel / 10.0) if len(co) > 3 and rel is not None else 0.0
        floor = (-4.0 - actual) if pos == "DST" else 0.0  # DST remaining goes negative as points are allowed; live total floors at -4
        fit = max(floor, (1 - f) * (co[0] * proj + co[1] * (actual / span) + co[2] * proj * (margin / 10.0) + extra))
    else:
        fit = v1  # class not in the export: the helpers fall back to v1 too
    return fit, v1, naive


# ---------------- player-exited rule ----------------
# A player whose league-scored total has not moved for a long stretch of GAME
# CLOCK has very likely left the game (2026 W1: Darnold exited after 2 attempts
# at 0.5 pts and every model kept projecting ~8 more at halftime). seen[sid] =
# {"pts", "f0"}: the total and the game fraction at which it last changed
# (0 when watched from kickoff, else the fraction at first sight). stale =
# f - f0 scales the fitted remaining by a per-position ramp (start, full,
# floor): a playing QB moves the total every drive, so his ramp is short and
# floors at 0; RB/WR/TE have normal quiet stretches, so they ramp slower and
# keep a floor. K/DST exempt. QB accelerator: another QB on the same team with
# >= 2 live pts while this one is stale >= 0.10 -> 0 (the backup has the job).
# Mirrors liveExitMult() in the helpers (Sleeper 0.29.26 / ESPN 0.20.36 /
# Yahoo 0.9.26). Logged as `live_fitx` beside the un-scaled `live_fit`.
# CALIBRATED on nflverse pbp 2019-25 (sim_lab/backtest_exit_rule.py): QB ramp on any
# total, floor 0.40 (empirical multiplier ~0.4 from stale 0.35 on); RB only once he has
# scored (zero-total RBs are quiet committee backs, not exits); WR/TE NO ramp (their
# multiplier is ~1.0 at every stale bucket; the hand-set ramp lost on holdout).
# Teammate-QB trigger -> x0.30 (right ~68% of the time; 0 over-cuts the mean).
EXIT_RAMP = {"QB": (0.15, 0.35, 0.40), "RB": (0.20, 0.80, 0.10)}
EXIT_GATED = {"RB"}          # ramp only after the player has scored
EXIT_TEAMMATE_MULT = 0.30
QB_BY_TEAM = {}  # team -> [sleeper ids of every QB on the roster] (teammate rule)
QB_NAME = {}     # sleeper id -> name (backup rows)
# BACKUP QB (Jack 09-10: "track the backup QB when the starter goes out"): a QB
# on a tracked team with no sim row who reaches >= 2 live pts is in for the
# starter -> logged as role=backup with proj = team starter's proj x
# BACKUP_SHARE, remaining paced from the fraction his points started (f_in).
# Mirrors liveBackupInherit() in the helpers.
BACKUP_SHARE = 0.90          # calibrated 2019-25: 0.95 after injury-like exits ...
BACKUP_SHARE_BLOWOUT = 0.60  # ... 0.59 after blowout pulls (|margin| >= BLOWOUT_MARGIN)
BLOWOUT_MARGIN = 17
BACKUP_MIN_PTS = 2.0


def seen_note(seen, sid, actual, f, st):
    """Record the last change of a player's total; returns the stale fraction."""
    s = seen.get(sid)
    if st == "pre":
        seen[sid] = {"pts": actual, "f0": 0.0}; return 0.0
    if s is None:
        s = seen[sid] = {"pts": actual, "f0": 0.0 if f <= 0.02 else f}
        if actual > 0:
            if f <= 0.02: s["f_in"] = 0.0
            else: s["f_in_unknown"] = True  # already producing at first sight: entry fraction unknown
        return 0.0
    if s["pts"] != actual:
        if actual > 0 and "f_in" not in s and not s.get("f_in_unknown"): s["f_in"] = f
        s["pts"] = actual; s["f0"] = f; return 0.0
    return max(0.0, f - s["f0"])


def exit_mult(pos, stale, teammate_qb=False, actual=None):
    ramp = EXIT_RAMP.get(pos)
    if not ramp: return 1.0
    mult = 1.0
    lo, hi, floor = ramp
    if stale > lo and not (pos in EXIT_GATED and actual == 0):
        mult = 1.0 - (1.0 - floor) * min(1.0, (stale - lo) / (hi - lo))
    if pos == "QB" and stale >= 0.10 and teammate_qb: mult = min(mult, EXIT_TEAMMATE_MULT)
    return mult


# FEED-FROZEN guard: if no watched total in a game (either team) has moved for
# FEED_FROZEN of game clock the stats feed is stalled -> exit rule paused
# (xmult 1, `frozen` column 1). feed[team] = f at the last observed change.
FEED_FROZEN = 0.10


def feed_update(feed, seen, states, sids_by_team, stats):
    """Per team: note changes vs last tick (before seen_note runs), seed new games."""
    changed = set()
    for t, sids in sids_by_team.items():
        g = states[t]
        if g["st"] != "in": continue
        if t not in feed: feed[t] = g["f"]
        for sid in sids:
            prev = seen.get(sid)
            pts = float((stats.get(sid) or {}).get("pts_ppr") or 0.0)
            if prev is not None and prev["pts"] != pts: changed.add(t); break
    for t in list(changed):
        feed[t] = states[t]["f"]
        opp = states[t].get("opp")
        if opp in states: feed[opp] = states[t]["f"]
    return {t: (states[t]["st"] == "in" and t in feed and states[t]["f"] - feed[t] >= FEED_FROZEN) for t in states}


def teammate_qb(stats, sid, team):
    for o in QB_BY_TEAM.get(team, []):
        if o != sid and float((stats.get(o) or {}).get("pts_ppr") or 0) >= 2: return True
    return False


# ---------------- tracked players ----------------
def load_qb_map(teams):
    """Every QB on the tracked teams (Sleeper dump) — backups have no sim row / players.json entry."""
    try: dump = get_json(SLEEPER_PLAYERS)
    except Exception as e:
        print("sleeper player dump failed (teammate-QB rule off):", e); return
    for sid, p in dump.items():
        if p.get("position") == "QB" and p.get("team") in teams:
            QB_BY_TEAM.setdefault(p["team"], []).append(str(sid))
            QB_NAME[str(sid)] = p.get("full_name") or (p.get("first_name", "") + " " + p.get("last_name", "")).strip()


def tracked_players(teams):
    sp = json.load(open(SIM_PROJ, encoding="utf-8"))
    week = str(sp.get("currentWeek") or 1)
    rows = sp["weeks"][week]
    idx = {norm(k): v for k, v in rows.items()}
    pj = json.load(open(PLAYERS, encoding="utf-8"))["players"]
    out = []
    for p in pj:
        if p.get("sTm") not in teams or not p.get("sid"): continue
        key = ("dst_" + p["sTm"].lower()) if p["s"] == "DST" else norm(p["n"])
        row = idx.get(key) or (rows.get("DST_" + p["sTm"]) if p["s"] == "DST" else None)
        if not row or not isinstance(row, list) or row[1] in (None, 0): continue
        out.append({"sid": str(p["sid"]), "name": p["n"], "pos": p["s"], "team": p["sTm"], "proj": float(row[1])})
    return int(week), out


def _load_claims():
    try: return json.load(open(CLAIMS))
    except Exception: return {}


def _save_claims(c):
    try: json.dump(c, open(CLAIMS, "w"), indent=1)
    except Exception as e: print("claims write failed:", e)


def select_games(window_h):
    """--all: teams of every game that is in progress or kicks off within
    window_h hours, minus games another live process claimed < 8h ago."""
    games = parse_scoreboard(get_json(SCOREBOARD + "?t=" + str(int(time.time()))))
    now = dt.datetime.now(dt.timezone.utc)
    claims = _load_claims()
    fresh = {g: c for g, c in claims.items() if now.timestamp() - c.get("ts", 0) < 8 * 3600}
    pick, seen = [], set()
    for team, g in games.items():
        gid = g["gid"]
        if gid in seen: continue
        seen.add(gid)
        if g["st"] == "post": continue
        if g["st"] == "pre":
            try: kick = dt.datetime.fromisoformat(str(g["kick"]).replace("Z", "+00:00"))
            except Exception: continue
            hrs = (kick - now).total_seconds() / 3600
            if hrs > window_h or hrs < -4: continue
        if gid in fresh and fresh[gid].get("pid") != os.getpid():
            print(f"  {g['opp']}@{team}: already tracked by pid {fresh[gid]['pid']} — skipping")
            continue
        pick.append(gid); fresh[gid] = {"pid": os.getpid(), "ts": now.timestamp(), "game": g["opp"] + "@" + team}
    _save_claims(fresh)
    teams = sorted(t for t, g in games.items() if g["gid"] in pick)
    return teams, [fresh[g]["game"] for g in pick]


FIELDS = ["ts", "team", "st", "f", "tag", "margin", "sid", "name", "pos", "proj", "actual",
          "rem_fit", "live_fit", "live_v1", "live_naive", "stale", "xmult", "live_fitx", "role", "f_in", "frozen"]


def tick(season, week, teams, players, model, writer=None, verbose=False, seen=None, backups=None, feed=None):
    seen = seen if seen is not None else {}
    backups = backups if backups is not None else {}
    feed = feed if feed is not None else {}
    games = parse_scoreboard(get_json(SCOREBOARD + "?t=" + str(int(time.time()))))
    try:
        stats = get_json(SLEEPER_STATS.format(season=season, week=week) + "?t=" + str(int(time.time()))) or {}
    except Exception as e:
        stats = {}
        print("  sleeper stats fetch failed:", e)
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    states = {t: games.get(t, {"st": "pre", "f": 0.0, "tag": "PRE"}) for t in teams}
    rows = []
    # BACKUP QBs: watch every QB on the tracked teams; one without a sim row who
    # reaches BACKUP_MIN_PTS while the game is on is in for the starter.
    tracked = {p["sid"] for p in players}
    watched = {t: [p["sid"] for p in players if p["team"] == t] + [o for o in QB_BY_TEAM.get(t, []) if o not in tracked] for t in teams}
    frozen = feed_update(feed, seen, states, watched, stats)
    for t in teams:
        g = states[t]
        starter = max((p for p in players if p["team"] == t and p["pos"] == "QB"), key=lambda p: p["proj"], default=None)
        for o in QB_BY_TEAM.get(t, []):
            if o in tracked: continue
            pts = float((stats.get(o) or {}).get("pts_ppr") or 0.0)
            seen_note(seen, o, pts, g["f"], g["st"])
            if o not in backups and g["st"] == "in" and pts >= BACKUP_MIN_PTS and starter:
                # entry fraction: his first points if we saw them; else when the starter's total
                # last moved (he left about then); else treat him as in from kickoff (conservative pace)
                f_in = seen[o].get("f_in")
                if f_in is None:
                    ss = seen.get(starter["sid"]); f_in = ss["f0"] if ss and ss.get("f0", 0) < g["f"] else 0.0
                mg = abs((g.get("pts") or 0) - (g.get("oppPts") or 0)) if g.get("pts") is not None and g.get("oppPts") is not None else 0
                share = BACKUP_SHARE_BLOWOUT if mg >= BLOWOUT_MARGIN else BACKUP_SHARE
                backups[o] = {"sid": o, "name": QB_NAME.get(o, o), "pos": "QB", "team": t, "role": "backup",
                              "proj": round(starter["proj"] * share, 2), "f_in": round(f_in, 3), "for": starter["name"]}
                print(f"  BACKUP IN: {backups[o]['name']} ({t}) at f={backups[o]['f_in']:.2f} with {pts:.1f} pts — inherits {starter['name']} {starter['proj']:.1f} x {share}" + (" (blowout)" if share < BACKUP_SHARE else ""))
    for p in players + [b for b in backups.values() if b["team"] in states]:
        g = states[p["team"]]
        st, f = g["st"], g["f"]
        s = stats.get(p["sid"]) or {}
        actual = float(s.get("pts_ppr") or 0.0)
        margin = (g.get("pts") or 0) - (g.get("oppPts") or 0) if g.get("pts") is not None and g.get("oppPts") is not None else 0.0
        if st == "pre":
            seen_note(seen, p["sid"], actual, 0.0, st); stale, xm = 0.0, 1.0
            rem = p["proj"]; live = (p["proj"], p["proj"], p["proj"]); fitx = p["proj"]
        elif st == "post":
            stale, xm = 0.0, 1.0
            rem = 0.0; live = (actual, actual, actual); fitx = actual
        else:
            rel = g.get("oppPts") if p["pos"] == "DST" else g.get("pts")
            fit, v1, nv = remaining(model, p["pos"], f, p["proj"], actual, margin, p.get("f_in", 0.0), rel)
            stale = seen_note(seen, p["sid"], actual, f, st)
            xm = 1.0 if frozen.get(p["team"]) else exit_mult(p["pos"], stale, teammate_qb(stats, p["sid"], p["team"]), actual)
            rem = fit; live = (actual + fit, actual + v1, actual + nv); fitx = actual + fit * xm
        row = {"ts": now, "team": p["team"], "st": st, "f": round(f, 3), "tag": g["tag"], "margin": margin,
               "sid": p["sid"], "name": p["name"], "pos": p["pos"], "proj": round(p["proj"], 2), "actual": round(actual, 2),
               "rem_fit": round(rem, 2), "live_fit": round(live[0], 2), "live_v1": round(live[1], 2), "live_naive": round(live[2], 2),
               "stale": round(stale, 3), "xmult": round(xm, 3), "live_fitx": round(fitx, 2),
               "role": p.get("role", ""), "f_in": round(p.get("f_in", 0.0), 3), "frozen": int(bool(frozen.get(p["team"])))}
        rows.append(row)
        if writer: writer.writerow(row)
    if verbose:
        for t in teams:
            g = states[t]
            print(f"  {t}: {g['st']} {g['tag']} f={g['f']:.2f} score {g.get('pts')}-{g.get('oppPts')}" + ("  FEED FROZEN (exit rule paused)" if frozen.get(t) else ""))
        for r in sorted(rows, key=lambda r: -r["proj"])[:12]:
            xt = f"  exit x{r['xmult']:.2f} (stale {r['stale']:.2f})" if r["xmult"] < 1 else ""
            if r["role"] == "backup": xt = f"  BACKUP in at f={r['f_in']:.2f}" + xt
            print(f"    {r['name']:<22}{r['pos']:<4} proj {r['proj']:5.1f}  scored {r['actual']:5.1f}  live fit {r['live_fit']:5.1f} | +exit {r['live_fitx']:5.1f} | v1 {r['live_v1']:5.1f} | naive {r['live_naive']:5.1f}{xt}")
    return states, rows


# ---------------- grading ----------------
def add_fitx(rows):
    """Logs written before the exit rule: replay it from the rows (teammate-QB
    signal limited to QBs that were in the log) so old and new logs grade alike."""
    if rows and rows[0].get("live_fitx") not in ("", None): return
    seen, qb_pts = {}, {}
    for r in rows:
        if r["pos"] == "QB": qb_pts.setdefault((r["ts"], r["team"]), {})[r["sid"]] = float(r["actual"])
    for r in rows:
        st, f, actual = r["st"], float(r["f"]), float(r["actual"])
        stale = seen_note(seen, r["sid"], actual, f, st)
        if st != "in":
            r["live_fitx"] = r["live_fit"]; r["xmult"] = "1"; r["stale"] = "0"; continue
        tq = r["pos"] == "QB" and any(v >= 2 for k, v in qb_pts.get((r["ts"], r["team"]), {}).items() if k != r["sid"])
        xm = exit_mult(r["pos"], stale, tq, actual)
        r["live_fitx"] = str(round(actual + float(r["rem_fit"]) * xm, 2)); r["xmult"] = str(round(xm, 3)); r["stale"] = str(round(stale, 3))


def grade(csv_path):
    paths = csv_path if isinstance(csv_path, list) else [csv_path]
    rows = []
    for pth in paths:
        rows += list(csv.DictReader(open(pth, encoding="utf-8")))
    if not rows: print("empty log"); return
    add_fitx(rows)
    csv_path = paths[0] if len(paths) == 1 else os.path.join(os.path.dirname(paths[0]), "live_track_COMBINED.csv")
    finals = {}
    for r in rows:
        if r["st"] == "post": finals[r["sid"]] = float(r["actual"])
    if not finals:  # game not final yet: use the latest actual as a provisional final
        last = {}
        for r in rows: last[r["sid"]] = float(r["actual"])
        finals = last
        print("NOTE: no FINAL rows in the log — grading against the latest scored value")
    live = [r for r in rows if r["st"] == "in" and r["sid"] in finals]
    if not live: print("no in-game snapshots to grade"); return
    bins = [(0.0, 0.25, "Q1"), (0.25, 0.5, "Q2"), (0.5, 0.75, "Q3"), (0.75, 1.01, "Q4")]
    print(f"\n=== LIVE GRADE {os.path.basename(csv_path)}: {len(live)} snapshots, {len(finals)} players ===")
    print("|live - final|   fitted | fit+exit | v1 | naive   (n)")
    summary = {"bins": {}, "players": {}}
    tot = [0.0, 0.0, 0.0, 0.0]; n = 0
    for lo, hi, lbl in bins:
        sel = [r for r in live if lo <= float(r["f"]) < hi]
        if not sel: continue
        e = [sum(abs(float(r[k]) - finals[r["sid"]]) for r in sel) / len(sel) for k in ("live_fit", "live_fitx", "live_v1", "live_naive")]
        for i in range(4): tot[i] += e[i] * len(sel)
        n += len(sel)
        summary["bins"][lbl] = {"fit": round(e[0], 3), "fitx": round(e[1], 3), "v1": round(e[2], 3), "naive": round(e[3], 3), "n": len(sel)}
        print(f"  {lbl}   {e[0]:.2f} | {e[1]:.2f} | {e[2]:.2f} | {e[3]:.2f}   ({len(sel)})")
    if n:
        print(f"  ALL  {tot[0]/n:.3f} | {tot[1]/n:.3f} | {tot[2]/n:.3f} | {tot[3]/n:.3f}   ({n})")
        summary["all"] = {"fit": round(tot[0] / n, 3), "fitx": round(tot[1] / n, 3), "v1": round(tot[2] / n, 3), "naive": round(tot[3] / n, 3), "n": n}
    print("\nper player (mean |live - final| over the game):  proj -> final   fitted | fit+exit | v1 | naive")
    by = {}
    for r in live: by.setdefault(r["sid"], []).append(r)
    wins = [0, 0, 0, 0]
    for sid, rs in sorted(by.items(), key=lambda kv: -float(kv[1][0]["proj"])):
        e = [sum(abs(float(r[k]) - finals[sid]) for r in rs) / len(rs) for k in ("live_fit", "live_fitx", "live_v1", "live_naive")]
        wins[e.index(min(e))] += 1
        role = rs[0].get("role") or ""
        summary["players"][rs[0]["name"]] = {"pos": rs[0]["pos"], "proj": float(rs[0]["proj"]), "final": finals[sid], "fit": round(e[0], 2), "fitx": round(e[1], 2), "v1": round(e[2], 2), "naive": round(e[3], 2), **({"role": role, "f_in": float(rs[0].get("f_in") or 0)} if role else {})}
        tag = " (backup)" if role == "backup" else ""
        print(f"  {(rs[0]['name'] + tag):<22}{rs[0]['pos']:<4} {float(rs[0]['proj']):5.1f} -> {finals[sid]:5.1f}   {e[0]:.2f} | {e[1]:.2f} | {e[2]:.2f} | {e[3]:.2f}")
    print(f"closest model per player: fitted {wins[0]}  fit+exit {wins[1]}  v1 {wins[2]}  naive {wins[3]}")
    summary["wins"] = {"fit": wins[0], "fitx": wins[1], "v1": wins[2], "naive": wins[3]}
    out = csv_path.replace(".csv", "_summary.json")
    json.dump(summary, open(out, "w"), indent=1)
    print("wrote", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", default="NE,SEA")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--grade", nargs="+")
    ap.add_argument("--out")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--window", type=float, default=WINDOW_H)
    a = ap.parse_args()
    if a.grade:
        import glob
        files = sorted(sum((glob.glob(g) for g in a.grade), []))
        grade(files); return
    if a.all:
        teams, games = select_games(a.window)
        if not teams:
            print(f"no game in progress or kicking off within {a.window:g}h — nothing to track"); return
        print("games:", ", ".join(games))
    else:
        teams = [t.strip().upper() for t in a.teams.split(",") if t.strip()]
    state = get_json(SLEEPER_STATE)
    season = state.get("season") or dt.date.today().year
    week, players = tracked_players(teams)
    load_qb_map(teams)
    model = load_model()
    print(f"tracking {len(players)} players on {teams}, season {season} week {week}, live model grid {model[0]}")
    if a.once:
        tick(season, week, teams, players, model, verbose=True, seen={}, backups={}, feed={}); return
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    label = "_".join(teams) if len(teams) <= 4 else f"{len(teams)//2}games_{stamp}"
    out = a.out or os.path.join(HERE, "data", f"live_track_{season}_w{week}_{label}.csv")
    if os.path.exists(out):  # a same-label log from before a column change: rotate it aside
        with open(out, encoding="utf-8") as fh0: head = fh0.readline().strip()
        if head != ",".join(FIELDS):
            os.replace(out, out.replace(".csv", "_oldcols.csv")); print("rotated old-column log aside")
    new = not os.path.exists(out)
    fh = open(out, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(fh, fieldnames=FIELDS)
    if new: w.writeheader()
    t0 = time.time(); ticks = 0; seen = {}; backups = {}; feed = {}
    while time.time() - t0 < MAX_HOURS * 3600:
        try:
            states, _ = tick(season, week, teams, players, model, writer=w, verbose=(ticks % 10 == 0), seen=seen, backups=backups, feed=feed)
            fh.flush(); ticks += 1
            if all(states[t]["st"] == "post" for t in teams):
                print("all tracked games FINAL"); break
            if all(states[t]["st"] == "pre" for t in teams):
                # pregame: cheap idle — poll every 2 min until kickoff
                time.sleep(120); continue
        except Exception as e:
            print("tick failed:", e)
        time.sleep(POLL)
    fh.close()
    grade(out)


if __name__ == "__main__":
    main()
