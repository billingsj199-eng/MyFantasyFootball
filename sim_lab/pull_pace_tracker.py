#!/usr/bin/env python3
r"""
In-season team pace / play-calling tracker.

  python pull_pace_tracker.py             build data/pace_2026.js
  python pull_pace_tracker.py --validate  2019-25: does early-season tendency
                                          drift predict rest-of-season drift?

Per team, season-to-date 2026: plays/gm, neutral-script pass rate (wp 20-80%
Q1-Q3), PROE, no-huddle rate, 2+TE personnel rate — compared against a
BASELINE built per the coach research (research_coach_tendencies.py):
  * same HC as 2025      -> baseline = the team's own 2025 numbers
  * new HC w/ history    -> pace-identity metrics (plays, no-huddle, 2+TE)
                            from HIS most recent team-season (they travel);
                            pass-mix metrics (npr, PROE) stay with the roster
                            (2025 team values) — the QB decides those.
  * new HC, no history   -> league average for pace identity, 2025 roster
                            values for pass mix.
Coaches are read from the 2026 pbp itself once games exist; preseason the
tracker publishes baselines only (engine multipliers stay 1.0).

The engine (paceMult) turns drift into small clamped multipliers on the
Clay-based weekly means, trust ramping in over ~6 team games. The JS Weekly
mean does NOT get them — realized PPG already embeds the new pace.

Data: nflverse play_by_play_2026 (re-downloaded each run in-season) +
pbp_participation_2026 into E:\MyFantasyFootball\pbp_cache.
"""
import json, os, sys, time, urllib.request
import numpy as np
import pandas as pd

CACHE = r"E:\MyFantasyFootball\pbp_cache"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pace_2026.js")
RESEARCH = os.path.join(CACHE, "coach_research.json")
SEASON, PREV = 2026, 2025
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS"}
def tm(t): return ALIAS.get(t, t)

PACE_METRICS = ["plays", "huddle", "te2"]   # coach-owned: travel with him
MIX_METRICS = ["npr", "proe"]               # roster-owned: stay with the team

# 2026 OFFENSIVE PLAY-CALLERS (Jack 2026-07-31: pace identity belongs to the
# play-caller — OC, or HC if he calls plays — not the head coach per se, and a
# new caller is assumed to bring HIS historical trend with him).
# MANUAL TABLE, verified 2026-07-31 vs Fantasy Index play-caller ranking
# (2026-02-20) + CBS Sports coordinator-hire grades. Update on staff changes /
# mid-season play-calling handoffs.
#   src "same"        -> caller called this team's plays in 2025 too (even if
#                        his title changed) -> baseline = team's own 2025.
#   src (team, year)  -> caller's most recent play-calling team-season; for
#                        FIRST-TIME callers it's the offense they come from
#                        (their tree's trend — Jack: "assume they follow their
#                        general philosophy").
PLAYCALLERS = {
    "ARI": {"caller": "Mike LaFleur (HC)",          "src": ("NYJ", 2022)},  # last called plays as Jets OC
    "ATL": {"caller": "Tommy Rees (OC)",            "src": ("CLE", 2025)},  # called CLE plays mid-2025
    "BAL": {"caller": "Declan Doyle (OC)",          "src": ("CHI", 2025)},  # 1st-time — Ben Johnson tree
    "BUF": {"caller": "Joe Brady (HC)",             "src": "same"},         # has called BUF plays since 2023
    "CAR": {"caller": "Dave Canales (HC)",          "src": "same"},
    "CHI": {"caller": "Ben Johnson (HC)",           "src": "same"},
    "CIN": {"caller": "Zac Taylor (HC)",            "src": "same"},
    "CLE": {"caller": "Todd Monken (HC)",           "src": ("BAL", 2025)},  # BAL OC play-caller 2023-25
    "DAL": {"caller": "Brian Schottenheimer (HC)",  "src": "same"},
    "DEN": {"caller": "Sean Payton (HC)",           "src": "same"},
    "DET": {"caller": "Drew Petzing (OC)",          "src": ("ARI", 2025)},  # ARI OC play-caller 2023-25
    "GB":  {"caller": "Matt LaFleur (HC)",          "src": "same"},
    "HOU": {"caller": "Nick Caley (OC)",            "src": "same"},         # HOU caller since 2025
    "IND": {"caller": "Shane Steichen (HC)",        "src": "same"},
    "JAX": {"caller": "Liam Coen (HC)",             "src": "same"},
    "KC":  {"caller": "Andy Reid (HC)",             "src": "same"},         # Bieniemy OC does not call
    "LAC": {"caller": "Mike McDaniel (OC)",         "src": ("MIA", 2024)},  # called MIA plays as HC
    "LAR": {"caller": "Sean McVay (HC)",            "src": "same"},
    "LV":  {"caller": "Klint Kubiak (HC)",          "src": ("SEA", 2025)},  # SEA OC play-caller 2025
    "MIA": {"caller": "Bobby Slowik (OC)",          "src": ("HOU", 2024)},  # HOU OC play-caller 2023-24
    "MIN": {"caller": "Kevin O'Connell (HC)",       "src": "same"},
    "NE":  {"caller": "Josh McDaniels (OC)",        "src": "same"},         # NE caller since 2025
    "NO":  {"caller": "Kellen Moore (HC)",          "src": "same"},
    "NYG": {"caller": "Matt Nagy (OC)",             "src": ("CHI", 2020)},  # last clear play-calling season
    "NYJ": {"caller": "Frank Reich (OC)",           "src": ("CAR", 2023)},  # last play-calling stop
    "PHI": {"caller": "Sean Mannion (OC)",          "src": ("GB", 2025)},   # 1st-time — M.LaFleur tree
    "PIT": {"caller": "Mike McCarthy (HC)",         "src": ("DAL", 2024)},  # called DAL plays 2023-24
    "SEA": {"caller": "Brian Fleury (OC)",          "src": ("SF", 2025)},   # 1st-time — Shanahan tree
    "SF":  {"caller": "Kyle Shanahan (HC)",         "src": "same"},
    "TB":  {"caller": "Zac Robinson (OC)",          "src": ("ATL", 2025)},  # ATL OC play-caller 2024-25
    "TEN": {"caller": "Brian Daboll (OC)",          "src": ("NYG", 2025)},  # called NYG plays as HC
    "WAS": {"caller": "David Blough (OC)",          "src": "same"},         # 1st-time, promoted internally -> own 2025 (Kingsbury offense)
}

def fetch(url, dest):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "simlab"})
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
            f.write(r.read())
        return os.path.getsize(dest) > 10000
    except Exception:
        if os.path.exists(dest) and os.path.getsize(dest) < 10000:
            os.remove(dest)
        return False

def te2_by_week(year):
    path = os.path.join(CACHE, f"pbp_participation_{year}.parquet")
    if not os.path.exists(path):
        return {}
    df = pd.read_parquet(path, columns=["nflverse_game_id", "possession_team", "offense_personnel"])
    df = df.dropna()
    df = df[df.possession_team != ""]
    df["week"] = df.nflverse_game_id.str.split("_").str[1].astype(int)
    te_n = df.offense_personnel.str.extract(r"(\d+)\s*TE")[0].astype(float)
    df = df.assign(te2=(te_n >= 2))
    out = {}
    for (t, wk), g in df.groupby(["possession_team", "week"]):
        out.setdefault(tm(t), {})[wk] = (float(g.te2.mean()), len(g))
    return out

