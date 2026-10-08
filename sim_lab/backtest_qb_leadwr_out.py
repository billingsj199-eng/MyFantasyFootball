#!/usr/bin/env python3
"""
QB DOCK WHEN THE LEAD RECEIVER IS OUT (Jack 2026-10-04 "don't you think sims should dock if best WR is out?"; engine test
2026-10-08 "run 1"). The 10-04 scratch study: QBs score 4-6% less in games their lead WR misses (2019-25, 97 / 66 games).
The sim leaves the QB untouched when a receiver is ruled out (vacated work only moves to the other pass catchers).

Rows: top-150 QB player-weeks 2019-25 (final week dropped, inherit rows out), base = blended number as wired
(QB .5 shadow + .5 live). Lead receiver for a team-week = the WR (variant: WR or TE) with the most targets over the
team's last 3 games before the week (needs 2+ team games, share of the team's targets in those games). Event = he has no
played row this week (healthy scratch, injury, suspension - the live engine would know the OUT flag).
  bias: actual / base on event rows vs the rest, by share band and by season
  multipliers: flat f on event rows (share >= .20, >= .25), graded 1 - k x share; WR-only and WR+TE lead
  grading: weighted error LOYO + forward (bar 5/7 + 3/4, whole-board guard) and the rank objective. Log qb_leadwr_out.log.
"""
import json, os, sys, warnings
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import backtest_qb_injury_usage as QI
import rank_grade as RG
SN = BR.SN; cal = SN.NW.cal; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "qb_leadwr_out.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
BBW = {"QB": 0.5, "RB": 0.8, "WR": 0.7, "TE": 0.3}


