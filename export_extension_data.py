"""Build slim players.json for the Underdog extension."""
import json, re, os, csv, time

OUT_PATH = "underdog-extension/data/players.json"
UD_CSV = "Site Rankings/UnderdogADP.csv"
CLAY_JS = "data/mike_clay_projections.js"
SIGMA_JS = "data/player_weekly_sigma.js"
KEEP_KEYS = ("n", "s", "t", "udA", "age", "bye", "p25", "p24", "p23", "fpR", "slR")
DROP_POS = {"K", "DST"}


def norm(n):
    s = (n or "").lower().strip()
    for suf in [" jr.", " jr", " sr.", " sr", " iii", " ii", " iv", " v"]:
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
    s = s.replace("'", "").replace("`", "").replace("’", "")
    s = s.replace(".", "").replace(",", "").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_underdog_names():
    out = {}
    if not os.path.exists(UD_CSV):
        return out
    with open(UD_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            fn = (row.get("firstName") or "").strip()
            ln = (row.get("lastName") or "").strip()
            if not fn or not ln:
                continue
            full = fn + " " + ln
            k = norm(full)
            if k and k not in out:
                out[k] = full
    return out


def load_clay_projections():
    out = {}
    if not os.path.exists(CLAY_JS):
        return out
    src = open(CLAY_JS, encoding="utf-8").read()
    # Tolerant: mike_clay_projections.js entries grew extra fields after rec
    # (ry/rtd/rcy/rctd, July 2026) — match the prefix, don't require the
    # object to close right after rec.
    pattern = re.compile(r'"([^"]+)":\s*\{pos:"([^"]+)",tm:"[^"]*",gm:(\d+),pts:(\d+),rec:(\d+)')
    for m in pattern.finditer(src):
        name = m.group(1)
        pos = m.group(2)
        gm = int(m.group(3))
        pts = int(m.group(4))
        rec = int(m.group(5))
        if gm <= 0:
            continue
        half_ppr_pts = pts - 0.5 * rec
        ppg = round(half_ppr_pts / gm, 1)
        out[norm(name)] = {"ppg": ppg, "szn": round(half_ppr_pts, 1), "gm": gm, "pos": pos}
    return out


def load_player_sigma():
    out = {}
    if not os.path.exists(SIGMA_JS):
        return out
    src = open(SIGMA_JS, encoding="utf-8").read()
    pattern = re.compile(r'"([^"]+)":\{"sigma_pct":([\d.]+),"sigma_abs":[\d.]+,"mean_ppg":([\d.]+),"games":(\d+)')
    for m in pattern.finditer(src):
        name = m.group(1)
        sp = float(m.group(2))
        games = int(m.group(4))
        if games < 10:
            continue
        out[norm(name)] = sp
    return out


ROOKIE_SIGMA_PCT_BY_TIER = {
    "RB": [(14, 0.50), (10, 0.62), (6, 0.80), (0, 0.91)],
    "WR": [(13, 0.56), (9, 0.66), (5, 0.80), (0, 0.99)],
    "TE": [(10, 0.53), (6, 0.70), (0, 0.91)],
    "QB": [(17, 0.41), (13, 0.47), (0, 0.65)],
}


def rookie_sigma_pct(pos, mean_ppg):
    tiers = ROOKIE_SIGMA_PCT_BY_TIER.get(pos)
    if not tiers:
        return 0.55
    for thresh, pct in tiers:
        if mean_ppg >= thresh:
            return pct
    return tiers[-1][1]


# Format-aware replacement levels (v0.9.67).
# Standard BBM 12-team (1QB / 2RB / 3WR / 1TE / 1FLEX, 18 rounds):
#   QB12  RB30  WR42  TE13  — used for `vor`, `up`, `hcPpg`
# Superflex BBM 12-team (1QB / 2RB / 2WR / 1TE / 1FLEX / 1SF, 18 rounds):
#   QB24 (1 QB + 1 SF; ~95% of SFs are QB) — late QBs jump +45 VOR
#   WR30 (2 WR + ~6 WR-FLEX, vs WR42 standard with 3 WR starters)
#         late WRs are structurally less valuable in SF
#   RB30 (unchanged), TE13 (unchanged)
VOR_REPL_LEVEL = {"QB": 12, "RB": 30, "WR": 42, "TE": 13}
VOR_REPL_LEVEL_SF = {"QB": 24, "RB": 30, "WR": 30, "TE": 13}

# v0.9.66: Handcuff modeling. Each position has its own dynamics.
# RB: lead misses ~22% of weeks; next-up captures 65% of lost workload.
#     Committees ALSO have an emergence ceiling — any RB might consolidate
#     the lead-back role, capturing ~55% of total team RB volume.
# WR: lead misses ~18% of weeks; absorption is target-share-based (55%).
#     No emergence floor since WR roles diffuse rather than consolidate.
HC_PARAMS = {
    "RB": {"workload_capture": 0.65, "prob_injury": 0.22, "emergence_lead_share": 0.55},
    "WR": {"workload_capture": 0.55, "prob_injury": 0.18},
    # v0.9.68: QB handcuff. In SF specifically, a backup behind a weak/
    # injured starter has real value — the next-up plays the whole game
    # when activated (capture ~0.85 of lost workload, much higher than
    # RB/WR). Injury+benching combined probability is ~13% per week.
    # This surfaces "Andy Dalton if Bryce Young loses the job" or
    # "Aaron Rodgers if the starter is hurt" as actual handcuff plays
    # in SF drafts. Standard format users still see this but it matters
    # less since QB depth isn't required.
    "QB": {"workload_capture": 0.85, "prob_injury": 0.13},
}


def qb_capture_quality(player):
    """Quality-aware QB workload capture.

    A proven veteran backup (Flacco for Cincy, Dalton, Aaron Rodgers, etc.)
    realistically posts ~14-18 PPG as a fill-in starter. A UDFA/career
    backup doesn't — even if elevated, they don't generate fantasy value.

    Look at the player's BEST recent season (p25, p24, p23) — Flacco was
    inactive in 2025 (p25 null) but posted starter-tier PPG in 2024 with
    Indianapolis. Use the highest of the three as the quality proxy.
    Age is a tertiary fallback for QBs with no recent meaningful PPG —
    older QBs are more likely seasoned vets capable of stepping in.

    Thresholds:
      best recent ≥10 PPG → 0.85 (starter-quality replacement)
      best recent 5-10    → 0.65 (some starting experience)
      else age ≥30        → 0.60 (career backup vet)
      else                → 0.45 (UDFA / unproven)
    """
    # Try p25/p24/p23 (3-year weighted rates) first; fall back to raw
    # season PPG if the rate is null but the season was played.
    recents = [v for v in [
        player.get("p25"), player.get("p24"), player.get("p23"),
        player.get("s25_ppg"), player.get("s24_ppg"), player.get("s23_ppg"),
    ] if v is not None]
    best = max(recents) if recents else None
    if best is not None:
        if best >= 10:
            return 0.85
        if best >= 5:
            return 0.65
    age = player.get("age")
    if age is not None and age >= 30:
        return 0.60
    return 0.45


def assign_handcuff_ppg(players, pos):
    if pos not in HC_PARAMS:
        return
    capture_default = HC_PARAMS[pos].get("workload_capture", 0.65)
    lead_share = HC_PARAMS[pos].get("emergence_lead_share")
    teams = {}
    for p in players:
        if p.get("s") != pos:
            continue
        if p.get("pPg") is None:
            continue
        team = p.get("t")
        if not team:
            continue
        teams.setdefault(team, []).append(p)
    for team, group in teams.items():
        group.sort(key=lambda x: -(x.get("pPg") or 0))
        top_ppg = group[0]["pPg"]
        if lead_share is not None:
            team_total = sum((p.get("pPg") or 0) for p in group)
            emergent_lead_ppg = max(top_ppg, team_total * lead_share)
        else:
            emergent_lead_ppg = top_ppg
        for i, p in enumerate(group):
            own = p["pPg"]
            if i == 0:
                p["hcPpg"] = round(max(own, emergent_lead_ppg), 1)
            else:
                # QB capture is vet-aware: backup quality varies wildly
                # (Flacco-tier vet vs UDFA scrub). RB/WR use the fixed rate.
                if pos == "QB":
                    capture = qb_capture_quality(p)
                else:
                    capture = capture_default
                p["hcPpg"] = round(own + (emergent_lead_ppg - own) * capture, 1)


def assign_vor(players, sigma_map):
    for p in players:
        ppg = p.get("pPg")
        if ppg is None or p.get("s") not in VOR_REPL_LEVEL:
            continue
        nk = norm(p["n"])
        sp = lookup_with_aliases(nk, sigma_map)
        if sp is None:
            sp = rookie_sigma_pct(p["s"], ppg)
        sigma_week = sp * ppg
        p["cPpg"] = round(ppg + sigma_week, 1)

    for hc_pos in HC_PARAMS:
        assign_handcuff_ppg(players, hc_pos)

    for p in players:
        pos = p.get("s")
        if pos not in HC_PARAMS:
            continue
        if p.get("cPpg") is None or p.get("hcPpg") is None:
            continue
        own_ppg = p.get("pPg") or 0
        hc_ppg = p["hcPpg"]
        if hc_ppg <= own_ppg:
            p["enhCPpg"] = p["cPpg"]
            continue
        hc_sigma_pct = rookie_sigma_pct(pos, hc_ppg)
        hc_cPpg = hc_ppg + hc_sigma_pct * hc_ppg
        p_inj = HC_PARAMS[pos]["prob_injury"]
        p["enhCPpg"] = round((1 - p_inj) * p["cPpg"] + p_inj * hc_cPpg, 1)

    # Compute VOR + UP under both standard and superflex replacement levels
    # so the extension can swap based on the contest type without
    # recomputing client-side.
    def _vor_pass(repl_levels, vor_key, up_key):
        by_pos = {pos: [] for pos in repl_levels}
        for p in players:
            if p.get("szn") is not None and p.get("s") in by_pos:
                by_pos[p["s"]].append(p)
        for pos, lst in by_pos.items():
            lst.sort(key=lambda x: -(x.get("szn") or 0))
            repl_idx = repl_levels[pos] - 1
            if repl_idx < len(lst):
                repl = lst[repl_idx]
            elif lst:
                repl = lst[-1]
            else:
                repl = None
            repl_pts = repl["szn"] if repl else 0
            repl_cPpg = repl.get("cPpg") if repl else None
            for p in lst:
                p[vor_key] = round((p.get("szn") or 0) - repl_pts)
                if p.get("cPpg") is None or repl_cPpg is None:
                    continue
                ceiling = p.get("enhCPpg") if pos in HC_PARAMS else p.get("cPpg")
                if ceiling is None:
                    ceiling = p["cPpg"]
                p[up_key] = round(ceiling - repl_cPpg, 1)

    _vor_pass(VOR_REPL_LEVEL, "vor", "up")
    _vor_pass(VOR_REPL_LEVEL_SF, "vorSf", "upSf")

    for p in players:
        p.pop("enhCPpg", None)
        # Strip helper fields used only for capture-quality calc
        p.pop("s25_ppg", None)
        p.pop("s24_ppg", None)
        p.pop("s23_ppg", None)
    return players


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


def _extract_szn_ppg(body, season_key):
    """Extract season PPG from nested {"yr":...,"gp":...,"ppg":X.X,...} object."""
    pat = r'"' + season_key + r'":\s*\{[^{}]*?"ppg":\s*([\-\d.]+)'
    m = re.search(pat, body)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


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
    # v0.9.68: also pull s25.ppg / s24.ppg / s23.ppg from the nested
    # season objects in d.js. p25/p24/p23 are sometimes null even when
    # the player had a real season (Flacco 2025 = 13 GP @ 11.7 PPG with
    # Browns/Bengals but p25 is null — the actual rate lives at s25.ppg).
    # Stash these as `s25_ppg` etc. for the QB quality function.
    for sk, out_key in [("s25", "s25_ppg"), ("s24", "s24_ppg"), ("s23", "s23_ppg")]:
        v = _extract_szn_ppg(body, sk)
        if v is not None:
            out[out_key] = v
    return out


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


def _shift_tiers(tiers, raw_to_dense):
    """Remap tier boundaries from raw board ranks onto densified ranks.

    `raw_to_dense[i]` is the rank the player sitting at raw index i ends up
    with after the dropped names are squeezed out. A boundary that lands on a
    dropped name slides down to the next kept player, which is what "tier
    starts here" means once that name is gone."""
    out = []
    for t in tiers:
        a = t["a"]
        out.append({**t, "a": raw_to_dense[a - 1] if 1 <= a <= len(raw_to_dense) else a})
    out.sort(key=lambda t: t["a"])
    return out


def load_jacks_format_boards(drop_names=None):
    """Jack's official redraft + superflex boards (Firestore, public read).
    Reuses the Sleeper export's fetcher; returns ({}, {}) on network failure.

    2026-08-18: `rank` used to come from Jack's BESTBALL board. Best Ball was
    retired from the site that day (one season board in-season), so Redraft is
    now the source. Redraft and Superflex both carry K/DST inline while this
    helper is best-ball-only, so `drop_names` (the K/DST name keys) are
    stripped and the surviving ranks re-densified — leaving the holes in place
    would push every rank below the first kicker out by the gap count. Tier
    boundaries ride the same shift so each break still lands on its player.

    Second return is his tier boundaries keyed by the FIELD NAME the extension
    reads the rank from ("rank" = redraft here, "jSf" = superflex): sorted
    [{a, l, n}] where a tier applies from rank `a` until the next boundary."""
    drop = drop_names or set()
    try:
        import export_sleeper_extension_data as sx

        doc = sx.fetch_jacks_doc()  # export-feed fn w/ public-REST fallback
        sx.load_ir_map(doc)   # top-level `ir` field — see the note in that module
        payload = json.loads(doc["fields"]["data"]["stringValue"])
        jacks = payload.get("jacks", {})
        out = {}
        tiers = {}
        # Superflex stays in RAW board numbering on purpose: the sidebar pairs
        # p.jSf with _posTiers boundaries that are also raw, and its live
        # Firestore refresh re-writes jSf raw. Only the redraft -> `rank` path
        # is squeezed, which is what the old bestball board looked like anyway
        # (it never carried K/DST).
        for mode, key in [("redraft", "jBb"), ("superflex", "jSf")]:
            order = (jacks.get(mode) or {}).get("_order") or []
            tier_key = "rank" if key == "jBb" else key
            raw_tiers = sx.extract_board_tiers(jacks.get(mode))
            if key != "jBb":
                out[key] = {norm(name): i + 1 for i, name in enumerate(order)}
                tiers[tier_key] = raw_tiers
                continue
            dense = {}
            raw_to_dense = []
            kept = 0
            for name in order:
                raw_to_dense.append(kept + 1)   # rank a kept player here would get
                nk = norm(name)
                if nk in drop:
                    continue
                kept += 1
                dense[nk] = kept
            out[key] = dense
            tiers[tier_key] = _shift_tiers(raw_tiers, raw_to_dense)
            if len(order) != kept:
                print(f"  {mode}: squeezed {len(order) - kept} K/DST out of {len(order)} board slots")
        print("Jacks format boards:", {k: len(v) for k, v in out.items()},
              " tiers:", {k: len(v) for k, v in tiers.items()})
        return out, tiers
    except Exception as e:
        print("WARN: could not fetch Jack's format boards:", e)
        return {}, {}


def main():
    src = open("data/d.js", encoding="utf-8").read()
    ud_names = load_underdog_names()
    clay_ppg = load_clay_projections()
    sigma_map = load_player_sigma()
    # Jack's Redraft/Superflex boards carry K/DST inline; this helper never
    # drafts them, so hand the board loader their names to squeeze out.
    kdst_names = set()
    for _s, _e in walk_d_array(src):
        _ent = parse_entry(src[_s:_e])
        if _ent.get("n") and _ent.get("s") in DROP_POS:
            kdst_names.add(norm(_ent["n"]))
    format_boards, jacks_tiers = load_jacks_format_boards(kdst_names)  # also populates sx.IR_OUT
    # Imported here, not at module scope: the Sleeper exporter imports THIS
    # module, so a top-level import would be circular.
    import export_sleeper_extension_data as _sx
    print("UD names:", len(ud_names), " Clay PPG:", len(clay_ppg), " sigma:", len(sigma_map))

    players = []
    rank_counter = 0
    ud_matched = 0
    ppg_matched = 0
    dropped = []
    ir_dropped = []
    for s, e in walk_d_array(src):
        body = src[s:e]
        entry = parse_entry(body)
        if not entry.get("n"):
            continue
        if entry.get("s") in DROP_POS:
            continue
        if entry.get("t") in (None, "TBD", ""):
            continue
        nk = norm(entry["n"])
        # Redraft is one of the site's IR-hidden formats, and this helper is
        # best-ball only — so an OUT FOR SEASON player is simply dropped here,
        # no flag needed (unlike the Sleeper/ESPN export, which also serves
        # dynasty modes where he must stay).
        if nk in _sx.IR_OUT:
            ir_dropped.append(entry["n"])
            continue
        # `rank` = Jack's position on his LIVE REDRAFT board, K/DST squeezed
        # out (Best Ball retired 2026-08-18), not the d.js array index.
        # d.js order drifts badly from the live boards, so board edits never
        # reached the extension. Absent from the board = he removed the player,
        # so drop him from the export.
        jbb = lookup_with_aliases(nk, format_boards.get("jBb") or {})
        if jbb is None:
            if format_boards.get("jBb"):
                dropped.append(entry["n"])
                continue
            rank_counter += 1   # board fetch failed — fall back to d.js order
            jbb = rank_counter
        entry["rank"] = jbb
        ud_n = lookup_with_aliases(nk, ud_names)
        if ud_n:
            entry["udN"] = ud_n
            ud_matched += 1
        clay_rec = lookup_with_aliases(nk, clay_ppg)
        if clay_rec is not None:
            entry["pPg"] = clay_rec["ppg"]
            entry["szn"] = clay_rec["szn"]
        for key, board in format_boards.items():
            if key == "jBb":
                continue  # already emitted as `rank` — don't ship it twice
            jr = lookup_with_aliases(nk, board)
            if jr is not None:
                entry[key] = jr
        players.append(entry)

    assign_vor(players, sigma_map)
    print("Wrote", len([p for p in players if p.get("vor") is not None]), "with VOR")
    print("QB hcPpg count:", len([p for p in players if p.get("s")=="QB" and p.get("hcPpg") is not None]))
    # PREMIUM LEAK FIX: bundle only the free slice of Jack's boards (top 36
    # real, deeper ranks re-numbered in Underdog-ADP order, tiers cut at 36).
    # Premium sessions restore the live board via the gated Firestore refresh.
    _sx.slice_jack_fields(players, {"rank": ["udA", "fpR", "slR"],
                                    "jSf":  ["udA", "fpR", "slR"]})
    jacks_tiers = _sx.slice_board_tiers(jacks_tiers)
    import os, json, time
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"version":7,"exported_at":time.strftime("%Y-%m-%d %H:%M:%S"),
                   "jackSlice":_sx.JACK_FREE_CUTOFF,"players":players,
                   # Jack's tier boundaries per rank field ("rank"=redraft, "jSf"):
                   # sorted [{a, l, n}], tier = last entry with a <= rank.
                   # SLICED: only boundaries within the free top-36 ship here.
                   "tiers":jacks_tiers}, f, ensure_ascii=False, indent=1)
    print("Wrote", len(players), "players ->", OUT_PATH)
    if ir_dropped:
        print(f"IR-DROPPED {len(ir_dropped)} flagged out for the season: " + ", ".join(ir_dropped))
    # Never drop silently — see the matching note in the Sleeper exporter.
    if dropped:
        print(f"DROPPED {len(dropped)} not on Jack's live redraft board: "
              + ", ".join(dropped[:15]) + (" ..." if len(dropped) > 15 else ""))


if __name__ == "__main__":
    main()
