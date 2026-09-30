#!/usr/bin/env python3
"""
ALIGNMENT MATCHUPS: slot vs outside (X / Z) vs inline, against what each defense allows to that alignment (2026-09-17).

Jack: "so matchups dont really matter like individually - example x z or slot". Position-level FPA is shipped; shadow
corners, player-x-defense history, target depth / side zones and man-zone x YPRR all failed. Alignment was never
tested. PFF weekly receiving (pff_receiving_summary_Y_wW: slot_rate, wide_rate, inline_rate, routes, receptions,
yards, touchdowns for EVERY receiver) gives, per defense-week, the half-PPR receiving points it allowed split by the
receiver's alignment share; walk-forward (weeks before the game, shrunk to last season) that becomes the defense's
points allowed PER ROUTE to slot / wide / inline, standardized across defenses each week. A receiver's matchup score =
his own alignment mix (walk-forward) x the opponent's alignment z-scores, and the contrast version: how much better /
worse the opponent is against HIS alignment than against receivers overall (the part position FPA cannot see).
Graded on the weekly RANK objective (mean within-position-week Spearman, top 150) LOYO + forward, WR and TE.
Log alignment_matchup.log; results -> data/alignment_matchup.js (SIM_ALIGN_BT).
"""
import json, os, sys, time, warnings
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy.stats import rankdata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B
import backtest_noclay_weekly as NW
import research_clay_vs_shadow as CS
import backtest_season_long as SL
from backtest_matchup_rank import PFF2NFL
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "alignment_matchup.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
YEARS = NW.YEARS
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "diag": [], "tests": []}
AL = ("slot", "wide", "inline")


def load_alignment():
    """per player-week alignment + points; per defense-week points and routes allowed by alignment."""
    pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "pff_id"])
    pff2g = {int(r.pff_id): r.gsis_id for r in pl.itertuples(index=False) if pd.notna(r.pff_id) and isinstance(r.gsis_id, str)}
    pw = defaultdict(dict); dw = defaultdict(dict)
    for Y in range(YEARS[0] - 1, YEARS[-1] + 1):
        games = B.load_games(Y)
        for w in range(1, 19):
            f = os.path.join(B.CACHE, "pff", "weekly", f"pff_receiving_summary_{Y}_w{w}.csv")
            if not os.path.exists(f): continue
            d = pd.read_csv(f); d = d[d.position.isin(["WR", "TE"]) & (d.routes > 0)]
            for r in d.itertuples(index=False):
                tm = PFF2NFL.get(r.team_name, r.team_name); gm = games.get((tm, w))
                sh = np.array([getattr(r, "slot_rate", np.nan), getattr(r, "wide_rate", np.nan), getattr(r, "inline_rate", np.nan)], dtype=float) / 100.0
                if np.isnan(sh).all(): continue
                sh = np.nan_to_num(sh); tot = sh.sum()
                if tot <= 0: continue
                sh = sh / tot; pts = 0.5 * (r.receptions or 0) + 0.1 * (r.yards or 0) + 6.0 * (r.touchdowns or 0)
                g_ = pff2g.get(int(r.player_id))
                if g_: pw[(Y, g_)][w] = (sh, float(r.routes))
                if gm:
                    a = dw[(Y, gm["opp"])].setdefault(w, {"pts": np.zeros(3), "rt": np.zeros(3)}); a["pts"] += pts * sh; a["rt"] += float(r.routes) * sh
    return pw, dw


