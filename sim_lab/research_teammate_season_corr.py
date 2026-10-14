"""
TEAMMATE SEASON CORRELATION (Jack 2026-10-14: "fix the season sim teammate correlation").

The season / league / best-ball sims draw one season shock per player, independent of his teammates
(engine drawSeasonShock). Step 1 (this file): measure on 2019-25 how teammates' season outcomes move
together, so a correlated shock can be calibrated against it.

Outcome per player-season: r = actual half-PPR total / preseason Clay half-PPR projection (the same pool as
backtest_sim_calibration.py: Clay >= 40 pts, QB/RB/WR/TE). Team = inferred from his games, else
data/player_team_history.js (so players wrecked before 4 games keep their team). Roles by Clay rank within
team: QB1, RB1, RB2, WR1, WR2, WR3, TE1.

Reports: Spearman / Pearson(log r) for role pairs, and conditional means E[r_B | A wrecked (r_A < .5)] vs
E[r_B | A not wrecked], with bootstrap CIs. Log: _tmp/teammate_corr.log
"""
import json, math, os, re, sys, collections
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_sim_calibration as B   # loads the weekly DB + schedules at import

REPO = B.REPO
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp", "teammate_corr.log")
os.makedirs(os.path.dirname(LOG), exist_ok=True)
_lf = open(LOG, "w", encoding="utf-8")
def out(*a):
    s = " ".join(str(x) for x in a); print(s); _lf.write(s + "\n"); _lf.flush()

def load_team_history():
    txt = open(os.path.join(REPO, "data", "player_team_history.js"), encoding="utf-8").read()
    res = {}
    for m in re.finditer(r"'((?:[^'\\]|\\.)+)'\s*:\s*\[(.*?)\]", txt):
        nm = m.group(1).replace("\\'", "'")
        spans = [(t, int(a), int(b)) for t, a, b in re.findall(r"t:'([A-Z]+)',y1:(\d+),y2:(\d+)", m.group(2))]
        res[B.norm(nm)] = spans
    return res
TH = load_team_history()
ALIAS = {"JAC": "JAX", "WSH": "WAS", "LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR"}

def team_for(name, wrec, Y):
    t = B.infer_team(wrec, Y) if wrec else None
    if t: return ALIAS.get(t, t), "games"
    for tt, a, b in TH.get(B.norm(name), []):
        if a <= Y <= b: return ALIAS.get(tt, tt), "history"
    return None, None

def build(Y, clay):
    rows = []
    for name, c in clay.items():
        pos = c.get("pos")
        if pos not in B.POS_KEEP: continue
        pts, gm, rec_n = c.get("pts") or 0, c.get("gm") or 0, c.get("rec") or 0
        if pts < B.POOL_MIN_PTS or gm < 2: continue
        half = max(0.5, pts - rec_n / 2.0)
        wrec = B.weekly_rec(name, pos)
        if wrec is None or not B.season_known(wrec, Y, name, pos): continue
        tot = sum(B.played_weeks(wrec, Y))
        tm, how = team_for(name, wrec, Y)
        if not tm: continue
        rows.append({"Y": Y, "name": name, "pos": pos, "tm": tm, "how": how, "half": half, "act": tot, "r": tot / half})
    # roles by Clay projection within team
    by = collections.defaultdict(list)
    for r in rows: by[(r["tm"], r["pos"])].append(r)
    for (tm, pos), lst in by.items():
        lst.sort(key=lambda r: -r["half"])
        for i, r in enumerate(lst, 1): r["role"] = f"{pos}{i}"
    return rows

def spearman(a, b):
    ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])

def main():
    clay = json.load(open(os.path.join(REPO, "data", "clay_history.json"), encoding="utf-8"))
    allrows = []
    for Y in B.SEASONS:
        rows = build(Y, clay[str(Y)]); allrows += rows
        out(f"{Y}: {len(rows)} player-seasons, team from games {sum(r['how']=='games' for r in rows)}, from history {sum(r['how']=='history' for r in rows)}")
    json.dump(allrows, open(os.path.join(os.path.dirname(LOG), "teammate_rows.json"), "w"), indent=0)
    idx = {(r["Y"], r["tm"], r["role"]): r for r in allrows}
    PAIRS = [("QB1", "WR1"), ("QB1", "WR2"), ("QB1", "TE1"), ("QB1", "RB1"), ("WR1", "WR2"), ("WR1", "TE1"), ("WR2", "WR3"),
             ("RB1", "RB2"), ("RB1", "WR1"), ("RB1", "TE1")]
    rng = np.random.default_rng(7)
    out("\nrole pair        n    spearman  pearson(log r)   E[rB | A wrecked<.5]  E[rB | A ok]   diff (95% boot CI)   n_wreck")
    for A, Bq in PAIRS:
        xs, ys = [], []
        for (Y, tm, role), ra in idx.items():
            if role != A: continue
            rb = idx.get((Y, tm, Bq))
            if rb: xs.append(ra["r"]); ys.append(rb["r"])
        xs, ys = np.array(xs), np.array(ys)
        if len(xs) < 20: continue
        lx, ly = np.log(np.maximum(xs, 0.03)), np.log(np.maximum(ys, 0.03))
        wr = xs < 0.5
        d = ys[wr].mean() - ys[~wr].mean() if wr.sum() >= 3 else float("nan")
        boots = []
        for _ in range(2000):
            ii = rng.integers(0, len(xs), len(xs)); w2 = xs[ii] < 0.5
            if w2.sum() >= 2 and (~w2).sum() >= 2: boots.append(ys[ii][w2].mean() - ys[ii][~w2].mean())
        lo, hi = (np.percentile(boots, 2.5), np.percentile(boots, 97.5)) if boots else (float("nan"),) * 2
        out(f"{A:>4s}-{Bq:<5s} {len(xs):6d}   {spearman(xs, ys):+.3f}    {np.corrcoef(lx, ly)[0,1]:+.3f}          "
            f"{ys[wr].mean() if wr.sum() else float('nan'):.3f}               {ys[~wr].mean():.3f}       {d:+.3f} ({lo:+.3f}, {hi:+.3f})   {int(wr.sum())}")
    # team-level: does a whole offense drift together? mean log r of the other skill players vs each player's own
    out("\nteam drift: corr of a player's log r with the mean log r of his OTHER teammates (excluding same-position room):")
    for pos in ("QB", "RB", "WR", "TE"):
        a, b = [], []
        teams = collections.defaultdict(list)
        for r in allrows: teams[(r["Y"], r["tm"])].append(r)
        for (Y, tm), lst in teams.items():
            for r in lst:
                if r["pos"] != pos or not r["role"].endswith("1"): continue
                oth = [math.log(max(q["r"], 0.03)) for q in lst if q["pos"] != pos]
                if len(oth) >= 2: a.append(math.log(max(r["r"], 0.03))); b.append(np.mean(oth))
        out(f"  {pos}1 vs other positions: n={len(a)} corr {np.corrcoef(a, b)[0,1]:+.3f}")

if __name__ == "__main__":
    main()
