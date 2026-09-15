#!/usr/bin/env python3
"""
ASCENDING / DESCENDING ROLE CHANGE backtest (2026-09-15).

Jack: "identify ascending and descending players - if a player's career average is 6 points on 50% of snaps
but in the last 10 games he averages 12 PPG on 85% of snaps, that more recent sample should be way more
accurate, especially if it is not due to an injury to a player in front of him on the depth chart."

Cross-season windows per player-week (bt_common samples 2019-25, RB / WR / TE), from the weekly DB (points)
and nflverse snap counts (share, team, position):
  recent   his last 10 played games before this week (any season), >= 6 with snap data
  career   his played games in the 3 prior seasons BEFORE the recent window, >= 8 with snap data
  jump     recent snap share - career snap share (points of snap %), recent PPG / career PPG
  vacated  a recent game counts as vacated when a same-position teammate who was AHEAD of him in the career
           window (avg snap share >= max(50, his + 10)) sat that game but played for the team again later
           (temporary absence = injury). A teammate who never played for the team again = departure =
           organic opening. vac_frac = vacated games / recent games; organic = vac_frac < .3
Base: bt_common shipped (P=5 blend of the preseason prior + season-to-date PPG, x Vegas x FPA) x the
shipped snap trend (base2).
  buckets   ASCENDING (snap jump >= +20 and PPG x1.5+) and DESCENDING (<= -20 and x0.67 or less), each
            organic vs vacated: actual / base2 and REL vs the position
  T1 blend  (1-w) base2 + w x recent-10 PPG x Vegas x FPA x snap trend, all rows / organic rows only
  T2 flags  base2 x m on ascending-organic, ascending-vacated, descending rows
  T3 level  base2 x clip(1 + k x z(snap jump)), organic rows only
Ship bar: <= -0.3% LOYO MSE with >= 5/7 years better. Log role_change_backtest.log;
results -> data/role_change_backtest.js (SIM_ROLECHG_BT), ZONES tab.
"""
import json, os, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B
from bt_common import iter_samples, to_arrays
from backtest_target_area import mse
import backtest_sim_calibration as cal

LOG = open(os.path.join(HERE, "role_change_backtest.log"), "w", encoding="utf-8")


class _Tee:
    def __init__(self, a, b): self.a, self.b = a, b
    def write(self, t): self.a.write(t); self.b.write(t); self.a.flush(); self.b.flush()
    def flush(self): self.a.flush(); self.b.flush()


sys.stdout = _Tee(sys.stdout, LOG)
def P(*a): print(" ".join(str(x) for x in a))

YEARS = list(range(2019, 2026))
SNAP_YEARS = list(range(2019, 2026))
SKILL = ("RB", "WR", "TE")
SNAP_W = [0.5, 0.3, 0.2]
SHIP_PCT, SHIP_WINS = -0.30, 5
RES = {"loyo": [], "buckets": [], "examples": [], "n": 0}


def loyo2(S, years, grid, predfn, label, family, pos):
    act = S["act"]; per = {}
    ys = [y for y in years if (S["year"] == y).any()]
    for v in grid:
        pred = predfn(v)
        per[v] = {y: mse(pred[S["year"] == y], act[S["year"] == y]) for y in ys}
    ship = per[grid[0]]; tot = n = wins = 0; picks = []
    for y in ys:
        m = S["year"] == y
        best = min(grid, key=lambda v: sum(per[v][yy] for yy in ys if yy != y))
        picks.append(best); e = mse(predfn(best)[m], act[m])
        tot += e * m.sum(); n += m.sum(); wins += e < ship[y]
    pooled_best = min(grid, key=lambda v: sum(per[v].values()))
    base_mse = sum(ship[y] * (S["year"] == y).sum() for y in ys) / n
    pct = (tot / n / base_mse - 1) * 100
    P(f"  {label}")
    P("    grid pooled MSE: " + "  ".join(f"{v:+.2f}:{sum(per[v].values())/len(ys):.3f}" for v in grid))
    P(f"    pooled best {pooled_best:+.2f} | LOYO MSE {tot/n:.4f} vs base {base_mse:.4f} ({pct:+.2f}%), years better {wins}/{len(ys)}, picks {picks}")
    RES["loyo"].append({"label": label, "family": family, "pos": pos, "n": int(n), "best": float(pooled_best), "pct": round(pct, 3),
                        "wins": int(wins), "years": len(ys), "picks": [float(p) for p in picks],
                        "verdict": "PASS" if (pct <= SHIP_PCT and wins >= SHIP_WINS) else ("lean" if (pct <= -0.1 and wins >= 4) else "FAIL")})


