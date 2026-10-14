#!/usr/bin/env python3
"""
WORKHORSE RB OUT (Jack 2026-10-09: Jeanty out -> engine gives direct RB2 Mike Washington Jr. only 4.7 -> 6.2 PPR).

Weekly DB 2019-25. Event = team-week with exactly one absent skill player with a meaningful trailing share (same rule as
backtest_vacated_pool.py: >= .12 team targets or >= .30 team carries, last 3 team games, 2+ played, not traded), that
player is a RB, and the starting QB is not also out. Absent RB's role = his trailing share of TEAM RB carries:
WORKHORSE >= WH (default .60) vs committee.
RB2 = top healthy RB with a trailing baseline by trailing carries (the direct backup); RB3 = next; bodies = RBs with no baseline.
Engine rule (POOL.RB): RB2 gets .28 of vacated carries at his own pts/carry and .28 of vacated targets at own pts/target x .92;
f = 1 + gained / max(own, 4.0) -> projection = own * f.
Control = the same RB2 construction in weeks the workhorse PLAYED (regression-to-trailing baseline).
Also WR/TE response (Jack: RB and WR/TE points not correlated) and team pass volume.
Log workhorse_rb_out.log.
"""
import os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_sim_calibration as cal
LOG = open(os.path.join(HERE, "workhorse_rb_out.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + "\n"); LOG.flush()

YEARS = list(range(2019, 2026)); TRAIL = 3
TGT_MIN, CAR_MIN = 0.12, 0.30
TM_ALIAS = {"ARZ": "ARI", "WSH": "WAS", "JAC": "JAX", "LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "HST": "HOU", "BLT": "BAL", "CLV": "CLE"}
ENG_C, ENG_T, EFF_T, FLOOR = 0.28, 0.28, 0.92, 4.0
PPC0, PPT0, K = 0.60, 1.45, 6.0   # league RB pts/carry, PPR pts/target priors (shrink trailing rates with K pseudo-units)

def pts(w):
    rec = w.get("rec") or 0
    rp_h = rec * 0.5 + (w.get("rcy") or 0) * 0.1 + (w.get("rctd") or 0) * 6
    cp = (w.get("ry") or 0) * 0.1 + (w.get("rtd") or 0) * 6
    return rp_h, rp_h + rec * 0.5, cp

def build(Y):
    rows = defaultdict(list); teams_of = defaultdict(set)
    for nm, lst in cal.WEEKLY.items():
        for rec in lst:
            pos = rec.get("pos")
            if pos not in ("QB", "RB", "WR", "TE"): continue
            inferred = None
            for w in rec.get("seasons", {}).get(str(Y), []):
                if not cal.played(w): continue
                tm = w.get("tm"); tm = TM_ALIAS.get(tm, tm) if tm else None
                if not tm:
                    if inferred is None: inferred = cal.infer_team(rec, Y) or ""
                    tm = TM_ALIAS.get(inferred, inferred)
                if not tm: continue
                rh, rf, cp = pts(w)
                key = (nm, pos)
                rows[(tm, int(w["wk"]))].append({"key": key, "n": nm, "pos": pos, "tgt": float(w.get("tgt") or 0), "ra": float(w.get("ra") or 0),
                                                 "rph": rh, "rpf": rf, "cp": cp, "pa": float(w.get("pa") or 0)})
                teams_of[key].add((tm, int(w["wk"])))
    return rows, teams_of

F = ("tgt", "ra", "rph", "rpf", "cp", "pa")

def collect():
    EV, CTRL, WRTE_CTRL = [], [], []
    for Y in YEARS:
        rows, teams_of = build(Y)
        tw = defaultdict(list)
        for (tm, wk) in rows: tw[tm].append(wk)
        for tm, wks in tw.items():
            wks.sort()
            for i, wk in enumerate(wks):
                if i < TRAIL: continue
                prev = wks[i - TRAIL:i]
                cur = {r["key"]: r for r in rows[(tm, wk)]}
                trail = {}
                for pw in prev:
                    for r in rows[(tm, pw)]:
                        t = trail.setdefault(r["key"], dict({k: 0.0 for k in F}, g=0, pos=r["pos"], n=r["n"]))
                        t["g"] += 1
                        for k in F: t[k] += r[k]
                trail = {k: v for k, v in trail.items() if v["g"] >= 2}
                for v in trail.values():
                    for k in F: v[k] /= v["g"]
                tsum = lambda f, cond=lambda r: True: sum(sum(r[f] for r in rows[(tm, pw)] if cond(r)) for pw in prev) / TRAIL
                team_tgt, team_car, team_pa = tsum("tgt"), tsum("ra"), tsum("pa")
                rb_car = tsum("ra", lambda r: r["pos"] == "RB")
                if team_tgt < 15 or team_car < 10 or rb_car < 8: continue
                absent = [(k, v) for k, v in trail.items() if k not in cur and not any(t2 != tm and w2 > wk for (t2, w2) in teams_of[k])]
                skill = [(k, v) for k, v in absent if v["pos"] in ("RB", "WR", "TE") and (v["tgt"] / team_tgt >= TGT_MIN or v["ra"] / team_car >= CAR_MIN)]
                qb_out = any(v["pos"] == "QB" and v["pa"] / max(1, team_pa) >= 0.6 for k, v in absent)
                if qb_out: continue
                # WR/TE totals (all rows incl. bodies), team pass volume
                wrte_now = sum(r["rpf"] for r in cur.values() if r["pos"] in ("WR", "TE"))
                wrte_tr = tsum("rpf", lambda r: r["pos"] in ("WR", "TE"))
                wrte_tgt_now = sum(r["tgt"] for r in cur.values() if r["pos"] in ("WR", "TE"))
                wrte_tgt_tr = tsum("tgt", lambda r: r["pos"] in ("WR", "TE"))
                pa_now = sum(r["pa"] for r in cur.values())
                car_now = sum(r["ra"] for r in cur.values()); tgt_now = sum(r["tgt"] for r in cur.values())
                rbs = sorted([(k, v) for k, v in trail.items() if v["pos"] == "RB" and k in cur], key=lambda kv: -kv[1]["ra"])
                team = dict(Y=Y, wk=wk, tm=tm, wrte_now=wrte_now, wrte_tr=wrte_tr, wrte_tgt_now=wrte_tgt_now, wrte_tgt_tr=wrte_tgt_tr,
                            pa_now=pa_now, pa_tr=team_pa, car_now=car_now, car_tr=team_car, tgt_now=tgt_now, tgt_tr=team_tgt)
                if not skill:
                    # control: a workhorse present (trailing RB carry share >= .60) and playing; RB2 behind him
                    if rbs and rbs[0][1]["ra"] / rb_car >= 0.60 and len(rbs) >= 2:
                        k2, v2 = rbs[1]; r2 = cur[k2]
                        CTRL.append(dict(team, share=rbs[0][1]["ra"] / rb_car, own=v2["rpf"] + v2["cp"], act=r2["rpf"] + r2["cp"], acth=r2["rph"] + r2["cp"],
                                         ownh=v2["rph"] + v2["cp"], dc=r2["ra"] - v2["ra"], dt=r2["tgt"] - v2["tgt"]))
                        WRTE_CTRL.append(team)
                    continue
                if len(skill) != 1 or skill[0][1]["pos"] != "RB": continue
                ka, va = skill[0]
                share = va["ra"] / rb_car
                ev = dict(team, share=share, a_n=va["n"], Vc=va["ra"], Vt=va["tgt"], a_ppr=va["rpf"] + va["cp"], a_half=va["rph"] + va["cp"], a_cp=va["cp"], a_rp=va["rpf"])
                def pl(kv):
                    k, v = kv; r = cur[k]
                    ppc = (v["cp"] * v["g"] + PPC0 * K) / (v["ra"] * v["g"] + K)
                    ppt = (v["rpf"] * v["g"] + PPT0 * K) / (v["tgt"] * v["g"] + K)
                    return dict(n=v["n"], own=v["rpf"] + v["cp"], ownh=v["rph"] + v["cp"], act=r["rpf"] + r["cp"], acth=r["rph"] + r["cp"],
                                bc=v["ra"], bt=v["tgt"], dc=r["ra"] - v["ra"], dt=r["tgt"] - v["tgt"], ppc=ppc, ppt=ppt, bshare=v["ra"] / rb_car)
                ev["rb2"] = pl(rbs[0]) if rbs else None
                ev["rb3"] = pl(rbs[1]) if len(rbs) > 1 else None
                bodies = [r for k, r in cur.items() if r["pos"] == "RB" and k not in trail]
                ev["body_c"] = sum(r["ra"] for r in bodies); ev["body_t"] = sum(r["tgt"] for r in bodies)
                ev["body_ppr"] = sum(r["rpf"] + r["cp"] for r in bodies); ev["nbodies"] = len(bodies)
                rb_now = sum(r["ra"] for r in cur.values() if r["pos"] == "RB"); ev["rb_car_now"] = rb_now; ev["rb_car_tr"] = rb_car
                EV.append(ev)
    return EV, CTRL, WRTE_CTRL

def proj(ev, sc, st, floor=True):
    b = ev["rb2"]; own = b["own"]
    gained = sc * ev["Vc"] * b["ppc"] + st * ev["Vt"] * b["ppt"] * EFF_T
    if own <= 0: return own + gained
    return own * (1 + gained / (max(own, FLOOR) if floor else own))

def mae(evs, sc, st, floor=True):
    return float(np.mean([abs(e["rb2"]["act"] - proj(e, sc, st, floor)) for e in evs])) if evs else np.nan

def fit(evs, floor=True):
    best = None
    for sc in np.arange(0.20, 0.81, 0.02):
        for st in np.arange(0.0, 0.61, 0.04):
            m = mae(evs, sc, st, floor)
            if best is None or m < best[0]: best = (m, sc, st)
    return best[1], best[2]

def main():
    EV, CTRL, WCTRL = collect()
    P(f"=== WORKHORSE RB OUT  (weekly DB 2019-25; {len(EV)} one-RB-absence team-weeks, {len(CTRL)} control weeks with a workhorse playing) ===")
    cm = lambda f, L: float(np.mean([x[f] for x in L])) if L else np.nan
    ctrl_d = cm("act", CTRL) - cm("own", CTRL)
    P(f"control: RB2 behind a PLAYING workhorse scores {cm('act', CTRL):.2f} PPR vs trailing {cm('own', CTRL):.2f} (regression {ctrl_d:+.2f}); carries {cm('dc', CTRL):+.2f}, tgt {cm('dt', CTRL):+.2f}")
    for thr in (0.50, 0.60, 0.70):
        wh = [e for e in EV if e["share"] >= thr and e["rb2"]]
        P(f"  threshold {thr:.2f}: workhorse n={len(wh)}  committee n={len([e for e in EV if e['share'] < thr and e['rb2']])}")
    for lab, sel in (("WORKHORSE (share >= .60)", lambda e: e["share"] >= 0.60), ("COMMITTEE (< .60)", lambda e: e["share"] < 0.60),
                     ("WORKHORSE strict (>= .70)", lambda e: e["share"] >= 0.70)):
        L = [e for e in EV if sel(e) and e["rb2"]]
        if not L: continue
        Vc, Vt = sum(e["Vc"] for e in L), sum(e["Vt"] for e in L)
        r2 = [e["rb2"] for e in L]; r3 = [e["rb3"] for e in L if e["rb3"]]
        P(f"\n--- {lab}: n={len(L)} (no healthy RB with baseline: {len([e for e in EV if sel(e) and not e['rb2']])}) ---")
        P(f"  absent RB: {Vc/len(L):.1f} car {Vt/len(L):.1f} tgt/g, {np.mean([e['a_ppr'] for e in L]):.1f} PPR/g ({np.mean([e['a_half'] for e in L]):.1f} half)")
        P(f"  team RB carries {np.mean([e['rb_car_tr'] for e in L]):.1f} -> {np.mean([e['rb_car_now'] for e in L]):.1f} (keeps {(sum(e['rb_car_now']-e['rb_car_tr'] for e in L)+Vc)/Vc:.2f} of vacated RB carries); "
          f"team carries keeps {(sum(e['car_now']-e['car_tr'] for e in L)+Vc)/Vc:.2f}; team targets {np.mean([e['tgt_tr'] for e in L]):.1f} -> {np.mean([e['tgt_now'] for e in L]):.1f}")
        P(f"  RB2 (direct backup): baseline {np.mean([b['bc'] for b in r2]):.1f} car {np.mean([b['bt'] for b in r2]):.1f} tgt -> absorbs {sum(b['dc'] for b in r2)/Vc:+.2f} of vacated car, {sum(b['dt'] for b in r2)/max(1,Vt):+.2f} of vacated tgt "
          f"(control-adj car {(sum(b['dc'] for b in r2)-len(r2)*cm('dc',CTRL))/Vc:+.2f})")
        acts = np.array([b["act"] for b in r2]); owns = np.array([b["own"] for b in r2])
        P(f"  RB2 PPR: trailing {owns.mean():.2f} -> actual {acts.mean():.2f} (gain {acts.mean()-owns.mean():+.2f}; minus control regression {acts.mean()-owns.mean()-ctrl_d:+.2f}); "
          f"half {np.mean([b['ownh'] for b in r2]):.2f} -> {np.mean([b['acth'] for b in r2]):.2f}")
        P(f"  RB2 PPR distribution: median {np.median(acts):.1f}  IQR {np.percentile(acts,25):.1f}-{np.percentile(acts,75):.1f}  P90 {np.percentile(acts,90):.1f}  share >= 12: {np.mean(acts>=12):.0%}  >= 10: {np.mean(acts>=10):.0%}")
        P(f"  RB2 actual / absent starter's PPR/g: {acts.sum()/sum(e['a_ppr'] for e in L):.2f} (median per-event {np.median(acts/np.array([max(1,e['a_ppr']) for e in L])):.2f})")
        if r3:
            P(f"  RB3: absorbs {sum(b['dc'] for b in r3)/Vc:+.2f} car {sum(b['dt'] for b in r3)/max(1,Vt):+.2f} tgt (n={len(r3)}), PPR {np.mean([b['own'] for b in r3]):.1f} -> {np.mean([b['act'] for b in r3]):.1f}")
        P(f"  bodies (no baseline): {sum(e['body_c'] for e in L)/Vc:+.2f} of vacated car, {sum(e['body_t'] for e in L)/max(1,Vt):+.2f} tgt, {np.mean([e['body_ppr'] for e in L]):.1f} PPR/event")
        eng = np.array([proj(e, ENG_C, ENG_T) for e in L])
        P(f"  ENGINE rule (.28/.28, floor 4): implied {eng.mean():.2f} PPR -> actual/engine {acts.sum()/eng.sum():.3f}; MAE {np.mean(np.abs(acts-eng)):.2f}")
        if lab.startswith("WORKHORSE ("):
            WH = L
    L = WH
    # per season
    P("\n--- workhorse-out RB2, per season: actual / engine ---")
    under = 0
    for Y in YEARS:
        s = [e for e in L if e["Y"] == Y]
        if not s: continue
        a = sum(e["rb2"]["act"] for e in s); g = sum(proj(e, ENG_C, ENG_T) for e in s)
        under += a > g
        P(f"  {Y}: n={len(s):3d} actual {a/len(s):5.2f} engine {g/len(s):5.2f}  ratio {a/g:.3f}")
    P(f"  under-projected in {under}/{len(YEARS)} seasons")
    # talent dependence
    P("\n--- RB2 talent / role (workhorse out): by RB2's own trailing PPR, and his trailing share of RB carries ---")
    for lo, hi in ((0, 3), (3, 6), (6, 99)):
        s = [e for e in L if lo <= e["rb2"]["own"] < hi]
        if s: P(f"  RB2 trailing {lo}-{hi} PPR: n={len(s)} actual {np.mean([e['rb2']['act'] for e in s]):.2f} (median {np.median([e['rb2']['act'] for e in s]):.1f}), engine {np.mean([proj(e,ENG_C,ENG_T) for e in s]):.2f}, car absorbed {sum(e['rb2']['dc'] for e in s)/sum(e['Vc'] for e in s):+.2f}")
    for lo, hi in ((0, 0.15), (0.15, 0.30), (0.30, 1)):
        s = [e for e in L if lo <= e["rb2"]["bshare"] < hi]
        if s: P(f"  RB2 trailing RB-carry share {lo:.2f}-{hi:.2f}: n={len(s)} actual {np.mean([e['rb2']['act'] for e in s]):.2f}, car absorbed {sum(e['rb2']['dc'] for e in s)/sum(e['Vc'] for e in s):+.2f}")
    s1 = [e for e in L if e["rb3"] is None or e["rb3"]["bc"] < 2]; s2 = [e for e in L if e["rb3"] is not None and e["rb3"]["bc"] >= 2]
    P(f"  RB2 with no real RB3 (RB3 < 2 car/g): n={len(s1)} actual {np.mean([e['rb2']['act'] for e in s1]):.2f} car {sum(e['rb2']['dc'] for e in s1)/sum(e['Vc'] for e in s1):+.2f} | with an RB3: n={len(s2)} actual {np.mean([e['rb2']['act'] for e in s2]):.2f} car {sum(e['rb2']['dc'] for e in s2)/sum(e['Vc'] for e in s2):+.2f}")

    # WR / TE response
    P("\n--- WR/TE response (team WR+TE PPR, all bodies) ---")
    for lab, S in (("workhorse RB out", L), ("committee RB out", [e for e in EV if e["share"] < 0.60 and e["rb2"]]), ("control (workhorse plays)", WCTRL)):
        d = np.array([e["wrte_now"] - e["wrte_tr"] for e in S])
        P(f"  {lab:28s} n={len(S):4d}: WR+TE PPR {np.mean([e['wrte_tr'] for e in S]):.1f} -> {np.mean([e['wrte_now'] for e in S]):.1f} ({d.mean():+.2f}, se {d.std()/np.sqrt(len(d)):.2f}); "
          f"WR+TE tgt {np.mean([e['wrte_tgt_tr'] for e in S]):.1f} -> {np.mean([e['wrte_tgt_now'] for e in S]):.1f}; pass att {np.mean([e['pa_tr'] for e in S]):.1f} -> {np.mean([e['pa_now'] for e in S]):.1f}; "
          f"team tgt x{sum(e['tgt_now'] for e in S)/sum(e['tgt_tr'] for e in S):.3f}")
    cw = np.mean([e["wrte_now"] - e["wrte_tr"] for e in WCTRL]); ct = np.mean([e["wrte_tgt_now"] - e["wrte_tgt_tr"] for e in WCTRL])
    dw = np.array([e["wrte_now"] - e["wrte_tr"] - cw for e in L]); dtg = np.array([e["wrte_tgt_now"] - e["wrte_tgt_tr"] - ct for e in L])
    P(f"  workhorse out, control-adjusted: WR+TE {dw.mean():+.2f} PPR (se {dw.std()/np.sqrt(len(dw)):.2f}), {dtg.mean():+.2f} tgt = {dtg.sum()/sum(e['Vt'] for e in L):+.2f} of vacated RB targets (engine tgtOther .15)")
    for Y in YEARS:
        s = [e["wrte_now"] - e["wrte_tr"] - cw for e in L if e["Y"] == Y]
        if s: P(f"    {Y}: {np.mean(s):+.2f} PPR (n={len(s)})")

    # proposed cell
    P("\n--- PROPOSED CELL: workhorse-out RB2 shares (fit by MAE grid) ---")
    for floor in (True, False):
        sc, st = fit(L, floor)
        P(f"  floor={floor}: full-sample fit car {sc:.2f} tgt {st:.2f}; MAE engine {mae(L, ENG_C, ENG_T):.3f} -> {mae(L, sc, st, floor):.3f}; mean proj {np.mean([proj(e, sc, st, floor) for e in L]):.2f} vs actual {np.mean([e['rb2']['act'] for e in L]):.2f}")
    for cand in ((0.50, 0.28, True), (0.55, 0.28, True), (0.60, 0.28, True), (0.50, 0.28, False), (0.55, 0.40, False)):
        sc, st, fl = cand
        P(f"  fixed car {sc:.2f} tgt {st:.2f} floor={fl}: MAE {mae(L, sc, st, fl):.3f}, mean {np.mean([proj(e, sc, st, fl) for e in L]):.2f}, "
          f"seasons better {sum(mae([e for e in L if e['Y']==Y], sc, st, fl) < mae([e for e in L if e['Y']==Y], ENG_C, ENG_T) for Y in YEARS)}/7")
    for floor in (True, False):
        P(f"  LOYO (floor={floor}):")
        win = 0; tot_b = tot_n = 0
        for Y in YEARS:
            tr = [e for e in L if e["Y"] != Y]; te = [e for e in L if e["Y"] == Y]
            sc, st = fit(tr, floor); mb, mn = mae(te, ENG_C, ENG_T), mae(te, sc, st, floor)
            win += mn < mb; tot_b += mb * len(te); tot_n += mn * len(te)
            P(f"    {Y}: fit car {sc:.2f} tgt {st:.2f}  MAE {mb:.3f} -> {mn:.3f} ({100*(mn/mb-1):+.1f}%) n={len(te)}")
        P(f"    LOYO improves {win}/7, pooled MAE {tot_b/len(L):.3f} -> {tot_n/len(L):.3f} ({100*(tot_n/tot_b-1):+.1f}%)")
        win = 0
        for Y in YEARS[-4:]:
            tr = [e for e in L if e["Y"] < Y]; te = [e for e in L if e["Y"] == Y]
            sc, st = fit(tr, floor); mb, mn = mae(te, ENG_C, ENG_T), mae(te, sc, st, floor)
            win += mn < mb
            P(f"    forward {Y}: fit car {sc:.2f} tgt {st:.2f}  MAE {mb:.3f} -> {mn:.3f} ({100*(mn/mb-1):+.1f}%)")
        P(f"    forward improves {win}/4")
    # committee check: does the fitted workhorse cell hurt if mis-applied to committee?
    C = [e for e in EV if e["share"] < 0.60 and e["rb2"]]
    P(f"\n  committee RB2 (n={len(C)}): engine MAE {mae(C, ENG_C, ENG_T):.3f}, actual/engine {sum(e['rb2']['act'] for e in C)/sum(proj(e,ENG_C,ENG_T) for e in C):.3f}; full fit {fit(C)}")


# ---------------- SHADOW (the number the site shows: ncMean = own + min(own, k x gained)) ----------------
SH_K = 0.75
def sproj(e, sc, st, k=SH_K, cap=1.0):
    own = e["rb2"]["own"]; g = k * (sc * e["a_cp"] + st * e["a_rp"] * EFF_T)
    return own + (min(own * cap, g) if cap is not None else g)
def smae(L, *a, **kw): return float(np.mean([abs(e["rb2"]["act"] - sproj(e, *a, **kw)) for e in L])) if L else np.nan
def sfit(L, cap):
    best = None
    for sc in np.arange(0.20, 1.01, 0.02):
        m = smae(L, sc, 0.28, cap=cap)
        if best is None or m < best[0]: best = (m, sc)
    return best[1]
def shadow_section(EV):
    L = [e for e in EV if e["share"] >= 0.60 and e["rb2"]]
    acts = np.array([e["rb2"]["act"] for e in L])
    P("\n=== SHADOW replica (site number): own + min(own, .75 x (.28 x absent rush pts + .28 x absent rec pts x .92)) ===")
    base = np.array([sproj(e, 0.28, 0.28) for e in L])
    P(f"  workhorse-out RB2 n={len(L)}: shadow {base.mean():.2f} vs actual {acts.mean():.2f} -> actual/shadow {acts.sum()/base.sum():.3f}; MAE {np.mean(np.abs(acts-base)):.3f}; cap binds in {np.mean([e['rb2']['own'] < SH_K*(0.28*e['a_cp']+0.28*e['a_rp']*EFF_T) for e in L]):.0%}")
    w = 0
    for Y in YEARS:
        s = [e for e in L if e["Y"] == Y]; a = sum(e["rb2"]["act"] for e in s); g = sum(sproj(e, .28, .28) for e in s); w += a > g
        P(f"    {Y}: n={len(s):3d} actual {a/len(s):5.2f} shadow {g/len(s):5.2f} ratio {a/g:.3f}")
    P(f"    under-projected {w}/7 seasons")
    # simple direct model: actual = own + s * absent PPR
    X = np.array([[e["rb2"]["own"], e["a_ppr"]] for e in L]); A = np.c_[np.ones(len(L)), X]
    co = np.linalg.lstsq(A, acts, rcond=None)[0]
    P(f"  OLS actual = {co[0]:.2f} + {co[1]:.2f} x RB2 own + {co[2]:.2f} x absent PPR/g   (Washington own 4.7, Jeanty 16.5 -> {co[0]+co[1]*4.7+co[2]*16.5:.1f})")
    for lo, hi in ((0, 11), (11, 15), (15, 99)):
        s = [e for e in L if lo <= e["a_ppr"] < hi]
        if s: P(f"  absent starter {lo}-{hi} PPR/g: n={len(s)} RB2 actual mean {np.mean([e['rb2']['act'] for e in s]):.2f} median {np.median([e['rb2']['act'] for e in s]):.1f} IQR {np.percentile([e['rb2']['act'] for e in s],25):.1f}-{np.percentile([e['rb2']['act'] for e in s],75):.1f}, RB2 own {np.mean([e['rb2']['own'] for e in s]):.1f}, shadow {np.mean([sproj(e,.28,.28) for e in s]):.2f}")
    s = [e for e in L if e["a_ppr"] >= 14 and e["rb2"]["own"] < 7]
    if s: P(f"  Jeanty/Washington-like (absent >= 14 PPR, RB2 own < 7): n={len(s)} actual mean {np.mean([e['rb2']['act'] for e in s]):.2f} median {np.median([e['rb2']['act'] for e in s]):.1f} IQR {np.percentile([e['rb2']['act'] for e in s],25):.1f}-{np.percentile([e['rb2']['act'] for e in s],75):.1f} >=12: {np.mean([e['rb2']['act']>=12 for e in s]):.0%}; shadow {np.mean([sproj(e,.28,.28) for e in s]):.2f}; own {np.mean([e['rb2']['own'] for e in s]):.1f}")
    P("  candidate cells (car share for the workhorse-out RB2, tgt .28, k .75):")
    cands = [("car .40 cap own", .40, 1.0), ("car .40 cap 1.5x own", .40, 1.5), ("car .40 no cap", .40, None), ("car .50 cap 1.5x", .50, 1.5), ("car .28 no cap", .28, None), ("car .28 cap 1.5x", .28, 1.5)]
    for lab, sc, cap in cands:
        pj = np.array([sproj(e, sc, .28, cap=cap) for e in L])
        wins = sum(smae([e for e in L if e["Y"] == Y], sc, .28, cap=cap) < smae([e for e in L if e["Y"] == Y], .28, .28) for Y in YEARS)
        fw = sum(smae([e for e in L if e["Y"] == Y], sc, .28, cap=cap) < smae([e for e in L if e["Y"] == Y], .28, .28) for Y in YEARS[-4:])
        mse0 = np.mean((acts - base) ** 2); mse1 = np.mean((acts - pj) ** 2)
        P(f"    {lab:22s}: mean {pj.mean():.2f} (act {acts.mean():.2f}) MAE {np.mean(np.abs(acts-base)):.3f} -> {np.mean(np.abs(acts-pj)):.3f} ({100*(np.mean(np.abs(acts-pj))/np.mean(np.abs(acts-base))-1):+.1f}%), seasons {wins}/7, last-4 {fw}/4 | MSE {100*(mse1/mse0-1):+.1f}%")
    for cap in (1.0, 1.5, None):
        w = 0; tb = tn = 0; fw = 0
        for Y in YEARS:
            tr = [e for e in L if e["Y"] != Y]; te = [e for e in L if e["Y"] == Y]; sc = sfit(tr, cap)
            mb, mn = smae(te, .28, .28), smae(te, sc, .28, cap=cap); w += mn < mb; tb += mb * len(te); tn += mn * len(te)
        fits = []
        for Y in YEARS[-4:]:
            tr = [e for e in L if e["Y"] < Y]; te = [e for e in L if e["Y"] == Y]; sc = sfit(tr, cap); fits.append(round(sc, 2))
            fw += smae(te, sc, .28, cap=cap) < smae(te, .28, .28)
        P(f"    fitted car share, cap={cap}: full fit {sfit(L, cap):.2f}; LOYO {w}/7 pooled MAE {100*(tn/tb-1):+.1f}%; forward {fw}/4 (fits {fits})")
    # does the shadow under-project the committee RB2?
    C = [e for e in EV if e["share"] < 0.60 and e["rb2"]]
    P(f"  committee RB2 n={len(C)}: actual {np.mean([e['rb2']['act'] for e in C]):.2f} shadow {np.mean([sproj(e,.28,.28) for e in C]):.2f} ratio {sum(e['rb2']['act'] for e in C)/sum(sproj(e,.28,.28) for e in C):.3f}")

if __name__ == "__main__":
    main()
    EV, _, _ = collect()
    shadow_section(EV)

# ---- targeted: gain cap for the workhorse-out RB2 = max(own, CAPABS) instead of own; car share variants ----
def tproj(e, sc, capabs, k=SH_K):
    own = e["rb2"]["own"]; g = k * (sc * e["a_cp"] + 0.28 * e["a_rp"] * EFF_T)
    return own + min(max(own, capabs), g)
def targeted(EV):
    L = [e for e in EV if e["share"] >= 0.60 and e["rb2"]]; acts = np.array([e["rb2"]["act"] for e in L])
    sub = [e for e in L if e["a_ppr"] >= 14 and e["rb2"]["own"] < 7]
    P("\n=== TARGETED CELL: workhorse-out RB2 gain cap = max(own, C) (shadow 'gain <= own'), car share s ===")
    mb = lambda S: float(np.mean([abs(e["rb2"]["act"] - sproj(e, .28, .28)) for e in S]))
    for sc in (0.28, 0.34, 0.40):
        for C in (0, 5, 6, 8):
            m = lambda S: float(np.mean([abs(e["rb2"]["act"] - tproj(e, sc, C)) for e in S]))
            wins = sum(m([e for e in L if e["Y"] == Y]) < mb([e for e in L if e["Y"] == Y]) for Y in YEARS)
            ties = sum(abs(m([e for e in L if e["Y"] == Y]) - mb([e for e in L if e["Y"] == Y])) < 1e-9 for Y in YEARS)
            fw = sum(m([e for e in L if e["Y"] == Y]) < mb([e for e in L if e["Y"] == Y]) for Y in YEARS[-4:])
            pj = np.array([tproj(e, sc, C) for e in L])
            P(f"  s {sc:.2f} C {C}: mean {pj.mean():.2f} (act {acts.mean():.2f}) MAE {100*(m(L)/mb(L)-1):+.1f}% seasons {wins}/7 (ties {ties}) last-4 {fw}/4 | "
              f"Washington-like n={len(sub)}: proj {np.mean([tproj(e, sc, C) for e in sub]):.2f} vs act {np.mean([e['rb2']['act'] for e in sub]):.2f}, MAE {100*(m(sub)/mb(sub)-1):+.1f}%")
targeted(collect()[0])

def targeted_loyo(EV):
    L = [e for e in EV if e["share"] >= 0.60 and e["rb2"]]
    m = lambda S, sc, C: float(np.mean([abs(e["rb2"]["act"] - tproj(e, sc, C)) for e in S]))
    mb = lambda S: float(np.mean([abs(e["rb2"]["act"] - sproj(e, .28, .28)) for e in S]))
    grid = [(sc, C) for sc in np.arange(0.20, 0.61, 0.02) for C in (0, 4, 5, 6, 7, 8, 10)]
    fitg = lambda S: min(grid, key=lambda g: m(S, *g))
    P("\n=== TARGETED CELL LOYO (fit car share s and cap floor C on 6 seasons, test the 7th) ===")
    w = 0; tb = tn = 0
    for Y in YEARS:
        tr = [e for e in L if e["Y"] != Y]; te = [e for e in L if e["Y"] == Y]; g = fitg(tr)
        a, b = mb(te), m(te, *g); w += b < a; tb += a * len(te); tn += b * len(te)
        P(f"  {Y}: fit s {g[0]:.2f} C {g[1]}  MAE {a:.3f} -> {b:.3f} ({100*(b/a-1):+.1f}%)")
    P(f"  LOYO {w}/7, pooled {100*(tn/tb-1):+.1f}%")
    fw = 0
    for Y in YEARS[-4:]:
        tr = [e for e in L if e["Y"] < Y]; te = [e for e in L if e["Y"] == Y]; g = fitg(tr)
        a, b = mb(te), m(te, *g); fw += b < a
        P(f"  forward {Y}: fit s {g[0]:.2f} C {g[1]}  MAE {a:.3f} -> {b:.3f} ({100*(b/a-1):+.1f}%)")
    P(f"  forward {fw}/4; full-sample fit {fitg(L)}")
targeted_loyo(collect()[0])
