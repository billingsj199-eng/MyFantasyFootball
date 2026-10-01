"""build_career_study_table.py - one row per backtest player: college profile + NFL career context.

Feeds the from-scratch model (scripts/jm_scratch_model.py) and the bust / late-hit study
(scripts/jm_outlier_study.py).

Inputs
  scripts/jm_table.json            (jm_extract_table.js: raw prospect fields + component scores)
  scripts/jm_outcome_grades.json   (build_outcome_grades.py: season values + career grade)
  data/weekly_stats_*.js           (season values for every NFL player -> teammate / QB context)
  data/wr_adv_career.js            (college aDOT, slot / wide / inline rate, YPRR ...)
  data/combine_data.js             (forty, vertical, broad, bench, cone, shuttle)
  pbp_cache: draft_picks.parquet, snap_counts_<yr>.parquet (2018+), injuries_<yr>.parquet (2019+),
             pff/pff_receiving_<yr>.csv + pff_rushing_<yr>.csv (2019+)

NFL context columns (seasons 1-3 unless noted; NaN when the source does not cover the year)
  n_avail3      share of team games played
  n_snap1..3    average offensive snap share in games played;  n_snapMax3
  n_first50     first season (1..) with a 50%+ snap share, NaN if never in six seasons
  n_out3        weeks listed Out / Doubtful on the injury report (2019+)
  n_slot3       PFF slot rate, route-weighted (WR / TE);  n_route3 = route participation
  n_pff3        PFF offense grade, snap/route weighted
  n_mateMax1    best season value of another player at his position on his team, rookie year
  n_mateMax3    same, averaged over seasons 1-3   (high = he shared the room with a star)
  n_matePrior   that position's best returning player on the team that drafted him (value the year before)
  n_qb3         best quarterback season value on his team, averaged over seasons 1-3
  n_teams4      distinct teams in the first four seasons

    python scripts/build_career_study_table.py [--table scripts/jm_table.json] [--out scripts/jm_study_table.json]
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import generate_extended_backtest as gb  # noqa: E402
import build_outcome_grades as bog  # noqa: E402

CACHE = os.path.join(os.path.dirname(ROOT), "pbp_cache")
LAST = 2025


def nrm(s):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", str(s or "").lower()))


def js_object(path, marker):
    """Evaluate a site data file with node and return window.<marker> (the files are JS, not JSON)."""
    import subprocess
    var = marker.split(".")[-1]
    js = "global.window={};require('vm').runInThisContext(require('fs').readFileSync(%s,'utf8'));process.stdout.write(JSON.stringify(window.%s||{}))" % (json.dumps(path), var)
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=120)
    return json.loads(r.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="scripts/jm_table.json")
    ap.add_argument("--grades", default="scripts/jm_outcome_grades.json")
    ap.add_argument("--out", default="scripts/jm_study_table.json")
    a = ap.parse_args()
    T = json.load(open(a.table, encoding="utf-8"))
    G = json.load(open(a.grades, encoding="utf-8"))["players"]

    # ---- league-wide season values (for teammate / QB context)
    data = gb.load_all_data()
    weekly = {}
    weekly.update(data["weekly_retired"]); weekly.update(data["weekly_active"])
    seas, posof = {}, {}
    for name, rec in weekly.items():
        if not isinstance(rec, dict):
            continue
        pos = rec.get("pos")
        pos = "RB" if pos == "HB" else pos
        if pos not in bog.CURVES:
            continue
        ss = [s for s in gb.get_player_seasons(rec) if s["yr"] <= LAST]
        if ss:
            seas[name] = ss; posof[name] = pos
    board = defaultdict(list)
    for name, ss in seas.items():
        for s in ss:
            if s["gp"] >= bog.RANK_MIN_GP:
                board[(s["yr"], posof[name])].append(s["ppg"])
    for k in board:
        board[k].sort(reverse=True)
    value = {}   # (nrm name, pos, yr) -> season value
    for name, ss in seas.items():
        pos = posof[name]
        for s in ss:
            lb = board.get((s["yr"], pos), [])
            rank = 1 + sum(1 for v in lb if v > s["ppg"])
            value[(nrm(name), pos, s["yr"])] = bog.curve(pos, rank) * min(1.0, s["gp"] / bog.FULL_GP) if s["gp"] >= 4 else 0.0

    # ---- snaps (2018+): per player-season games / snap share / team; team rooms by position
    snaps = []
    for yr in range(2018, LAST + 1):
        p = os.path.join(CACHE, "snap_counts_%d.parquet" % yr)
        if os.path.exists(p):
            d = pd.read_parquet(p, columns=["season", "game_type", "player", "pfr_player_id", "position", "team", "offense_snaps", "offense_pct"])
            snaps.append(d[d.game_type == "REG"])
    snaps = pd.concat(snaps)
    snaps["position"] = snaps.position.replace({"HB": "RB", "FB": "RB"})
    sk = snaps[snaps.position.isin(["QB", "RB", "WR", "TE"])]
    played = sk[sk.offense_snaps > 0]
    ps = played.groupby(["pfr_player_id", "season"]).agg(games=("offense_snaps", "size"), snap=("offense_pct", "mean"),
                                                         team=("team", lambda x: x.mode().iat[0]), player=("player", "first"), position=("position", "first")).reset_index()
    by_pfr = {(r.pfr_player_id, r.season): r for r in ps.itertuples()}
    room = defaultdict(list)   # (team, season, pos) -> [(nrm name, pfr id)]
    for r in ps.itertuples():
        room[(r.team, r.season, r.position)].append((nrm(r.player), r.pfr_player_id))

    # ---- draft picks -> pfr / gsis ids
    dp = pd.read_parquet(os.path.join(CACHE, "draft_picks.parquet"))
    dp = dp[dp.season >= 2017]
    dkey = {(nrm(r.pfr_player_name), int(r.season)): r for r in dp.itertuples()}
    dpick = {(int(r.season), int(r.pick)): r for r in dp.itertuples()}

    # ---- injuries (2019+)
    inj = []
    for yr in range(2019, LAST + 1):
        p = os.path.join(CACHE, "injuries_%d.parquet" % yr)
        if os.path.exists(p):
            d = pd.read_parquet(p, columns=["season", "game_type", "gsis_id", "report_status"])
            inj.append(d[(d.game_type == "REG") & d.report_status.isin(["Out", "Doubtful"])])
    inj = pd.concat(inj).groupby(["gsis_id", "season"]).size().to_dict()

    # ---- PFF NFL (2019+)
    pff_rec, pff_rush = {}, {}
    for yr in range(2019, LAST + 1):
        p = os.path.join(CACHE, "pff", "pff_receiving_%d.csv" % yr)
        if os.path.exists(p):
            for r in pd.read_csv(p).itertuples():
                pff_rec[(nrm(r.player), "RB" if r.position in ("HB", "FB") else r.position, yr)] = r
        p = os.path.join(CACHE, "pff", "pff_rushing_%d.csv" % yr)
        if os.path.exists(p):
            for r in pd.read_csv(p).itertuples():
                pff_rush[(nrm(r.player), "RB" if r.position in ("HB", "FB") else r.position, yr)] = r

    # ---- college extras
    wradv = js_object("data/wr_adv_career.js", "window._WR_ADV_CAREER")
    wr_norm = {nrm(k): v for k, v in wradv.items()}
    cb = json.loads(open("data/combine_data.js", encoding="utf-8").read().split("=", 1)[1].strip().rstrip(";"))

    out, cov = [], defaultdict(int)
    for r in T["rows"]:
        name, pos, dy = r["name"], r["pos"], r["o_yr"]
        g = G.get("%s|%d" % (name, dy)) or {}
        row = {k: v for k, v in r.items() if k not in ("comps", "o_raw")}
        for k, v in (r.get("comps") or {}).items():
            row["c_" + k] = v
        row.update({"career": g.get("grade"), "elite": g.get("elite"), "starter": g.get("starter"), "provisional": g.get("provisional"),
                    "elapsed": g.get("elapsed"), "best": g.get("best"), "seasons": g.get("seasons")})
        pick = r.get("o_pick")
        d = dkey.get((nrm(name), dy)) or dkey.get((nrm(r["o_raw"]["n"]), dy)) or (dpick.get((dy, int(pick))) if isinstance(pick, (int, float)) and pick == pick else None)
        pfr = getattr(d, "pfr_player_id", None) if d is not None else None
        gsis = getattr(d, "gsis_id", None) if d is not None else None
        row["draftTeam"] = getattr(d, "team", None) if d is not None else None
        if pfr is None:   # undrafted: find by name + position in the snap table
            hits = ps[(ps.player.map(nrm) == nrm(name)) & (ps.position == pos) & (ps.season >= dy)]
            pfr = hits.pfr_player_id.iat[0] if len(hits) else None
        cov["pfr"] += pfr is not None
        team_games = lambda y: 16 if y <= 2020 else 17
        sn, gms, teams, mates, qbs, slot_w, slot_r, route_w, pffg, pffw, outw = [], [], [], [], [], 0.0, 0.0, [], 0.0, 0.0, 0
        first50 = np.nan
        for i in range(6):
            yr = dy + i
            if yr > LAST:
                break
            s = by_pfr.get((pfr, yr)) if pfr else None
            if i < 3:
                if yr >= 2018:
                    sn.append(s.snap if s is not None else 0.0)
                    gms.append((s.games if s is not None else 0) / team_games(yr))
                else:
                    sn.append(np.nan); gms.append(np.nan)
                if gsis and yr >= 2019:
                    outw += inj.get((gsis, yr), 0)
            if s is not None:
                if i < 4:
                    teams.append(s.team)
                if np.isnan(first50) and s.snap >= 0.5 and s.games >= 6:
                    first50 = i + 1
                if i < 3:
                    others = [value.get((nm, pos, yr), 0.0) for nm, pid in room.get((s.team, yr, pos), []) if pid != pfr]
                    mates.append(max(others) if others else 0.0)
                    qv = [value.get((nm, "QB", yr), 0.0) for nm, pid in room.get((s.team, yr, "QB"), []) if pid != pfr]
                    qbs.append(max(qv) if qv else 0.0)
                    pr = pff_rec.get((nrm(name), pos, yr))
                    if pr is not None and pr.routes and pr.routes == pr.routes:
                        slot_w += pr.routes; slot_r += pr.routes * (pr.slot_rate or 0)
                        route_w.append(pr.route_rate)
                        pffg += pr.routes * (pr.grades_offense or 0); pffw += pr.routes
                    pu = pff_rush.get((nrm(name), pos, yr))
                    if pu is not None and pos == "RB" and pu.attempts == pu.attempts and pu.attempts:
                        pffg += pu.attempts * (pu.grades_offense or 0); pffw += pu.attempts
        # the room he was drafted into: best returning player at the position (value the year before)
        prior = np.nan
        t0 = row["draftTeam"]
        TEAM_FIX = {"GNB": "GB", "KAN": "KC", "NWE": "NE", "NOR": "NO", "SFO": "SF", "TAM": "TB", "LVR": "LV", "OAK": "LV", "SDG": "LAC", "STL": "LA", "LAR": "LA"}
        t0 = TEAM_FIX.get(t0, t0)
        if t0 and dy - 1 >= 2018:
            first = by_pfr.get((pfr, dy)) if pfr else None
            tm = first.team if first is not None else t0
            stay = {nm for nm, pid in room.get((tm, dy, pos), []) if pid != pfr}
            vals = [value.get((nm, pos, dy - 1), 0.0) for nm, pid in room.get((tm, dy - 1, pos), []) if nm in stay]
            prior = max(vals) if vals else 0.0
        an = lambda x: float(np.nanmean(x)) if len(x) and not np.all(np.isnan(x)) else np.nan
        row.update({
            "n_avail3": an(gms), "n_snap1": sn[0] if len(sn) > 0 else np.nan, "n_snap2": sn[1] if len(sn) > 1 else np.nan, "n_snap3": sn[2] if len(sn) > 2 else np.nan,
            "n_snapMax3": float(np.nanmax(sn)) if len(sn) and not np.all(np.isnan(sn)) else np.nan, "n_first50": first50,
            "n_out3": outw if (gsis and dy + 2 >= 2019) else np.nan,
            "n_slot3": slot_r / slot_w if slot_w else np.nan, "n_route3": an(route_w), "n_pff3": pffg / pffw if pffw else np.nan,
            "n_mateMax1": mates[0] if mates else np.nan, "n_mateMax3": an(mates), "n_matePrior": prior, "n_qb3": an(qbs), "n_teams4": len(set(teams)) if teams else np.nan,
        })
        w = wradv.get(name) or wr_norm.get(nrm(name)) or {}
        for k in ("adot", "slotRate", "wideRate", "inlineRate", "yprr", "contestedRate", "dropRate", "yacPerRec"):
            row["k_" + k] = w.get(k)
        c = cb.get(name) or {}
        for k in ("forty", "vert", "broad", "bench", "cone", "shuttle"):
            v = c.get(k)
            row["t_" + k] = float(v) if isinstance(v, (int, float)) else None
        cov["snap"] += not np.isnan(row["n_snapMax3"]) if row["n_snapMax3"] is not None else 0
        cov["pff"] += pffw > 0
        cov["wradv"] += bool(w)
        out.append(row)

    def clean(o):
        if isinstance(o, float) and (np.isnan(o) or np.isinf(o)):
            return None
        if isinstance(o, (np.floating, np.integer)):
            return clean(float(o))
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(v) for v in o]
        return o
    json.dump(clean({"rows": out}), open(a.out, "w", encoding="utf-8"), separators=(",", ":"))
    print("rows %d | matched to an NFL id %d | with snap data %d | with PFF NFL data %d | with college alignment %d -> %s" % (
        len(out), cov["pfr"], cov["snap"], cov["pff"], cov["wradv"], a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
