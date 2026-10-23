#!/usr/bin/env python3
"""
ADP ERA DRIFT (Jack 2026-10-20: "I also feel like the game has changed and adp has gotten sharper so if the earlier years are
a problem lmk"). RESEARCH ONLY. Run with SIM_BT_YEARS=2012-2025 after `DUMP0=1 research_usage_legit.py` (writes
_bt_ext/adp_variants_dump*.pkl: wired / B (no ADP in the prior) / H (blend x.5) rest-of-season + next-game predictions).

  A  ADP SHARPNESS by season x position: Spearman(ADP, season PPG) and R^2 of an ADP-only curve (PPG ~ a + b ln ADP, fit per
     season), outcomes scored half-PPR AND in the ADP's own format (FFC 2012-17 = PPR / standard; 2018+ mostly half) -
     receptions per game from play-by-play; plus Spearman(ADP, rest-of-season PPG) at checkpoints after 4 / 6 / 8 games
  B  ADP's INCREMENTAL value by season: B-vs-wired rest-of-season error gap (the prior without ADP), and the per-season OLS
     coefficient of ln ADP next to the ADP-free prior (standardized) + the R^2 it adds
  C  TRENDS: OLS slope per season with 95% CI, 2013-25 and 2018-25 (half-PPR-consistent)
Log _bt_ext/adp_era_ext2012_2025_tf.log.
"""
import os, sys, json, pickle
from collections import defaultdict
import numpy as np, pandas as pd
from scipy import stats
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_ext as BX
import bt_common as B
import backtest_noclay_weekly as NW
POS4 = ("QB", "RB", "WR", "TE"); YRS = [y for y in BX.YEARS if y >= 2013]


