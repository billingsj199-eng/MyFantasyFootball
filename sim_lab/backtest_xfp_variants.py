#!/usr/bin/env python3
"""
Can the site's xFP be improved on games that already happened?

Play-level harness: every target and rush 2019-25 (nflverse pbp) with the
opportunity's context. Each xFP VARIANT is a set of lookup tables refit
LEAVE-ONE-YEAR-OUT (train on the other six seasons, apply to the held-out
one), so no variant gets in-sample credit. Variants are cumulative unless
noted.

  V0  site today: catch% + yds by air-yards bucket; rec TD by yardline x
      end-zone throw; rush yds/TD by yardline (QB own tables)   [refit LOYO]
  V1  + receiver POSITION (RB/WR/TE) as a table dimension
  V2  + yardline bucket for catch% / yards (a target at the 3 can't gain 10)
  V3  + nflfastR per-play models: xrec = cp, xyds = cp*(air+xyac_mean);
      TD table kept (falls back to V2 where cp/xyac are null)
  V4  + rush context: QB scramble vs designed; short-yardage / down bucket;
      shotgun; TD by yardline x goal-to-go
  V5  + situation: garbage time (4Q |diff|>=17) and 2-min drill buckets
  V6  + expected INT (QB, by air-yards bucket) -> only matters for full-
      scoring bias; graded separately

Grades (rows with xFP >= 5 unless noted): weekly r / MAE / bias vs actual;
rest-of-season r from the first 3 and 5 games vs plain PPG; YoY
r(xFP/g_Y, PPG_Y+1). Half-PPR. Log: xfp_variants_backtest.log.
"""
import os, sys, io
import numpy as np
import pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
CACHE = r"E:\MyFantasyFootball\pbp_cache"
YEARS = list(range(2019, 2026))
POS4 = ("QB", "RB", "WR", "TE")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xfp_variants_backtest.log")
_log = open(LOG, "w", encoding="utf-8")
def P(*a):
    s = " ".join(str(x) for x in a); print(s); _log.write(s + "\n"); _log.flush()

def ab_bucket(a):  # <0, 0-4, 5-9, 10-14, 15-19, 20-29, 30+
    return np.select([a < 0, a < 5, a < 10, a < 15, a < 20, a < 30], [0, 1, 2, 3, 4, 5], 6)
def yl_bucket(y):  # <=5, 6-10, 11-20, 21-40, 41+
    return np.select([y <= 5, y <= 10, y <= 20, y <= 40], [0, 1, 2, 3], 4)
def yl_td_bucket(y):  # 1,2,3,4,5,10,20,40,100
    return np.select([y <= 1, y <= 2, y <= 3, y <= 4, y <= 5, y <= 10, y <= 20, y <= 40], [0, 1, 2, 3, 4, 5, 6, 7], 8)
def dist_bucket(d):  # <=2, 3-6, 7+
    return np.select([d <= 2, d <= 6], [0, 1], 2)

def load():
    pl = pd.read_csv(os.path.join(CACHE, "players.csv"), usecols=["gsis_id", "display_name", "position"], low_memory=False)
    pl = pl[pl.position.isin(POS4) & pl.gsis_id.notna()]
    pos_of = dict(zip(pl.gsis_id, pl.position))
    cols = ["season_type", "week", "pass_attempt", "rush_attempt", "sack", "passer_player_id", "receiver_player_id",
            "rusher_player_id", "yardline_100", "air_yards", "complete_pass", "receiving_yards", "rushing_yards", "passing_yards",
            "pass_touchdown", "rush_touchdown", "interception", "td_player_id", "cp", "xyac_mean_yardage", "qb_scramble",
            "shotgun", "down", "ydstogo", "goal_to_go", "score_differential", "qtr", "half_seconds_remaining"]
    T, R = [], []
    for Y in YEARS:
        d = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), usecols=cols, low_memory=False)
        d = d[d.season_type == "REG"].copy(); d["Y"] = Y
        d["yl"] = d.yardline_100.fillna(50.0)
        d["situ"] = np.select([(d.qtr >= 4) & (d.score_differential.abs() >= 17), (d.half_seconds_remaining <= 120)], [1, 2], 0)
        d["down_b"] = d.down.fillna(1).clip(1, 4).astype(int)
        t = d[(d.pass_attempt == 1) & (d.sack != 1) & d.receiver_player_id.notna()].copy()
        t["pos"] = t.receiver_player_id.map(pos_of)
        t["qpos"] = t.passer_player_id.map(pos_of)
        t["ay"] = t.air_yards.fillna(0.0)
        t["ab"] = ab_bucket(t.ay.values); t["ylb"] = yl_bucket(t.yl.values); t["ez"] = (t.ay >= t.yl).astype(int)
        t["yltd"] = np.select([t.yl <= 5, t.yl <= 10, t.yl <= 20, t.yl <= 40], [0, 1, 2, 3], 4)
        t["comp"] = (t.complete_pass == 1).astype(int)
        t["ryd"] = np.where(t.comp == 1, t.receiving_yards.fillna(0.0), 0.0)
        t["rtd"] = ((t.pass_touchdown == 1) & (t.td_player_id.isna() | (t.td_player_id == t.receiver_player_id))).astype(int)
        t["intc"] = (t.interception == 1).astype(int)
        t["xy_fast"] = t.cp * (t.ay + t.xyac_mean_yardage)  # NaN where either model is null
        T.append(t[["Y", "week", "receiver_player_id", "passer_player_id", "pos", "qpos", "ab", "ylb", "ez", "yltd", "down_b", "situ", "cp", "xy_fast", "comp", "ryd", "rtd", "intc", "yl"]])
        r = d[(d.rush_attempt == 1) & d.rusher_player_id.notna()].copy()
        r["pos"] = r.rusher_player_id.map(pos_of); r = r[r.pos.notna()]
        r["isqb"] = (r.pos == "QB").astype(int)
        r["scr"] = (r.qb_scramble == 1).astype(int)
        r["ylb"] = yl_bucket(r.yl.values); r["yltd"] = yl_td_bucket(r.yl.values)
        r["distb"] = dist_bucket(r.ydstogo.fillna(10).values); r["sg"] = (r.shotgun == 1).astype(int); r["g2g"] = (r.goal_to_go == 1).astype(int)
        r["ryd"] = r.rushing_yards.fillna(0.0)
        r["rtd"] = ((r.rush_touchdown == 1) & (r.td_player_id.isna() | (r.td_player_id == r.rusher_player_id))).astype(int)
        R.append(r[["Y", "week", "rusher_player_id", "pos", "isqb", "scr", "ylb", "yltd", "distb", "sg", "g2g", "down_b", "situ", "ryd", "rtd"]])
        P(f"  pbp {Y}: {len(t)} targets, {len(r)} rushes")
    return pd.concat(T, ignore_index=True), pd.concat(R, ignore_index=True)

