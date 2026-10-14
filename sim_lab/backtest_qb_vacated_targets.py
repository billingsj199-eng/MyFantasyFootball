#!/usr/bin/env python3
"""
QB WHEN SEVERAL PASS CATCHERS ARE OUT (Jack 2026-10-08: "so if the other receivers dont get a massive boost based on injury does
the qb get a massive nerf?" -> "can we test this"). Follow-up to backtest_qb_leadwr_out.py (lead receiver alone: actual / base
1.003 at share >= .20 - REJECTED). Here the event is the TOTAL target share the team is missing: every WR / TE / RB with a trailing
share >= .10 (last 3 team games, 2+ played) who has no played row this week; bands by vacated share and by how many are out.
Rows / base / grading exactly as backtest_qb_leadwr_out.py: top-150 QB player-weeks 2019-25 (final week dropped, inherit rows
out), base = blend as wired (QB .5 shadow + .5 live), weighted error LOYO + forward, bar 5/7 + 3/4, board guard, rank line.
Log qb_vacated_targets.log.
"""
import json, os, sys, warnings
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; cal = SN.NW.cal; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "qb_vacated_targets.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
BBW = {"QB": 0.5, "RB": 0.8, "WR": 0.7, "TE": 0.3}
MIN_SHARE = 0.10


def week_team(Y, w, opp):
    o = cal.OPP_ALIAS.get(opp, opp)
    for t, s in cal.SCHEDULES.get(Y, {}).items():
        if s.get(str(w)) == o: return t
    return None


