#!/usr/bin/env python3
"""
TEAM VACATED BOOST (Jack 2026-10-08: "if the other receivers dont get a massive boost based on injury does the qb get a massive
nerf?" -> "can we test this" -> "or else other teammates need a larger boost overall unless they all get a slight boost and it all
adds up"). backtest_qb_vacated_targets.py: QBs are NOT nerfed (act/base 1.03-1.08 with 30%+ of targets missing, every dock fails);
the healthy pass catchers together run 1.08 (vacated .20-.30), 1.09 (.30-.40), 1.23 (.40+), 1.17 (2+ regulars out) - the top
remaining 1.04-1.12, everyone else ~1.20.

Base here = the shadow replica (pool .75 inside) x the WIRED next-man-up cells x the WIRED promoted-backup multipliers (RB 1.034 /
WR 1.071 / TE 1.207 when a same-position regular is out), so the test is what is left after today's layers.
Variant: every healthy WR / TE / RB on the team that week x (1 + k x vacated target share), vacated = sum of the trailing-3 target
shares of the team's pass catchers (share >= .10) with no row this week; k grid; optional floor (only when vacated >= .15).
Grading: rows RB/WR/TE shadow >= 1, final week out; LOYO + forward pick-best, bar LOYO < -0.3% on touched rows 5/7, forward 3/4,
board not worse. Log team_vacated_boost.log.
"""
import json, os, sys, warnings
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
cal = BR.cal; YEARS = BR.YEARS; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "team_vacated_boost" + ("_car" if os.environ.get("TV_CAR") == "1" else "") + ".log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()
SK = ("RB", "WR", "TE"); REG_MIN = 5.0; PROMO = {"RB": 1.034, "WR": 1.071, "TE": 1.207}


def week_team(Y, w, opp):
    o = cal.OPP_ALIAS.get(opp, opp)
    for t, s in cal.SCHEDULES.get(Y, {}).items():
        if s.get(str(w)) == o: return t
    return None


def tables():
    """targets per team-week, plus promoted-backup flags (regular ahead out) per (norm, Y, wk)"""
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    tg = defaultdict(dict); cg = defaultdict(dict); tcache = {}; roster = defaultdict(list); games = {}
    for Y in YEARS:
        W = 16 if Y <= 2020 else 17
        for nm, c in (ch.get(str(Y)) or {}).items():
            ps = c.get("pos")
            if ps not in SK: continue
            rec = cal.weekly_rec(nm, ps)
            if rec is None: continue
            team = cal.infer_team(rec, Y)
            gmv = (c.get("gm") or 0); half = max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0)
            cpg = half / gmv if gmv >= 4 else half / W
            gl = {}
            for w in rec.get("seasons", {}).get(str(Y), []):
                if not (cal.played(w) and w.get("opp")): continue
                k = (Y, int(w["wk"]), w["opp"])
                if k not in tcache: tcache[k] = week_team(Y, int(w["wk"]), w["opp"])
                tw = tcache[k]
                if tw: tg[(Y, tw, int(w["wk"]))][(nm, ps)] = float(w.get("tgt") or 0); cg[(Y, tw, int(w["wk"]))][(nm, ps)] = float(w.get("ra") or 0); gl[int(w["wk"])] = tw
            games[(nm, ps, Y)] = (team, cpg, gl)
            if team: roster[(Y, team, ps)].append((nm, cpg))
    promo = set()
    for (nm, ps, Y), (team, cpg, gl) in games.items():
        if not team: continue
        regs = [r for r, rc in roster[(Y, team, ps)] if r != nm and rc > cpg and rc >= REG_MIN]
        rplay = {r: {w for w, t in games[(r, ps, Y)][2].items() if t == team} for r in regs}
        for w, t in gl.items():
            if t == team and any(w not in rplay[r] for r in regs): promo.add((cal.norm(nm), Y, w))
    return tg, promo, cg


