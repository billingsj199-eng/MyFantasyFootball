#!/usr/bin/env python3
"""
CONTEXT FEATURE TABLE (2026-09-16) - step 1 of the joint context model.

Jack: "create the ultimate projections ... context to all players based on new situations, prospect model or any
variable that can be different for each player, with coaching and play calling tendencies along with injury
vacancies" -> "start on steps 1 and 2 and lets backtest it all before we actually apply it".

One row per bt_common player-week 2019-25 (QB/RB/WR/TE, week 2+, same rows every layer was graded on) with the
shipped projection and every variable KNOWN BEFORE KICKOFF side by side. Nothing here changes the engine.

  base2        shipped (P=5 Clay/PPG blend x Vegas x FPA) x snapMult (the shipped snap-trend layer)
  usage        season-to-date (weeks < this week, games he played) target / carry / red-zone / goal-line /
               air-yard shares, WOPR, xFP per game, points over xFP, last-3 shares and trends, snap share
               (season, last game, trend), QB dropback share and attempts
  prior        last season: target / carry share, xFP per game, PPG, games, team change
  team         team pass rate over expected (neutral downs, season-to-date and last season), plays per game
  coach        new head coach / new playcaller vs last season; the playcaller's own history (prior seasons, any
               team): pass rate over expected, RB and TE target share, RB1 carry share, plays per game
  vacancy      teammates with season-to-date work who are OUT this week (final injury report Out/Doubtful,
               or roster status IR / cut / practice squad / gone): vacated target and carry share (all, same
               position), the player's expected inheritance (his share of the healthy same-position room), top QB out
  own_injury   his own final report status and last practice (ALREADY SHIPPED live as the banged-up docks)
  prospect     draft pick, experience, age, JM prospect score (JM weights were tuned with hindsight - read with care)
  env          implied total, opponent implied, spread, game total, dome, precipitation, wind, temperature, kickoff hour
  matchup      opponent FPA (shipped), opponent man-coverage rate (PFF, season-to-date and last season), the
               player's yards per route vs man and vs zone (last season + to date, shrunk), man-zone gap x opp man rate

Output: sim_lab/ctx_features.parquet (+ ctx_features_groups.json). Run: python build_context_features.py
"""
import glob, json, math, os, re, sys, time
from collections import defaultdict, Counter
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B
from bt_common import iter_samples, POS4
from pull_pace_tracker import _xfp_ab, _xtd_rec, _xfp_rush, _xtd, XFP_CATCH, XFP_TGT_YDS
import build_scheme as BS

CACHE = B.CACHE
YEARS = list(range(2019, 2026))
OUT = os.path.join(HERE, "ctx_features.parquet")
SNAP_W = [0.5, 0.3, 0.2]
ABSENT_ROSTER = {"RES", "CUT", "DEV", "RET", "EXE", "PUP", "NFI", "SUS", "TRC", "TRD", "TRT"}
REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"

GROUPS = {
    "base": ["pos_qb", "pos_rb", "pos_wr", "pos_te", "wk", "g", "ppg", "clay", "base2", "veg", "fpa_mult", "ppg_over_clay", "snapmult"],
    "usage": ["tgt_sh", "car_sh", "rz_tgt_sh", "rz_car_sh", "gl_car_sh", "ay_sh", "wopr", "xfp_pg", "pts_over_xfp", "tgt_sh_l3", "car_sh_l3",
              "tgt_trend", "car_trend", "snap_std", "snap_l1", "snap_trend", "db_sh", "att_pg"],
    "prior": ["tgt_sh_py", "car_sh_py", "xfp_pg_py", "ppg_py", "g_py", "team_change"],
    "team": ["proe_std", "proe_py", "plays_pg_std", "plays_pg_py"],
    "coach": ["new_hc", "new_pc", "pc_seasons", "pc_proe", "pc_rb_tgt", "pc_te_tgt", "pc_rb1_car", "pc_plays_pg"],
    "vacancy": ["vac_tgt", "vac_car", "vac_tgt_same", "vac_car_same", "inherit_tgt", "inherit_car", "qb_out"],
    "own_injury": ["rep_q", "rep_d", "prac_dnp", "prac_lim"],
    "prospect": ["draft_pick", "undrafted", "exp", "age", "jm", "rookie", "yr2"],
    "env": ["implied", "opp_implied", "spread", "game_total", "dome", "precip", "wind", "temp", "hour"],
    "matchup": ["opp_man_std", "opp_man_py", "yprr_man", "yprr_zone", "man_gap_x_opp"],
    "oline": ["ol_pb_full", "ol_rb_full", "ol_pb_now", "ol_rb_now", "ol_pb_drop", "ol_rb_drop", "ol_best_pb", "ol_worst_pb_now", "ol_out_n", "ol_q_n"],
}
OL_KEYS = GROUPS["oline"]


