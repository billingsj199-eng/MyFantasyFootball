#!/usr/bin/env python3
"""
DO WE NEED A 3-YEAR HISTORY? history-window test for the shadow's raw history input (2026-09-17).

Jack: "do we really need a 3 year history maybe we do a game history or is 3 years the most accurate". Prompted by
Justin Jefferson W2: half of his prior is his last 8 games of 2025 (9.0 a game in the Minnesota QB collapse).
Today the raw history = 0.5 x (3-season weighted PPG, .5 / .3 / .2) + 0.5 x (last 8 played games). Candidates, all built
ONLY from games before the season being predicted (2019-25 Clay pool, veterans with 8+ prior games):
  seasons   last season only | 2 seasons (.65 / .35) | 3 seasons (.5 / .3 / .2) | 3 seasons equal
  games     last 4 / 8 / 12 / 16 / 24 / 32 played games (flat)
  decayed   exponentially weighted games, half-life 6 / 10 / 16 / 24 games
  blends    0.5 x 3-season + 0.5 x last-8 (current) | 0.5 x 3-season + 0.5 x last-16 | best season + best game window
  robust    last 16 with the single worst 25% of games trimmed is NOT tested (no principled basis)
Each is graded as a predictor of the player's actual full-season PPG (4+ games): correlation, and games-weighted MSE
after a leave-one-season-out linear calibration per position (so a window is not punished for its level), over all
veterans, the top 150 by ADP importance-weighted (Jack's rule), and by ADP band. Then the top candidates replace the raw
history inside the WEEKLY shadow's hand prior for the first read of how much it matters in-season.
Log history_window.log; results -> data/history_window.js (SIM_HISTWIN_BT).
"""
import json, os, sys, time, warnings
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import backtest_season_long as SL
import backtest_top150_weighted as TW
cal = NW.cal
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "history_window.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
YEARS, POS4 = NW.YEARS, NW.POS4
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "rows": [], "bands": []}


def windows(wrec, Y):
    """every candidate from games strictly before season Y (played games, chronological)."""
    games = []
    for yy in range(Y - 4, Y):
        for w in wrec.get("seasons", {}).get(str(yy), []):
            if cal.played(w) and isinstance(w.get("fpts"), (int, float)): games.append((yy, int(w["wk"]), float(w["fpts"])))
    games.sort(); pts = [g_[2] for g_ in games]
    if len(pts) < 8: return None
    out = {}
    seas = {yy: [g_[2] for g_ in games if g_[0] == yy] for yy in (Y - 1, Y - 2, Y - 3)}
    def wavg(ws):
        num = den = 0.0
        for yy, w_ in zip((Y - 1, Y - 2, Y - 3), ws):
            if len(seas[yy]) >= 4: num += w_ * np.mean(seas[yy]); den += w_
        return num / den if den > 0 else np.nan
    out["last season only"] = np.mean(seas[Y - 1]) if len(seas[Y - 1]) >= 4 else np.nan
    out["2 seasons (.65/.35)"] = wavg((0.65, 0.35, 0.0)); out["3 seasons (.5/.3/.2) = today's h3"] = wavg((0.5, 0.3, 0.2)); out["3 seasons equal"] = wavg((1 / 3, 1 / 3, 1 / 3))
    for N in (4, 8, 12, 16, 24, 32): out[f"last {N} games"] = float(np.mean(pts[-N:])) if len(pts) >= min(N, 8) else np.nan
    for hl in (6, 10, 16, 24):
        k = np.arange(len(pts))[::-1]; w_ = 0.5 ** (k / hl); out[f"decayed games, half-life {hl}"] = float(np.sum(w_ * np.array(pts)) / np.sum(w_))
    out["CURRENT: .5 x 3 seasons + .5 x last 8"] = 0.5 * out["3 seasons (.5/.3/.2) = today's h3"] + 0.5 * out["last 8 games"]
    out[".5 x 3 seasons + .5 x last 16"] = 0.5 * out["3 seasons (.5/.3/.2) = today's h3"] + 0.5 * out["last 16 games"]
    out[".5 x 3 seasons + .5 x decayed hl 16"] = 0.5 * out["3 seasons (.5/.3/.2) = today's h3"] + 0.5 * out["decayed games, half-life 16"]
    out["n_games"] = len(pts)
    return out


