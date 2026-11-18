"""jm_competition_study.py - who do prospects put up big points against, and does it predict the NFL?

Game-by-game: every pre-draft college game of the 2017-2024 drafted skill players (QB/RB/WR/TE) is
tagged with how strong the opponent was, three ways:
  def    SP+ overall defense (z within season; FCS / unrated = soft)
  unit   SP+ PASS defense for QB/WR/TE, RUSH defense for RB (falls back to overall when missing)
  nfl    real NFL talent on that defense: the opponent's future-drafted DBs (for QB/WR/TE) or front
         seven (for RB) on the roster that season, from nflverse draft picks (drafted 1-2 years later
         = 1.0, 3 years later = 0.5; rounds 1-2 x1.5, rounds 5-7 x0.6)
Per player (career, pre-draft, >= 3 games in a bucket):
  ppg_strong / ppg_weak    points per game vs the top quarter / the softest 30% (incl. FCS)
  r_strong                 ppg_strong / ppg_all  (holds up against good defenses?)
  soft_share               share of all points scored against the softest 30%
  big_strong               rate of big games (>= position 75th-pct game) against the top quarter
Evaluation per position vs the graded NFL career outcome (jm_outcome_grades.json):
  rho        Spearman(feature, grade)
  |pick      Spearman(feature, grade residual after log pick)
  |JM        Spearman(feature, grade residual after JM)          <- signal JM is missing
  yrs+       draft years (of 8) where the |JM correlation is positive
  LOYO       pooled out-of-year Spearman of OLS(grade ~ JM + feature percentile) minus JM alone, each
             draft year held out. Adding ANY input costs ~.01-.03 here, so judge it with the perm mode.

Modes (run from the repo root):
  python -I scripts/jm_competition_study.py study ROWS [--out scripts/jm_competition_<date>.json]
      ROWS = scripts/jm_projpick_eval.js output; its "real" rows are the live JM per backtest player.
      Make it with an empty scenario file: write {} to s.json, then
      node scripts/jm_projpick_eval.js --scenarios s.json --out rows.json
  python -I scripts/jm_competition_study.py perm N [--src study.json] [--out scripts/jm_competition_perm_<date>.json]
      shuffle test: every feature vs N shuffled copies of itself (p-values for LOYO and |JM)
  python -I scripts/jm_competition_study.py view2027 [--out scripts/jm_competition_2027_<date>.json]
      the current class's 2026 games: opponent SP+ defense rank, points, PPG vs top-30 defenses vs soft
Options: --picks <nflverse draft_picks.csv> (default E:/MyFantasyFootball/trivia_daily_cache/draft_picks.csv)
SP+ ratings with pass / rush defense splits are cached in scripts/_sp_splits.json (pulled from CFBD with
cfbd_config.CFBD_API_KEY when a season is missing). CFBD stopped publishing the splits after 2024, so 2025+
use overall defense.

Result 2026-11-18 (535 players, 64 feature tests, 200 shuffles):
  RB  holding up vs NFL-caliber fronts (r_strong_nfl): beyond JM +.25 (p .015), positive 6 of 8 classes,
      LOYO beats 96.5% of shuffles - the one competition input JM is missing.
  QB  points vs weak defenses (ppg_weak_def): beyond JM -.39 (p .005), 5 of 7 classes - JM over-credits
      production against soft defenses (overall PPG -.22).
  WR / TE  nothing competition-specific; raw college PPG beyond JM is negative for QB / WR / TE.
  Not tested in the real model yet (needs flag-gated inputs in app.js + jm_optimize.js --exp).
  Earlier and different: scripts/jm_sos_analysis.py (SP+-adjusted season PPG, 2026-09-30, no ship).
"""
import csv
import datetime
import json
import math
import os
import random
import re
import sys
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARGS = sys.argv[1:]
TODAY = datetime.date.today().isoformat()


def _opt(k, d=None):
    return ARGS[ARGS.index(k) + 1] if k in ARGS and ARGS.index(k) + 1 < len(ARGS) else d


PICKS = _opt("--picks", "E:/MyFantasyFootball/trivia_daily_cache/draft_picks.csv")
SPF = os.path.join(ROOT, "scripts", "_sp_splits.json")
GRADES = os.path.join(ROOT, "scripts", "jm_outcome_grades.json")
WEEKLY_FILES = ["data/college_weekly_1.js", "data/college_weekly_2.js", "data/college_weekly_3.js",
                "data/college_weekly_devy.js", "data/college_stats_devy.js"]
