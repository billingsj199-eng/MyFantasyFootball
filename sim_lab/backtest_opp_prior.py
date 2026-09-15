#!/usr/bin/env python3
"""
OPPORTUNITY PRIOR backtest (2026-09-15).

Jack: "start on the opportunity prior next" - roadmap step 5 for the Clay-free shadow base (Clay stays the live
base). A preseason projection built only from our own inputs: expected opportunities x value per opportunity.

Per RB / WR / TE season Y (>= 6 games with an opportunity), everything known before Y (pbp 2016-2025):
  shares      target share = player targets per game / his team's targets per game (all targets);
              carry share = player carries per game / team non-QB carries per game
  vets        played >= 6 games in Y-1: share_Y ~ a + b share_{Y-1} + c alloc + d mover x share_{Y-1} + e (age-27)
              alloc = team's vacated share (Y-1 shares of its RB/WR/TE who are not on the team in Y) x his Y-1 share /
              sum of Y-1 shares of everyone on the team in Y (movers bring their old-team share)
  rookies     drafted in Y: share_Y ~ a + b log(pick) + c vacated share, per position (nflverse draft_picks)
  volume      team targets / carries per game = .5 x the team's Y-1 value + .5 x league mean
  value       his Y-1 xFP per target / per carry (site xFP tables: pull_pace_tracker) shrunk to the position mean
              (K = 60 opportunities); efficiency ratio (actual - xFP) / xFP shrunk n/(n+150), weight lambda fit
  OPP         = (target share x team targets x value per target + carry share x team carries x value per carry)
                x (1 + lambda x efficiency)
Baselines (test seasons 2019-2025, fits refit without the test season):
  CLAY        Clay's preseason projection per game (data/clay_history.json, half-PPR)
  HIST        3-yr weighted PPG (.5/.3/.2, >= 6 games) - the shadow's history prior
  HISTREG     HIST with log regression toward the position mean (the shadow now applies regression + age)
  blends      OPP with HISTREG (vets) and OPP with CLAY (all), weight fit on training seasons
  SHADOW      HISTREG for vets, OPP for rookies (what replaces the Clay fallback)
Segments: returning vets, team-changing vets, rookies. Actual = half-PPR receiving + rushing points per game.
Log opp_prior_backtest.log; results -> data/opp_prior_backtest.js (SIM_OPPPRIOR_BT), ZONES tab.
"""
import json, math, os, sys, time
from collections import defaultdict, Counter
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B
from backtest_target_area import mse
from pull_pace_tracker import _xfp_ab, _xtd_rec, _xfp_rush, _xtd, XFP_CATCH, XFP_TGT_YDS

LOG = open(os.path.join(HERE, "opp_prior_backtest.log"), "w", encoding="utf-8")


class _Tee:
    def __init__(self, a, b): self.a, self.b = a, b
    def write(self, t): self.a.write(t); self.b.write(t); self.a.flush(); self.b.flush()
    def flush(self): self.a.flush(); self.b.flush()


sys.stdout = _Tee(sys.stdout, LOG)
def P(*a): print(" ".join(str(x) for x in a))

LOAD = list(range(2016, 2026))
BUILD = list(range(2017, 2026))
TEST = list(range(2019, 2026))
SKILL = ("RB", "WR", "TE")
K_VAL, K_EFF = 60.0, 150.0
RES = {"segments": [], "coef": {}, "n": 0}


def load_positions():
    p = pd.read_csv(os.path.join(B.CACHE, "players.csv"), usecols=["gsis_id", "position", "display_name", "birth_date"], low_memory=False)
    pos, name, bd = {}, {}, {}
    for r in p.itertuples(index=False):
        if not isinstance(r.gsis_id, str):
            continue
        ps = "RB" if r.position == "FB" else r.position
        pos[r.gsis_id] = ps; name[r.gsis_id] = r.display_name
        bd[r.gsis_id] = pd.to_datetime(r.birth_date, errors="coerce") if isinstance(r.birth_date, str) else pd.NaT
    return pos, name, bd


