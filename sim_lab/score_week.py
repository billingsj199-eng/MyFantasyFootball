#!/usr/bin/env python3
"""
Weekly model scorecard — the headless twin of the Sim Lab TRACKING tab's
SCORE ritual (which lives in browser localStorage, per device).

Grades the PRE-KICKOFF lock (data/snapshots/simlab_snapshot_w{N}.json,
auto-locked by export_site_proj.js ~75 min before each game) against the
site's actual half-PPR game logs (repo data/weekly_stats_active.js), for:

  mean      shipped weekly mean (prop-anchored in-season)
  jsMean    JS Weekly (Bayesian Clay->actual shrink + live layers)   CLEAN
  clayMean  Clay stack (Clay rate x Vegas x matchup layers)           CLEAN
  propMean  market-anchored mean                                      = mean
  cons      site consensus weekly (Sleeper+ESPN+FP+CBS, 'h')  <- data/weekly_consensus_w{N}.json
  espn / cbs / fp   the individual consensus legs (half-PPR)

Reports MAE / bias / RMSE per model (played players only), by position,
p10-p90 band coverage, head-to-head win counts vs consensus, and the
biggest misses. DNP (locked but no game row) are listed, not scored.

Usage: python score_week.py --week 1 [--min-proj 5]
Copy the week's consensus file BEFORE the 9am job flips it to next week:
  cp "<repo>/data/weekly_projections.json" data/weekly_consensus_w{N}.json
"""
import argparse, json, os, re, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"

def norm(s):
    s = s.lower().replace(".", "").replace("'", "").replace("-", " ")
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()

def load_actuals(week):
    raw = open(os.path.join(REPO, "data", "weekly_stats_active.js"), encoding="utf-8").read()
    d = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    out = {}
    for name, rec in d.items():
        for w in (rec.get("seasons") or {}).get("2026") or []:
            if w.get("wk") == week and isinstance(w.get("fpts"), (int, float)):
                out[norm(name)] = float(w["fpts"])
    return out

def load_consensus(week):
    p = os.path.join(HERE, "data", f"weekly_consensus_w{week}.json")
    if not os.path.exists(p):
        return {}, None
    d = json.load(open(p, encoding="utf-8"))
    if d.get("week") != week:
        print(f"WARN {p} is week {d.get('week')}, not {week} — consensus columns skipped")
        return {}, None
    return {norm(k): v for k, v in d["players"].items()}, d.get("updated")

