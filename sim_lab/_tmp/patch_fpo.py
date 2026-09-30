import io
p = "backtest_fantasy_playoffs.py"; s = io.open(p, encoding="utf-8").read()
old = "    s = {r_[\"stage\"]: r_ for r_ in RES[\"stage\"]}"; assert s.count(old) == 1
new = '''    P("=== 4. ASYMMETRIC recency: only a COLD last 4 moves the evidence (hot streaks untouched). Found in the playoff cut, so weeks 5-9 and 10-to-playoffs are the out-of-cut check ===")
    RES["asym"] = []; cold = np.where((g >= 6) & ~np.isnan(l4), np.minimum(0.0, l4 - ppg), 0.0); hotv = np.where((g >= 6) & ~np.isnan(l4), np.maximum(0.0, l4 - ppg), 0.0)
    V4 = {}
    for a_ in (0.25, 0.5, 0.75): V4[f"cold only, weight {a_}"] = shadow(ppg + a_ * cold)
    for thr in (2.0, 3.0): V4[f"cold only beyond -{thr:.0f}, weight 0.5"] = shadow(ppg + 0.5 * np.minimum(0.0, cold + thr))
    V4["cold 0.5 AND hot 0.5 (symmetric, for contrast)"] = shadow(ppg + 0.5 * cold + 0.5 * hotv)
    V4["hot only, weight 0.5 (contrast)"] = shadow(ppg + 0.5 * hotv)
    for nm, p in V4.items():
        row = {"variant": nm}; cells = []
        for lab, sm in (("weeks 5-9", (wk >= 5) & (wk <= 9)), ("10 to playoffs", (wk >= 10) & ~po & ~final), ("playoffs", po), ("all non-final", ~final)):
            m = sm & top150; d = (wm(p, m) / wm(SH, m) - 1) * 100; wins = sum(1 for y in YEARS if wm(p, m & (year == y)) < wm(SH, m & (year == y)) - 1e-12); rr = rho(p, m) - rho(SH, m)
            row[lab] = {"d": round(d, 2), "wins": wins, "drho": round(rr, 4)}; cells.append(f"{lab}: {d:+.2f}% ({wins}/7) rho {rr:+.4f}")
        mE = po & top150 & ok; row["poVsEspn"] = round((e(p, mE) / e(esp, mE) - 1) * 100, 2)
        RES["asym"].append(row); P(f"  {nm:48s} " + " | ".join(cells) + f" | playoffs vs ESPN {row['poVsEspn']:+.2f}%")
    P("  cold players by position (playoffs + weeks 10+, top 150, last 4 at least 3 below season): actual vs shadow")
    for ps in POS4:
        m = (pos == ps) & top150 & (wk >= 10) & ~final & (hot <= -3); P(f"    {ps}: n={m.sum():4d} actual {act[m].mean():5.2f} | shadow {SH[m].mean():5.2f} | season PPG {ppg[m].mean():5.2f} | last 4 {l4[m].mean():5.2f} | snap share last game vs season {np.nanmean(colv('snap_l1')[m]):.3f} / {np.nanmean(colv('snap_std')[m]):.3f}")
'''
s = s.replace(old, new + old); io.open(p, "w", encoding="utf-8", newline="\n").write(s); print("ok")
