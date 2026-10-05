#!/usr/bin/env python3
"""
OUR OWN FUTURE TEAM TOTALS (Jack 2026-10-02: "those totals aren't necessarily true anymore as the books took them
down and will be changed when that week comes up - we need to make our own future team totals now based on data
including each new week's team totals and take into account current and future injuries").

Replaces build_future_totals.py as the writer of data/sim_future_totals.js (same file, same shape, so the engine's
buildSchedule and the site overlay need no change). A future game no longer starts from the book's May / July
look-ahead number for that game. It is built from our own team ratings:

  implied(team, game) = league mean + OFFENSE[team] + DEFENSE[opponent] + home edge            (the rating)
  rating = PRESEASON rating (fit once on the frozen preseason lines: what the market thought of each team)
         + SHIFT from every line the book has posted in season - played weeks, the current week and any
           later week already re-posted ("each new week's team totals"), per quarterback, weather taken out,
           ridge 2, half-life 2 weeks, cap 4 a side                                  [backtest_future_totals*.py]
         + RESULTS: 0.10 / 0.15 / 0.20 (by games played) x the recency-weighted scoring surprise (points - implied) of the offense and of the
           opposing defense                                                             [backtest_own_totals.py]
  QUARTERBACK for each future week = everyone who can start x the probability he does (dump_team_state.js:
           depth chart x availability from the injury layer - out-windows, news timelines, the availability
           curve), not one projected name. A quarterback who starts only because the man ahead of him is out and
           who has no lines of his own yet takes NEW_QB (-3.0) on the offense.          [backtest_own_totals.py]

backtest_own_totals.py, 2019-25 closing lines, live timing (next week already lined): the rating + quarterback +
weather form misses the eventual closing line by 2.22 (-19% vs a rating that is never updated); + results -3.9%
(7/7 seasons); + new-quarterback dock -10.2% (7/7); both -13% (7/7). SKILL-PLAYER injuries were tested and
REJECTED: knowing exactly when the players out today come back added 0.0% (0/7) - the lines posted while they are
out already carry it and the per-player effect is too small to separate; only the quarterback moves a team total.

A line the book has posted or moved in the last FRESH_DAYS is kept as the book's and is used as an observation.
Writes data/sim_future_totals.js. `--test` = 2026 walk-forward (own rating vs the stale game line as the base).
"""
import datetime, json, os, re, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import build_future_totals as B
import backtest_future_totals as F
OUT = B.OUT
LAM, HL, CAP, LAM_Q, FRESH_DAYS = B.LAM, B.HL, B.CAP, B.LAM_QB, B.FRESH_DAYS
RES_PSEUDO, NEW_QB = 1.0, -3.0
def res_weight(games_played):
    """weight on the scoring surprise: the leave-one-season-out pick at each checkpoint (.10 after 2 games, .15 after 4, .20 from 8 on)"""
    return 0.10 if games_played < 3 else (0.15 if games_played < 8 else 0.20)
RES_W = 0.15
def ridge_for(weeks_played):
    """pull toward the PRESEASON rating by point in the season (backtest_own_totals_prior.py, 2019-25, picked
    leave-one-season-out at every checkpoint): 2.0 is best through week 4 - MORE preseason weight (4 / 8 / 16) is
    worse at every checkpoint, week 2 included - and from week 6 on the preseason rating should count for LESS
    (0.5: -1.3% at week 6, -3.8% at week 12 vs a flat 2.0). The schedule vs flat 2.0: -0.74%, 6/7 seasons."""
    return 2.0 if weeks_played <= 4 else (1.0 if weeks_played == 5 else 0.5)
PRE_DATE = "2026-08-26"

def preseason_ratings(pre):
    """league mean + O[team] + D[opp] + home, fit on the frozen preseason lines -> fn(team, opp, home) and the fit"""
    rows = []
    for g in pre.values():
        h, a = B.imp(g)
        rows.append((g["home"], g["away"], 1.0, h)); rows.append((g["away"], g["home"], 0.0, a))
    d = pd.DataFrame(rows, columns=["team", "opp", "home", "imp"]); teams = sorted(set(d.team))
    m = F.ridge_od(d, d.imp.values, np.ones(len(d)), teams, 0.05)
    resid = d.imp.values - F.predict(m, d)
    mu, hfa = float(m["rest"][0]), float(m["rest"][1])
    fn = lambda t, o, home: mu + m["O"][t] + m["D"][o] + hfa * (1.0 if home else 0.0)
    return fn, {"mu": mu, "home": hfa, "O": m["O"], "D": m["D"], "resid_sd": float(resid.std())}

