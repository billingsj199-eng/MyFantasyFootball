#!/usr/bin/env python3
"""
The whole-board test: every shipped layer, graded in the currency the board
actually ranks in — SEASON fantasy points (not per-game rate).

Why this exists: backtest_combined_layers.py grades PPG on veterans with 3
years of history, so it structurally cannot see the two newest layers —
the rookie no-Clay discount (rookies have no history and are excluded) and
the availability/Clay-games layer (a games adjustment, invisible to a
per-game metric). This pools BOTH populations and grades season points, so
"never played" and "missed 6 games" count as the failures they are.

  VETERANS (3-yr history)
    base      core PPG x 17
    +VS       volume x share blend (30/70, RB/WR/TE)
    +MOVER    contract-tiered team-change discount
    +TEROUTE  TE route-participation mean reversion
    +AVAIL    Clay gm<=13 -> half-way blend (17+gm)/2 games   [SHIPPED]
    +SHRINK   core shrunk toward CLAY's positional mean       [SHIPPED]
              (QB/RB down-only, WR/TE symmetric — engine config mirrored)
  ROOKIES (drafted, no history)
    base      round-bucket mean season points
    +NOCLAY   x0.15 when Clay's guide omits him               [SHIPPED]
    +ROOM     team returning-share room multiplier

LOYO by season throughout.
"""
import numpy as np
import pandas as pd
import json, os, re
from collections import defaultdict
from backtest_sim_calibration import (played, WEEKLY, infer_team, POS_KEEP,
                                      SCHEDULES, CHANGES)
import backtest_sim_calibration as cal

CACHE = r"E:\MyFantasyFootball\pbp_cache"
REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"
PFF = os.path.join(CACHE, "pff")
W3 = [0.5, 0.3, 0.2]
VS_POS = ("RB", "WR", "TE")
K_SAME, K_NEW = 0.60, 0.35
MOVER_TIER = {"big": 1.0, "mid": 0.95, "cheap": 0.86, "unknown": 0.94}
EFF_SHRINK = {"RB": 1.0, "WR": 0.5, "TE": 0.5}
VS_W, EXP_BUMP = 0.30, 1.10
TE_SLOPE, TE_MEAN, TE_CLAMP = -0.00657, 85.56, 0.10
# SHIPPED config (engine.js _JS_SHRINK_K / _JS_SHRINK_DIR)
SHRINK_K = {"QB": 0.80, "RB": 0.85, "WR": 0.90, "TE": 0.90}
SHRINK_DIR = {"QB": "down", "RB": "down", "WR": "both", "TE": "both"}
NOCLAY_MULT = 0.15
PFR_TEAM = {"NWE": "NE", "GNB": "GB", "KAN": "KC", "NOR": "NO", "SFO": "SF",
            "TAM": "TB", "LVR": "LV", "SDG": "LAC", "OAK": "LV", "STL": "LAR"}

def rows_of(rec, Y):
    return [w for w in rec.get("seasons", {}).get(str(Y), []) if played(w)]

