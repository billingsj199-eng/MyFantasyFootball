#!/usr/bin/env python3
"""
refresh_2027.py - one command that rebuilds the early 2027 in-house list (and the 2026 check) from whatever is on disk.
Jack 2026-11-21: "have it update based on new information". It FETCHES NOTHING: it reads what the existing pulls brought in.
It never re-tunes anything: same switches as the working version (v7 + the A15 provisional rookie class), fixed constants.

  python refresh_2027.py                 # normal run (latest completed 2026 week)
  python refresh_2027.py --as-of-week 9  # rebuild as of an earlier completed week (for checks / history)

Each run:
  1. checks every input (exists, parses, date, fingerprint); a malformed input ABORTS the run and keeps the last good list
  2. detects the offseason stage from the data on disk
  3. rebuilds: output_rankings.py -> sf_view_a10.py -> a15_rookies.py insert (outputs restored if any step fails)
  4. sanity checks (row counts, duplicates, players missing since last time, team rooms)
  5. writes a dated snapshot (output/snapshots/<stamp>/, never overwritten) and a change log vs the previous snapshot
     (output/changelog/<stamp>.md): every player whose position rank moved 3+ or total moved 10+ pts / 5%, with the driver
  6. writes output/2027_refresh_status.md (stage, input dates, what is still missing, stale inputs) and puts it at the
     top of output/2027_inhouse_early.md
Cadence: scheduled weekly, Tuesday 10:00 (Task 'MFF 2027 List Refresh', sim_lab/list_2027_refresh.ps1, Jack 2026-11-24) through week 18 (after the Monday game and the
Tuesday stats pulls), then once after each milestone: playoffs end, bowls + Jan 15 declaration deadline, combine, start of
free agency, the draft, early-June depth charts, August depth charts + 2027 win totals.
"""
import os, sys, json, hashlib, shutil, subprocess, datetime as dt
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "output")
SITE = r"E:\MyFantasyFootball\MyFantasyFootball Files"; CACHE = r"E:\MyFantasyFootball\pbp_cache"; SIMD = r"E:\MyFantasyFootball\sim_lab\data"
PY = sys.executable
LIST27 = os.path.join(OUT, "2027_inhouse_early.csv"); MD27 = os.path.join(OUT, "2027_inhouse_early.md")
OUTFILES = ["2026_inhouse_check.csv", "2026_inhouse_check.md", "2027_inhouse_early.csv", "2027_inhouse_early.md", "2027_inhouse_early_norookies.csv"]

