"""
LIVE TRACKER (cloud edition) — grades the helpers' live-projection layer on
real games as they happen, on the same data path the helpers use:

  pregame proj  = the site's data/sim_proj_2026.json week row (PPR frame)   [Sim Lab]
  scored so far = Sleeper /v1/stats/nfl/regular/<season>/<week>  pts_ppr
  game clock    = ESPN public scoreboard (period + clock + score)
  remaining     = fitted live model (sim_proj `liveModel`, else live_model.json here)
                  vs the v1 heuristic vs a naive proj × game-left split

Runs from GitHub Actions (.github/workflows/live-tracker.yml) at every NFL
kickoff window, so the home machine can be off. `--all` picks every game in
progress or kicking off within --window hours, CLAIMS them in
<logs-dir>/live_claims.json (committed at once so the overlapping EDT/EST
crons and the Sunday windows never double-track a game), logs one row per
player per minute to <logs-dir>/live_track_<season>_w<week>_<label>.csv, and
grades every snapshot against the finals when the slate ends
(<label>_summary.json). Set TRACKER_GIT=1 to commit + push from the logs
checkout (claims right after selection, results at the end).

Mirror of E:/MyFantasyFootball/sim_lab/live_tracker.py (the machine-local
copy) with network inputs instead of local files.

usage:
  python live_tracker.py --all [--window 2] [--logs-dir logs/data]
  python live_tracker.py --teams NE,SEA --once             # dry run
  python live_tracker.py --grade "logs/data/live_track_2026_w1_*.csv"
"""
import argparse, csv, glob, json, os, subprocess, sys, time, datetime as dt
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
SIM_PROJ_URL = os.environ.get("MFF_SIM_PROJ_URL", "https://www.myfantasyfootball.co/data/sim_proj_2026.json")
SLEEPER_PLAYERS = "https://api.sleeper.app/v1/players/nfl"
SLEEPER_STATE = "https://api.sleeper.app/v1/state/nfl"
SLEEPER_STATS = "https://api.sleeper.app/v1/stats/nfl/regular/{season}/{week}"
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
LOCAL_MODEL = os.path.join(HERE, "live_model.json")
ESPN_FIX = {"WSH": "WAS", "JAC": "JAX", "LA": "LAR", "OAK": "LV", "SD": "LAC"}
POLL = 60
MAX_HOURS = 5.5
WINDOW_H = 2.0
UA = {}  # ESPN's edge 403s a browser UA from a non-browser client; the default requests UA is fine


def norm(n):
    s = (n or "").lower().strip()
    for suf in (" jr.", " jr", " sr.", " sr", " iii", " ii", " iv", " v"):
        if s.endswith(suf): s = s[: -len(suf)].strip()
    for ch in "'’`.,": s = s.replace(ch, "")
    return " ".join(s.replace("-", " ").split())


def get_json(url):
    r = requests.get(url, headers=UA, timeout=30)
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
def load_model(sim_proj):
    lm = sim_proj.get("liveModel") if isinstance(sim_proj, dict) else None
    src = "site export"
    if not (lm and lm.get("grid") and lm.get("pos")):
        lm = json.load(open(LOCAL_MODEL)); src = "local live_model.json"
    print(f"live model: {src} (built {lm.get('built')}, grid {lm['grid']})")
    return lm["grid"], lm["pos"]


def coefs(grid, rows, f):
    if f <= grid[0]: return rows[0]
    if f >= grid[-1]: return rows[-1]
    i = 0
    while i < len(grid) - 2 and grid[i + 1] < f: i += 1
    t = (f - grid[i]) / (grid[i + 1] - grid[i])
    return [rows[i][k] + (rows[i + 1][k] - rows[i][k]) * t for k in range(3)]


