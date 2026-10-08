"""Add rank-objective lines (rank_grade.py) to the two shadow harnesses so their shipped layers get a rank reading (2026-10-08). Line-based, newline-agnostic."""
import os, re
HERE = os.path.dirname(os.path.abspath(__file__))


def patch(fname, fixed_indent, mask, T, logname):
    p = os.path.join(HERE, fname); raw = open(p, encoding="utf-8", newline="").read()
    if "rank_grade" in raw: print("already patched", fname); return
    nl = "\r\n" if "\r\n" in raw else "\n"; lines = raw.split(nl)
    out = []; done_imp = done_fix = 0
    for ln in lines:
        out.append(ln)
        if not done_imp and ln.startswith("import numpy as np"):
            out.append("import rank_grade as RG"); done_imp = 1
        if ln.strip() == 'P(f"    fixed: {fixed}")':
            ind = ln[:len(ln) - len(ln.lstrip())]
            out.append(ind + 'P("    " + RG.rank_line(preds, ' + mask + ', ' + T + ', year, wk, pos) + " | seasons rank better: " + " ".join(f"{kk} {RG.rank_seasons(preds[kk], preds[\'off\'], ' + mask + ', ' + T + ', year, wk, pos, YEARS)}/7" for kk in names[1:]))')
            done_fix += 1
    assert done_imp == 1 and done_fix == 1, (fname, done_imp, done_fix)
    s = nl.join(out).replace('"' + logname + '.log"', '"' + logname + '_rank.log"')
    assert logname + "_rank.log" in s
    open(p, "w", encoding="utf-8", newline="").write(s); print("patched", fname)


patch("backtest_shadow_healthy_prior.py", None, "ok", "T", "shadow_healthy_prior")
patch("backtest_shadow_ports.py", None, "okN", "act", "shadow_ports")
