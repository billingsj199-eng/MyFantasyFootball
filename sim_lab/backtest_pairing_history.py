#!/usr/bin/env python3
"""
PLAYER x DEFENSE PAIRING HISTORY backtest, 2019-2025 (Jack 2026-09-15: "can we
test ... to find specific players that do great or horrible against specific
defenses?").

For every player-week, the residual r = actual / shipped - 1 (shipped = P=5
blend x Vegas x in-season FPA). Predictors built ONLY from earlier games:
  pair_prev   mean residual of this player's previous meetings vs THIS defense
              (any earlier season or week; n >= 1, also n >= 2)
  pair_same   the residual from the FIRST meeting this season (divisional
              rematch: does game 1 predict game 2?)
  gen_prev    mean residual of the player's previous games vs OTHER defenses
              over the same window (control: is it the player, not the pairing?)
  pair_excess pair_prev - gen_prev (the pairing-specific part)
  home        home / away split (the harness has no home term; Vegas carries it)
Gates: corr(predictor, current residual); persistence of pairing residual
between consecutive meetings; then LOYO multipliers shipped x (1 + k x
shrunk pairing excess). Log: pairing_history_backtest.log
"""
import numpy as np
from collections import defaultdict
from bt_common import iter_samples, to_arrays, loyo, mse, bucket_table, POS4

def main():
    S = iter_samples(POS4)
    S.sort(key=lambda s: (s["year"], s["wk"]))
    A = to_arrays(S)
    years = sorted(set(A["year"]))
    n = len(S)
    resid = A["act"] / A["shipped"] - 1.0
    resid = np.clip(resid, -1.0, 3.0)
    # walk forward: per player, history of (year, wk, opp, resid)
    hist = defaultdict(list)
    pair_prev = np.full(n, np.nan); pair_n = np.zeros(n); pair_same = np.full(n, np.nan)
    gen_prev = np.full(n, np.nan); gen_n = np.zeros(n)
    for i, s in enumerate(S):
        key = (s["name"], s["pos"]); h = hist[key]
        same = [r for (y, w, o, r) in h if o == s["opp"]]
        other = [r for (y, w, o, r) in h if o != s["opp"]]
        if same: pair_prev[i] = np.mean(same); pair_n[i] = len(same)
        if other: gen_prev[i] = np.mean(other[-16:]); gen_n[i] = len(other[-16:])   # recent-ish general form
        ss = [r for (y, w, o, r) in h if o == s["opp"] and y == s["year"]]
        if ss: pair_same[i] = ss[-1]
        h.append((s["year"], s["wk"], s["opp"], resid[i]))
    ok = ~np.isnan(pair_prev); ok2 = ok & (pair_n >= 2); oks = ~np.isnan(pair_same)
    okg = ok & ~np.isnan(gen_prev)
    print(f"\n{n} player-weeks | with a prior meeting vs this defense: {ok.sum()} (>= 2 prior: {ok2.sum()}) | same-season rematch: {oks.sum()}")
    print("\n=== GATE. does the pairing history predict the current residual? (corr with actual/shipped - 1) ===")
    print(f"  prior meetings vs THIS defense (n>=1): r = {np.corrcoef(pair_prev[ok], resid[ok])[0,1]:+.3f}  (n={ok.sum()})")
    print(f"  prior meetings vs THIS defense (n>=2): r = {np.corrcoef(pair_prev[ok2], resid[ok2])[0,1]:+.3f}  (n={ok2.sum()})")
    print(f"  same-season rematch (game 1 -> game 2): r = {np.corrcoef(pair_same[oks], resid[oks])[0,1]:+.3f}  (n={oks.sum()})")
    print(f"  CONTROL general form vs OTHER defenses:  r = {np.corrcoef(gen_prev[okg], resid[okg])[0,1]:+.3f}  (n={okg.sum()})")
    exc = pair_prev - gen_prev
    print(f"  pairing EXCESS (pair - general):          r = {np.corrcoef(exc[okg], resid[okg])[0,1]:+.3f}")
    for p in POS4:
        m = okg & (A["pos"] == p)
        print(f"    {p}: pair r {np.corrcoef(pair_prev[m], resid[m])[0,1]:+.3f} | general r {np.corrcoef(gen_prev[m], resid[m])[0,1]:+.3f} | excess r {np.corrcoef(exc[m], resid[m])[0,1]:+.3f} (n={m.sum()})")
    print("\n=== 1. actual / shipped by prior-pairing residual tercile (players who crushed / flopped vs this D before) ===")
    q = np.quantile(pair_prev[ok], [1/3, 2/3])
    for lo, hi, lab in ((-np.inf, q[0], "flopped before"), (q[0], q[1], "middle"), (q[1], np.inf, "crushed before")):
        m = ok & (pair_prev >= lo) & (pair_prev < hi)
        print(f"  {lab:16s} prior resid {pair_prev[m].mean():+.2f} -> now {A['act'][m].mean()/A['shipped'][m].mean():.3f} (n={m.sum()})")
    q = np.quantile(pair_same[oks], [1/3, 2/3])
    for lo, hi, lab in ((-np.inf, q[0], "game-1 flop"), (q[0], q[1], "middle"), (q[1], np.inf, "game-1 crush")):
        m = oks & (pair_same >= lo) & (pair_same < hi)
        print(f"  rematch {lab:12s} game-1 resid {pair_same[m].mean():+.2f} -> game 2 {A['act'][m].mean()/A['shipped'][m].mean():.3f} (n={m.sum()})")
    bucket_table(A, [("home", A["home"]), ("away", ~A["home"])], "1b. home / away (harness has no home term; Vegas spread carries it)")

    print("\n=== 2. LOYO: shipped x (1 + k x shrunk predictor) (grid[0] = shipped) ===")
    def shrunk(x, cnt, k0):
        z = np.nan_to_num(x) * (cnt / (cnt + k0)); return z
    Sok = {"year": A["year"], "act": A["act"]}; sh = A["shipped"]
    grid = [0.0, 0.1, 0.2, 0.3, 0.5]
    loyo(Sok, years, grid, lambda k: sh * np.clip(1 + k * shrunk(pair_prev, pair_n, 2.0), 0.7, 1.4), "a) pairing residual (shrunk n/(n+2))")
    loyo(Sok, years, grid, lambda k: sh * np.clip(1 + k * shrunk(exc, pair_n, 2.0), 0.7, 1.4), "b) pairing EXCESS over general form")
    loyo(Sok, years, grid, lambda k: sh * np.clip(1 + k * np.nan_to_num(pair_same), 0.7, 1.4), "c) same-season rematch: game-1 residual")
    loyo(Sok, years, grid, lambda k: sh * np.clip(1 + k * shrunk(gen_prev, gen_n, 4.0), 0.7, 1.4), "d) CONTROL: general form vs other defenses (recent 16)")
    loyo(Sok, years, [1.0, 0.98, 0.96, 1.02, 1.04], lambda m: np.where(A["home"], sh * m, sh), "e) home multiplier")

if __name__ == "__main__":
    main()
