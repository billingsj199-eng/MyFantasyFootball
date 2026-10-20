#!/usr/bin/env python3
"""
BACKTEST SEASON RANGE (2026-10-20, Jack: "yes download back to 2012 and rebuild").

The ROS / next-game harness chain (backtest_noclay_weekly -> research_clay_vs_shadow -> backtest_season_long ->
backtest_shadow_next -> backtest_shadow_ros / ablate_shadow_next) reads its seasons from here.

  SIM_BT_YEARS   unset (DEFAULT) = 2019-2025, Clay pool, every file and number exactly as before.
                 "2013-2025" (or "2012-2025", "2019-2025", ...) = EXTENDED mode.
  SIM_BT_POOL    "ext" forces the Clay-free pool even for 2019-2025 (to measure the pool effect alone).
  SIM_BT_EVAL    optional "2013-2018": grade only these seasons inside a run (fits / LOYO still use every season).

EXTENDED mode (EXT True):
  - player pool = data/bt_pool_ext.json (build_bt_pool_ext.py: ADP <= 200 U week-1 chart U history U rookies rd 1-3),
    not Clay's sheet; every Clay number (shipped blend, Clay rate) is NaN -> "Clay baselines n/a" in the reports
  - derived inputs go to ext-tagged files (ext_path): ctx_features_ext<TAG>.parquet, ctx_live_layers_ext<TAG>.parquet,
    opp_prior_preds_ext<TAG>.json, logs <name>_ext<TAG>.log - the default files are never written in EXT mode
  - data that does not exist early stays MISSING (NaN), never zero: participation (2016+), FTN (2022+), PFF (2018+),
    snap counts (2013+; the 2012 file is empty), JM (draft classes 2017+), 2011 play-by-play (not downloaded)
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_YEARS = list(range(2019, 2026))


def _span(s, dflt):
    if not s:
        return dflt
    a, _, b = s.strip().partition("-")
    a = int(a); b = int(b) if b else a
    return list(range(a, b + 1))


YEARS = _span(os.environ.get("SIM_BT_YEARS", ""), DEFAULT_YEARS)
POOL = "ext" if (YEARS != DEFAULT_YEARS or os.environ.get("SIM_BT_POOL", "").lower() == "ext") else "clay"
# TEAM FIX (2026-10-20, from the mid-season trade study): team PER GAME (pbp touches > snap counts > weekly roster), the
# opponent / Vegas / FPA from that game's schedule, never the weekly record's opp field (retired records have none; 2025
# records carry the current team's schedule). On by default in extended mode; SIM_BT_TEAMFIX=1/0 forces it.
_tf = os.environ.get("SIM_BT_TEAMFIX", "")
TEAMFIX = (_tf == "1") if _tf in ("0", "1") else (POOL == "ext" or YEARS != DEFAULT_YEARS)
EXT = POOL == "ext" or YEARS != DEFAULT_YEARS or TEAMFIX
EVAL = _span(os.environ.get("SIM_BT_EVAL", ""), None)
FIRST = YEARS[0]
TAG = "" if not EXT else (f"_ext{YEARS[0]}_{YEARS[-1]}" + ("" if POOL == "ext" else "_clay") + ("_tf" if TEAMFIX else ""))
# forward-test folds (earlier seasons only): default keeps 2022-25; extended adds every season with 3+ earlier ones
FWD = (2022, 2023, 2024, 2025) if not EXT else tuple(y for y in YEARS if y >= YEARS[0] + 3)
EXT_DIR = os.path.join(HERE, "_bt_ext")


def ext_path(name):
    """default mode: HERE/name (unchanged). EXT: HERE/_bt_ext/<stem><TAG><ext> (directory created on demand)."""
    if not EXT:
        return os.path.join(HERE, name)
    os.makedirs(EXT_DIR, exist_ok=True)
    stem, dot, ext = name.rpartition(".")
    return os.path.join(EXT_DIR, (stem + TAG + dot + ext) if dot else (name + TAG))


def data_path(name):
    """for files under data/: default HERE/data/name, EXT HERE/_bt_ext/<stem><TAG><ext>"""
    return os.path.join(HERE, "data", name) if not EXT else ext_path(name)


def atomic_parquet(df, path):
    tmp = path + ".tmp"
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def atomic_text(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def describe():
    return f"years {YEARS[0]}-{YEARS[-1]} | pool {POOL} | team fix {'on' if TEAMFIX else 'off'} | {'EXTENDED' if EXT else 'default'}" + (f" | eval {EVAL[0]}-{EVAL[-1]}" if EVAL else "")