SOFT = -1.5                       # strength given to FCS / unrated opponents
DB_POS = {"CB", "DB", "S", "SAF", "FS", "SS"}
FRONT_POS = {"DE", "DT", "DL", "NT", "LB", "OLB", "ILB", "EDGE"}
POSITIONS = ("QB", "RB", "WR", "TE")


# ---------- helpers ----------
def nrm(s):
    s = (s or "").lower()
    s = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def tnorm(t):
    """College / team name -> comparable key (nflverse 'Ohio St.' == CFBD 'Ohio State')."""
    t = (t or "").strip()
    alias = {"Miami (FL)": "Miami", "Southern California": "USC", "Louisiana St.": "LSU",
             "Mississippi": "Ole Miss", "Brigham Young": "BYU", "Texas Christian": "TCU", "Southern Methodist": "SMU",
             "Alabama-Birmingham": "UAB", "Ala-Birmingham": "UAB", "Nevada-Las Vegas": "UNLV", "North Carolina St.": "NC State",
             "Boston Col.": "Boston College", "Central Florida": "UCF", "Texas-San Antonio": "UTSA",
             "Texas-El Paso": "UTEP", "Louisiana-Lafayette": "Louisiana", "Louisiana-Monroe": "UL Monroe",
             "Hawaii": "Hawai'i", "San Jose St.": "San José State", "Massachusetts": "UMass", "Connecticut": "UConn",
             "Appalachian St.": "App State", "Middle Tennessee St.": "Middle Tennessee", "Middle Tenn. St.": "Middle Tennessee",
             "Southern Mississippi": "Southern Miss", "Bowling Green St.": "Bowling Green", "Fla. Atlantic": "Florida Atlantic",
             "Sam Houston St.": "Sam Houston"}
    t = alias.get(t, t)
    t = re.sub(r"\bSt\.$", "State", t)
    return re.sub(r"[^a-z0-9]", "", t.lower().replace("&", "and").replace("é", "e"))


def spearman(xs, ys):
    n = len(xs)
    if n < 5:
        return float("nan")
    def rank(a):
        idx = sorted(range(n), key=lambda i: a[i]); r = [0.0] * n; i = 0
        while i < n:
            j = i
            while j + 1 < n and a[idx[j + 1]] == a[idx[i]]:
                j += 1
            for k in range(i, j + 1):
                r[idx[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx)); dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return num / (dx * dy) if dx and dy else float("nan")


def resid(xs, ys):
    n = len(xs); mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0
    return [y - (my + b * (x - mx)) for x, y in zip(xs, ys)]


def ols2(X, y):
    """y ~ 1 + X[:,0] + X[:,1] by normal equations (3x3)."""
    rows = [[1.0, a, b] for a, b in X]
    A = [[sum(r[i] * r[j] for r in rows) for j in range(3)] for i in range(3)]
    v = [sum(r[i] * t for r, t in zip(rows, y)) for i in range(3)]
    for i in range(3):
        p = max(range(i, 3), key=lambda k: abs(A[k][i])); A[i], A[p] = A[p], A[i]; v[i], v[p] = v[p], v[i]
        if abs(A[i][i]) < 1e-12:
            return [sum(y) / len(y), 0, 0]
        for k in range(3):
            if k != i:
                f = A[k][i] / A[i][i]
                A[k] = [a - f * c for a, c in zip(A[k], A[i])]; v[k] -= f * v[i]
    return [v[i] / A[i][i] for i in range(3)]


def fpts(g):
    return (g.get("py", 0) / 25 + g.get("ptd", 0) * 4 - g.get("int", 0) * 2 + g.get("ry", 0) / 10 + g.get("rtd", 0) * 6
            + g.get("rec", 0) * 0.5 + g.get("rcy", 0) / 10 + g.get("rctd", 0) * 6 - g.get("fl", 0) * 2)


