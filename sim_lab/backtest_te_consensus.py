#!/usr/bin/env python3
"""
OUTSIDE CONSENSUS AS THE TIGHT-END BASE (Jack 2026-10-08: "test the outside consensus for te only").
TE is the one Clay dependency left (every history-based shadow fix failed). Can the ESPN weekly projection (the outside
number we hold for 2019-25) replace Clay's form for tight ends? TE rows only, everything else untouched.
  families (TE rows with an ESPN row; rows without one keep the shadow):
    CLAY   today's wired TE number (Clay-side live form, blend weight 0)            <- the reference
    ESPN   ESPN alone | shadow w x shadow + (1 - w) x ESPN, w .3 / .5 / .7 | shadow alone           <- Clay-free
    MIXED  Clay .5 + ESPN .5 (not Clay-free, for scale)
  horizons: next game (pre-book) and rest of season (4+ games left, target = average of the remaining games)
  grading: top-150 importance-weighted error vs CLAY + seasons better; rank objective (rho / pairs); LOYO + forward
  picks inside the Clay-free family; ship bar 5/7 + 3/4 and no worse than CLAY. Log te_consensus.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "te_consensus.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    esp = BR.load_espn(X)
    if esp is None: P("no ESPN rows - stop"); return
    TE = pos == "TE"; okE = ~np.isnan(esp) & (esp > 0.5)
    base = top150 & ~final & ~LV["inh"]; baseTE = base & TE
    P(f"=== OUTSIDE CONSENSUS (ESPN weekly) AS THE TE BASE: {int(baseTE.sum()):,} top-150 TE player-weeks 2019-25; ESPN row on {int((baseTE & okE).sum()):,} ({100*(baseTE & okE).sum()/max(1, baseTE.sum()):.0f}%) ===")
    P("    ESPN coverage by season: " + " ".join(f"{y}:{100*(baseTE & okE & (year == y)).sum()/max(1, (baseTE & (year == y)).sum()):.0f}%" for y in YEARS) + " | by games played: " + " ".join(f"g{a}:{100*(baseTE & okE & (g == a)).sum()/max(1, (baseTE & (g == a)).sum()):.0f}%" for a in (0, 1, 2, 3)))
    P(f"    level actual / number on TE rows with ESPN: Clay form {act[baseTE & okE].sum()/TODAY[baseTE & okE].sum():.3f}  shadow {act[baseTE & okE].sum()/SHADOW[baseTE & okE].sum():.3f}  ESPN {act[baseTE & okE].sum()/esp[baseTE & okE].sum():.3f}")
    def fam(ref, sh, es):
        """TE-row variants; non-TE rows and TE rows without ESPN keep `ref` (Clay form) or the shadow as labelled"""
        out = {"CLAY (wired)": ref.copy()}
        def te(v, fallback):
            p = ref.copy(); p[TE] = fallback[TE]; p[TE & okE] = v[TE & okE]; return p
        out["ESPN alone"] = te(es, sh)
        for w in (0.3, 0.5, 0.7): out[f"shadow {w:.1f} + ESPN"] = te(w * sh + (1 - w) * es, sh)
        out["shadow alone"] = te(sh, sh)
        out["Clay .5 + ESPN .5 (not Clay-free)"] = te(0.5 * ref + 0.5 * es, ref)
        return out
    # rest-of-season target / context
    seqn = defaultdict(list)
    for i in range(n):
        if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ix in seqn.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(X["layers"][ix], 0.5, 1.8)
        for a, i in enumerate(ix): nfut[i] = len(ix) - a; Tr[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    ctx0 = np.nan_to_num(ctx, nan=1.0); ros = lambda p: p / np.maximum(X["layers"], 0.3) * ctx0
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    CF = ("ESPN alone", "shadow 0.3 + ESPN", "shadow 0.5 + ESPN", "shadow 0.7 + ESPN", "shadow alone")
    for hlab, T, m, tf in (("NEXT GAME", act, baseTE, lambda p: p), ("REST OF SEASON (4+ games left)", Tr, baseTE & (g >= 1) & (g <= 10) & ~np.isnan(Tr) & (nfut >= 4), ros)):
        preds = {k: tf(v) for k, v in fam(TODAY, SHADOW, esp).items()}; b0 = preds["CLAY (wired)"]
        wm = lambda p, mm: float(np.average((p[mm] - T[mm]) ** 2, weights=wt[mm])) if mm.any() else np.nan
        RS = lambda p, mm: RG.rank_stats(p, mm, T, year, wk, pos)
        P(f"\n--- {hlab}: {int(m.sum()):,} TE rows ---")
        r0, p0 = RS(b0, m)
        for k, p in preds.items():
            if k == "CLAY (wired)": continue
            wins = sum(1 for y in YEARS if wm(p, m & (year == y)) < wm(b0, m & (year == y)) - 1e-12); r, pr = RS(p, m); rw = RG.rank_seasons(p, b0, m, T, year, wk, pos, YEARS)
            fw = 100 * (wm(p, m & (year >= 2022)) / wm(b0, m & (year >= 2022)) - 1); fwins = sum(1 for y in FWD if wm(p, m & (year == y)) < wm(b0, m & (year == y)) - 1e-12)
            P(f"  {k:36s} error {100*(wm(p, m)/wm(b0, m)-1):+6.2f}% ({wins}/7) | 2022-25 {fw:+6.2f}% ({fwins}/4) | rho {r:.4f} ({r - r0:+.4f}, {rw}/7) | pairs {pr:.2f}% ({pr - p0:+.2f}) | level {T[m].sum()/p[m].sum():.3f}")
        P("  cuts, ESPN alone / shadow .5 + ESPN vs CLAY (error):")
        for clab, cm in (("ADP <= 60", adpx <= 60), ("ADP 61-150", adpx > 60), ("games 0-3", g <= 3), ("games 4+", g >= 4), ("rookies", X["rookie"]), ("vets", ~X["rookie"])):
            mm = m & cm
            if mm.sum() < 40: continue
            P(f"    {clab:12s} n{int(mm.sum()):4d} | ESPN alone {100*(wm(preds['ESPN alone'], mm)/wm(b0, mm)-1):+6.2f}% | shadow .5 + ESPN {100*(wm(preds['shadow 0.5 + ESPN'], mm)/wm(b0, mm)-1):+6.2f}% | shadow alone {100*(wm(preds['shadow alone'], mm)/wm(b0, mm)-1):+6.2f}%")
        # pick inside the Clay-free family, graded vs CLAY
        pick = lambda yrs: min(CF, key=lambda k: wm(preds[k], m & np.isin(year, yrs)))
        for flab, folds in (("LOYO", LOSO), ("forward", FORW)):
            pr_ = b0.copy(); picks = []; wins = 0
            for tr, te in folds:
                k = pick(tr); picks.append(k); mm = year == te; pr_[mm] = preds[k][mm]; wins += wm(preds[k], m & mm) < wm(b0, m & mm) - 1e-12
            tem = m & np.isin(year, [te for _, te in folds]); r, _ = RS(pr_, tem); r0_, _ = RS(b0, tem)
            P(f"  Clay-free pick {flab:8s}: error {100*(wm(pr_, tem)/wm(b0, tem)-1):+.2f}% vs CLAY ({wins}/{len(folds)}) | rho {r - r0_:+.4f} | picks {picks}")
    P("\nLimitations: ESPN weekly rows only where the file has the player (coverage printed); ESPN is an in-season weekly number, not a preseason prior; both the Clay form and ESPN carry their own game context; book anchor / docks not replayed; non-TE rows untouched.")
    LOG.close()


if __name__ == "__main__":
    main()
