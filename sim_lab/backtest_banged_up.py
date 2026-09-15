#!/usr/bin/env python3
"""
BANGED-UP layer backtest (2026-09-15).

Jack: "injuries (banged up playing or missing actual time) how that impacts teammates and
player performance" -> "start on the banged up layer next".

The engine already docks designated players (applyInSeasonInjuries, 2026-09-09, set by
judgment, never backtested): Doubtful x0.5, Questionable + DNP on the latest practice x0.75
(no prop anchor), Questionable + Limited/Full = no change. This study sizes those rules and
asks what they miss, from nflverse injuries_<yr>.parquet (final report status + latest
practice participation + injury) and snap_counts_<yr>.parquet, 2019-2025.

  class      healthy (not on report, or Full practice with no designation), none-LP / none-DNP
             (practiced limited / not at all, no game designation), Q-FP / Q-LP / Q-DNP, D
  relevant   offense_pct average >= .40 over the player's prior games that season (>= 2)
  PLAY       P(played | class, position) for relevant players (offense_snaps > 0)
  SNAPS      game-day offense_pct / prior-3-game average when they play, vs healthy players
  COND       conditional on playing, actual / shipped on bt_common's base (P=5 blend x Vegas
             x FPA; the base has no injury layer), REL = class ratio / healthy ratio within the
             same position and week band (2-8 / 9-13 / 14-18); LOYO flagged multipliers
  IMPLIED    unconditional expected-value multiplier = P(play) x REL, next to the shipped dock
  TEAMMATES  healthy player whose same-group teammate (RB-RB, WR/TE-WR/TE) played banged up
             (Q-DNP / Q-LP / D), and pass catchers / RBs whose QB played banged up; rows with a
             same-group teammate who SAT are excluded (that is the shipped opportunity pool)

Ship bar (README): LOYO MSE <= -0.3% with >= 5/7 years better, or a flagged-row effect on a
rare flag. Log banged_up_backtest.log; results -> data/banged_up_backtest.js (SIM_BANGED_BT).
"""
import json, os, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B
from bt_common import iter_samples, to_arrays, POS4
from backtest_target_area import mse

LOG = open(os.path.join(HERE, "banged_up_backtest.log"), "w", encoding="utf-8")


class _Tee:
    def __init__(self, a, b): self.a, self.b = a, b
    def write(self, t): self.a.write(t); self.b.write(t); self.a.flush(); self.b.flush()
    def flush(self): self.a.flush(); self.b.flush()


sys.stdout = _Tee(sys.stdout, LOG)
def P(*a): print(" ".join(str(x) for x in a))

YEARS = list(range(2019, 2026))
SOFT = {"hamstring", "groin", "calf", "quadricep", "quad", "thigh", "hip flexor"}
CLASSES = ["none-LP", "none-DNP", "Q-FP", "Q-LP", "Q-DNP", "D"]
BANGED = ("Q-DNP", "Q-LP", "D")
SHIPPED_DOCK = {"Q-DNP": 0.75, "D": 0.50}
SHIP_PCT, SHIP_WINS = -0.30, 5
RES = {"loyo": [], "buckets": [], "play": [], "snaps": [], "implied": [], "n": 0}


