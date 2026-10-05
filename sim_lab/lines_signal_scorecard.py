#!/usr/bin/env python3
"""
LINES-UP + PRACTICE-TREND scorecard (Jack 2026-10-01: "sportsbooks adding lines for the players or not").

Reads data/lines_signal_log.jsonl (build_injury_signals.py appends a row whenever a designated player's state
changes: report status, latest practice, practice sequence, Sleeper tag, which books have a yardage / reception
line up) and grades it against who actually played (data/sim_2026.js).

Only the PRE-INACTIVES state counts: for each player-week the last row logged at least 100 minutes before his own
kickoff (inactives post 90 minutes out; after that the books have simply pulled the scratches and the signal is
hindsight - the end-of-week file read 100% / 18% on weeks 1-3, the honest cut 78% / 36%).

  python lines_signal_scorecard.py              cumulative table + the latest finished week
  python lines_signal_scorecard.py --backfill   one-time: rebuild weeks 1-3 rows from the repo's git history
Intel only until the sample is big enough to set a weight (about 100 Questionable player-weeks, ~week 9-10).
Log lines_signal_scorecard.log. Chained in weekly_scorecard.py (Tuesday).
"""
import datetime, json, os, re, subprocess, sys, tempfile
from collections import defaultdict
import build_injury_signals as S
HERE = os.path.dirname(os.path.abspath(__file__))
CUT_MIN = 100

def git(*a): return subprocess.run(["git", "-C", S.REPO] + list(a), capture_output=True, text=True, encoding="utf-8", errors="replace").stdout

def backfill():
    kicks = S.load_kicks(); cur = S.current_week(kicks)
    have = set()
    if os.path.exists(S.LOG_PATH):
        for line in open(S.LOG_PATH, encoding="utf-8"):
            try: r = json.loads(line)
            except Exception: continue
            if r.get("bf"): have.add(r["wk"])
    node = r"E:\node\node.exe" if os.path.exists(r"E:\node\node.exe") else "node"
    js = "global.window=global;require('vm').runInThisContext(require('fs').readFileSync(process.argv[1],'utf8'));process.stdout.write(JSON.stringify(window.BETTING_2026.weeklyProps||{}))"
    rows = []
    for wk in range(1, cur):
        if wk in have: continue
        slots = defaultdict(list)
        for tm, iso in (kicks.get(str(wk)) or {}).items(): slots[iso].append(tm)
        for iso, tms in sorted(slots.items()):
            cut = (S._dt(iso) - datetime.timedelta(minutes=CUT_MIN)).isoformat()
            hb = git("log", "-1", "--format=%H", f"--until={cut}", "--", "data/betting_lines_2026.js").strip()
            hp = git("log", "-1", "--format=%H %aI", f"--until={cut}", "--", "data/practice_2026.js").strip().split(" ")
            if not hb or not hp[0]: continue
            tmp = os.path.join(tempfile.gettempdir(), "bl_bf.js")
            open(tmp, "w", encoding="utf-8").write(git("show", f"{hb}:data/betting_lines_2026.js"))
            try: WP = json.loads(subprocess.run([node, "-e", js, tmp], capture_output=True, text=True, encoding="utf-8").stdout)
            except Exception: continue
            m = re.search(r"window\.PRACTICE_2026\s*=\s*(\{.*\});?\s*$", git("show", f"{hp[0]}:data/practice_2026.js"), re.S)
            if not m: continue
            PR = json.loads(m.group(1))
            if PR.get("week") != wk: continue
            up = S.books_up(WP.get(str(wk))); usual = set()
            for w2, o in WP.items():
                if w2 != str(wk): usual |= set(S.books_up(o))
            seqs = {}
            try: seqs = json.load(open(S.SEQ_PATH, encoding="utf-8")).get(str(wk), {})
            except Exception: pass
            for nm, v in PR.get("players", {}).items():
                if v.get("pos") not in S.SKILL or v.get("tm") not in tms: continue
                n = S.norm(nm); days = (seqs.get(n) or {}).get("days") or {}
                days = {d: p for d, p in days.items() if d <= cut[:10]}
                rows.append({"ts": S._dt(hp[1]).astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "wk": wk, "n": n, "name": nm, "pos": v["pos"], "tm": v["tm"],
                             "gs": v.get("gs", ""), "pr": v.get("pr", ""), "seq": S.seq_str(days), "sl": "", "g": S.grp(v.get("inj")), "books": up.get(n, []), "usual": n in usual, "ko": iso, "bf": True})
    if rows:
        with open(S.LOG_PATH, "a", encoding="utf-8") as f:
            for r in rows: f.write(json.dumps(r, separators=(",", ":")) + "\n")
    print(f"backfilled {len(rows)} rows (weeks {sorted(set(r['wk'] for r in rows))})")

