#!/usr/bin/env python3
"""
ENGINE-FORM RE-GRADE of P-20261013-2 (vacancy fade in later weeks) and P-20261013-3 (ctxShare raw share), 2026-10-13, Jack approved
pending this re-grade. The real engine.js only runs on 2026 data (SIM_2026 etc. are season aggregates with no as-of-week cut), so a
clean 2019-25 walk-forward of engine.js itself is impossible; these replicas follow the ENGINE's form of each change, not the
volume-budget harness copy:
  P-2  per-FUTURE-WEEK availability: from each checkpoint (3-10 games, 4+ left) every later week j carries the vacancy boost only
       if a regular is actually out in week j (the engine's best case: availability curve = truth), the checkpoint week keeps the
       full boost, later weeks x pool^(.75 f), f = max(0, 1 - seen / c), seen = games he already played (before the checkpoint)
       without that week's biggest absent regular. Target = his mean over the remaining games.
  P-3  engine snapMult (RB / TE in the shadow chain) + shadow snap LEVEL (WR / TE last game) rebuilt from participation with
       ctxShare as shipped (re-measure + week weight), as proposed (raw pct + week weight) and fully off; v2.32 blowout no-dock
       (ADP <= 150, last game 6+ garbage plays and 15%+ of plays) in every arm.
Log vacfade_ctx_regrade.log. Also writes the losing-season player breakdowns for P-1 / P-2 / P-3.
"""
import os, sys, pickle
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import research_volume_budget as VB
from research_volume_budget import (n, act, year, wk, pos, g, adp, name, pid, team, final, top150, WT, S, S0, L, GW, TW, TWEEKS, PGAMES, POSOF, SK,
                                    YEARS, FWD, NEXT, ROSM, TR, ros, wmse, mae, fold_table, loyo_pick, H)
import research_volume_budget_c as VC
LOG = open(os.path.join(HERE, "vacfade_ctx_regrade" + ("_p3" if "p3" in sys.argv else ("_p2_noTE" if os.environ.get("NOFADE") else "_p2")) + ".log"), "w", encoding="utf-8")
def P(s=""):
    print(s, flush=True); LOG.write(s + "\n"); LOG.flush()
VB.P = P
on, pm = H["on"], H["pm"]
NOFADE = tuple(os.environ.get("NOFADE", "").split(",")) if os.environ.get("NOFADE") else ()


def losers(lab, base, cand, T_, mm, tf=lambda p: p, k=6, extra=None):
    """seasons where cand loses to base: the rows that add the most weighted squared error, with tags"""
    b, c = tf(base), tf(cand)
    for Y in YEARS:
        q = mm & (year == Y)
        if not q.any(): continue
        e0, e1 = wmse(b, T_, q), wmse(c, T_, q)
        if e1 <= e0: continue
        d = WT * ((c - T_) ** 2 - (b - T_) ** 2); ix = np.where(q)[0]; ix = ix[np.argsort(-d[ix])][:k]
        net = d[q].sum(); top = d[ix].sum()
        P(f"  {lab} LOST {Y} ({100*(e1/e0-1):+.2f}%): top {k} rows = {100*top/max(net,1e-9):.0f}% of the net loss")
        for i in ix:
            tg = extra(i) if extra else ""
            P(f"     {name[i]:24s} {pos[i]} {team[i]} wk{int(wk[i]):2d} actual {T_[i]:5.1f} base {b[i]:5.1f} cand {c[i]:5.1f} {tg}")