def load_season(Y, pos_of):
    cols = ["season_type", "week", "posteam", "pass_attempt", "rush_attempt", "sack", "receiver_player_id", "rusher_player_id",
            "yardline_100", "air_yards", "complete_pass", "receiving_yards", "rushing_yards", "pass_touchdown", "rush_touchdown", "td_player_id"]
    pbp = pd.read_csv(os.path.join(B.CACHE, f"play_by_play_{Y}.csv.gz"), usecols=cols, low_memory=False)
    pbp = pbp[(pbp.season_type == "REG") & pbp.posteam.notna()]
    pl = defaultdict(lambda: {"tg": 0, "car": 0, "xr": 0.0, "xc": 0.0, "act": 0.0, "weeks": set(), "tm": Counter()})
    tm_ = defaultdict(lambda: {"tg": 0, "car": 0, "weeks": set()})
    pa = pbp[(pbp.pass_attempt == 1) & (pbp.sack != 1) & pbp.receiver_player_id.notna()]
    for r in pa.itertuples(index=False):
        t = B.tm(str(r.posteam)); wk = int(r.week)
        tm_[t]["tg"] += 1; tm_[t]["weeks"].add(wk)
        rcv = r.receiver_player_id
        if pos_of.get(rcv) not in SKILL:
            continue
        yl = float(r.yardline_100) if pd.notna(r.yardline_100) else 50.0
        a = float(r.air_yards) if pd.notna(r.air_yards) else 0.0
        b = _xfp_ab(a)
        q = pl[rcv]; q["tg"] += 1; q["weeks"].add(wk); q["tm"][t] += 1
        q["xr"] += 0.5 * XFP_CATCH[b] + 0.1 * XFP_TGT_YDS[b] + 6 * _xtd_rec(yl, a >= yl)
        if r.complete_pass == 1:
            q["act"] += 0.5 + 0.1 * (float(r.receiving_yards) if pd.notna(r.receiving_yards) else 0.0)
            if r.pass_touchdown == 1 and (pd.isna(r.td_player_id) or r.td_player_id == rcv):
                q["act"] += 6
    ru = pbp[(pbp.rush_attempt == 1) & pbp.rusher_player_id.notna()]
    for r in ru.itertuples(index=False):
        pid = r.rusher_player_id
        if pos_of.get(pid) == "QB":
            continue
        t = B.tm(str(r.posteam)); wk = int(r.week)
        tm_[t]["car"] += 1; tm_[t]["weeks"].add(wk)
        if pos_of.get(pid) not in SKILL:
            continue
        yl = float(r.yardline_100) if pd.notna(r.yardline_100) else 50.0
        q = pl[pid]; q["car"] += 1; q["weeks"].add(wk); q["tm"][t] += 1
        q["xc"] += 0.1 * _xfp_rush(yl, False) + 6 * _xtd(yl, True)
        q["act"] += 0.1 * (float(r.rushing_yards) if pd.notna(r.rushing_yards) else 0.0)
        if r.rush_touchdown == 1 and (pd.isna(r.td_player_id) or r.td_player_id == pid):
            q["act"] += 6
    teams = {t: {"tg_pg": v["tg"] / len(v["weeks"]), "car_pg": v["car"] / len(v["weeks"]), "g": len(v["weeks"])} for t, v in tm_.items() if v["weeks"]}
    players = {}
    for pid, q in pl.items():
        g = len(q["weeks"])
        t = q["tm"].most_common(1)[0][0]
        tv = teams.get(t)
        if not g or not tv:
            continue
        players[pid] = {"pos": pos_of[pid], "tm": t, "g": g, "tg": q["tg"], "car": q["car"], "xr": q["xr"], "xc": q["xc"], "act": q["act"],
                        "ts": (q["tg"] / g) / tv["tg_pg"] if tv["tg_pg"] else 0.0, "cs": (q["car"] / g) / tv["car_pg"] if tv["car_pg"] else 0.0}
    return players, teams