def receiver_table():
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    tg = defaultdict(dict); tcache = {}
    for Y in YEARS:
        for nm, c in (ch.get(str(Y)) or {}).items():
            ps = c.get("pos")
            if ps not in ("WR", "TE", "RB"): continue
            rec = cal.weekly_rec(nm, ps)
            if rec is None: continue
            for w in rec.get("seasons", {}).get(str(Y), []):
                if not (cal.played(w) and w.get("opp")): continue
                k = (Y, int(w["wk"]), w["opp"])
                if k not in tcache: tcache[k] = week_team(Y, int(w["wk"]), w["opp"])
                tw = tcache[k]
                if tw: tg[(Y, tw, int(w["wk"]))][(nm, ps)] = float(w.get("tgt") or 0)
    return tg


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["team"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    bw = np.array([BBW[p_] for p_ in pos]); BASE = bw * SHADOW + (1 - bw) * TODAY
    base = top150 & ~final & ~LV["inh"] & (g >= 1) & (BASE >= 3)
    QB = base & (pos == "QB")
    tg = receiver_table()
    team_wks = defaultdict(list)
    for (Y, t, w) in tg: team_wks[(Y, t)].append(w)
    for k in team_wks: team_wks[k].sort()
    vac = np.full(n, np.nan); nout = np.zeros(n, int)
    for i in np.where(QB)[0]:
        Y, t, w = int(year[i]), team[i], int(wk[i])
        if not t or (Y, t, w) not in tg: continue
        prior = [u for u in team_wks.get((Y, t), []) if u < w][-3:]
        if len(prior) < 2: continue
        tot = 0.0; by = defaultdict(float); gp = defaultdict(int)
        for u in prior:
            for key, v in tg[(Y, t, u)].items():
                tot += v; by[key] += v; gp[key] += 1
        if tot < 30: continue
        v_ = 0.0; k_ = 0
        for key, v in by.items():
            if gp[key] >= 2 and v / tot >= MIN_SHARE and key not in tg[(Y, t, w)]:
                v_ += v / tot; k_ += 1
        vac[i] = v_; nout[i] = k_
    wm = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    has = QB & ~np.isnan(vac)
    P(f"=== QB x VACATED TARGET SHARE: {int(QB.sum()):,} top-150 QB rows 2019-25, {int(has.sum()):,} with a receiver read ===")
    P("\n--- 1  BIAS: actual / base (1.00 = the projection is right) ---")
    bands = (("nobody out", has & (nout == 0)), ("any regular out", has & (nout >= 1)), ("vacated .10-.20", has & (vac >= .10) & (vac < .20)),
             ("vacated .20-.30", has & (vac >= .20) & (vac < .30)), ("vacated .30-.40", has & (vac >= .30) & (vac < .40)), ("vacated .40+", has & (vac >= .40)),
             ("2+ regulars out", has & (nout >= 2)), ("3+ regulars out", has & (nout >= 3)))
    for lab, bm in bands:
        if bm.sum() < 5: P(f"  {lab:18s} n{int(bm.sum())}"); continue
        ys = [(y, act[bm & (year == y)].sum() / BASE[bm & (year == y)].sum(), int((bm & (year == y)).sum())) for y in YEARS if (bm & (year == y)).sum() >= 4]
        P(f"  {lab:18s} n{int(bm.sum()):5d} act {act[bm].mean():5.2f} base {BASE[bm].mean():5.2f} -> {act[bm].sum()/BASE[bm].sum():.3f} | under 1 in {sum(1 for _, r, _ in ys if r < 1)}/{len(ys)} | " + " ".join(f"{y}:{r:.2f}(n{c})" for y, r, c in ys))
    for lab, bm in (("vac .30+ QB ADP <= 60", has & (vac >= .30) & (adpx <= 60)), ("vac .30+ QB ADP 61-150", has & (vac >= .30) & (adpx > 60))):
        if bm.sum() >= 5: P(f"  {lab:24s} n{int(bm.sum()):4d} -> {act[bm].sum()/BASE[bm].sum():.3f}")
    # --- 1b  WHERE THE PRODUCTION GOES (Jack: "or else other teammates need a larger boost overall unless they all get a slight
    # boost and it all adds up"): the healthy WR / TE / RB who played in those team-weeks, summed - actual vs base (the base already
    # carries the vacated pool + promotions as the replica has them), per band. 1.00 = the team's receiving points are where we put them.
    P("\n--- 1b  HEALTHY PASS CATCHERS (summed per team-week, all of them with base >= 1): actual / base ---")
    rows_tw = defaultdict(list)
    okr = (~final) & np.isin(pos, ("WR", "TE", "RB")) & (BASE >= 1)
    for i in np.where(okr)[0]:
        if team[i]: rows_tw[(int(year[i]), team[i], int(wk[i]))].append(i)
    for lab, bm in bands:
        A_ = B_ = 0.0; nt = 0; per_y = defaultdict(lambda: [0.0, 0.0])
        for i in np.where(bm)[0]:
            ks = rows_tw.get((int(year[i]), team[i], int(wk[i])), [])
            if not ks: continue
            a = act[ks].sum(); b = BASE[ks].sum(); A_ += a; B_ += b; nt += 1; per_y[int(year[i])][0] += a; per_y[int(year[i])][1] += b
            # each healthy teammate individually by role: top remaining (largest base) vs the rest
        if nt >= 5:
            P(f"  {lab:18s} team-weeks {nt:5d} -> receivers {A_/B_:.3f} | " + " ".join(f"{y}:{v[0]/v[1]:.2f}" for y, v in sorted(per_y.items()) if v[1] > 0))
    # split: the top remaining pass catcher vs everyone else, on the bigger vacated bands
    for lab, bm in (("vacated .30+", has & (vac >= .30)), ("2+ regulars out", has & (nout >= 2))):
        top_a = top_b = rest_a = rest_b = 0.0
        for i in np.where(bm)[0]:
            ks = rows_tw.get((int(year[i]), team[i], int(wk[i])), [])
            if not ks: continue
            ks = sorted(ks, key=lambda j: -BASE[j]); top_a += act[ks[0]]; top_b += BASE[ks[0]]
            rest_a += act[ks[1:]].sum(); rest_b += BASE[ks[1:]].sum()
        if top_b > 0 and rest_b > 0: P(f"  {lab:18s} top remaining receiver {top_a/top_b:.3f} | everyone else {rest_a/rest_b:.3f}")
    P("\n--- 2  DOCKS on the event rows, graded on all top-150 QB rows; LOYO + forward, bar 5/7 + 3/4 ---")
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    def test(title, preds, m, touched):
        names = list(preds); b0 = preds["off"]; pick = lambda yrs: min(names, key=lambda kk: wm(preds[kk], m & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = b0.copy()
            for tr_, te in folds:
                kk = pick(tr_); picks.append(kk); mm = year == te; pr[mm] = preds[kk][mm]; wins += wm(preds[kk], m & mm) < wm(b0, m & mm) - 1e-12
            tem = np.isin(year, [te for _, te in folds]); return 100 * (wm(pr, m & tem) / wm(b0, m & tem) - 1), 100 * (wm(pr, base & tem) / wm(b0, base & tem) - 1), wins, picks
        lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
        okk = best != "off" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
        P(f"\n  {title} (touched {int(touched.sum())}, actual/base on them {act[touched].sum()/max(1e-9, b0[touched].sum()):.3f})")
        P("    fixed: " + "  ".join(f"{kk}: {100*(wm(preds[kk], m)/wm(b0, m)-1):+.2f}%" for kk in names[1:]))
        P("    " + RG.rank_line(preds, m, act, year, wk, pos))
        P(f"    LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | picks {lo[3]}"); P(f"    FWD  {fw[0]:+.2f}% {fw[2]}/4 | picks {fw[3]}"); P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
    for lab, ev in (("vacated >= .30", has & (vac >= .30)), ("vacated >= .40", has & (vac >= .40)), ("2+ regulars out", has & (nout >= 2))):
        preds = {"off": BASE}
        for f in (0.97, 0.95, 0.92, 0.88): p = BASE.copy(); p[ev] = BASE[ev] * f; preds[f"x{f}"] = p
        for k in (0.15, 0.25, 0.35): p = BASE.copy(); p[ev] = BASE[ev] * np.clip(1 - k * vac[ev], 0.8, 1.0); preds[f"1-{k}xvac"] = p
        test(lab, preds, QB, ev)
    LOG.close()


if __name__ == "__main__":
    main()