def receiver_table():
    """(Y, team, wk) -> {(name, pos): targets} for every WR / TE / RB with a played row (Clay pool names); team from the schedule"""
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    tg = defaultdict(dict); tcache = {}
    for Y in YEARS:
        pool = ch.get(str(Y)) or {}
        for nm, c in pool.items():
            ps = c.get("pos")
            if ps not in ("WR", "TE", "RB"): continue
            rec = cal.weekly_rec(nm, ps)
            if rec is None: continue
            for w in rec.get("seasons", {}).get(str(Y), []):
                if not (cal.played(w) and w.get("opp")): continue
                k = (Y, int(w["wk"]), w["opp"])
                if k not in tcache: tcache[k] = QI.week_team(Y, int(w["wk"]), w["opp"])
                tw = tcache[k]
                if tw: tg[(Y, tw, int(w["wk"]))][(nm, ps)] = float(w.get("tgt") or 0)
    return tg


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, team, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["team"], X["name"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    bw = np.array([BBW[p_] for p_ in pos]); BASE = bw * SHADOW + (1 - bw) * TODAY
    base = top150 & ~final & ~LV["inh"] & (g >= 1) & (BASE >= 3)
    QB = base & (pos == "QB")
    tg = receiver_table(); P(f"receiver table: {len(tg):,} team-weeks")
    team_wks = defaultdict(list)
    for (Y, t, w) in tg: team_wks[(Y, t)].append(w)
    for k in team_wks: team_wks[k].sort()
    # lead receiver per QB row
    def lead_of(Y, t, w, kinds):
        prior = [u for u in team_wks.get((Y, t), []) if u < w][-3:]
        if len(prior) < 2: return None
        tot = 0.0; by = defaultdict(float)
        for u in prior:
            for (nm, ps), v in tg[(Y, t, u)].items():
                tot += v
                if ps in kinds: by[(nm, ps)] += v
        if tot < 30 or not by: return None
        (nm, ps), v = max(by.items(), key=lambda kv: kv[1])
        return nm, ps, v / tot
    OUT = {}; SHARE = {}; LEADPTS = {}
    for kinds, lab in ((("WR",), "WR"), (("WR", "TE"), "WRTE")):
        out = np.zeros(n, bool); share = np.full(n, np.nan); lpts = np.full(n, np.nan)
        for i in np.where(QB)[0]:
            Y, t, w = int(year[i]), team[i], int(wk[i])
            if not t or (Y, t, w) not in tg: continue           # team must have played (QB row exists, so it did unless the table is missing it)
            L = lead_of(Y, t, w, kinds)
            if L is None: continue
            nm, ps, sh = L; share[i] = sh; out[i] = (nm, ps) not in tg[(Y, t, w)]
        OUT[lab] = out; SHARE[lab] = share
    wm = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    RS = lambda p, m: RG.rank_stats(p, m, act, year, wk, pos)
    P(f"\n=== QB x LEAD RECEIVER OUT: {int(QB.sum()):,} top-150 QB player-weeks 2019-25, base = blend as wired ===")
    P("\n--- 1  BIAS: actual / base (1.00 = right level) ---")
    for lab in ("WR", "WRTE"):
        out, sh = OUT[lab], SHARE[lab]; has = QB & ~np.isnan(sh)
        P(f"  lead = {lab}: rows with a lead read {int(has.sum()):,}; lead out {int((has & out).sum())} ({100*(has & out).sum()/max(1, has.sum()):.1f}%)")
        for blab, bm in (("lead in", has & ~out), ("lead out, any share", has & out), ("lead out, share >= .20", has & out & (sh >= 0.20)), ("lead out, share >= .25", has & out & (sh >= 0.25)), ("lead out, share < .20", has & out & (sh < 0.20))):
            if bm.sum() < 10: P(f"    {blab:28s} n{int(bm.sum())}"); continue
            ys = [(y, act[bm & (year == y)].sum() / BASE[bm & (year == y)].sum(), int((bm & (year == y)).sum())) for y in YEARS if (bm & (year == y)).sum() >= 5]
            P(f"    {blab:28s} n{int(bm.sum()):5d} act {act[bm].mean():5.2f} base {BASE[bm].mean():5.2f} -> {act[bm].sum()/BASE[bm].sum():.3f} | under 1 in {sum(1 for _, r, _ in ys if r < 1)}/{len(ys)} seasons | " + " ".join(f"{y}:{r:.2f}(n{c})" for y, r, c in ys))
        # by QB tier
        for tlab, tm in (("QB ADP <= 60", has & out & (adpx <= 60)), ("QB ADP 61-150", has & out & (adpx > 60)), ("base >= 18", has & out & (BASE >= 18)), ("base < 18", has & out & (BASE < 18))):
            if tm.sum() >= 10: P(f"    {tlab:28s} n{int(tm.sum()):5d} -> {act[tm].sum()/BASE[tm].sum():.3f}")
    P("\n--- 2  MULTIPLIERS on the event rows, graded on ALL top-150 QB rows (error) + whole-board guard + rank; LOYO + forward, bar 5/7 + 3/4 ---")
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    def test(title, preds, m, touched):
        names = list(preds); b0 = preds["off"]; pick = lambda yrs: min(names, key=lambda kk: wm(preds[kk], m & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = b0.copy()
            for tr_, te in folds:
                kk = pick(tr_); picks.append(kk); mm = year == te; pr[mm] = preds[kk][mm]; wins += wm(preds[kk], m & mm) < wm(b0, m & mm) - 1e-12
            tem = np.isin(year, [te for _, te in folds]); return 100 * (wm(pr, m & tem) / wm(b0, m & tem) - 1), 100 * (wm(pr, base & tem) / wm(b0, base & tem) - 1), wins, picks
        lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
        fixed = "  ".join(f"{kk}: {100*(wm(preds[kk], m)/wm(b0, m)-1):+.2f}% ({sum(1 for y in YEARS if wm(preds[kk], m & (year == y)) < wm(b0, m & (year == y)) - 1e-12)}/7)" for kk in names[1:])
        okk = best != "off" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
        P(f"\n  {title} (QB rows {int(m.sum()):,}, touched {int(touched.sum())}, actual/base on touched {act[touched].sum()/b0[touched].sum():.3f})")
        P(f"    fixed (all QB rows): {fixed}")
        P(f"    on the touched rows only: " + "  ".join(f"{kk}: {100*(wm(preds[kk], touched)/wm(b0, touched)-1):+.2f}% ({sum(1 for y in YEARS if (touched & (year == y)).sum() >= 5 and wm(preds[kk], touched & (year == y)) < wm(b0, touched & (year == y)) - 1e-12)}/{sum(1 for y in YEARS if (touched & (year == y)).sum() >= 5)})" for kk in names[1:]))
        P("    " + RG.rank_line(preds, m, act, year, wk, pos) + " | seasons rank better: " + " ".join(f"{kk} {RG.rank_seasons(preds[kk], b0, m, act, year, wk, pos, YEARS)}/7" for kk in names[1:]))
        P(f"    LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | picks {lo[3]}"); P(f"    FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}"); P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
    for lab in ("WR", "WRTE"):
        out, sh = OUT[lab], SHARE[lab]
        for slab, smin in (("share >= .20", 0.20), ("share >= .25", 0.25)):
            ev = QB & out & (sh >= smin); preds = {"off": BASE}
            for f in (0.97, 0.95, 0.93, 0.90): p = BASE.copy(); p[ev] = BASE[ev] * f; preds[f"x{f}"] = p
            for k in (0.15, 0.25): p = BASE.copy(); p[ev] = BASE[ev] * np.clip(1 - k * sh[ev], 0.85, 1.0); preds[f"1-{k}xshare"] = p
            test(f"lead {lab} out, {slab}", preds, QB, ev)
    P("\nLimitations: 'out' = no played row (injury, scratch, suspension alike); lead from the last 3 team games' targets (Clay-pool receivers only); the blend already carries Vegas / FPA; book anchor not replayed. The live engine would apply the dock only on an OUT / IR flag, a subset of these events.")
    LOG.close()


if __name__ == "__main__":
    main()
