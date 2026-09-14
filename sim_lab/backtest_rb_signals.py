#!/usr/bin/env python3
"""
Closing the RB gap: which RB-specific signals predict how a back beats or
misses the 3-yr recency core the FOLLOWING season? (2019-2025)

Candidates (all from Y-1 or knowable at Y's draft):
  tdoe        TD over expected — actual rush+rec TDs minus xTD built from
              red-zone/goal-line carries and RZ targets (rates fit on the
              pooled sample). RB scoring is TD-heavy and TDs are the noisiest
              component; the classic finding is RZ USAGE persists while TD
              CONVERSION does not, so a back who scored well above his usage
              should regress.
  burden      carries in Y-1 (the "workload cliff" question)
  age         age in Y (RBs are supposed to fall off a cliff)
  draftcomp   team drafted an RB in the top 100 of Y's draft (dilution — the
              mirror image of the shipped rookie-room layer)
  recshare    his share of team TARGETS in Y-1 (pass-game role = PPR floor
              and is supposedly stickier than early-down work)
  rzshare     his share of the team's inside-10 carries in Y-1

Each: correlation with the log residual, tercile means, and a LOYO MAE test
applying it as a centered multiplier (the same protocol that shipped the
mover / TE-route layers and rejected the PFF efficiency metrics).
"""
import numpy as np
import pandas as pd
import os, re
from collections import defaultdict
from backtest_sim_calibration import played, WEEKLY, infer_team, POS_KEEP
import backtest_sim_calibration as cal

CACHE = r"E:\MyFantasyFootball\pbp_cache"
W3 = [0.5, 0.3, 0.2]
YEARS = range(2019, 2026)
PFR_TEAM = {"NWE": "NE", "GNB": "GB", "KAN": "KC", "NOR": "NO", "SFO": "SF",
            "TAM": "TB", "LVR": "LV", "SDG": "LAC", "OAK": "LV", "STL": "LAR"}
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS"}

def rows_of(rec, Y):
    return [w for w in rec.get("seasons", {}).get(str(Y), []) if played(w)]

def ppg_of(rec, Y):
    pts = [w["fpts"] for w in rows_of(rec, Y) if isinstance(w.get("fpts"), (int, float))]
    return (sum(pts) / len(pts), len(pts)) if pts else (None, 0)

def abbrev(name):
    """pbp uses 'J.Cook' style — build that key from a full name."""
    parts = [p for p in str(name).replace(".", " ").split() if p]
    if len(parts) < 2:
        return None
    return cal.norm(parts[0][0] + "." + parts[-1])

def redzone(year):
    """per player: inside-20/inside-10 carries, RZ targets, and team totals."""
    cols = ["season_type", "posteam", "rush_attempt", "pass_attempt", "yardline_100",
            "rusher_player_name", "receiver_player_name", "complete_pass"]
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{year}.csv.gz"),
                     usecols=cols, low_memory=False)
    df = df[(df.season_type == "REG") & df.yardline_100.notna()]
    rz = df[df.yardline_100 <= 20]
    i10 = df[df.yardline_100 <= 10]
    out = defaultdict(lambda: {"rz_car": 0, "i10_car": 0, "rz_tgt": 0})
    team = defaultdict(lambda: {"rz_car": 0, "i10_car": 0, "rz_tgt": 0})
    for d, key in ((rz, "rz_car"), (i10, "i10_car")):
        g = d[d.rush_attempt == 1].dropna(subset=["rusher_player_name", "posteam"])
        for (nm, tm), n in g.groupby(["rusher_player_name", "posteam"]).size().items():
            out[(cal.norm(str(nm)), ALIAS.get(tm, tm))][key] += int(n)
        for tm, n in g.posteam.value_counts().items():
            team[ALIAS.get(tm, tm)][key] += int(n)
    g = rz[rz.pass_attempt == 1].dropna(subset=["receiver_player_name", "posteam"])
    for (nm, tm), n in g.groupby(["receiver_player_name", "posteam"]).size().items():
        out[(cal.norm(str(nm)), ALIAS.get(tm, tm))]["rz_tgt"] += int(n)
    for tm, n in g.posteam.value_counts().items():
        team[ALIAS.get(tm, tm)]["rz_tgt"] += int(n)
    return out, team

