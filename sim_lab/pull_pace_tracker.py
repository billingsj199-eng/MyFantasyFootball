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
    with open(ROUTES_OUT, "w", encoding="utf-8") as f:
        f.write("// built by pull_pace_tracker.py — TE weekly route participation (% of team dropbacks)\n")
        f.write("window.SIM_ROUTES_2026 = ")
        json.dump(routes, f, separators=(",", ":"))
        f.write(";\n")
        f.write("// per-defense season-to-date pressure PROXY counts [qb_hit-or-sack dropbacks, dropbacks] (pbp only; backtest_pressure_proxy.py)\n")
        f.write("window.SIM_PRESSURE_2026 = ")
        json.dump(pressure, f, separators=(",", ":"))
        f.write(";\n")
    print(f"wrote {ROUTES_OUT} — {len(routes)} TEs with 2026 route data, {len(pressure)} defenses with pressure data")

def build():
    # in-season the 2026 pbp grows weekly — re-fetch every run
    got_pbp = fetch(f"https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{SEASON}.csv.gz",
                    os.path.join(CACHE, f"play_by_play_{SEASON}.csv.gz"))
    fetch(f"https://github.com/nflverse/nflverse-data/releases/download/pbp_participation/pbp_participation_{SEASON}.parquet",
          os.path.join(CACHE, f"pbp_participation_{SEASON}.parquet"))
    build_routes_2026()
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
