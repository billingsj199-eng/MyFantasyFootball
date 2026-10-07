#!/usr/bin/env python3
"""
Tuesday wrapper: archive last week's consensus projections, then run
score_week.py + diagnose_week.py for that week into scorecards/wN.log.

Runs from tuesday_stats.ps1 at 7:00 (was 8:30 until 2026-09-15; moved so the
chain finishes before Jack's morning; nflverse pbp with MNF lands ~06:20 ET,
Sleeper actuals at 01:45) — BEFORE the 9am consensus job flips
data/weekly_projections.json to the new week, so the file on disk is still
the week just played (its own `week` field says which). Idempotent: the
consensus archive is only written once per week; the logs are rewritten
(stat corrections through Tuesday can change actuals slightly).

Usage: python weekly_scorecard.py            # week from weekly_projections.json
       python weekly_scorecard.py --week 3   # explicit
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"

def consensus_from_git(wk, dst, max_commits=40):
    """FALLBACK (2026-09-30): the chain ran late on Tue 09-29 (PC asleep at 07:00, caught up 10:10 - after the 9am
    consensus job had already flipped data/weekly_projections.json to week 4), so W3 was graded with no site columns.
    The repo commits that file every morning, so take the LAST committed version that is still week `wk` - the same
    file the on-time run would have copied."""
    try:
        r = subprocess.run(["git", "-C", REPO, "log", f"-{max_commits}", "--format=%h", "--", "data/weekly_projections.json"],
                           capture_output=True, text=True, encoding="utf-8")
        for c in r.stdout.split():
            s = subprocess.run(["git", "-C", REPO, "show", f"{c}:data/weekly_projections.json"], capture_output=True, text=True, encoding="utf-8")
            if s.returncode != 0 or not s.stdout:
                continue
            d = json.loads(s.stdout)
            w = int(d.get("week") or 0)
            if w == wk:
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(s.stdout)
                print(f"archived consensus from git {c} (updated {d.get('updated')}) -> {dst}")
                return True
            if w < wk:
                break   # walked past the week: it was never committed
    except Exception as e:  # noqa: BLE001
        print(f"consensus git fallback failed: {e}")
    return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None)
    a = ap.parse_args()
    src = os.path.join(REPO, "data", "weekly_projections.json")
    wk = a.week
    if wk is None:
        # Score the LATEST week that has both a lock snapshot and actual game
        # rows - never the projections file's week (Sleeper may flip that to
        # next week before the 8:30 chain runs, which would skip the scoring).
        import glob, re
        from score_week import load_actuals
        cands = sorted(int(re.search(r"_w(\d+)\.json$", f).group(1))
                       for f in glob.glob(os.path.join(HERE, "data", "snapshots", "simlab_snapshot_w*.json")))
        wk = next((w for w in reversed(cands) if load_actuals(w)), 0)
        if not wk:
            print("no lock snapshot with actuals yet - nothing to score")
            return 0
        print(f"scoring W{wk} (latest lock with actuals)")
    if wk < 1:
        print("no week to score")
        return 0
    snap = os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{wk}.json")
    if not os.path.exists(snap):
        print(f"no lock snapshot for W{wk} ({snap}) - nothing to score")
        return 0
    dst = os.path.join(HERE, "data", f"weekly_consensus_w{wk}.json")
    if not os.path.exists(dst):
        try:
            if int(json.load(open(src, encoding="utf-8")).get("week") or 0) == wk:
                shutil.copyfile(src, dst)
                print(f"archived consensus -> {dst}")
            elif consensus_from_git(wk, dst):
                pass
            else:
                print(f"weekly_projections.json is not W{wk} and no committed W{wk} version was found; consensus columns will be blank")
        except Exception as e:  # noqa: BLE001
            print(f"consensus archive skipped: {e}")
    outdir = os.path.join(HERE, "scorecards")
    os.makedirs(outdir, exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    with open(os.path.join(outdir, f"w{wk}.log"), "w", encoding="utf-8") as f:
        for script in ("score_week.py", "diagnose_week.py", "vs_books_week.py", "luck_scorecard.py", "peck_scorecard.py", "layers_scorecard.py", "usage_scorecard.py", "return_scorecard.py", "lines_signal_scorecard.py", "backtest_news_status.py"):
            r = subprocess.run([sys.executable, os.path.join(HERE, script), "--week", str(wk)],
                               capture_output=True, text=True, encoding="utf-8", env=env, cwd=HERE)
            f.write(f"##### {script} --week {wk}\n{r.stdout}\n{r.stderr}\n")
            if r.returncode != 0:
                print(f"{script} exit {r.returncode}: {(r.stderr or '')[-300:]}")
    print(f"scorecard W{wk} -> {outdir}\\w{wk}.log")
    # slow weekly knob update (per-position market weight + sigma), shrunk to priors
    r = subprocess.run([sys.executable, os.path.join(HERE, "tune_weekly.py")], capture_output=True, text=True, encoding="utf-8", env=env, cwd=HERE)
    print(r.stdout.strip())
    if r.returncode != 0:
        print(f"tune_weekly exit {r.returncode}: {(r.stderr or '')[-300:]}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
