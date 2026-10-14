"""
Correlated SEASON SHOCKS for teammates (Jack 2026-10-14: "fix the season sim teammate correlation").
Evidence step 1: research_teammate_season_corr.py (_tmp/teammate_corr.log): QB1 moves with his skill players
(Spearman +.26/+.31), RB1-RB2 and WR2-WR3 trade off (-.25 / -.15), WR1-WR2 ~0.

Model (applied on top of the shipped per-player wrecked-season mixture, which keeps E[g] = 1):
  1. QB HUB:   every RB / WR / TE on the team: g_j *= max(.05, 1 + k_pos * (g_QB1 - 1))       (k_pass WR/TE, k_rb RB)
  2. ROOM:     a room-mate's lost (or extra) points move to the rest of the room in proportion to projection:
               g_j += s_pos * sum_i (1 - g_i) * half_i / sum_{others} half,  floor .05            (s_rb, s_wr, s_te)
  Both terms are linear in (1 - g) of an independent draw, so every player's mean stays exactly 1 (bar the floor).
Season total = g' x N where N = the harness's weekly-noise season (sim_player with shock 1): gamma draws scale
linearly with the base, so N is drawn once per player and every variant reuses it.

Grade (2019-25, preseason Clay pool, backtest_sim_calibration.py data): pair correlations vs actual, STACK p10-p90
coverage (QB1+WR1, QB1+TE1, QB1+RB1, RB1+RB2, WR2+WR3, team skill total; target 80, real stacks currently miss
it because independent shocks make sums too narrow) and the per-player marginals (must not get worse).
Leave-one-year-out: weights picked on 6 seasons by loss, scored on the 7th.  Log: _tmp/teammate_shock.log
"""
import itertools, json, math, os, sys, collections
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_sim_calibration as B
import research_teammate_season_corr as R

SIMS = 2000
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp", "teammate_shock.log")
_lf = open(LOG, "w", encoding="utf-8")
def out(*a):
    s = " ".join(str(x) for x in a); print(s); _lf.write(s + "\n"); _lf.flush()

STACKS = [("QB1", "WR1"), ("QB1", "TE1"), ("QB1", "RB1"), ("RB1", "RB2"), ("WR2", "WR3"), ("WR1", "WR2")]
PAIRS = [("QB1", "WR1"), ("QB1", "WR2"), ("QB1", "TE1"), ("QB1", "RB1"), ("WR1", "WR2"), ("WR2", "WR3"), ("RB1", "RB2"), ("WR1", "TE1")]

def season_data(Y, clay):
    rows = R.build(Y, clay)
    W = 16 if Y <= 2020 else 17
    rng = np.random.default_rng(B.SEED + Y)
    for r in rows:
        c = clay[r["name"]]; gm = min(c.get("gm") or W, W)
        wrec = B.weekly_rec(r["name"], r["pos"])
        sig = B.sigma_entering(r["name"], r["pos"], Y)
        wm = r["half"] / gm
        N = B.sim_player(rng, wm, sig, W, gm / W, shock=np.ones((SIMS, 1))).sum(axis=1)
        r["N"] = N
        r["g0"] = B.draw_shock(rng, B.SHIPPED_SHOCK, r["half"]).reshape(-1)   # shipped independent shock
    return rows

