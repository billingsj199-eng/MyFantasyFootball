#!/usr/bin/env python3
"""
layers.py - which PIECES of the scratch model carry the value, and do they help on top of the LIVE number?

  A. ablation of the STRUCT pieces: 2025 (history, forward-ish) and 2026 W1-7 (clean), top-150 weighted
  B. candidate layers applied ON TOP of the live Sim Lab number for 2026 (the port test): zone opponent multiplier,
     team-volume Vegas tilt, QB opportunity base, per-position blends - each graded by week with the knob fitted
     leave-one-week-out
  C. QB deep dive: by-week bias / MAE live vs scratch vs market
  D. RB / WR: where the live ordering edge comes from (gap buckets)
Writes out/layers.md
"""
import os, json, numpy as np, pandas as pd
from collections import defaultdict
from model import struct_predict, apply_cal, grade, importance, load_asof, POS4, HERE
from fit_history import finalize_rows

OUT = os.path.join(HERE, "out")
P = json.load(open(os.path.join(OUT, "params.json")))
curve = {k: tuple(v) for k, v in P["curve"].items()}; cal = {k: tuple(v) for k, v in P["cal"].items()}
L = []
def PR(s=""):
    print(s); L.append(s)


def struct(df, prm=None, neutral=()):
    p = dict(P["prm"]); p.update(prm or {})
    d = df.copy()
    if "vegas" in neutral:
        d["tspread"] = 0.0; d["total"] = 44.0; d["implied"] = 22.0
    if "status" in neutral:
        d["gs"] = ""; d["pr"] = ""
    if "zone" in neutral:
        p["e_def"] = 0.0; p["e_td"] = 0.0
    if "ezshare" in neutral:
        p["w_ez"] = 0.0; p["w_gl"] = 0.0
    if "prevseason" in neutral:
        p["w_prev"] = 0.0
    if "shortewma" in neutral:
        p["a_short"] = 0.0
    if "longonly" in neutral:
        p["a_short"] = 1.0
    if "noprior" in neutral:
        for k in POS4:
            p["P_" + k] = 0.05
    if "vacated" in neutral:
        d["vac_tsh"] = 0.0; d["vac_csh"] = 0.0
    raw, parts = struct_predict(d, p, curve, P["tcoef"], P["L"])
    return apply_cal(d, raw, cal), parts


def row(df, pred, w, label, min_rows=8):
    r = grade(df, pred, w, min_rows=min_rows, label=label)
    return f"| {label} | {r['n']} | {r['mae']:.3f} | {r['bias']:+.2f} | {r['rho']:.3f} | {r['pair_acc']:.3f} |"


def section_a():
    PR("## A. STRUCT ablations (piece switched off; constants as fitted 2017-25)\n")
    h25 = finalize_rows(load_asof([2025])); h25 = h25[h25.adp <= 150].reset_index(drop=True)
    bt = pd.read_csv(os.path.join(OUT, "bt_rows.csv")); bt = bt[bt.adp <= 150].reset_index(drop=True)
    for name, df in (("2025 history (constants fitted through 2025: in-sample for the constants, not for the design)", h25), ("2026 W1-7 (clean)", bt)):
        w = importance(df, curve)
        PR(f"### {name}, top-150, weighted\n")
        PR("| variant | n | MAE | bias | Spearman | pair acc |"); PR("|---|---|---|---|---|---|")
        base, _ = struct(df)
        PR(row(df, base, w, "STRUCT full"))
        for neu, lab in (("zone", "no opponent zone rates (e_def=0)"), ("vegas", "no Vegas line (league-average game)"), ("status", "no injury-status multiplier"),
                         ("ezshare", "no end-zone / goal-line TD share"), ("prevseason", "no prior-season level in the prior"), ("noprior", "no preseason prior (evidence only)"),
                         ("longonly", "short EWMA only (no long window)"), ("shortewma", "long EWMA only (no recency)"), ("vacated", "no vacated-share read (already ~0)")):
            pr, _ = struct(df, neutral=(neu,))
            PR(row(df, pr, w, lab))
        for pos in POS4:
            m = df.pos.values == pos
            PR(f"\n{pos} only:\n"); PR("| variant | n | MAE | bias | Spearman | pair acc |"); PR("|---|---|---|---|---|---|")
            PR(row(df[m], base[m], w[m], "STRUCT full"))
            for neu, lab in (("zone", "no zone"), ("vegas", "no Vegas"), ("ezshare", "no EZ/GL share"), ("noprior", "no prior"), ("longonly", "short only"), ("shortewma", "long only")):
                pr, _ = struct(df, neutral=(neu,))
                PR(row(df[m], pr[m], w[m], lab))
        PR("")


