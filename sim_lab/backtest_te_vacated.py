#!/usr/bin/env python3
"""
TE VACATED: is the back-up tight end under-projected while the starter is out?  (2026-10-05, RESEARCH ONLY - nothing in
engine.js / overrides.js is changed.)

Trigger: fillin_usage.log section 0b - TE "starter still OUT" rows, mean actual / mean live projection 1.395 next game
(n 82), 1.53 / 1.65 rest of season (n 42 / 56), while RB (0.893) and WR (0.987) are fine.

Live form: copied from backtest_fillin_usage.setup() (itself a copy of backtest_live_blend_pos.setup) - NOT imported,
importing either module truncates its log.  The next-game chain INCLUDES the harness replay of the engine vacated pool
(ctx_live_layers.parquet pool_mult, built by build_live_layers.py with the engine POOL weights); the rest-of-season
chain in those scripts has NO pool, so here the rest-of-season baseline on the target rows adds the pool multiplier on
the share of the remaining games the starter actually missed (engine applies the pool over the injury window).

Definitions (per team-season, tight ends from clay_history with a weekly record, team per game from the schedule):
  TE1          the team's lead tight end by Clay per-game projection (half PPR, per projected game), >= 4.0 a game,
               who played 1+ game for the team that season
  TE1 out      the team played week w, TE1 has no stat row for the team in w (weekly DB rows exist only for games with
               a stat), and he did not play for another team in or after w (not traded / released)
  backup row   a harness TE row (Clay pool, 40+ pts) of the same team in a TE1-out week, not TE1;  "TE2" = the highest
               Clay per-game TE among those who played for the team that week other than TE1
Rules (applied on the backup rows only; graded on those rows, LOYO 2019-25 and forward 2022-25, plus the board):
  a   share s of the absent TE1's season-to-date targets per game to the TE2 (replaces the harness pool gain on the
      row): f = 1 + s x V x ppt x .92 / max(own ppg, 3.5)  (engine form); ppt = his season-to-date half-PPR pts per
      target (league TE mean when < 5 targets);  a+ = the same gain ADDED (no ratio-to-floor damping)
  b   role inheritance: projection = max(live, k x TE1 level x chain)   (floor) or live(no pool) + k x TE1 level x
      chain (additive, QB-style); TE1 level = P5 blend of his Clay per game and his games so far
  c   faster blend of the back-up's own fill-in games (games TE1 missed) while TE1 is still out:
      base' = (Pc x live base + nf x fill-in ppg) / (Pc + nf), pool kept or dropped
  d   the engine "sec" rule gives the healthy TE ranked first NOTHING (POOL.TE.sec.tgtSame[0] = 0.00); a TE1 is "lead"
      only when he is his team's top target-getter.  Grid on the sec share for the TE2.
Log te_vacated.log.
"""
import json, os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import research_clay_vs_shadow as CS
from backtest_inseason_usage import route_features
cal = NW.cal
warnings.filterwarnings("ignore")

YEARS = list(NW.YEARS); POS4 = ("QB", "RB", "WR", "TE"); FWD = (2022, 2023, 2024, 2025)
LIVE_P = 5
TDK = {"QB": 0.5 * 4.0, "RB": 0.75 * 6.0, "WR": 1.0 * 6.0, "TE": 1.0 * 6.0}
USE_C = {"WR": (0.37, 0.53, 0.005, 0.050), "TE": (-1.87, 0.47, 0.023, 0.057)}
ROS_TILT = {"QB": 0.06, "TE": 0.08}
TE1_MIN = 4.0
LOG = open(os.path.join(HERE, "te_vacated.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + "\n"); LOG.flush()


# ------------------------------------------------------------------ live form (copied from backtest_fillin_usage.setup)
def setup():
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, clay, layers, adp, pid, name = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"], F["adp"], A["pid"], A["name"]
    ch = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, name)], dtype=float)
    W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay)
    mu_y = {}
    for y in YEARS:
        wy = 16.0 if y <= 2020 else 17.0
        lv = sorted([max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0) / wy for c in ch[str(y)].values() if c.get("pos") == "QB"], reverse=True)[:32]
        mu_y[y] = float(np.mean(lv))
    mu = np.array([mu_y[int(y)] for y in year])
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet"))
    def joiner(D):
        k = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(D.year, D.pid, D.wk)) if isinstance(b, str)}
        ix = np.array([k.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)])
        return lambda c, d=np.nan: np.where(ix >= 0, D[c].values[np.maximum(ix, 0)].astype(float), d), ix >= 0
    cv, hasC = joiner(C); lv_, hasL = joiner(L)
    xfp, snap = cv("xfp_pg"), cv("snap_std"); rt, _ = route_features(year, pid, wk)
    useok = hasC & (g >= 1) & ~np.isnan(xfp) & ~np.isnan(snap) & ~np.isnan(rt)
    lam_wr = np.select([g <= 2, g <= 5, g <= 8], [0.8, 0.6, 0.5], 0.3); lam_te = np.where(g <= 3, 0.0, 0.3)
    lam = np.where(useok & (pos == "WR"), lam_wr, np.where(useok & (pos == "TE"), lam_te, 0.0))
    ppg0 = np.maximum(0.0, ppg)
    tdl = np.nan_to_num(lv_("td_luck_pg", 0.0), nan=0.0); tdk = np.array([TDK[p_] for p_ in pos])
    rook = np.nan_to_num(lv_("rookie_mult", 1.0), nan=1.0); cond = np.nan_to_num(lv_("cond_mult", 1.0), nan=1.0)
    wx = np.nan_to_num(lv_("weather_mult", 1.0), nan=1.0); pool = np.nan_to_num(lv_("pool_mult", 1.0), nan=1.0)
    inh = np.nan_to_num(lv_("qb_inherit_mult", 1.0), nan=1.0) > 1.0
    rbu = lv_("usage_half"); rbu = np.where(pos == "RB", rbu, np.nan)
    snapm = np.nan_to_num(cv("snapmult", 1.0), nan=1.0)
    chain = layers * snapm * cond * wx * pool
    att, proe = cv("att_pg"), cv("proe_std"); team = A["team"]; z = np.zeros(n)
    for y in YEARS:
        for w_ in range(2, 19):
            m = (year == y) & (wk == w_)
            q = m & (pos == "QB") & (g >= 2) & (att >= 10)
            if q.sum() >= 8 and att[q].std() > 0: z[q] = np.clip((att[q] - att[q].mean()) / att[q].std(), -2, 2)
            tm = m & (g >= 2) & ~np.isnan(proe)
            if tm.sum():
                tv = {}
                for i in np.where(tm)[0]: tv.setdefault(team[i], proe[i])
                v = np.array(list(tv.values()))
                if len(v) >= 8 and v.std() > 0:
                    t_ = m & (pos == "TE") & (g >= 2) & ~np.isnan(proe)
                    z[t_] = np.clip((proe[t_] - v.mean()) / v.std(), -2, 2)
    tilt_e = np.array([ROS_TILT.get(p_, 0.0) for p_ in pos])
    return dict(F=F, A=A, n=n, act=act, year=year, wk=wk, pos=pos, g=g, ppg=ppg0, clay_gm=clay_gm, layers=layers, adp=adp, pid=pid, name=name, mu=mu, lam=lam,
                tdl=tdl, tdk=tdk, rook=rook, inh=inh, rbu=rbu, chain=chain, z=z, tilt_e=tilt_e, hasC=hasC, useok=useok, xfp=xfp, snap=snap, rt=rt, team=team,
                pool=pool, pool_tg=np.nan_to_num(lv_("pool_gain_tg", 0.0), nan=0.0), ch=ch)