def fit_apply(train, test, keys, col, min_n=40):
    """Per-key mean on train applied to test with coarsening fallback
    (drop the last key until n >= min_n; final fallback = grand mean)."""
    out = pd.Series(np.nan, index=test.index)
    filled = pd.Series(False, index=test.index)
    for k in range(len(keys), 0, -1):
        ks = keys[:k]
        g = train.groupby(ks)[col].agg(["mean", "size"])
        g = g[g["size"] >= min_n]["mean"]
        m = test[ks].apply(tuple, axis=1).map(g) if k > 1 else test[ks[0]].map(g)
        sel = (~filled) & m.notna()
        out[sel] = m[sel]; filled |= sel
    out[~filled] = train[col].mean()
    return out.values

VARIANTS = ["V0", "V1", "V2", "V3", "V4", "V5"]
def expectations(T, R, variant, Y):
    """Return per-play expected rec/yds/td (targets), yds/td (rushes), xint for held-out year Y."""
    tr, te = T[T.Y != Y], T[T.Y == Y].copy()
    rr, re_ = R[R.Y != Y], R[R.Y == Y].copy()
    v = int(variant[1])
    tkeys = ["ab"]
    if v >= 1: tkeys = ["ab", "pos"]
    if v >= 2: tkeys = ["ab", "pos", "ylb"]
    if v >= 5: tkeys = tkeys + ["situ"]
    te["xrec"] = fit_apply(tr, te, tkeys, "comp")
    te["xyds"] = fit_apply(tr, te, tkeys, "ryd")
    if v >= 3:
        ok = te.xy_fast.notna() & te.cp.notna()
        te.loc[ok, "xrec"] = te.loc[ok, "cp"]
        te.loc[ok, "xyds"] = te.loc[ok, "xy_fast"]
    tdkeys = ["yltd", "ez"] if v < 1 else ["yltd", "ez", "pos"]
    te["xtd"] = fit_apply(tr, te, tdkeys, "rtd")
    te["xint"] = fit_apply(tr, te, ["ab"], "intc") if v >= 0 else 0.0
    rkeys = ["ylb", "isqb"]
    if v >= 4: rkeys = ["ylb", "isqb", "scr", "distb", "sg"]
    if v >= 5: rkeys = rkeys + ["situ"]
    re_["xyds"] = fit_apply(rr, re_, rkeys, "ryd")
    rtdkeys = ["yltd", "isqb"] if v < 4 else ["yltd", "isqb", "scr", "g2g"]
    re_["xtd"] = fit_apply(rr, re_, rtdkeys, "rtd")
    return te, re_

