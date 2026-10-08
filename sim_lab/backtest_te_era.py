#!/usr/bin/env python3
"""
TE ERA LEVEL (Jack 2026-10-08: "more recent TE production and lower WR3 production with increased 12 personnel").
research_te_trend.py: TE share of receiving points .219-.223 (2019-24) -> .252 (2025), 12 personnel .238 -> .309, WR3 pts/g
5.4 -> 3.8; 2026 W1-4 TE 10.83 pts per team-game (highest W1-4 on record). The shadow is fitted on 2019-25 equally, so it
cannot see an era shift. Walk-forward league TE level, known before the game:
  L(Y, wk) = blend of last season's TE pts per team-game and this season's weeks < wk (weight g / (g + 6)), divided by the
             average of all prior seasons (2016 .. Y-1)
TE rows x L^e (e .5 / 1 / 1.5); also a WR3-side mirror (WR rows ranked 3+ on the depth string x L^-e) to check the other half.
Honest next-game replica, LOYO + forward (bar 5/7 + 3/4, < -0.3%), board guard, ADP bands cubed, rank line. Log te_era.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import research_te_trend as TT
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "te_era.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    # league TE points per team-game by (season, week)
    tewk = {}; gms = {}
    for Y in range(2016, 2026):
        d = TT.season_rows(Y)
        te = d[d.pos == "TE"].groupby("week").pts.sum(); g = d.groupby("week").apply(lambda x: x.groupby(["game_id", "posteam"]).ngroups)
        for w in g.index: tewk[(Y, int(w))] = float(te.get(w, 0.0)); gms[(Y, int(w))] = int(g[w])
    seas = {Y: sum(v for (y, w), v in tewk.items() if y == Y) / max(1, sum(v for (y, w), v in gms.items() if y == Y)) for Y in range(2016, 2026)}
    P("TE pts per team-game by season: " + " ".join(f"{Y}:{v:.2f}" for Y, v in seas.items()))
    def L(Y, wk):
        prior_avg = np.mean([seas[y] for y in range(2016, Y)]); last = seas[Y - 1]
        cur_p = sum(tewk.get((Y, w), 0.0) for w in range(1, wk)); cur_g = sum(gms.get((Y, w), 0) for w in range(1, wk))
        gw = cur_g / 32.0   # team-games -> weeks
        cur = cur_p / cur_g if cur_g else last
        lvl = (6.0 * last + gw * cur) / (6.0 + gw) if cur_g else last
        return lvl / prior_avg
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, adp = X["act"], X["year"], X["wk"], X["pos"], X["adp"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & (adpx <= 150)].mean()
    wt2 = np.maximum(0.05, lv) ** 2; wt3 = np.maximum(0.05, lv) ** 3
    TODAY, LV = BR.live_today(X); SH, _ = BR.shadow_current(X)
    base = (adpx <= 150) & ~final & ~LV["inh"] & (SH >= 3)
    Lv = np.array([L(int(year[i]), int(wk[i])) if year[i] >= 2017 else 1.0 for i in range(n)])
    te = base & (pos == "TE")
    P(f"TE rows {int(te.sum()):,} | act/shadow by season: " + " ".join(f"{y}:{act[te & (year == y)].sum()/SH[te & (year == y)].sum():.3f} (L {Lv[te & (year == y)].mean():.3f})" for y in YEARS))
    P(f"  corr across seasons of (act/shadow) with L: {np.corrcoef([act[te & (year == y)].sum()/SH[te & (year == y)].sum() for y in YEARS], [Lv[te & (year == y)].mean() for y in YEARS])[0,1]:+.2f}")
    strb = F["strb"]; wr3 = base & (pos == "WR") & (strb >= 3)
    P(f"WR3+ rows {int(wr3.sum()):,} | act/shadow by season: " + " ".join(f"{y}:{act[wr3 & (year == y)].sum()/max(1e-9, SH[wr3 & (year == y)].sum()):.3f}" for y in YEARS))
    w2 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt2[m])) if m.any() else np.nan
    w3 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt3[m])) if m.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    t100 = base & (adpx <= 100)
    def test(title, m, preds):
        b0 = preds["off"]; names = list(preds)
        pick = lambda yrs: min(names, key=lambda kk: w2(preds[kk], m & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = b0.copy()
            for tr_, te_ in folds:
                kk = pick(tr_); picks.append(kk); mx = year == te_; pr[mx] = preds[kk][mx]; wins += w2(preds[kk], m & mx) < w2(b0, m & mx) - 1e-12
            tem = np.isin(year, [te_ for _, te_ in folds]); return 100 * (w2(pr, m & tem) / w2(b0, m & tem) - 1), 100 * (w2(pr, base & tem) / w2(b0, base & tem) - 1), wins, picks, pr
        lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
        okk = best != "off" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
        P(f"\n  {title}  (rows {int(m.sum()):,})")
        for kk in names[1:]:
            p = preds[kk]
            bands = " ".join(f"{bl}:{100*(w3(p, base & bm)/w3(b0, base & bm)-1):+.2f}" for bl, bm in (("1-12", adpx <= 12), ("13-30", (adpx > 12) & (adpx <= 30)), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100)), ("101-150", adpx > 100)))
            P(f"    {kk:14s} rows {100*(w2(p, m)/w2(b0, m)-1):+.2f}% ({sum(1 for y in YEARS if w2(p, m & (year == y)) < w2(b0, m & (year == y)) - 1e-12)}/7) | top-100 cubed {100*(w3(p, t100)/w3(b0, t100)-1):+.3f}% | {bands}")
        P("    " + RG.rank_line(preds, m, act, year, wk, pos))
        P(f"    LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | top-100 cubed {100*(w3(lo[4], t100)/w3(b0, t100)-1):+.3f}% | picks {lo[3]}")
        P(f"    FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}")
        P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
    preds = {"off": SH}
    for e in (0.5, 1.0, 1.5): preds[f"TE x L^{e}"] = np.where(te, SH * np.power(Lv, e), SH)
    for k in (1.02, 1.03, 1.04): preds[f"TE flat x{k}"] = np.where(te, SH * k, SH)
    test("A  TE level follows the league TE era (walk-forward)", te, preds)
    fbp = F["fb_pos"]; hist = F["hist"]; h3 = np.array(F["has_h3"], bool); ratio = np.where(fbp > 0, np.nan_to_num(hist) / fbp, 0)
    prov = te & h3 & (ratio >= 1.6)
    preds = {"off": SH}
    for k in (1.02, 1.03, 1.04, 1.06): preds[f"proven x{k}"] = np.where(prov, SH * k, SH)
    for e in (0.5, 1.0): preds[f"proven x L^{e}"] = np.where(prov, SH * np.power(Lv, e), SH)
    test("B  proven TEs (3 seasons, 1.6x+ the TE mean): flat lift / era lift", prov, preds)
    preds = {"off": SH}
    for e in (0.5, 1.0): preds[f"WR3+ x L^-{e}"] = np.where(wr3, SH * np.power(Lv, -e), SH)
    test("C  WR3+ (depth string 3+) mirror: down when the TE era is up", wr3, preds)
    P("\nLimitations: honest replica, next game, no book anchor; league TE level from play-by-play receiving points (half PPR); 2016 starts the prior average; 2026 W1-4 sits at 10.83 TE pts per team-game vs 2016-25 average ~9.9.")
    LOG.close()


if __name__ == "__main__":
    main()
