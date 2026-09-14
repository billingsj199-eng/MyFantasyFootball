#!/usr/bin/env python3
"""
VACATED OPPORTUNITY POOL — where do a missing player's targets / carries go?
(Jack, 2026-09-11: replace the flat "60% of his fantasy points to his position
group" vacated-share rule with a team opportunity-pool constraint, Clay-style.)

Data: the site's weekly DB (active + retired, 2019-2025, tgt / ra per game).
Event = a team-week where EXACTLY ONE player with a meaningful trailing share
(>= TGT_SHARE_MIN of team targets, or >= CAR_SHARE_MIN of team carries over
his last 3 played games) has no row while the team played, and he was not
traded (no later row with another team that season).

For each event we measure, in stat units and in half-PPR points:
  retention   team targets / carries this week vs the team's trailing 3-game avg
  absorption  sum of (this week - trailing) over healthy players WITH a trailing
              baseline, split same-position / other-position, as a share of the
              vacated volume V
  efficiency  absorbers' points per target (per carry) this week vs their own
              trailing rate, weighted by absorbed volume
  points test the current engine constant: points gained by the same-position
              group / the absent player's trailing points (engine says 0.60)
  depth       absorption by trailing-share rank inside the same-position group
QB-out section: team targets retention + healthy receivers' pts/target ratio
when the trailing passing leader (>= 60% of team attempts) is absent.
"""
import sys, json
from collections import defaultdict
import backtest_sim_calibration as cal

SEASONS = range(2019, 2026)
TRAIL = 3
TGT_SHARE_MIN = 0.12
CAR_SHARE_MIN = 0.30
POS = ("RB", "WR", "TE")
TM_ALIAS = {"ARZ": "ARI", "WSH": "WAS", "JAC": "JAX", "LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR",
            "HST": "HOU", "BLT": "BAL", "CLV": "CLE"}

def hpts(w):
    return (w.get("rec") or 0) * 0.5 + (w.get("rcy") or 0) * 0.1 + (w.get("rctd") or 0) * 6
def cpts(w):
    return (w.get("ry") or 0) * 0.1 + (w.get("rtd") or 0) * 6

def build(season):
    """rows[(team, wk)] -> list of dict(norm,pos,tgt,ra,rp,cp,pa)"""
    rows = defaultdict(list)
    for nm, lst in cal.WEEKLY.items():
        for rec in lst:
            pos = rec.get("pos")
            if pos not in ("QB", "RB", "WR", "TE"):
                continue
            wks = [w for w in rec.get("seasons", {}).get(str(season), []) if cal.played(w)]
            if not wks:
                continue
            inferred = None
            for w in wks:
                tm = w.get("tm")
                tm = TM_ALIAS.get(tm, tm) if tm else None
                if not tm:
                    if inferred is None:
                        inferred = cal.infer_team(rec, season) or ""
                    tm = inferred
                if not tm:
                    continue
                rows[(tm, int(w["wk"]))].append({
                    "n": nm, "pos": pos, "tgt": w.get("tgt") or 0, "ra": w.get("ra") or 0,
                    "rp": hpts(w), "cp": cpts(w), "pa": w.get("pa") or 0,
                    "seen": (nm, pos)})
    return rows

def team_weeks(rows):
    tw = defaultdict(list)
    for (tm, wk) in rows:
        tw[tm].append(wk)
    for tm in tw:
        tw[tm].sort()
    return tw

