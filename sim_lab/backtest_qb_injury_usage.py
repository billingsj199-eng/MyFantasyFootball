#!/usr/bin/env python3
"""
QB-AWARE EVIDENCE, BANGED-UP PRIOR DISCOUNT, HEAVIER / SITUATION-AWARE USAGE  (Jack 2026-10-07, after the
Drake London / Brock Bowers question: "can we add a qb aware test / injury discount ... increase the usage in the
projections ... make sure usage is hyper aware of situation though qb / other injuries on team etc").  RESEARCH.

Live form replicated from backtest_fillin_usage.py (setup / live_base copied, not imported - importing truncates
its log): base = (5 x Clay per game + g x evidence) / (5 + g), WR / TE usage mix, RB snap mix, rookie level,
TD luck, chain (next game) / mean context x tilt (rest of season). 2019-25, every season held out.

T1  QB-AWARE EVIDENCE   a receiver's game is 'off-QB' when the QB who threw the most passes for his team that
    week is not the QB expected to start the target week. Expected starter = (a) the starter of the team's most
    recent game (what the engine can know without a depth chart), (b) the actual starter of the target week
    (oracle upper bound). Off-QB games get weight w in the points evidence and in the per-game usage inputs.
T2  BANGED-UP PRIOR      last season's games tagged hurt = listed Questionable, or practice Limited / DNP that
    week, or snap share < 75% of his own season median. Clay's per-game prior is lifted toward last season's
    HEALTHY points per game when he had 3+ hurt games (the Bowers 2025 case).
T3  USAGE WEIGHT         heavier lam schedules for WR / TE (incl. TE from game 1); usage inputs made situation-
    aware: off-QB games, his own banged-up games and stale fill-in games (all ADP) reweighted in the usage
    inputs only, points evidence untouched.
Graded: next game, rest of season 4+ left, rest of season all; MSE vs the live replica, seasons better of 7,
top-150 weighted, within-position rank; LOYO and forward (2022-25) picks. Log qb_injury_usage.log.
"""
import json, os, re, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import research_clay_vs_shadow as CS
import bt_common as B
from backtest_inseason_usage import route_features
cal = NW.cal
warnings.filterwarnings("ignore")

YEARS = list(NW.YEARS); POS4 = ("QB", "RB", "WR", "TE"); SK = ("RB", "WR", "TE"); FWD = (2022, 2023, 2024, 2025)
LIVE_P = 5
TDK = {"QB": 0.5 * 4.0, "RB": 0.75 * 6.0, "WR": 1.0 * 6.0, "TE": 1.0 * 6.0}
USE_C = {"WR": (0.37, 0.53, 0.005, 0.050), "TE": (-1.87, 0.47, 0.023, 0.057)}
ROS_TILT = {"QB": 0.06, "TE": 0.08}
REG_MIN = 5.0
BOOST = {"RB": 1.26, "WR": 1.08, "TE": 1.15}
WGRID = (0.0, 0.25, 0.5, 0.75, 1.0)
REFINE = "--refine" in sys.argv
LOG = open(os.path.join(HERE, "qb_injury_usage_refine.log" if REFINE else "qb_injury_usage.log"), "w", encoding="utf-8") if __name__ == "__main__" else None
def P(s=""):
    print(s)
    if LOG: LOG.write(s + chr(10)); LOG.flush()


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
                useok=useok, tdl=tdl, tdk=tdk, rook=rook, inh=inh, rbu=rbu, chain=chain, z=z, tilt_e=tilt_e, hasC=hasC, xfp=xfp, snap=snap, rt=rt, team=team,
                snap_l1=cv("snap_l1"), ch=ch, rep_q=cv("rep_q"), prac_lim=cv("prac_lim"), prac_dnp=cv("prac_dnp"))


def uimp_of(X, xfp, snap):
    pos = X["pos"]; cw, ct = USE_C["WR"], USE_C["TE"]; rt = X["rt"]
    u = np.where(pos == "WR", cw[0] + cw[1] * xfp + cw[2] * rt + cw[3] * snap, ct[0] + ct[1] * xfp + ct[2] * rt + ct[3] * snap)
    return np.maximum(0.0, np.nan_to_num(u, nan=0.0))


def live_base(X, ppg, ge, xfp, snap, lam=None, clay=None):
    """live per-game base + TD-luck term with the points evidence, the evidence game count, the WR/TE usage inputs,
    the usage weight and the Clay prior all swappable. TD luck keeps the real game count."""
    g, pos = X["g"], X["pos"]
    lam = X["lam"] if lam is None else lam
    clay = X["clay_gm"] if clay is None else clay
    ev = np.where(lam > 0, lam * uimp_of(X, xfp, snap) + (1 - lam) * ppg, ppg)
    base = np.where(ge > 1e-9, (LIVE_P * clay + ge * ev) / (LIVE_P + ge), clay)
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


# ------------------------------------------------------------------ game tables: skill games, team-week starting QB, fill-in regulars
def build_games(X):
    ch = X["ch"]; tcache = {}
    games = {}                           # (name, pos, Y) -> (season team, clay pg, {wk: (fpts, team that week)})
    roster = defaultdict(list)           # (Y, team, pos) -> [(name, clay pg)]
    qbpa = defaultdict(dict)             # (Y, team, wk) -> {qb: pass attempts}
    for Y in YEARS + [YEARS[0] - 1]:     # one extra season back for the T2 prior (2018 games where the stats exist)
        W = 16 if Y <= 2020 else 17
        pool = ch.get(str(Y)) or ch[str(YEARS[0])]
        for nm, c in pool.items():
            ps = c.get("pos")
            if ps not in POS4: continue
            rec = cal.weekly_rec(nm, ps)
            if rec is None: continue
            team = cal.infer_team(rec, Y) if Y in YEARS else None
            gmv = (c.get("gm") or 0); half = max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0)
            cpg = half / gmv if gmv >= 4 else half / W
            gl = {}
            for w in rec.get("seasons", {}).get(str(Y), []):
                if not (cal.played(w) and isinstance(w.get("fpts"), (int, float)) and w.get("opp")): continue
                k = (Y, int(w["wk"]), w["opp"])
                if k not in tcache: tcache[k] = week_team(Y, int(w["wk"]), w["opp"])
                tw = tcache[k]
                if ps == "QB":
                    pa = w.get("pa") or 0
                    if pa > 0 and tw: qbpa[(Y, tw, int(w["wk"]))][nm] = qbpa[(Y, tw, int(w["wk"]))].get(nm, 0) + pa
                else:
                    gl[int(w["wk"])] = (float(w["fpts"]), tw)
            if ps in SK:
                games[(nm, ps, Y)] = (team, cpg, gl)
                if team and Y in YEARS: roster[(Y, team, ps)].append((nm, cpg))
    starter = {k: max(v, key=v.get) for k, v in qbpa.items() if max(v.values()) >= 10}
    team_weeks = defaultdict(list)
    for (Y, t, w) in starter: team_weeks[(Y, t)].append(w)
    for k in team_weeks: team_weeks[k].sort()
    return games, roster, starter, team_weeks