def load_weekly(wanted=None):
    out = {}
    key_fix = re.compile(r"([{,])(\w+):")
    for f in WEEKLY_FILES:
        txt = open(os.path.join(ROOT, f), encoding="utf-8").read()
        for m in re.finditer(r"COLLEGE_WEEKLY\[(['\"])(.+?)\1\](?:\[(\d{4})\])?\s*=\s*(\{.*?\}|\[.*?\]);", txt):
            name = m.group(2).replace("\\'", "'")
            if wanted is not None and nrm(name) not in wanted:
                continue
            try:
                val = json.loads(key_fix.sub(r'\1"\2":', m.group(4)))
            except ValueError:
                continue
            d = out.setdefault(nrm(name), {"name": name, "seasons": {}})
            if m.group(3):
                d["seasons"][int(m.group(3))] = val
            elif isinstance(val, dict):
                for yr, games in val.items():
                    d["seasons"][int(yr)] = games
    return out


def sp_splits(years):
    cache = json.load(open(SPF)) if os.path.exists(SPF) else {}
    missing = [y for y in years if str(y) not in cache]
    if missing:
        import requests
        sys.path.insert(0, ROOT)
        from cfbd_config import CFBD_API_KEY
        for y in missing:
            r = requests.get("https://apinext.collegefootballdata.com/ratings/sp", headers={"Authorization": "Bearer " + CFBD_API_KEY},
                             params={"year": y}, timeout=40)
            rows = r.json() if r.status_code == 200 else []
            cache[str(y)] = {x["team"]: {"def": (x.get("defense") or {}).get("rating"), "pass": (x.get("defense") or {}).get("passing"),
                                         "rush": (x.get("defense") or {}).get("rushing"), "conf": x.get("conference")}
                             for x in rows if x.get("team")}
            print("  SP+ %d: %d teams" % (y, len(cache[str(y)])), flush=True)
            time.sleep(0.4)
        json.dump(cache, open(SPF, "w"))
    return {int(y): t for y, t in cache.items()}


# ---------- opponent strength ----------
def zscores(vals):
    v = [x for x in vals.values() if x is not None]
    mu = sum(v) / len(v); sd = math.sqrt(sum((x - mu) ** 2 for x in v) / len(v)) or 1
    return {k: (x - mu) / sd for k, x in vals.items() if x is not None}


def strength_tables(sp):
    """yr -> teamkey -> {def, pass, rush} (positive = strong defense); NFL talent per (season, team)."""
    STR = {}
    for y, teams in sp.items():
        zd = zscores({tnorm(k): -t["def"] if t["def"] is not None else None for k, t in teams.items()})
        zp = zscores({tnorm(k): t["pass"] for k, t in teams.items()}) if any(t["pass"] is not None for t in teams.values()) else {}
        zr = zscores({tnorm(k): t["rush"] for k, t in teams.items()}) if any(t["rush"] is not None for t in teams.values()) else {}
        STR[y] = {k: {"def": zd[k], "pass": zp.get(k, zd[k]), "rush": zr.get(k, zd[k])} for k in zd}
    talent = defaultdict(lambda: {"db": 0.0, "front": 0.0})
    unmatched = defaultdict(int)
    fbs_keys = set().union(*[set(v) for v in STR.values()])
    for r in csv.DictReader(open(PICKS, encoding="utf-8")):
        D = int(r["season"]); pos = r["position"]
        grp = "db" if pos in DB_POS else "front" if pos in FRONT_POS else None
        if grp is None or D < 2013:
            continue
        k = tnorm(r["college"])
        if k not in fbs_keys:
            unmatched[r["college"]] += 1
            continue
        rd = int(r["round"]); rw = 1.5 if rd <= 2 else 1.0 if rd <= 4 else 0.6
        for S, yw in ((D - 1, 1.0), (D - 2, 1.0), (D - 3, 0.5)):
            talent[(S, k)][grp] += rw * yw
    return STR, talent, unmatched


def opp_strength(STR, talent, yr, opp):
    k = tnorm(opp)
    s = STR.get(yr, {})
    if k not in s:
        for tk in s:
            if tk.startswith(k) or k.startswith(tk):
                k = tk; break
    if k not in s:
        return None          # FCS / unrated
    t = talent.get((yr, k), {"db": 0.0, "front": 0.0})
    return {**s[k], "db": t["db"], "front": t["front"]}