def main():
    agg = defaultdict(lambda: defaultdict(float))   # by absent pos -> sums
    depth = defaultdict(lambda: defaultdict(float))  # (pos, rank) -> [absorbed, V]
    qb = defaultdict(float)
    n_events = defaultdict(int)
    for Y in SEASONS:
        rows = build(Y)
        tw = team_weeks(rows)
        for tm, wks in tw.items():
            for i, wk in enumerate(wks):
                if i < TRAIL:
                    continue
                prev = wks[i - TRAIL:i]
                cur = {r["seen"]: r for r in rows[(tm, wk)]}
                # trailing per player (>= 2 of the last 3 team games)
                trail = {}
                for pw in prev:
                    for r in rows[(tm, pw)]:
                        t = trail.setdefault(r["seen"], {"g": 0, "tgt": 0.0, "ra": 0.0, "rp": 0.0, "cp": 0.0, "pa": 0.0, "pos": r["pos"], "n": r["n"]})
                        t["g"] += 1
                        for k in ("tgt", "ra", "rp", "cp", "pa"):
                            t[k] += r[k]
                trail = {k: v for k, v in trail.items() if v["g"] >= 2}
                for v in trail.values():
                    for k in ("tgt", "ra", "rp", "cp", "pa"):
                        v[k] /= v["g"]
                team_tgt_tr = sum(sum(r["tgt"] for r in rows[(tm, pw)]) for pw in prev) / TRAIL
                team_car_tr = sum(sum(r["ra"] for r in rows[(tm, pw)]) for pw in prev) / TRAIL
                team_pa_tr = sum(sum(r["pa"] for r in rows[(tm, pw)]) for pw in prev) / TRAIL
                if team_tgt_tr < 15 or team_car_tr < 10:
                    continue
                # absent = trailing player with no row this week, not traded
                absent = []
                later_other = set()
                for key, v in trail.items():
                    if key in cur:
                        continue
                    # traded / released? any later row this season on another team
                    moved = False
                    for (tm2, wk2), lst in rows.items():
                        if tm2 != tm and wk2 > wk and any(r["seen"] == key for r in lst):
                            moved = True
                            break
                    if moved:
                        continue
                    absent.append((key, v))
                team_tgt = sum(r["tgt"] for r in cur.values())
                team_car = sum(r["ra"] for r in cur.values())
                # ---- QB-out section ----
                qb_abs = [(k, v) for k, v in absent if v["pos"] == "QB" and team_pa_tr > 0 and v["pa"] / team_pa_tr >= 0.6]
                if len(qb_abs) == 1 and not [1 for k, v in absent if v["pos"] != "QB" and (v["tgt"] / team_tgt_tr >= TGT_SHARE_MIN or v["ra"] / team_car_tr >= CAR_SHARE_MIN)]:
                    qb["n"] += 1
                    qb["tgt_tr"] += team_tgt_tr; qb["tgt"] += team_tgt
                    qb["car_tr"] += team_car_tr; qb["car"] += team_car
                    for key, v in trail.items():
                        if v["pos"] in POS and key in cur and v["tgt"] >= 2:
                            r = cur[key]
                            qb["abs_tgt"] += r["tgt"]; qb["abs_rp"] += r["rp"]
                            qb["abs_exp_rp"] += r["tgt"] * (v["rp"] / v["tgt"])
                    continue
                skill_abs = [(k, v) for k, v in absent if v["pos"] in POS and (v["tgt"] / team_tgt_tr >= TGT_SHARE_MIN or v["ra"] / team_car_tr >= CAR_SHARE_MIN)]
                if len(skill_abs) != 1:
                    continue
                if any(v["pos"] == "QB" and v["pa"] / max(1, team_pa_tr) >= 0.6 for k, v in absent):
                    continue  # QB also out — different regime
                key, va = skill_abs[0]
                # LEAD = he was the team's top target-getter (any position) over the trailing window
                lead = va["tgt"] >= max(v["tgt"] for v in trail.values())
                apos = va["pos"] + ("_lead" if lead else "_sec")
                a = agg[apos]
                n_events[apos] += 1
                Vt, Vc = va["tgt"], va["ra"]
                a["Vt"] += Vt; a["Vc"] += Vc; a["Vrp"] += va["rp"]; a["Vcp"] += va["cp"]
                a["team_tgt_tr"] += team_tgt_tr; a["team_tgt"] += team_tgt
                a["team_car_tr"] += team_car_tr; a["team_car"] += team_car
                # healthy absorbers with a trailing baseline
                same = []
                for k2, v in trail.items():
                    if k2 == key or k2 not in cur or v["pos"] not in POS + ("QB",):
                        continue
                    r = cur[k2]
                    grp = "same" if v["pos"] == va["pos"] else "other"
                    dt, dc = r["tgt"] - v["tgt"], r["ra"] - v["ra"]
                    a[grp + "_dt"] += dt; a[grp + "_dc"] += dc
                    a[grp + "_drp"] += r["rp"] - v["rp"]; a[grp + "_dcp"] += r["cp"] - v["cp"]
                    # efficiency of the ADDED targets: actual rp vs expected at trailing rate
                    if dt > 0 and v["tgt"] >= 1:
                        a[grp + "_eff_act"] += r["rp"]; a[grp + "_eff_exp"] += r["tgt"] * (v["rp"] / v["tgt"]); a[grp + "_eff_w"] += dt
                    if dc > 0 and v["ra"] >= 1:
                        a[grp + "_ceff_act"] += r["cp"]; a[grp + "_ceff_exp"] += r["ra"] * (v["cp"] / v["ra"]); a[grp + "_ceff_w"] += dc
                    if grp == "same":
                        same.append((v["tgt"] + v["ra"], dt, dc, v["tgt"], v["ra"]))
                # new bodies (no trailing baseline) this week
                for k2, r in cur.items():
                    if k2 not in trail and r["pos"] in POS:
                        a["new_tgt"] += r["tgt"]; a["new_ra"] += r["ra"]
                same.sort(reverse=True)
                for rank, (lvl, dt, dc, bt, bc) in enumerate(same[:3]):
                    d = depth[(apos, rank + 1)]
                    d["dt"] += dt; d["dc"] += dc; d["Vt"] += Vt; d["Vc"] += Vc; d["bt"] += bt; d["bc"] += bc; d["n"] += 1
    # ---- report ----
    out = {}
    print("VACATED OPPORTUNITY POOL  (2019-2025, half-PPR, one qualifying absence per team-week)")
    for apos in sorted(agg.keys()):
        a = agg[apos]; n = n_events[apos]
        if not n:
            continue
        Vt, Vc = a["Vt"], a["Vc"]
        print(f"\n=== absent {apos}: {n} events | vacated per game: {Vt/n:.1f} tgt, {Vc/n:.1f} car, {a['Vrp']/n:.1f} rec pts, {a['Vcp']/n:.1f} rush pts")
        print(f"  team targets  trailing {a['team_tgt_tr']/n:.1f} -> {a['team_tgt']/n:.1f}  (retention of vacated: {(a['team_tgt']-a['team_tgt_tr']+Vt)/max(1,Vt):.2f})")
        print(f"  team carries  trailing {a['team_car_tr']/n:.1f} -> {a['team_car']/n:.1f}  (retention of vacated: {(a['team_car']-a['team_car_tr']+Vc)/max(1,Vc):.2f})")
        print(f"  targets absorbed: same-pos {a['same_dt']/max(1,Vt):+.2f}  other-pos {a['other_dt']/max(1,Vt):+.2f}  new bodies {a['new_tgt']/max(1,Vt):+.2f}   (of vacated targets)")
        print(f"  carries absorbed: same-pos {a['same_dc']/max(1,Vc):+.2f}  other-pos {a['other_dc']/max(1,Vc):+.2f}  new bodies {a['new_ra']/max(1,Vc):+.2f}   (of vacated carries)")
        se = a["same_eff_act"] / a["same_eff_exp"] if a["same_eff_exp"] else float("nan")
        oe = a["other_eff_act"] / a["other_eff_exp"] if a["other_eff_exp"] else float("nan")
        sce = a["same_ceff_act"] / a["same_ceff_exp"] if a["same_ceff_exp"] else float("nan")
        print(f"  efficiency of absorbers (pts/target this wk vs own trailing): same {se:.2f}  other {oe:.2f} | pts/carry same {sce:.2f}")
        print(f"  POINTS test vs engine 0.60: same-pos rec+rush pts gained / absent pts = {(a['same_drp']+a['same_dcp'])/max(1,a['Vrp']+a['Vcp']):+.2f}   other-pos {(a['other_drp']+a['other_dcp'])/max(1,a['Vrp']+a['Vcp']):+.2f}")
        for rank in (1, 2, 3):
            d = depth[(apos, rank)]
            if d["n"]:
                print(f"    same-pos #{rank} healthy (by trailing volume, n={int(d['n'])}): baseline {d['bt']/d['n']:.1f} tgt {d['bc']/d['n']:.1f} car -> absorbs {d['dt']/max(1,d['Vt']):+.2f} of vacated tgt, {d['dc']/max(1,d['Vc']):+.2f} of vacated car")
        out[apos] = {"n": n, "tgt_retention": (a['team_tgt']-a['team_tgt_tr']+Vt)/max(1,Vt), "car_retention": (a['team_car']-a['team_car_tr']+Vc)/max(1,Vc),
                     "tgt_same": a['same_dt']/max(1,Vt), "tgt_other": a['other_dt']/max(1,Vt), "car_same": a['same_dc']/max(1,Vc), "car_other": a['other_dc']/max(1,Vc),
                     "eff_same": se, "eff_other": oe, "pts_same": (a['same_drp']+a['same_dcp'])/max(1,a['Vrp']+a['Vcp']), "pts_other": (a['other_drp']+a['other_dcp'])/max(1,a['Vrp']+a['Vcp'])}
    n = qb["n"]
    if n:
        print(f"\n=== starting QB absent: {int(n)} events")
        print(f"  team targets trailing {qb['tgt_tr']/n:.1f} -> {qb['tgt']/n:.1f} ({qb['tgt']/qb['tgt_tr']:.2f}) | carries {qb['car_tr']/n:.1f} -> {qb['car']/n:.1f} ({qb['car']/qb['car_tr']:.2f})")
        print(f"  healthy receivers' rec pts vs expected at own trailing pts/target: {qb['abs_rp']/qb['abs_exp_rp']:.2f}")
        out["QB"] = {"n": int(n), "tgt_ratio": qb['tgt']/qb['tgt_tr'], "car_ratio": qb['car']/qb['car_tr'], "rec_eff": qb['abs_rp']/qb['abs_exp_rp']}
    json.dump(out, open("data/vacated_pool_backtest.json", "w"), indent=1)
    print("\nwrote data/vacated_pool_backtest.json")

if __name__ == "__main__":
    main()
