#!/usr/bin/env python3
"""
THREE HAND-LAYER FIXES (2026-09-16). Jack: "yes test those three layer fixes" - candidates from the learned-shadow
audit (tune_learned_shadow.py): big opportunity-pool boosts ran 0.887 of the hand number, Questionable + no practice
players who played ran 0.836, strong-wind games 0.955.

Rows / HAND = build_learned_shadow.load() (17,657 player-weeks 2019-25, live stack rebuilt with engine constants).
  1 POOL      cap:    f -> min(f, C), C in none / 1.50 / 1.35 / 1.25 / 1.20 / 1.15
              shrink: f -> 1 + s (f - 1), s in 1 / .85 / .7 / .55 / .4
  2 Q + DNP   cond x m for the Q-DNP class (live cond QB .891 RB .877 WR .884 TE .891), m in 1 / .95 / .90 / .85 / .80 / .75
              (+ the same for Q-LP as a check, m in 1 / .97 / .94 / .91)
  3 WIND      wind dock ^ e (e 1 = live: >=15 QB .94 WR .93 TE .95, 10-15 .97/.97/.98), e in 1 / 1.5 / 2 / 2.5 / 3;
              and >=15 only
  ALL         the three picked together
Graded vs HAND: LOYO (strength picked on the other six seasons) and FORWARD 2021-25 (picked on earlier seasons),
all rows and flagged rows (rows the fix touches). Ship bar: <= -0.3% overall with >= 5/7, or a rare-flag effect
(flagged rows <= -1% with >= 5/7 and forward better). Log layer_fixes_backtest.log; data/layer_fixes_backtest.js
(SIM_LAYERFIX_BT), ZONES tab.
"""
import json, os, sys, time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
LOG = open(os.path.join(HERE, "layer_fixes_backtest.log"), "w", encoding="utf-8")


class _Tee:
    def __init__(self, a, b): self.a, self.b = a, b
    def write(self, t): self.a.write(t); self.b.write(t); self.a.flush(); self.b.flush()
    def flush(self): self.a.flush(); self.b.flush()


import build_learned_shadow as BL
sys.stdout = _Tee(sys.stdout, LOG)
def P(*a): print(" ".join(str(x) for x in a))

YEARS = list(range(2019, 2026))
RES = {"tests": []}


def mse(a, b):
    return float(np.mean((np.asarray(a, dtype=float) - np.asarray(b, dtype=float)) ** 2))


def hand(df, pool=None, cond=None, wind=None):
    d = df
    th = BL.HAND_TH
    pm = d.pool_mult.values if pool is None else pool
    cm = d.cond_mult.values if cond is None else cond
    wm = d.weather_mult.values if wind is None else wind
    b1 = d.blend.values * d.rookie_mult.values
    u = d.usage_half.values
    b1 = np.where(np.isfinite(u), 0.85 * b1 + 0.15 * np.nan_to_num(u), b1)
    chain = d.veg.values * d.fpa_mult.values * d.snapmult.values * wm * cm * pm * d.qb_inherit_mult.values
    return b1 * chain + d.td_luck_adj.values


def grade(df, label, family, grid, predfn, flag):
    act = df.act.values; yr = df.year.values; H = df.HAND.values
    per = {v: predfn(v) for v in grid}
    def err(pred, m):
        return mse(pred[m], act[m])
    out = {"label": label, "family": family, "grid": [str(g) for g in grid], "nFlag": int(flag.sum())}
    # pooled grid (all seasons) for reference
    out["pooled"] = {str(v): round((err(per[v], np.ones(len(df), bool)) / err(H, np.ones(len(df), bool)) - 1) * 100, 3) for v in grid}
    out["pooledFlag"] = {str(v): round((err(per[v], flag) / err(H, flag) - 1) * 100, 3) for v in grid} if flag.sum() else {}
    for mode in ("loyo", "fwd"):
        years = YEARS if mode == "loyo" else list(range(2021, 2026))
        pred = np.full(len(df), np.nan); picks = []
        for T in years:
            tr = (yr != T) if mode == "loyo" else (yr < T)
            best = min(grid, key=lambda v: err(per[v], tr))
            picks.append(str(best))
            te = yr == T
            pred[te] = per[best][te]
        mm = np.isin(yr, years)
        for scope, m in (("all", mm), ("flag", mm & flag)):
            if m.sum() == 0:
                continue
            e, h = err(pred, m), err(H, m)
            wins = sum(err(pred, m & (yr == y)) < err(H, m & (yr == y)) for y in years if (m & (yr == y)).sum())
            out[f"{mode}_{scope}"] = round((e / h - 1) * 100, 3)
            out[f"{mode}_{scope}_wins"] = int(wins)
        out[f"{mode}_picks"] = picks
        out[f"{mode}_years"] = len(years)
    la, lw, fa = out["loyo_all"], out["loyo_all_wins"], out["fwd_all"]
    lf, lfw, ff = out.get("loyo_flag", 0), out.get("loyo_flag_wins", 0), out.get("fwd_flag", 0)
    out["verdict"] = ("PASS" if (la <= -0.3 and lw >= 5 and fa < 0) else
                      ("PASS (rare flag)" if (lf <= -1.0 and lfw >= 5 and ff < 0 and la <= 0) else
                       ("lean" if (lf < 0 and ff < 0 and la <= 0) else "FAIL")))
    RES["tests"].append(out)
    P(f"  {label}")
    P("    pooled grid all rows: " + "  ".join(f"{k}:{v:+.3f}%" for k, v in out["pooled"].items()))
    if out["pooledFlag"]:
        P("    pooled grid flagged : " + "  ".join(f"{k}:{v:+.2f}%" for k, v in out["pooledFlag"].items()))
    P(f"    LOYO all {la:+.3f}% ({lw}/7) flagged {lf:+.2f}% ({lfw}/7) picks {out['loyo_picks']} | FORWARD all {fa:+.3f}% flagged {ff:+.2f}% ({out.get('fwd_flag_wins', 0)}/5) picks {out['fwd_picks']} -> {out['verdict']}")
    return out


