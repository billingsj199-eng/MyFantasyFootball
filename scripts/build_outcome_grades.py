"""build_outcome_grades.py - graded NFL outcomes for the JM backtest (no black-and-white hit / bust).

Jack (2026-10-01): a "hit" should not be binary. Some players luck into volume for one
year; what matters is elite seasons and career consistency.

Every completed NFL season gets a SEASON VALUE 0-100 from the player's positional finish in
points per game (ranked among players with 8+ games), scaled by availability:

    value = curve(position, ppg rank) * min(1, games / 10)

    curve anchors (rank -> value, linear in between)
      QB  1:100  5:85   12:55  18:30  24:10  32:0
      RB  1:100  6:85   12:70  24:45  36:20  48:5   60:0
      WR  1:100  6:88   12:75  24:52  36:30  48:12  60:0
      TE  1:100  3:88   6:70   12:45  18:22  24:8   30:0

The CAREER GRADE is a weighted sum of the player's four best seasons inside his first six
NFL seasons, best first:  0.40 / 0.30 / 0.20 / 0.10. One big year followed by nothing tops
out at 40; two elite years reach 70; four strong years are needed for 90+. Six seasons (not
four) so a year-5 breakout still counts (Njoku, Sutton); a year-7 one does not (Mayfield),
because that is not what a dynasty drafter was paying for. Classes with fewer than four
completed seasons use the weights of the seasons they have had (renormalised) and are
flagged provisional.

Also reported per player: elite seasons (value 85+), starter seasons (value 50+), counted
over the whole career to date.

Source: data/weekly_stats_active.js + weekly_stats_retired_*.js (PPR points).

    python scripts/build_outcome_grades.py [--table scripts/jm_table.json] [--out scripts/jm_outcome_grades.json]
                                           [--js data/jm_career_grades.js [--bump]] [--last-season 2026]

The --js file feeds the tier chips on the Prospect page (average career grade per tier). The January
outcomes refresh regenerates it once the season is complete.
"""
import argparse
import datetime
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
import generate_extended_backtest as gb  # noqa: E402

CURVES = {
    "QB": [(1, 100), (5, 85), (12, 55), (18, 30), (24, 10), (32, 0)],
    "RB": [(1, 100), (6, 85), (12, 70), (24, 45), (36, 20), (48, 5), (60, 0)],
    "WR": [(1, 100), (6, 88), (12, 75), (24, 52), (36, 30), (48, 12), (60, 0)],
    "TE": [(1, 100), (3, 88), (6, 70), (12, 45), (18, 22), (24, 8), (30, 0)],
}
WEIGHTS = [0.40, 0.30, 0.20, 0.10]
WINDOW = 6          # seasons from the draft year that can supply the best four
RANK_MIN_GP = 8      # ranked among players with this many games
FULL_GP = 10         # availability factor reaches 1 here
ELITE, STARTER = 85, 50


def curve(pos, rank):
    pts = CURVES[pos]
    if rank <= pts[0][0]:
        return float(pts[0][1])
    for (r0, v0), (r1, v1) in zip(pts, pts[1:]):
        if rank <= r1:
            return v0 + (v1 - v0) * (rank - r0) / (r1 - r0)
    return 0.0