def uimp_of(X, xfp, snap):
    pos = X["pos"]; cw, ct = USE_C["WR"], USE_C["TE"]; rt = X["rt"]
    u = np.where(pos == "WR", cw[0] + cw[1] * xfp + cw[2] * rt + cw[3] * snap, ct[0] + ct[1] * xfp + ct[2] * rt + ct[3] * snap)
    return np.maximum(0.0, np.nan_to_num(u, nan=0.0))


def live_base(X):
    g, pos, lam, ppg = X["g"], X["pos"], X["lam"], X["ppg"]; ge = g.astype(float)
    ev = np.where(lam > 0, lam * uimp_of(X, X["xfp"], X["snap"]) + (1 - lam) * ppg, ppg)
    base = np.where(ge > 1e-9, (LIVE_P * X["clay_gm"] + ge * ev) / (LIVE_P + ge), X["clay_gm"])
    base = base * X["rook"]
    fl = (pos == "QB") & ~X["inh"] & (base >= 5) & (base < X["mu"])
    base = np.where(fl, X["mu"] + 0.70 * (base - X["mu"]), base)
    base = np.where(~np.isnan(X["rbu"]), 0.85 * base + 0.15 * np.nan_to_num(X["rbu"], nan=0.0), base)
    luck = np.where(g > 0, X["tdk"] * X["tdl"] * g / (LIVE_P + g) * (1 - lam), 0.0)
    return base, luck


def week_team(Y, w, opp):
    o = cal.OPP_ALIAS.get(opp, opp)
    for t, s in cal.SCHEDULES.get(Y, {}).items():
        if s.get(str(w)) == o: return t
    return None


def hpts(w):
    return (w.get("rec") or 0) * 0.5 + (w.get("rcy") or 0) * 0.1 + (w.get("rctd") or 0) * 6


# ------------------------------------------------------------------ tight-end rooms
def build_rooms(ch):
    tcache = {}
    games = {}            # (nm, Y) -> {wk: dict(team, fpts, tgt, rp)}
    clay = {}             # (nm, Y) -> clay per game (half)
    room = defaultdict(list)
    for Y in YEARS:
        W = 16 if Y <= 2020 else 17
        for nm, c in ch[str(Y)].items():
            if c.get("pos") != "TE": continue
            rec = cal.weekly_rec(nm, "TE")
            if rec is None: continue
            gmv = c.get("gm") or 0; half = max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0)
            cpg = half / gmv if gmv >= 4 else half / W
            gl = {}
            for w in rec.get("seasons", {}).get(str(Y), []):
                if cal.played(w) and w.get("opp"):
                    k = (Y, int(w["wk"]), w["opp"])
                    if k not in tcache: tcache[k] = week_team(Y, int(w["wk"]), w["opp"])
                    gl[int(w["wk"])] = dict(team=tcache[k], fpts=float(w.get("fpts") or 0), tgt=float(w.get("tgt") or 0), rp=hpts(w))
            team = cal.infer_team(rec, Y)
            games[(nm, Y)] = gl; clay[(nm, Y)] = cpg
            tms = {v["team"] for v in gl.values() if v["team"]} | ({team} if team else set())
            for t in tms: room[(Y, t)].append(nm)
    return games, clay, room