def results_2026():
    """{(team, wk): (points scored, points allowed)} for finished games, from the 2026 play-by-play"""
    out = {}
    try:
        d = pd.read_csv(B.PBP, low_memory=False, usecols=["game_id", "season_type", "week", "home_team", "away_team", "home_score", "away_score"])
    except Exception as e:
        print(f"  WARN no 2026 play-by-play ({e}) - no results term"); return out
    g = d[d.season_type == "REG"].dropna(subset=["home_team", "home_score"]).groupby("game_id").first()
    for _, r in g.iterrows():
        out[(B.tm(r.home_team), int(r.week))] = (float(r.home_score), float(r.away_score))
        out[(B.tm(r.away_team), int(r.week))] = (float(r.away_score), float(r.home_score))
    return out

def engine_qb_mix(cur_wk):
    """{team: {wk: [(qb key, P, rank, name)]}} from dump_team_state.js, or None"""
    try:
        import shutil
        node = shutil.which("node") or "E:/node/node.exe"
        r = subprocess.run([node, os.path.join(HERE, "dump_team_state.js"), str(cur_wk)], capture_output=True, text=True, encoding="utf-8", cwd=HERE, timeout=300)
        d = json.loads(r.stdout.strip().splitlines()[-1])
        return {B.tm(t): {int(w): [(B.qkey(q[0]), float(q[1]), int(q[2]), q[0]) for q in v] for w, v in x.items()} for t, x in d.items()}
    except Exception as e:
        print(f"  WARN quarterback state helper failed ({e}) - totals are built without quarterback context"); return None

