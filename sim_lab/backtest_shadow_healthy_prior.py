#!/usr/bin/env python3
"""
HEALTHY-GAMES HISTORY PRIOR FOR THE SHADOW (Jack 2026-10-07: "let's do it in order" - item 1).  The shadow's preseason
prior is half his 3-year weighted PPG and half his last 8 games (age-adjusted), 25% of the vet prior once the market
blend is in, and replaced by the opportunity prior for vets with 6+ games last season. All of it counts games he
limped through. Here the history pieces are rebuilt from HEALTHY games only (hurt = listed Questionable, final practice
Limited / DNP, or snap share under 75% of his season median) and the shadow is re-graded.
  V1  healthy h3 + l8, prior seasons only (this season's games kept)        k = 1 (replace) / .5 (half way)
  V2  healthy everywhere (this season's hurt games out of the l8 tail too)
  V3  V1 + vets on the opportunity prior: pull it half way to the healthy history when 3+ hurt games last season
  V4  lift form (the live rule): prior + .5 x (healthy ppg - all ppg) last season, gated 3+ hurt / 4+ healthy, cap 2
Rows: 2019-25, shadow v2.24 harness form (SN.shadow with the prior swapped), next game top-150 weighted + a rest-of-
season read; touched rows, by position, by games played; LOYO + forward. Log shadow_healthy_prior.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
import backtest_qb_injury_usage as QI
NW = SN.NW; cal = NW.cal; YEARS = list(NW.YEARS); POS4 = ("QB", "RB", "WR", "TE"); FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "shadow_healthy_prior.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
W3 = getattr(NW, "W3", (0.5, 0.3, 0.2)); MIN_SEASON_G = getattr(NW, "MIN_SEASON_G", 4); MIN_H3_G = getattr(NW, "MIN_H3_G", 8); MIN_L8_G = getattr(NW, "MIN_L8_G", 4)


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, g, adp, name, pid, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], A["pid"], X["team"]
    age = np.array(A["age"], float); exp = np.array(A["exp"], float); rookie = np.array(A["rookie"], bool)
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    inj = QI.load_injuries(); snaps = QI.load_snaps()
    P(f"injury rows {len(inj):,}, snap players {len(snaps):,}")
    pid_of = {}
    for i in range(n):
        if pid[i]: pid_of[(name[i], pos[i])] = pid[i]
    tcache = {}
    def tw(Y, w, opp):
        k = (Y, w, opp)
        if k not in tcache: tcache[k] = QI.week_team(Y, w, opp)
        return tcache[k]
    def hurt(nm, ps, Y, w, opp):
        gid = pid_of.get((nm, ps)); t = tw(Y, w, opp) if opp else None
        rs, pr = inj.get((Y, t, w, gid), ("", "")) if (gid and t) else ("", "")
        if rs == "Questionable" or "Limited" in pr or "Did Not" in pr: return True
        sy = snaps.get(cal.norm(nm), {}).get(Y, {}); vals = [v for v in sy.values() if v > 0]
        if len(vals) >= 4 and w in sy and sy[w] > 0 and sy[w] < 0.75 * float(np.median(vals)): return True
        return False
    # per player-season game lists with hurt tags (cached by (name, pos, Y))
    glog = {}
    def games_of(nm, ps, Y):
        k = (nm, ps, Y)
        if k in glog: return glog[k]
        rec = cal.weekly_rec(nm, ps); out = []
        for w in (rec or {}).get("seasons", {}).get(str(Y), []):
            if cal.played(w) and isinstance(w.get("fpts"), (int, float)):
                out.append((int(w["wk"]), float(w["fpts"]), hurt(nm, ps, Y, int(w["wk"]), w.get("opp"))))
        out.sort(); glog[k] = out; return out
    def h3_of(nm, ps, Y, healthy):
        num = den = 0.0; hg = 0
        for i, yy in enumerate((Y - 1, Y - 2, Y - 3)):
            pts = [f for (w, f, h) in games_of(nm, ps, yy) if not (healthy and h)]
            if len(pts) >= MIN_SEASON_G: num += W3[i] * (sum(pts) / len(pts)); den += W3[i]; hg += len(pts)
        return (num / den) if (den > 0 and hg >= MIN_H3_G) else np.nan
    def l8_of(nm, ps, Y, w0, healthy_prior, healthy_cur):
        tail = []
        for yy in (Y - 2, Y - 1, Y):
            for (w, f, h) in games_of(nm, ps, yy):
                if (yy, w) >= (Y, w0): continue
                if h and ((yy < Y and healthy_prior) or (yy == Y and healthy_cur)): continue
                tail.append(f)
        tail = tail[-8:]; return (sum(tail) / len(tail)) if len(tail) >= MIN_L8_G else np.nan
    def combine(h3, l8):
        if not np.isnan(h3) and not np.isnan(l8): return 0.5 * h3 + 0.5 * l8
        return h3 if not np.isnan(h3) else l8
    hist0 = F["hist"]; has_hist = ~np.isnan(hist0)
    histA = np.full(n, np.nan); histB = np.full(n, np.nan); hist_chk = np.full(n, np.nan)
    hurtN = np.zeros(n); healthyN = np.zeros(n); prev_h = np.full(n, np.nan); prev_a = np.full(n, np.nan)
    rows_m = ~rookie & has_hist
    for i in np.where(rows_m)[0]:
        Y = int(year[i]); nm = name[i]; ps = pos[i]
        hist_chk[i] = combine(h3_of(nm, ps, Y, False), l8_of(nm, ps, Y, int(wk[i]), False, False))
        histA[i] = combine(h3_of(nm, ps, Y, True), l8_of(nm, ps, Y, int(wk[i]), True, False))
        histB[i] = combine(h3_of(nm, ps, Y, True), l8_of(nm, ps, Y, int(wk[i]), True, True))
        gl = games_of(nm, ps, Y - 1)
        if len(gl) >= 4:
            hp = [f for (w, f, h) in gl if not h]; prev_a[i] = np.mean([f for (w, f, h) in gl]); hurtN[i] = len(gl) - len(hp); healthyN[i] = len(hp)
            if len(hp) >= 1: prev_h[i] = np.mean(hp)
    chk = rows_m & ~np.isnan(hist_chk) & ~np.isnan(hist0)
    P(f"rows with a history prior {int(rows_m.sum()):,}; replica of hist (raw) max |diff| {np.nanmax(np.abs(hist_chk[chk] - hist0[chk])):.3f}, median {np.nanmedian(np.abs(hist_chk[chk] - hist0[chk])):.3f}")
    P(f"players with 3+ hurt games last season: {int((rows_m & (hurtN >= 3)).sum()):,} rows; healthy-vs-all gap on them: mean {np.nanmean((prev_h - prev_a)[rows_m & (hurtN >= 3)]):+.2f} half-PPR/g")
    # age-adjust both versions like the harness, then the delta into the prior
    adj = lambda h, i: NW.age_adjust(pos[i], h, age[i]) if not np.isnan(h) else np.nan
    hist0_adj = np.array([adj(hist0[i], i) for i in range(n)]); hA_adj = np.array([adj(histA[i], i) for i in range(n)]); hB_adj = np.array([adj(histB[i], i) for i in range(n)])
    wv = np.where(exp == 1, 0.5, 0.75); w_hist = np.where(F["mkt_ok"], 1 - wv, 1.0)
    used = rows_m & ~F["vet_opp"]                      # rows where the history (not the opportunity prior) is the prior's base
    ridge_on = np.abs(X["prior"] - F["prior"]) > 1e-9  # non-QB rows where the ridge season prior is mixed in at 50%
    mixw = np.where(ridge_on, 0.5, 1.0)
    def with_delta(d):
        return X["prior"] + mixw * d
    def var_hist(h_adj, k, opp_k=0.0):
        d = np.zeros(n); m = used & ~np.isnan(h_adj)
        d[m] = 0.8 * w_hist[m] * k * (h_adj[m] - hist0_adj[m])
        if opp_k > 0:
            mo = rows_m & F["vet_opp"] & ~np.isnan(h_adj) & (hurtN >= 3) & ~np.isnan(np.array(A["oppcal"], float))
            d[mo] = 0.8 * w_hist[mo] * opp_k * (h_adj[mo] - np.array(A["oppcal"], float)[mo])
        return with_delta(d), (np.abs(d) > 1e-9)
    def var_lift(a, cap=2.0):
        d = np.zeros(n); m = rows_m & (hurtN >= 3) & (healthyN >= 4) & ~np.isnan(prev_h) & (prev_h > X["prior"])
        d[m] = np.minimum(cap, np.maximum(0.0, a * (prev_h[m] - prev_a[m])))
        return X["prior"] + d, (d > 1e-9)
    base = SN.shadow(X); okN = (g >= 1) & ~final & top150 & (base >= 3)
    def shadow_with(prior):
        X2 = dict(X); X2["prior"] = prior; return SN.shadow(X2)
    # rest-of-season read: rate x mean future context (fill-in harness style)
    seqn = defaultdict(list)
    for i in range(n):
        if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ix in seqn.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(X["layers"][ix], 0.5, 1.8)
        for a, i in enumerate(ix): nfut[i] = len(ix) - a; Tr[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    okR = (g >= 1) & (g <= 10) & ~np.isnan(Tr) & top150 & (nfut >= 4) & (base >= 3); ctx0 = np.nan_to_num(ctx, nan=1.0)
    ros = lambda pred: pred / np.maximum(X["layers"], 0.3) * ctx0
    wm = lambda p, m, T: float(np.average((p[m] - T[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    FAMS = [("V1 healthy h3 + l8, prior seasons only", {"k .5": lambda: var_hist(hA_adj, 0.5), "k 1": lambda: var_hist(hA_adj, 1.0)}),
            ("V2 healthy everywhere (this season's hurt games out of l8 too)", {"k .5": lambda: var_hist(hB_adj, 0.5), "k 1": lambda: var_hist(hB_adj, 1.0)}),
            ("V3 V1 k 1 + opportunity-prior vets pulled toward healthy history (3+ hurt)", {"opp .5": lambda: var_hist(hA_adj, 1.0, 0.5), "opp 1": lambda: var_hist(hA_adj, 1.0, 1.0)}),
            ("V4 lift form: prior + a x (healthy - all) last season, 3+ hurt / 4+ healthy, cap 2", {"a .25": lambda: var_lift(0.25), "a .5": lambda: var_lift(0.5), "a .75": lambda: var_lift(0.75)})]
    for title, fam in FAMS:
        V = {k: f() for k, f in fam.items()}
        for key, T, ok, fn in (("NEXT GAME", act, okN, lambda p: p), ("REST OF SEASON (4+ left)", Tr, okR, ros)):
            preds = {"off": fn(base)}; touched = np.zeros(n, bool)
            for k, (pr, tm_) in V.items(): preds[k] = fn(shadow_with(pr)); touched |= tm_
            m = touched & ok
            if m.sum() < 60: P(f"\n  {title} | {key}: too few rows ({int(m.sum())})"); continue
            names = list(preds); pick = lambda yrs: min(names, key=lambda kk: wm(preds[kk], m & np.isin(year, yrs), T))
            def run(folds):
                wins = 0; picks = []; pr_ = preds["off"].copy()
                for tr_, te in folds:
                    kk = pick(tr_); picks.append(kk); mm = year == te; pr_[mm] = preds[kk][mm]; wins += wm(preds[kk], m & mm, T) < wm(preds["off"], m & mm, T) - 1e-12
                tem = np.isin(year, [te for _, te in folds]); return 100 * (wm(pr_, m & tem, T) / wm(preds["off"], m & tem, T) - 1), 100 * (wm(pr_, ok & tem, T) / wm(preds["off"], ok & tem, T) - 1), wins, picks
            lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
            fixed = "  ".join(f"{kk}: {100*(wm(preds[kk], m, T)/wm(preds['off'], m, T)-1):+.2f}% ({sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and wm(preds[kk], m & (year == y), T) < wm(preds['off'], m & (year == y), T) - 1e-12)}/7)" for kk in names[1:])
            pb = preds[best]
            P(f"\n  {title} | {key}  rows {int(m.sum()):,}  actual/shadow on them {T[m].sum()/preds['off'][m].sum():.3f}")
            P(f"    fixed: {fixed}")
            P(f"    best {best}: " + " | ".join(f"{ps} {100*(wm(pb, m & (pos == ps), T)/wm(preds['off'], m & (pos == ps), T)-1):+.2f}% (n{int((m & (pos == ps)).sum())})" for ps in POS4) + f" | g 1-3 {100*(wm(pb, m & (g <= 3), T)/wm(preds['off'], m & (g <= 3), T)-1):+.2f}% | g 4-8 {100*(wm(pb, m & (g >= 4) & (g <= 8), T)/wm(preds['off'], m & (g >= 4) & (g <= 8), T)-1):+.2f}% | g 9+ {100*(wm(pb, m & (g >= 9), T)/wm(preds['off'], m & (g >= 9), T)-1):+.2f}% | ADP<=60 {100*(wm(pb, m & (adp <= 60), T)/wm(preds['off'], m & (adp <= 60), T)-1):+.2f}%")
            P(f"    LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | picks {lo[3]}")
            P(f"    FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}")
            okk = best != "off" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
            P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
    P("\nLimitations: harness shadow form (v2.24 + prior swap), the as-wired extra layers are multiplicative and identical across variants; opportunity prior rows only touched in V3; string docks not re-applied to the delta; hurt tags need the nflverse report (2019+) or snap counts.")
    LOG.close()


if __name__ == "__main__":
    main()
