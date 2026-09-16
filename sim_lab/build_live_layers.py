#!/usr/bin/env python3
"""
LIVE LAYER RECONSTRUCTION (2026-09-16) - ingredients for the learned-combination test (backtest_learned_combo.py).

Rebuilds, on every ctx_features.parquet player-week 2019-25, the hand-tuned layers the live engine ships, with the
engine's own constants (engine.js), so the historical HAND projection is the live stack minus what cannot be
replayed (the 70% player-prop anchor, availability for players who sat, forecast vs game-time wind, TE route trend).

  td luck      RB k .75 x 6 (rush xTD table on carries, target table on targets), WR/TE k 1.0 x 6 (receiver
               yardline x end-zone table on targets + rush table on carries), QB k .5 x 4 (passing only, receiver
               table on targeted attempts); luck = (xTD - TD) / games with a touch, season to date;
               adj = k x tdPts x luck x g / (5 + g)   (additive, after the chain)
  banged cond  final report Questionable x last practice Full / Limited / DNP -> engine BANGED cond (played rows)
  rookie       QB / RB rookies with >= 1 game: blend x 1.08
  rb usage     RB with >= 3 prior snap weeks: blend = .85 blend + .15 x (avg snap share x team plays/g x .315)
  weather      wind >= 15: QB .94 WR .93 TE .95; 10-15: .97 / .97 / .98 (outdoor)
  pool         teammates designated Out / Doubtful / IR (injury report or roster IR/PUP/NFI/SUS): their season-to-
               date targets / carries per game redistributed by the engine POOL weights (depth rank by his own
               per-game volume among healthy same-position teammates, lead / secondary rule, other positions
               pro rata by targets); gained = absorbed tgt x own pts/tgt x .92 + carries x pts/carry;
               f = 1 + gained / max(own ppg, 3.5)   (engine floor 4 PPR ~ 3.5 half)
  backup qb    QB who is not his team's season-to-date dropback leader, leader designated out: f = 1 + .85 x
               leader's blend / max(own blend, 1)
Output: ctx_live_layers.parquet (year, pid, wk, name + ingredients + multipliers).
"""
import os, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B
from pull_pace_tracker import _xtd, _xtd_rec
import build_context_features as CF

YEARS = list(range(2019, 2026))
BANGED_COND = {"Q-FP": {"QB": 0.951, "RB": 0.952, "WR": 0.961, "TE": 0.955},
               "Q-LP": {"QB": 0.941, "RB": 0.942, "WR": 0.943, "TE": 0.933},
               "Q-DNP": {"QB": 0.891, "RB": 0.877, "WR": 0.884, "TE": 0.891}}
WEATHER = {"QB": (0.94, 0.97), "WR": (0.93, 0.97), "TE": (0.95, 0.98)}
POOL = {
    "RB": {"lead": {"tgtSame": [0.28, 0.18], "carSame": [0.28, 0.16, 0.10], "tgtOther": 0.15},
           "sec": {"tgtSame": [0.28, 0.18], "carSame": [0.28, 0.16, 0.10], "tgtOther": 0.15}},
    "WR": {"lead": {"tgtSame": [0.09, 0.15, 0.16, 0.10], "carSame": [], "tgtOther": 0.08},
           "sec": {"tgtSame": [0.00, 0.11, 0.15, 0.10], "carSame": [], "tgtOther": 0.00}},
    "TE": {"lead": {"tgtSame": [0.25, 0.10], "carSame": [], "tgtOther": 0.36},
           "sec": {"tgtSame": [0.00, 0.22], "carSame": [], "tgtOther": 0.00}},
}
TDK = {"RB": (0.75, 6.0), "WR": (1.0, 6.0), "TE": (1.0, 6.0), "QB": (0.5, 4.0)}
ABSENT_ROSTER = {"RES", "PUP", "NFI", "SUS"}


def P(*a):
    print(" ".join(str(x) for x in a), flush=True)


