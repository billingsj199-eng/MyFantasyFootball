#!/usr/bin/env python3
"""
A19 test (2026-11-24, TEST ONLY - nothing shipped): the team-code mapping with the drafted-competition input left out of
the QB per-game fit, QBs left to the A11 / A13 job-security step.

Three states, all from reruns of games_model / pergame_model / qb_a11 / qb_a13 on otherwise identical code:
  A  current production                      (_gate_teamcodes/pre_*)
  B  full team-code mapping only             (_gate_teamcodes/post_*; the run that failed the A18 gate)
  C  B + drafted_comp zeroed for QB rows in pergame_model.add_context (_gate_teamcodes/C_run/*), i.e. the term is out of
     the QB volume ridges of the S7 lean per-game model, train and predict. RB / WR / TE keep it on the corrected
     mapping; team_r1qb (games model) and comp_hi (A11 / A13) stay on the corrected mapping.
  (B was also rerun through the same scratch runner as C - _gate_teamcodes/B_run - to prove the runner reproduces
   the stored B rows before C is trusted.)

Gate, same rule as A18 and fixed before C was looked at: a position FAILS if C is worse than A on per-game MAE with a
paired per-season t above +1.81 in the ADP top-150 pool or the all-veterans pool. "Better beyond noise" = t below -1.81.

  python a19_qbdrop_gate.py   -> a19_qbdrop_gate.log
"""
import os, sys, re, warnings
import numpy as np, pandas as pd
from scipy.stats import spearmanr
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); G = os.path.join(HERE, "_gate_teamcodes")
POS4 = ("QB", "RB", "WR", "TE"); YEARS = list(range(2015, 2026)); C_ = "S6 blend"
LOG = open(os.path.join(HERE, "a19_qbdrop_gate.log"), "w", encoding="utf-8")
def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n")
PATH = {"A": lambda n: os.path.join(G, f"pre_{n}"), "B": lambda n: os.path.join(G, f"post_{n}"),
        "C": lambda n: os.path.join(G, "C_run", "data" if n.endswith(".parquet") else "", n), "Bchk": lambda n: os.path.join(G, "B_run", "data" if n.endswith(".parquet") else "", n)}
def rows(st, n): return pd.read_parquet(PATH[st](n + ".parquet"))
def logtxt(st, n): return open(PATH[st](n + ".log"), encoding="utf-8").read()


def wmae(x, c=C_):
    m = (x.act_games >= 4) & x[c].notna()
    return float(np.sum(x.act_games[m] * np.abs(x[c] - x.act_ppg)[m]) / x.act_games[m].sum()) if m.sum() else np.nan


def rho(x, c=C_):
    m = (x.act_games >= 4) & x[c].notna()
    v = [spearmanr(g[c], g.act_ppg).correlation for _, g in x[m].groupby("season") if len(g) >= 8]
    return float(np.nanmean(v)) if v else np.nan


