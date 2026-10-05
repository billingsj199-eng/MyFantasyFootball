#!/usr/bin/env python3
"""
FUTURE TEAM TOTALS from this season's lines (Jack 2026-09-29, backtest_future_totals.py).

The books' lines for far-out weeks in data/betting_lines_2026.js are the May / July look-ahead
numbers; they do not move until a game is a week or so away. For every game already lined
in-season:   delta = implied total now - implied total in the PRESEASON file (frozen copy of the
2026-08-26 commit, data/preseason_lines_2026_frozen.js), and
             delta(team in game) = dOff[team] + dDef[opponent]     ridge LAM, recency half-life HL weeks
then every FUTURE game whose line is stale becomes  line implied + dOff[team] + dDef[opponent].

Backtest: 2019-25 (proxy preseason view) the miss vs the eventual closing line drops 13% standing
after week 4 (6/7 seasons), 23% after week 8 (7/7), and points-scored MSE -2.9% / -4.8%; on the real
2026 preseason lines -7% to -12% walking forward through weeks 1-4.

Rules
  * a future line the book moved in the last FRESH_DAYS is kept as it is
  * an older line only takes the shift measured from games that kicked off AFTER the line's own date
    (a preseason line takes all of it), so nothing is counted twice
  * a team's shift is capped at CAP points per side
  * QUARTERBACK CONTEXT (backtest_future_totals_context.py): the offense shift is measured per team x quarterback.
    A line posted for a backup says nothing about the weeks the starter is back, and the reverse. Played games = who
    threw the team's first pass (2026 play-by-play); the current and future weeks = the engine's projected starter
    (dump_qb_state.js: injury layer, out overrides, quarterback-room windows). Offense shift = a TEAM shift shared by
    all of his quarterbacks + a deviation per quarterback (ridge LAM_QB), so a quarterback with no lines of his own
    yet takes the team shift. backtest_future_totals_live_form.py (this exact form, 2019-25): miss vs the closing
    line -16.8% vs no shift (7/7 seasons) and -3.0% vs the shift without quarterback context (7/7); starter back
    after backup weeks, standing after week 4: -10.9% vs no context (6/7).
  * WEATHER: a line for a windy / wet game has the usual weather discount taken back out before the shift is
    measured (absorbing weather was neutral in the backtest; dropping those games was slightly worse)
Writes data/sim_future_totals.js -> window.SIM_FUTURE_TOTALS (engine buildSchedule; kill switch
window.SIM_FUTURE_TOTALS_OFF = true). Called at the end of refresh_data.py.
"""
import os, re, json, datetime, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "sim_future_totals.js")
LAM, HL, CAP, FRESH_DAYS = 2.0, 2.0, 4.0, 10
LAM_QB = 0.5     # ridge on a quarterback's deviation from his team's shift (backtest_future_totals_live_form.py)
# weather a line already priced in (2019-25: closing line minus the preseason view ran -0.86 in wind 15+ and
# -0.67 in wind 10-15 / rain / snow, vs -0.17 in clean games) - taken back out before the shift is measured
WX_WIND15, WX_MILD = -0.7, -0.5
PBP = r"E:\MyFantasyFootball\pbp_cache\play_by_play_2026.csv.gz"
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
def tm(t): return ALIAS.get(t, t)
RX = re.compile(r"'(W(\d+)_([A-Z]+)_([A-Z]+))':\s*\{\s*total:\s*([\d.]+),\s*spread:\s*([+-]?[\d.]+),\s*asOf:\s*'([\d-]+)'")

def parse(path):
    out = {}
    for key, w, a, h, tot, sp, d in RX.findall(open(path, encoding="utf-8").read()):
        out[key] = {"wk": int(w), "away": tm(a), "home": tm(h), "total": float(tot), "spread": float(sp), "asOf": d}
    return out
