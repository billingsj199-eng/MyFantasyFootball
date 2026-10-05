#!/usr/bin/env python3
"""
PFF PRO METRIC SCREEN (2026-10-05, Jack: "look at the new stats to add and see if there is any good correlation in
backtesting to help with sims").

Stage A of two, same method as research_metric_atlas.py: every NEW PFF Pro metric (pull_pff_pro_history.py ->
pbp_cache/pff/pro_hist), as it stood ENTERING each game (season to date through the previous week, shrunk toward
the player's / team's prior season with K = 4 games), correlated with
  next    the player's points that game
  ros     his points per game over the rest of the season
  res     what the live projection missed that game (actual - rebuilt live stack)      <- can improve weekly
  resRos  what it missed over the rest of the season                                       <- can improve season-long
Spearman by position, 2019-25, rows with live projection >= 5 and 2+ games (data/metric_atlas_rows.parquet).
Split-half check: the residual r in 2019-22 and in 2023-25 must share a sign to be called consistent.

Families
  player   receiving (catch rate over expected, positively / negatively graded play rates, hands grade, lined up vs
           CB / S / LB), passing (grade, big-time / turnover-worthy rates, accuracy and completion over expected, EPA
           without play-action / screens, time to throw, pressure to sack, pass rate over expected), rushing (graded
           play rates, explosive rate, zone share)
  own team PFF team tables (wEPA, series conversion, pressure over expectation allowed, yards before contact,
           stuff rate, run / pass rate over expectation, play-action / screen rate, target share by position ...)
           + offensive line pass-block win rate (snap-weighted from the pass-blocking report)
  opponent PFF defensive team tables (wEPA allowed, pressure over expectation, yards before contact allowed,
           air-yard vs YAC share allowed, man rate, opponent tendencies ...)
Log pff_pro_screen.log; table -> data/pff_pro_screen.csv; feature rows -> data/pff_pro_features.parquet (stage B).
"""
import glob, json, os, re, sys, warnings
import numpy as np, pandas as pd
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = r"E:\MyFantasyFootball\pbp_cache"
HIST = os.path.join(CACHE, "pff", "pro_hist")
K = 4.0
warnings.filterwarnings("ignore")
TEAMFIX = {"ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "LA": "LAR", "OAK": "LV", "SD": "LAC", "SL": "LAR",
           "WSH": "WAS", "JAC": "JAX"}
TEAM_SKIP = {"teamId", "abbreviation", "name", "offensiveTurnovers", "defensiveTurnovers", "scrambleRushingYards",
             "scrambleRushingTouchdowns", "designedRushingYards", "designedRushingTouchdowns", "passingTouchdownsAllowed",
             "interceptions", "totalPressures", "sacks", "scrambleRushingYardsAllowed", "scrambleRushingTouchdownsAllowed",
             "designedRushingYardsAllowed", "designedRushingTouchdownsAllowed"}
OFF_CATS = ["offense-overall-success", "offense-passing", "offense-rushing"]
DEF_CATS = ["defense-overall-success", "defense-passing", "defense-rushing", "defense-opponent-tendencies"]


def tm(x):
    return TEAMFIX.get(x, x)


def load(kind, name, y, tag):
    f = os.path.join(HIST, f"{kind}_{name}_{y}_{tag}.json")
    if not os.path.exists(f):
        return None
    return json.load(open(f, encoding="utf-8")).get("rows") or []


def num(r, k):
    v = r.get(k)
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def ratio(r, a, b):
    d = num(r, b)
    return num(r, a) / d if d and d > 0 else np.nan


