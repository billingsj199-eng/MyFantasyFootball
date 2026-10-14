"""
OUT-UNCONFIRMED play rate (Jack 2026-10-14: "measure the out-unconfirmed play rate and propose a level").

Replays the engine's applyInSeasonInjuries rule (engine.js ~3103) at every committed snapshot of the repo's
Sleeper injury feed (data/injury_updates.js, ~3/day since 09-01):
    Sleeper tag "..., Out"  AND  Sleeper's weekly projection for that week > 0 (weekly_projections.json 'h',
    same week)  AND  NFL report game status for that week not Out / Doubtful
    -> engine prices x0.75 'out-unconfirmed'.
Outcome = played that week (2026 snap share row > 0, data/snap_counts.js; fallback weekly_stats_active row with an opp).
Weeks graded: completed ones only. Read-only on the repo (git show).

Usage: python research_out_unconfirmed.py   (log: _tmp/out_unconfirmed.log)
"""
import datetime, json, math, os, re, subprocess, sys, collections

REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"
HERE = os.path.dirname(os.path.abspath(__file__))
KICKS = json.load(open(os.path.join(HERE, "data", "kickoffs_2026.json"), encoding="utf-8"))
LOG = os.path.join(HERE, "_tmp", "out_unconfirmed.log")
os.makedirs(os.path.dirname(LOG), exist_ok=True)
_logf = open(LOG, "w", encoding="utf-8")
def out(*a):
    s = " ".join(str(x) for x in a); print(s); _logf.write(s + "\n")

def git(*a):
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True, encoding="utf-8").stdout

def snaps(path, since="2026-09-01"):
    rows = []
    for line in git("log", f"--since={since}", "--format=%H %cI", "--", path).splitlines():
        h, t = line.split(" ", 1)
        rows.append((datetime.datetime.fromisoformat(t).astimezone(datetime.timezone.utc), h))
    return sorted(rows)

def js_obj(txt):
    i = txt.index("{")
    return json.JSONDecoder().raw_decode(txt[i:])[0]   # first object only (some files carry more statements after it)

def kick(tm, wk):
    v = (KICKS.get(str(wk)) or {}).get(tm)
    return datetime.datetime.fromisoformat(v.replace("Z", "+00:00")) if v else None

def next_week(tm, t):
    for wk in range(1, 19):
        k = kick(tm, wk)
        if k and k > t: return wk, k
    return None, None

def wilson(k, n, z=1.96):
    if n == 0: return (float("nan"),) * 2
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - r) / d, (c + r) / d