def imp(g): return (g["total"] - g["spread"]) / 2, (g["total"] + g["spread"]) / 2     # home, away
def qkey(name):
    """'Caleb Williams' / 'C.Williams' / 'Michael Penix Jr.' -> 'c.williams' / 'm.penix'"""
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", str(name).lower()).replace("'", "").strip()
    if "." in s and " " not in s.split(".")[0]: first, last = s.split(".", 1)
    else: parts = s.split(); first, last = parts[0], parts[-1]
    return first[:1] + "." + last.strip().split()[-1]

def played_context():
    """from the 2026 play-by-play: {(team, wk): starter key} (who threw the team's first pass) and {(home, wk): weather offset}"""
    import pandas as pd
    qb, wx = {}, {}
    try:
        d = pd.read_csv(PBP, low_memory=False, usecols=["game_id", "play_id", "season_type", "week", "posteam", "home_team", "roof", "wind", "weather", "passer_player_name", "pass_attempt"])
    except Exception as e:
        print(f"  WARN no 2026 play-by-play ({e}) - played games get no quarterback / weather context"); return qb, wx
    d = d[d.season_type == "REG"]
    p = d[(d.pass_attempt == 1) & d.passer_player_name.notna()].sort_values(["game_id", "play_id"]).groupby(["posteam", "week"]).first()
    for (t, w), r in p.iterrows(): qb[(tm(t), int(w))] = qkey(r.passer_player_name)
    g = d.dropna(subset=["home_team"]).groupby("game_id").first()
    for _, r in g.iterrows():
        if str(r.roof) in ("dome", "closed"): off = 0.0
        else:
            wind = float(r.wind) if r.wind == r.wind else 0.0
            wet = bool(re.search(r"rain|snow|shower|sleet|storm", str(r.weather), re.I))
            off = WX_WIND15 if wind >= 15 else (WX_MILD if (wind >= 10 or wet) else 0.0)
        wx[(tm(r.home_team), int(r.week))] = off
    return qb, wx

def engine_qbs(cur_wk):
    """({team: {wk: qb key}}, {team: {wk: name}}) - the engine's projected starter from the current week on"""
    import subprocess
    try:
        import shutil
        node = shutil.which("node") or "E:/node/node.exe"     # Task Scheduler runs without node on PATH
        r = subprocess.run([node, os.path.join(HERE, "dump_qb_state.js"), str(cur_wk)], capture_output=True, text=True, encoding="utf-8", cwd=HERE, timeout=240)
        d = json.loads(r.stdout.strip().splitlines()[-1])
        return ({tm(t): {int(w): qkey(v[0]) for w, v in x["weeks"].items()} for t, x in d.items()},
                {tm(t): {int(w): v[0] for w, v in x["weeks"].items()} for t, x in d.items()})
    except Exception as e:
        print(f"  WARN quarterback state helper failed ({e}) - shifts are fit without quarterback context"); return None, None

def fit(obs, teams, now_wk):
    """obs: [(wk, 'TEAM|qb', defense team, delta)] -> (offense fn(team, qb), {team: dDef}, {team: T}, {'TEAM|qb': dev}).
    offense shift = TEAM shift (shared by all of his quarterbacks) + a deviation per quarterback (ridge LAM_QB)."""
    ents = sorted(set(o[1] for o in obs)); ne = len(ents); n = len(teams)
    ei = {e: i for i, e in enumerate(ents)}; ix = {t: i for i, t in enumerate(teams)}
    if not obs: return (lambda t, q: 0.0), {t: 0.0 for t in teams}, {t: 0.0 for t in teams}, {}
    X = np.zeros((len(obs), n + ne + n)); y = np.zeros(len(obs)); w = np.zeros(len(obs))
    for i, (wk, e, o, d) in enumerate(obs):
        X[i, ix[e.split("|")[0]]] = 1; X[i, n + ei[e]] = 1; X[i, n + ne + ix[o]] = 1; y[i] = d; w[i] = 0.5 ** ((now_wk - wk) / HL)
    pen = np.r_[np.full(n, LAM), np.full(ne, LAM_QB), np.full(n, LAM)]
    A = X * np.sqrt(w)[:, None]; b = y * np.sqrt(w)
    beta = np.linalg.solve(A.T @ A + np.diag(pen), A.T @ b)
    T = dict(zip(teams, beta[:n])); Q = dict(zip(ents, beta[n:n + ne])); D = {t: float(np.clip(v, -CAP, CAP)) for t, v in zip(teams, beta[n + ne:])}
    off = lambda t, q: float(np.clip(T.get(t, 0.0) + Q.get(t + "|" + q, 0.0), -CAP, CAP))
    return off, D, T, Q