def team_weeks(year):
    """per team per REG week: plays, neutral pass, proe, no-huddle (+te2)."""
    path = os.path.join(CACHE, f"play_by_play_{year}.csv.gz")
    if not os.path.exists(path):
        return {}, {}
    cols = ["season_type", "week", "posteam", "home_team", "away_team", "game_id",
            "home_coach", "away_coach", "play_type", "pass", "rush",
            "pass_oe", "wp", "qtr", "no_huddle", "qb_kneel", "qb_spike"]
    df = pd.read_csv(path, usecols=cols, low_memory=False)
    df = df[(df.season_type == "REG")]
    coach = {}
    for _, r in df.dropna(subset=["posteam"]).groupby("game_id").first().iterrows():
        coach.setdefault(tm(r.home_team), []).append(r.home_coach)
        coach.setdefault(tm(r.away_team), []).append(r.away_coach)
    coach = {t: pd.Series(v).mode().iloc[0] for t, v in coach.items()}
    plays = df[((df["pass"] == 1) | (df["rush"] == 1)) & (df.play_type != "no_play")
               & (df.qb_kneel != 1) & (df.qb_spike != 1)].copy()
    plays["posteam"] = plays.posteam.map(lambda t: tm(t) if isinstance(t, str) else t)
    te2 = te2_by_week(year)
    out = {}
    for (t, wk), g in plays.groupby(["posteam", "week"]):
        neutral = g[(g.wp >= 0.2) & (g.wp <= 0.8) & (g.qtr <= 3)]
        rec = {"plays": len(g),
               "npr": float(neutral["pass"].mean()) if len(neutral) >= 10 else None,
               "proe": float(g.pass_oe.mean()),
               "huddle": float(g.no_huddle.mean()),
               "te2": None}
        t2 = te2.get(t, {}).get(int(wk))
        if t2 and t2[1] >= 20:
            rec["te2"] = t2[0]
        out.setdefault(t, {})[int(wk)] = rec
    return out, coach

def agg(weeks, wk_filter=None):
    sel = [r for wk, r in weeks.items() if wk_filter is None or wk_filter(wk)]
    if not sel:
        return None
    def mean_of(k):
        vals = [r[k] for r in sel if r.get(k) is not None]
        return round(float(np.mean(vals)), 4) if vals else None
    return {"games": len(sel), "plays": mean_of("plays"), "npr": mean_of("npr"),
            "proe": mean_of("proe"), "huddle": mean_of("huddle"), "te2": mean_of("te2")}

def research_metrics():
    R = json.load(open(RESEARCH, encoding="utf-8"))["metrics"]
    # normalize: {year: {team: {coach, plays_gm->plays, ...}}}
    out = {}
    for y, teams in R.items():
        out[int(y)] = {t: {"coach": v["coach"], "plays": v["plays_gm"], "npr": v["npr"],
                           "proe": v["proe"], "huddle": v["huddle"], "te2": v["te2"]}
                       for t, v in teams.items()}
    return out

def build_baseline(team, coach_now, R, upto_year):
    """Baseline dict + source label, per the coach-ownership research."""
    prev = R.get(upto_year - 1, {}).get(team)
    prev_coach = prev["coach"] if prev else None
    lg = {m: round(float(np.mean([v[m] for v in R.get(upto_year - 1, {}).values()
                                  if v.get(m) is not None])), 4)
          for m in PACE_METRICS + MIX_METRICS} if R.get(upto_year - 1) else {}
    if prev and (coach_now is None or coach_now == prev_coach):
        return {m: prev[m] for m in PACE_METRICS + MIX_METRICS}, \
            ("%s 2025 (coach %s)" % (team, "TBC" if coach_now is None else "same"))
    # new coach: find his most recent season anywhere
    hist = None
    for y in sorted(R, reverse=True):
        if y >= upto_year:
            continue
        for t2, v in R[y].items():
            if v["coach"] == coach_now:
                hist = (y, t2, v)
                break
        if hist:
            break
    base = {}
    for m in PACE_METRICS:
        base[m] = hist[2][m] if hist and hist[2].get(m) is not None else lg.get(m)
    for m in MIX_METRICS:
        base[m] = prev[m] if prev and prev.get(m) is not None else lg.get(m)
    src = ("new HC %s: pace from %s %d, mix from roster" % (coach_now, hist[1], hist[0])) if hist \
        else ("new HC %s: pace lg-avg, mix from roster" % coach_now)
    return base, src

def caller_baseline(team, R):
    """2026 baseline from the PLAY-CALLER map: pace identity from the caller's
    own play-calling history (or his tree for first-timers), pass mix from the
    roster. Falls back to the HC-based build_baseline if a team is missing."""
    pc = PLAYCALLERS.get(team)
    if not pc:
        return build_baseline(team, None, R, SEASON)
    prev = R.get(PREV, {}).get(team)
    lg = {m: round(float(np.mean([v[m] for v in R.get(PREV, {}).values()
                                  if v.get(m) is not None])), 4)
          for m in PACE_METRICS + MIX_METRICS} if R.get(PREV) else {}
    base = {}
    if pc["src"] == "same":
        for m in PACE_METRICS:
            base[m] = prev[m] if prev and prev.get(m) is not None else lg.get(m)
        src = "caller %s returning: pace = own 2025" % pc["caller"]
    else:
        st, sy = pc["src"]
        hist = R.get(sy, {}).get(st)
        for m in PACE_METRICS:
            base[m] = hist[m] if hist and hist.get(m) is not None else lg.get(m)
        src = "caller %s: pace from %s %d, mix from roster" % (pc["caller"], st, sy)
    for m in MIX_METRICS:
        base[m] = prev[m] if prev and prev.get(m) is not None else lg.get(m)
    return base, src

def validate():
    """2019-25: does drift (weeks<=8 vs baseline) predict drift (weeks>=9)?"""
    R = research_metrics()
    pairs = {m: [] for m in PACE_METRICS + MIX_METRICS}
    for Y in range(2019, 2026):
        weeks, coach = team_weeks(Y)
        for t, wks in weeks.items():
            base, _ = build_baseline(t, coach.get(t), R, Y)
            early, late = agg(wks, lambda w: w <= 8), agg(wks, lambda w: w >= 9)
            if not early or not late or not base:
                continue
            for m in pairs:
                if None not in (early.get(m), late.get(m), base.get(m)):
                    pairs[m].append((early[m] - base[m], late[m] - base[m]))
        print(f"  {Y} done ({len(weeks)} teams)")
    print("\n=== Does early drift (wk<=8 vs baseline) predict late drift (wk>=9)? ===")
    for m, pr in pairs.items():
        a = np.array([p[0] for p in pr]); b = np.array([p[1] for p in pr])
        r = float(np.corrcoef(a, b)[0, 1]) if len(pr) >= 10 else None
        own = "coach-owned" if m in PACE_METRICS else "roster-owned"
        print(f"  {m:<7} r={r:+.2f}  (n={len(pr)}, {own})")

