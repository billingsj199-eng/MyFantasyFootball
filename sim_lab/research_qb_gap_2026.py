#!/usr/bin/env python3
"""
WHY DO THE SIM'S QB PROJECTIONS TRAIL THE MARKET IN 2026? (Jack 2026-10-23) - research only, nothing wired.
Lock rows W1-6 2026 (data/snapshots/simlab_snapshot_wN.json) x actual half-PPR (weekly_stats_active) x site consensus.
  A  bias / MAE / rank by model and week (shipped, prop, model base, shadow, Clay, books-implied market, consensus, ESPN)
  B  replay of TODAY's rule (face-value lines, base = shadow, tuner propW at lock, book cap) - checks it reproduces W5-6
  C  where the error sits (segments) for the replay vs consensus
  D  candidate fixes, leave-one-week-out (W2-6; W1 has no shadow -> base = Clay-side jsMean, reported separately):
     C1 QB market scoring completed (INT -1, fumble lost -2, 2-pt) - the market mean omits them, actuals include them
     C2 pass-TD line -> devigged Poisson mean from the over/under odds (face value 1.5 is a median, not a mean)
     W  QB anchor weight re-fit (LOWO), alone and on top of C1/C2
Log research_qb_gap_2026.log.
"""
import json, os, sys, math
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from score_week import norm, load_consensus
from diagnose_week import load_rows
LOG = open(os.path.join(HERE, "research_qb_gap_2026.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + "\n"); LOG.flush()
BOOKS = ["UD", "PP", "DK", "FD", "MGM"]
# league QB per-game rates the market leaves out, 2022-25 starters (pa >= 15) from weekly_stats_active: INT .69, FL .20, 2-pt/other +.19 pts
INT_G, FL_G, OTH_PTS = 0.69, 0.20, 0.19


def med(e, k):
    v = sorted(e[b][k] for b in BOOKS if isinstance(e.get(b), dict) and isinstance(e[b].get(k), (int, float)))
    return v[len(v) // 2] if v else None


def am(o): return (-o / (-o + 100)) if o < 0 else 100 / (o + 100)


def pois_over_mean(line, po):
    k = int(math.floor(line)); lo, hi = 0.01, 6.0
    for _ in range(60):
        m = (lo + hi) / 2; cdf = sum(math.exp(-m) * m ** i / math.factorial(i) for i in range(k + 1))
        lo, hi = (m, hi) if 1 - cdf < po else (lo, m)
    return m


def odds_mean(e, k, ko, ku):
    v = []
    for b in BOOKS:
        r = e.get(b)
        if isinstance(r, dict) and all(isinstance(r.get(x), (int, float)) for x in (k, ko, ku)):
            po, pu = am(r[ko]), am(r[ku]); v.append(pois_over_mean(r[k], po / (po + pu)))
    return float(np.median(v)) if v else None


def ptd_devig(e): return odds_mean(e, "ptd", "ptdo", "ptdu")
def int_mean(e): return odds_mean(e, "int", "into", "intu")


def market(p, c1=False, c2=False, int_src="league"):
    """engine propImpliedFp for a QB (face-value lines, ATD juice 1.06), plus the candidate fixes."""
    e = p.get("lines") or {}; c = p.get("comps") or {}
    py, ptd, ry, atd = med(e, "py"), med(e, "ptd"), med(e, "ry"), med(e, "atd")
    mpy, mry = c.get("py", 0) * .04, c.get("ry", 0) * .1
    cov = (mpy if py else 0) + (mry if ry else 0)
    if not (mpy + mry > 0) or cov / (mpy + mry) < 0.6: return None
    fp = (py * .04 if py else mpy) + (ry * .1 if ry else mry)
    pt = ptd if ptd else c.get("ptd", 0)
    if c2 and ptd:
        dv = ptd_devig(e)
        if dv is not None: pt = dv
    fp += pt * 4
    if atd is not None:
        pT = min(.85, max(.01, am(atd) / 1.06)); lam = -math.log(1 - pT); fp += lam * 6
    else:
        fp += c.get("rtd", 0) * 6
    if c1:
        im = int_mean(e) if int_src == "ud" else None
        fp += -(im if im is not None else INT_G) - 2 * FL_G + OTH_PTS
    return fp


def full(p):
    e = p.get("lines") or {}
    return all(med(e, k) for k in ("py", "ptd", "ry"))


def spear(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 4: return np.nan
    ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b)); return float(np.corrcoef(ra, rb)[0, 1])


def load():
    R = []
    for w in range(1, 7):
        s = json.load(open(os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{w}.json"), encoding="utf-8"))
        act = load_rows(w); cons, _ = load_consensus(w)
        imp = {}
        for p in s["players"]:
            if p.get("tm") and isinstance(p.get("implied"), (int, float)): imp[p["tm"]] = p["implied"]
        for p in s["players"]:
            if p.get("pos") != "QB" or (p.get("mean") or 0) < 5: continue
            a = act.get(norm(p["name"]))
            if not a: continue
            c = cons.get(norm(p["name"])) or {}
            t = p.get("tun") or {}
            R.append(dict(p=p, wk=w, name=p["name"], tm=p["tm"], act=float(a["fpts"]), stat=a, mean=p["mean"], prop=p.get("propMean"), js=p.get("jsMean"),
                          nc=p.get("ncMean"), clay=p.get("clayMean"), cons=c.get("h"), espn=(c.get("e") or [None])[0], w=t.get("w", 0.70) if t else 0.70,
                          implied=p.get("implied"), oppimp=imp.get(p.get("opp")), ncSrc=str(p.get("ncSrc") or ""), qbf=p.get("qbf") or 1,
                          ry=(p.get("comps") or {}).get("ry", 0)))
    return R


def anchored(r, mk, w, base):
    if mk is None: return base
    v = w * mk + (1 - w) * base
    if full(r["p"]) and v > mk * 1.2: v = mk * 1.2
    return v


def grade(rows, key):
    rr = [r for r in rows if isinstance(r.get(key), (int, float))]
    e = np.array([r[key] - r["act"] for r in rr])
    rho = np.nanmean([spear([r[key] for r in rr if r["wk"] == w], [r["act"] for r in rr if r["wk"] == w]) for w in sorted(set(r["wk"] for r in rr))])
    return len(rr), float(np.mean(np.abs(e))), float(np.mean(e)), rho


def main():
    R = load()
    P(f"=== QB gap 2026: {len(R)} scored QB rows (shipped mean >= 5, played), W1-6 ===")
    for r in R:
        r["mkt"] = market(r["p"]); r["base"] = r["nc"] if r["nc"] is not None else r["js"]
        r["replay"] = anchored(r, r["mkt"], r["w"], r["base"])
    C = [r for r in R if r["cons"] is not None and r["espn"] is not None]
    P(f"rows with consensus + ESPN: {len(C)}")
    P("\n--- A  bias / MAE / within-week Spearman (same rows) ---")
    keys = [("mean", "SHIPPED"), ("prop", "propMean"), ("js", "model base jsMean"), ("nc", "shadow ncMean"), ("clay", "Clay stack"),
            ("mkt", "books-implied (face, engine formula)"), ("replay", "TODAY's rule replay"), ("cons", "site consensus"), ("espn", "ESPN")]
    for lab_, rows in (("W1-6", C), ("W2-6 (shadow exists)", [r for r in C if r["wk"] >= 2]), ("W5-6 (current pipeline)", [r for r in C if r["wk"] >= 5])):
        P(f"  {lab_}:")
        for k, lab in keys:
            n, mae, b, rho = grade(rows, k)
            P(f"    {lab:38s} n{n:4d} MAE {mae:5.2f} bias {b:+5.2f} rho {rho:.3f}")
    P("\n  by week, MAE (bias): shipped | replay | shadow/base | market | consensus | ESPN")
    for w in range(1, 7):
        rows = [r for r in C if r["wk"] == w]
        P("    W%d n%2d " % (w, len(rows)) + " | ".join("%5.2f (%+5.2f)" % grade(rows, k)[1:3] for k in ("mean", "replay", "base", "mkt", "cons", "espn")))
    d56 = [abs(r["replay"] - r["prop"]) for r in R if r["wk"] >= 5 and r["prop"] is not None]
    P(f"\n  replay check W5-6: |replay - stored propMean| median {np.median(d56):.3f}, mean {np.mean(d56):.3f} (n{len(d56)}) -> replay = today's rule")
    d14 = [r["prop"] - r["replay"] for r in R if r["wk"] <= 4 and r["prop"] is not None]
    P(f"  W1-4 stored propMean minus today's rule: mean {np.mean(d14):+.2f} (lines were divided by the gamma median ratio until 10-07)")
    P("\n--- A2  component bias on lined rows: books' lines vs actual stat (pts) ---")
    L = [r for r in R if r["mkt"] is not None]
    for k, sk, pt in (("py", "py", .04), ("ptd", "ptd", 4), ("ry", "ry", .1)):
        a = np.array([(med(r["p"]["lines"], k), r["stat"].get(sk, 0)) for r in L if med(r["p"]["lines"], k)])
        P(f"    {sk:4s} line {a[:,0].mean():7.2f} act {a[:,1].mean():7.2f} act/line {a[:,1].sum()/a[:,0].sum():.3f} -> market pts {(a[:,0]-a[:,1]).mean()*pt:+.2f}")
    a = np.array([(ptd_devig(r["p"]["lines"]), med(r["p"]["lines"], "ptd"), r["stat"].get("ptd", 0)) for r in L if ptd_devig(r["p"]["lines"]) is not None])
    P(f"    pass TD n{len(a)}: face line {a[:,1].mean():.3f} | devigged Poisson mean {a[:,0].mean():.3f} | actual {a[:,2].mean():.3f} | MAE face {np.abs(a[:,1]-a[:,2]).mean():.3f} devig {np.abs(a[:,0]-a[:,2]).mean():.3f}")
    P(f"    INT / fumbles / 2-pt are NOT in the market mean: 2026 rows avg INT {np.mean([r['stat'].get('int',0) for r in L]):.2f}, FL {np.mean([r['stat'].get('fl',0) for r in L]):.2f}"
      f" -> {-np.mean([r['stat'].get('int',0)+2*r['stat'].get('fl',0) for r in L]):+.2f} pts the books' number never subtracts (2022-25 league: INT .69, FL .20, 2-pt +.19)")

    P("\n--- C  where the error sits: replay (today's rule) vs consensus, W2-6 ---")
    C2 = [r for r in C if r["wk"] >= 2]
    imps = sorted(r["implied"] or 0 for r in C2); t1, t2 = imps[len(imps) // 3], imps[2 * len(imps) // 3]
    def spread(r): return (r["implied"] or 0) - (r["oppimp"] if r["oppimp"] is not None else (r["implied"] or 0))
    segs = [("rushing QB (model ry >= 25)", lambda r: r["ry"] >= 25), ("mid rush 12-25", lambda r: 12 <= r["ry"] < 25), ("pocket (ry < 12)", lambda r: r["ry"] < 12),
            (f"team total low (< {t1})", lambda r: (r["implied"] or 0) < t1), ("team total mid", lambda r: t1 <= (r["implied"] or 0) < t2), (f"team total high (>= {t2})", lambda r: (r["implied"] or 0) >= t2),
            ("big favorite (implied edge >= 5.5)", lambda r: spread(r) >= 5.5), ("near pick-em", lambda r: abs(spread(r)) < 5.5), ("big underdog", lambda r: spread(r) <= -5.5),
            ("shipped >= 20 (QB1 tier)", lambda r: r["mean"] >= 20), ("shipped 16-20", lambda r: 16 <= r["mean"] < 20), ("shipped < 16", lambda r: r["mean"] < 16),
            ("shadow on history prior", lambda r: r["ncSrc"].startswith("hist")), ("shadow on other prior (new/young/backup)", lambda r: not r["ncSrc"].startswith("hist")),
            ("health prior tag (hlth)", lambda r: "hlth" in r["ncSrc"]), ("Clay-side QB floor lifted", lambda r: r["qbf"] > 1.001),
            ("model above market by 2+", lambda r: r["mkt"] is not None and r["base"] - r["mkt"] >= 2), ("market above model by 2+", lambda r: r["mkt"] is not None and r["mkt"] - r["base"] >= 2),
            ("model within 2 of market", lambda r: r["mkt"] is not None and abs(r["mkt"] - r["base"]) < 2)]
    tot = sum(abs(r["replay"] - r["act"]) - abs(r["cons"] - r["act"]) for r in C2)
    P(f"    total MAE gap replay - consensus over {len(C2)} rows: {tot/len(C2):+.3f} per row")
    P(f"    {'segment':42s}   n | replay MAE bias | shadow MAE bias | market MAE bias | cons MAE bias | gap")
    for lab, f in segs:
        rr = [r for r in C2 if f(r)]
        if len(rr) < 8: continue
        def g(k):
            x = [r for r in rr if r[k] is not None]
            return np.mean([abs(r[k] - r["act"]) for r in x]), np.mean([r[k] - r["act"] for r in x])
        gap = sum(abs(r["replay"] - r["act"]) - abs(r["cons"] - r["act"]) for r in rr)
        P(f"    {lab:42s} {len(rr):3d} | {g('replay')[0]:5.2f} {g('replay')[1]:+5.2f} | {g('base')[0]:5.2f} {g('base')[1]:+5.2f} | {g('mkt')[0]:5.2f} {g('mkt')[1]:+5.2f} | {g('cons')[0]:5.2f} {g('cons')[1]:+5.2f} | {gap/len(rr):+.2f}/row ({100*gap/tot:+.0f}% of gap)")
    P("\n  biggest replay misses vs consensus (W2-6):")
    for r in sorted(C2, key=lambda r: -(abs(r["replay"] - r["act"]) - abs(r["cons"] - r["act"])))[:12]:
        mk = r["mkt"] if r["mkt"] is not None else float("nan")
        P(f"    W{r['wk']} {r['name']:20s} act {r['act']:5.1f} replay {r['replay']:5.1f} shadow {r['base']:5.1f} market {mk:5.1f} cons {r['cons']:5.1f} espn {r['espn']:5.1f}")

    P("\n--- D  candidate fixes, leave-one-week-out on W2-6 (w picked on the other 4 weeks by MAE, applied to the held-out week) ---")
    VAR = {"today (face lines)": dict(), "C1 market + INT/FL/2pt": dict(c1=True), "C1 with UD INT odds": dict(c1=True, int_src="ud"),
           "C2 pass-TD devig": dict(c2=True), "C1+C2": dict(c1=True, c2=True)}
    WG = np.round(np.arange(0, 1.0001, 0.05), 2)
    for r in R:
        for vn, kw in VAR.items(): r["mk_" + vn] = market(r["p"], **kw)
    D = [r for r in C if r["wk"] >= 2]
    def pred(r, vn, w): return anchored(r, r["mk_" + vn], w, r["base"])
    def mae(rows, vn, w): return np.mean([abs(pred(r, vn, w) - r["act"]) for r in rows])
    P(f"    {'variant':26s} {'w rule':7s} | per held-out week MAE / w            | pooled MAE  rho   bias | folds better than today | cons MAE")
    base_fold = {}
    for vn in VAR:
        for wr in ("lock w", "LOWO"):
            out, preds = [], []
            for hw in range(2, 7):
                te = [r for r in D if r["wk"] == hw]; tr = [r for r in D if r["wk"] != hw]
                if wr == "LOWO":
                    wb = WG[int(np.argmin([mae(tr, vn, w) for w in WG]))]
                    pv = [pred(r, vn, wb) for r in te]; lab_w = f"{wb:.2f}"
                else:
                    pv = [pred(r, vn, r["w"]) for r in te]; lab_w = f"{np.mean([r['w'] for r in te]):.2f}"
                e = np.mean([abs(p_ - r["act"]) for p_, r in zip(pv, te)]); rho = spear(pv, [r["act"] for r in te])
                out.append((e, rho, lab_w)); preds += list(zip(pv, te))
            if vn == "today (face lines)" and wr == "lock w": base_fold = {i: o[0] for i, o in enumerate(out)}
            wins = sum(1 for i, o in enumerate(out) if o[0] < base_fold.get(i, 9e9) - 1e-9)
            pm = np.mean([abs(p_ - r["act"]) for p_, r in preds]); pb = np.mean([p_ - r["act"] for p_, r in preds])
            prho = np.mean([o[1] for o in out]); cm = np.mean([abs(r["cons"] - r["act"]) for _, r in preds])
            P(f"    {vn:26s} {wr:7s} | " + " ".join(f"{o[0]:4.2f}/{o[2]}" for o in out) + f" | {pm:5.3f}  {prho:.3f} {pb:+5.2f} | {wins}/5 | {cm:.3f}")
    P("\n    pooled w sweep (W2-6), MAE:")
    for vn in VAR:
        P(f"    {vn:26s} " + " ".join(f"{w:.1f}:{mae(D, vn, w):.3f}" for w in WG[::2]))
    P("    pooled w sweep (W2-6), mean within-week rho:")
    for vn in VAR:
        P(f"    {vn:26s} " + " ".join(f"{w:.1f}:{np.mean([spear([pred(r, vn, w) for r in D if r['wk'] == k], [r['act'] for r in D if r['wk'] == k]) for k in range(2, 7)]):.3f}" for w in WG[::2]))
    P("\n    W1 (base = Clay-side jsMean; no shadow): MAE / rho at lock w")
    W1 = [r for r in C if r["wk"] == 1]
    for vn in VAR:
        pv = [anchored(r, r["mk_" + vn], r["w"], r["js"]) for r in W1]
        P(f"      {vn:26s} {np.mean([abs(p_ - r['act']) for p_, r in zip(pv, W1)]):.3f}  rho {spear(pv, [r['act'] for r in W1]):.3f}")

    P("\n--- E  FORWARD tuner simulation W1-6 (honest: week k uses only weeks < k) ---")
    P("    tune_weekly.py QB propW = (4 x prior + n x wBest) / (4 + n), wBest = MAE-best w on the earlier weeks; base = shadow (W1: Clay-side jsMean)")
    P("    graded per week on MAE / RMSE / within-week rho; 'cons' = site consensus on the same rows")
    CC = [r for r in C]
    for r in CC: r["b6"] = r["base"]
    def sim(prior, vn, below_gap=None):
        res, wpath = {}, []
        for k in range(1, 7):
            past = [r for r in CC if r["wk"] < k]
            if past:
                wb = WG[int(np.argmin([np.mean([abs(anchored(r, r["mk_" + vn], w, r["b6"]) - r["act"]) for r in past]) for w in WG]))]
                nwk = len(set(r["wk"] for r in past)); w = (4 * prior + nwk * wb) / (4 + nwk)
            else:
                w = prior
            wpath.append(w)
            te = [r for r in CC if r["wk"] == k]
            pv = []
            for r in te:
                ww = w
                if below_gap is not None and r["mk_" + vn] is not None and r["mk_" + vn] - r["b6"] >= below_gap and r["mk_" + vn] >= 8: ww = min(ww, 0.28)
                pv.append(anchored(r, r["mk_" + vn], ww, r["b6"]))
            e = np.array([p_ - r["act"] for p_, r in zip(pv, te)])
            res[k] = (float(np.mean(np.abs(e))), float(np.sqrt(np.mean(e ** 2))), spear(pv, [r["act"] for r in te]), float(np.mean(e)))
        return res, wpath
    ref, _ = sim(0.70, "today (face lines)")
    consw = {k: (np.mean([abs(r["cons"] - r["act"]) for r in CC if r["wk"] == k]), spear([r["cons"] for r in CC if r["wk"] == k], [r["act"] for r in CC if r["wk"] == k])) for k in range(1, 7)}
    P(f"    {'variant':44s} | " + " ".join(f"W{k} MAE/rho      " for k in range(1, 7)) + "| MAE   RMSE  rho   bias | MAE wins / rho wins vs today | w path")
    def row(lab, res, wpath):
        mae_ = np.mean([res[k][0] for k in res]); rm = np.mean([res[k][1] for k in res]); rh = np.mean([res[k][2] for k in res]); bi = np.mean([res[k][3] for k in res])
        mw = sum(1 for k in res if res[k][0] < ref[k][0] - 1e-9); rw = sum(1 for k in res if res[k][2] > ref[k][2] + 1e-9)
        P(f"    {lab:44s} | " + " ".join(f"{res[k][0]:4.2f}/{res[k][2]:.3f}     " for k in range(1, 7)) + f"| {mae_:.3f} {rm:.3f} {rh:.3f} {bi:+.2f} | {mw}/6 {rw}/6 | " + " ".join(f"{w:.2f}" for w in wpath))
    for lab, prior, vn, bg in (("today: prior .70, face lines", 0.70, "today (face lines)", None),
                               ("prior .50", 0.50, "today (face lines)", None), ("prior .30", 0.30, "today (face lines)", None),
                               ("prior .20 (RB/TE rule)", 0.20, "today (face lines)", None),
                               ("belowW for QB at a 2-pt gap (prior .70)", 0.70, "today (face lines)", 2.0),
                               ("C1 INT/FL/2pt, prior .70", 0.70, "C1 market + INT/FL/2pt", None), ("C1, prior .30", 0.30, "C1 market + INT/FL/2pt", None),
                               ("C1 UD INT odds, prior .30", 0.30, "C1 with UD INT odds", None),
                               ("C1+C2, prior .70", 0.70, "C1+C2", None), ("C1+C2, prior .30", 0.30, "C1+C2", None),
                               ("model alone (w 0)", 0.0, "today (face lines)", None)):
        if prior == 0.0:
            res = {}
            for k in range(1, 7):
                te = [r for r in CC if r["wk"] == k]; e = np.array([r["b6"] - r["act"] for r in te])
                res[k] = (float(np.mean(np.abs(e))), float(np.sqrt(np.mean(e ** 2))), spear([r["b6"] for r in te], [r["act"] for r in te]), float(np.mean(e)))
            row(lab, res, [0] * 6); continue
        res, wp = sim(prior, vn, bg); row(lab, res, wp)
    P("    consensus (reference)                        | " + " ".join(f"{consw[k][0]:4.2f}/{consw[k][1]:.3f}     " for k in range(1, 7)) + f"| {np.mean([consw[k][0] for k in consw]):.3f}")
    P("\n--- F  info only: 50/50 shadow + consensus on W2-6 (Jack's standing call - outside numbers in the public mean) ---")
    for k in range(2, 7):
        te = [r for r in CC if r["wk"] == k]
        P(f"    W{k} shadow {np.mean([abs(r['b6']-r['act']) for r in te]):.2f}/{spear([r['b6'] for r in te],[r['act'] for r in te]):.3f}  cons {np.mean([abs(r['cons']-r['act']) for r in te]):.2f}/{spear([r['cons'] for r in te],[r['act'] for r in te]):.3f}  50/50 {np.mean([abs(.5*r['b6']+.5*r['cons']-r['act']) for r in te]):.2f}/{spear([.5*r['b6']+.5*r['cons'] for r in te],[r['act'] for r in te]):.3f}")
    LOG.close()


if __name__ == "__main__":
    main()
