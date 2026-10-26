#!/usr/bin/env python3
"""
P-20261023-2 REPLAY on the 2026 fill-in starters (2026-10-23, Jack: "build the history table, replay it on the 2026 fill-in
starters, and show me before wiring anything"). RESEARCH ONLY: reads the weekly locks, the play-by-play, the actuals file and a
headless dump of the live engine (_tmp/qb_replay_dump.js, in-memory patch only); engine.js / overrides.js untouched.

Rows
  PLAYED (W2-W7): every (team, week) where the QB with the most dropbacks was not the team's main QB (engine main = highest
  preseason Clay total, dump_qb_state.js) plus every QB lock row the vacancy layer touched (ncSrc '+vacx') whose team's main QB
  was absent. 'fired' = the fill-in has a lock row with '+vacx' (the layer moved his number pre-kickoff).
  UPCOMING (W7 remaining games, W8, W9): from the live engine's shadow cache: own / full / cap / string per QB.
Numbers
  shipped  = the lock's effective mean (propMean when a line / rate anchor was used, else jsMean) = what the site carried
  nc       = the lock's shadow number (since 10-08 the current week IS the shadow; W2-W3 locks pre-date the max form - the
             shadow then ADDED .85 x starter: those rows are marked 'add' and own / S are reconstructed, see notes)
  L        = history level (build_qb_history.QbHistory, walk-forward: games before that week only)
  P-2 nc   = (L + max(own, .85 S)) / 2 x T, T = the post-vacancy multipliers (QB total tilt etc.) = nc / max(own, .85 S); on
             played rows own / S are not in the lock so P-2 nc = (L + nc) / 2 (T folded in; the tilt is +-5% at most)
  P-2 ship = propMean + (1 - w) x (P-2 nc - nc) with w the anchor weight actually applied (lock tun.wa / engine p._propWUsed);
             no anchor -> P-2 nc
  actual   = half-PPR points (data/sim_actuals_2026.js by Sleeper id: pts_std + .5 x rec)
Output: _tmp/qb_inherit_replay_2026.md (+ .log)
"""
import os, sys, json, re
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from build_qb_history import QbHistory, players_map, norm, qkey, tm, SEASON, PBP
SNAP = os.path.join(HERE, "data", "snapshots"); TMP = os.path.join(HERE, "_tmp")
DUMP = os.path.join(TMP, "qb_replay_dump_w7.json"); STATE = os.path.join(TMP, "qb_state_w7.json")
OUT = os.path.join(TMP, "qb_inherit_replay_2026.md"); LOG = open(os.path.join(TMP, "qb_inherit_replay_2026.log"), "w", encoding="utf-8")
FRAC = 0.85
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()

def load_js(fp):
    t = open(fp, encoding="utf-8").read(); return json.loads(t[t.find("{"):t.rfind("}") + 1])
def eff(r):
    return r.get("propMean") if r.get("propMean") is not None else (r.get("jsMean") if r.get("jsMean") is not None else r.get("mean"))

