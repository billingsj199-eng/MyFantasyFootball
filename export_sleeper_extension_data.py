"""Build slim players.json for the Sleeper draft extension.

Sources:
  data/d.js                  — Jack's rankings (order = rank), team, age, p25, fpR, slR
  data/_bundle_lookups.js    — KTC_SF / KTC_1QB dynasty values (name -> value)
  sleeper_nfl.json           — Sleeper players dump (player_id mapping)

Output: sleeper-extension/data/players.json
Run after every rankings/KTC refresh: python export_sleeper_extension_data.py
"""
import json, re, os, time, urllib.request, datetime as _dt

OUT_PATH = "sleeper-extension/data/players.json"
D_JS = "data/d.js"
BUNDLE_JS = "data/_bundle_lookups.js"
SLEEPER_JSON = "sleeper_nfl.json"
# Jack's live per-mode boards (superflex/dynasty/dynastysf) — public-read Firestore doc
FIRESTORE_URL = (
    "https://firestore.googleapis.com/v1/projects/jackb933-website/databases/(default)"
    "/documents/rankings/jacks-official?key=AIzaSyD9D_Rhb5hEpz2cBWqQr7hcFCDoluwq6uY"
)
KEEP_KEYS = ("n", "s", "t", "age", "bye", "p25",
             "fpR", "fpSf", "fpDy", "fpDsf", "slR", "slSf", "slDy", "slDsf",
             "a", "sfa", "da", "sa")  # mode-aware ADPs: redraft/superflex/dynasty/dynastysf
POSITIONS = {"QB", "RB", "WR", "TE", "K", "DST"}
SLEEPER_POSITIONS = {"QB", "RB", "WR", "TE", "K"}  # DST maps by team abbr instead


def norm(n):
    s = (n or "").lower().strip()
    for suf in [" jr.", " jr", " sr.", " sr", " iii", " ii", " iv", " v"]:
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
    s = s.replace("'", "").replace("`", "").replace("’", "")
    s = s.replace(".", "").replace(",", "").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


ALIASES = {
    "kenneth walker iii": "kenneth walker",
    "ken walker iii": "kenneth walker",
    "cam ward": "cameron ward",
    "cameron ward": "cam ward",
    "chig okonkwo": "chigoziem okonkwo",
    "chigoziem okonkwo": "chig okonkwo",
    "marquise brown": "hollywood brown",
    "hollywood brown": "marquise brown",
    "joshua palmer": "josh palmer",
    "josh palmer": "joshua palmer",
    "dj moore": "d j moore",
    "d j moore": "dj moore",
    "kenneth gainwell": "kenny gainwell",
    "kenny gainwell": "kenneth gainwell",
}


def lookup_with_aliases(name_norm, lookup_map):
    if name_norm in lookup_map:
        return lookup_map[name_norm]
    alias = ALIASES.get(name_norm)
    if alias and alias in lookup_map:
        return lookup_map[alias]
    return None


def walk_d_array(src):
    m = re.search(r"\bD\s*=\s*\[", src)
    if not m:
        raise RuntimeError("Could not locate D=[ start")
    i = m.end()
    depth = 0
    in_str = False
    str_ch = ""
    esc = False
    obj_start = None
    while i < len(src):
        c = src[i]
        if esc:
            esc = False
            i += 1
            continue
        if in_str:
            if c == "\\":
                esc = True
            elif c == str_ch:
                in_str = False
            i += 1
            continue
        if c in ('"', "'"):
            in_str = True
            str_ch = c
            i += 1
            continue
        if c == "{":
            if depth == 0:
                obj_start = i
            depth += 1
            i += 1
            continue
        if c == "}":
            depth -= 1
            if depth == 0 and obj_start is not None:
                yield (obj_start, i + 1)
                obj_start = None
            i += 1
            continue
        if c == "]" and depth == 0:
            break
        i += 1


def parse_entry(body):
    out = {}
    for k in KEEP_KEYS:
        pat = '"' + k + r'"\s*:\s*("([^"]*)"|null|([\-\d.]+))'
        m = re.search(pat, body)
        if not m:
            continue
        if m.group(2) is not None:
            out[k] = m.group(2)
        elif m.group(3) is not None:
            try:
                v = float(m.group(3))
                out[k] = int(v) if v == int(v) else v
            except ValueError:
                out[k] = m.group(3)
    return out