def main():
    t0 = time.time()
    P("=== Alignment matchups: slot / outside / inline vs what each defense allows to that alignment (rank objective) ===")
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, layers, adp, pid = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["layers"], F["adp"], A["pid"]
    T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    xfp = np.where(has, C["xfp_pg"].values[np.maximum(idx, 0)], np.nan).astype(float); ev = has & (g >= 1) & ~np.isnan(xfp); xf = np.where(ev, xfp, ppg)
    lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    def pred_of(fwd):
        lo = (SL.forward if fwd else SL.loyo)(T, LIVE, "ridge", 10.0); key = {(int(y), nm, ps): v for y, nm, ps, v in zip(T.year, T.name, T.pos, lo)}
        r = np.array([key.get((year[i], A["name"][i], pos[i]), np.nan) for i in range(n)]); prior = np.where(np.isnan(r) | (pos == "QB"), F["prior"], 0.5 * r + 0.5 * F["prior"])
        rate = NW.blend(prior, g, lam * xf + (1 - lam) * ppg, F["Pvec"])
        for gi, m_ in enumerate([0.7, 0.8], start=1): rate = np.where(F["buried_rk"] & (wk == gi), rate * m_, rate)
        return np.where(F["on"], rate * np.power(F["pm"], 0.75), rate) * layers
    PRED = {False: pred_of(False), True: pred_of(True)}
    opp = np.array([C["opp"].values[idx[i]] if has[i] else None for i in range(n)], dtype=object)
    pw, dw = load_alignment(); K = 4.0
    # defense walk-forward points per route by alignment (+ overall), then z across defenses within the season-week
    def d_rate(Y, tm, w):
        cur = dw.get((Y, tm), {}); py = dw.get((Y - 1, tm), {})
        ps = sum((cur[x]["pts"] for x in cur if x < w), np.zeros(3)); rs = sum((cur[x]["rt"] for x in cur if x < w), np.zeros(3)); ns = sum(1 for x in cur if x < w)
        pp = sum((py[x]["pts"] for x in py), np.zeros(3)); rp = sum((py[x]["rt"] for x in py), np.zeros(3))
        if rs.sum() <= 0 and rp.sum() <= 0: return None
        out = np.full(4, np.nan)
        for j in range(3):
            a = ps[j] / rs[j] if rs[j] > 30 else np.nan; b = pp[j] / rp[j] if rp[j] > 100 else np.nan
            out[j] = a if np.isnan(b) else (b if np.isnan(a) else (K * b + ns * a) / (K + ns))
        a = ps.sum() / rs.sum() if rs.sum() > 60 else np.nan; b = pp.sum() / rp.sum() if rp.sum() > 200 else np.nan
        out[3] = a if np.isnan(b) else (b if np.isnan(a) else (K * b + ns * a) / (K + ns)); return out
    teams = sorted({t for (_, t) in dw}); DZ = {}
    for Y in YEARS:
        for w in range(1, 19):
            rows = {t: d_rate(Y, t, w) for t in teams}; rows = {t: v for t, v in rows.items() if v is not None}
            if len(rows) < 20: continue
            M = np.array([rows[t] for t in rows]); mu, sd = np.nanmean(M, 0), np.nanstd(M, 0); sd[sd == 0] = 1
            for t in rows: DZ[(Y, t, w)] = np.nan_to_num((rows[t] - mu) / sd)
    # player walk-forward alignment mix (season to date routes-weighted, shrunk to last season)
    mix = np.full((n, 3), np.nan)
    for i in range(n):
        if pos[i] not in ("WR", "TE") or not pid[i]: continue
        cur = pw.get((int(year[i]), pid[i]), {}); py = pw.get((int(year[i]) - 1, pid[i]), {})
        num = np.zeros(3); den = 0.0
        for x, (sh, rt) in cur.items():
            if x < wk[i]: num += sh * rt; den += rt
        for x, (sh, rt) in py.items(): num += 0.35 * sh * rt; den += 0.35 * rt
        if den >= 40: mix[i] = num / den
    z = np.zeros((n, 4)); okz = np.zeros(n, bool)
    for i in range(n):
        v = DZ.get((int(year[i]), opp[i], int(wk[i]))) if opp[i] is not None else None
        if v is not None: z[i] = v; okz[i] = True
    okm = ~np.isnan(mix[:, 0]); use = okm & okz; mixf = np.nan_to_num(mix)
    f_mix = np.where(use, (mixf * z[:, :3]).sum(1), 0.0)                       # opponent z weighted by HIS alignment mix
    f_contrast = np.where(use, (mixf * (z[:, :3] - z[:, [3]])).sum(1), 0.0)     # ... minus the opponent's overall z = alignment-specific part only
    f_slot = np.where(use & (mixf[:, 0] >= 0.55), z[:, 0] - z[:, 3], 0.0); f_wide = np.where(use & (mixf[:, 1] >= 0.65), z[:, 1] - z[:, 3], 0.0); f_inl = np.where(use & (mixf[:, 2] >= 0.45), z[:, 2] - z[:, 3], 0.0)
    top150 = adp <= 150
    groups = defaultdict(list)
    for i in np.where(top150)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
    groups = {k: np.array(v) for k, v in groups.items() if len(v) >= 8}
    def metrics(pred, ps, years):
        rho, pwn, tot, se, sn = [], 0, 0, 0.0, 0
        for (y, w, p_), ix in groups.items():
            if p_ != ps or y not in years: continue
            a = act[ix]; pv = pred[ix]; rho.append(np.corrcoef(rankdata(a), rankdata(pv))[0, 1])
            d = pv[:, None] - pv[None, :]; o = a[:, None] - a[None, :]; iu = np.triu_indices(len(ix), 1); dd, oo = d[iu], o[iu]; ok = (dd != 0) & (oo != 0)
            pwn += int(((dd > 0) == (oo > 0))[ok].sum()); tot += int(ok.sum()); se += float(((pv - a) ** 2).sum()); sn += len(ix)
        return float(np.mean(rho)), 100.0 * pwn / max(1, tot), se / max(1, sn)
    # ---- diagnostics: is the defense-by-alignment signal even persistent, and does it line up with outcomes? ----
    P(f"  WR/TE top-150 rows {int((top150 & np.isin(pos, ['WR', 'TE'])).sum())} | with alignment mix + opponent alignment z: {int((use & top150).sum())}")
    P("\n=== Diagnostics ===")
    first, second = defaultdict(list), defaultdict(list)
    for (Y, t), wks in dw.items():
        if Y not in YEARS: continue
        a = sum((wks[x]["pts"] for x in wks if x <= 9), np.zeros(3)); ar = sum((wks[x]["rt"] for x in wks if x <= 9), np.zeros(3)); b = sum((wks[x]["pts"] for x in wks if x > 9), np.zeros(3)); br = sum((wks[x]["rt"] for x in wks if x > 9), np.zeros(3))
        if ar.min() > 50 and br.min() > 50:
            ra, rb = a / ar, b / br; oa, ob = a.sum() / ar.sum(), b.sum() / br.sum()
            for j, nm in enumerate(AL): first[nm].append(ra[j] - oa); second[nm].append(rb[j] - ob)
            first["overall"].append(oa); second["overall"].append(ob)
    for nm in ("overall",) + AL:
        r = float(np.corrcoef(first[nm], second[nm])[0, 1]); RES["diag"].append({"what": nm, "r": round(r, 3)})
        P(f"  defense points per route allowed, weeks 1-9 vs 10-18, {'OVERALL' if nm == 'overall' else nm + ' minus overall (the alignment-specific part)'}: r = {r:+.3f} ({len(first[nm])} defense-seasons)")
    for ps, fz, lab in (("WR", f_slot, "slot WR (55%+ slot)"), ("WR", f_wide, "outside WR (65%+ wide)"), ("TE", f_inl, "inline TE (45%+ inline)")):
        m = top150 & (pos == ps) & (fz != 0); base = PRED[False]
        if m.sum() < 200: continue
        hi = m & (fz >= 0.75); lo_ = m & (fz <= -0.75)
        P(f"  {lab}: opponent SOFT vs his alignment (z >= +.75) n={hi.sum()} actual/projected {act[hi].mean()/base[hi].mean():.3f} | opponent TOUGH (z <= -.75) n={lo_.sum()} actual/projected {act[lo_].mean()/base[lo_].mean():.3f}")
        RES["diag"].append({"what": lab, "soft": round(float(act[hi].mean() / base[hi].mean()), 3), "tough": round(float(act[lo_].mean() / base[lo_].mean()), 3), "nSoft": int(hi.sum()), "nTough": int(lo_.sum())})
    # ---- LOYO tilt on the rank objective ----
    CG = [-0.08, -0.05, -0.03, 0.0, 0.03, 0.05, 0.08, 0.12]
    def loyo(feat, ps, fwd):
        base = PRED[fwd]; cand = {c: base * np.exp(c * feat) for c in CG}; stat = {c: {y: metrics(cand[c], ps, {y}) for y in YEARS} for c in CG}
        ys = YEARS[2:] if fwd else YEARS; o, b, picks, wins, opw, bpw, om, bm = [], [], [], 0, [], [], [], []
        for y in ys:
            tr = [yy for yy in YEARS if (yy < y if fwd else yy != y)]; best = max(CG, key=lambda c: np.mean([stat[c][yy][0] for yy in tr])); picks.append(best)
            o.append(stat[best][y][0]); b.append(stat[0.0][y][0]); opw.append(stat[best][y][1]); bpw.append(stat[0.0][y][1]); om.append(stat[best][y][2]); bm.append(stat[0.0][y][2]); wins += int(stat[best][y][0] > stat[0.0][y][0] + 1e-9)
        return {"dRho": round(float(np.mean(o) - np.mean(b)), 4), "dPair": round(float(np.mean(opw) - np.mean(bpw)), 2), "dMsePct": round(float((np.mean(om) / np.mean(bm) - 1) * 100), 2), "wins": wins, "years": len(ys), "picks": picks, "base": round(float(np.mean(b)), 4)}
    P("\n=== Rank test: x exp(c x feature), c per position LOYO on mean within-week Spearman, then forward ===")
    for lab, feat, positions in (("opponent z weighted by HIS alignment mix", f_mix, ("WR", "TE")), ("alignment-SPECIFIC part only (minus the opponent's overall z)", f_contrast, ("WR", "TE")),
                                 ("slot-heavy WRs vs the opponent's slot z (specific part)", f_slot, ("WR",)), ("outside WRs vs the opponent's wide z (specific part)", f_wide, ("WR",)), ("inline TEs vs the opponent's inline z (specific part)", f_inl, ("TE",))):
        for ps in positions:
            a = loyo(feat, ps, False); f = loyo(feat, ps, True); ok = a["dRho"] >= 0.004 and a["wins"] >= 5 and f["dRho"] > 0 and f["wins"] >= 3
            RES["tests"].append({"label": lab, "pos": ps, **a, "fwd": f, "pass": bool(ok)})
            P(f"  {lab} [{ps}]: LOYO rho {a['dRho']:+.4f} (base {a['base']:.3f}), pairs {a['dPair']:+.2f}, MSE {a['dMsePct']:+.2f}%, seasons {a['wins']}/{a['years']}, picks {sorted(set(a['picks']))} | forward rho {f['dRho']:+.4f}, {f['wins']}/{f['years']}{'  <== PASS' if ok else ''}")
    npass = sum(1 for t in RES["tests"] if t["pass"])
    RES["summary"] = (f"Alignment matchups on the weekly rank objective: {npass} of {len(RES['tests'])} tests pass. Defense points-per-route allowed persist overall (r {RES['diag'][0]['r']:+.2f} first half to second half) "
                      f"but the alignment-specific part does not (slot {RES['diag'][1]['r']:+.2f}, wide {RES['diag'][2]['r']:+.2f}, inline {RES['diag'][3]['r']:+.2f}).")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "alignment_matchup.js"), "w", encoding="utf-8") as fh:
        fh.write("window.SIM_ALIGN_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/alignment_matchup.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
