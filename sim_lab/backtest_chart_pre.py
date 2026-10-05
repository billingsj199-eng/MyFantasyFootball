#!/usr/bin/env python3
"""
PRE-INJURY CHART SPOT backtest (Jack 2026-10-02: "can we back test"). The Clay-free model reads a player's depth
chart string and docks second / third stringers (vetDock RB 2: x.8, 3: x.4; WR 2 / 3: x.6; TE 2: x.8). A chart
drops a player down or off while he is out, so a projection made DURING his absence for the weeks after his return
saw a demoted player. Shipped today: read him at the spot he held going into his last game instead.

Return events 2019-24 (nflverse weekly depth charts; 2025 is a different schema): a player who missed 1+ team
games after playing, graded on his first three games back, on the shared bt_common base (P=5 blend x Vegas x FPA)
with the shipped return ramp on both sides:
    pre      his string on the chart of the week of his last game before the absence
    listed   his string on the chart of the LAST week he missed (off the chart = third string)
    A  "pre-injury spot"   base x ramp
    B  "chart as listed"   base x ramp x dock(listed) / dock(pre)
Also: the teammate listed first at his position while he was out - his points before vs after the return.
Log chart_pre_backtest.log.
"""
import os, sys
from collections import defaultdict
import numpy as np, pandas as pd
from bt_common import iter_samples, to_arrays, load_games, POS4
from backtest_return_game import snaps_year
import backtest_sim_calibration as cal
HERE = os.path.dirname(os.path.abspath(__file__)); CACHE = r"E:\MyFantasyFootball\pbp_cache"
YEARS = list(range(2019, 2025))
RAMP = {"1": [0.95], "2-3": [0.92], "4+": [0.85, 0.92, 0.96]}
DOCK = {"RB": {1: 1.0, 2: 0.8, 3: 0.4}, "WR": {1: 1.0, 2: 0.6, 3: 0.6}, "TE": {1: 1.0, 2: 0.8, 3: 0.8}}
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}

def charts(Y):
    """{(week, norm name): string}, {(team, week, pos): [names listed first]}"""
    d = pd.read_parquet(os.path.join(CACHE, f"depth_charts_{Y}.parquet"), columns=["week", "game_type", "club_code", "depth_team", "formation", "position", "depth_position", "full_name"])
    d = d[(d.game_type == "REG") & (d.formation == "Offense") & d.position.isin(["RB", "WR", "TE"])]
    st, first = {}, defaultdict(list)
    for r in d.itertuples(index=False):
        try: s = int(r.depth_team)
        except Exception: continue
        k = (int(r.week), cal.norm(str(r.full_name)))
        if k not in st or s < st[k]: st[k] = s
        if s == 1: first[(ALIAS.get(r.club_code, r.club_code), int(r.week), r.position)].append(cal.norm(str(r.full_name)))
    return st, first