def extract_js_object(src, var_name):
    """Brace-match `var NAME={...}` out of a JS bundle and json.loads it."""
    m = re.search(r"\bvar\s+" + var_name + r"\s*=\s*\{", src)
    if not m:
        return {}
    start = m.end() - 1
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(src)):
        c = src[i]
        if esc:
            esc = False
            continue
        if in_str:
            if c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(src[start : i + 1])
    return {}


def load_ktc():
    src = open(BUNDLE_JS, encoding="utf-8").read()
    sf = extract_js_object(src, "KTC_SF")
    oneqb = extract_js_object(src, "KTC_1QB")
    sf_n = {norm(k): v for k, v in sf.items()}
    oneqb_n = {norm(k): v for k, v in oneqb.items()}
    # Rookie-pick assets ("2027 Early 1st") ride along for startup drafts
    # that include picks. Keyed by raw KTC label.
    picks = {k: {"sf": v, "oneqb": oneqb.get(k)} for k, v in sf.items() if re.match(r"^\d{4}\s", k)}
    return sf_n, oneqb_n, picks


def load_clay_projections():
    """Parse every numeric field per Clay entry. Clay's `pts` is FULL PPR with
    4-pt passing TDs; we also keep gm/rec/ptd components so the extension can
    re-score to the league's actual scoring_settings client-side."""
    out = {}
    path = "data/mike_clay_projections.js"
    if not os.path.exists(path):
        return out
    src = open(path, encoding="utf-8").read()
    pattern = re.compile(r'"([^"]+)":\s*\{([^}]*)\}')
    for m in pattern.finditer(src):
        body = m.group(2)
        if "pos:" not in body or "pts:" not in body:
            continue
        fields = dict(re.findall(r"(\w+):(-?[\d.]+)", body))
        gm = int(float(fields.get("gm", 0)))
        pts = float(fields.get("pts", 0))
        rec = float(fields.get("rec", 0))
        ptd = float(fields.get("ptd", 0))
        if gm <= 0:
            continue
        half_ppr = pts - 0.5 * rec
        rec_out = {
            "ppg": round(half_ppr / gm, 1),
            "szn": round(half_ppr, 1),
            "gm": gm, "pts": pts, "rec": rec, "ptd": ptd,
        }
        # Kicker volume components (fgm/fga/xpm/xpa) — the extension re-scores
        # them with the league's real kicker rules (distance buckets, miss
        # penalties) and scales the volumes by the week's Vegas implied total.
        for f in ("fgm", "fga", "xpm", "xpa"):
            if f in fields:
                rec_out[f] = float(fields[f])
        out[norm(m.group(1))] = rec_out
    return out


def load_kicker_splits():
    """norm-name -> FG makes-share per distance bucket [1-19,20-29,30-39,
    40-49,50+] from data/kicker_splits.js (ESPN actuals via
    scripts/pull_kicker_splits.py). Captures tendencies like Brandon Aubrey's
    league-high 50+ attempt rate for leagues with distance bonuses."""
    path = "data/kicker_splits.js"
    out = {}
    if not os.path.exists(path):
        return out
    src = open(path, encoding="utf-8").read()
    m = re.search(r"window\.KICKER_SPLITS\s*=\s*(\{.*\});", src, re.S)
    if not m:
        return out
    for name, rec in json.loads(m.group(1)).items():
        fgm = rec.get("fgm") or []
        total = sum(fgm)
        if len(fgm) == 5 and total >= 8:
            out[norm(name)] = [round(v / total, 3) for v in fgm]
    return out


def load_byes():
    """team abbr -> bye week, derived from the betting-lines schedule
    (data/betting_lines_2026.json gameTotals keys W{wk}_{AWAY}_{HOME}).
    A team's bye is the one week of 1-17 it never appears in; only trusted
    when 8+ weeks are mapped so a sparse pull can't invent byes. Baking this
    into players.json keeps byes working when the extensions' live
    betting-lines fetch fails, and fills the player-profile Bye row."""
    path = "data/betting_lines_2026.json"
    out = {}
    if not os.path.exists(path):
        return out
    gt = json.load(open(path, encoding="utf-8")).get("gameTotals") or {}
    weeks = {}
    for key in gt:
        m = re.match(r"W(\d+)_([A-Z]{2,3})_([A-Z]{2,3})$", key)
        if not m:
            continue
        wk = int(m.group(1))
        if not 1 <= wk <= 17:
            continue
        for t in (m.group(2), m.group(3)):
            weeks.setdefault(t, set()).add(wk)
    for t, ws in weeks.items():
        missing = set(range(1, 18)) - ws
        if len(ws) >= 8 and len(missing) == 1:
            out[t] = missing.pop()
    return out


