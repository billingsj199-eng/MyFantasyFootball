"""jm_sos_analysis.py - does opponent strength inflate or deflate college PPG, and
would an opponent-adjusted PPG predict NFL outcomes better than raw PPG?

Data
  * CFBD SP+ ratings per season (/ratings/sp?year=) -> each FBS team's DEFENSE
    rating (lower = better defense). Cached in scripts/_sp_ratings.json.
  * COLLEGE_WEEKLY game logs (data/college_weekly_1/2/3.js + college_stats_devy.js)
    for the backtest players (2017-2024 classes) -> per-game fantasy points
    (site college scoring: half PPR) and the opponent.
  * jm_optimize results JSON -> jm, outcome (curveScore), pick per player.

Method
  1. Opponent defense z-score within each season (FCS / unrated opponents get
     the softest bucket, z = +1.5).
  2. Per position, expected points by opponent-defense bucket (deciles of z) over
     ALL player-games -> multiplicative factor = overall mean / bucket mean.
  3. adj points = raw points x factor(opponent); season adjPPG = mean adj over
     games (>= 6 GP); best season raw vs adj.
  4. Compare Spearman(bestPPG, outcome) vs Spearman(bestAdjPPG, outcome) per
     position, and whether (adj - raw) explains the model's misses
     (Spearman with the outcome residual on JM). Also a "soft slate" share.

    python scripts/jm_sos_analysis.py scripts/jm_optimize_results_2026-09-30.json
"""
import datetime
import json
import math
import os
import re
import sys
import time
from collections import defaultdict

ROOT = __file__.rsplit("scripts", 1)[0] or "."
sys.path.insert(0, ROOT)
SP_CACHE = ROOT + "scripts/_sp_ratings.json"
WEEKLY_FILES = ["data/college_weekly_1.js", "data/college_weekly_2.js", "data/college_weekly_3.js", "data/college_weekly_devy.js"]
MIN_GP = 6
SOFT_Z = 1.5


def nrm(s):
    s = (s or "").lower()
    s = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def sp_ratings(years):
    cache = json.load(open(SP_CACHE)) if os.path.exists(SP_CACHE) else {}
    missing = [y for y in years if str(y) not in cache]
    if missing:
        import requests
        from cfbd_config import CFBD_API_KEY
        for y in missing:
            r = requests.get("https://apinext.collegefootballdata.com/ratings/sp", headers={"Authorization": "Bearer " + CFBD_API_KEY},
                             params={"year": y}, timeout=40)
            rows = r.json() if r.status_code == 200 else []
            cache[str(y)] = {x["team"]: {"def": (x.get("defense") or {}).get("rating"), "off": (x.get("offense") or {}).get("rating"),
                                         "conf": x.get("conference")} for x in rows if x.get("team")}
            print("  SP+ %d: %d teams" % (y, len(cache[str(y)])), flush=True)
            time.sleep(0.4)
        json.dump(cache, open(SP_CACHE, "w"), separators=(",", ":"))
    return cache


def load_weekly(wanted):
    """-> {name: {yr: [game dicts]}} for wanted names only."""
    out = {}
    key_fix = re.compile(r"([{,])(\w+):")
    for f in WEEKLY_FILES:
        try:
            txt = open(ROOT + f, encoding="utf-8").read()
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


def fpts(g):
    return (g.get("py", 0) / 25 + g.get("ptd", 0) * 4 - g.get("int", 0) * 2 + g.get("ry", 0) / 10 + g.get("rtd", 0) * 6
            + g.get("rec", 0) * 0.5 + g.get("rcy", 0) / 10 + g.get("rctd", 0) * 6 - g.get("fl", 0) * 2)


def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    def rank(a):
        idx = sorted(range(n), key=lambda i: a[i]); r = [0] * n; i = 0
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
    return num / (dx * dy) if dx and dy else 0.0


def ols(xs, ys):
    n = len(xs); mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0
    return b, my - b * mx


