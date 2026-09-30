import io, os
os.chdir(r"E:\MyFantasyFootball\sim_lab")
p = "backtest_evidence_clean.py"; s = io.open(p, encoding="utf-8").read()
old = '"A k=0.5 + B drop 0.50", "A k=0.5 + B drop 0.50 + C w=0.5"): add(nm)'; assert s.count(old) == 1
s = s.replace(old, '"A k=0.5 + B drop 0.50", "A k=0.5 + B drop 0.50 + C w=0.5", "A Vegas-only k=1.5", "A Vegas-only k=2", "A Vegas-only k=3", "A Vegas-only k=1, 4+ games only"): add(nm)')
old = '        setv("B drop partial < 0.50", (~p50)'; assert s.count(old) == 1
s = s.replace(old, '        for k_ in (1.5, 2, 3): setv(f"A Vegas-only k={k_:g}", one, pts / vg_ ** k_)\n        if ng >= 4: setv("A Vegas-only k=1, 4+ games only", one, pts / vg_)\n' + old)
old = '    P("' + chr(92) + 'n=== On the rows each fix actually moves'; assert s.count(old) == 1
new = '''    P("=== Vegas-adjusted evidence by position (top 150 weighted, weeks 2+, final week dropped) ===")
    RES["pos"] = []
    for nm in ("A Vegas-only k=1", "A Vegas-only k=2"):
        cells = []
        for ps in POS4:
            m = live & top150 & (pos == ps); p = PRED[nm]; d = (wm(p, m) / wm(SH, m) - 1) * 100; wins = sum(1 for y in YEARS if wm(p, m & (year == y)) < wm(SH, m & (year == y)) - 1e-12); dr = rho(p, m) - rho(SH, m)
            RES["pos"].append({"variant": nm, "pos": ps, "d": round(d, 2), "wins": wins, "drho": round(dr, 4)}); cells.append(f"{ps} {d:+.2f}% ({wins}/7) rho {dr:+.4f}")
        P(f"  {nm:24s} " + " | ".join(cells))
'''
s = s.replace(old, new + old); io.open(p, "w", encoding="utf-8", newline="\n").write(s); print("ok")