def player_weeks(te, re_):
    rows = {}
    def get(pid, pos, wk):
        return rows.setdefault((pid, wk), {"pos": pos, "x": 0.0, "a": 0.0, "xint": 0.0, "int": 0, "opps": 0})
    for r in te.itertuples(index=False):
        if isinstance(r.pos, str):
            q = get(r.receiver_player_id, r.pos, r.week); q["opps"] += 1
            q["x"] += 0.5 * r.xrec + 0.1 * r.xyds + 6 * r.xtd
            q["a"] += 0.5 * r.comp + 0.1 * r.ryd + 6 * r.rtd
        if r.qpos == "QB":
            q = get(r.passer_player_id, "QB", r.week); q["opps"] += 1
            q["x"] += 0.04 * r.xyds + 4 * r.xtd; q["a"] += 0.04 * r.ryd + 4 * r.rtd
            q["xint"] += r.xint; q["int"] += r.intc
    for r in re_.itertuples(index=False):
        q = get(r.rusher_player_id, r.pos, r.week); q["opps"] += 1
        q["x"] += 0.1 * r.xyds + 6 * r.xtd; q["a"] += 0.1 * r.ryd + 6 * r.rtd
    return rows

def grade(df, label):
    """df: Y,pid,pos,wk,xfp,act (+xint,int). Prints one block."""
    P(f"\n--- {label} ---")
    P("  pos    n(x>=5)   r     MAE   bias  | RoS r G=3 (xFP vs PPG)  G=5 (xFP vs PPG)  | YoY r(xFP_Y,PPG_Y+1) vs r(PPG,PPG)")
    df = df.sort_values(["Y", "pid", "wk"])
    res = {}
    for pos in POS4:
        d = df[df.pos == pos]; e = d[d.xfp >= 5]
        r = np.corrcoef(e.xfp, e.act)[0, 1]; mae = (e.act - e.xfp).abs().mean(); bias = (e.act - e.xfp).mean()
        ros = {}
        for G in (3, 5):
            rows = []
            for (Y, pid), grp in d.groupby(["Y", "pid"]):
                if len(grp) < G + 4: continue
                h, t = grp.iloc[:G], grp.iloc[G:]
                if (h.act.mean() + h.xfp.mean()) / 2 < 5: continue
                rows.append((h.act.mean(), h.xfp.mean(), t.act.mean()))
            a = np.array(rows)
            ros[G] = (np.corrcoef(a[:, 1], a[:, 2])[0, 1], np.corrcoef(a[:, 0], a[:, 2])[0, 1])
        s = d.groupby(["Y", "pid"]).agg(g=("act", "size"), ppg=("act", "mean"), xpg=("xfp", "mean")).reset_index()
        s = s[s.g >= 8]
        m = s.merge(s.assign(Y=s.Y - 1), on=["Y", "pid"], suffixes=("", "_n")); m = m[(m.ppg + m.xpg) / 2 >= 5]
        yoy = (np.corrcoef(m.xpg, m.ppg_n)[0, 1], np.corrcoef(m.ppg, m.ppg_n)[0, 1])
        res[pos] = (r, mae, bias, ros[3][0], ros[5][0], yoy[0])
        P(f"  {pos:3s} {len(e):7d}   {r:+.3f}  {mae:5.2f}  {bias:+5.2f} |   {ros[3][0]:+.3f} vs {ros[3][1]:+.3f}       {ros[5][0]:+.3f} vs {ros[5][1]:+.3f}     |   {yoy[0]:+.3f} vs {yoy[1]:+.3f}")
    return res

def main():
    P("=== xFP VARIANTS (LOYO-refit tables, 2019-25, half-PPR) ===")
    T, R = load()
    summary = {}
    for variant in VARIANTS:
        parts = []
        for Y in YEARS:
            te, re_ = expectations(T, R, variant, Y)
            rows = player_weeks(te, re_)
            parts += [(Y, pid, q["pos"], wk, q["x"], q["a"], q["xint"], q["int"]) for (pid, wk), q in rows.items() if q["opps"] > 0]
        df = pd.DataFrame(parts, columns=["Y", "pid", "pos", "wk", "xfp", "act", "xint", "int"])
        summary[variant] = grade(df, variant)
        if variant == "V0":
            q = df[(df.pos == "QB") & (df.xfp >= 5)]
            P(f"  V6 check (QB expected INT by air-yards bucket): full-scoring bias {((q.act - 2*q['int']) - q.xfp).mean():+.2f}/g -> with xINT {((q.act - 2*q['int']) - (q.xfp - 2*q.xint)).mean():+.2f}/g; xINT/g {q.xint.mean():.2f} vs INT/g {q['int'].mean():.2f}")
    P("\n=== SUMMARY: change vs V0 (weekly r among xFP>=5 rows | RoS r from 3 games | YoY r) ===")
    P("  var   " + "   ".join(f"{p}: dr  dRoS3  dYoY" for p in POS4))
    for variant in VARIANTS[1:]:
        cells = []
        for p in POS4:
            a, b = summary[variant][p], summary["V0"][p]
            cells.append(f"{p}: {a[0]-b[0]:+.3f} {a[3]-b[3]:+.3f} {a[5]-b[5]:+.3f}")
        P(f"  {variant}   " + "   ".join(cells))
    P(f"\nlog: {LOG}")

if __name__ == "__main__":
    main()
