#!/usr/bin/env python3
"""
Harness patch for MID-SEASON TEAM CHANGES (Jack 2026-10-20, MHJ). Research only - imported by research_midseason_trade.py,
changes nothing on disk except reading.

The shared harness (backtest_noclay_weekly.build_samples / bt_common.iter_samples) gives a player ONE team per season via
infer_team (70%+ schedule match): a mid-season mover is either dropped (21 of 31 pool movers 2019-24) or keeps one team's
Vegas / opponent for every week; retired-file records have no opponent at all, and 2025 records carry the CURRENT team's
schedule (Meyers 2025 = JAX all season). This patch, for mover player-seasons only (snap_counts show 2+ teams), gives each
row the team he actually played for that week (snap_counts), the opponent / Vegas / FPA of that game, and rebuilds the
mover rows of ctx_features in memory with season-to-date usage over ALL his games, any team (what the live engine reads:
SIM_XFP / SIM_SNAPS are keyed by player, not team). Every non-mover row is untouched.
"""
import os, sys, json, pickle
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_common as B
import backtest_sim_calibration as cal
import backtest_noclay_weekly as NW
import build_context_features as BCF

MG = pickle.load(open(os.path.join(HERE, "_tmp", "mst", "mover_games.pkl"), "rb"))
MOVERS = {k: v for k, v in MG.items() if v["events"]}
_LAST_S = {}
STATS = defaultdict(int)

def team_of(Y, pid, wk):
    v = MOVERS.get((Y, pid))
    if not v: return None
    w = v["weeks"]
    if wk in w: return w[wk]["team"]
    prev = [x for x in w if x <= wk]
    return w[max(prev)]["team"] if prev else w[min(w)]["team"]