def load_snaps():
    """snap[(norm, Y, wk)] = (pct, team, pos); roster[(team, Y, wk)] = {pos: {norm: pct}}; seq[(team, norm)] = sorted (Y, wk)"""
    snap, roster, seq = {}, defaultdict(lambda: defaultdict(dict)), defaultdict(list)
    for Y in SNAP_YEARS:
        d = pd.read_parquet(os.path.join(B.CACHE, f"snap_counts_{Y}.parquet"),
                            columns=["week", "game_type", "player", "position", "team", "offense_snaps", "offense_pct"])
        d = d[(d.game_type == "REG") & d.position.isin(SKILL) & (d.offense_snaps > 0)]
        for r in d.itertuples(index=False):
            nk, tm, wk = B.cal.norm(str(r.player)), B.tm(str(r.team)), int(r.week)
            pct = 100.0 * float(r.offense_pct)
            snap[(nk, Y, wk)] = (pct, tm, r.position)
            roster[(tm, Y, wk)][r.position][nk] = pct
            seq[(tm, nk)].append((Y, wk))
    for k in seq:
        seq[k].sort()
    return snap, roster, seq


def snap_mult(snap, nk, Y, W):
    past = sorted([wk for wk in range(1, W) if (nk, Y, wk) in snap], reverse=True)
    if len(past) < 2 or past[0] < W - 3:
        return 1.0
    vals = {wk: snap[(nk, Y, wk)][0] for wk in past}
    rec = sum(vals[w] * SNAP_W[i] for i, w in enumerate(past[:3])) / sum(SNAP_W[:len(past[:3])])
    return min(1.30, max(0.75, 1 + (rec - float(np.mean(list(vals.values())))) / 100.0))


