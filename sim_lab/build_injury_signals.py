#!/usr/bin/env python3
"""
INJURY SIGNALS (Jack 2026-10-01: "get the practice reports of all teams everyday ... what kind of injury they have
... checks for the big accounts ... sportsbooks adding lines for the players or not"). Called at the end of
refresh_data.py (non-fatal) and runnable alone. Writes data/sim_injury_signals.js:

  window.SIM_INJ_SIGNALS = {
    week,                                   current NFL week (first week whose last kickoff + 6h is still ahead)
    body:  {norm: {b, n, g}}                Sleeper injury_body_part / injury_notes + the injury GROUP the backtests use
    prac:  {wk: {norm: {inj, g, gs, seq}}}  official practice report per week: injury text, group, game status and
                                            the day-by-day participation sequence ("DNP-LP-FP") from our own archive
    news:  {norm: {...}}                    availability read off the news feed: window {from, to, curve}, single-week
                                            out / play / doubt / gtd flags, each with its date + headline
  }

Persistent side files (sim_lab/data):
  practice_seq_2026.json    the day-by-day archive (nfl.com only shows the LATEST practice day; nflverse history keeps
                            only the final one) - backfilled once from the repo's git history of data/practice_2026.js
  lines_signal_log.jsonl    one row per change: which designated players have prop lines up, at how many books, with
                            the report status at that moment - graded by lines_signal_scorecard.py (pre-inactives rows)
"""
import datetime, json, os, re, subprocess, sys, unicodedata
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(os.path.dirname(HERE), "MyFantasyFootball Files")
DATA = os.path.join(HERE, "data")
SEQ_PATH = os.path.join(DATA, "practice_seq_2026.json")
LOG_PATH = os.path.join(DATA, "lines_signal_log.jsonl")
OUT_PATH = os.path.join(DATA, "sim_injury_signals.js")
SKILL = ("QB", "RB", "WR", "TE")
TEAMS = "ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LAC LAR LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS".split()

def norm(n):
    n = unicodedata.normalize("NFKD", str(n or "")).encode("ascii", "ignore").decode()
    n = n.lower().replace(".", "").replace("'", "").replace("-", " ")
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return re.sub(r"\s+", " ", n).strip()

# ---- injury groups: the SAME mapping as backtest_injury_type_play.py / backtest_avail_recency.py ----
GROUPS = [("hamstring", ("hamstring",)), ("ankle", ("ankle",)), ("knee", ("knee", "acl", "mcl", "meniscus", "pcl")), ("concussion", ("concussion", "head")),
          ("shoulder", ("shoulder", "collarbone", "clavicle", "ac joint")), ("groin", ("groin", "abductor", "adductor")), ("calf", ("calf",)), ("achilles", ("achilles",)),
          ("foot", ("foot", "heel", "lisfranc")), ("toe", ("toe",)), ("back", ("back", "lumbar")), ("hip", ("hip",)), ("quad", ("quad", "thigh")),
          ("core", ("rib", "chest", "oblique", "abdomen", "core", "pectoral", "sternum", "abdominal")), ("hand", ("hand", "wrist", "finger", "thumb", "forearm", "elbow")),
          ("neck", ("neck", "stinger")), ("illness", ("illness", "covid")), ("rest", ("not injury related", "rest", "personal", "coach"))]
def grp(inj):
    s = str(inj or "").lower()
    if not s or s in ("nan", "undisclosed"): return ""
    for g, keys in GROUPS:
        if any(k in s for k in keys): return g
    return "other"

# ---- calendar ----
def load_kicks():
    try: return json.load(open(os.path.join(DATA, "kickoffs_2026.json"), encoding="utf-8"))
    except Exception: return {}
def _dt(iso): return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
def current_week(kicks, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc); cur = 1
    for wk in range(1, 19):
        w = kicks.get(str(wk))
        if not w: continue
        cur = wk
        if now < max(_dt(v) for v in w.values()) + datetime.timedelta(hours=6): break
    return cur
def et_date(dt): return (dt.astimezone(datetime.timezone.utc) - datetime.timedelta(hours=4)).date()
def team_games(kicks, tm):
    """[(week, ET date of kickoff)] for a team, in order."""
    out = []
    for wk in range(1, 19):
        k = (kicks.get(str(wk)) or {}).get(tm)
        if k: out.append((wk, et_date(_dt(k))))
    return out

