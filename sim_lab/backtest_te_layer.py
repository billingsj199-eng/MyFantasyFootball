#!/usr/bin/env python3
"""
TIGHT ENDS on the Clay-free shadow (2026-09-16).

Jack: "build the tight end layer next." TE rows sit flat vs the shipped Clay blend on shadow v2.6 (every other
position is below Clay); week 1 TE +5.4% (act/shadow .88), 2nd-year TE +2.3%. Reads on the 3,686 TE player-weeks
by week band, string, age, ADP bucket and LAST SEASON'S ROUTE PARTICIPATION (nflverse participation: share of the
team's pass plays with the TE on the field, 2018-24; the live engine's TE route-trend layer is the in-season twin).
Sweeps, TE rows only, LOYO vs shadow v2.6:
  LEVEL        prior x m (all weeks) and in week 1 only
  P / SHRINK   TE prior strength (v2.6 = 8) and shrink k (.8)
  ADP          TE market weight (.75)
  AGE          the age curve on / off for TEs
  ROUTES       last season's route participation: low / high tercile x m ("blocking TE" vs "receiving TE")
  STRING       TE 2nd-string dock re-check (.8) and 3rd+ (none)
Candidate = passing pieces, forward. Log te_layer_backtest.log; data/te_layer_backtest.js (SIM_TE_BT), ZONES.
"""
import json, os, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import backtest_rookie_prior as RP
import backtest_rookie_depth_live as RD
import backtest_demoted_vets as DV
import backtest_nochart_vets as NC
import bt_common as B
from backtest_target_area import mse

sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "te_layer_backtest.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

YEARS, POS4, BANDS = NW.YEARS, NW.POS4, NW.BANDS
FIT_WK = 8
RAMP = [0.7, 0.8]
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "reads": [], "sweeps": [], "candidate": {}}


def load_route_rates():
    """(Y, gsis) -> TE route participation = pass plays on the field / team pass plays, seasons 2018-24."""
    pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "position"])
    tes = set(pl[pl.position == "TE"].gsis_id.dropna())
    out = {}
    for Y in range(2018, 2025):
        pbp = pd.read_csv(os.path.join(B.CACHE, f"play_by_play_{Y}.csv.gz"), usecols=["game_id", "play_id", "season_type", "posteam", "pass_attempt", "sack"], low_memory=False)
        pbp = pbp[(pbp.season_type == "REG") & (pbp.pass_attempt == 1) & pbp.posteam.notna()]
        keys = set(zip(pbp.game_id, pbp.play_id.astype(int)))
        part = pd.read_parquet(os.path.join(B.CACHE, f"pbp_participation_{Y}.parquet"), columns=["nflverse_game_id", "play_id", "possession_team", "offense_players"])
        part = part[part.offense_players.notna()]
        team_pass = defaultdict(int); te_pass = defaultdict(int)
        for r in part.itertuples(index=False):
            k = (r.nflverse_game_id, int(r.play_id))
            if k not in keys: continue
            t = B.tm(str(r.possession_team)); team_pass[t] += 1
            for gid in str(r.offense_players).split(";"):
                if gid in tes: te_pass[(gid, t)] += 1
        for (gid, t), c in te_pass.items():
            if team_pass[t] >= 200: out[(Y, gid)] = max(out.get((Y, gid), 0.0), c / team_pass[t])
        P(f"  routes {Y}: {len([k for k in out if k[0] == Y])} TE-seasons")
    return out


