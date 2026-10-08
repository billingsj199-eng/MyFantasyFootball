"""regen_backtest_outcomes.py - roll data/backtest_outcomes.js forward one NFL season.

Run each January after Week 18 (Task Scheduler "MFF January Outcomes Refresh",
scripts/january_outcomes_refresh.ps1). The file feeds the JM backtest page and
the offline tuner (scripts/jm_optimize.js), so comparability matters more than
purity: FINALIZED verdicts are never recomputed.

What changes
  * entries whose outcome window was still open (pending / partial) are
    recomputed with the newly completed season (e.g. 2024 RB/WR/TE finalize
    after 2026; 2023 QBs finalize after 2026),
  * new cohorts are added (the class drafted in `season`-1 gets its 2nd
    season, the class drafted in `season` enters as rookies / pending),
  * everything else is copied byte-for-byte from the current file.

Verdict formula
  The original curve formula is not in the repo; generate_extended_backtest.py
  carries a reconstruction that agrees with the stored verdicts only ~70% of the
  time. So this script CALIBRATES it: recomputed curveScores for players whose
  stored verdict is final are mapped onto the stored scores with an isotonic
  (monotone) fit, and that mapping is applied to every recomputed entry before
  the stud/hit/contributor/bust thresholds (70/45/22). Recomputed entries carry
  `"regen": <season>` so the tuner can be run with or without them.

Safety gate: verdict agreement on the calibration set must be >= 75% (or
--force); ~79% is the reconstruction's ceiling (2026-09-30 test: QB 90 / WR 81 / TE 76 / RB 74). Backs up the current file to data/backtest_outcomes.js.bak_<date>,
bumps the backtest_outcomes.js ?v= in index.html (current tag read from disk).

    python scripts/regen_backtest_outcomes.py --season 2026 --dry-run
    python scripts/regen_backtest_outcomes.py --season 2026
"""
import argparse
import datetime
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
import generate_extended_backtest as gb  # noqa: E402

OUT = "data/backtest_outcomes.js"
INDEX_HTML = "index.html"
THRESH = [("stud", 70), ("hit", 45), ("contributor", 22)]
FIRST_COHORT = 2017


def verdict_of(score):
    if score is None:
        return "pending"
    for v, t in THRESH:
        if score >= t:
            return v
    return "bust"


def nrm(s):
    s = (s or "").lower()
    s = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def pava(xs, ys):
    """Isotonic (non-decreasing) regression: returns sorted breakpoints [(x, fitted_y)]."""
    pts = sorted(zip(xs, ys))
    blocks = [[x, y, 1] for x, y in pts]          # [x_last, mean_y, n]
    merged = []
    for b in blocks:
        merged.append(b)
        while len(merged) >= 2 and merged[-2][1] > merged[-1][1]:
            a, c = merged[-2], merged[-1]
            n = a[2] + c[2]
            merged[-2] = [c[0], (a[1] * a[2] + c[1] * c[2]) / n, n]
            merged.pop()
    return [(b[0], b[1]) for b in merged]


def make_mapper(bp):
    def f(x):
        if x is None:
            return None
        if x <= bp[0][0]:
            return bp[0][1]
        for (x0, y0), (x1, y1) in zip(bp, bp[1:]):
            if x <= x1:
                return y0 + (y1 - y0) * ((x - x0) / (x1 - x0) if x1 > x0 else 0)
        return bp[-1][1]
    return f


