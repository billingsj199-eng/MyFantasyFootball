#!/usr/bin/env python3
"""
Jack 2026-09-29: "this season we are seeing increased TE usage and decrease in WR3 usage".
League-wide, weeks 1-3 of every season 2019-2026 from nflverse play-by-play (every player, not
just the board): share of targets / receiving yards / receiving TDs / half-PPR receiving points
by position, the WR split by rank on his own team (targets in the window), plus snap shares
(snap_counts) for the WR3 and TE1 of each team. Full-season columns show how much weeks 1-3 of
a season say about the rest of it.
"""
import pandas as pd, numpy as np, os
C = r"E:\MyFantasyFootball\pbp_cache"
pl = pd.read_csv(os.path.join(C, "players.csv"), low_memory=False, usecols=["gsis_id", "position", "pfr_id"]).dropna(subset=["gsis_id"]).drop_duplicates("gsis_id")
POS = dict(zip(pl.gsis_id, pl.position))
def load(Y):
    d = pd.read_csv(os.path.join(C, f"play_by_play_{Y}.csv.gz"), low_memory=False,
                    usecols=["season_type", "week", "posteam", "pass_attempt", "sack", "receiver_player_id", "complete_pass", "yards_gained", "pass_touchdown", "two_point_attempt", "play_type"])
    d = d[(d.season_type == "REG") & (d.play_type == "pass") & d.receiver_player_id.notna() & (d.two_point_attempt != 1)].copy()
    d["pos"] = d.receiver_player_id.map(POS)
    d["pos"] = d.pos.where(d.pos.isin(["WR", "TE", "RB"]), np.where(d.pos == "FB", "RB", "other"))
    d["rec"] = d.complete_pass.fillna(0); d["yds"] = np.where(d.rec == 1, d.yards_gained.fillna(0), 0); d["td"] = np.where(d.rec == 1, d.pass_touchdown.fillna(0), 0)
    d["fp"] = 0.5 * d.rec + 0.1 * d.yds + 6 * d.td
    return d
def table(d):
    # WR rank on own team by targets in the window
    wr = d[d.pos == "WR"].groupby(["posteam", "receiver_player_id"]).size().rename("t").reset_index()
    wr["rk"] = wr.groupby("posteam").t.rank(ascending=False, method="first")
    rk = dict(zip(zip(wr.posteam, wr.receiver_player_id), wr.rk))
    g = d.copy()
    g["grp"] = [("WR1" if rk.get((t, r), 9) == 1 else "WR2" if rk.get((t, r), 9) == 2 else "WR3" if rk.get((t, r), 9) == 3 else "WR4+") if p == "WR" else p for t, r, p in zip(g.posteam, g.receiver_player_id, g.pos)]
    out = {}
    for k in ("WR1", "WR2", "WR3", "WR4+", "TE", "RB"):
        x = g[g.grp == k]
        out[k] = dict(tgt=len(x) / len(g), yds=x.yds.sum() / g.yds.sum(), td=x.td.sum() / max(1, g.td.sum()), fp=x.fp.sum() / g.fp.sum())
    out["_n"] = len(g); out["_td"] = int(g.td.sum())
    return out
rows = {}
for Y in range(2019, 2027):
    try: d = load(Y)
    except Exception as e: print(Y, "skip", e); continue
    rows[Y] = (table(d[d.week <= 3]), table(d[d.week >= 4]) if (d.week >= 4).any() else None, int(d.week.max()))