def model(cur, pre, now, cur_wk, kos, qb_played, wx_played, wx_fc, mix, results, base="own", use_results=True, use_newqb=True, obs_max_wk=None, fresh_obs=True):
    """returns predict(key) -> (home implied, away implied) for any game, plus the parts for the payload"""
    teams = sorted(set(g["home"] for g in cur.values()) | set(g["away"] for g in cur.values()))
    rate, R = preseason_ratings(pre)
    def base_imp(k, g):
        own = (rate(g["home"], g["away"], True), rate(g["away"], g["home"], False))
        if base == "own" or k not in pre: return own
        ln = B.imp(pre[k])
        return ln if base == "line" else ((own[0] + ln[0]) / 2, (own[1] + ln[1]) / 2)
    opener = {}
    for (t, w) in sorted(qb_played, key=lambda x: x[1]): opener.setdefault(t, qb_played[(t, w)])
    def top_qb(t, wk):
        m = (mix or {}).get(t, {}).get(wk)
        return max(m, key=lambda q: q[1])[0] if m else None
    regular = {}
    for t in teams:
        fut = [top_qb(t, w) for w in range(cur_wk + 1, 19) if top_qb(t, w)]
        regular[t] = max(set(fut), key=fut.count) if fut else (top_qb(t, cur_wk) or opener.get(t))
    def qb_obs(t, wk):
        return qb_played.get((t, wk)) or top_qb(t, wk) or regular.get(t) or "x"
    today = now.date(); obs = []; notes = {}
    for k, g in cur.items():
        if k not in pre or g["asOf"] <= PRE_DATE: continue
        if obs_max_wk is not None and g["wk"] > obs_max_wk: continue
        if g["wk"] > cur_wk and not (fresh_obs and (today - datetime.date.fromisoformat(g["asOf"])).days <= FRESH_DAYS): continue
        (h1, a1), (h0, a0) = B.imp(g), base_imp(k, g)
        wx = wx_played.get((g["home"], g["wk"]), wx_fc.get((g["home"], g["wk"]), 0.0))
        for t, o, d in ((g["home"], g["away"], h1 - h0), (g["away"], g["home"], a1 - a0)):
            q = qb_obs(t, g["wk"])
            obs.append((g["wk"], t + "|" + q, o, d - wx))
            if regular.get(t) and q != regular[t]: notes.setdefault(t, []).append(f"wk {g['wk']} line was for {q}")
            if wx: notes.setdefault(t, []).append(f"wk {g['wk']} weather {wx:+.1f} taken out")
    ref_wk = max([o[0] for o in obs], default=cur_wk)
    played_wks = max([w for (_, w) in results], default=0) if results else 0
    if obs_max_wk is not None: played_wks = min(played_wks, obs_max_wk)
    lam0 = B.LAM; B.LAM = ridge_for(played_wks)          # B.fit reads the team / defense ridge from its module
    try: O, D, T, Q = B.fit(obs, teams, ref_wk)
    finally: B.LAM = lam0
    # results: recency-weighted scoring surprise of each offense and each defense, finished games only
    so, sd = {t: 0.0 for t in teams}, {t: 0.0 for t in teams}
    if use_results and results:
        last = max(w for (_, w) in results)
        num_o, den_o, num_d, den_d = {}, {}, {}, {}
        for k, g in cur.items():
            for t, o, li in ((g["home"], g["away"], B.imp(g)[0]), (g["away"], g["home"], B.imp(g)[1])):
                r = results.get((t, g["wk"]))
                if r is None or (obs_max_wk is not None and g["wk"] > obs_max_wk): continue
                w = 0.5 ** ((last - g["wk"]) / HL); s = r[0] - li
                num_o[t] = num_o.get(t, 0) + w * s; den_o[t] = den_o.get(t, 0) + w
                num_d[o] = num_d.get(o, 0) + w * s; den_d[o] = den_d.get(o, 0) + w
        rw = res_weight(last) / RES_W          # so / sd are stored already scaled to the RES_W unit the payload reports
        so = {t: rw * num_o.get(t, 0) / (den_o.get(t, 0) + RES_PSEUDO) for t in teams}
        sd = {t: rw * num_d.get(t, 0) / (den_d.get(t, 0) + RES_PSEUDO) for t in teams}
    lined = set(Q)
    def offense(t, wk):
        """expected offense shift over the quarterbacks who can start that week"""
        m = (mix or {}).get(t, {}).get(wk)
        if not m:
            q = regular.get(t) or "x"; return O(t, q), [(q, 1.0, 0)]
        tot = 0.0; left = 1.0
        for q, p, rank, _ in m:
            new = use_newqb and rank > 0 and (t + "|" + q) not in lined and q != opener.get(t)
            tot += p * (O(t, q) + (NEW_QB if new else 0.0)); left -= p
        if left > 0.005: tot += left * (O(t, "?") + (NEW_QB if use_newqb else 0.0))
        return tot, [(q, p, rank) for q, p, rank, _ in m]
    def predict(k, g):
        h0, a0 = base_imp(k, g)
        oh, _ = offense(g["home"], g["wk"]); oa, _ = offense(g["away"], g["wk"])
        h = h0 + oh + D[g["away"]] + RES_W * (so[g["home"]] + sd[g["away"]])
        a = a0 + oa + D[g["home"]] + RES_W * (so[g["away"]] + sd[g["home"]])
        return max(7.0, h), max(7.0, a)
    return predict, dict(teams=teams, R=R, O=O, D=D, T=T, Q=Q, so=so, sd=sd, regular=regular, notes=notes, nobs=len(obs) // 2, offense=offense, opener=opener)

def _context(now):
    cur = B.parse(os.path.join(HERE, "data", "betting_lines_2026.js"))
    pre = B.parse(os.path.join(HERE, "data", "preseason_lines_2026_frozen.js"))
    kick = json.load(open(os.path.join(HERE, "data", "kickoffs_2026.json"), encoding="utf-8"))
    def ko(g):
        w = kick.get(str(g["wk"])) or {}
        s = next((v for k, v in w.items() if B.tm(k) in (g["home"], g["away"])), None)
        return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=datetime.timezone.utc) if s else None
    kos = {k: ko(g) for k, g in cur.items()}
    weeks = sorted(set(g["wk"] for g in cur.values()))
    cur_wk = next((w for w in weeks if any(kos[k] and kos[k] > now for k, g in cur.items() if g["wk"] == w)), weeks[-1] + 1)
    qb_played, wx_played = B.played_context()
    wx_fc = {}
    try:
        raw = open(os.path.join(HERE, "data", "sim_weather.js"), encoding="utf-8").read()
        for h, byw in json.loads(raw[raw.index("{", raw.index("=")):raw.rindex("}") + 1]).items():
            for w, v in byw.items():
                wind = (v or {}).get("wind") or 0
                wx_fc[(B.tm(h), int(w))] = B.WX_WIND15 if wind >= 15 else (B.WX_MILD if wind >= 10 else 0.0)
    except Exception:
        pass
    return cur, pre, kos, cur_wk, qb_played, wx_played, wx_fc