def nrm(s):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", str(s or "").lower()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="scripts/jm_table.json")
    ap.add_argument("--out", default="scripts/jm_outcome_grades.json")
    ap.add_argument("--js", help="also write the compact site file (data/jm_career_grades.js)")
    ap.add_argument("--bump", action="store_true", help="with --js: rebuild the lookups bundle and bump its ?v= tag")
    ap.add_argument("--last-season", type=int, help="last COMPLETED NFL season (default: inferred from today)")
    a = ap.parse_args()
    today = datetime.date.today()
    # the regular season ends in the first days of January; treat it as complete from Jan 10
    last = a.last_season or (today.year - 1 if (today.month, today.day) >= (1, 10) else today.year - 2)
    data = gb.load_all_data()
    weekly = {}
    weekly.update(data["weekly_retired"])
    weekly.update(data["weekly_active"])
    seasons, posof = {}, {}
    for name, rec in weekly.items():
        if not isinstance(rec, dict):
            continue
        pos = rec.get("pos") or rec.get("s")
        if pos == "HB":
            pos = "RB"
        if pos not in CURVES:
            continue
        ss = [s for s in gb.get_player_seasons(rec) if s["yr"] <= last]
        if ss:
            seasons[name] = ss
            posof[name] = pos
    # ppg leaderboards per (year, position) among RANK_MIN_GP+ games
    board = defaultdict(list)
    for name, ss in seasons.items():
        for s in ss:
            if s["gp"] >= RANK_MIN_GP:
                board[(s["yr"], posof[name])].append(s["ppg"])
    for k in board:
        board[k].sort(reverse=True)
    by_norm = {nrm(n): n for n in seasons}
    print("players with NFL seasons: %d | last completed season %d" % (len(seasons), last))

    t = json.load(open(a.table, encoding="utf-8"))
    out, missing = {}, 0
    for r in t["rows"]:
        name, pos, dy = r["name"], r["pos"], r["o_yr"]
        key = name if name in seasons else by_norm.get(nrm(name)) or by_norm.get(nrm(r["o_raw"]["n"]))
        elapsed = max(0, min(len(WEIGHTS), last - dy + 1))
        ss = [s for s in (seasons.get(key) or []) if s["yr"] >= dy] if key else []
        if not key:
            missing += 1
        rows = []
        for s in ss:
            lb = board.get((s["yr"], pos), [])
            rank = 1 + sum(1 for v in lb if v > s["ppg"])
            val = curve(pos, rank) * min(1.0, s["gp"] / FULL_GP) if s["gp"] >= 4 else 0.0
            rows.append({"yr": s["yr"], "gp": s["gp"], "ppg": round(s["ppg"], 1), "rank": rank, "v": round(val, 1)})
        window = sorted((x["v"] for x in rows if x["yr"] < dy + WINDOW), reverse=True)[:elapsed]
        window += [0.0] * (elapsed - len(window))
        wsum = sum(WEIGHTS[:elapsed]) or 1.0
        grade = sum(w * v for w, v in zip(WEIGHTS, window)) / wsum if elapsed else None
        out["%s|%d" % (name, dy)] = {
            "grade": round(grade, 1) if grade is not None else None,
            "elapsed": elapsed, "provisional": elapsed < len(WEIGHTS),
            "elite": sum(1 for x in rows if x["v"] >= ELITE), "starter": sum(1 for x in rows if x["v"] >= STARTER),
            "best": round(max([x["v"] for x in rows] or [0]), 1), "seasons": rows,
        }
    json.dump({"last_season": last, "curves": CURVES, "weights": WEIGHTS, "players": out}, open(a.out, "w", encoding="utf-8"), separators=(",", ":"))
    if a.js:
        # "Name|draftYr": [career grade, elite seasons, starter seasons, provisional 0/1]
        compact = {k: [v["grade"], v["elite"], v["starter"], 1 if v["provisional"] else 0] for k, v in sorted(out.items()) if v["grade"] is not None}
        with open(a.js, "w", encoding="utf-8", newline="\n") as f:
            f.write("// GENERATED by scripts/build_outcome_grades.py - graded NFL career outcomes for the JM backtest players.\n")
            f.write("// career grade 0-100 = best four of the first six NFL seasons (40/30/20/10); elite season = value 85+,\n")
            f.write("// starter season = 50+. Through the %d season. Feeds the tier chips on the Prospect page.\n" % last)
            f.write("window.JM_CAREER_GRADES = " + json.dumps(compact, separators=(",", ":"), ensure_ascii=False) + ";\n")
        print("wrote %s (%d players)" % (a.js, len(compact)))
        if a.bump:
            # the file ships inside data/_bundle_lookups.js - rebuild it and bump its ?v= (read from disk now)
            import subprocess
            r = subprocess.run([sys.executable, os.path.join("scripts", "bundle_lookups.py")], capture_output=True, text=True, timeout=300)
            print("bundle_lookups.py exit %d" % r.returncode)
            if r.returncode == 0:
                with open("index.html", "r+b") as f:
                    html = f.read().decode("utf-8")
                    m = re.search(r"_bundle_lookups\.js\?v=([\w.-]+)", html)
                    if m:
                        base = today.isoformat() + "-cg"
                        m2 = re.match(re.escape(base) + r"(\d+)$", m.group(1))
                        new = base + str((int(m2.group(1)) + 1) if m2 else 1)
                        f.seek(0); f.write(html.replace("_bundle_lookups.js?v=" + m.group(1), "_bundle_lookups.js?v=" + new).encode("utf-8")); f.truncate()
                        print("bumped _bundle_lookups.js ?v= %s -> %s" % (m.group(1), new))
    print("graded %d backtest players (%d with no NFL games on file -> grade 0) -> %s" % (len(out), missing, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
