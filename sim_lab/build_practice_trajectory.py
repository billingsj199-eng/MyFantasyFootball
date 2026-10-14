#!/usr/bin/env python3
"""
PRACTICE TRAJECTORY play rates (Jack 2026-10-08: "have the percentages change based on the trajectory, example
limited limited full or dnp limited").

Data: FootballDB's archived injury reports (footballdb.com/transactions/injuries.html?yr=Y&wk=W&type=reg), which keep
EVERY report day (nfl.com / nflverse keep only the last one), 2019-25 regular season minus the final week (resting
starters). Pages cached in pbp_cache/fdb_injuries/. Joined to nflverse snap counts: played = any offensive snap.
Population as backtest_injury_type_play.py: QB/RB/WR/TE averaging 40%+ of offensive snaps over 2+ prior games.

Sequence = the last three report days (Wed-Thu-Fri for a Sunday game). A day before he first appears ('--') counts as
FP (not on the report yet = practicing); a blank after a listed day repeats the previous day.

Fit (recent seasons weighted, half-life 3):
  day[k][X]       P(plays | status on report day k = X)                      pooled positions
  pre[seq]        P(plays | statuses so far) shrunk K_SEQ to day[k][last]   pooled positions
  fin[seq|des]    final report with its designation (Q / D / Out / none), shrunk K_SEQ to last|des, which is
                  shrunk K_SEQ to the pooled last|des rate
  pos[P][X]       logit shift for position P at last status X, shrunk K_POS (added on the site)
Grading: leave-one-season-out Brier of pre / fin vs the last-status-only rate.

Writes data/practice_trajectory.json and prints the compact JS for app.js (_PRAC_TRAJ).
"""
import json, math, os, re, sys, time
from collections import defaultdict
import numpy as np, pandas as pd, requests
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_common as B
sys.path.insert(0, r"E:\MyFantasyFootball\MyFantasyFootball Files\scripts")
import fdb_practice as F

POS4 = ("QB", "RB", "WR", "TE"); YEARS = list(range(2019, 2026)); HALF = 3; K_SEQ, K_POS = 40, 60
CACHE = os.path.join(HERE, "pbp_cache", "fdb_injuries"); os.makedirs(CACHE, exist_ok=True)
lg = lambda p: math.log(min(.995, max(.005, p)) / (1 - min(.995, max(.005, p))))
sg = lambda z: 1 / (1 + math.exp(-z))


def page(y, w):
    fn = os.path.join(CACHE, f"{y}_{w:02d}.html")
    if os.path.exists(fn) and os.path.getsize(fn) > 50000:
        return open(fn, encoding="utf-8", errors="replace").read()
    url = f"{F.URL}?yr={y}&wk={w}&type=reg"
    for a in range(3):
        try:
            r = requests.get(url, headers=F.UA, timeout=45)
            if r.status_code == 200 and len(r.text) > 50000:
                open(fn, "w", encoding="utf-8").write(r.text)
                time.sleep(1.5)
                return r.text
        except Exception:
            pass
        time.sleep(5)
    print(f"  !! no page {y} wk {w}")
    return ""


def seq3(days):
    lv = [d[2] for d in days][-3:]
    out, seen = [], False
    for x in lv:
        if x: seen = True; out.append(x)
        else: out.append(out[-1] if seen else "FP")
    while len(out) < 3: out.insert(0, "FP")
    return out


def _elite_map(Y):
    """{norm name: rank within position by PPG} for season Y (8+ games), from the site's weekly DB."""
    W = B.cal.WEEKLY
    ppg = defaultdict(list)
    for k, cands in W.items():
        for c in cands:
            pos = c.get("pos")
            if pos not in POS4: continue
            pts = [w["fpts"] for w in c.get("seasons", {}).get(str(Y), []) if B.cal.played(w) and isinstance(w.get("fpts"), (int, float))]
            if len(pts) >= 8: ppg[pos].append((sum(pts) / len(pts), k))
    out = {}
    for pos, arr in ppg.items():
        for i, (_, k) in enumerate(sorted(arr, reverse=True)): out[(k, pos)] = i + 1
    return out


