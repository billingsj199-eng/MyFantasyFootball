#!/usr/bin/env python3
"""
Slow weekly tuner (Jack, 2026-09-14: "slowly implement each week").

Re-fits engine knobs from EVERY scored week so far and shrinks each toward
its preseason prior with a 4-week-equivalent weight — one week moves a knob
~1/5 of the way to what that week says; five agreeing weeks move it most of
the way; one wild week barely registers.

  propW[pos]        market-anchor weight per position (engine PROP_W = .70; prior per
                    position = PRIOR_W_POS, RB/TE .20 since 2026-09-29, floor W_FLOOR)
                    evidence = MAE-minimising w on the lock rows; market is
                    reconstructed from the stored means with the weight that
                    was LIVE at lock: market = (propMean − (1−w)·jsMean) / w
  sigmaMult[pos]    multiplier on SIGMA_CAL[pos] (QB/RB/WR/TE/K) from p10-p90
                    coverage (target 80%): evidence = liveMult · (1 + (.80 − inside))
  tdMult[pos][stat] TD-rate multipliers on the Clay prior's ptd/rtd/rctd
                    components: evidence = Σ actual TDs / Σ raw projected TDs,
                    prior worth 4 weeks of projected TDs (Poisson-honest)
  kLevel            kicker level multiplier (Σ actual / Σ raw clean mean)
  dstShift          additive DST level (mean actual − raw model), shrunk to 0; + sigmaMult.DST
  belowW            market weight used ONLY when the clean model sits >= BELOW_GAP pts under
                    the market on a starter (market >= BELOW_STARTER_MIN); pooled across
                    positions, evidence = MAE-minimising w on those rows, shrunk to PROP_W
  aboveW            market weight used ONLY when the clean model sits >= ABOVE_GAP pts ABOVE
                    the market on an ABOVE_POS player (WR, 2026-10-07); same fit, shrunk to
                    PROP_W; the engine takes max(w, aboveW) — it only ever raises the weight
  atdJuice[pos]     anytime-TD devig factor replacing the flat PROP_ATD_JUICE 1.06 inside the
                    market-implied mean (2026-10-07, written for ATD_JUICE_POS = RB + WR):
                    J such that Σ λ(p_raw/J) = Σ actual rush+rec TDs, Poisson-honest shrink
                    like tdMult, clamp 1.0-1.35; evidence printed for every position

Every lock row carries `tun` = the tuner values live when it was locked
(export_site_proj.js), so evidence is always measured against the RAW prior
(divide the live multiplier back out) — the loop converges instead of
compounding. W1 2026 rows have no `tun` (nothing was live) = raw.

Writes data/sim_tuning.js -> window.SIM_TUNING, read by engine.js
(propWeight, buildPlayers) in index.html AND export_site_proj.js.
jsMean / clayMean / comps are the CLEAN model — TD/K calibration is model
tuning (like SIGMA_CAL), the market anchor never touches them.
Delete the file (or window.SIM_TUNING = null) to fall back to the priors.

Usage: python tune_weekly.py            # all snapshots with actuals
       python tune_weekly.py --dry      # print, don't write
"""
import argparse, glob, json, os, re, time
import numpy as np
from score_week import HERE, norm
from diagnose_week import load_rows, load_k, load_dst