print("weeks in 2026 file:", rows[2026][2])
for met, lab in (("tgt", "TARGET share"), ("fp", "half-PPR receiving POINTS share"), ("td", "receiving TD share"), ("yds", "receiving YARDS share")):
    print(f"\n=== {lab}, weeks 1-3 of each season (league-wide) ===")
    print("  season   " + "".join(f"{k:>8s}" for k in ("WR1", "WR2", "WR3", "WR4+", "TE", "RB")) + "    all WR")
    hist = {k: [] for k in ("WR1", "WR2", "WR3", "WR4+", "TE", "RB", "WR")}
    for Y, (e, l, _) in rows.items():
        wr = sum(e[k][met] for k in ("WR1", "WR2", "WR3", "WR4+"))
        print(f"  {Y}     " + "".join(f"{100*e[k][met]:8.1f}" for k in ("WR1", "WR2", "WR3", "WR4+", "TE", "RB")) + f"  {100*wr:8.1f}" + ("   <- this season" if Y == 2026 else ""))
        if Y < 2026:
            for k in ("WR1", "WR2", "WR3", "WR4+", "TE", "RB"): hist[k].append(100 * e[k][met])
            hist["WR"].append(100 * wr)
    e = rows[2026][0]; cur = {k: 100 * e[k][met] for k in ("WR1", "WR2", "WR3", "WR4+", "TE", "RB")}; cur["WR"] = sum(cur[k] for k in ("WR1", "WR2", "WR3", "WR4+"))
    print("  2019-25  " + "".join(f"{np.mean(hist[k]):8.1f}" for k in ("WR1", "WR2", "WR3", "WR4+", "TE", "RB")) + f"  {np.mean(hist['WR']):8.1f}   avg")
    print("  range    " + "".join(f"{min(hist[k]):4.1f}-{max(hist[k]):<4.1f}"[:9].rjust(8) for k in ("WR1", "WR2", "WR3", "WR4+", "TE", "RB")))
    print("  2026 z   " + "".join(f"{(cur[k]-np.mean(hist[k]))/np.std(hist[k], ddof=1):+8.1f}" for k in ("WR1", "WR2", "WR3", "WR4+", "TE", "RB")) + f"  {(cur['WR']-np.mean(hist['WR']))/np.std(hist['WR'], ddof=1):+8.1f}   (standard deviations from the 7-season norm)")
print("\n=== does a weeks 1-3 league shift LAST? share in weeks 1-3 vs weeks 4+ of the same season (targets / points) ===")
for k in ("TE", "WR3", "WR4+", "RB"):
    for met in ("tgt", "fp"):
        a = [100 * rows[Y][0][k][met] for Y in range(2019, 2026)]; b = [100 * rows[Y][1][k][met] for Y in range(2019, 2026)]
        print(f"  {k:5s} {met:3s}  early-vs-late corr across seasons {np.corrcoef(a, b)[0,1]:+.2f}   " + "  ".join(f"{Y}: {x:.1f}->{y:.1f}" for Y, x, y in zip(range(2019, 2026), a, b)))
print("\n=== receiving TDs per team-game, weeks 1-3 ===")
for Y, (e, l, _) in rows.items():
    print(f"  {Y}: total rec TDs {e['_td']:3d}  TE {e['TE']['td']*e['_td']:.0f}  WR3+4 {(e['WR3']['td']+e['WR4+']['td'])*e['_td']:.0f}  targets {e['_n']}")
# snaps: WR3 and TE1/TE2 snap share by team, weeks 1-3
print("\n=== snap share (offense %), weeks 1-3: average across teams of the 3rd WR / top TE / 2nd TE by snaps ===")
for Y in range(2019, 2027):
    s = pd.read_parquet(os.path.join(C, f"snap_counts_{Y}.parquet"), columns=["game_type", "week", "player", "position", "team", "offense_snaps", "offense_pct"])
    s = s[(s.game_type == "REG") & (s.week <= 3) & s.position.isin(["WR", "TE", "RB"])]
    tg = s.groupby(["team", "week"]).offense_snaps.max().groupby("team").sum().rename("tot")
    a = s.groupby(["team", "position", "player"]).offense_snaps.sum().reset_index().join(tg, on="team")
    a["pct"] = 100 * a.offense_snaps / a.tot
    a["rk"] = a.groupby(["team", "position"]).pct.rank(ascending=False, method="first")
    f = lambda p, r: a[(a.position == p) & (a.rk == r)].pct.mean()
    te_all = a[a.position == "TE"].groupby("team").pct.sum().mean(); wr_all = a[a.position == "WR"].groupby("team").pct.sum().mean()
    print(f"  {Y}: WR1 {f('WR',1):5.1f}  WR2 {f('WR',2):5.1f}  WR3 {f('WR',3):5.1f}  WR4 {f('WR',4):5.1f} | TE1 {f('TE',1):5.1f}  TE2 {f('TE',2):5.1f} | TEs on field per play {te_all/100:.2f}  WRs per play {wr_all/100:.2f}")