def pbp_week_tables(Y, pos_of):
    cols = ["season_type", "week", "posteam", "pass_attempt", "rush_attempt", "sack", "qb_dropback", "two_point_attempt",
            "receiver_player_id", "rusher_player_id", "passer_player_id", "yardline_100", "air_yards", "complete_pass",
            "receiving_yards", "rushing_yards", "pass_touchdown", "rush_touchdown", "td_player_id"]
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), usecols=cols, low_memory=False)
    df = df[(df.season_type == "REG") & df.posteam.notna() & (df.two_point_attempt.fillna(0) != 1)]
    W = defaultdict(lambda: defaultdict(float)); T = {}
    for r in df.itertuples(index=False):
        wk = int(r.week); tm = B.tm(str(r.posteam))
        yl = float(r.yardline_100) if pd.notna(r.yardline_100) else 99.0
        if r.pass_attempt == 1 and r.sack != 1:
            rcv = r.receiver_player_id; ps = r.passer_player_id
            ay = float(r.air_yards) if pd.notna(r.air_yards) else np.nan
            ez = pd.notna(ay) and ay >= yl
            if isinstance(ps, str):
                q = W[(ps, wk)]; T[(ps, wk)] = tm
                q["att"] += 1
                if isinstance(rcv, str):
                    q["pxtd"] += _xtd_rec(yl, ez)
                q["ptd"] += r.pass_touchdown == 1
            if isinstance(rcv, str):
                q = W[(rcv, wk)]; T[(rcv, wk)] = tm
                rp = pos_of.get(rcv)
                q["tg"] += 1
                q["xtd"] += _xtd(yl, False) if rp == "RB" else _xtd_rec(yl, ez)
                if r.complete_pass == 1:
                    q["rec_pts"] += 0.5 + 0.1 * (float(r.receiving_yards) if pd.notna(r.receiving_yards) else 0.0)
                if r.pass_touchdown == 1 and (pd.isna(r.td_player_id) or r.td_player_id == rcv):
                    q["td"] += 1; q["rec_pts"] += 6
        if r.rush_attempt == 1 and isinstance(r.rusher_player_id, str):
            pid = r.rusher_player_id
            q = W[(pid, wk)]; T[(pid, wk)] = tm
            q["car"] += 1
            if pos_of.get(pid) != "QB":
                q["xtd"] += _xtd(yl, True)
                if r.rush_touchdown == 1 and (pd.isna(r.td_player_id) or r.td_player_id == pid):
                    q["td"] += 1
            q["rush_pts"] += 0.1 * (float(r.rushing_yards) if pd.notna(r.rushing_yards) else 0.0) + (6 if r.rush_touchdown == 1 and (pd.isna(r.td_player_id) or r.td_player_id == pid) else 0)
        if r.qb_dropback == 1 and isinstance(r.passer_player_id, str):
            W[(r.passer_player_id, wk)]["db"] += 1; T.setdefault((r.passer_player_id, wk), tm)
    return W, T


CACHE = B.CACHE