# ---------------- per-table feature builders: rows -> {id: (games, {feat: value})}
def f_receiving(rows):
    out = {}
    for r in rows:
        if not (num(r, "targets") > 0 or num(r, "routes") > 0):
            continue
        cb, s, lb = num(r, "linedUpVsCb"), num(r, "linedUpVsS"), num(r, "linedUpVsLb")
        tot = np.nansum([cb, s, lb])
        out[int(r["playerId"])] = (num(r, "gamesPlayed"), {
            "rec_catch_oe": num(r, "receptionsOe"),
            "rec_catch_oe_per_tgt": ratio(r, "receptionsOeTotal", "targets"),
            "rec_pos_graded": num(r, "offensePosGradedRate"),
            "rec_neg_graded": num(r, "offenseNegGradedRate"),
            "rec_hands_grade": num(r, "gradesHandsDrop"),
            "rec_vs_lb_share": lb / tot if tot > 0 else np.nan,
            "rec_vs_cb_share": cb / tot if tot > 0 else np.nan})
    return out


def f_passing(rows):
    out = {}
    for r in rows:
        if not num(r, "dropbacks") > 0:
            continue
        out[int(r["playerId"])] = (num(r, "playerGameCount"), {
            "qb_grade_pass": num(r, "gradesPass"), "qb_btt_rate": num(r, "bttRate"), "qb_twp_rate": num(r, "twpRate"),
            "qb_accuracy": num(r, "accuracyPercent"), "qb_accuracy_oe": num(r, "accuracyOe"),
            "qb_completion_oe": num(r, "completionOe"), "qb_ttt": num(r, "avgTimeToThrow"),
            "qb_p2s": num(r, "pressureToSackRate"), "qb_sack_pct": num(r, "sackPercent"),
            "qb_epa": num(r, "epa"), "qb_npa_epa": num(r, "npaEpa"), "qb_noscreen_epa": num(r, "noScreenEpa"),
            "qb_pos_epa_pct": num(r, "positiveEpaPercent"), "qb_pass_rate_oe": num(r, "passRateOe"),
            "qb_pos_graded": num(r, "offensePosGradedRate"), "qb_neg_graded": num(r, "offenseNegGradedRate"),
            "qb_pressured_rate": ratio(r, "defGenPressures", "dropbacks"),
            "qb_scramble_rate": ratio(r, "scrambles", "dropbacks"),
            "qb_grade_run": num(r, "gradesRun")})
    return out


def f_rushing(rows):
    out = {}
    for r in rows:
        if not num(r, "attempts") > 0:
            continue
        out[int(r["playerId"])] = (num(r, "playerGameCount"), {
            "ru_pos_graded": num(r, "offensePosGradedRate"), "ru_neg_graded": num(r, "offenseNegGradedRate"),
            "ru_explosive_rate": ratio(r, "explosive", "attempts"), "ru_zone_share": ratio(r, "zoneAttempts", "attempts"),
            "ru_designed_ypc": ratio(r, "designedYards", "attempts"), "ru_grade_run": num(r, "gradesRun")})
    return out


def f_ol(rows):
    """team offensive line: snap-weighted pass-block win rate etc. keyed by team code"""
    acc = {}
    for r in rows:
        pos = str(r.get("position") or "")
        if not re.fullmatch(r"(L|R)?(T|G)|C|OL|OT|OG", pos):
            continue
        w = num(r, "snapCountsPassBlock")
        if not w > 0:
            continue
        t = tm(r.get("teamAbbreviation") or r.get("team") or "")
        a = acc.setdefault(t, {"w": 0.0, "pbwr": 0.0, "tps": 0.0, "tpsw": 0.0, "pra": 0.0, "pbe": 0.0, "g": 0.0})
        for k, src in (("pbwr", "pbwr"), ("pra", "pressureRateAllowed"), ("pbe", "pbe")):
            v = num(r, src)
            if v == v:
                a[k] += v * w
        a["w"] += w
        v, w2 = num(r, "truePassSetPbwr"), num(r, "truePassSetSnapCountsPassBlock")
        if v == v and w2 > 0:
            a["tps"] += v * w2; a["tpsw"] += w2
        a["g"] = max(a["g"], num(r, "gamesPlayed") if num(r, "gamesPlayed") == num(r, "gamesPlayed") else 0)
    return {t: (a["g"], {"ol_pbwr": a["pbwr"] / a["w"], "ol_true_set_pbwr": a["tps"] / a["tpsw"] if a["tpsw"] else np.nan,
                         "ol_pressure_rate_allowed": a["pra"] / a["w"], "ol_pbe": a["pbe"] / a["w"]})
            for t, a in acc.items() if a["w"] > 0}