def load():
    rows = []
    for Y in YEARS:
        last = 17 if Y <= 2020 else 18
        ros = pd.read_parquet(os.path.join(B.CACHE, f"roster_weekly_{Y}.parquet"), columns=["full_name", "position", "birth_date", "years_exp", "week"])
        bio = {}
        for r in ros.itertuples(index=False):
            bio[(B.cal.norm(str(r.full_name)), r.position)] = (r.birth_date, r.years_exp)
        prev_rank = _elite_map(Y - 1)
        season_start = pd.Timestamp(f"{Y}-09-01")
        sn = pd.read_parquet(os.path.join(B.CACHE, f"snap_counts_{Y}.parquet"), columns=["week", "game_type", "player", "position", "offense_snaps", "offense_pct"])
        sn = sn[(sn.game_type == "REG") & sn.position.isin(POS4) & (sn.offense_snaps > 0)]
        hist = defaultdict(dict)
        for r in sn.itertuples(index=False): hist[B.cal.norm(str(r.player))][int(r.week)] = float(r.offense_pct)
        for W in range(1, last):
            html = page(Y, W)
            if not html: continue
            for x in F.parse(html, Y):
                if x["pos"] not in POS4: continue
                k = B.cal.norm(x["name"])
                prev = [v for w, v in hist.get(k, {}).items() if w < W]
                if len(prev) < 2 or np.mean(prev) < .40: continue
                s = seq3(x["days"])
                bd, ye = bio.get((k, x["pos"]), (None, None))
                try: age = (season_start - pd.Timestamp(bd)).days / 365.25 if bd else None
                except Exception: age = None
                rk = prev_rank.get((k, x["pos"]))
                inj = (x["inj"] or "").lower()
                rows.append(dict(year=Y, week=W, pos=x["pos"], s1=s[0], s2=s[1], s3=s[2], des=x["gs"] or "none", played=int(W in hist.get(k, {})),
                                 age=age, exp=ye if ye == ye else None, prk=rk,
                                 elite=int(rk is not None and rk <= (12 if x["pos"] in ("QB", "TE") else 24)),
                                 rest=int("rest" in inj or "not injury" in inj), inj=inj))
        print(f"  {Y}: {sum(1 for r in rows if r['year'] == Y)} rows")
    return pd.DataFrame(rows)


def fit(A, ref):
    w = 0.5 ** ((ref - A.year.values) / HALF)
    A = A.assign(w=w, wp=w * A.played.values)
    def rate(mask): s = A[mask]; return (s.wp.sum(), s.w.sum(), len(s))
    tot = A.wp.sum() / A.w.sum()
    day, pre, fin, n = {}, {}, {}, {}
    cols = ["s1", "s2", "s3"]
    for k in (1, 2, 3):
        c = cols[k - 1]
        for X in ("FP", "LP", "DNP"):
            wp, ww, nn = rate(A[c] == X)
            day[f"{k}:{X}"] = (wp + 10 * tot) / (ww + 10) if ww else tot
        for key, g in A.groupby(cols[:k]):
            key = key if isinstance(key, tuple) else (key,)
            par = day[f"{k}:{key[-1]}"]
            p = (g.wp.sum() + K_SEQ * par) / (g.w.sum() + K_SEQ)
            pre["-".join(key)] = p; n["-".join(key)] = len(g)
    lastdes = {}
    for (X, d), g in A.groupby(["s3", "des"]):
        par = day[f"3:{X}"]
        lastdes[f"{X}|{d}"] = (g.wp.sum() + K_SEQ * par) / (g.w.sum() + K_SEQ)
    for (a, b, c, d), g in A.groupby(cols + ["des"]):
        par = lastdes.get(f"{c}|{d}", day[f"3:{c}"])
        fin[f"{a}-{b}-{c}|{d}"] = (g.wp.sum() + K_SEQ * par) / (g.w.sum() + K_SEQ); n[f"{a}-{b}-{c}|{d}"] = len(g)
    pos = {}
    for P in POS4:
        pos[P] = {}
        for X in ("FP", "LP", "DNP"):
            g = A[(A.pos == P) & (A.s3 == X)]; base = day[f"3:{X}"]
            pp = (g.wp.sum() + K_POS * base) / (g.w.sum() + K_POS)
            pos[P][X] = lg(pp) - lg(base)
    return dict(day=day, pre=pre, fin=fin, lastdes=lastdes, pos=pos, n=n)


def predict(M, r, k, final):
    s = [r.s1, r.s2, r.s3][:k]
    if final:
        p = M["fin"].get("-".join(s) + "|" + r.des) or M["lastdes"].get(f"{s[-1]}|{r.des}") or M["day"][f"3:{s[-1]}"]
    else:
        p = M["pre"].get("-".join(s)) or M["day"][f"{k}:{s[-1]}"]
    return sg(lg(p) + M["pos"].get(r.pos, {}).get(s[-1], 0))


def predict_last(M, r, k, final):
    X = [r.s1, r.s2, r.s3][k - 1]
    p = M["lastdes"].get(f"{X}|{r.des}", M["day"][f"3:{X}"]) if final else M["day"][f"{k}:{X}"]
    return sg(lg(p) + M["pos"].get(r.pos, {}).get(X, 0))


FLAGS = ("rest", "vet", "elite", "conc")   # applied in this order, each fit on the previous ones' residuals (conc = concussion, research_concussion_return.py 10-08)
STAGES = ((1, False), (2, False), (3, False), (3, True))
K_ADJ = 60


def _flag(r, f):
    if f == "vet": return int(r.age is not None and r.age == r.age and r.age >= 30)
    if f == "conc": return int("concussion" in (r.inj or ""))
    return int(getattr(r, f))


