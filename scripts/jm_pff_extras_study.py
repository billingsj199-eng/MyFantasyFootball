"""jm_pff_extras_study.py - do the PFF Pro college tables add anything beyond the JM model?

Joins the backtest table (scripts/jm_extract_table.js output: every graded drafted player
2017-2024 with pick + live JM) to the season-level PFF NCAA extra facets pulled by
scripts/pull_pff_ncaa.py --seasons ... (receiving scheme / concept / depth, passing
pressure / depth / concept / time-in-pocket), builds a per-player profile from the
FINAL college season (falls back to the season before when the final season is too
thin), and reports, per position:

    rho      raw Spearman with the graded career outcome (jm_outcome_grades.json)
    |pick    partial Spearman controlling for draft pick
    |jm      partial Spearman controlling for the live JM grade (= new information)
    yrs+     draft classes (of those with n >= 6) where the |jm sign is positive

Join: PFF rows carry draft_season, so name + draft_season == draft year is exact; name +
season in (yr-1, yr-2) is the fallback for rows without it.

    python scripts/jm_pff_extras_study.py --table <jm_table.json> [--out results.json]

FINDINGS 2026-10-06 (graded career outcome, classes 2017-2024): nothing ships.
  QB 47 features / RB 25 / WR 25: no leave-one-class-out gain over JM (best +.008).
  TE deep yards per target looked strong on 2016-18 + 2020 seasons only (|jm .43,
  LOYO +.066, n 64) and faded with every season filled in (n 99: |jm .26, LOYO +.008,
  4/8 classes). In the real model (jm_eval_cfgs.js, weights .05-.16, weight picked on
  training classes) per-class Spearman fell .576 -> .553 and the tier penalty rose.
  --te-deep-cfgs needs a calcJM hook reading window._JM_EXP.teDeep (removed after
  the test - re-add the 'teDeep' score next to 'athl' to rerun).
  Coverage: man/zone splits are charted only from the 2018 season on (2016-17 have
  ~90 players); receiving/depth season calls 504 from 2019 on - those seasons were
  rebuilt by summing weekly tables.
"""
import argparse
import glob
import json
import os
import re
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jm_model_lab import spearman, partial_spearman  # noqa: E402

NCAA = r"E:\MyFantasyFootball\pbp_cache\pff\ncaa"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POS = ["QB", "RB", "WR", "TE"]
MIN_ROUTES = {"WR": 150, "TE": 120, "RB": 60}
MIN_DROPBACKS = 150