def main():
    pos_of, name_of, bd_of = load_positions()
    P("loading pbp 2016-2025 (targets, carries, site xFP, half-PPR points) ...")
    SEAS = {}
    for Y in LOAD:
        SEAS[Y] = load_season(Y, pos_of)
        P(f"  {Y}: {len(SEAS[Y][0])} RB/WR/TE player-seasons, {len(SEAS[Y][1])} teams")
    dp = pd.read_parquet(os.path.join(B.CACHE, "draft_picks.parquet"), columns=["season", "pick", "gsis_id", "position"])
    draft = {r.gsis_id: (int(r.season), int(r.pick)) for r in dp.itertuples(index=False) if isinstance(r.gsis_id, str) and pd.notna(r.pick)}
    clay_hist = json.load(open(os.path.join(B.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    resolve = B.player_ids()
    clay = {}
    for ys, pls in clay_hist.items():
        Y = int(ys); W = 16 if Y <= 2020 else 17
        for nm, c in pls.items():
            if c.get("pos") not in SKILL:
                continue
            g = resolve(nm, c["pos"], Y)
            if g:
                clay[(Y, g)] = max(0.0, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0) / W

    rows = []
    for Y in BUILD:
        cur_pl, cur_tm = SEAS[Y]; prv_pl, prv_tm = SEAS[Y - 1]
        lg_tg = float(np.mean([t["tg_pg"] for t in prv_tm.values()])); lg_car = float(np.mean([t["car_pg"] for t in prv_tm.values()]))
        # vacated and returning shares per team in Y
        on_team_Y = defaultdict(set)
        for pid, q in cur_pl.items():
            on_team_Y[q["tm"]].add(pid)
        vac = defaultdict(lambda: {"tg": 0.0, "car": 0.0}); ret = defaultdict(lambda: {"tg": 0.0, "car": 0.0})
        for pid, q in prv_pl.items():
            if pid not in on_team_Y[q["tm"]]:
                vac[q["tm"]]["tg"] += q["ts"]; vac[q["tm"]]["car"] += q["cs"]
        for t, pids in on_team_Y.items():
            for pid in pids:
                pq = prv_pl.get(pid)
                if pq:
                    ret[t]["tg"] += pq["ts"]; ret[t]["car"] += pq["cs"]
        for pid, q in cur_pl.items():
            if q["g"] < 6:
                continue
            t = q["tm"]; pv = prv_pl.get(pid); tprev = prv_tm.get(t)
            if not tprev:
                continue
            row = {"Y": Y, "pid": pid, "pos": q["pos"], "tm": t, "ppg": q["act"] / q["g"], "ts": q["ts"], "cs": q["cs"],
                   "tg_pg": 0.5 * tprev["tg_pg"] + 0.5 * lg_tg, "car_pg": 0.5 * tprev["car_pg"] + 0.5 * lg_car,
                   "vac_tg": vac[t]["tg"], "vac_car": vac[t]["car"], "clay": clay.get((Y, pid))}
            b = bd_of.get(pid)
            row["age"] = ((pd.Timestamp(Y, 9, 1) - b).days / 365.25) if b is not None and not pd.isna(b) else 26.0
            d = draft.get(pid)
            if d and d[0] == Y:
                row["seg"] = "rookie"; row["pick"] = d[1]
            elif pv and pv["g"] >= 6:
                row["seg"] = "mover" if pv["tm"] != t else "stay"
                row.update({"ts_p": pv["ts"], "cs_p": pv["cs"], "tg_p": pv["tg"], "car_p": pv["car"], "xr_p": pv["xr"], "xc_p": pv["xc"],
                            "act_p": pv["act"], "g_p": pv["g"],
                            "alloc_tg": vac[t]["tg"] * pv["ts"] / ret[t]["tg"] if ret[t]["tg"] else 0.0,
                            "alloc_car": vac[t]["car"] * pv["cs"] / ret[t]["car"] if ret[t]["car"] else 0.0})
                w = num = 0.0
                for lag, wt in ((1, 0.5), (2, 0.3), (3, 0.2)):
                    s3 = SEAS.get(Y - lag, ({}, {}))[0].get(pid)
                    if s3 and s3["g"] >= 6:
                        w += wt; num += wt * s3["act"] / s3["g"]
                row["hist"] = num / w if w else None
            else:
                continue
            rows.append(row)
    P(f"  {len(rows)} player-seasons 2017-2025: " + ", ".join(f"{s} {sum(1 for r in rows if r['seg'] == s)}" for s in ("stay", "mover", "rookie")))

    def fit(train):
        M = {}
        for p in SKILL:
            vt = [r for r in train if r["pos"] == p and r["seg"] in ("stay", "mover")]
            rk = [r for r in train if r["pos"] == p and r["seg"] == "rookie"]
            for key, prev, alloc in (("ts", "ts_p", "alloc_tg"), ("cs", "cs_p", "alloc_car")):
                X = np.array([[1.0, r[prev], r[alloc], (r["seg"] == "mover") * r[prev], r["age"] - 27.0] for r in vt])
                y = np.array([r[key] for r in vt])
                M[(p, "vet", key)] = np.linalg.lstsq(X, y, rcond=None)[0] if len(vt) >= 30 else None
                vk = "vac_tg" if key == "ts" else "vac_car"
                if len(rk) >= 15:
                    Xr = np.array([[1.0, math.log(r["pick"]), r[vk]] for r in rk]); yr = np.array([r[key] for r in rk])
                    M[(p, "rookie", key)] = np.linalg.lstsq(Xr, yr, rcond=None)[0]
                else:
                    M[(p, "rookie", key)] = None
            tg = sum(r["tg_p"] for r in vt); car = sum(r["car_p"] for r in vt)
            M[(p, "v_tg")] = sum(r["xr_p"] for r in vt) / tg if tg else 1.4
            M[(p, "v_car")] = sum(r["xc_p"] for r in vt) / car if car else 0.6
            hv = [r for r in vt if r.get("hist") and r["hist"] >= 1.0]
            if len(hv) >= 30:
                x = np.log([r["hist"] for r in hv]); yv = np.log([max(r["ppg"], 0.5) for r in hv])
                bb, aa = np.polyfit(x, yv, 1); sm = float(np.mean(np.exp(yv - (aa + bb * x))))
                M[(p, "reg")] = (aa, bb, sm)
        return M

    def opp_raw(r, M, lam):
        p = r["pos"]
        if r["seg"] == "rookie":
            ct, cc = M[(p, "rookie", "ts")], M[(p, "rookie", "cs")]
            if ct is None or cc is None:
                return None
            ts = max(0.0, ct @ [1.0, math.log(r["pick"]), r["vac_tg"]]); cs = max(0.0, cc @ [1.0, math.log(r["pick"]), r["vac_car"]])
            return ts * r["tg_pg"] * M[(p, "v_tg")] + cs * r["car_pg"] * M[(p, "v_car")]
        ct, cc = M[(p, "vet", "ts")], M[(p, "vet", "cs")]
        if ct is None or cc is None:
            return None
        mv = 1.0 if r["seg"] == "mover" else 0.0
        ts = max(0.0, ct @ [1.0, r["ts_p"], r["alloc_tg"], mv * r["ts_p"], r["age"] - 27.0])
        cs = max(0.0, cc @ [1.0, r["cs_p"], r["alloc_car"], mv * r["cs_p"], r["age"] - 27.0])
        vt = (r["xr_p"] + K_VAL * M[(p, "v_tg")]) / (r["tg_p"] + K_VAL)
        vc = (r["xc_p"] + K_VAL * M[(p, "v_car")]) / (r["car_p"] + K_VAL)
        x_prev = r["xr_p"] + r["xc_p"]; n = r["tg_p"] + r["car_p"]
        eff = ((r["act_p"] - x_prev) / x_prev) * n / (n + K_EFF) if x_prev > 0 else 0.0
        return (ts * r["tg_pg"] * vt + cs * r["car_pg"] * vc) * (1 + lam * eff)

    def histreg(r, M):
        if not r.get("hist"):
            return None
        rg = M.get((r["pos"], "reg"))
        return math.exp(rg[0] + rg[1] * math.log(max(r["hist"], 1.0))) * rg[2] if rg else r["hist"]

    # ---- LOYO over test seasons ----
    preds = defaultdict(dict)
    lam_picks = []
    for T in TEST:
        train = [r for r in rows if r["Y"] != T]
        M = fit(train)
        best = min((0.0, 0.25, 0.5, 0.75, 1.0), key=lambda lam: np.mean([(opp_raw(r, M, lam) - r["ppg"]) ** 2 for r in train if opp_raw(r, M, lam) is not None and r["seg"] != "rookie"]))
        lam_picks.append(best)
        tr = [r for r in train if r.get("clay") is not None]
        def wfit(fa, fb, subset):
            cand = [r for r in subset if fa(r) is not None and fb(r) is not None]
            if len(cand) < 30:
                return 0.5
            return min([i / 10 for i in range(11)], key=lambda w: np.mean([((1 - w) * fb(r) + w * fa(r) - r["ppg"]) ** 2 for r in cand]))
        w_hist = wfit(lambda r: opp_raw(r, M, best), lambda r: histreg(r, M), [r for r in tr if r["seg"] != "rookie"])
        w_clay = wfit(lambda r: opp_raw(r, M, best), lambda r: r["clay"], tr)
        opp_c = {id(r): opp_raw(r, M, best) for r in train}
        hist_c = {id(r): histreg(r, M) for r in train}

        def linfit(fns, subset):
            cand = [r for r in subset if all(f(r) is not None for f in fns)]
            if len(cand) < 25:
                return None
            X = np.array([[1.0] + [f(r) for f in fns] for r in cand]); yv = np.array([r["ppg"] for r in cand])
            return np.linalg.lstsq(X, yv, rcond=None)[0]
        cal = {}
        for p in SKILL:
            trp = [r for r in train if r["pos"] == p]
            vets = [r for r in trp if r["seg"] != "rookie"]
            fc = lambda r: r.get("clay"); fo = lambda r: opp_c.get(id(r)); fh = lambda r: hist_c.get(id(r))
            cal[(p, "CLAYCAL")] = linfit([fc], trp)
            cal[(p, "OPPCAL")] = linfit([fo], trp)
            cal[(p, "HISTCAL")] = linfit([fh], vets)
            cal[(p, "CLAY+OPP")] = linfit([fc, fo], trp)
            cal[(p, "HIST+OPP")] = linfit([fh, fo], vets)
            cal[(p, "ROOKIE_OPP")] = linfit([fo], [r for r in trp if r["seg"] == "rookie"])
        for r in rows:
            if r["Y"] != T:
                continue
            k = id(r)
            o = opp_raw(r, M, best); h = histreg(r, M)
            preds[k].update({"OPP": o, "HIST": r.get("hist"), "HISTREG": h, "CLAY": r.get("clay")})
            preds[k]["OPP+HISTREG"] = (1 - w_hist) * h + w_hist * o if (o is not None and h is not None) else None
            preds[k]["OPP+CLAY"] = (1 - w_clay) * r["clay"] + w_clay * o if (o is not None and r.get("clay") is not None) else None
            preds[k]["SHADOW"] = o if r["seg"] == "rookie" else preds[k]["OPP+HISTREG"]

            def apply(key, vals, r=r):
                c = cal.get((r["pos"], key))
                if c is None or any(v is None for v in vals):
                    return None
                return float(c @ np.array([1.0] + list(vals)))
            preds[k]["CLAYCAL"] = apply("CLAYCAL", [r.get("clay")])
            preds[k]["OPPCAL"] = apply("OPPCAL", [o])
            preds[k]["HISTCAL"] = apply("HISTCAL", [h]) if r["seg"] != "rookie" else None
            preds[k]["CLAY+OPP"] = apply("CLAY+OPP", [r.get("clay"), o])
            preds[k]["HIST+OPP"] = apply("HIST+OPP", [h, o]) if r["seg"] != "rookie" else None
            preds[k]["SHADOWCAL"] = apply("ROOKIE_OPP", [o]) if r["seg"] == "rookie" else preds[k]["HIST+OPP"]
    P(f"  efficiency lambda picks per test season: {lam_picks}")

    models = ["CLAY", "CLAYCAL", "HIST", "HISTREG", "HISTCAL", "OPP", "OPPCAL", "HIST+OPP", "CLAY+OPP", "SHADOW", "SHADOWCAL"]
    P("\n=== season PPG prediction, test seasons 2019-2025 (every model on the same rows per segment; parenthesis = seasons better than CALIBRATED Clay) ===")
    test_rows = [r for r in rows if r["Y"] in TEST and r.get("clay") is not None]
    RES["n"] = len(test_rows)
    for seg in ("stay", "mover", "rookie", "all vets", "all"):
        for p in ("ALL",) + SKILL:
            sub = [r for r in test_rows if (p == "ALL" or r["pos"] == p) and (r["seg"] == seg or (seg == "all vets" and r["seg"] != "rookie") or seg == "all")]
            avail = [m for m in models if sub and all(preds[id(r)].get(m) is not None for r in sub)]
            sub2 = sub
            if len(avail) < 2:
                # rookies: history models are missing by definition - compare what exists
                avail = [m for m in ("CLAY", "CLAYCAL", "OPP", "OPPCAL", "CLAY+OPP", "SHADOWCAL") if sub and all(preds[id(r)].get(m) is not None for r in sub)]
            if len(sub2) < 20 or not avail:
                continue
            act = np.array([r["ppg"] for r in sub2])
            out = {}
            for m in avail:
                pr = np.array([preds[id(r)][m] for r in sub2])
                wins = 0; yrs = 0
                for T in TEST:
                    mk = np.array([r["Y"] == T for r in sub2])
                    if mk.sum() >= 5:
                        cl = np.array([preds[id(r)]["CLAYCAL"] for r in sub2])
                        wins += mse(pr[mk], act[mk]) < mse(cl[mk], act[mk]); yrs += 1
                out[m] = {"mse": round(mse(pr, act), 3), "r": round(float(np.corrcoef(pr, act)[0, 1]), 3), "beatsClayYears": f"{wins}/{yrs}"}
            P(f"  {seg:8s} {p:3s} n {len(sub2):4d} | " + " | ".join(f"{m} MSE {v['mse']:.2f} r {v['r']:.2f} ({v['beatsClayYears']})" for m, v in out.items()))
            RES["segments"].append({"seg": seg, "pos": p, "n": len(sub2), "models": out})
    Mall = fit(rows)
    for p in SKILL:
        RES["coef"][p] = {k2: [round(float(x), 4) for x in Mall[(p, s, k2)]] if Mall[(p, s, k2)] is not None else None
                          for s in ("vet", "rookie") for k2 in ("ts", "cs")} if False else {
            "vet_ts": [round(float(x), 4) for x in Mall[(p, "vet", "ts")]] if Mall[(p, "vet", "ts")] is not None else None,
            "vet_cs": [round(float(x), 4) for x in Mall[(p, "vet", "cs")]] if Mall[(p, "vet", "cs")] is not None else None,
            "rookie_ts": [round(float(x), 4) for x in Mall[(p, "rookie", "ts")]] if Mall[(p, "rookie", "ts")] is not None else None,
            "rookie_cs": [round(float(x), 4) for x in Mall[(p, "rookie", "cs")]] if Mall[(p, "rookie", "cs")] is not None else None,
            "v_tg": round(Mall[(p, "v_tg")], 3), "v_car": round(Mall[(p, "v_car")], 3)}
        P(f"  {p} share models (all seasons): vet target share [1, prev, alloc, mover x prev, age-27] {RES['coef'][p]['vet_ts']} | "
          f"rookie target share [1, log pick, vacated] {RES['coef'][p]['rookie_ts']} | value/target {RES['coef'][p]['v_tg']} /carry {RES['coef'][p]['v_car']}")
    RES["lambda"] = lam_picks
    # full-fit calibration of HIST + OPP for veterans (what the Clay-free shadow applies live; build_opp_prior.py reads it)
    lam_all = float(np.median(lam_picks))
    RES["lambdaAll"] = lam_all
    RES["calAll"] = {}
    for p in SKILL:
        cand = []
        for r in rows:
            if r["pos"] != p or r["seg"] == "rookie":
                continue
            hv, ov = histreg(r, Mall), opp_raw(r, Mall, lam_all)
            if hv is not None and ov is not None:
                cand.append((hv, ov, r["ppg"]))
        if len(cand) >= 30:
            X = np.array([[1.0, c[0], c[1]] for c in cand]); yv = np.array([c[2] for c in cand])
            RES["calAll"][p] = [round(float(v), 4) for v in np.linalg.lstsq(X, yv, rcond=None)[0]]
    RES["regAll"] = {p: [round(float(v), 4) for v in Mall[(p, "reg")]] for p in SKILL if (p, "reg") in Mall}
    P("  full-fit HIST + OPP calibration [a, b hist, c opp]: " + "; ".join(f"{p} {v}" for p, v in RES["calAll"].items()))
    RES["updated"] = time.strftime("%Y-%m-%d %H:%M")
    def seg_best(seg):
        s = next((x for x in RES["segments"] if x["seg"] == seg and x["pos"] == "ALL"), None)
        if not s:
            return ""
        b = min(s["models"].items(), key=lambda kv: kv[1]["mse"])
        return f"{seg}: best {b[0]} MSE {b[1]['mse']} (calibrated Clay {s['models'].get('CLAYCAL', {}).get('mse')}, Clay-free SHADOWCAL {s['models'].get('SHADOWCAL', {}).get('mse')})"
    RES["summary"] = "Opportunity prior, season PPG 2019-25 LOYO - " + "; ".join(x for x in (seg_best("stay"), seg_best("mover"), seg_best("rookie"), seg_best("all")) if x)
    with open(os.path.join(HERE, "data", "opp_prior_backtest.js"), "w", encoding="utf-8") as fh:
        fh.write("// built by backtest_opp_prior.py - opportunity prior (shares x team volume x value per opportunity) vs Clay and the history prior; shown on the ZONES tab\n")
        fh.write("window.SIM_OPPPRIOR_BT = "); json.dump(RES, fh, separators=(",", ":")); fh.write(";\n")
    P(f"\nwrote data/opp_prior_backtest.js: {RES['summary']}")
    P("done")


if __name__ == "__main__":
    main()