# ---------- study ----------
NAMES = ["ppg_all"] + [p + m for m in ("def", "unit", "nfl") for p in ("ppg_strong_", "ppg_weak_", "r_strong_", "big_strong_", "soft_share_")]


def features(gs, cuts):
    f = {}
    if len(gs) < 6:
        return f
    allp = sum(g["pts"] for g in gs) / len(gs)
    f["ppg_all"] = allp
    tot = sum(max(0, g["pts"]) for g in gs)
    for m in ("def", "unit", "nfl"):
        hi, lo = cuts[m]
        st = [g for g in gs if g[m] >= hi]
        wk = [g for g in gs if g[m] <= lo]
        if len(st) >= 3:
            ps = sum(g["pts"] for g in st) / len(st)
            f["ppg_strong_" + m] = ps
            f["r_strong_" + m] = ps / allp if allp > 0 else None
            f["big_strong_" + m] = sum(1 for g in st if g["pts"] >= cuts["big"]) / len(st)
        if len(wk) >= 3:
            f["ppg_weak_" + m] = sum(g["pts"] for g in wk) / len(wk)
        if tot > 0:
            f["soft_share_" + m] = sum(max(0, g["pts"]) for g in gs if g[m] <= lo) / tot
    return {k: v for k, v in f.items() if v is not None}


def pct_rank(values):
    have = sorted(v for v in values if v is not None)
    def p(v):
        return (sum(1 for t in have if t < v) + sum(1 for t in have if t == v) / 2) / len(have)
    return [p(v) if v is not None else 0.5 for v in values]


def loyo_delta(rows, xs):
    """Pooled out-of-year Spearman of OLS(grade ~ JM + x) minus JM alone; xs aligned with rows."""
    pc, pj, t = [], [], []
    for y in range(2017, 2025):
        tr = [i for i, r in enumerate(rows) if r["yr"] != y]; te = [i for i, r in enumerate(rows) if r["yr"] == y]
        if not te:
            continue
        b = ols2([(rows[i]["jm"], xs[i]) for i in tr], [rows[i]["cs"] for i in tr])
        for i in te:
            pc.append(b[0] + b[1] * rows[i]["jm"] + b[2] * xs[i]); pj.append(rows[i]["jm"]); t.append(rows[i]["cs"])
    return spearman(pc, t) - spearman(pj, t)


def partial_jm(rows, raw):
    idx = [i for i, v in enumerate(raw) if v is not None]
    rj = resid([rows[i]["jm"] for i in idx], [rows[i]["cs"] for i in idx])
    return spearman([raw[i] for i in idx], rj)