def main():
    X = setup(); n = X["n"]
    act, year, wk, pos, g, adp, name, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["team"]
    F = X["F"]; finw = np.where(year <= 2020, 17, 18); final = wk == finw
    top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    games, clayg, room = build_rooms(X["ch"])

    # league TE pts per target (half PPR)
    tt = sum(v["tgt"] for gl in games.values() for v in gl.values()); tp = sum(v["rp"] for gl in games.values() for v in gl.values())
    PPT_TE = tp / tt

    # ---- TE1 per team-season and his absences
    te1 = {}
    for (Y, t), lst in room.items():
        cand = [nm for nm in lst if any(v["team"] == t for v in games[(nm, Y)].values())]
        if not cand: continue
        best = max(cand, key=lambda nm: clayg[(nm, Y)])
        if clayg[(best, Y)] >= TE1_MIN: te1[(Y, t)] = best
    def te1_out(Y, t, w):
        nm = te1.get((Y, t))
        if not nm: return False
        gl = games[(nm, Y)]
        if w in gl and gl[w]["team"] == t: return False
        if any(v["team"] not in (t, None) and ww >= w for ww, v in gl.items()): return False   # moved on
        return True

    # ---- backup rows in the harness
    sel = np.zeros(n, bool); te2 = np.zeros(n, bool); first = np.zeros(n, bool); nfill = np.zeros(n); fill_ppg = np.zeros(n)
    t1lvl = np.zeros(n); t1clay = np.zeros(n); V = np.zeros(n); ppt = np.full(n, PPT_TE); frac_out = np.zeros(n); t1lead = np.zeros(n, bool)
    rowkey = {}
    for i in range(n):
        if pos[i] != "TE": continue
        Y, w, nm = int(year[i]), int(wk[i]), name[i]
        gl = games.get((nm, Y))
        if not gl or w not in gl: continue
        t = gl[w]["team"]
        if not t or te1.get((Y, t)) in (None, nm) or not te1_out(Y, t, w): continue
        sel[i] = True; rowkey[i] = (nm, Y, t)
        T1 = te1[(Y, t)]; g1 = games[(T1, Y)]
        played_t = [ww for ww, v in g1.items() if v["team"] == t]
        if not played_t: sel[i] = False; continue
        # TE2 of the week: best Clay among TEs playing for t in w other than TE1
        mates = [m_ for m_ in room[(Y, t)] if m_ != T1 and w in games[(m_, Y)] and games[(m_, Y)][w]["team"] == t]
        te2[i] = max(mates, key=lambda m_: clayg[(m_, Y)]) == nm
        # first game without TE1 = TE1 played the team's previous game (any earlier week for the team), else later
        prev = [ww for ww, v in gl.items() if ww < w and v["team"] == t]
        tw = sorted(set(prev) | {ww for ww in played_t if ww < w})
        first[i] = (not tw) or (max(tw) in played_t)
        # fill-in evidence: his earlier games for t where TE1 was out
        fi = [v["fpts"] for ww, v in gl.items() if ww < w and v["team"] == t and te1_out(Y, t, ww)]
        nfill[i] = len(fi); fill_ppg[i] = np.mean(fi) if fi else 0.0
        # TE1 level (P5 blend), targets per game so far
        e1 = [v for ww, v in g1.items() if ww < w and v["team"] == t]
        c1 = clayg[(T1, Y)]; t1clay[i] = c1
        t1lvl[i] = (LIVE_P * c1 + sum(v["fpts"] for v in e1)) / (LIVE_P + len(e1))
        ch1 = X["ch"][str(Y)][T1]; W = 16 if Y <= 2020 else 17; gm1 = ch1.get("gm") or 0
        clay_tg = (ch1.get("rec") or 0) / 0.68 / (gm1 if gm1 >= 4 else W)
        V[i] = (LIVE_P * clay_tg + sum(v["tgt"] for v in e1)) / (LIVE_P + len(e1)) if e1 else clay_tg
        mt = sum(v["tgt"] for ww, v in gl.items() if ww < w); mp = sum(v["rp"] for ww, v in gl.items() if ww < w)
        if mt >= 5: ppt[i] = mp / mt
        fut = [ww for ww in gl if ww >= w and ww < (17 if Y <= 2020 else 18) and gl[ww]["team"] == t]
        frac_out[i] = np.mean([te1_out(Y, t, ww) for ww in fut]) if fut else 1.0
        # was TE1 his team's season-to-date target leader? (engine 'lead' rule) - approximated with Clay-pool receivers
        t1lead[i] = False
    # engine lead flag: TE1 targets/g >= every teammate's (from the weekly DB of WR/RB in the room's team)
    tgt_lead = {}
    for (Y, t) in {(k[1], k[2]) for k in rowkey.values()}:
        tgt_lead[(Y, t)] = {}
    wr_by = defaultdict(list)
    for Y in YEARS:
        for nm, c in X["ch"][str(Y)].items():
            if c.get("pos") not in ("WR", "RB"): continue
            rec = cal.weekly_rec(nm, c["pos"])
            if rec is None: continue
            tmx = cal.infer_team(rec, Y)
            if (Y, tmx) in tgt_lead:
                wr_by[(Y, tmx)].append({int(w["wk"]): float(w.get("tgt") or 0) for w in rec["seasons"].get(str(Y), []) if cal.played(w)})
    for i in np.where(sel)[0]:
        nm, Y, t = rowkey[i]; w = int(wk[i]); T1 = te1[(Y, t)]
        e1 = [v["tgt"] for ww, v in games[(T1, Y)].items() if ww < w and v["team"] == t]
        if not e1: continue
        r1 = np.mean(e1)
        others = [np.mean([x for ww, x in d.items() if ww < w]) for d in wr_by[(Y, t)] if any(ww < w for ww in d)]
        t1lead[i] = all(r1 >= o for o in others)

    P(f"=== TE VACATED backtest: {n:,} Clay-pool player-weeks 2019-25 (live form replicated from backtest_fillin_usage, P 5) ===")
    P(f"    team-seasons with a TE1 (Clay >= {TE1_MIN} half-PPR/g): {len(te1)}; harness backup-TE rows in TE1-out weeks: {int(sel.sum())} "
      f"(TE2 {int((sel & te2).sum())}, TE3+ {int((sel & ~te2).sum())}); league TE half-PPR pts/target {PPT_TE:.3f}")
    P(f"    harness pool replay on those rows: pool_mult > 1 on {int((sel & (X['pool'] > 1)).sum())} of {int(sel.sum())} (mean when on {X['pool'][sel & (X['pool'] > 1)].mean() if (sel & (X['pool'] > 1)).any() else 1:.3f});"
      f" TE1 was his team's target leader (engine 'lead' rule) on {int((sel & t1lead).sum())} rows")

    # ---- targets / predictions
    seqn = defaultdict(list)
    for i in range(n):
        if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ix in seqn.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(X["layers"][ix], 0.5, 1.8)
        for a, i in enumerate(ix): nfut[i] = len(ix) - a; Tr[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    ramp = np.clip((nfut - 1.5) / np.maximum(nfut, 1), 0, 1)
    tilt = 1 - X["tilt_e"] * ramp * X["z"]; ctx0 = np.nan_to_num(ctx, nan=1.0)
    okN = (g >= 1) & ~final & ~X["inh"]
    okR1 = (g >= 1) & (g <= 10) & ~np.isnan(Tr) & ~X["inh"]; okR4 = okR1 & (nfut >= 4)
    base, luck = live_base(X)
    pool = X["pool"]; chain_np = X["chain"] / pool
    # per target: (label, T, ok, multiplier without pool, pool-window fraction for the target rows)
    TG = {"next": ("NEXT GAME", act, okN, chain_np, np.ones(n)),
          "ros4": ("REST OF SEASON, 4+ games left", Tr, okR4, ctx0 * tilt, frac_out),
          "ros1": ("REST OF SEASON, no survivor filter", Tr, okR1, ctx0 * tilt, frac_out)}
    KEYS = ("next", "ros4", "ros1")
    def pred_from(key, b=base, f=None, add=None, floor=None):
        """f = pool-type multiplier on sel rows (applied over frac window); add = additive pts per game on sel rows (window)"""
        _, T, ok, mult, fr = TG[key]
        pm = pool if key == "next" else np.where(sel, 1 + (pool - 1) * fr, 1.0)    # baseline: engine pool over the out window
        if f is not None: pm = np.where(sel, 1 + (f - 1) * fr, pm)
        p_ = b * mult * pm + luck
        if add is not None: p_ = p_ + np.where(sel, add * mult * fr, 0.0)
        if floor is not None:
            fl = floor * mult
            p_ = np.where(sel, (1 - fr) * p_ + fr * np.maximum(p_, fl + luck), p_)
        return np.maximum(0.0, p_)
    BASE = {k: pred_from(k) for k in KEYS}
    NOPOOL = {k: pred_from(k, f=np.ones(n)) for k in KEYS}

    # ================================================================ 1 bias
    P("\n--- 1  BIAS: mean actual / mean projected on backup-TE rows while TE1 is out (live = harness live form INCLUDING the engine pool;")
    P("        'no pool' = same without the pool layer).  under = seasons where actual > projected ---")
    def b(key, m, pr=None):
        _, T, ok, _, _ = TG[key]; m = m & ok; pr = BASE[key] if pr is None else pr
        if m.sum() < 8: return f"n {int(m.sum()):4d}"
        ys = [T[m & (year == y)].sum() / pr[m & (year == y)].sum() for y in YEARS if (m & (year == y)).sum() >= 4]
        return f"n {int(m.sum()):4d} act {T[m].mean():5.2f} live {pr[m].mean():5.2f} -> {T[m].mean()/pr[m].mean():.3f} (under {sum(1 for v in ys if v > 1)}/{len(ys)}) | no pool {T[m].mean()/NOPOOL[key][m].mean():.3f}"
    lvl = X["clay_gm"]
    SPL = [("ALL backup rows", sel), ("TE2 of the week", sel & te2), ("TE3+", sel & ~te2),
           ("TE2, first game without TE1", sel & te2 & first), ("TE2, later games", sel & te2 & ~first),
           ("TE2, 0 fill-in games in evidence", sel & te2 & (nfill == 0)), ("TE2, 1+ fill-in games", sel & te2 & (nfill >= 1)), ("TE2, 3+ fill-in games", sel & te2 & (nfill >= 3)),
           ("TE2, TE1 Clay >= 9 /g (elite)", sel & te2 & (t1clay >= 9)), ("TE2, TE1 Clay 6.5-9", sel & te2 & (t1clay >= 6.5) & (t1clay < 9)), ("TE2, TE1 Clay < 6.5", sel & te2 & (t1clay < 6.5)),
           ("TE2, own Clay < 2.5 /g", sel & te2 & (lvl < 2.5)), ("TE2, own Clay 2.5-4", sel & te2 & (lvl >= 2.5) & (lvl < 4)), ("TE2, own Clay >= 4", sel & te2 & (lvl >= 4)),
           ("TE2, TE1 = team target leader (engine lead)", sel & te2 & t1lead), ("TE2, TE1 not target leader (engine sec)", sel & te2 & ~t1lead),
           ("TE2, harness pool on (>1)", sel & te2 & (pool > 1)), ("TE2, harness pool off", sel & te2 & (pool <= 1))]
    for key in KEYS:
        P(f"\n  {TG[key][0]}")
        for lab, m in SPL: P(f"    {lab:46s} {b(key, m)}")
    # selection control: low-Clay TEs in normal weeks (rows exist only for games with a stat)
    P("\n  CONTROL (selection on games with a stat): TE rows NOT in TE1-out weeks, by own Clay level, next game")
    for lab, m in (("own Clay < 2.5", (pos == "TE") & ~sel & (lvl < 2.5)), ("own Clay 2.5-4", (pos == "TE") & ~sel & (lvl >= 2.5) & (lvl < 4)), ("own Clay >= 4", (pos == "TE") & ~sel & (lvl >= 4))):
        P(f"    {lab:46s} {b('next', m)}")
    # per-season bias
    _, T, ok, _, _ = TG["next"]; m = sel & te2 & ok
    P("    TE2 next game by season: " + "  ".join(f"{y}: n{int((m & (year == y)).sum())} {T[m & (year == y)].mean() / max(BASE['next'][m & (year == y)].mean(), 1e-9):.2f}" for y in YEARS))

    # ---- where do the targets go (all weekly-DB TEs, not only harness rows)
    P("\n--- 2  TARGET FLOW (weekly DB, every TE1-out team-week 2019-25; TE1 season-to-date tgt/g before the week; healthy TE ranked by Clay)")
    acc = defaultdict(lambda: [0.0, 0.0, 0.0, 0])   # key -> [sum delta tgt, sum V, sum delta pts, n]
    for (Y, t), T1 in te1.items():
        g1 = games[(T1, Y)]; played_t = sorted(ww for ww, v in g1.items() if v["team"] == t)
        tw = sorted({ww for m_ in room[(Y, t)] for ww, v in games[(m_, Y)].items() if v["team"] == t})
        mates = [m_ for m_ in room[(Y, t)] if m_ != T1]
        for w in tw:
            if not te1_out(Y, t, w): continue
            e1 = [g1[ww]["tgt"] for ww in played_t if ww < w]
            if len(e1) < 2: continue
            Vw = np.mean(e1)
            # mates ranked by Clay per game; delta vs their games with TE1 present (same season)
            rk = sorted(mates, key=lambda m_: -clayg[(m_, Y)])
            healthy = [m_ for m_ in rk if any(v["team"] == t for v in games[(m_, Y)].values())]
            for r_, m_ in enumerate(healthy[:2]):
                gm_ = games[(m_, Y)]
                with_ = [v for ww, v in gm_.items() if v["team"] == t and ww in played_t]
                # games present with TE1 (rows exist only for stat games; weeks with no row while TE1 played count 0)
                pres = [gm_[ww]["tgt"] if ww in gm_ else 0.0 for ww in played_t]
                prp = [gm_[ww]["rp"] if ww in gm_ else 0.0 for ww in played_t]
                if len(pres) < 2: continue
                cur_t = gm_[w]["tgt"] if w in gm_ else 0.0; cur_p = gm_[w]["rp"] if w in gm_ else 0.0
                k = ("TE2" if r_ == 0 else "TE3", "first" if (not [ww for ww in tw if ww < w]) or max(ww for ww in tw if ww < w) in played_t else "later")
                a = acc[k]; a[0] += cur_t - np.mean(pres); a[1] += Vw; a[2] += cur_p - np.mean(prp); a[3] += 1
                a = acc[(k[0], "all")]; a[0] += cur_t - np.mean(pres); a[1] += Vw; a[2] += cur_p - np.mean(prp); a[3] += 1
    for k in sorted(acc):
        a = acc[k]
        P(f"    healthy {k[0]} ({k[1]:5s}): n {a[3]:4d} | TE1 vacated {a[1]/a[3]:4.1f} tgt/g | gain {a[0]/a[3]:+5.2f} tgt/g = {a[0]/a[1]:+.2f} of vacated | {a[2]/a[3]:+5.2f} half-PPR pts/g")
    P("    (engine: TE lead out -> TE2 +0.25, WR +0.36; TE sec out -> healthy TE ranked 1st +0.00, 2nd +0.22.  backtest_vacated_pool.py needed a")
    P("     trailing baseline in 2 of 3 games, so a back-up with no stat rows fell into 'new bodies' (+0.61 of a sec TE's vacated targets);")
    P("     here a week with no stat row while TE1 played counts as 0 targets for the back-up.)")

    # ================================================================ 3 rules
    def mse(pr, T, m):
        d_ = pr[m] - T[m]; return float(np.mean(d_ * d_)) if m.any() else np.nan
    def rho(pr, T, ok, yrs, ps=None):
        gr = defaultdict(list)
        for i in np.where(ok & top150 & np.isin(year, list(yrs)) & ((pos == ps) if ps else True))[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        out = [np.corrcoef(rankdata(T[ix]), rankdata(pr[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]
        return float(np.nanmean(out))
    def cell(key, pr, m, yrs=YEARS, minrows=4):
        _, T, ok, _, _ = TG[key]; bs = BASE[key]; m = m & ok & np.isin(year, list(yrs))
        if m.sum() < 15: return f"{'n/a (n' + str(int(m.sum())) + ')':>22s}"
        ys = [y for y in yrs if (m & (year == y)).sum() >= minrows]
        wins = sum(1 for y in ys if mse(pr, T, m & (year == y)) < mse(bs, T, m & (year == y)) - 1e-12)
        return f"{100*(mse(pr, T, m)/mse(bs, T, m)-1):+7.2f}% ({wins}/{len(ys)}) n{int(m.sum())}"
    def board(key, pr, yrs=YEARS):
        _, T, ok, _, _ = TG[key]; bs = BASE[key]; m = ok & np.isin(year, list(yrs)); mte = m & (pos == "TE"); m150 = m & top150
        a = 100 * (mse(pr, T, m) / mse(bs, T, m) - 1); te = 100 * (mse(pr, T, mte) / mse(bs, T, mte) - 1)
        w_ = 100 * (np.average((pr[m150] - T[m150]) ** 2, weights=wt[m150]) / np.average((bs[m150] - T[m150]) ** 2, weights=wt[m150]) - 1)
        mt = m150 & (pos == "TE")
        wte = 100 * (np.average((pr[mt] - T[mt]) ** 2, weights=wt[mt]) / np.average((bs[mt] - T[mt]) ** 2, weights=wt[mt]) - 1)
        return (f"TE {te:+.3f}% TE150w {wte:+.3f}% TErank {rho(pr, T, ok, yrs, 'TE') - rho(bs, T, ok, yrs, 'TE'):+.4f} | all {a:+.3f}% 150w {w_:+.3f}% rank {rho(pr, T, ok, yrs) - rho(bs, T, ok, yrs):+.4f}")

    own = ppg_own = X["ppg"]
    def f_share(s, scope):
        gained = s * V * ppt * 0.92
        return np.where(scope, 1 + gained / np.maximum(own, 3.5), pool)
    def add_share(s, scope):
        return np.where(scope, s * V * ppt * 0.92, 0.0)
    S_GRID = (0.25, 0.35, 0.45, 0.55, 0.70)
    K_GRID = (0.15, 0.25, 0.35, 0.45, 0.55, 0.70)
    PC_GRID = (0.5, 1.0, 2.0, 3.0, 5.0)
    TE2s = sel & te2
    def mk(key, fam, v, scope=TE2s):
        if fam == "a": return pred_from(key, f=f_share(v, scope))
        if fam == "a+": return pred_from(key, f=np.where(scope, 1.0, pool), add=add_share(v, scope))
        if fam == "bfl": return pred_from(key, floor=np.where(scope, v * t1lvl, 0.0))
        if fam == "badd": return pred_from(key, f=np.where(scope, 1.0, pool), add=np.where(scope, v * t1lvl, 0.0))
        if fam == "c":
            sc = scope & (nfill >= 1)
            b2 = np.where(sc, (v * base + nfill * fill_ppg) / (v + nfill), base)
            return pred_from(key, b=b2)
        if fam == "cnp":
            sc = scope & (nfill >= 1)
            b2 = np.where(sc, (v * base + nfill * fill_ppg) / (v + nfill), base)
            return pred_from(key, b=b2, f=np.where(sc, 1.0, pool))
        if fam == "d":   # engine sec rule share for TE2 (lead rows keep the engine .25 replay as is unless below)
            sc = scope & ~t1lead
            return pred_from(key, f=np.where(sc, 1 + v * V * ppt * 0.92 / np.maximum(own, 3.5), pool))
        raise ValueError(fam)
    FAMS = [("a   TE2 share of TE1 targets (engine ratio form)", "a", S_GRID),
            ("a+  TE2 share, gain ADDED (no floor damping)", "a+", S_GRID),
            ("b   floor k x TE1 level", "bfl", K_GRID),
            ("b+  additive k x TE1 level (no pool)", "badd", K_GRID),
            ("c   fill-in games blend Pc (pool kept)", "c", PC_GRID),
            ("c-  fill-in games blend Pc (pool dropped)", "cnp", PC_GRID),
            ("d   sec-rule TE2 share (TE1 not target leader)", "d", S_GRID)]
    HDR = f"    {'rule':52s} {'TE2 rows':>22s} {'TE2 first game':>22s} {'TE2 later':>22s} {'TE3+ (untouched)':>18s} | board"
    for key in KEYS:
        P(f"\n--- 3  FIXED GRIDS, {TG[key][0]}: error vs live on the TE2 rows (seasons better); board = all rows of the target ---"); P(HDR)
        for lab, fam, grid in FAMS:
            for v in grid:
                pr = mk(key, fam, v)
                P(f"    {lab[:40]:40s} {v:>11.2f} {cell(key, pr, TE2s)} {cell(key, pr, TE2s & first)} {cell(key, pr, TE2s & ~first)} | {board(key, pr)}")
            pr0 = mk(key, fam, grid[len(grid) // 2])
        P("    -- 2022-25 only (fixed) --")
        for lab, fam, grid in FAMS:
            for v in grid:
                pr = mk(key, fam, v)
                P(f"    {lab[:40]:40s} {v:>11.2f} {cell(key, pr, TE2s, FWD)} | {board(key, pr, FWD)}")

    # ---- LOYO / forward fits
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    def fit(key, fam, grid, folds):
        _, T, ok, _, _ = TG[key]; preds = {v: mk(key, fam, v) for v in grid}; out = BASE[key].copy(); picks = []
        m = TE2s & ok
        for tr, te in folds:
            trm = np.isin(year, tr)
            best = min(grid, key=lambda v: mse(preds[v], T, m & trm)); picks.append(best)
            s_ = sel & (year == te); out[s_] = preds[best][s_]
        return out, picks
    SUMMARY = []
    for key in KEYS:
        P(f"\n--- 4  LOYO (fit on the TE2 rows of the other six seasons) and FORWARD (fit on earlier seasons, graded 2022-25): {TG[key][0]} ---")
        for lab, fam, grid in FAMS:
            pr, pk = fit(key, fam, grid, LOSO); prf, pkf = fit(key, fam, grid, FORW)
            P(f"    {lab:52s} LOYO {cell(key, pr, TE2s)} | {board(key, pr)}")
            P(f"    {'':52s} picks {pk}")
            P(f"    {'':52s} FWD  {cell(key, prf, TE2s, FWD)} | {board(key, prf, FWD)}  picks {pkf}")
            _, T, ok, _, _ = TG[key]; m = TE2s & ok
            SUMMARY.append((key, lab, cell(key, pr, TE2s).strip(), cell(key, prf, TE2s, FWD).strip(), board(key, pr), pk, pkf,
                            T[m].mean() / BASE[key][m].mean(), T[m].mean() / pr[m].mean()))
    P("\n--- 5  SUMMARY (TE2 rows: LOYO error change (seasons better /7) | forward (/4) | bias live -> rule | board, LOYO) ---")
    for key, lab, c1, c2, bd, pk, pkf, b0, b1 in SUMMARY:
        P(f"    {key:5s} {lab:52s} LOYO {c1:24s} FWD {c2:24s} bias {b0:.3f}->{b1:.3f} | {bd}")
    # ================================================================ 6 candidate detail
    adpx = np.where(np.isnan(adp), 999.0, adp)
    m150 = sel & te2 & (adpx <= 150)
    P(f"\n--- 6  CANDIDATES IN DETAIL (fixed values, no fitting) ---")
    P(f"    TE2 rows with ADP <= 150 (the only touched rows inside the top-150 weighting): {int(m150.sum())}")
    for i in np.where(m150 & okN)[0]:
        nm, Y, t = rowkey[i]
        P(f"      {Y} wk{int(wk[i]):2d} {nm:22s} {t:3s} ADP {adp[i]:5.0f} own Clay {lvl[i]:4.1f} TE1 {te1[(Y, t)]:20s} ({t1clay[i]:4.1f}) | act {act[i]:5.1f} live {BASE['next'][i]:5.1f} a.25 {mk('next', 'a', 0.25)[i]:5.1f}")
    lowc = TE2s & (lvl < 4.0); undr = TE2s & (adpx > 150)
    CAND = [("a .25  all TE2", "a", 0.25, TE2s), ("a .35  all TE2", "a", 0.35, TE2s), ("d .25  sec rows only (= lead value)", "d", 0.25, TE2s),
            ("b+ .25 additive TE1 level", "badd", 0.25, TE2s), ("b+ .35 additive TE1 level", "badd", 0.35, TE2s),
            ("a .25  TE2 own Clay < 4", "a", 0.25, lowc), ("a .35  TE2 own Clay < 4", "a", 0.35, lowc), ("a .45  TE2 own Clay < 4", "a", 0.45, lowc),
            ("b+ .25 TE2 own Clay < 4", "badd", 0.25, lowc), ("b+ .35 TE2 own Clay < 4", "badd", 0.35, lowc),
            ("a .25  TE2 ADP > 150", "a", 0.25, undr), ("a .35  TE2 ADP > 150", "a", 0.35, undr)]
    for key in KEYS:
        _, T, ok, _, _ = TG[key]
        P(f"\n  {TG[key][0]}")
        for lab, fam, v, sc in CAND:
            pr = mk(key, fam, v, sc); m = TE2s & ok
            ys = "  ".join(f"{y}:{100*(mse(pr, T, m & (year == y))/mse(BASE[key], T, m & (year == y))-1):+.0f}%/n{int((m & (year == y)).sum())}" for y in YEARS if (m & (year == y)).sum() >= 4)
            P(f"    {lab:36s} {cell(key, pr, TE2s)} fwd {cell(key, pr, TE2s, FWD)} bias {T[m].mean()/BASE[key][m].mean():.3f}->{T[m].mean()/pr[m].mean():.3f} | {ys}")
            P(f"    {'':36s} board LOYO-free all seasons: {board(key, pr)} | fwd: {board(key, pr, FWD)}")

    # ================================================================ 7 the engine-shaped candidate: share for a TRUE back-up TE2
    P("\n--- 7  ENGINE-SHAPED: TE2 share only when the TE2 is a true back-up (own Clay < 4 half-PPR/g); share LOYO / forward fitted ---")
    sc_low = TE2s & (lvl < 4.0)
    for fam, lab in (("a", "a  share, lead + sec rows"), ("d", "d  share, sec rows only (lead keeps engine .25)")):
        for key in KEYS:
            _, T, ok, _, _ = TG[key]; preds = {v: mk(key, fam, v, sc_low) for v in S_GRID}
            def fitf(folds):
                out = BASE[key].copy(); pk = []
                for tr, te in folds:
                    best = min(S_GRID, key=lambda v: mse(preds[v], T, TE2s & ok & np.isin(year, tr))); pk.append(best)
                    s_ = sel & (year == te); out[s_] = preds[best][s_]
                return out, pk
            pr, pk = fitf(LOSO); prf, pkf = fitf(FORW)
            P(f"    {lab:46s} {key:5s} LOYO {cell(key, pr, TE2s)} picks {pk} | FWD {cell(key, prf, TE2s, FWD)} picks {pkf} | board {board(key, pr)}")

    # ================================================================ 8 ADP bands (Jack: top 30 / 60 / 100)
    P("\n--- 8  ADP BANDS: recommended rule (fixed .25, TE2 own Clay < 4) and fixed .25 all TE2 ---")
    P("    touched = rows whose projection changes. Both rules change ONLY the TE2's own row: the engine sec rule has tgtOther 0,")
    P("    so no WR/TE teammate moves (the lead rule's .25 / WR .36 is already live and unchanged).")
    BND = [("ADP 1-30", (adpx > 0) & (adpx <= 30)), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100)),
           ("top 30", adpx <= 30), ("top 60", adpx <= 60), ("top 100", adpx <= 100), ("101-150", (adpx > 100) & (adpx <= 150)), ("151+/none", adpx > 150)]
    RULES = [("rec  .25 own Clay<4", None, lowc), ("all  .25 all TE2", None, TE2s)]
    for key in KEYS:
        _, T, ok, _, _ = TG[key]; P(f"\n  {TG[key][0]}")
        for rl, _, sc in RULES:
            pr = mk(key, "a", 0.25, sc); chg = ok & (np.abs(pr - BASE[key]) > 1e-9)
            for bl, bm in BND:
                mb = ok & bm; tch = chg & bm
                if mb.sum() == 0: continue
                allc = 100 * (mse(pr, T, mb) / mse(BASE[key], T, mb) - 1)
                rk = rho(pr, T, ok & bm, YEARS) - rho(BASE[key], T, ok & bm, YEARS) if (bm & top150).any() else float('nan')
                if tch.sum() == 0:
                    P(f"    {rl:20s} {bl:10s} touched 0 rows (band n {int(mb.sum())}) -> no change")
                else:
                    P(f"    {rl:20s} {bl:10s} touched {int(tch.sum())}: {cell(key, pr, tch, minrows=1) if tch.sum() >= 15 else f'{100*(mse(pr, T, tch)/mse(BASE[key], T, tch)-1):+.1f}% (n{int(tch.sum())}, too few for season counts)'}"
                      f" | all band rows {allc:+.3f}% (n {int(mb.sum())}) | rank {rk:+.4f}")
    # current engine bias for top-100 TEs whose TE teammate was out
    P("\n  CURRENT live bias, TE rows (ADP <= 100) in weeks a TE teammate (played for the team that season) was out:")
    tmo = np.zeros(n, bool)
    for i in np.where((pos == "TE") & (adpx <= 100))[0]:
        Y, w, nm = int(year[i]), int(wk[i]), name[i]; gl = games.get((nm, Y))
        if not gl or w not in gl or not gl[w]["team"]: continue
        t = gl[w]["team"]
        for m_ in room[(Y, t)]:
            if m_ == nm: continue
            g2 = games[(m_, Y)]
            if not any(v["team"] == t for v in g2.values()) or (w in g2 and g2[w]["team"] == t): continue
            if any(v["team"] not in (t, None) and ww >= w for ww, v in g2.items()): continue
            if clayg[(m_, Y)] >= 2.0: tmo[i] = True
    for key in KEYS:
        _, T, ok, _, _ = TG[key]
        for bl, bm in BND[:6]:
            m = ok & tmo & bm
            P(f"    {key:5s} {bl:10s} n {int(m.sum()):4d}" + (f"  act {T[m].mean():5.2f} live {BASE[key][m].mean():5.2f} -> {T[m].mean()/BASE[key][m].mean():.3f}" if m.sum() >= 5 else ""))

    P("\nLimitations: rows exist only for games with a stat (a back-up's 0-target games are missing from evidence AND targets);")
    P("TE1 'out' = no stat row (a TE1 who played without a stat would read as out); team per game from the schedule; harness = Clay")
    P("pool (40+ pts), so deep back-ups are absent; rest-of-season windows use the starter's ACTUAL absences (oracle; the engine")
    P("knows the injury window + availability curve only); prop anchor / pecking dock not replayable.")
    LOG.close()


if __name__ == "__main__":
    main()