def load_jm_scores():
    """norm-name -> JM prospect-model record from data/jm_scores.json
    (dumped off the live site by scripts/pull_jm_scores.py — the model only
    runs in-browser). Keeps score, class year, and the site's own
    position-specific tier label/color for the sidebar pill."""
    path = "data/jm_scores.json"
    if not os.path.exists(path):
        return {}
    scores = json.load(open(path, encoding="utf-8")).get("scores") or {}
    return {norm(k): v for k, v in scores.items()}


def load_team_grades():
    """abbr -> Clay composite defense RANK (1=best) from clay_team_grades_2026.js.
    The composite defGr value's scale is ambiguous (lower appears better,
    contradicting the 1-10 unit scale), so bake the explicit rank instead."""
    path = "data/clay_team_grades_2026.js"
    out = {}
    if not os.path.exists(path):
        return out
    src = open(path, encoding="utf-8").read()
    for m in re.finditer(r"'([A-Z]{2,4})':\s*\{([^}]*)\}", src):
        fields = dict(re.findall(r"(\w+):(-?[\d.]+)", m.group(2)))
        if "defRk" in fields:
            out[m.group(1)] = int(float(fields["defRk"]))
    return out


# ---- OUT FOR SEASON (IR) ----------------------------------------------
# Jack's admin card toggle flags a player out for the season. It deliberately
# KEEPS the board slot (so clearing the flag restores their exact spot), and
# writes a separate top-level `ir` field on rankings/jacks-official as
# {"Player Name": seasonYear} — NOT inside the rankings data blob. So a
# flagged player looks completely normal in _order, and any exporter reading
# only _order keeps shipping him (the 2026-08-05 "I removed Pearsall but the
# extension still shows him" report).
#
# Mirrors app.js: IR_SEASON rolls over March 1, and the flag hides a player
# from redraft / bestball / superflex / weekly ONLY — dynasty keeps him.
_d = _dt.date.today()
IR_SEASON = _d.year if _d.month >= 3 else _d.year - 1
IR_OUT = set()


def load_ir_map(doc):
    """norm-names flagged out for the CURRENT season (older years ignored)."""
    IR_OUT.clear()
    try:
        raw = doc["fields"].get("ir", {}).get("stringValue")
        if not raw:
            return
        for name, season in (json.loads(raw) or {}).items():
            if season == IR_SEASON:
                IR_OUT.add(norm(name))
        if IR_OUT:
            print(f"IR out for {IR_SEASON}: {len(IR_OUT)} -> " + ", ".join(sorted(IR_OUT)))
    except Exception as e:
        print("WARN: could not read IR flags:", e)


def extract_board_tiers(mode_obj):
    """Jack's ALL-board tier boundaries for one mode -> [{a, l, n}, ...].

    A tier applies from rank `a` (afterRank, 1-based, inclusive) until the next
    tier's boundary — same semantics as the site's _tierLabelForRank. Sorted
    ascending so clients can walk the list with a simple "last a <= rank" scan.
    """
    tiers = ((mode_obj or {}).get("_posTiers") or {}).get("ALL") or []
    out = []
    for t in tiers:
        a = t.get("afterRank")
        l = t.get("label")
        if isinstance(a, (int, float)) and a >= 1 and l:
            out.append({"a": int(a), "l": str(l), "n": str(t.get("name") or "")})
    out.sort(key=lambda t: t["a"])
    return out