def P(*a):
    print(" ".join(str(x) for x in a), flush=True)


def norm(n):
    return B.cal.norm(str(n))


def load_positions():
    p = pd.read_csv(os.path.join(CACHE, "players.csv"), usecols=["gsis_id", "position", "display_name", "birth_date", "rookie_season"], low_memory=False)
    pos, bd, rook = {}, {}, {}
    for r in p.itertuples(index=False):
        if not isinstance(r.gsis_id, str):
            continue
        pos[r.gsis_id] = "RB" if r.position == "FB" else r.position
        bd[r.gsis_id] = pd.to_datetime(r.birth_date, errors="coerce") if isinstance(r.birth_date, str) else pd.NaT
        rook[r.gsis_id] = int(r.rookie_season) if pd.notna(r.rookie_season) else None
    return pos, bd, rook


# ---------------- pbp: player-week and team-week tables ----------------
def pbp_tables(Y, pos_of):
    cols = ["season_type", "week", "posteam", "pass_attempt", "rush_attempt", "sack", "qb_dropback", "two_point_attempt",
            "receiver_player_id", "rusher_player_id", "passer_player_id", "yardline_100", "air_yards", "complete_pass",
            "pass_touchdown", "rush_touchdown", "td_player_id", "pass_oe", "wp", "down"]
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), usecols=cols, low_memory=False)
    df = df[(df.season_type == "REG") & df.posteam.notna() & (df.two_point_attempt.fillna(0) != 1)].copy()
    df["tm"] = df.posteam.map(lambda t: B.tm(str(t)))
    df["week"] = df.week.astype(int)
    yl = df.yardline_100.fillna(50.0)
    pw = defaultdict(lambda: defaultdict(float)); ptm = {}
    tw = defaultdict(lambda: defaultdict(float))
    # targets
    pa = df[(df.pass_attempt == 1) & (df.sack != 1)]
    for r, y in zip(pa.itertuples(index=False), yl[pa.index]):
        t, wk = r.tm, r.week
        tw[(t, wk)]["att"] += 1
        rcv = r.receiver_player_id
        if not isinstance(rcv, str):
            continue
        a = float(r.air_yards) if pd.notna(r.air_yards) else 0.0
        tw[(t, wk)]["tg"] += 1; tw[(t, wk)]["ay"] += max(a, 0.0); tw[(t, wk)]["rz_tg"] += y <= 20
        rp = pos_of.get(rcv)
        if rp in ("RB", "WR", "TE"):
            tw[(t, wk)]["tg_" + rp] += 1
        q = pw[(rcv, wk)]; ptm[(rcv, wk)] = t
        b = _xfp_ab(a)
        q["tg"] += 1; q["ay"] += a; q["rz_tg"] += y <= 20
        q["xfp"] += 0.5 * XFP_CATCH[b] + 0.1 * XFP_TGT_YDS[b] + 6 * _xtd_rec(y, a >= y)
    # carries
    ru = df[(df.rush_attempt == 1) & df.rusher_player_id.notna()]
    for r, y in zip(ru.itertuples(index=False), yl[ru.index]):
        t, wk, pid = r.tm, r.week, r.rusher_player_id
        rp = pos_of.get(pid)
        q = pw[(pid, wk)]; ptm[(pid, wk)] = t
        q["car"] += 1; q["rz_car"] += y <= 20; q["gl_car"] += y <= 5
        q["xfp"] += 0.1 * _xfp_rush(y, False) + 6 * _xtd(y, True)
        if rp != "QB":
            tw[(t, wk)]["car"] += 1; tw[(t, wk)]["rz_car"] += y <= 20; tw[(t, wk)]["gl_car"] += y <= 5
            if rp == "RB":
                tw[(t, wk)]["car_RB"] += 1
    # dropbacks
    db = df[(df.qb_dropback == 1)]
    for r in db.itertuples(index=False):
        t, wk = r.tm, r.week
        tw[(t, wk)]["db"] += 1
        if isinstance(r.passer_player_id, str):
            q = pw[(r.passer_player_id, wk)]; ptm.setdefault((r.passer_player_id, wk), t)
            q["db"] += 1; q["att"] += (r.pass_attempt == 1 and r.sack != 1)
    # plays + neutral pass rate over expected
    pl = df[(df.pass_attempt == 1) | (df.rush_attempt == 1)]
    for (t, wk), n in pl.groupby(["tm", "week"]).size().items():
        tw[(t, wk)]["plays"] = float(n)
    neu = df[df.pass_oe.notna() & df.wp.between(0.2, 0.8) & df.down.isin([1, 2, 3])]
    for (t, wk), g in neu.groupby(["tm", "week"]).pass_oe:
        tw[(t, wk)]["proe_sum"] = float(g.sum()); tw[(t, wk)]["proe_n"] = float(len(g))
    return pw, ptm, tw


