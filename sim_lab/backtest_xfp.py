#!/usr/bin/env python3
"""
How accurate is the site's xFP (2026-09-15, standard definition)?

Rebuilds SIM_XFP_2026-style expected points for every QB/RB/WR/TE player-week
2019-25 from the nflverse pbp cache with the SAME tables/functions the site
uses (pull_pace_tracker.build_xfp_2026) and grades it three ways:

  1. DESCRIPTIVE  weekly xFP vs actual: r, R^2, MAE, bias per position
                  (tables pooled on 2018-25 = in-sample for level; the per-
                  year drift table shows how far one season sits from pooled)
  2. PREDICTIVE   season-to-date xFP/g vs actual PPG as a predictor of
                  (a) the NEXT game and (b) the rest of the season
  3. STABILITY    YoY: xFP/g(Y) vs PPG(Y+1) against PPG(Y) vs PPG(Y+1)

Scoring = half-PPR site default (0.5/rec, 0.1/yd, 6/TD, 0.04/pass yd, 4/pass
TD). xFP ignores INT / fumbles / 2-pt (standard), so "actual" here is graded
both ways (with and without the penalty/bonus items).
Log: xfp_backtest.log.
"""
import os, sys, io
import numpy as np
import pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pull_pace_tracker as ppt
from pull_pace_tracker import (_xfp_ab, _xtd_rec, _xfp_rush, _xfp_qb_rush_td, _xtd, XFP_CATCH, XFP_TGT_YDS, CACHE)

YEARS = list(range(2019, 2026))
POS4 = ("QB", "RB", "WR", "TE")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xfp_backtest.log")
_log = open(LOG, "w", encoding="utf-8")
def P(*a):
    s = " ".join(str(x) for x in a)
    print(s); _log.write(s + "\n"); _log.flush()

def score(rec, recyd, rectd, ruyd, rutd, pyd, ptd):
    return 0.5 * rec + 0.1 * (recyd + ruyd) + 6 * (rectd + rutd) + 0.04 * pyd + 4 * ptd