def lowo_scale(df, base, mult, grid):
    """LIVE x mult**e with e fitted leave-one-week-out on weighted MSE; returns prediction + chosen e per week"""
    out = np.full(len(df), np.nan); es = {}
    w = df.w.values; act = df.act.values
    for wk in sorted(df.week.unique()):
        tr = df.week.values != wk; te = ~tr
        best = min(grid, key=lambda e: np.average((base[tr] * mult[tr] ** e - act[tr]) ** 2, weights=w[tr]))
        es[wk] = best; out[te] = base[te] * mult[te] ** best
    return out, es


def lowo_w(df, a, b, grid=np.linspace(0, 1, 21), by_pos=True):
    out = np.full(len(df), np.nan); ws = {}
    w = df.w.values; act = df.act.values
    for pos in (POS4 if by_pos else ("ALL",)):
        pm = (df.pos.values == pos) if by_pos else np.ones(len(df), bool)
        for wk in sorted(df.week.unique()):
            tr = pm & (df.week.values != wk) & ~np.isnan(a) & ~np.isnan(b); te = pm & (df.week.values == wk)
            if tr.sum() < 15:
                continue
            best = min(grid, key=lambda x: np.average((x * a[tr] + (1 - x) * b[tr] - act[tr]) ** 2, weights=w[tr]))
            ws[(pos, wk)] = best; out[te] = best * a[te] + (1 - best) * b[te]
    return out, ws


def weekly_table(df, preds, title):
    PR(f"\n{title}\n")
    labs = list(preds)
    PR("| week | n | " + " | ".join(labs) + " |"); PR("|---|---|" + "---|" * len(labs))
    wins = defaultdict(int); wins_r = defaultdict(int)
    for wk in sorted(df.week.unique()):
        m = df.week.values == wk
        cells = []; res = {}
        for lab in labs:
            r = grade(df[m], preds[lab][m], df.w.values[m], label=lab); res[lab] = r
            cells.append(f"{r['mae']:.2f} / {r['rho']:.3f}")
        base = res[labs[0]]
        for lab in labs[1:]:
            wins[lab] += int(res[lab]["mae"] < base["mae"]); wins_r[lab] += int(res[lab]["rho"] > base["rho"])
        PR(f"| {wk} | {int(m.sum())} | " + " | ".join(cells) + " |")
    cells = []
    for lab in labs:
        r = grade(df, preds[lab], df.w.values, label=lab); cells.append(f"{r['mae']:.3f} / {r['rho']:.3f} / pair {r['pair_acc']:.3f}")
    PR("| ALL | " + str(len(df)) + " | " + " | ".join(cells) + " |")
    nw = len(df.week.unique())
    PR("weeks better than " + labs[0] + " (MAE / rank): " + ", ".join(f"{lab} {wins[lab]}/{nw} / {wins_r[lab]}/{nw}" for lab in labs[1:]))


