#!/usr/bin/env python3
"""
VACATED VOLUME BY STAT: when a teammate is out, which STAT LINES rise? (2026-09-20)

Jack asked why Aaron Jones' rush-yards number barely rose with Jordan Mason on IR (model 41 vs books 59.5). The
opportunity pool (engine POOL, backtest_vacated_pool.py) already works in stat units - absorbed TARGETS and CARRIES per
healthy teammate - but then converts them to fantasy points and applies ONE factor f = 1 + gained / own to the mean, sd
and EVERY stat component. Mason vacates carries, yet Jones' receptions and receiving yards rose with his rush yards
(x1.18 each) and the rush line got +7 yards where the absorbed carries are worth +15.

Same events as backtest_vacated_pool.py (2019-25 team-weeks where exactly one meaningful RB/WR/TE is absent, QB healthy).
For every healthy absorber the engine's rules give volume to (same-position by rank, WR/TE for the other-position
target share), baseline = his trailing 3-game per-game line. Three predictions of THIS week's ry / rec / rcy:
  none      trailing line, no boost
  uniform   trailing line x f                                   (today's engine)
  by-stat   ry + k x absorbed carries x his yds/carry;  rec, rcy + k x absorbed targets x EFF x his rec (yds) per target
            k = 1 is the engine's own volume; k grid shows whether the pool weights themselves are too small.
No fitted parameters at k = 1 (the pool weights are shared by uniform and by-stat), so every event is out of sample for
the comparison; k is chosen leave-one-season-out. Log vacated_mix.log, results data/vacated_mix_bt.json.
"""
import json, os, sys
from collections import defaultdict
import numpy as np
import backtest_sim_calibration as cal
from backtest_vacated_pool import TM_ALIAS, TRAIL, TGT_SHARE_MIN, CAR_SHARE_MIN, POS, team_weeks

HERE = os.path.dirname(os.path.abspath(__file__))
SEASONS = range(2019, 2026)
POOL = {"RB": {"lead": {"tgtSame": [0.28, 0.18], "carSame": [0.28, 0.16, 0.10], "tgtOther": 0.15},
               "sec": {"tgtSame": [0.28, 0.18], "carSame": [0.28, 0.16, 0.10], "tgtOther": 0.15}},
        "WR": {"lead": {"tgtSame": [0.09, 0.15, 0.16, 0.10], "carSame": [], "tgtOther": 0.08},
               "sec": {"tgtSame": [0.00, 0.11, 0.15, 0.10], "carSame": [], "tgtOther": 0.00}},
        "TE": {"lead": {"tgtSame": [0.25, 0.10], "carSame": [], "tgtOther": 0.36},
               "sec": {"tgtSame": [0.00, 0.22], "carSame": [], "tgtOther": 0.00}}}
EFF_T, EFF_C, FLOOR = 0.92, 1.00, 4.0
STATS = ("ry", "rec", "rcy"); KEYS = ("tgt", "ra", "ry", "rec", "rcy", "rtd", "rctd", "pa")
KG = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
_LOG = open(os.path.join(HERE, "vacated_mix.log"), "w", encoding="utf-8")
def P(*a):
    t = " ".join(str(x) for x in a); _LOG.write(t + "\n"); _LOG.flush()
    try: sys.__stdout__.write(t + "\n"); sys.__stdout__.flush()
    except Exception: pass


def build(season):
    rows = defaultdict(list)
    for nm, lst in cal.WEEKLY.items():
        for rec in lst:
            pos = rec.get("pos")
            if pos not in ("QB", "RB", "WR", "TE"): continue
            wks = [w for w in rec.get("seasons", {}).get(str(season), []) if cal.played(w)]
            if not wks: continue
            inferred = None
            for w in wks:
                tm = w.get("tm"); tm = TM_ALIAS.get(tm, tm) if tm else None
                if not tm:
                    if inferred is None: inferred = cal.infer_team(rec, season) or ""
                    tm = inferred
                if not tm: continue
                r = {"n": nm, "pos": pos, "seen": (nm, pos)}
                for k in KEYS: r[k] = w.get(k) or 0
                rows[(tm, int(w["wk"]))].append(r)
    return rows