def main():
    src = sys.argv[1]
    res = json.load(open(src, encoding="utf-8"))
    rows = [r for r in res["rows"] if r.get("verdict") != "pending" and r.get("cs") is not None]
    wanted = {nrm(r["n"]) for r in rows}
    weekly = load_weekly(wanted)
    print("backtest players: %d, with game logs: %d" % (len(rows), len(weekly)))
    years = sorted({yr for d in weekly.values() for yr in d})
    sp = sp_ratings([y for y in years if y >= 2013])

    # opponent defense z per season
    zmap = {}
    for y, teams in sp.items():
        vals = [t["def"] for t in teams.values() if t.get("def") is not None]
        if len(vals) < 50:
            continue
        mu = sum(vals) / len(vals); sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / len(vals)) or 1
        zmap[int(y)] = {tm: (t["def"] - mu) / sd for tm, t in teams.items() if t.get("def") is not None}

    def opp_z(yr, opp):
        z = zmap.get(yr, {})
        if opp in z:
            return z[opp]
        # loose match (e.g. "Miami" vs "Miami (FL)")
        for tm, v in z.items():
            if tm.lower().startswith(opp.lower()) or opp.lower().startswith(tm.lower()):
                return v
        return SOFT_Z    # FCS / unrated = soft

    # collect player-games
    games = []  # (pos, name, yr, fpts, z)
    pos_of = {nrm(r["n"]): r["pos"] for r in rows}
    draft_yr = {nrm(r["n"]): r["yr"] for r in rows}
    for nk, seasons in weekly.items():
        for yr, gl in seasons.items():
            if yr >= draft_yr[nk] or yr not in zmap:
                continue
            for g in gl:
                if not isinstance(g, dict) or not g.get("opp"):
                    continue
                games.append((pos_of[nk], nk, yr, fpts(g), opp_z(yr, g["opp"])))
    print("player-games with opponent rating: %d (seasons %d-%d)" % (len(games), min(zmap), max(zmap)))

    # factor by opponent-defense bucket per position (deciles of z)
    factors = {}
    for pos in ("QB", "RB", "WR", "TE"):
        pg = [g for g in games if g[0] == pos]
        if len(pg) < 200:
            continue
        zs = sorted(g[4] for g in pg)
        cuts = [zs[int(len(zs) * k / 10)] for k in range(1, 10)]
        def bucket(z):
            return sum(1 for c in cuts if z > c)
        overall = sum(g[3] for g in pg) / len(pg)
        by_b = defaultdict(list)
        for g in pg:
            by_b[bucket(g[4])].append(g[3])
        factors[pos] = {"cuts": cuts, "f": {b: (overall / (sum(v) / len(v)) if v and sum(v) > 0 else 1.0) for b, v in by_b.items()},
                        "mean": {b: round(sum(v) / len(v), 2) for b, v in by_b.items()}}
        print("  %s: mean pts by opponent-defense decile (best defense -> softest): %s" % (
            pos, " ".join("%.1f" % factors[pos]["mean"][b] for b in range(10))))

    # per player: best raw vs adjusted season
    feats = {}
    for nk, seasons in weekly.items():
        pos = pos_of[nk]
        if pos not in factors:
            continue
        cuts = factors[pos]["cuts"]; f = factors[pos]["f"]
        best_raw = best_adj = None; soft = None
        for yr, gl in seasons.items():
            if yr >= draft_yr[nk] or yr not in zmap:
                continue
            gs = [g for g in gl if isinstance(g, dict) and g.get("opp")]
            if len(gs) < MIN_GP:
                continue
            raw = [fpts(g) for g in gs]
            zs = [opp_z(yr, g["opp"]) for g in gs]
            adj = [p * f.get(sum(1 for c in cuts if z > c), 1.0) for p, z in zip(raw, zs)]
            rp, ap = sum(raw) / len(raw), sum(adj) / len(adj)
            soft_share = sum(1 for z in zs if z >= cuts[6]) / len(zs)   # top-30% softest defenses
            if best_raw is None or rp > best_raw:
                best_raw = rp
            if best_adj is None or ap > best_adj:
                best_adj, soft = ap, soft_share
        if best_raw is not None:
            feats[nk] = {"raw": best_raw, "adj": best_adj, "delta": best_adj - best_raw, "soft": soft}

    out = {"source": src, "date": datetime.date.today().isoformat(), "factors": factors, "by_pos": {}}
    print("\n%-4s %4s %9s %9s %10s %11s %11s" % ("pos", "n", "rho raw", "rho adj", "rho delta", "delta|jm", "soft|jm"))
    for pos in ("QB", "RB", "WR", "TE"):
        sub = [(r, feats[nrm(r["n"])]) for r in rows if r["pos"] == pos and nrm(r["n"]) in feats]
        if len(sub) < 20:
            continue
        b, a = ols([r["jm"] for r, _ in sub], [r["cs"] for r, _ in sub])
        res_jm = [r["cs"] - (a + b * r["jm"]) for r, _ in sub]
        cs = [r["cs"] for r, _ in sub]
        r_raw = spearman([f["raw"] for _, f in sub], cs); r_adj = spearman([f["adj"] for _, f in sub], cs)
        r_delta = spearman([f["delta"] for _, f in sub], cs); r_dj = spearman([f["delta"] for _, f in sub], res_jm)
        r_sj = spearman([f["soft"] for _, f in sub], res_jm)
        out["by_pos"][pos] = {"n": len(sub), "rho_raw": round(r_raw, 3), "rho_adj": round(r_adj, 3), "rho_delta": round(r_delta, 3), "rho_delta_resjm": round(r_dj, 3), "rho_soft_resjm": round(r_sj, 3)}
        print("%-4s %4d %9.3f %9.3f %10.3f %11.3f %11.3f" % (pos, len(sub), r_raw, r_adj, r_delta, r_dj, r_sj))
        big = sorted(sub, key=lambda x: x[1]["delta"])
        print("   most inflated by soft slates: " + ", ".join("%s %+.1f (raw %.1f)" % (r["n"], f["delta"], f["raw"]) for r, f in big[:4]))
        print("   most deflated by tough slates: " + ", ".join("%s %+.1f (raw %.1f)" % (r["n"], f["delta"], f["raw"]) for r, f in big[-4:]))
    out["players"] = {nk: feats[nk] for nk in feats}
    dst = ROOT + "scripts/jm_sos_%s.json" % out["date"]
    json.dump(out, open(dst, "w", encoding="utf-8"), indent=1)
    print("\nwrote", dst)


if __name__ == "__main__":
    main()