def build(now=None, quiet=False):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    cur, pre, kos, cur_wk, qb_played, wx_played, wx_fc = _context(now)
    mix = engine_qb_mix(cur_wk); results = results_2026()
    predict, M = model(cur, pre, now, cur_wk, kos, qb_played, wx_played, wx_fc, mix, results)
    games = {}; kept = 0; today = now.date()
    for k, g in cur.items():
        if g["wk"] <= cur_wk: continue
        if (today - datetime.date.fromisoformat(g["asOf"])).days <= FRESH_DAYS: kept += 1; continue      # the book's own fresh line
        h, a = predict(k, g)
        games[k] = {"total": round(h + a, 2), "spread": round(a - h, 2), "book": [g["total"], g["spread"], g["asOf"]]}
    teams = M["teams"]; R = M["R"]
    shift = {t: [round(M["O"](t, M["regular"].get(t) or "x") + RES_W * M["so"][t], 2), round(float(M["D"][t]) + RES_W * M["sd"][t], 2)] for t in teams}
    rating = {t: [round(R["mu"] + R["O"][t] + shift[t][0], 2), round(R["mu"] + R["D"][t] + shift[t][1], 2)] for t in teams}
    qbw = {}
    if mix:
        for t in teams:
            for w, m in sorted(mix.get(t, {}).items()):
                if w > cur_wk and (len(m) > 1 or (m and m[0][1] < 0.995)): qbw.setdefault(t, {})[str(w)] = [[n, p] for _, p, _, n in m]
    payload = {"asOf": now.strftime("%Y-%m-%dT%H:%MZ"), "currentWeek": cur_wk, "model": "own-ratings", "lam": LAM, "halfLife": HL, "cap": CAP, "freshDays": FRESH_DAYS,
               "resW": RES_W, "newQb": NEW_QB, "observed": M["nobs"], "keptFresh": kept, "qbContext": bool(mix),
               "mean": round(R["mu"], 2), "home": round(R["home"], 2), "shift": shift, "rating": rating,
               "results": {t: [round(M["so"][t], 2), round(M["sd"][t], 2)] for t in teams},
               "qb": ({t: M["regular"].get(t) for t in teams} if mix else None), "qbWeeks": qbw,
               "byQb": {e: round(M["O"](e.split("|")[0], e.split("|")[1]), 2) for e in M["Q"]}, "notes": {t: sorted(set(v)) for t, v in M["notes"].items()}, "games": games}
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// AUTO-GENERATED by build_own_totals.py - OUR OWN future game totals (the book's far-out look-ahead lines are not used)\n")
        f.write("// rating[team] = [points his offense is rated to score vs an average defense on a neutral field, points his defense allows];\n")
        f.write("// shift[team] = [offense, defense] movement vs the preseason rating (lines posted this season + results), with the quarterback he plays most;\n")
        f.write("// qbWeeks[team][wk] = [[quarterback, P(starts)]] where it is not one certain starter; byQb['TEAM|qb'] = offense shift with that quarterback;\n")
        f.write("// games[key] = {total, spread (home), book: [the book's last posted total, spread, date]}. Kill: window.SIM_FUTURE_TOTALS_OFF = true.\n")
        f.write("window.SIM_FUTURE_TOTALS = " + json.dumps(payload, separators=(",", ":")) + ";\n")
    if not quiet:
        print(f"own team totals: current week {cur_wk}, {M['nobs']} in-season lines observed, {len(results)//2} results, {len(games)} future games built from our ratings, "
              f"{kept} fresh book lines kept, quarterback context {'ON' if mix else 'OFF'} -> {os.path.basename(OUT)}")
    return payload, cur