def f_team(rows, prefix, cat):
    out = {}
    for r in rows:
        t = tm(r.get("abbreviation") or "")
        feats = {}
        for k, v in r.items():
            if k in TEAM_SKIP or k.endswith("Rank") or not isinstance(v, (int, float)) or isinstance(v, bool):
                continue
            feats[f"{prefix}{k}"] = float(v)
        out[t] = (np.nan, feats)
    return out


def shrink(cur, prev, n):
    """season to date shrunk toward last season with K games of weight"""
    out = {}
    keys = set(cur or {}) | set(prev or {})
    for k in keys:
        a = (cur or {}).get(k, np.nan); b = (prev or {}).get(k, np.nan)
        if a != a and b != b:
            continue
        if a != a:
            out[k] = b
        elif b != b or not (n > 0):
            out[k] = a
        else:
            out[k] = (K * b + n * a) / (K + n)
    return out


def build_maps(years):
    """{(table, year, thru): {id: (games, feats)}}; thru 'season' for full prior season"""
    specs = [("rep", "receiving", f_receiving), ("rep", "passing", f_passing), ("rep", "rushing", f_rushing),
             ("rep", "pass-blocking", f_ol)]
    specs += [("team", c, (lambda rows, c=c: f_team(rows, "own_", c))) for c in OFF_CATS]
    specs += [("team", c, (lambda rows, c=c: f_team(rows, "opp_", c))) for c in DEF_CATS]
    maps = {}
    for kind, name, fn in specs:
        for y in years:
            for tag in ["season"] + [f"thru{t}" for t in range(1, 18)]:
                rows = load(kind, name, y, tag)
                if rows is not None:
                    maps[(name, y, tag)] = fn(rows)
    return maps, specs