def main():
    t0 = time.time()
    P("=== Tight ends on the Clay-free shadow ===")
    S = NW.build_samples(); A = NW.arrays(S); n = len(S)
    act, year, wk, pos, g, ppg, clay, layers = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"]
    is_rookie, pid, team = A["rookie"], A["pid"], A["team"]
    shipped = NW.blend(clay, g, ppg, NW.PRIOR_P) * layers
    weekly, dated = RD.load_depth(); weekly_any, dated_any = NC.load_depth_any(); games = {Y: B.load_games(Y) for Y in YEARS}
    def string_at(i, w, same_team=True):
        if pid[i] is None: return None
        if year[i] <= 2024:
            if same_team: return weekly.get((year[i], pid[i], team[i], w))
            v = weekly_any.get((year[i], pid[i], w)); return v[0] if v else None
        gm = games[2025].get((team[i], w))
        if not gm: return None
        lst = dated.get((pid[i], team[i])) if same_team else dated_any.get(pid[i])
        if not lst: return None
        before = [x for x in lst if x[0] < gm["date"]]
        return before[-1][1] if before else None
    string = np.array([np.nan if string_at(i, wk[i]) is None else string_at(i, wk[i]) for i in range(n)], dtype=float)
    any_str = np.array([np.nan if string_at(i, wk[i], False) is None else string_at(i, wk[i], False) for i in range(n)], dtype=float)
    str_any = np.where(np.isnan(string), any_str, string); has = ~np.isnan(str_any); strb = np.where(has, np.minimum(str_any, 3), np.nan)
    # ---- v2.6 prior pieces ----
    adp_map = RP.load_adp()
    adp = np.array([adp_map.get((y, NW.cal.norm(nm), ps), np.nan) for y, nm, ps in zip(year, A["name"], pos)])
    has_adp = ~np.isnan(adp); ladp = np.log(np.where(has_adp, adp, RP.ADP_CAP)); lpick = np.log(np.where(np.isnan(A["pick"]), 262.0, A["pick"]))
    h3, l8 = A["h3"], A["l8"]; has_h3, has_l8 = ~np.isnan(h3), ~np.isnan(l8)
    yr2 = A["exp"] == 1
    raw_hist = np.full(n, np.nan); both = has_h3 & has_l8
    raw_hist[both] = 0.5 * h3[both] + 0.5 * l8[both]; raw_hist[has_h3 & ~has_l8] = h3[has_h3 & ~has_l8]; raw_hist[~has_h3 & has_l8] = l8[~has_h3 & has_l8]
    def hist_with_age(use_age_te):
        hist = raw_hist.copy()
        for i in np.where(~np.isnan(hist))[0]:
            if pos[i] == "TE" and not use_age_te: continue
            hist[i] = NW.age_adjust(pos[i], hist[i], A["age"][i])
        oppcal = A["oppcal"]; vet_opp = (~np.isnan(oppcal)) & (A["seg"] != "rookie") & (~is_rookie) & ~np.isnan(hist) & (hist >= 4); hist[vet_opp] = oppcal[vet_opp]
        return hist
    hist0 = hist_with_age(True); hist_noage = hist_with_age(False); has_hist = ~np.isnan(hist0)
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
    vet = ~is_rookie & has_hist; buried_rk = is_rookie & ~(strb == 1); te = pos == "TE"
    # 2nd-year low-snap boost (v2.6) via the second-year loader
    import backtest_second_year as SY
    snaps = SY.load_snaps()
    late = np.array([snaps[(year[i] - 1, pid[i])]["late"] if (pid[i] and (year[i] - 1, pid[i]) in snaps) else np.nan for i in range(n)])
    yr2lo = yr2 & ~np.isnan(late) & (late < 0.4)
    PPOS0 = {"QB": 12, "RB": 5, "WR": 8, "TE": 8}
    def build(hist=None, P_te=8, k_te=0.8, w_te=0.75, mult=None, dock2=0.8, dock3=1.0):
        hist = hist0 if hist is None else hist
        wv = np.where(yr2, 0.5, 0.75); wv = np.where(te & ~yr2, w_te, wv)
        pr = np.where(mkt_ok, (1 - wv) * hist + wv * adp_curve, hist)
        miss = np.isnan(pr); pr[miss] = fb[miss]
        vd = {"RB": {2: 0.8, 3: 0.4}, "WR": {2: 0.6, 3: 0.6}, "TE": {2: dock2, 3: dock3}}
        for ps, d in vd.items():
            for sb, mm_ in d.items():
                mk = vet & (pos == ps) & (strb == sb); pr[mk] *= mm_
        pr = np.where(yr2lo & vet, pr * 1.2, pr)
        if mult is not None: pr = pr * mult
        kk = np.where(te, k_te, 0.8); pr = fb_pos + kk * (pr - fb_pos)
        Pv = np.array([PPOS0[ps] for ps in pos], dtype=float); Pv = np.where(te, P_te, Pv)
        out = NW.blend(pr, g, ppg, Pv) * layers
        for gi, m_ in enumerate(RAMP, start=1): out = np.where(buried_rk & (wk == gi), out * m_, out)
        return out
    ref = build()
    pc, w, ny = NW.pct_vs(ref, shipped, act, year)
    P(f"  {n} player-weeks | shadow v2.6 vs shipped {pc:+.2f}% ({w}/{ny}) | TE rows {te.sum()}: {(mse(ref[te], act[te]) / mse(shipped[te], act[te]) - 1) * 100:+.2f}% vs shipped")

    # ---- route participation feature (last season) ----
    rr = load_route_rates()
    route = np.array([rr.get((year[i] - 1, pid[i]), np.nan) if pid[i] else np.nan for i in range(n)])
    has_rt = ~np.isnan(route)
    q = np.nanpercentile(route[te & vet & has_rt], [33.3, 66.7])
    P(f"  TE rows with last-season route participation: {int((te & has_rt).sum())} (terciles at {q[0]:.2f} / {q[1]:.2f})")
    P("\n=== TE reads (actual / shadow, actual / shipped, shadow vs shipped) ===")
    def read(lab, mm):
        if mm.sum() < 20: P(f"  {lab:40s} n={mm.sum()} too few"); return
        row = {"label": lab, "n": int(mm.sum()), "actOverShadow": round(float(act[mm].mean() / ref[mm].mean()), 3), "actOverShipped": round(float(act[mm].mean() / shipped[mm].mean()), 3), "vsShip": round((mse(ref[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 2)}
        RES["reads"].append(row); P(f"  {lab:40s} n={mm.sum():5d} act/shadow {row['actOverShadow']:.3f} act/shipped {row['actOverShipped']:.3f} shadow vs shipped {row['vsShip']:+6.2f}%")
    read("TE, all", te)
    for lab, lo, hi in BANDS: read(f"  {lab}", te & (wk >= lo) & (wk <= hi))
    read("  vets same team", te & vet & ~A["mover"]); read("  vets changed team", te & vet & A["mover"]); read("  2nd-year", te & yr2 & has_hist); read("  rookies", te & is_rookie)
    for sb, lab in ((1, "1st string"), (2, "2nd string"), (3, "3rd+")): read(f"  vets {lab}", te & vet & (strb == sb))
    for lab, lo, hi in (("age <= 25", 0, 25), ("age 26-29", 25, 29), ("age 30+", 29, 99)): read(f"  vets {lab}", te & vet & (A["age"] > lo) & (A["age"] <= hi))
    for lab, lo, hi in (("ADP 1-60", 0, 60), ("ADP 61-120", 60, 120), ("ADP 121-180", 120, 181)): read(f"  vets {lab}", te & vet & has_adp & (adp > lo) & (adp <= hi))
    read("  vets no ADP", te & vet & ~has_adp)
    read(f"  vets route rate low (< {q[0]:.2f})", te & vet & has_rt & (route < q[0])); read("  vets route rate mid", te & vet & has_rt & (route >= q[0]) & (route <= q[1])); read(f"  vets route rate high (> {q[1]:.2f})", te & vet & has_rt & (route > q[1]))
    read("  vets high routes & prior < 6 half-PPR", te & vet & has_rt & (route > q[1]) & (raw_hist < 6)); read("  vets low routes & prior >= 6", te & vet & has_rt & (route < q[0]) & (raw_hist >= 6))

    # ---- sweeps ----
    P("\n=== TE sweeps (LOYO vs shadow v2.6) ===")
    DV.RES["sweeps"] = []
    def mult_on(mask, m_): v = np.ones(n); v[mask] = m_; return v
    DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.95, 0.9, 1.05, 1.1], lambda m_: build(mult=mult_on(te, m_)), "LEVEL TE x m (all weeks)", te)
    DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.95, 0.9, 0.85, 1.05], lambda m_: np.where(te & (wk == 1), ref * m_, ref), "  LEVEL TE week 1 x m", te & (wk == 1))
    DV.loyo_vs_ref(A, ref, shipped, [8, 5, 6, 10, 12, 16], lambda p_: build(P_te=p_), "P prior strength, TE", te)
    DV.loyo_vs_ref(A, ref, shipped, [0.8, 0.7, 0.6, 0.9, 1.0], lambda k_: build(k_te=k_), "SHRINK k, TE", te)
    DV.loyo_vs_ref(A, ref, shipped, [0.75, 0.5, 0.9, 1.0, 0.25], lambda w_: build(w_te=w_), "ADP weight, TE vets", te & vet & mkt_ok)
    DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.0], lambda on_: build(hist=(hist0 if on_ == 1.0 else hist_noage)), "AGE curve on (1) / off (0), TE", te & vet)
    DV.loyo_vs_ref(A, ref, shipped, [0.8, 0.9, 0.7, 0.6, 1.0], lambda d_: build(dock2=d_), "2nd-string dock, TE (re-check)", te & vet & (strb == 2))
    DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.9, 0.8, 0.7], lambda d_: build(dock3=d_), "3rd+ dock, TE", te & vet & (strb == 3))
    lo_r = te & vet & has_rt & (route < q[0]); hi_r = te & vet & has_rt & (route > q[1])
    DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.9, 0.8, 1.1, 1.2], lambda m_: build(mult=mult_on(lo_r, m_)), "ROUTES: low-route TE x m", lo_r)
    DV.loyo_vs_ref(A, ref, shipped, [1.0, 1.1, 1.2, 0.9, 0.8], lambda m_: build(mult=mult_on(hi_r, m_)), "ROUTES: high-route TE x m", hi_r)
    hi_lowp = te & vet & has_rt & (route > q[1]) & (raw_hist < 6)
    if hi_lowp.sum() >= 40: DV.loyo_vs_ref(A, ref, shipped, [1.0, 1.1, 1.2, 1.3, 0.9], lambda m_: build(mult=mult_on(hi_lowp, m_)), "  high routes & prior < 6 x m", hi_lowp)
    DV.loyo_vs_ref(A, ref, shipped, [1.0, 1.1, 1.2, 0.9], lambda m_: build(mult=mult_on(te & yr2 & has_hist, m_)), "2nd-year TE x m", te & yr2 & has_hist)
    RES["sweeps"] = DV.RES["sweeps"]

    # ---- candidate + forward ----
    pieces = [r for r in RES["sweeps"] if r["verdict"] in ("PASS", "lean")]
    P("\n=== Candidate from passing pieces: " + (", ".join(f"{r['label'].strip()} = {r['pooledBest']}" for r in pieces) if pieces else "NONE") + " ===")
    def cand_pred(cfg):
        kw = {}; mult = np.ones(n)
        for lab, v in cfg.items():
            if lab.startswith("P prior"): kw["P_te"] = v
            elif lab.startswith("SHRINK"): kw["k_te"] = v
            elif lab.startswith("ADP weight"): kw["w_te"] = v
            elif lab.startswith("AGE"): kw["hist"] = hist0 if v == 1.0 else hist_noage
            elif lab.startswith("2nd-string dock"): kw["dock2"] = v
            elif lab.startswith("3rd+ dock"): kw["dock3"] = v
            elif lab.startswith("LEVEL TE x m"): mult[te] *= v
            elif lab.startswith("ROUTES: low"): mult[lo_r] *= v
            elif lab.startswith("ROUTES: high"): mult[hi_r] *= v
            elif "high routes & prior" in lab: mult[hi_lowp] *= v
            elif lab.startswith("2nd-year TE"): mult[te & yr2 & has_hist] *= v
        out = build(mult=mult, **kw)
        if "  LEVEL TE week 1 x m" in cfg: out = np.where(te & (wk == 1), out * cfg["  LEVEL TE week 1 x m"], out)
        return out
    cfg = {r["label"]: r["pooledBest"] for r in pieces}
    cand = cand_pred(cfg) if pieces else ref
    pc2, w2, ny2 = NW.pct_vs(cand, shipped, act, year); pv, wvv, _ = NW.pct_vs(cand, ref, act, year); pt, wt, _ = NW.pct_vs(cand[te], ref[te], act[te], year[te])
    P(f"  ALL rows: vs shipped {pc2:+.2f}% ({w2}/{ny2}) | vs shadow v2.6 {pv:+.2f}% ({wvv}/{ny2}) | TE rows {pt:+.2f}% vs shadow ({wt}/{ny2}), vs shipped {(mse(cand[te], act[te]) / mse(shipped[te], act[te]) - 1) * 100:+.2f}% (was {(mse(ref[te], act[te]) / mse(shipped[te], act[te]) - 1) * 100:+.2f}%)")
    RES["pieceForward"] = []; fm = year >= YEARS[2]; ft = fm & te
    for r in pieces:
        fw = np.full(n, np.nan)
        for y in YEARS[2:]:
            mk = te & (year < y)
            v = min(r["grid"], key=lambda v: mse(cand_pred({r["label"]: v})[mk], act[mk])) if mk.sum() >= 60 else r["grid"][0]
            fw = np.where(year == y, cand_pred({r["label"]: v}), fw)
        pa_, wa_, py_ = NW.pct_vs(fw[fm], ref[fm], act[fm], year[fm]); pt_, wt_, _ = NW.pct_vs(fw[ft], ref[ft], act[ft], year[ft])
        RES["pieceForward"].append({"label": r["label"].strip(), "allVsRef": round(pa_, 3), "allWins": int(wa_), "teVsRef": round(pt_, 3), "teWins": int(wt_), "years": py_})
        P(f"  FORWARD piece {r['label'].strip():36s}: all rows {pa_:+.2f}% ({wa_}/{py_}) | TE rows {pt_:+.2f}% ({wt_}/{py_})")
    RES["candidate"] = {"cfg": cfg, "pct": round(pc2, 3), "wins": int(w2), "years": ny2, "vsRef": round(pv, 3), "vsRefWins": int(wvv), "teVsRef": round(pt, 3), "teWins": int(wt),
                        "teVsShip": round((mse(cand[te], act[te]) / mse(shipped[te], act[te]) - 1) * 100, 3), "teRefVsShip": round((mse(ref[te], act[te]) / mse(shipped[te], act[te]) - 1) * 100, 3)}
    RES["summary"] = (f"TE rows (n {te.sum()}) shadow {RES['candidate']['teRefVsShip']:+.2f}% vs shipped. " + "; ".join(f"{r['label'].strip()} {r['loyoPct']:+.2f}% ({r['wins']}/{r['years']}, {r['verdict']})" for r in RES["sweeps"]) +
                      f". Candidate: TE rows {pt:+.2f}% vs v2.6 ({wt}/{ny2}).")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "te_layer_backtest.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_TE_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/te_layer_backtest.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