def load_jacks_boards():
    """name-norm -> rank for Jack's live boards, plus his tier boundaries.

    "jR" (redraft) is the source of the `rank` field — i.e. what the extensions
    label "Jack's Rank". It MUST come from here and not from d.js array order:
    d.js order is a separate, hand-maintained sequence that drifts badly from
    the live board (measured 2026-08-05: 250 of 552 players 15+ spots apart,
    Tyler Bass #415 in d.js vs #613 on the board), so board edits — including
    removing a player outright — never reached any extension.

    Returns (boards, tiers): tiers is keyed by the FIELD NAME the extensions
    read the rank from ("rank" for redraft, else jSf/jDy/jDsf) so the sidebar
    can map any rank value to its tier without knowing mode->key wiring.
    """
    out = {"jR": {}, "jSf": {}, "jDy": {}, "jDsf": {}}
    tiers = {}
    try:
        with urllib.request.urlopen(FIRESTORE_URL, timeout=20) as r:
            doc = json.load(r)
        load_ir_map(doc)
        payload = json.loads(doc["fields"]["data"]["stringValue"])
        jacks = payload.get("jacks", {})
        for mode, key in [("redraft", "jR"), ("superflex", "jSf"),
                          ("dynasty", "jDy"), ("dynastysf", "jDsf")]:
            order = (jacks.get(mode) or {}).get("_order") or []
            for i, name in enumerate(order):
                out[key][norm(name)] = i + 1
            tiers["rank" if key == "jR" else key] = extract_board_tiers(jacks.get(mode))
        print("Jacks boards:", {k: len(v) for k, v in out.items()},
              " tiers:", {k: len(v) for k, v in tiers.items()},
              " updated:", doc["fields"].get("updatedAt", {}).get("stringValue", "?"))
    except Exception as e:
        print("WARN: could not fetch Jack's live boards:", e)
    return out, tiers


def load_sleeper_ids():
    """norm-name -> list of candidate sleeper records (id, pos, team, status)."""
    d = json.load(open(SLEEPER_JSON, encoding="utf-8"))
    out = {}
    for pid, rec in d.items():
        if not isinstance(rec, dict):
            continue
        pos = rec.get("position")
        if pos not in SLEEPER_POSITIONS:
            continue
        name = rec.get("full_name") or ((rec.get("first_name") or "") + " " + (rec.get("last_name") or ""))
        nk = norm(name)
        if not nk:
            continue
        out.setdefault(nk, []).append(
            {"id": pid, "pos": pos, "team": rec.get("team"), "status": rec.get("status")}
        )
    return out


def pick_sleeper_id(nk, pos, sleeper_map):
    cands = lookup_with_aliases(nk, sleeper_map)
    if not cands:
        return None
    same_pos = [c for c in cands if c["pos"] == pos]
    pool = same_pos or cands
    # Prefer active players on a roster; the dump is full of retired dupes.
    pool.sort(key=lambda c: ((c.get("team") is None), (c.get("status") != "Active")))
    return pool[0]


TEAM_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


def write_sim_pack():
    """Bundle the season-sim engine + its data into the extension (v0.14.0
    PICKS tab). Three parts, all local-only (extension dirs never reach the
    public repo — .git/info/exclude whitelist):

      data/sim_pack.js      — verbatim concat of mike_clay_projections.js +
                              player_weekly_sigma.js + clay_team_grades_2026.js
                              (each already declares the global the engine
                              expects: MIKE_CLAY_PROJ / PLAYER_WEEKLY_SIGMA /
                              window.CLAY_TEAM_GRADES_2026)
      engine_sim.js         — verbatim copy of ../sim_lab/engine.js (source of
                              truth stays sim_lab; this copy step prevents drift)
      data/sim_overrides.js — verbatim copy of ../sim_lab/overrides.js
                              (QB room / injury-window camp-news overrides)
    """
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    pack_srcs = [
        "data/mike_clay_projections.js",
        "data/player_weekly_sigma.js",
        "data/clay_team_grades_2026.js",
    ]
    missing = [p for p in pack_srcs if not os.path.exists(p)]
    if missing:
        print("WARN: sim_pack skipped, missing:", missing)
    else:
        parts = ["// sim_pack.js — GENERATED by export_sleeper_extension_data.py "
                 + stamp + "\n// Data bundle for the season-sim PICKS tab. Do not edit.\n"]
        for p in pack_srcs:
            parts.append("\n// ---- " + p + " ----\n")
            parts.append(open(p, encoding="utf-8").read())
        for pack_dst in ("sleeper-extension/data/sim_pack.js",
                         "espn-extension/data/sim_pack.js"):
            if os.path.isdir(os.path.dirname(pack_dst)):
                with open(pack_dst, "w", encoding="utf-8") as f:
                    f.write("".join(parts))
                print("Wrote", pack_dst)

    import shutil
    for src, dst in [("../sim_lab/engine.js", "sleeper-extension/engine_sim.js"),
                     ("../sim_lab/overrides.js", "sleeper-extension/data/sim_overrides.js"),
                     ("../sim_lab/engine.js", "espn-extension/engine_sim.js"),
                     ("../sim_lab/overrides.js", "espn-extension/data/sim_overrides.js")]:
        if os.path.exists(src):
            header = ("// COPY of " + src + " (synced " + stamp
                      + " by export_sleeper_extension_data.py — edit the sim_lab original)\n")
            with open(src, encoding="utf-8") as fi, open(dst, "w", encoding="utf-8") as fo:
                fo.write(header + fi.read())
            print("Synced", src, "->", dst)
        else:
            print("WARN: missing", src, "- sim engine copy skipped")