PRIOR_W = 0.70
# Jack 2026-09-29 ("drop the market anchor weight for rb and te"): W1-3 the MAE-best weight was 0
# for RB and TE every week while the slow steps had only reached ~.41 -> their prior drops to .20.
# QB/WR keep .70 (QB best ~.80). W_FLOOR keeps a sliver of market in the shipped mean so lock rows
# still carry propMean and the market stays reconstructable (w = 0 would end the evidence).
PRIOR_W_POS = {"RB": 0.20, "TE": 0.20}
W_FLOOR = 0.10
PRIOR_WEEKS = 4          # shrinkage: prior worth this many weeks of evidence
POS = ("QB", "RB", "WR", "TE")
TD_STATS = {"QB": ("ptd", "rtd"), "RB": ("rtd", "rctd"), "WR": ("rctd",), "TE": ("rctd",)}
TD_CLAMP = (0.70, 1.40)
BELOW_GAP = 3.0          # mirrors engine.js BELOW_GAP / BELOW_STARTER_MIN
BELOW_STARTER_MIN = 8.0
ABOVE_GAP = 1.0          # mirrors engine.js ABOVE_GAP / ABOVE_POS (2026-10-07): clean model >= 1 pt ABOVE the market
ABOVE_POS = ("WR",)      # W1-4: market closer 67% on those WR rows (n=94); RB/TE/QB showed no side
ABOVE_MARKET_MAX = 12.0  # mirrors engine.js: WR1-level markets (>= 12) are exempt (model was closer 5/8 there)
ATD_JUICE_PRIOR = 1.06   # engine PROP_ATD_JUICE (flat devig on anytime-TD implied probability)
ATD_JUICE_POS = ("RB", "WR")  # positions the fitted factor is WRITTEN for (Jack 2026-10-07: RB, then WR); evidence printed for all
ATD_JUICE_CLAMP = (1.0, 1.35)
ATD_BOOKS = ("DK", "FD", "MGM", "UD", "PP")
def atd_raw_p(lines):
    """median raw implied P(anytime TD) across books, juice still in."""
    v = [lines[b]["atd"] for b in ATD_BOOKS if isinstance(lines.get(b), dict) and isinstance(lines[b].get("atd"), (int, float)) and lines[b]["atd"] != 0]
    if not v:
        return None
    o = float(np.median(v))
    return (-o / (-o + 100)) if o < 0 else 100 / (o + 100)
W_GRID = np.round(np.arange(0.0, 1.0001, 0.05), 2)
MIN_PROJ = 5.0
OUT = os.path.join(HERE, "data", "sim_tuning.js")

def collect():
    rows, krows, drows = [], [], []
    for f in sorted(glob.glob(os.path.join(HERE, "data", "snapshots", "simlab_snapshot_w*.json"))):
        wk = int(re.search(r"_w(\d+)\.json$", f).group(1))
        act = load_rows(wk)
        if not act:
            continue
        kact = load_k(wk); dact = load_dst(wk)
        snap = json.load(open(f, encoding="utf-8"))
        for p in snap["players"]:
            tun = p.get("tun") or {}
            if p.get("pos") == "DST":
                a = dact.get((p.get("tm") or "").upper())
                if a is not None and isinstance(p.get("mean"), (int, float)):
                    drows.append({"wk": wk, "act": a, "mean": p["mean"], "p10": p.get("p10"), "p90": p.get("p90"),
                                  "d": tun.get("d") or 0.0, "s": tun.get("s") or 1.0})
                continue
            if p.get("pos") == "K":
                a = kact.get(norm(p["name"]))
                if a is not None and isinstance(p.get("clayMean"), (int, float)) and p["clayMean"] > 0:
                    krows.append({"wk": wk, "act": a, "clay": p["clayMean"], "mean": p["mean"], "p10": p.get("p10"), "p90": p.get("p90"),
                                  "k": tun.get("k") or 1.0, "s": tun.get("s") or 1.0, "src": tun.get("kSrc") or "clay"})
                continue
            if p.get("pos") not in POS or (p.get("mean") or 0) < MIN_PROJ:
                continue
            w = act.get(norm(p["name"]))
            if w is None:
                continue
            rows.append({"wk": wk, "pos": p["pos"], "act": float(w["fpts"]), "stat": w, "comps": p.get("comps") or {},
                         "mean": p["mean"], "js": p.get("jsMean"), "prop": p.get("propMean"), "src": p.get("propSrc"),
                         "p10": p.get("p10"), "p90": p.get("p90"), "atd": atd_raw_p(p.get("lines") or {}),
                         "w": tun.get("wa") or tun.get("w") or PRIOR_W, "s": tun.get("s") or 1.0, "td": tun.get("td") or {}})
    return rows, krows, drows