def team_season(tw, t, weeks=None):
    s = defaultdict(float); n = 0
    for (tt, wk), v in tw.items():
        if tt == t and (weeks is None or wk in weeks):
            n += 1
            for k, x in v.items():
                s[k] += x
    return s, n


def load_snaps(Y):
    d = pd.read_parquet(os.path.join(CACHE, f"snap_counts_{Y}.parquet"), columns=["week", "game_type", "player", "position", "team", "offense_snaps", "offense_pct"])
    d = d[(d.game_type == "REG") & (d.offense_snaps > 0)]
    out = defaultdict(dict)
    for r in d.itertuples(index=False):
        out[(norm(r.player), B.tm(str(r.team)))][int(r.week)] = 100.0 * float(r.offense_pct)
    return out


def snap_mult(wkpct, wk):
    past = sorted([w for w in wkpct if w < wk], reverse=True)
    if len(past) < 2 or past[0] < wk - 3:
        return 1.0
    rec = sum(wkpct[w] * SNAP_W[i] for i, w in enumerate(past[:3])) / sum(SNAP_W[:len(past[:3])])
    avg = float(np.mean([wkpct[w] for w in past]))
    return min(1.30, max(0.75, 1 + (rec - avg) / 100.0))


def injuries(Y):
    d = pd.read_parquet(os.path.join(CACHE, f"injuries_{Y}.parquet"), columns=["game_type", "team", "week", "gsis_id", "full_name", "report_status", "practice_status"])
    d = d[d.game_type == "REG"]
    out, by_name = {}, {}
    for r in d.itertuples(index=False):
        rec = (str(r.report_status or ""), str(r.practice_status or ""))
        t = B.tm(str(r.team))
        if isinstance(r.gsis_id, str):
            out[(t, int(r.week), r.gsis_id)] = rec
        by_name[(t, int(r.week), norm(r.full_name))] = rec
    return out, by_name


# ---------------- offensive line: individual linemen, updated for injuries ----------------
OL_K = 300.0