def build_samples():
    """backtest_noclay_weekly.build_samples with per-week teams for mover player-seasons (copied 2026-10-20; non-movers identical)"""
    resolve = B.player_ids()
    n_ahead = NW.build_shares()
    pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "birth_date", "rookie_season"])
    birth = {r.gsis_id: pd.to_datetime(r.birth_date, errors="coerce") for r in pl.itertuples(index=False) if isinstance(r.gsis_id, str)}
    rook = {r.gsis_id: (int(r.rookie_season) if pd.notna(r.rookie_season) else None) for r in pl.itertuples(index=False) if isinstance(r.gsis_id, str)}
    dp = pd.read_parquet(os.path.join(B.CACHE, "draft_picks.parquet"), columns=["season", "round", "pick", "gsis_id"])
    draft = {r.gsis_id: (int(r.season), int(r.round), int(r.pick)) for r in dp.itertuples(index=False) if isinstance(r.gsis_id, str)}
    preds = json.load(open(os.path.join(HERE, "opp_prior_preds.json"), encoding="utf-8"))
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    weekly_fpa, season_fpa, lg_fpa = NW.build_fpa()
    out = []; miss = defaultdict(int)
    for Y in NW.YEARS:
        games = B.load_games(Y)
        imps = [v["implied"] for v in games.values() if v["implied"] is not None]
        avg = float(np.mean(imps)); W = 16 if Y <= 2020 else 17
        for name, c in clay_hist[str(Y)].items():
            pos = c.get("pos")
            if pos not in NW.POS4 or (c.get("pts") or 0) < cal.POOL_MIN_PTS:
                continue
            wrec = cal.weekly_rec(name, pos)
            if wrec is None: miss["weekly"] += 1; continue
            pid = resolve(name, pos, Y)
            mover = pid is not None and (Y, pid) in MOVERS
            team = cal.infer_team(wrec, Y)
            if mover:
                wk0 = min(MOVERS[(Y, pid)]["weeks"]); team = team_of(Y, pid, wk0); STATS["mover_ps"] += 1
            if not team: miss["team"] += 1; continue
            team_prev = cal.infer_team(wrec, Y - 1)
            if pid is not None and (Y - 1, pid) in MOVERS:
                wl = MOVERS[(Y - 1, pid)]["weeks"]; team_prev = wl[max(wl)]["team"]
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            num = den = 0.0; h3g = 0
            for i, yy in enumerate((Y - 1, Y - 2, Y - 3)):
                pts = NW.season_pts(wrec, yy)
                if len(pts) >= NW.MIN_SEASON_G:
                    num += NW.W3[i] * (sum(pts) / len(pts)); den += NW.W3[i]; h3g += len(pts)
            h3 = num / den if (den > 0 and h3g >= NW.MIN_H3_G) else None
            prior_games = []
            for yy in (Y - 2, Y - 1, Y):
                for w in wrec.get("seasons", {}).get(str(yy), []):
                    if cal.played(w) and isinstance(w.get("fpts"), (int, float)):
                        prior_games.append((yy, int(w["wk"]), float(w["fpts"])))
            prior_games.sort()
            bd = birth.get(pid) if pid else None
            age = ((pd.Timestamp(year=Y, month=9, day=1) - bd).days / 365.25) if (bd is not None and pd.notna(bd)) else np.nan
            dr = draft.get(pid) if pid else None
            rs = rook.get(pid) if pid else None
            is_rookie = bool((rs == Y) or (dr and dr[0] == Y))
            exp = (Y - rs) if rs is not None else np.nan
            rnd = dr[1] if (dr and dr[0] == Y) else (8 if is_rookie else 0)
            pick = float(dr[2]) if (dr and dr[0] == Y) else (262.0 if is_rookie else np.nan)
            nah = n_ahead(cal.norm(name), pos, team, Y) if is_rookie else np.nan
            pr = preds.get(f"{Y}|{pid}") if pid else None
            opp_cal = pr.get("SHADOWCAL") if pr else None
            seg = pr.get("seg") if pr else None
            rows = sorted([(int(w["wk"]), float(w["fpts"]), cal.OPP_ALIAS.get(w.get("opp"), w.get("opp")))
                           for w in wrec.get("seasons", {}).get(str(Y), []) if cal.played(w) and isinstance(w.get("fpts"), (int, float))])
            hist = []
            for wk, fpts, opp in rows:
                tw_ = team_of(Y, pid, wk) if mover else team
                gm = games.get((tw_, wk))
                if mover and gm: opp = gm["opp"]
                if gm and gm["implied"] is not None and opp:
                    g = len(hist); ppg = (sum(hist) / g) if g else 0.0
                    veg = min(1.35, max(0.7, 1 + B.VEG[pos] * (gm["implied"] - avg) / avg))
                    cur = weekly_fpa.get((Y, opp, pos), {}); past = [w for w in cur if w < wk]
                    fpa = 1.0
                    if past and lg_fpa.get((Y, pos)):
                        ratio = min(1.25, max(0.8, (sum(cur[w] for w in past) / len(past)) / lg_fpa[(Y, pos)]))
                        fpa = 1 + B.FPA_E * (ratio - 1) * min(1, len(past) / B.FPA_TRUST_G)
                    tail = [f for (yy, ww, f) in prior_games if (yy, ww) < (Y, wk)][-8:]
                    l8 = (sum(tail) / len(tail)) if len(tail) >= NW.MIN_L8_G else None
                    out.append({"year": Y, "name": name, "pos": pos, "team": tw_, "pid": pid, "wk": wk, "act": fpts, "g": g, "ppg": ppg,
                                "clay": clay_pg, "layers": veg * fpa, "h3": h3, "h3g": h3g, "l8": l8, "l8g": len(tail), "age": age,
                                "rookie": is_rookie, "exp": exp, "rnd": rnd, "mover": bool(team_prev and team_prev != team),
                                "oppcal": opp_cal, "seg": seg, "pick": pick, "nahead": nah})
                    if mover:
                        _LAST_S[(Y, pid, wk)] = dict(name=name, pos=pos, team=tw_, opp=opp, veg=veg, implied=gm["implied"], opp_implied=gm.get("oppImplied"), ppg=ppg, g=g)
                        STATS["mover_rows"] += 1
                    hist.append(fpts)
                elif mover:
                    STATS["mover_rows_skipped"] += 1
    print(f"  [mst patch] samples {len(out)}; skipped {dict(miss)}; movers {dict(STATS)}")
    return out

USAGE_COLS = ["xfp_pg", "snap_l1", "snap_std", "snap_trend", "snapmult", "tgt_sh", "car_sh", "ay_sh", "tgt_sh_l3", "car_sh_l3", "tgt_trend", "car_trend", "pts_over_xfp",
              "veg", "implied", "opp_implied", "game_total", "team", "opp", "qb_out", "wopr", "db_sh", "att_pg"]
_CTX = {}