# ================= NEWS -> availability =================
NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "a couple": 2, "a few": 3, "several": 4}
_N = r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|a couple(?: of)?|a few|several)"
def _n(s):
    s = s.lower().replace(" of", "")
    return int(s) if s.isdigit() else NUM.get(s)
HEDGE = r"(could|may|might|fear\w*|possibl\w*|potential\w*|won'?t rule out|not rul\w+ out|hasn'?t ruled out|if |unless|avoid\w*|not |n't |no )"
RX_SEASON = re.compile(r"(out|done|lost|finished|sidelined|shut down) for (the )?(rest|remainder) of (the )?(2026 )?(regular )?(season|year)|(out|done|lost|finished) for the (2026 )?(season|year)|season[- ]ending|season (is )?over|miss(es)? the (rest|remainder) of the (2026 )?(regular )?season|\btorn (acl|achilles)\b|ruptured achilles|tore (his )?(acl|achilles)", re.I)
RX_RANGE = re.compile(_N + r"\s*(?:-|–|—|to)\s*" + _N + r"[- ]+(weeks?|games?)", re.I)
RX_ATLEAST = re.compile(r"(?:at least|a minimum of|minimum|miss(?:es|ing)?(?: the next)?|out(?: for)?(?: the next| about| roughly| around| approximately)?|sidelined(?: for)?(?: about| roughly)?|next)\s+" + _N + r"(?: more)?[- ]+(weeks?|games?)", re.I)
RX_TIMELINE_N = re.compile(_N + r"[- ]week (?:timeline|absence|recovery|timetable)", re.I)
RX_RET = re.compile(r"(?:out until|until at least|earliest (?:return )?(?:is |in )?|eligible (?:to return )?(?:in |for )?|expected back (?:in |by |for )?|targeting (?:a )?|return(?:s|ing)? (?:in |by |for )|back (?:in |by |for )|out through)\s*(?:at least )?week\s*(\d{1,2})", re.I)
RX_OUT = re.compile(r"ruled out|will not play|won'?t play|not playing|inactive (?:for|vs|tonight|sunday|monday|thursday)|ruled inactive|declared (?:out|inactive)|is out (?:for|vs)|out for (?:week \d+|sunday|monday|thursday|saturday|tonight)|will sit|downgraded to out", re.I)
RX_PLAY = re.compile(r"expect(?:s|ed)?(?: him)? to play|['\"]?expects['\"]? him to play|will play|is active\b|active and playing|officially active|cleared to (?:play|return)|good to go|no injury designation|carries no (?:injury )?designation|off the (?:final )?injury report|removed from the injury report|trending toward(?:s)? playing|on track to play|set to play|plans? to play|will suit up|returns? to (?:the )?(?:lineup|action)|will make (?:his )?(?:season |2026 )?debut|trending to make", re.I)
RX_DOUBT = re.compile(r"unlikely (?:to play|for|to suit up)|not expected to play|doubtful|long shot to play|trending toward(?:s)? (?:sitting|missing|not playing)|not counting on him", re.I)
RX_GTD = re.compile(r"game[- ]time decision|pre-?game decision|true (?:game[- ]time|pre-?game)", re.I)
RX_W2W = re.compile(r"week[- ]to[- ]week|day[- ]to[- ]day", re.I)
RX_EXIT = re.compile(r"\bexit(?:s|ed)?\b|\bleft\b|\bleaves\b|carted|rest of (?:the )?game|did not return|won'?t return|will not return|after just|ruled out early|re-?aggravat|in the (?:first|second|third|fourth) quarter|at halftime", re.I)
RX_WEEKNO = re.compile(r"week\s*(\d{1,2})", re.I)

OTHER = r"(after|following|with|for|replac\w+|fill\w* in for|in place of|back from|return\w* from|recover\w* from|removed from|since|behind|'s|’s)\s+[^,;:]*$"
def _hedged(text, m):
    pre = text[max(0, m.start() - 45):m.start()]
    return re.search(HEDGE + r"[^.;,]{0,30}$", pre, re.I) is not None