def apply(rows, P):
    """-> {id(row): g'} for variant params P = (k_pass, k_rb, s_rb, s_wr, s_te)"""
    k_pass, k_rb, s_rb, s_wr, s_te = P
    g = {id(r): r["g0"].copy() for r in rows}
    teams = collections.defaultdict(list)
    for r in rows: teams[r["tm"]].append(r)
    for tm, lst in teams.items():
        # room substitution first (uses the raw draws), then the QB hub on top
        add = {id(r): 0.0 for r in lst}
        for pos, s in (("RB", s_rb), ("WR", s_wr), ("TE", s_te)):
            if s <= 0: continue
            room = [r for r in lst if r["pos"] == pos]
            if len(room) < 2: continue
            for i in room:
                others = [j for j in room if j is not i]; tot = sum(j["half"] for j in others)
                for j in others:
                    add[id(j)] = add[id(j)] + s * (1 - i["g0"]) * i["half"] / tot
        for r in lst:
            if isinstance(add[id(r)], np.ndarray): g[id(r)] = np.maximum(0.05, g[id(r)] + add[id(r)])
        qb = next((r for r in lst if r["role"] == "QB1"), None)
        if qb is not None and (k_pass or k_rb):
            for r in lst:
                if r["pos"] == "QB": continue
                k = k_rb if r["pos"] == "RB" else k_pass
                if k: g[id(r)] = g[id(r)] * np.maximum(0.05, 1 + k * (qb["g0"] - 1))
    return g

def grade(seasons, P):
    """pooled over the given seasons: pair-corr error, stack coverage, marginal coverage"""
    pc_mod = collections.defaultdict(list); pc_act = collections.defaultdict(list)
    st = collections.defaultdict(lambda: [0, 0, 0, 0])   # in, below, above, n
    mg = collections.defaultdict(lambda: [0, 0, 0, 0])
    for rows in seasons:
        g = apply(rows, P)
        idx = {(r["tm"], r["role"]): r for r in rows}
        tot = {id(r): g[id(r)] * r["N"] for r in rows}
        for r in rows:
            t = tot[id(r)]; lo, hi = np.percentile(t, 10), np.percentile(t, 90)
            m = mg[r["pos"]]; m[3] += 1
            if r["act"] < lo: m[1] += 1
            elif r["act"] > hi: m[2] += 1
            else: m[0] += 1
        for A, Bq in PAIRS:
            for (tm, role), ra in idx.items():
                if role != A: continue
                rb = idx.get((tm, Bq))
                if not rb: continue
                x = tot[id(ra)] / ra["half"]; y = tot[id(rb)] / rb["half"]
                pc_mod[(A, Bq)].append(float(np.corrcoef(x, y)[0, 1]))
                pc_act[(A, Bq)].append((ra["r"], rb["r"]))
        for A, Bq in STACKS:
            for (tm, role), ra in idx.items():
                if role != A: continue
                rb = idx.get((tm, Bq))
                if not rb: continue
                s = tot[id(ra)] + tot[id(rb)]; a = ra["act"] + rb["act"]
                lo, hi = np.percentile(s, 10), np.percentile(s, 90); c = st[(A, Bq)]; c[3] += 1
                if a < lo: c[1] += 1
                elif a > hi: c[2] += 1
                else: c[0] += 1
        teams = collections.defaultdict(list)
        for r in rows: teams[r["tm"]].append(r)
        for tm, lst in teams.items():
            if len(lst) < 4: continue
            s = sum(tot[id(r)] for r in lst); a = sum(r["act"] for r in lst)
            lo, hi = np.percentile(s, 10), np.percentile(s, 90); c = st[("TEAM", "all")]; c[3] += 1
            if a < lo: c[1] += 1
            elif a > hi: c[2] += 1
            else: c[0] += 1
    pair = {}
    for k in pc_mod:
        xs = np.array(pc_act[k]); pair[k] = (float(np.mean(pc_mod[k])), float(np.corrcoef(xs[:, 0], xs[:, 1])[0, 1]), len(xs))
    return pair, dict(st), dict(mg)

def loss(pair, st, mg):
    l = sum((m - a) ** 2 * n for m, a, n in pair.values()) / max(1, sum(n for _, _, n in pair.values()))
    l += sum(((c[0] / c[3]) - 0.80) ** 2 for c in st.values() if c[3]) / max(1, len(st))
    l += sum(((c[0] / c[3]) - 0.80) ** 2 for c in mg.values() if c[3]) / max(1, len(mg))
    return l

