#!/usr/bin/env python3
"""
HARNESS REPLAY of the scratch-model legs (Jack 2026-10-27, via scripts/scratch_model_report.md proposals 1 and 3):

  QB leg   teamAttempts(as-of pace, spread, total) x shrunk YPA (k~330 att) x opp pass-yard rate^.76
           + 4 x teamExpTD(implied) x attempt share + rush (EWMA carries x shrunk YPC) - INT
  TE leg   target share x teamAttempts x (0.5 catch rate + 0.1 yards/target x opp rate) + 6 x TD share (end-zone targets) x team pass TDs

each blended w x leg + (1 - w) x shadow (the engine-parity next-game number, backtest_shadow_next.shadow), w = .25 / .5 / .75,
in two forms: EV = the opportunity formula alone (rows with 1+ games), FULL = the scratch model's calibrated number (ADP prior
blended in by effective games). Team-volume OLS and league rates are refit on the training seasons of every fold; the shrink
constants (k_ypa 328, k_int 249, k_ypc 22, k_ypt 33, e_def .76) are the 2017-25 fit and are stated as such.

Grading = the house rules copied from backtest_shadow_next.test(): LEAVE-ONE-SEASON-OUT pick + FORWARD pick (earlier seasons
only), error on the rows the leg touches, whole-board top-150 importance-weighted guard, weekly within-position rank rho,
final week out. Ship bar: LOSO better in 5+ of 7 seasons (ext: n-2) AND forward better in 3+ of 4, touched-row error -0.3%+,
whole-board guard <= +0.02%. Plus the per-season table Jack asked for (MAE, Spearman, pair accuracy, wins).

  python backtest_scratch_legs.py            # default harness 2019-25 (setup ~90 s)
  SIM_BT_YEARS=2012-2025 python backtest_scratch_legs.py   # extended 2013-25 from _bt_ext/X_cache_ext2012_2025_tf.pkl
Log: scratch_model/out/harness_legs<TAG>.log
"""
import os, sys, json, pickle
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata, spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "scratch_model"))
import bt_ext as BX
import backtest_shadow_next as SN
from model import struct_predict, apply_cal, team_volume_model, fit_league, POS4
SM = os.path.join(HERE, "scratch_model"); OUT = os.path.join(SM, "out")
YEARS = list(BX.YEARS); FWD = list(BX.FWD)
P_ = json.load(open(os.path.join(OUT, "params.json")))
curve = {k: tuple(v) for k, v in P_["curve"].items()}; cal = {k: tuple(v) for k, v in P_["cal"].items()}; PRM = P_["prm"]
LOG = open(os.path.join(OUT, f"harness_legs{BX.TAG}{'_fpaopp' if os.environ.get('SCRATCH_QB_OPP') == 'fpa' else ''}.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + "\n"); LOG.flush()


def load_X():
    if BX.EXT:
        p = BX.ext_path("X_cache.pkl")
        if os.path.exists(p):
            return pickle.load(open(p, "rb"))
    return SN.setup()


def main():
    X = load_X(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["team"]
    pid = X["A"]["pid"]
    SH = SN.shadow(X)
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; top100 = adp <= 100
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2; wt3 = np.maximum(0.05, lv) ** 3
    base = top150 & ~final; allr = ~final & (SH >= 3)
    yrs = sorted(set(int(y) for y in year))
    # ---- scratch as-of rows for the harness seasons
    A = pd.concat([pd.read_parquet(os.path.join(SM, "cache", f"asof_{y}.parquet")) for y in yrs if os.path.exists(os.path.join(SM, "cache", f"asof_{y}.parquet"))], ignore_index=True)
    key = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(A.season, A.pid, A.week))}
    idx = np.array([key.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    P(f"=== scratch legs on the engine-parity harness  {BX.describe()}  rows {n:,}  joined to as-of rows {int(has.sum()):,} ===")
    P(f"baseline = shadow (next game); rank rho top-150 {rho(SH, base, year, wk, pos, act):.4f}; QB top-150 rows {int((base & (pos == 'QB')).sum()):,}, TE {int((base & (pos == 'TE')).sum()):,}")
    wm = lambda q, mm: float(np.average((q[mm] - act[mm]) ** 2, weights=wt[mm])) if mm.any() else np.nan
    wm3 = lambda q, mm: float(np.average((q[mm] - act[mm]) ** 2, weights=wt3[mm])) if mm.any() else np.nan
    ms = lambda q, mm: float(np.mean((q[mm] - act[mm]) ** 2)) if mm.any() else np.nan

    def legs_for(ps):
        """EV and FULL leg per harness row for position ps, with the team-volume OLS / league rates refit per LOYO fold
        (fold = the held-out season); returns {fold_year: (ev, full)} plus the all-seasons fit under key 0."""
        sub = A[A.pos == ps].reset_index(drop=True)
        if ps == "QB" and os.environ.get("SCRATCH_QB_OPP") == "fpa":   # engine-available substitute: FPA points allowed to QBs (relative), not the pbp yards/attempt rate
            sub["z_qb_ypa"] = sub.def_qb_rel.values
        rows = np.where((pos == ps) & has)[0]
        aidx = idx[rows]
        # map harness row -> position in sub
        pos_in_sub = {int(i): j for j, i in enumerate(sub.index)}
        a_all = A.index.values
        sub_key = {(int(a), b, int(c)): j for j, (a, b, c) in enumerate(zip(sub.season, sub.pid, sub.week))}
        j_of = np.array([sub_key.get((int(year[i]), pid[i], int(wk[i])), -1) for i in rows])
        out = {}
        for fold in [0] + yrs:
            tr = A[(A.season != fold) & (A.season <= 2025)] if fold else A[A.season <= 2025]
            tcoef = team_volume_model(tr); L = fit_league(tr)
            raw, parts = struct_predict(sub, PRM, curve, tcoef, L)
            full = apply_cal(sub, raw, cal); ev = parts["ev"]
            ev_h = np.full(n, np.nan); full_h = np.full(n, np.nan)
            ok = j_of >= 0
            ev_h[rows[ok]] = ev[j_of[ok]]; full_h[rows[ok]] = full[j_of[ok]]
            gq = sub.g.values
            ev_h[rows[ok]] = np.where(gq[j_of[ok]] >= 1, ev_h[rows[ok]], np.nan)   # the formula needs a game of evidence
            out[fold] = (ev_h, full_h)
        return out

    def test(title, ps, legs, form, ws=(0.25, 0.5, 0.75)):
        """family = baseline + blends; LOYO / forward picks with the leg built from the fold's own training seasons"""
        def fam_for(fold):
            ev, full = legs[fold]; leg = ev if form == "EV" else full
            m = ~np.isnan(leg) & (pos == ps)
            fam = {"shadow": SH}
            for w in ws:
                fam[f"w{w:.2f}"] = np.where(m, w * leg + (1 - w) * SH, SH)
            fam["leg alone"] = np.where(m, leg, SH)
            return fam
        fam0 = fam_for(0); names = list(fam0); b = SH
        touched = np.zeros(n, bool)
        for k in names[1:]: touched |= np.abs(fam0[k] - b) > 1e-9
        tm = touched & allr
        def pick(trs):
            fam = fam_for(0)   # settings are compared on training seasons with the all-season leg (constants barely move); fold leg used for the held-out year
            return min(names[:-1], key=lambda k: ms(fam[k], tm & np.isin(year, trs)))
        def run(folds):
            wins = ny = 0; picks = []; pred = b.copy()
            for trs, te in folds:
                k = pick(trs); picks.append(k); m = year == te; fam = fam_for(te); pred[m] = fam[k][m]
                if (tm & m).sum() >= 8:
                    ny += 1; wins += ms(pred, tm & m) < ms(b, tm & m) - 1e-12
            tem = np.isin(year, [te for _, te in folds])
            return pred, 100 * (wm(pred, base & tem) / wm(b, base & tem) - 1), 100 * (ms(pred, tm & tem) / ms(b, tm & tem) - 1), wins, picks, ny, 100 * (wm3(pred, top100 & ~final & tem) / wm3(b, top100 & ~final & tem) - 1)
        lo = run([([y for y in yrs if y != t], t) for t in yrs]); fw = run([([y for y in yrs if y < t], t) for t in FWD])
        best = pick(yrs)
        need = max(5, lo[5] - 2)
        ok = best != names[0] and lo[2] < -0.3 and lo[3] >= need and fw[2] < 0 and fw[3] >= 3 and lo[1] <= 0.02
        P(); P(f"--- {title} ---   rows touched {int(tm.sum()):,} ({int((tm & top150).sum()):,} top-150); actual / shadow on them {act[tm].sum() / max(1e-9, b[tm].sum()):.3f}")
        P("    pooled touched rows (all-season leg): " + "  ".join(f"{k}: {100 * (ms(fam0[k], tm) / ms(b, tm) - 1):+.2f}%" for k in names[1:]))
        P(f"    LEAVE-ONE-SEASON-OUT  touched {lo[2]:+.2f}%  seasons better {lo[3]}/{lo[5]}  | whole board top-150 wtd {lo[1]:+.2f}%  top-100 cubed {lo[6]:+.2f}%  rank rho {rho(lo[0], base, year, wk, pos, act) - rho(b, base, year, wk, pos, act):+.4f} (pos only {rho(lo[0], base & (pos == ps), year, wk, pos, act) - rho(b, base & (pos == ps), year, wk, pos, act):+.4f})  | picks {lo[4]}")
        P(f"    FORWARD {FWD[0]}-{FWD[-1]}       touched {fw[2]:+.2f}%  seasons better {fw[3]}/{fw[5]}  | whole board top-150 wtd {fw[1]:+.2f}%  top-100 cubed {fw[6]:+.2f}%  | picks {fw[4]}")
        P(f"    -> {'PASS: ' + best if ok else 'FAIL'}  (bar: LOSO {need}+/{lo[5]} and forward 3+/{fw[5]}, touched -0.3%+, guard <= +0.02%)")
        # per-season table for every fixed setting (leg from that season's fold)
        P(f"\n    per season, {ps} top-150 rows, final week out: wtd MAE / Spearman (within {ps}-week) / pair acc   [wins vs shadow: MAE, rho, pair]")
        hdr = "    | season | n | shadow | " + " | ".join(names[1:]) + " |"; P(hdr); P("    |" + "---|" * (len(names) + 2))
        wins = {k: [0, 0, 0] for k in names[1:]}; nyrs = 0
        for y in yrs:
            m = base & (pos == ps) & (year == y)
            if m.sum() < 30: continue
            nyrs += 1
            fam = fam_for(y)
            cells = []; rb = metrics(b, m, wt, year, wk, pos, act)
            cells.append(f"{rb[0]:.3f} / {rb[1]:.3f} / {rb[2]:.3f}")
            for k in names[1:]:
                r = metrics(fam[k], m, wt, year, wk, pos, act)
                wins[k][0] += r[0] < rb[0] - 1e-9; wins[k][1] += r[1] > rb[1] + 1e-9; wins[k][2] += r[2] > rb[2] + 1e-9
                cells.append(f"{r[0]:.3f} / {r[1]:.3f} / {r[2]:.3f}")
            P(f"    | {y} | {int(m.sum())} | " + " | ".join(cells) + " |")
        P("    | wins | | | " + " | ".join(f"{wins[k][0]}/{wins[k][1]}/{wins[k][2]} of {nyrs}" for k in names[1:]) + " |")
        mall = base & (pos == ps)
        rb = metrics(b, mall, wt, year, wk, pos, act)
        P("    | ALL | " + str(int(mall.sum())) + f" | {rb[0]:.3f} / {rb[1]:.3f} / {rb[2]:.3f} | " + " | ".join("%.3f / %.3f / %.3f" % metrics(lo_pred_setting(k, legs, ps, form, yrs, SH, pos), mall, wt, year, wk, pos, act) for k in names[1:]) + " |")
        return ok, best, lo, fw

    res = {}
    for ps, title in (("QB", "QB leg"), ("TE", "TE leg")):
        if ps == "TE" and os.environ.get("SCRATCH_SKIP_TE"): continue
        legs = legs_for(ps)
        for form in ("EV", "FULL"):
            res[(ps, form)] = test(f"{title}, {form} form ({'opportunity formula only, 1+ games' if form == 'EV' else 'scratch number with its ADP prior + calibration'})", ps, legs, form)
    P("\n=== SUMMARY ===")
    for (ps, form), (ok, best, lo, fw) in res.items():
        P(f"  {ps} {form}: {'PASS ' + best if ok else 'FAIL'} | LOSO touched {lo[2]:+.2f}% {lo[3]}/{lo[5]} | fwd {fw[2]:+.2f}% {fw[3]}/{fw[5]} | guard {lo[1]:+.2f}% | top-100^3 {lo[6]:+.2f}%")
    P(f"log: {LOG.name}")


def lo_pred_setting(k, legs, ps, form, yrs, SH, pos):
    """the fixed setting k applied with each season's own fold leg (for the ALL row of the per-season table)"""
    out = SH.copy()
    for y in yrs:
        ev, full = legs[y]; leg = ev if form == "EV" else full
        m = ~np.isnan(leg) & (pos == ps) & (Y_ARR == y)
        if k == "leg alone":
            out[m] = leg[m]
        else:
            w = float(k[1:]); out[m] = w * leg[m] + (1 - w) * SH[m]
    return out


def rho(p, m, year, wk, pos, act):
    groups = defaultdict(list)
    for i in np.where(m)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
    rh = [np.corrcoef(rankdata(act[ix]), rankdata(p[ix]))[0, 1] for ix in (np.array(x) for x in groups.values()) if len(ix) >= 8]
    return float(np.mean(rh)) if rh else np.nan


def metrics(p, m, wt, year, wk, pos, act):
    """weighted MAE, mean within-week Spearman, pairwise order accuracy (top half by projection, gap >= 1)"""
    mae = float(np.average(np.abs(p[m] - act[m]), weights=wt[m]))
    groups = defaultdict(list)
    for i in np.where(m)[0]: groups[(int(year[i]), int(wk[i]))].append(i)
    rh = []; ok = tot = 0
    for ix in groups.values():
        ix = np.array(ix)
        if len(ix) < 8: continue
        a = act[ix]; q = p[ix]
        r = spearmanr(a, q).correlation
        if not np.isnan(r): rh.append(r)
        order = np.argsort(-q)[: max(2, len(ix) // 2)]
        for s in range(len(order)):
            for t in range(s + 1, len(order)):
                x, y_ = order[s], order[t]
                if abs(q[x] - q[y_]) < 1.0 or a[x] == a[y_]: continue
                tot += 1; ok += (q[x] > q[y_]) == (a[x] > a[y_])
    return mae, float(np.mean(rh)) if rh else np.nan, ok / tot if tot else np.nan


if __name__ == "__main__":
    _X = load_X(); Y_ARR = _X["year"]
    SN.setup = lambda: _X   # reuse the one build
    main()
