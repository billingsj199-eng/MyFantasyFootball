#!/usr/bin/env python3
"""
LINEUP-CONDITIONAL USAGE (Jack 2026-10-07 "let's do it in order", item 4).  A receiver's usage inputs (xFP per game,
snap share) and points evidence are season-to-date averages over every game, including games where a teammate was out
(his share inflated) or where a teammate who is out now was in (his share deflated). Here each evidence game is tagged
with the set of same-position REGULARS (same team, Clay >= 5 half-PPR/g) who played in it, compared with the set
expected active THIS week, and the inputs are rebuilt from the games with the same lineup when there are enough.
  rules  U1  usage inputs (xFP, snap) from same-lineup games only (2+ such games), points untouched
         U2  usage inputs half same-lineup / half all games
         U3  U1 + points evidence from same-lineup games too (game count = same-lineup games)
         U4  usage inputs from games with the same lineup OR a smaller set (never from games where a regular who is
             active now was absent) - the one-directional 'fill-in' version
  scope  WR / TE / RB, rows with 1+ evidence game whose lineup differs from this week's; by position, ADP band, whether the
         difference is a teammate RETURNING (was out in the evidence) or a teammate now OUT (was in)
Live form (backtest_qb_injury_usage.live_base), 2019-25, next game + rest of season, LOYO + forward, bar 5/7 + 3/4.
Expected-active set this week = the regulars who actually played that week (the engine would read the injury report).
Log lineup_usage.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_qb_injury_usage as QI
NW = QI.NW; cal = QI.cal; YEARS = QI.YEARS; SK = QI.SK; FWD = QI.FWD; POS4 = QI.POS4
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "lineup_usage.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
REG_MIN = 5.0


def main():
    X = QI.setup(); n = X["n"]
    act, year, wk, pos, g, adp, name, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["team"]
    F = X["F"]; finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    games, roster, starter, team_weeks = QI.build_games(X)
    # regulars per (Y, team, pos) and the weeks each played for that team
    played = {}
    for (nm, ps, Y), (tm_, cpg, gl) in games.items():
        if tm_: played[(nm, ps, Y)] = {w for w, (f, t) in gl.items() if t == tm_}
    regs_of = {}
    for (Y, tm_, ps), lst in roster.items():
        regs_of[(Y, tm_, ps)] = [nm for nm, cpg in lst if cpg >= REG_MIN]
    # per-game xFP / snap from the cumulative columns (QI pattern)
    xfp, snl1 = X["xfp"], X["snap_l1"]; seq = defaultdict(list)
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
    # per row: evidence games with lineup match flags
    EV = [None] * n; covered = np.zeros(n, bool); n_diff = np.zeros(n); n_same = np.zeros(n); kind = np.array([""] * n, dtype=object)
    for i in range(n):
        if pos[i] not in SK or g[i] < 1 or not team[i]: continue
        key = (name[i], pos[i], int(year[i])); Y = int(year[i])
        if key not in games: continue
        tm_, cpg, gl = games[key]; evw = [w for w in sorted(gl) if w < wk[i]]
        if len(evw) != int(g[i]): continue
        regs = [r for r in regs_of.get((Y, tm_, pos[i]), []) if r != name[i]]
        now = frozenset(r for r in regs if int(wk[i]) in played.get((r, pos[i], Y), set()))
        f_, x_, s_, same, sub, kinds = [], [], [], [], [], set()
        for w in evw:
            f, tw = gl[w]; S = frozenset(r for r in regs if w in played.get((r, pos[i], Y), set()))
            f_.append(f); x_.append(gx.get(key + (w,), np.nan)); s_.append(gsn.get(key + (w,), np.nan))
            same.append(S == now); sub.append(S <= now)   # sub: nobody who is out now was in that game (lineup same or smaller)
            if S != now:
                if now - S: kinds.add("return")   # a regular active now was absent then
                if S - now: kinds.add("out")      # a regular who was in then is out now
        covered[i] = True; n_diff[i] = sum(1 for s in same if not s); n_same[i] = sum(same); kind[i] = "+".join(sorted(kinds))
        EV[i] = dict(f=np.array(f_), x=np.array(x_, float), s=np.array(s_, float), same=np.array(same, bool), sub=np.array(sub, bool))
    diff_r = covered & (n_diff > 0)
    P(f"rows covered {int(covered.sum()):,}; with 1+ evidence game under a different lineup {int(diff_r.sum()):,} ({int((diff_r & top150).sum()):,} top-150); of those with 2+ same-lineup games {int((diff_r & (n_same >= 2)).sum()):,}")
    P("    kinds: " + " | ".join(f"{k}: {int((diff_r & (kind == k)).sum())}" for k in ("return", "out", "out+return")))
    # targets
    seqn = defaultdict(list)
    for i in range(n):
        if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ix in seqn.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(X["layers"][ix], 0.5, 1.8)
        for a, i in enumerate(ix): nfut[i] = len(ix) - a; Tr[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    ramp = np.clip((nfut - 1.5) / np.maximum(nfut, 1), 0, 1); tilt = 1 - X["tilt_e"] * ramp * X["z"]; ctx0 = np.nan_to_num(ctx, nan=1.0)
    okN = (g >= 1) & ~final & ~X["inh"]; okR1 = (g >= 1) & (g <= 10) & ~np.isnan(Tr) & ~X["inh"]; okR4 = okR1 & (nfut >= 4)
    TG = {"next": ("NEXT GAME", act, okN, X["chain"]), "ros4": ("REST OF SEASON, 4+ games left", Tr, okR4, ctx0 * tilt), "ros1": ("REST OF SEASON, no survivor filter", Tr, okR1, ctx0 * tilt)}
    KEYS = ("next", "ros4", "ros1")
    def predict(key, ppg=None, ge=None, xf=None, sn=None):
        _, T, ok, mult = TG[key]
        b, lk = QI.live_base(X, X["ppg"] if ppg is None else ppg, g.astype(float) if ge is None else ge, X["xfp"] if xf is None else xf, X["snap"] if sn is None else sn)
        return np.maximum(0.0, b * mult + lk)
    BASE = {k: predict(k) for k in KEYS}
    mse = lambda p, T, m: float(np.mean((p[m] - T[m]) ** 2)) if m.any() else np.nan
    wmse = lambda p, T, m: float(np.average((p[m] - T[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    def rebuild(sel_fn, usage_w=1.0, points=False, min_same=2, scope=None):
        """inputs rebuilt from the selected evidence games: usage_w = weight of the selected-game average vs the full one"""
        ppg = X["ppg"].copy(); ge = g.astype(float).copy(); xf = X["xfp"].copy(); sp = X["snap"].copy(); touched = np.zeros(n, bool)
        for i in np.where(diff_r if scope is None else (diff_r & scope))[0]:
            e = EV[i]; sel = sel_fn(e)
            if sel.sum() < min_same or sel.all(): continue
            touched[i] = True
            for arr, col in ((xf, "x"), (sp, "s")):
                v = e[col]; k = ~np.isnan(v); ks = k & sel
                if ks.sum() == 0 or k.sum() == 0 or np.isnan(arr[i]) or arr[i] <= 1e-9: continue
                full = v[k].mean(); part = v[ks].mean()
                arr[i] = arr[i] * ((usage_w * part + (1 - usage_w) * full) / max(full, 1e-9))
            if points:
                ppg[i] = max(0.0, float(e["f"][sel].mean())); ge[i] = float(sel.sum())
        return dict(ppg=ppg, ge=ge, xf=xf, sn=sp), touched
    RULES = [("U1 usage from same-lineup games only (2+)", dict(sel_fn=lambda e: e["same"])),
             ("U2 usage half same-lineup / half all", dict(sel_fn=lambda e: e["same"], usage_w=0.5)),
             ("U3 U1 + points evidence from same-lineup games", dict(sel_fn=lambda e: e["same"], points=True)),
             ("U4 usage from same-or-smaller lineup games (fill-in direction only)", dict(sel_fn=lambda e: e["sub"])),
             ("U1 with 3+ same-lineup games", dict(sel_fn=lambda e: e["same"], min_same=3))]
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    RECV = np.isin(pos, ("WR", "TE"))
    for title, kw in RULES:
        V, touched = rebuild(**kw)
        for key in KEYS:
            _, T, ok, _ = TG[key]; b0 = BASE[key]; pr = predict(key, **V); m = touched & ok
            if m.sum() < 60: P(f"\n  {title} | {TG[key][0]}: too few rows"); continue
            preds = {"off": b0, "on": pr}
            def run(folds):
                wins = 0; picks = []; out = b0.copy()
                for tr_, te in folds:
                    k = min(preds, key=lambda kk: mse(preds[kk], T, m & np.isin(year, tr_))); picks.append(k); mm = year == te; out[mm] = preds[k][mm]; wins += mse(preds[k], T, m & mm) < mse(b0, T, m & mm) - 1e-12
                tem = np.isin(year, [te for _, te in folds]); return 100 * (mse(out, T, m & tem) / mse(b0, T, m & tem) - 1), 100 * (wmse(out, T, ok & top150 & tem) / wmse(b0, T, ok & top150 & tem) - 1), wins, picks
            lo = run(LOSO); fw = run(FORW)
            wins_f = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and mse(pr, T, m & (year == y)) < mse(b0, T, m & (year == y)) - 1e-12)
            P(f"\n  {title} | {TG[key][0]}  rows {int(m.sum()):,} (top-150 {int((m & top150).sum())})  actual/live {T[m].sum()/b0[m].sum():.3f}")
            P(f"    fixed {100*(mse(pr, T, m)/mse(b0, T, m)-1):+.2f}% ({wins_f}/7) | " + " | ".join(f"{ps} {100*(mse(pr, T, m & (pos == ps))/mse(b0, T, m & (pos == ps))-1):+.2f}% (n{int((m & (pos == ps)).sum())})" for ps in SK if (m & (pos == ps)).sum() >= 30)
              + f" | ADP<=60 {100*(mse(pr, T, m & (adpx <= 60))/mse(b0, T, m & (adpx <= 60))-1):+.2f}% (n{int((m & (adpx <= 60)).sum())}) | 61-150 {100*(mse(pr, T, m & (adpx > 60) & (adpx <= 150))/mse(b0, T, m & (adpx > 60) & (adpx <= 150))-1):+.2f}% | 151+ {100*(mse(pr, T, m & (adpx > 150))/mse(b0, T, m & (adpx > 150))-1):+.2f}%")
            P(f"    by kind: " + " | ".join(f"{k}: {100*(mse(pr, T, m & (kind == k))/mse(b0, T, m & (kind == k))-1):+.2f}% (n{int((m & (kind == k)).sum())}, act/live {T[m & (kind == k)].sum()/max(1e-9, b0[m & (kind == k)].sum()):.3f})" for k in ("return", "out", "out+return") if (m & (kind == k)).sum() >= 30))
            P(f"    LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | picks {lo[3]}")
            P(f"    FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}")
            okk = lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
            P(f"    -> {'PASS' if okk else 'FAIL'}")
    P("\nLimitations: regulars = same-position teammates with Clay >= 5/g (cross-position target competition not in the set); expected-active set = who played this week (oracle for the report); route rate not rebuilt; prop anchor / docks not replayed.")
    LOG.close()


if __name__ == "__main__":
    main()