ROUTES_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sim_routes.js")

def norm_name(n):
    import re as _re
    n = n.lower().replace(".", "").replace("'", "").replace("-", " ")
    n = _re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return _re.sub(r"\s+", " ", n).strip()

# ---------------------------------------------------------------------------
# RB TD LUCK (backtest_rb_role.py, 2026-09-14): per RB season-to-date expected
# TDs from the yardline of every carry/target vs actual TDs. Unlucky-so-far
# backs beat the P=5 base by ~13%, lucky ones land on it; the engine adds
# 0.75 x 6 x (xTD-TD)/g x g/(P+g) (LOYO -0.36%, 5/7 years, identical when
# centered per season -> real per-player mean reversion, not a level effect).
# League TD rates per touch by yardline bucket, pooled nflverse pbp 2018-25
# (targets inside the 5 are one bucket - thin n at the 1-3). RB = players.csv
# position (refetched when older than 7 days).
XTD_BINS = [1, 2, 3, 4, 5, 10, 20, 40, 100]
XTD_RUSH = [0.540, 0.379, 0.339, 0.257, 0.215, 0.105, 0.042, 0.011, 0.003]
XTD_TGT  = [0.405, 0.405, 0.405, 0.405, 0.405, 0.247, 0.094, 0.029, 0.003]

def _xtd(yl, is_rush):
    tbl = XTD_RUSH if is_rush else XTD_TGT
    for i, hi in enumerate(XTD_BINS):
        if yl <= hi:
            return tbl[i]
    return tbl[-1]

def build_rb_tdluck_2026():
    """{norm: {xtd, td, g, n}} for every RB with a 2026 touch (g = games with
    >= 1 touch, n = touches). Empty preseason -> engine tdLuckAdj is a no-op."""
    out = {}
    pbp_p = os.path.join(CACHE, f"play_by_play_{SEASON}.csv.gz")
    players_p = os.path.join(CACHE, "players.csv")
    try:
        if not os.path.exists(players_p) or time.time() - os.path.getmtime(players_p) > 7 * 86400:
            fetch("https://github.com/nflverse/nflverse-data/releases/download/players/players.csv", players_p)
        if not (os.path.exists(pbp_p) and os.path.exists(players_p)):
            return out
        pl = pd.read_csv(players_p, usecols=["gsis_id", "display_name", "position"], low_memory=False)
        pl = pl[(pl.position == "RB") & pl.gsis_id.notna()]
        rb_name = dict(zip(pl.gsis_id, pl.display_name))
        pbp = pd.read_csv(pbp_p, usecols=["season_type", "week", "rush_attempt", "pass_attempt",
                                          "rusher_player_id", "receiver_player_id", "yardline_100",
                                          "rush_touchdown", "pass_touchdown"], low_memory=False)
        pbp = pbp[pbp.season_type == "REG"]
        rush = pbp[(pbp.rush_attempt == 1) & pbp.rusher_player_id.isin(rb_name)]
        tgt = pbp[(pbp.pass_attempt == 1) & pbp.receiver_player_id.isin(rb_name)]
        acc = {}
        for df, pid_col, td_col, is_rush in ((rush, "rusher_player_id", "rush_touchdown", True),
                                             (tgt, "receiver_player_id", "pass_touchdown", False)):
            for pid, td, yl, wk in df[[pid_col, td_col, "yardline_100", "week"]].itertuples(index=False):
                a = acc.setdefault(pid, {"xtd": 0.0, "td": 0, "n": 0, "wks": set(), "w": {}})
                x = _xtd(float(yl) if pd.notna(yl) else 99.0, is_rush); t = int(td == 1)
                a["xtd"] += x; a["td"] += t; a["n"] += 1; a["wks"].add(int(wk))
                wv = a["w"].setdefault(str(int(wk)), [0.0, 0]); wv[0] += x; wv[1] += t
        for pid, a in acc.items():
            out[norm_name(str(rb_name[pid]))] = {"xtd": round(a["xtd"], 3), "td": a["td"],
                                                 "g": len(a["wks"]), "n": a["n"],
                                                 "w": {k: [round(v[0], 2), v[1]] for k, v in a["w"].items()}}
    except Exception as e:
        print(f"WARN rb tdluck skipped ({e})")
    return out

REPO_DATA = r"E:\MyFantasyFootball\MyFantasyFootball Files\data"

def route_pct_fallback(routes):
    """In-season source for SIM_ROUTES_2026 (2026-09-14, backtest_snap_split.py):
    nflverse participation is postseason-only, so the participation join above
    leaves `routes` empty all season and the shipped TE routeMult is a no-op.
    The repo's data/route_pct.js (scripts/pull_route_pct.py) carries REAL weekly
    route participation for the current season from the PFF Premium weekly
    export (routes / team dropbacks - the same definition). Fill any player
    the join did not cover; skip seasons flagged `est` (snap-share estimates
    would double-count the snap trend)."""
    p = os.path.join(REPO_DATA, "route_pct.js")
    if not os.path.exists(p):
        return routes, 0
    try:
        raw = open(p, encoding="utf-8").read()
        i = raw.index("window.ROUTE_PCT = ") + len("window.ROUTE_PCT = ")
        d, _ = json.JSONDecoder().raw_decode(raw, i)
    except Exception as e:
        print(f"WARN route_pct.js unreadable ({e})")
        return routes, 0
    added = 0
    for name, yrs in d.items():
        y = yrs.get(str(SEASON))
        if not y or y.get("est") or not y.get("w"):
            continue
        k = norm_name(name)
        if k in routes:
            continue
        wk = {str(w): float(v) for w, v in y["w"].items() if v is not None}
        if wk:
            routes[k] = wk
            added += 1
    return routes, added

# RECEIVER TD LUCK (backtest_wr_tdluck.py, 2026-09-14): the same mean
# reversion for WR/TE. xTD per TARGET depends on depth as well as field
# position (an end-zone throw from the 30 is not a screen from the 30):
# league TD rate by yardline bucket x end-zone-throw flag (air_yards >=
# yardline_100), pooled pbp 2018-25; WR/TE carries use the RB rush table.
# LOYO -0.93% (WR -0.79%, TE -1.26%), 7/7 years, k=1.0 every fold, identical
# centered per season. Engine: tdLuckAdj, TDLUCK_K_REC = 1.0.
XTD_REC_BINS = [5, 10, 20, 40, 100]
XTD_REC_NONEZ = [0.264, 0.213, 0.080, 0.030, 0.007]
XTD_REC_EZ    = [0.501, 0.384, 0.330, 0.271, 0.232]

def _xtd_rec(yl, ez):
    tbl = XTD_REC_EZ if ez else XTD_REC_NONEZ
    for i, hi in enumerate(XTD_REC_BINS):
        if yl <= hi:
            return tbl[i]
    return tbl[-1]

