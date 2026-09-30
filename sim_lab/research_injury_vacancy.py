#!/usr/bin/env python3
"""
Are INJURIES (how long a player is out) and VACANCIES (who absorbs his work) a source of projection error?
(Jack 2026-09-30, for season-long / weekly.)

PART 1  how long absences last, 2019-25. Fantasy starters (preseason guide >= 8 half-PPR a game) who played
        at least one game, then missed one: how often is he back the NEXT game, and how many more does he
        miss? The engine treats an "Out" designation as THIS WEEK ONLY and IR as four games, so the
        rest-of-season numbers assume a full-strength return right after.
PART 2  what he does when he comes back (first game back, second, third) vs the projection form.
PART 3  2026 weeks 1-3: when a starter was out, how did we project the teammates who absorb his work, and
        the rest of that offense? (locked shipped number vs actual)
PART 4  2026 season-long: preseason per-game projections (ours, Clay, the sites) vs points per game so far.
Log injury_vacancy.log.
"""
import json, os, sys, io, re
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_sim_calibration as cal
from backtest_sim_calibration import played, weekly_rec, infer_team, OPP_ALIAS
from score_week import norm
REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"
class Tee:
    def __init__(s, *f): s.f = f
    def write(s, x):
        for f in s.f: f.write(x)
    def flush(s):
        for f in s.f: f.flush()

def part12():
    ch = json.load(open(os.path.join(REPO, "data", "clay_history.json"), encoding="utf-8"))
    spells = []     # (pos, length, censored, clay_pg, week started)
    back = defaultdict(list)   # (pos, games back 1/2/3, spell length bucket) -> act / expected
    for Y in range(2019, 2026):
        W = 16 if Y <= 2020 else 17; last = W + 1
        for name, c in ch[str(Y)].items():
            pos = c.get("pos")
            if pos not in ("QB", "RB", "WR", "TE"): continue
            pg = max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2) / W
            if pg < 8: continue
            rec = weekly_rec(name, pos)
            if rec is None: continue
            team = infer_team(rec, Y)
            if not team: continue
            sched = cal.SCHEDULES.get(Y, {}).get(team, {})
            gw = sorted(int(w) for w in sched if 1 <= int(w) <= last)
            pl = {w["wk"]: float(w["fpts"]) for w in rec.get("seasons", {}).get(str(Y), []) if played(w) and isinstance(w.get("fpts"), (int, float))}
            seq = [(w, pl.get(w)) for w in gw]
            i = 0; seen = False; hist = []
            while i < len(seq):
                w, v = seq[i]
                if v is not None:
                    seen = True; hist.append(v); i += 1; continue
                if not seen: i += 1; continue          # never played yet: a preseason injury / holdout, not an in-season absence
                j = i
                while j < len(seq) and seq[j][1] is None: j += 1
                L = j - i; cens = j >= len(seq)
                spells.append((pos, L, cens, pg, seq[i][0]))
                if not cens and len(hist) >= 1:
                    exp = (5 * pg + sum(hist)) / (5 + len(hist))       # the live blend form at his return
                    for k in range(3):
                        if j + k < len(seq) and seq[j + k][1] is not None and exp > 0:
                            back[(pos, k + 1, "1" if L == 1 else "2-3" if L <= 3 else "4+")].append(seq[j + k][1] / exp)
                        else: break
                i = j
    print("=== PART 1: how long an in-season absence lasts, fantasy starters 2019-25 ===")
    print(f"  absences: {len(spells)} (a run of missed team games after he had played that season; still out at season's end counted as at least that long)")
    print("  already missed   chance he ALSO misses the next game   further games missed on average   (engine: Out = back next game, IR = 4 games then back)")
    for k in (1, 2, 3, 4, 6, 8):
        at = [s for s in spells if s[1] >= k]                       # reached k missed
        nxt = [s for s in at if s[1] >= k + 1 or (s[2] and s[1] == k and False)]
        known = [s for s in at if not (s[2] and s[1] == k)]          # censored exactly at k: unknown whether he would miss k+1
        more = np.mean([s[1] - k for s in at])                        # lower bound (censoring)
        print(f"   {k} game{'s' if k > 1 else ' '}          {100*len([s for s in known if s[1] >= k + 1])/max(1,len(known)):5.1f}%  (n={len(known)})                      {more:4.1f}+")
    print("  by position: share of one-game-so-far absences that continue | average total length")
    for pos in ("QB", "RB", "WR", "TE"):
        x = [s for s in spells if s[0] == pos]; known = [s for s in x if not (s[2] and s[1] == 1)]
        print(f"   {pos}: n={len(x):4d}  misses the next game too {100*len([s for s in known if s[1] >= 2])/max(1,len(known)):4.1f}%   avg length {np.mean([s[1] for s in x]):.1f} games   1 game {100*np.mean([s[1]==1 for s in x]):.0f}% / 2-3 {100*np.mean([2<=s[1]<=3 for s in x]):.0f}% / 4+ {100*np.mean([s[1]>=4 for s in x]):.0f}%")
    L = np.array([s[1] for s in spells])
    print(f"  all: 1 game {100*np.mean(L==1):.0f}%, 2 {100*np.mean(L==2):.0f}%, 3 {100*np.mean(L==3):.0f}%, 4-6 {100*np.mean((L>=4)&(L<=6)):.0f}%, 7+ {100*np.mean(L>=7):.0f}%; median {np.median(L):.0f}, mean {L.mean():.1f}")
    print("\n=== PART 2: production when he returns, actual / the live blend's expectation (no matchup layers) ===")
    print("  spell length   first game back        second               third")
    for b in ("1", "2-3", "4+"):
        cells = []
        for k in (1, 2, 3):
            v = [x for pos in ("RB", "WR", "TE", "QB") for x in back.get((pos, k, b), [])]
            cells.append(f"{np.mean(v):.3f} (n={len(v)})" if len(v) >= 30 else f"- (n={len(v)})")
        print(f"   missed {b:4s}   " + "    ".join(f"{c:18s}" for c in cells))
    for pos in ("RB", "WR", "TE", "QB"):
        v = [x for b in ("1", "2-3", "4+") for x in back.get((pos, 1, b), [])]
        v4 = back.get((pos, 1, "4+"), [])
        print(f"   {pos} first game back: {np.mean(v):.3f} (n={len(v)})   after 4+ missed: " + (f"{np.mean(v4):.3f} (n={len(v4)})" if len(v4) >= 20 else f"n={len(v4)}"))
    return spells