# (label, path, what refreshes it, how often)
INPUTS = [
    ("2026 play-by-play", os.path.join(CACHE, "play_by_play_2026.csv.gz"), "Task 'MFF Sim Proj Export' (sim_proj_task.ps1 -> sim_lab/refresh_data.py)", "daily / several times on game days"),
    ("current ESPN depth chart", os.path.join(SIMD, "sim_depth.js"), "Task 'MFF Sim Proj Export' (refresh_data.py <- data/depth_charts_2026.json)", "daily"),
    ("2026 schedule + final scores", os.path.join(CACHE, "schedules_games.csv"), "NOTHING scheduled (nflverse cache pulled by hand)", "manual"),
    ("historical contracts (OTC)", os.path.join(CACHE, "historical_contracts.parquet"), "NOTHING found for this file (the daily 'MFF Player Contracts' task writes the site's contracts data, not this cache)", "manual"),
    ("NFL draft picks", os.path.join(CACHE, "draft_picks.parquet"), "NOTHING scheduled (nflverse cache pulled by hand)", "manual; must be re-pulled after the April draft"),
    ("coaches", os.path.join(CACHE, "coaches.json"), "NOTHING scheduled", "manual"),
    ("2025 weekly depth charts (week-1 roles history)", os.path.join(CACHE, "depth_charts_2025.parquet"), "NOTHING scheduled (nflverse cache)", "manual"),
    ("win totals 2012-2025 (+2026 from frozen lines)", os.path.join(HERE, "data", "win_totals_2012_2025.csv"), "NOTHING (built once in preseason2027); 2027 totals not on disk", "manual"),
    ("2026 frozen preseason lines", os.path.join(SIMD, "preseason_lines_2026_frozen.js"), "frozen 2026-08-26 (by design)", "never"),
    ("JM scores (2027 class)", os.path.join(SITE, "data", "jm_scores.json"),
     "Task 'MFF 2027 List Refresh' (sim_lab/list_2027_refresh.ps1 -> scripts/pull_jm_scores.py, then this script); the Tuesday Dynasty SIM refresh runs the same export", "weekly (Tue)"),
    ("college stats (devy)", os.path.join(SITE, "data", "college_stats_devy.js"), "Task 'MFF Devy Weekly Refresh' (weekly_devy_refresh.ps1 -> refresh_devy_stats.py)", "weekly (Mon)"),
    ("combine / prospect data", os.path.join(SITE, "data", "combine_data.js"), "Task 'MFF Devy Weekly Refresh'", "weekly (Mon)"),
    ("consensus mock (inside JM)", os.path.join(SITE, "data", "draft_proj.js"), "Task 'MFF Devy Weekly Refresh' (pull_draft_boards.py; its mock CSVs are saved by hand in Chrome and dropped after 10 days)", "weekly, needs hand-saved CSVs"),
    ("UD ADP history (2026 check comparison column only)", os.path.join(SITE, "data", "ud_adp_history.json"), "9am consensus-ADP task", "daily"),
]


