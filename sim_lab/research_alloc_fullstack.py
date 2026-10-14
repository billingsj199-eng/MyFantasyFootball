#!/usr/bin/env python3
"""
P-20261013-1 REPLAY ON THE FULL TEAMMATE STACK (2026-10-13, Jack: port behind a switch defaulted OFF, replay on the full engine stack,
report so he can decide). The budget allocation (research_volume_budget.py, availability renorm ratio Ra = budget(next roster) /
budget(no renorm)) is graded against the wired teammate stack as replicated for 2019-25:
  STACK = shadow replica with the pool (vacx stand-in, k .75) x NEXT MAN UP rank cells (1.04 / .99 / 1.03) x PROMOTED BACKUP
          (RB 1.034 / WR 1.071 / TE 1.207) x TEAM VACATED (1 + .2 x vacated target share)       [backtest_team_vacated_boost.py base]
  ALLOC-A = shadow WITHOUT the pool x Ra^e, NMU / PROMO / TVAC kept           (replaces the pool / vacx only)
  ALLOC-B = shadow WITHOUT the pool x Ra^e, nothing else                       (replaces the whole teammate stack)
Not replicable here: the engine's workhorse cell and fill-in rescale (the harness pool is usage-based, not Clay-level).
Next game, top-150 weighted, final week out; losing seasons broken down by player. Log alloc_fullstack.log.
"""
import os, sys, json, pickle
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import research_volume_budget as VB
from research_volume_budget import (n, act, year, wk, pos, name, team, adp, final, WT, S, S0, NEXT, YEARS, FWD, wmse, fold_table, loyo_pick, H, GW, TW, TWEEKS, PGAMES, pid, POSOF)
import research_volume_budget_c as VC
import backtest_base_remeasure as BR
cal = BR.cal
LOG = open(os.path.join(HERE, "alloc_fullstack.log"), "w", encoding="utf-8")
def P(s=""):
    print(s, flush=True); LOG.write(s + "\n"); LOG.flush()
VB.P = P
SK = ("RB", "WR", "TE"); REG_MIN = 5.0; PROMO = {"RB": 1.034, "WR": 1.071, "TE": 1.207}
PT = pickle.load(open(os.path.join(HERE, "_tmp", "vb_points.pkl"), "rb")); Ra = PT["Ra"]
TG = pickle.load(open(os.path.join(HERE, "_tmp", "vb_tags.pkl"), "rb")); kseen = TG["kseen"]; tags = TG["tags"]


def week_team(Y, w, opp, cache={}):
    k = (Y, w, opp)
    if k not in cache:
        o = cal.OPP_ALIAS.get(opp, opp); t = None
        for t_, s in cal.SCHEDULES.get(Y, {}).items():
            if s.get(str(w)) == o: t = t_; break
        cache[k] = t
    return cache[k]


def tables():
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    tg = defaultdict(dict); roster = defaultdict(list); games = {}
    for Y in YEARS:
        W = 16 if Y <= 2020 else 17
        for nm, c in (ch.get(str(Y)) or {}).items():
            ps = c.get("pos")
            if ps not in SK: continue
            rec = cal.weekly_rec(nm, ps)
            if rec is None: continue
            tm = cal.infer_team(rec, Y); gmv = (c.get("gm") or 0); half = max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0)
            cpg = half / gmv if gmv >= 4 else half / W; gl = {}
            for w in rec.get("seasons", {}).get(str(Y), []):
                if not (cal.played(w) and w.get("opp")): continue
                tw = week_team(Y, int(w["wk"]), w["opp"])
                if tw: tg[(Y, tw, int(w["wk"]))][(nm, ps)] = float(w.get("tgt") or 0); gl[int(w["wk"])] = tw
            games[(nm, ps, Y)] = (tm, cpg, gl)
            if tm: roster[(Y, tm, ps)].append((nm, cpg))
    promo = set()
    for (nm, ps, Y), (tm, cpg, gl) in games.items():
        if not tm: continue
        regs = [r for r, rc in roster[(Y, tm, ps)] if r != nm and rc > cpg and rc >= REG_MIN]
        rplay = {r: {w for w, t in games[(r, ps, Y)][2].items() if t == tm} for r in regs}
        for w, t in gl.items():
            if t == tm and any(w not in rplay[r] for r in regs): promo.add((cal.norm(nm), Y, w))
    return tg, promo


