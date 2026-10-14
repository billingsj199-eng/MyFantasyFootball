#!/usr/bin/env python3
"""
ABSENCE MAP follow-up tests (2026-10-09, research_absence_all_positions.py top mismatches). Harness = backtest_base_remeasure shadow
replica (pool .75 inside) x wired NEXT MAN UP x PROMO x TEAM_VAC (absent RBs excluded, as wired today) - the same base the
TEAM_VAC / NMU / PROMO layers were graded on. Rows RB/WR/TE (and QB for C3 read) shadow >= 1, final week out.
  C1  RBs (and optionally TEs) do NOT take the TEAM_VAC / NMU boosts when a WR/TE is out (map: WR1 out -> RB1 -1.7 PPR, engine +1.1;
      WR2 out -> TE1 -1.3, engine +0.5).
  C2  starting QB out: WR dock by WR ROOM RANK instead of ADP (map: WR1 +0.6 vs engine -1.4, WR2 -2.7 vs engine -0.6), and an RB1 lift
      (map: RB1 +2.6, engine 0).
Bar: touched rows LOYO better 5/7 and forward 3/4 (pick-best on training seasons), board not worse. Log absence_changes.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import backtest_team_vacated_boost as TVB
cal = BR.cal; YEARS = BR.YEARS; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "absence_changes.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()
SK = ("RB", "WR", "TE"); PROMO = {"RB": 1.034, "WR": 1.071, "TE": 1.207}


def main():
    X = BR.SN.setup(); n = X["n"]
    act, year, wk, pos, name, adp, team = X["act"], X["year"], X["wk"], X["pos"], X["name"], X["adp"], X["team"]
    SH, _ = BR.shadow_current(X)
    finw = np.where(year <= 2020, 17, 18)
    nlog = os.path.join(HERE, "next_man_up.log"); keep = open(nlog, encoding="utf-8").read() if os.path.exists(nlog) else None
    import research_next_man_up as R
    if keep is not None: R.LOG.close(); open(nlog, "w", encoding="utf-8").write(keep)
    Ev, _c = R.events(); TODAY, LV = BR.live_today(X)
    adpx = np.where(np.isnan(adp), 999.0, adp); nbase = (adpx <= 150) & (wk != finw) & ~LV["inh"] & (SH >= 3)
    idx = {(R.nz(name[i]), int(year[i]), int(wk[i])): i for i in range(n)}
    NMU = np.ones(n)
    for r in Ev:
        i = idx.get((R.nz(r["n"]), r["Y"], r["wk"]))
        if i is None or not nbase[i] or r["rank"] > 6: continue
        if all(p_ == "RB" for p_ in r["absPos"]): continue   # wired: an absent RB does not trigger NMU
        NMU[i] = 1.04 if r["rank"] == 1 else 0.99 if r["rank"] <= 3 else 1.03
    tg, promo, cg = TVB.tables()
    PR = np.ones(n)
    for i in range(n):
        if pos[i] in PROMO and (cal.norm(name[i]), int(year[i]), int(wk[i])) in promo: PR[i] = PROMO[pos[i]]
    team_wks = defaultdict(list)
    for (Y, t, w) in tg: team_wks[(Y, t)].append(w)
    for k in team_wks: team_wks[k].sort()
    # per team-week: vacated target share by absent position; WR / RB room ranks by trailing targets / carries
    cache = {}
    def info(Y, t, w):
        key = (Y, t, w)
        if key in cache: return cache[key]
        res = None
        if (Y, t, w) in tg:
            prior = [u for u in team_wks.get((Y, t), []) if u < w][-3:]
            if len(prior) >= 2:
                tot = 0.0; by = defaultdict(float); gp = defaultdict(int); car = defaultdict(float)
                for u in prior:
                    for kk, v in tg[(Y, t, u)].items(): tot += v; by[kk] += v; gp[kk] += 1
                    for kk, v in cg.get((Y, t, u), {}).items(): car[kk] += v
                if tot >= 30:
                    vac = defaultdict(float)
                    for kk, v in by.items():
                        if gp[kk] >= 2 and v / tot >= 0.10 and kk not in tg[(Y, t, w)]: vac[kk[1]] += v / tot
                    wr = sorted([kk for kk in by if kk[1] == "WR" and gp[kk] >= 2], key=lambda k: -by[k])
                    rb = sorted([kk for kk in car if kk[1] == "RB" and gp[kk] >= 2], key=lambda k: -car[k])
                    rbl = [kk for kk in car if kk[1] == "RB" and gp.get(kk, 0) >= 2 or (kk[1] == "RB" and car[kk] >= 6)]
                    rbo = sorted([kk for kk in car if kk[1] == "RB"], key=lambda k: -car[k])
                    rbinfo = dict(top=cal.norm(rbo[0][0]) if rbo else None, top_out=bool(rbo) and rbo[0] not in cg.get((Y, t, w), {}) and rbo[0] not in tg[(Y, t, w)],
                                  top_room=(car[rbo[0]] / max(1e-9, sum(car[k] for k in rbo))) if rbo else 0,
                                  car={cal.norm(k[0]): car[k] / len(prior) for k in rbo}, tgt={cal.norm(k[0]): by.get(k, 0.0) / len(prior) for k in rbo},
                                  order=[cal.norm(k[0]) for k in rbo])
                    res = dict(rbi=rbinfo, vac=vac, wr={cal.norm(k[0]): j + 1 for j, k in enumerate(wr)}, rb={cal.norm(k[0]): j + 1 for j, k in enumerate(rb)})
        cache[key] = res; return res
    INF = [info(int(year[i]), team[i], int(wk[i])) if (team[i] and pos[i] in SK + ("QB",)) else None for i in range(n)]
    vac_wr = np.array([I["vac"].get("WR", 0.0) if I else 0.0 for I in INF]); vac_te = np.array([I["vac"].get("TE", 0.0) if I else 0.0 for I in INF])
    vac = vac_wr + vac_te
    wrk = np.array([I["wr"].get(cal.norm(name[i]), 0) if I else 0 for i, I in enumerate(INF)])
    rbk = np.array([I["rb"].get(cal.norm(name[i]), 0) if I else 0 for i, I in enumerate(INF)])
    hasI = np.array([I is not None for I in INF])
    TV = np.where(hasI & np.isin(pos, SK), 1 + 0.2 * vac, 1.0)
    B0 = SH * NMU * PR * TV
    ok = np.isin(pos, SK) & (wk != finw) & (SH >= 1) & np.isfinite(act) & hasI
    mse = lambda p, m: float(np.mean((p[m] - act[m]) ** 2))
    P(f"rows {ok.sum()} RB/WR/TE; base = shadow x NMU x PROMO x TEAM_VAC (WR/TE absences)")

    def grade(title, preds, touched, allrows):
        names = list(preds)
        def pick(yrs): return min(names, key=lambda kk: mse(preds[kk], allrows & np.isin(year, yrs)))
        P(f"\n=== {title}: touched rows {int(touched.sum())} ===")
        P("  actual/base on touched rows by season: " + " ".join(f"{y}:{act[touched & (year == y)].sum()/max(1e-9, B0[touched & (year == y)].sum()):.3f}" for y in YEARS)
          + f" | all {act[touched].sum()/B0[touched].sum():.3f}")
        for label, folds in (("LOYO", [(tuple(y for y in YEARS if y != t), t) for t in YEARS]), ("FORWARD", [(tuple(y for y in YEARS if y < t), t) for t in FWD])):
            wins = 0; a0 = a1 = b0 = b1 = 0.0; picks = []
            for tr, te in folds:
                kk = pick(tr); picks.append(kk); r = touched & (year == te); w_ = allrows & (year == te)
                if r.sum() == 0: continue
                e0, e1 = mse(preds["off"], r), mse(preds[kk], r); wins += int(e1 < e0 - 1e-12)
                a0 += e0 * r.sum(); a1 += e1 * r.sum(); b0 += mse(preds["off"], w_) * w_.sum(); b1 += mse(preds[kk], w_) * w_.sum()
            P(f"  {label}: touched {100*(a1/a0-1):+.2f}% ({wins}/{len(folds)}), board {100*(b1/b0-1):+.3f}% | picks {picks}")
        P("  fixed, all seasons (touched MSE / seasons better): " + "  ".join(
            f"{kk} {100*(mse(preds[kk], touched)/mse(preds['off'], touched)-1):+.2f}% {sum(mse(preds[kk], touched & (year == y)) < mse(preds['off'], touched & (year == y)) for y in YEARS)}/7"
            for kk in names[1:]))

    # ---- C1: no TEAM_VAC / NMU for RBs (and TEs) when a WR/TE is out
    rbt = ok & (pos == "RB") & ((TV > 1) | (NMU != 1))
    P(f"\nC1 read: RB rows getting TEAM_VAC / NMU: {int(rbt.sum())}, actual/base {act[rbt].sum()/B0[rbt].sum():.3f}; same rows without those layers {act[rbt].sum()/(SH*PR)[rbt].sum():.3f}")
    tet = ok & (pos == "TE") & (vac_wr > 0) & (vac_te == 0)
    P(f"C1 read: TE rows when only WRs are out: {int(tet.sum())}, actual/base {act[tet].sum()/B0[tet].sum():.3f}; without TV/NMU {act[tet].sum()/(SH*PR)[tet].sum():.3f}")
    wrt = ok & (pos == "WR") & (vac > 0)
    P(f"C1 read: WR rows with a WR/TE out: {int(wrt.sum())}, actual/base {act[wrt].sum()/B0[wrt].sum():.3f}")
    preds = {"off": B0,
             "RB no TV": np.where(pos == "RB", SH * NMU * PR, B0),
             "RB no TV/NMU": np.where(pos == "RB", SH * PR, B0),
             "RB half TV/NMU": np.where(pos == "RB", SH * PR * np.sqrt(NMU * TV), B0),
             "RB+TE(WR out) no TV/NMU": np.where(pos == "RB", SH * PR, np.where((pos == "TE") & (vac_te == 0), SH * PR, B0))}
    grade("C1 RB/TE excluded from TEAM_VAC + NMU", preds, ok & (((pos == "RB") & ((TV > 1) | (NMU != 1))) | tet), ok)
    grade("C1a RB rows only", {k: preds[k] for k in ("off", "RB no TV", "RB no TV/NMU", "RB half TV/NMU")}, rbt, ok)

    # ---- C2: QB out
    qbo = X["qbo"]
    for ps in SK:
        for k in (1, 2, 3):
            m = ok & qbo & (pos == ps) & ((wrk == k) if ps == "WR" else (rbk == k) if ps == "RB" else np.ones(n, bool))
            if ps == "TE" and k > 1: continue
            if m.sum() >= 15:
                P(f"C2 read: QB out, {ps}{k if ps != 'TE' else ''}: n {int(m.sum())} actual/base {act[m].sum()/B0[m].sum():.3f} (ADP<=60 share {np.mean(adpx[m] <= 60):.2f})")
    undock = np.where((pos == "WR") & qbo, np.where(adp <= 60, 1 / 0.85, 1 / 0.95), 1.0)   # remove the wired ADP dock
    preds = {"off": B0}
    for d1, d2 in ((0.05, 0.10), (0.05, 0.15), (0.0, 0.10), (0.0, 0.15), (0.10, 0.15), (0.05, 0.20)):
        dock = np.where(wrk == 1, 1 - d1, np.where(wrk >= 2, 1 - d2, 1 - d2))
        preds[f"WR1 -{d1:.2f} WR2+ -{d2:.2f}"] = np.where((pos == "WR") & qbo, B0 * undock * dock, B0)
    touched_wr = ok & qbo & (pos == "WR")
    grade("C2a QB out: WR dock by room rank (replaces ADP <= 60 tier)", preds, touched_wr, ok)
    preds = {"off": B0}
    for k in (0.04, 0.08, 0.12, 0.16):
        preds[f"RB1 x{1+k:.2f}"] = np.where((pos == "RB") & qbo & (rbk == 1), B0 * (1 + k), B0)
    grade("C2b QB out: RB1 lift", preds, ok & qbo & (pos == "RB") & (rbk == 1), ok)
    # ---- C3: QB lift when pass catchers are out (map: TE1 out -> QB +1.8 6/7, WR3 out +1.0, RB2 out +0.9; engine 0)
    qok = (pos == "QB") & (wk != finw) & (SH >= 5) & np.isfinite(act) & hasI & ~qbo
    for lab, m in (("no WR/TE out", qok & (vac == 0)), ("WR/TE out .10-.20", qok & (vac > 0) & (vac < .2)), ("WR/TE out .20+", qok & (vac >= .2)),
                   ("TE out only", qok & (vac_te > 0) & (vac_wr == 0)), ("WR out only", qok & (vac_wr > 0) & (vac_te == 0))):
        if m.sum() >= 10: P(f"C3 read: QB {lab}: n {int(m.sum())} actual/shadow {act[m].sum()/SH[m].sum():.3f}")
    preds = {"off": SH}
    for k in (0.05, 0.10, 0.20, 0.30):
        preds[f"QB x(1+{k}vac)"] = np.where(qok, SH * (1 + k * vac), SH)
    for k in (0.03, 0.06):
        preds[f"QB x{1+k} if TE out"] = np.where(qok & (vac_te > 0), SH * (1 + k), SH)
    B0 = SH
    grade("C3 QB lift when WR/TE are out", preds, qok & (vac > 0), qok)
    # ---- C5: CLEAR RB2 WITH A RECEIVING ROLE when the RB1 is out (rooms study: direct backup with a 5+ carry/g lead on the RB3 and
    # 2.5+ targets/g ran +1.4 PPR over the regression-corrected replica, 6/7 seasons). Harness rows: RB, team's trailing RB1 has no
    # row this week, this RB = trailing RB2.
    rbr = np.zeros(n, bool); clear = np.zeros(n, bool); catch = np.zeros(n, bool); wh = np.zeros(n, bool)
    for i, I in enumerate(INF):
        if I is None or pos[i] != "RB" or not I["rbi"]["top_out"]: continue
        o = I["rbi"]["order"]; nm_ = cal.norm(name[i])
        if len(o) >= 2 and o[1] == nm_:
            rbr[i] = True; c2 = I["rbi"]["car"][nm_]; c3 = I["rbi"]["car"][o[2]] if len(o) > 2 else 0.0
            clear[i] = c2 - c3 >= 5; catch[i] = I["rbi"]["tgt"].get(nm_, 0) >= 2.5; wh[i] = I["rbi"]["top_room"] >= 0.6
    okr = ok & rbr
    for lab, m in (("direct backup, RB1 out (all)", okr), ("clear RB2", okr & clear), ("clear RB2 + catches", okr & clear & catch), ("clear + catches + workhorse out", okr & clear & catch & wh),
                   ("not clear", okr & ~clear), ("clear, no catching role", okr & clear & ~catch)):
        if m.sum() >= 5: P(f"C5 read: {lab:32s} n {int(m.sum()):3d} actual/base {act[m].sum()/B0[m].sum():.3f} | " + " ".join(f"{y}:{act[m & (year == y)].sum()/max(1e-9, B0[m & (year == y)].sum()):.2f}" for y in YEARS if (m & (year == y)).sum()))
    B0 = SH * NMU * PR * TV
    tch = okr & clear & catch
    preds = {"off": B0}
    for k in (1.04, 1.08, 1.12, 1.16):
        preds[f"x{k}"] = np.where(tch, B0 * k, B0)
    grade("C5 clear RB2 with a receiving role, RB1 out", preds, tch, ok)
    preds = {"off": B0}
    for k in (1.05, 1.10, 1.15, 1.20, 1.25):
        preds[f"x{k}"] = np.where(okr, B0 * k, B0)
    grade("C5b ANY direct backup (trailing RB2) when the trailing RB1 is out", preds, okr, ok)
    preds = {"off": B0}
    for k in (1.05, 1.10, 1.15, 1.20):
        preds[f"wh x{k}"] = np.where(okr & wh, B0 * k, B0); preds[f"comm x{k}"] = np.where(okr & ~wh, B0 * k, B0)
    grade("C5c direct backup split workhorse / committee", preds, okr, ok)
    P("C5 read by base level: " + " | ".join(f"base {lo}-{hi}: n {int((okr & (B0 >= lo) & (B0 < hi)).sum())} {act[okr & (B0 >= lo) & (B0 < hi)].sum()/max(1e-9, B0[okr & (B0 >= lo) & (B0 < hi)].sum()):.2f}" for lo, hi in ((0, 5), (5, 8), (8, 11), (11, 99))))
    LOG.close()


if __name__ == "__main__":
    main()
