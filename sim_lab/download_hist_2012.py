#!/usr/bin/env python3
"""
2026-10-20 (Jack: "yes download back to 2012 and rebuild") - pull the nflverse files + FFC ADP needed to extend the
Sim Lab backtest history from 2019-25 back to 2012-25. ADD-ONLY: an existing cached file is never touched; each file
goes to <target>.part, is validated (parquet/csv readable), then renamed. ffc_adp_hist.json gets new year keys only -
the existing year blocks are copied through byte-identical (verified after the write).

  python download_hist_2012.py           # everything below
  python download_hist_2012.py --adp     # FFC ADP only
Writes a summary to E:/MyFantasyFootball/sim_lab/download_hist_2012.log
"""
import json, os, sys, time, urllib.request, io, gzip

CACHE = r"E:\MyFantasyFootball\pbp_cache"
HERE = os.path.dirname(os.path.abspath(__file__))
REL = "https://github.com/nflverse/nflverse-data/releases/download"
LOG = open(os.path.join(HERE, "download_hist_2012.log"), "a", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + "\n"); LOG.flush()

JOBS = []
for y in range(2012, 2016): JOBS.append((f"{REL}/pbp/play_by_play_{y}.csv.gz", f"play_by_play_{y}.csv.gz"))
for y in range(2012, 2018): JOBS.append((f"{REL}/snap_counts/snap_counts_{y}.parquet", f"snap_counts_{y}.parquet"))
for y in range(2012, 2018): JOBS.append((f"{REL}/depth_charts/depth_charts_{y}.parquet", f"depth_charts_{y}.parquet"))
for y in range(2012, 2019): JOBS.append((f"{REL}/injuries/injuries_{y}.parquet", f"injuries_{y}.parquet"))
for y in range(2012, 2019): JOBS.append((f"{REL}/weekly_rosters/roster_weekly_{y}.parquet", f"roster_weekly_{y}.parquet"))
JOBS.append((f"{REL}/schedules/games.csv", "schedules_games.csv"))
TRADES = [(f"{REL}/trades/trades.csv", "trades.csv"), ("https://github.com/nflverse/nfldata/raw/master/data/trades.csv", "trades.csv")]


def fetch(url, timeout=180):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (sim_lab backtest download)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def validate(path, raw):
    import pandas as pd
    if path.endswith(".parquet"):
        d = pd.read_parquet(io.BytesIO(raw)); return len(d)
    if path.endswith(".csv.gz"):
        d = pd.read_csv(io.BytesIO(gzip.decompress(raw)), nrows=5000, low_memory=False); return len(d)
    d = pd.read_csv(io.BytesIO(raw), low_memory=False); return len(d)


def get(url, name):
    tgt = os.path.join(CACHE, name)
    if os.path.exists(tgt):
        P(f"  SKIP (exists) {name}"); return 0
    try:
        raw = fetch(url)
    except Exception as e:
        P(f"  FAIL {name}: {e}"); return None
    try:
        nrow = validate(name, raw)
    except Exception as e:
        P(f"  FAIL {name}: not readable ({e})"); return None
    part = tgt + ".part"
    with open(part, "wb") as f: f.write(raw)
    if os.path.exists(tgt):
        os.remove(part); P(f"  SKIP (appeared meanwhile) {name}"); return 0
    os.replace(part, tgt)
    P(f"  OK   {name}  {len(raw)/1e6:6.2f} MB  rows {nrow}")
    return len(raw)


def ffc_adp():
    """FFC 12-team preseason ADP 2012-2018 merged into data/ffc_adp_hist.json. Rule copied from the 2019-25 blocks:
    half-ppr first, then ppr for players not in half-ppr, then standard (half-ppr only exists 2018+)."""
    path = os.path.join(HERE, "data", "ffc_adp_hist.json")
    old_raw = open(path, "rb").read()
    old = json.loads(old_raw.decode("utf-8"))
    new_years = {}
    for y in range(2012, 2019):
        if str(y) in old:
            P(f"  ADP {y}: already in file, skipped"); continue
        blocks = {}
        for fmt in ("half-ppr", "ppr", "standard"):
            try:
                d = json.loads(fetch(f"https://fantasyfootballcalculator.com/api/v1/adp/{fmt}?teams=12&year={y}", 60).decode("utf-8"))
                pl = d.get("players") or []
            except Exception as e:
                pl = []; P(f"  ADP {y} {fmt}: {e}")
            if pl: blocks[fmt] = pl
            time.sleep(1.0)
        seen = set(); players = []; meta = {}
        for fmt in ("half-ppr", "ppr", "standard"):
            pl = blocks.get(fmt) or []
            meta[fmt] = len(pl)
            for p in pl:
                key = (p.get("name"), p.get("position"))
                if key in seen: continue
                seen.add(key)
                players.append({"name": p.get("name"), "pos": p.get("position"), "team": p.get("team"), "adp": p.get("adp"), "n": p.get("times_drafted"), "fmt": fmt})
        meta = {k: v for k, v in meta.items() if v}
        if not players:
            P(f"  ADP {y}: nothing returned"); continue
        players.sort(key=lambda p: (p["adp"] if isinstance(p["adp"], (int, float)) else 999))
        new_years[str(y)] = {"meta": meta, "players": players}
        P(f"  ADP {y}: {len(players)} players, meta {meta}")
    if not new_years:
        return
    # write: existing year blocks copied through as their exact original JSON text, new years appended after them
    txt = old_raw.decode("utf-8").rstrip()
    assert txt.endswith("}")
    add = "".join("," + json.dumps(k) + ":" + json.dumps(v, ensure_ascii=False, separators=(",", ":")) for k, v in sorted(new_years.items()))
    out = txt[:-1] + add + "}"
    chk = json.loads(out)
    for k in old: assert json.dumps(chk[k], sort_keys=True) == json.dumps(old[k], sort_keys=True), k
    assert out.startswith(txt[:-1])   # byte-identical prefix: every old block untouched
    tmp = path + ".tmp_20261020"
    with open(tmp, "wb") as f: f.write(out.encode("utf-8"))
    bak = path + ".bak_pre_2012ext_20261020"
    if not os.path.exists(bak):
        with open(bak, "wb") as f: f.write(old_raw)
    os.replace(tmp, path)
    P(f"  ffc_adp_hist.json: +{len(new_years)} years ({sorted(new_years)}); old blocks byte-identical (prefix check passed); backup {os.path.basename(bak)}")


def main():
    P(f"=== download_hist_2012 {time.strftime('%Y-%m-%d %H:%M')} ===")
    if "--adp" not in sys.argv:
        tot = 0; fails = []
        for url, name in JOBS:
            r = get(url, name)
            if r is None: fails.append(name)
            else: tot += r
        got = False
        for url, name in TRADES:
            if os.path.exists(os.path.join(CACHE, name)): P(f"  SKIP (exists) {name}"); got = True; break
            r = get(url, name)
            if r is not None: tot += r; got = True; break
        if not got: fails.append("trades.csv")
        P(f"  nflverse total downloaded {tot/1e6:.1f} MB; failures {fails}")
    ffc_adp()


if __name__ == "__main__":
    main()