def stats(pred, act):
    pred, act = np.array(pred, float), np.array(act, float)
    e = pred - act
    return len(e), float(np.mean(np.abs(e))), float(np.mean(e)), float(np.sqrt(np.mean(e ** 2)))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--min-proj", type=float, default=5.0, help="score only locked rows with shipped mean >= this")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()

    snap = json.load(open(os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{a.week}.json"), encoding="utf-8"))
    act = load_actuals(a.week)
    cons, cons_stamp = load_consensus(a.week)
    print(f"W{a.week} lock: {len(snap['players'])} players, {len(snap['lockedGames'])} games, preset {snap.get('preset')}, sims {snap.get('sims')}")
    print(f"actuals: {len(act)} game rows | consensus file: {'yes (' + str(cons_stamp) + ')' if cons else 'NO'}")

    rows, dnp = [], []
    for p in snap["players"]:
        if p.get("pos") not in ("QB", "RB", "WR", "TE"):
            continue
        if (p.get("mean") or 0) < a.min_proj:
            continue
        k = norm(p["name"])
        if k not in act:
            dnp.append((p["name"], p["pos"], p["mean"]))
            continue
        c = cons.get(k) or {}
        rows.append({"name": p["name"], "pos": p["pos"], "tm": p["tm"], "opp": p["opp"], "act": act[k],
                     "mean": p["mean"], "js": p.get("jsMean"), "clay": p.get("clayMean"), "prop": p.get("propMean"),
                     "p10": p.get("p10"), "p90": p.get("p90"), "propSrc": p.get("propSrc"),
                     "cons": c.get("h"), "espn": (c.get("e") or [None])[0], "cbs": (c.get("c") or [None])[0],
                     "fp": (c.get("f") or [None])[0]})
    print(f"scored: {len(rows)} played (shipped mean >= {a.min_proj}) | DNP/unmatched: {len(dnp)}")

    models = [("mean", "SHIPPED mean"), ("js", "JS Weekly"), ("clay", "Clay stack"), ("prop", "prop-anchored"),
              ("cons", "site consensus"), ("espn", "ESPN"), ("cbs", "CBS"), ("fp", "FantasyPros")]
    print("\n=== ALL positions (same rows for every model where available) ===")
    print(f"  {'model':16s} {'n':>4s} {'MAE':>6s} {'bias':>6s} {'RMSE':>6s}")
    for key, lab in models:
        pr = [(r[key], r["act"]) for r in rows if isinstance(r.get(key), (int, float))]
        if len(pr) < 10:
            continue
        n, mae, bias, rmse = stats([x for x, _ in pr], [y for _, y in pr])
        print(f"  {lab:16s} {n:4d} {mae:6.2f} {bias:+6.2f} {rmse:6.2f}")
    print("\n=== by position (MAE) ===")
    hdr = "  pos    n  " + " ".join(f"{k:>6s}" for k, _ in models)
    print(hdr)
    for pos in ("QB", "RB", "WR", "TE"):
        rr = [r for r in rows if r["pos"] == pos]
        if not rr:
            continue
        line = f"  {pos:3s} {len(rr):4d}  "
        for key, _ in models:
            pr = [(r[key], r["act"]) for r in rr if isinstance(r.get(key), (int, float))]
            line += f"{stats([x for x,_ in pr],[y for _,y in pr])[1]:6.2f} " if len(pr) >= 5 else f"{'-':>6s} "
        print(line)

    # head-to-head vs consensus (row-level |err|)
    print("\n=== head-to-head, row-level |error| (wins-losses-ties, tie = within 0.1) ===")
    for key, lab in (("mean", "SHIPPED"), ("js", "JS Weekly"), ("clay", "Clay stack")):
        for okey, olab in (("cons", "consensus"), ("espn", "ESPN")):
            w = l = t = 0
            for r in rows:
                if not isinstance(r.get(key), (int, float)) or not isinstance(r.get(okey), (int, float)):
                    continue
                d = abs(r[key] - r["act"]) - abs(r[okey] - r["act"])
                if d < -0.1: w += 1
                elif d > 0.1: l += 1
                else: t += 1
            if w + l + t:
                print(f"  {lab:10s} vs {olab:10s}: {w}-{l}-{t}  ({100*w/max(1,w+l):.0f}% of decided)")

    # band calibration
    band = [r for r in rows if isinstance(r.get("p10"), (int, float)) and isinstance(r.get("p90"), (int, float))]
    if band:
        below = sum(1 for r in band if r["act"] < r["p10"]); above = sum(1 for r in band if r["act"] > r["p90"])
        print(f"\n=== p10-p90 band (target 80% inside / 10% / 10%) ===\n  n={len(band)} inside {100*(len(band)-below-above)/len(band):.1f}%  below p10 {100*below/len(band):.1f}%  above p90 {100*above/len(band):.1f}%")
        for pos in ("QB", "RB", "WR", "TE"):
            b = [r for r in band if r["pos"] == pos]
            if len(b) >= 8:
                bl = sum(1 for r in b if r["act"] < r["p10"]); ab = sum(1 for r in b if r["act"] > r["p90"])
                print(f"    {pos}: n={len(b)} inside {100*(len(b)-bl-ab)/len(b):.0f}% below {100*bl/len(b):.0f}% above {100*ab/len(b):.0f}%")
    srcs = {}
    for r in rows:
        srcs[r.get("propSrc")] = srcs.get(r.get("propSrc"), 0) + 1
    print(f"  prop anchor source mix: {srcs}")

    print(f"\n=== biggest misses, shipped mean (top {a.top}) ===")
    for r in sorted(rows, key=lambda r: -abs(r["mean"] - r["act"]))[:a.top]:
        print(f"  {r['name']:22s} {r['pos']} {r['tm']:3s} vs {r['opp']:3s}  proj {r['mean']:5.1f}  act {r['act']:5.1f}  "
              f"({r['mean']-r['act']:+5.1f})  js {r['js'] if r['js'] is not None else '-':>5} clay {r['clay'] if r['clay'] is not None else '-':>5} cons {r['cons'] if r['cons'] is not None else '-':>5}")
    if dnp:
        print(f"\n=== locked but no game row ({len(dnp)}) ===")
        print("  " + ", ".join(f"{n} ({p} {m:.1f})" for n, p, m in sorted(dnp, key=lambda x: -x[2])[:20]))

if __name__ == "__main__":
    main()