def loyo2(S, years, grid, predfn, label, family, pos):
    act = S["act"]; per = {}
    ys = [y for y in years if (S["year"] == y).any()]
    for v in grid:
        pred = predfn(v)
        per[v] = {y: mse(pred[S["year"] == y], act[S["year"] == y]) for y in ys}
    ship = per[grid[0]]; tot = n = wins = 0; picks = []
    for y in ys:
        m = S["year"] == y
        best = min(grid, key=lambda v: sum(per[v][yy] for yy in ys if yy != y))
        picks.append(best); e = mse(predfn(best)[m], act[m])
        tot += e * m.sum(); n += m.sum(); wins += e < ship[y]
    pooled_best = min(grid, key=lambda v: sum(per[v].values()))
    base_mse = sum(ship[y] * (S["year"] == y).sum() for y in ys) / n
    pct = (tot / n / base_mse - 1) * 100
    P(f"  {label}")
    P("    grid pooled MSE: " + "  ".join(f"{v:+.2f}:{sum(per[v].values())/len(ys):.3f}" for v in grid))
    P(f"    pooled best {pooled_best:+.2f} | LOYO MSE {tot/n:.4f} vs shipped {base_mse:.4f} ({pct:+.2f}%), years better {wins}/{len(ys)}, picks {picks}")
    RES["loyo"].append({"label": label, "family": family, "pos": pos, "n": int(n), "best": float(pooled_best), "pct": round(pct, 3),
                        "wins": int(wins), "years": len(ys), "picks": [float(p) for p in picks],
                        "verdict": "PASS" if (pct <= SHIP_PCT and wins >= SHIP_WINS) else ("lean" if (pct <= -0.1 and wins >= 4) else "FAIL")})


def prac_code(s):
    s = str(s or "")
    if s.startswith("Did Not"): return "DNP"
    if s.startswith("Limited"): return "LP"
    if s.startswith("Full"): return "FP"
    return ""


def class_of(rs, pr):
    rs = str(rs or "")
    if rs == "Doubtful": return "D"
    if rs == "Out": return "Out"
    if rs == "Questionable": return {"DNP": "Q-DNP", "LP": "Q-LP"}.get(pr, "Q-FP")
    if pr == "DNP": return "none-DNP"
    if pr == "LP": return "none-LP"
    return "healthy"


def load_injuries(Y):
    d = pd.read_parquet(os.path.join(B.CACHE, f"injuries_{Y}.parquet"),
                        columns=["game_type", "team", "week", "gsis_id", "position", "full_name", "report_status", "practice_status", "report_primary_injury", "practice_primary_injury"])
    d = d[(d.game_type == "REG") & d.position.isin(POS4)].drop_duplicates(["team", "week", "gsis_id"])
    by_gsis, by_name, by_tw = {}, {}, defaultdict(list)
    for r in d.itertuples(index=False):
        inj = str(r.report_primary_injury if isinstance(r.report_primary_injury, str) else (r.practice_primary_injury or "")).lower()
        rec = {"norm": B.cal.norm(str(r.full_name)), "tm": B.tm(str(r.team)), "wk": int(r.week), "pos": r.position,
               "cls": class_of(r.report_status, prac_code(r.practice_status)), "soft": inj in SOFT, "inj": inj}
        if isinstance(r.gsis_id, str):
            by_gsis[(r.gsis_id, rec["wk"])] = rec
        by_name[(rec["norm"], rec["tm"], rec["wk"])] = rec
        by_tw[(rec["tm"], rec["wk"])].append(rec)
    return by_gsis, by_name, by_tw


def load_snaps(Y):
    d = pd.read_parquet(os.path.join(B.CACHE, f"snap_counts_{Y}.parquet"),
                        columns=["week", "game_type", "player", "position", "team", "offense_snaps", "offense_pct"])
    d = d[(d.game_type == "REG") & d.position.isin(POS4) & (d.offense_snaps > 0)]
    pct, hist = {}, defaultdict(list)
    for r in d.itertuples(index=False):
        k = (B.cal.norm(str(r.player)), B.tm(str(r.team)))
        pct[(k[0], k[1], int(r.week))] = float(r.offense_pct)
        hist[k].append((int(r.week), float(r.offense_pct)))
    for k in hist:
        hist[k].sort()
    return pct, hist


def prior(hist, norm, tm_, W, last=None):
    rows = [p for w, p in hist.get((norm, tm_), ()) if w < W]
    if last:
        rows = rows[-last:]
    return float(np.mean(rows)) if rows else None, len(rows)