def main():
    dp = pd.read_parquet(os.path.join(CACHE, "draft_picks.parquet"),
                         columns=["season", "pick", "position", "team"])
    dp = dp[(dp.position == "RB") & (dp.pick <= 100)]
    drafted = defaultdict(set)
    for _, r in dp.iterrows():
        drafted[int(r.season)].add(PFR_TEAM.get(r.team, r.team))

    rzs = {}
    for y in range(2018, 2026):
        if os.path.exists(os.path.join(CACHE, f"play_by_play_{y}.csv.gz")):
            rzs[y] = redzone(y)
            print(f"  rz {y} ok")

    # team target pools for recshare
    pool = defaultdict(float)
    per = {}
    for nk, lst in WEEKLY.items():
        for rec in lst:
            if rec.get("pos") not in POS_KEEP:
                continue
            for Ys in rec.get("seasons", {}):
                Y = int(Ys)
                rws = rows_of(rec, Y)
                if not rws:
                    continue
                t = infer_team(rec, Y)
                tg = sum(w.get("tgt") or 0 for w in rws)
                car = sum(w.get("ra") or 0 for w in rws)
                td = sum((w.get("rtd") or 0) + (w.get("rctd") or 0) for w in rws)
                per[(id(rec), Y)] = {"team": t, "tgt": tg, "car": car, "td": td, "g": len(rws)}
                if t:
                    pool[(t, Y)] += tg

    rows = []
    for nk, lst in WEEKLY.items():
        for rec in lst:
            if rec.get("pos") != "RB":
                continue
            for Y in YEARS:
                act, g = ppg_of(rec, Y)
                if act is None or g < 6:
                    continue
                n = d_ = 0.0
                for i, yy in enumerate((Y - 1, Y - 2, Y - 3)):
                    p, gg = ppg_of(rec, yy)
                    if p is not None and gg >= 4:
                        n += W3[i] * p; d_ += W3[i]
                if d_ == 0:
                    continue
                core = n / d_
                if core < 3:
                    continue
                prev = per.get((id(rec), Y - 1))
                if not prev or prev["g"] < 6:
                    continue
                rz = rzs.get(Y - 1)
                s = {"Y": Y, "core": core, "act": act, "resid": np.log(max(0.2, act) / core),
                     "burden": prev["car"], "td": prev["td"],
                     "recshare": (prev["tgt"] / pool[(prev["team"], Y - 1)]) if prev["team"] and pool.get((prev["team"], Y - 1)) else None,
                     "draftcomp": 1.0 if (per.get((id(rec), Y)) and per[(id(rec), Y)]["team"] in drafted.get(Y, set())) else 0.0}
                if rz:
                    pr = rz[0].get((abbrev(rec.get("name") or nk), prev["team"])) if prev["team"] else None
                    tt = rz[1].get(prev["team"]) if prev["team"] else None
                    if pr:
                        s["rz_car"], s["i10_car"], s["rz_tgt"] = pr["rz_car"], pr["i10_car"], pr["rz_tgt"]
                        if tt and tt["i10_car"] > 20:
                            s["rzshare"] = pr["i10_car"] / tt["i10_car"]
                rows.append(s)
    df = pd.DataFrame(rows)
    # xTD from RZ usage (pooled fit), then TD over expected
    sub = df.dropna(subset=["rz_car"])
    A = np.c_[sub.rz_car, sub.i10_car, sub.rz_tgt]
    coef, *_ = np.linalg.lstsq(A, sub.td.values, rcond=None)
    df["xtd"] = df.rz_car * coef[0] + df.i10_car * coef[1] + df.rz_tgt * coef[2]
    df["tdoe"] = df.td - df.xtd
    print(f"\n{len(df)} RB seasons; xTD coefs rz_car {coef[0]:.3f} i10_car {coef[1]:.3f} rz_tgt {coef[2]:.3f}")

    def report(sig, label):
        sel = df.dropna(subset=[sig])
        if len(sel) < 60:
            print(f"  {label}: n={len(sel)} too few"); return
        x = sel[sig].astype(float).values
        r = float(np.corrcoef(x, sel.resid.values)[0, 1])
        q = np.quantile(x, [0.33, 0.67])
        lo = sel[x <= q[0]].resid.mean(); mid = sel[(x > q[0]) & (x <= q[1])].resid.mean(); hi = sel[x > q[1]].resid.mean()
        eb, em = [], []
        for Y in YEARS:
            tr, te = sel[sel.Y != Y], sel[sel.Y == Y]
            if len(te) < 5 or len(tr) < 40:
                continue
            b = np.polyfit(tr[sig].astype(float), tr.resid, 1)[0]
            mu = tr[sig].astype(float).mean()
            for _, t in te.iterrows():
                pred = t.core * np.exp(np.clip(b * (float(t[sig]) - mu), -0.2, 0.2))
                em.append(abs(pred - t.act)); eb.append(abs(t.core - t.act))
        d = (np.mean(em) - np.mean(eb)) / np.mean(eb) * 100 if eb else 0
        flag = "  <== HELPS" if d < -0.5 else ("  (hurts)" if d > 0.5 else "  (flat)")
        print(f"  {label:<12} corr {r:+.3f}  terciles {np.exp(lo):.3f}/{np.exp(mid):.3f}/{np.exp(hi):.3f}  "
              f"MAE {np.mean(eb):.3f}->{np.mean(em):.3f} ({d:+.2f}%)  n={len(sel)}{flag}")

    print("\n=== RB signals: does Y-1 predict the Y residual? ===")
    for sig, lab in [("tdoe", "TD over exp"), ("td", "raw TDs"), ("burden", "carries"),
                     ("recshare", "target share"), ("rzshare", "i10 share"),
                     ("rz_car", "RZ carries")]:
        report(sig, lab)
    print("\n=== draft competition (team drafted RB top-100 in Y) ===")
    for v, lab in [(0.0, "no RB drafted"), (1.0, "RB drafted top-100")]:
        sel = df[df.draftcomp == v]
        print(f"  {lab:<22} mean resid {np.exp(sel.resid.mean()):.3f}  (n={len(sel)})")

if __name__ == "__main__":
    main()