def run_study(rows_path, out_path):
    STR, talent, unmatched = strength_tables(sp_splits(range(2013, int(TODAY[:4]) + 1)))
    grades = json.load(open(GRADES, encoding="utf-8"))["players"]
    bt = []
    for n, pos, yr, jm, pick, dr in json.load(open(rows_path))["real"]:
        g = grades.get("%s|%d" % (n, yr))
        if g and g.get("grade") is not None:
            bt.append({"n": n, "pos": pos, "yr": yr, "jm": jm, "pick": pick if isinstance(pick, int) else 300, "cs": g["grade"]})
    weekly = load_weekly({nrm(r["n"]) for r in bt})

    def player_games(nk, pos, before_yr):
        out = []
        for yr, gl in weekly.get(nk, {}).get("seasons", {}).items():
            if yr >= before_yr or yr < 2013 or not isinstance(gl, list):
                continue
            for g in gl:
                if not isinstance(g, dict) or not g.get("opp"):
                    continue
                s = opp_strength(STR, talent, yr, g["opp"])
                out.append({"yr": yr, "opp": g["opp"], "pts": fpts(g),
                            "def": s["def"] if s else SOFT, "unit": s["rush" if pos == "RB" else "pass"] if s else SOFT,
                            "nfl": s["front" if pos == "RB" else "db"] if s else 0.0})
        return out

    games = {r["n"]: player_games(nrm(r["n"]), r["pos"], r["yr"]) for r in bt}
    CUTS = {}
    for pos in POSITIONS:
        pg = [g for r in bt if r["pos"] == pos for g in games[r["n"]]]
        CUTS[pos] = {}
        for m in ("def", "unit", "nfl"):
            vals = sorted(g[m] for g in pg)
            CUTS[pos][m] = (vals[int(len(vals) * 0.75)], vals[int(len(vals) * 0.30)])
        pts = sorted(g["pts"] for g in pg)
        CUTS[pos]["big"] = pts[int(len(pts) * 0.75)]
        CUTS[pos]["n_games"] = len(pg)
    FEATS = {r["n"]: features(games[r["n"]], CUTS[r["pos"]]) for r in bt}

    out = {"date": TODAY, "cuts": CUTS, "unmatched_colleges": sorted(unmatched.items(), key=lambda kv: -kv[1])[:25],
           "coverage": {}, "results": {}}
    print("players with a grade: %d; with >= 6 logged pre-draft games: %d" % (len(bt), sum(1 for r in bt if FEATS[r["n"]])))
    for pos in POSITIONS:
        rows = [r for r in bt if r["pos"] == pos]
        res = {}
        for fn in NAMES:
            sub = [r for r in rows if fn in FEATS[r["n"]]]
            if len(sub) < 25:
                continue
            x = [FEATS[r["n"]][fn] for r in sub]; cs = [r["cs"] for r in sub]
            rjm = resid([r["jm"] for r in sub], cs); rpk = resid([math.log(r["pick"]) for r in sub], cs)
            yrs_pos = yrs_n = 0
            for y in range(2017, 2025):
                idx = [i for i, r in enumerate(sub) if r["yr"] == y]
                if len(idx) >= 6:
                    yrs_n += 1
                    rr = resid([sub[i]["jm"] for i in idx], [cs[i] for i in idx])
                    yrs_pos += spearman([x[i] for i in idx], rr) > 0
            loyo = loyo_delta(rows, pct_rank([FEATS[r["n"]].get(fn) for r in rows]))
            res[fn] = {"n": len(sub), "rho": spearman(x, cs), "pick": spearman(x, rpk), "jm": spearman(x, rjm),
                       "yrs": "%d/%d" % (yrs_pos, yrs_n), "loyo": loyo}
        out["results"][pos] = res
        out["coverage"][pos] = [sum(1 for r in rows if FEATS[r["n"]]), len(rows)]
        jm_rho = spearman([r["jm"] for r in rows], [r["cs"] for r in rows])
        print("\n=== %s  (%d of %d with game logs, %d games; JM alone rho %.3f) ===" % (pos, out["coverage"][pos][0], len(rows), CUTS[pos]["n_games"], jm_rho))
        print("  %-22s %4s %7s %7s %7s %6s %8s" % ("feature", "n", "rho", "|pick", "|JM", "yrs+", "LOYO d"))
        for fn, m in res.items():
            print("  %-22s %4d %7.3f %7.3f %7.3f %6s %+8.3f" % (fn, m["n"], m["rho"], m["pick"], m["jm"], m["yrs"], m["loyo"]))
    out["features"] = {r["n"]: dict(FEATS[r["n"]], pos=r["pos"], yr=r["yr"], jm=r["jm"], pick=r["pick"], cs=r["cs"]) for r in bt}
    json.dump(out, open(out_path, "w"), indent=1)
    print("\nwrote", out_path)


def run_perm(src, n_perm, out_path):
    D = json.load(open(src)); d = D["features"]
    out = {}
    for pos in POSITIONS:
        rows = [dict(v, n=k) for k, v in d.items() if v["pos"] == pos]
        for fn in D["results"][pos]:
            raw = [r.get(fn) for r in rows]
            obs = loyo_delta(rows, pct_rank(raw)); obs_p = partial_jm(rows, raw)
            ge = ge2 = 0
            rnd = random.Random(7)
            for _ in range(n_perm):
                perm = raw[:]; rnd.shuffle(perm)
                ge += loyo_delta(rows, pct_rank(perm)) >= obs
                ge2 += abs(partial_jm(rows, perm)) >= abs(obs_p)
            out[pos + ":" + fn] = {"loyo": obs, "p_loyo": (ge + 1) / (n_perm + 1), "partial_jm": obs_p, "p_partial": (ge2 + 1) / (n_perm + 1)}
            print("%-3s %-18s LOYO %+.3f p=%.3f   |JM %+.3f p=%.3f" % (pos, fn, obs, out[pos + ":" + fn]["p_loyo"], obs_p, out[pos + ":" + fn]["p_partial"]), flush=True)
    json.dump({"date": TODAY, "source": src, "shuffles": n_perm, "tests": out}, open(out_path, "w"), indent=1)
    print("wrote", out_path)


