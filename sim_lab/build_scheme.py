"""
SCHEME / ALIGNMENT intel from the PFF Premium weekly facets -> data/scheme_2026.js
(window.SIM_SCHEME_2026). INTEL ONLY - nothing here moves a projection.

Jack 2026-09-15: "we can definitely find alignments and where each defense gets
targeted or what type of runs outside/inside zone etc somewhere maybe pff" -> "do it";
then "get the info from last season and see if there are any similarities to week 1
because then that team defense or offensive players will be somewhat reliable" ->
the same profiles are built for the PRIOR season (PFF weekly facets 1-18, fetched once
by the puller) and shipped as *Prior maps plus a league-wide W1-vs-prior correlation
per metric (`persist`), so the tab can flag what carried over.

Source files (scripts/pull_pff_weekly.py in the site repo, one CSV per facet per
played week, E:\\MyFantasyFootball\\pbp_cache\\pff\\weekly\\pff_<facet>_<season>_w<N>.csv):
  defense_coverage_scheme  per defender man / zone coverage snaps        -> team MAN RATE
  defense_summary          per defender alignment snaps + grades         -> safety-in-box rate, DB/LB rush share, grades
  defense_pass_rush        per rusher pass-rush wins / opportunities     -> team PASS-RUSH WIN RATE
  passing_pressure         per QB blitz / pressure dropback splits       -> QB splits; BLITZ % and PRESSURE % *generated* by
                                                                            the defense he faced (opponent map from nflverse pbp)
  rushing_summary          per rusher gap vs zone attempts, yco, breakaway-> RB style; run defense faced (ypc, yco, gap share...)
  rushing_direction        per rusher carries by lane (LE LT LG ML MR RG RT RE) -> RB lane mix; lanes a defense gets run at
  receiving_scheme         per receiver man / zone routes, targets, yards -> man-beater / zone-beater profiles; team man seen
  receiving_concept        per receiver screen + slot routes / targets    -> screen share, slot share
  receiving (summary)      slot / wide / inline snaps                      -> alignment mix
                           (current season = pff_receiving_<yr>_w<N>.csv, prior = pff_receiving_summary_<yr>_w<N>.csv)
  (receiving_depth is saved by the puller but not aggregated here - the ZONES
   tab already carries target depth x side from pbp.)

Backtest context (README): per-player man/zone splits (r .05), per-zone defense
efficiency and per-direction run efficiency are NOISE as projection layers;
funnels / identities persist. So this file is what a defense IS and what a
player DOES, for the ZONES + NOTES tabs and Jack's videos.

Team codes: PFF uses ARZ/BLT/CLV/HST/LA -> ARI/BAL/CLE/HOU/LAR (Sim Lab codes).
Player keys: pull_pace_tracker.norm_name (same key the engine uses).
Run standalone (python build_scheme.py) or via pull_pace_tracker.build().
"""
import glob, json, math, os, re, sys, time

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = r"E:\MyFantasyFootball\pbp_cache"
PFF_WEEKLY = os.path.join(CACHE, "pff", "weekly")
OUT = os.path.join(HERE, "data", "scheme_2026.js")
SEASON, PRIOR = 2026, 2025
PFF_ALIAS = {"ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "LA": "LAR", "OAK": "LV", "SD": "LAC", "WSH": "WAS"}
LANES = ["LE", "LT", "LG", "ML", "MR", "RG", "RT", "RE"]      # PFF direction codes (W1 2026 counts confirm)
LANE_ALIAS = {"JS-L": "LE", "EA-L": "LE", "JS-R": "RE", "EA-R": "RE"}  # jet sweeps / end-arounds = edge; QB* codes ignored
EDGE = {"LE", "RE"}
# defense metrics compared season-over-season (key, sub) - identities first
PERSIST_KEYS = [("man", None), ("blitz", None), ("prs", None), ("prwr", None), ("sBox", None), ("dbRush", None),
                ("mtRate", None), ("slotYd", None), ("screenTg", None), ("grCov", None), ("grRun", None), ("grPrsh", None),
                ("ypc", "run"), ("yco", "run"), ("gap", "run"), ("edge", "run"), ("exp", "run"), ("mtf", "run")]


def tm(t):
    t = str(t or "").strip()
    return PFF_ALIAS.get(t, t)


def norm_name(n):
    n = str(n).lower().replace(".", "").replace("'", "").replace("-", " ")
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return re.sub(r"\s+", " ", n).strip()


def load(facet, season):
    """All weeks of one facet for one season -> DataFrame (numeric coerced); None when absent."""
    files = sorted(glob.glob(os.path.join(PFF_WEEKLY, f"pff_{facet}_{season}_w*.csv")),
                   key=lambda p: int(re.search(r"_w(\d+)\.csv$", p).group(1)))
    if not files:
        return None
    parts = []
    for p in files:
        d = pd.read_csv(p, low_memory=False)
        d["week"] = int(re.search(r"_w(\d+)\.csv$", p).group(1))   # receiving files predate the week column
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    keep = ["player", "position", "team_name", "week"] + [c for c in ("directions",) if c in df.columns]
    num = {c: pd.to_numeric(df[c], errors="coerce") for c in df.columns if c not in keep and c != "team"}
    df = pd.concat([df[keep], pd.DataFrame(num)], axis=1)
    df["tm"] = df["team_name"].map(tm)
    return df


def load_all(season, receiving_key):
    F = {k: load(k, season) for k in ("defense_coverage_scheme", "defense_summary", "defense_pass_rush", "passing_pressure",
                                      "rushing_summary", "rushing_direction", "receiving_scheme", "receiving_concept")}
    F["receiving"] = load(receiving_key, season)
    return F


def opp_map(season):
    """{(week, team): opponent} from nflverse pbp (nightly)."""
    p = os.path.join(CACHE, f"play_by_play_{season}.csv.gz")
    out = {}
    if not os.path.exists(p):
        return out
    df = pd.read_csv(p, usecols=["week", "home_team", "away_team", "season_type"], low_memory=False)
    df = df[df.season_type == "REG"].drop_duplicates()
    for r in df.itertuples(index=False):
        h, a = tm(r.home_team), tm(r.away_team)
        out[(int(r.week), h)] = a
        out[(int(r.week), a)] = h
    return out


def S(df, col):
    return float(df[col].fillna(0).sum()) if df is not None and col in df.columns else 0.0


def rate(a, b, nd=3):
    return round(a / b, nd) if b else None


def wmean(df, col, wcol):
    if df is None or col not in df.columns or wcol not in df.columns:
        return None
    d = df[[col, wcol]].dropna()
    w = d[wcol].sum()
    return round(float((d[col] * d[wcol]).sum() / w), 1) if w else None


def lanes_of(df):
    """Sum rushing_direction JSON per lane -> {lane: [att, yds]}."""
    acc = {l: [0, 0] for l in LANES}
    if df is None or "directions" not in df.columns:
        return acc
    for s in df["directions"].dropna():
        try:
            for d in json.loads(s):
                l = d.get("direction"); l = LANE_ALIAS.get(l, l)
                if l in acc:
                    acc[l][0] += int(d.get("attempts") or 0)
                    acc[l][1] += int(d.get("yards") or 0)
        except (ValueError, TypeError):
            pass
    return acc


def run_block(rs, rd):
    """Rushing profile for a set of rusher rows (own team, or the RBs a defense faced)."""
    if rs is None or rs.empty:
        return None
    att = S(rs, "attempts")
    if not att:
        return None
    lanes = lanes_of(rd) if rd is not None and not rd.empty else {}
    lane_att = sum(v[0] for v in lanes.values())
    out = {"att": int(att), "ypc": rate(S(rs, "yards"), att, 2), "yco": rate(S(rs, "yards_after_contact"), att, 2),
           "gap": rate(S(rs, "gap_attempts"), S(rs, "gap_attempts") + S(rs, "zone_attempts")),
           "exp": rate(S(rs, "explosive"), att), "mtf": rate(S(rs, "avoided_tackles"), att),
           "brk": rate(S(rs, "breakaway_yards"), S(rs, "yards"))}
    if lane_att:
        out["edge"] = rate(sum(lanes[l][0] for l in EDGE), lane_att)
        out["lanes"] = {l: v for l, v in lanes.items()}
    return out


def aggregate(F, opp):
    """One season's frames -> (DEF, OFF, REC, RB, QB, LG, weeks)."""
    cov, ds, pr, pp = F["defense_coverage_scheme"], F["defense_summary"], F["defense_pass_rush"], F["passing_pressure"]
    rs, rd, rsc, rcc, rsum = F["rushing_summary"], F["rushing_direction"], F["receiving_scheme"], F["receiving_concept"], F["receiving"]
    frames = [d for d in (cov, ds, pr, pp, rs, rd, rsc, rcc, rsum) if d is not None]
    if not frames:
        return None
    weeks = sorted(set().union(*[set(int(w) for w in d.week.unique()) for d in frames]))
    teams = sorted(set().union(*[set(d.tm.unique()) for d in (cov, ds, rs, rsc) if d is not None]))

    def faced(df):
        """rows of players who played AGAINST team T (via opponent map)."""
        if df is None or df.empty or not opp:
            return {}
        df = df.assign(opp=[opp.get((int(w), t)) for w, t in zip(df.week, df.tm)])
        return {t: g for t, g in df[df.opp.notna()].groupby("opp")}
    noqb = lambda df: None if df is None else df[~df.position.isin(["QB"])]   # run D faced = RB/WR/FB carries, no scrambles/kneels
    pp_faced, rs_faced, rd_faced, rcc_faced, rsum_faced = faced(pp), faced(noqb(rs)), faced(noqb(rd)), faced(rcc), faced(rsum)

    DEF, OFF = {}, {}
    for T in teams:
        d = {"g": 0}
        if cov is not None:
            c = cov[cov.tm == T]
            man, zone = S(c, "man_snap_counts_coverage"), S(c, "zone_snap_counts_coverage")
            d["man"] = rate(man, man + zone); d["covSnaps"] = int(man + zone)
            d["grCov"] = wmean(c, "zone_grades_coverage_defense", "zone_snap_counts_coverage")
            d["g"] = int(c.week.nunique())
        if ds is not None:
            s = ds[ds.tm == T]
            d["g"] = max(d["g"], int(s.week.nunique()))
            saf = s[s.position == "S"]
            d["sBox"] = rate(S(saf, "snap_counts_box"), S(saf, "snap_counts_defense"))
            pass_plays = float(s.groupby("week").apply(lambda g: (g.snap_counts_pass_rush.fillna(0) + g.snap_counts_coverage.fillna(0)).max()).sum()) if len(s) else 0.0
            d["dbRush"] = rate(S(s[s.position.isin(["LB", "S", "CB"])], "snap_counts_pass_rush"), pass_plays)
            d["grDef"] = wmean(s, "grades_defense", "snap_counts_defense")
            d["grRun"] = wmean(s, "grades_run_defense", "snap_counts_run_defense")
            d["grPrsh"] = wmean(s, "grades_pass_rush_defense", "snap_counts_pass_rush")
            d["mtRate"] = rate(S(s, "missed_tackles"), S(s, "tackles") + S(s, "assists") + S(s, "missed_tackles"))
            if pass_plays:
                d["prsRaw"] = rate(S(s, "total_pressures"), pass_plays)
        if pr is not None:
            r = pr[pr.tm == T]
            d["prwr"] = rate(S(r, "pass_rush_wins"), S(r, "pass_rush_opp"))
        q = pp_faced.get(T)
        if q is not None and len(q):
            db = S(q, "base_dropbacks")
            d["blitz"] = rate(S(q, "blitz_dropbacks"), db); d["prs"] = rate(S(q, "pressure_dropbacks"), db); d["db"] = int(db)
            d["sk"] = rate(S(q, "pressure_sacks") + S(q, "no_pressure_sacks"), db)
            d["qbGr"] = wmean(q, "grades_pass", "base_dropbacks")
        rb = run_block(rs_faced.get(T), rd_faced.get(T))
        if rb:
            d["run"] = rb
        cf = rcc_faced.get(T)
        if cf is not None and len(cf):
            sf = rsum_faced.get(T)
            d["slotYd"] = rate(S(cf, "slot_yards"), S(sf, "yards")) if sf is not None else None   # share of receiving yds allowed to slot routes
            d["screenTg"] = rate(S(cf, "screen_targets"), S(cf, "base_targets"))
        DEF[T] = d

        o = {"g": 0}
        if rs is not None:
            own = rs[(rs.tm == T) & (~rs.position.isin(["QB"]))]
            rb = run_block(own, rd[(rd.tm == T) & (~rd.position.isin(["QB"]))] if rd is not None else None)
            if rb:
                o["run"] = rb
            o["g"] = int(own.week.nunique())
        if rsc is not None:
            r = rsc[rsc.tm == T]
            mr, zr = S(r, "man_routes"), S(r, "zone_routes")
            o["manSeen"] = rate(mr, mr + zr)
            o["mYprr"] = rate(S(r, "man_yards"), mr, 2); o["zYprr"] = rate(S(r, "zone_yards"), zr, 2)
        if rcc is not None:
            r = rcc[rcc.tm == T]
            o["screen"] = rate(S(r, "screen_targets"), S(r, "base_targets"))
        if pp is not None:
            q = pp[pp.tm == T]
            db = S(q, "base_dropbacks")
            o["blitzFaced"] = rate(S(q, "blitz_dropbacks"), db); o["prsFaced"] = rate(S(q, "pressure_dropbacks"), db)
        OFF[T] = o

    # ---- players -------------------------------------------------------
    REC, RB, QB = {}, {}, {}
    if rsc is not None:
        slot = {}
        if rsum is not None:
            for k, g in rsum.groupby("player_id"):
                slot[k] = (S(g, "slot_snaps"), S(g, "wide_snaps"), S(g, "inline_snaps"))
        scr = {}
        if rcc is not None:
            for k, g in rcc.groupby("player_id"):
                scr[k] = (S(g, "screen_targets"), S(g, "screen_yards"), S(g, "slot_targets"), S(g, "slot_yards"))
        for pid, g in rsc.groupby("player_id"):
            mr, zr = S(g, "man_routes"), S(g, "zone_routes")
            if mr + zr < 1:
                continue
            last = g.sort_values("week").iloc[-1]
            rec = {"tm": last.tm, "pos": last.position, "g": int(g.week.nunique()),
                   "mR": int(mr), "zR": int(zr), "mT": int(S(g, "man_targets")), "zT": int(S(g, "zone_targets")),
                   "mY": int(S(g, "man_yards")), "zY": int(S(g, "zone_yards")),
                   "mRec": int(S(g, "man_receptions")), "zRec": int(S(g, "zone_receptions")),
                   "mTd": int(S(g, "man_touchdowns")), "zTd": int(S(g, "zone_touchdowns"))}
            if pid in slot:
                rec["sl"], rec["wd"], rec["il"] = [int(x) for x in slot[pid]]
            if pid in scr:
                rec["scT"], rec["scY"], rec["slT"], rec["slY"] = [int(x) for x in scr[pid]]
            REC[norm_name(last.player)] = rec
    if rs is not None:
        for pid, g in rs.groupby("player_id"):
            att = S(g, "attempts")
            if att < 1:
                continue
            last = g.sort_values("week").iloc[-1]
            r = {"tm": last.tm, "pos": last.position, "g": int(g.week.nunique()), "att": int(att), "yds": int(S(g, "yards")),
                 "gap": int(S(g, "gap_attempts")), "zone": int(S(g, "zone_attempts")), "yco": int(S(g, "yards_after_contact")),
                 "exp": int(S(g, "explosive")), "mtf": int(S(g, "avoided_tackles")), "brkY": int(S(g, "breakaway_yards")),
                 "elu": wmean(g, "elusive_rating", "attempts")}
            if rd is not None:
                ln = lanes_of(rd[rd.player_id == pid])
                if sum(v[0] for v in ln.values()):
                    r["lanes"] = ln
            RB[norm_name(last.player)] = r
    if pp is not None:
        for pid, g in pp.groupby("player_id"):
            db = S(g, "base_dropbacks")
            if db < 1:
                continue
            last = g.sort_values("week").iloc[-1]
            QB[norm_name(last.player)] = {
                "tm": last.tm, "g": int(g.week.nunique()), "db": int(db),
                "bDb": int(S(g, "blitz_dropbacks")), "pDb": int(S(g, "pressure_dropbacks")),
                "pAtt": int(S(g, "pressure_attempts")), "pY": int(S(g, "pressure_yards")), "pTd": int(S(g, "pressure_touchdowns")),
                "pInt": int(S(g, "pressure_interceptions")), "pSk": int(S(g, "pressure_sacks")), "pTwp": int(S(g, "pressure_turnover_worthy_plays")),
                "nAtt": int(S(g, "no_pressure_attempts")), "nY": int(S(g, "no_pressure_yards")), "nTd": int(S(g, "no_pressure_touchdowns")),
                "nInt": int(S(g, "no_pressure_interceptions")),
                "bAtt": int(S(g, "blitz_attempts")), "bY": int(S(g, "blitz_yards")), "bTd": int(S(g, "blitz_touchdowns")),
                "nbAtt": int(S(g, "no_blitz_attempts")), "nbY": int(S(g, "no_blitz_yards")), "nbTd": int(S(g, "no_blitz_touchdowns")),
                "pGr": wmean(g, "pressure_grades_pass", "pressure_dropbacks"), "nGr": wmean(g, "no_pressure_grades_pass", "no_pressure_dropbacks"),
                "bGr": wmean(g, "blitz_grades_pass", "blitz_dropbacks"), "nbGr": wmean(g, "no_blitz_grades_pass", "no_blitz_dropbacks"),
                "p2s": rate(S(g, "pressure_sacks"), S(g, "pressure_dropbacks"))}

    # ---- league ---------------------------------------------------------
    LG = {}
    def lg_mean(key, sub=None):
        vals = []
        for d in DEF.values():
            v = d.get(sub, {}).get(key) if sub else d.get(key)
            if v is not None:
                vals.append(v)
        return round(sum(vals) / len(vals), 3) if vals else None
    for k in ("man", "blitz", "prs", "prwr", "sBox", "dbRush", "mtRate", "sk", "slotYd", "screenTg", "grDef", "grRun", "grCov", "grPrsh", "qbGr", "prsRaw"):
        LG[k] = lg_mean(k)
    LG["run"] = {k: lg_mean(k, "run") for k in ("ypc", "yco", "gap", "exp", "mtf", "brk", "edge")}
    if rs is not None:
        lanes = lanes_of(rd[~rd.position.isin(["QB"])]) if rd is not None else {}
        la = sum(v[0] for v in lanes.values())
        LG["lanes"] = {l: rate(v[0], la) for l, v in lanes.items()} if la else None
        LG["laneYpc"] = {l: rate(v[1], v[0], 2) for l, v in lanes.items()} if la else None
    if rsc is not None:
        mr, zr = S(rsc, "man_routes"), S(rsc, "zone_routes")
        LG["rec"] = {"manSeen": rate(mr, mr + zr), "mTgR": rate(S(rsc, "man_targets"), mr), "zTgR": rate(S(rsc, "zone_targets"), zr),
                     "mYprr": rate(S(rsc, "man_yards"), mr, 2), "zYprr": rate(S(rsc, "zone_yards"), zr, 2)}
        if rcc is not None:
            LG["rec"]["screen"] = rate(S(rcc, "screen_targets"), S(rcc, "base_targets"))
        if rsum is not None:
            sl, wd, il = S(rsum, "slot_snaps"), S(rsum, "wide_snaps"), S(rsum, "inline_snaps")
            LG["rec"]["slot"] = rate(sl, sl + wd + il)
    if pp is not None:
        db = S(pp, "base_dropbacks")
        LG["qb"] = {"blitz": rate(S(pp, "blitz_dropbacks"), db), "prs": rate(S(pp, "pressure_dropbacks"), db),
                    "pGr": wmean(pp, "pressure_grades_pass", "pressure_dropbacks"), "nGr": wmean(pp, "no_pressure_grades_pass", "no_pressure_dropbacks"),
                    "pYpa": rate(S(pp, "pressure_yards"), S(pp, "pressure_attempts"), 2), "nYpa": rate(S(pp, "no_pressure_yards"), S(pp, "no_pressure_attempts"), 2)}
    return DEF, OFF, REC, RB, QB, LG, weeks


def pearson(pairs):
    n = len(pairs)
    if n < 8:
        return None
    mx = sum(a for a, _ in pairs) / n; my = sum(b for _, b in pairs) / n
    sxx = sum((a - mx) ** 2 for a, _ in pairs); syy = sum((b - my) ** 2 for _, b in pairs)
    if not sxx or not syy:
        return None
    return round(sum((a - mx) * (b - my) for a, b in pairs) / math.sqrt(sxx * syy), 2)


def persistence(DEF, DEFP):
    """League-wide correlation of each defense metric: current season-to-date vs prior full season."""
    out = {}
    for key, sub in PERSIST_KEYS:
        pairs = []
        for t, d in DEF.items():
            p = DEFP.get(t)
            if not p:
                continue
            a = (d.get(sub) or {}).get(key) if sub else d.get(key)
            b = (p.get(sub) or {}).get(key) if sub else p.get(key)
            if a is not None and b is not None:
                pairs.append((a, b))
        out[(sub + "." if sub else "") + key] = {"r": pearson(pairs), "n": len(pairs)}
    return out


def build():
    cur = aggregate(load_all(SEASON, "receiving"), opp_map(SEASON))
    if cur is None:
        print("scheme: no PFF facet files yet - nothing written")
        return None
    DEF, OFF, REC, RB, QB, LG, weeks = cur
    payload = {"updated": time.strftime("%Y-%m-%d %H:%M"), "season": SEASON, "prior": PRIOR, "weeks": weeks,
               "lg": LG, "def": DEF, "off": OFF, "rec": REC, "rb": RB, "qb": QB}
    pri = aggregate(load_all(PRIOR, "receiving_summary"), opp_map(PRIOR))
    if pri is not None:
        DEFP, OFFP, RECP, RBP, QBP, LGP, weeksP = pri
        payload.update({"lgPrior": LGP, "defPrior": DEFP, "offPrior": OFFP, "recPrior": RECP, "rbPrior": RBP, "qbPrior": QBP,
                        "weeksPrior": weeksP, "persist": persistence(DEF, DEFP)})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// built by build_scheme.py from PFF Premium weekly facets - defense scheme (man rate, blitz, pressure, run lanes) + player style profiles, current season + prior season + persistence; INTEL ONLY\n")
        f.write("window.SIM_SCHEME_2026 = ")
        json.dump(payload, f, separators=(",", ":"))
        f.write(";\n")
    msg = f"wrote {OUT} - {SEASON} weeks {weeks}, {len(DEF)} defenses, {len(REC)} receivers, {len(RB)} rushers, {len(QB)} QBs"
    if pri is not None:
        pz = payload["persist"]
        msg += f"; {PRIOR} prior weeks {weeksP[0]}-{weeksP[-1]} ({len(DEFP)} D, {len(RECP)} rec); W1-vs-{PRIOR} r: " + \
               ", ".join(f"{k} {v['r']}" for k, v in pz.items() if v["r"] is not None)
    print(msg)
    return payload


if __name__ == "__main__":
    sys.exit(0 if build() is not None else 1)