def sha(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()[:12]


def check_inputs():
    rows, bad = [], []
    for lab, p, who, how in INPUTS:
        if not os.path.exists(p):
            rows.append((lab, p, None, None, who, how, "MISSING")); bad.append(f"{lab}: missing ({p})"); continue
        st = "ok"
        try:
            if p.endswith(".json"):
                d = json.load(open(p, encoding="utf-8"))
                if p.endswith("jm_scores.json"):
                    n27 = sum(1 for v in d["scores"].values() if v.get("yr") == 2027)
                    if n27 < 50: st = f"MALFORMED (only {n27} 2027 prospects)"
            elif p.endswith(".js"):
                s = open(p, encoding="utf-8").read(200000)
                if "window." not in s and "const " not in s and "var " not in s: st = "MALFORMED (no data object)"
            elif p.endswith(".parquet"):
                pd.read_parquet(p).head(1)
            elif p.endswith(".csv") or p.endswith(".csv.gz"):
                pd.read_csv(p, nrows=5)
        except Exception as e:
            st = f"MALFORMED ({type(e).__name__}: {str(e)[:80]})"
        if st != "ok": bad.append(f"{lab}: {st}")
        m = dt.datetime.fromtimestamp(os.path.getmtime(p))
        rows.append((lab, p, m, sha(p), who, how, st))
    return rows, bad


def completed_week(as_of=None):
    d = pd.read_csv(os.path.join(CACHE, "play_by_play_2026.csv.gz"), usecols=["week", "game_id", "season_type"], low_memory=False)
    got = d[d.season_type == "REG"].groupby("week").game_id.nunique()
    s = pd.read_csv(os.path.join(CACHE, "schedules_games.csv"), usecols=["season", "week", "game_type"])
    sched = s[(s.season == 2026) & (s.game_type == "REG")].groupby("week").size()
    done = [w for w in sorted(got.index) if got[w] >= sched.get(w, 99)]
    w = max([x for i, x in enumerate(done) if done[: i + 1] == list(range(1, x + 1))] or [0])
    return (min(w, as_of) if as_of else w), {int(k): int(v) for k, v in got.items()}, {int(k): int(v) for k, v in sched.items()}


def stage(week, today):
    dp = pd.read_parquet(os.path.join(CACHE, "draft_picks.parquet"), columns=["season"])
    drafted27 = bool((dp.season == 2027).any())
    wt = pd.read_csv(os.path.join(HERE, "data", "win_totals_2012_2025.csv"))
    have_wt27 = bool((wt.season == 2027).any())
    aug_chart = os.path.exists(os.path.join(CACHE, "depth_charts_2027.parquet"))
    lines, missing = [], []
    if drafted27:
        lines.append("POST-DRAFT: 2027 draft results are on disk. The real rookie prior (pick + landing spot) is NOT wired into this refresh yet - the JM placeholders are still shown and must be replaced (see A15).")
    elif week >= 18:
        lines.append("2026 regular season complete; 2027 rookies are PROVISIONAL JM placeholders.")
    else:
        lines.append(f"2026 in progress (through week {week}); 2027 rookies are PROVISIONAL JM placeholders.")
    if week < 18: missing.append(f"2026 weeks {week + 1}-18 and the playoffs")
    if today < dt.date(2027, 1, 16): missing.append("final college stats, bowls, and the Jan 15 2027 declaration deadline (class status stays 'uncertain' for underclassmen)")
    if today < dt.date(2027, 3, 3): missing.append("NFL combine testing")
    if today < dt.date(2027, 3, 11): missing.append("free agency and trades (veterans' teams are their 2026 teams)")
    if not drafted27: missing.append("the 2027 draft (late April): real draft capital + landing spots; veterans not adjusted for incoming rookies")
    if not have_wt27: missing.append("2027 win totals (team strength = league median)")
    if not aug_chart: missing.append("2027 August depth charts (2027 look uses today's ESPN chart)")
    missing.append("coaching / play-caller changes for 2027 (coaches.json has no 2027)")
    return lines, missing


def sanity(prev, cur):
    out = []
    out.append(f"rows {len(cur)} (veterans {int((cur.get('provisional', 0) == 0).sum())}, provisional rookies {int((cur.get('provisional', 0) == 1).sum())})")
    dup = cur.duplicated(["name", "pos", "team"]).sum(); out.append(f"duplicate players: {int(dup)}")
    v = cur[cur.get("provisional", 0) == 0]
    rooms = v.groupby("team").pos.apply(lambda s: {p: int((s == p).sum()) for p in ("QB", "RB", "WR", "TE")})
    thin = [f"{t} {p}={n}" for (t, p), n in rooms.items() if (p == "QB" and n < 1) or (p in ("RB", "TE") and n < 1) or (p == "WR" and n < 2)]
    out.append(f"teams {v.team.nunique()}; thin rooms: {', '.join(thin) if thin else 'none'}")
    qbg = v[v.pos == "QB"].groupby("team").games.sum()
    out.append(f"team QB games (sum of listed QBs): min {qbg.min():.1f}, max {qbg.max():.1f}")
    if prev is not None:
        gone = set(map(tuple, prev[["name", "pos"]].values)) - set(map(tuple, cur[["name", "pos"]].values))
        out.append(f"players in the last snapshot but not now: {len(gone)}" + (" - " + "; ".join(f"{n} ({p})" for n, p in sorted(gone)[:15]) if gone else ""))
    return out, int(dup)


def changelog(prev, cur):
    if prev is None: return ["first snapshot: nothing to compare"], 0
    a = prev.copy(); b = cur.copy()
    for X in (a, b):
        if "provisional" not in X: X["provisional"] = 0
    if a.shape == b.shape and a.reset_index(drop=True).equals(b.reset_index(drop=True)):
        return ["no changes: the list matches the previous snapshot exactly"], 0
    m = a.merge(b, on=["name", "pos"], how="outer", suffixes=("_o", "_n"), indicator=True)
    lines, n = [], 0
    for r in m[m._merge == "left_only"].itertuples(index=False):
        why = "no longer in the JM 2027 class (returned to school / reclassified / renamed)" if getattr(r, "provisional_o", 0) == 1 else "dropped from the depth chart or the 2026 pool"
        lines.append(f"- REMOVED {r.name} ({r.pos}): {why}"); n += 1
    for r in m[m._merge == "right_only"].itertuples(index=False):
        lines.append(f"- ADDED {r.name} ({r.pos}, {r.team_n if isinstance(r.team_n, str) else 'no team'}): " + ("new in the JM 2027 class" if getattr(r, "provisional_n", 0) == 1 else "new on the depth chart / 2026 pool")); n += 1
    both = m[m._merge == "both"]
    for _, r in both.iterrows():
        dr = r.pos_rank_n - r.pos_rank_o; dtot = r.total_n - r.total_o
        if abs(dr) < 3 and not (abs(dtot) >= 10 or (r.total_o > 0 and abs(dtot) / r.total_o >= .05)): continue
        why = []
        if str(r.get("team_o")) != str(r.get("team_n")): why.append(f"team {r.get('team_o')} -> {r.get('team_n')}")
        if r.get("provisional_n", 0) == 1:
            if r.get("jm_o") != r.get("jm_n"): why.append(f"JM {r.get('jm_o')} -> {r.get('jm_n')}")
            if r.get("class_status_o") != r.get("class_status_n"): why.append(f"class status {r.get('class_status_o')} -> {r.get('class_status_n')}")
        else:
            if "dc_o" in r and str(r.get("dc_o")) != str(r.get("dc_n")): why.append(f"depth chart {r.get('dc_o')} -> {r.get('dc_n')}")
            if abs((r.get("ppg26_n") or 0) - (r.get("ppg26_o") or 0)) > 1e-9: why.append(f"new 2026 game data (2026 ppg {r.get('ppg26_o'):.1f} -> {r.get('ppg26_n'):.1f})")
        if not why: why.append("own projection unchanged: others moved around him" if abs(dtot) < 1e-6 else "shared model inputs (team games, contracts, history) moved")
        lines.append(f"- {r['name']} ({r.pos}): {r.pos}{int(r.pos_rank_o)} -> {r.pos}{int(r.pos_rank_n)}, overall {int(r.rank_o)} -> {int(r.rank_n)}, total {r.total_o:.0f} -> {r.total_n:.0f} | {'; '.join(why)}"); n += 1
    return (lines if lines else ["values changed below the reporting thresholds only"]), n


def main():
    args = sys.argv[1:]; as_of = int(args[args.index("--as-of-week") + 1]) if "--as-of-week" in args else None
    now = dt.datetime.now(); stamp = now.strftime("%Y-%m-%d_%H%M%S"); today = now.date()
    os.makedirs(os.path.join(OUT, "snapshots"), exist_ok=True); os.makedirs(os.path.join(OUT, "changelog"), exist_ok=True)
    inv, bad = check_inputs()
    status = [f"# 2027 refresh status - {now:%Y-%m-%d %H:%M}", ""]
    if bad:
        status += ["**ABORTED: an input is missing or malformed. The previous list was kept unchanged.**", ""] + [f"- {b}" for b in bad]
        open(os.path.join(OUT, "2027_refresh_status.md"), "w", encoding="utf-8").write("\n".join(status) + "\n")
        print("\n".join(status)); sys.exit(2)
    week, got, sched = completed_week(as_of)
    st_lines, missing = stage(week, today)
    # 3. rebuild, restoring the previous outputs if any step fails
    keep = os.path.join(OUT, "_prev_run"); os.makedirs(keep, exist_ok=True)
    for f in OUTFILES:
        if os.path.exists(os.path.join(OUT, f)): shutil.copy2(os.path.join(OUT, f), os.path.join(keep, f))
    env = dict(os.environ, PRE27_LAST_WK=str(week))
    for step in (["output_rankings.py"], ["sf_view_a10.py"], ["a15_rookies.py", "insert"]):
        r = subprocess.run([PY, os.path.join(HERE, step[0])] + step[1:], cwd=HERE, env=env, capture_output=True, text=True)
        if r.returncode != 0:
            for f in OUTFILES:
                if os.path.exists(os.path.join(keep, f)): shutil.copy2(os.path.join(keep, f), os.path.join(OUT, f))
            status += [f"**ABORTED: step {' '.join(step)} failed; previous list restored.**", "", "```", r.stderr[-2000:], "```"]
            open(os.path.join(OUT, "2027_refresh_status.md"), "w", encoding="utf-8").write("\n".join(status) + "\n")
            print("\n".join(status)); sys.exit(3)
    cur = pd.read_csv(LIST27)
    snaps = sorted(d for d in os.listdir(os.path.join(OUT, "snapshots")) if os.path.isdir(os.path.join(OUT, "snapshots", d)))
    prev = pd.read_csv(os.path.join(OUT, "snapshots", snaps[-1], "2027_inhouse_early.csv")) if snaps else None
    san, ndup = sanity(prev, cur)
    cl, nchg = changelog(prev, cur)
    sd = os.path.join(OUT, "snapshots", stamp); i = 1
    while os.path.exists(sd): sd = os.path.join(OUT, "snapshots", f"{stamp}_{i}"); i += 1
    os.makedirs(sd)
    for f in OUTFILES:
        if os.path.exists(os.path.join(OUT, f)): shutil.copy2(os.path.join(OUT, f), os.path.join(sd, f))
    manifest = {"stamp": os.path.basename(sd), "as_of_week": week, "stage": st_lines, "missing": missing,
                "inputs": [{"label": l, "path": p, "modified": m.isoformat(timespec="minutes") if m else None, "sha1": h, "status": s} for l, p, m, h, w_, hw, s in inv]}
    json.dump(manifest, open(os.path.join(sd, "manifest.json"), "w", encoding="utf-8"), indent=1)
    clp = os.path.join(OUT, "changelog", os.path.basename(sd) + ".md")
    open(clp, "w", encoding="utf-8").write(f"# Change log {os.path.basename(sd)} vs {snaps[-1] if snaps else '(none)'}\n\n" + "\n".join(cl) + "\n")
    # status / header
    status += ["## Stage", ""] + [f"- {x}" for x in st_lines] + [f"- 2026 data through week {week} (pbp games per week {got}; scheduled {sched})", "",
               "## Still missing", ""] + [f"- {x}" for x in missing] + ["", "## Inputs used (date on disk, fingerprint)", "",
               "| input | modified | age (days) | sha1 | refreshed by | cadence |", "|---|---|---|---|---|---|"]
    for l, p, m, h, w_, hw, s in inv:
        status.append(f"| {l} | {m:%Y-%m-%d %H:%M} | {(now - m).days} | {h} | {w_} | {hw} |")
    stale = [l for l, p, m, h, w_, hw, s in inv if "NOTHING" in w_]
    status += ["", f"**Not refreshed by any scheduled job: {', '.join(stale)}.** These stop the list from really updating until someone re-pulls them.",
               "- schedules_games.csv has 2026 final scores only through week 6, so the 2026 work data has no team-game rows for weeks 7+ (see A15).",
               "", "## Sanity", ""] + [f"- {x}" for x in san] + ["", f"## Change log ({nchg} entries) - full list: output/changelog/{os.path.basename(sd)}.md", ""] + cl[:40]
    open(os.path.join(OUT, "2027_refresh_status.md"), "w", encoding="utf-8").write("\n".join(status) + "\n")
    md = open(MD27, encoding="utf-8").read()
    hdr = (f"> **Refresh {os.path.basename(sd)}** - stage: {st_lines[0]} 2026 data through week {week}. Still missing: {'; '.join(missing)}. "
           f"Inputs and stale sources: output/2027_refresh_status.md.\n\n")
    open(MD27, "w", encoding="utf-8").write(hdr + md)
    shutil.copy2(MD27, os.path.join(sd, "2027_inhouse_early.md"))
    print("\n".join(status[:12])); print(f"snapshot {sd}\nchange log {clp} ({nchg} entries): " + cl[0])
    if ndup: sys.exit(4)


if __name__ == "__main__":
    main()