def load_state():
    """{(wk, norm): last row at least CUT_MIN before his kickoff}"""
    st = {}
    if not os.path.exists(S.LOG_PATH): return st
    for line in open(S.LOG_PATH, encoding="utf-8"):
        try: r = json.loads(line)
        except Exception: continue
        if not r.get("ko"): continue
        if S._dt(r["ts"]) > S._dt(r["ko"]) - datetime.timedelta(minutes=CUT_MIN): continue
        k = (r["wk"], r["n"])
        if k not in st or r["ts"] >= st[k]["ts"]: st[k] = r
    return st

def trend(seq):
    s = [x for x in (seq or "").split("-") if x in ("DNP", "LP", "FP")]
    if len(s) < 2: return "one day"
    rk = {"DNP": 0, "LP": 1, "FP": 2}
    return "upgraded" if rk[s[-1]] > rk[s[0]] else "downgraded" if rk[s[-1]] < rk[s[0]] else "flat"

def main():
    if "--backfill" in sys.argv: backfill()
    log = open(os.path.join(HERE, "lines_signal_scorecard.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n")
    kicks = S.load_kicks(); cur = S.current_week(kicks); played = S.played_weeks(); st = load_state()
    rows = [dict(r, played=(r["wk"] in played.get(r["n"], ()))) for (wk, n), r in st.items() if wk < cur and n in played]
    P(f"=== lines-up + practice-trend scorecard: {len(rows)} designated player-weeks, weeks {sorted(set(r['wk'] for r in rows))} (pre-inactives state) ===")
    def rate(lab, x, ind="    "):
        if not x: return
        k = sum(r["played"] for r in x); P(f"{ind}{lab:46s} played {k:3d}/{len(x):3d}  ({100*k/len(x):3.0f}%)")
    for gs in ("Questionable", "Doubtful", "Out", ""):
        x = [r for r in rows if r["gs"] == gs]
        if not x: continue
        P(f"\n  game status: {gs or 'none (on the report, no designation)'}"); rate("all", x)
        rate("lines up at 2+ books", [r for r in x if len(r["books"]) >= 2]); rate("lines up at 1 book", [r for r in x if len(r["books"]) == 1])
        rate("no lines, usually has them", [r for r in x if not r["books"] and r["usual"]]); rate("no lines, never lined", [r for r in x if not r["books"] and not r["usual"]])
    q = [r for r in rows if r["gs"] == "Questionable"]
    if q:
        P("\n  Questionable by the week's practice sequence:")
        for pr in ("FP", "LP", "DNP"):
            for t in ("upgraded", "flat", "downgraded", "one day"):
                rate(f"last {pr}, {t}", [r for r in q if r["pr"] == pr and trend(r["seq"]) == t])
        P("\n  Questionable, lines x last practice:")
        for pr in ("FP", "LP", "DNP"):
            rate(f"last {pr}, lines at 2+ books", [r for r in q if r["pr"] == pr and len(r["books"]) >= 2]); rate(f"last {pr}, no lines", [r for r in q if r["pr"] == pr and not r["books"]])
        P(f"\n  sample for a weight: {len(q)} Questionable player-weeks so far (target ~100 before the lines signal moves a projection)")
    last = cur - 1
    x = [r for r in rows if r["wk"] == last and r["gs"] == "Questionable"]
    if x:
        P(f"\n  week {last} Questionable detail:")
        for r in sorted(x, key=lambda r: -len(r["books"])): P(f"    {r['name']:22s} {r['pos']} {r['tm']:3s} {r['seq'] or r['pr']:14s} {len(r['books'])} books  {'PLAYED' if r['played'] else 'sat'}")
    log.close()

if __name__ == "__main__":
    main()