def main():
    log = open(BX.ext_path("adp_era.log"), "w", encoding="utf-8")
    def P(s=""): print(s, flush=True); log.write(s + "\n"); log.flush()
    D = pickle.load(open(BX.ext_path("adp_variants_dump.pkl"), "rb"))
    year, pos, wk, g, act, adp, T, ok, okN = D["year"], D["pos"], D["wk"], D["g"], D["act"], D["adp"], D["T"], D["ok"], D["okN"]
    name, pid = D["name"], D["pid"]; n = len(year)
    # receptions per player-game
    rec = {}
    for Y in sorted(set(int(y) for y in year)):
        d = pd.read_csv(os.path.join(B.CACHE, f"play_by_play_{Y}.csv.gz"), usecols=["season_type", "week", "receiver_player_id", "complete_pass", "two_point_attempt"], low_memory=False)
        d = d[(d.season_type == "REG") & (d.complete_pass == 1) & (d.two_point_attempt.fillna(0) != 1) & d.receiver_player_id.notna()]
        for (p_, w_), c in d.groupby(["receiver_player_id", "week"]).size().items(): rec[(Y, p_, int(w_))] = int(c)
    rc = np.array([rec.get((int(year[i]), pid[i], int(wk[i])), 0) if pid[i] else 0 for i in range(n)], float)
    fj = json.load(open(os.path.join(HERE, "data", "ffc_adp_hist.json"), encoding="utf-8")); fmt = {}
    for y_, blk in fj.items():
        for p_ in blk["players"]: fmt[(int(y_), NW.cal.norm(p_["name"]), {"PK": "K", "DEF": "DST"}.get(p_["pos"], p_["pos"]))] = p_.get("fmt", "")
    fm = np.array([fmt.get((int(year[i]), NW.cal.norm(name[i]), pos[i]), "") for i in range(n)])
    own = np.where(fm == "ppr", act + 0.5 * rc, np.where(fm == "standard", act - 0.5 * rc, act))
    P(f"=== ADP ERA DRIFT ({BX.describe()}) ===")
    P("  ADP format share by season (rows with ADP): " + " ".join(f"{y}:" + "/".join(f"{100*np.mean(fm[(year == y) & ~np.isnan(adp)] == f_):.0f}" for f_ in ("half-ppr", "ppr", "standard")) for y in YRS) + "  (% half/ppr/std)")
    # player-season table
    ks = defaultdict(list)
    for i in range(n): ks[(int(year[i]), name[i], pos[i])].append(i)
    S = []
    for (y_, nm, ps), ix in ks.items():
        if len(ix) < 4 or y_ not in YRS: continue
        ix = sorted(ix, key=lambda i: wk[i]); a0 = adp[ix[0]]
        S.append(dict(year=y_, pos=ps, adp=a0, half=float(np.mean(act[ix])), own=float(np.mean(own[ix])), prb=float(D["PRB"][ix[0]]), fmt=fm[ix[0]]))
    S = pd.DataFrame(S); S = S[~S.adp.isna() & (S.adp <= 200)]
    def trend(xs, ys):
        xs, ys = np.asarray(xs, float), np.asarray(ys, float); m = ~np.isnan(ys)
        if m.sum() < 4: return "n/a"
        r = stats.linregress(xs[m], ys[m]); tq = stats.t.ppf(0.975, m.sum() - 2)
        return f"slope {r.slope:+.4f}/yr [95% CI {r.slope - tq*r.stderr:+.4f}, {r.slope + tq*r.stderr:+.4f}]"
    P("\n--- A  ADP SHARPNESS: Spearman(ADP rank, season PPG) per season (players ADP <= 200, 4+ games); half-PPR outcome | ADP's own-format outcome ---")
    A_ = {}
    for ps in POS4 + ("ALL",):
        rows = []
        for y in YRS:
            s = S[(S.year == y) & ((S.pos == ps) if ps != "ALL" else True)]
            if len(s) < 15: rows.append((y, np.nan, np.nan, np.nan, np.nan)); continue
            rh = stats.spearmanr(-s.adp, s.half).correlation; ro = stats.spearmanr(-s.adp, s.own).correlation
            if ps == "ALL":   # within-position Spearman averaged
                rh = np.mean([stats.spearmanr(-q.adp, q.half).correlation for _, q in s.groupby("pos") if len(q) >= 10])
                ro = np.mean([stats.spearmanr(-q.adp, q.own).correlation for _, q in s.groupby("pos") if len(q) >= 10])
            X_ = np.column_stack([np.ones(len(s)), np.log(s.adp)]); r2 = lambda yv: 1 - np.sum((yv - X_ @ np.linalg.lstsq(X_, yv, rcond=None)[0]) ** 2) / np.sum((yv - yv.mean()) ** 2)
            rows.append((y, rh, ro, r2(s.half.values), r2(s.own.values)))
        A_[ps] = rows
        P(f"  {ps:3s} rho half " + " ".join(f"{y % 100:02d}:{r:.2f}" for y, r, _, _, _ in rows) + f"   | {trend([r[0] for r in rows], [r[1] for r in rows])}")
        P(f"      rho own  " + " ".join(f"{y % 100:02d}:{r:.2f}" for y, _, r, _, _ in rows) + f"   | {trend([r[0] for r in rows], [r[2] for r in rows])}")
        P(f"      R2 half  " + " ".join(f"{y % 100:02d}:{r:.2f}" for y, _, _, r, _ in rows) + f"   | {trend([r[0] for r in rows], [r[3] for r in rows])}")
        r18 = [r for r in rows if r[0] >= 2018]
        P(f"      2018-25 only (half-PPR ADP): rho half {trend([r[0] for r in r18], [r[1] for r in r18])}; mean 2013-17 {np.nanmean([r[1] for r in rows if r[0] < 2018]):.3f} (own fmt {np.nanmean([r[2] for r in rows if r[0] < 2018]):.3f}) vs 2018-25 {np.nanmean([r[1] for r in r18]):.3f}")
    P("\n  rest of season: Spearman(ADP rank, ROS PPG) at the checkpoint after k games (within position, averaged), per season")
    for k in (4, 6, 8):
        rows = []
        for y in YRS:
            m = ok & (g == k) & (year == y) & ~np.isnan(adp) & (adp <= 200)
            v = [stats.spearmanr(-adp[m & (pos == ps)], T[m & (pos == ps)]).correlation for ps in POS4 if (m & (pos == ps)).sum() >= 10]
            rows.append((y, float(np.mean(v)) if v else np.nan))
        P(f"    after {k}: " + " ".join(f"{y % 100:02d}:{r:.2f}" for y, r in rows) + f"   | {trend([r[0] for r in rows], [r[1] for r in rows])}")
    # ---------------- B incremental ----------------
    P("\n--- B  ADP's INCREMENTAL VALUE by season ---")
    FULL, QB_, FULLN, QBN, QH = D["FULL"], D["QB"], D["FULLN"], D["QBN"], D["QH"]
    e = lambda q, m, t: float(np.mean((q[m] - t[m]) ** 2))
    for lab, Q, BASE, mm, tgt in (("ROS, B (no ADP in prior) vs wired", QB_, FULL, ok, T), ("ROS, H (blend x.5) vs wired", QH, FULL, ok, T), ("NEXT, B vs wired", QBN, FULLN, okN, act)):
        P(f"  {lab}: error gap % per season (+ = removing ADP hurts = ADP earns its keep)")
        for ps in POS4 + ("ALL",):
            rows = [(y, 100 * (e(Q, mm & (year == y) & ((pos == ps) if ps != "ALL" else True), tgt) / e(BASE, mm & (year == y) & ((pos == ps) if ps != "ALL" else True), tgt) - 1)) for y in YRS]
            P(f"    {ps:3s} " + " ".join(f"{y % 100:02d}:{v:+.1f}" for y, v in rows) + f"   | {trend([r[0] for r in rows], [r[1] for r in rows])} | 2018-25 {trend([r[0] for r in rows if r[0] >= 2018], [r[1] for r in rows if r[0] >= 2018])}"
              + f" | mean 13-17 {np.mean([v for y, v in rows if y < 2018]):+.2f} 18-25 {np.mean([v for y, v in rows if y >= 2018]):+.2f} | 13-15 {np.mean([v for y, v in rows if y < 2016]):+.2f} 16-25 {np.mean([v for y, v in rows if y >= 2016]):+.2f}")
    P("\n  OLS per season x position: season PPG (half | own format) ~ ADP-free prior + ln ADP (standardized); ln-ADP coef (negative = better ADP -> more points) and R^2 added over the prior alone")
    for ps in POS4:
        rows = []
        for y in YRS:
            s = S[(S.year == y) & (S.pos == ps) & ~S.prb.isna()]
            if len(s) < 20: rows.append((y, np.nan, np.nan, np.nan)); continue
            out = []
            for col in ("half", "own"):
                z = lambda v: (v - v.mean()) / v.std()
                Xa = np.column_stack([np.ones(len(s)), z(s.prb.values), z(np.log(s.adp.values))]); X0 = Xa[:, :2]; yv = s[col].values
                ba = np.linalg.lstsq(Xa, yv, rcond=None)[0]; b0 = np.linalg.lstsq(X0, yv, rcond=None)[0]
                sst = np.sum((yv - yv.mean()) ** 2); dr2 = (np.sum((yv - X0 @ b0) ** 2) - np.sum((yv - Xa @ ba) ** 2)) / sst
                out += [ba[2], dr2]
            rows.append((y, out[0], out[1], out[3]))
        P(f"    {ps} coef " + " ".join(f"{y % 100:02d}:{c:+.2f}" for y, c, _, _ in rows) + f"   | {trend([r[0] for r in rows], [r[1] for r in rows])}")
        P(f"       dR2  " + " ".join(f"{y % 100:02d}:{d:.3f}" for y, _, d, _ in rows) + f"   | {trend([r[0] for r in rows], [r[2] for r in rows])} | own-format dR2 mean 13-17 {np.nanmean([r[3] for r in rows if r[0] < 2018]):.3f} 18-25 {np.nanmean([r[3] for r in rows if r[0] >= 2018]):.3f}")
    log.close()


if __name__ == "__main__":
    main()