def build_rec_tdluck_2026():
    """{norm: {xtd, td, g, n}} for every WR/TE with a 2026 touch."""
    out = {}
    pbp_p = os.path.join(CACHE, f"play_by_play_{SEASON}.csv.gz")
    players_p = os.path.join(CACHE, "players.csv")
    try:
        if not (os.path.exists(pbp_p) and os.path.exists(players_p)):
            return out
        pl = pd.read_csv(players_p, usecols=["gsis_id", "display_name", "position"], low_memory=False)
        pl = pl[pl.position.isin(["WR", "TE"]) & pl.gsis_id.notna()]
        names = dict(zip(pl.gsis_id, pl.display_name))
        pbp = pd.read_csv(pbp_p, usecols=["season_type", "week", "rush_attempt", "pass_attempt", "sack",
                                          "rusher_player_id", "receiver_player_id", "yardline_100", "air_yards",
                                          "rush_touchdown", "pass_touchdown"], low_memory=False)
        pbp = pbp[pbp.season_type == "REG"]
        tg = pbp[(pbp.pass_attempt == 1) & (pbp.sack != 1) & pbp.receiver_player_id.isin(names)]
        ru = pbp[(pbp.rush_attempt == 1) & pbp.rusher_player_id.isin(names)]
        acc = {}
        def _tally(a, x, t, wk):
            a["xtd"] += x; a["td"] += t; a["n"] += 1; a["wks"].add(int(wk))
            wv = a["w"].setdefault(str(int(wk)), [0.0, 0]); wv[0] += x; wv[1] += t
        for pid, td, yl, ay, wk in tg[["receiver_player_id", "pass_touchdown", "yardline_100", "air_yards", "week"]].itertuples(index=False):
            a = acc.setdefault(pid, {"xtd": 0.0, "td": 0, "n": 0, "wks": set(), "w": {}})
            yl = float(yl) if pd.notna(yl) else 99.0
            ez = pd.notna(ay) and float(ay) >= yl
            _tally(a, _xtd_rec(yl, ez), int(td == 1), wk)
        for pid, td, yl, wk in ru[["rusher_player_id", "rush_touchdown", "yardline_100", "week"]].itertuples(index=False):
            a = acc.setdefault(pid, {"xtd": 0.0, "td": 0, "n": 0, "wks": set(), "w": {}})
            _tally(a, _xtd(float(yl) if pd.notna(yl) else 99.0, True), int(td == 1), wk)
        for pid, a in acc.items():
            out[norm_name(str(names[pid]))] = {"xtd": round(a["xtd"], 3), "td": a["td"], "g": len(a["wks"]), "n": a["n"],
                                               "w": {k: [round(v[0], 2), v[1]] for k, v in a["w"].items()}}
    except Exception as e:
        print(f"WARN rec tdluck skipped ({e})")
    return out

# QB PASSING-TD LUCK (backtest_qb_tdluck.py, 2026-09-14): xPassTD = sum over
# his targeted attempts of the receiver table (yardline x end-zone throw);
# throwaways count 0. QB RUSH luck graded flat and is NOT included. LOYO
# pass-only -0.44% (5/7), k = 0.5 x pass-TD value, uncentered (live
# season-to-date centering graded weaker, -0.34%).
def build_qb_tdluck_2026():
    """{norm: {xtd, td, g, n}} passing only, every QB with a 2026 attempt."""
    out = {}
    pbp_p = os.path.join(CACHE, f"play_by_play_{SEASON}.csv.gz")
    players_p = os.path.join(CACHE, "players.csv")
    try:
        if not (os.path.exists(pbp_p) and os.path.exists(players_p)):
            return out
        pl = pd.read_csv(players_p, usecols=["gsis_id", "display_name", "position"], low_memory=False)
        pl = pl[(pl.position == "QB") & pl.gsis_id.notna()]
        names = dict(zip(pl.gsis_id, pl.display_name))
        pbp = pd.read_csv(pbp_p, usecols=["season_type", "week", "pass_attempt", "sack", "passer_player_id",
                                          "receiver_player_id", "yardline_100", "air_yards", "pass_touchdown"], low_memory=False)
        pbp = pbp[(pbp.season_type == "REG") & (pbp.pass_attempt == 1) & (pbp.sack != 1) & pbp.passer_player_id.isin(names)]
        acc = {}
        for pid, rcv, td, yl, ay, wk in pbp[["passer_player_id", "receiver_player_id", "pass_touchdown", "yardline_100", "air_yards", "week"]].itertuples(index=False):
            a = acc.setdefault(pid, {"xtd": 0.0, "td": 0, "n": 0, "wks": set(), "w": {}})
            yl = float(yl) if pd.notna(yl) else 99.0
            x = _xtd_rec(yl, pd.notna(ay) and float(ay) >= yl) if pd.notna(rcv) else 0.0
            t = int(td == 1)
            a["xtd"] += x; a["td"] += t; a["n"] += 1; a["wks"].add(int(wk))
            wv = a["w"].setdefault(str(int(wk)), [0.0, 0]); wv[0] += x; wv[1] += t
        for pid, a in acc.items():
            out[norm_name(str(names[pid]))] = {"xtd": round(a["xtd"], 3), "td": a["td"], "g": len(a["wks"]), "n": a["n"],
                                               "w": {k: [round(v[0], 2), v[1]] for k, v in a["w"].items()}}
    except Exception as e:
        print(f"WARN qb tdluck skipped ({e})")
    return out

# KICKER FG/XP LUCK (backtest_k_fgluck.py, 2026-09-15) - INTEL ONLY. Expected
# points per attempt from league make rates by distance (pooled pbp 2018-25:
# <30 .979, 30-39 .932, 40-49 .784, 50-54 .712, 55+ .576; XP .946) x points if
# made (3/4/5 by distance, XP 1) minus miss (-1). Kicker accuracy over
# expected does NOT persist (YoY r .09), so a run of misses is luck, not a
# slump. NOT an engine layer: the live K mean is Clay x kLevel x Vegas x the
# kicking-points market and has no realized-points half to correct. Feeds the
# NOTES leaderboard K section.
K_FG_RATE = [(29, 0.979), (39, 0.932), (49, 0.784), (54, 0.712), (999, 0.576)]
K_XP_RATE = 0.946

def _k_xpts(dist):
    pm = next(r for hi, r in K_FG_RATE if dist <= hi)
    pts = 5 if dist >= 50 else (4 if dist >= 40 else 3)
    return pm * pts - (1 - pm) * 1