def shrink(prior, evidence, n_ev, n0):
    return (n0 * prior + n_ev * evidence) / (n0 + n_ev)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry", action="store_true"); a = ap.parse_args()
    rows, krows, drows = collect()
    weeks = sorted(set(r["wk"] for r in rows))
    nweeks = max(1, len(weeks))
    print(f"scored rows: {len(rows)} skill + {len(krows)} K + {len(drows)} DST across weeks {weeks}")
    tuning = {"asOf": time.strftime("%Y-%m-%d"), "weeksScored": weeks, "priorW": PRIOR_W, "priorWeeks": PRIOR_WEEKS,
              "propW": {}, "sigmaMult": {}, "tdMult": {}, "kLevel": 1.0, "dstShift": 0.0, "belowW": PRIOR_W, "aboveW": PRIOR_W, "evidence": {}}
    for pos in POS:
        rs = [r for r in rows if r["pos"] == pos]
        n0 = PRIOR_WEEKS * len(rs) / nweeks
        ev = {"n": len(rs)}
        # --- market weight (market reconstructed with the weight live at lock)
        an = [r for r in rs if r["src"] == "line" and isinstance(r["prop"], (int, float)) and isinstance(r["js"], (int, float))
              and abs(r["prop"] - r["js"]) > 0.05 and 0 < r["w"] <= 1]
        ev["nAnchored"] = len(an)
        prior_w = PRIOR_W_POS.get(pos, PRIOR_W)
        w_new = prior_w
        if len(an) >= 20:
            base = np.array([r["js"] for r in an]); prop = np.array([r["prop"] for r in an]); act = np.array([r["act"] for r in an])
            wl = np.array([r["w"] for r in an])
            market = (prop - (1 - wl) * base) / wl
            maes = [float(np.mean(np.abs((1 - w) * base + w * market - act))) for w in W_GRID]
            w_best = float(W_GRID[int(np.argmin(maes))])
            w_new = max(W_FLOOR, shrink(prior_w, w_best, len(an), n0))
            ev.update({"wBest": w_best, "maeAtPrior": round(maes[int(np.argmin(np.abs(W_GRID - prior_w)))], 3), "maeAtBest": round(min(maes), 3)})
        tuning["propW"][pos] = round(w_new, 3)
        # --- sigma (evidence relative to the width that was live)
        band = [r for r in rs if isinstance(r["p10"], (int, float)) and isinstance(r["p90"], (int, float))]
        m_new = 1.0
        if len(band) >= 20:
            inside = sum(1 for r in band if r["p10"] <= r["act"] <= r["p90"]) / len(band)
            live = float(np.mean([r["s"] for r in band]))
            m_ev = live * (1 + (0.80 - inside))
            m_new = shrink(1.0, m_ev, len(band), n0)
            ev.update({"bandInside": round(inside, 3), "sigmaEvidence": round(m_ev, 3)})
        tuning["sigmaMult"][pos] = round(m_new, 3)
        # --- TD rates (Poisson-honest: prior worth 4 weeks of projected TDs)
        tuning["tdMult"][pos] = {}
        for st in TD_STATS[pos]:
            proj = sum((r["comps"].get(st) or 0) / ((r["td"] or {}).get(st) or 1.0) for r in rs)
            actual = sum((r["stat"].get(st) or 0) for r in rs)
            if proj < 3:
                continue
            t0 = PRIOR_WEEKS * proj / nweeks
            m = (t0 + actual) / (t0 + proj)
            m = min(TD_CLAMP[1], max(TD_CLAMP[0], m))
            tuning["tdMult"][pos][st] = round(m, 3)
            ev[f"td_{st}"] = {"proj": round(proj, 1), "act": round(actual, 1), "ratio": round(actual / proj, 3)}
        tuning["evidence"][pos] = ev
        tds = " ".join(f"{k} x{v:.3f}" for k, v in tuning["tdMult"][pos].items())
        print(f"  {pos}: n={len(rs):3d} anchored={len(an):3d}  propW {prior_w:.2f} -> {w_new:.3f} (best {ev.get('wBest','-')})"
              f"  sigma x{m_new:.3f} (inside {ev.get('bandInside','-')})  TD {tds}")
    # --- kickers: level + sigma
    # 2026-10-08 Clay-free kicker base: once any scored kicker rows carry the 'vegas' base tag, kLevel is fit on THOSE rows only
    # (the Clay-base rows would push a level fit for a different base); the engine applies kLevel to the vegas base only when kBase says so.
    kv = [r for r in krows if r.get("src") == "vegas"]
    if kv: krows = kv; tuning["kBase"] = "vegas"
    else: tuning["kBase"] = "clay"
    kev = {"n": len(krows), "base": tuning["kBase"]}
    if len(krows) >= 15:
        raw = np.array([r["clay"] / (r["k"] or 1.0) for r in krows]); act = np.array([r["act"] for r in krows])   # k = the level actually applied at lock time
        p0 = PRIOR_WEEKS * raw.sum() / nweeks
        k_new = (p0 + act.sum()) / (p0 + raw.sum())
        tuning["kLevel"] = round(float(min(1.3, max(0.7, k_new))), 3)
        kev.update({"projSum": round(float(raw.sum()), 1), "actSum": round(float(act.sum()), 1), "ratio": round(float(act.sum() / raw.sum()), 3)})
        band = [r for r in krows if isinstance(r["p10"], (int, float)) and isinstance(r["p90"], (int, float))]
        if len(band) >= 15:
            inside = sum(1 for r in band if r["p10"] <= r["act"] <= r["p90"]) / len(band)
            live = float(np.mean([r["s"] for r in band]))
            n0 = PRIOR_WEEKS * len(band) / nweeks
            tuning["sigmaMult"]["K"] = round(shrink(1.0, live * (1 + (0.80 - inside)), len(band), n0), 3)
            kev["bandInside"] = round(inside, 3)
    tuning["evidence"]["K"] = kev
    # --- DST: additive level shift (raw = locked mean minus the shift live at lock) + sigma
    dev = {"n": len(drows)}
    if len(drows) >= 15:
        raw = np.array([r["mean"] - r["d"] for r in drows]); act = np.array([r["act"] for r in drows])
        n0 = PRIOR_WEEKS * len(drows) / nweeks
        sh = shrink(0.0, float(np.mean(act - raw)), len(drows), n0)
        tuning["dstShift"] = round(float(min(3.0, max(-3.0, sh))), 3)
        dev.update({"projMean": round(float(raw.mean()), 2), "actMean": round(float(act.mean()), 2), "evidenceShift": round(float(np.mean(act - raw)), 3)})
        band = [r for r in drows if isinstance(r["p10"], (int, float)) and isinstance(r["p90"], (int, float))]
        if len(band) >= 15:
            inside = sum(1 for r in band if r["p10"] <= r["act"] <= r["p90"]) / len(band)
            live = float(np.mean([r["s"] for r in band]))
            tuning["sigmaMult"]["DST"] = round(shrink(1.0, live * (1 + (0.80 - inside)), len(band), n0), 3)
            dev["bandInside"] = round(inside, 3)
    tuning["evidence"]["DST"] = dev
    # --- model-below-market-on-a-starter weight (pooled across positions)
    bl = []
    for r in rows:
        if r["src"] != "line" or not isinstance(r["prop"], (int, float)) or not isinstance(r["js"], (int, float)) or not (0 < r["w"] <= 1):
            continue
        mkt = (r["prop"] - (1 - r["w"]) * r["js"]) / r["w"]
        if mkt - r["js"] >= BELOW_GAP and mkt >= BELOW_STARTER_MIN:
            bl.append((r["js"], mkt, r["act"]))
    bev = {"n": len(bl)}
    if len(bl) >= 10:
        base = np.array([b[0] for b in bl]); mk = np.array([b[1] for b in bl]); ac = np.array([b[2] for b in bl])
        maes = [float(np.mean(np.abs((1 - w) * base + w * mk - ac))) for w in W_GRID]
        w_best = float(W_GRID[int(np.argmin(maes))])
        n0 = PRIOR_WEEKS * len(bl) / nweeks
        tuning["belowW"] = round(float(shrink(PRIOR_W, w_best, len(bl), n0)), 3)
        bev.update({"wBest": w_best, "maeAtPrior": round(maes[int(np.argmin(np.abs(W_GRID - PRIOR_W)))], 3), "maeAtBest": round(min(maes), 3),
                    "modelSide": round(float(np.mean(ac < mk)), 3)})
    tuning["evidence"]["below"] = bev
    print(f"  BELOW-market starters: n={len(bl):3d}  belowW {PRIOR_W:.2f} -> {tuning['belowW']:.3f} (best {bev.get('wBest','-')}, actual under market {bev.get('modelSide','-')})")
    # --- model-ABOVE-market weight (WR only; mirror of belowW, raises the weight)
    al = []
    for r in rows:
        if r["pos"] not in ABOVE_POS or r["src"] != "line" or not isinstance(r["prop"], (int, float)) or not isinstance(r["js"], (int, float)) or not (0 < r["w"] <= 1):
            continue
        mkt = (r["prop"] - (1 - r["w"]) * r["js"]) / r["w"]
        if r["js"] - mkt >= ABOVE_GAP and mkt < ABOVE_MARKET_MAX:
            al.append((r["js"], mkt, r["act"]))
    aev = {"n": len(al), "pos": list(ABOVE_POS)}
    if len(al) >= 10:
        base = np.array([b[0] for b in al]); mk = np.array([b[1] for b in al]); ac = np.array([b[2] for b in al])
        maes = [float(np.mean(np.abs((1 - w) * base + w * mk - ac))) for w in W_GRID]
        w_best = float(W_GRID[int(np.argmin(maes))])
        n0 = PRIOR_WEEKS * len(al) / nweeks
        tuning["aboveW"] = round(float(shrink(PRIOR_W, w_best, len(al), n0)), 3)
        aev.update({"wBest": w_best, "maeAtPrior": round(maes[int(np.argmin(np.abs(W_GRID - PRIOR_W)))], 3), "maeAtBest": round(min(maes), 3),
                    "marketSide": round(float(np.mean(np.abs(mk - ac) < np.abs(base - ac))), 3)})
    tuning["evidence"]["above"] = aev
    print(f"  ABOVE-market {'/'.join(ABOVE_POS)}: n={len(al):3d}  aboveW {PRIOR_W:.2f} -> {tuning['aboveW']:.3f} (best {aev.get('wBest','-')}, market closer {aev.get('marketSide','-')})")
    # --- anytime-TD devig per position: J such that Σ λ(p_raw / J) matches Σ actual rush+rec TDs,
    #     Poisson-honest shrink like tdMult (prior worth PRIOR_WEEKS of projected TDs at the flat 1.06).
    tuning["atdJuice"] = {}
    tuning["evidence"]["atd"] = {}
    for pos in POS:
        rs = [r for r in rows if r["pos"] == pos and isinstance(r["atd"], (int, float))]
        if len(rs) < 20:
            continue
        lam0 = sum(-np.log(1 - min(0.85, max(0.01, r["atd"] / ATD_JUICE_PRIOR))) for r in rs)
        actual = sum((r["stat"].get("rtd") or 0) + (r["stat"].get("rctd") or 0) for r in rs)
        t0 = PRIOR_WEEKS * lam0 / nweeks
        ratio = (t0 + actual) / (t0 + lam0)          # shrunk actual / book-implied TD count
        j = ATD_JUICE_PRIOR / ratio
        j = float(min(ATD_JUICE_CLAMP[1], max(ATD_JUICE_CLAMP[0], j)))
        tuning["evidence"]["atd"][pos] = {"n": len(rs), "lamAt106": round(float(lam0), 1), "act": round(float(actual), 1), "ratio": round(float(actual / lam0), 3), "juiceFit": round(j, 3), "applied": pos in ATD_JUICE_POS}
        if pos in ATD_JUICE_POS:
            tuning["atdJuice"][pos] = round(j, 3)
    print("  ATD devig: " + "  ".join(f"{pos} n={e['n']} act/Σλ {e['ratio']:.2f} -> J {e['juiceFit']:.3f}{'*' if e['applied'] else ''}" for pos, e in tuning["evidence"]["atd"].items()) + "  (* = written)")
    print(f"  DST: n={len(drows):3d}  shift {tuning['dstShift']:+.3f} pts (evidence {dev.get('evidenceShift','-')})  sigma x{tuning['sigmaMult'].get('DST', 1.0):.3f} (inside {dev.get('bandInside','-')})")
    print(f"  K : n={len(krows):3d}  level x{tuning['kLevel']:.3f} (ratio {kev.get('ratio','-')})  sigma x{tuning['sigmaMult'].get('K', 1.0):.3f} (inside {kev.get('bandInside','-')})")
    if a.dry:
        return
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// AUTO-GENERATED by tune_weekly.py (Tuesday chain) - slow weekly knob updates, shrunk to priors\n")
        f.write("// propW = market-anchor weight per position (engine default .70); sigmaMult scales SIGMA_CAL[pos];\n")
        f.write("// tdMult[pos][stat] scales the Clay prior's TD components; kLevel scales kicker prior points.\n")
        f.write("window.SIM_TUNING = " + json.dumps(tuning, separators=(",", ":")) + ";\n")
    print(f"wrote {OUT}")

if __name__ == "__main__":
    main()
