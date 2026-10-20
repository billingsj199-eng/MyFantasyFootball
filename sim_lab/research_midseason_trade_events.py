#!/usr/bin/env python3
"""
MID-SEASON TEAM CHANGES - event set (Jack 2026-10-20, MHJ ARI -> HOU). Research only.

Per-week team for every pool player-season 2019-25 from his opponent that week (the team whose schedule has that
opponent that week is unique), cross-checked with nflverse roster_weekly. A MOVER = a clean split: every played game
before week X on team A, every played game from X on team B (A != B), 1+ played games on each side.
Also reports whether the shared harness (infer_team, >= 70% schedule match) keeps the player-season and how.
Writes _tmp/midseason_events.json (used by research_midseason_trade.py).
"""
import json, os, sys
from collections import defaultdict, Counter
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_sim_calibration as cal
import bt_common as B
YEARS = list(range(2019, 2026))
POS4 = ("QB", "RB", "WR", "TE")

def team_by_week(wrec, Y):
    S = cal.SCHEDULES.get(Y, {})
    inv = {}
    for t, s in S.items():
        for w, o in s.items(): inv[(int(w), o)] = t
    out = {}
    for w in wrec.get("seasons", {}).get(str(Y), []):
        if not cal.played(w) or not isinstance(w.get("fpts"), (int, float)): continue
        opp = cal.OPP_ALIAS.get(w.get("opp"), w.get("opp"))
        if not opp: continue
        out[int(w["wk"])] = inv.get((int(w["wk"]), opp))
    return out

def mover_split(tbw):
    """clean A..A B..B split -> (A, B, first week on B) else None"""
    wks = sorted(tbw)
    if len(wks) < 2 or any(tbw[w] is None for w in wks): return None
    seq = [tbw[w] for w in wks]
    ch = [i for i in range(1, len(seq)) if seq[i] != seq[i - 1]]
    if len(ch) != 1: return None
    return seq[0], seq[-1], wks[ch[0]]

def main():
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    resolve = B.player_ids()
    pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "birth_date", "rookie_season", "display_name"])
    birth = {r.gsis_id: pd.to_datetime(r.birth_date, errors="coerce") for r in pl.itertuples(index=False) if isinstance(r.gsis_id, str)}
    ev = []
    for Y in YEARS:
        rw = pd.read_parquet(os.path.join(B.CACHE, f"roster_weekly_{Y}.parquet"), columns=["team", "week", "game_type", "gsis_id", "status"])
        rw = rw[rw.game_type == "REG"]
        rteam = {(r.gsis_id, int(r.week)): B.tm(str(r.team)) for r in rw.itertuples(index=False) if isinstance(r.gsis_id, str)}
        for name, c in clay_hist[str(Y)].items():
            pos = c.get("pos")
            if pos not in POS4: continue
            in_pool = (c.get("pts") or 0) >= cal.POOL_MIN_PTS
            wrec = cal.weekly_rec(name, pos)
            if wrec is None: continue
            tbw = team_by_week(wrec, Y); sp = mover_split(tbw)
            if not sp: continue
            A, Bt, wx = sp
            pid = resolve(name, pos, Y)
            # roster_weekly cross-check: team listed the week of his first new-team game
            rt = rteam.get((pid, wx)) if pid else None; rt_prev = rteam.get((pid, max(w for w in tbw if w < wx))) if pid else None
            inf = cal.infer_team(wrec, Y)
            bd = birth.get(pid) if pid else None
            age = round(((pd.Timestamp(year=Y, month=9, day=1) - bd).days / 365.25), 1) if (bd is not None and pd.notna(bd)) else None
            nA = sum(1 for w in tbw if w < wx); nB = sum(1 for w in tbw if w >= wx)
            ev.append(dict(year=Y, name=name, pos=pos, pid=pid, old=A, new=Bt, first_new_wk=wx, n_old=nA, n_new=nB, in_pool=in_pool,
                           clay_pts=c.get("pts"), harness_team=inf, roster_new=rt, roster_prev=rt_prev, age=age, tbw={str(k): v for k, v in sorted(tbw.items())}))
    os.makedirs(os.path.join(HERE, "_tmp"), exist_ok=True)
    json.dump(ev, open(os.path.join(HERE, "_tmp", "midseason_events.json"), "w"), indent=1)
    print(f"movers (clean split, any games): {len(ev)}; in Clay pool (40+ pts): {sum(e['in_pool'] for e in ev)}")
    print("by position (pool):", Counter(e["pos"] for e in ev if e["in_pool"]))
    print("harness keeps (infer_team ok):", Counter((e["harness_team"] == e["new"], e["harness_team"] == e["old"], e["harness_team"] is None) for e in ev if e["in_pool"]))
    for e in sorted(ev, key=lambda e: (e["year"], e["pos"], e["name"])):
        if not e["in_pool"]: continue
        print(f"  {e['year']} {e['pos']} {e['name']:24s} {e['old']}->{e['new']} wk{e['first_new_wk']:2d}  old g {e['n_old']:2d} new g {e['n_new']:2d}  age {e['age']}  harness={e['harness_team']}  roster_new={e['roster_new']} prev={e['roster_prev']}")

if __name__ == "__main__":
    main()
