#!/usr/bin/env python3
"""
VACATED VOLUME x DEPTH CHART AT THE START OF THE SEASON -> a bump for the season prior (2026-09-16).

Jack: "can we try to add a vacated volume / depth chart check at the beginning of seasons to try and give players a
bump." The top-60 archetype analysis said every season-long miss vs Clay is a player whose ROLE grew (committee
dissolved, first-round rookie RB, elite QB/TE compressed) and our prior only sees last year's box score + log ADP.
Per player-season 2019-25 (pbp via backtest_opp_prior.load_season): the team's vacated target share (WR/TE) or carry
share (RB) = Y-1 shares of players no longer on the team; whether the Y-1 leader at his position left; his Y-1 share
rank on the team; the week-1 depth string (harness). Tests, all LOYO per position then forward 2021-25, graded on
Jack's tiers (top 60 / 61-100 / 101-150 / top 150) vs Clay and vs the v2.15 shadow prior:
  A. ridge LIVE + vacated features (vac, str1 x vac, leader-left, promotion, rookie str1 x vac)
  B. BUMP RULE on the shadow prior: prior x (1 + k x str1 x vac)  and  prior x (1 + k x promo), k per position LOYO
Log vacated_bump.log; results -> data/vacated_bump.js (SIM_VACBUMP_BT).
"""
import json, os, sys, time, warnings
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import backtest_season_long as SL
import backtest_opp_prior as OP
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "vacated_bump.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
OP.P = P
YEARS, POS4 = NW.YEARS, NW.POS4
LIVE = [f for f in SL.BASIC if f != "mover"]
VAC = ["vac", "str1_vac", "leader_left", "promo", "rk_str1_vac"]
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "ridge": [], "bump": [], "forward": [], "risers": []}
TIERS = (("top 60", lambda T: (T.adp <= 60).values), ("ADP 61-100", lambda T: ((T.adp > 60) & (T.adp <= 100)).values), ("ADP 101-150", lambda T: ((T.adp > 100) & (T.adp <= 150)).values), ("top 150", lambda T: (T.adp <= 150).values), ("ALL", lambda T: np.ones(len(T), bool)))


def fmt(v, nd=2):
    return "-" if v is None or (isinstance(v, float) and np.isnan(v)) else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def add_vacated(T):
    pos_of, _, _ = OP.load_positions()
    SEAS = {Y: OP.load_season(Y, pos_of) for Y in range(YEARS[0] - 1, YEARS[-1] + 1)}
    vac = np.zeros(len(T)); ll = np.zeros(len(T)); prk = np.full(len(T), np.nan); found = 0
    for i, r in enumerate(T.itertuples(index=False)):
        Y = int(r.year); cur, prv = SEAS[Y][0], SEAS[Y - 1][0]
        q = cur.get(r.pid); t = q["tm"] if q else r.team
        if r.pos == "QB" or not t: continue
        key = "cs" if r.pos == "RB" else "ts"
        on_t = {pid for pid, z in cur.items() if z["tm"] == t}
        prev_grp = sorted([(z[key], pid) for pid, z in prv.items() if z["tm"] == t and z["pos"] == r.pos], reverse=True)
        gone = [(s, pid) for s, pid in prev_grp if pid not in on_t]
        vac[i] = sum(s for s, _ in gone); found += 1
        if prev_grp and prev_grp[0][1] not in on_t: ll[i] = 1
        for k, (s, pid) in enumerate(prev_grp, start=1):
            if pid == r.pid: prk[i] = k
    T["vac"] = vac; T["leader_left"] = ll; T["prev_rank"] = prk
    s1 = (T.strb == 1).astype(float).values
    T["str1_vac"] = s1 * vac
    T["promo"] = s1 * ((np.isnan(prk)) | (prk >= 2)).astype(float)   # string 1 now, was not the team's leader last year (or was elsewhere / rookie)
    T["rk_str1_vac"] = T.rookie.values * s1 * vac
    P(f"  vacated features on {found} of {len(T)} rows | mean vac (RB/WR/TE) {vac[(T.pos != 'QB').values].mean():.3f} | leader-left {int(ll.sum())} | promo {int(T.promo.sum())} | string-1 rows {int(s1.sum())}")
    return T