def build_fillin(games, roster):
    """per player-season: evidence games with the regulars absent that week (backtest_fillin_usage definitions)"""
    info = {}
    for (nm, ps, Y), (team, cpg, gl) in games.items():
        if not team or Y not in YEARS: continue
        regs = [(r, rc) for r, rc in roster[(Y, team, ps)] if r != nm and rc > cpg and rc >= REG_MIN]
        rplay = {r: {w for w, (f, t) in games[(r, ps, Y)][2].items() if t == team} for r, _ in regs}
        rows = {}
        for w in sorted(gl):
            f, t = gl[w]
            rows[w] = tuple(r for r, _ in regs if t == team and w not in rplay[r])
        info[(nm, ps, Y)] = (rows, rplay)
    return info


def load_injuries():
    inj = {}
    for Y in YEARS + [YEARS[0] - 1]:
        p = os.path.join(B.CACHE, f"injuries_{Y}.parquet")
        if not os.path.exists(p): continue
        d = pd.read_parquet(p, columns=["game_type", "team", "week", "gsis_id", "report_status", "practice_status"])
        d = d[d.game_type == "REG"]
        for t, w, gid, rs, pr in zip(d.team, d.week, d.gsis_id, d.report_status, d.practice_status):
            if not isinstance(gid, str): continue
            inj[(Y, B.tm(str(t)), int(w), gid)] = (str(rs) if isinstance(rs, str) else "", str(pr) if isinstance(pr, str) else "")
    return inj


def load_snaps():
    s = open(os.path.join(cal.REPO, "data", "snap_counts.js"), encoding="utf-8").read()
    s = s[s.index("{"):]
    raw, _ = json.JSONDecoder().raw_decode(s); out = {}
    for nm, yrs in raw.items():
        out[cal.norm(nm)] = {int(y): {int(w): float(v) for w, v in (d.get("w") or {}).items()} for y, d in yrs.items()}
    return out


