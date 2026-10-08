#!/usr/bin/env python3
"""
DOES A RECEIVER'S LAST GAME WITH THE BACKUP CARRY? (follow-up to backtest_backup_qb_volume.py section 3, Jack 10-08: "Nabers was
good with Winston last week"). On the backup's 2nd+ start, receivers whose last game with him was big (> 1.25x the shadow) scored
1.12x the wired number next; whose last game was small (< .75x) scored 0.81x. The shadow already holds that game in its
evidence, so this is under-reaction to the first game of a new quarterback pairing. Variants on those rows (QB-out WR weeks,
backup also started the previous game): shadow x (last game / shadow)^k, k .15 / .25 / .4, clipped .6-1.6; LOYO + forward with
the bar (5/7 + 3/4, LOYO < -0.3%), whole-board guard, rank line. Log backup_lastgame.log.
"""
import os, sys, json, warnings
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import backtest_qb_injury_usage as QI
import rank_grade as RG
SN = BR.SN; cal = SN.NW.cal; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "backup_lastgame.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["team"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    base = top150 & ~final & ~LV["inh"] & (SHADOW >= 3)
    Xg = dict(X); Xg["ch"] = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    games, roster, starter, team_weeks = QI.build_games(Xg)
    WR = base & (pos == "WR") & X["qbo"]
    prevSame = np.zeros(n, bool); lastpts = np.full(n, np.nan); first = np.zeros(n, bool)
    for i in np.where(WR)[0]:
        Y = int(year[i]); pw = [w for w in team_weeks.get((Y, team[i]), []) if w < wk[i]]
        if not pw: continue
        bq = starter.get((Y, team[i], pw[-1]))
        if len(pw) >= 2 and bq and starter.get((Y, team[i], pw[-2])) == bq: prevSame[i] = True
        elif len(pw) >= 2 and bq and starter.get((Y, team[i], pw[-2])) != bq: first[i] = True
        gl = games.get((name[i], "WR", Y), (None, None, {}))[2]
        if pw[-1] in gl: lastpts[i] = gl[pw[-1]][0]
    m = WR & prevSame & ~np.isnan(lastpts)
    P(f"=== QB-out WR rows where the backup also started the previous game: {int(m.sum())} (backup's first start: {int((WR & first).sum())}) ===")
    ratio = np.where(m, np.clip(lastpts / np.maximum(SHADOW, 1e-9), 0.1, 5.0), 1.0)
    for lab, mm in (("all", m), ("last game > 1.25x", m & (ratio > 1.25)), ("last game .75-1.25x", m & (ratio >= 0.75) & (ratio <= 1.25)), ("last game < .75x", m & (ratio < 0.75)), ("ADP <= 60", m & (adpx <= 60)), ("ADP 61-150", m & (adpx > 60))):
        if mm.sum() < 15: continue
        P(f"  {lab:20s} n{int(mm.sum()):4d} | act/wired {act[mm].sum()/SHADOW[mm].sum():.3f} | seasons over 1.0: {sum(1 for y in YEARS if (mm & (year == y)).sum() >= 5 and act[mm & (year == y)].sum()/SHADOW[mm & (year == y)].sum() > 1)}/{sum(1 for y in YEARS if (mm & (year == y)).sum() >= 5)}")
    # control: non-QB-out WR rows, same construction (last game vs projection) - is it a general last-game under-reaction?
    ctrl = base & (pos == "WR") & ~X["qbo"] & (g >= 2)
    lastC = np.full(n, np.nan)
    for i in np.where(ctrl)[0]:
        Y = int(year[i]); gl = games.get((name[i], "WR", Y), (None, None, {}))[2]; pw = [w for w in gl if w < wk[i]]
        if pw: lastC[i] = gl[max(pw)][0]
    mc = ctrl & ~np.isnan(lastC); rc = np.where(mc, np.clip(lastC / np.maximum(SHADOW, 1e-9), 0.1, 5.0), 1.0)
    P("  control (WR, starter in): " + " | ".join(f"{lab} n{int(mm.sum())} act/wired {act[mm].sum()/SHADOW[mm].sum():.3f}" for lab, mm in (("last > 1.25x", mc & (rc > 1.25)), ("last .75-1.25x", mc & (rc >= 0.75) & (rc <= 1.25)), ("last < .75x", mc & (rc < 0.75)))))
    wm = lambda p, mm: float(np.average((p[mm] - act[mm]) ** 2, weights=wt[mm])) if mm.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    def test(title, mm, rr):
        preds = {"off": SHADOW}
        for k in (0.15, 0.25, 0.4): p = SHADOW.copy(); p[mm] = SHADOW[mm] * np.clip(np.power(rr[mm], k), 0.6, 1.6); preds[f"k {k}"] = p
        names = list(preds); pick = lambda yrs: min(names, key=lambda kk: wm(preds[kk], mm & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = SHADOW.copy()
            for tr_, te in folds:
                kk = pick(tr_); picks.append(kk); mx = year == te; pr[mx] = preds[kk][mx]; wins += wm(preds[kk], mm & mx) < wm(SHADOW, mm & mx) - 1e-12
            tem = np.isin(year, [te for _, te in folds]); return 100 * (wm(pr, mm & tem) / wm(SHADOW, mm & tem) - 1), 100 * (wm(pr, base & tem) / wm(SHADOW, base & tem) - 1), wins, picks
        lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
        fixed = "  ".join(f"{kk}: {100*(wm(preds[kk], mm)/wm(SHADOW, mm)-1):+.2f}% ({sum(1 for y in YEARS if (mm & (year == y)).sum() >= 5 and wm(preds[kk], mm & (year == y)) < wm(SHADOW, mm & (year == y)) - 1e-12)}/{sum(1 for y in YEARS if (mm & (year == y)).sum() >= 5)})" for kk in names[1:])
        okk = best != "off" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
        P(f"\n  {title} (rows {int(mm.sum()):,})"); P(f"    fixed: {fixed}"); P("    " + RG.rank_line(preds, mm, act, year, wk, pos))
        P(f"    LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | picks {lo[3]}"); P(f"    FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}"); P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
    test("A  last game with the backup carried into the shadow: x (last / shadow)^k", m, ratio)
    test("B  control - same rule on every WR with the starter in (should FAIL if the backup case is special)", mc, rc)
    P("\nLimitations: 222 rows over 7 seasons; the shadow already holds the last game at its usual weight; honest replica, no book anchor (the lines already price a hot game).")
    LOG.close()


if __name__ == "__main__":
    main()