def build_k_luck_2026():
    """{norm: {xpts, pts, g, att, xp}} for every kicker with a 2026 attempt."""
    out = {}
    pbp_p = os.path.join(CACHE, f"play_by_play_{SEASON}.csv.gz")
    try:
        if not os.path.exists(pbp_p):
            return out
        pbp = pd.read_csv(pbp_p, usecols=["season_type", "week", "kicker_player_id", "kicker_player_name",
                                          "field_goal_result", "kick_distance", "extra_point_result"], low_memory=False)
        pbp = pbp[(pbp.season_type == "REG") & pbp.kicker_player_id.notna()]
        acc = {}
        for r in pbp.itertuples(index=False):
            a = acc.setdefault(r.kicker_player_id, {"name": r.kicker_player_name, "xpts": 0.0, "pts": 0, "att": 0, "xp": 0, "wks": set()})
            if isinstance(r.field_goal_result, str):
                d = float(r.kick_distance) if pd.notna(r.kick_distance) else 40.0
                a["xpts"] += _k_xpts(d); a["att"] += 1; a["wks"].add(int(r.week))
                a["pts"] += (5 if d >= 50 else (4 if d >= 40 else 3)) if r.field_goal_result == "made" else -1
            elif isinstance(r.extra_point_result, str):
                a["xpts"] += K_XP_RATE * 1 - (1 - K_XP_RATE) * 1; a["xp"] += 1; a["wks"].add(int(r.week))
                a["pts"] += 1 if r.extra_point_result == "good" else -1
        for pid, a in acc.items():
            # pbp names are 'B.Aubrey' - resolve via players.csv display name when possible
            out[pid] = {"name": a["name"], "xpts": round(a["xpts"], 2), "pts": a["pts"], "g": len(a["wks"]), "att": a["att"], "xp": a["xp"]}
        players_p = os.path.join(CACHE, "players.csv")
        if os.path.exists(players_p):
            pl = pd.read_csv(players_p, usecols=["gsis_id", "display_name"], low_memory=False)
            full = dict(zip(pl.gsis_id, pl.display_name))
            out = {norm_name(str(full.get(pid, v["name"]))): dict(v, name=str(full.get(pid, v["name"]))) for pid, v in out.items()}
    except Exception as e:
        print(f"WARN k luck skipped ({e})")
    return out

# DST COMPONENT INTEL (backtest_dst_regression.py, 2026-09-15) - INTEL ONLY.
# Season-to-date DST points split into components (Sleeper-default scoring:
# sack 1, INT/FR 2, def+return TD 6, safety/block 2, points-allowed buckets).
# Def/ST TDs are pure noise (early->late r .06, YoY .11) and NO realized
# component beats the Vegas-only DST mean (dstWeeklyMean), so nothing here
# feeds projections - it flags DSTs whose season-to-date points are riding
# TDs (people over-rate them) for the NOTES leaderboard.
DST_LG_TD_PG = 0.73   # league def/ST TD points per team-game, 2025

def build_dst_luck_2026():
    """{TEAM: {g, pts, td, sack, to, pa}} season-to-date (points by component)."""
    out = {}
    pbp_p = os.path.join(CACHE, f"play_by_play_{SEASON}.csv.gz")
    try:
        if not os.path.exists(pbp_p):
            return out
        df = pd.read_csv(pbp_p, usecols=["season_type", "week", "defteam", "game_id", "home_team", "away_team",
                                         "home_score", "away_score", "sack", "interception", "fumble_lost",
                                         "touchdown", "td_team", "safety", "field_goal_result", "punt_blocked"], low_memory=False)
        df = df[df.season_type == "REG"]
        acc = {}
        def add(team, wk, k, p):
            if not isinstance(team, str) or not team: return
            a = acc.setdefault(tm(team), {"td": 0, "sack": 0, "to": 0, "pa": 0, "misc": 0, "wks": set()})
            a[k] += p; a["wks"].add(int(wk))
        d = df[df.defteam.notna()]
        for r in d[d.sack == 1][["defteam", "week"]].itertuples(index=False): add(r.defteam, r.week, "sack", 1)
        for r in d[d.interception == 1][["defteam", "week"]].itertuples(index=False): add(r.defteam, r.week, "to", 2)
        for r in d[d.fumble_lost == 1][["defteam", "week"]].itertuples(index=False): add(r.defteam, r.week, "to", 2)
        for r in d[(d.touchdown == 1) & d.td_team.notna()][["defteam", "td_team", "week"]].itertuples(index=False):
            if r.td_team == r.defteam: add(r.defteam, r.week, "td", 6)
        for r in d[d.safety == 1][["defteam", "week"]].itertuples(index=False): add(r.defteam, r.week, "misc", 2)
        for r in d[d.field_goal_result == "blocked"][["defteam", "week"]].itertuples(index=False): add(r.defteam, r.week, "misc", 2)
        for r in d[d.punt_blocked == 1][["defteam", "week"]].itertuples(index=False): add(r.defteam, r.week, "misc", 2)
        def pa_pts(pa):
            return 10 if pa == 0 else 7 if pa <= 6 else 4 if pa <= 13 else 1 if pa <= 20 else 0 if pa <= 27 else -1 if pa <= 34 else -4
        games = df.dropna(subset=["home_team"]).groupby("game_id").first()
        for _, gm in games.iterrows():
            add(gm.home_team, gm.week, "pa", pa_pts(int(gm.away_score))); add(gm.away_team, gm.week, "pa", pa_pts(int(gm.home_score)))
        for t, a in acc.items():
            out[t] = {"g": len(a["wks"]), "td": a["td"], "sack": a["sack"], "to": a["to"], "pa": a["pa"], "misc": a["misc"],
                      "pts": a["td"] + a["sack"] + a["to"] + a["pa"] + a["misc"]}
    except Exception as e:
        print(f"WARN dst luck skipped ({e})")
    return out

# EXPECTED FANTASY POINTS components (2026-09-15, Jack: "use the standard
# definition"). Industry xFP: every target / carry / attempt valued at what the
# AVERAGE player produces from that spot, summed. Tables pooled from nflverse
# pbp 2018-25 (n = 138k targets, 97k RB-group carries, 17k QB carries):
#   target  -> catch rate + yards by air-yards bucket; TD by yardline x end-zone throw
#   carry   -> yards by yardline bucket (RB group / QB separate); TD by yardline
#   QB att  -> targeted attempts use the target tables (throwaways 0)
# Exported per player per week as raw expected COMPONENTS so the site can score
# them in any format:  RB/WR/TE [tg, xrec, xrecyd, xrectd, car, xruyd, xrutd]
#                      QB       [att, xpyd, xptd, car, xruyd, xrutd]
# FPOE = actual - xFP. Our backtests: the TD part of FPOE is luck (YoY r .09),
# the yards/catch part is skill (r .34/.32) - the card tooltip splits them.
XFP_AB_BINS = [-0.01, 4.99, 9.99, 14.99, 19.99, 29.99]            # <0, 0-4, 5-9, 10-14, 15-19, 20-29, 30+
XFP_CATCH = [0.837, 0.755, 0.703, 0.589, 0.547, 0.416, 0.302]
XFP_TGT_YDS = [4.87, 5.39, 6.83, 9.00, 11.42, 11.88, 13.46]
XFP_RUSH_BINS = [5, 10, 20, 40]                                   # <=5, 6-10, 11-20, 21-40, 41+
XFP_RUSH_YDS = [1.10, 2.88, 3.82, 4.45, 4.75]
XFP_RUSH_YDS_QB = [1.07, 3.22, 4.05, 4.48, 4.77]
XFP_QB_RUSH_TD = [(1, 0.619), (2, 0.302), (3, 0.366), (5, 0.304), (10, 0.201), (20, 0.059), (40, 0.011), (999, 0.001)]

def _xfp_ab(ay):
    for i, hi in enumerate(XFP_AB_BINS):
        if ay <= hi:
            return i
    return len(XFP_AB_BINS)

def _xfp_rush(yl, is_qb):
    tbl = XFP_RUSH_YDS_QB if is_qb else XFP_RUSH_YDS
    for i, hi in enumerate(XFP_RUSH_BINS):
        if yl <= hi:
            return tbl[i]
    return tbl[-1]