def ol_context(Y, inj_name):
    """(team, wk) -> OL features. Expected starting five = the five C/G/T with the most snap share in weeks before
    this one (this season). Each graded by LAST season's PFF pass-block / run-block grade (shrunk to replacement by
    snaps; rookies and unknowns = replacement). 'now' swaps starters on this week's final report as Out/Doubtful for
    replacement level. No current-season grades (they would leak the game being projected)."""
    sc = pd.read_parquet(os.path.join(CACHE, f"snap_counts_{Y}.parquet"), columns=["week", "game_type", "player", "position", "team", "offense_pct"])
    sc = sc[(sc.game_type == "REG") & sc.position.isin(["C", "G", "T"]) & (sc.offense_pct > 0)]
    tw = defaultdict(dict)
    for r in sc.itertuples(index=False):
        tw[(B.tm(str(r.team)), int(r.week))][norm(r.player)] = float(r.offense_pct)
    gp = os.path.join(CACHE, "pff", f"pff_blocking_{Y-1}.csv")
    grades, rep_pb, rep_rb = {}, np.nan, np.nan
    if os.path.exists(gp):
        g = pd.read_csv(gp)
        g = g[g.position.isin(["C", "G", "T"])]
        for r in g.itertuples(index=False):
            n = float(r.snap_counts_offense or 0)
            if n > 0 and pd.notna(r.grades_pass_block):
                k = norm(r.player)
                o = grades.get(k)
                if o is None or n > o[2]:
                    grades[k] = (float(r.grades_pass_block), float(r.grades_run_block), n)
        reg = g[g.snap_counts_offense.between(150, 600)]
        rep_pb, rep_rb = float(reg.grades_pass_block.median()), float(reg.grades_run_block.median())
    out = {}
    teams = {t for (t, _) in tw}
    for t in teams:
        wks = sorted(w for (tt, w) in tw if tt == t)
        for wk in range(2, 19):
            acc = Counter()
            for w in wks:
                if w < wk:
                    for nm, pct in tw[(t, w)].items():
                        acc[nm] += pct
            if not acc:
                continue
            five = [nm for nm, _ in acc.most_common(5)]
            if np.isnan(rep_pb):
                out[(t, wk)] = {"ol_out_n": float(sum(inj_name.get((t, wk, nm), ("", ""))[0] in ("Out", "Doubtful") for nm in five)),
                                "ol_q_n": float(sum(inj_name.get((t, wk, nm), ("", ""))[0] == "Questionable" for nm in five))}
                continue
            pb_full, rb_full, pb_now, rb_now, n_out, n_q = [], [], [], [], 0, 0
            for nm in five:
                gr = grades.get(nm)
                pb = (gr[0] * gr[2] + rep_pb * OL_K) / (gr[2] + OL_K) if gr else rep_pb
                rb = (gr[1] * gr[2] + rep_rb * OL_K) / (gr[2] + OL_K) if gr else rep_rb
                st = inj_name.get((t, wk, nm), ("", ""))[0]
                pb_full.append(pb); rb_full.append(rb)
                if st in ("Out", "Doubtful"):
                    n_out += 1; pb_now.append(rep_pb); rb_now.append(rep_rb)
                else:
                    pb_now.append(pb); rb_now.append(rb)
                    n_q += st == "Questionable"
            out[(t, wk)] = {"ol_pb_full": float(np.mean(pb_full)), "ol_rb_full": float(np.mean(rb_full)),
                            "ol_pb_now": float(np.mean(pb_now)), "ol_rb_now": float(np.mean(rb_now)),
                            "ol_pb_drop": float(np.mean(pb_full) - np.mean(pb_now)), "ol_rb_drop": float(np.mean(rb_full) - np.mean(rb_now)),
                            "ol_best_pb": float(max(pb_full)), "ol_worst_pb_now": float(min(pb_now)),
                            "ol_out_n": float(n_out), "ol_q_n": float(n_q)}
    return out


def rosters(Y):
    d = pd.read_parquet(os.path.join(CACHE, f"roster_weekly_{Y}.parquet"), columns=["team", "week", "game_type", "status", "gsis_id", "pff_id"])
    d = d[d.game_type == "REG"]
    st, have = {}, set()
    pff = {}
    for r in d.itertuples(index=False):
        t = B.tm(str(r.team))
        have.add((t, int(r.week)))
        if isinstance(r.gsis_id, str):
            st[(t, int(r.week), r.gsis_id)] = str(r.status)
            if pd.notna(r.pff_id):
                try:
                    pff[str(int(float(r.pff_id)))] = r.gsis_id
                except ValueError:
                    pass
    return st, have, pff


# ---------------- PFF coverage ----------------
def pff_tables(Y, pff2g):
    cov = BS.load("defense_coverage_scheme", Y)
    man = defaultdict(lambda: [0.0, 0.0])
    if cov is not None:
        for r in cov.itertuples(index=False):
            m = getattr(r, "man_snap_counts_coverage", np.nan); z = getattr(r, "zone_snap_counts_coverage", np.nan)
            if pd.notna(m) or pd.notna(z):
                man[(r.tm, int(r.week))][0] += 0 if pd.isna(m) else float(m)
                man[(r.tm, int(r.week))][1] += 0 if pd.isna(z) else float(z)
    rs = BS.load("receiving_scheme", Y)
    rec = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]))
    if rs is not None and "player_id" in rs.columns:
        for r in rs.itertuples(index=False):
            g = pff2g.get(str(int(r.player_id))) if pd.notna(r.player_id) else None
            if not g:
                continue
            v = rec[g][int(r.week)]
            for i, c in enumerate(("man_yards", "man_routes", "zone_yards", "zone_routes")):
                x = getattr(r, c, np.nan)
                v[i] += 0 if pd.isna(x) else float(x)
    return man, rec