def build(now=None, quiet=False):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    cur = parse(os.path.join(HERE, "data", "betting_lines_2026.js"))
    pre = parse(os.path.join(HERE, "data", "preseason_lines_2026_frozen.js"))
    raw_keys = {}
    for key, w, a, h, *_ in RX.findall(open(os.path.join(HERE, "data", "betting_lines_2026.js"), encoding="utf-8").read()): raw_keys[key] = key
    kick = json.load(open(os.path.join(HERE, "data", "kickoffs_2026.json"), encoding="utf-8"))
    def ko(g):
        w = kick.get(str(g["wk"])) or {}
        s = next((v for k, v in w.items() if tm(k) in (g["home"], g["away"])), None)
        return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=datetime.timezone.utc) if s else None
    kos = {k: ko(g) for k, g in cur.items()}
    weeks = sorted(set(g["wk"] for g in cur.values()))
    cur_wk = next((w for w in weeks if any(kos[k] and kos[k] > now for k, g in cur.items() if g["wk"] == w)), weeks[-1] + 1)
    teams = sorted(set(g["home"] for g in cur.values()) | set(g["away"] for g in cur.values()))
    # ---- context: who the quarterback was / will be, and the weather the line priced in ----
    qb_played, wx_played = played_context()
    qb_proj, qb_names = engine_qbs(cur_wk)
    use_qb = qb_proj is not None
    wx_fc = {}
    try:
        raw = open(os.path.join(HERE, "data", "sim_weather.js"), encoding="utf-8").read()
        for h, byw in json.loads(raw[raw.index("{", raw.index("=")):raw.rindex("}") + 1]).items():
            for w, v in byw.items():
                wind = (v or {}).get("wind") or 0
                wx_fc[(tm(h), int(w))] = WX_WIND15 if wind >= 15 else (WX_MILD if wind >= 10 else 0.0)
    except Exception:
        pass
    regular = {}
    if use_qb:
        for t in teams:
            fut = [q for w, q in (qb_proj.get(t) or {}).items() if w > cur_wk] or list((qb_proj.get(t) or {}).values())
            regular[t] = max(set(fut), key=fut.count) if fut else None     # the quarterback he is projected to play most of the remaining games with
    def qb_of(t, wk):
        if not use_qb: return "x"
        if (t, wk) in qb_played: return qb_played[(t, wk)]
        return (qb_proj.get(t) or {}).get(wk) or regular.get(t) or "x"
    # observations: games of weeks <= the current week that the book has re-lined since the frozen preseason file
    obs_all = []; notes = {}
    for k, g in cur.items():
        if g["wk"] > cur_wk or k not in pre or g["asOf"] <= "2026-08-26": continue
        (h1, a1), (h0, a0) = imp(g), imp(pre[k])
        wx = wx_played.get((g["home"], g["wk"]), wx_fc.get((g["home"], g["wk"]), 0.0))
        for t, o, d in ((g["home"], g["away"], h1 - h0), (g["away"], g["home"], a1 - a0)):
            q = qb_of(t, g["wk"])
            obs_all.append((g["wk"], t + "|" + q, o, d - wx, kos[k]))
            if use_qb and regular.get(t) and q != regular[t]: notes.setdefault(t, []).append(f"wk {g['wk']} line was for {q}")
            if wx: notes.setdefault(t, []).append(f"wk {g['wk']} weather {wx:+.1f} taken out")
    fits = {}
    def shift_for(as_of):
        if as_of not in fits:
            cut = datetime.datetime.strptime(as_of, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc) + datetime.timedelta(days=1)
            fits[as_of] = fit([(w, e, o, d) for (w, e, o, d, kk) in obs_all if kk is None or kk > cut], teams, cur_wk)
        return fits[as_of]
    games = {}; kept = 0
    today = now.date()
    for k, g in cur.items():
        if g["wk"] <= cur_wk: continue
        age = (today - datetime.date.fromisoformat(g["asOf"])).days
        if age <= FRESH_DAYS: kept += 1; continue
        O, D, _, _ = shift_for(g["asOf"])
        h0, a0 = imp(g)
        qh, qa = qb_of(g["home"], g["wk"]), qb_of(g["away"], g["wk"])
        h1 = max(7.0, h0 + O(g["home"], qh) + D[g["away"]]); a1 = max(7.0, a0 + O(g["away"], qa) + D[g["home"]])
        games[k] = {"total": round(h1 + a1, 2), "spread": round(a1 - h1, 2), "book": [g["total"], g["spread"], g["asOf"]]}
    O, D, T, Q = shift_for("2026-08-26")
    shift = {}
    for t in teams:
        reg = (regular.get(t) if use_qb else "x") or "x"
        shift[t] = [round(O(t, reg), 2), round(float(D[t]), 2)]
    payload = {"asOf": now.strftime("%Y-%m-%dT%H:%MZ"), "currentWeek": cur_wk, "lam": LAM, "halfLife": HL, "cap": CAP, "freshDays": FRESH_DAYS,
               "observed": len(obs_all) // 2, "keptFresh": kept, "qbContext": bool(use_qb),
               "shift": shift, "qb": ({t: regular.get(t) for t in teams} if use_qb else None),
               "byQb": {e: round(O(e.split("|")[0], e.split("|")[1]), 2) for e in Q}, "notes": {t: sorted(set(v)) for t, v in notes.items()}, "games": games}
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// AUTO-GENERATED by build_future_totals.py - future game totals re-rated from this season's lines\n")
        f.write("// shift[team] = [points his OFFENSE moved with the quarterback he is projected to play with, points his DEFENSE allows moved]\n")
        f.write("// vs the preseason lines; byQb['TEAM|qb'] = the offense shift measured with that quarterback; notes = lines set aside or adjusted;\n")
        f.write("// games[key] = {total, spread (home), book: [book total, book spread, book line date]}. Kill: window.SIM_FUTURE_TOTALS_OFF = true.\n")
        f.write("window.SIM_FUTURE_TOTALS = " + json.dumps(payload, separators=(",", ":")) + ";\n")
    if not quiet:
        print(f"future totals: current week {cur_wk}, {len(obs_all)//2} in-season games observed, {len(games)} future games re-rated, {kept} fresh book lines kept, quarterback context {'ON' if use_qb else 'OFF'} -> {os.path.basename(OUT)}")
    return payload, cur