def events():
    out = []
    for Y in SEASONS:
        rows = build(Y); tw = team_weeks(rows)
        for tm, wks in tw.items():
            for i, wk in enumerate(wks):
                if i < TRAIL: continue
                prev = wks[i - TRAIL:i]; cur = {r["seen"]: r for r in rows[(tm, wk)]}
                trail = {}
                for pw in prev:
                    for r in rows[(tm, pw)]:
                        t = trail.setdefault(r["seen"], dict({k: 0.0 for k in KEYS}, g=0, pos=r["pos"], n=r["n"]))
                        t["g"] += 1
                        for k in KEYS: t[k] += r[k]
                trail = {k: v for k, v in trail.items() if v["g"] >= 2}
                for v in trail.values():
                    for k in KEYS: v[k] /= v["g"]
                tt = sum(sum(r["tgt"] for r in rows[(tm, pw)]) for pw in prev) / TRAIL
                tc = sum(sum(r["ra"] for r in rows[(tm, pw)]) for pw in prev) / TRAIL
                tp = sum(sum(r["pa"] for r in rows[(tm, pw)]) for pw in prev) / TRAIL
                if tt < 15 or tc < 10: continue
                absent = []
                for key, v in trail.items():
                    if key in cur: continue
                    if any(tm2 != tm and wk2 > wk and any(r["seen"] == key for r in lst) for (tm2, wk2), lst in rows.items()): continue
                    absent.append((key, v))
                if any(v["pos"] == "QB" and v["pa"] / max(1, tp) >= 0.6 for k, v in absent): continue
                sk = [(k, v) for k, v in absent if v["pos"] in POS and (v["tgt"] / tt >= TGT_SHARE_MIN or v["ra"] / tc >= CAR_SHARE_MIN)]
                if len(sk) != 1: continue
                key, va = sk[0]
                lead = va["tgt"] >= max(v["tgt"] for v in trail.values())
                rule = POOL[va["pos"]]["lead" if lead else "sec"]
                healthy = [(k, v) for k, v in trail.items() if v["pos"] in POS and k in cur]
                ppr = lambda v: v["rec"] + 0.1 * (v["rcy"] + v["ry"]) + 6 * (v["rctd"] + v["rtd"])
                same = sorted([kv for kv in healthy if kv[1]["pos"] == va["pos"]], key=lambda kv: -ppr(kv[1]))
                gT, gC = defaultdict(float), defaultdict(float)
                for j, (k, v) in enumerate(same):
                    if j < len(rule["tgtSame"]): gT[k] += va["tgt"] * rule["tgtSame"][j]
                    if j < len(rule["carSame"]): gC[k] += va["ra"] * rule["carSame"][j]
                if rule["tgtOther"] > 0:
                    oth = [kv for kv in healthy if kv[1]["pos"] != va["pos"] and kv[1]["pos"] != "RB"]; tot = sum(v["tgt"] for _, v in oth)
                    if tot > 0:
                        for k, v in oth: gT[k] += va["tgt"] * rule["tgtOther"] * v["tgt"] / tot
                for k, v in healthy:
                    if not (gT[k] or gC[k]): continue
                    rp = v["rec"] + 0.1 * v["rcy"] + 6 * v["rctd"]; cp = 0.1 * v["ry"] + 6 * v["rtd"]
                    ppt = rp / v["tgt"] if v["tgt"] > 0 else 0; ppc = cp / v["ra"] if v["ra"] > 0 else 0
                    gained = gT[k] * ppt * EFF_T + gC[k] * ppc * EFF_C; own = ppr(v)
                    f = 1 + gained / max(own, FLOOR) if own > 0 and gained > 0 else 1.0
                    add = {"ry": gC[k] * (v["ry"] / v["ra"] if v["ra"] > 0 else 0) * EFF_C,
                           "rec": gT[k] * (v["rec"] / v["tgt"] if v["tgt"] > 0 else 0) * EFF_T,
                           "rcy": gT[k] * (v["rcy"] / v["tgt"] if v["tgt"] > 0 else 0) * EFF_T}
                    out.append({"Y": Y, "apos": va["pos"], "pos": v["pos"], "same": v["pos"] == va["pos"], "f": f, "n": v["n"], "absent": va["n"], "tm": tm, "wk": wk,
                                "base": {s: v[s] for s in STATS}, "add": add, "act": {s: cur[k][s] for s in STATS}})
    return out