def main():
    t0 = time.time()
    pos_of, bd_of, rook_of = CF.load_positions()
    df = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet"))
    out = []
    for Y in YEARS:
        W, T = pbp_week_tables(Y, pos_of)
        inj, _ = CF.injuries(Y)
        ros, _, _ = CF.rosters(Y)
        snaps = CF.load_snaps(Y)
        by_pid = defaultdict(dict)
        team_pl = defaultdict(set)
        for (pid, wk), v in W.items():
            by_pid[pid][wk] = v; team_pl[T[(pid, wk)]].add(pid)
        rows = df[df.year == Y]
        # blend value of each QB sample by (team, wk) for the backup-QB rule
        qb_blend = {}
        for r in rows[rows.pos == "QB"].itertuples(index=False):
            qb_blend[(r.pid, r.team, r.wk)] = r.shipped / max(r.veg * r.fpa_mult, 1e-9)
        qb_last_blend = {}
        for r in rows[rows.pos == "QB"].sort_values("wk").itertuples(index=False):
            qb_last_blend.setdefault((r.pid, r.team), []).append((r.wk, r.shipped / max(r.veg * r.fpa_mult, 1e-9)))

        def std(pid, t, wk):
            acc = defaultdict(float); g = 0
            for w, v in by_pid.get(pid, {}).items():
                if w < wk and T.get((pid, w)) == t:
                    g += 1
                    for k, x in v.items():
                        acc[k] += x
            return acc, g

        def absent(pid, t, wk):
            rs = inj.get((t, wk, pid), ("", ""))[0]
            return rs in ("Out", "Doubtful") or ros.get((t, wk, pid)) in ABSENT_ROSTER

        pool_cache = {}

        def team_pool(t, wk):
            if (t, wk) in pool_cache:
                return pool_cache[(t, wk)]
            mem = []
            for q in team_pl.get(t, ()):
                qp = pos_of.get(q)
                if qp not in POOL:
                    continue
                a, g = std(q, t, wk)
                if g == 0 or (a["tg"] + a["car"]) == 0:
                    continue
                mem.append({"pid": q, "pos": qp, "tg": a["tg"] / g, "car": a["car"] / g, "abs": absent(q, t, wk)})
            gainT, gainC = defaultdict(float), defaultdict(float)
            if mem:
                top = max(m["tg"] for m in mem)
                vac = {}
                for m in mem:
                    if m["abs"]:
                        v = vac.setdefault(m["pos"], {"tg": 0.0, "car": 0.0, "lead": False})
                        v["tg"] += m["tg"]; v["car"] += m["car"]
                        if m["tg"] >= top - 1e-9:
                            v["lead"] = True
                for apos, v in vac.items():
                    rule = POOL[apos]["lead" if v["lead"] else "sec"]
                    healthy = [m for m in mem if not m["abs"]]
                    same = sorted([m for m in healthy if m["pos"] == apos], key=lambda m: -(m["car"] if apos == "RB" else m["tg"]))
                    for i, m in enumerate(same):
                        if i < len(rule["tgtSame"]) and rule["tgtSame"][i]:
                            gainT[m["pid"]] += v["tg"] * rule["tgtSame"][i]
                        if i < len(rule["carSame"]) and rule["carSame"][i]:
                            gainC[m["pid"]] += v["car"] * rule["carSame"][i]
                    if rule["tgtOther"] > 0:
                        others = [m for m in healthy if m["pos"] not in (apos, "RB")]
                        tot = sum(m["tg"] for m in others)
                        for m in others:
                            if tot > 0:
                                gainT[m["pid"]] += v["tg"] * rule["tgtOther"] * m["tg"] / tot
            pool_cache[(t, wk)] = (gainT, gainC)
            return gainT, gainC

        for r in rows.itertuples(index=False):
            pid, t, wk, p = r.pid, r.team, int(r.wk), r.pos
            blend = r.shipped / max(r.veg * r.fpa_mult, 1e-9)
            rec = {"year": Y, "pid": pid, "wk": wk, "name": r.name, "blend": blend}
            a, g_touch = std(pid, t, wk) if pid else (defaultdict(float), 0)
            # td luck
            k, tdp = TDK[p]
            if p == "QB":
                n_att_g = sum(1 for w, v in by_pid.get(pid, {}).items() if w < wk and v.get("att", 0) > 0 and T.get((pid, w)) == t) if pid else 0
                luck = (a["pxtd"] - a["ptd"]) / n_att_g if n_att_g else 0.0
            else:
                luck = (a["xtd"] - a["td"]) / g_touch if g_touch else 0.0
            rec["td_luck_pg"] = luck
            rec["td_luck_adj"] = k * tdp * luck * (r.g / (5.0 + r.g)) if r.g else 0.0
            # banged cond
            rs, pr = inj.get((t, wk, pid), ("", "")) if pid else ("", "")
            cls = None
            if rs == "Questionable":
                cls = "Q-DNP" if "Did Not" in pr else ("Q-LP" if "Limited" in pr else ("Q-FP" if "Full" in pr else None))
            rec["banged_cls"] = cls or ""
            rec["cond_mult"] = BANGED_COND[cls][p] if cls else 1.0
            # rookie
            rk = rook_of.get(pid) if pid else None
            rec["rookie_mult"] = 1.08 if (p in ("QB", "RB") and rk == Y and r.g >= 1) else 1.0
            # rb usage
            sn = snaps.get((B.cal.norm(r.name), t), {})
            sw = [v for w, v in sn.items() if w < wk and v > 0]
            rec["usage_half"] = np.nan
            if p == "RB" and len(sw) >= 3 and pd.notna(r.plays_pg_std):
                rec["usage_half"] = float(np.mean(sw)) / 100.0 * r.plays_pg_std * 0.315
            # weather
            wm = 1.0
            if p in WEATHER and not r.dome and pd.notna(r.wind):
                wm = WEATHER[p][0] if r.wind >= 15 else (WEATHER[p][1] if r.wind >= 10 else 1.0)
            rec["weather_mult"] = wm
            # pool
            rec["pool_gain_tg"] = rec["pool_gain_car"] = 0.0; rec["pool_mult"] = 1.0
            if p in POOL and pid:
                gT, gC = team_pool(t, wk)
                gt, gc = gT.get(pid, 0.0), gC.get(pid, 0.0)
                if gt or gc:
                    ppt = a["rec_pts"] / a["tg"] if a["tg"] else 0.0
                    ppc = a["rush_pts"] / a["car"] if a["car"] else 0.0
                    gained = gt * ppt * 0.92 + gc * ppc
                    rec["pool_gain_tg"], rec["pool_gain_car"] = gt, gc
                    rec["pool_mult"] = 1 + gained / max(r.ppg if pd.notna(r.ppg) else 0.0, 3.5)
            # backup qb
            rec["qb_inherit_mult"] = 1.0
            if p == "QB" and pid:
                best, bdb = None, 0.0
                for q in team_pl.get(t, ()):
                    if pos_of.get(q) != "QB":
                        continue
                    qa, _ = std(q, t, wk)
                    if qa["db"] > bdb:
                        best, bdb = q, qa["db"]
                if best and best != pid and absent(best, t, wk):
                    lb = [b for w, b in qb_last_blend.get((best, t), []) if w < wk]
                    if lb:
                        rec["qb_inherit_mult"] = 1 + 0.85 * lb[-1] / max(blend, 1.0)
            out.append(rec)
        P(f"  {Y}: {len(out)} rows ({time.time()-t0:.0f}s)")
    L = pd.DataFrame(out)
    L.to_parquet(os.path.join(HERE, "ctx_live_layers.parquet"), index=False)
    P(f"wrote ctx_live_layers.parquet: {len(L)} rows")
    P("layer activity: " + ", ".join([
        f"td luck nonzero {(L.td_luck_adj != 0).mean():.2f} (mean |adj| {L.td_luck_adj.abs().mean():.2f})",
        f"banged {(L.cond_mult < 1).mean():.3f}", f"rookie {(L.rookie_mult > 1).mean():.3f}",
        f"rb usage {L.usage_half.notna().mean():.3f}", f"weather {(L.weather_mult < 1).mean():.3f}",
        f"pool {(L.pool_mult > 1).mean():.3f} (mean mult when on {L.pool_mult[L.pool_mult > 1].mean():.3f})",
        f"backup qb {(L.qb_inherit_mult > 1).mean():.3f}"]))


if __name__ == "__main__":
    main()