def main():
    P("loading nflverse injury reports + snap counts 2019-2025...")
    INJ, SNP = {}, {}
    for Y in YEARS:
        INJ[Y] = load_injuries(Y); SNP[Y] = load_snaps(Y)
        P(f"  {Y}: {len(INJ[Y][1])} skill player-weeks on the report, {len(SNP[Y][0])} skill player-weeks with snaps")

    # ---------------- PLAY + SNAPS (relevant players only) ----------------
    play = defaultdict(lambda: [0, 0])     # (pos, cls) -> [played, n]
    snapr = defaultdict(list)              # (pos, cls) -> game-day / prior-3 share
    for Y in YEARS:
        _, by_name, _ = INJ[Y]; pct, hist = SNP[Y]
        for (norm, tm_, W), rec in by_name.items():
            if rec["cls"] == "healthy":
                continue
            avg, n = prior(hist, norm, tm_, W)
            if n < 2 or avg < 0.40:
                continue
            played = (norm, tm_, W) in pct
            play[(rec["pos"], rec["cls"])][0] += played; play[(rec["pos"], rec["cls"])][1] += 1
            play[("ALL", rec["cls"])][0] += played; play[("ALL", rec["cls"])][1] += 1
            if played:
                p3, n3 = prior(hist, norm, tm_, W, 3)
                if p3:
                    snapr[(rec["pos"], rec["cls"])].append(pct[(norm, tm_, W)] / p3)
                    snapr[("ALL", rec["cls"])].append(pct[(norm, tm_, W)] / p3)
        for (norm, tm_), rows in hist.items():              # healthy baseline
            for i, (W, pc) in enumerate(rows):
                if i < 2 or (norm, tm_, W) in by_name:
                    continue
                prev = [p for _, p in rows[:i]]
                if np.mean(prev) < 0.40:
                    continue
                p3 = np.mean(prev[-3:])
                pos = None
                snapr[("ALL", "healthy")].append(pc / p3)
    P("\n=== PLAY RATE for relevant players (prior avg offense share >= 40%), by class ===")
    for cls in CLASSES + ["Out"]:
        parts = []
        for pos in ("ALL",) + POS4:
            pl, n = play[(pos, cls)]
            if n:
                parts.append(f"{pos} {pl / n:.2f} (n {n})")
                RES["play"].append({"pos": pos, "cls": cls, "n": n, "rate": round(pl / n, 3)})
        P(f"  {cls:9s} " + " | ".join(parts))
    P("\n=== SNAP SHARE when they play: game-day / prior-3-game average ===")
    base = float(np.mean(snapr[("ALL", "healthy")])) if snapr[("ALL", "healthy")] else None
    P(f"  healthy baseline {base:.3f} (n {len(snapr[('ALL', 'healthy')])})")
    for cls in CLASSES:
        parts = []
        for pos in ("ALL",) + POS4:
            v = snapr[(pos, cls)]
            if len(v) >= 20:
                parts.append(f"{pos} {np.mean(v):.3f} (n {len(v)})")
                RES["snaps"].append({"pos": pos, "cls": cls, "n": len(v), "ratio": round(float(np.mean(v)), 3), "rel": round(float(np.mean(v)) / base, 3)})
        P(f"  {cls:9s} " + " | ".join(parts))

    # ---------------- COND: bt_common samples (played weeks) ----------------
    P("\nloading base samples (bt_common)...")
    S = iter_samples(POS4)
    A = to_arrays(S); n = len(S)
    act, ship = A["act"], A["shipped"]
    cls = np.array(["healthy"] * n, dtype=object); soft = np.zeros(n, dtype=bool)
    tm_bang = np.zeros(n); tm_qb_bang = np.zeros(n); vac = np.zeros(n)
    GRP = {"RB": "RB", "WR": "PC", "TE": "PC", "QB": "QB"}
    for i, s in enumerate(S):
        Y, W = s["year"], s["wk"]
        by_gsis, by_name, by_tw = INJ[Y]; pct, hist = SNP[Y]
        own = B.cal.norm(s["name"])
        rec = by_gsis.get((s["pid"], W)) if s["pid"] else None
        rec = rec or by_name.get((own, s["team"], W))
        if rec:
            cls[i] = rec["cls"]; soft[i] = rec["soft"]
        for t in by_tw.get((s["team"], W), ()):
            if t["norm"] == own or t["cls"] == "healthy":
                continue
            avg, k = prior(hist, t["norm"], t["tm"], W)
            if k < 2 or avg < 0.40:
                continue
            played = (t["norm"], t["tm"], W) in pct
            same = GRP.get(t["pos"]) == GRP.get(s["pos"])
            if same and not played:
                vac[i] += 1
            elif same and played and t["cls"] in BANGED:
                tm_bang[i] += 1
            if t["pos"] == "QB" and s["pos"] != "QB" and played and t["cls"] in BANGED:
                tm_qb_bang[i] = 1
    wk = A["wk"]; band = np.where(wk <= 8, 0, np.where(wk <= 13, 1, 2))
    healthy = cls == "healthy"
    P(f"  {n} played player-weeks; class counts: " + ", ".join(f"{c} {int((cls == c).sum())}" for c in ["healthy"] + CLASSES))

    def ratio(m):
        return float(act[m].sum() / ship[m].sum()) if m.sum() else None

    def rel(mask, pm, ref):
        num = nf = 0.0
        for b in (0, 1, 2):
            fm = pm & (band == b) & mask; um = pm & (band == b) & ref
            if fm.sum() < 8 or um.sum() < 50:
                continue
            num += fm.sum() * ratio(fm) / ratio(um); nf += fm.sum()
        return num / nf if nf else None

    def bucket(name, pos, mask, ref=None, extra=None):
        pm = np.ones(n, dtype=bool) if pos == "ALL" else (A["pos"] == pos)
        ref = healthy if ref is None else ref
        mm = mask & pm
        r, rl = ratio(mm), rel(mask, pm, ref)
        P(f"  {pos:4s} {name:52s} n {int(mm.sum()):5d}  act/ship {'-' if r is None else f'{r:.3f}'}  REL {'-' if rl is None else f'{rl:.3f}'}")
        rec = {"pos": pos, "name": name, "n": int(mm.sum()), "ratio": None if r is None else round(r, 3), "rel": None if rl is None else round(rl, 3)}
        if extra: rec.update(extra)
        RES["buckets"].append(rec)
        return rl

    P("\n=== COND: actual / shipped when the player PLAYS, by class (REL vs healthy, same pos + week band) ===")
    relc = {}
    for c in CLASSES:
        for pos in ("ALL",) + POS4:
            v = bucket(f"{c}", pos, cls == c)
            relc[(pos, c)] = v
    P("\n  injury type (soft tissue = hamstring / groin / calf / quad / thigh / hip flexor):")
    for c in ("Q-LP", "Q-DNP", "D"):
        bucket(f"{c} soft tissue", "ALL", (cls == c) & soft)
        bucket(f"{c} other injury", "ALL", (cls == c) & ~soft)

    P("\n=== IMPLIED unconditional multiplier = P(play) x conditional REL (vs the shipped dock) ===")
    for c in CLASSES:
        for pos in ("ALL",) + POS4:
            pr = next((x["rate"] for x in RES["play"] if x["pos"] == pos and x["cls"] == c), None)
            rl = relc.get((pos, c))
            if pr is None or rl is None:
                continue
            ev = pr * rl
            P(f"  {c:9s} {pos:4s} P(play) {pr:.2f} x REL {rl:.3f} = {ev:.3f}   shipped {SHIPPED_DOCK.get(c, 1.0):.2f}")
            RES["implied"].append({"cls": c, "pos": pos, "play": pr, "rel": round(rl, 3), "ev": round(ev, 3), "shipped": SHIPPED_DOCK.get(c, 1.0)})

    years = YEARS
    P("\n=== LOYO conditional flagged multipliers (played weeks; shipped x m on the class rows) ===")
    grid = [1.0, 0.97, 0.94, 0.91, 0.88, 0.85, 1.03]
    for c in ("Q-FP", "Q-LP", "Q-DNP", "D", "none-LP", "none-DNP"):
        for pos in ("ALL",) + POS4:
            pm = np.ones(n, dtype=bool) if pos == "ALL" else (A["pos"] == pos)
            mk = (cls == c)[pm]
            if mk.sum() < 60:
                continue
            Ssub = {"year": A["year"][pm], "act": act[pm]}; sp = ship[pm]
            loyo2(Ssub, years, grid, lambda m, mk=mk, sp=sp: np.where(mk, sp * m, sp), f"{c} {pos} (flagged n={int(mk.sum())})", "class rows x m (played)", f"{pos} {c}")
    for c in ("Q-LP", "Q-DNP"):
        mk_all = (cls == c) & soft
        if mk_all.sum() >= 60:
            loyo2({"year": A["year"], "act": act}, years, grid, lambda m, mk=mk_all: np.where(mk, ship * m, ship), f"{c} soft tissue ALL (flagged n={int(mk_all.sum())})", "class rows x m (played)", f"ALL {c} soft")

    P("\n=== TEAMMATES of banged-up players who played (own player healthy; rows with a same-group teammate who SAT excluded) ===")
    clean = healthy & (vac == 0)
    tgrid = [1.0, 1.02, 1.04, 1.06, 0.98, 0.96]
    for pos in ("RB", "WR", "TE"):
        pm = A["pos"] == pos
        bucket("same-group teammate played banged up", pos, clean & (tm_bang >= 1), ref=clean & (tm_bang == 0) & (tm_qb_bang == 0))
        bucket("QB played banged up", pos, clean & (tm_qb_bang >= 1), ref=clean & (tm_bang == 0) & (tm_qb_bang == 0))
        for lab, mask in (("same-group teammate played banged up", clean & (tm_bang >= 1)), ("QB played banged up", clean & (tm_qb_bang >= 1))):
            mk = mask[pm]
            if mk.sum() < 60:
                P(f"  {pos} {lab}: too few rows ({int(mk.sum())})"); continue
            Ssub = {"year": A["year"][pm], "act": act[pm]}; sp = ship[pm]
            loyo2(Ssub, years, tgrid, lambda m, mk=mk, sp=sp: np.where(mk, sp * m, sp), f"{pos} {lab} (flagged n={int(mk.sum())})", "teammate rows x m", f"{pos} {lab}")

    RES["n"] = int(n); RES["years"] = years; RES["updated"] = time.strftime("%Y-%m-%d %H:%M")
    RES["bar"] = {"pct": SHIP_PCT, "wins": SHIP_WINS}
    passed = [r for r in RES["loyo"] if r["verdict"] == "PASS"]
    RES["summary"] = (f"Banged up: {len(RES['loyo'])} LOYO tests on {n} played player-weeks 2019-25; " +
                      (f"{len(passed)} pass: " + "; ".join(f"{r['pos']} x{r['best']:.2f} {r['pct']:+.2f}% ({r['wins']}/7)" for r in passed) if passed else "none pass the ship bar"))
    with open(os.path.join(HERE, "data", "banged_up_backtest.js"), "w", encoding="utf-8") as fh:
        fh.write("// built by backtest_banged_up.py - injury designation x practice: play rates, snap share, conditional + implied docks, teammates; shown on the ZONES tab\n")
        fh.write("window.SIM_BANGED_BT = "); json.dump(RES, fh, separators=(",", ":")); fh.write(";\n")
    P(f"\nwrote data/banged_up_backtest.js: {RES['summary']}")
    P("done")


if __name__ == "__main__":
    main()