def paired(a, b):
    d = []
    for Y in YEARS:
        xa, xb = a[a.season == Y], b[b.season == Y]
        if ((xa.act_games >= 4) & xa[C_].notna()).sum() < 3: continue
        d.append(wmae(xb) - wmae(xa))
    d = np.array(d); t = d.mean() / (d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 and d.std(ddof=1) > 0 else 0.0
    return int((d < 0).sum()), len(d), float(d.mean()), float(t)


def main():
    PG = {s: rows(s, "pergame_rows") for s in ("A", "B", "C")}
    P("=== A19 TEST: mapping + drafted-competition input out of the QB per-game fit (A = production, B = mapping only, C = variant) ===")
    try:
        bc = rows("Bchk", "pergame_rows"); m = PG["B"][["season", "pid", C_]].merge(bc[["season", "pid", C_]], on=["season", "pid"], suffixes=("", "_chk"))
        gb = rows("B", "games_model_rows"); gc = rows("Bchk", "games_model_rows"); mg = gb[["season", "pid", "g_main"]].merge(gc[["season", "pid", "g_main"]], on=["season", "pid"], suffixes=("", "_chk"))
        qa = rows("B", "qb_a13_rows"); qc = rows("Bchk", "qb_a13_rows"); mq = qa[["season", "pid", "p_F3"]].merge(qc[["season", "pid", "p_F3"]], on=["season", "pid"], suffixes=("", "_chk"))
        P(f"  runner check (B rerun through the scratch runner vs the stored B rows): max |diff| per-game S6 {np.nanmax(np.abs(m[C_] - m[C_ + '_chk'])):.6f} on {len(m)} rows; "
          f"games g_main {np.nanmax(np.abs(mg.g_main - mg.g_main_chk)):.6f}; A13 p_F3 {np.nanmax(np.abs(mq.p_F3 - mq.p_F3_chk)):.6f}")
    except Exception as e:
        P(f"  runner check not available: {e}")
    for s in ("A", "B", "C"):
        x = PG[s]; v = (x.rookie == 0) & x.season.isin(YEARS)
        P(f"  state {s}: veterans flagged drafted_comp 2015-25 = {int(x[v].drafted_comp.sum())} (QB {int(x[v & (x.pos == 'QB')].drafted_comp.sum())}, RB {int(x[v & (x.pos == 'RB')].drafted_comp.sum())}, WR {int(x[v & (x.pos == 'WR')].drafted_comp.sum())}, TE {int(x[v & (x.pos == 'TE')].drafted_comp.sum())})")
    fails, wins = [], []
    for lab, f in (("ADP top 150 (as the per-game log grades)", lambda x: x[(x.adp <= 150)]), ("all veterans", lambda x: x[x.rookie == 0]), ("everyone with a projection", lambda x: x)):
        P(f"\n  per-game S6 blend, {lab}, 2015-25: MAE / rank corr; vs A = seasons better, mean per-season change, paired t")
        P("| pos | n (4+ g) | A production | B mapping only | B vs A | C variant | C vs A | C vs B |"); P("|---|---|---|---|---|---|---|---|")
        for ps in POS4 + ("ALL",):
            sel = lambda x: f(x[x.season.isin(YEARS) & ((x.pos == ps) if ps != "ALL" else True) & x[C_].notna()])
            a, b, c = sel(PG["A"]), sel(PG["B"]), sel(PG["C"])
            wb, nb, mb, tb = paired(a, b); wc, nc, mc, tc = paired(a, c); wx, nx, mx, tx = paired(b, c)
            P(f"| {ps} | {int((a.act_games >= 4).sum())} | {wmae(a):.3f} / {rho(a):.3f} | {wmae(b):.3f} / {rho(b):.3f} | {wb}/{nb}, {mb:+.4f}, t {tb:+.2f} | {wmae(c):.3f} / {rho(c):.3f} | {wc}/{nc}, {mc:+.4f}, t {tc:+.2f} | {wx}/{nx}, {mx:+.4f}, t {tx:+.2f} |")
            if ps != "ALL" and not lab.startswith("everyone"):
                if mc > 0 and tc > 1.81: fails.append((lab, ps, mc, tc))
                if mc < 0 and tc < -1.81: wins.append((lab, ps, mc, tc))
    P("\n  end-to-end season totals (tot_new = per-game x games model), ADP top 150: MAE / Spearman")
    P("| pos | n | A | B | C |"); P("|---|---|---|---|---|")
    for ps in POS4 + ("ALL",):
        o = []
        for s in ("A", "B", "C"):
            x = PG[s]; y = x[x.season.isin(YEARS) & ((x.pos == ps) if ps != "ALL" else True) & (x.adp <= 150) & x.tot_new.notna()]
            o.append(f"{np.mean(np.abs(y.tot_new - y.act_total)):.2f} / {np.nanmean([spearmanr(g.tot_new, g.act_total).correlation for _, g in y.groupby(['season'] + ([] if ps != 'ALL' else ['pos'])) if len(g) >= 8]):.3f}")
        P(f"| {ps} | {len(y)} | " + " | ".join(o) + " |")
    GMr = {s: rows(s, "games_model_rows") for s in ("A", "B", "C")}
    P("\n  games model (g_main x G vs actual games), ADP top 150: MAE; rows with team_r1qb = 1")
    P("| pos | n | A | B | C | team_r1qb rows A / B / C |"); P("|---|---|---|---|---|---|")
    for ps in POS4:
        o, k = [], []
        for s in ("A", "B", "C"):
            x = GMr[s]; y = x[x.season.isin(YEARS) & (x.pos == ps) & (x.adp <= 150) & x.g_main.notna()]
            o.append(f"{np.mean(np.abs(y.g_main * y.G - y.act_games)):.3f}"); k.append(str(int(x[x.season.isin(YEARS) & (x.pos == ps)].team_r1qb.sum())))
        P(f"| {ps} | {len(y)} | " + " | ".join(o) + " | " + " / ".join(k) + " |")
    for nm, cols in (("qb_a11_rows", ["p_bench"]), ("qb_a13_rows", ["p_F0", "p_F3"])):
        R = {s: rows(s, nm) for s in ("A", "B", "C")}
        P(f"\n  {nm}: walk-forward P(bench) Brier on the week-1 QB1 rows all three states share")
        for c in cols:
            m = None
            for s in ("A", "B", "C"):
                x = R[s][R[s][c].notna() & R[s].benched.notna()][["season", "pid", c, "benched"]].rename(columns={c: f"p_{s}", "benched": f"b_{s}"})
                m = x if m is None else m.merge(x, on=["season", "pid"])
            P(f"   {c}: n {len(m)} | A {np.mean((m.p_A - m.b_A) ** 2):.4f} | B {np.mean((m.p_B - m.b_B) ** 2):.4f} | C {np.mean((m.p_C - m.b_C) ** 2):.4f} | no-skill {np.mean((m.b_A.mean() - m.b_A) ** 2):.4f}"
              + f" | all rows: A n {int(R['A'][c].notna().sum())}, B n {int(R['B'][c].notna().sum())}, C n {int(R['C'][c].notna().sum())}")
        P(f"   comp_hi = 1 rows: A {int(R['A'][R['A'][cols[0]].notna()].comp_hi.sum())} | B {int(R['B'][R['B'][cols[0]].notna()].comp_hi.sum())} | C {int(R['C'][R['C'][cols[0]].notna()].comp_hi.sum())}")
    P("\n  A13 log lines, the F3 column (the kept job-security form): QB games, QB season totals, superflex QB13-28")
    pat = (("P(bench) Brier F3 dev 2015-22", r"dev 2015-22 F3 one investment input\s*: all n (\d+) Brier ([\d.]+)"), ("P(bench) Brier F3 holdout 2023-25", r"holdout 2023-25 F3 one investment input\s*: all n (\d+) Brier ([\d.]+)"),
           ("games dev pool: MAE no job security / F3", r"games dev pool\s+n \d+ act [\d.]+ \| g_use [\d.]+ MAE ([\d.]+) .*?g_F3 [\d.]+ MAE ([\d.]+)"), ("games holdout pool: MAE no job security / F3", r"games holdout pool\s+n \d+ act [\d.]+ \| g_use [\d.]+ MAE ([\d.]+) .*?g_F3 [\d.]+ MAE ([\d.]+)"),
           ("totals dev pool F3: MAE / rho", r"totals dev\s+pool: .*?g_F3 MAE ([\d.]+) rho ([\d.]+)"), ("totals holdout pool F3: MAE / rho", r"totals holdout pool: .*?g_F3 MAE ([\d.]+) rho ([\d.]+)"),
           ("totals dev pool, no job security: MAE / rho", r"totals dev\s+pool: g_use MAE ([\d.]+) rho ([\d.]+)"), ("totals holdout pool, no job security: MAE / rho", r"totals holdout pool: g_use MAE ([\d.]+) rho ([\d.]+)"),
           ("totals dev QBs with ADP F3: MAE / rho", r"totals dev\s+QBs with ADP: .*?g_F3 MAE ([\d.]+) rho ([\d.]+)"), ("totals holdout QBs with ADP F3: MAE / rho", r"totals holdout QBs with ADP: .*?g_F3 MAE ([\d.]+) rho ([\d.]+)"),
           ("superflex QB13-28 dev F3: MAE / rho", r"superflex QB13-28 dev\s*: .*?g_F3 MAE ([\d.]+) rho ([\d.]+)"), ("superflex QB13-28 holdout F3: MAE / rho", r"superflex QB13-28 holdout: .*?g_F3 MAE ([\d.]+) rho ([\d.]+)"),
           ("superflex QB13-28 all F3: MAE / rho", r"superflex QB13-28 all\s*: .*?g_F3 MAE ([\d.]+) rho ([\d.]+)"), ("superflex QB13-28 all, no job security: MAE / rho", r"superflex QB13-28 all\s*: g_use MAE ([\d.]+) rho ([\d.]+)"))
    T = {s: logtxt(s, "qb_a13") for s in ("A", "B", "C")}
    P("| metric | A | B | C |"); P("|---|---|---|---|")
    for lab, rx in pat:
        o = []
        for s in ("A", "B", "C"):
            mm = re.search(rx, T[s]); o.append(" / ".join(mm.groups()) if mm else "n/a")
        P(f"| {lab} | " + " | ".join(o) + " |")
    T2 = {s: logtxt(s, "pergame_model") for s in ("A", "B", "C")}
    P("\n  per-game log, S6 blend rows as the step prints them (MAE, rho, seasons beating ADP)")
    for hdr in ("ADP top 150, dev 2015-22", "ADP top 150, final 2023-25", "ADP top 150, 2015-25", "  QB (n", "  RB (n", "  WR (n", "  TE (n"):
        o = []
        for s in ("A", "B", "C"):
            i = T2[s].find(hdr); mm = re.search(r"S6 blend\s+([\d.]+)\s+([\d.nan]+)\s+(\d+/\d+)", T2[s][i:]) if i >= 0 else None
            o.append(f"{s} {mm.group(1)} / {mm.group(2)} ({mm.group(3)})" if mm else f"{s} n/a")
        P(f"   {hdr.strip():28s}: " + " | ".join(o))
    P("\n  GATE for C (vs A): " + ("FAIL - " + "; ".join(f"{ps} worse in '{lab}' by {md:+.4f} per season (t {t:+.2f})" for lab, ps, md, t in fails) if fails else "PASS - no position is worse than production beyond season-to-season noise (paired t <= +1.81 in both pools)"))
    P("  C better than A beyond noise (t < -1.81): " + ("; ".join(f"{ps} in '{lab}' {md:+.4f} (t {t:+.2f})" for lab, ps, md, t in wins) if wins else "nowhere"))


if __name__ == "__main__":
    main()