def js(path, var=None):
    raw = open(path, encoding="utf-8", errors="replace").read()
    i = raw.index("window." + var) if var else (raw.index("window.") if "window." in raw[:3000] else 0)
    return json.JSONDecoder().raw_decode(raw[raw.index("{", i):])[0]

def part3():
    print("\n=== PART 3: 2026 weeks 1-3 - starters who sat, and how we projected the players around them ===")
    stats = js(os.path.join(REPO, "data", "weekly_stats_active.js"))
    slp = js(os.path.join(HERE, "data", "sleeper_players.js"))["players"]
    act = defaultdict(dict); tmwk = defaultdict(set)
    for name, rec in stats.items():
        for w in (rec.get("seasons") or {}).get("2026") or []:
            if isinstance(w.get("fpts"), (int, float)) and ((w.get("fpts") or 0) != 0 or (w.get("tgt") or 0) > 0 or (w.get("ra") or 0) > 0 or (w.get("pa") or 0) > 0):
                act[w["wk"]][norm(name)] = float(w["fpts"])
                if w.get("tm"): tmwk[w["wk"]].add(w["tm"])
    key = []   # starters by preseason guide
    for p in slp:
        if p.get("s") in ("QB", "RB", "WR", "TE") and p.get("cPts") and p.get("sTm"):
            pg = max(0.2, p["cPts"] - (p.get("cRec") or 0) / 2) / 17
            if pg >= (13 if p["s"] == "QB" else 8): key.append((p["n"], p["s"], p["sTm"], pg))
    rows = []; outs = []
    for wk in (1, 2, 3):
        snap = json.load(open(os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{wk}.json"), encoding="utf-8"))
        locked = {norm(p["name"]): p for p in snap["players"]}
        teams_playing = set(p["tm"] for p in snap["players"] if p.get("tm"))
        out_by = defaultdict(list)
        for n, pos, tm_, pg in key:
            if tm_ in teams_playing and norm(n) not in act[wk]:
                lk = locked.get(norm(n)); proj = lk["mean"] if lk else 0.0
                out_by[tm_].append((n, pos, pg, proj)); outs.append((wk, n, pos, tm_, pg, proj))
        for p in snap["players"]:
            if p.get("pos") not in ("QB", "RB", "WR", "TE") or (p.get("mean") or 0) < 5: continue
            a = act[wk].get(norm(p["name"]))
            if a is None: continue
            o = out_by.get(p["tm"], [])
            same = [x for x in o if x[1] == p["pos"]]; qb = [x for x in o if x[1] == "QB"]
            rec_out = [x for x in o if x[1] in ("WR", "TE")]
            cat = ("same position starter out" if same else "team QB out" if (qb and p["pos"] != "QB") else
                   "a pass catcher out (other position)" if (rec_out and p["pos"] in ("WR", "TE")) else
                   "other starter out on the team" if o else "full-strength team")
            rows.append({"wk": wk, "name": p["name"], "pos": p["pos"], "tm": p["tm"], "proj": p["mean"], "act": a, "cat": cat,
                         "surprise": bool(same and any(x[3] >= 5 for x in same)), "js": p.get("jsMean"), "clay": p.get("clayMean")})
    print(f"  starters who sat a game their team played: {len(outs)} player-weeks; we had a full projection locked for {sum(1 for o in outs if o[5] >= 5)} of them:")
    print("   " + "; ".join(f"W{o[0]} {o[1]} ({o[5]:.0f})" for o in outs if o[5] >= 5))
    print("   known in advance (locked at ~0): " + "; ".join(f"W{o[0]} {o[1]}" for o in outs if o[5] < 5)[:700])
    def line(lab, x):
        if len(x) < 6: print(f"   {lab:44s} n={len(x):3d} (too few)"); return
        e = np.array([r["proj"] - r["act"] for r in x]); se = e.std() / np.sqrt(len(e))
        print(f"   {lab:44s} n={len(x):3d}  actual/projected {sum(r['act'] for r in x)/sum(r['proj'] for r in x):.2f}  bias {e.mean():+5.2f} (t {e.mean()/se:+4.1f})  MAE {np.abs(e).mean():.2f}")
    print("  how the players around them did vs our locked number:")
    for c in ("full-strength team", "same position starter out", "team QB out", "a pass catcher out (other position)", "other starter out on the team"):
        line(c, [r for r in rows if r["cat"] == c])
    for pos in ("RB", "WR", "TE"):
        line(f"  {pos}: same position starter out", [r for r in rows if r["cat"] == "same position starter out" and r["pos"] == pos])
    line("  same position, starter was a LATE scratch", [r for r in rows if r["cat"] == "same position starter out" and r["surprise"]])
    line("  same position, absence known at lock", [r for r in rows if r["cat"] == "same position starter out" and not r["surprise"]])
    x = sorted([r for r in rows if r["cat"] == "same position starter out"], key=lambda r: r["proj"] - r["act"])
    print("   biggest under-projections next to an absent starter: " + "; ".join(f"W{r['wk']} {r['name']} {r['proj']:.1f}->{r['act']:.1f}" for r in x[:6]))
    print("   biggest over-projections: " + "; ".join(f"W{r['wk']} {r['name']} {r['proj']:.1f}->{r['act']:.1f}" for r in x[-6:]))

def part4():
    print("\n=== PART 4: 2026 season-long - preseason per-game projections vs actual through week 3 (full PPR, 2+ games played) ===")
    d = json.load(open(os.path.join(REPO, "accuracy", "data", "season_2026.json"), encoding="utf-8"))["players"]
    rows = []
    for n, p in d.items():
        wk = (p.get("act") or {}).get("wk") or {}
        pj = p.get("pj") or {}
        if len(wk) < 2 or p.get("pos") not in ("QB", "RB", "WR", "TE"): continue
        if not all(isinstance(pj.get(k), (int, float)) for k in ("sl", "espn", "cbs", "sim", "clay")): continue
        if max(pj["sim"], pj["espn"]) < 8: continue
        rows.append(dict(name=n, pos=p["pos"], act=float(np.mean(list(wk.values()))), g=len(wk), **{k: pj[k] for k in ("sim", "clay", "sl", "espn", "cbs")}, pre=p.get("pre") or {}))
    print(f"  players: {len(rows)} (projected 8+ PPR a game by us or ESPN)")
    def sp(a, b):
        ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b)); return float(np.corrcoef(ra, rb)[0, 1])
    lab = {"sim": "MFF sim (preseason)", "clay": "Clay", "sl": "Sleeper", "espn": "ESPN", "cbs": "CBS"}
    print(f"   {'source':22s} {'MAE':>6s} {'bias':>6s}   rank corr by position: QB     RB     WR     TE")
    for k in ("sim", "clay", "sl", "espn", "cbs"):
        e = np.array([r[k] - r["act"] for r in rows])
        cs = "  ".join(f"{sp([r[k] for r in rows if r['pos']==p], [r['act'] for r in rows if r['pos']==p]):+.2f}" for p in ("QB", "RB", "WR", "TE"))
        print(f"   {lab[k]:22s} {np.abs(e).mean():6.2f} {e.mean():+6.2f}                          {cs}")
    print("  preseason RANK boards, correlation with points-per-game finish inside each position (higher = better):")
    for k, l in (("jack", "Jack's board"), ("fp", "FantasyPros"), ("ud", "Underdog ADP"), ("espn", "ESPN"), ("sl", "Sleeper"), ("cbs", "CBS"), ("yahoo", "Yahoo")):
        cs = []
        for p in ("QB", "RB", "WR", "TE"):
            x = [r for r in rows if r["pos"] == p and isinstance(r["pre"].get(k), (int, float))]
            cs.append(f"{sp([-r['pre'][k] for r in x], [r['act'] for r in x]):+.2f} (n={len(x)})" if len(x) >= 10 else "-")
        print(f"   {l:14s} " + "   ".join(f"{p} {c}" for p, c in zip(("QB", "RB", "WR", "TE"), cs)))
    for tier, lo, hi in (("projected 15+", 15, 99), ("10-15", 10, 15), ("8-10", 8, 10)):
        x = [r for r in rows if lo <= r["sim"] < hi]
        if x: print(f"   our preseason number {tier:13s} n={len(x):3d}  actual/projected {sum(r['act'] for r in x)/sum(r['sim'] for r in x):.2f}   Clay {sum(r['act'] for r in x)/sum(r['clay'] for r in x):.2f}   ESPN {sum(r['act'] for r in x)/sum(r['espn'] for r in x):.2f}")

if __name__ == "__main__":
    sys.stdout = Tee(io.TextIOWrapper(sys.__stdout__.buffer, encoding="utf-8", errors="replace"), open(os.path.join(HERE, "injury_vacancy.log"), "w", encoding="utf-8"))
    part12(); part3(); part4()