def _other(text, m):
    """the phrase describes someone else's injury or a past one ("after Dart's season-ending surgery", "back from torn ACL")"""
    pre = text[max(0, m.start() - 60):m.start()]
    return re.search(OTHER, pre, re.I) is not None

def parse_item(it):
    """-> {k: season|weeks|ret|out|play|doubt|gtd|w2w, lo, hi, wk} or None. The routine's own structured `avail`
    field wins when present. The fallback reads the HEADLINE only (the take is commentary and usually names other
    players) and skips hedged or second-hand phrases; the engine also requires the player's own designation to agree."""
    a = it.get("avail")
    if isinstance(a, dict) and a.get("k"):
        return {k: a[k] for k in ("k", "lo", "hi", "wk", "unit") if a.get(k) is not None}
    text = str(it.get("headline") or "")
    # timelines only need the hedge guard ("out for at least 4 weeks" has a 'for' in front of it); season-ending
    # and single-week phrases also need the someone-else guard, and any clean occurrence counts
    okh = lambda m: m and not _hedged(text, m)
    ok = lambda m: m and not _hedged(text, m) and not _other(text, m)
    if any(ok(m) for m in RX_SEASON.finditer(text)): return {"k": "season"}
    m = RX_RANGE.search(text)
    if okh(m):
        lo, hi = _n(m.group(1)), _n(m.group(2))
        if lo and hi and lo <= hi <= 16: return {"k": "weeks", "lo": lo, "hi": hi, "unit": m.group(3)[0].lower()}
    m = RX_RET.search(text)
    if okh(m) and 1 <= int(m.group(1)) <= 18:
        return {"k": "ret", "wk": int(m.group(1)) + (1 if "through" in m.group(0).lower() else 0)}
    m = RX_TIMELINE_N.search(text) or RX_ATLEAST.search(text)
    if okh(m):
        lo = _n(m.group(1))
        if lo and lo <= 16:
            return {"k": "weeks", "lo": lo, "hi": lo + 2, "unit": (m.group(2)[0].lower() if m.lastindex and m.lastindex >= 2 else "w")}
    w = RX_WEEKNO.search(text); wk = {"wk": int(w.group(1))} if w and 1 <= int(w.group(1)) <= 18 else {}
    if ok(RX_OUT.search(text)):
        if RX_EXIT.search(text): return {"k": "exit"}            # hurt DURING the game: he played that week
        return {"k": "out", **wk}
    if RX_DOUBT.search(text): return {"k": "doubt", **wk}
    if RX_GTD.search(text): return {"k": "gtd"}
    if ok(RX_PLAY.search(text)): return {"k": "play", **wk}
    if RX_W2W.search(text): return {"k": "w2w"}
    return None

def _next_game(games, d):
    """first (week, date) with kickoff date >= d"""
    for wk, gd in games:
        if gd >= d: return wk, gd
    return None, None

def played_weeks():
    """{norm: set(weeks with a 2026 game row)} from data/sim_2026.js"""
    try:
        raw = open(os.path.join(DATA, "sim_2026.js"), encoding="utf-8").read()
        d = json.loads(raw[raw.index("{", raw.index("window.SIM_2026")):].rstrip().rstrip(";"))["players"]
        return {n: set(v.get("wks") or []) for n, v in d.items()}
    except Exception:
        return {}