def remaining(model, pos, f, proj, actual, margin):
    """(fitted, v1, naive) remaining points — same arithmetic as the helpers."""
    grid, table = model
    cls = "QB" if pos == "QB" else "RB" if pos == "RB" else "REC" if pos in ("WR", "TE") else None
    naive = max(0.0, proj * (1 - f))
    pace_v1 = actual / f if f >= 0.15 else proj
    w = 0.25 * f
    v1 = max(0.0, (1 - f) * ((1 - w) * proj + w * pace_v1))
    if cls and cls in table:
        a, b, m = coefs(grid, table[cls], f)
        fit = max(0.0, (1 - f) * (a * proj + b * (actual / max(f, 0.1)) + m * proj * (margin / 10.0)))
    else:
        fit = v1  # K/DST: the helpers fall back to v1 too
    return fit, v1, naive


# ---------------- tracked players ----------------
def tracked_players(teams, sim_proj):
    """Sleeper's player dump (id/name/pos/team) joined to the site's week rows."""
    week = str(sim_proj.get("currentWeek") or 1)
    rows = sim_proj["weeks"][week]
    idx = {norm(k): v for k, v in rows.items()}
    dump = get_json(SLEEPER_PLAYERS)
    out, seen = [], set()
    for sid, p in dump.items():
        tm = p.get("team")
        pos = p.get("position")
        if tm not in teams or not pos: continue
        if pos == "DEF":
            row = rows.get("DST_" + tm)
            name = (p.get("first_name", "") + " " + p.get("last_name", "")).strip() + " D/ST"
            pos = "DST"
        else:
            if pos not in ("QB", "RB", "WR", "TE", "K"): continue
            name = p.get("full_name") or (p.get("first_name", "") + " " + p.get("last_name", "")).strip()
            row = idx.get(norm(name))
        if not row or not isinstance(row, list) or row[1] in (None, 0): continue
        key = (norm(name), pos)
        if key in seen: continue  # duplicate dump entries (retired ids) — first wins
        seen.add(key)
        out.append({"sid": str(sid), "name": name, "pos": pos, "team": tm, "proj": float(row[1])})
    return int(week), out


# ---------------- claims (overlapping windows) ----------------
def _claims_path(logs_dir): return os.path.join(logs_dir, "live_claims.json")


def select_games(window_h, logs_dir):
    games = parse_scoreboard(get_json(SCOREBOARD + "?t=" + str(int(time.time()))))
    now = dt.datetime.now(dt.timezone.utc)
    try: claims = json.load(open(_claims_path(logs_dir)))
    except Exception: claims = {}
    run_id = os.environ.get("GITHUB_RUN_ID") or str(os.getpid())
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
        if gid in fresh and fresh[gid].get("run") != run_id:
            print(f"  {g['opp']}@{team}: already tracked by run {fresh[gid]['run']} — skipping")
            continue
        pick.append(gid); fresh[gid] = {"run": run_id, "ts": now.timestamp(), "game": g["opp"] + "@" + team}
    os.makedirs(logs_dir, exist_ok=True)
    json.dump(fresh, open(_claims_path(logs_dir), "w"), indent=1)
    teams = sorted(t for t, g in games.items() if g["gid"] in pick)
    return teams, [fresh[g]["game"] for g in pick]


def git_publish(logs_dir, msg, paths):
    """Commit the given paths inside the logs checkout and push (rebase + retry)."""
    if os.environ.get("TRACKER_GIT") != "1": return
    def run(*cmd):
        return subprocess.run(["git", *cmd], cwd=logs_dir, capture_output=True, text=True)
    run("add", "--", *paths)
    if run("diff", "--cached", "--quiet").returncode == 0:
        print("git: nothing to commit"); return
    r = run("commit", "-q", "-m", msg)
    if r.returncode: print("git commit:", r.stderr.strip()); return
    for attempt in range(4):
        run("pull", "-q", "--rebase", "-X", "theirs", "origin", "live-tracker-logs")
        r = run("push", "-q", "origin", "HEAD:live-tracker-logs")
        if r.returncode == 0: print("git: pushed", msg); return
        print(f"git push failed (attempt {attempt + 1}):", r.stderr.strip()[-200:])
        time.sleep(15)


FIELDS = ["ts", "team", "st", "f", "tag", "margin", "sid", "name", "pos", "proj", "actual",
          "rem_fit", "live_fit", "live_v1", "live_naive"]