def _xfp_qb_rush_td(yl):
    return next(r for hi, r in XFP_QB_RUSH_TD if yl <= hi)

# INT rate per target by air-yards bucket (same 7 buckets), pooled pbp 2018-25
# (backtest_xfp_variants.py V6: xINT/g 0.71 vs actual 0.70; fixes the QB
# full-scoring bias -1.33/g -> +0.10/g). Sleeper scores an INT -1.
XFP_INT = [0.0077, 0.0107, 0.0188, 0.0318, 0.0416, 0.0557, 0.0692]

def build_xfp_2026():
    """{norm: {pos, w: {wk: [components]}}} for every QB/RB/WR/TE with a 2026 touch."""
    out = {}
    pbp_p = os.path.join(CACHE, f"play_by_play_{SEASON}.csv.gz")
    players_p = os.path.join(CACHE, "players.csv")
    try:
        if not (os.path.exists(pbp_p) and os.path.exists(players_p)):
            return out
        pl = pd.read_csv(players_p, usecols=["gsis_id", "display_name", "position"], low_memory=False)
        pl = pl[pl.position.isin(["QB", "RB", "WR", "TE"]) & pl.gsis_id.notna()]
        pos_of = dict(zip(pl.gsis_id, pl.position)); name_of = dict(zip(pl.gsis_id, pl.display_name))
        pbp = pd.read_csv(pbp_p, usecols=["season_type", "week", "pass_attempt", "rush_attempt", "sack", "passer_player_id",
                                          "receiver_player_id", "rusher_player_id", "yardline_100", "air_yards",
                                          "cp", "xyac_mean_yardage"], low_memory=False)
        pbp = pbp[pbp.season_type == "REG"]
        acc = {}
        def row(pid, wk):
            a = acc.setdefault(pid, {})
            return a.setdefault(str(int(wk)), {"tg": 0, "xrec": 0.0, "xrecyd": 0.0, "xrectd": 0.0, "car": 0, "xruyd": 0.0, "xrutd": 0.0,
                                                "att": 0, "xpyd": 0.0, "xptd": 0.0, "xint": 0.0})
        # targets (receivers) + attempts (passers). Catch / yards per target come
        # from nflfastR's per-play models where present (cp x (air + xYAC), ~93%
        # of targets; the ~7% without an xYAC are mostly goal-line throws) and
        # fall back to the air-yards bucket tables (backtest_xfp_variants.py V3:
        # WR +.013 weekly r, +.014 rest-of-season r, +.012 YoY; others flat).
        pa = pbp[(pbp.pass_attempt == 1) & (pbp.sack != 1)]
        for pid, rcv, yl, ay, wk, cp, xyac in pa[["passer_player_id", "receiver_player_id", "yardline_100", "air_yards", "week",
                                                  "cp", "xyac_mean_yardage"]].itertuples(index=False):
            yl = float(yl) if pd.notna(yl) else 50.0
            targeted = pd.notna(rcv)
            if targeted:
                a = float(ay) if pd.notna(ay) else 0.0
                b = _xfp_ab(a); ez = a >= yl
                xtd = _xtd_rec(yl, ez)
                if pd.notna(cp) and pd.notna(xyac):
                    xr, xy = float(cp), float(cp) * (a + float(xyac))
                else:
                    xr, xy = XFP_CATCH[b], XFP_TGT_YDS[b]
                if rcv in pos_of:
                    r = row(rcv, wk); r["tg"] += 1; r["xrec"] += xr; r["xrecyd"] += xy; r["xrectd"] += xtd
            if pd.notna(pid) and pos_of.get(pid) == "QB":
                q = row(pid, wk); q["att"] += 1
                if targeted:
                    q["xpyd"] += xy; q["xptd"] += xtd; q["xint"] += XFP_INT[b]
        ru = pbp[(pbp.rush_attempt == 1) & pbp.rusher_player_id.notna()]
        for pid, yl, wk in ru[["rusher_player_id", "yardline_100", "week"]].itertuples(index=False):
            if pid not in pos_of: continue
            yl = float(yl) if pd.notna(yl) else 50.0
            is_qb = pos_of[pid] == "QB"
            r = row(pid, wk); r["car"] += 1; r["xruyd"] += _xfp_rush(yl, is_qb)
            r["xrutd"] += _xfp_qb_rush_td(yl) if is_qb else _xtd(yl, True)
        for pid, wks in acc.items():
            pos = pos_of[pid]
            w = {}
            for wk, r in wks.items():
                if pos == "QB":
                    w[wk] = [r["att"], round(r["xpyd"], 1), round(r["xptd"], 2), r["car"], round(r["xruyd"], 1), round(r["xrutd"], 2), round(r["xint"], 2)]
                else:
                    w[wk] = [r["tg"], round(r["xrec"], 2), round(r["xrecyd"], 1), round(r["xrectd"], 2), r["car"], round(r["xruyd"], 1), round(r["xrutd"], 2)]
            out[norm_name(str(name_of[pid]))] = {"pos": pos, "w": w}
    except Exception as e:
        print(f"WARN xfp skipped ({e})")
    return out