def show(tag, pair, st, mg):
    out(f"  [{tag}]")
    out("    pairs (model corr / actual corr):  " + "  ".join(f"{a}-{b} {m:+.2f}/{x:+.2f}" for (a, b), (m, x, n) in sorted(pair.items())))
    out("    stacks p10-p90 in / below / above: " + "  ".join(f"{a}+{b} {c[0]/c[3]*100:.0f}/{c[1]/c[3]*100:.0f}/{c[2]/c[3]*100:.0f}" for (a, b), c in sorted(st.items())))
    out("    players p10-p90 in / below / above: " + "  ".join(f"{p} {c[0]/c[3]*100:.0f}/{c[1]/c[3]*100:.0f}/{c[2]/c[3]*100:.0f}" for p, c in sorted(mg.items())))

def main():
    clay = json.load(open(os.path.join(B.REPO, "data", "clay_history.json"), encoding="utf-8"))
    data = {Y: season_data(Y, clay[str(Y)]) for Y in B.SEASONS}
    out("player-seasons:", {Y: len(v) for Y, v in data.items()})
    GRID = list(itertools.product([0, .2, .35, .5], [0, .2, .35, .5], [0, .25, .4, .6], [0, .1, .2, .3], [0, .2]))
    out(f"grid {len(GRID)} variants (k_pass, k_rb, s_rb, s_wr, s_te)")
    base = (0, 0, 0, 0, 0)
    pooled = {}
    for P in GRID:
        pooled[P] = {Y: grade([data[Y]], P) for Y in B.SEASONS}
    def comb(P, years):
        # combine per-season grades: re-run pooled grade for exactness
        return grade([data[Y] for Y in years], P)
    out("\n=== ALL SEASONS: shipped independent vs best pooled ===")
    allY = list(B.SEASONS)
    b_all = comb(base, allY); show("independent (live)", *b_all)
    scores = sorted(GRID, key=lambda P: loss(*pooled_loss(pooled, P)))
    best = scores[0]; out(f"  best pooled params {best}"); show(f"coupled {best}", *comb(best, allY))
    out("\n=== LEAVE-ONE-YEAR-OUT ===")
    agg_b = []; agg_c = []
    for hold in allY:
        train = [Y for Y in allY if Y != hold]
        Pb = min(GRID, key=lambda P: loss(*pooled_loss(pooled, P, train)))
        gb, gc = grade([data[hold]], base), grade([data[hold]], Pb)
        lb, lc = loss(*gb), loss(*gc); agg_b.append(lb); agg_c.append(lc)
        sb = gb[1]; sc_ = gc[1]
        stk = lambda s: np.mean([c[0] / c[3] for c in s.values() if c[3]]) * 100
        out(f"  hold {hold}: picked {Pb} | loss indep {lb:.4f} -> coupled {lc:.4f} | mean stack coverage {stk(sb):.1f} -> {stk(sc_):.1f}")
    out(f"  LOYO: coupled better in {sum(c < b for b, c in zip(agg_b, agg_c))}/{len(allY)} seasons; mean loss {np.mean(agg_b):.4f} -> {np.mean(agg_c):.4f}")

def pooled_loss(pooled, P, years=None):
    """pool per-season grade parts for params P (pairs averaged by n, counts summed)"""
    years = years or list(pooled[P].keys())
    pair = collections.defaultdict(lambda: [0.0, 0.0, 0]); st = collections.defaultdict(lambda: [0, 0, 0, 0]); mg = collections.defaultdict(lambda: [0, 0, 0, 0])
    for Y in years:
        p, s, m = pooled[P][Y]
        for k, (mo, ac, n) in p.items():
            q = pair[k]; q[0] += mo * n; q[1] += ac * n; q[2] += n
        for k, c in s.items():
            for i in range(4): st[k][i] += c[i]
        for k, c in m.items():
            for i in range(4): mg[k][i] += c[i]
    pair = {k: (v[0] / v[2], v[1] / v[2], v[2]) for k, v in pair.items() if v[2]}
    return pair, dict(st), dict(mg)

if __name__ == "__main__":
    main()
