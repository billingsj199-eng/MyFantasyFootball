#!/usr/bin/env python3
"""
DEFENSES vs SLOT / OUTSIDE / TE through 4 weeks (Jack 2026-10-08: "even down to weekly if teams allow more points to slot vs
outside WR" -> "can we check through 4 weeks to see if there are any specific teams").
PFF single-week receiving exports (slot_rate / wide_rate / inline_rate, routes, receptions, yards, TDs for every receiver):
  1  2026 weeks 1-4: half-PPR receiving points each defense allowed PER ROUTE run from the slot, from out wide, and by TEs
     (inline + TE slot/wide), vs the league; the slot-minus-outside contrast; extremes listed.
  2  does a 4-week read hold? 2019-25: each defense's weeks 1-4 rate vs its weeks 5-17 rate (Pearson r) for slot, outside,
     TE, all-receiver, and the contrast; the 4 most extreme defenses each season after week 4 -> where they finished (weeks 5+),
     as a share of their week 1-4 gap that survived.
Log defense_alignment_2026.log.
"""
import os, sys, glob, warnings
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import bt_common as B
from backtest_matchup_rank import PFF2NFL
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "defense_alignment_2026.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
WK = os.path.join(B.CACHE, "pff", "weekly")


def week_file(Y, w):
    for f in (f"pff_receiving_summary_{Y}_w{w}.csv", f"pff_receiving_{Y}_w{w}.csv"):
        p = os.path.join(WK, f)
        if os.path.exists(p): return p
    return None


def season(Y, weeks):
    """per defense: {'slot': [pts, routes], 'wide': [...], 'te': [...], 'all': [...]} summed over weeks, plus per week."""
    games = B.load_games(Y); D = defaultdict(lambda: defaultdict(lambda: np.zeros(2)))
    for w in weeks:
        f = week_file(Y, w)
        if not f: continue
        d = pd.read_csv(f); d = d[d.position.isin(["WR", "TE"]) & (d.routes > 0)]
        for r in d.itertuples(index=False):
            tm = PFF2NFL.get(r.team_name, r.team_name); gm = games.get((tm, w))
            if not gm: continue
            opp = gm["opp"]; pts = 0.5 * (r.receptions or 0) + 0.1 * (r.yards or 0) + 6.0 * (r.touchdowns or 0)
            sl, wd, il = [max(0.0, float(getattr(r, k) if pd.notna(getattr(r, k)) else 0.0)) for k in ("slot_rate", "wide_rate", "inline_rate")]
            tot = sl + wd + il
            if tot <= 0: continue
            rt = float(r.routes)
            if r.position == "TE":
                D[opp]["te"] += (pts, rt)
            else:
                D[opp]["slot"] += (pts * sl / tot, rt * sl / tot); D[opp]["wide"] += (pts * (wd + il) / tot, rt * (wd + il) / tot)
            D[opp]["all"] += (pts, rt)
    return D


def rates(D, k, min_rt=40):
    return {t: v[k][0] / v[k][1] for t, v in D.items() if v[k][1] >= min_rt}