def main():
    nlog = os.path.join(HERE, "next_man_up.log"); keep = open(nlog, encoding="utf-8").read() if os.path.exists(nlog) else None
    import research_next_man_up as R
    if keep is not None: R.LOG.close(); open(nlog, "w", encoding="utf-8").write(keep)
    Ev, _ = R.events()
    adpx = np.where(np.isnan(adp), 999.0, adp); nbase = (adpx <= 150) & ~final & ~H["inh"] & (S >= 3)
    idx = {(R.nz(name[i]), int(year[i]), int(wk[i])): i for i in range(n)}
    NMU = np.ones(n)
    for r in Ev:
        i = idx.get((R.nz(r["n"]), r["Y"], r["wk"]))
        if i is None or not nbase[i] or r["rank"] > 6: continue
        NMU[i] = 1.04 if r["rank"] == 1 else 0.99 if r["rank"] <= 3 else 1.03
    tg, promo = tables()
    PR = np.array([PROMO[pos[i]] if (pos[i] in PROMO and (cal.norm(name[i]), int(year[i]), int(wk[i])) in promo) else 1.0 for i in range(n)])
    team_wks = defaultdict(list)
    for (Y, t, w) in tg: team_wks[(Y, t)].append(w)
    for k in team_wks: team_wks[k].sort()
    def vac_of(Y, t, w):
        if (Y, t, w) not in tg: return 0.0
        prior = [u for u in team_wks.get((Y, t), []) if u < w][-3:]
        if len(prior) < 2: return 0.0
        tot = 0.0; by = defaultdict(float); gp = defaultdict(int)
        for u in prior:
            for kk, v in tg[(Y, t, u)].items(): tot += v; by[kk] += v; gp[kk] += 1
        if tot < 30: return 0.0
        return sum(v / tot for kk, v in by.items() if gp[kk] >= 2 and v / tot >= 0.10 and kk not in tg[(Y, t, w)])
    tname = H["team"]
    vac = np.array([vac_of(int(year[i]), tname[i], int(wk[i])) if pos[i] in SK else 0.0 for i in range(n)])
    TV = np.where(np.isin(pos, SK), 1 + 0.2 * vac, 1.0)
    STACK = S * NMU * PR * TV
    m = NEXT & ~np.isnan(PT["BUD"])
    P(f"rows {int(m.sum())}; NMU moves {int((m & (NMU != 1)).sum())}, PROMO {int((m & (PR != 1)).sum())}, TVAC {int((m & (TV != 1)).sum())}, pool {int((m & H['on']).sum())}")
    fold_table("reference: STACK vs shadow-with-pool only", S, STACK, act, m)
    predsA, predsB = {"stack (wired)": STACK}, {"stack (wired)": STACK}
    for e in (0.5, 0.75, 1.0):
        A = S0 * np.clip(Ra ** e, 0.6, 1.8) * NMU * PR * TV; Bv = S0 * np.clip(Ra ** e, 0.6, 1.8)
        predsA[f"A e {e}"] = A; predsB[f"B e {e}"] = Bv
        fold_table(f"ALLOC-A e {e} (replaces pool/vacx; NMU/PROMO/TVAC kept)", STACK, A, act, m)
        fold_table(f"ALLOC-B e {e} (replaces the whole teammate stack)", STACK, Bv, act, m)
        fold_table(f"   A e {e}, rows with any teammate layer on", STACK, A, act, m & ((NMU != 1) | (PR != 1) | (TV != 1) | H["on"]))
    Ae, _ = loyo_pick(predsA, STACK, act, m, "ALLOC-A vs stack")
    Be, _ = loyo_pick(predsB, STACK, act, m, "ALLOC-B vs stack")
    A1 = predsA["A e 1.0"]
    for ps in SK: fold_table(f"ALLOC-A e1 {ps}", STACK, A1, act, m & (pos == ps))
    a_ = adpx
    for lo, hi in ((1, 30), (31, 60), (61, 100), (101, 150)): fold_table(f"ALLOC-A e1 ADP {lo}-{hi}", STACK, A1, act, m & (a_ >= lo) & (a_ <= hi))
    fold_table("ALLOC-A e1, RB same-room RB out", STACK, A1, act, m & tags["RB committee: same-room RB out"])
    fold_table("ALLOC-A e1, absence never seen (seen 0)", STACK, A1, act, m & H["on"] & (kseen == 0))
    fold_table("ALLOC-A e1, absence seen 1+", STACK, A1, act, m & H["on"] & (kseen >= 1))
    def tagf(i):
        Y, t, w = int(year[i]), team[i], int(wk[i]); tw = [k for k in TWEEKS.get((Y, t), []) if k < w]
        ab = VC.members_absent(Y, t, w, tw) if tw else []
        nm = ",".join(sorted(set(str(VB_name(z[0])) for z in ab))[:3])
        return f"| Ra {Ra[i]:.2f} pool {H['pm'][i] if H['on'][i] else 1:.2f} NMU {NMU[i]:.2f} PR {PR[i]:.2f} TV {TV[i]:.2f} seen {kseen[i]} | out: {nm}"
    for lab, C in (("ALLOC-A e1", A1), ("ALLOC-B e1", predsB["B e 1.0"])):
        P(f"\n--- losing seasons, {lab} vs stack (next game) ---")
        losers(lab, STACK, C, act, m, tagf)
    pickle.dump(dict(STACK=STACK, NMU=NMU, PR=PR, TV=TV), open(os.path.join(HERE, "_tmp", "vb_stack.pkl"), "wb"))


import pandas as pd
_NM = None
def VB_name(p_):
    global _NM
    if _NM is None:
        d = pd.read_csv(os.path.join(VB.B.CACHE, "players.csv"), usecols=["gsis_id", "display_name"], low_memory=False); _NM = dict(zip(d.gsis_id, d.display_name))
    return _NM.get(p_, p_)


def losers(lab, base, cand, T_, mm, extra=None, k=6):
    for Y in YEARS:
        q = mm & (year == Y)
        e0, e1 = wmse(base, T_, q), wmse(cand, T_, q)
        if e1 <= e0: continue
        d = WT * ((cand - T_) ** 2 - (base - T_) ** 2); ix = np.where(q)[0]; ix = ix[np.argsort(-d[ix])][:k]
        P(f"  {lab} LOST {Y} ({100*(e1/e0-1):+.2f}%): top {k} rows = {100*d[ix].sum()/max(d[q].sum(),1e-9):.0f}% of the net loss")
        for i in ix: P(f"     {name[i]:24s} {pos[i]} {team[i]} wk{int(wk[i]):2d} actual {T_[i]:5.1f} stack {base[i]:5.1f} alloc {cand[i]:5.1f} {extra(i) if extra else ''}")


if __name__ == "__main__":
    main()