def main():
    # Reuse the Underdog export's Clay-projection loader + VOR/handcuff engine
    import export_extension_data as ud

    src = open(D_JS, encoding="utf-8").read()
    ktc_sf, ktc_1qb, pick_assets = load_ktc()
    sleeper_map = load_sleeper_ids()
    jacks_boards, jacks_tiers = load_jacks_boards()
    clay = load_clay_projections()
    team_grades = load_team_grades()
    kicker_splits = load_kicker_splits()
    byes = load_byes()
    jm_scores = load_jm_scores()
    sigma = ud.load_player_sigma()
    print("Clay projections:", len(clay), " def grades:", len(team_grades),
          " kicker splits:", len(kicker_splits), " team byes:", len(byes))
    print("KTC SF:", len(ktc_sf), " KTC 1QB:", len(ktc_1qb), " Sleeper names:", len(sleeper_map))

    players = []
    rank_counter = 0
    sid_matched = 0
    ktc_matched = 0
    dropped = []
    for s, e in walk_d_array(src):
        entry = parse_entry(src[s:e])
        if not entry.get("n"):
            continue
        pos = entry.get("s")
        if pos not in POSITIONS:
            continue
        nk = norm(entry["n"])
        # `rank` — what the extensions show as "Jack's Rank" — is his position
        # on the LIVE redraft board, NOT the d.js array index. A player he took
        # off the board is simply absent here, so he drops out of the export:
        # that removal reaching the extensions is the whole point.
        jr = lookup_with_aliases(nk, jacks_boards["jR"])
        if jr is None:
            if jacks_boards["jR"]:
                dropped.append(entry["n"])
                continue
            rank_counter += 1   # board fetch failed — fall back to d.js order
            jr = rank_counter
        entry["rank"] = jr
        # Flag rather than drop: the sidebar hides `ir` players in the redraft
        # and superflex modes but keeps them in dynasty, matching the site's
        # _IR_HIDDEN_MODES. Dropping here would wrongly hide them everywhere.
        if nk in IR_OUT:
            entry["ir"] = 1
        if pos == "DST":
            # Sleeper DEF player_id IS the team abbreviation ("HOU").
            abbr = TEAM_ABBR.get(entry.get("t") or entry["n"].replace(" D/ST", ""))
            if abbr:
                entry["sid"] = abbr
                entry["sTm"] = abbr
                sid_matched += 1
                # Clay composite defense rank (1=best) → weekly DST baseline
                if abbr in team_grades:
                    entry["dRk"] = team_grades[abbr]
            entry.pop("t", None)
            players.append(entry)
            continue
        for key, board in jacks_boards.items():
            if key == "jR":
                continue  # already emitted as `rank` — don't ship it twice
            v = lookup_with_aliases(nk, board)
            if v is not None:
                entry[key] = v
        clay_rec = lookup_with_aliases(nk, clay)
        if clay_rec is not None:
            entry["pPg"] = clay_rec["ppg"]
            entry["szn"] = clay_rec["szn"]
            # components for client-side league-scoring adjustment
            entry["cGm"] = clay_rec["gm"]
            entry["cPts"] = clay_rec["pts"]
            if clay_rec["rec"]:
                entry["cRec"] = clay_rec["rec"]
            if clay_rec["ptd"]:
                entry["cPtd"] = clay_rec["ptd"]
            if pos == "K" and clay_rec.get("fga"):
                # season FG/XP volumes → the extension models kicker points
                # from the league's real kicker scoring + Vegas totals
                for f in ("fgm", "fga", "xpm", "xpa"):
                    if clay_rec.get(f):
                        entry["k" + f.capitalize()] = clay_rec[f]
                kd = kicker_splits.get(nk)
                if kd:
                    entry["kD"] = kd  # FG makes share per distance bucket
        jm_rec = lookup_with_aliases(nk, jm_scores)
        if jm_rec and jm_rec.get("jm") is not None and not jm_rec.get("lc"):
            # Same-name devy/NFL collisions exist in the dump (last-wins, matching
            # the site); only attach when the position agrees to avoid mislabeling.
            if not jm_rec.get("pos") or jm_rec["pos"] == pos:
                entry["jmS"] = jm_rec["jm"]
                if jm_rec.get("yr"):
                    entry["jmC"] = jm_rec["yr"]
                if jm_rec.get("tier"):
                    entry["jmT"] = jm_rec["tier"]
                if jm_rec.get("col"):
                    entry["jmCol"] = jm_rec["col"]
        v_sf = lookup_with_aliases(nk, ktc_sf)
        v_1qb = lookup_with_aliases(nk, ktc_1qb)
        if v_sf is not None:
            entry["ktcSf"] = v_sf
            ktc_matched += 1
        if v_1qb is not None:
            entry["ktc1qb"] = v_1qb
        srec = pick_sleeper_id(nk, pos, sleeper_map)
        if srec:
            entry["sid"] = srec["id"]
            if srec.get("team"):
                entry["sTm"] = srec["team"]
            sid_matched += 1
        # d.js team wins when it maps cleanly — Jack applies offseason moves
        # there before the sleeper dump refreshes. Keep "t" until after
        # assign_vor (the handcuff model groups by full team name).
        if entry.get("t") in TEAM_ABBR:
            entry["sTm"] = TEAM_ABBR[entry["t"]]
        players.append(entry)

    # d.js carries no bye field, so fill it from the Vegas-schedule map
    # (sTm is set for both skill players and DSTs by this point).
    for p in players:
        if p.get("bye") is None and byes.get(p.get("sTm")):
            p["bye"] = byes[p["sTm"]]

    # VOR / upside under both standard and superflex replacement levels
    ud.assign_vor(players, sigma)
    for p in players:
        p.pop("t", None)
        p.pop("hcPpg", None)  # helper only; cPpg (ceiling) stays

    picks_out = []
    for label, vals in sorted(pick_assets.items(), key=lambda kv: -(kv[1]["sf"] or 0)):
        picks_out.append({"n": label, "s": "PICK", "ktcSf": vals["sf"], "ktc1qb": vals["oneqb"]})

    jm_matched = sum(1 for p in players if "jmS" in p)
    print(f"Players: {len(players)}  sleeper-id matched: {sid_matched}  KTC-SF matched: {ktc_matched}  JM matched: {jm_matched}")
    # Never drop silently — a player vanishing from the extensions should be a
    # deliberate board edit, and if it isn't, this line is how you spot it.
    if dropped:
        print(f"DROPPED {len(dropped)} not on Jack's live redraft board: "
              + ", ".join(dropped[:15]) + (" ..." if len(dropped) > 15 else ""))
    unmatched = [p["n"] for p in players[:200] if "sid" not in p]
    if unmatched:
        print("Top-200 players missing sleeper id:", unmatched)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "version": 1,
                "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "players": players,
                "pickAssets": picks_out,
                # Jack's tier boundaries per rank field ("rank"/jSf/jDy/jDsf):
                # sorted [{a, l, n}], tier = last entry with a <= rank.
                "tiers": jacks_tiers,
            },
            f,
            ensure_ascii=False,
            indent=1,
        )
    print("Wrote", len(players), "players +", len(picks_out), "pick assets ->", OUT_PATH)
    # The ESPN and Yahoo helpers share this data file (name-matched; the
    # sleeper sids also bridge injuries/actuals/trending there) — keep their
    # copies in sync on every export.
    import shutil
    for copy_path in ("espn-extension/data/players.json",
                      "yahoo-extension/data/players.json"):
        if os.path.isdir(os.path.dirname(copy_path)):
            shutil.copyfile(OUT_PATH, copy_path)
            print("Synced copy ->", copy_path)
    write_sim_pack()


if __name__ == "__main__":
    main()