def main():
    X = BR.SN.setup(); n = X["n"]
    act, year, wk, pos, name, adp, team = X["act"], X["year"], X["wk"], X["pos"], X["name"], X["adp"], X["team"]
    SH, _ = BR.shadow_current(X)
    finw = np.where(year <= 2020, 17, 18)
    # wired NMU cells (log of research_next_man_up preserved)
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
        NMU[i] = 1.04 if r["rank"] == 1 else 0.99 if r["rank"] <= 3 else 1.03
    tg, promo, cg = tables()
    PR = np.ones(n)
    for i in range(n):
        if pos[i] in PROMO and (cal.norm(name[i]), int(year[i]), int(wk[i])) in promo: PR[i] = PROMO[pos[i]]
    B0 = SH * NMU * PR
    # team vacated target share per team-week
    team_wks = defaultdict(list)
    for (Y, t, w) in tg: team_wks[(Y, t)].append(w)
    for k in team_wks: team_wks[k].sort()
    vcache = {}
    def vac_of(Y, t, w):
        key = (Y, t, w)
        if key in vcache: return vcache[key]
        v_ = np.nan
        if (Y, t, w) in tg:
            prior = [u for u in team_wks.get((Y, t), []) if u < w][-3:]
            if len(prior) >= 2:
                tot = 0.0; by = defaultdict(float); gp = defaultdict(int)
                for u in prior:
                    for kk, v in tg[(Y, t, u)].items(): tot += v; by[kk] += v; gp[kk] += 1
                if tot >= 30: v_ = sum(v / tot for kk, v in by.items() if gp[kk] >= 2 and v / tot >= 0.10 and kk not in tg[(Y, t, w)])
        vcache[key] = v_; return v_
    vac = np.array([vac_of(int(year[i]), team[i], int(wk[i])) if (team[i] and pos[i] in SK) else np.nan for i in range(n)])
    ccache = {}
    def cvac_of(Y, t, w):
        key = (Y, t, w)
        if key in ccache: return ccache[key]
        v_ = 0.0
        if (Y, t, w) in cg:
            prior = [u for u in team_wks.get((Y, t), []) if u < w][-3:]
            if len(prior) >= 2:
                tot = 0.0; by = defaultdict(float); gp = defaultdict(int)
                for u in prior:
                    for kk, v in cg.get((Y, t, u), {}).items():
                        if kk[1] != 'RB': continue
                        tot += v; by[kk] += v; gp[kk] += 1
                if tot >= 30: v_ = sum(v / tot for kk, v in by.items() if gp[kk] >= 2 and v / tot >= 0.10 and kk not in cg[(Y, t, w)])
        ccache[key] = v_; return v_
    cvac = np.array([cvac_of(int(year[i]), team[i], int(wk[i])) if (team[i] and pos[i] in SK) else 0.0 for i in range(n)])
    ok = np.isin(pos, SK) & (wk != finw) & (SH >= 1) & np.isfinite(act) & np.isfinite(vac)
    P(f"rows {ok.sum()} RB/WR/TE player-weeks with a team read; base = shadow x NMU x PROMO")
    for lab, m in (("nobody out", ok & (vac == 0)), ("vac .01-.20", ok & (vac > 0) & (vac < .20)), ("vac .20-.30", ok & (vac >= .20) & (vac < .30)),
                   ("vac .30-.40", ok & (vac >= .30) & (vac < .40)), ("vac .40+", ok & (vac >= .40))):
        P(f"  {lab:12s} n{int(m.sum()):6d} actual / base {act[m].sum()/B0[m].sum():.3f} | " + " ".join(f"{ps} {act[m & (pos == ps)].sum()/max(1e-9, B0[m & (pos == ps)].sum()):.2f}" for ps in SK))
    mse = lambda p, m: float(np.mean((p[m] - act[m]) ** 2))
    if os.environ.get('TV_CAR') == '1':
        B0 = B0 * np.where(ok, 1 + 0.2 * np.nan_to_num(vac), 1.0)
        rbm = ok & (pos == 'RB')
        P(f"CARRY TEST: base = shipped (target tvac .2 on); RB rows with carry vacated > 0: {int((rbm & (cvac > 0)).sum())}")
        for lab, m in (("RB no RB out", rbm & (cvac == 0)), ("RB cvac .10-.40", rbm & (cvac > 0) & (cvac < .40)), ("RB cvac .40-.70", rbm & (cvac >= .40) & (cvac < .70)), ("RB cvac .70+", rbm & (cvac >= .70)),
                       ("WR/TE when RB out", ok & np.isin(pos, ('WR', 'TE')) & (cvac >= .40))):
            if m.sum() >= 5: P(f"  {lab:20s} n{int(m.sum()):5d} actual / base {act[m].sum()/B0[m].sum():.3f}")
        preds = {"off": B0}
        for k in (0.05, 0.10, 0.15, 0.20, 0.30):
            preds[f"rbk{k}"] = B0 * np.where(rbm, 1 + k * cvac, 1.0)
        touched = rbm & (cvac > 0)
        names = list(preds)
        mse = lambda p, m: float(np.mean((p[m] - act[m]) ** 2))
        def pick(yrs): return min(names, key=lambda kk: mse(preds[kk], ok & np.isin(year, yrs)))
        for label, folds in (("LOYO", [(tuple(y for y in YEARS if y != t), t) for t in YEARS]), ("FORWARD", [(tuple(y for y in YEARS if y < t), t) for t in FWD])):
            wins = 0; a0 = a1 = b0 = b1 = 0.0; picks = []
            for tr, te in folds:
                kk = pick(tr); picks.append(kk); r = touched & (year == te); w_ = ok & (year == te)
                e0, e1 = mse(B0, r), mse(preds[kk], r); wins += int(e1 < e0)
                a0 += e0 * r.sum(); a1 += e1 * r.sum(); b0 += mse(B0, w_) * w_.sum(); b1 += mse(preds[kk], w_) * w_.sum()
            P(f"{label}: touched RB rows {100*(a1/a0-1):+.2f}% ({wins}/{len(folds)}), board {100*(b1/b0-1):+.3f}% | picks {picks}")
        P("fixed: " + "  ".join(f"{kk} {100*(mse(preds[kk], touched)/mse(B0, touched)-1):+.2f}%" for kk in names[1:]))
        LOG.close(); return
    preds = {"off": B0}
    for k in (0.10, 0.20, 0.30, 0.40, 0.50):
        preds[f"k{k}"] = B0 * np.where(ok, 1 + k * np.nan_to_num(vac), 1.0)
        preds[f"k{k}f"] = B0 * np.where(ok & (vac >= 0.15), 1 + k * np.nan_to_num(vac), 1.0)
    for t0 in (0.20, 0.30):
        for k in (0.3, 0.5, 0.8):
            preds[f"t{t0}k{k}"] = B0 * np.where(ok, 1 + k * np.maximum(0, np.nan_to_num(vac) - t0), 1.0)
    for k in (0.3, 0.5, 0.8):
        preds[f"sq{k}"] = B0 * np.where(ok, 1 + k * np.nan_to_num(vac) ** 2, 1.0)
    touched = ok & (vac > 0)
    names = list(preds)
    def pick(yrs): return min(names, key=lambda kk: mse(preds[kk], ok & np.isin(year, yrs)))
    for label, folds in (("LOYO", [(tuple(y for y in YEARS if y != t), t) for t in YEARS]), ("FORWARD", [(tuple(y for y in YEARS if y < t), t) for t in FWD])):
        wins = 0; a0 = a1 = b0 = b1 = 0.0; picks = []
        for tr, te in folds:
            kk = pick(tr); picks.append(kk); r = touched & (year == te); w_ = ok & (year == te)
            e0, e1 = mse(B0, r), mse(preds[kk], r); wins += int(e1 < e0)
            a0 += e0 * r.sum(); a1 += e1 * r.sum(); b0 += mse(B0, w_) * w_.sum(); b1 += mse(preds[kk], w_) * w_.sum()
        P(f"{label}: touched rows {100*(a1/a0-1):+.2f}% ({wins}/{len(folds)}), board {100*(b1/b0-1):+.3f}% | picks {picks}")
    P("fixed (all seasons, touched rows): " + "  ".join(f"{kk} {100*(mse(preds[kk], touched)/mse(B0, touched)-1):+.2f}%" for kk in names[1:]))
    P("best all seasons: " + pick(YEARS))
    LOG.close()


if __name__ == "__main__":
    main()