def main():
    clay_raw = json.load(open(os.path.join(REPO, "data", "clay_history.json"), encoding="utf-8"))
    clay = {int(y): {cal.norm(n): v for n, v in ps.items()} for y, ps in clay_raw.items()}
    con = pd.read_parquet(os.path.join(CACHE, "historical_contracts.parquet"),
                          columns=["player", "year_signed", "apy_cap_pct", "date_of_birth"])
    con["norm"] = con.player.map(cal.norm)
    deals = defaultdict(list)
    for _, r in con.dropna(subset=["apy_cap_pct"]).iterrows():
        deals[(r["norm"], int(r.year_signed))].append(float(r.apy_cap_pct))
    born = {}
    for _, r in con.dropna(subset=["date_of_birth"]).iterrows():
        m = re.search(r"(\d{4})", str(r.date_of_birth))
        if m:
            born[r["norm"]] = int(m.group(1))
    te_route = {}
    for y in range(2018, 2026):
        p = os.path.join(PFF, f"pff_receiving_{y}.csv")
        if os.path.exists(p):
            df = pd.read_csv(p)
            for _, r in df[df.position == "TE"].iterrows():
                if (r.get("routes") or 0) >= 100 and pd.notna(r.get("route_rate")):
                    te_route[(cal.norm(r.player), y)] = float(r.route_rate)

    recs = [(nk, rec) for nk, lst in WEEKLY.items() for rec in lst if rec.get("pos") in POS_KEEP]
    P, team_pool, first_seen = {}, defaultdict(lambda: [0.0, 0.0]), {}
    for nk, rec in recs:
        for Ys in rec.get("seasons", {}):
            Y = int(Ys)
            first_seen[id(rec)] = min(first_seen.get(id(rec), 9999), Y)
            rws = rows_of(rec, Y)
            if not rws:
                continue
            t = infer_team(rec, Y)
            f = [w["fpts"] for w in rws if isinstance(w.get("fpts"), (int, float))]
            d = {"team": t, "tgt": sum(w.get("tgt") or 0 for w in rws),
                 "car": sum(w.get("ra") or 0 for w in rws),
                 "rpts": sum((w.get("rec") or 0)*.5 + (w.get("rcy") or 0)*.1 + (w.get("rctd") or 0)*6 for w in rws),
                 "cpts": sum((w.get("ry") or 0)*.1 + (w.get("rtd") or 0)*6 for w in rws),
                 "g": len(rws), "ppg": (sum(f)/len(f)) if f else None, "season": sum(f)}
            P[(id(rec), Y)] = d
            if t:
                team_pool[(t, Y)][0] += d["tgt"]; team_pool[(t, Y)][1] += d["car"]

    def games(t, Y):
        return len(SCHEDULES.get(Y, {}).get(t, {})) or (16 if Y <= 2020 else 17)

    lg_vol, eff_lg = {}, defaultdict(lambda: [0.0]*4)
    for Y in range(2016, 2026):
        ts = [(v[0]/games(t, Y), v[1]/games(t, Y)) for (t, yy), v in team_pool.items() if yy == Y]
        if ts:
            lg_vol[Y] = (float(np.mean([a for a,_ in ts])), float(np.mean([b for _,b in ts])))
    pos_of = {id(rec): rec.get("pos") for nk, rec in recs}
    for (rid, Y), d in P.items():
        e = eff_lg[(pos_of[rid], Y)]
        e[0]+=d["rpts"]; e[1]+=d["tgt"]; e[2]+=d["cpts"]; e[3]+=d["car"]
    def lg_eff(pos, Y):
        r=[0.0]*4
        for yy in (Y-1, Y-2, Y-3):
            e = eff_lg.get((pos, yy))
            if e:
                for i in range(4): r[i]+=e[i]
        return (r[0]/max(1,r[1]), r[2]/max(1,r[3]))

    V = []
    for Y in range(2019, 2026):
        lgm = lg_vol.get(Y-1)
        W = 16 if Y <= 2020 else 17
        for nk, rec in recs:
            pos = rec["pos"]
            cur = P.get((id(rec), Y))
            if not cur or cur["ppg"] is None or cur["g"] < 6:
                continue
            sh_t=sh_c=shw=cn=cd=0.0; ept=[0.0,0.0]; epc=[0.0,0.0]
            for i, yy in enumerate((Y-1, Y-2, Y-3)):
                d = P.get((id(rec), yy))
                if not d or d["g"] < 4: continue
                tp = team_pool.get((d["team"], yy)) if d["team"] else None
                if tp and tp[0] > 200:
                    sh_t += W3[i]*(d["tgt"]/tp[0]); sh_c += W3[i]*(d["car"]/max(1,tp[1])); shw += W3[i]
                ept[0]+=d["rpts"]; ept[1]+=d["tgt"]; epc[0]+=d["cpts"]; epc[1]+=d["car"]
                if d["ppg"] is not None: cn += W3[i]*d["ppg"]; cd += W3[i]
            if cd == 0: continue
            core = cn/cd
            if core < 3: continue
            c = clay.get(Y, {}).get(nk)
            V.append({"Y": Y, "pos": pos, "nk": nk, "core": core, "W": W,
                      "actual": cur["season"], "team": cur["team"], "rec": rec,
                      "shw": shw, "sh_t": sh_t, "sh_c": sh_c, "ept": ept, "epc": epc,
                      "clay_gm": (c or {}).get("gm"),
                      "te_rr": te_route.get((nk, Y-1)),
                      "prev_team": (P.get((id(rec), Y-1)) or {}).get("team"),
                      "exp": Y - first_seen.get(id(rec), Y),
                      "age": (Y - born[nk]) if nk in born else None})
        print(f"  {Y} vets done")

    def layers(v, use_shrink, mean_core):
        core, pos, Y = v["core"], v["pos"], v["Y"]
        base = core
        if use_shrink and mean_core is not None:
            if SHRINK_DIR[pos] == "both" or core > mean_core:
                base = mean_core + SHRINK_K[pos]*(core - mean_core)
        out = base
        if pos in VS_POS and v["shw"] > 0 and v["team"]:
            s_t, s_c = v["sh_t"]/v["shw"], v["sh_c"]/v["shw"]
            pv = team_pool.get((v["team"], Y-1)); lgm = lg_vol.get(Y-1)
            if pv and lgm:
                k = K_NEW if v["team"] in CHANGES.get(Y, set()) else K_SAME
                gpv = games(v["team"], Y-1)
                tv = (lgm[0]+k*(pv[0]/gpv-lgm[0]), lgm[1]+k*(pv[1]/gpv-lgm[1]))
            else:
                tv = lgm or (33.0, 26.0)
            mult = 1.0
            if v["prev_team"] and v["prev_team"] != v["team"]:
                ds = deals.get((v["nk"], Y)) or deals.get((v["nk"], Y-1))
                cap = max(ds) if ds else None
                mult = MOVER_TIER["unknown" if cap is None else ("big" if cap>=.04 else "mid" if cap>=.015 else "cheap")]
            if v["exp"] <= 2: mult *= EXP_BUMP
            es = EFF_SHRINK[pos]; lpt, lpc = lg_eff(pos, Y)
            p_t = lpt + es*((v["ept"][0]/max(1,v["ept"][1]))-lpt) if v["ept"][1]>=30 else lpt
            p_c = lpc + es*((v["epc"][0]/max(1,v["epc"][1]))-lpc) if v["epc"][1]>=30 else lpc
            vs = s_t*mult*tv[0]*p_t + s_c*mult*tv[1]*p_c
            if vs > 0.5: out = VS_W*vs + (1-VS_W)*base
        if pos != "QB" and v["prev_team"] and v["team"] and v["prev_team"] != v["team"]:
            ds = deals.get((v["nk"], Y)) or deals.get((v["nk"], Y-1))
            cap = max(ds) if ds else None
            mv = MOVER_TIER["unknown" if cap is None else ("big" if cap>=.04 else "mid" if cap>=.015 else "cheap")]
            if v["age"] is not None and v["age"] >= 29: mv *= 0.92
            out *= max(0.80, mv)
        if pos == "TE" and v["te_rr"] is not None:
            out *= float(np.exp(np.clip(TE_SLOPE*(v["te_rr"]-TE_MEAN), -TE_CLAMP, TE_CLAMP)))
        g = v["W"]
        gm = v["clay_gm"]
        if gm is not None and 1 <= gm <= 13:
            g = (v["W"] + gm) / 2.0
        return out * v["W"], out * g   # (no availability, with availability)

    print("\n=== VETERANS — season points, LOYO ===")
    print(f"{'pos':<5}{'n':>6}{'base':>10}{'+layers':>10}{'+avail':>10}{'+shrink':>10}{'delta':>9}")
    tot = defaultdict(list)
    for pos in ("QB", "RB", "WR", "TE"):
        sel = [v for v in V if v["pos"] == pos]
        e_base, e_lay, e_av, e_all = [], [], [], []
        for Y in sorted({v["Y"] for v in sel}):
            tr = [v for v in sel if v["Y"] != Y]
            if len(tr) < 40: continue
            # engine shrinks toward CLAY's positional mean, not the model's
            cl = [clay[Y][v["nk"]] for v in sel
                  if v["Y"] == Y and clay.get(Y, {}).get(v["nk"])
                  and (clay[Y][v["nk"]].get("gm") or 0) >= 1]
            cpg = [(c["pts"] + (c.get("rec") or 0) * -0.5) / c["gm"] for c in cl
                   if (c.get("pts") or 0) >= 40]
            mc = float(np.mean(cpg)) if len(cpg) >= 10 else None
            for v in [x for x in sel if x["Y"] == Y]:
                a = v["actual"]
                e_base.append(abs(v["core"]*v["W"] - a))
                nl, wl = layers(v, False, mc)
                e_lay.append(abs(nl - a)); e_av.append(abs(wl - a))
                _, ws = layers(v, True, mc)
                e_all.append(abs(ws - a))
        for k, vv in (("base", e_base), ("all", e_all)): tot[k].extend(vv)
        b = np.mean(e_base)
        print(f"{pos:<5}{len(e_base):>6}{b:>10.1f}{np.mean(e_lay):>10.1f}{np.mean(e_av):>10.1f}"
              f"{np.mean(e_all):>10.1f}{(np.mean(e_all)-b)/b*100:>+8.2f}%")
    b, a = np.mean(tot["base"]), np.mean(tot["all"])
    print(f"{'ALL':<5}{len(tot['base']):>6}{b:>10.1f}{'':>10}{'':>10}{a:>10.1f}{(a-b)/b*100:>+8.2f}%")

    # ---- rookies ----
    dp = pd.read_parquet(os.path.join(CACHE, "draft_picks.parquet"),
                         columns=["season","round","pick","pfr_player_name","position","team"])
    dp = dp[(dp.season >= 2019) & (dp.position.isin(VS_POS))].copy()
    dp["norm"] = dp.pfr_player_name.map(lambda n: cal.norm(str(n)))
    dp["tm"] = dp.team.map(lambda t: PFR_TEAM.get(t, t))
    seasonpts = {}
    for nk, rec in recs:
        for Ys in rec.get("seasons", {}):
            d = P.get((id(rec), int(Ys)))
            if d: seasonpts[(nk, rec["pos"], int(Ys))] = d["season"]
    R = []
    for _, r in dp.iterrows():
        Y, pos, nk = int(r.season), r.position, r["norm"]
        R.append({"Y": Y, "pos": pos, "round": int(r["round"]),
                  "in_clay": nk in clay.get(Y, {}),
                  "actual": seasonpts.get((nk, pos, Y), 0.0)})
    print("\n=== ROOKIES — season points, LOYO (round-bucket baseline) ===")
    print(f"{'pos':<5}{'n':>6}{'base':>10}{'+noClay':>10}{'delta':>9}")
    tb, tn = [], []
    for pos in VS_POS:
        sel = [x for x in R if x["pos"] == pos]
        eb, en = [], []
        for Y in sorted({x["Y"] for x in sel}):
            tr = [x for x in sel if x["Y"] != Y]
            if len(tr) < 40: continue
            bm = defaultdict(list)
            for x in tr: bm[x["round"]].append(x["actual"])
            gmn = float(np.mean([x["actual"] for x in tr]))
            for x in [y for y in sel if y["Y"] == Y]:
                b = float(np.mean(bm[x["round"]])) if bm.get(x["round"]) else gmn
                eb.append(abs(b - x["actual"]))
                en.append(abs(b*(1.0 if x["in_clay"] else NOCLAY_MULT) - x["actual"]))
        tb.extend(eb); tn.extend(en)
        print(f"{pos:<5}{len(eb):>6}{np.mean(eb):>10.1f}{np.mean(en):>10.1f}"
              f"{(np.mean(en)-np.mean(eb))/np.mean(eb)*100:>+8.2f}%")
    print(f"{'ALL':<5}{len(tb):>6}{np.mean(tb):>10.1f}{np.mean(tn):>10.1f}"
          f"{(np.mean(tn)-np.mean(tb))/np.mean(tb)*100:>+8.2f}%")

if __name__ == "__main__":
    main()