def build_year(Y, pos_of):
    p = os.path.join(CACHE, f"play_by_play_{Y}.csv.gz")
    cols = ["season_type", "week", "pass_attempt", "rush_attempt", "sack", "passer_player_id", "receiver_player_id",
            "rusher_player_id", "yardline_100", "air_yards", "complete_pass", "receiving_yards", "rushing_yards",
            "passing_yards", "pass_touchdown", "rush_touchdown", "interception", "fumble_lost", "two_point_conv_result",
            "lateral_receiver_player_id", "lateral_rusher_player_id", "posteam", "td_player_id"]
    pbp = pd.read_csv(p, usecols=cols, low_memory=False)
    pbp = pbp[pbp.season_type == "REG"]
    acc = {}
    def row(pid, wk):
        a = acc.setdefault(pid, {})
        return a.setdefault(int(wk), {"tg": 0, "xrec": 0.0, "xrecyd": 0.0, "xrectd": 0.0, "car": 0, "xruyd": 0.0, "xrutd": 0.0,
                                      "att": 0, "xpyd": 0.0, "xptd": 0.0,
                                      "rec": 0, "recyd": 0.0, "rectd": 0, "ruyd": 0.0, "rutd": 0, "pyd": 0.0, "ptd": 0,
                                      "int": 0, "fum": 0, "two": 0})
    pa = pbp[(pbp.pass_attempt == 1) & (pbp.sack != 1)]
    for r in pa.itertuples(index=False):
        yl = float(r.yardline_100) if pd.notna(r.yardline_100) else 50.0
        rcv = r.receiver_player_id; targeted = pd.notna(rcv)
        if targeted:
            a = float(r.air_yards) if pd.notna(r.air_yards) else 0.0
            b = _xfp_ab(a); ez = a >= yl
            xtd = _xtd_rec(yl, ez)
            comp = r.complete_pass == 1
            ry = float(r.receiving_yards) if pd.notna(r.receiving_yards) else 0.0
            if rcv in pos_of:
                q = row(rcv, r.week); q["tg"] += 1; q["xrec"] += XFP_CATCH[b]; q["xrecyd"] += XFP_TGT_YDS[b]; q["xrectd"] += xtd
                if comp:
                    q["rec"] += 1; q["recyd"] += ry
                    if r.pass_touchdown == 1 and (pd.isna(r.td_player_id) or r.td_player_id == rcv): q["rectd"] += 1
                if r.fumble_lost == 1 and comp: q["fum"] += 1
                if isinstance(r.two_point_conv_result, str) and r.two_point_conv_result == "success": q["two"] += 1
        pid = r.passer_player_id
        if pd.notna(pid) and pos_of.get(pid) == "QB":
            q = row(pid, r.week); q["att"] += 1
            if targeted:
                q["xpyd"] += XFP_TGT_YDS[b]; q["xptd"] += xtd
            if r.complete_pass == 1:
                q["pyd"] += float(r.passing_yards) if pd.notna(r.passing_yards) else 0.0
                if r.pass_touchdown == 1: q["ptd"] += 1
            if r.interception == 1: q["int"] += 1
    ru = pbp[(pbp.rush_attempt == 1) & pbp.rusher_player_id.notna()]
    for r in ru.itertuples(index=False):
        pid = r.rusher_player_id
        if pid not in pos_of: continue
        yl = float(r.yardline_100) if pd.notna(r.yardline_100) else 50.0
        is_qb = pos_of[pid] == "QB"
        q = row(pid, r.week); q["car"] += 1; q["xruyd"] += _xfp_rush(yl, is_qb)
        q["xrutd"] += _xfp_qb_rush_td(yl) if is_qb else _xtd(yl, True)
        q["ruyd"] += float(r.rushing_yards) if pd.notna(r.rushing_yards) else 0.0
        if r.rush_touchdown == 1 and (pd.isna(r.td_player_id) or r.td_player_id == pid): q["rutd"] += 1
        if r.fumble_lost == 1: q["fum"] += 1
        if isinstance(r.two_point_conv_result, str) and r.two_point_conv_result == "success": q["two"] += 1
    rows = []
    for pid, wks in acc.items():
        pos = pos_of[pid]
        for wk, q in wks.items():
            x = score(q["xrec"], q["xrecyd"], q["xrectd"], q["xruyd"], q["xrutd"], q["xpyd"], q["xptd"])
            a = score(q["rec"], q["recyd"], q["rectd"], q["ruyd"], q["rutd"], q["pyd"], q["ptd"])
            a_full = a - 2 * q["int"] - 2 * q["fum"] + 2 * q["two"]
            opps = q["tg"] + q["car"] + q["att"]
            x_td = 6 * (q["xrectd"] + q["xrutd"]) + 4 * q["xptd"]
            a_td = 6 * (q["rectd"] + q["rutd"]) + 4 * q["ptd"]
            rows.append((Y, pid, pos, wk, opps, x, a, a_full, x_td, a_td,
                         q["tg"], q["xrec"], q["rec"], q["xrecyd"], q["recyd"], q["car"], q["xruyd"], q["ruyd"], q["att"], q["xpyd"], q["pyd"]))
    df = pd.DataFrame(rows, columns=["Y", "pid", "pos", "wk", "opps", "xfp", "act", "act_full", "xtd", "atd",
                                     "tg", "xrec", "rec", "xrecyd", "recyd", "car", "xruyd", "ruyd", "att", "xpyd", "pyd"])
    P(f"  pbp {Y}: {len(df)} player-weeks ({(df.opps>0).sum()} with an opportunity)")
    return df

