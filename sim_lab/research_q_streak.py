#!/usr/bin/env python3
"""
REPEATED-QUESTIONABLE STARTERS (Jack 2026-11-02, from the RB level check: Breece Hall Q / out W4-8 but projected back each
week, Braelon Allen held at ~8 while scoring ~19). A starter listed QUESTIONABLE on the final report after missing k straight
team games: how often does he play, and what does his game come to vs his healthy rate - by k, practice status, position;
and his backup's game in those weeks vs the backup's fill-in rate. 2013-2025 (snap counts start 2013).
Engine today: Q-DNP x.75, Q-LP / Q-FP x1 (applyInSeasonInjuries), x.85 more when he missed last week (v2.10 qRet).
Log q_streak.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_common as B
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "q_streak.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
C = B.CACHE
YEARS = list(range(2013, 2026))
pl = pd.read_csv(os.path.join(C, "players.csv"), low_memory=False, usecols=["gsis_id", "pfr_id", "position"])
PFR2G = dict(zip(pl.pfr_id, pl.gsis_id)); POSOF = dict(zip(pl.gsis_id, pl.position))
ENG = {"DNP": 0.75, "LP": 1.0, "FP": 1.0}


def pts_by_game(Y):
    cols = ["season_type", "week", "posteam", "rush_attempt", "rusher_player_id", "rushing_yards", "rush_touchdown", "pass_attempt", "receiver_player_id",
            "complete_pass", "receiving_yards", "pass_touchdown", "passer_player_id", "passing_yards", "interception", "two_point_attempt", "sack"]
    d = pd.read_csv(os.path.join(C, f"play_by_play_{Y}.csv.gz"), usecols=lambda c: c in cols, low_memory=False)
    d = d[(d.season_type == "REG") & (d.two_point_attempt.fillna(0) != 1)]
    out = defaultdict(float)
    ru = d[(d.rush_attempt == 1) & d.rusher_player_id.notna()]
    for (w, p), v in (0.1 * ru.rushing_yards.fillna(0) + 6 * ru.rush_touchdown.fillna(0)).groupby([ru.week, ru.rusher_player_id]).sum().items(): out[(int(w), p)] += v
    re_ = d[(d.pass_attempt == 1) & d.receiver_player_id.notna()]
    for (w, p), v in (0.5 * re_.complete_pass.fillna(0) + 0.1 * re_.receiving_yards.fillna(0) + 6 * re_.pass_touchdown.fillna(0)).groupby([re_.week, re_.receiver_player_id]).sum().items(): out[(int(w), p)] += v
    pa = d[(d.pass_attempt == 1) & d.passer_player_id.notna()]
    for (w, p), v in (0.04 * pa.passing_yards.fillna(0) + 4 * pa.pass_touchdown.fillna(0) - 2 * pa.interception.fillna(0)).groupby([pa.week, pa.passer_player_id]).sum().items(): out[(int(w), p)] += v
    return out


def main():
    rows = []; bk = []
    for Y in YEARS:
        sn = pd.read_parquet(os.path.join(C, f"snap_counts_{Y}.parquet")); sn = sn[sn.game_type == "REG"]
        sn["gid"] = sn.pfr_player_id.map(PFR2G); sn = sn[sn.gid.notna() & sn.position.isin(["QB", "RB", "WR", "TE"])]
        snap = {(r.gid, int(r.week)): (r.team, float(r.offense_pct or 0)) for r in sn.itertuples(index=False)}
        teamwk = defaultdict(set)
        for r in sn.itertuples(index=False): teamwk[r.team].add(int(r.week))
        ros = pd.read_parquet(os.path.join(C, f"roster_weekly_{Y}.parquet"), columns=["team", "week", "gsis_id", "position", "game_type"])
        ros = ros[(ros.game_type == "REG") & ros.position.isin(["QB", "RB", "WR", "TE"])]
        onteam = {(r.gsis_id, int(r.week)): r.team for r in ros.itertuples(index=False)}
        inj = pd.read_parquet(os.path.join(C, f"injuries_{Y}.parquet")); inj = inj[(inj.game_type == "REG") & inj.gsis_id.notna()]
        rep = {(r.gsis_id, int(r.week)): (str(r.report_status or ""), str(r.practice_status or "")) for r in inj.itertuples(index=False)}
        fp = pts_by_game(Y)
        tw_pos = defaultdict(list)
        for (gid, w), (tm, pct) in snap.items(): tw_pos[(tm, w, POSOF.get(gid))].append((gid, pct))
        for (gid, w), (st, ps) in rep.items():
            if st != "Questionable": continue
            tm = onteam.get((gid, w)); pos = POSOF.get(gid)
            if not tm or pos not in ("QB", "RB", "WR", "TE") or w not in teamwk[tm]: continue
            wks = sorted(x for x in teamwk[tm] if x < w)
            k = 0   # missed team games right before this week (on the roster, no snaps)
            for x in reversed(wks):
                if (gid, x) in snap and snap[(gid, x)][1] > 0: break
                if onteam.get((gid, x)) != tm: break
                k += 1
            pre = [x for x in wks[:len(wks) - k] if (gid, x) in snap and snap[(gid, x)][1] > 0]
            if len(pre) < 2: continue
            pre_pct = np.mean([snap[(gid, x)][1] for x in pre]); pre_pts = np.mean([fp.get((x, gid), 0.0) for x in pre])
            if pre_pct < 0.5 or pre_pts < 3: continue            # starters / real roles only
            played = (gid, w) in snap and snap[(gid, w)][1] > 0
            pts = fp.get((w, gid), 0.0) if played else 0.0
            pcls = "DNP" if ps.startswith("Did Not") else ("LP" if ps.startswith("Limited") else "FP")
            rows.append(dict(Y=Y, w=w, pos=pos, k=k, pc=pcls, played=played, ratio=pts / pre_pts, pct=(snap[(gid, w)][1] / pre_pct) if played else 0.0))
            # backup: same position, top snap share among the others during the missed streak (fill-in); his game this week vs his fill-in rate
            if k >= 1 and pos in ("RB", "WR", "TE"):
                miss = wks[len(wks) - k:]
                cand = defaultdict(list)
                for x in miss:
                    for og, pct in tw_pos[(tm, x, pos)]:
                        if og != gid: cand[og].append((pct, fp.get((x, og), 0.0)))
                if cand:
                    og = max(cand, key=lambda q: np.mean([a for a, _ in cand[q]]) * len(cand[q]))
                    fill = np.mean([b for _, b in cand[og]]); fpct = np.mean([a for a, _ in cand[og]])
                    pre_o = [fp.get((x, og), 0.0) for x in pre if (og, x) in snap and snap[(og, x)][1] > 0]
                    if fill >= 3 and fpct >= 0.4 and (og, w) in snap and snap[(og, w)][1] > 0:
                        bk.append(dict(Y=Y, pos=pos, k=k, pc=pcls, st_played=played, b_ratio=fp.get((w, og), 0.0) / fill, b_pre=(np.mean(pre_o) / fill) if pre_o else np.nan))
    R = pd.DataFrame(rows); K = pd.DataFrame(bk)
    R["kb"] = np.minimum(R.k, 3); K["kb"] = np.minimum(K.k, 3)
    P(f"=== Questionable starters (final report), 2013-2025: {len(R):,} player-weeks; starter = 50%+ snaps and 3+ half-PPR pts/g in games before the streak ===")
    P("  EV = his game (0 if he sat) / his pre-injury pts per game; engine EV = practice dock x (.85 if he missed last week)")
    P("  streak  practice     n   played  snaps-if-played  EV      engine EV   EV/engine | seasons with EV < engine")
    for kb in (0, 1, 2, 3):
        for pc in ("DNP", "LP", "FP", "all"):
            m = (R.kb == kb) & ((R.pc == pc) if pc != "all" else True); x = R[m]
            if len(x) < 15: continue
            eng = (x.pc.map(ENG) * (0.85 if kb >= 1 else 1.0)).mean()
            ys = [Y for Y in YEARS if (x.Y == Y).sum() >= 4]
            lo = sum(1 for Y in ys if x[x.Y == Y].ratio.mean() < (x[x.Y == Y].pc.map(ENG) * (0.85 if kb >= 1 else 1.0)).mean())
            P(f"  {('k=' + str(kb) + ('+' if kb == 3 else '')):6s}  {pc:4s}  {len(x):6d}   {x.played.mean():.3f}     {x[x.played].pct.mean():.3f}          {x.ratio.mean():.3f}   {eng:.3f}      {x.ratio.mean()/eng:.3f}   | {lo}/{len(ys)}")
    P("")
    P("  by position, streak 2+ (all practice):")
    for ps in ("QB", "RB", "WR", "TE"):
        x = R[(R.kb >= 2) & (R.pos == ps)]
        if len(x) >= 15: P(f"    {ps}  n {len(x):4d}  played {x.played.mean():.3f}  EV {x.ratio.mean():.3f}  engine {(x.pc.map(ENG) * .85).mean():.3f}")
    P("")
    P("=== BACKUP in those weeks (RB/WR/TE; backup = top-snap teammate at the position during the starter's missed streak, 40%+ snaps, 3+ pts; played this week) ===")
    P("  backup's game / his own fill-in rate during the streak (pre-injury = his rate before the injury / fill-in rate)")
    for kb in (1, 2, 3):
        for lab, mm in (("starter sat", ~K.st_played), ("starter played", K.st_played), ("all", np.ones(len(K), bool))):
            x = K[(K.kb == kb) & mm]
            if len(x) >= 15: P(f"  {('k=' + str(kb) + ('+' if kb == 3 else '')):6s} {lab:15s} n {len(x):5d}  backup game / fill-in rate {x.b_ratio.mean():.3f}  (median {x.b_ratio.median():.3f})  pre-injury level / fill-in {np.nanmean(x.b_pre):.3f}")
    for ps in ("RB", "WR", "TE"):
        x = K[(K.kb >= 2) & (K.pos == ps)]
        if len(x) >= 15: P(f"    {ps} streak 2+: n {len(x)}  starter played {x.st_played.mean():.3f}  backup game / fill-in {x.b_ratio.mean():.3f}  pre-injury level / fill-in {np.nanmean(x.b_pre):.3f}")
    R.to_pickle(os.path.join(HERE, "_tmp", "q_streak_rows.pkl")); K.to_pickle(os.path.join(HERE, "_tmp", "q_streak_backups.pkl"))
    LOG.close()


if __name__ == "__main__":
    main()