def news_state(items, kicks, cur, played=None):
    """Walk each player's items oldest -> newest and keep the standing availability read."""
    by = {}
    order = sorted(range(len(items)), key=lambda i: (str(items[i].get("date") or ""), -i))   # file is newest-first within a day
    for i in order:
        it = items[i]
        if it.get("pos") not in SKILL: continue
        st = parse_item(it)
        if not st: continue
        try: d = datetime.date.fromisoformat(str(it.get("date"))[:10])
        except Exception: continue
        games = team_games(kicks, it.get("team"))
        if not games: continue
        w0, g0 = _next_game(games, d)
        if w0 is None: continue
        if g0 == d and w0 in (played or {}).get(norm(it.get("player")), ()):
            # dated on a game day he played: the news is from that game (hurt in it), so the absence starts next game
            # and a single-week read ("ruled out", "expected to play") was about the game already played
            if st["k"] in ("out", "play", "doubt", "gtd") and not st.get("wk"): continue
            w0, g0 = _next_game(games, d + datetime.timedelta(days=1))
            if w0 is None: continue
        meta = {"date": str(d), "hl": str(it.get("headline") or "")[:110]}
        s = by.setdefault(norm(it.get("player")), {"name": it.get("player"), "tm": it.get("team"), "pos": it.get("pos"), "out": {}, "flag": {}})
        k = st["k"]; wk_named = st.get("wk")
        # an injury analyst's read ("fantasy doctors", src_type expert) never overrides the team's / an insider's:
        # his timeline only stands when there is no reported one, his single-week reads are chips, not inputs
        if it.get("src_type") == "expert":
            meta["x"] = 1
            if k in ("out", "play", "doubt", "gtd"):
                s.setdefault("expert", {})[str(wk_named or w0)] = dict(meta, k=k); continue
            if s.get("win") and not s["win"].get("x"): continue
        if k == "season":
            s["win"] = dict(meta, k="season", **{"from": w0, "to": 18})
        elif k in ("weeks", "ret"):
            if k == "ret":
                wr = max(w0, min(19, st["wk"])); to = wr - 1
                tail = [w for w, _ in games if w >= wr][:3]; curve = {str(w): p for w, p in zip(tail, (0.6, 0.8, 0.9))}
            else:
                lo, hi = st["lo"], st["hi"]
                if st.get("unit") == "g":
                    fut = [w for w, _ in games if w >= w0]
                    wlo = fut[lo] if lo < len(fut) else 19; whi = fut[hi] if hi < len(fut) else 19
                else:
                    wlo = _next_game(games, d + datetime.timedelta(days=7 * lo - 3))[0] or 19
                    whi = _next_game(games, d + datetime.timedelta(days=7 * hi - 3))[0] or 19
                to = wlo - 1
                # soft landing between the reported minimum and maximum: 50% at the first week he could be back,
                # 90% by the reported maximum, then back (the daily designation takes over long before that)
                span = [w for w, _ in games if wlo <= w <= max(whi, wlo)]
                curve = {}
                for j, w in enumerate(span[:6]):
                    curve[str(w)] = round(0.5 + 0.4 * (j / max(1, len(span) - 1)), 2) if len(span) > 1 else 0.6
                nxt = [w for w, _ in games if w > (span[-1] if span else wlo)]
                if span and len(span) == 1 and nxt: curve[str(nxt[0])] = 0.85
            if to >= w0: s["win"] = dict(meta, k=k, curve=curve, **{"from": w0, "to": min(18, to)})
        elif k == "out":
            s["out"][str(wk_named or w0)] = meta
        elif k in ("play", "doubt", "gtd"):
            wk = wk_named or w0
            s["flag"][str(wk)] = dict(meta, k=k)
            if k == "play":
                s["out"].pop(str(wk), None)
                if s.get("win") and s["win"]["k"] != "season" and wk >= s["win"]["from"]: s.pop("win", None)   # back ahead of the timeline
                elif s.get("win") and s["win"]["k"] == "season": s.pop("win", None)
        # w2w: no window - the designation logic + availability curve own it
    out = {}
    for n, s in by.items():
        rec = {"name": s["name"], "tm": s["tm"]}
        w = s.get("win")
        if w and (w["to"] >= cur or any(int(x) >= cur for x in (w.get("curve") or {}))): rec["win"] = w
        if str(cur) in s["out"]: rec["out"] = s["out"][str(cur)]
        if str(cur) in s["flag"]: rec["flag"] = s["flag"][str(cur)]
        if str(cur) in s.get("expert", {}): rec["expert"] = s["expert"][str(cur)]
        if len(rec) > 2: out[n] = rec
    return out

# ================= practice sequence archive =================
def _prac_day(updated_iso):
    """the practice day a snapshot reflects: reports post late afternoon ET, so a morning pull shows yesterday's"""
    dt = _dt(updated_iso) if "T" in updated_iso else datetime.datetime.fromisoformat(updated_iso)
    return str(et_date(dt - datetime.timedelta(hours=16)))