def run_view2027(out_path):
    sp = sp_splits([int(TODAY[:4])])[int(TODAY[:4])]
    ranked = sorted((t["def"], k) for k, t in sp.items() if t["def"] is not None)
    RANK = {tnorm(k): i + 1 for i, (v, k) in enumerate(ranked)}; NFBS = len(ranked)

    def opp_rank(opp):
        k = tnorm(opp)
        if k in RANK:
            return RANK[k]
        for tk in RANK:
            if tk.startswith(k) or k.startswith(tk):
                return RANK[tk]
        return None

    boards = json.load(open(os.path.join(ROOT, "scripts", "draft_boards_2027.json"), encoding="utf-8"))
    players = boards.get("players", boards) if isinstance(boards, dict) else boards
    wanted = {nrm(v.get("site") or k): (v.get("site") or k, v.get("pos"), v.get("school"), v.get("mock") or v.get("official"), v.get("consensus"))
              for k, v in players.items() if isinstance(v, dict) and v.get("pos") in POSITIONS}
    W = load_weekly(set(wanted))
    out = []
    for nk, (name, pos, school, proj, cons) in wanted.items():
        gl = W.get(nk, {}).get("seasons", {}).get(int(TODAY[:4]))
        if not gl:
            continue
        gs = [{"wk": g.get("wk"), "opp": g["opp"], "rk": opp_rank(g["opp"]), "pts": round(fpts(g), 1)}
              for g in gl if isinstance(g, dict) and g.get("opp")]
        if len(gs) < 4:
            continue
        top = [g for g in gs if g["rk"] and g["rk"] <= 30]; soft = [g for g in gs if not g["rk"] or g["rk"] >= NFBS - 45]
        ppg = lambda L: round(sum(g["pts"] for g in L) / len(L), 1) if L else None
        best = max(top, key=lambda g: g["pts"]) if top else None
        out.append({"name": name, "pos": pos, "school": school, "proj": proj, "cons": cons, "gp": len(gs), "ppg": ppg(gs),
                    "n_top": len(top), "ppg_top": ppg(top), "n_soft": len(soft), "ppg_soft": ppg(soft),
                    "soft_share": round(sum(max(0, g["pts"]) for g in soft) / max(1e-9, sum(max(0, g["pts"]) for g in gs)), 2),
                    "best_top": best, "games": gs})
    json.dump({"date": TODAY, "n_fbs": NFBS, "top": 30, "soft": "bottom 45 FBS + FCS", "players": out}, open(out_path, "w"), indent=1)
    print("players", len(out), "FBS defenses", NFBS)
    for p in sorted(out, key=lambda p: (p["pos"], -(p["ppg"] or 0))):
        bt = p["best_top"]
        print("%-2s %-24s %-15s proj %-4s gp %2d ppg %5.1f | vs top-30 D: %d g %5s | vs soft: %d g %5s share %.2f | best vs top-30: %s" % (
            p["pos"], p["name"][:24], (p["school"] or "")[:15], p["proj"], p["gp"], p["ppg"], p["n_top"], p["ppg_top"], p["n_soft"],
            p["ppg_soft"], p["soft_share"], ("%s %.1f (#%d)" % (bt["opp"], bt["pts"], bt["rk"])) if bt else "-"))
    print("wrote", out_path)


if __name__ == "__main__":
    mode = ARGS[0] if ARGS else None
    if mode == "study" and len(ARGS) > 1:
        run_study(ARGS[1], _opt("--out", os.path.join(ROOT, "scripts", "jm_competition_%s.json" % TODAY)))
    elif mode == "perm" and len(ARGS) > 1:
        run_perm(_opt("--src", os.path.join(ROOT, "scripts", "jm_competition_%s.json" % TODAY)), int(ARGS[1]),
                 _opt("--out", os.path.join(ROOT, "scripts", "jm_competition_perm_%s.json" % TODAY)))
    elif mode == "view2027":
        run_view2027(_opt("--out", os.path.join(ROOT, "scripts", "jm_competition_2027_%s.json" % TODAY)))
    else:
        sys.exit(__doc__)