def test():
    """2026 walk-forward: standing at each week T with the lines through T and the results before T, how close
    are the totals for the later weeks the book HAS since posted - own rating vs the stale game line as the base."""
    now = datetime.datetime.now(datetime.timezone.utc)
    cur, pre, kos, cur_wk, qb_played, wx_played, wx_fc = _context(now)
    results = results_2026(); rate, R = preseason_ratings(pre)
    print(f"preseason rating fit on {len(pre)} frozen lines: league mean {R['mu']:.2f}, home edge {R['home']:+.2f}, "
          f"game-specific part the rating does not explain: sd {R['resid_sd']:.2f} points per team")
    posted = {k: g for k, g in cur.items() if g["asOf"] > PRE_DATE and k in pre and (g["wk"] <= cur_wk or (now.date() - datetime.date.fromisoformat(g["asOf"])).days <= FRESH_DAYS)}
    rows = []
    for T in range(1, cur_wk + 1):
        res_T = {k: v for k, v in results.items() if k[1] < T}
        qbp = {k: v for k, v in qb_played.items() if k[1] <= T}
        # the quarterback of each graded game: who actually started it when known (same convention as the backtests)
        mixT = {}
        for (t, w), q in qb_played.items(): mixT.setdefault(t, {})[w] = [(q, 1.0, 0, q)]
        for label, kw in (("never updated: stale game line", dict(base="line", none=True)), ("never updated: preseason rating", dict(base="own", none=True)),
                          ("stale game line + shift (what ran until today)", dict(base="line", use_results=False, use_newqb=False)),
                          ("own rating + shift", dict(base="own", use_results=False, use_newqb=False)),
                          ("own rating + shift + results", dict(base="own", use_results=True, use_newqb=False)),
                          ("half own / half stale line + shift + results", dict(base="mix", use_results=True, use_newqb=False))):
            none = kw.pop("none", False)
            predict, M = model(cur, pre, now, T, kos, qbp, wx_played, wx_fc, mixT, res_T, obs_max_wk=(0 if none else T), fresh_obs=False, **kw)
            for k, g in posted.items():
                if g["wk"] <= T: continue
                h, a = predict(k, g); (h1, a1) = B.imp(g)
                rows.append((label, T, g["wk"], abs(h - h1))); rows.append((label, T, g["wk"], abs(a - a1)))
    d = pd.DataFrame(rows, columns=["m", "T", "wk", "err"])
    print(f"\n2026 walk-forward, graded on the lines the book has since posted for weeks 2-{max(d.wk)} ({len(d)//d.m.nunique()} team-games per row; small sample):")
    for m in d.m.unique():
        x = d[d.m == m]
        print(f"  {m:50s} miss {x.err.mean():.2f}   " + "  ".join(f"from wk {T}: {x[x['T']==T].err.mean():.2f}" for T in sorted(x['T'].unique())))

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=None, help="repo root: also write data/future_totals_2026.js there")
    ap.add_argument("--test", action="store_true"); ap.add_argument("--quiet", action="store_true"); ap.add_argument("--dry", action="store_true", help="build to a scratch file, leave the live one")
    a = ap.parse_args()
    if a.test: test(); sys.exit(0)
    if a.dry: OUT = os.path.join(HERE, "data", "_own_totals_dry.js")
    p, cur = build(quiet=a.quiet)
    if a.site and not a.dry: B.write_site(p, a.site)
    if a.quiet: sys.exit(0)
    r = sorted(p["rating"].items(), key=lambda kv: -kv[1][0])
    print("offense rating (points vs an average defense, neutral field):  " + "  ".join(f"{t} {v[0]:.1f}" for t, v in r[:6]) + "  ...  " + "  ".join(f"{t} {v[0]:.1f}" for t, v in r[-6:]))
    tot = {}
    for k, g in p["games"].items():
        c = cur[k]; h0, a0 = (g["book"][0] - g["book"][1]) / 2, (g["book"][0] + g["book"][1]) / 2
        h1, a1 = (g["total"] - g["spread"]) / 2, (g["total"] + g["spread"]) / 2
        for t, b, n in ((c["home"], h0, h1), (c["away"], a0, a1)): tot.setdefault(t, []).append((b, n))
    rr = sorted(((np.mean([n - b for b, n in v]), t, np.mean([b for b, n in v]), np.mean([n for b, n in v])) for t, v in tot.items()))
    print("average implied total over the future games, the book's old line -> ours:")
    for dd, t, b, n in rr[:8] + rr[-8:]: print(f"   {t:4s} {b:5.1f} -> {n:5.1f}  ({dd:+.1f})")
