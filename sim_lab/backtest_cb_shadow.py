#!/usr/bin/env python3
"""
Does an ELITE (shadow) CORNERBACK measurably suppress opposing WR fantasy
points, beyond what the team-level layers (Vegas, Clay unit grades, in-season
FPA) already price? 2019-2025.

Design: curated elite/shadow CB-seasons (All-Pro / consensus lockdown reps).
Weekly on/off from nflverse snap counts (defense_pct >= 0.5 = active; a CB
"belongs" to a defense-season after >= 4 active games for that team, so
midseason trades split correctly). Opposing-WR samples come from the same
harness as every other backtest: base = P=5 Clay/PPG blend, act = that week's
fantasy points. Three buckets:

  ACTIVE : opponent defense employs an elite CB and he played that week
  OUT    : same defenses, weeks the CB missed (the causal on/off contrast)
  CONTROL: defenses with no elite CB that season

Reported on raw base AND on base * shipped jsOppMult (in-season WR FPA,
e=0.25, trust min(1,g/8), clamp [0.8,1.25]) — the second answers "is any CB
effect already captured by the FPA layer we ship?". WR1 split = the highest-
base WR of the offense that week (the guy a shadow corner would follow).
"""
import numpy as np
import pandas as pd
import json, os
from collections import defaultdict
from backtest_sim_calibration import (played, weekly_rec, infer_team,
                                      POOL_MIN_PTS, OPP_ALIAS, WEEKLY)
import backtest_sim_calibration as cal

CACHE = r"E:\MyFantasyFootball\pbp_cache"
P = 5
YEARS = range(2019, 2026)

# Consensus elite / shadow corners by season (reputation a projection system
# could have known AT THE TIME — All-Pros and established lockdown reps).
ELITE_CBS = {
    2019: ["Stephon Gilmore", "Tre'Davious White", "Richard Sherman",
           "Marcus Peters", "Marlon Humphrey", "Jalen Ramsey"],
    2020: ["Stephon Gilmore", "Tre'Davious White", "Jalen Ramsey",
           "Xavien Howard", "Jaire Alexander", "Marlon Humphrey"],
    2021: ["Jalen Ramsey", "Trevon Diggs", "J.C. Jackson", "A.J. Terrell",
           "Marshon Lattimore", "Jaire Alexander", "Xavien Howard"],
    2022: ["Sauce Gardner", "Patrick Surtain II", "Jaire Alexander",
           "James Bradberry", "Jalen Ramsey", "Darius Slay"],
    2023: ["Sauce Gardner", "Patrick Surtain II", "DaRon Bland",
           "Charvarius Ward", "Jaylon Johnson", "Denzel Ward", "Jalen Ramsey"],
    2024: ["Patrick Surtain II", "Derek Stingley Jr.", "Sauce Gardner",
           "Jaylon Johnson", "Christian Gonzalez", "Marlon Humphrey"],
    2025: ["Patrick Surtain II", "Derek Stingley Jr.", "Sauce Gardner",
           "Christian Gonzalez", "Quinyon Mitchell", "Jaylon Johnson"],
}

def team_norm(t):
    return OPP_ALIAS.get(t, t)

def load_cb_status():
    """Return active[(Y,def,wk)] = set(cb), out[(Y,def,wk)] = set(cb),
    employs[(Y,def)] = set(cb), plus a per-CB-season log for the table."""
    active = defaultdict(set)
    employs = defaultdict(set)
    team_weeks = defaultdict(set)
    log = []
    for Y in YEARS:
        df = pd.read_parquet(
            os.path.join(CACHE, f"snap_counts_{Y}.parquet"),
            columns=["week", "game_type", "player", "position", "team",
                     "opponent", "defense_pct"])
        df = df[df.game_type == "REG"]
        for t, wk in df[["team", "week"]].drop_duplicates().itertuples(index=False):
            team_weeks[(Y, team_norm(t))].add(int(wk))
        targets = {cal.norm(n): n for n in ELITE_CBS[Y]}
        d = df[df.defense_pct >= 0.5].copy()
        d["nm"] = d.player.map(cal.norm)
        d = d[d.nm.isin(targets)]
        found = set()
        cb_games = defaultdict(list)   # (cb, def) -> [wk]
        for r in d.itertuples(index=False):
            found.add(r.nm)
            cb_games[(targets[r.nm], team_norm(r.team))].append(int(r.week))
        missing = [targets[n] for n in targets if n not in found]
        if missing:
            print(f"  !! {Y}: no defensive snaps matched for {missing}")
        for (cb, tm), wks in cb_games.items():
            if len(wks) < 4:      # cameo stints (trade tails) don't define a defense
                continue
            employs[(Y, tm)].add(cb)
            for wk in wks:
                active[(Y, tm, wk)].add(cb)
            log.append((Y, cb, tm, sorted(wks)))
    out = defaultdict(set)
    for (Y, tm), cbs in employs.items():
        for wk in team_weeks[(Y, tm)]:
            for cb in cbs:
                if cb not in active.get((Y, tm, wk), ()):
                    out[(Y, tm, wk)].add(cb)
    return active, out, employs, log

