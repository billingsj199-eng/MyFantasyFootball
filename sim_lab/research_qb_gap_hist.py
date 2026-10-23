#!/usr/bin/env python3
"""
QB GAP vs THE MARKET, HISTORY 2013-25 (Jack 2026-10-23: is the 2026 QB lag 2026-only?) - research only, nothing wired.
Harness = the wired Clay-free shadow, NEXT game, as research_oos_layer_retest.full_next() builds it (team fix on),
QB rows only, top-150 ADP, final week out, row filter shadow >= 3 like the OOS harness.
Market references available historically (book props do not exist before 2026):
  ESPN weekly projection (2019-25, rescored to half-PPR incl. -1 INT / -2 FL)  = the "site market"
  Vegas-only QB line: act ~ a + b x implied team total (LOYO fit, 2013-25)     = the pure betting-market read
Sections
  1  QB level / MAE / rank by season: shadow vs ESPN vs Vegas-only (and the RB/WR/TE gap vs ESPN for contrast)
  2  where the QB shadow error sits (segments: rushing share, team total, spread, tier, games, team change, Questionable)
  3  candidate QB fixes, leave-one-season-out + forward, graded on top-150 MAE + rank (within week) + level:
     H1 blend toward ESPN (2019-25) k LOYO          (the 2026 consensus edge, as a history check)
     H2 blend toward the Vegas-only QB line k LOYO  (a heavier "market" anchor that exists in history)
     H3 two-sided shrink of the QB tier to the week's QB mean (bias at the extremes)
Log _bt_ext/qb_gap_hist_ext2012_2025_tf.log  |  SIM_BT_YEARS=2012-2025 python research_qb_gap_hist.py
"""
import os, sys, pickle, json, re
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_ext as BX
GY = list(range(2013, 2026)); EY = list(range(2019, 2026)); POS4 = ("QB", "RB", "WR", "TE")
ESPN_DIR = r"E:\MyFantasyFootball\pbp_cache\espn_proj"


def nrm(s):
    s = str(s).lower().replace(".", "").replace("'", "").replace("-", " "); s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s); return re.sub(r"\s+", " ", s).strip()


def espn_half(s):
    g = lambda k: float(s.get(k, 0) or 0)
    return 0.04 * g("3") + 4 * g("4") - 1 * g("20") + 0.1 * g("24") + 6 * g("25") + 0.1 * g("42") + 6 * g("43") + 0.5 * g("53") - 2 * g("72")