def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    sim = json.loads(open(os.path.join(REPO, "data", "sim_proj_2026.json"), encoding="utf-8").read())
    team_of = sim["teamOf"]
    sc = js_obj(git("show", "HEAD:data/snap_counts.js"))
    ws = js_obj(git("show", "HEAD:data/weekly_stats_active.js"))
    pos_of = {n: v.get("pos") for n, v in ws.items()}

    def played(n, wk):
        w = ((sc.get(n) or {}).get("2026") or {}).get("w") or {}
        if str(wk) in w: return (w[str(wk)] or 0) > 0
        for r in ((ws.get(n) or {}).get("seasons") or {}).get("2026", []):
            if r.get("wk") == wk: return bool(r.get("opp")) and any((r.get(k) or 0) for k in ("ra", "tgt", "rec", "fpts", "py") if k in r)
        return False

    inj_s = snaps("data/injury_updates.js")
    wp_s = snaps("data/weekly_projections.json", "2026-08-25")
    pr_s = snaps("data/practice_2026.js", "2026-08-25")
    out(f"snapshots: injury {len(inj_s)}, weekly proj {len(wp_s)}, practice {len(pr_s)}")
    cache = {}
    def load(path, h, js):
        k = (path, h)
        if k not in cache:
            txt = git("show", f"{h}:{path}")
            try: cache[k] = js_obj(txt) if js else json.loads(txt)
            except Exception: cache[k] = None
        return cache[k]
    def latest(series, t):
        best = None
        for ts, h in series:
            if ts <= t: best = h
            else: break
        return best

    states = {}   # (player, wk) -> list of (t, hours_to_kick)
    confirmed = collections.Counter()
    for t, h in inj_s:
        inj = load("data/injury_updates.js", h, True)
        if not inj: continue
        hw, hp = latest(wp_s, t), latest(pr_s, t)
        wp = load("data/weekly_projections.json", hw, False) if hw else None
        pr = load("data/practice_2026.js", hp, True) if hp else None
        for n, tag in (inj.get("players") or {}).items():
            if not re.search(r",\s*Out$", str(tag)): continue
            tm = team_of.get(n)
            if not tm or pos_of.get(n) not in ("QB", "RB", "WR", "TE"): continue
            wk, k = next_week(tm, t)
            if not wk or k > now: continue                       # only completed weeks
            if not wp or int(wp.get("week") or 0) != wk: confirmed["no Sleeper weekly for that week (engine zeroes)"] += 1; continue
            hproj = ((wp.get("players") or {}).get(n) or {}).get("h")
            if not hproj or hproj <= 0: confirmed["Sleeper weekly proj 0/absent (confirmed)"] += 1; continue
            gs = ""
            if pr and int(pr.get("week") or 0) == wk:
                gs = str(((pr.get("players") or {}).get(n) or {}).get("gs") or "").lower()
            if gs == "out": confirmed["NFL Out (confirmed)"] += 1; continue
            if gs == "doubtful": confirmed["NFL Doubtful (x0.5 dock)"] += 1; continue
            states.setdefault((n, wk), []).append((t, (k - t).total_seconds() / 3600, gs))
    out("snapshots NOT unconfirmed (engine zero/dock):", dict(confirmed))

    rows = []
    for (n, wk), lst in states.items():
        first = min(lst); last = max(lst)
        rows.append({"n": n, "wk": wk, "pos": pos_of.get(n), "tm": team_of.get(n),
                     "h_first": first[1], "h_last": last[1], "gs_last": last[2],
                     "prev": played(n, wk - 1) if wk > 1 else None, "played": played(n, wk)})
    out(f"\nplayer-weeks ever out-unconfirmed (weeks graded <= now): {len(rows)}")

    def rep(label, sub):
        k = sum(r["played"] for r in sub); n = len(sub)
        lo, hi = wilson(k, n)
        out(f"  {label:44s} n={n:3d}  played {k:3d}  rate {k / n if n else float('nan'):.2f}  95% CI {lo:.2f}-{hi:.2f}")
    rep("ALL", rows)
    out("by hours before kickoff at the LAST unconfirmed snapshot (= the state the number stood on longest-into-the-week):")
    for lab, a, b in [(">96 h (Mon-Wed for a Sunday game)", 96, 1e9), ("48-96 h (Thu-Fri)", 48, 96), ("<48 h (Sat-gameday)", 0, 48)]:
        rep(lab, [r for r in rows if a <= r["h_last"] < b])
    out("by the FIRST unconfirmed snapshot:")
    for lab, a, b in [(">96 h", 96, 1e9), ("48-96 h", 48, 96), ("<48 h", 0, 48)]:
        rep(lab, [r for r in rows if a <= r["h_first"] < b])
    out("by previous game:")
    rep("played his previous game (new injury)", [r for r in rows if r["prev"] is True])
    rep("missed his previous game (Out lingering)", [r for r in rows if r["prev"] is False])
    out("by NFL game status at last snapshot:")
    for g in sorted(set(r["gs_last"] for r in rows)):
        rep(f"gs='{g}'", [r for r in rows if r["gs_last"] == g])
    out("by position:")
    for p in ("QB", "RB", "WR", "TE"):
        rep(p, [r for r in rows if r["pos"] == p])

    # snapshot-weighted: how often a published number sat on this state, and the play rate behind it
    snap_rows = [(n, wk, hh, gs) for (n, wk), lst in states.items() for (_, hh, gs) in lst]
    pw = {(r["n"], r["wk"]): r["played"] for r in rows}
    k = sum(pw[(n, wk)] for n, wk, _, _ in snap_rows)
    out(f"\nsnapshot-weighted (every export-time state): n={len(snap_rows)} played-rate {k / len(snap_rows):.2f}")

    # Brier of flat levels vs outcome, player-week level
    out("\nBrier (player-week, lower = better) for a flat P(plays):")
    for lv in (0.75, 0.6, 0.5, 0.4, 0.33, 0.25):
        b = sum((lv - r["played"]) ** 2 for r in rows) / max(1, len(rows))
        out(f"  {lv:.2f}: {b:.4f}")
    out("\nearly week (> 96 h at the snapshot) x previous game, SNAPSHOT level (each export-time state):")
    sn = [(n, wk, hh, gs) for (n, wk), lst in states.items() for (_, hh, gs) in lst]
    prev = {(r["n"], r["wk"]): r["prev"] for r in rows}
    def rep_s(label, sub):
        k = sum(pw[(n, wk)] for n, wk, _, _ in sub); m = len(sub); lo, hi = wilson(k, m)
        pws = len(set((n, wk) for n, wk, _, _ in sub)); kp = sum(pw[x] for x in set((n, wk) for n, wk, _, _ in sub))
        out(f"  {label:44s} snapshots {m:3d} rate {k / m if m else float('nan'):.2f} | player-weeks {pws:3d} played {kp:3d} rate {kp / pws if pws else float('nan'):.2f}  CI {wilson(kp, pws)[0]:.2f}-{wilson(kp, pws)[1]:.2f}")
    for hl, a, b in [(">96 h", 96, 1e9), ("36-96 h", 36, 96), ("<36 h", 0, 36)]:
        for pl, pv in [("missed prev (lingering)", False), ("played prev (new injury)", True), ("week 1 (no prev)", None)]:
            rep_s(f"{hl} {pl}", [s for s in sn if a <= s[2] < b and prev[(s[0], s[1])] is pv])

    # candidate tiered levels, graded at the SNAPSHOT level (what each export published), Brier vs flat
    def tier(hh, pv, lv):
        if hh < 36: return lv["late"]
        if pv is True: return lv["new"]
        return lv["linger"]
    cands = {"flat .75 (live)": dict(late=.75, new=.75, linger=.75), "flat .33": dict(late=.33, new=.33, linger=.33),
             "tiered .50/.10/0": dict(late=0.0, new=0.10, linger=0.50), "tiered .50/.15/.05": dict(late=0.05, new=0.15, linger=0.50),
             "tiered .60/.15/0": dict(late=0.0, new=0.15, linger=0.60), "tiered .40/.10/0": dict(late=0.0, new=0.10, linger=0.40)}
    out("\nBrier at snapshot level (lower = better) - n=%d export-time states:" % len(sn))
    for nm, lv in cands.items():
        b = sum((tier(hh, prev[(n, wk)], lv) - pw[(n, wk)]) ** 2 for n, wk, hh, _ in sn) / len(sn)
        out(f"  {nm:22s} {b:.4f}")
    # leave-one-week-out for the tiered fit: fit linger / new rates on other weeks, score the held-out week
    out("\nleave-one-week-out (tiered rates fit on the other weeks, late tier = 0):")
    tot_t = tot_f = 0; nn = 0
    for hold in sorted(set(wk for _, wk, _, _ in sn)):
        tr = [s for s in sn if s[1] != hold and s[2] >= 36]
        def rate(sub, pvs):
            x = [pw[(n, wk)] for n, wk, _, _ in sub if prev[(n, wk)] in pvs]
            return (sum(x) + 1) / (len(x) + 2)   # Laplace
        lv = dict(late=0.0, new=rate(tr, (True,)), linger=rate(tr, (False, None)))
        te = [s for s in sn if s[1] == hold]
        bt = sum((tier(hh, prev[(n, wk)], lv) - pw[(n, wk)]) ** 2 for n, wk, hh, _ in te)
        bf = sum((0.75 - pw[(n, wk)]) ** 2 for n, wk, hh, _ in te)
        tot_t += bt; tot_f += bf; nn += len(te)
        out(f"  hold wk{hold}: n={len(te):3d} fit linger {lv['linger']:.2f} new {lv['new']:.2f} | Brier tiered {bt / max(1, len(te)):.3f} vs flat .75 {bf / max(1, len(te)):.3f}")
    out(f"  pooled: tiered {tot_t / nn:.4f} vs flat .75 {tot_f / nn:.4f}")
    out("\nrows:")
    for r in sorted(rows, key=lambda r: (r["wk"], r["n"])):
        out(f"  wk{r['wk']} {r['n']:24s} {r['pos']} {r['tm']:4s} first {r['h_first']:6.0f}h last {r['h_last']:6.0f}h gs={r['gs_last'] or '-':12s} prev={r['prev']} PLAYED={r['played']}")

if __name__ == "__main__":
    main()
