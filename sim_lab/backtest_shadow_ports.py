#!/usr/bin/env python3
"""
SHADOW PORTS (Jack 2026-10-07 "let's do it in order", items 2 and 3).  On the harness shadow (SN.shadow form, 2019-25,
top-150 weighted, LOYO + forward, bar 5/7 + 3/4):
  2   QB-OUT DOCK SCOPE   the WR dock (.85 ADP <= 60 / .95) applies every week the team's regular QB is out. Today's
                          graded-dock test said it is right in the first week and wrong once the replacement has
                          started 2+ weeks. Variants: first week only; first two weeks; taper .85 / .92 / 1.
  3a  HURT GAMES x.5 IN THE USAGE INPUTS   the shadow's usage evidence is xFP/g season to date (WR / RB lam schedule);
                          games he played hurt get half weight in that average (passed on the live form).
  3b  VOLUME CONTEXT      1 - .03 z(script excess) on WR/TE + 1 - .04 z(att/g) on underdogs (passed on the live form;
                          the shadow already Vegas-cleans its evidence, so the size may differ).
Log shadow_ports.log.
"""
import os, sys, warnings
from collections import defaultdict, Counter
import numpy as np, pandas as pd
import rank_grade as RG
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
import backtest_qb_injury_usage as QI
import backtest_volume_context as VC
NW = SN.NW; cal = NW.cal; YEARS = list(NW.YEARS); POS4 = ("QB", "RB", "WR", "TE"); FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "shadow_ports_rank.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, g, adp, name, pid, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], A["pid"], X["team"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    BASE = SN.shadow(X); okN = (g >= 1) & ~final & top150 & (BASE >= 3)
    wm = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    def grade(title, preds, m):
        names = list(preds); b0 = preds["off"]
        pick = lambda yrs: min(names, key=lambda k: wm(preds[k], m & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = b0.copy()
            for tr_, te in folds:
                k = pick(tr_); picks.append(k); mm = year == te; pr[mm] = preds[k][mm]; wins += wm(preds[k], m & mm) < wm(b0, m & mm) - 1e-12
            tem = np.isin(year, [te for _, te in folds]); return 100 * (wm(pr, m & tem) / wm(b0, m & tem) - 1), 100 * (wm(pr, okN & tem) / wm(b0, okN & tem) - 1), wins, picks
        lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
        fixed = "  ".join(f"{k}: {100*(wm(preds[k], m)/wm(b0, m)-1):+.2f}% ({sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and wm(preds[k], m & (year == y)) < wm(b0, m & (year == y)) - 1e-12)}/7)" for k in names[1:])
        pb = preds[best]
        P(f"\n=== {title}: rows {int(m.sum()):,}, actual/shadow {act[m].sum()/b0[m].sum():.3f} ===")
        P(f"    fixed: {fixed}")
        P("    " + RG.rank_line(preds, okN, act, year, wk, pos) + " | seasons rank better: " + " ".join(f"{kk} {RG.rank_seasons(preds[kk], preds['off'], okN, act, year, wk, pos, YEARS)}/7" for kk in names[1:]))
        P(f"    best {best}: " + " | ".join(f"{ps} {100*(wm(pb, m & (pos == ps))/wm(b0, m & (pos == ps))-1):+.2f}% (n{int((m & (pos == ps)).sum())})" for ps in POS4 if (m & (pos == ps)).sum() >= 40) + f" | ADP<=60 {100*(wm(pb, m & (adpx <= 60))/wm(b0, m & (adpx <= 60))-1):+.2f}% | 61-150 {100*(wm(pb, m & (adpx > 60))/wm(b0, m & (adpx > 60))-1):+.2f}%")
        P(f"    LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | picks {lo[3]}")
        P(f"    FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}")
        okk = best != "off" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
        P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
    # ---------------------------------------------------------------- 2  QB-out dock scope
    import json as _json
    Xg = dict(X); Xg["ch"] = _json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    games, roster, starter, team_weeks = QI.build_games(Xg)
    weeks_out = np.full(n, -1)   # how many prior weeks the regular has already been out this stretch (0 = first week)
    for i in np.where(X["qbo"] & (pos == "WR"))[0]:
        Y = int(year[i]); tm_ = team[i]; prior_w = [w for w in team_weeks.get((Y, tm_), []) if w < wk[i]]
        if not prior_w: weeks_out[i] = 0; continue
        cnt = Counter(starter[(Y, tm_, w)] for w in prior_w); top = max(cnt.values()); cands = [q for q, c in cnt.items() if c == top]
        reg = cands[0] if len(cands) == 1 else max(cands, key=lambda q: max(w for w in prior_w if starter[(Y, tm_, w)] == q))
        k = 0
        for w in reversed(prior_w):
            if starter[(Y, tm_, w)] != reg: k += 1
            else: break
        weeks_out[i] = k
    dock0 = np.where(adp <= 60, 0.85, 0.95); undock = np.where((pos == "WR") & X["qbo"], 1.0 / dock0, 1.0)
    NOD = BASE * undock   # the shadow with the dock removed
    mQ = okN & (pos == "WR") & X["qbo"] & (weeks_out >= 0)
    P(f"WR rows with the team's QB out: {int(mQ.sum())}; by weeks already out: " + " | ".join(f"{k}: n{int((mQ & (weeks_out == k)).sum())} act/shadow {act[mQ & (weeks_out == k)].sum()/BASE[mQ & (weeks_out == k)].sum():.3f} act/undocked {act[mQ & (weeks_out == k)].sum()/NOD[mQ & (weeks_out == k)].sum():.3f}" for k in (0, 1, 2, 3) if (mQ & (weeks_out == k)).sum() >= 15) + f" | 4+: n{int((mQ & (weeks_out >= 4)).sum())} act/shadow {act[mQ & (weeks_out >= 4)].sum()/max(1e-9, BASE[mQ & (weeks_out >= 4)].sum()):.3f}")
    def scoped(maxw, taper=None):
        p = NOD.copy(); m = (pos == "WR") & X["qbo"] & (weeks_out >= 0)
        if taper is None: mm = m & (weeks_out <= maxw); p[mm] = NOD[mm] * dock0[mm]
        else:
            for k, f in enumerate(taper):
                mm = m & (weeks_out == k); p[mm] = NOD[mm] * (1 - (1 - dock0[mm]) * f)
        return p
    grade("2  QB-out WR dock scope", {"off": BASE, "no dock at all": NOD, "first week only": scoped(0), "first two weeks": scoped(1), "first three weeks": scoped(2), "taper 1 / .5 / 0": scoped(None, (1.0, 0.5, 0.0)), "taper 1 / .75 / .5 / .25": scoped(None, (1.0, 0.75, 0.5, 0.25))}, mQ)
    # ---------------------------------------------------------------- 3a  hurt games x.5 in the shadow's usage inputs
    inj = QI.load_injuries(); snaps = QI.load_snaps(); pid_of = {}
    for i in range(n):
        if pid[i]: pid_of[(name[i], pos[i])] = pid[i]
    xfp = X["xf"]; seq = defaultdict(list)
    for i in range(n): seq[(name[i], pos[i], int(year[i]))].append(i)
    gx = {}
    for key, ix in seq.items():
        ix.sort(key=lambda i: wk[i])
        for a in range(len(ix) - 1):
            i, j = ix[a], ix[a + 1]
            if g[j] - g[i] == 1 and X["has_x"][j] and X["has_x"][i] or (g[j] - g[i] == 1 and X["has_x"][j] and g[i] == 0):
                prevx = xfp[i] * g[i] if g[i] > 0 else 0.0
                gx[key + (int(wk[i]),)] = xfp[j] * g[j] - prevx
    tcache = {}
    def hurt(nm, ps, Y, w, opp):
        gid = pid_of.get((nm, ps)); k = (Y, w, opp)
        if k not in tcache: tcache[k] = QI.week_team(Y, w, opp) if opp else None
        t = tcache[k]; rs, pr = inj.get((Y, t, w, gid), ("", "")) if (gid and t) else ("", "")
        if rs == "Questionable" or "Limited" in pr or "Did Not" in pr: return True
        sy = snaps.get(cal.norm(nm), {}).get(Y, {}); vals = [v for v in sy.values() if v > 0]
        return len(vals) >= 4 and w in sy and sy[w] > 0 and sy[w] < 0.75 * float(np.median(vals))
    xf_h = xfp.copy(); touched3 = np.zeros(n, bool)
    for i in np.where(okN & np.isin(pos, ("WR", "RB")) & (g >= 1) & X["has_x"])[0]:
        key = (name[i], pos[i], int(year[i]))
        if key not in games: continue
        tm_, cpg, gl = games[key]; evw = [w for w in sorted(gl) if w < wk[i]]
        vals = [(gx.get(key + (w,)), hurt(name[i], pos[i], int(year[i]), w, None) if False else None) for w in evw]
        xs = []; ws = []
        for w in evw:
            v = gx.get(key + (w,))
            if v is None: continue
            rec = cal.weekly_rec(name[i], pos[i]); opp = None
            for r_ in (rec or {}).get("seasons", {}).get(str(int(year[i])), []):
                if int(r_.get("wk", -1)) == w: opp = r_.get("opp"); break
            hw = 0.5 if hurt(name[i], pos[i], int(year[i]), w, opp) else 1.0
            xs.append(v * hw); ws.append(hw)
        if ws and sum(ws) > 0 and any(w_ < 1 for w_ in ws):
            xf_h[i] = sum(xs) / sum(ws); touched3[i] = True
    SH_h = SN.shadow(dict(X, xf=xf_h))
    grade("3a hurt games x.5 in the shadow's usage inputs (WR / RB xFP evidence)", {"off": BASE, "x.5": SH_h}, okN & touched3)
    # ---------------------------------------------------------------- 3b volume context on the shadow
    TW = VC.load_team_weeks(YEARS)
    attpg = np.full(n, np.nan); exc = np.full(n, np.nan)
    for i in range(n):
        if not okN[i] or not team[i]: continue
        Y = int(year[i]); rows = [TW[(Y, team[i], w)] for w in range(1, int(wk[i])) if (Y, team[i], w) in TW]
        if len(rows) < 2: continue
        a = np.sum(rows, axis=0); gms = len(rows); attpg[i] = a[1] / gms; nrate = a[3] / max(a[2], 1); exc[i] = attpg[i] - nrate * (a[0] / gms)
    RECV = np.isin(pos, ("WR", "TE")); Z = {}
    for k, M in (("att", attpg), ("exc", exc)):
        z = np.full(n, np.nan)
        for y in YEARS:
            for w in range(1, 19):
                m = okN & (year == y) & (wk == w) & ~np.isnan(M) & RECV
                if m.sum() >= 20 and np.nanstd(M[m]) > 0: z[m] = np.clip((M[m] - np.nanmean(M[m])) / np.nanstd(M[m]), -2.5, 2.5)
        Z[k] = z
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    spread = np.where(has, C["spread"].values[np.maximum(idx, 0)], np.nan).astype(float); und = ~np.isnan(spread) & (spread > 0)
    mV = okN & RECV & ~np.isnan(Z["exc"])
    def vol(eb, ef):
        p = BASE.copy(); mm = mV & ~np.isnan(Z["exc"]); p[mm] = p[mm] * np.clip(1 - eb * Z["exc"][mm], 0.8, 1.2)
        mm2 = mV & und & ~np.isnan(Z["att"]); p[mm2] = p[mm2] * np.clip(1 - ef * Z["att"][mm2], 0.8, 1.2); return p
    grade("3b volume context on the shadow (script excess everyone + att/g underdogs)", {"off": BASE, "B .03 only": vol(0.03, 0.0), "F3 .04 only": vol(0.0, 0.04), "B .03 + F3 .04 (live setting)": vol(0.03, 0.04), "B .02 + F3 .03": vol(0.02, 0.03), "B .04 + F3 .06": vol(0.04, 0.06)}, mV)
    P("\nLimitations: harness shadow v2.24 form; weeks_out from the game's top passer; 3a reweights the xFP average only (route / snap level not in this form).")
    LOG.close()


if __name__ == "__main__":
    main()