def main():
    P("loading snap counts 2019-2025 ...")
    snap, roster, seq = load_snaps()
    P(f"  {len(snap)} skill player-weeks with snaps")
    S = iter_samples(("QB", "RB", "WR", "TE"))
    A = to_arrays(S); n = len(S)
    act, ship, pos = A["act"], A["shipped"], A["pos"]
    sm = np.ones(n)
    F = {k: np.full(n, np.nan) for k in ("rec_ppg", "rec_snap", "car_ppg", "car_snap", "jump_snap", "jump_ppg", "vac_frac")}
    for i, s in enumerate(S):
        Y, W, p = s["year"], s["wk"], s["pos"]
        nk = B.cal.norm(s["name"])
        sm[i] = snap_mult(snap, nk, Y, W)
        if p not in SKILL:
            continue
        rec = cal.weekly_rec(s["name"], p)
        if not rec:
            continue
        hist = []
        for yy in range(Y - 3, Y + 1):
            for r in rec.get("seasons", {}).get(str(yy), []):
                if not cal.played(r) or not isinstance(r.get("fpts"), (int, float)) or not str(r.get("wk", "")).isdigit():
                    continue
                wk = int(r["wk"])
                if yy == Y and wk >= W:
                    continue
                sn = snap.get((nk, yy, wk))
                hist.append((yy, wk, float(r["fpts"]), sn))
        hist.sort(key=lambda t: (t[0], t[1]))
        recent = hist[-10:]; career = hist[:-10]
        rs = [h for h in recent if h[3]]; cs = [h for h in career if h[3]]
        if len(rs) < 6 or len(cs) < 8:
            continue
        rp = float(np.mean([h[2] for h in recent])); cp = float(np.mean([h[2] for h in career]))
        rsn = float(np.mean([h[3][0] for h in rs])); csn = float(np.mean([h[3][0] for h in cs]))
        # teammates ahead of him in the career window (same position, same team at the time)
        mate = defaultdict(list)
        for yy, wk, _, sn in cs:
            for nk2, pct2 in roster[(sn[1], yy, wk)].get(p, {}).items():
                if nk2 != nk:
                    mate[(sn[1], nk2)].append(pct2)
        ahead = {k for k, v in mate.items() if len(v) >= 4 and np.mean(v) >= max(50.0, csn + 10.0)}
        vac = 0
        for yy, wk, _, sn in rs:
            tm = sn[1]
            for (tm2, nk2) in ahead:
                if tm2 != tm or nk2 in roster[(tm, yy, wk)].get(p, {}):
                    continue
                later = [g for g in seq.get((tm, nk2), []) if g > (yy, wk) and g < (Y, W)]
                if later:                      # sat, then played for the team again = temporary (injury)
                    vac += 1
                    break
        F["rec_ppg"][i] = rp; F["car_ppg"][i] = cp; F["rec_snap"][i] = rsn; F["car_snap"][i] = csn
        F["jump_snap"][i] = rsn - csn; F["jump_ppg"][i] = rp / max(cp, 2.0); F["vac_frac"][i] = vac / len(rs)
    base2 = ship * sm
    have = np.isfinite(F["jump_snap"])
    RES["n"] = int(n)
    P(f"  {n} player-weeks; role windows on {int(have.sum())} RB/WR/TE rows")

    asc = have & (F["jump_snap"] >= 20) & (F["jump_ppg"] >= 1.5)
    dsc = have & (F["jump_snap"] <= -20) & (F["jump_ppg"] <= 0.67)
    org = have & (F["vac_frac"] < 0.3)
    vacd = have & (F["vac_frac"] >= 0.5)

    def ratio(m):
        return float(act[m].sum() / base2[m].sum()) if m.sum() else None

    P("\n=== buckets: actual / base2 (REL = / all feature rows of the position) ===")
    for p in SKILL:
        pm = (pos == p) & have
        ref = ratio(pm)
        for lab, mk in (("ASCENDING organic", asc & org), ("ASCENDING, teammate ahead was hurt", asc & vacd),
                        ("DESCENDING organic", dsc & org), ("DESCENDING, while a teammate was hurt", dsc & vacd),
                        ("steady (snap jump within +-10)", have & (np.abs(F["jump_snap"]) <= 10))):
            m = pm & mk
            if m.sum() < 20:
                P(f"  {p} {lab:40s} n {int(m.sum())} (too few)"); continue
            r = ratio(m)
            P(f"  {p} {lab:40s} n {int(m.sum()):5d}  actual/base2 {r:.3f}  REL {r / ref:.3f}  | recent PPG {np.nanmean(F['rec_ppg'][m]):.1f} vs career {np.nanmean(F['car_ppg'][m]):.1f}, actual {act[m].mean():.1f}, base2 {base2[m].mean():.1f}")
            RES["buckets"].append({"pos": p, "name": lab, "n": int(m.sum()), "ratio": round(r, 3), "rel": round(r / ref, 3),
                                   "recPpg": round(float(np.nanmean(F["rec_ppg"][m])), 1), "carPpg": round(float(np.nanmean(F["car_ppg"][m])), 1),
                                   "act": round(float(act[m].mean()), 1), "proj": round(float(base2[m].mean()), 1)})
    ex = [(S[i]["name"], S[i]["year"], S[i]["wk"], F["car_ppg"][i], F["car_snap"][i], F["rec_ppg"][i], F["rec_snap"][i], base2[i], act[i], F["vac_frac"][i])
          for i in np.where(asc & org & (pos == "WR"))[0][:6]]
    RES["examples"] = [{"name": e[0], "year": int(e[1]), "wk": int(e[2]), "car": [round(e[3], 1), round(e[4])], "rec": [round(e[5], 1), round(e[6])], "proj": round(e[7], 1), "act": round(e[8], 1)} for e in ex]
    for e in RES["examples"]:
        P(f"  e.g. {e['name']} {e['year']} wk{e['wk']}: career {e['car'][0]} PPG on {e['car'][1]}% -> last 10 {e['rec'][0]} on {e['rec'][1]}%; projected {e['proj']}, scored {e['act']}")

    years = YEARS
    P("\n=== T1 recency blend: (1-w) base2 + w x recent-10 PPG x Vegas x FPA x snap trend ===")
    for p in SKILL:
        pm = pos == p
        Ssub = {"year": A["year"][pm], "act": act[pm]}; b2 = base2[pm]
        u_all = F["rec_ppg"][pm] * A["veg"][pm] * A["fpa"][pm] * sm[pm]
        for lab, mk in (("all rows", have[pm]), ("organic rows only", (have & org)[pm]), ("ascending or descending organic only", ((asc | dsc) & org)[pm])):
            u = np.where(mk & np.isfinite(u_all), u_all, b2)
            loyo2(Ssub, years, [0.0, 0.1, 0.2, 0.3, 0.5, 0.75], lambda w, u=u, b2=b2: (1 - w) * b2 + w * u, f"{p} recency blend, {lab} (rows {int(mk.sum())})", "blend w", f"{p} recency {lab}")

    P("\n=== T2 flag multipliers ===")
    fgrid = [1.0, 1.03, 1.06, 1.10, 1.15, 0.97, 0.94, 0.90, 0.85]
    for p in SKILL:
        pm = pos == p
        Ssub = {"year": A["year"][pm], "act": act[pm]}; b2 = base2[pm]
        for lab, mk in (("ascending organic", (asc & org)[pm]), ("ascending, teammate hurt", (asc & vacd)[pm]),
                        ("descending organic", (dsc & org)[pm]), ("descending, teammate hurt", (dsc & vacd)[pm])):
            if mk.sum() < 60:
                P(f"  {p} {lab}: too few rows ({int(mk.sum())})"); continue
            loyo2(Ssub, years, fgrid, lambda m_, mk=mk, b2=b2: np.where(mk, b2 * m_, b2), f"{p} {lab} (flagged n={int(mk.sum())})", "flag x m", f"{p} {lab}")

    P("\n=== T3 snap-jump level on organic rows: base2 x clip(1 + k x z) ===")
    for p in SKILL:
        pm = pos == p
        Ssub = {"year": A["year"][pm], "act": act[pm]}; b2 = base2[pm]
        v = F["jump_snap"][pm]; ok = (have & org)[pm]
        if ok.sum() < 300:
            continue
        z = np.zeros(pm.sum()); z[ok] = np.clip((v[ok] - v[ok].mean()) / (v[ok].std() or 1.0), -3, 3)
        loyo2(Ssub, years, [0.0, 0.01, 0.02, 0.04, 0.06, -0.01, -0.02], lambda k, z=z, b2=b2: b2 * np.clip(1 + k * z, 0.8, 1.25), f"{p} snap jump level (organic rows {int(ok.sum())})", "level (1 + k z)", f"{p} snap jump")

    RES["updated"] = time.strftime("%Y-%m-%d %H:%M"); RES["years"] = YEARS; RES["bar"] = {"pct": SHIP_PCT, "wins": SHIP_WINS}
    passed = [r for r in RES["loyo"] if r["verdict"] == "PASS"]
    RES["summary"] = (f"Role change: {len(RES['loyo'])} LOYO tests on {n} player-weeks 2019-25; " +
                      (f"{len(passed)} pass: " + "; ".join(f"{r['pos']} {r['pct']:+.2f}% ({r['wins']}/7)" for r in passed) if passed else "none pass the ship bar"))
    with open(os.path.join(HERE, "data", "role_change_backtest.js"), "w", encoding="utf-8") as fh:
        fh.write("// built by backtest_role_change.py - ascending / descending players (last 10 games vs career window, organic vs teammate injury); shown on the ZONES tab\n")
        fh.write("window.SIM_ROLECHG_BT = "); json.dump(RES, fh, separators=(",", ":")); fh.write(";\n")
    P(f"\nwrote data/role_change_backtest.js: {RES['summary']}")
    P("done")


if __name__ == "__main__":
    main()
