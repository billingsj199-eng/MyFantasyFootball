#!/usr/bin/env python3
"""
VACATED ROLE on the Clay-free shadow (2026-09-16).

Jack: "build the vacated role layer for the shadow next." Live, a zeroed player's projection is redistributed to
the healthy teammates by depth rank (applyInSeasonInjuries -> iA > 1) and the shadow inherits the SAME multiplier
- a ratio computed on the Clay base. build_live_layers.py rebuilt that layer from shares (pool_mult = 1 + points
gained from vacated targets / carries by the engine's depth weights, over the player's season-to-date PPG), which
is Clay-free by construction, on the 17,657 context player-weeks. Here it is graded on the shadow: shadow x
pool_mult^k, k in {0 .. 2} (k = 1 is the live strength), on the rows where a role was vacated, by position and by
size of the boost; the backup-QB inheritance multiplier on QB rows; forward. The harness shadow has NO vacated
layer, so the reference is "shadow without it".
Log vacated_shadow_backtest.log; results -> data/vacated_shadow_backtest.js (SIM_VACATED_BT), ZONES tab.
"""
import json, os, sys, time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import backtest_rookie_prior as RP
import backtest_rookie_depth_live as RD
import backtest_demoted_vets as DV
import backtest_nochart_vets as NC
import backtest_second_year as SY
import bt_common as B
from backtest_target_area import mse

sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "vacated_shadow_backtest.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

YEARS, POS4, BANDS = NW.YEARS, NW.POS4, NW.BANDS
FIT_WK = 8; RAMP = [0.7, 0.8]
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "reads": [], "sweeps": [], "candidate": {}, "curve": {}}


def load_grades():
    pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "pff_id"])
    pff2g = {int(r.pff_id): r.gsis_id for r in pl.itertuples(index=False) if pd.notna(r.pff_id) and isinstance(r.gsis_id, str)}
    out = {}
    for Y in range(2018, 2026):
        f = os.path.join(B.CACHE, "pff", f"pff_receiving_{Y}.csv")
        if not os.path.exists(f): continue
        d = pd.read_csv(f)
        for r in d.itertuples(index=False):
            g = pff2g.get(int(r.player_id))
            if g and (r.routes or 0) >= 50 and pd.notna(r.grades_pass_route): out[(Y, g)] = (float(r.grades_pass_route), float(r.routes))
    return out