def p2():
    P("=" * 110); P("P-20261013-2 ENGINE FORM: later-week vacancy boost by actual future-week absences, faded by games already seen"); P("=" * 110)
    seq = defaultdict(list)
    for i in range(n):
        if not final[i]: seq[(name[i], pos[i], int(year[i]))].append(i)
    for k in seq: seq[k].sort(key=lambda i: wk[i])
    m = ROSM & np.isin(pos, SK)
    # per checkpoint: list of (j, pm_j, seen_j)
    plan = {}
    for i in np.where(m)[0]:
        Y, t, w = int(year[i]), team[i], int(wk[i])
        tw = [k for k in TWEEKS.get((Y, t), []) if k < w]; mine = [k for k in tw if pid[i] in GW[(Y, t, k)]]
        ix = [j for j in seq[(name[i], pos[i], Y)] if wk[j] >= w]
        rows = []
        for j in ix:
            seen = 0
            if on[j] and team[j] == t:
                ab = VC.members_absent(Y, t, int(wk[j]), tw)
                if ab:
                    big = max(ab, key=lambda z: z[1] + z[2])[0]; seen = sum(1 for k in mine if big not in GW[(Y, t, k)])
            rows.append((j, pm[j] if on[j] else 1.0, seen, j == i))
        plan[i] = rows
    def pred(c, scale=0.75):
        out = np.full(n, np.nan)
        for i, rows in plan.items():
            r0 = S0[i] / max(L[i], 0.3); v = []
            for j, pmj, seen, cur in rows:
                f = 1.0 if (cur or c is None or pos[i] in NOFADE) else (0.0 if c == 0 else max(0.0, 1 - seen / c))
                v.append(r0 * np.clip(L[j], 0.5, 1.8) * pmj ** (scale * f))
            out[i] = np.mean(v)
        return out
    # target: mean actual over the same rows
    Tm = np.full(n, np.nan)
    for i, rows in plan.items(): Tm[i] = np.mean([act[j] for j, _, _, _ in rows])
    mm = m & ~np.isnan(Tm)
    base = pred(None)
    nl = sum(1 for i, rows in plan.items() if any((not cur) and pmj > 1 for j, pmj, s, cur in rows))
    P(f"  checkpoints {int(mm.sum())}; with a later-week vacancy boost {nl}")
    preds = {"wired (boost every later week it applies)": base}
    for c in (2, 4, 6, 8):
        C = pred(c); preds[f"fade c {c}"] = C; fold_table(f"fade max(0, 1 - seen/{c}) later weeks", base, C, Tm, mm)
    C0 = pred(0); preds["no later-week boost"] = C0; fold_table("no boost in later weeks", base, C0, Tm, mm)
    affected = mm & np.array([any((not cur) and pmj > 1 and s >= 1 for j, pmj, s, cur in plan.get(i, [])) for i in range(n)])
    fold_table("fade c 4, affected checkpoints only", base, preds["fade c 4"], Tm, affected)
    for ps in SK: fold_table(f"fade c 4, {ps}", base, preds["fade c 4"], Tm, mm & (pos == ps))
    loyo_pick(preds, base, Tm, mm, "P-2 engine form")
    def tagf(i):
        rows = plan[i]; s = max([s for _, pmj, s, cur in rows if not cur and pmj > 1] + [0])
        return f"| later boost weeks {sum(1 for _, pmj, s_, cur in rows if not cur and pmj > 1)}/{len(rows)} max seen {s} pm {max([pmj for _, pmj, _, _ in rows]):.2f}"
    losers("P-2 fade c4", base, preds["fade c 4"], Tm, mm, extra=tagf)
    return base, preds["fade c 4"], Tm, mm


def snap_engine(remeasure, weight, nodock=True):
    """engine snapMult + last-game competitive level read, from participation; returns (smx, l1) per harness row"""
    smx = np.ones(n); l1 = np.full(n, np.nan); bl = np.zeros(n, bool)
    SW = [0.5, 0.3, 0.2]
    for i in range(n):
        if pos[i] not in SK or not pid[i]: continue
        Y, w = int(year[i]), int(wk[i])
        gl = [(w_, t_) for (w_, t_) in PGAMES.get((Y, pid[i]), []) if w_ < w]
        if not gl: continue
        val, wt = {}, {}
        for (w_, t_) in gl:
            r = GW[(Y, t_, w_)][pid[i]]; T_ = TW[(Y, t_, w_)]
            if T_.pp_plays <= 0: continue
            pct = 100 * r.on / T_.pp_plays; tot = T_.pp_plays; gar = T_.pp_plays - T_.pp_plays_c
            if gar < 6: val[w_], wt[w_] = pct, 1.0; continue
            comp = tot - gar; cnt = pct / 100 * tot
            adj = min(100, 100 * cnt / comp) if cnt <= comp + 0.5 else pct
            val[w_] = (adj if cnt >= 0.85 * comp else pct) if remeasure else pct
            wt[w_] = comp / tot if weight else 1.0
        past = sorted(val, reverse=True)
        if not past: continue
        l1[i] = val[past[0]]
        lt = gl[-1]; T_ = TW[(Y, lt[1], lt[0])]; bl[i] = (T_.pp_plays > 0 and (T_.pp_plays - T_.pp_plays_c) >= 6 and (T_.pp_plays - T_.pp_plays_c) / T_.pp_plays >= 0.15)
        if len(past) < 2 or past[0] < w - 3: continue
        rec = sum(val[x] * SW[k] * wt[x] for k, x in enumerate(past[:3])) / sum(SW[k] * wt[x] for k, x in enumerate(past[:3]))
        avg = sum(val[x] * wt[x] for x in past) / sum(wt[x] for x in past)
        smx[i] = min(1.30, max(0.75, 1 + (rec - avg) / 100))
    a_ = np.nan_to_num(adp, nan=999)
    if nodock: smx = np.where((pos == "RB") & (smx < 1) & (a_ <= 150) & bl, 1.0, smx)
    return smx, l1, bl