def main():
    t0 = time.time()
    df, _ = BL.load()
    H = df.HAND.values
    P(f"{len(df)} player-weeks; HAND MSE {mse(H, df.act):.3f}; check rebuild {mse(hand(df), df.act):.3f}")
    pos = df.pos.values
    # ---- 1 pool ----
    P("\n=== 1. opportunity pool ===")
    pf = df.pool_mult.values; pflag = pf > 1
    for lo, hi in ((1, 1.05), (1.05, 1.15), (1.15, 1.35), (1.35, 99)):
        m = (pf > lo) & (pf <= hi)
        P(f"  pool {lo}-{hi}: n {m.sum()} actual/HAND {df.act[m].mean() / H[m].mean():.3f}")
    caps = [99.0, 1.5, 1.35, 1.25, 1.2, 1.15]
    grade(df, "pool cap (max multiplier)", "pool", caps, lambda C: hand(df, pool=np.minimum(pf, C)), pflag)
    grade(df, "pool shrink (1 + s x boost)", "pool", [1.0, 0.85, 0.7, 0.55, 0.4], lambda s: hand(df, pool=1 + s * (pf - 1)), pflag)
    grade(df, "pool cap, big boosts only flagged (>1.35)", "pool", caps, lambda C: hand(df, pool=np.minimum(pf, C)), pf > 1.35)
    # ---- 2 Q + DNP ----
    P("\n=== 2. Questionable + did not practice (played) ===")
    cls = df.banged_cls.values; cm = df.cond_mult.values
    for c in ("Q-DNP", "Q-LP", "Q-FP"):
        m = cls == c
        P(f"  {c}: n {m.sum()} actual/HAND {df.act[m].mean() / H[m].mean():.3f}" + " | " + " ".join(f"{p} {df.act[m & (pos == p)].mean() / H[m & (pos == p)].mean():.3f} (n {int((m & (pos == p)).sum())})" for p in ("QB", "RB", "WR", "TE") if (m & (pos == p)).sum() >= 10))
    dnp = cls == "Q-DNP"
    grade(df, "Q-DNP extra dock (cond x m)", "q-dnp", [1.0, 0.95, 0.9, 0.85, 0.8, 0.75], lambda m_: hand(df, cond=np.where(dnp, cm * m_, cm)), dnp)
    lp = cls == "Q-LP"
    grade(df, "Q-LP extra dock (check)", "q-lp", [1.0, 0.97, 0.94, 0.91], lambda m_: hand(df, cond=np.where(lp, cm * m_, cm)), lp)
    # ---- 3 wind ----
    P("\n=== 3. wind ===")
    wm = df.weather_mult.values; wflag = wm < 1; strong = (df.wind.values >= 15) & wflag
    for lab, m in (("wind 10-15 docked", wflag & ~strong), ("wind 15+ docked", strong)):
        P(f"  {lab}: n {m.sum()} actual/HAND {df.act[m].mean() / H[m].mean():.3f} | " + " ".join(f"{p} {df.act[m & (pos == p)].mean() / H[m & (pos == p)].mean():.3f} (n {int((m & (pos == p)).sum())})" for p in ("QB", "WR", "TE") if (m & (pos == p)).sum() >= 10))
    grade(df, "wind dock strength (mult ^ e)", "wind", [1.0, 1.5, 2.0, 2.5, 3.0], lambda e: hand(df, wind=wm ** e), wflag)
    grade(df, "wind 15+ only (mult ^ e)", "wind", [1.0, 1.5, 2.0, 2.5, 3.0], lambda e: hand(df, wind=np.where(strong, wm ** e, wm)), strong)
    # ---- all three ----
    P("\n=== ALL three together (each at its pooled-best grid value from above; LOYO / forward re-pick jointly over a small grid) ===")
    combos = [(C, m_, e) for C in (99.0, 1.35, 1.25) for m_ in (1.0, 0.9, 0.8) for e in (1.0, 2.0)]
    grade(df, "pool cap x Q-DNP dock x wind exponent", "all", combos,
          lambda v: hand(df, pool=np.minimum(pf, v[0]), cond=np.where(dnp, cm * v[1], cm), wind=wm ** v[2]), pflag | dnp | wflag)
    RES["updated"] = time.strftime("%Y-%m-%d %H:%M"); RES["n"] = int(len(df))
    passed = [t for t in RES["tests"] if t["verdict"].startswith("PASS")]
    RES["summary"] = ("Hand-layer fixes vs the rebuilt live stack: " + "; ".join(f"{t['label']} LOYO {t['loyo_all']:+.2f}% ({t['loyo_all_wins']}/7), flagged {t.get('loyo_flag', 0):+.2f}%, forward {t['fwd_all']:+.2f}% -> {t['verdict']}" for t in RES["tests"]))
    with open(os.path.join(HERE, "data", "layer_fixes_backtest.js"), "w", encoding="utf-8") as fh:
        fh.write("// built by backtest_layer_fixes.py - pool cap / Q+DNP dock / wind strength vs the rebuilt live stack; ZONES tab\n")
        fh.write("window.SIM_LAYERFIX_BT = "); json.dump(RES, fh, separators=(",", ":"), default=str); fh.write(";\n")
    P(f"\npassing: {', '.join(t['label'] for t in passed) if passed else 'none'}")
    P(f"done ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
