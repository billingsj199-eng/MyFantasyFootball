#!/usr/bin/env python3
"""
Build data/sim_prior_health.js for the engine from a COMPLETED season (2026-10-07; run by the January refresh task).

  p[name] = [healthy ppg, all ppg, hurt games, healthy games, games]          -> live banged-up prior lift (SIM_HEALTH_PRIOR)
  h[name] = {h3h, h3g, l8h[]}  healthy 3-yr weighted PPG (.5/.3/.2 over season, season-1, season-2; seasons with 4+ healthy
            games; 8+ healthy games total), its game count, and the last 8 healthy game points of (season-1, season)
            oldest first (the engine appends the new season's games)                  -> shadow healthy-history prior (SIM_NC_HEALTHY)
Hurt game = listed Questionable, or final practice Limited / DNP (nflverse injuries), or snap share under 75% of his season
median (data/snap_counts.js). Players = every QB / RB / WR / TE with 1+ played game in the season in weekly_stats_active.js;
keys are written both as the raw name and the normalized name so the engine's p.name / p.norm lookups both hit.
Usage: python build_prior_health.py --season 2026   (downloads injuries_<season>.parquet from nflverse if missing)
"""
import argparse, json, os, re, sys, urllib.request
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_sim_calibration as cal
import bt_common as B
W3 = (0.5, 0.3, 0.2)
OUT = os.path.join(HERE, "data", "sim_prior_health.js")


def ensure_injuries(Y):
    p = os.path.join(B.CACHE, f"injuries_{Y}.parquet")
    if os.path.exists(p): return p
    url = f"https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{Y}.parquet"
    print(f"downloading {url}"); urllib.request.urlretrieve(url, p); return p


def load_injuries(years):
    inj = {}
    for Y in years:
        try: p = ensure_injuries(Y)
        except Exception as e: print(f"WARN injuries {Y}: {e}"); continue
        d = pd.read_parquet(p, columns=["game_type", "team", "week", "gsis_id", "report_status", "practice_status"])
        d = d[d.game_type == "REG"]
        for t, w, gid, rs, pr in zip(d.team, d.week, d.gsis_id, d.report_status, d.practice_status):
            if isinstance(gid, str): inj[(Y, B.tm(str(t)), int(w), gid)] = (str(rs) if isinstance(rs, str) else "", str(pr) if isinstance(pr, str) else "")
    return inj


def load_snaps():
    s = open(os.path.join(cal.REPO, "data", "snap_counts.js"), encoding="utf-8").read(); s = s[s.index("{"):]
    raw, _ = json.JSONDecoder().raw_decode(s)
    return {cal.norm(nm): {int(y): {int(w): float(v) for w, v in (d.get("w") or {}).items()} for y, d in yrs.items()} for nm, yrs in raw.items()}


def load_gsis():
    d = pd.read_csv(os.path.join(B.CACHE, "players.csv"), usecols=["gsis_id", "display_name", "position"], low_memory=False)
    d = d[d.gsis_id.notna() & d.display_name.notna() & d.position.isin(["QB", "RB", "WR", "TE", "FB", "HB"])]
    out = {}
    for gid, nm, ps in zip(d.gsis_id, d.display_name, d.position): out.setdefault((cal.norm(nm), "RB" if ps in ("FB", "HB") else ps), gid)
    return out