def p3():
    P("\n" + "=" * 110); P("P-20261013-3 ENGINE FORM: snapMult (RB/TE) + snap level (WR/TE) with ctxShare as shipped / raw pct / off"); P("=" * 110)
    import backtest_base_remeasure as BR
    X = BR.SN.setup(); assert X["n"] == n
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet"))
    orig_rp = BR.pd.read_parquet
    key = {(int(a), b, int(c)): k for k, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    rowkey = [key.get((int(year[i]), pid[i], int(wk[i])), -1) for i in range(n)]
    def shadow_with(smx, l1, bl):
        C2 = C.copy(); sm = C2["snapmult"].values.astype(float).copy()
        for i in range(n):
            if rowkey[i] >= 0 and pos[i] in SK: sm[rowkey[i]] = smx[i]
        C2["snapmult"] = sm
        BR.pd.read_parquet = lambda p, *a, **k: C2 if str(p).endswith("ctx_features.parquet") else orig_rp(p, *a, **k)
        try:
            X2 = dict(X); X2["snap_l1"] = np.where(np.isnan(l1), X["snap_l1"], l1)
            out, _ = BR.shadow_current(X2)
            a_ = np.nan_to_num(adp, nan=999); nd = bl & (a_ <= 150) & np.isin(pos, ["WR", "TE"])
            X3 = dict(X2); X3["snap_l1"] = np.where(nd, np.nan, X2["snap_l1"]); out3, _ = BR.shadow_current(X3)
            out = np.where(nd, np.maximum(out, out3), out)   # v2.32: the level read can lift but not dock after a blowout (top 150)
        finally:
            BR.pd.read_parquet = orig_rp
        # v2.32: no snap-LEVEL dock after a blowout for ADP <= 150 (approximate: undo a level dock by recomputing with the dock floored)
        return out
    arms = {}
    for lab, rm, wt_ in (("shipped (re-measure + weight)", True, True), ("P-3 raw pct + weight", False, True), ("ctx off (raw, no weight)", False, False)):
        smx, l1, bl = snap_engine(rm, wt_); arms[lab] = (shadow_with(smx, l1, bl), smx, l1)
        P(f"  built {lab}: RB/TE snap mult != 1 on {int((np.abs(smx-1) > 1e-9).sum())} rows")
    b = arms["shipped (re-measure + weight)"][0]
    m = NEXT
    for lab in ("P-3 raw pct + weight", "ctx off (raw, no weight)"):
        c = arms[lab][0]; fold_table(f"{lab} vs shipped (next game)", b, c, act, m)
        moved = m & (np.abs(c - b) > 1e-6); fold_table(f"   rows it moves", b, c, act, moved)
        for ps in SK: fold_table(f"   {ps}", b, c, act, m & (pos == ps))
        fold_table(f"{lab} vs shipped (ROS)", b, c, TR, ROSM, ros)
    c = arms["P-3 raw pct + weight"][0]
    def tagf(i):
        Y = int(year[i]); gl = [(w_, t_) for (w_, t_) in PGAMES.get((Y, pid[i]), []) if w_ < wk[i]]
        if not gl: return ""
        w_, t_ = gl[-1]; T_ = TW[(Y, t_, w_)]; r = GW[(Y, t_, w_)][pid[i]]
        return f"| last game wk{w_} margin {T_.margin:+.0f} garbage {int(T_.garb)} his snaps {100*r.on/max(T_.pp_plays,1):.0f}% (comp {100*r.on_c/max(T_.pp_plays_c,1):.0f}%)"
    losers("P-3 raw", b, c, act, m & (np.abs(c - b) > 1e-6), extra=tagf)
    return b, c


if __name__ == "__main__":
    if 'p3' in sys.argv: p3()
    else: p2()