def fit_adj(A, M):
    """adj[flag][stage][X] = shrunk logit shift for rows with that flag, by stage (day 1/2/3, 3 + designation) and the
    latest status. Fit in FLAGS order on the residual after the earlier flags (rest overlaps the veterans)."""
    adj = {f: {} for f in FLAGS}
    rows = list(A.itertuples(index=False))
    for k, final in STAGES:
        st = f"{k}{'f' if final else ''}"
        z = np.array([lg(predict(M, r, k, final)) for r in rows])
        y = np.array([r.played for r in rows])
        X = np.array([[r.s1, r.s2, r.s3][k - 1] for r in rows])
        for f in FLAGS:
            fl = np.array([_flag(r, f) for r in rows])
            adj[f][st] = {}
            for x in ("FP", "LP", "DNP"):
                m = (fl == 1) & (X == x)
                if m.sum() < 10: continue
                pbar = np.mean([sg(v) for v in z[m]])
                pobs = (y[m].sum() + K_ADJ * pbar) / (m.sum() + K_ADJ)
                sh = lg(pobs) - lg(pbar)
                adj[f][st][x] = sh
                z[m] = z[m] + sh
    return adj


def predict_adj(M, adj, r, k, final):
    p = predict(M, r, k, final)
    st = f"{k}{'f' if final else ''}"; x = [r.s1, r.s2, r.s3][k - 1]
    zz = lg(p)
    for f in FLAGS:
        if _flag(r, f): zz += adj[f].get(st, {}).get(x, 0)
    return sg(zz)


def main():
    A = load()
    print(f"{len(A)} injury-week rows (regular starters), 2019-25")
    # leave-one-season-out: trajectory vs last-status-only
    for k, final in ((1, False), (2, False), (3, False), (3, True)):
        e_t, e_l = [], []
        for Y in YEARS:
            tr, te = A[A.year != Y], A[A.year == Y]
            M = fit(tr, max(tr.year))
            for r in te.itertuples(index=False):
                e_t.append((predict(M, r, k, final) - r.played) ** 2); e_l.append((predict_last(M, r, k, final) - r.played) ** 2)
        print(f"  day {k}{' + designation' if final else ''}: Brier trajectory {np.mean(e_t):.4f} vs last-status {np.mean(e_l):.4f} ({100*(np.mean(e_t)/np.mean(e_l)-1):+.1f}%)")
    # + rest tag / veteran (30+) / elite (last season top-12 QB/TE, top-24 RB/WR) shifts, LOSO, per season
    for k, final in STAGES:
        e_t, e_a, wins = [], [], 0
        for Y in YEARS:
            tr, te = A[A.year != Y], A[A.year == Y]
            M = fit(tr, max(tr.year)); adj = fit_adj(tr, M)
            a = [(predict(M, r, k, final) - r.played) ** 2 for r in te.itertuples(index=False)]
            b = [(predict_adj(M, adj, r, k, final) - r.played) ** 2 for r in te.itertuples(index=False)]
            e_t += a; e_a += b; wins += int(np.mean(b) < np.mean(a))
        print(f"  day {k}{' + designation' if final else ''}: + rest/vet/elite {np.mean(e_t):.4f} -> {np.mean(e_a):.4f} ({100*(np.mean(e_a)/np.mean(e_t)-1):+.2f}%, better in {wins}/{len(YEARS)} seasons)")
    M = fit(A, 2025)
    ADJ = fit_adj(A, M)
    print("  adj:", {f: {st: {x: round(v, 2) for x, v in d.items()} for st, d in ADJ[f].items()} for f in FLAGS})
    show = ["LP", "LP-LP", "LP-LP-LP", "LP-LP-FP", "DNP-LP-FP", "DNP-DNP-LP", "DNP-LP-LP", "FP-LP-LP", "DNP", "DNP-DNP", "DNP-DNP-DNP", "DNP-LP", "LP-FP"]
    for s in show:
        if s in M["pre"]: print(f"    {s:12s} {100*M['pre'][s]:5.1f}%  (n {M['n'].get(s, 0)})")
    for s in ("LP-LP-FP|Questionable", "DNP-LP-FP|Questionable", "DNP-DNP-LP|Questionable", "LP-LP-LP|Questionable", "DNP-LP-LP|Questionable", "DNP-DNP-DNP|Questionable"):
        if s in M["fin"]: print(f"    {s:26s} {100*M['fin'][s]:5.1f}%  (n {M['n'].get(s, 0)})")
    r3 = lambda d: {k: round(v, 3) for k, v in d.items()}
    out = {"asOf": "2019-25 FootballDB x nflverse snaps", "half": HALF, "kSeq": K_SEQ, "kPos": K_POS,
           "day": r3(M["day"]), "pre": r3(M["pre"]), "fin": r3(M["fin"]), "lastdes": r3(M["lastdes"]),
           "pos": {P: r3(v) for P, v in M["pos"].items()}, "n": M["n"],
           "adj": {f: {st: r3(d) for st, d in ADJ[f].items()} for f in FLAGS}}
    json.dump(out, open(os.path.join(HERE, "data", "practice_trajectory.json"), "w"), indent=1)
    js = {k: out[k] for k in ("day", "pre", "fin", "lastdes", "pos", "adj")}
    print("JS:", json.dumps(js, separators=(",", ":")))


if __name__ == "__main__":
    main()