def grade(T, pred, base, clay, label, mask, store):
    m = mask & ~np.isnan(pred) & ~np.isnan(base)
    act, g, year = T.ppg.values, T.games.values.astype(float), T.year.values
    e, eb, ec = SL.wmse(pred[m], act[m], g[m]), SL.wmse(base[m], act[m], g[m]), SL.wmse(clay[m], act[m], g[m])
    ys = [y for y in YEARS if (m & (year == y)).sum() >= 12]
    wb = sum(1 for y in ys if SL.wmse(pred[m & (year == y)], act[m & (year == y)], g[m & (year == y)]) < SL.wmse(base[m & (year == y)], act[m & (year == y)], g[m & (year == y)]))
    wc = sum(1 for y in ys if SL.wmse(pred[m & (year == y)], act[m & (year == y)], g[m & (year == y)]) < SL.wmse(clay[m & (year == y)], act[m & (year == y)], g[m & (year == y)]))
    row = {"label": label, "n": int(m.sum()), "mse": round(e, 3), "vsBase": round((e / eb - 1) * 100, 2), "baseWins": int(wb), "vsClay": round((e / ec - 1) * 100, 2), "clayWins": int(wc), "years": len(ys), "baseVsClay": round((eb / ec - 1) * 100, 2)}
    P(f"  {label:46s} n={m.sum():4d} | vs shadow prior {row['vsBase']:+6.2f}% ({wb}/{len(ys)}) | vs Clay {row['vsClay']:+6.2f}% ({wc}/{len(ys)})  [shadow vs Clay {row['baseVsClay']:+.2f}%]")
    store.append(row); return row


def bump_loyo(T, sh, feat, grid, sel_mask):
    """per position, pick k on the other years (top-150 games-weighted MSE), apply to the held-out year."""
    out = sh.copy(); picks = {}
    act, g, year, pos = T.ppg.values, T.games.values.astype(float), T.year.values, T.pos.values
    f = T[feat].values
    for ps in POS4:
        picks[ps] = []
        for y in YEARS:
            tr = (pos == ps) & (year != y) & sel_mask; te = (pos == ps) & (year == y)
            best = min(grid, key=lambda k: SL.wmse(sh[tr] * (1 + k * f[tr]), act[tr], g[tr]))
            out[te] = sh[te] * (1 + best * f[te]); picks[ps].append(best)
    return out, picks