def main():
    QH = QbHistory(quiet=False); PM = players_map()
    gsis_by_norm = {}
    for g, r in PM.items():
        if r["pos"] == "QB": gsis_by_norm.setdefault(norm(r["name"]), g)
    # engine main QB per team (highest preseason Clay total) from dump_qb_state.js
    state = json.loads(open(STATE, encoding="utf-8").read().strip().splitlines()[-1]); MAIN = {tm(t): x["main"] for t, x in state.items()}
    # actuals by sleeper id
    A = load_js(os.path.join(HERE, "data", "sim_actuals_2026.js")); AW = A["weeks"]
    def actual(wk, sid):
        r = AW.get(str(wk), {}).get(str(sid)) if sid else None
        return None if r is None else round(r[0] + 0.5 * r[1], 1)
    # locks
    locks = {}
    for wk in range(1, 10):
        fp = os.path.join(SNAP, f"simlab_snapshot_w{wk}.json")
        if os.path.exists(fp): locks[wk] = json.load(open(fp, encoding="utf-8"))
    def lock_row(wk, name):
        s = locks.get(wk); nk = norm(name)
        if not s: return None
        for v in s["players"]:
            if v.get("pos") == "QB" and norm(v["name"]) == nk: return v
        return None
    def lock_qbs(wk, team):
        s = locks.get(wk); return [v for v in (s["players"] if s else []) if v.get("pos") == "QB" and v["tm"] == team]
    # 2026 starters from the play-by-play
    d = pd.read_csv(os.path.join(PBP, f"play_by_play_{SEASON}.csv.gz"), usecols=["game_id", "week", "season_type", "posteam", "passer_player_id", "passer_player_name", "pass_attempt", "sack", "two_point_attempt", "play_id"], low_memory=False)
    d = d[(d.season_type == "REG") & (d.two_point_attempt != 1)]; d["posteam"] = d.posteam.map(tm)
    pa = d[((d.pass_attempt == 1) | (d.sack == 1)) & d.passer_player_id.notna()]
    g = pa.groupby(["week", "posteam", "passer_player_id", "passer_player_name"]).size().reset_index(name="db")
    st = g.sort_values("db", ascending=False).groupby(["week", "posteam"]).first().reset_index()
    first = pa.sort_values(["game_id", "play_id"]).groupby(["week", "posteam"]).first().reset_index()[["week", "posteam", "passer_player_name"]].rename(columns={"passer_player_name": "first_passer"})
    st = st.merge(first, on=["week", "posteam"])
    played_weeks = sorted(st.week.unique())
    # ---------------------------------------------------------------- PLAYED rows
    # The absent STARTER a fill-in stands in for: the engine main (highest preseason Clay total) or the team's starts leader
    # (most weeks as the top-dropback passer before this week), whichever is absent in this week's lock (no row / effective
    # mean < 2) and had started at least once this season. Teams whose preseason 'main' never started (Tua ATL, Sanders CLE,
    # Mendoza LV: camp competitions, not injuries) therefore produce no rows - their healthy starter is not a fill-in.
    ABSENT_PRESEASON = {("ATL", 1): "Michael Penix Jr.", ("ATL", 2): "Michael Penix Jr."}   # Penix missed W1-2 before his first start (no 2026 appearance to count)
    # dump_qb_state's main = highest PRESEASON Clay total: stale for three camp competitions the other QB won outright (never an
    # injury absence) - the real 2026 starter is the main there
    MAIN.update({"ATL": "Michael Penix Jr.", "CLE": "Deshaun Watson", "LV": "Kirk Cousins"})
    def prior_starts(team, wk):
        h = st[(st.posteam == team) & (st.week < wk)]; c = {}
        for r_ in h.itertuples(index=False):   # a start = the team's FIRST passer that week (top-dropback passer when the lists differ counts too)
            for nm in {r_.first_passer, r_.passer_player_name}: c[qkey(nm)] = c.get(qkey(nm), 0) + 1
        return c
    def absent_in_lock(wk, name):
        mr = lock_row(wk, name); return mr is None or eff(mr) is None or eff(mr) < 2
    def absent_starter(team, wk, fill_name):
        m = MAIN.get(team)
        if m and qkey(m) == qkey(fill_name): return None   # the main himself (returning) is never a fill-in
        if (team, wk) in ABSENT_PRESEASON and qkey(ABSENT_PRESEASON[(team, wk)]) != qkey(fill_name): return ABSENT_PRESEASON[(team, wk)]
        ps = prior_starts(team, wk); cands = []
        if m and ps.get(qkey(m), 0) >= 1: cands.append(m)
        if ps:
            lead = max(ps, key=ps.get)
            for g_, r_ in PM.items():
                if r_["pos"] == "QB" and qkey(r_["name"]) == lead and (r_["tm"] == team or any(h.posteam == team for h in st[st.passer_player_id == g_].itertuples(index=False))):
                    cands.append(r_["name"]); break
        for c in cands:
            if qkey(c) != qkey(fill_name) and absent_in_lock(wk, c): return c
        return None
    rows = []
    seen = set()
    gsis_by_qkey_team = {}
    for r_ in pa.drop_duplicates(["passer_player_id", "posteam"]).itertuples(index=False): gsis_by_qkey_team[(qkey(r_.passer_player_name), r_.posteam)] = r_.passer_player_id
    for r in st.itertuples(index=False):
        wk, team = int(r.week), r.posteam
        # the STARTER = the first passer of the game (the engine projected him); the top-dropback passer when different = an in-game replacement
        for who, started_game, note in ((r.first_passer, True, ""), (r.passer_player_name, True, " (in-game replacement)")):
            if who == r.passer_player_name and r.first_passer == r.passer_player_name and note: continue
            if who == r.first_passer and note: continue
            pid = gsis_by_qkey_team.get((qkey(who), team)) or (r.passer_player_id if who == r.passer_player_name else None)
            name = PM.get(pid, {}).get("name", who) if pid else who
            absent = absent_starter(team, wk, name)
            if not absent or (wk, norm(name)) in seen: continue
            lr = lock_row(wk, name)
            rows.append(dict(wk=wk, tm=team, name=name + note, gsis=pid, main=absent, started=True, db=int(r.db) if who == r.passer_player_name else 0, first=r.first_passer, lock=lr))
            seen.add((wk, norm(name)))
    for wk in played_weeks:   # vacx rows the layer touched for an absent starter, even if that QB did not start (chart miss)
        for v in (locks.get(wk) or {}).get("players", []):
            if v.get("pos") != "QB" or "+vacx" not in (v.get("ncSrc") or "") or (wk, norm(v["name"])) in seen: continue
            absent = absent_starter(v["tm"], wk, v["name"])
            if absent and not any(x["wk"] == wk and x["tm"] == v["tm"] and x["started"] for x in rows if norm(x["name"]) != norm(v["name"]) and x["lock"] and "+vacx" in (x["lock"].get("ncSrc") or "")):
                rows.append(dict(wk=wk, tm=v["tm"], name=v["name"], gsis=gsis_by_norm.get(norm(v["name"])), main=absent, started=False, db=0, first=None, lock=v)); seen.add((wk, norm(v["name"])))
    rows.sort(key=lambda x: (x["wk"], x["tm"]))
    # starter's last healthy lock number before the absence (display S on played rows; reconstruction on W2-W3 'add' rows)
    def starter_S(wk, main):
        for w in range(wk - 1, 0, -1):
            mr = lock_row(w, main)
            if mr and (mr.get("ncMean") or 0) >= 5 and "+vacx" not in (mr.get("ncSrc") or ""): return mr["ncMean"], w
        return None, None
    P(f"P-20261023-2 replay on 2026 - {pd.Timestamp.now():%Y-%m-%d %H:%M}; locks {sorted(locks)}; engine mains {len(MAIN)} teams; actuals weeks {sorted(int(k) for k in AW)}")
    P(); P("PLAYED fill-in rows (engine main QB absent; 'fired' = lock row carried +vacx):")
    hdr = "| wk | QB | team | for | fired | form | shipped | nc | own | S (last lock) | L (hist g / db) | P-2 nc | P-2 ship | actual | moved |"
    P(hdr); P("|" + "---|" * 15)
    md_played = [hdr, "|" + "---|" * 15]
    graded = []
    for x in rows:
        wk, lr = x["wk"], x["lock"]; pid = x["gsis"]
        lv = QH.level(pid, x["tm"], SEASON, wk) if pid else None
        L = lv["L"] if lv else None
        sid = lr.get("sid") if lr else None
        if not sid:
            for r_ in lock_qbs(wk, x["tm"]):
                if norm(r_["name"]) == norm(x["name"]): sid = r_.get("sid")
        act = actual(wk, sid) if x["started"] else None
        fired = bool(lr and "+vacx" in (lr.get("ncSrc") or ""))
        S, Sw = starter_S(wk, x["main"])
        form = "-" if not lr else ("add" if wk <= 3 else "max")
        shipped = eff(lr) if lr else None; nc = lr.get("ncMean") if lr else None
        own = None; base = None; p2nc = None; p2ship = None
        if lr and nc is not None and L is not None:
            if form == "add" and S is not None and nc - FRAC * S > 0.5:
                own = nc - FRAC * S; base = max(own, FRAC * S)   # reconstructed: the W2-W3 shadow added .85 x starter to own
            else: base = nc
            p2nc = (L + base) / 2
            w = (lr.get("tun") or {}).get("wa")
            if lr.get("propMean") is not None and w is not None: p2ship = lr["propMean"] + (1 - w) * (p2nc - base) + (nc - base) * 0   # anchor keeps its weight; base swap
            elif lr.get("propMean") is not None: p2ship = lr["propMean"] + (1 - 0.5) * (p2nc - base)
            else: p2ship = p2nc
            if form == "add": shipped_cur = (lr["propMean"] + (1 - (w if w is not None else .5)) * (base - lr["jsMean"])) if lr.get("propMean") is not None else base   # what the CURRENT engine form (shadow alone + anchor) would have shipped
            else: shipped_cur = shipped
        else: shipped_cur = shipped
        moved = "" if p2nc is None or base is None else ("up" if p2nc > base + 0.05 else "down" if p2nc < base - 0.05 else "flat")
        f = lambda v: "-" if v is None else f"{v:.1f}"
        Ltxt = "-" if lv is None else f"{L:.1f} ({lv['g']} g / {lv['n']} db, shrink {lv['shrink']:.2f}; db/g {lv['teamDb']:.0f})"
        line = f"| {wk} | {x['name']} | {x['tm']} | {x['main']} | {'yes' if fired else ('no row' if not lr else 'no')} | {form} | {f(shipped)} | {f(nc)} | {f(own)} | {f(S)}{'' if Sw is None else f' (W{Sw})'} | {Ltxt} | {f(p2nc)} | {f(p2ship)} | {f(act) if x['started'] else 'DNP'} | {moved} |"
        P(line); md_played.append(line)
        if x["started"] and act is not None and fired and p2nc is not None:
            graded.append(dict(wk=wk, name=x["name"], tm=x["tm"], form=form, shipped=shipped, shipped_cur=shipped_cur, nc=nc, base=base, L=L, p2nc=p2nc, p2ship=p2ship, act=act, w=(lr.get("tun") or {}).get("wa"), db=x["db"]))
    # ---------------------------------------------------------------- grading
    G = pd.DataFrame(graded)
    summ = []
    def mae(a, b): return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))
    def block(title, g):
        if not len(g): return
        n = len(g)
        s = [f"**{title}** n {n}: shadow nc MAE {mae(g.base, g.act):.2f} -> P-2 nc {mae(g.p2nc, g.act):.2f} ({100*(mae(g.p2nc, g.act)/mae(g.base, g.act)-1):+.1f}%), "
             f"shipped MAE {mae(g.shipped_cur, g.act):.2f} -> P-2 shipped {mae(g.p2ship, g.act):.2f} ({100*(mae(g.p2ship, g.act)/mae(g.shipped_cur, g.act)-1):+.1f}%); "
             f"bias (proj - act) shadow {np.mean(g.base - g.act):+.2f} -> {np.mean(g.p2nc - g.act):+.2f}, shipped {np.mean(g.shipped_cur - g.act):+.2f} -> {np.mean(g.p2ship - g.act):+.2f}; "
             f"P-2 closer on {int((np.abs(g.p2ship - g.act) < np.abs(g.shipped_cur - g.act) - 1e-9).sum())}/{n} rows (shipped), {int((np.abs(g.p2nc - g.act) < np.abs(g.base - g.act) - 1e-9).sum())}/{n} (shadow); "
             f"rows moved up {int((g.p2nc > g.base + .05).sum())} / down {int((g.p2nc < g.base - .05).sum())}; mean L {g.L.mean():.1f} vs shadow {g.base.mean():.1f} vs actual {g.act.mean():.1f}"]
        for t in s: P("  " + t); summ.append(t)
    P(); block("ALL fired + started rows", G); block("W4-W7 (max form, lock nc = max(own, .85 S) x tilt)", G[G.form == "max"]); block("W2-W3 (additive-era locks, own / S reconstructed)", G[G.form == "add"])
    block("Finished the game (10+ dropbacks; drops the in-game injury row)", G[G.db >= 10]); block("W4-W7 max form, finished the game", G[(G.form == "max") & (G.db >= 10)])
    # ---------------------------------------------------------------- UPCOMING rows from the live engine
    dmp = json.loads(open(DUMP, encoding="utf-8").read().strip().splitlines()[-1])
    P(); P(f"UPCOMING rows (live engine, current week {dmp['cur']}; a team is listed when a QB in the room has availability < 1 and a healthy QB carries +vacx):")
    hdr2 = "| wk | QB (string) | team | absent (cap, full) | own | S = absent full | .85 S | engine nc | T | L (hist) | P-2 nc | engine shipped (anchor w) | P-2 shipped | actual |"
    P(hdr2); P("|" + "---|" * 14); md_up = [hdr2, "|" + "---|" * 14]
    for wk, W in sorted(dmp["weeks"].items(), key=lambda kv: int(kv[0])):
        wk = int(wk)
        for team, x in sorted(W.items()):
            q = x["qbs"]; absent = [r for r in q if r.get("cap") is not None and r["cap"] < 1 and (r.get("full") or 0) > 0]
            fills = [r for r in q if "+vacx" in (r.get("ncSrc") or "") and (r.get("cap") == 1)]
            if not absent or not fills: continue
            lost_r = max(absent, key=lambda r: r["full"] * (1 - r["cap"])); lost = lost_r["full"] * (1 - lost_r["cap"]); gained = FRAC * lost
            for fr in fills:
                own = fr.get("own") or 0; S = lost_r["full"]
                # GATE the replay applies (and the wiring must): the fill-in is the projected STARTER (effective string 1 among available
                # QBs) and the absent QB is the team's starter (engine main or the better chart string) and is Out / Doubtful / IR (cap <= .5),
                # not a Questionable starter or an absent backup - otherwise P-2 would lift Kaliakmanis (WAS QB3) or Bagent behind a Q Caleb.
                genuine = (fr.get("str") == 1) and lost_r["cap"] <= 0.5 and ((lost_r.get("dstr") or 99) < (fr.get("dstr") or 99) or norm(lost_r["name"]) == norm(MAIN.get(team, "")))
                base = max(own, gained); T = (fr["ncMean"] / base) if base > 0 else 1.0
                pid = gsis_by_norm.get(fr["norm"]); lv = QH.level(pid, team, SEASON, wk) if pid else None; L = lv["L"] if lv else None
                p2nc = None if L is None else (L + max(own, FRAC * S)) / 2 * T
                w = fr.get("propW"); ship = fr["eff"]
                p2ship = None if p2nc is None else (fr["propMean"] + (1 - w) * (p2nc - fr["ncMean"]) if fr.get("propMean") is not None and w is not None else p2nc)
                act = actual(wk, fr.get("sid"))
                f = lambda v: "-" if v is None else f"{v:.1f}"
                tag = "" if genuine else " (GATE: not a next-man-up start - P-2 must NOT fire)"
                if not genuine: p2nc = None; p2ship = None
                line = (f"| {wk} | {fr['name']} ({fr.get('cstr')}){tag} | {team} | {lost_r['name']} ({lost_r['cap']:.2f}, {lost_r['full']:.1f}) | {own:.1f} | {S:.1f} | {FRAC*S:.1f} | {fr['ncMean']:.1f} | {T:.2f} | "
                        f"{'-' if lv is None else f'{L:.1f} ({lv['g']} g / {lv['n']} db, shrink {lv['shrink']:.2f}; db/g {lv['teamDb']:.0f})'} | {f(p2nc)} | {ship:.1f} ({fr.get('propSrc') or 'none'}{'' if w is None else f' w {w:.2f}'}) | {f(p2ship)} | {f(act) if act is not None else 'upcoming'} |")
                P(line); md_up.append(line)
    # ---------------------------------------------------------------- write the markdown
    md = ["# P-20261023-2 replay on the 2026 fill-in starters", f"_{pd.Timestamp.now():%Y-%m-%d %H:%M}_ - research only; engine.js / overrides.js / exports untouched.", "",
          "Definitions: shipped = the lock's effective mean (prop anchor when a line existed); nc = lock shadow number; L = history level (build_qb_history.py,",
          "walk-forward: games before that week only, .6^k season decay, 120-dropback shrink to replacement, x the team's dropbacks per game season to date + rush pts/g);",
          "P-2 nc = (L + max(own, .85 S)) / 2 (played rows: (L + nc) / 2 - own / S are not stored in the lock); P-2 shipped = the same prop anchor on the new base.",
          "'add' rows: the W2-W3 shadow ADDED .85 x the starter (the max form shipped 10-02) - own and S are reconstructed from the starter's last healthy lock number.", "",
          "## Played rows", *md_played, "", "## Grading (fired + started rows)", *[f"- {s}" for s in summ], "",
          "## Upcoming rows (live engine)", *md_up, "",
          "Notes: the live engine's S for a long-term absence (IR / season override) is the absent starter's number AT HIS CURRENT CHART STRING (the backup cap tag +qb4",
          "docks him to a backup level, e.g. Hurts full 7.5, Dart 3.4), so for IR'd starters the engine's .85 x S floor is already far below the fill-in's own number and",
          "P-2 reduces to avg(L, own). The backtest's S was the starter's real rate; the difference only matters when .85 S would beat own."]
    with open(OUT, "wb") as fh: fh.write("\n".join(md).encode("utf-8"))
    P(); P(f"wrote {OUT}")
    LOG.close()

if __name__ == "__main__":
    main()
