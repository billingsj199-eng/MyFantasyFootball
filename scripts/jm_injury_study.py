"""jm_injury_study.py - does a college injury history show up in the NFL career?

Jack (2026-10-01): "look into college injury history and how it impacts nfl careers".

Two sources, because neither is complete on its own:

  A. GAMES MISSED IN COLLEGE (every backtest player, 2017-2024 classes)
     data/college_weekly_*.js game logs against the team's regular-season schedule
     (CFBD /games, cached in scripts/_cfb_games.json). Once a player has a real role
     (first season in which he appears in 60%+ of his team's games) every later stretch of
     two or more straight team games without him counts as an absence. A whole season with
     no games between two seasons at the same school is a lost season. One-game gaps are
     ignored (a receiver with no catch leaves no log line).
        col_absent   games missed in those stretches      col_rate = absent / team games
        col_run      longest stretch                      col_lost = a lost season
        col_final    games missed in the final college season
        tier         clean (0-1) / minor (2-3) / major (4+ straight, or a lost season)
     It is a proxy: it cannot tell an injury from a benching, a suspension or an opt-out.

  B. NAMED INJURIES (players on the Draft Sharks injury page, saved by --ds file)
     each record has a date, body part, condition, games missed and an NFL / pre-NFL flag.
     Only players still relevant today are listed, so it is a survivor sample: use it for
     "did the college injury come back", not for "did he bust".

NFL side: scripts/jm_study_table.json (build_career_study_table.py) - career grade, share of
games played in seasons 1-3 (n_avail3), weeks listed out (n_out3), pick, JM grade.

    python scripts/jm_injury_study.py --study <study_table.json> [--ds <ds_players.json>] [--out scripts/jm_injury_study.json]
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
GAMES_CACHE = os.path.join("scripts", "_cfb_games.json")
WEEKLY_FILES = ["data/college_weekly_1.js", "data/college_weekly_2.js", "data/college_weekly_3.js", "data/college_weekly_devy.js"]

TEAM_ALIAS = {"miamifl": "miami", "mississippi": "olemiss", "texassanantonio": "utsa", "southernmethodist": "smu", "centralflorida": "ucf",
              "brighamyoung": "byu", "louisianastate": "lsu", "southerncalifornia": "usc", "texaschristian": "tcu", "pitt": "pittsburgh",
              "hawaii": "hawaii", "sanjosstate": "sanjosestate", "ncstate": "ncstate", "northcarolinastate": "ncstate", "ulmonroe": "ulmonroe",
              "louisianamonroe": "ulmonroe", "louisianalafayette": "louisiana", "massachusetts": "umass", "connecticut": "uconn",
              "appalachianstate": "appstate", "floridainternational": "fiu", "middletennesseestate": "middletennessee", "southernmississippi": "southernmiss"}


def nrm(s):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", str(s or "").lower()))


def tnorm(s):
    s = str(s or "").lower().replace("&", "and")
    s = re.sub(r"^(vs\.?|@|at)\s+", "", s.strip())
    s = re.sub(r"\bst\.?$", "state", s)
    s = re.sub(r"\bst\.?\b", "state", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return TEAM_ALIAS.get(s, s)


def schedules(years):
    cache = json.load(open(GAMES_CACHE)) if os.path.exists(GAMES_CACHE) else {}
    missing = [(y, st) for y in years for st in ("regular", "postseason") if (str(y) if st == "regular" else "%dp" % y) not in cache]
    if missing:
        import requests
        from cfbd_config import CFBD_API_KEY
        for y, st in missing:
            r = requests.get("https://apinext.collegefootballdata.com/games", headers={"Authorization": "Bearer " + CFBD_API_KEY},
                             params={"year": y, "seasonType": st}, timeout=90)
            rows = r.json() if r.status_code == 200 else []
            key = str(y) if st == "regular" else "%dp" % y
            cache[key] = [[g.get("week"), g.get("startDate"), g.get("homeTeam"), g.get("awayTeam")] for g in rows if g.get("completed", True)]
            print("  schedule %d %s: %d games" % (y, st, len(cache[key])), flush=True)
            time.sleep(0.4)
        json.dump(cache, open(GAMES_CACHE, "w"), separators=(",", ":"))
    sched = defaultdict(list)   # (team norm, yr) -> [(date, week, opp norm)]  regular season
    post = Counter()            # (team norm, yr) -> postseason games
    for y, rows in cache.items():
        for wk, dt, h, a in rows:
            if y.endswith("p"):
                post[(tnorm(h), int(y[:-1]))] += 1; post[(tnorm(a), int(y[:-1]))] += 1
                continue
            sched[(tnorm(h), int(y))].append((dt or "", wk, tnorm(a)))
            sched[(tnorm(a), int(y))].append((dt or "", wk, tnorm(h)))
    for k in sched:
        sched[k].sort()
    return sched, post


def load_weekly(wanted):
    out = {}
    key_fix = re.compile(r"([{,])(\w+):")
    for f in WEEKLY_FILES:
        try:
            txt = open(f, encoding="utf-8").read()
        except OSError:
            continue
        for m in re.finditer(r"COLLEGE_WEEKLY\[(['\"])(.+?)\1\](?:\[(\d{4})\])?\s*=\s*(\{.*?\}|\[.*?\]);", txt):
            name = m.group(2).replace("\\'", "'")
            if nrm(name) not in wanted:
                continue
            body = key_fix.sub(r'\1"\2":', m.group(4))
            try:
                val = json.loads(body)
            except ValueError:
                continue
            d = out.setdefault(nrm(name), {})
            if m.group(3):
                d[int(m.group(3))] = val
            else:
                for yr, games in val.items():
                    d[int(yr)] = games
    return out


def availability(logs, draft_yr, sched, post):
    """logs: {yr: [game dicts]} -> proxy dict or None when no season could be matched to a schedule."""
    seasons = []
    for yr in sorted(logs):
        games = [g for g in logs[yr] if isinstance(g, dict)]
        if yr >= draft_yr or not games:
            continue
        team = Counter(tnorm(g.get("tm")) for g in games).most_common(1)[0][0]
        sc = sched.get((team, yr))
        if not sc:
            seasons.append({"yr": yr, "team": team, "n": None})
            continue
        if not any(g.get("opp") or g.get("wk") for g in games):
            # season logged without week / opponent (another source): only the COUNT is known, and it
            # includes bowls and playoff games - compare with regular + postseason team games
            total = len(sc) + post.get((team, yr), 0)
            missed = max(0, total - len(games))
            seasons.append({"yr": yr, "team": team, "n": total, "played": [True] * (total - missed) + [False] * missed, "count_only": True})
            continue
        played = [False] * len(sc)
        for g in games:
            opp, wk = tnorm(g.get("opp")), g.get("wk")
            idx = next((i for i, s in enumerate(sc) if s[2] == opp and not played[i]), None)
            if idx is None:
                idx = next((i for i, s in enumerate(sc) if s[1] == wk and not played[i] and tnorm(g.get("tm")) == team), None)
            if idx is not None:
                played[idx] = True
        seasons.append({"yr": yr, "team": team, "n": len(sc), "played": played})
    known = [s for s in seasons if s["n"]]
    if not known:
        return None
    est = None
    for s in known:
        if sum(s["played"]) >= 0.6 * s["n"]:
            est = s["yr"]
            break
    out = {"seasons": len(known), "est": est, "col_absent": 0, "col_games": 0, "col_run": 0, "col_lost": 0, "col_final": 0, "col_trail": 0, "detail": []}
    if est is None:
        out["tier"] = "no role"
        return out
    last_yr = known[-1]["yr"]
    prev = None
    for s in known:
        if s["yr"] < est:
            prev = s
            continue
        # a whole season missing between two seasons at the same school
        if prev is not None and s["yr"] - prev["yr"] == 2 and prev["team"] == s["team"] and prev["yr"] >= est:
            out["col_lost"] += 1
            out["detail"].append("%d lost season" % (s["yr"] - 1))
        runs, run = [], 0
        for p in s["played"]:
            if p:
                if run:
                    runs.append(run)
                run = 0
            else:
                run += 1
        trail = run
        if run:
            runs.append(run)
        absent = sum(r for r in runs if r >= 2)
        out["col_absent"] += absent
        out["col_games"] += s["n"]
        out["col_run"] = max(out["col_run"], max(runs or [0]))
        if s["yr"] == last_yr:
            out["col_final"] = absent
            out["col_trail"] = trail if (trail >= 2 and not s.get("count_only")) else 0
        out["count_only"] = out.get("count_only", 0) + (1 if s.get("count_only") else 0)
        if absent:
            out["detail"].append("%d missed %d of %d (longest %d)" % (s["yr"], absent, s["n"], max(runs)))
        prev = s
    out["col_rate"] = out["col_absent"] / out["col_games"] if out["col_games"] else None
    out["tier"] = "major" if (out["col_run"] >= 4 or out["col_lost"]) else "minor" if out["col_absent"] >= 2 else "clean"
    return out


def pick_curve(df):
    """Expected career grade from the pick alone, per position: smooth fit on log(pick)."""
    exp = pd.Series(index=df.index, dtype=float)
    for pos, s in df.groupby("pos"):
        x = np.log(s.pick.clip(1, 262).values.astype(float))
        X = np.column_stack([np.ones(len(x)), x, x * x])
        b = np.linalg.lstsq(X, s.career.values.astype(float), rcond=None)[0]
        exp.loc[s.index] = X @ b
    return exp


def tstat(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) < 3 or len(b) < 3:
        return float("nan")
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return float((a.mean() - b.mean()) / se) if se else float("nan")


def spearman(a, b):
    d = pd.DataFrame({"a": a, "b": b}).dropna()
    return (float(d.a.rank().corr(d.b.rank())), len(d)) if len(d) > 5 else (float("nan"), len(d))


BODY = {"knee_major": lambda t: t["body_part"] == "Knee" and t["site"] in ("ACL", "PCL", "MCL", "Meniscus", "Patella", "LCL") and "Tear" in (t["condition"] or ""),
        "lower_soft": lambda t: t["site"] in ("Hamstring", "Quad", "Calf", "Groin", "Hip Flexor") or t["body_part"] == "Thigh",
        "ankle_foot": lambda t: t["body_part"] == "Pedal",
        "knee_any": lambda t: t["body_part"] == "Knee",
        "shoulder": lambda t: t["body_part"] == "Shoulder",
        "head": lambda t: t["body_part"] == "Head"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--study", required=True)
    ap.add_argument("--ds")
    ap.add_argument("--out", default="scripts/jm_injury_study.json")
    a = ap.parse_args()
    st = json.load(open(a.study, encoding="utf-8"))
    rows = st["rows"] if isinstance(st, dict) else st
    df = pd.DataFrame([{k: r.get(k) for k in ("name", "pos", "draftYr", "o_pick", "jm", "career", "provisional", "elite", "starter", "gp", "numSeasons",
                                               "n_avail3", "n_out3", "n_snapMax3", "n_teams4", "lastCollege", "seasons")} for r in rows])
    df = df.rename(columns={"o_pick": "pick", "draftYr": "yr"})
    df["yr"] = df.yr.astype(int)
    print("backtest players:", len(df))

    wk = load_weekly({nrm(n) for n in df.name})
    sched, post = schedules(range(2010, 2025))
    prox = []
    for r in df.itertuples():
        p = availability(wk.get(nrm(r.name), {}), r.yr, sched, post) if nrm(r.name) in wk else None
        prox.append(p or {})
    px = pd.DataFrame(prox)
    df = pd.concat([df.reset_index(drop=True), px.reset_index(drop=True)], axis=1)
    have = df[df.tier.notna()]
    print("with game logs matched to a schedule: %d | tiers: %s" % (len(have), dict(have.tier.value_counts())))
    df["exp_pick"] = pick_curve(df)
    df["res_pick"] = df.career - df.exp_pick
    # NFL availability over the first four seasons from the season rows (games / 17 or 16)
    def nfl_gp(r, k=3):
        ss = [s for s in (r.seasons or []) if s["yr"] < r.yr + k]
        tot = sum((17 if y >= 2021 else 16) for y in range(r.yr, min(r.yr + k, 2026)))
        return sum(s["gp"] for s in ss) / tot if tot else np.nan
    df["nfl_gp3"] = [nfl_gp(r) for r in df.itertuples()]
    res = {"n": len(df), "matched": len(have)}

    use = df[df.tier.isin(["clean", "minor", "major"])].copy()
    print("\n=== A. GAMES MISSED IN COLLEGE vs THE NFL CAREER (n=%d with a college role) ===" % len(use))
    print("%-7s %4s %6s %6s %8s %9s %9s %9s %8s" % ("tier", "n", "pick", "JM", "career", "vs pick", "NFL gp3", "avail3", "out wks"))
    res["tiers"] = {}
    for scope, sub in (("all", use), ("top100", use[use.pick <= 100]), ("QB", use[use.pos == "QB"]), ("RB", use[use.pos == "RB"]), ("WR", use[use.pos == "WR"]), ("TE", use[use.pos == "TE"])):
        print("-- %s" % scope)
        res["tiers"][scope] = {}
        for tier in ("clean", "minor", "major"):
            s = sub[sub.tier == tier]
            if not len(s):
                continue
            rec = {"n": len(s), "pick": float(s.pick.median()), "jm": float(s.jm.mean()), "career": float(s.career.mean()), "res_pick": float(s.res_pick.mean()),
                   "nfl_gp3": float(s.nfl_gp3.mean()), "avail3": float(s.n_avail3.astype(float).mean()), "out3": float(s.n_out3.astype(float).mean()),
                   "elite": float((s.elite > 0).mean()), "empty": float((s.career < 10).mean())}
            res["tiers"][scope][tier] = rec
            print("%-7s %4d %6.0f %6.1f %8.1f %+9.1f %8.0f%% %8.0f%% %8.1f" % (tier, rec["n"], rec["pick"], rec["jm"], rec["career"], rec["res_pick"], 100 * rec["nfl_gp3"], 100 * rec["avail3"], rec["out3"]))
        c, m = sub[sub.tier == "clean"], sub[sub.tier == "major"]
        t1, t2 = tstat(m.res_pick, c.res_pick), tstat(m.nfl_gp3, c.nfl_gp3)
        res["tiers"][scope]["t_res"] = t1; res["tiers"][scope]["t_gp"] = t2
        print("   major vs clean: career vs pick t=%.2f | NFL games played t=%.2f" % (t1, t2))
    for lab, col in (("career vs pick", "res_pick"), ("NFL games played, yrs 1-3", "nfl_gp3"), ("weeks listed out, yrs 1-3", "n_out3"), ("career grade", "career"), ("draft pick", "pick")):
        r, n = spearman(use.col_rate, use[col].astype(float))
        res.setdefault("corr", {})[col] = [r, n]
        print("  college miss rate vs %-28s rho %+.3f (n=%d)" % (lab, r, n))
    # final-season absences: the injury a team drafts
    fin = use[use.col_final >= 3]
    rest = use[use.col_final < 3]
    res["final"] = {"n": len(fin), "career": float(fin.career.mean()), "res_pick": float(fin.res_pick.mean()), "nfl_gp3": float(fin.nfl_gp3.mean()),
                    "rest_gp3": float(rest.nfl_gp3.mean()), "t_res": tstat(fin.res_pick, rest.res_pick), "t_gp": tstat(fin.nfl_gp3, rest.nfl_gp3),
                    "rookie_gp": None}
    print("\n  missed 3+ games in the FINAL college season: n %d | pick %.0f | career %.1f | vs pick %+.1f (t %.2f) | NFL gp yrs 1-3 %.0f%% vs %.0f%% (t %.2f)" %
          (len(fin), fin.pick.median(), fin.career.mean(), fin.res_pick.mean(), res["final"]["t_res"], 100 * fin.nfl_gp3.mean(), 100 * rest.nfl_gp3.mean(), res["final"]["t_gp"]))
    # the model's view: does JM over- or under-rate them (career vs what players with that JM averaged at the position)
    use["exp_jm"] = np.nan
    for pos, s in use.groupby("pos"):
        X = np.column_stack([np.ones(len(s)), s.jm.values, s.jm.values ** 2])
        b = np.linalg.lstsq(X, s.career.values.astype(float), rcond=None)[0]
        use.loc[s.index, "exp_jm"] = X @ b
    use["res_jm"] = use.career - use.exp_jm
    res["res_jm"] = {}
    for tier in ("clean", "minor", "major"):
        s = use[use.tier == tier]
        res["res_jm"][tier] = float(s.res_jm.mean())
    print("  career vs JM grade expectation: clean %+.1f | minor %+.1f | major %+.1f (t major vs clean %.2f)" %
          (res["res_jm"]["clean"], res["res_jm"]["minor"], res["res_jm"]["major"], tstat(use[use.tier == "major"].res_jm, use[use.tier == "clean"].res_jm)))
    maj = use[use.tier == "major"].sort_values("pick")
    res["major_list"] = [{"name": r.name, "pos": r.pos, "yr": r.yr, "pick": int(r.pick), "career": r.career, "res_pick": round(r.res_pick, 1), "gp3": round(r.nfl_gp3, 2),
                          "detail": r.detail} for r in maj.itertuples()]
    print("\n  major college absences, earliest picks first")
    for r in maj.head(45).itertuples():
        print("    %-22s %s %d pick %3d | career %5.1f (%+5.1f vs pick) | NFL gp %3.0f%% | %s" % (r.name, r.pos, r.yr, r.pick, r.career, r.res_pick, 100 * r.nfl_gp3, "; ".join(r.detail)))

    # ------------------------------------------------------------------ B. named injuries
    if a.ds:
        pd_ = json.load(open(a.ds, encoding="utf-8"))
        sk = [p for p in pd_ if p.get("position") in ("QB", "RB", "WR", "TE")]
        print("\n=== B. NAMED INJURIES (Draft Sharks, %d current skill players) ===" % len(sk))
        recs = []
        for p in sk:
            inj = p.get("sipInjuries") or []
            col = [x for x in inj if not x.get("nfl")]
            nfl = [x for x in inj if x.get("nfl")]
            exp = max(1, int(p.get("experience") or 0)) if (p.get("experience") or 0) > 0 else 0
            row = {"name": p["first_name"] + " " + p["last_name"], "pos": p["position"], "exp": int(p.get("experience") or 0),
                   "col_n": len(col), "col_missed": sum(x.get("games_missed") or 0 for x in col),
                   "col_big": int(any((x.get("games_missed") or 0) >= 4 for x in col)),
                   "nfl_n": len(nfl), "nfl_missed": sum(x.get("games_missed") or 0 for x in nfl)}
            for k, f in BODY.items():
                row["col_" + k] = int(any(f(x["sipInjuryType"]) for x in col if x.get("sipInjuryType")))
                row["nfl_" + k] = int(any(f(x["sipInjuryType"]) for x in nfl if x.get("sipInjuryType")))
            recs.append(row)
        ds = pd.DataFrame(recs)
        vets = ds[ds.exp >= 2].copy()   # at least two NFL seasons behind them
        vets["nfl_missed_per_yr"] = vets.nfl_missed / vets.exp
        vets["nfl_inj_per_yr"] = vets.nfl_n / vets.exp
        res["ds"] = {"n": len(ds), "vets": len(vets), "with_college_injury": int((ds.col_n > 0).sum()), "with_big": int(ds.col_big.sum())}
        print("players with any pre-NFL injury on file: %d of %d | one that cost 4+ games: %d" % ((ds.col_n > 0).sum(), len(ds), ds.col_big.sum()))
        print("\n  NFL injuries for players with 2+ seasons (n=%d), by college history" % len(vets))
        res["ds"]["groups"] = {}
        for lab, mask in (("no college injury", vets.col_n == 0), ("college injury, under 4 games", (vets.col_n > 0) & (vets.col_big == 0)), ("college injury, 4+ games", vets.col_big == 1)):
            s = vets[mask]
            rec = {"n": len(s), "missed_per_yr": float(s.nfl_missed_per_yr.mean()), "inj_per_yr": float(s.nfl_inj_per_yr.mean()), "exp": float(s.exp.mean())}
            res["ds"]["groups"][lab] = rec
            print("    %-32s n %3d | NFL games missed per season %.2f | NFL injuries per season %.2f | avg experience %.1f" % (lab, rec["n"], rec["missed_per_yr"], rec["inj_per_yr"], rec["exp"]))
        res["ds"]["t_big_vs_none"] = tstat(vets[vets.col_big == 1].nfl_missed_per_yr, vets[vets.col_n == 0].nfl_missed_per_yr)
        res["ds"]["t_any_vs_none"] = tstat(vets[vets.col_n > 0].nfl_missed_per_yr, vets[vets.col_n == 0].nfl_missed_per_yr)
        print("    t (4+ games vs none) %.2f | t (any vs none) %.2f" % (res["ds"]["t_big_vs_none"], res["ds"]["t_any_vs_none"]))
        print("\n  does the same body part come back?  (players with 2+ NFL seasons)")
        res["ds"]["recur"] = {}
        for k in BODY:
            had, not_ = vets[vets["col_" + k] == 1], vets[vets["col_" + k] == 0]
            if len(had) < 5:
                continue
            nk = "nfl_knee_any" if k == "knee_major" else "nfl_" + k
            rec = {"n": len(had), "rate_had": float(had[nk].mean()), "rate_not": float(not_[nk].mean()), "missed_had": float(had.nfl_missed_per_yr.mean()), "missed_not": float(not_.nfl_missed_per_yr.mean())}
            res["ds"]["recur"][k] = rec
            print("    college %-11s n %3d | NFL injury to that area %.0f%% vs %.0f%% without | NFL games missed per season %.2f vs %.2f" %
                  (k, rec["n"], 100 * rec["rate_had"], 100 * rec["rate_not"], rec["missed_had"], rec["missed_not"]))
        # check the proxy against the named records
        dsn = {nrm(r["name"]): r for r in recs}
        both = use[[nrm(n) in dsn for n in use.name]].copy()
        both["ds_big"] = [dsn[nrm(n)]["col_big"] for n in both.name]
        both["ds_missed"] = [dsn[nrm(n)]["col_missed"] for n in both.name]
        tp = int(((both.tier == "major") & (both.ds_big == 1)).sum())
        res["ds"]["proxy_check"] = {"n": len(both), "ds_big": int(both.ds_big.sum()), "proxy_major": int((both.tier == "major").sum()), "both": tp,
                                    "rho": spearman(both.col_absent, both.ds_missed)[0]}
        print("\n  proxy check on %d players in both sources: named 4+ game college injury %d | proxy 'major' %d | both %d | rank agreement of games missed %.2f" %
              (len(both), both.ds_big.sum(), (both.tier == "major").sum(), tp, res["ds"]["proxy_check"]["rho"]))
        # survivors only: college injury vs career grade against the pick
        both["ds_any"] = [int(dsn[nrm(n)]["col_n"] > 0) for n in both.name]
        for lab, m in (("named college injury 4+ games", both.ds_big == 1), ("any named college injury", both.ds_any == 1), ("none on file", both.ds_any == 0)):
            s = both[m]
            print("    %-30s n %3d | pick %3.0f | career %.1f | vs pick %+.1f | NFL gp yrs 1-3 %.0f%%" % (lab, len(s), s.pick.median(), s.career.mean(), s.res_pick.mean(), 100 * s.nfl_gp3.mean()))
            res["ds"].setdefault("survivors", {})[lab] = {"n": len(s), "pick": float(s.pick.median()), "career": float(s.career.mean()), "res_pick": float(s.res_pick.mean()), "gp3": float(s.nfl_gp3.mean())}
        res["ds"]["coverage"] = {int(y): [int(len(both[both.yr == y])), int(len(use[use.yr == y]))] for y in sorted(use.yr.unique())}

    keep = ["name", "pos", "yr", "pick", "jm", "career", "res_pick", "nfl_gp3", "tier", "col_absent", "col_games", "col_run", "col_lost", "col_final", "col_trail", "detail"]
    out_rows = json.loads(df[keep].to_json(orient="records"))
    json.dump({"res": res, "rows": out_rows}, open(a.out, "w", encoding="utf-8"), separators=(",", ":"), default=float)
    print("\nwrote", a.out)


if __name__ == "__main__":
    main()