SITE_HEAD = """// AUTO-GENERATED by sim_lab (build_own_totals.py -> scripts/sim_proj_task.ps1) - do not hand-edit.
// OUR OWN FUTURE GAME TOTALS (2026-10-02). The book's lines for far-out weeks in betting_lines_2026.js are the
// May / July look-ahead numbers - they were taken down and get re-posted when each week comes up. Future games
// are built from our own team ratings instead: preseason rating + every line posted this season (per
// quarterback, weather taken out) + scoring results, with each future week's quarterback weighted by the chance
// he starts. games[key] = [total, home spread, book's last total, book's last spread]. The overlay below swaps
// our numbers into BETTING_2026.gameTotals (the book's stay on the row as bookTotal / bookSpread), so every
// reader - rest-of-season Team Total, SOS, team PPG - sees them. A line the book has posted since the build is
// left alone. Off switch: localStorage.setItem('mff_future_totals_off', '1').
"""
SITE_TAIL = """(function () {
  var F = window.FUTURE_TOTALS_2026, B = window.BETTING_2026, off = false;
  try { off = window.MFF_FUTURE_TOTALS_OFF === true || localStorage.getItem('mff_future_totals_off') === '1'; } catch (e) {}
  if (!F || !F.games || !B || !B.gameTotals || off) return;
  var n = 0;
  Object.keys(F.games).forEach(function (k) {
    var g = B.gameTotals[k], r = F.games[k];
    if (!g || g.reRated || g.total !== r[2] || g.spread !== r[3]) return;   // the book moved this line: keep the book's
    g.bookTotal = g.total; g.bookSpread = g.spread; g.total = r[0]; g.spread = r[1]; g.reRated = true; n++;
  });
  F.applied = n;
})();
"""
def write_site(payload, repo):
    """site twin: data/future_totals_2026.js, rewritten only when the numbers changed (keeps git quiet)."""
    body = {"currentWeek": payload["currentWeek"], "qbContext": payload["qbContext"], "shift": payload["shift"], "qb": payload["qb"],
            "notes": payload["notes"],
            "games": {k: [round(g["total"], 1), round(g["spread"], 1), g["book"][0], g["book"][1]] for k, g in sorted(payload["games"].items())}}
    path = os.path.join(repo, "data", "future_totals_2026.js")
    core = json.dumps(body, separators=(",", ":"))
    try:
        old = open(path, encoding="utf-8").read()
        if core in old:
            print(f"future totals site file unchanged ({len(body['games'])} games)"); return False
    except FileNotFoundError:
        pass
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(SITE_HEAD + "window.FUTURE_TOTALS_2026 = " + core[:-1] + ',"asOf":"' + payload["asOf"][:10] + '"};\n' + SITE_TAIL)
    print(f"future totals site file written: {len(body['games'])} games re-rated -> {path}")
    return True

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=None, help="repo root: also write data/future_totals_2026.js there")
    ap.add_argument("--no-rebuild", action="store_true", help="with --site: reuse data/sim_future_totals.js instead of rebuilding")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if a.site and a.no_rebuild and os.path.exists(OUT):
        raw = open(OUT, encoding="utf-8").read()
        write_site(json.loads(raw[raw.index("{", raw.index("window.")):raw.rindex("}") + 1]), a.site)
        sys.exit(0)
    p, cur = build()
    if a.site: write_site(p, a.site)
    if a.site or a.quiet: sys.exit(0)
    s = sorted(p["shift"].items(), key=lambda kv: kv[1][0])
    print("offense shift (points per game vs preseason lines):")
    print("   down: " + "  ".join(f"{t} {v[0]:+.1f}" for t, v in s[:8]))
    print("   up:   " + "  ".join(f"{t} {v[0]:+.1f}" for t, v in s[::-1][:8]))
    s = sorted(p["shift"].items(), key=lambda kv: kv[1][1])
    print("defense shift (points ALLOWED per game; negative = defense better than priced):")
    print("   better: " + "  ".join(f"{t} {v[1]:+.1f}" for t, v in s[:8]))
    print("   worse:  " + "  ".join(f"{t} {v[1]:+.1f}" for t, v in s[::-1][:8]))
    tot = {}
    for k, g in p["games"].items():
        c = cur[k]; h0, a0 = (c["total"] - c["spread"]) / 2, (c["total"] + c["spread"]) / 2
        h1, a1 = (g["total"] - g["spread"]) / 2, (g["total"] + g["spread"]) / 2
        for t, b, n in ((c["home"], h0, h1), (c["away"], a0, a1)):
            tot.setdefault(t, []).append((b, n))
    r = sorted(((np.mean([n - b for b, n in v]), t, np.mean([b for b, n in v]), np.mean([n for b, n in v])) for t, v in tot.items()))
    print("average implied total over the re-rated future games, book line -> re-rated:")
    for d, t, b, n in r[:8] + r[-8:]: print(f"   {t:4s} {b:5.1f} -> {n:5.1f}  ({d:+.1f})")