def build_wr_samples():
    """WR player-weeks with a P=5 blend base, tagged (Y, opp, wk, own team)."""
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"),
                               encoding="utf-8"))
    S = []
    for Y in YEARS:
        if str(Y) not in clay_hist:
            continue
        W = 16 if Y <= 2020 else 17
        for name, c in clay_hist[str(Y)].items():
            if c.get("pos") != "WR" or (c.get("pts") or 0) < POOL_MIN_PTS:
                continue
            wrec = weekly_rec(name, "WR")
            if wrec is None:
                continue
            team = infer_team(wrec, Y)
            rows = sorted([(w["wk"], w["fpts"], OPP_ALIAS.get(w.get("opp"), w.get("opp")))
                           for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            hist = []
            for wk, fpts, opp in rows:
                if hist and opp:
                    g = len(hist)
                    base = (P * clay_pg + g * (sum(hist) / g)) / (P + g)
                    S.append({"Y": Y, "wk": int(wk), "opp": opp, "team": team,
                              "base": base, "act": fpts, "name": name})
                hist.append(fpts)
    # WR1 flag: highest base among same offense same week
    best = {}
    for i, s in enumerate(S):
        if s["team"] is None:
            continue
        k = (s["Y"], s["team"], s["wk"])
        if k not in best or S[best[k]]["base"] < s["base"]:
            best[k] = i
    for i, s in enumerate(S):
        s["wr1"] = (s["team"] is not None and
                    best.get((s["Y"], s["team"], s["wk"])) == i)
    return S

def build_wr_fpa():
    """In-season WR FPA multiplier, exactly the jsOppMult design (e=0.25)."""
    weekly_fpa = defaultdict(dict)
    for recs in WEEKLY.values():
        for rec in recs:
            if rec.get("pos") != "WR":
                continue
            for y, rows in rec.get("seasons", {}).items():
                Y = int(y)
                if Y < 2018:
                    continue
                for w in rows:
                    if played(w) and w.get("opp"):
                        d = OPP_ALIAS.get(w["opp"], w["opp"])
                        wkk = int(w["wk"])
                        weekly_fpa[(Y, d)][wkk] = weekly_fpa[(Y, d)].get(wkk, 0) + (w["fpts"] or 0)
    lg = defaultdict(list)
    for (Y, d), wks in weekly_fpa.items():
        if len(wks) >= 10:
            lg[Y].append(sum(wks.values()) / len(wks))
    lg = {Y: float(np.mean(v)) for Y, v in lg.items()}
    def mult(Y, d, wk):
        cur = weekly_fpa.get((Y, d), {})
        past = [w for w in cur if w < wk]
        if len(past) < 4 or Y not in lg:
            return 1.0
        ratio = min(1.25, max(0.8, (sum(cur[w] for w in past) / len(past)) / lg[Y]))
        return 1 + 0.25 * min(1, len(past) / 8) * (ratio - 1)
    return mult

def ratio(sub, key="base"):
    if not sub:
        return None, 0
    b = sum(s[key] for s in sub)
    a = sum(s["act"] for s in sub)
    return (a / b if b else None), len(sub)

def main():
    print("loading CB on/off from snap counts...")
    active, out, employs, log = load_cb_status()
    print(f"  {sum(len(v) for v in employs.values())} elite CB-defense-seasons\n")
    print("building WR samples...")
    S = build_wr_samples()
    fpa_mult = build_wr_fpa()
    for s in S:
        s["base_fpa"] = s["base"] * fpa_mult(s["Y"], s["opp"], s["wk"])
    print(f"  {len(S)} WR player-weeks\n")

    def bucket(s):
        k = (s["Y"], s["opp"], s["wk"])
        if active.get(k):
            return "ACTIVE"
        if out.get(k):
            return "OUT"
        return "EMPLOYS-?" if employs.get((s["Y"], s["opp"])) else "CONTROL"

    for s in S:
        s["b"] = bucket(s)

    for label, key in (("raw base", "base"), ("base * shipped FPA layer", "base_fpa")):
        print(f"=== act/exp by bucket — {label} ===")
        for b in ("ACTIVE", "OUT", "CONTROL"):
            sub = [s for s in S if s["b"] == b]
            r, n = ratio(sub, key)
            r1, n1 = ratio([s for s in sub if s["wr1"]], key)
            print(f"  {b:8s} all-WR {r:.3f} (n={n:5d})   WR1 {r1:.3f} (n={n1:4d})")
        print()

    # paired within-defense-season: same defense, CB active vs out weeks
    print("=== paired within defense-season (defenses with >=2 OUT weeks sampled) ===")
    pairs = []
    for (Y, tm), cbs in sorted(employs.items()):
        sa = [s for s in S if s["Y"] == Y and s["opp"] == tm and s["b"] == "ACTIVE"]
        so = [s for s in S if s["Y"] == Y and s["opp"] == tm and s["b"] == "OUT"]
        owks = len({(s["wk"]) for s in so})
        if owks < 2:
            continue
        ra, na = ratio(sa); ro, no = ratio(so)
        if ra and ro:
            pairs.append((ra, ro, na, no))
            print(f"  {Y} {tm:4s} {'/'.join(sorted(cbs)):24s} active {ra:.3f} (n={na:3d})  out {ro:.3f} (n={no:3d})")
    if pairs:
        wa = sum(p[2] for p in pairs); wo = sum(p[3] for p in pairs)
        ma = sum(p[0] * p[2] for p in pairs) / wa
        mo = sum(p[1] * p[3] for p in pairs) / wo
        print(f"  POOLED ({len(pairs)} defense-seasons): active {ma:.3f}  out {mo:.3f}  "
              f"-> CB worth {100 * (mo - ma):+.1f}% of a WR week\n")

    # flat dock sweep on ACTIVE weeks (on top of the shipped FPA base)
    print("=== flat WR dock on elite-CB-active weeks, MSE (base*FPA) ===")
    act_s = [s for s in S if s["b"] == "ACTIVE"]
    a = np.array([s["act"] for s in act_s]); b = np.array([s["base_fpa"] for s in act_s])
    line = " "
    for d in (1.00, 0.98, 0.96, 0.94, 0.92, 0.90):
        line += f"  x{d:.2f} {float(np.mean((b * d - a) ** 2)):.3f}"
    print(line)
    a1 = np.array([s["act"] for s in act_s if s["wr1"]])
    b1 = np.array([s["base_fpa"] for s in act_s if s["wr1"]])
    line = "  WR1 only:"
    for d in (1.00, 0.98, 0.96, 0.94, 0.92, 0.90):
        line += f"  x{d:.2f} {float(np.mean((b1 * d - a1) ** 2)):.3f}"
    print(line)

    # per-CB-season table (active ratio only; out shown when sampled)
    print("\n=== per elite-CB-season (opposing all-WR act/base, raw) ===")
    for Y, cb, tm, wks in sorted(log):
        sa = [s for s in S if s["Y"] == Y and s["opp"] == tm
              and cb in active.get((s["Y"], s["opp"], s["wk"]), ())]
        so = [s for s in S if s["Y"] == Y and s["opp"] == tm
              and cb in out.get((s["Y"], s["opp"], s["wk"]), ())]
        ra, na = ratio(sa); ro, no = ratio(so)
        os_ = f"  out {ro:.3f} (n={no:3d})" if ro else ""
        print(f"  {Y} {cb:22s} {tm:4s} {len(wks):2d} gms  active {ra:.3f} (n={na:3d}){os_}")

if __name__ == "__main__":
    main()