def build_routes_2026():
    """TE weekly route participation (%% of team dropbacks on the field) from
    2026 pbp + participation — feeds engine routeMult (backtest_route_trend.py:
    TE-only, e=1.0 on top of the snap trend; WR/RB add nothing over snaps).
    NOTE (2026-09-14): pbp_participation is FTN-sourced from 2023 on and is
    published only AFTER the postseason, so the routes map stays empty all
    season (routeMult = provable no-op). Kept for the post-season rebuild.
    ALSO emits per-defense pressure counts for the engine's soft-pass-rush
    QB boost — since 2026-09-14 from pbp ALONE: (qb_hit OR sack) / dropbacks,
    the public pressure PROXY re-backtested in backtest_pressure_proxy.py
    (def-season corr +0.68 vs was_pressure; same one-sided boost, thr -0.02
    in proxy units). Nightly pbp keeps it live in-season."""
    routes = {}
    pressure = {}
    pbp_p = os.path.join(CACHE, f"play_by_play_{SEASON}.csv.gz")
    part_p = os.path.join(CACHE, f"pbp_participation_{SEASON}.parquet")
    try:
        if os.path.exists(pbp_p):
            pbp = pd.read_csv(pbp_p, usecols=["game_id", "play_id", "week", "posteam",
                                              "defteam", "qb_dropback", "season_type",
                                              "qb_hit", "sack"],
                              low_memory=False)
            pbp = pbp[(pbp.season_type == "REG") & (pbp.qb_dropback == 1) & pbp.defteam.notna()]
            for r in pbp.itertuples(index=False):
                pv = pressure.setdefault(tm(r.defteam), [0, 0])
                pv[1] += 1
                if r.qb_hit == 1 or r.sack == 1:
                    pv[0] += 1
        if os.path.exists(pbp_p) and os.path.exists(part_p):
            part = pd.read_parquet(part_p, columns=["nflverse_game_id", "play_id",
                                                    "offense_names", "offense_positions"])
            m = part.merge(pbp[["game_id", "play_id", "week", "posteam"]],
                           left_on=["nflverse_game_id", "play_id"],
                           right_on=["game_id", "play_id"], how="inner")
            pres, team_db = {}, {}
            for r in m.itertuples(index=False):
                if not isinstance(r.offense_names, str) or not r.offense_names:
                    continue
                t = tm(r.posteam)
                wk = int(r.week)
                team_db[(t, wk)] = team_db.get((t, wk), 0) + 1
                poss = (r.offense_positions or "").split(";")
                for i, nm_ in enumerate(r.offense_names.split(";")):
                    if i < len(poss) and poss[i] == "TE":
                        k = (norm_name(nm_), t, wk)
                        pres[k] = pres.get(k, 0) + 1
            for (nm_, t, wk), c in pres.items():
                db = team_db.get((t, wk), 0)
                if db >= 10:
                    routes.setdefault(nm_, {})[str(wk)] = round(100.0 * c / db, 1)
    except Exception as e:
        print(f"WARN routes/pressure skipped ({e})")
    routes, n_pff = route_pct_fallback(routes)
    tdluck = build_rb_tdluck_2026()
    rectd = build_rec_tdluck_2026()
    qbtd = build_qb_tdluck_2026()
    kluck = build_k_luck_2026()
    dstluck = build_dst_luck_2026()
    xfp = build_xfp_2026()
    with open(ROUTES_OUT, "w", encoding="utf-8") as f:
        f.write("// built by pull_pace_tracker.py — TE weekly route participation (% of team dropbacks)\n")
        f.write("window.SIM_ROUTES_2026 = ")
        json.dump(routes, f, separators=(",", ":"))
        f.write(";\n")
        f.write("// per-defense season-to-date pressure PROXY counts [qb_hit-or-sack dropbacks, dropbacks] (pbp only; backtest_pressure_proxy.py)\n")
        f.write("window.SIM_PRESSURE_2026 = ")
        json.dump(pressure, f, separators=(",", ":"))
        f.write(";\n")
        f.write("// per-RB season-to-date TD luck {norm: {xtd, td, g, n}} (pbp only; backtest_rb_role.py) -> engine tdLuckAdj\n")
        f.write("window.SIM_RB_TDLUCK_2026 = ")
        json.dump(tdluck, f, separators=(",", ":"))
        f.write(";\n")
        f.write("// per-WR/TE season-to-date TD luck (targets: yardline x end-zone-throw table; backtest_wr_tdluck.py)\n")
        f.write("window.SIM_REC_TDLUCK_2026 = ")
        json.dump(rectd, f, separators=(",", ":"))
        f.write(";\n")
        f.write("// per-QB season-to-date PASSING TD luck (targets: yardline x end-zone-throw table; backtest_qb_tdluck.py)\n")
        f.write("window.SIM_QB_TDLUCK_2026 = ")
        json.dump(qbtd, f, separators=(",", ":"))
        f.write(";\n")
        f.write("// per-kicker season-to-date FG/XP luck {norm: {name, xpts, pts, g, att, xp}} (backtest_k_fgluck.py) - INTEL ONLY (NOTES tab)\n")
        f.write("window.SIM_K_LUCK_2026 = ")
        json.dump(kluck, f, separators=(",", ":"))
        f.write(";\n")
        f.write("// per-DST season-to-date points by component {TEAM: {g, pts, td, sack, to, pa, misc}} (backtest_dst_regression.py) - INTEL ONLY (NOTES tab)\n")
        f.write("window.SIM_DST_LUCK_2026 = ")
        json.dump(dstluck, f, separators=(",", ":"))
        f.write(";\n")
        f.write("// per-player per-week expected fantasy point COMPONENTS (standard opportunity-based xFP; site scores them per format)\n")
        f.write("window.SIM_XFP_2026 = ")
        json.dump(xfp, f, separators=(",", ":"))
        f.write(";\n")
    print(f"wrote {ROUTES_OUT} — {len(routes)} players with 2026 route data ({n_pff} from repo route_pct.js / PFF weekly), {len(pressure)} defenses with pressure data, {len(tdluck)} RBs + {len(rectd)} WR/TEs + {len(qbtd)} QBs with TD-luck data, {len(kluck)} kickers with FG-luck data, {len(dstluck)} DSTs, {len(xfp)} players with xFP components")

# ---------------------------------------------------------------------------
# TARGET-AREA ZONES (backtest_target_area.py, 2026-09-14) - INTEL ONLY.
# Per defense: targets faced by depth (behind LOS / 0-9 / 10-19 / 20+) and
# side (left / middle / right) with half-PPR receiving pts allowed per target;
# per receiver: his target mix by depth/side + aDOT. 2025 full season rides
# along as the prior. Persistence (2019-25): player mix YoY r .75-.88 (deep,
# behind-LOS) = a real profile; defense FUNNEL (share of targets faced per
# zone) early->late r .2-.5 = a soft scheme identity; defense EFFICIENCY
# allowed per zone beyond its overall rate r ~0 in-season AND YoY = noise.
# The matchup multiplier graded flat (LOYO +0.03%, 2/7) and is NOT applied;
# the ZONES tab shows the profiles for start/sit + video reads.
ZONES_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "zones_2026.js")
Z_DEPTH = ["bl", "sh", "in", "dp"]
Z_SIDE = ["left", "middle", "right"]

def _zone_frame(year):
    p = os.path.join(CACHE, f"play_by_play_{year}.csv.gz")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p, usecols=["season_type", "week", "posteam", "defteam", "pass_attempt", "sack",
                                 "receiver_player_id", "air_yards", "pass_location", "complete_pass",
                                 "yards_gained", "pass_touchdown"], low_memory=False)
    t = df[(df.season_type == "REG") & (df.pass_attempt == 1) & df.receiver_player_id.notna()
           & (df.sack != 1) & df.air_yards.notna() & df.pass_location.isin(Z_SIDE)].copy()
    if t.empty:
        return t
    t["def"] = t.defteam.map(tm)
    t["off"] = t.posteam.map(tm)
    t["depth"] = pd.cut(t.air_yards, [-100, -0.01, 9.99, 19.99, 200], labels=Z_DEPTH).astype(str)
    t["side"] = t.pass_location
    comp = t.complete_pass.fillna(0)
    t["pts"] = 0.5 * comp + 0.1 * t.yards_gained.fillna(0) * comp + 6 * t.pass_touchdown.fillna(0)
    return t

def _zone_counts(t, zone_cols):
    """{zone: {'n': targets, 'p': pts}} for each zone column."""
    out = {}
    for zc, zones in zone_cols:
        g = t.groupby(zc).pts.agg(["count", "sum"])
        out[zc] = {z: {"n": int(g["count"].get(z, 0)), "p": round(float(g["sum"].get(z, 0.0)), 1)} for z in zones}
    return out

def _zone_league(t):
    return {"N": int(len(t)), **_zone_counts(t, (("depth", Z_DEPTH), ("side", Z_SIDE)))}

def _zone_defs(t):
    out = {}
    for d, g in t.groupby("def"):
        out[d] = {"N": int(len(g)), "gms": int(g.week.nunique()),
                  **_zone_counts(g, (("depth", Z_DEPTH), ("side", Z_SIDE)))}
    return out

