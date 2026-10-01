"""jm_career_window_study.py - how an early look at a career compares with the finished one.

Jack (2026-10-01): "players that have looked great but only a couple years into their career,
how do they grade vs guys with 8+ years already".

The career grade (scripts/build_outcome_grades.py) is the best four seasons inside the first six,
weighted 40/30/20/10. A class with fewer than four seasons is graded on what it has played, with
the weights renormalised (provisional). This script replays that rule on every drafted skill
player since 2000 and asks:

  1. EARLY LOOK -> FINAL   the grade after 1, 2, 3, 4, 5 seasons against the six-season grade
  2. LONG CAREERS          the six-season grade against the best four seasons of the WHOLE career,
                           and how much production comes after year six, by position
  3. PROJECTION            a per-position, per-seasons-played regression of the final grade on the
                           early grade, applied to today's provisional backtest players

Sources: data/all_players.js (ALL_PLAYERS_DB season lines - complete careers; the weekly files
drop older seasons for some veterans), pbp_cache/draft_picks.parquet (nflverse).

    python scripts/jm_career_window_study.py [--out scripts/jm_career_window_study.json]
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import generate_extended_backtest as gb  # noqa: E402
import build_outcome_grades as bog  # noqa: E402

CACHE = os.path.join(os.path.dirname(ROOT), "pbp_cache")
LAST = 2025
W = bog.WEIGHTS


def nrm(s):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", str(s or "").lower()))


def grade_after(vals_by_offset, k):
    """Career grade as the site would have printed it k seasons after the draft (k >= 1)."""
    use = min(k, len(W))
    window = sorted((v for off, v in vals_by_offset.items() if off < min(k, bog.WINDOW)), reverse=True)[:use]
    window += [0.0] * (use - len(window))
    return sum(w * v for w, v in zip(W, window)) / sum(W[:use])


def grade_whole(vals_by_offset):
    window = sorted(vals_by_offset.values(), reverse=True)[:4]
    window += [0.0] * (4 - len(window))
    return sum(w * v for w, v in zip(W, window))


def spearman(a, b):
    a, b = pd.Series(a), pd.Series(b)
    return float(a.rank().corr(b.rank())) if len(a) > 2 else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="scripts/jm_career_window_study.json")
    a = ap.parse_args()

    txt = open("data/all_players.js", encoding="utf-8").read()
    db = json.loads(txt[txt.index("["):txt.rindex("]") + 1])
    seas, posof = {}, {}     # record index -> seasons / position
    by_key = defaultdict(list)   # (nrm name, pos) -> [record index]
    for i, p in enumerate(db):
        pos = "RB" if p.get("pos") in ("HB", "FB") else p.get("pos")
        if pos not in bog.CURVES:
            continue
        ss = [{"yr": int(c["yr"]), "gp": int(c.get("gp") or 0), "ppg": float(c.get("ppg") or 0)} for c in p.get("career", []) if c.get("yr") and int(c["yr"]) <= LAST]
        if ss:
            seas[i] = ss; posof[i] = pos
            by_key[(nrm(re.sub(r"\s*\(.*?\)\s*$", "", p["name"])), pos)].append(i)
            by_key[(nrm(re.sub(r"\s*\(.*?\)\s*$", "", p["name"])), "*")].append(i)
    board = defaultdict(list)
    for i, ss in seas.items():
        for x in ss:
            if x["gp"] >= bog.RANK_MIN_GP:
                board[(x["yr"], posof[i])].append(x["ppg"])
    for k in board:
        board[k].sort(reverse=True)

    def values(name, pos, dy):
        out = {}
        for s in seas[name]:
            if s["yr"] < dy:
                continue
            lb = board.get((s["yr"], pos), [])
            rank = 1 + sum(1 for v in lb if v > s["ppg"])
            out[s["yr"] - dy] = bog.curve(pos, rank) * min(1.0, s["gp"] / bog.FULL_GP) if s["gp"] >= 4 else 0.0
        return out

    dp = pd.read_parquet(os.path.join(CACHE, "draft_picks.parquet"))
    dp = dp[(dp.season >= 2000) & (dp.season <= 2024) & dp.position.isin(["QB", "RB", "WR", "TE", "FB"])]
    rows = []
    for r in dp.itertuples():
        pos = "RB" if r.position == "FB" else r.position
        ok = lambda n: any(0 <= s["yr"] - r.season <= 3 for s in seas[n]) and min(s["yr"] for s in seas[n]) >= r.season
        # a same-name player from another era is not him: first season on file must sit at the draft year
        cands = [n for n in by_key.get((nrm(r.pfr_player_name), pos), []) if ok(n)]
        if not cands:   # drafted at one position, played another (Cordarrelle Patterson, Tim Tebow)
            cands = [n for n in by_key.get((nrm(r.pfr_player_name), "*"), []) if ok(n)]
        if cands:
            pos = posof[cands[0]]
        vals = values(cands[0], pos, r.season) if cands else {}
        elapsed = LAST - r.season + 1
        row = {"name": r.pfr_player_name, "pos": pos, "yr": int(r.season), "pick": int(r.pick), "elapsed": elapsed,
               "vals": {int(k): round(v, 1) for k, v in sorted(vals.items())}, "matched": bool(cands)}
        for k in range(1, 7):
            row["g%d" % k] = round(grade_after(vals, k), 1) if elapsed >= k else None
        row["gAll"] = round(grade_whole(vals), 1)
        row["late_starter"] = sum(1 for off, v in vals.items() if off >= 6 and v >= bog.STARTER)
        row["late_elite"] = sum(1 for off, v in vals.items() if off >= 6 and v >= bog.ELITE)
        row["starter6"] = sum(1 for off, v in vals.items() if off < 6 and v >= bog.STARTER)
        row["seasons_played"] = sum(1 for off, v in vals.items() if v > 0)
        rows.append(row)
    df = pd.DataFrame(rows)
    print("drafted skill players 2000-2024: %d (%d with NFL seasons on file)" % (len(df), int(df.matched.sum())))
    res = {"n": len(df)}

    # ---------------- 1. early look -> final (classes with six seasons played out: 2000-2020)
    full = df[df.elapsed >= 6].copy()
    print("\n=== 1. EARLY LOOK vs SIX-SEASON GRADE  (classes 2000-2020, n=%d) ===" % len(full))
    res["early"] = {}
    for k in (1, 2, 3, 4, 5):
        g = full["g%d" % k]
        d = full.g6 - g
        res["early"][k] = {"rho": spearman(g, full.g6), "mae": float(d.abs().mean())}
        print("after %d season(s): rank agreement with final %.3f | avg |change| %.1f" % (k, res["early"][k]["rho"], d.abs().mean()))
    bands = [(80, 101, "80+"), (65, 80, "65-79"), (50, 65, "50-64"), (35, 50, "35-49"), (20, 35, "20-34"), (5, 20, "5-19"), (-1, 5, "under 5")]
    res["bands"] = {}
    for k in (2, 3):
        print("\n  grade after %d seasons -> final grade" % k)
        print("  %-8s %5s %9s %9s %8s %8s %8s %8s" % ("band", "n", "avg then", "avg final", "p25", "p75", ">=70", "<45"))
        res["bands"][k] = []
        for lo, hi, lab in bands:
            s = full[(full["g%d" % k] >= lo) & (full["g%d" % k] < hi)]
            if not len(s):
                continue
            rec = {"band": lab, "n": len(s), "then": float(s["g%d" % k].mean()), "final": float(s.g6.mean()),
                   "p25": float(s.g6.quantile(.25)), "p75": float(s.g6.quantile(.75)),
                   "ge70": float((s.g6 >= 70).mean()), "lt45": float((s.g6 < 45).mean())}
            res["bands"][k].append(rec)
            print("  %-8s %5d %9.1f %9.1f %8.1f %8.1f %7.0f%% %7.0f%%" % (lab, rec["n"], rec["then"], rec["final"], rec["p25"], rec["p75"], 100 * rec["ge70"], 100 * rec["lt45"]))
    # by position for the "looked great after two / three" group
    print("\n  looked great early (grade 70+), by position -> final")
    res["great_early"] = {}
    for k in (2, 3):
        for pos in ("QB", "RB", "WR", "TE"):
            s = full[(full["g%d" % k] >= 70) & (full.pos == pos)]
            if len(s):
                rec = {"n": len(s), "then": float(s["g%d" % k].mean()), "final": float(s.g6.mean()), "ge70": float((s.g6 >= 70).mean()),
                       "lt50": float((s.g6 < 50).mean()), "late_starter": float(s[s.elapsed >= 10].late_starter.mean()) if (s.elapsed >= 10).any() else None}
                res["great_early"]["%d_%s" % (k, pos)] = rec
                print("  after %d, %s: n %3d | then %.1f -> final %.1f | still 70+ %.0f%% | under 50 %.0f%% | starter seasons after yr 6: %s" %
                      (k, pos, rec["n"], rec["then"], rec["final"], 100 * rec["ge70"], 100 * rec["lt50"], "%.1f" % rec["late_starter"] if rec["late_starter"] is not None else "-"))
    # quiet starts that became strong careers
    for k in (2, 3):
        s = full[full.g6 >= 60]
        print("  of %d strong finished careers (60+), share graded under 35 after %d seasons: %.0f%%" % (len(s), k, 100 * (s["g%d" % k] < 35).mean()))
        res["slow_start_%d" % k] = float((s["g%d" % k] < 35).mean())
        for pos in ("QB", "RB", "WR", "TE"):
            sp = s[s.pos == pos]
            print("      %s: %.0f%% of %d" % (pos, 100 * (sp["g%d" % k] < 35).mean(), len(sp)))
            res["slow_start_%d_%s" % (k, pos)] = [float((sp["g%d" % k] < 35).mean()), len(sp)]

    # ---------------- 2. long careers (ten seasons elapsed: classes 2000-2016)
    long_ = df[df.elapsed >= 10].copy()
    print("\n=== 2. SIX-SEASON GRADE vs WHOLE CAREER  (classes 2000-2016, n=%d) ===" % len(long_))
    print("rank agreement six-season vs whole-career grade: %.3f" % spearman(long_.g6, long_.gAll))
    res["long"] = {"rho": spearman(long_.g6, long_.gAll), "n": len(long_), "pos": {}}
    for pos in ("QB", "RB", "WR", "TE"):
        s = long_[long_.pos == pos]
        good = s[s.g6 >= 50]
        gain = s.gAll - s.g6
        rec = {"n": len(s), "gain10": int((gain >= 10).sum()), "gain10_share_of_real": float((gain[s.gAll >= 30] >= 10).mean()),
               "good_n": len(good), "late_starter_good": float(good.late_starter.mean()), "late_any_good": float((good.late_starter > 0).mean()),
               "starter6_good": float(good.starter6.mean())}
        res["long"]["pos"][pos] = rec
        print("  %s: n %4d | whole-career grade 10+ higher than six-season: %3d players (%.0f%% of careers worth 30+) | careers graded 50+: %3d, starter seasons inside six %.1f, after six %.1f (%.0f%% had any)" %
              (pos, rec["n"], rec["gain10"], 100 * rec["gain10_share_of_real"], rec["good_n"], rec["starter6_good"], rec["late_starter_good"], 100 * rec["late_any_good"]))
    late = long_.assign(gain=long_.gAll - long_.g6).sort_values("gain", ascending=False).head(25)
    res["late_bloomers"] = late[["name", "pos", "yr", "pick", "g6", "gAll", "gain"]].to_dict("records")
    print("\n  biggest late bloomers (whole career minus six-season grade)")
    for r in late.itertuples():
        print("    %-22s %s %d  six %.0f -> whole %.0f" % (r.name, r.pos, r.yr, r.g6, r.gAll))
    # eight-plus-year careers vs short ones at the same six-season grade
    print("\n  same six-season grade, different length (classes 2000-2016)")
    res["length"] = []
    for lo, hi in ((70, 101), (50, 70), (30, 50)):
        s = long_[(long_.g6 >= lo) & (long_.g6 < hi)]
        l8 = s[s.seasons_played >= 8]
        rec = {"band": "%d-%d" % (lo, hi - 1 if hi < 101 else 100), "n": len(s), "share8": float(len(l8) / max(1, len(s))),
               "avg_seasons": float(s.seasons_played.mean()), "late_starter": float(s.late_starter.mean())}
        res["length"].append(rec)
        print("    grade %s: n %3d | played 8+ seasons %.0f%% | avg productive seasons %.1f | starter seasons after yr 6 %.1f" %
              (rec["band"], rec["n"], 100 * rec["share8"], rec["avg_seasons"], rec["late_starter"]))

    # ---------------- 3. projection of provisional grades
    # final = a + b * early, fitted per (position, seasons played) on finished classes; leave-one-class-out error
    print("\n=== 3. PROJECTING A PROVISIONAL GRADE ===")
    res["proj"] = {}
    for pos in ("QB", "RB", "WR", "TE"):
        for k in (1, 2, 3, 4, 5):
            s = full[full.pos == pos]
            x, y = s["g%d" % k].values.astype(float), s.g6.values.astype(float)
            X = np.column_stack([np.ones(len(x)), x, x * x])
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            # leave-one-class-out
            err_raw, err_fit = [], []
            for yr in sorted(s.yr.unique()):
                tr, te = (s.yr != yr).values, (s.yr == yr).values
                b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
                err_fit.extend(np.abs(X[te] @ b - y[te])); err_raw.extend(np.abs(x[te] - y[te]))
            res["proj"]["%s_%d" % (pos, k)] = {"beta": [float(v) for v in beta], "mae_raw": float(np.mean(err_raw)), "mae_fit": float(np.mean(err_fit)), "n": len(s)}
            print("  %s after %d: final = %.1f + %.3f g + %.5f g^2 | error raw %.1f -> projected %.1f (out of class)" % (pos, k, beta[0], beta[1], beta[2], np.mean(err_raw), np.mean(err_fit)))

    def project(pos, k, g):
        b = res["proj"]["%s_%d" % (pos, k)]["beta"]
        return float(max(0.0, min(100.0, b[0] + b[1] * g + b[2] * g * g)))

    # today's backtest players still inside their six-season window
    G = json.load(open("scripts/jm_outcome_grades.json", encoding="utf-8"))["players"]
    T = json.load(open("scripts/jm_table.json", encoding="utf-8"))["rows"] if os.path.exists("scripts/jm_table.json") else []
    posmap = {"%s|%d" % (r["name"], r["o_yr"]): (r["pos"], r["jm"], r["o_pick"]) for r in T}
    cur = []
    for key, v in G.items():
        name, yr = key.rsplit("|", 1)
        yr = int(yr)
        k = LAST - yr + 1
        if key not in posmap or v["grade"] is None:
            continue
        pos, jm, pick = posmap[key]
        proj = project(pos, k, v["grade"]) if 1 <= k <= 5 else v["grade"]
        cur.append({"name": name, "pos": pos, "yr": yr, "pick": pick, "jm": jm, "seasons": k, "grade": v["grade"], "proj": round(proj, 1), "open": k < 6})
    res["current"] = cur
    cd = pd.DataFrame(cur)
    if len(cd):
        print("\n  backtest players still inside the six-season window: %d of %d" % (int(cd.open.sum()), len(cd)))
        for yr in sorted(cd.yr.unique()):
            s = cd[cd.yr == yr]
            print("    class %d (%d seasons): avg grade now %.1f -> projected final %.1f" % (yr, s.seasons.iat[0], s.grade.mean(), s.proj.mean()))
        top = cd[cd.open & (cd.grade >= 55)].sort_values("grade", ascending=False)
        print("\n  open-window players graded 55+ today")
        for r in top.itertuples():
            print("    %-24s %s %d (%d seasons)  now %.0f -> projected %.0f" % (r.name, r.pos, r.yr, r.seasons, r.grade, r.proj))
    json.dump({"res": res, "rows": rows}, open(a.out, "w", encoding="utf-8"), separators=(",", ":"), default=float)
    print("\nwrote", a.out)


if __name__ == "__main__":
    main()