def main():
    log = open(BX.ext_path("qb_gap_hist.log"), "w", encoding="utf-8")
    def P(s=""): print(s, flush=True); log.write(s + "\n"); log.flush()
    X = pickle.load(open(BX.ext_path("X_cache.pkl"), "rb"))
    n = X["n"]; F = X["F"]; A = X["A"]
    act, year, wk, pos, g, name, adp, layers = X["act"], X["year"].astype(int), X["wk"], X["pos"], X["g"], X["name"], X["adp"], X["layers"]
    C = pd.read_parquet(BX.ext_path("ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = A["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    # ---- wired next-game shadow (research_oos_layer_retest.full_next, S = {}) ----
    lamb = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    ev = lamb * X["xf"] + (1 - lamb) * X["ppg_v"]
    Pw = F["Pvec"] * np.where((pos == "WR") & (g == 1), 5.0, 1.0)
    SH = (Pw * X["prior"] + g * ev) / np.maximum(Pw + g, 1e-9) * layers
    for gi, m_ in enumerate([0.7, 0.8], start=1): SH = np.where(F["buried_rk"] & (wk == gi), SH * m_, SH)
    SH = np.where(F["on"], SH * np.power(F["pm"], 0.75), SH)
    tq = (pos == "QB") & ((adp > 30) | np.isnan(adp)); SH = np.where(tq, SH * np.exp(0.03 * X["z"]), SH)
    SH = np.where((pos == "QB") & X["mover"], SH * 0.90, SH)
    low = np.maximum(0, 19 - np.nan_to_num(X["implied"], nan=19)) / 19; SH = np.where(pos == "QB", SH * (1 - 0.75 * low), SH)
    finw = np.where(year <= 2020, 17, 18); final = wk == finw
    base = (adp <= 150) & ~final & (year >= 2013) & (SH >= 3)
    # ---- ESPN ----
    E = {}
    for Y in EY:
        d = json.load(open(os.path.join(ESPN_DIR, f"espn_proj_{Y}.json"), encoding="utf-8"))
        for w_, rows in d["weeks"].items():
            for k, v in rows.items():
                nm, ps = k.rsplit("|", 1); E[(Y, int(w_), nrm(nm), ps)] = espn_half(v.get("s") or {})
    esp = np.array([E.get((int(year[i]), int(wk[i]), nrm(name[i]), pos[i]), np.nan) for i in range(n)], dtype=float)
    imp = X["implied"]; spread = colv("spread"); carsh = colv("car_sh"); repq = colv("rep_q"); tchg = colv("team_change"); exp_ = colv("exp")
    Q = base & (pos == "QB")
    # ---- Vegas-only QB line, LOYO over 2013-25 ----
    veg = np.full(n, np.nan)
    okv = Q & ~np.isnan(imp)
    for y in GY:
        tr = okv & (year != y); te = (pos == "QB") & (year == y) & ~np.isnan(imp)
        b = np.polyfit(imp[tr], act[tr], 1); veg[te] = np.polyval(b, imp[te])
    def mae(p, m): return float(np.mean(np.abs(p[m] - act[m])))
    def rho(p, m):
        gr = defaultdict(list)
        for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        v = [np.corrcoef(rankdata(act[np.array(ix)]), rankdata(p[np.array(ix)]))[0, 1] for ix in gr.values() if len(ix) >= 8]
        return float(np.nanmean(v)) if v else np.nan
    QE = Q & ~np.isnan(esp) & (esp > 0)
    P(f"=== QB gap vs market, history: {BX.describe()} | QB next-game rows top-150 2013-25 {int(Q.sum()):,} (ESPN-matched 2019-25 {int(QE.sum()):,}) ===")
    P("\n--- 1  by season: MAE | bias (proj - act) | within-week rank rho ---")
    P(f"  {'season':6s} {'n':>5s} | {'shadow':>22s} | {'Vegas-only':>22s} | {'ESPN':>22s} | shadow vs ESPN MAE")
    for y in GY:
        m = Q & (year == y); me = QE & (year == y)
        s = f"  {y:6d} {int(m.sum()):5d} | {mae(SH, m):5.2f} {np.mean(SH[m]-act[m]):+5.2f} {rho(SH, m):.3f} | {mae(veg, m & ~np.isnan(veg)):5.2f} {np.mean(veg[m & ~np.isnan(veg)]-act[m & ~np.isnan(veg)]):+5.2f} {rho(veg, m & ~np.isnan(veg)):.3f} |"
        if me.sum() > 50: s += f" {mae(esp, me):5.2f} {np.mean(esp[me]-act[me]):+5.2f} {rho(esp, me):.3f} | {100*(mae(SH, me)/mae(esp, me)-1):+5.2f}% (n{int(me.sum())})"
        P(s)
    for lab, m in (("2013-18", Q & (year <= 2018)), ("2019-25", Q & (year >= 2019)), ("2013-25", Q)):
        P(f"  {lab:7s} {int(m.sum()):5d} | shadow MAE {mae(SH, m):5.3f} bias {np.mean(SH[m]-act[m]):+5.2f} rho {rho(SH, m):.3f} | Vegas-only MAE {mae(veg, m & ~np.isnan(veg)):5.3f} rho {rho(veg, m & ~np.isnan(veg)):.3f} (rows with a total {int((m & ~np.isnan(veg)).sum())})")
    P(f"  ESPN-matched 2019-25: shadow MAE {mae(SH, QE):.3f} bias {np.mean(SH[QE]-act[QE]):+.2f} rho {rho(SH, QE):.4f} | ESPN MAE {mae(esp, QE):.3f} bias {np.mean(esp[QE]-act[QE]):+.2f} rho {rho(esp, QE):.4f} | gap {100*(mae(SH, QE)/mae(esp, QE)-1):+.2f}%"
      f" | seasons ESPN better {sum(1 for y in EY if mae(esp, QE & (year == y)) < mae(SH, QE & (year == y)))}/7")
    P("  contrast, other positions vs ESPN (2019-25, same filters):")
    for ps in ("RB", "WR", "TE"):
        m = base & (pos == ps) & ~np.isnan(esp) & (esp > 0)
        P(f"    {ps}: n{int(m.sum()):5d} shadow MAE {mae(SH, m):.3f} ESPN {mae(esp, m):.3f} gap {100*(mae(SH, m)/mae(esp, m)-1):+.2f}% | rho {rho(SH, m):.4f} vs {rho(esp, m):.4f}")

    P("\n--- 2  where the QB shadow error sits (ESPN-matched 2019-25: share of the MAE gap; level act/proj both eras) ---")
    tot = float(np.sum(np.abs(SH[QE] - act[QE]) - np.abs(esp[QE] - act[QE])))
    segs = [("rushing QB (car share >= .15)", carsh >= 0.15), ("some rushing .08-.15", (carsh >= 0.08) & (carsh < 0.15)), ("pocket (< .08)", carsh < 0.08),
            ("team total < 20", imp < 20), ("team total 20-24", (imp >= 20) & (imp < 24)), ("team total >= 24", imp >= 24),
            ("big favorite (spread <= -6.5)", spread <= -6.5), ("near pick-em", np.abs(spread) < 6.5), ("big underdog (spread >= 6.5)", spread >= 6.5),
            ("shadow >= 20", SH >= 20), ("shadow 16-20", (SH >= 16) & (SH < 20)), ("shadow 12-16", (SH >= 12) & (SH < 16)), ("shadow < 12", SH < 12),
            ("ADP 1-60", adp <= 60), ("ADP 61-150", adp > 60), ("games 0", g == 0), ("games 1-3", (g >= 1) & (g <= 3)), ("games 4+", g >= 4),
            ("changed team", tchg == 1), ("rookie / yr 1-2", exp_ <= 1), ("Questionable", repq == 1)]
    P(f"  total MAE gap shadow - ESPN: {tot/max(1, QE.sum()):+.3f}/row over {int(QE.sum())} rows")
    P(f"  {'segment':32s}   n13-25 act/shadow 13-18 | 19-25 |  nE  shadow MAE  ESPN MAE  gap/row  share | act/ESPN")
    for lab, cm in segs:
        m1 = Q & cm & (year <= 2018); m2 = Q & cm & (year >= 2019); me = QE & cm
        if me.sum() < 30: continue
        gp = float(np.sum(np.abs(SH[me] - act[me]) - np.abs(esp[me] - act[me])))
        P(f"  {lab:32s} {int((Q & cm).sum()):6d}   {act[m1].sum()/max(1e-9, SH[m1].sum()):.3f}   | {act[m2].sum()/max(1e-9, SH[m2].sum()):.3f} | {int(me.sum()):4d}  {mae(SH, me):6.2f}    {mae(esp, me):6.2f}   {gp/me.sum():+.2f}  {100*gp/tot:+5.0f}% | {act[me].sum()/esp[me].sum():.3f}")

    P("\n--- 3  candidate QB fixes (QB rows only; LOYO = k picked on the other seasons by MAE; forward = k from earlier seasons only) ---")
    KG = np.round(np.arange(0, 1.0001, 0.1), 2)
    def evaluate(lab, mk, years, ref_mask, fwd_from):
        m = ref_mask
        out, fw = [], []
        for y in years:
            tr = m & (year != y); te = m & (year == y)
            kb = KG[int(np.argmin([mae(mk(k), tr) for k in KG]))]
            out.append((y, kb, mae(mk(kb), te), mae(SH, te), rho(mk(kb), te), rho(SH, te)))
            if y >= fwd_from:
                trf = m & (year < y); kf = KG[int(np.argmin([mae(mk(k), trf) for k in KG]))]
                fw.append((y, kf, mae(mk(kf), te), mae(SH, te), rho(mk(kf), te), rho(SH, te)))
        P(f"  {lab}")
        P("    LOYO   " + " ".join(f"{y}:k{k:.1f} {100*(a/b-1):+.1f}%/{(r1-r0):+.3f}" for y, k, a, b, r1, r0 in out))
        w = sum(1 for o in out if o[2] < o[3]); wr = sum(1 for o in out if o[4] > o[5])
        pool = np.sum([o[2] * (m & (year == o[0])).sum() for o in out]) / np.sum([(m & (year == o[0])).sum() for o in out])
        pool0 = mae(SH, m & np.isin(year, years))
        P(f"    LOYO pooled MAE {pool:.3f} vs shadow {pool0:.3f} ({100*(pool/pool0-1):+.2f}%), MAE better {w}/{len(out)}, rank better {wr}/{len(out)}, mean drho {np.mean([o[4]-o[5] for o in out]):+.4f}")
        if fw:
            P("    FWD    " + " ".join(f"{y}:k{k:.1f} {100*(a/b-1):+.1f}%/{(r1-r0):+.3f}" for y, k, a, b, r1, r0 in fw)
              + f" | MAE better {sum(1 for o in fw if o[2] < o[3])}/{len(fw)}, rank better {sum(1 for o in fw if o[4] > o[5])}/{len(fw)}")
        P("    pooled k sweep MAE: " + " ".join(f"{k:.1f}:{mae(mk(k), m & np.isin(year, years)):.3f}" for k in KG))
    evaluate("H1 shadow -> ESPN blend, (1-k) shadow + k ESPN (2019-25)", lambda k: (1 - k) * SH + k * np.where(np.isnan(esp), SH, esp), EY, QE, 2021)
    evaluate("H2 shadow -> Vegas-only QB line, (1-k) shadow + k Vegas (2013-25)", lambda k: (1 - k) * SH + k * np.where(np.isnan(veg), SH, veg), GY, Q & ~np.isnan(veg), 2016)
    mu = np.full(n, np.nan)
    gr = defaultdict(list)
    for i in np.where(Q)[0]: gr[(int(year[i]), int(wk[i]))].append(i)
    for ix in gr.values(): ix = np.array(ix); mu[ix] = np.mean(SH[ix])
    evaluate("H3 two-sided shrink to the week's QB mean, mu + (1-k)(shadow - mu) (2013-25)", lambda k: np.where(np.isnan(mu), SH, mu + (1 - k) * (SH - mu)), GY, Q, 2016)
    P("\n  read: a fix ships only if LOYO MAE better in a clear majority of seasons, rank not worse, forward holds; ESPN in the public number is Jack's call.")
    log.close()


if __name__ == "__main__":
    main()