def tick(season, week, teams, players, model, writer=None, verbose=False):
    games = parse_scoreboard(get_json(SCOREBOARD + "?t=" + str(int(time.time()))))
    try:
        stats = get_json(SLEEPER_STATS.format(season=season, week=week) + "?t=" + str(int(time.time()))) or {}
    except Exception as e:
        stats = {}
        print("  sleeper stats fetch failed:", e)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    states = {t: games.get(t, {"st": "pre", "f": 0.0, "tag": "PRE"}) for t in teams}
    rows = []
    for p in players:
        g = states[p["team"]]
        st, f = g["st"], g["f"]
        s = stats.get(p["sid"]) or {}
        actual = float(s.get("pts_ppr") or 0.0)
        margin = (g.get("pts") or 0) - (g.get("oppPts") or 0) if g.get("pts") is not None and g.get("oppPts") is not None else 0.0
        if st == "pre":
            rem = p["proj"]; live = (p["proj"], p["proj"], p["proj"])
        elif st == "post":
            rem = 0.0; live = (actual, actual, actual)
        else:
            fit, v1, nv = remaining(model, p["pos"], f, p["proj"], actual, margin)
            rem = fit; live = (actual + fit, actual + v1, actual + nv)
        row = {"ts": now, "team": p["team"], "st": st, "f": round(f, 3), "tag": g["tag"], "margin": margin,
               "sid": p["sid"], "name": p["name"], "pos": p["pos"], "proj": round(p["proj"], 2), "actual": round(actual, 2),
               "rem_fit": round(rem, 2), "live_fit": round(live[0], 2), "live_v1": round(live[1], 2), "live_naive": round(live[2], 2)}
        rows.append(row)
        if writer: writer.writerow(row)
    if verbose:
        for t in teams:
            g = states[t]
            print(f"  {t}: {g['st']} {g['tag']} f={g['f']:.2f} score {g.get('pts')}-{g.get('oppPts')}")
        for r in sorted(rows, key=lambda r: -r["proj"])[:12]:
            print(f"    {r['name']:<22}{r['pos']:<4} proj {r['proj']:5.1f}  scored {r['actual']:5.1f}  live fit {r['live_fit']:5.1f} | v1 {r['live_v1']:5.1f} | naive {r['live_naive']:5.1f}")
    return states, rows