def main():
    t0 = time.time()
    pos_of, bd_of, rook_of = load_positions()
    coaches = BS.load_coaches()
    jmraw = json.load(open(os.path.join(REPO, "data", "jm_scores.json"), encoding="utf-8"))["scores"]
    jm = {(norm(n), v.get("pos")): (v.get("jm"), v.get("yr")) for n, v in jmraw.items()}
    dp = pd.read_parquet(os.path.join(CACHE, "draft_picks.parquet"), columns=["season", "pick", "gsis_id"])
    draft = {r.gsis_id: (int(r.season), int(r.pick)) for r in dp.itertuples(index=False) if isinstance(r.gsis_id, str)}

    P("loading pbp 2017-2025 ...")
    PB = {Y: pbp_tables(Y, pos_of) for Y in range(2017, 2026)}
    P(f"  pbp done {time.time()-t0:.0f}s")

    # team-season summaries (for prior season team + playcaller history)
    tsum = {}
    for Y, (pw, ptm, tw) in PB.items():
        teams = {t for (t, _) in tw}
        for t in teams:
            s, n = team_season(tw, t)
            if not n:
                continue
            tsum[(Y, t)] = {"proe": s["proe_sum"] / s["proe_n"] if s["proe_n"] else np.nan, "plays_pg": s["plays"] / n,
                            "rb_tgt": s["tg_RB"] / s["tg"] if s["tg"] else np.nan, "te_tgt": s["tg_TE"] / s["tg"] if s["tg"] else np.nan,
                            "rb1_car": np.nan}
    # RB1 carry share per team-season (top RB carries / RB carries)
    for Y, (pw, ptm, tw) in PB.items():
        acc = defaultdict(Counter)
        for (pid, wk), v in pw.items():
            t = ptm.get((pid, wk))
            if t and pos_of.get(pid) == "RB":
                acc[t][pid] += v["car"]
        for t, c in acc.items():
            tot = sum(c.values())
            if (Y, t) in tsum and tot:
                tsum[(Y, t)]["rb1_car"] = max(c.values()) / tot

    def pc_name(Y, t):
        c = coaches.get(Y, {}).get(t)
        return str(c["ocPlay"]).split(",")[0].strip() if c and c.get("ocPlay") else None

    _pch = {}

    def pc_hist(Y, t):
        if (Y, t) not in _pch:
            _pch[(Y, t)] = _pc_hist(Y, t)
        return _pch[(Y, t)]

    def _pc_hist(Y, t):
        nm = pc_name(Y, t)
        if not nm:
            return None
        rows = [tsum[(y, tt)] for y in range(2017, Y) for tt in coaches.get(y, {}) if pc_name(y, tt) == nm and (y, tt) in tsum]
        if not rows:
            return {"n": 0}
        return {"n": len(rows), **{k: float(np.nanmean([r[k] for r in rows])) for k in ("proe", "rb_tgt", "te_tgt", "rb1_car", "plays_pg")}}

    P("loading bt_common samples ...")
    S = iter_samples(POS4, verbose=False)
    P(f"  {len(S)} player-weeks ({time.time()-t0:.0f}s)")

    rows = []
    for Y in YEARS:
        pw, ptm, tw = PB[Y]; pwp, ptmp, twp = PB[Y - 1]
        snaps = load_snaps(Y); inj, inj_name = injuries(Y); ros, ros_have, pff2g = rosters(Y)
        olc = ol_context(Y, inj_name)
        _, _, pff2g_p = rosters(Y - 1) if Y - 1 >= 2019 else (None, None, {})
        pff2g_all = {**pff2g_p, **pff2g}
        man, rec = pff_tables(Y, pff2g_all); man_p, rec_p = pff_tables(Y - 1, pff2g_all)
        lg_man = (sum(v[0] for v in man_p.values()) + 1) / (sum(v[0] + v[1] for v in man_p.values()) + 2)
        # player weeks per season, and team rosters of involvement
        by_pid = defaultdict(dict)
        for (pid, wk), v in pw.items():
            by_pid[pid][wk] = v
        team_players = defaultdict(set)
        for (pid, wk), t in ptm.items():
            team_players[t].add(pid)
        by_pid_p = defaultdict(dict)
        for (pid, wk), v in pwp.items():
            by_pid_p[pid][wk] = v
        for s in [x for x in S if x["year"] == Y]:
            pid, t, wk, p = s["pid"], s["team"], s["wk"], s["pos"]
            f = {"year": Y, "name": s["name"], "pos": p, "team": t, "opp": s["opp"], "pid": pid, "wk": wk, "act": s["act"], "shipped": s["shipped"]}
            sn = snaps.get((norm(s["name"]), t), {})
            sm = snap_mult(sn, wk) if sn else 1.0
            f.update({"pos_qb": p == "QB", "pos_rb": p == "RB", "pos_wr": p == "WR", "pos_te": p == "TE", "g": s["g"], "ppg": s["ppg"], "clay": s["clay"],
                      "base2": s["shipped"] * sm, "veg": s["veg"], "fpa_mult": s["fpa"], "ppg_over_clay": s["ppg"] / s["clay"] if s["clay"] else np.nan, "snapmult": sm})
            # ---- usage to date ----
            mine = by_pid.get(pid, {}) if pid else {}
            played = sorted({w for w in sn if w < wk} | {w for w in mine if w < wk and ptm.get((pid, w)) == t})
            tot = defaultdict(float); ttot = defaultdict(float)
            for w in played:
                for k, x in mine.get(w, {}).items():
                    tot[k] += x
                for k, x in tw.get((t, w), {}).items():
                    ttot[k] += x
            ng = max(len(played), 1)
            sh = lambda a, b: tot[a] / ttot[b] if ttot[b] else np.nan
            f.update({"tgt_sh": sh("tg", "tg"), "car_sh": sh("car", "car"), "rz_tgt_sh": sh("rz_tg", "rz_tg"), "rz_car_sh": sh("rz_car", "rz_car"),
                      "gl_car_sh": sh("gl_car", "gl_car"), "ay_sh": sh("ay", "ay"), "xfp_pg": tot["xfp"] / ng, "db_sh": sh("db", "db"), "att_pg": tot["att"] / ng})
            f["wopr"] = 1.5 * (f["tgt_sh"] if pd.notna(f["tgt_sh"]) else 0) + 0.7 * (f["ay_sh"] if pd.notna(f["ay_sh"]) else 0)
            f["pts_over_xfp"] = s["ppg"] - f["xfp_pg"] if p != "QB" else np.nan
            l3 = played[-3:]
            l3t = defaultdict(float); l3tt = defaultdict(float)
            for w in l3:
                for k, x in mine.get(w, {}).items():
                    l3t[k] += x
                for k, x in tw.get((t, w), {}).items():
                    l3tt[k] += x
            f["tgt_sh_l3"] = l3t["tg"] / l3tt["tg"] if l3tt["tg"] else np.nan
            f["car_sh_l3"] = l3t["car"] / l3tt["car"] if l3tt["car"] else np.nan
            f["tgt_trend"] = f["tgt_sh_l3"] - f["tgt_sh"]; f["car_trend"] = f["car_sh_l3"] - f["car_sh"]
            sp = [sn[w] for w in sorted(sn) if w < wk]
            f["snap_std"] = float(np.mean(sp)) if sp else np.nan
            f["snap_l1"] = sp[-1] if sp else np.nan
            f["snap_trend"] = (float(np.mean(sp[-3:])) - f["snap_std"]) if len(sp) >= 3 else np.nan
            # ---- prior season ----
            mp = by_pid_p.get(pid, {}) if pid else {}
            if mp:
                tcount = Counter(ptmp.get((pid, w)) for w in mp)
                tpy = tcount.most_common(1)[0][0]
                ptot = defaultdict(float); pttot = defaultdict(float)
                for w, v in mp.items():
                    for k, x in v.items():
                        ptot[k] += x
                    for k, x in twp.get((ptmp.get((pid, w)), w), {}).items():
                        pttot[k] += x
                gpy = len(mp)
                f.update({"tgt_sh_py": ptot["tg"] / pttot["tg"] if pttot["tg"] else np.nan, "car_sh_py": ptot["car"] / pttot["car"] if pttot["car"] else np.nan,
                          "xfp_pg_py": ptot["xfp"] / gpy, "g_py": gpy, "team_change": float(tpy != t)})
            else:
                f.update({"tgt_sh_py": np.nan, "car_sh_py": np.nan, "xfp_pg_py": np.nan, "g_py": 0, "team_change": np.nan})
            f["ppg_py"] = np.nan  # filled below from weekly db if available
            # ---- team ----
            tw_std = [tw[(t, w)] for w in range(1, wk) if (t, w) in tw]
            ps = sum(v.get("proe_sum", 0) for v in tw_std); pn = sum(v.get("proe_n", 0) for v in tw_std)
            f["proe_std"] = ps / pn if pn else np.nan
            f["plays_pg_std"] = float(np.mean([v.get("plays", 0) for v in tw_std])) if tw_std else np.nan
            tp = tsum.get((Y - 1, t), {})
            f["proe_py"] = tp.get("proe", np.nan); f["plays_pg_py"] = tp.get("plays_pg", np.nan)
            # ---- coach ----
            c0, c1 = coaches.get(Y, {}).get(t), coaches.get(Y - 1, {}).get(t)
            f["new_hc"] = float(bool(c0 and c1 and c0.get("hc") != c1.get("hc"))) if c0 and c1 else np.nan
            f["new_pc"] = float(pc_name(Y, t) != pc_name(Y - 1, t)) if c0 and c1 else np.nan
            h = pc_hist(Y, t) or {"n": 0}
            f["pc_seasons"] = h["n"]
            for k in ("proe", "rb_tgt", "te_tgt", "rb1_car", "plays_pg"):
                f["pc_" + k] = h.get(k, np.nan)
            # ---- vacancy ----
            vt = vc = vts = vcs = 0.0; room_t = room_c = 0.0; qb_top = None; qb_db = 0.0
            for q in team_players.get(t, ()):
                if q == pid:
                    continue
                qw = [w for w in by_pid.get(q, {}) if w < wk and ptm.get((q, w)) == t]
                if not qw:
                    continue
                qt = defaultdict(float); qtt = defaultdict(float)
                for w in qw:
                    for k, x in by_pid[q][w].items():
                        qt[k] += x
                    for k, x in tw.get((t, w), {}).items():
                        qtt[k] += x
                tsh = qt["tg"] / qtt["tg"] if qtt["tg"] else 0.0; csh = qt["car"] / qtt["car"] if qtt["car"] else 0.0
                qp = pos_of.get(q)
                if qp == "QB" and qt["db"] > qb_db:
                    qb_db, qb_top = qt["db"], q
                rs_ = inj.get((t, wk, q), ("", ""))[0]
                rst = ros.get((t, wk, q))
                absent = rs_ in ("Out", "Doubtful") or (rst in ABSENT_ROSTER) or ((t, wk) in ros_have and rst is None)
                if absent:
                    vt += tsh; vc += csh if qp != "QB" else 0.0
                    if qp == p:
                        vts += tsh; vcs += csh
                elif qp == p:
                    room_t += tsh; room_c += csh
            my_t = f["tgt_sh"] if pd.notna(f["tgt_sh"]) else 0.0; my_c = f["car_sh"] if pd.notna(f["car_sh"]) else 0.0
            f.update({"vac_tgt": vt, "vac_car": vc, "vac_tgt_same": vts, "vac_car_same": vcs,
                      "inherit_tgt": vts * my_t / (my_t + room_t) if (my_t + room_t) > 0 else 0.0,
                      "inherit_car": vcs * my_c / (my_c + room_c) if (my_c + room_c) > 0 else 0.0})
            if qb_top and p != "QB":
                rs_ = inj.get((t, wk, qb_top), ("", ""))[0]; rst = ros.get((t, wk, qb_top))
                f["qb_out"] = float(rs_ in ("Out", "Doubtful") or rst in ABSENT_ROSTER or ((t, wk) in ros_have and rst is None))
            else:
                f["qb_out"] = np.nan
            # ---- own injury ----
            rs_, pr_ = inj.get((t, wk, pid), ("", "")) if pid else ("", "")
            f.update({"rep_q": float(rs_ == "Questionable"), "rep_d": float(rs_ in ("Doubtful", "Out")),
                      "prac_dnp": float("Did Not" in pr_), "prac_lim": float("Limited" in pr_)})
            # ---- prospect ----
            d = draft.get(pid) if pid else None
            f["draft_pick"] = float(d[1]) if d else np.nan
            f["undrafted"] = float(d is None and pid is not None)
            rk = rook_of.get(pid) if pid else None
            if rk is None and d:
                rk = d[0]
            f["exp"] = float(Y - rk) if rk else np.nan
            b = bd_of.get(pid) if pid else None
            f["age"] = (pd.Timestamp(Y, 9, 1) - b).days / 365.25 if b is not None and not pd.isna(b) else np.nan
            j = jm.get((norm(s["name"]), p))
            f["jm"] = float(j[0]) if j and j[1] and j[1] <= Y and j[0] is not None else np.nan
            f["rookie"] = float(f["exp"] == 0) if pd.notna(f["exp"]) else np.nan
            f["yr2"] = float(f["exp"] == 1) if pd.notna(f["exp"]) else np.nan
            # ---- environment ----
            gm = B.load_games(Y).get((t, wk), {})
            imp, oimp = gm.get("implied"), gm.get("oppImplied")
            f.update({"implied": imp, "opp_implied": oimp, "spread": (imp - oimp) if imp is not None and oimp is not None else np.nan,
                      "game_total": (imp + oimp) if imp is not None and oimp is not None else np.nan,
                      "dome": float(str(gm.get("roof", "")).lower() in ("dome", "closed")), "hour": gm.get("hour", np.nan)})
            wx = str(gm.get("weather", "")).lower()
            f["precip"] = float(bool(re.search(r"rain|snow|shower|drizzle|sleet", wx)) and f["dome"] == 0)
            mw = re.search(r"wind:\s*\w*\s*(\d+)\s*mph", wx); mt = re.search(r"temp:\s*(-?\d+)", wx)
            f["wind"] = float(mw.group(1)) if mw and f["dome"] == 0 else 0.0
            f["temp"] = float(mt.group(1)) if mt and f["dome"] == 0 else 70.0
            # ---- matchup ----
            o = s["opp"]
            om = [man[(o, w)] for w in range(1, wk) if (o, w) in man]
            ms, zs = sum(v[0] for v in om), sum(v[1] for v in om)
            f["opp_man_std"] = (ms + 400 * lg_man) / (ms + zs + 400) if (ms + zs) else np.nan
            omp = [v for (tt, w), v in man_p.items() if tt == o]
            ms, zs = sum(v[0] for v in omp), sum(v[1] for v in omp)
            f["opp_man_py"] = ms / (ms + zs) if (ms + zs) else np.nan
            if p in ("WR", "TE", "RB") and pid:
                a = [0.0, 0.0, 0.0, 0.0]
                for src, lim in ((rec_p.get(pid, {}), 99), (rec.get(pid, {}), wk)):
                    for w, v in src.items():
                        if w < lim:
                            for i in range(4):
                                a[i] += v[i]
                K = 60.0
                f["yprr_man"] = (a[0] + K * 1.5) / (a[1] + K) if (a[1] + a[3]) > 0 else np.nan
                f["yprr_zone"] = (a[2] + K * 1.5) / (a[3] + K) if (a[1] + a[3]) > 0 else np.nan
                f["man_gap_x_opp"] = (f["yprr_man"] - f["yprr_zone"]) * (f["opp_man_std"] if pd.notna(f["opp_man_std"]) else f["opp_man_py"]) if pd.notna(f["yprr_man"]) else np.nan
            else:
                f["yprr_man"] = f["yprr_zone"] = f["man_gap_x_opp"] = np.nan
            oc = olc.get((t, wk), {})
            for k in OL_KEYS:
                f[k] = oc.get(k, np.nan)
            rows.append(f)
        P(f"  {Y}: rows {len(rows)} ({time.time()-t0:.0f}s)")

    df = pd.DataFrame(rows)
    # prior-season PPG from the same weekly db the samples use (last season's rows of this player)
    last =df.sort_values("wk").groupby(["year", "pid"]).agg(lastppg=("ppg", "last"), lastact=("act", "last"), lastg=("g", "last"))
    last["ppg_full"] = (last.lastppg * last.lastg + last.lastact) / (last.lastg + 1)
    m = {(y + 1, pid): v for (y, pid), v in last.ppg_full.items()}
    df["ppg_py"] = [m.get((y, pid), np.nan) for y, pid in zip(df.year, df.pid)]
    for c in df.columns:
        if df[c].dtype == bool:
            df[c] = df[c].astype(float)
    df.to_parquet(OUT, index=False)
    json.dump(GROUPS, open(os.path.join(HERE, "ctx_features_groups.json"), "w"), indent=1)
    feats = [c for g in GROUPS.values() for c in g]
    P(f"\nwrote {OUT}: {len(df)} rows x {len(feats)} features ({time.time()-t0:.0f}s)")
    cov = df[feats].notna().mean().sort_values()
    P("coverage (share non-missing), lowest 15: " + ", ".join(f"{k} {v:.2f}" for k, v in cov.head(15).items()))
    P("means by position: " + " | ".join(f"{p} vac_tgt_same {g.vac_tgt_same.mean():.3f} inherit_tgt {g.inherit_tgt.mean():.3f} tgt_sh {g.tgt_sh.mean():.3f} jm {g.jm.mean():.1f}" for p, g in df.groupby("pos")))


if __name__ == "__main__":
    main()