def _seq_merge(seq, payload):
    wk = payload.get("week"); up = payload.get("updated")
    if not wk or not up: return
    day = _prac_day(up); W = seq.setdefault(str(wk), {})
    for nm, v in (payload.get("players") or {}).items():
        if v.get("pos") not in SKILL: continue
        r = W.setdefault(norm(nm), {"name": nm, "tm": v.get("tm"), "pos": v.get("pos"), "inj": "", "gs": "", "days": {}})
        if v.get("pr"): r["days"][day] = v["pr"]
        if v.get("inj"): r["inj"] = v["inj"]
        r["gs"] = v.get("gs") or ""; r["tm"] = v.get("tm") or r["tm"]

def _git(*a):
    return subprocess.run(["git", "-C", REPO] + list(a), capture_output=True, text=True, encoding="utf-8", errors="replace").stdout

def backfill_practice(seq):
    """one-time: replay every committed data/practice_2026.js snapshot"""
    n = 0
    for h in reversed(_git("log", "--format=%H", "--", "data/practice_2026.js").split()):
        m = re.search(r"window\.PRACTICE_2026\s*=\s*(\{.*\});?\s*$", _git("show", f"{h}:data/practice_2026.js"), re.S)
        if not m: continue
        try: _seq_merge(seq, json.loads(m.group(1))); n += 1
        except Exception: pass
    return n

def practice_seq():
    seq = None
    try: seq = json.load(open(SEQ_PATH, encoding="utf-8"))
    except Exception: pass
    if seq is None:
        seq = {}; n = backfill_practice(seq); print(f"  practice sequence archive backfilled from {n} git snapshots")
    try: _seq_merge(seq, json.load(open(os.path.join(REPO, "data", "practice_2026.json"), encoding="utf-8")))
    except Exception as e: print(f"  WARN practice_2026.json unreadable ({e})")
    json.dump(seq, open(SEQ_PATH, "w", encoding="utf-8"), separators=(",", ":"))
    return seq

def seq_str(days):
    return "-".join(days[d] for d in sorted(days))

# ================= lines-up log =================
def books_up(props_wk):
    """{norm: [books with a yardage / reception line]}"""
    out = {}
    for nm, rec in (props_wk or {}).items():
        b = [bk for bk, v in rec.items() if isinstance(v, dict) and any(k in v for k in ("py", "ry", "rcy", "rec"))]
        if b: out[norm(nm)] = sorted(b)
    return out

def load_props():
    """weeklyProps from the copied betting file (a JS literal -> node, the engine's own reader)"""
    node = "node"
    for cand in (r"E:\node\node.exe",):
        if os.path.exists(cand): node = cand
    js = "global.window=global;require('vm').runInThisContext(require('fs').readFileSync(process.argv[1],'utf8'));process.stdout.write(JSON.stringify(window.BETTING_2026.weeklyProps||{}))"
    try:
        r = subprocess.run([node, "-e", js, os.path.join(DATA, "betting_lines_2026.js")], capture_output=True, text=True, encoding="utf-8", timeout=60)
        return json.loads(r.stdout)
    except Exception as e:
        print(f"  WARN weekly props unreadable ({e})"); return {}

