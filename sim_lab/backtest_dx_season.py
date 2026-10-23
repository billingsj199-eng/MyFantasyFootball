#!/usr/bin/env python3
"""
DX-SEASON CHECK (Jack 2026-10-20: Mike Evans "doesnt have a torn achille" - Sleeper's "Achilles, Out" zeroed him W7-W18).

engine.js INJURY SIGNALS 4 calls a player out through week 18 when Sleeper's body part is ACL / Achilles and he is
Out, Doubtful or on a reserve list. Question: when a player who has played this season shows up on the weekly NFL
game-status report (so he is still on the ACTIVE roster) as Out / Doubtful with an Achilles injury, how often is his
season actually over? Real tears normally go straight to IR and drop off the weekly report.

Data: nflverse injuries_{Y}.parquet (game-status report) + snap_counts_{Y}.parquet, 2019-25 REG.
Event = the first week of a player-season he is listed Out / Doubtful with 'achilles' in the primary injury, having
played (offense or defense/ST snaps > 0) earlier that season. Outcome = plays again in a later REG week that season.
(The NFL report says "Knee" for ACL tears, so the ACL half of the rule can't be graded from history.)
Log -> dx_season.log
"""
import os, sys
from collections import defaultdict
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_common as B
YEARS = list(range(2019, 2026))
SKILL = {"QB", "RB", "WR", "TE"}

def main():
    ev = []
    for Y in YEARS:
        inj = pd.read_parquet(os.path.join(B.CACHE, f"injuries_{Y}.parquet"))
        inj = inj[inj.game_type == "REG"]
        sn = pd.read_parquet(os.path.join(B.CACHE, f"snap_counts_{Y}.parquet"))
        sn = sn[sn.game_type == "REG"]
        tot = sn.get("offense_snaps", 0).fillna(0) + sn.get("defense_snaps", 0).fillna(0) + sn.get("st_snaps", 0).fillna(0)
        sn = sn.assign(tot=tot)
        played = defaultdict(set)
        for r in sn[sn.tot > 0].itertuples(index=False):
            played[(str(r.player).lower(), r.team)].add(int(r.week))
        lastwk = int(sn.week.max())
        a = inj[inj.report_primary_injury.fillna("").str.contains("chilles", case=False) & inj.report_status.isin(["Out", "Doubtful"])]
        a = a.sort_values("week")
        seen = set()
        for r in a.itertuples(index=False):
            key = (str(r.full_name).lower(), r.team)
            if key in seen: continue
            wk = int(r.week); pw = played.get(key, set())
            if not any(w < wk for w in pw): continue          # never played before this listing (camp / PUP case)
            seen.add(key)
            later = sorted(w for w in pw if w > wk)
            # still on the weekly report the week after = still on the active roster (not IR)
            nxt = inj[(inj.full_name == r.full_name) & (inj.team == r.team) & (inj.week == wk + 1)]
            ev.append(dict(season=Y, name=r.full_name, team=r.team, pos=r.position, wk=wk, status=r.report_status,
                           inj=r.report_primary_injury, back=bool(later), back_wk=later[0] if later else None,
                           missed=(later[0] - wk) if later else None, lastwk=lastwk, onrep_next=len(nxt) > 0))
    df = pd.DataFrame(ev)
    L = []
    def line(s=""): L.append(s); print(s)
    def block(name, d):
        if not len(d): line(f"{name}: n=0"); return
        b = d[d.back]
        med = b.missed.median() if len(b) else float("nan")
        line(f"{name}: n={len(d)}  season over {100 * (1 - d.back.mean()):.0f}%  ({(~d.back).sum()})  |  came back {d.back.sum()}, "
             f"median {med:.0f} wk(s) after the listing (weeks incl. byes)")
    line("DX-SEASON CHECK - Out/Doubtful + Achilles on the weekly NFL report, played earlier that season (2019-25 REG)")
    line("")
    block("ALL positions", df)
    block("  skill QB/RB/WR/TE", df[df.pos.isin(SKILL)])
    block("  listed Out", df[df.status == "Out"])
    block("  listed Doubtful", df[df.status == "Doubtful"])
    block("  still on the report the next week (active roster)", df[df.onrep_next])
    block("  gone from the report the next week (IR / season over)", df[~df.onrep_next])
    late = df[df.wk >= df.lastwk - 2]
    block("  (listed in the last 3 weeks - little season left to return in)", late)
    block("ALL, listed before the last 3 weeks", df[df.wk < df.lastwk - 2])
    line("")
    line("Skill-position events:")
    for r in df[df.pos.isin(SKILL)].sort_values(["season", "wk"]).itertuples(index=False):
        line(f"  {r.season} W{r.wk:>2} {r.pos:<2} {r.name:<24} {r.team:<3} {r.status:<8} {'back W' + str(r.back_wk) if r.back else 'did not play again'}"
             f"{'' if r.onrep_next else '  (off the report next week)'}")
    open(os.path.join(HERE, "dx_season.log"), "w", encoding="utf-8").write("\n".join(L) + "\n")

if __name__ == "__main__":
    main()
