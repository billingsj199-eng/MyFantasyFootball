#!/usr/bin/env python3
"""
BACKUP QB BY HIS OWN VOLUME, not a flat dock (Jack 2026-10-08: "let's not automatically dock for backup but rank the QBs -
Winston historically is a high-volume passer where Dart was lower volume but more efficient; Nabers was good with Winston").
Honest replica, next game. Rows = WR top-150 weeks with the team's primary QB out (the shadow's wired dock: x.85 ADP <= 60,
x.95 otherwise). The backup = the team's top passer in the PREVIOUS team game (known before kickoff). His volume = pass
attempts per game over his career starts before this season (weekly logs, 15+ attempts), split high / mid / low by tercile
within the season's backups. Variants: wired flat dock; no dock; dock only on low-volume backups; dock scaled by the backup's
attempts vs the league starter average; the backup's volume as a multiplier with no dock. LOYO + forward, bar 5/7 + 3/4,
whole-board guard, rank line. Also: WR rows in the backup's 2nd+ start where the WR's LAST game was with him - does that game
carry? Log backup_qb_volume.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import backtest_qb_injury_usage as QI
import rank_grade as RG
SN = BR.SN; cal = SN.NW.cal; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "backup_qb_volume.log"), "w", encoding="utf-8")
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
    import json
    Xg = dict(X); Xg["ch"] = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    games, roster, starter, team_weeks = QI.build_games(Xg)
    # QB career volume before season Y: attempts per game over starts (15+ att) in seasons < Y (plus this season's earlier games)
    qvol = {}
    def qb_vol(qb, Y, before_wk):
        k = (qb, Y, before_wk)
        if k in qvol: return qvol[k]
        rec = cal.weekly_rec(qb, "QB"); att = []
        for y_, rows in (rec or {}).get("seasons", {}).items():
            yy = int(y_)
            if yy > Y: continue
            for w in rows:
                if yy == Y and int(w.get("wk", 99)) >= before_wk: continue
                pa = w.get("pa") or 0
                if cal.played(w) and pa >= 15: att.append(float(pa))
        qvol[k] = (float(np.mean(att)) if len(att) >= 3 else np.nan, len(att)); return qvol[k]
    WR = base & (pos == "WR") & X["qbo"]
    bvol = np.full(n, np.nan); bname = [None] * n; nstarts = np.zeros(n)
    for i in np.where(WR)[0]:
        Y = int(year[i]); prior_w = [w for w in team_weeks.get((Y, team[i]), []) if w < wk[i]]
        if not prior_w: continue
        qb = starter.get((Y, team[i], prior_w[-1])); bname[i] = qb
        if qb: v, nn = qb_vol(qb, Y, int(wk[i])); bvol[i] = v; nstarts[i] = nn
    # league starter average attempts per game that season (top-32 passers by attempts in prior seasons' logs) ~ use the row-season mean of all backups' league: simpler = 33
    LGATT = 33.0
    m = WR & ~np.isnan(bvol)
    P(f"=== WR weeks with the primary QB out: {int(WR.sum()):,}; backup identified with a career volume read: {int(m.sum()):,} ===")
    dock0 = np.where(adpx <= 60, 0.85, 0.95); NOD = np.where(WR, SHADOW / dock0, SHADOW)
    z = np.full(n, np.nan)
    for y in YEARS:
        mm = m & (year == y)
        if mm.sum() >= 10: z[mm] = (bvol[mm] - np.nanmean(bvol[mm])) / max(np.nanstd(bvol[mm]), 1e-9)
    terc = np.full(n, "", dtype=object)
    for y in YEARS:
        mm = m & (year == y)
        if mm.sum() >= 10:
            q1, q2 = np.nanpercentile(bvol[mm], [33, 67]); terc[mm & (bvol <= q1)] = "low"; terc[mm & (bvol > q1) & (bvol <= q2)] = "mid"; terc[mm & (bvol > q2)] = "high"
    P("\n--- 1  actual / UNDOCKED shadow by the backup's career volume (what the dock should be) ---")
    for lab, mm in (("all QB-out WR rows", m), ("backup low volume", m & (terc == "low")), ("backup mid", m & (terc == "mid")), ("backup high volume", m & (terc == "high")), ("ADP <= 60 WRs", m & (adpx <= 60)), ("ADP 61-150", m & (adpx > 60)), ("backup's first start", m & (nstarts >= 0) & np.array([bname[i] is not None and (int(year[i]), team[i], (([w for w in team_weeks.get((int(year[i]), team[i]), []) if w < wk[i]] or [0])[-1])) in starter and sum(1 for w in [w for w in team_weeks.get((int(year[i]), team[i]), []) if w < wk[i]][-3:] if starter.get((int(year[i]), team[i], w)) == bname[i]) == 1 for i in range(n)]))):
        if mm.sum() < 15: P(f"  {lab:24s} n{int(mm.sum())}"); continue
        P(f"  {lab:24s} n{int(mm.sum()):4d} | act/undocked {act[mm].sum()/NOD[mm].sum():.3f} | act/wired {act[mm].sum()/SHADOW[mm].sum():.3f} | backup att/g {np.nanmean(bvol[mm]):.1f} | seasons under 1.0 (undocked): {sum(1 for y in YEARS if (mm & (year == y)).sum() >= 5 and act[mm & (year == y)].sum()/NOD[mm & (year == y)].sum() < 1)}/{sum(1 for y in YEARS if (mm & (year == y)).sum() >= 5)}")
    P("\n--- 2  variants on the QB-out WR rows (whole-board guard), vs the WIRED flat dock ---")
    wm = lambda p, mm: float(np.average((p[mm] - act[mm]) ** 2, weights=wt[mm])) if mm.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    preds = {"off": SHADOW, "no dock": NOD}
    p = NOD.copy(); mm = m & (terc == "low"); p[mm] = NOD[mm] * dock0[mm]; preds["dock low-volume backups only"] = p
    p = NOD.copy(); mm = m & (terc != "high"); p[mm] = NOD[mm] * dock0[mm]; preds["dock low + mid, not high"] = p
    for e in (0.03, 0.06):
        p = NOD.copy(); p[m] = NOD[m] * np.clip(1 - (1 - dock0[m]) + e * z[m], 0.75, 1.1); preds[f"flat dock + {e} x volume z"] = p
    for e in (0.03, 0.06):
        p = NOD.copy(); p[m] = NOD[m] * np.clip(1 + e * z[m], 0.85, 1.15); preds[f"no dock, volume tilt {e} z"] = p
    p = NOD.copy(); p[m] = NOD[m] * np.clip(bvol[m] / LGATT, 0.75, 1.1) * np.where(adpx[m] <= 60, 0.95, 1.0); preds["backup att/g over 33 (x.95 stars)"] = p
    names = list(preds); b0 = SHADOW; pick = lambda yrs: min(names, key=lambda kk: wm(preds[kk], m & np.isin(year, yrs)))
    def run(folds):
        wins = 0; picks = []; pr = b0.copy()
        for tr_, te in folds:
            kk = pick(tr_); picks.append(kk); mmm = year == te; pr[mmm] = preds[kk][mmm]; wins += wm(preds[kk], m & mmm) < wm(b0, m & mmm) - 1e-12
        tem = np.isin(year, [te for _, te in folds]); return 100 * (wm(pr, m & tem) / wm(b0, m & tem) - 1), 100 * (wm(pr, base & tem) / wm(b0, base & tem) - 1), wins, picks
    lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
    P("  fixed: " + "  ".join(f"{kk}: {100*(wm(preds[kk], m)/wm(b0, m)-1):+.2f}% ({sum(1 for y in YEARS if (m & (year == y)).sum() >= 5 and wm(preds[kk], m & (year == y)) < wm(b0, m & (year == y)) - 1e-12)}/7)" for kk in names[1:]))
    P("  " + RG.rank_line(preds, m, act, year, wk, pos))
    P(f"  LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | picks {lo[3]}"); P(f"  FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}")
    okk = best != "off" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
    P(f"  -> {'PASS: ' + best if okk else 'FAIL (wired flat dock stays)'}")
    P("\n--- 3  does the WR's last game WITH this backup carry? rows where the backup also started the previous game ---")
    prevSame = np.zeros(n, bool); lastpts = np.full(n, np.nan)
    for i in np.where(m)[0]:
        Y = int(year[i]); pw = [w for w in team_weeks.get((Y, team[i]), []) if w < wk[i]]
        if len(pw) >= 2 and starter.get((Y, team[i], pw[-1])) == bname[i] and starter.get((Y, team[i], pw[-2])) == bname[i]: prevSame[i] = True
        gl = games.get((name[i], "WR", Y), (None, None, {}))[2]
        if pw and pw[-1] in gl: lastpts[i] = gl[pw[-1]][0]
    mm = m & prevSame & ~np.isnan(lastpts)
    if mm.sum() >= 20:
        hot = mm & (lastpts > SHADOW * 1.25); cold = mm & (lastpts < SHADOW * 0.75)
        P(f"  backup's 2nd+ start, n{int(mm.sum())}: act/wired {act[mm].sum()/SHADOW[mm].sum():.3f} | last game with him was big (> 1.25x proj) n{int(hot.sum())}: act/wired {act[hot].sum()/max(1e-9, SHADOW[hot].sum()):.3f} | was small (< .75x) n{int(cold.sum())}: {act[cold].sum()/max(1e-9, SHADOW[cold].sum()):.3f}")
    P("\nLimitations: backup = previous game's top passer (the pre-kickoff read); career volume from weekly logs (15+ att games, 3+ needed); honest replica next game; no book anchor (live, the lines already carry the backup).")
    LOG.close()


if __name__ == "__main__":
    main()
