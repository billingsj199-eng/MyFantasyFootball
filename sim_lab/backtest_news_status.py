#!/usr/bin/env python3
"""NEWS STATUS check (2026-10-01): how often did the availability read off a news headline come true, weeks 1-3?
single-week reads (ruled out / expected to play / doubtful / game-time decision) vs whether he played that week;
timelines (out N-M weeks, out until week N, season) vs whether he played inside the window. Log news_status.log."""
import json, os, datetime, collections
import build_injury_signals as S
HERE = os.path.dirname(os.path.abspath(__file__))
def main():
    log = open(os.path.join(HERE, "news_status.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n")
    kicks = S.load_kicks(); cur = S.current_week(kicks)
    items = json.load(open(os.path.join(S.REPO, "data", "camp_news_2026.json"), encoding="utf-8"))["items"]
    raw = open(os.path.join(S.DATA, "sim_2026.js"), encoding="utf-8").read()
    D = json.loads(raw[raw.index("{", raw.index("window.SIM_2026")):].rstrip().rstrip(";"))["players"]
    res = collections.defaultdict(list); tl = []; PL = S.played_weeks()
    for it in items:
        if it.get("pos") not in S.SKILL: continue
        st = S.parse_item(it)
        if not st: continue
        n = S.norm(it["player"]); rec = D.get(n)
        d = datetime.date.fromisoformat(it["date"][:10]); games = S.team_games(kicks, it.get("team"))
        w0, _ = S._next_game(games, d)
        if w0 is None: continue
        wks = set((rec or {}).get("wks") or [])
        if st["k"] in ("out", "play", "doubt", "gtd"):
            wk = st.get("wk") or w0
            if wk >= cur: continue
            res[st["k"]].append((wk in wks, it["player"], wk, it["headline"]))
        elif st["k"] in ("season", "weeks", "ret"):
            st2 = S.news_state([it], kicks, 1, PL).get(n, {}).get("win")
            if not st2: continue
            inside = [w for w, _ in games if st2["from"] <= w <= st2["to"] and w < cur]
            if inside: tl.append((sum(w in wks for w in inside), len(inside), it["player"], st2["k"], st2["from"], st2["to"], it["date"], it["headline"]))
    P(f"=== news availability reads, weeks 1-{cur-1} (headline parser) ===")
    for k, lab in (("out", "ruled out"), ("doubt", "doubtful / unlikely"), ("gtd", "game-time decision"), ("play", "expected to play / cleared")):
        x = res[k]
        if not x: P(f"  {lab:28s} n 0"); continue
        P(f"  {lab:28s} played {sum(a for a, *_ in x)}/{len(x)} ({100*sum(a for a, *_ in x)/len(x):.0f}%)")
        for a, nm, wk, hl in x:
            if (k in ("out", "doubt") and a) or (k == "play" and not a): P(f"      miss: wk {wk} {nm} - {hl}")
    g = sum(a for a, *_ in tl); n = sum(b for _, b, *_ in tl)
    P(f"  timelines: {len(tl)} items, {n} player-games inside the stated window already played out -> he played {g} ({100*g/max(1,n):.0f}%)")
    for a, b, nm, k, f, t, dt, hl in tl:
        if a: P(f"      early return: {nm} played {a} of {b} games inside wk{f}-{t} ({k}, {dt}) - {hl}")
    log.close()
if __name__ == "__main__": main()