def section_b():
    PR("\n## B. Candidate layers ON TOP of the live number, 2026 W1-7, top-150 (knobs leave-one-week-out)\n")
    bt = pd.read_csv(os.path.join(OUT, "bt_rows.csv")); bt = bt[(bt.adp <= 150)].reset_index(drop=True)
    bt["w"] = importance(bt, curve)
    live = bt.LIVE.values.astype(float)
    full, parts = struct(bt)
    nozone, _ = struct(bt, neutral=("zone",)); noveg, _ = struct(bt, neutral=("vegas",))
    zone_mult = full / nozone; veg_mult = full / noveg
    grid = np.linspace(0, 1.5, 16)
    z_live, ez = lowo_scale(bt, live, zone_mult, grid)
    v_live, ev = lowo_scale(bt, live, veg_mult, grid)
    PR(f"zone multiplier on the live number: LOWO exponent by week {ez}; multiplier spread p10 {np.percentile(zone_mult, 10):.3f} p90 {np.percentile(zone_mult, 90):.3f}")
    PR(f"Vegas team-volume tilt on the live number: LOWO exponent by week {ev}; spread p10 {np.percentile(veg_mult, 10):.3f} p90 {np.percentile(veg_mult, 90):.3f}")
    preds = {"LIVE": live, "LIVE x zone^e": z_live, "LIVE x vegasTilt^e": v_live, "LIVE x zone (e=1)": live * zone_mult, "LIVE x zone (e=.5)": live * zone_mult ** 0.5}
    weekly_table(bt, preds, "### B1. opponent zone rates / Vegas tilt on the live number (all positions)")
    for pos in POS4:
        m = bt.pos.values == pos
        sub = bt[m].reset_index(drop=True)
        preds = {"LIVE": live[m], "LIVE x zone^e": z_live[m], "LIVE x zone (e=1)": (live * zone_mult)[m], "LIVE x zone (e=.5)": (live * zone_mult ** .5)[m]}
        weekly_table(sub, preds, f"### B1-{pos}. zone layer on live, {pos}")
    # QB: swap / blend
    m = bt.pos.values == "QB"; sub = bt[m].reset_index(drop=True)
    mk = sub.MARKET.values.astype(float)
    bl, ws = lowo_w(sub, full[m], live[m], by_pos=False)
    preds = {"LIVE": live[m], "STRUCT": full[m], "MARKET": np.where(np.isnan(mk), live[m], mk), "STRUCT+LIVE lowo": bl, "avg(STRUCT,LIVE)": 0.5 * (full[m] + live[m]),
             "LIVE - 0.8 (bias fix)": live[m] - 0.8}
    weekly_table(sub, preds, "### B2. QB: scratch opportunity base vs live (market rows filled with live where no line)")
    PR(f"QB blend weight on STRUCT by LOWO week: { {k[1]: v for k, v in ws.items()} }")
    # TE
    m = bt.pos.values == "TE"; sub = bt[m].reset_index(drop=True)
    bl, ws = lowo_w(sub, full[m], live[m], by_pos=False)
    preds = {"LIVE": live[m], "STRUCT": full[m], "STRUCT+LIVE lowo": bl, "avg(STRUCT,LIVE)": 0.5 * (full[m] + live[m])}
    weekly_table(sub, preds, "### B3. TE: scratch vs live")
    # RB / WR blends
    for pos in ("RB", "WR"):
        m = bt.pos.values == pos; sub = bt[m].reset_index(drop=True)
        bl, ws = lowo_w(sub, full[m], live[m], by_pos=False)
        preds = {"LIVE": live[m], "STRUCT": full[m], "STRUCT+LIVE lowo": bl, "avg(STRUCT,LIVE)": 0.5 * (full[m] + live[m])}
        weekly_table(sub, preds, f"### B4-{pos}. {pos}: scratch vs live")
    # the live number re-centred on the scratch RB/WR bias? no - report bias by position by week instead (section C)


def section_c():
    PR("\n## C. QB deep dive (top-150 rows with full lines)\n")
    bt = pd.read_csv(os.path.join(OUT, "bt_rows.csv")); bt = bt[(bt.adp <= 150) & (bt.pos == "QB") & bt.MARKET.notna()].reset_index(drop=True)
    bt["w"] = importance(bt, curve)
    PR("| week | n | LIVE bias | STRUCT bias | MARKET bias | LIVE MAE | STRUCT MAE | MARKET MAE | live vs market mean gap |")
    PR("|---|---|---|---|---|---|---|---|---|")
    for wk in sorted(bt.week.unique()):
        s = bt[bt.week == wk]
        PR(f"| {wk} | {len(s)} | {(s.LIVE - s.act).mean():+.2f} | {(s.STRUCT - s.act).mean():+.2f} | {(s.MARKET - s.act).mean():+.2f} | "
           f"{np.abs(s.LIVE - s.act).mean():.2f} | {np.abs(s.STRUCT - s.act).mean():.2f} | {np.abs(s.MARKET - s.act).mean():.2f} | {(s.LIVE - s.MARKET).mean():+.2f} |")
    s = bt
    PR(f"\nAll weeks: live above market by {(s.LIVE - s.MARKET).mean():+.2f} on average; rows where live >= market + 2: n={int((s.LIVE >= s.MARKET + 2).sum())}, "
       f"actual - live there {((s.act - s.LIVE)[s.LIVE >= s.MARKET + 2]).mean():+.2f}, actual - market {((s.act - s.MARKET)[s.LIVE >= s.MARKET + 2]).mean():+.2f}")
    PR(f"STRUCT QB components: team attempts (as-of pace + Vegas) x shrunk YPA (k={P['prm']['k_ypa']:.0f} att) x opponent pass-yard rate^{P['prm']['e_def']:.2f}; "
       f"pass TD = team expected TD (Vegas) x attempt share; rush = EWMA carries x shrunk YPC.")
    # which QBs
    g = bt.groupby("name").agg(n=("act", "size"), act=("act", "mean"), live=("LIVE", "mean"), struct=("STRUCT", "mean"), mk=("MARKET", "mean"))
    g["live_err"] = g.live - g.act; g["struct_err"] = g.struct - g.act
    g = g[g.n >= 4].sort_values("live_err")
    PR("\nPer-QB mean error (4+ weeks):\n")
    PR("| QB | n | actual | LIVE | STRUCT | MARKET | live err | struct err |"); PR("|---|---|---|---|---|---|---|---|")
    for r in g.itertuples():
        PR(f"| {r.Index} | {r.n} | {r.act:.1f} | {r.live:.1f} | {r.struct:.1f} | {r.mk:.1f} | {r.live_err:+.1f} | {r.struct_err:+.1f} |")