def main():
    lf = open(os.path.join(HERE, "pff_pro_screen.log"), "w", encoding="utf-8")

    def P(s=""):
        print(s, flush=True); lf.write(s + "\n")

    M = pd.read_parquet(os.path.join(HERE, "data", "metric_atlas_rows.parquet"))
    pl = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "pff_id"]).dropna()
    g2pff = {g: int(p) for p, g in zip(pl.pff_id, pl.gsis_id)}
    maps, specs = build_maps(range(2018, 2026))
    P(f"PFF Pro tables loaded: {len(maps)}")
    feat_rows = []
    for i, r in enumerate(M.itertuples(index=False)):
        y, wk = int(r.year), int(r.wk)
        thru = f"thru{wk - 1}"
        row = {"year": y, "pid": r.pid, "wk": wk}
        pffid = g2pff.get(r.pid)
        team, opp = r.team, r.opp
        for kind, name, _ in specs:
            if kind == "rep" and name != "pass-blocking":
                key = pffid
            elif name == "pass-blocking" or name in OFF_CATS:
                key = team
            else:
                key = opp
            if key is None:
                continue
            cur = maps.get((name, y, thru), {}).get(key)
            prev = maps.get((name, y - 1, "season"), {}).get(key)
            if cur is None and prev is None:
                continue
            n = cur[0] if cur is not None and cur[0] == cur[0] else (wk - 1)
            row.update(shrink(cur[1] if cur else None, prev[1] if prev else None, n))
        feat_rows.append(row)
    F = pd.DataFrame(feat_rows)
    F.to_parquet(os.path.join(HERE, "data", "pff_pro_features.parquet"))
    D = M.merge(F, on=["year", "pid", "wk"], how="left")
    base = D[(D.live >= 5) & (D.g >= 2)]
    feats = [c for c in F.columns if c not in ("year", "pid", "wk")]
    P(f"rows: {len(base)} player-weeks (live >= 5, 2+ games); new metrics: {len(feats)}")
    P("Spearman r by position: next / rest-of-season PPG || residual next / residual rest of season; "
      "'*' = |residual r| >= .05 AND same sign in 2019-22 and 2023-25")
    recs = []
    for f in feats:
        for pos in ("QB", "RB", "WR", "TE"):
            d = base[(base.pos == pos) & base[f].notna()]
            if len(d) < 300 or d[f].nunique() < 5:
                continue
            r1 = spearmanr(d[f], d.act).correlation
            d2 = d[d.ros.notna()]
            r2 = spearmanr(d2[f], d2.ros).correlation if len(d2) >= 300 else np.nan
            r3 = spearmanr(d[f], d.res).correlation
            d4 = d[d.resRos.notna()]
            r4 = spearmanr(d4[f], d4.resRos).correlation if len(d4) >= 300 else np.nan
            e, l = d[d.year <= 2022], d[d.year >= 2023]
            h3 = (spearmanr(e[f], e.res).correlation, spearmanr(l[f], l.res).correlation)
            e4, l4 = e[e.resRos.notna()], l[l.resRos.notna()]
            h4 = (spearmanr(e4[f], e4.resRos).correlation if len(e4) > 100 else np.nan,
                  spearmanr(l4[f], l4.resRos).correlation if len(l4) > 100 else np.nan)
            recs.append({"metric": f, "pos": pos, "n": len(d), "r_next": r1, "r_ros": r2, "r_res": r3, "r_resRos": r4,
                         "res_early": h3[0], "res_late": h3[1], "resRos_early": h4[0], "resRos_late": h4[1]})
    A = pd.DataFrame(recs)
    A.to_csv(os.path.join(HERE, "data", "pff_pro_screen.csv"), index=False)

    def consistent(a, b, full):
        return abs(full) >= 0.05 and a == a and b == b and np.sign(a) == np.sign(b) == np.sign(full)

    for pos in ("QB", "RB", "WR", "TE"):
        x = A[A.pos == pos].copy()
        x["key"] = x.r_res.abs().fillna(0).combine(x.r_resRos.abs().fillna(0), max)
        x = x.sort_values("key", ascending=False)
        P(f"\n=== {pos} ({len(x)} metrics) ===")
        P(f"  {'metric':40s} {'n':>5s} {'next':>6s} {'ros':>6s} || {'res':>6s} [{'19-22':>6s} {'23-25':>6s}] {'resRos':>6s} [{'19-22':>6s} {'23-25':>6s}]")
        for r in x.head(30).itertuples():
            f1 = "*" if consistent(r.res_early, r.res_late, r.r_res) else " "
            f2 = "*" if consistent(r.resRos_early, r.resRos_late, r.r_resRos) else " "
            P(f"  {r.metric:40s} {r.n:5d} {r.r_next:+6.3f} {r.r_ros:+6.3f} || {r.r_res:+6.3f}{f1}[{r.res_early:+6.3f} {r.res_late:+6.3f}] "
              f"{r.r_resRos:+6.3f}{f2}[{r.resRos_early:+6.3f} {r.resRos_late:+6.3f}]")
    P("\nstrongest RAW predictors of next-game points among the new metrics (top 8 per position):")
    for pos in ("QB", "RB", "WR", "TE"):
        x = A[A.pos == pos].reindex(A[A.pos == pos].r_next.abs().sort_values(ascending=False).index).head(8)
        P(f"  {pos}: " + ", ".join(f"{r.metric} {r.r_next:+.2f}" for r in x.itertuples()))
    lf.close()


if __name__ == "__main__":
    main()