def nz(s):
    return re.sub(r"[^a-z]", "", re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", (s or "").lower()))


def load_facet(key):
    frames = []
    for f in glob.glob(os.path.join(NCAA, "pff_ncaa_%s_[0-9][0-9][0-9][0-9].csv" % key)):
        d = pd.read_csv(f, low_memory=False)
        frames.append(d)
    if not frames:
        return None
    d = pd.concat(frames, ignore_index=True)
    d["nz"] = d.player.map(nz)
    return d


def num(d, c):
    return pd.to_numeric(d[c], errors="coerce") if c in d.columns else pd.Series(np.nan, index=d.index)


def sdiv(a, b):
    return np.where((b > 0) & np.isfinite(b), a / np.where(b > 0, b, 1), np.nan)


def receiving_features(sch, con, dep):
    """-> DataFrame keyed (player_id, season) with receiving features."""
    out = pd.DataFrame({"player_id": sch.player_id, "season": sch.season, "nz": sch.nz,
                        "draft_season": num(sch, "draft_season"), "position": sch.position})
    mr, zr = num(sch, "man_routes").fillna(0), num(sch, "zone_routes").fillna(0)
    out["routes"] = mr + zr
    out["man_yprr"] = num(sch, "man_yprr")
    out["zone_yprr"] = num(sch, "zone_yprr")
    out["man_route_grade"] = num(sch, "man_grades_pass_route")
    out["zone_route_grade"] = num(sch, "zone_grades_pass_route")
    out["man_minus_zone_yprr"] = out.man_yprr - out.zone_yprr
    mt, zt = num(sch, "man_targets").fillna(0), num(sch, "zone_targets").fillna(0)
    out["man_tgt_per_route"] = sdiv(mt, mr)
    out["zone_tgt_per_route"] = sdiv(zt, zr)
    out["man_route_share"] = sdiv(mr, mr + zr)
    out["man_contested_rate"] = num(sch, "man_contested_catch_rate")
    out["man_epa_per_route"] = sdiv(num(sch, "man_epa"), mr)
    yds = num(sch, "man_yards").fillna(0) + num(sch, "zone_yards").fillna(0)
    out["yprr_all"] = sdiv(yds, mr + zr)
    out["targets"] = mt + zt
    out["yards"] = yds
    out = out.set_index(["player_id", "season"])
    if con is not None:
        c = con.set_index(["player_id", "season"])
        c = c[~c.index.duplicated()]
        sr = num(c, "screen_routes").fillna(0)
        sy = num(c, "screen_yards").fillna(0)
        st = num(c, "screen_targets").fillna(0)
        slr = num(c, "slot_routes").fillna(0)
        j = out.join(pd.DataFrame({"sr": sr, "sy": sy, "st": st, "slr": slr,
                                   "slot_yprr": num(c, "slot_yprr"),
                                   "slot_grade": num(c, "slot_grades_pass_route")}), how="left")
        out["screen_tgt_share"] = sdiv(j.st, j.targets)
        out["nonscreen_yprr"] = sdiv(j.yards - j.sy, j.routes - j.sr)
        out["slot_route_share"] = sdiv(j.slr, j.routes)
        out["slot_yprr"] = j.slot_yprr
    if dep is not None:
        dd = dep.set_index(["player_id", "season"])
        dd = dd[~dd.index.duplicated()]
        def col(prefix, stat):
            # depth facet columns look like deep_<stat> / <side>_deep_<stat>; take the all-field one
            for c in (prefix + "_" + stat,):
                if c in dd.columns:
                    return num(dd, c)
            return pd.Series(np.nan, index=dd.index)
        deep_t = col("deep", "targets")
        beh_t = col("behind_los", "targets")
        j = out.join(pd.DataFrame({"deep_t": deep_t, "beh_t": beh_t,
                                   "deep_yprr": col("deep", "yprr"),
                                   "deep_grade": col("deep", "grades_pass_route"),
                                   "deep_caught": col("deep", "caught_percent"),
                                   "int_yprr": col("medium", "yprr"),
                                   "short_yprr": col("short", "yprr")}), how="left")
        out["deep_tgt_share"] = sdiv(j.deep_t, j.targets)
        out["behind_los_tgt_share"] = sdiv(j.beh_t, j.targets)
        for c in ("deep_yprr", "deep_grade", "deep_caught", "int_yprr", "short_yprr"):
            out[c] = j[c]
    return out.reset_index()


def passing_features(pre, pdp, pco, ptm):
    base = None
    if pre is not None:
        p = pre
        base = pd.DataFrame({"player_id": p.player_id, "season": p.season, "nz": p.nz,
                             "draft_season": num(p, "draft_season"), "position": p.position})
        for side in ("pressure", "no_pressure", "blitz", "no_blitz"):
            for stat in ("grades_pass", "btt_rate", "twp_rate", "ypa", "accuracy_percent", "dropbacks", "sack_percent"):
                base["%s_%s" % (side, stat)] = num(p, "%s_%s" % (side, stat))
        db = base.pressure_dropbacks.fillna(0) + base.no_pressure_dropbacks.fillna(0)
        base["dropbacks"] = db
        base["pressure_rate"] = sdiv(base.pressure_dropbacks, db)
        base["pressure_grade_drop"] = base.no_pressure_grades_pass - base.pressure_grades_pass
        base["pressure_to_sack"] = num(p, "pressure_sack_percent") if "pressure_sack_percent" in p.columns else base.pressure_sack_percent
        base = base.set_index(["player_id", "season"])
    def add(d, prefix_map):
        nonlocal base
        if d is None or base is None:
            return
        x = d.set_index(["player_id", "season"])
        x = x[~x.index.duplicated()]
        for out_col, src in prefix_map.items():
            if src in x.columns:
                base = base.join(num(x, src).rename(out_col), how="left")
    add(pdp, {"deep_grade": "deep_grades_pass", "deep_acc": "deep_accuracy_percent", "deep_btt": "deep_btt_rate",
              "deep_att": "deep_attempts", "short_grade": "short_grades_pass", "behind_grade": "behind_los_grades_pass",
              "medium_grade": "medium_grades_pass"})
    add(pco, {"pa_grade": "pa_grades_pass", "npa_grade": "npa_grades_pass", "pa_dropbacks": "pa_dropbacks",
              "screen_att": "screen_attempts", "npa_ypa": "npa_ypa", "npa_btt": "npa_btt_rate"})
    add(ptm, {"quick_grade": "less_grades_pass", "long_grade": "more_grades_pass", "ttt": "avg_time_to_throw",
              "long_dropbacks": "more_dropbacks"})
    if base is None:
        return None
    base = base.reset_index()
    if "pa_dropbacks" in base:
        base["pa_rate"] = sdiv(base.pa_dropbacks, base.dropbacks)
    if "deep_att" in base:
        base["deep_att_rate"] = sdiv(base.deep_att, base.dropbacks)
    if "long_dropbacks" in base:
        base["long_rate"] = sdiv(base.long_dropbacks, base.dropbacks)
    return base


def pick_rows(feat, tbl, vol_col, min_vol):
    """For each table player -> the feature row of the final college season (or the one before)."""
    if feat is None:
        return pd.DataFrame(index=tbl.index)
    by_draft = {}
    by_name = {}
    for i, r in feat.iterrows():
        by_name.setdefault(r.nz, []).append(i)
        if np.isfinite(r.draft_season):
            by_draft.setdefault((r.nz, int(r.draft_season)), []).append(i)
    rows = {}
    for ti, t in tbl.iterrows():
        key = nz(t["name"])
        yr = int(t.draftYr)
        cand = by_draft.get((key, yr)) or [i for i in by_name.get(key, []) if feat.at[i, "season"] in (yr - 1, yr - 2)]
        if not cand:
            continue
        c = feat.loc[cand]
        c = c[c.season <= yr - 1].sort_values("season", ascending=False)
        if c.empty:
            continue
        ok = c[c[vol_col] >= min_vol]
        rows[ti] = (ok.iloc[0] if not ok.empty else c.iloc[0])
    return pd.DataFrame.from_dict(rows, orient="index")


def write_te_deep_cfgs(rec, tbl, out):
    """Configs for scripts/jm_eval_cfgs.js: the live TE tables with 'teDeep' blended in at
    several weights (floor and ceiling scaled by 1-w), plus the window._JM_EXP payload."""
    g = tbl[tbl.pos == "TE"]
    f = pick_rows(rec, g, "routes", MIN_ROUTES["TE"])
    x = pd.to_numeric(f.get("deep_yprr"), errors="coerce")
    mp = {g.at[i, "name"]: round(float(v), 2) for i, v in x.items() if np.isfinite(v)}
    vals = np.array(list(mp.values()))
    exp = {"teDeep": {"map": mp, "mu": round(float(vals.mean()), 3), "sd": round(float(vals.std()), 3)}}
    print("TE deep map: %d players, mu %.2f sd %.2f" % (len(mp), vals.mean(), vals.std()))
    src = open(os.path.join(ROOT, "data", "jm_weights.js"), encoding="utf-8").read()
    srcc = open(os.path.join(ROOT, "data", "jm_ceiling_weights.js"), encoding="utf-8").read()

    def te_table(s):
        line = [ln for ln in s.splitlines() if re.match(r"\s*TE:\s*\{", ln)][0]
        body = line.split("{", 1)[1].split("}", 1)[0]
        return {k.strip(): float(v) for k, v in (kv.split(":") for kv in body.split(","))}
    fl, ce = te_table(src), te_table(srcc)
    cfgs = {"exp_only": {"exp": exp}}
    for w in (0.05, 0.08, 0.12, 0.16):
        cfgs["teDeep_%.2f" % w] = {
            "floor": {"TE": dict({k: round(v * (1 - w), 5) for k, v in fl.items()}, teDeep=w)},
            "ceiling": {"TE": dict({k: round(v * (1 - w), 5) for k, v in ce.items()}, teDeep=w)},
            "exp": exp}
    json.dump(cfgs, open(out, "w"), indent=1)
    print("wrote", out, list(cfgs))


def loyo_gain(j, feat):
    """Leave-one-draft-class-out: on the other classes fit
        pct(grade) ~ a + b*pct(jm) + c*pct(feat)   (players missing feat get pct .5)
    then score the held-out class. -> mean per-class Spearman(blend) - Spearman(jm),
    weighted by class size, and the count of classes that improved."""
    x = pd.to_numeric(j[feat], errors="coerce")
    d = pd.DataFrame({"yr": j.draftYr, "g": j.grade, "jm": j.jm, "x": x}).dropna(subset=["g", "jm"])
    if d.x.notna().sum() < 30:
        return dict(loyo_gain=np.nan, loyo_yrs="")
    d["pg"] = d.groupby("yr").g.rank(pct=True)
    d["pj"] = d.groupby("yr").jm.rank(pct=True)
    d["px"] = d.groupby("yr").x.rank(pct=True).fillna(0.5)
    tot, n, up, yrs = 0.0, 0, 0, 0
    for yr in sorted(d.yr.unique()):
        tr, te = d[d.yr != yr], d[d.yr == yr]
        if len(te) < 8 or te.x.notna().sum() < 4:
            continue
        A = np.c_[np.ones(len(tr)), tr.pj, tr.px]
        coef = np.linalg.lstsq(A, tr.pg, rcond=None)[0]
        pred = coef[1] * te.pj + coef[2] * te.px
        s1, s0 = spearman(pred, te.g), spearman(te.jm, te.g)
        if np.isfinite(s1) and np.isfinite(s0):
            tot += (s1 - s0) * len(te)
            n += len(te)
            yrs += 1
            up += s1 > s0
    return dict(loyo_gain=tot / n if n else np.nan, loyo_yrs="%d/%d" % (up, yrs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--te-deep-cfgs", default="", help="write jm_eval_cfgs.js configs for the TE deep-target test")
    a = ap.parse_args()
    t = json.load(open(a.table, encoding="utf-8"))
    tbl = pd.DataFrame([{k: v for k, v in r.items() if k not in ("comps", "o_raw")} for r in t["rows"]])
    og = json.load(open(os.path.join(ROOT, "scripts", "jm_outcome_grades.json"), encoding="utf-8"))["players"]
    tbl["grade"] = [(og.get("%s|%s" % (r["name"], r["draftYr"])) or {}).get("grade") for _, r in tbl.iterrows()]
    tbl["pickn"] = pd.to_numeric(tbl.o_pick, errors="coerce").fillna(300)
    tbl = tbl[tbl.grade.notna()].copy()
    print("players with graded outcome: %d" % len(tbl))

    sch, con, dep = load_facet("receiving_scheme"), load_facet("receiving_concept"), load_facet("receiving_depth")
    pre, pdp, pco, ptm = (load_facet(k) for k in ("passing_pressure", "passing_depth", "passing_concept", "passing_time"))
    for k, d in (("scheme", sch), ("concept", con), ("depth", dep), ("pressure", pre), ("pdepth", pdp),
                 ("pconcept", pco), ("ptime", ptm)):
        print("  %-9s %s" % (k, "missing" if d is None else "%d rows, seasons %s" % (len(d), sorted(d.season.unique()))))

    rec = receiving_features(sch, con, dep) if sch is not None else None
    pas = passing_features(pre, pdp, pco, ptm)
    if a.te_deep_cfgs:
        write_te_deep_cfgs(rec, tbl, a.te_deep_cfgs)
        return
    results = {}
    for pos in POS:
        g = tbl[tbl.pos == pos]
        if pos == "QB":
            f = pick_rows(pas, g, "dropbacks", MIN_DROPBACKS)
        else:
            f = pick_rows(rec, g, "routes", MIN_ROUTES[pos])
        if f.empty:
            continue
        drop = {"player_id", "season", "nz", "draft_season", "position"}
        feats = [c for c in f.columns if c not in drop]
        for c in feats:
            f[c] = pd.to_numeric(f[c], errors="coerce")
        j = g.join(f[feats], how="left")
        print("\n=== %s  n=%d  matched=%d" % (pos, len(g), f.index.isin(g.index).sum()))
        print("  %-24s %5s %6s %6s %6s %5s %7s %5s" % ("feature", "n", "rho", "|pick", "|jm", "yrs+", "LOYO+", "yrs"))
        res = []
        for c in feats:
            x = pd.to_numeric(j[c], errors="coerce")
            if x.notna().sum() < 20:
                continue
            r0 = spearman(x, j.grade)
            rp, n = partial_spearman(x, j.grade, -np.log(j.pickn))
            rj, _ = partial_spearman(x, j.grade, j.jm)
            pos_yrs, tot_yrs = 0, 0
            for yr, gy in j.groupby("draftYr"):
                # per class: x vs (outcome rank - JM rank) = what the grade got wrong that year
                resid = gy.grade.rank(pct=True) - gy.jm.rank(pct=True)
                ry = spearman(x[gy.index], resid)
                if np.isfinite(ry):
                    tot_yrs += 1
                    pos_yrs += ry * np.sign(rj or 1) > 0
            res.append(dict(feature=c, n=int(n), rho=r0, p_pick=rp, p_jm=rj, yrs="%d/%d" % (pos_yrs, tot_yrs)))
        for d in res:
            d.update(loyo_gain(j, d["feature"]))
        res.sort(key=lambda d: -abs(d["p_jm"] if np.isfinite(d["p_jm"]) else 0))
        for d in res[:14]:
            print("  %-24s %5d %6.2f %6.2f %6.2f %5s %+7.3f %5s" % (d["feature"], d["n"], d["rho"], d["p_pick"], d["p_jm"], d["yrs"],
                                                               d["loyo_gain"], d["loyo_yrs"]))
        g_all = [d["loyo_gain"] for d in res if np.isfinite(d["loyo_gain"])]
        print("  features tested %d | LOYO gain > +.01: %d | < -.01: %d" % (
            len(g_all), sum(x > .01 for x in g_all), sum(x < -.01 for x in g_all)))
        results[pos] = res
    if a.out:
        json.dump(results, open(a.out, "w"), indent=1, default=float)
        print("\nwrote", a.out)


if __name__ == "__main__":
    main()