def main():
    t0 = time.time()
    P("=== Vacated role on the Clay-free shadow ===")
    S = NW.build_samples(); A = NW.arrays(S); n = len(S)
    act, year, wk, pos, g, ppg, clay, layers = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"]
    is_rookie, pid, team = A["rookie"], A["pid"], A["team"]
    shipped = NW.blend(clay, g, ppg, NW.PRIOR_P) * layers
    games = {Y: B.load_games(Y) for Y in YEARS}
    weekly, dated = RD.load_depth(); weekly_any, dated_any = NC.load_depth_any()
    def string_at(i, w, same_team=True):
        if pid[i] is None: return None
        if year[i] <= 2024:
            if same_team: return weekly.get((year[i], pid[i], team[i], w))
            v = weekly_any.get((year[i], pid[i], w)); return v[0] if v else None
        gm = games[2025].get((team[i], w))
        if not gm: return None
        lst = dated.get((pid[i], team[i])) if same_team else dated_any.get(pid[i])
        if not lst: return None
        before = [q for q in lst if q[0] < gm["date"]]
        return before[-1][1] if before else None
    string = np.array([np.nan if string_at(i, wk[i]) is None else string_at(i, wk[i]) for i in range(n)], dtype=float)
    any_str = np.array([np.nan if string_at(i, wk[i], False) is None else string_at(i, wk[i], False) for i in range(n)], dtype=float)
    str_any = np.where(np.isnan(string), any_str, string); has = ~np.isnan(str_any); strb = np.where(has, np.minimum(str_any, 3), np.nan)
    adp_map = RP.load_adp()
    adp = np.array([adp_map.get((y, NW.cal.norm(nm), ps), np.nan) for y, nm, ps in zip(year, A["name"], pos)])
    has_adp = ~np.isnan(adp); ladp = np.log(np.where(has_adp, adp, RP.ADP_CAP)); lpick = np.log(np.where(np.isnan(A["pick"]), 262.0, A["pick"]))
    h3, l8 = A["h3"], A["l8"]; has_h3, has_l8 = ~np.isnan(h3), ~np.isnan(l8); yr2 = A["exp"] == 1
    hist = np.full(n, np.nan); both = has_h3 & has_l8
    hist[both] = 0.5 * h3[both] + 0.5 * l8[both]; hist[has_h3 & ~has_l8] = h3[has_h3 & ~has_l8]; hist[~has_h3 & has_l8] = l8[~has_h3 & has_l8]
    for i in np.where(~np.isnan(hist))[0]: hist[i] = NW.age_adjust(pos[i], hist[i], A["age"][i])
    oppcal = A["oppcal"]; vet_opp = (~np.isnan(oppcal)) & (A["seg"] != "rookie") & (~is_rookie) & ~np.isnan(hist) & (hist >= 4); hist[vet_opp] = oppcal[vet_opp]
    has_hist = ~np.isnan(hist)
    adp_curve = np.full(n, np.nan)
    for y in YEARS:
        for ps in POS4:
            tr = (year != y) & (pos == ps) & has_adp & (wk <= FIT_WK); ap = (year == y) & (pos == ps) & has_adp
            if tr.sum() >= 60 and ap.any():
                b = np.linalg.lstsq(np.column_stack([np.ones(tr.sum()), ladp[tr]]), act[tr], rcond=None)[0]; adp_curve[ap] = np.maximum(0.5, b[0] + b[1] * ladp[ap])
    mkt_ok = ~is_rookie & ~np.isnan(adp_curve) & has_hist
    pos_mean = {ps: NW.loyo_const(A, lambda ps=ps: (pos == ps), YEARS) for ps in POS4}
    fb_pos = np.array([pos_mean[ps].get(y, np.nan) for ps, y in zip(pos, year)]); fb = fb_pos.copy()
    for y in YEARS:
        for ps in POS4:
            tr = (year != y) & is_rookie & (pos == ps) & (wk <= FIT_WK); ap = (year == y) & is_rookie & (pos == ps)
            if tr.sum() < 40 or not ap.any(): continue
            def X(m):
                cols = [np.ones(m.sum()), lpick[m]]
                if ps in ("RB", "WR"): cols += [np.where(has[m], (strb[m] == 2).astype(float), 0.0), np.where(has[m], (strb[m] >= 3).astype(float), 1.0)]
                return np.column_stack(cols)
            b = np.linalg.lstsq(X(tr), act[tr], rcond=None)[0]; fb[ap] = np.maximum(0.5, X(ap) @ b)
    vet = ~is_rookie & has_hist; buried_rk = is_rookie & ~(strb == 1)
    snaps = SY.load_snaps(); late = np.array([snaps[(year[i] - 1, pid[i])]["late"] if (pid[i] and (year[i] - 1, pid[i]) in snaps) else np.nan for i in range(n)]); yr2lo = yr2 & ~np.isnan(late) & (late < 0.4)
    PPOS0 = {"QB": 12, "RB": 5, "WR": 8, "TE": 8}; Pvec = np.array([PPOS0[ps] for ps in pos], dtype=float)
    def prior_base():
        wv = np.where(yr2, 0.5, 0.75); pr = np.where(mkt_ok, (1 - wv) * hist + wv * adp_curve, hist)
        miss = np.isnan(pr); pr[miss] = fb[miss]
        for ps, d in NC.VETDOCK.items():
            for sb, mm_ in d.items():
                mk = vet & (pos == ps) & (strb == sb); pr[mk] *= mm_
        pr = np.where(yr2lo & vet, pr * 1.2, pr)
        return pr
    pr0 = prior_base()
    def build(pr=None, mask_wk=None):
        pr = pr0 if pr is None else pr
        pr = fb_pos + 0.8 * (pr - fb_pos)
        out = NW.blend(pr, g, ppg, Pvec) * layers
        for gi, m_ in enumerate(RAMP, start=1): out = np.where(buried_rk & (wk == gi), out * m_, out)
        return out
    ref = build()
    pc, w, ny = NW.pct_vs(ref, shipped, act, year)
    # ---- join the rebuilt live layers (pool_mult, qb_inherit_mult) by (year, pid, wk) ----
    L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet"), columns=["year", "pid", "wk", "pool_mult", "qb_inherit_mult", "pool_gain_tg", "pool_gain_car"])
    key = {(int(r.year), r.pid, int(r.wk)): (float(r.pool_mult), float(r.qb_inherit_mult)) for r in L.itertuples(index=False) if isinstance(r.pid, str)}
    pm = np.array([key.get((year[i], pid[i], wk[i]), (np.nan, np.nan))[0] if pid[i] else np.nan for i in range(n)])
    qi = np.array([key.get((year[i], pid[i], wk[i]), (np.nan, np.nan))[1] if pid[i] else np.nan for i in range(n)])
    joined = ~np.isnan(pm); on = joined & (pm > 1.0); qon = joined & (qi > 1.0)
    P(f"  {n} player-weeks | shadow v2.6 vs shipped {pc:+.2f}% ({w}/{ny}) | joined to the rebuilt live layers: {joined.sum()} rows, vacated-role boost on {on.sum()} (mean x{pm[on].mean():.3f}, max x{pm[on].max():.2f}), QB inheritance on {qon.sum()}")
    P("\n=== Reads: actual / shadow on boosted rows (shadow WITHOUT the layer) ===")
    shr0 = ref
    for lab, mm in (("all boosted", on), ("boost 1.00-1.05", on & (pm <= 1.05)), ("boost 1.05-1.15", on & (pm > 1.05) & (pm <= 1.15)), ("boost 1.15-1.4", on & (pm > 1.15) & (pm <= 1.4)), ("boost > 1.4", on & (pm > 1.4)),
                    ("QB inheritance", qon)):
        if mm.sum() >= 20: P(f"  {lab:18s} n={mm.sum():5d} act/shadow {act[mm].mean() / ref[mm].mean():.3f} act/shipped {act[mm].mean() / shipped[mm].mean():.3f} shadow vs shipped {(mse(ref[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100:+.2f}% | mean pool_mult {pm[mm].mean():.3f}")
    for ps in POS4:
        mm = on & (pos == ps)
        if mm.sum() >= 30: P(f"  boosted {ps:3s}        n={mm.sum():5d} act/shadow {act[mm].mean() / ref[mm].mean():.3f} act/shipped {act[mm].mean() / shipped[mm].mean():.3f} | mean pool_mult {pm[mm].mean():.3f}")
    # ---- sweeps ----
    P("\n=== Sweeps: shadow x pool_mult^k, LOYO vs shadow (k = 1 is the live strength) ===")
    DV.RES["sweeps"] = []
    KG = [0.0, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
    def pool(k, mask): return np.where(mask, ref * np.power(pm, k), ref)
    DV.loyo_vs_ref(A, ref, shipped, KG, lambda k: pool(k, on), "vacated-role boost ^k, all boosted rows", on)
    for ps in POS4:
        mm = on & (pos == ps)
        if mm.sum() >= 60: DV.loyo_vs_ref(A, ref, shipped, KG, lambda k, mm=mm: pool(k, mm), f"  ^k, {ps}", mm)
    for lab, mm in (("boost <= 1.05", on & (pm <= 1.05)), ("boost 1.05-1.15", on & (pm > 1.05) & (pm <= 1.15)), ("boost > 1.15", on & (pm > 1.15))):
        if mm.sum() >= 60: DV.loyo_vs_ref(A, ref, shipped, KG, lambda k, mm=mm: pool(k, mm), f"  ^k, {lab}", mm)
    if qon.sum() >= 5:
        DV.loyo_vs_ref(A, ref, shipped, [0.0, 0.5, 1.0, 1.5], lambda k: np.where(qon, ref * np.power(qi, k), ref), "  backup-QB inheritance ^k (n small)", qon)
    RES["sweeps"] = DV.RES["sweeps"]
    top = RES["sweeps"][0]; k_best = top["pooledBest"]
    cand = pool(k_best, on)
    pc2, w2, ny2 = NW.pct_vs(cand, shipped, act, year); pv, wvv, _ = NW.pct_vs(cand, ref, act, year); pa, wa, _ = NW.pct_vs(cand[on], ref[on], act[on], year[on])
    P(f"\n=== Candidate: pool_mult^{k_best} ===")
    P(f"  ALL rows: vs shipped {pc2:+.2f}% ({w2}/{ny2}) | vs shadow {pv:+.2f}% ({wvv}/{ny2}) | boosted rows n={on.sum()} {pa:+.2f}% ({wa}/{ny2})")
    fwd = np.full(n, np.nan); fm = year >= YEARS[2]
    for y in YEARS[2:]:
        mk = on & (year < y); k_y = min(KG, key=lambda k: mse(pool(k, on)[mk], act[mk])); fwd = np.where(year == y, pool(k_y, on), fwd)
    fr, frw, fy = NW.pct_vs(fwd[fm], ref[fm], act[fm], year[fm]); fa, faw, _ = NW.pct_vs(fwd[fm & on], ref[fm & on], act[fm & on], year[fm & on])
    P(f"  FORWARD (2021-25, k picked on earlier seasons): all rows {fr:+.2f}% ({frw}/{fy}) | boosted rows {fa:+.2f}% ({faw}/{fy})")
    RES["candidate"] = {"k": float(k_best), "pct": round(pc2, 3), "wins": int(w2), "years": ny2, "vsRef": round(pv, 3), "vsRefWins": int(wvv), "affectedN": int(on.sum()), "affectedVsRef": round(pa, 3), "affectedWins": int(wa),
                        "forward": {"vsRef": round(fr, 3), "vsRefWins": int(frw), "years": fy, "affectedVsRef": round(fa, 3), "affectedWins": int(faw)}}
    RES["summary"] = (f"Vacated-role boost on the shadow: k best {k_best} ({top['loyoPct']:+.2f}% on boosted rows vs shadow without it, {top['wins']}/{top['years']}, {top['verdict']}); " +
                      "; ".join(f"{r['label'].strip()} k {r['pooledBest']} {r['loyoPct']:+.2f}% ({r['wins']}/{r['years']})" for r in RES["sweeps"][1:]) + f". Forward boosted rows {fa:+.2f}% ({faw}/{fy}).")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "vacated_shadow_backtest.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_VACATED_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/vacated_shadow_backtest.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