def main():
    t0 = time.time()
    P("=== Vacated volume x depth chart at the start of the season: a bump for the season prior ===")
    T = SL.build_table(); T = add_vacated(T)
    clay = T.clay.values; adp = T.adp.values; ws = T.games.values.astype(float)
    lo = SL.loyo(T, LIVE, "ridge", 10.0); sh = np.where(np.isnan(lo), T.prior.values, 0.5 * lo + 0.5 * T.prior.values)   # v2.15 shadow prior
    # --- does the signal exist on the riser rows? ---
    d = (clay - lo >= 2) & (adp <= 60)
    P(f"\n=== the {d.sum()} top-60 rows where Clay sat 2+ above the ridge: is there a vacated / depth signal? ===")
    for i in np.where(d)[0]:
        r = T.iloc[i]
        P(f"  {int(r.year)} {r['name']:22s} {r.pos} {r.team} adp {r.adp:4.0f} | string {fmt(r.strb, 0)} | vac {r.vac:.2f} leader-left {int(r.leader_left)} prev-rank {fmt(r.prev_rank, 0)} promo {int(r.promo)} | act {r.ppg:5.1f} Clay {r.clay:5.1f} shadow {sh[i]:5.1f}")
    t60 = (adp <= 60) & (T.pos != "QB").values
    P(f"  riser rows: mean vac {np.average(T.vac.values[d], weights=ws[d]):.3f} vs all top-60 non-QB {np.average(T.vac.values[t60], weights=ws[t60]):.3f} | promo share {T.promo.values[d].mean():.2f} vs {T.promo.values[adp <= 60].mean():.2f} | leader-left {T.leader_left.values[d].mean():.2f} vs {T.leader_left.values[adp <= 60].mean():.2f}")
    # --- A. ridge + vacated features ---
    P("\n=== A. ridge LIVE + vacated features (LOYO), by tier ===")
    lo_v = SL.loyo(T, LIVE + VAC, "ridge", 10.0); sh_v = np.where(np.isnan(lo_v), T.prior.values, 0.5 * lo_v + 0.5 * T.prior.values)
    for lab, fn in TIERS: grade(T, sh_v, sh, clay, f"{lab}: shadow prior with ridge+vacated", fn(T), RES["ridge"])
    for ps in POS4: grade(T, sh_v, sh, clay, f"top 150 {ps}: ridge+vacated", (adp <= 150) & (T.pos == ps).values, RES["ridge"])
    # --- B. bump rules ---
    P("\n=== B. bump rules on the v2.15 shadow prior (k per position, LOYO on top-150 rows) ===")
    top150 = adp <= 150
    for feat, grid, lab in (("str1_vac", [0, 0.25, 0.5, 0.75, 1.0, 1.5], "prior x (1 + k x string-1 x vacated share)"), ("promo", [0, 0.05, 0.1, 0.15, 0.2], "prior x (1 + k x promotion flag)"), ("vac", [0, 0.25, 0.5, 0.75, 1.0], "prior x (1 + k x vacated share), any string")):
        bumped, picks = bump_loyo(T, sh, feat, grid, top150)
        P(f"  -- {lab}: k picks " + " ".join(f"{ps} {sorted(set(v))}" for ps, v in picks.items()))
        for tl, fn in TIERS: grade(T, bumped, sh, clay, f"{tl}: {lab.split(' x ', 1)[1]}", fn(T), RES["bump"])
        for ps in POS4: grade(T, bumped, sh, clay, f"top 150 {ps}: {feat} bump", (adp <= 150) & (T.pos == ps).values, RES["bump"])
        P(f"     riser rows mean pred {np.average(bumped[d], weights=ws[d]):5.2f} (shadow {np.average(sh[d], weights=ws[d]):5.2f}, act {np.average(T.ppg.values[d], weights=ws[d]):5.2f}, Clay {np.average(clay[d], weights=ws[d]):5.2f})")
    # --- forward ---
    P("\n=== Forward 2021-25 (fit on earlier seasons only) ===")
    fm = (T.year >= YEARS[2]).values
    fw = SL.forward(T, LIVE, "ridge", 10.0); shf = np.where(np.isnan(fw), T.prior.values, 0.5 * fw + 0.5 * T.prior.values)
    fw_v = SL.forward(T, LIVE + VAC, "ridge", 10.0); shf_v = np.where(np.isnan(fw_v), T.prior.values, 0.5 * fw_v + 0.5 * T.prior.values)
    for lab, fn in TIERS: grade(T, shf_v, shf, clay, f"forward {lab}: ridge+vacated", fm & fn(T), RES["forward"])
    act, g, year, pos = T.ppg.values, T.games.values.astype(float), T.year.values, T.pos.values
    for feat, grid, lab in (("str1_vac", [0, 0.25, 0.5, 0.75, 1.0, 1.5], "string-1 x vacated bump"), ("promo", [0, 0.05, 0.1, 0.15, 0.2], "promotion bump")):
        f = T[feat].values; out = shf.copy()
        for ps in POS4:
            for y in YEARS[2:]:
                tr = (pos == ps) & (year < y) & top150; te = (pos == ps) & (year == y)
                best = min(grid, key=lambda k: SL.wmse(shf[tr] * (1 + k * f[tr]), act[tr], g[tr])); out[te] = shf[te] * (1 + best * f[te])
        for tl, fn in TIERS: grade(T, out, shf, clay, f"forward {tl}: {lab}", fm & fn(T), RES["forward"])
    b150 = [r for r in RES["bump"] if r["label"].startswith("top 150:")]; f150 = [r for r in RES["forward"] if r["label"].startswith("forward top 150")]
    RES["summary"] = ("Top 150 LOYO: " + "; ".join(f"{r['label'].split(': ', 1)[1]} {r['vsBase']:+.2f}% vs shadow ({r['baseWins']}/{r['years']})" for r in b150) +
                      ". Forward top 150: " + "; ".join(f"{r['label'].split(': ', 1)[1]} {r['vsBase']:+.2f}% ({r['baseWins']}/{r['years']})" for r in f150) + ".")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "vacated_bump.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_VACBUMP_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/vacated_bump.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