def log_lines(cur, seq, body, props, kicks, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    up = books_up(props.get(str(cur))); usual = set()
    for w, o in props.items():
        if w != str(cur): usual |= set(books_up(o))
    last = {}
    if os.path.exists(LOG_PATH):
        for line in open(LOG_PATH, encoding="utf-8"):
            try: r = json.loads(line)
            except Exception: continue
            if r.get("wk") == cur: last[r["n"]] = r
    rows = []; W = seq.get(str(cur), {})
    names = set(W) | {n for n, b in body.items() if b.get("s") in ("Questionable", "Doubtful", "Out")}
    for n in sorted(names):
        p = W.get(n, {}); b = body.get(n, {})
        tm = p.get("tm") or b.get("tm")
        if not tm: continue
        days = p.get("days") or {}
        rec = {"ts": now.strftime("%Y-%m-%dT%H:%MZ"), "wk": cur, "n": n, "name": p.get("name") or b.get("name"), "pos": p.get("pos") or b.get("pos"), "tm": tm,
               "gs": p.get("gs", ""), "pr": (days[max(days)] if days else ""), "seq": seq_str(days), "sl": b.get("s", ""), "g": grp(p.get("inj")) or b.get("g", ""),
               "books": up.get(n, []), "usual": n in usual, "ko": (kicks.get(str(cur)) or {}).get(tm)}
        if rec["ko"] and now > _dt(rec["ko"]): continue                        # his game has started - the pre-game state is final
        prev = last.get(n)
        if prev and all(prev.get(k) == rec[k] for k in ("gs", "pr", "sl", "books", "seq")): continue
        rows.append(rec)
    if rows:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            for r in rows: f.write(json.dumps(r, separators=(",", ":")) + "\n")
    return len(rows)

# ================= pre-injury depth-chart spot =================
CHART_CACHE = os.path.join(DATA, "chart_pre_2026.json")
OUT_STATUS = {"IR", "PUP", "Out", "Doubtful", "NA", "Sus", "NFI", "DNR", "COV"}
TEAM_ALIAS = {"WSH": "WAS", "JAC": "JAX", "ARZ": "ARI", "LA": "LAR"}

def chart_pre(body, news, kicks, played):
    """{norm: {tm, pos, i, wk}} - where each player who is out NOW sat on his team's depth chart going into the last
    game he played (list index on the ESPN chart, from the repo's git history of data/depth_charts_2026.js). ESPN
    drops a player down or off the chart while he is out; the Clay-free model reads that as a demotion and docks
    him after his return. Players who have not played this season are not here (the engine ranks them by ADP)."""
    try: cache = json.load(open(CHART_CACHE, encoding="utf-8"))
    except Exception: cache = {}
    cands = {n for n, b in body.items() if b.get("s") in OUT_STATUS} | {n for n, v in news.items() if v.get("win") or v.get("out")}
    commits = None; shown = {}; out = {}; dirty = False
    for n in sorted(cands):
        tm = (body.get(n) or news.get(n) or {}).get("tm"); wks = played.get(n) or set()
        if not tm or not wks: continue
        tm = TEAM_ALIAS.get(tm, tm); last = max(wks); key = f"{n}|{tm}|{last}"
        if key in cache:
            if cache[key]: out[n] = cache[key]
            continue
        ko = (kicks.get(str(last)) or {}).get(tm)
        if not ko: continue
        if commits is None:
            commits = [l.split(" ", 1) for l in _git("log", "--reverse", "--format=%H %aI", "--", "data/depth_charts_2026.js").strip().splitlines()]
            commits = [(h, datetime.datetime.fromisoformat(t)) for h, t in commits]
        prior = [h for h, t in commits if t <= _dt(ko)]
        if not prior: continue
        h = prior[-1]
        if h not in shown:
            m = re.search(r"window\.DEPTH_2026\s*=\s*(\{.*\});?\s*$", _git("show", f"{h}:data/depth_charts_2026.js"), re.S)
            try: shown[h] = json.loads(m.group(1)).get("teams", {}) if m else {}
            except Exception: shown[h] = {}
        rec = None
        for ctm, byp in shown[h].items():
            if TEAM_ALIAS.get(ctm, ctm) != tm: continue
            for pos, lst in byp.items():
                for i, nm in enumerate(lst or []):
                    if norm(nm) == n: rec = {"tm": tm, "pos": pos, "i": i, "wk": last}
        cache[key] = rec; dirty = True
        if rec: out[n] = rec
    if dirty: json.dump(cache, open(CHART_CACHE, "w", encoding="utf-8"), separators=(",", ":"))
    return out

# ================= last season's team (quarterbacks who changed teams) =================
def prev_teams():
    """{norm: team in his last 2025 regular-season game} for quarterbacks, from the nflverse 2025 snap counts (the
    site's weekly stats carry the CURRENT team on old rows, so they cannot say who moved). The Clay-free model docks
    a quarterback who changed teams (backtest_shadow_next.py). Cached - 2025 does not change."""
    cp = os.path.join(DATA, "prev_team_2025.json")
    try: return json.load(open(cp, encoding="utf-8"))
    except Exception: pass
    out = {}
    try:
        import pandas as pd
        d = pd.read_parquet(r"E:\MyFantasyFootball\pbp_cache\snap_counts_2025.parquet", columns=["week", "game_type", "player", "position", "team", "offense_snaps"])
        d = d[(d.game_type == "REG") & (d.position == "QB") & (d.offense_snaps > 0)].sort_values("week")
        al = {"LA": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI", "OAK": "LV", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
        for r in d.itertuples(index=False): out[norm(r.player)] = al.get(r.team, r.team)
        json.dump(out, open(cp, "w", encoding="utf-8"), separators=(",", ":"))
    except Exception as e:
        print(f"  WARN last season's teams unreadable ({e})")
    return out

# ================= build =================
def build(allp=None, now=None):
    kicks = load_kicks(); cur = current_week(kicks, now)
    # --- Sleeper diagnosis (body part + notes) ---
    if allp is None:
        import urllib.request
        req = urllib.request.Request("https://api.sleeper.app/v1/players/nfl", headers={"User-Agent": "simlab-refresh"})
        with urllib.request.urlopen(req, timeout=60) as r: allp = json.load(r)
    body = {}
    for sid, p in allp.items():
        if not isinstance(p, dict) or p.get("position") not in SKILL or not p.get("team"): continue
        if not (p.get("injury_status") or p.get("injury_body_part")): continue
        nm = (p.get("first_name") or "") + " " + (p.get("last_name") or ""); n = norm(nm)
        if n in body and not p.get("injury_status"): continue
        bp = p.get("injury_body_part") or ""
        body[n] = {"name": nm.strip(), "tm": p.get("team"), "pos": p.get("position"), "b": bp, "n": p.get("injury_notes") or "", "g": grp(bp), "s": p.get("injury_status") or ""}
    # --- practice sequence ---
    seq = practice_seq()
    prac = {}
    for wk, W in seq.items():
        if int(wk) > cur: continue
        prac[wk] = {n: {"inj": r.get("inj", ""), "g": grp(r.get("inj")), "gs": r.get("gs", ""), "seq": seq_str(r.get("days") or {})} for n, r in W.items()}
    # --- news ---
    news = {}
    try:
        items = json.load(open(os.path.join(REPO, "data", "camp_news_2026.json"), encoding="utf-8")).get("items", [])
        news = news_state(items, kicks, cur, played_weeks())
    except Exception as e:
        print(f"  WARN news feed unreadable ({e})")
    # --- pre-injury depth-chart spot for players who are out now ---
    cpre = {}
    try: cpre = chart_pre(body, news, kicks, played_weeks())
    except Exception as e: print(f"  WARN pre-injury chart spots skipped ({e})")
    # --- lines log ---
    nlog = 0
    try: nlog = log_lines(cur, seq, body, load_props(), kicks, now)
    except Exception as e: print(f"  WARN lines log skipped ({e})")
    payload = {"updated": (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%MZ"), "week": cur,
               "body": {n: {"b": v["b"], "n": v["n"], "g": v["g"]} for n, v in body.items()}, "prac": prac, "news": news, "chartPre": cpre, "prevTm": prev_teams()}
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("// AUTO-GENERATED by build_injury_signals.py - Sleeper diagnosis, practice sequence archive, news availability\n")
        f.write("window.SIM_INJ_SIGNALS = "); json.dump(payload, f, separators=(",", ":"), ensure_ascii=False); f.write(";\n")
    nw = sum(1 for v in news.values() if v.get("win")); no = sum(1 for v in news.values() if v.get("out")); nf = sum(1 for v in news.values() if v.get("flag"))
    print(f"wrapped sim_injury_signals.js  (week {cur}: {len(body)} diagnoses, {len(prac.get(str(cur), {}))} on the practice report, news: {nw} timelines / {no} ruled out / {nf} play-or-doubt flags, {nlog} lines-log rows, {len(cpre)} pre-injury chart spots)")
    return payload

if __name__ == "__main__":
    p = build()
    if "--show" in sys.argv:
        for n, v in sorted(p["news"].items()):
            w = v.get("win")
            print(f"  {v['name']:22s} {v['tm']:4s}", (f"{w['k']} wk{w['from']}-{w['to']} curve {w.get('curve')} [{w['date']}] {w['hl']}" if w else ""),
                  ("| OUT: " + v["out"]["hl"] if v.get("out") else ""), ("| " + v["flag"]["k"].upper() + ": " + v["flag"]["hl"] if v.get("flag") else ""))