def window_complete(entry, season):
    ry = min(s["yr"] for s in entry["seasons"]) if entry.get("seasons") else None
    if ry is None:
        return entry.get("verdict") not in ("pending",) and not entry.get("partial")
    return ry + gb.WINDOW_YEARS.get(entry["pos"], 3) - 1 <= season


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, help="last COMPLETED NFL season (default: previous calendar year in Jan-Jul)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="write even if the calibration gate fails")
    ap.add_argument("--min-agree", type=float, default=75.0)
    a = ap.parse_args()
    today = datetime.date.today()
    season = a.season or (today.year - 1 if today.month <= 7 else today.year)
    gb.CURRENT_SEASON = season
    print("=== backtest outcomes regen: completed season %d (%s) ===" % (season, today))

    data = gb.load_all_data()
    old = data["backtest"]
    weekly = dict(data["weekly_retired"]); weekly.update(data["weekly_active"])
    wk_nrm = {nrm(k): k for k in weekly}
    cb_nrm = {nrm(k): k for k in data["combine"]}
    all_seasons = {n: gb.get_player_seasons(r) for n, r in weekly.items()}
    all_pos = {n: (r.get("pos") if isinstance(r, dict) else None) for n, r in weekly.items()}
    ranks = gb.compute_season_ranks(all_pos, all_seasons)
    max_season_seen = max((s["yr"] for ss in all_seasons.values() for s in ss), default=0)
    print("weekly stats: %d players, latest season on disk %d" % (len(weekly), max_season_seen))
    if max_season_seen < season:
        print("ERROR: weekly stats do not contain season %d yet - run scripts/pull_postgame_stats.py first (exit 3)" % season)
        return 3

    def recompute(name):
        wk = weekly.get(name) or weekly.get(wk_nrm.get(nrm(name), ""))
        if not wk:
            return None
        cbr = data["combine"].get(name) or data["combine"].get(cb_nrm.get(nrm(name), ""))
        res = gb.generate_entry(name, wk, cbr, all_seasons, ranks)
        return res[0] if res else None

    # ---- calibration on finalized stored verdicts ---------------------------------
    xs, ys, pairs = [], [], []
    for yr, entries in old.items():
        for e in entries:
            if e.get("verdict") in (None, "pending") or e.get("curveScore") is None or e.get("partial"):
                continue
            r = recompute(e["n"])
            if not r or r.get("curveScore") is None or r["verdict"] == "pending":
                continue
            xs.append(r["curveScore"]); ys.append(e["curveScore"]); pairs.append((e, r))
    # per-position monotone maps (the reconstruction's bias differs by position: TE/RB
    # under-credit positional finishes; a global map gets ~74%, per-position ~79%)
    mappers = {}
    for pos in ("QB", "RB", "WR", "TE"):
        pp = [(e, r) for e, r in pairs if e["pos"] == pos]
        if len(pp) >= 15:
            mappers[pos] = make_mapper(pava([r["curveScore"] for _, r in pp], [e["curveScore"] for e, _ in pp]))
    glob = make_mapper(pava(xs, ys)) if pairs else (lambda v: v)

    def mapper(score, pos):
        return mappers.get(pos, glob)(score)

    agree = sum(1 for e, r in pairs if verdict_of(mapper(r["curveScore"], e["pos"])) == e["verdict"])
    raw_agree = sum(1 for e, r in pairs if r["verdict"] == e["verdict"])
    pct = 100.0 * agree / len(pairs) if pairs else 0
    print("calibration: %d finalized players | raw agreement %.1f%% -> calibrated %.1f%%" % (
        len(pairs), 100.0 * raw_agree / len(pairs) if pairs else 0, pct))
    for pos in ("QB", "RB", "WR", "TE"):
        pp = [(e, r) for e, r in pairs if e["pos"] == pos]
        if pp:
            print("  %s: n %3d  %.1f%%" % (pos, len(pp), 100.0 * sum(1 for e, r in pp if verdict_of(mapper(r["curveScore"], pos)) == e["verdict"]) / len(pp)))
    if pct < a.min_agree and not a.force:
        print("GATE FAILED: calibrated agreement %.1f%% < %.1f%% - not writing (exit 2)" % (pct, a.min_agree))
        return 2

    # ---- rebuild cohorts ------------------------------------------------------------
    new = {}
    stats = {}
    for yr in range(FIRST_COHORT, season + 1):
        key = str(yr)
        entries = {e["n"]: dict(e) for e in old.get(key, [])}
        kept = recomputed = added = 0
        for name, e in list(entries.items()):
            if e.get("verdict") != "pending" and not e.get("partial") and window_complete(e, season - 1):
                kept += 1
                continue                       # finalized before this season: never touched
            r = recompute(name)
            if not r:
                kept += 1
                continue
            if r["verdict"] != "pending":
                r["curveScore"] = round(mapper(r["curveScore"], r["pos"]), 1) if r["curveScore"] is not None else None
                r["verdict"] = verdict_of(r["curveScore"])
            r["regen"] = season
            r["pick"] = e.get("pick") or r.get("pick"); r["round"] = e.get("round") or r.get("round"); r["team"] = e.get("team") or r.get("team")
            entries[name] = r
            recomputed += 1
        # new players for this cohort (rookie year == yr, drafted, not already present)
        if yr >= season - 1:
            for name, rec in weekly.items():
                if not isinstance(rec, dict) or rec.get("pos") not in ("QB", "RB", "WR", "TE"):
                    continue
                seasons = all_seasons.get(name) or []
                ry = gb.find_rookie_year(seasons)
                if ry != yr or name in entries or any(nrm(name) == nrm(k) for k in entries):
                    continue
                cbr = data["combine"].get(name) or data["combine"].get(cb_nrm.get(nrm(name), ""))
                res = gb.generate_entry(name, rec, cbr, all_seasons, ranks)
                if not res or res[0]["pick"] is None:
                    continue
                r = res[0]
                if r["verdict"] != "pending":
                    r["curveScore"] = round(mapper(r["curveScore"], r["pos"]), 1) if r["curveScore"] is not None else None
                    r["verdict"] = verdict_of(r["curveScore"])
                r["regen"] = season
                entries[name] = r
                added += 1
        rows = sorted(entries.values(), key=lambda e: (e.get("pick") or 999, e["n"]))
        new[key] = rows
        vc = {}
        for e in rows:
            vc[e["verdict"]] = vc.get(e["verdict"], 0) + 1
        stats[key] = (len(rows), kept, recomputed, added, vc)
        print("  %s: n %3d  kept %3d  recomputed %3d  added %3d  %s" % (key, len(rows), kept, recomputed, added, json.dumps(vc, sort_keys=True)))

    if a.dry_run:
        print("DRY RUN - nothing written")
        return 0

    bak = OUT + ".bak_%s" % today.isoformat()
    shutil.copyfile(OUT, bak)
    header = (
        "// Auto-generated rookie outcomes for JM model backtest\n"
        "// Cohorts: %d-%d. Finalized verdicts are frozen; entries with \"regen\":<season> were (re)computed by\n"
        "// scripts/regen_backtest_outcomes.py with the calibrated reconstruction (isotonic map of\n"
        "// generate_extended_backtest.py curve scores onto the stored scale; %.1f%% verdict agreement on %d finalized players).\n"
        "// Verdicts use v4 continuous curve formula:\n"
        "//   score = peakSig(peakPpg)*0.55 + tanh(sumPpgValue/3)*100*0.35 + rankBonus + breakout + activity + trajectory\n"
        "//   stud >= 70 | hit >= 45 | contributor >= 22 | bust < 22\n"
        "//   pending = window still open with < 2 qualifying seasons\n"
        "// Window: years 1-3 for RB/WR/TE, years 1-4 for QB. Min 6 GP per season to qualify. Current season: %d\n"
    ) % (FIRST_COHORT, season, pct, len(pairs), season)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(header + "const BACKTEST_OUTCOMES = " + json.dumps(new, separators=(",", ":"), ensure_ascii=False) + ";\n")
    print("wrote %s (backup %s)" % (OUT, bak))
    with open(INDEX_HTML, encoding="utf-8", newline="") as f:
        html = f.read()
    m = re.search(r"backtest_outcomes\.js\?v=([\w.-]+)", html)
    if m:
        new_tag = today.isoformat() + "-regen"
        html2 = html.replace("backtest_outcomes.js?v=" + m.group(1), "backtest_outcomes.js?v=" + new_tag)
        if html2 != html:
            with open(INDEX_HTML, "w", encoding="utf-8", newline="") as f:
                f.write(html2)
            print("bumped backtest_outcomes.js ?v= %s -> %s" % (m.group(1), new_tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