def main():
    log = open(os.path.join(HERE, "chart_pre_backtest.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n")
    S = iter_samples(POS4, verbose=False); A = to_arrays(S)
    act, ship, pos, year = A["act"], A["shipped"], A["pos"], A["year"]
    rowi = {(s["year"], cal.norm(s["name"]), s["wk"]): i for i, s in enumerate(S)}
    ev = []; fill = []
    for Y in YEARS:
        sn = snaps_year(Y); games = load_games(Y); st, first = charts(Y)
        tw_all = defaultdict(set)
        for (t, wk) in games: tw_all[t].add(wk)
        seen_fill = set()
        for i, s in enumerate(S):
            if s["year"] != Y or s["pos"] == "QB": continue
            nk = cal.norm(s["name"]); p = sn.get(nk)
            if not p: continue
            playedw = {w for w, v in p.items() if v[0] > 0}
            if s["wk"] not in playedw: continue
            tw = sorted(tw_all.get(s["team"], [])); prior = [w for w in tw if w < s["wk"]]
            back = 0; j = len(prior) - 1
            while j >= 0 and prior[j] in playedw: back += 1; j -= 1
            k = 0; last_missed = prior[j] if j >= 0 and prior[j] not in playedw else None
            while j >= 0 and prior[j] not in playedw: k += 1; j -= 1
            if k == 0 or j < 0 or last_missed is None: continue
            b = "1" if k == 1 else "2-3" if k <= 3 else "4+"
            if back >= 3: continue
            last_played = prior[j]
            pre = st.get((last_played, nk)); lst = st.get((last_missed, nk))
            if pre is None: continue                               # not on the chart before he got hurt: nothing to restore
            pre = min(3, pre); lsk = 3 if lst is None else min(3, lst)
            ramp = RAMP[b][back] if (back < len(RAMP[b]) and s["pos"] != "TE") else 1.0
            ev.append(dict(i=i, year=Y, pos=s["pos"], k=k, b=b, back=back + 1, pre=pre, listed=lsk, off=lst is None, ramp=ramp))
            # the teammate listed first at his position while he was out (once per absence)
            key = (nk, last_missed)
            if pre == 1 and back == 0 and key not in seen_fill:
                seen_fill.add(key)
                first_missed = prior[j + 1]
                for fn in first.get((ALIAS.get(s["team"], s["team"]), last_missed, s["pos"]), []):
                    if fn == nk: continue
                    during = [act[rowi[(Y, fn, w)]] for w in tw if first_missed <= w <= last_missed and (Y, fn, w) in rowi]
                    after = [act[rowi[(Y, fn, w)]] for w in tw if s["wk"] <= w <= s["wk"] + 3 and (Y, fn, w) in rowi]
                    before = [act[rowi[(Y, fn, w)]] for w in tw if w < first_missed and (Y, fn, w) in rowi][-3:]
                    if during and after: fill.append(dict(year=Y, pos=s["pos"], during=np.mean(during), after=np.mean(after), before=np.mean(before) if before else np.nan))
    E = pd.DataFrame(ev); E["act"] = act[E.i.values]; E["base"] = ship[E.i.values] * E.ramp.values
    E["B"] = E.base * [DOCK[p][l] / DOCK[p][q] for p, l, q in zip(E.pos, E.listed, E.pre)]
    P(f"=== pre-injury chart spot: {len(E)} first-three-games-back rows, RB / WR / TE, 2019-24 ===")
    P("\n  what the chart showed in the last week he missed, vs his spot going into his last game:")
    E["cat"] = np.where(E.listed == E.pre, "same spot", np.where(E.off, "dropped off the chart", np.where(E.listed > E.pre, "listed lower", "listed higher")))
    for c, x in E.groupby("cat"):
        P(f"    {c:24s} n {len(x):4d}  actual / (base x return ramp) {x.act.sum()/x.base.sum():.3f}   by position: " + "  ".join(f"{p} {y.act.sum()/y.base.sum():.2f} (n {len(y)})" for p, y in x.groupby("pos") if len(y) >= 15))
    P("    starters (first string before the absence) only:")
    for c, x in E[E.pre == 1].groupby("cat"):
        P(f"      {c:22s} n {len(x):4d}  actual / base {x.act.sum()/x.base.sum():.3f}   games missed: median {x.k.median():.0f}")
    D = E[E.B != E.base]
    P(f"\n  rows where the two rules differ: {len(D)} ({100*len(D)/len(E):.0f}% of return rows)")
    def cmp(x, lab):
        if len(x) < 25: P(f"    {lab:34s} n {len(x)} (too few)"); return
        ea, eb = (x.base - x.act) ** 2, (x.B - x.act) ** 2
        wins = sum(1 for Y in YEARS if (x.year == Y).sum() >= 5 and ea[x.year == Y].mean() < eb[x.year == Y].mean()); ny = sum(1 for Y in YEARS if (x.year == Y).sum() >= 5)
        P(f"    {lab:34s} n {len(x):4d}  actual {x.act.mean():5.2f}  pre-injury spot predicts {x.base.mean():5.2f}  chart-as-listed predicts {x.B.mean():5.2f}  | MSE pre-injury vs listed {100*(ea.mean()/eb.mean()-1):+.1f}%  MAE {100*(np.abs(x.base-x.act).mean()/np.abs(x.B-x.act).mean()-1):+.1f}%  seasons better {wins}/{ny}")
    cmp(D, "all")
    for p in ("RB", "WR", "TE"): cmp(D[D.pos == p], p)
    cmp(D[D.pre == 1], "was first string")
    cmp(D[D.off], "dropped off the chart")
    cmp(D[(~D.off) & (D.listed > D.pre)], "listed lower")
    cmp(D[D.b == "4+"], "missed 4+ games")
    cmp(D[D.b != "4+"], "missed 1-3 games")
    for g in (1, 2, 3): cmp(D[D.back == g], f"game {g} back")
    Fd = pd.DataFrame(fill)
    if len(Fd):
        P(f"\n  the teammate listed first while a starter was out ({len(Fd)} cases): points per game")
        for p, x in [("ALL", Fd)] + list(Fd.groupby("pos")):
            if len(x) < 20: continue
            xb = x.dropna(subset=["before"])
            P(f"    {p:4s} n {len(x):3d}  before the injury {xb.before.mean():5.2f}  while he was out {x.during.mean():5.2f}  after he returned {x.after.mean():5.2f}  (kept {100*(x.after.mean()-xb.before.mean())/max(1e-9, x.during.mean()-xb.before.mean()):.0f}% of the bump)")
    log.close()

if __name__ == "__main__":
    main()