def main():
    X = setup(); n = X["n"]
    act, year, wk, pos, g, adp, name, pid, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["pid"], X["team"]
    F = X["F"]; finw = np.where(year <= 2020, 17, 18); final = wk == finw
    adpx = np.where(np.isnan(adp), 999.0, adp); top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2

    games, roster, starter, team_weeks = build_games(X)
    fill = build_fillin(games, roster)
    inj = load_injuries(); snaps = load_snaps()
    P(f"tables: {len(games):,} skill player-seasons, {len(starter):,} team-week starting QBs, {len(inj):,} injury-report rows, {len(snaps):,} players with snap counts")

    # per-game xFP / snap share from the cumulative context columns (as research_excused_games.py / fill-in harness)
    xfp, snl1 = X["xfp"], X["snap_l1"]
    seq = defaultdict(list)
    for i in range(n): seq[(name[i], pos[i], int(year[i]))].append(i)
    gx, gsn = {}, {}
    for (nm, ps, Y), ix in seq.items():
        ix.sort(key=lambda i: wk[i])
        for a in range(len(ix) - 1):
            i, j = ix[a], ix[a + 1]
            if g[j] - g[i] == 1 and not np.isnan(xfp[j]):
                prevx = xfp[i] * g[i] if (g[i] > 0 and not np.isnan(xfp[i])) else (0.0 if g[i] == 0 else np.nan)
                if not np.isnan(prevx): gx[(nm, ps, Y, int(wk[i]))] = xfp[j] * g[j] - prevx
            if g[j] - g[i] == 1 and not np.isnan(snl1[j]): gsn[(nm, ps, Y, int(wk[i]))] = snl1[j]
    pid_of = {}
    for i in range(n):
        if pid[i]: pid_of[(name[i], pos[i])] = pid[i]

    def hurt_tag(nm, ps, Y, w, tw):
        """(listed Questionable, practice limited / DNP, low snap share) for a game he played"""
        gid = pid_of.get((nm, ps)); rs, pr = inj.get((Y, tw, w, gid), ("", "")) if (gid and tw) else ("", "")
        q = rs == "Questionable"; lim = ("Limited" in pr) or ("Did Not" in pr)
        sy = snaps.get(cal.norm(nm), {}).get(Y, {})
        med = np.median([v for v in sy.values() if v > 0]) if len([v for v in sy.values() if v > 0]) >= 4 else None
        low = (med is not None and w in sy and sy[w] > 0 and sy[w] < 0.75 * med)
        return q, lim, low

    # ---------------- per-row evidence lists
    Z = lambda: np.zeros(n)
    covered = np.zeros(n, bool)
    EV = [None] * n                       # per row: dict of arrays over the evidence games
    exp_last = [None] * n; exp_act = [None] * n; qb_new = np.zeros(n, bool); qb_known = np.zeros(n, bool)
    prev = {"healthy": np.full(n, np.nan), "all": np.full(n, np.nan), "hurtN": Z(), "healthyN": Z(), "N": Z()}
    cur_hurt_pts = defaultdict(list)
    for i in range(n):
        if pos[i] not in SK or g[i] < 1: continue
        key = (name[i], pos[i], int(year[i])); Y = int(year[i])
        if key not in games: continue
        tm_, cpg, gl = games[key]
        evw = [w for w in sorted(gl) if w < wk[i]]
        if len(evw) != int(g[i]) or not tm_: continue
        covered[i] = True
        tw_list = team_weeks.get((Y, tm_), [])
        prior_w = [w for w in tw_list if w < wk[i]]
        s_last = starter.get((Y, tm_, prior_w[-1])) if prior_w else None
        s_act = starter.get((Y, tm_, int(wk[i])))
        exp_last[i] = s_last; exp_act[i] = s_act
        qb_known[i] = s_last is not None
        f_, x_, s_, offL, offA, hurt, stale, hasx, hass = [], [], [], [], [], [], [], [], []
        rows_f, rplay = fill.get(key, ({}, {}))
        n_prior_starts = 0
        for w in evw:
            f, tw = gl[w]
            qb = starter.get((Y, tw, w)) if tw else None
            offL.append(qb is not None and s_last is not None and qb != s_last)
            offA.append(qb is not None and s_act is not None and qb != s_act)
            if qb is not None and s_last is not None and qb == s_last: n_prior_starts += 1
            q, lim, low = hurt_tag(name[i], pos[i], Y, w, tw)
            hurt.append(q or lim or low)
            ab = rows_f.get(w, ())
            stale.append(any(wk[i] in rplay[r] for r in ab))
            gk = (name[i], pos[i], Y, w)
            f_.append(f); x_.append(gx.get(gk, np.nan)); s_.append(gsn.get(gk, np.nan))
            if hurt[-1]: cur_hurt_pts[(pos[i], "hurt")].append(f)
            else: cur_hurt_pts[(pos[i], "ok")].append(f)
        qb_new[i] = qb_known[i] and n_prior_starts <= 1
        EV[i] = dict(f=np.array(f_), x=np.array(x_, float), s=np.array(s_, float), offL=np.array(offL, bool), offA=np.array(offA, bool),
                     hurt=np.array(hurt, bool), stale=np.array(stale, bool))
        # previous season for the T2 prior
        pk = (name[i], pos[i], Y - 1)
        if pk in games:
            _, _, pgl = games[pk]
            hp, ap = [], []
            for w, (f, tw) in pgl.items():
                q, lim, low = hurt_tag(name[i], pos[i], Y - 1, w, tw)
                ap.append(f)
                if not (q or lim or low): hp.append(f)
            if len(ap) >= 4:
                prev["all"][i] = np.mean(ap); prev["N"][i] = len(ap); prev["hurtN"][i] = len(ap) - len(hp); prev["healthyN"][i] = len(hp)
                if len(hp) >= 4: prev["healthy"][i] = np.mean(hp)
    ppg_chk = np.array([EV[i]["f"].mean() if EV[i] is not None else np.nan for i in range(n)])
    chk = covered & ~np.isnan(ppg_chk)
    P(f"rows: {int(covered.sum()):,} RB/WR/TE player-weeks with the evidence rebuilt (of {int((np.isin(pos, SK) & (g >= 1)).sum()):,}); replica ppg max abs diff {np.nanmax(np.abs(ppg_chk[chk] - X['ppg'][chk])):.3f}, rows off > 0.05: {int((chk & (np.abs(ppg_chk - X['ppg']) > 0.05)).sum())}")

    def counts(flag):
        return np.array([EV[i][flag].sum() if EV[i] is not None else 0 for i in range(n)])
    nev = np.array([len(EV[i]["f"]) if EV[i] is not None else 0 for i in range(n)])
    n_offL, n_offA, n_hurt, n_stale = counts("offL"), counts("offA"), counts("hurt"), counts("stale")

    # ---------------- targets (fill-in harness)
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
    TG = {"next": ("NEXT GAME", act, okN, X["chain"]), "ros4": ("REST OF SEASON, 4+ games left", Tr, okR4, ctx0 * tilt),
          "ros1": ("REST OF SEASON, no survivor filter", Tr, okR1, ctx0 * tilt)}
    KEYS = ("next", "ros4", "ros1")

    def predict(key, ppg=None, ge=None, xf=None, sn=None, lam=None, clay=None):
        _, T, ok, mult = TG[key]
        b, lk = live_base(X, X["ppg"] if ppg is None else ppg, g.astype(float) if ge is None else ge, X["xfp"] if xf is None else xf,
                          X["snap"] if sn is None else sn, lam=lam, clay=clay)
        return np.maximum(0.0, b * mult + lk)
    BASE = {k: predict(k) for k in KEYS}

    def reweight(flag, w, scope, points=True, usage=True, divide=None):
        """evidence with the flagged games weighted w (or their points / xFP divided by `divide`) for rows in scope.
        points: the points-per-game evidence and game count; usage: the per-game xFP and snap inputs."""
        ppg = X["ppg"].copy(); ge = g.astype(float).copy(); xf = X["xfp"].copy(); sp = X["snap"].copy()
        for i in np.where(scope & covered)[0]:
            e = EV[i]; fl = e[flag]
            if not fl.any(): continue
            if divide is None:
                wv = np.where(fl, w, 1.0)
            else:
                wv = np.ones(len(fl))
            if points:
                if divide is None:
                    den = wv.sum(); ppg[i] = max(0.0, float((wv * e["f"]).sum() / den)) if den > 1e-9 else 0.0; ge[i] = den
                else:
                    ppg[i] = max(0.0, float(np.where(fl, e["f"] / divide, e["f"]).mean()))
            if usage:
                for arr, col in ((xf, "x"), (sp, "s")):
                    v = e[col]; k = ~np.isnan(v)
                    if k.sum() == 0 or np.isnan(arr[i]) or arr[i] <= 1e-9: continue
                    if divide is None:
                        d0 = wv[k].sum()
                        if d0 <= 1e-9: continue
                        r = ((wv[k] * v[k]).sum() / d0) / max(v[k].mean(), 1e-9)
                    else:
                        r = np.where(fl[k], v[k] / divide, v[k]).mean() / max(v[k].mean(), 1e-9)
                    arr[i] = arr[i] * r
        return dict(ppg=ppg, ge=ge, xf=xf, sn=sp)

    def mse(pred, T, m):
        d_ = pred[m] - T[m]; return float(np.mean(d_ * d_)) if m.any() else np.nan

    def rho(pred, T, ok, yrs):
        gr = defaultdict(list)
        for i in np.where(ok & top150 & np.isin(year, list(yrs)))[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        out = [np.corrcoef(rankdata(T[ix]), rankdata(pred[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]
        return float(np.nanmean(out))

    def cell(key, pred, m, yrs=YEARS, minrows=8):
        _, T, ok, _ = TG[key]; base = BASE[key]; m = m & ok & np.isin(year, list(yrs))
        if m.sum() < 30: return f"{'n/a (n' + str(int(m.sum())) + ')':>18s}"
        if np.abs(pred[m] - base[m]).max() < 1e-12: return f"{'no change n' + str(int(m.sum())):>18s}"
        ys = [y for y in yrs if (m & (year == y)).sum() >= minrows]
        wins = sum(1 for y in ys if mse(pred, T, m & (year == y)) < mse(base, T, m & (year == y)) - 1e-12)
        return f"{100*(mse(pred, T, m)/mse(base, T, m)-1):+6.2f}% ({wins}/{len(ys)}) n{int(m.sum())}"

    def board(key, pred, yrs=YEARS):
        _, T, ok, _ = TG[key]; base = BASE[key]; m = ok & np.isin(year, list(yrs)); m150 = m & top150
        a = 100 * (mse(pred, T, m) / mse(base, T, m) - 1)
        w_ = 100 * (np.average((pred[m150] - T[m150]) ** 2, weights=wt[m150]) / np.average((base[m150] - T[m150]) ** 2, weights=wt[m150]) - 1)
        return f"all {a:+.3f}%  top150-wtd {w_:+.3f}%  rank {rho(pred, T, ok, yrs) - rho(base, T, ok, yrs):+.4f}"

    def ratio(key, m):
        _, T, ok, _ = TG[key]; m = m & ok
        if m.sum() < 10: return f"n {int(m.sum())}"
        ys = [T[m & (year == y)].sum() / BASE[key][m & (year == y)].sum() for y in YEARS if (m & (year == y)).sum() >= 8]
        return f"n {int(m.sum()):5d} act {T[m].mean():5.2f} proj {BASE[key][m].mean():5.2f} -> {T[m].mean()/BASE[key][m].mean():.3f} (under in {sum(1 for v in ys if v < 1)}/{len(ys)})"

    BANDS = [("ADP 1-30", adpx <= 30), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100)), ("101+/none", adpx > 100)]
    ALLSK = np.isin(pos, SK); RECV = np.isin(pos, ("WR", "TE"))
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]

    def fit_pick(key, preds_by_v, scopes, folds, rows_m):
        """per scope: pick the grid value with the lowest MSE on the training seasons' rows_m rows; apply to the held-out season"""
        _, T, ok, _ = TG[key]; out = BASE[key].copy(); picks = [[] for _ in scopes]
        for tr, te in folds:
            trm = np.isin(year, tr)
            for k, sm in enumerate(scopes):
                m = sm & rows_m & ok & trm
                if m.sum() < 30: picks[k].append(None); continue
                best = min(preds_by_v, key=lambda v: mse(preds_by_v[v], T, m)); picks[k].append(best)
                sel = sm & (year == te); out[sel] = preds_by_v[best][sel]
        return out, picks

    if REFINE:
        # ============================================================ REFINE: banged-up prior, WR / TE only (RB failed in the main run)
        hn, hg, hp, ap, nn_ = prev["hurtN"], prev["healthyN"], prev["healthy"], prev["all"], prev["N"]
        gapv = np.nan_to_num(hp - ap, nan=0.0)
        bg = covered & RECV & ~np.isnan(hp)
        main_g = bg & (hn >= 3) & (hg >= 4) & (hp > X["clay_gm"])
        GATES = [("main: 3+ hurt, 4+ healthy, healthy > Clay", main_g),
                 ("2+ hurt, 4+ healthy, healthy > Clay", bg & (hn >= 2) & (hg >= 4) & (hp > X["clay_gm"])),
                 ("3+ hurt, 6+ healthy, healthy > Clay", bg & (hn >= 3) & (hg >= 6) & (hp > X["clay_gm"])),
                 ("3+ hurt, 4+ healthy, no Clay gate", bg & (hn >= 3) & (hg >= 4)),
                 ("main, hurt share >= 25% of his games", main_g & (hn >= 0.25 * np.maximum(nn_, 1))),
                 ("main, ADP <= 100 only", main_g & (adpx <= 100))]
        def prior_of(gate, a, cap=None, tohealthy=False, floor0=False):
            cl = X["clay_gm"].copy(); lift = a * gapv
            if floor0: lift = np.maximum(lift, 0.0)
            if tohealthy: lift = np.minimum(lift, np.maximum(0.0, np.nan_to_num(hp, nan=0.0) - cl))
            if cap is not None: lift = np.minimum(lift, cap)
            cl[gate] = cl[gate] + lift[gate]; return cl
        P("=== REFINE  BANGED-UP PRIOR, WR / TE only: Clay/g + a x (healthy ppg - all ppg) last season ===")
        P(f"    main gate rows: {int(main_g.sum()):,} (WR {int((main_g & (pos == 'WR')).sum()):,}, TE {int((main_g & (pos == 'TE')).sum()):,}); mean lift at a=.5: WR {0.5*gapv[main_g & (pos == 'WR')].mean():+.2f}, TE {0.5*gapv[main_g & (pos == 'TE')].mean():+.2f} half-PPR per game")
        HDRR = f"    {'gate / rule':58s} {'WR touched':>24s} {'TE touched':>24s} | " + " ".join(f"{bl:>22s}" for bl, _ in BANDS) + " | board"
        def rline(key, lab, pr, gate, yrs=YEARS):
            P(f"    {lab:58s} {cell(key, pr, gate & (pos == 'WR'), yrs):>24s} {cell(key, pr, gate & (pos == 'TE'), yrs):>24s} | " + " ".join(f"{cell(key, pr, gate & bm, yrs):>22s}" for _, bm in BANDS) + f" | {board(key, pr, yrs)}")
        for key in KEYS:
            P(f"\n  {TG[key][0]}"); P(HDRR)
            for gl, gm_ in GATES:
                for a in ((0.25, 0.4, 0.5, 0.6, 0.75) if gl.startswith("main:") else (0.5,)):
                    rline(key, f"{gl[:40]} a={a:.2f}", predict(key, clay=prior_of(gm_, a)), gm_)
            rline(key, "main a=.5, lift capped at 2.0", predict(key, clay=prior_of(main_g, 0.5, cap=2.0)), main_g)
            rline(key, "main a=.5, lift capped at 3.0", predict(key, clay=prior_of(main_g, 0.5, cap=3.0)), main_g)
            rline(key, "main a=.5, never above healthy ppg", predict(key, clay=prior_of(main_g, 0.5, tohealthy=True)), main_g)
            rline(key, "main a=.75, never above healthy ppg", predict(key, clay=prior_of(main_g, 0.75, tohealthy=True)), main_g)
            rline(key, "main a=.5, lift floored at 0", predict(key, clay=prior_of(main_g, 0.5, floor0=True)), main_g)
            rline(key, "main a=.5, floored at 0 + capped at 2.0 (SHIP CANDIDATE)", predict(key, clay=prior_of(main_g, 0.5, cap=2.0, floor0=True)), main_g)
            rline(key, "main a=.4, floored at 0 + capped at 2.0", predict(key, clay=prior_of(main_g, 0.4, cap=2.0, floor0=True)), main_g)
            P("    -- 2022-25 only --")
            for a in (0.4, 0.5, 0.6): rline(key, f"main a={a:.2f}", predict(key, clay=prior_of(main_g, a)), main_g, FWD)
            rline(key, "main a=.5, never above healthy ppg", predict(key, clay=prior_of(main_g, 0.5, tohealthy=True)), main_g, FWD)
            rline(key, "main a=.5, floored at 0 + capped at 2.0 (SHIP CANDIDATE)", predict(key, clay=prior_of(main_g, 0.5, cap=2.0, floor0=True)), main_g, FWD)
        P("\n--- a PICKED LEAVE-ONE-SEASON-OUT / FORWARD per position (main gate rows of the training seasons) ---")
        for key in KEYS:
            P(f"  {TG[key][0]}"); P(HDRR)
            preds = {a: predict(key, clay=prior_of(main_g, a)) for a in (0.0, 0.25, 0.4, 0.5, 0.6, 0.75, 1.0)}
            pr, pk = fit_pick(key, preds, [pos == "WR", pos == "TE"], LOSO, main_g); rline(key, "LOYO pick per position", pr, main_g)
            P(f"        picks: WR {pk[0]} | TE {pk[1]}")
            prf, pkf = fit_pick(key, preds, [pos == "WR", pos == "TE"], FORW, main_g); rline(key, "   forward 2022-25", prf, main_g, FWD)
            P(f"        picks: WR {pkf[0]} | TE {pkf[1]}")
        P("\n--- BY SEASON, main gate a=.5 ---")
        for key in KEYS:
            _, T, ok, _ = TG[key]; pr = predict(key, clay=prior_of(main_g, 0.5))
            for ps in ("WR", "TE"):
                m_ = main_g & ok & (pos == ps)
                P(f"  {TG[key][0]} {ps}: " + "  ".join(f"{y}: {100*(mse(pr, T, m_ & (year == y))/mse(BASE[key], T, m_ & (year == y))-1):+.1f}% n{int((m_ & (year == y)).sum())}" for y in YEARS))
        P("\n--- BY GAMES PLAYED this season, main gate a=.5 (does the lift still help once the evidence is in?) ---")
        for key in KEYS:
            pr = predict(key, clay=prior_of(main_g, 0.5))
            P(f"  {TG[key][0]}: " + " | ".join(f"g {lo}-{hi}: {cell(key, pr, main_g & (g >= lo) & (g <= hi)).strip()}" for lo, hi in ((1, 2), (3, 4), (5, 7), (8, 17))))
        # ---------------- 2026 preview from the 2025 tags + the data file the engine reads
        src = open(os.path.join(HERE, "data", "mike_clay_projections.js"), encoding="utf-8").read()
        clay26 = {}
        for m_ in re.finditer(r'"([^"]+)":\s*\{pos:"(\w+)",tm:"(\w+)",gm:(\d+),pts:([\d.]+),rec:([\d.]+)', src):
            nm_, ps_, tm_, gm_, pts_, rec_ = m_.group(1), m_.group(2), m_.group(3), int(m_.group(4)), float(m_.group(5)), float(m_.group(6))
            if ps_ in SK or ps_ == "QB": clay26[nm_] = (ps_, tm_, (pts_ - rec_ / 2.0) / (gm_ if gm_ >= 4 else 17))
        health = {}; preview = []
        for (nm_, ps_, Y_), (tm_, cpg_, gl_) in games.items():
            if Y_ != 2025 or len(gl_) < 4: continue
            hp_, ap_ = [], []
            for w_, (f_, tw_) in gl_.items():
                q_, l_, lo_ = hurt_tag(nm_, ps_, 2025, w_, tw_); ap_.append(f_)
                if not (q_ or l_ or lo_): hp_.append(f_)
            health[nm_] = [round(float(np.mean(hp_)), 2) if len(hp_) >= 1 else None, round(float(np.mean(ap_)), 2), len(ap_) - len(hp_), len(hp_), len(ap_)]
            c26 = clay26.get(nm_)
            if c26 and ps_ in ("WR", "TE") and len(ap_) - len(hp_) >= 3 and len(hp_) >= 4 and np.mean(hp_) > c26[2]:
                preview.append((nm_, ps_, c26[1], c26[2], np.mean(hp_), np.mean(ap_), len(ap_) - len(hp_), len(hp_), 0.5 * (np.mean(hp_) - np.mean(ap_))))
        # healthy-games HISTORY for the shadow prior (backtest_shadow_healthy_prior.py V3, 2026-10-07): per 2026 Clay-pool player,
        # h3h = 3-yr weighted PPG (W3 .5/.3/.2 over 2025/24/23, seasons with 4+ healthy games, 8+ healthy games total) and
        # l8h = his last 8 healthy game points from 2024-25 (oldest first; the engine appends this season's games)
        W3 = (0.5, 0.3, 0.2); hist_h = {}; nh = 0
        def gl_h(nm_, ps_, Y_):
            if (nm_, ps_, Y_) in games:
                tm0, c0, g0 = games[(nm_, ps_, Y_)]
                return [(w_, f_, any(hurt_tag(nm_, ps_, Y_, w_, tw_))) for w_, (f_, tw_) in sorted(g0.items())]
            rec_ = cal.weekly_rec(nm_, ps_); out2 = []
            for w_ in (rec_ or {}).get("seasons", {}).get(str(Y_), []):
                if cal.played(w_) and isinstance(w_.get("fpts"), (int, float)):
                    tw_ = QI_week_team(Y_, int(w_["wk"]), w_.get("opp")) if w_.get("opp") else None
                    out2.append((int(w_["wk"]), float(w_["fpts"]), any(hurt_tag(nm_, ps_, Y_, int(w_["wk"]), tw_))))
            return sorted(out2)
        QI_week_team = week_team
        for nm_, (ps_, tm_, cpg_) in clay26.items():
            if ps_ not in ("RB", "WR", "TE") and ps_ != "QB": continue
            num = den = 0.0; hg = 0
            for k_, Y_ in enumerate((2025, 2024, 2023)):
                pts = [f_ for (w_, f_, h_) in gl_h(nm_, ps_, Y_) if not h_]
                if len(pts) >= 4: num += W3[k_] * (sum(pts) / len(pts)); den += W3[k_]; hg += len(pts)
            h3h = round(num / den, 2) if (den > 0 and hg >= 8) else None
            tail = [f_ for Y_ in (2024, 2025) for (w_, f_, h_) in gl_h(nm_, ps_, Y_) if not h_][-8:]
            if h3h is not None or len(tail) >= 1:
                hist_h[nm_] = {"h3h": h3h, "h3g": hg, "l8h": [round(x, 1) for x in tail]}; nh += 1
        P(f"healthy history for the shadow prior: {nh} players (h3h for {sum(1 for v in hist_h.values() if v['h3h'] is not None)})")
        out_ = {"season": 2025, "built": pd.Timestamp.now().strftime("%Y-%m-%d"), "src": "backtest_qb_injury_usage.py --refine (nflverse injury reports + snap_counts.js + weekly_stats)", "h": hist_h, "hFields": "h3h = healthy 3-yr weighted PPG (2025/24/23), h3g = healthy games in it, l8h = last 8 healthy game points 2024-25 oldest first (shadow prior, backtest_shadow_healthy_prior.py V3)",
                "fields": "[healthy ppg, all ppg, hurt games, healthy games, games] half-PPR; hurt = listed Questionable, practice Limited/DNP, or snap share < 75% of own season median", "p": health}
        with open(os.path.join(HERE, "data", "sim_prior_health.js"), "w", encoding="utf-8") as fh:
            fh.write("// AUTO-GENERATED by backtest_qb_injury_usage.py --refine - last season's healthy vs all points per game for the banged-up prior lift\n")
            fh.write("window.SIM_PRIOR_HEALTH = " + json.dumps(out_) + ";\n")
        P(f"\nwrote data/sim_prior_health.js: {len(health)} players (2025 tags)")
        P("\n--- 2026 PREVIEW: WR / TE in the 2026 Clay pool who pass the main gate on their 2025 season (lift = .5 x gap, half-PPR per game) ---")
        for r_ in sorted(preview, key=lambda t: -t[-1]):
            P(f"    {r_[0]:24s} {r_[1]} {r_[2]:3s}  Clay {r_[3]:5.1f}/g  2025 healthy {r_[4]:5.1f} over {r_[7]} g, all {r_[5]:5.1f} over {r_[7]+r_[6]} g ({r_[6]} hurt)  -> prior {r_[3]+r_[-1]:5.1f} ({r_[-1]:+.2f})")
        LOG.close(); return

    # ================================================================ named sanity checks
    P("\n=== 0  TAGGING CHECK: London and Bowers ===")
    for nm, ps, Y in (("Drake London", "WR", 2025), ("Brock Bowers", "TE", 2025), ("Brock Bowers", "TE", 2024), ("Drake London", "WR", 2024)):
        if (nm, ps, Y) not in games: P(f"  {nm} {Y}: not in the Clay pool"); continue
        tm_, cpg, gl = games[(nm, ps, Y)]
        parts = []
        for w in sorted(gl):
            f, tw = gl[w]; qb = starter.get((Y, tw, w)); q, lim, low = hurt_tag(nm, ps, Y, w, tw)
            sy = snaps.get(cal.norm(nm), {}).get(Y, {})
            parts.append(f"wk{w} {f:4.1f} {(qb or '?').split()[-1]:>9s}{' Q' if q else ''}{' lim' if lim else ''}{' lowsnap' if low else ''}{(' snap' + str(int(sy[w]))) if w in sy else ''}")
        P(f"  {nm} {Y} ({tm_}, Clay {cpg:.1f}/g): " + " | ".join(parts))
        hp = [gl[w][0] for w in gl if not any(hurt_tag(nm, ps, Y, w, gl[w][1]))]; ap = [gl[w][0] for w in gl]
        P(f"      all games {np.mean(ap):.2f} ppg over {len(ap)}; healthy-tagged {np.mean(hp) if hp else float('nan'):.2f} over {len(hp)}; hurt games {len(ap) - len(hp)}")

    # ================================================================ 1  QB-AWARE EVIDENCE
    P("\n=== 1  QB-AWARE EVIDENCE (WR / TE / RB; off-QB = the game's top passer is not the expected starter) ===")
    P("    expected starter (a) 'last' = who started the team's most recent game; (b) 'actual' = who starts the target week (oracle)")
    offL_r = covered & (n_offL > 0); offA_r = covered & (n_offA > 0)
    mixedL = offL_r & (n_offL < nev); allL = offL_r & (n_offL == nev)
    P(f"    rows with 1+ off-QB game (last): {int(offL_r.sum()):,} = {100*offL_r.sum()/covered.sum():.1f}% of covered; mixed {int(mixedL.sum()):,}, every evidence game off-QB {int(allL.sum()):,}; 'QB new' (expected starter has <= 1 prior start) {int((covered & qb_new).sum()):,}")
    P(f"    rows with 1+ off-QB game (actual): {int(offA_r.sum()):,}")
    # does the off-QB evidence mislead? split by whether the off-QB games scored lower or higher than the on-QB games
    lowoff = np.zeros(n, bool); highoff = np.zeros(n, bool)
    for i in np.where(mixedL)[0]:
        e = EV[i]; a = e["f"][e["offL"]].mean(); b_ = e["f"][~e["offL"]].mean()
        lowoff[i] = a < b_ - 1.0; highoff[i] = a > b_ + 1.0
    P("\n--- 1a  LIVE-FORM BIAS on rows with off-QB evidence (actual / projected; 'under' = projection too low) ---")
    for key in KEYS:
        lab, T, ok, _ = TG[key]; P(f"  {lab}")
        for ps in SK:
            mp = ok & (pos == ps)
            P(f"    {ps}  no off-QB evidence       {ratio(key, mp & covered & (n_offL == 0))}")
            P(f"        1+ off-QB game (last)    {ratio(key, mp & offL_r)}")
            P(f"          off games scored LOWER than on-QB games   {ratio(key, mp & lowoff)}")
            P(f"          off games scored HIGHER                   {ratio(key, mp & highoff)}")
            P(f"          every evidence game off-QB (new starter)  {ratio(key, mp & allL)}")
            P(f"        1+ off-QB game (actual)  {ratio(key, mp & offA_r)}")
            P(f"        bands (last): " + " | ".join(f"{bl} {ratio(key, mp & offL_r & bm)}" for bl, bm in BANDS))
    HDR = f"    {'rule':50s} {'off-QB rows':>24s} | " + " ".join(f"{ps:>24s}" for ps in SK) + f" | {'board (all rows)'}"
    def line(key, lab, pred, rows_m, yrs=YEARS):
        P(f"    {lab:50s} {cell(key, pred, rows_m, yrs):>24s} | " + " ".join(f"{cell(key, pred, rows_m & (pos == ps), yrs):>24s}" for ps in SK) + f" | {board(key, pred, yrs)}")
    P("\n--- 1b  FIXED WEIGHTS on the off-QB games (points + usage inputs), every RB/WR/TE; error vs live, seasons better of 7 ---")
    T1 = {}
    for which, rows_m, flag in (("last", offL_r, "offL"), ("actual", offA_r, "offA")):
        for key in KEYS:
            P(f"\n  {TG[key][0]} - expected starter = {which}"); P(HDR)
            for w in (0.0, 0.25, 0.5, 0.75):
                V = reweight(flag, w, ALLSK); pr = predict(key, **V); T1[(which, key, w)] = pr
                line(key, f"off-QB games x{w:.2f}", pr, rows_m)
            Vp = reweight(flag, 0.5, ALLSK, usage=False); line(key, "x0.50 points only (usage untouched)", predict(key, **Vp), rows_m)
            Vu = reweight(flag, 0.5, ALLSK, points=False); line(key, "x0.50 usage inputs only", predict(key, **Vu), rows_m)
            Vr = reweight(flag, 0.5, RECV); line(key, "x0.50 WR/TE only", predict(key, **Vr), rows_m)
            Vm = reweight(flag, 0.5, ALLSK & ~allL if which == "last" else ALLSK & ~(n_offA == nev)); line(key, "x0.50 mixed rows only (keep new-starter rows)", predict(key, **Vm), rows_m)
            P("    -- 2022-25 only --")
            for w in (0.0, 0.5): line(key, f"off-QB games x{w:.2f}", T1[(which, key, w)], rows_m, FWD)
    P("\n--- 1c  BY ADP BAND (expected starter = last; off-QB games x0.50 and x0.00; graded on that band's off-QB rows) ---")
    for key in KEYS:
        P(f"  {TG[key][0]}")
        for ps in SK:
            P(f"    {ps}  " + " | ".join(f"{bl}: x.5 {cell(key, T1[('last', key, 0.5)], offL_r & (pos == ps) & bm).strip()} x0 {cell(key, T1[('last', key, 0.0)], offL_r & (pos == ps) & bm).strip()}" for bl, bm in BANDS))
    P("\n--- 1d  WEIGHT PICKED LEAVE-ONE-SEASON-OUT / FORWARD per position (fit on the off-QB rows of the training seasons, expected starter = last) ---")
    for key in KEYS:
        P(f"  {TG[key][0]}"); P(HDR)
        preds = {w: T1[("last", key, w)] for w in (0.0, 0.25, 0.5, 0.75)}; preds[1.0] = BASE[key]
        pr, pk = fit_pick(key, preds, [pos == ps for ps in SK], LOSO, offL_r); line(key, "LOYO pick per position", pr, offL_r)
        P("        picks: " + " | ".join(f"{SK[k]} {pk[k]}" for k in range(3)))
        prf, pkf = fit_pick(key, preds, [pos == ps for ps in SK], FORW, offL_r); line(key, "   forward 2022-25", prf, offL_r, FWD)
        P("        picks: " + " | ".join(f"{SK[k]} {pkf[k]}" for k in range(3)))
    P("\n--- 1e  BY SEASON, off-QB games x0.50 (last), off-QB rows ---")
    for key in KEYS:
        _, T, ok, _ = TG[key]; pr = T1[("last", key, 0.5)]
        P(f"  {TG[key][0]}: " + "  ".join(f"{y}: {100*(mse(pr, T, offL_r & ok & (year == y))/mse(BASE[key], T, offL_r & ok & (year == y))-1):+.1f}% n{int((offL_r & ok & (year == y)).sum())}" for y in YEARS))

    # ================================================================ 2  BANGED-UP PRIOR
    P("\n=== 2  BANGED-UP PRIOR: last season's hurt games (Questionable / limited or DNP practice / snap share < 75% of own median) ===")
    hurt3 = covered & (prev["hurtN"] >= 3) & ~np.isnan(prev["healthy"])
    gap = np.nan_to_num(prev["healthy"] - prev["all"], nan=0.0)
    up = hurt3 & (prev["healthy"] > X["clay_gm"])
    P(f"    rows with last-season data: {int((covered & ~np.isnan(prev['all'])).sum()):,}; 3+ hurt games and 4+ healthy games: {int(hurt3.sum()):,}; of those, healthy ppg above Clay's per-game prior: {int(up.sum()):,}")
    P(f"    mean healthy-minus-all gap on those rows: {gap[hurt3].mean():+.2f} half-PPR per game (RB {gap[hurt3 & (pos=='RB')].mean():+.2f}, WR {gap[hurt3 & (pos=='WR')].mean():+.2f}, TE {gap[hurt3 & (pos=='TE')].mean():+.2f})")
    P("\n--- 2a  LIVE-FORM BIAS: does the live number under-project players coming off a banged-up season? ---")
    for key in KEYS:
        lab, T, ok, _ = TG[key]; P(f"  {lab}")
        for ps in SK:
            mp = ok & (pos == ps) & covered & ~np.isnan(prev["all"])
            P(f"    {ps}  0-2 hurt games last season  {ratio(key, mp & (prev['hurtN'] <= 2))}")
            P(f"        3+ hurt games               {ratio(key, mp & (prev['hurtN'] >= 3))}")
            P(f"        3+ hurt, healthy > Clay     {ratio(key, mp & up)}")
            P(f"        3+ hurt, healthy > Clay, g <= 4   {ratio(key, mp & up & (g <= 4))}")
            P(f"        bands (3+ hurt, healthy > Clay): " + " | ".join(f"{bl} {ratio(key, mp & up & bm)}" for bl, bm in BANDS))
    P("\n--- 2b  PRIOR CANDIDATES (rows: 3+ hurt games last season, healthy ppg above Clay) ---")
    P("    A  Clay/g + a x (healthy ppg - all ppg) last season      B  (1-b) x Clay/g + b x healthy ppg last season")
    HDR2 = f"    {'rule':50s} {'touched rows':>24s} | " + " ".join(f"{ps:>24s}" for ps in SK) + " | board"
    T2 = {}
    for key in KEYS:
        P(f"\n  {TG[key][0]}"); P(HDR2)
        for a in (0.25, 0.5, 0.75, 1.0):
            cl = X["clay_gm"].copy(); cl[up] = cl[up] + a * gap[up]; pr = predict(key, clay=cl); T2[(key, "A", a)] = pr
            P(f"    {'A a=' + f'{a:.2f}':50s} {cell(key, pr, up):>24s} | " + " ".join(f"{cell(key, pr, up & (pos == ps)):>24s}" for ps in SK) + f" | {board(key, pr)}")
        for b_ in (0.25, 0.5):
            cl = X["clay_gm"].copy(); cl[up] = (1 - b_) * cl[up] + b_ * prev["healthy"][up]; pr = predict(key, clay=cl); T2[(key, "B", b_)] = pr
            P(f"    {'B b=' + f'{b_:.2f}':50s} {cell(key, pr, up):>24s} | " + " ".join(f"{cell(key, pr, up & (pos == ps)):>24s}" for ps in SK) + f" | {board(key, pr)}")
        cl = X["clay_gm"].copy(); cl[up] = cl[up] + 0.5 * gap[up]; cl[~(up & (g <= 4))] = X["clay_gm"][~(up & (g <= 4))]; pr = predict(key, clay=cl)
        P(f"    {'A a=0.50, first 4 games only':50s} {cell(key, pr, up):>24s} | " + " ".join(f"{cell(key, pr, up & (pos == ps)):>24s}" for ps in SK) + f" | {board(key, pr)}")
        P("    -- 2022-25 only --")
        for a in (0.5, 1.0):
            pr = T2[(key, "A", a)]
            P(f"    {'A a=' + f'{a:.2f}':50s} {cell(key, pr, up, FWD):>24s} | " + " ".join(f"{cell(key, pr, up & (pos == ps), FWD):>24s}" for ps in SK) + f" | {board(key, pr, FWD)}")
        P("    by band, A a=0.50: " + " | ".join(f"{bl} {cell(key, T2[(key, 'A', 0.5)], up & bm).strip()}" for bl, bm in BANDS))
        _, T, ok, _ = TG[key]; pr = T2[(key, "A", 0.5)]
        P("    by season, A a=0.50: " + "  ".join(f"{y}: {100*(mse(pr, T, up & ok & (year == y))/mse(BASE[key], T, up & ok & (year == y))-1):+.1f}% n{int((up & ok & (year == y)).sum())}" for y in YEARS))
    P("\n--- 2c  the same discount applied to THIS season's evidence: his own banged-up games this season x w in the POINTS evidence (excused-games check) ---")
    hurt_r = covered & (n_hurt > 0)
    for key in KEYS:
        P(f"  {TG[key][0]}"); P(HDR)
        for w in (0.5, 0.0):
            V = reweight("hurt", w, ALLSK, usage=False); line(key, f"own hurt games x{w:.2f} in points evidence", predict(key, **V), hurt_r)

    # ================================================================ 3  USAGE WEIGHT
    P("\n=== 3  USAGE WEIGHT (WR / TE usage evidence = lam x usage-implied + (1 - lam) x points) ===")
    useok = X["useok"]
    def lam_of(wr_sched, te_sched):
        lw = np.select([g <= a for a, _ in wr_sched], [v for _, v in wr_sched], wr_sched[-1][1])
        lt = np.select([g <= a for a, _ in te_sched], [v for _, v in te_sched], te_sched[-1][1])
        return np.where(useok & (pos == "WR"), lw, np.where(useok & (pos == "TE"), lt, 0.0))
    WR_SHIP = ((2, .8), (5, .6), (8, .5), (99, .3)); TE_SHIP = ((3, 0.0), (99, .3))
    SCHED = [("shipped WR .8/.8/.6/.6/.5/.3  TE 0/0/0/.3", WR_SHIP, TE_SHIP),
             ("WR held-out 1/1/.7/.7/.55/.33  TE shipped", ((2, 1.0), (5, .7), (8, .55), (99, .33)), TE_SHIP),
             ("WR shipped +.15 (cap 1)        TE shipped", ((2, .95), (5, .75), (8, .65), (99, .45)), TE_SHIP),
             ("WR shipped                     TE .3 from game 1", WR_SHIP, ((99, .3),)),
             ("WR shipped                     TE .5 from game 1", WR_SHIP, ((99, .5),)),
             ("WR shipped                     TE .3/.3/.3/.5", WR_SHIP, ((3, .3), (99, .5))),
             ("WR held-out                    TE .3 from game 1", ((2, 1.0), (5, .7), (8, .55), (99, .33)), ((99, .3),)),
             ("WR 1.0 flat                    TE .5 flat", ((99, 1.0),), ((99, .5),))]
    T3 = {}
    HDR3 = f"    {'schedule':52s} {'WR':>24s} {'TE':>24s} | " + " ".join(f"{bl:>22s}" for bl, _ in BANDS) + " | board"
    for key in KEYS:
        P(f"\n  {TG[key][0]}"); P(HDR3)
        for lab, ws, ts in SCHED:
            lam = lam_of(ws, ts); pr = predict(key, lam=lam); T3[(key, lab)] = pr
            P(f"    {lab:52s} {cell(key, pr, useok & (pos == 'WR')):>24s} {cell(key, pr, useok & (pos == 'TE')):>24s} | " + " ".join(f"{cell(key, pr, useok & RECV & bm):>22s}" for _, bm in BANDS) + f" | {board(key, pr)}")
        P("    -- 2022-25 only --")
        for lab, ws, ts in SCHED[1:]:
            pr = T3[(key, lab)]
            P(f"    {lab:52s} {cell(key, pr, useok & (pos == 'WR'), FWD):>24s} {cell(key, pr, useok & (pos == 'TE'), FWD):>24s} | " + " ".join(f"{cell(key, pr, useok & RECV & bm, FWD):>22s}" for _, bm in BANDS) + f" | {board(key, pr, FWD)}")
    P("\n--- 3a  TE usage from game 1, by season (TE rows with 1-3 games played, where the shipped weight is 0) ---")
    for key in KEYS:
        _, T, ok, _ = TG[key]; m0 = useok & (pos == "TE") & (g <= 3) & ok
        for lab in ("WR shipped                     TE .3 from game 1", "WR shipped                     TE .5 from game 1"):
            pr = T3[(key, lab)]
            P(f"  {TG[key][0]} {lab.split('TE')[1].strip():18s}: " + "  ".join(f"{y}: {100*(mse(pr, T, m0 & (year == y))/mse(BASE[key], T, m0 & (year == y))-1):+.1f}% n{int((m0 & (year == y)).sum())}" for y in YEARS) + f" | bias live {np.mean(BASE[key][m0]-T[m0]):+.2f} -> {np.mean(pr[m0]-T[m0]):+.2f}")
    P("\n--- 3b  SITUATION-AWARE USAGE INPUTS (points evidence untouched; WR/TE rows with usage evidence) ---")
    stale_r = covered & (n_stale > 0)
    SIT = [("off-QB games (last) x0.5 in usage inputs", reweight("offL", 0.5, RECV, points=False), offL_r),
           ("off-QB games (last) x0.0 in usage inputs", reweight("offL", 0.0, RECV, points=False), offL_r),
           ("own banged-up games x0.5 in usage inputs", reweight("hurt", 0.5, RECV, points=False), hurt_r),
           ("own banged-up games x0.0 in usage inputs", reweight("hurt", 0.0, RECV, points=False), hurt_r),
           ("stale fill-in games / boost in usage inputs, all ADP", reweight("stale", None, RECV, points=False, divide=np.nan), stale_r)]
    # fill-in divide needs a per-row divisor: redo with the position boost
    def reweight_div(flag, scope, points=False):
        ppg = X["ppg"].copy(); ge = g.astype(float).copy(); xf = X["xfp"].copy(); sp = X["snap"].copy()
        for i in np.where(scope & covered)[0]:
            e = EV[i]; fl = e[flag]
            if not fl.any(): continue
            dv = BOOST.get(pos[i], 1.0); v = e["x"]; k = ~np.isnan(v)
            if points: ppg[i] = max(0.0, float(np.where(fl, e["f"] / dv, e["f"]).mean()))
            if k.sum() == 0 or np.isnan(xf[i]) or xf[i] <= 1e-9: continue
            xf[i] = xf[i] * (np.where(fl[k], v[k] / dv, v[k]).mean() / max(v[k].mean(), 1e-9))
        return dict(ppg=ppg, ge=ge, xf=xf, sn=sp)
    SIT[-1] = ("stale fill-in games / boost in usage xFP, all ADP", reweight_div("stale", RECV), stale_r)
    SIT.append(("stale fill-in / boost in POINTS + usage xFP, all ADP (Adams case)", reweight_div("stale", RECV, points=True), stale_r))
    SIT.append(("stale fill-in / boost points + xFP, 2+ stale games, all ADP", reweight_div("stale", RECV & (n_stale >= 2), points=True), stale_r & (n_stale >= 2)))
    HDR4 = f"    {'rule':52s} {'touched rows':>24s} {'WR':>24s} {'TE':>24s} | " + " ".join(f"{bl:>22s}" for bl, _ in BANDS) + " | board"
    for key in KEYS:
        P(f"\n  {TG[key][0]}"); P(HDR4)
        for lab, V, rows_m in SIT:
            pr = predict(key, **V); rm = rows_m & useok & RECV
            P(f"    {lab:52s} {cell(key, pr, rm):>24s} {cell(key, pr, rm & (pos == 'WR')):>24s} {cell(key, pr, rm & (pos == 'TE')):>24s} | " + " ".join(f"{cell(key, pr, rm & bm):>22s}" for _, bm in BANDS) + f" | {board(key, pr)}")
            P(f"    {'   2022-25':52s} {cell(key, pr, rm, FWD):>24s} {cell(key, pr, rm & (pos == 'WR'), FWD):>24s} {cell(key, pr, rm & (pos == 'TE'), FWD):>24s}")
    P("\n--- 3c  COMBINATIONS: QB-aware evidence (points + usage, last, x0.5) + heavier usage schedule ---")
    for key in KEYS:
        P(f"\n  {TG[key][0]}"); P(HDR3)
        for lab, ws, ts in SCHED[:1] + SCHED[1:2] + SCHED[3:4] + SCHED[6:7]:
            V = reweight("offL", 0.5, ALLSK); pr = predict(key, lam=lam_of(ws, ts), **V)
            P(f"    {('QB x.5 + ' + lab)[:52]:52s} {cell(key, pr, useok & (pos == 'WR')):>24s} {cell(key, pr, useok & (pos == 'TE')):>24s} | " + " ".join(f"{cell(key, pr, useok & RECV & bm):>22s}" for _, bm in BANDS) + f" | {board(key, pr)}")
    P("\nLimitations: starting QB = top passer of the game (a QB hurt mid-game still counts as the starter); expected starter 'last' ignores the")
    P("injury report the engine would see; route rate per game not reweighted; hurt tag needs the nflverse report or snap counts (name-keyed);")
    P("prop anchor / pecking dock / availability curves not replayable; team = season team (mid-season trades untagged).")
    LOG.close()


if __name__ == "__main__":
    main()