def _zone_players(t, names, min_n):
    out = {}
    for pid, g in t.groupby("receiver_player_id"):
        if len(g) < min_n or pid not in names:
            continue
        nm, pos, team = names[pid]
        rec = {"name": nm, "pos": pos, "tm": team, "N": int(len(g)), "ay": round(float(g.air_yards.sum()), 1),
               "p": round(float(g.pts.sum()), 1)}
        rec["depth"] = {z: int(v) for z, v in g.depth.value_counts().items()}
        rec["side"] = {z: int(v) for z, v in g.pass_location.value_counts().items()}
        # team = the offense he was targeted with most (trades)
        rec["tm"] = tm(g.off.value_counts().index[0]) if len(g.off.value_counts()) else team
        out[norm_name(str(nm))] = rec
    return out

def build_zones_2026():
    try:
        pl = pd.read_csv(os.path.join(CACHE, "players.csv"),
                         usecols=["gsis_id", "display_name", "position", "latest_team"], low_memory=False)
        pl = pl[pl.gsis_id.notna() & pl.position.isin(["WR", "TE", "RB", "QB", "FB"])]
        names = {r.gsis_id: (r.display_name, r.position, tm(str(r.latest_team)) if pd.notna(r.latest_team) else "")
                 for r in pl.itertuples(index=False)}
        cur = _zone_frame(SEASON)
        prior = _zone_frame(PREV)
        payload = {"updated": time.strftime("%Y-%m-%d %H:%M"), "season": SEASON, "prev": PREV,
                   "weeks": sorted(int(w) for w in cur.week.unique()) if cur is not None and not cur.empty else [],
                   "lg": _zone_league(cur) if cur is not None and not cur.empty else None,
                   "lgPrior": _zone_league(prior) if prior is not None and not prior.empty else None,
                   "def": _zone_defs(cur) if cur is not None and not cur.empty else {},
                   "defPrior": _zone_defs(prior) if prior is not None and not prior.empty else {},
                   "players": _zone_players(cur, names, 1) if cur is not None and not cur.empty else {},
                   "playersPrior": _zone_players(prior, names, 20) if prior is not None and not prior.empty else {}}
        with open(ZONES_OUT, "w", encoding="utf-8") as f:
            f.write("// built by pull_pace_tracker.py - target-area zones (defense funnel/efficiency by depth+side, receiver target mix); INTEL ONLY (backtest_target_area.py)\n")
            f.write("window.SIM_ZONES_2026 = ")
            json.dump(payload, f, separators=(",", ":"))
            f.write(";\n")
        print(f"wrote {ZONES_OUT} - {len(payload['def'])} defenses, {len(payload['players'])} receivers with {SEASON} targets, "
              f"{len(payload['playersPrior'])} with {PREV} priors")
    except Exception as e:
        print(f"WARN zones skipped ({e})")

# ---------------------------------------------------------------------------
# GAME CONTEXT for the snap / route trends (Jack 2026-09-15): a starter pulled
# up 24 in the 4th must not read as a shrinking role. Per team-week: offensive
# plays, dropbacks, and the GARBAGE share (Q4 with |margin| >= 17, Q3 with
# |margin| >= 28). The engine re-measures such weeks against competitive plays
# and down-weights them in the trend (snapMult / routeMult). Written to
# data/sim_context.js as SIM_GAMECTX_2026 = {TEAM: {wk: {pl, gp, db, gdb}}}.
CTX_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sim_context.js")

def build_context_2026():
    try:
        p = os.path.join(CACHE, f"play_by_play_{SEASON}.csv.gz")
        df = pd.read_csv(p, usecols=["season_type", "week", "posteam", "qtr", "score_differential", "play_type", "qb_dropback"], low_memory=False)
        df = df[(df.season_type == "REG") & df.posteam.notna() & df.play_type.isin(["run", "pass", "qb_spike", "qb_kneel"])]
        df["garbage"] = ((df.qtr >= 4) & (df.score_differential.abs() >= 17)) | ((df.qtr == 3) & (df.score_differential.abs() >= 28))
        df["db"] = df.qb_dropback.fillna(0) == 1
        out = {}
        for (team, wk), g in df.groupby(["posteam", "week"]):
            t = tm(str(team))
            out.setdefault(t, {})[str(int(wk))] = {"pl": int(len(g)), "gp": int(g.garbage.sum()),
                                                   "db": int(g.db.sum()), "gdb": int((g.db & g.garbage).sum())}
        with open(CTX_OUT, "w", encoding="utf-8") as f:
            f.write("// built by pull_pace_tracker.py - per team-week offensive plays / dropbacks and GARBAGE-TIME plays (Q4 |margin|>=17, Q3 >=28) for the blowout-aware snap & route trends\n")
            f.write("window.SIM_GAMECTX_2026 = ")
            json.dump(out, f, separators=(",", ":"))
            f.write(";\n")
        nb = sum(1 for t in out.values() for w in t.values() if w["gp"] >= 6)
        print(f"wrote {CTX_OUT} - {sum(len(t) for t in out.values())} team-weeks, {nb} with 6+ garbage plays")
    except Exception as e:
        print(f"WARN game context skipped ({e})")

def build():
    # in-season the 2026 pbp grows weekly — re-fetch every run
    got_pbp = fetch(f"https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{SEASON}.csv.gz",
                    os.path.join(CACHE, f"play_by_play_{SEASON}.csv.gz"))
    fetch(f"https://github.com/nflverse/nflverse-data/releases/download/pbp_participation/pbp_participation_{SEASON}.parquet",
          os.path.join(CACHE, f"pbp_participation_{SEASON}.parquet"))
    build_context_2026()
    build_routes_2026()
    build_zones_2026()
    try:   # PFF scheme/alignment intel (build_scheme.py) - needs the weekly facet CSVs from scripts/pull_pff_weekly.py
        import build_scheme
        build_scheme.build()
    except Exception as e:
        print(f"WARN scheme skipped ({e})")
    R = research_metrics()
    weeks, coach = team_weeks(SEASON) if got_pbp else ({}, {})
    teams = {}
    all_teams = sorted(R[PREV].keys())
    for t in all_teams:
        c = coach.get(t)
        base, src = caller_baseline(t, R)
        cur = agg(weeks.get(t, {}))
        teams[t] = {"coach": c or R[PREV][t]["coach"] + " (2025, TBC)",
                    "caller": (PLAYCALLERS.get(t) or {}).get("caller"),
                    "games": cur["games"] if cur else 0,
                    "cur": cur, "base": base, "baseSrc": src,
                    "weekly": {str(wk): {"plays": r["plays"], "npr": r["npr"]}
                               for wk, r in sorted(weeks.get(t, {}).items())}}
    payload = {"updated": time.strftime("%Y-%m-%d %H:%M"), "season": SEASON, "teams": teams}
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// built by pull_pace_tracker.py — team pace/play-calling season-to-date vs baseline\n")
        f.write("window.SIM_PACE_2026 = ")
        json.dump(payload, f, separators=(",", ":"))
        f.write(";\n")
    n_live = sum(1 for t in teams.values() if t["games"])
    print(f"wrote {OUT} — {len(teams)} teams, {n_live} with 2026 data"
          + ("" if got_pbp else " (no 2026 pbp yet — baselines only)"))

if __name__ == "__main__":
    if "--validate" in sys.argv:
        validate()
    else:
        build()