def main():
    P("=== Vacated volume by stat: uniform factor (engine today) vs carries -> rush yds, targets -> rec / rec yds ===")
    E = events(); P(f"  absorber rows: {len(E)} over {len(set((e['Y'], e['tm'], e['wk']) for e in E))} one-absence team-weeks 2019-25")
    Y = np.array([e["Y"] for e in E]); RES = {"n": len(E), "cuts": {}}
    MINB = {"ry": 15.0, "rec": 1.5, "rcy": 15.0}
    def table(lbl, mask):
        P(f"\n--- {lbl} ---"); RES["cuts"][lbl] = {}
        for s in STATS:
            base = np.array([e["base"][s] for e in E]); add = np.array([e["add"][s] for e in E]); act = np.array([e["act"][s] for e in E]); f = np.array([e["f"] for e in E])
            m = mask & ((base >= MINB[s]) | (base + add >= MINB[s]))
            if m.sum() < 40: continue
            preds = {"none": base, "uniform": base * f, "by-stat": base + add}
            # k chosen leave-one-season-out on MSE
            loyo = np.full(len(E), np.nan); ks = []
            for yy in sorted(set(Y[m])):
                tr = m & (Y != yy); te = m & (Y == yy)
                kb = min(KG, key=lambda k: np.mean((base[tr] + k * add[tr] - act[tr]) ** 2)); ks.append(kb); loyo[te] = base[te] + kb * add[te]
            preds["by-stat, k LOYO"] = loyo
            u = np.mean((preds["uniform"][m] - act[m]) ** 2); row = {}
            P(f"  {s:3s} n {int(m.sum()):5d}  actual {act[m].mean():6.2f}  | " + "  ".join(f"{nm}: mean {p[m].mean():6.2f} MSE {np.mean((p[m]-act[m])**2):8.2f} ({100*(np.mean((p[m]-act[m])**2)/u-1):+5.1f}% vs uniform, won {sum(1 for yy in set(Y[m]) if np.mean((p[m&(Y==yy)]-act[m&(Y==yy)])**2) < np.mean((preds['uniform'][m&(Y==yy)]-act[m&(Y==yy)])**2))}/{len(set(Y[m]))})" for nm, p in preds.items() if nm != "uniform") + f"  | uniform mean {preds['uniform'][m].mean():6.2f} MSE {u:8.2f} | k picks {ks}")
            for nm, p in preds.items(): row[nm] = {"mean": round(float(p[m].mean()), 2), "mse_vs_uniform": round(100 * (np.mean((p[m] - act[m]) ** 2) / u - 1), 2)}
            row["actual"] = round(float(act[m].mean()), 2); row["n"] = int(m.sum()); row["k"] = ks; RES["cuts"][lbl][s] = row
    allm = np.ones(len(E), bool); apos = np.array([e["apos"] for e in E]); same = np.array([e["same"] for e in E]); pos = np.array([e["pos"] for e in E]); f = np.array([e["f"] for e in E])
    table("ALL absorbers", allm)
    table("RB out -> other RBs (the Jones / Mason case)", (apos == "RB") & same)
    table("RB out -> next RB only, boost >= x1.10", (apos == "RB") & same & (f >= 1.10))
    table("WR out -> WRs", (apos == "WR") & same)
    table("TE out -> TEs", (apos == "TE") & same)
    table("other-position absorbers (WR/TE when an RB or TE is out)", ~same)
    table("big boosts only (f >= 1.15)", f >= 1.15)
    # the cross-stat leak: RBs absorbing CARRIES - does their receiving line really rise like uniform says?
    m = (apos == "RB") & same & (f >= 1.05)
    if m.sum() > 40:
        for s in ("rec", "rcy"):
            base = np.array([e["base"][s] for e in E])[m]; act = np.array([e["act"][s] for e in E])[m]; ff = f[m]; add = np.array([e["add"][s] for e in E])[m]
            P(f"\n  leak check RB-out -> RB {s}: trailing {base.mean():.2f}  uniform says {np.mean(base*ff):.2f}  by-stat says {np.mean(base+add):.2f}  ACTUAL {act.mean():.2f}  (n {int(m.sum())})")
    json.dump(RES, open(os.path.join(HERE, "data", "vacated_mix_bt.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
