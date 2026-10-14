#!/usr/bin/env python3
"""
ABSENCE MAP, ALL POSITIONS (Jack 2026-10-09: "can we run all weekly data in past seasons for when players are out, how it impacts
all positions" / "we have to give the correct volume to correct players").

Weekly DB 2019-25 (backtest_sim_calibration.WEEKLY; team from row tm or cal.infer_team). Per team-week (4th+ team game):
  trailing = last 3 team games, player needs 2+ of them. Roles by ORIGINAL trailing rank on the team (absent player included):
  QB1 = most trailing pass att; RB1/2/3+ by carries; WR1/2/3/4+ by targets; TE1/TE2+ by targets.
  MEANINGFUL absence = trailing player with no row, not traded/moved later that season, and (QB1 with >= .60 of team att) or
  (skill with >= .08 of team targets or >= .15 of team carries).
  Absent roles: QB1 | RB_WH (RB1 >= .60 of team RB carries) | RB_COMM (RB1 < .60) | RB2 | WR1 | WR2 | WR3 | TE1_TOP (TE1 who is
  the team's top target-getter) | TE1 | TE2.
  SINGLE = exactly one meaningful absence (so QB-out weeks are excluded unless the QB is the absence). CONTROL = zero.
Teammate groups (sum over players in the slot, absent minor players included as -trailing): QB1, QBB (other QBs), RB1, RB2, RB3,
  WR1..WR4, TE1, TE2 (+ deeper), and BODIES by position (row now, no baseline). Delta = this week - trailing avg, control-adjusted
  by subtracting the same slot's mean delta in that season's control weeks. Points: full PPR (QB incl. 4-pt pass TD).
Engine replica (weekly units, own = trailing PPR): pool (POOL lead/sec shares by same-pos healthy rank, tgtOther, workhorse
  cell .30 / cap max(own,6)), x .75 strength, gain <= own; then NMU rank mult, PROMO, TEAM_VAC; QB out: backup QB = max(own,
  .85 x starter), WR dock .15 star (trailing >= 14 PPR as ADP<=60 proxy) / .05.
Writes absence_all_positions.log + data/absence_all_positions.json (+ data/absence_events.pkl for the follow-up tests).
"""
import os, sys, json, pickle
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_sim_calibration as cal
LOG = open(os.path.join(HERE, "absence_all_positions.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + "\n"); LOG.flush()

YEARS = list(range(2019, 2026)); TRAIL = 3
TGT_MIN, CAR_MIN, QB_MIN = 0.08, 0.15, 0.60
TM_ALIAS = {"ARZ": "ARI", "WSH": "WAS", "JAC": "JAX", "LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "HST": "HOU", "BLT": "BAL", "CLV": "CLE"}
SLOTS = ["QB1", "QBB", "RB1", "RB2", "RB3", "WR1", "WR2", "WR3", "WR4", "TE1", "TE2"]
BODY = ["bQB", "bRB", "bWR", "bTE"]
F = ("tgt", "ra", "pa", "ppr", "half", "recp", "rushp")

# ---------------- engine constants (sim_lab/engine.js as of 2026-10-09) ----------------
ENG = dict(
    POOL={"RB": {"lead": dict(tgtSame=[0.28, 0.18], carSame=[0.28, 0.16, 0.10], tgtOther=0.0),
                 "sec": dict(tgtSame=[0.28, 0.18], carSame=[0.28, 0.16, 0.10], tgtOther=0.0)},
          "WR": {"lead": dict(tgtSame=[0.09, 0.15, 0.16, 0.10], carSame=[], tgtOther=0.08),
                 "sec": dict(tgtSame=[0.00, 0.11, 0.15, 0.10], carSame=[], tgtOther=0.00)},
          "TE": {"lead": dict(tgtSame=[0.25, 0.10], carSame=[], tgtOther=0.36),
                 "sec": dict(tgtSame=[0.00, 0.22], carSame=[], tgtOther=0.00)}},
    TE_SEC2=(0.25, 4.0), EFF_T=0.92, EFF_C=1.0, K=0.75, WH=(0.60, 0.30, 6.0),
    NMU={1: 1.04, 2: 0.99, 3: 0.99, 4: 1.03, 5: 1.03, 6: 1.03}, PROMO={"RB": 1.034, "WR": 1.071, "TE": 1.207}, PROMO_MIN=5.0,
    TV=0.2, QB_INH=0.85, QBDOCK=(0.15, 0.05), QBSTAR_PPR=14.0)


def pts(w, pos):
    rec = w.get("rec") or 0
    recp = rec + (w.get("rcy") or 0) * 0.1 + (w.get("rctd") or 0) * 6
    rushp = (w.get("ry") or 0) * 0.1 + (w.get("rtd") or 0) * 6
    passp = (w.get("py") or 0) * 0.04 + (w.get("ptd") or 0) * 4 - (w.get("int") or 0) * 2 if pos == "QB" else 0.0
    fl = (w.get("fl") or 0) * 2
    return recp, rushp, recp + rushp + passp - fl, recp + rushp + passp - fl - rec * 0.5


def build(Y):
    rows = defaultdict(list); teams_of = defaultdict(set); hist = defaultdict(list)
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
                recp, rushp, ppr, half = pts(w, pos)
                key = (nm, pos, id(rec))
                rows[(tm, int(w["wk"]))].append(dict(key=key, n=nm, pos=pos, tgt=float(w.get("tgt") or 0), ra=float(w.get("ra") or 0),
                                                     pa=float(w.get("pa") or 0), ppr=ppr, half=half, recp=recp, rushp=rushp))
                teams_of[key].add((tm, int(w["wk"])))
                hist[(key, tm)].append((int(w["wk"]), float(w.get("tgt") or 0) + float(w.get("ra") or 0), float(w.get("pa") or 0)))
    return rows, teams_of, hist


def slot_of(pos, rank):
    if pos == "QB": return "QB1" if rank == 1 else "QBB"
    if pos == "RB": return "RB%d" % min(rank, 3)
    if pos == "WR": return "WR%d" % min(rank, 4)
    return "TE%d" % min(rank, 2)


def collect():
    EV, CTRL = [], []
    for Y in YEARS:
        rows, teams_of, hist = build(Y)
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
                T = dict(tgt=tsum("tgt"), ra=tsum("ra"), pa=tsum("pa"), skp=tsum("ppr", lambda r: r["pos"] != "QB"), qbp=tsum("ppr", lambda r: r["pos"] == "QB"),
                         rbra=tsum("ra", lambda r: r["pos"] == "RB"))
                if T["tgt"] < 15 or T["ra"] < 10 or T["pa"] < 15: continue
                N = dict(tgt=sum(r["tgt"] for r in cur.values()), ra=sum(r["ra"] for r in cur.values()), pa=sum(r["pa"] for r in cur.values()),
                         skp=sum(r["ppr"] for r in cur.values() if r["pos"] != "QB"), qbp=sum(r["ppr"] for r in cur.values() if r["pos"] == "QB"))
                # ranks
                rank = {}
                for pos, f in (("QB", "pa"), ("RB", "ra"), ("WR", "tgt"), ("TE", "tgt")):
                    L = sorted([k for k, v in trail.items() if v["pos"] == pos], key=lambda k: -(trail[k][f] + 1e-3 * trail[k]["tgt"] + 1e-6 * trail[k]["ppr"]))
                    for j, k in enumerate(L): rank[k] = j + 1
                pcs = sorted([k for k, v in trail.items() if v["pos"] != "QB"], key=lambda k: -trail[k]["tgt"])
                pcrank = {k: j + 1 for j, k in enumerate(pcs)}
                top_tgt = trail[pcs[0]]["tgt"] if pcs else 0
                absent = [k for k in trail if k not in cur and not any(t2 != tm and w2 > wk for (t2, w2) in teams_of[k])]
                def meaningful(k):
                    v = trail[k]
                    if v["pos"] == "QB": return rank[k] == 1 and v["pa"] / T["pa"] >= QB_MIN
                    return v["tgt"] / T["tgt"] >= TGT_MIN or v["ra"] / T["ra"] >= CAR_MIN
                M = [k for k in absent if meaningful(k)]
                if len(M) > 2: continue
                def role(k):
                    v = trail[k]; r = rank[k]
                    if v["pos"] == "QB": return "QB1"
                    if v["pos"] == "RB":
                        if r == 1: return "RB_WH" if v["ra"] / max(1e-9, T["rbra"]) >= 0.60 else "RB_COMM"
                        return "RB2" if r == 2 else "RB3+"
                    if v["pos"] == "WR": return "WR%d" % r if r <= 3 else "WR4+"
                    if r == 1: return "TE1_TOP" if v["tgt"] >= top_tgt - 1e-9 else "TE1"
                    return "TE2"
                # slot deltas (exclude meaningful absents themselves)
                sl = {s: dict(dc=0.0, dt=0.0, dp=0.0, n=0) for s in SLOTS + BODY}
                mem = []
                for k, v in trail.items():
                    if k in M: continue
                    s = slot_of(v["pos"], rank[k]); r = cur.get(k)
                    a = r if r else dict(tgt=0.0, ra=0.0, ppr=0.0, half=0.0, recp=0.0, rushp=0.0, pa=0.0)
                    d = sl[s]; d["dc"] += a["ra"] - v["ra"]; d["dt"] += a["tgt"] - v["tgt"]; d["dp"] += a["ppr"] - v["ppr"]; d["n"] += 1
                    if r and v["pos"] != "QB":
                        mem.append(dict(slot=s, pos=v["pos"], n=v["n"], rank=rank[k], pcrank=pcrank.get(k, 99), own=v["ppr"], ownh=v["half"],
                                        ownrec=v["recp"], ownrush=v["rushp"], bt=v["tgt"], bc=v["ra"], act=a["ppr"], at=a["tgt"], ac=a["ra"]))
                    elif r and v["pos"] == "QB":
                        mem.append(dict(slot=s, pos="QB", n=v["n"], rank=rank[k], pcrank=99, own=v["ppr"], ownh=v["half"], ownrec=0, ownrush=v["rushp"],
                                        bt=0, bc=v["ra"], act=a["ppr"], at=0, ac=a["ra"]))
                for k, r in cur.items():
                    if k in trail: continue
                    d = sl["b" + r["pos"]]; d["dc"] += r["ra"]; d["dt"] += r["tgt"]; d["dp"] += r["ppr"]; d["n"] += 1
                    if r["pos"] == "QB": mem.append(dict(slot="bQB", pos="QB", n=r["n"], rank=0, pcrank=99, own=0.0, ownh=0.0, ownrec=0, ownrush=0, bt=0, bc=0, act=r["ppr"], at=0, ac=r["ra"]))
                # RETURNER = plays now, no trailing baseline, but was a regular for this team earlier this season (2+ games,
                # >= 5 touches+targets or >= 15 att a game): an injured starter coming back, not a new body
                ret = False
                for k in cur:
                    if k in trail: continue
                    h = [x for x in hist[(k, tm)] if x[0] < wk]
                    if len(h) >= 2 and (np.mean([x[1] for x in h]) >= 5 or np.mean([x[2] for x in h]) >= 15): ret = True; break
                base = dict(Y=Y, wk=wk, tm=tm, T=T, N=N, sl=sl, mem=mem, ret=ret)
                if not M:
                    CTRL.append(base); continue
                A = []
                for k in M:
                    v = trail[k]
                    A.append(dict(role=role(k), pos=v["pos"], n=v["n"], ppr=v["ppr"], half=v["half"], recp=v["recp"], rushp=v["rushp"], tgt=v["tgt"], ra=v["ra"],
                                  pa=v["pa"], tsh=v["tgt"] / T["tgt"], roomsh=(v["ra"] / T["rbra"] if v["pos"] == "RB" and T["rbra"] > 0 else 0),
                                  lead=(v["pos"] != "QB" and v["tgt"] >= top_tgt - 1e-9), pcrank=pcrank.get(k, 99)))
                base["A"] = A
                EV.append(base)
    return EV, CTRL


# ---------------- engine replica ----------------
def eng_proj(ev, m, E=ENG):
    """projected PPR for teammate row m in event ev (single or double absence), weekly units."""
    own = m["own"]
    A = ev["A"]; qb_out = any(a["pos"] == "QB" for a in A)
    if m["pos"] == "QB":
        if qb_out:
            st = max(a["ppr"] for a in A if a["pos"] == "QB")
            # backup = the best healthy QB (rank-1 of who played) -> max(own, .85 x starter)
            if m["slot"] in ("QBB", "bQB") and m.get("qbfill"): return max(own, E["QB_INH"] * st)
        return own
    healthy = [x for x in ev["mem"] if x["pos"] in ("RB", "WR", "TE")]
    gained = 0.0; capx = own; mult = 1.0
    for a in A:
        if a["pos"] == "QB": continue
        rule = E["POOL"][a["pos"]]["lead" if a["lead"] else "sec"]
        same = sorted([x for x in healthy if x["pos"] == a["pos"]], key=lambda x: x["rank"])
        i = next((j for j, x in enumerate(same) if x is m), -1)
        if i >= 0:
            wt = rule["tgtSame"][i] if i < len(rule["tgtSame"]) else 0
            if a["pos"] == "TE" and not a["lead"] and i == 0 and not wt and m["ownh"] < E["TE_SEC2"][1]: wt = E["TE_SEC2"][0]
            cs = rule["carSame"][i] if i < len(rule["carSame"]) else 0
            if a["pos"] == "RB" and m["pos"] == "RB" and i == 0 and a["roomsh"] >= E["WH"][0]:
                cs = E["WH"][1]; capx = max(own, E["WH"][2])
            gained += wt * a["recp"] * E["EFF_T"] + cs * a["rushp"] * E["EFF_C"]
        if rule["tgtOther"] > 0 and m["pos"] != a["pos"] and m["pos"] != "RB":
            oth = [x for x in healthy if x["pos"] != a["pos"] and x["pos"] != "RB"]; tot = sum(x["ownrec"] for x in oth)
            if tot > 0: gained += rule["tgtOther"] * a["recp"] * m["ownrec"] / tot * E["EFF_T"]
        # PROMO: same-pos regular ahead (half >= 5 and above own)
        if a["pos"] == m["pos"] and a["half"] >= E["PROMO_MIN"] and a["half"] > m["ownh"]: mult = max(mult, E["PROMO"][m["pos"]])
    p = own + min(capx, E["K"] * gained) if own > 0 else E["K"] * gained
    # NMU: non-RB pass catcher with share >= .10 out -> by original pass-catcher rank
    if any(a["pos"] in ("WR", "TE") and a["tsh"] >= 0.10 for a in A):
        p *= E["NMU"].get(m["pcrank"], 1.0)
    p *= mult
    tv = sum(a["tsh"] for a in A if a["pos"] in ("WR", "TE") and a["tsh"] >= 0.10)
    if tv > 0: p *= 1 + E["TV"] * tv
    if qb_out and m["pos"] == "WR":
        p *= 1 - (E["QBDOCK"][0] if own >= E["QBSTAR_PPR"] else E["QBDOCK"][1])
    return p


def tag_qbfill(ev):
    """mark the QB who actually replaced the starter (most att among QBs who played, excluding QB1 rows)."""
    qbs = [m for m in ev["mem"] if m["pos"] == "QB" and m["slot"] in ("QBB", "bQB")]
    if qbs:
        best = max(qbs, key=lambda m: m["act"] + 0 * m["ac"])
        best["qbfill"] = True


def pv(num, den, n):
    return f"{num/den:+6.2f}" if den / max(1, n) >= 1.0 else "     ."


def main():
    EV0, CTRL0 = collect()
    EV = [e for e in EV0 if not e["ret"]]; CTRL = [c for c in CTRL0 if not c["ret"]]
    P(f"(returning-regular weeks excluded: {len(EV0)-len(EV)} of {len(EV0)} absence weeks, {len(CTRL0)-len(CTRL)} of {len(CTRL0)} control weeks)")
    for ev in EV: tag_qbfill(ev)
    single = [e for e in EV if len(e["A"]) == 1]; double = [e for e in EV if len(e["A"]) == 2]
    P(f"=== ABSENCE MAP 2019-25: {len(single)} single-absence team-weeks, {len(double)} double, {len(CTRL)} control (no meaningful absence) ===")
    # control means by season x slot
    cm = {}
    for Y in YEARS:
        C = [c for c in CTRL if c["Y"] == Y]
        for s in SLOTS + BODY:
            for f in ("dc", "dt", "dp"):
                cm[(Y, s, f)] = float(np.mean([c["sl"][s][f] for c in C]))
        for f in ("tgt", "ra", "pa", "skp", "qbp"):
            cm[(Y, "team", f)] = float(np.mean([c["N"][f] - c["T"][f] for c in C]))
    P("control (all slots, mean delta vs trailing, PPR): " + " ".join(f"{s} {np.mean([cm[(Y, s, 'dp')] for Y in YEARS]):+.2f}" for s in SLOTS + BODY))

    out = {"meta": dict(n_single=len(single), n_double=len(double), n_ctrl=len(CTRL), years=YEARS), "cells": {}, "team": {}}
    ROLES = ["QB1", "RB_WH", "RB_COMM", "RB2", "WR1", "WR2", "WR3", "TE1_TOP", "TE1", "TE2"]
    STAR = {"QB": 20.0}
    mism = []
    for R in ROLES:
        L = [e for e in single if e["A"][0]["role"] == R]
        if not L: continue
        a0 = lambda e: e["A"][0]
        Vt = np.mean([a0(e)["tgt"] for e in L]); Vc = np.mean([a0(e)["ra"] for e in L]); Vp = np.mean([a0(e)["ppr"] for e in L])
        P(f"\n##### ABSENT {R}: n={len(L)} | he averaged {Vt:.1f} tgt, {Vc:.1f} car" + (f", {np.mean([a0(e)['pa'] for e in L]):.1f} att" if R == "QB1" else "") + f", {Vp:.1f} PPR/g")
        # team totals
        tl = []
        for f, lab in (("ra", "team carries"), ("tgt", "team targets"), ("pa", "pass att"), ("skp", "RB+WR+TE PPR"), ("qbp", "QB pts")):
            d = np.array([e["N"][f] - e["T"][f] - cm[(e["Y"], "team", f)] for e in L])
            sg = sum(np.sign(np.mean([e["N"][f] - e["T"][f] - cm[(e["Y"], "team", f)] for e in L if e["Y"] == Y])) == np.sign(d.mean()) for Y in YEARS if any(e["Y"] == Y for e in L))
            tl.append(f"{lab} {d.mean():+.1f} ({sg}/7)")
            out["team"].setdefault(R, {})[f] = float(d.mean())
        P("  TEAM (ctrl-adj): " + " | ".join(tl))
        kp = lambda f, V: (f"{1 + np.mean([e['N'][f] - e['T'][f] - cm[(e['Y'], 'team', f)] for e in L]) / V:.2f}" if V >= 1 else "n/a")
        P(f"  team keeps {kp('tgt', Vt)} of his targets, {kp('ra', Vc)} of his carries, skill-player PPR keeps {kp('skp', Vp)} of his PPR")
        P(f"  {'slot':5s} {'n':>4s} {'base PPR':>8s} {'dCar':>6s} {'dTgt':>6s} {'%carV':>6s} {'%tgtV':>6s} {'dPPR':>6s} {'med':>5s} {'sgn':>4s} | {'engine':>6s} {'gap':>6s} verdict")
        for s in SLOTS + BODY:
            rows = [e for e in L if e["sl"][s]["n"] > 0]
            if len(rows) < 8: continue
            dc = np.array([e["sl"][s]["dc"] - cm[(e["Y"], s, "dc")] for e in rows]); dt = np.array([e["sl"][s]["dt"] - cm[(e["Y"], s, "dt")] for e in rows])
            dp = np.array([e["sl"][s]["dp"] - cm[(e["Y"], s, "dp")] for e in rows])
            sg = sum(np.sign(np.mean([dp[j] for j, e in enumerate(rows) if e["Y"] == Y])) == np.sign(dp.mean()) for Y in YEARS if any(e["Y"] == Y for e in rows))
            base = np.mean([sum(m["own"] for m in e["mem"] if m["slot"] == s) for e in rows])
            # engine delta for the slot (members who played; bodies: engine only covers the backup QB)
            ed = []
            for e in rows:
                ms = [m for m in e["mem"] if m["slot"] == s]
                ed.append(sum(eng_proj(e, m) - m["own"] for m in ms))
            ed = np.array(ed); gap = dp.mean() - ed.mean()
            se = dp.std() / np.sqrt(len(dp))
            if abs(gap) < max(0.3, 1.5 * se): vd = "OK"
            elif gap > 0: vd = "UNDER" + (" (engine gives ~0)" if abs(ed.mean()) < 0.1 else "")
            else: vd = "OVER" + (" (wrong player: data ~0)" if abs(dp.mean()) < max(0.3, 1.5 * se) else "")
            P(f"  {s:5s} {len(rows):4d} {base:8.1f} {dc.mean():+6.2f} {dt.mean():+6.2f} {pv(dc.sum(), sum(a0(e)['ra'] for e in rows), len(rows))} {pv(dt.sum(), sum(a0(e)['tgt'] for e in rows), len(rows))} "
              f"{dp.mean():+6.2f} {np.median(dp):+5.1f} {sg}/7 | {ed.mean():+6.2f} {gap:+6.2f} {vd}")
            out["cells"][f"{R}|{s}"] = dict(n=len(rows), base=float(base), dCar=float(dc.mean()), dTgt=float(dt.mean()), dPPR=float(dp.mean()), med=float(np.median(dp)),
                                           se=float(se), sign=int(sg), engine=float(ed.mean()), gap=float(gap), verdict=vd,
                                           carV=float(dc.sum() / max(1e-9, sum(a0(e)['ra'] for e in rows))), tgtV=float(dt.sum() / max(1e-9, sum(a0(e)['tgt'] for e in rows))))
            if not s.startswith("b") or s == "bQB":
                mism.append((abs(gap) * len(rows) / 7, R, s, gap, len(rows), dp.mean(), ed.mean(), sg, se))
        # level split
        thr = STAR.get(L[0]["A"][0]["pos"], 15.0)
        for lab, sel in (("STAR (>= %.0f PPR/g)" % thr, lambda e: a0(e)["ppr"] >= thr), ("regular", lambda e: a0(e)["ppr"] < thr)):
            S = [e for e in L if sel(e)]
            if len(S) < 15: P(f"  level {lab}: n={len(S)} (too few)"); continue
            cells = []
            for s in SLOTS + ["bQB", "bRB", "bWR", "bTE"]:
                rows = [e for e in S if e["sl"][s]["n"] > 0]
                if len(rows) < 10: continue
                dp = np.mean([e["sl"][s]["dp"] - cm[(e["Y"], s, "dp")] for e in rows])
                ed = np.mean([sum(eng_proj(e, m) - m["own"] for m in e["mem"] if m["slot"] == s) for e in rows])
                if abs(dp) >= 0.4 or abs(ed) >= 0.4: cells.append(f"{s} {dp:+.1f} (eng {ed:+.1f})")
            P(f"  level {lab} n={len(S)}: " + ", ".join(cells))
    # QB-out specifics
    L = [e for e in single if e["A"][0]["role"] == "QB1"]
    if L:
        fill = [m for e in L for m in e["mem"] if m.get("qbfill")]
        st = [e["A"][0]["ppr"] for e in L for m in e["mem"] if m.get("qbfill")]
        act = np.array([m["act"] for m in fill]); stp = np.array(st)
        P(f"\n##### BACKUP QB (the QB who played, n={len(fill)}): actual {act.mean():.2f} pts vs starter's trailing {stp.mean():.2f} -> ratio {act.sum()/stp.sum():.2f} "
          f"(engine .85 x starter = {0.85*stp.mean():.2f}); median {np.median(act):.1f}; with baseline: {sum(1 for m in fill if m['slot']=='QBB')}")
        for Y in YEARS:
            ii = [j for j, e in enumerate([e for e in L for m in e["mem"] if m.get("qbfill")]) if e["Y"] == Y]
            if ii: P(f"    {Y}: n={len(ii)} ratio {act[ii].sum()/stp[ii].sum():.2f}")
        for lo, hi in ((0, 16), (16, 20), (20, 99)):
            ii = [j for j in range(len(stp)) if lo <= stp[j] < hi]
            if ii: P(f"    starter {lo}-{hi} pts/g: n={len(ii)} backup {act[ii].mean():.2f} ratio {act[ii].sum()/stp[ii].sum():.2f}")
        out["backup_qb"] = dict(n=len(fill), act=float(act.mean()), starter=float(stp.mean()), ratio=float(act.sum() / stp.sum()))
    # double absences
    P("\n##### DOUBLE ABSENCES (two meaningful out; ctrl-adj dPPR by slot, engine in parens)")
    combos = defaultdict(list)
    for e in double: combos[tuple(sorted(a["role"] for a in e["A"]))].append(e)
    for cb, L2 in sorted(combos.items(), key=lambda kv: -len(kv[1])):
        P(f"  {'+'.join(cb):18s} n={len(L2)}")
        if len(L2) < 20: continue
        cells = []
        for s in SLOTS + BODY:
            rows = [e for e in L2 if e["sl"][s]["n"] > 0]
            if len(rows) < 10: continue
            dp = np.mean([e["sl"][s]["dp"] - cm[(e["Y"], s, "dp")] for e in rows])
            ed = np.mean([sum(eng_proj(e, m) - m["own"] for m in e["mem"] if m["slot"] == s) for e in rows])
            if abs(dp) >= 0.5 or abs(ed) >= 0.5: cells.append(f"{s} {dp:+.1f} ({ed:+.1f})")
        P(f"  {'+'.join(cb):18s} n={len(L2):3d}: " + ", ".join(cells))
    # mismatch ranking
    mism.sort(reverse=True)
    P("\n##### BIGGEST MISMATCHES (|data - engine| PPR per event x events per season)")
    for sc, R, s, gap, n, dp, ed, sg, se in mism[:20]:
        P(f"  {R:8s} -> {s:4s}: data {dp:+.2f} engine {ed:+.2f} gap {gap:+.2f} (se {se:.2f}, n {n}, sign {sg}/7) = {sc:.1f} PPR/season mis-assigned")
    out["mismatch"] = [dict(score=float(a), absent=b, slot=c, gap=float(d), n=int(e), data=float(f), engine=float(g), sign=int(h)) for a, b, c, d, e, f, g, h, _ in mism[:25]]
    json.dump(out, open(os.path.join(HERE, "data", "absence_all_positions.json"), "w"), indent=1)
    pickle.dump((EV, CTRL), open(os.path.join(HERE, "data", "absence_events.pkl"), "wb"))
    P("\nwrote data/absence_all_positions.json, data/absence_events.pkl")


if __name__ == "__main__":
    main()