def r2(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    if len(x) < 3: return float("nan"), float("nan")
    r = np.corrcoef(x, y)[0, 1]
    return r, r * r

def main():
    pl = pd.read_csv(os.path.join(CACHE, "players.csv"), usecols=["gsis_id", "display_name", "position"], low_memory=False)
    pl = pl[pl.position.isin(POS4) & pl.gsis_id.notna()]
    pos_of = dict(zip(pl.gsis_id, pl.position)); name_of = dict(zip(pl.gsis_id, pl.display_name))
    P("=== xFP backtest (site tables, standard definition, half-PPR) ===")
    df = pd.concat([build_year(Y, pos_of) for Y in YEARS], ignore_index=True)
    df = df[df.opps > 0].copy()

    # ---------- 1. descriptive: weekly xFP vs actual ----------
    P("\n=== 1. WEEKLY xFP vs ACTUAL (player-weeks 2019-25 with >= 1 opportunity) ===")
    P("  pos   n      r     R^2    MAE   bias(act-xFP)  | rows with xFP >= 5:   n      r     R^2    MAE   bias | TD-only r")
    for pos in POS4:
        d = df[df.pos == pos]
        r, rr = r2(d.xfp, d.act); mae = (d.act - d.xfp).abs().mean(); bias = (d.act - d.xfp).mean()
        e = d[d.xfp >= 5]
        r5, rr5 = r2(e.xfp, e.act); mae5 = (e.act - e.xfp).abs().mean(); bias5 = (e.act - e.xfp).mean()
        rtd, _ = r2(e.xtd, e.atd)
        P(f"  {pos:3s} {len(d):6d}  {r:+.3f}  {rr:.3f}  {mae:5.2f}  {bias:+6.2f}          |                   {len(e):6d}  {r5:+.3f}  {rr5:.3f}  {mae5:5.2f}  {bias5:+6.2f} | {rtd:+.3f}")
    P("  (bias incl. INT/fumble/2-pt, which xFP ignores by design:)")
    for pos in POS4:
        e = df[(df.pos == pos) & (df.xfp >= 5)]
        P(f"    {pos:3s} bias(act_full - xFP) = {(e.act_full - e.xfp).mean():+.2f}/g")

    P("\n  Per-year LEVEL drift (rows xFP >= 5): does one season sit above/below the pooled tables?")
    P("  year  pos   n     act/xFP   catch%/xCatch   yds-per-tgt/x   rushYds/x   TD/xTD")
    for Y in YEARS:
        for pos in POS4:
            e = df[(df.Y == Y) & (df.pos == pos) & (df.xfp >= 5)]
            if not len(e): continue
            cr = e.rec.sum() / max(1, e.xrec.sum()); yt = e.recyd.sum() / max(1, e.xrecyd.sum()) if pos != "QB" else e.pyd.sum() / max(1, e.xpyd.sum())
            ry = e.ruyd.sum() / max(1e-9, e.xruyd.sum()); td = e.atd.sum() / max(1e-9, e.xtd.sum())
            P(f"  {Y}  {pos:3s} {len(e):5d}    {e.act.sum()/e.xfp.sum():.3f}      {cr:.3f}          {yt:.3f}         {ry:.3f}       {td:.3f}")

    # ---------- 2. predictive ----------
    P("\n=== 2. PREDICTIVE: season-to-date xFP/g vs actual PPG (players with >= 1 opp that week) ===")
    df = df.sort_values(["Y", "pid", "wk"])
    df["g"] = df.groupby(["Y", "pid"]).cumcount() + 1
    df["cum_x"] = df.groupby(["Y", "pid"]).xfp.cumsum(); df["cum_a"] = df.groupby(["Y", "pid"]).act.cumsum()
    df["ppg_sofar"] = (df.cum_a - df.act) / (df.g - 1).replace(0, np.nan)
    df["xpg_sofar"] = (df.cum_x - df.xfp) / (df.g - 1).replace(0, np.nan)
    P("  a) NEXT GAME actual vs prior-games PPG / xFP-per-game / 50-50 blend (rows: >= 4 prior games, avg(prior PPG, prior xFP/g) >= 5 — neutral filter)")
    P("  pos    n     r(PPG)   r(xFP/g)   r(blend)   |  MAE(PPG-scaled)  MAE(xFP-scaled)  MAE(blend)")
    for pos in POS4:
        d = df[(df.pos == pos) & (df.g >= 5) & ((df.ppg_sofar + df.xpg_sofar) / 2 >= 5)]
        y = d.act.values; xa = d.ppg_sofar.values; xx = d.xpg_sofar.values; xb = 0.5 * (xa + xx)
        ra, _ = r2(xa, y); rx, _ = r2(xx, y); rb, _ = r2(xb, y)
        def mae_fit(x):
            A = np.vstack([x, np.ones_like(x)]).T; k, c = np.linalg.lstsq(A, y, rcond=None)[0]
            return np.abs(y - (k * x + c)).mean()
        P(f"  {pos:3s} {len(d):6d}   {ra:+.3f}    {rx:+.3f}     {rb:+.3f}     |     {mae_fit(xa):5.2f}            {mae_fit(xx):5.2f}          {mae_fit(xb):5.2f}")

    P("\n  b) REST OF SEASON PPG from the first G games (players with >= G+4 games; avg(PPG, xFP/g) >= 5 through G — neutral filter)")
    P("  G   pos    n    r(PPG)   r(xFP/g)   r(blend)  | RMSE PPG  RMSE xFP  RMSE blend  (scaled fits)   | mean shrink of PPG toward xFP that fits best")
    for G in (3, 5, 8):
        for pos in POS4:
            rows = []
            for (Y, pid), grp in df[df.pos == pos].groupby(["Y", "pid"]):
                if len(grp) < G + 4: continue
                head = grp.iloc[:G]; tail = grp.iloc[G:]
                if (head.act.mean() + head.xfp.mean()) / 2 < 5: continue
                rows.append((head.act.mean(), head.xfp.mean(), tail.act.mean()))
            if len(rows) < 30: continue
            a = np.array(rows); y = a[:, 2]; xa = a[:, 0]; xx = a[:, 1]
            ra, _ = r2(xa, y); rx, _ = r2(xx, y); rb, _ = r2(0.5 * (xa + xx), y)
            def rmse_fit(x):
                A = np.vstack([x, np.ones_like(x)]).T; k, c = np.linalg.lstsq(A, y, rcond=None)[0]
                return np.sqrt(((y - (k * x + c)) ** 2).mean())
            best = None
            for w in np.arange(0, 1.01, 0.1):
                e = rmse_fit((1 - w) * xa + w * xx)
                if best is None or e < best[1]: best = (w, e)
            P(f"  {G}   {pos:3s} {len(rows):5d}   {ra:+.3f}    {rx:+.3f}     {rb:+.3f}    |  {rmse_fit(xa):5.2f}     {rmse_fit(xx):5.2f}      {rmse_fit(0.5*(xa+xx)):5.2f}                    | w(xFP)={best[0]:.1f} RMSE {best[1]:.2f}")

    # ---------- 3. YoY ----------
    P("\n=== 3. YEAR-OVER-YEAR (>= 8 games both seasons, avg(PPG, xFP/g) >= 5 in Y) ===")
    P("  pos    n    r(PPG_Y, PPG_Y+1)   r(xFP/g_Y, PPG_Y+1)   r(FPOE/g_Y, FPOE/g_Y+1)   r(TDluck/g_Y, TDluck/g_Y+1)")
    seas = df.groupby(["Y", "pid", "pos"]).agg(g=("act", "size"), ppg=("act", "mean"), xpg=("xfp", "mean"),
                                                 tdo=("atd", "mean"), xtd=("xtd", "mean")).reset_index()
    seas = seas[seas.g >= 8]
    for pos in POS4:
        s = seas[seas.pos == pos]
        m = s.merge(s.assign(Y=s.Y - 1), on=["Y", "pid", "pos"], suffixes=("", "_n"))
        m = m[(m.ppg + m.xpg) / 2 >= 5]
        if len(m) < 30: continue
        r1, _ = r2(m.ppg, m.ppg_n); r2_, _ = r2(m.xpg, m.ppg_n)
        r3, _ = r2(m.ppg - m.xpg, m.ppg_n - m.xpg_n); r4, _ = r2(m.tdo - m.xtd, m.tdo_n - m.xtd_n)
        P(f"  {pos:3s} {len(m):5d}        {r1:+.3f}               {r2_:+.3f}                 {r3:+.3f}                    {r4:+.3f}")

    # ---------- 4. biggest single-week misses (sanity) ----------
    P("\n=== 4. Largest weekly FPOE 2025 (sanity: are the misses TD-driven?) ===")
    d = df[df.Y == 2025].copy(); d["fpoe"] = d.act - d.xfp; d["tdpart"] = d.atd - d.xtd
    for _, r in d.reindex(d.fpoe.abs().sort_values(ascending=False).index).head(8).iterrows():
        P(f"  W{int(r.wk):2d} {name_of.get(r.pid, r.pid):22s} {r.pos}  act {r.act:5.1f}  xFP {r.xfp:5.1f}  FPOE {r.fpoe:+5.1f}  (TD part {r.tdpart:+5.1f})")
    P(f"\nlog: {LOG}")

if __name__ == "__main__":
    main()