def main():
    P("=== 1  2026 WEEKS 1-4: receiving points allowed per route (half PPR), by alignment ===")
    D = season(2026, range(1, 5))
    R = {k: rates(D, k, 30 if k != "all" else 60) for k in ("slot", "wide", "te", "all")}
    lg = {k: np.mean(list(v.values())) for k, v in R.items()}
    P("  league per-route: " + " | ".join(f"{k} {lg[k]:.3f}" for k in R))
    rows = []
    for t in sorted(D):
        if t not in R["slot"] or t not in R["wide"]: continue
        rows.append((t, R["slot"][t] / lg["slot"], R["wide"][t] / lg["wide"], R.get("te", {}).get(t, np.nan) / lg["te"], R["all"].get(t, np.nan) / lg["all"], D[t]["slot"][1], D[t]["wide"][1], D[t]["te"][1]))
    df = pd.DataFrame(rows, columns=["def", "slot", "outside", "te", "all", "slotRt", "wideRt", "teRt"])
    df["contrast"] = df.slot - df.outside
    P(f"  ratio to league (1.00 = average; 1.30 = allows 30% more per route). {len(df)} defenses.")
    for col, lab in (("slot", "vs SLOT WRs"), ("outside", "vs OUTSIDE WRs"), ("te", "vs TEs"), ("contrast", "slot MINUS outside (slot-specific weakness)")):
        s = df.sort_values(col, ascending=False)
        P(f"\n  {lab}: most generous " + ", ".join(f"{r.def_ if hasattr(r, 'def_') else r[1]} {getattr(r, col):.2f}" for r in s.head(5).itertuples()) + " | stingiest " + ", ".join(f"{r[1]} {getattr(r, col):.2f}" for r in s.tail(5).iloc[::-1].itertuples()))
    df.round(3).to_csv(os.path.join(HERE, "defense_alignment_2026.csv"), index=False)

    P("\n=== 2  DOES A 4-WEEK READ HOLD? 2019-25: weeks 1-4 vs the same defense in weeks 5-17 ===")
    cors = defaultdict(list); keep = defaultdict(list)
    for Y in range(2019, 2026):
        A_ = season(Y, range(1, 5)); Bq = season(Y, range(5, 18))
        for k in ("slot", "wide", "te", "all"):
            ra = rates(A_, k, 30 if k != "all" else 60); rb = rates(Bq, k, 100)
            ts = [t for t in ra if t in rb]
            if len(ts) < 20: continue
            a = np.array([ra[t] for t in ts]); b = np.array([rb[t] for t in ts])
            cors[k].append(np.corrcoef(a, b)[0, 1])
            la, lb = a.mean(), b.mean(); za = a / la - 1; zb = b / lb - 1
            o = np.argsort(-np.abs(za))[:4]   # the 4 most extreme after week 4
            keep[k].append(float(np.sum(zb[o] * np.sign(za[o])) / np.sum(np.abs(za[o]))))
        ra_s, ra_w = rates(A_, "slot", 30), rates(A_, "wide", 30); rb_s, rb_w = rates(Bq, "slot", 100), rates(Bq, "wide", 100)
        ts = [t for t in ra_s if t in ra_w and t in rb_s and t in rb_w]
        if len(ts) >= 20:
            ca = np.array([ra_s[t] / np.mean(list(ra_s.values())) - ra_w[t] / np.mean(list(ra_w.values())) for t in ts])
            cb = np.array([rb_s[t] / np.mean(list(rb_s.values())) - rb_w[t] / np.mean(list(rb_w.values())) for t in ts])
            cors["contrast"].append(np.corrcoef(ca, cb)[0, 1])
            o = np.argsort(-np.abs(ca))[:4]; keep["contrast"].append(float(np.sum(cb[o] * np.sign(ca[o])) / np.sum(np.abs(ca[o]))))
    for k, lab in (("all", "all receivers (position FPA-like)"), ("slot", "slot WRs"), ("wide", "outside WRs"), ("te", "TEs"), ("contrast", "slot-vs-outside contrast")):
        if cors[k]:
            P(f"  {lab:34s} r weeks 1-4 -> 5-17: {np.mean(cors[k]):+.2f} (by season {' '.join(f'{c:+.2f}' for c in cors[k])}) | the 4 most extreme defenses keep {100*np.mean(keep[k]):.0f}% of their week 1-4 gap")
    P("\n  read: r near 0 = the 4-week ranking is mostly noise; 'keep' = how much of an extreme team's early gap shows up the rest of the year.")
    P("\nLimitations: PFF alignment shares per player-week (a receiver's points split by his route mix); receiving points only; TE = all TE routes; 2026 = 4 games per defense.")
    LOG.close()


if __name__ == "__main__":
    main()
