#!/usr/bin/env python3
"""
run_all.py - rerun the whole scratch-model experiment end to end.

  python run_all.py            # rebuild everything from the pbp cache (~5 min features, ~15 min fit, ~1 min backtest)
  python run_all.py --quick    # reuse cached feature tables + fitted params, just regrade 2026

Steps: features.py (pbp -> player/team-game tables) -> asof.py (leak-free weekly feature rows) ->
       fit_history.py (fit 2017-24, forward-check 2025, refit through 2025) -> backtest.py (2026 W1-7 vs live / books).
Nothing here touches the live engine, the sim export or the repo; outputs land in scratch_model/out/.
"""
import os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
quick = "--quick" in sys.argv


def run(args):
    t = time.time()
    print(f"\n>>> {' '.join(args)}")
    r = subprocess.run([sys.executable] + args, cwd=HERE)
    if r.returncode != 0:
        sys.exit(f"step failed: {args}")
    print(f"    ({time.time() - t:.0f}s)")


if not quick:
    run(["features.py"] + [str(y) for y in range(2016, 2027)])
    run(["asof.py", "2017", "2026"])
    run(["fit_history.py"])
else:
    run(["features.py", "2026"])
    run(["asof.py", "2026", "2026"])
run(["backtest.py"])
print("\ndone - see out/bt_tables.md")