def section_d():
    PR("\n## D. RB / WR: where the live ordering edge comes from\n")
    bt = pd.read_csv(os.path.join(OUT, "bt_rows.csv")); bt = bt[(bt.adp <= 150) & bt.pos.isin(["RB", "WR"])].reset_index(drop=True)
    bt["w"] = importance(bt, curve)
    bt["gap"] = bt.STRUCT - bt.LIVE
    bt["ratio"] = bt.LIVE / bt.STRUCT
    PR("Rows bucketed by live/scratch ratio (the live number carries news the as-of stat state cannot see: practice reports, depth charts, overrides):\n")
    PR("| pos | live/scratch | n | actual | LIVE | STRUCT | MARKET | STRUCT closer |"); PR("|---|---|---|---|---|---|---|---|")
    for pos in ("RB", "WR"):
        s = bt[bt.pos == pos]
        for lo, hi, lab in ((0, 0.6, "< 0.6 (live knows he is limited)"), (0.6, 0.85, "0.6-0.85"), (0.85, 1.15, "0.85-1.15 (agree)"), (1.15, 1.5, "1.15-1.5"), (1.5, 9, "> 1.5 (live sees a bigger role)")):
            x = s[(s.ratio >= lo) & (s.ratio < hi)]
            if len(x) == 0:
                continue
            closer = (np.abs(x.STRUCT - x.act) < np.abs(x.LIVE - x.act)).mean()
            mk = x.MARKET.mean()
            PR(f"| {pos} | {lab} | {len(x)} | {x.act.mean():.1f} | {x.LIVE.mean():.1f} | {x.STRUCT.mean():.1f} | {mk:.1f} | {closer:.0%} |")
    PR("\nIf the scratch model is handed the live number's news (rows where live/scratch < 0.6 or > 1.5 take the live number), what happens to its rank score?\n")
    news = (bt.ratio < 0.6) | (bt.ratio > 1.5)
    patched = np.where(news, bt.LIVE.values, bt.STRUCT.values)
    for pos in ("RB", "WR"):
        m = bt.pos.values == pos
        PR("| model | n | MAE | bias | Spearman | pair acc |"); PR("|---|---|---|---|---|---|")
        PR(row(bt[m], bt.LIVE.values[m], bt.w.values[m], f"{pos} LIVE")); PR(row(bt[m], bt.STRUCT.values[m], bt.w.values[m], f"{pos} STRUCT"))
        PR(row(bt[m], patched[m], bt.w.values[m], f"{pos} STRUCT with live's news rows ({int((news & m).sum())} rows)"))
        PR("")
    # lead-back read: STRUCT vs LIVE by carry-share bucket
    PR("RB by as-of carry share (short EWMA), 2+ games:\n")
    s = bt[(bt.pos == "RB") & (bt.g >= 2)]
    PR("| carry share | n | actual | LIVE | STRUCT | MARKET |"); PR("|---|---|---|---|---|---|")
    for lo, hi in ((0, .3), (.3, .5), (.5, .65), (.65, 1.01)):
        x = s[(s.csh_s >= lo) & (s.csh_s < hi)]
        if len(x):
            PR(f"| {lo:.2f}-{hi:.2f} | {len(x)} | {x.act.mean():.1f} | {x.LIVE.mean():.1f} | {x.STRUCT.mean():.1f} | {x.MARKET.mean():.1f} |")


if __name__ == "__main__":
    section_a(); section_b(); section_c(); section_d()
    open(os.path.join(OUT, "layers.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("wrote out/layers.md")