def main():
    t0 = time.time()
    P("=== Do we need a 3-year history? history windows as predictors of the coming season's PPG (veterans) ===")
    T = SL.build_table()
    rows = []
    for r in T.itertuples(index=False):
        wrec = cal.weekly_rec(r.name, r.pos)
        if wrec is None: rows.append(None); continue
        rows.append(windows(wrec, int(r.year)))
    ok = np.array([x is not None for x in rows]); names = [k for k in rows[int(np.where(ok)[0][0])].keys() if k != "n_games"]
    X = {k: np.array([x[k] if x is not None else np.nan for x in rows], dtype=float) for k in names}
    act, g, yr, pos, adp = T.ppg.values, T.games.values.astype(float), T.year.values, T.pos.values, T.adp.values
    vet = ok & (T.rookie.values == 0)
    lv = TW.level_of(T); top150 = adp <= 150; rel = lv.copy()
    for ps in POS4:
        m = pos == ps; rel[m] = lv[m] / np.average(lv[m & top150], weights=g[m & top150])
    wimp = g * rel ** 2
    P(f"  veteran player-seasons with 8+ prior games: {int(vet.sum())} of {len(T)} (top 150: {int((vet & top150).sum())})")
    def calib(x, mask):
        """leave-one-season-out linear calibration per position; returns calibrated predictions (nan where x is nan)."""
        out = np.full(len(x), np.nan)
        for ps in POS4:
            for y in YEARS:
                tr = mask & (pos == ps) & (yr != y) & ~np.isnan(x); te = mask & (pos == ps) & (yr == y) & ~np.isnan(x)
                if tr.sum() < 25 or not te.any(): continue
                b = np.polyfit(x[tr], act[tr], 1, w=np.sqrt(g[tr])); out[te] = b[1] + b[0] * x[te]
        return out
    base_name = "CURRENT: .5 x 3 seasons + .5 x last 8"; common = vet.copy()
    for k in names: common &= ~np.isnan(X[k])
    P(f"  graded on the {int(common.sum())} veteran seasons where EVERY window is defined (same rows for all)")
    CAL = {k: calib(X[k], common) for k in names}; cb = CAL[base_name]
    def score(k, m, w):
        p = CAL[k]; mm = m & common & ~np.isnan(p) & ~np.isnan(cb)
        e, eb = SL.wmse(p[mm], act[mm], w[mm]), SL.wmse(cb[mm], act[mm], w[mm]); ys = [y for y in YEARS if (mm & (yr == y)).sum() >= 10]
        wins = sum(1 for y in ys if SL.wmse(p[mm & (yr == y)], act[mm & (yr == y)], w[mm & (yr == y)]) < SL.wmse(cb[mm & (yr == y)], act[mm & (yr == y)], w[mm & (yr == y)]) - 1e-12)
        return e, (e / eb - 1) * 100, wins, len(ys), float(np.corrcoef(X[k][mm], act[mm])[0, 1])
    P("\n=== All veterans (games-weighted) | TOP 150 importance-weighted: MSE vs the CURRENT blend (seasons better), raw correlation with the season ===")
    P(f"  {'window':42s} {'all vets':>22s} {'corr':>6s} | {'top 150 weighted':>22s} {'corr':>6s}")
    for k in names:
        e, d, w_, ny, c = score(k, np.ones(len(T), bool), g); e2, d2, w2, ny2, c2 = score(k, top150, wimp)
        RES["rows"].append({"window": k, "all": round(d, 2), "allWins": w_, "allCorr": round(c, 3), "top": round(d2, 2), "topWins": w2, "topCorr": round(c2, 3), "years": ny})
        P(f"  {k:42s} {d:+8.2f}% ({w_}/{ny}) mse {e:5.2f} {c:6.3f} | {d2:+8.2f}% ({w2}/{ny2}) mse {e2:5.2f} {c2:6.3f}")
    P("\n=== By ADP band (games-weighted MSE vs the CURRENT blend) ===")
    for lab, bm in (("ADP 1-30", adp <= 30), ("ADP 31-60", (adp > 30) & (adp <= 60)), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150", (adp > 100) & (adp <= 150))):
        cells = []
        for k in ("last season only", "3 seasons (.5/.3/.2) = today's h3", "last 8 games", "last 16 games", "last 24 games", "decayed games, half-life 16", ".5 x 3 seasons + .5 x last 16"):
            e, d, w_, ny, c = score(k, bm, g); cells.append(f"{k.split(' =')[0][:24]} {d:+.1f}% ({w_}/{ny})"); RES["bands"].append({"band": lab, "window": k, "d": round(d, 2), "wins": w_})
        P(f"  {lab:12s} " + " | ".join(cells))
    P("\n=== By position, top 150 importance-weighted: best window vs CURRENT ===")
    for ps in POS4:
        res = sorted(((score(k, top150 & (pos == ps), wimp)[1], k) for k in names)); P(f"  {ps}: best {res[0][1]} {res[0][0]:+.2f}% | 2nd {res[1][1]} {res[1][0]:+.2f}% | 3 seasons alone {score(names[2], top150 & (pos == ps), wimp)[1]:+.2f}% | last 8 alone {score('last 8 games', top150 & (pos == ps), wimp)[1]:+.2f}% | last season alone {score('last season only', top150 & (pos == ps), wimp)[1]:+.2f}%")
    # the Jefferson case: players whose last 8 games sat far below their 3-season level - who was right?
    h3 = X["3 seasons (.5/.3/.2) = today's h3"]; l8 = X["last 8 games"]; gap = l8 - h3
    P("\n=== When the last 8 games disagree with the 3-season level (top 150 veterans): which one did the next season follow? ===")
    for lab, m in (("last 8 FAR BELOW 3-season (gap <= -3)", gap <= -3), ("last 8 below (-3 to -1)", (gap > -3) & (gap <= -1)), ("about equal", np.abs(gap) < 1), ("last 8 above (+1 to +3)", (gap >= 1) & (gap < 3)), ("last 8 FAR ABOVE (gap >= +3)", gap >= 3)):
        mm = m & common & top150
        if mm.sum() < 15: continue
        P(f"  {lab:40s} n={mm.sum():3d} | 3-season {np.average(h3[mm], weights=g[mm]):5.2f} | last 8 {np.average(l8[mm], weights=g[mm]):5.2f} | NEXT SEASON actual {np.average(act[mm], weights=g[mm]):5.2f} | weight on last 8 that fits best {np.clip(np.sum(g[mm]*(act[mm]-h3[mm])*(l8[mm]-h3[mm]))/max(1e-9, np.sum(g[mm]*(l8[mm]-h3[mm])**2)), -1, 2):.2f}")
    best = min(RES["rows"], key=lambda r: r["top"])
    RES["summary"] = (f"Top 150 weighted, vs the current blend (.5 x 3 seasons + .5 x last 8): best window = {best['window']} {best['top']:+.2f}% ({best['topWins']}/{best['years']}). "
                      + "; ".join(f"{r['window'].split(' =')[0]} {r['top']:+.1f}%" for r in RES["rows"] if r["window"] in ("last season only", "3 seasons (.5/.3/.2) = today's h3", "last 8 games", "last 16 games", "last 32 games")) + ".")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "history_window.js"), "w", encoding="utf-8") as fh:
        fh.write("window.SIM_HISTWIN_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/history_window.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
