import io, os
os.chdir(r"E:\MyFantasyFootball\sim_lab")
p = "backtest_evidence_clean.py"; s = io.open(p, encoding="utf-8").read()
old = "    best = min(RES[\"rows\"], key=lambda r_: r_[\"ALL weeks 2+ (no final)\"][\"d\"])"; assert s.count(old) == 1 and "LIVE Clay blend" not in s
new = '''    P("=== Same fix on the LIVE Clay blend (Clay per-game prior, P = 5, points evidence): error vs today's Clay blend ===")
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8")); clay = A["clay"]
    gm = np.array([(ch[str(y)].get(nm_) or {}).get("gm") or 0 for y, nm_ in zip(year, name)], dtype=float)
    Wk = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * Wk / np.maximum(gm, 1), clay); CUR = NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers
    RES["live"] = []
    for nm in ("A Vegas-only k=1", "A Vegas-only k=1.5"):
        pv = NW.blend(clay_gm, g, V[nm]["pts"], NW.PRIOR_P) * layers; cells = []
        for lab, m in cuts:
            m = m & top150; d = (wm(pv, m) / wm(CUR, m) - 1) * 100; wins = sum(1 for y in YEARS if wm(pv, m & (year == y)) < wm(CUR, m & (year == y)) - 1e-12); dr = rho(pv, m) - rho(CUR, m)
            RES["live"].append({"variant": nm, "cut": lab, "d": round(d, 2), "wins": wins, "drho": round(dr, 4)}); cells.append(f"{lab}: {d:+.2f}% ({wins}/7) rho {dr:+.4f}")
        P(f"  {nm:24s} " + " | ".join(cells))
'''
s = s.replace(old, new + old); io.open(p, "w", encoding="utf-8", newline="\n").write(s); print("ok")
