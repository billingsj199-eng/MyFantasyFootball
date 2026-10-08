#!/usr/bin/env python3
"""
NEXT MAN UP (Jack 2026-10-08: "run tests on how the next man up produces when top targets are out - if target 1 is out how
does 2 or 3 get better, if target 2 is out does target 1 fill in or target 3; this is most likely impacted by matchups (do
worse players get a much larger boost in easier matchups) and how good the missing targets are (vacated share)").

Weekly DB 2019-25. Pass catchers (WR / TE / RB) ranked 1..N on the team by trailing target share (last 3 team games, 2+ played).
Event = a team-week where a trailing pass catcher with share >= .10 has no row (not traded). For every healthy teammate with a
trailing baseline: change in targets and receiving points vs his own trailing average, the share of the vacated targets he took.
  1  who absorbs: absent rank x teammate's ORIGINAL rank (one absence), and the engine's read (rank among the healthy)
  2  two absences (ranks 1+2, 1+3, 2+3)
  3  vacated size: absent share .10-.17 / .17-.24 / .24+
  4  matchup: opponent receiving points allowed to date (terciles), event vs no-event weeks (difference in differences)
  5  the WIRED model (honest shadow replica, vacated pool at .75 inside it): actual / shadow for the absorbers by cell, vs the same
     ranks in no-absence weeks - where the current rule over- or under-pays.
Log next_man_up.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_sim_calibration as cal
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "next_man_up.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()

YEARS = range(2019, 2026); TRAIL = 3; SH_MIN = 0.10
TM_ALIAS = {"ARZ": "ARI", "WSH": "WAS", "JAC": "JAX", "LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "HST": "HOU", "BLT": "BAL", "CLV": "CLE"}
rpts = lambda w: (w.get("rec") or 0) * 0.5 + (w.get("rcy") or 0) * 0.1 + (w.get("rctd") or 0) * 6
nz = lambda s: str(s).lower().replace(".", "").replace("'", "").replace("-", " ").strip()


def build(Y):
    rows = defaultdict(list); teams_of = defaultdict(set)
    for nm, lst in cal.WEEKLY.items():
        for rec in lst:
            pos = rec.get("pos")
            if pos not in ("WR", "TE", "RB"): continue
            inferred = None
            for w in rec.get("seasons", {}).get(str(Y), []):
                if not cal.played(w): continue
                tm = w.get("tm"); tm = TM_ALIAS.get(tm, tm) if tm else None
                if not tm:
                    if inferred is None: inferred = cal.infer_team(rec, Y) or ""
                    tm = TM_ALIAS.get(inferred, inferred)
                if not tm: continue
                opp = w.get("opp"); opp = str(opp or "").replace("@", "").replace("vs", "").strip().upper(); opp = TM_ALIAS.get(opp, opp)
                rows[(tm, int(w["wk"]))].append({"n": nm, "pos": pos, "tgt": float(w.get("tgt") or 0), "rp": rpts(w), "opp": opp, "key": (nm, pos)})
                teams_of[(nm, pos)].add((tm, int(w["wk"])))
    return rows, teams_of


def events():
    E = []      # absorber rows: dict
    CTRL = []   # no-absence rows (same construction) for the matchup baseline / model control
    for Y in YEARS:
        rows, teams_of = build(Y)
        tw = defaultdict(list)
        for (tm, wk) in rows: tw[tm].append(wk)
        # opponent receiving points allowed per game to date (WR+TE+RB receiving half-PPR), by (opp, wk)
        allowed = defaultdict(list)   # opp -> [(wk, pts)]
        for (tm, wk), lst in rows.items():
            if lst: allowed[lst[0]["opp"]].append((wk, sum(r["rp"] for r in lst)))
        def opp_allow(opp, wk):
            v = [p for w, p in allowed.get(opp, []) if w < wk]
            return np.mean(v) if len(v) >= 3 else np.nan
        for tm, wks in tw.items():
            wks.sort()
            for i, wk in enumerate(wks):
                if i < TRAIL: continue
                prev = wks[i - TRAIL:i]
                cur = {r["key"]: r for r in rows[(tm, wk)]}
                if not cur: continue
                trail = {}
                for pw in prev:
                    for r in rows[(tm, pw)]:
                        t = trail.setdefault(r["key"], {"g": 0, "tgt": 0.0, "rp": 0.0, "pos": r["pos"], "n": r["n"]})
                        t["g"] += 1; t["tgt"] += r["tgt"]; t["rp"] += r["rp"]
                trail = {k: v for k, v in trail.items() if v["g"] >= 2}
                for v in trail.values(): v["tgt"] /= v["g"]; v["rp"] /= v["g"]
                team_tgt = sum(sum(r["tgt"] for r in rows[(tm, pw)]) for pw in prev) / TRAIL
                if team_tgt < 20: continue
                order = sorted(trail.items(), key=lambda kv: -kv[1]["tgt"])
                rank = {k: j + 1 for j, (k, v) in enumerate(order)}
                share = {k: v["tgt"] / team_tgt for k, v in trail.items()}
                absent = []
                for k, v in trail.items():
                    if k in cur or share[k] < SH_MIN: continue
                    if any(t2 != tm and w2 > wk for (t2, w2) in teams_of[k]): continue   # traded / moved
                    absent.append(k)
                opp = next(iter(cur.values()))["opp"]; oa = opp_allow(opp, wk)
                healthy = [k for k in trail if k in cur]
                # rank among the healthy (the engine's read)
                hord = sorted(healthy, key=lambda k: -trail[k]["tgt"]); hrank = {k: j + 1 for j, k in enumerate(hord)}
                vac = sum(trail[k]["tgt"] for k in absent)
                for k in healthy:
                    r = cur[k]; t = trail[k]
                    row = {"Y": Y, "wk": wk, "tm": tm, "n": t["n"], "pos": t["pos"], "rank": rank[k], "hrank": hrank[k], "share": share[k],
                           "dt": r["tgt"] - t["tgt"], "dp": r["rp"] - t["rp"], "tr_rp": t["rp"], "tr_tgt": t["tgt"], "absRp": sum(trail[a]["rp"] for a in absent), "hshare": t["tgt"] / max(1e-9, sum(trail[h]["tgt"] for h in healthy)), "rp": r["rp"], "oa": oa, "vac": vac, "teamTgt": team_tgt,
                           "abs": tuple(sorted(rank[a] for a in absent)), "absShare": tuple(share[a] for a in sorted(absent, key=lambda a: rank[a])), "absPos": tuple(trail[a]["pos"] for a in sorted(absent, key=lambda a: rank[a]))}
                    (E if absent else CTRL).append(row)
    return E, CTRL


def main():
    E, CTRL = events()
    P(f"=== NEXT MAN UP: {len(E):,} teammate rows in absence weeks, {len(CTRL):,} in normal weeks (2019-25, pass catchers ranked by trailing target share) ===")
    ctrl_dp = defaultdict(list); ctrl_dt = defaultdict(list)
    for r in CTRL:
        if r["rank"] <= 5: ctrl_dp[r["rank"]].append(r["dp"]); ctrl_dt[r["rank"]].append(r["dt"])
    P("  normal weeks (regression to trailing avg) by rank: " + " | ".join(f"#{k} dTgt {np.mean(ctrl_dt[k]):+.2f} dPts {np.mean(ctrl_dp[k]):+.2f}" for k in sorted(ctrl_dp)))
    cdt = {k: np.mean(v) for k, v in ctrl_dt.items()}; cdp = {k: np.mean(ctrl_dp[k]) for k in ctrl_dp}

    P("\n--- 1  ONE ABSENCE: absent rank x teammate's ORIGINAL rank - extra targets / extra half-PPR receiving pts vs normal weeks (n), % of vacated targets taken ---")
    one = [r for r in E if len(r["abs"]) == 1]
    for a in (1, 2, 3, 4):
        cells = []
        rows_a = [r for r in one if r["abs"][0] == a]
        if not rows_a: continue
        for k in range(1, 7):
            if k == a: continue
            rr = [r for r in rows_a if r["rank"] == k]
            if len(rr) < 25: continue
            et = np.mean([r["dt"] for r in rr]) - cdt.get(k, 0); ep = np.mean([r["dp"] for r in rr]) - cdp.get(k, 0)
            take = np.mean([(r["dt"] - cdt.get(k, 0)) / max(r["vac"], 1) for r in rr])
            cells.append(f"#{k}: +{et:.2f} tgt +{ep:.2f} pts {100*take:.0f}% (n{len(rr)})")
        P(f"  target #{a} out (vacated {np.mean([r['vac'] for r in rows_a if r['rank'] == (2 if a == 1 else 1)] or [0]):.1f} tgt/g): " + " | ".join(cells))
    P("  by position of the absorber (target #1 out): " + " | ".join(f"{ps} #{k}: +{np.mean([r['dt'] for r in one if r['abs'][0] == 1 and r['rank'] == k and r['pos'] == ps]) - cdt.get(k, 0):.2f} tgt (n{len([r for r in one if r['abs'][0] == 1 and r['rank'] == k and r['pos'] == ps])})" for ps in ("WR", "TE", "RB") for k in (2, 3, 4) if len([r for r in one if r['abs'][0] == 1 and r['rank'] == k and r['pos'] == ps]) >= 25))
    P("  same-position vs other-position absorber (WR out): " + " | ".join(f"{lab}: +{np.mean([r['dt'] - cdt.get(r['rank'], 0) for r in rr]):.2f} tgt (n{len(rr)})" for lab, rr in (("WR teammates", [r for r in one if r["absPos"][0] == "WR" and r["pos"] == "WR"]), ("TE", [r for r in one if r["absPos"][0] == "WR" and r["pos"] == "TE"]), ("RB", [r for r in one if r["absPos"][0] == "WR" and r["pos"] == "RB"]))))

    P("\n--- 2  TWO ABSENCES: extra targets by the teammate's original rank ---")
    two = [r for r in E if len(r["abs"]) == 2]
    for combo in ((1, 2), (1, 3), (2, 3)):
        rr0 = [r for r in two if r["abs"] == combo]
        if len(rr0) < 30: continue
        cells = []
        for k in range(1, 7):
            if k in combo: continue
            rr = [r for r in rr0 if r["rank"] == k]
            if len(rr) < 12: continue
            cells.append(f"#{k}: +{np.mean([r['dt'] for r in rr]) - cdt.get(k, 0):.2f} tgt +{np.mean([r['dp'] for r in rr]) - cdp.get(k, 0):.2f} pts (n{len(rr)})")
        P(f"  #{combo[0]} + #{combo[1]} out: " + " | ".join(cells))
    P("  vs one absence for the same teammate: when #1 AND #2 are out, #3's gain vs #1-only out = " + (lambda a, b: f"{a:.2f} vs {b:.2f} tgt")(np.mean([r['dt'] for r in two if r['abs'] == (1, 2) and r['rank'] == 3] or [np.nan]) - cdt.get(3, 0), np.mean([r['dt'] for r in one if r['abs'] == (1,) and r['rank'] == 3] or [np.nan]) - cdt.get(3, 0)))

    P("\n--- 3  VACATED SIZE (one absence): extra targets for the next two pass catchers by the absent player's trailing share ---")
    for lo, hi in ((0.10, 0.17), (0.17, 0.24), (0.24, 1.0)):
        rr0 = [r for r in one if lo <= r["absShare"][0] < hi]
        next2 = [r for r in rr0 if r["rank"] <= 3]
        P(f"  share {lo:.2f}-{hi:.2f} (n events-rows {len(rr0)}): all healthy +{np.mean([r['dt'] - cdt.get(r['rank'], 0) for r in rr0]):.2f} tgt each, top-3 healthy +{np.mean([r['dt'] - cdt.get(r['rank'], 0) for r in next2]):.2f} tgt +{np.mean([r['dp'] - cdp.get(r['rank'], 0) for r in next2]):.2f} pts | team absorbs {100*np.mean([sum(x['dt'] - cdt.get(x['rank'], 0) for x in rr0 if (x['Y'], x['wk'], x['tm']) == ev) / max(1, [x for x in rr0 if (x['Y'], x['wk'], x['tm']) == ev][0]['vac']) for ev in list({(x['Y'], x['wk'], x['tm']) for x in rr0})[:400]]):.0f}% of vacated targets")

    P("\n--- 4  MATCHUP: receiving pts allowed by the opponent to date (terciles) - do fill-ins gain more in easy matchups? ---")
    oa_all = np.array([r["oa"] for r in CTRL + E if not np.isnan(r["oa"])]); q1, q2 = np.percentile(oa_all, [33.3, 66.7])
    terc = lambda v: "hard" if v < q1 else ("easy" if v > q2 else "mid")
    for lab, sel in (("depth receivers (orig rank 2-4) when #1 is out", lambda r: len(r["abs"]) == 1 and r["abs"][0] == 1 and 2 <= r["rank"] <= 4),
                     ("depth receivers (orig rank 3-5) when #1 or #2 is out", lambda r: len(r["abs"]) == 1 and r["abs"][0] <= 2 and 3 <= r["rank"] <= 5)):
        cells = []
        for t in ("hard", "mid", "easy"):
            ev = [r for r in E if not np.isnan(r["oa"]) and terc(r["oa"]) == t and sel(r)]
            base = [r for r in CTRL if not np.isnan(r["oa"]) and terc(r["oa"]) == t and (2 <= r["rank"] <= 5)]
            bmap = defaultdict(list)
            for r in base: bmap[r["rank"]].append(r["dp"])
            ex = np.mean([r["dp"] - np.mean(bmap[r["rank"]]) for r in ev]) if ev else np.nan
            cells.append(f"{t}: +{ex:.2f} pts over same-matchup normal weeks (n{len(ev)}; normal-week {np.mean([r['dp'] for r in base]):+.2f})")
        P(f"  {lab}: " + " | ".join(cells))
    P("  read: if the 'easy' gain is clearly bigger than 'hard', the boost interacts with matchup; else the matchup effect is the same as for anyone")

    # ---- 5  the wired model
    try:
        import backtest_base_remeasure as BR
        SN = BR.SN; X = SN.setup(); n = X["n"]; act, year, wk, pos, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["adp"], X["name"]
        finw = np.where(year <= 2020, 17, 18); final = wk == finw
        TODAY, LV = BR.live_today(X); SH, _ = BR.shadow_current(X)
        idx = {(nz(name[i]), int(year[i]), int(wk[i])): i for i in range(n)}
        def resid(rows_):
            ii = [idx.get((nz(r["n"]), r["Y"], r["wk"])) for r in rows_]; ii = [i for i in ii if i is not None and not final[i] and SH[i] >= 3]
            return (act[ii].sum() / SH[ii].sum(), len(ii)) if ii else (np.nan, 0)
        P("\n--- 5  WIRED MODEL (shadow replica incl. the vacated pool): actual / projection for teammates, absence weeks vs normal weeks ---")
        for k in (1, 2, 3, 4):
            c = resid([r for r in CTRL if r["rank"] == k])
            P(f"  normal weeks, rank #{k}: {c[0]:.3f} (n{c[1]})")
        for a in (1, 2, 3):
            cells = []
            for k in range(1, 6):
                if k == a: continue
                c = resid([r for r in one if r["abs"][0] == a and r["rank"] == k])
                if c[1] >= 25: cells.append(f"#{k} {c[0]:.3f} (n{c[1]})")
            P(f"  #{a} out: " + " | ".join(cells))
        for combo in ((1, 2), (1, 3), (2, 3)):
            cells = []
            for k in range(1, 6):
                if k in combo: continue
                c = resid([r for r in two if r["abs"] == combo and r["rank"] == k])
                if c[1] >= 12: cells.append(f"#{k} {c[0]:.3f} (n{c[1]})")
            if cells: P(f"  #{combo[0]}+#{combo[1]} out: " + " | ".join(cells))
        for lo, hi in ((0.10, 0.17), (0.17, 0.24), (0.24, 1.0)):
            c = resid([r for r in one if lo <= r["absShare"][0] < hi and r["rank"] <= 4])
            P(f"  vacated share {lo:.2f}-{hi:.2f}, absorbers ranked 1-4: {c[0]:.3f} (n{c[1]})")
        for t in ("hard", "mid", "easy"):
            c = resid([r for r in one if not np.isnan(r["oa"]) and terc(r["oa"]) == t and r["rank"] <= 5]); c0 = resid([r for r in CTRL if not np.isnan(r["oa"]) and terc(r["oa"]) == t and r["rank"] <= 5])
            P(f"  matchup {t}: absorbers {c[0]:.3f} (n{c[1]}) vs normal weeks {c0[0]:.3f} (n{c0[1]})")
        P("  by season, absorbers (ranks 2-4 when #1 out): " + " ".join(f"{y}:{resid([r for r in one if r['Y'] == y and r['abs'][0] == 1 and 2 <= r['rank'] <= 4])[0]:.3f}" for y in YEARS))
    except Exception as e:
        P(f"\n(model section failed: {e})")
    P("\nLimitations: trailing 3-game ranks; receiving points only (half PPR); RB pass-catching counted as a pass catcher; absences inferred from missing rows (not traded).")
    LOG.close()


if __name__ == "__main__":
    main()