def mover_ctx_rows(C):
    """replace / add ctx rows for every mover player-week in the patched samples"""
    pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "rookie_season", "birth_date"])
    rk = {r.gsis_id: (int(r.rookie_season) if pd.notna(r.rookie_season) else None) for r in pl.itertuples(index=False) if isinstance(r.gsis_id, str)}
    bd = {r.gsis_id: pd.to_datetime(r.birth_date, errors="coerce") for r in pl.itertuples(index=False) if isinstance(r.gsis_id, str)}
    dp = pd.read_parquet(os.path.join(B.CACHE, "draft_picks.parquet"), columns=["season", "pick", "gsis_id"])
    draft = {r.gsis_id: (int(r.season), int(r.pick)) for r in dp.itertuples(index=False) if isinstance(r.gsis_id, str)}
    keyset = {(Y, pid) for (Y, pid, wk) in _LAST_S}
    isk = np.array([(int(y), p) in keyset for y, p in zip(C.year, C.pid)])
    orig = C[isk]; base = C[~isk]
    tmpl = {}
    for r in orig.to_dict("records"): tmpl[(int(r["year"]), r["pid"], int(r["wk"]))] = r
    new = []
    for (Y, pid, wk), s in sorted(_LAST_S.items()):
        same = tmpl.get((Y, pid, wk))
        cand = [k for k in tmpl if k[0] == Y and k[1] == pid]
        t0 = dict(same) if same else (dict(tmpl[min(cand, key=lambda k: abs(k[2] - wk))]) if cand else {c: np.nan for c in C.columns})
        r = t0
        r.update(year=Y, pid=pid, wk=wk, name=s["name"], pos=s["pos"])
        if not cand:
            rs = rk.get(pid); r["rookie"] = float(rs == Y) if rs else np.nan; r["yr2"] = float(rs == Y - 1) if rs else np.nan; r["exp"] = (Y - rs) if rs else np.nan
            b = bd.get(pid); r["age"] = ((pd.Timestamp(year=Y, month=9, day=1) - b).days / 365.25) if (b is not None and pd.notna(b)) else np.nan
            d = draft.get(pid); r["draft_pick"] = d[1] if d else np.nan; r["undrafted"] = float(d is None)
        M = MOVERS[(Y, pid)]["weeks"]; past = sorted(w for w in M if w < wk)
        tot = defaultdict(float)
        for w in past:
            for k in ("tg", "team_tg", "car", "team_car", "xfp", "ay", "team_ay", "db", "team_db"): tot[k] += M[w][k]
        ng = max(len(past), 1)
        sh = lambda a, b: tot[a] / tot[b] if tot[b] else np.nan
        r["xfp_pg"] = tot["xfp"] / ng if past else np.nan
        r["tgt_sh"] = sh("tg", "team_tg"); r["car_sh"] = sh("car", "team_car"); r["ay_sh"] = sh("ay", "team_ay"); r["db_sh"] = sh("db", "team_db")
        r["wopr"] = 1.5 * (r["tgt_sh"] if pd.notna(r["tgt_sh"]) else 0) + 0.7 * (r["ay_sh"] if pd.notna(r["ay_sh"]) else 0)
        l3 = past[-3:]; l3t = defaultdict(float)
        for w in l3:
            for k in ("tg", "team_tg", "car", "team_car"): l3t[k] += M[w][k]
        r["tgt_sh_l3"] = l3t["tg"] / l3t["team_tg"] if l3t["team_tg"] else np.nan; r["car_sh_l3"] = l3t["car"] / l3t["team_car"] if l3t["team_car"] else np.nan
        r["tgt_trend"] = r["tgt_sh_l3"] - r["tgt_sh"] if pd.notna(r["tgt_sh_l3"]) and pd.notna(r["tgt_sh"]) else np.nan
        r["car_trend"] = r["car_sh_l3"] - r["car_sh"] if pd.notna(r["car_sh_l3"]) and pd.notna(r["car_sh"]) else np.nan
        sn = {w: M[w]["snap"] for w in M}
        sp = [sn[w] for w in past]
        r["snap_std"] = float(np.mean(sp)) if sp else np.nan; r["snap_l1"] = sp[-1] if sp else np.nan
        r["snap_trend"] = (float(np.mean(sp[-3:])) - r["snap_std"]) if len(sp) >= 3 else np.nan
        r["snapmult"] = BCF.snap_mult(sn, wk)
        r["pts_over_xfp"] = s["ppg"] - r["xfp_pg"] if s["pos"] != "QB" and pd.notna(r["xfp_pg"]) else np.nan
        r["veg"] = s["veg"]; r["implied"] = s["implied"]; r["opp_implied"] = s["opp_implied"]
        r["game_total"] = (s["implied"] + s["opp_implied"]) if s["opp_implied"] is not None else np.nan
        if not (same and same.get("team") == s["team"]): r["qb_out"] = 0.0
        r["team"] = s["team"]; r["opp"] = s["opp"]
        new.append(r)
    N = pd.DataFrame(new)
    for c in C.columns:
        if c not in N.columns: N[c] = np.nan
    out = pd.concat([base, N[C.columns].astype(C.dtypes.to_dict(), errors="ignore")], ignore_index=True)
    print(f"  [mst patch] ctx rows: {len(C)} -> {len(out)} (mover player-seasons {len(keyset)}, original rows replaced {len(orig)}, mover rows now {len(N)})")
    return out

_read_parquet = pd.read_parquet
def read_parquet(path, *a, **k):
    if os.path.basename(str(path)) == "ctx_features.parquet":
        cols = k.pop("columns", None)
        if "full" not in _CTX:
            _CTX["full"] = mover_ctx_rows(_read_parquet(path, *a, **k)) if _LAST_S else _read_parquet(path, *a, **k)
        D = _CTX["full"]
        return D[cols].copy() if cols is not None else D.copy()
    return _read_parquet(path, *a, **k)

def install():
    NW.build_samples = build_samples
    pd.read_parquet = read_parquet
    print(f"  [mst patch] installed: {len(MOVERS)} mover player-seasons in the snap data")