def week_team(Y, w, opp):
    o = cal.OPP_ALIAS.get(opp, opp)
    for t, s in cal.SCHEDULES.get(Y, {}).items():
        if s.get(str(w)) == o: return t
    return None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--season", type=int, required=True); a = ap.parse_args(); S = a.season
    years = [S, S - 1, S - 2]
    inj = load_injuries(years); snaps = load_snaps(); gsis = load_gsis()
    print(f"injury rows {len(inj):,}, snap players {len(snaps):,}, gsis ids {len(gsis):,}")
    def hurt(nm, ps, Y, w, opp):
        gid = gsis.get((cal.norm(nm), ps)); t = week_team(Y, w, opp) if opp else None
        rs, pr = inj.get((Y, t, w, gid), ("", "")) if (gid and t) else ("", "")
        if rs == "Questionable" or "Limited" in pr or "Did Not" in pr: return True
        sy = snaps.get(cal.norm(nm), {}).get(Y, {}); vals = [v for v in sy.values() if v > 0]
        return len(vals) >= 4 and w in sy and sy[w] > 0 and sy[w] < 0.75 * float(np.median(vals))
    def games_of(rec, nm, ps, Y):
        out = []
        for w in rec.get("seasons", {}).get(str(Y), []):
            if cal.played(w) and isinstance(w.get("fpts"), (int, float)): out.append((int(w["wk"]), float(w["fpts"]), hurt(nm, ps, Y, int(w["wk"]), w.get("opp"))))
        return sorted(out)
    # player universe: everyone with a played game in the season (raw names from weekly_stats_active.js; collision-aware record)
    raw = open(os.path.join(cal.REPO, "data", "weekly_stats_active.js"), encoding="utf-8").read(); d, _ = json.JSONDecoder().raw_decode(raw, raw.index("{"))
    names = []
    for nm, rec0 in d.items():
        ps = rec0.get("pos")
        if ps not in ("QB", "RB", "WR", "TE"): continue
        rec = cal.weekly_rec(nm, ps) or rec0
        if any(cal.played(w) for w in rec.get("seasons", {}).get(str(S), [])): names.append((nm, ps, rec))
    print(f"players with a {S} game: {len(names)}")
    P, H = {}, {}
    for nm, ps, rec in names:
        gl = games_of(rec, nm, ps, S)
        if len(gl) >= 4:
            hp = [f for (w, f, h) in gl if not h]; ap_ = [f for (w, f, h) in gl]
            P[nm] = [round(float(np.mean(hp)), 2) if hp else None, round(float(np.mean(ap_)), 2), len(ap_) - len(hp), len(hp), len(ap_)]
        num = den = 0.0; hg = 0
        for k, Y in enumerate(years):
            pts = [f for (w, f, h) in games_of(rec, nm, ps, Y) if not h]
            if len(pts) >= 4: num += W3[k] * (sum(pts) / len(pts)); den += W3[k]; hg += len(pts)
        h3h = round(num / den, 2) if (den > 0 and hg >= 8) else None
        tail = [f for Y in (S - 1, S) for (w, f, h) in games_of(rec, nm, ps, Y) if not h][-8:]
        if h3h is not None or tail: H[nm] = {"h3h": h3h, "h3g": hg, "l8h": [round(x, 1) for x in tail]}
    # normalized-name aliases so p.norm lookups hit too
    for d in (P, H):
        for nm in list(d.keys()):
            k = cal.norm(nm)
            if k not in d: d[k] = d[nm]
    out = {"season": S, "built": pd.Timestamp.now().strftime("%Y-%m-%d"), "src": "build_prior_health.py (nflverse injury reports + snap_counts.js + weekly_stats_active.js)",
           "fields": "p[name] = [healthy ppg, all ppg, hurt games, healthy games, games] half-PPR; hurt = listed Questionable, practice Limited/DNP, or snap share < 75% of own season median",
           "hFields": "h3h = healthy 3-yr weighted PPG, h3g = healthy games in it, l8h = last 8 healthy game points (season-1, season) oldest first", "p": P, "h": H}
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("// AUTO-GENERATED by build_prior_health.py - last season's healthy vs all points per game (live banged-up prior lift) + healthy history (shadow prior)\n")
        fh.write("window.SIM_PRIOR_HEALTH = " + json.dumps(out) + ";\n")
    print(f"wrote {OUT}: p {sum(1 for k in P if k == k)} entries (incl. aliases), h {len(H)}; season {S}")


if __name__ == "__main__":
    main()