# ---------------- grading ----------------
def grade(paths):
    paths = paths if isinstance(paths, list) else [paths]
    rows = []
    for pth in paths:
        rows += list(csv.DictReader(open(pth, encoding="utf-8")))
    if not rows: print("empty log"); return None
    out_path = (paths[0] if len(paths) == 1 else os.path.join(os.path.dirname(paths[0]), "live_track_COMBINED.csv")).replace(".csv", "_summary.json")
    finals = {}
    for r in rows:
        if r["st"] == "post": finals[r["sid"]] = float(r["actual"])
    if not finals:
        for r in rows: finals[r["sid"]] = float(r["actual"])
        print("NOTE: no FINAL rows in the log — grading against the latest scored value")
    live = [r for r in rows if r["st"] == "in" and r["sid"] in finals]
    if not live: print("no in-game snapshots to grade"); return None
    bins = [(0.0, 0.25, "Q1"), (0.25, 0.5, "Q2"), (0.5, 0.75, "Q3"), (0.75, 1.01, "Q4")]
    print(f"\n=== LIVE GRADE {', '.join(os.path.basename(p) for p in paths)}: {len(live)} snapshots, {len(finals)} players ===")
    print("|live - final|   fitted | v1 | naive   (n)")
    summary = {"files": [os.path.basename(p) for p in paths], "bins": {}, "players": {}}
    tot = [0.0, 0.0, 0.0]; n = 0
    for lo, hi, lbl in bins:
        sel = [r for r in live if lo <= float(r["f"]) < hi]
        if not sel: continue
        e = [sum(abs(float(r[k]) - finals[r["sid"]]) for r in sel) / len(sel) for k in ("live_fit", "live_v1", "live_naive")]
        for i in range(3): tot[i] += e[i] * len(sel)
        n += len(sel)
        summary["bins"][lbl] = {"fit": round(e[0], 3), "v1": round(e[1], 3), "naive": round(e[2], 3), "n": len(sel)}
        print(f"  {lbl}   {e[0]:.2f} | {e[1]:.2f} | {e[2]:.2f}   ({len(sel)})")
    if n:
        print(f"  ALL  {tot[0]/n:.3f} | {tot[1]/n:.3f} | {tot[2]/n:.3f}   ({n})")
        summary["all"] = {"fit": round(tot[0] / n, 3), "v1": round(tot[1] / n, 3), "naive": round(tot[2] / n, 3), "n": n}
    by = {}
    for r in live: by.setdefault(r["sid"], []).append(r)
    wins = [0, 0, 0]
    print("\nper player (mean |live - final| over the game):  proj -> final   fitted | v1 | naive")
    for sid, rs in sorted(by.items(), key=lambda kv: -float(kv[1][0]["proj"])):
        e = [sum(abs(float(r[k]) - finals[sid]) for r in rs) / len(rs) for k in ("live_fit", "live_v1", "live_naive")]
        wins[e.index(min(e))] += 1
        summary["players"][rs[0]["name"]] = {"pos": rs[0]["pos"], "proj": float(rs[0]["proj"]), "final": finals[sid], "fit": round(e[0], 2), "v1": round(e[1], 2), "naive": round(e[2], 2)}
        print(f"  {rs[0]['name']:<22}{rs[0]['pos']:<4} {float(rs[0]['proj']):5.1f} -> {finals[sid]:5.1f}   {e[0]:.2f} | {e[1]:.2f} | {e[2]:.2f}")
    print(f"closest model per player: fitted {wins[0]}  v1 {wins[1]}  naive {wins[2]}")
    summary["wins"] = {"fit": wins[0], "v1": wins[1], "naive": wins[2]}
    json.dump(summary, open(out_path, "w"), indent=1)
    print("wrote", out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--window", type=float, default=WINDOW_H)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--grade", nargs="+")
    ap.add_argument("--logs-dir", default=os.path.join(HERE, "logs"))
    a = ap.parse_args()
    if a.grade:
        files = sorted(sum((glob.glob(g) for g in a.grade), []))
        grade(files); return
    logs_dir = a.logs_dir
    os.makedirs(logs_dir, exist_ok=True)
    if a.all:
        teams, games = select_games(a.window, logs_dir)
        if not teams:
            print(f"no game in progress or kicking off within {a.window:g}h — nothing to track"); return
        print("games:", ", ".join(games))
        git_publish(logs_dir, f"claims: {', '.join(games)}", ["live_claims.json"])
    else:
        teams = [t.strip().upper() for t in a.teams.split(",") if t.strip()]
        if not teams: ap.error("--teams or --all required")
    state = get_json(SLEEPER_STATE)
    season = state.get("season") or dt.date.today().year
    sim_proj = get_json(SIM_PROJ_URL + "?t=" + str(int(time.time())))
    week, players = tracked_players(teams, sim_proj)
    model = load_model(sim_proj)
    print(f"tracking {len(players)} players on {teams}, season {season} week {week}")
    if a.once:
        tick(season, week, teams, players, model, verbose=True); return
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M")
    label = "_".join(teams) if len(teams) <= 4 else f"{len(teams)//2}games_{stamp}"
    out = os.path.join(logs_dir, f"live_track_{season}_w{week}_{label}.csv")
    new = not os.path.exists(out)
    fh = open(out, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(fh, fieldnames=FIELDS)
    if new: w.writeheader()
    t0 = time.time(); ticks = 0
    while time.time() - t0 < MAX_HOURS * 3600:
        try:
            states, _ = tick(season, week, teams, players, model, writer=w, verbose=(ticks % 10 == 0))
            fh.flush(); ticks += 1
            if all(states[t]["st"] == "post" for t in teams):
                print("all tracked games FINAL"); break
            if all(states[t]["st"] == "pre" for t in teams):
                time.sleep(120); continue
        except Exception as e:
            print("tick failed:", e)
        time.sleep(POLL)
    fh.close()
    summ = grade(out)
    git_publish(logs_dir, f"live track {season} w{week} {label}", [os.path.basename(out)] + ([os.path.basename(summ)] if summ else []))


if __name__ == "__main__":
    main()
