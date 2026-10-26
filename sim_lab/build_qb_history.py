#!/usr/bin/env python3
"""
QB HISTORY TABLE for the P-20261023-2 inherit layer (2026-10-23, replay-first per Jack; standalone - refresh_data.py untouched).

Writes data/sim_qb_history.js:
  window.SIM_QB_HISTORY_2026 = { asOf, season, week (games before this week are in), stdDb, replacement: {fpp, rush},
                                 teamDb: {TEAM: dropbacks per game, 2026 season to date (>= 2 games) else 2025},
                                 p: { <engine norm key>: {fpp, rush, L, L35, n, nw, g, seasons, last, shrink, tm, gsis, qkey, name} } }
Level definition = EXACTLY the research_qb_inherit_grade.py (d) form so the replay is faithful:
  fpp   = shrunk fantasy points per dropback: sum over his games of .6^(asOfSeason - gameSeason) x (.04 py + 4 ptd - 1 int)
          plus 120 dropbacks of replacement, over the decayed dropbacks + 120 (replacement = pooled pts/dropback of QB games
          played with fewer than 300 career dropbacks before them, 2012-25)
  rush  = decayed mean of (.1 rush yds + 6 rush td) per game over games with 10+ dropbacks, shrunk with 6 games of the
          replacement rush rate (same low-experience pool)
  L     = fpp x teamDb[his 2026 team] + rush   (half-PPR points per game; receptions never apply to a QB)
  L35   = fpp x stdDb + rush, stdDb = the 2025 league mean team dropbacks per game (a team-free reference only)
  The engine would use fpp x the TEAM's dropbacks per game + rush (pts/dropback x team volume) because the backtest level
  was built that way and a backup inherits his team's pass volume, not a league-average one.
Walk-forward: --asof-week W uses only 2026 games before week W (the 2012-25 history is always in). Default = every 2026 game
in the play-by-play cache (the current state).
Sources: _tmp/qbx_cache/qbgame_<y>.pkl 2012-25 (research_backup_qb_features.build - built on demand if missing),
E:/MyFantasyFootball/pbp_cache/play_by_play_2026.csv.gz (2026 games, rebuilt every run), pbp_cache/players.csv (gsis -> name).
Keys: the engine's norm() of the nflverse display name (lower, no dots / apostrophes, hyphen -> space, no jr/sr/ii/iii/iv/v);
qkey ('c.wentz', build_future_totals.py style) is stored alongside. --pool <dump.json> reports pool QBs without a table row.
Usage: python build_qb_history.py [--asof-week W] [--pool _tmp/qb_replay_dump_w7.json] [--out data/sim_qb_history.js]
"""
import os, sys, re, json, argparse, datetime
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
PBP = r"E:/MyFantasyFootball/pbp_cache"; CACHE = os.path.join(HERE, "_tmp", "qbx_cache")
SEASON = 2026; HIST_YEARS = list(range(2012, 2026))
REPL_K = 120; DECAY = 0.6; RUSH_K = 6; MIN_DB_GAME = 10
TEAM_ALIAS = {"LA": "LAR", "STL": "LAR", "SD": "LAC", "OAK": "LV", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI"}
def tm(t): return TEAM_ALIAS.get(str(t), str(t))
def norm(n):
    s = str(n or "").lower().replace(".", "").replace("'", "").replace("-", " ")
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()
def qkey(name):
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", str(name).lower()).replace("'", "").strip()
    if "." in s and " " not in s.split(".")[0]: first, last = s.split(".", 1)
    else: parts = s.split(); first, last = parts[0], parts[-1]
    return first[:1] + "." + last.strip().split()[-1]

COLS = ["game_id", "season", "week", "season_type", "posteam", "passer_player_id", "passer_player_name", "rusher_player_id",
        "pass_attempt", "sack", "passing_yards", "rushing_yards", "pass_touchdown", "rush_touchdown", "interception", "two_point_attempt", "play_type", "rush_attempt"]
def build_games(y):
    """one row per (game, team, passer): db, pyds, ptd, int, rush_yds, rush_td - the qbgame_<y>.pkl columns the level needs"""
    d = pd.read_csv(os.path.join(PBP, f"play_by_play_{y}.csv.gz"), usecols=COLS, low_memory=False)
    d = d[(d.season_type == "REG") & (d.two_point_attempt != 1)].copy()
    pa = d[(d.pass_attempt == 1) | (d.sack == 1)].dropna(subset=["passer_player_id"])
    q = pa.groupby(["game_id", "week", "posteam", "passer_player_id"]).agg(name=("passer_player_name", "first"), db=("pass_attempt", "size"), pyds=("passing_yards", "sum"),
                                                                           ptd=("pass_touchdown", "sum"), int=("interception", "sum")).reset_index().rename(columns={"passer_player_id": "pid"})
    ru = d[(d.play_type == "run") & d.rusher_player_id.notna()].groupby(["game_id", "rusher_player_id"]).agg(rush_yds=("rushing_yards", "sum"), rush_td=("rush_touchdown", "sum")).reset_index().rename(columns={"rusher_player_id": "pid"})
    q = q.merge(ru, on=["game_id", "pid"], how="left").fillna({"rush_yds": 0, "rush_td": 0}); q["season"] = y
    return q

def load_history():
    frames = []
    for y in HIST_YEARS:
        fp = os.path.join(CACHE, f"qbgame_{y}.pkl")
        if os.path.exists(fp): frames.append(pd.read_pickle(fp)[["game_id", "week", "posteam", "pid", "name", "db", "pyds", "ptd", "int", "rush_yds", "rush_td", "season"]])
        else: frames.append(build_games(y))
    Q = pd.concat(frames, ignore_index=True)
    return Q

def prep(Q):
    Q = Q.copy(); Q["posteam"] = Q.posteam.map(tm); Q["t"] = Q.season * 100 + Q.week
    Q["fpp"] = 0.04 * Q.pyds + 4 * Q.ptd - 1 * Q["int"]; Q["rushp"] = 0.1 * Q.rush_yds + 6 * Q.rush_td
    return Q.sort_values(["t", "game_id"]).reset_index(drop=True)

class QbHistory:
    def __init__(self, asof_week=None, quiet=False):
        H = prep(load_history())
        G26 = prep(build_games(SEASON)) if os.path.exists(os.path.join(PBP, f"play_by_play_{SEASON}.csv.gz")) else H.iloc[0:0]
        if asof_week is not None: G26 = G26[G26.week < asof_week]
        self.asof_week = asof_week if asof_week is not None else (int(G26.week.max()) + 1 if len(G26) else 1)
        self.Q = pd.concat([H, G26], ignore_index=True).sort_values("t").reset_index(drop=True)
        self.rows = {pid: g for pid, g in self.Q.groupby("pid")}
        # replacement level from the 2012-25 history only (as the backtest): games with < 300 career dropbacks before them
        cum = H.groupby("pid").db.cumsum() - H.db; low = H.loc[cum.index[cum.values < 300]]
        self.repl = dict(fpp=float(low.fpp.sum() / low.db.sum()), rush=float(low.rushp[low.db >= MIN_DB_GAME].mean()))
        T = self.Q.groupby(["season", "posteam", "week"]).db.sum().reset_index(); self.team_db = T
        self.std_db = float(T[T.season == SEASON - 1].groupby(["posteam", "week"]).db.sum().mean())
        self.names = {}
        for pid, g in self.rows.items(): self.names[pid] = str(g.name.iloc[-1])
        if not quiet: print(f"history: {len(H):,} passer-games 2012-25 + {len(G26):,} in {SEASON} (weeks < {self.asof_week}); replacement fpp {self.repl['fpp']:.3f} rush/g {self.repl['rush']:.2f}; std team db/g {self.std_db:.1f}")
        self._hc = {}
    def hist(self, pid, year=SEASON, wk=None):
        """level inputs using only games before (year, wk): fpp (shrunk pts/dropback), rush (pts/g), n raw dropbacks, nw decayed, g games 10+ db, seasons, last"""
        wk = self.asof_week if wk is None else wk
        key = (pid, year, wk)
        if key in self._hc: return self._hc[key]
        g = self.rows.get(pid); out = dict(fpp=self.repl["fpp"], rush=self.repl["rush"], n=0, nw=0.0, g=0, seasons=None, last=None, shrink=0.0)
        if g is not None:
            h = g[g.t < year * 100 + wk]
            if len(h):
                w = DECAY ** (year - h.season.values).astype(float); dbw = float(np.sum(w * h.db.values))
                out["n"] = int(h.db.sum()); out["nw"] = round(dbw, 1); out["fpp"] = (float(np.sum(w * h.fpp.values)) + REPL_K * self.repl["fpp"]) / (dbw + REPL_K)
                gm = h[h.db >= MIN_DB_GAME]; wg = DECAY ** (year - gm.season.values).astype(float)
                out["rush"] = (float(np.sum(wg * gm.rushp.values)) + RUSH_K * self.repl["rush"]) / (float(wg.sum()) + RUSH_K) if len(gm) else self.repl["rush"]
                out["g"] = int(len(gm)); out["seasons"] = [int(h.season.min()), int(h.season.max())]; out["last"] = int(h.season.max()); out["shrink"] = dbw / (dbw + REPL_K)
        self._hc[key] = out; return out
    def team_db_pg(self, team, year=SEASON, wk=None):
        wk = self.asof_week if wk is None else wk; T = self.team_db
        h = T[(T.season == year) & (T.posteam == team) & (T.week < wk)]
        if len(h) >= 2: return float(h.db.mean()), f"{year} wk<{wk} ({len(h)} g)"
        h2 = T[(T.season == year - 1) & (T.posteam == team)]
        return (float(h2.db.mean()), f"{year - 1} avg") if len(h2) else (float(T[T.season == year].db.mean()), f"{year} league")
    def level(self, pid, team, year=SEASON, wk=None):
        b = self.hist(pid, year, wk); tdb, src = self.team_db_pg(team, year, wk)
        return dict(L=b["fpp"] * tdb + b["rush"], L35=b["fpp"] * self.std_db + b["rush"], teamDb=tdb, teamDbSrc=src, **b)

def players_map():
    p = pd.read_csv(os.path.join(PBP, "players.csv"), low_memory=False)
    p = p[p.gsis_id.notna()]
    return {r.gsis_id: dict(name=str(r.display_name), pos=str(r.position), tm=tm(r.latest_team) if isinstance(r.latest_team, str) else None, last=int(r.last_season) if r.last_season == r.last_season else None, status=str(r.status)) for r in p.itertuples(index=False)}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--asof-week", type=int, default=None); ap.add_argument("--pool", default=None); ap.add_argument("--out", default=os.path.join(HERE, "data", "sim_qb_history.js"))
    a = ap.parse_args()
    QH = QbHistory(a.asof_week); PM = players_map()
    # QBs: every passer 2012-26 whose players.csv position is QB, plus every active 2026 QB on players.csv (no history -> replacement)
    pids = set(QH.rows) | {g for g, r in PM.items() if r["pos"] == "QB" and r["last"] == SEASON}
    table = {}; dup = []; nonqb = 0
    for pid in pids:
        r = PM.get(pid)
        if not r: r = dict(name=QH.names.get(pid, pid), pos="QB", tm=None, last=None, status="")
        if r["pos"] != "QB": nonqb += 1; continue
        last_tm = r["tm"]
        g = QH.rows.get(pid)
        if g is not None and len(g[g.season == SEASON]): last_tm = str(g[g.season == SEASON].posteam.iloc[-1])   # the team he threw for this season
        team = last_tm or "LEAGUE"
        lv = QH.level(pid, team) if team != "LEAGUE" else dict(QH.hist(pid), L=None, L35=QH.hist(pid)["fpp"] * QH.std_db + QH.hist(pid)["rush"], teamDb=None, teamDbSrc=None)
        key = norm(r["name"]); row = dict(name=r["name"], gsis=pid, qkey=qkey(r["name"]), tm=team if team != "LEAGUE" else None, fpp=round(lv["fpp"], 4), rush=round(lv["rush"], 2), L=None if lv["L"] is None else round(lv["L"], 2), L35=round(lv["L35"], 2),
                                          n=lv["n"], nw=lv["nw"], g=lv["g"], seasons=lv["seasons"], last=lv["last"], shrink=round(lv["shrink"], 3))
        if key in table:
            old = table[key]; dup.append((key, old["gsis"], old["last"], pid, row["last"]))
            if (row["last"] or 0) < (old["last"] or 0) or ((row["last"] or 0) == (old["last"] or 0) and row["n"] < old["n"]): continue
        table[key] = row
    teams = sorted({t for t in QH.team_db[QH.team_db.season.isin((SEASON, SEASON - 1))].posteam.unique()})
    teamDb = {t: round(QH.team_db_pg(t)[0], 2) for t in teams if t in {"ARI","ATL","BAL","BUF","CAR","CHI","CIN","CLE","DAL","DEN","DET","GB","HOU","IND","JAX","KC","LAC","LAR","LV","MIA","MIN","NE","NO","NYG","NYJ","PHI","PIT","SEA","SF","TB","TEN","WAS"}}
    out = dict(asOf=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), season=SEASON, week=QH.asof_week, stdDb=round(QH.std_db, 2), replacement=dict(fpp=round(QH.repl["fpp"], 4), rush=round(QH.repl["rush"], 2)),
               decay=DECAY, replK=REPL_K, rushK=RUSH_K, teamDb=teamDb, p=dict(sorted(table.items())))
    js = ("// AUTO-GENERATED by build_qb_history.py (P-20261023-2 QB inherit history level; replay-first, not yet read by engine.js)\n"
          "// p[norm] = {fpp: shrunk half-PPR pts per dropback (.6^k season decay, 120-db shrink to replacement), rush: pts/g, L: fpp x teamDb[tm] + rush,\n"
          "//            L35: fpp x stdDb + rush, n: career dropbacks, nw: decayed, g: games 10+ db, seasons, last, shrink = own-evidence share, gsis, qkey}\n"
          "window.SIM_QB_HISTORY_2026 = " + json.dumps(out, separators=(",", ":")) + ";\n")
    with open(a.out, "wb") as f: f.write(js.encode("utf-8"))
    with_hist = sum(1 for r in table.values() if r["n"] > 0); act26 = sum(1 for r in table.values() if r["last"] == SEASON)
    print(f"wrote {a.out}: {len(table)} QBs ({with_hist} with 2012-{SEASON} dropbacks, {act26} seen in {SEASON}; {nonqb} non-QB passers skipped; {len(dup)} name collisions), week {QH.asof_week}, {len(teamDb)} team db/g")
    for d in dup: print(f"  collision {d[0]}: kept the later of {d[1]} (last {d[2]}) / {d[3]} (last {d[4]})")
    if a.pool and os.path.exists(a.pool):
        dmp = json.loads(open(a.pool, encoding="utf-8").read().strip().splitlines()[-1]); pool = {}
        for wk, W in dmp["weeks"].items():
            for t, x in W.items():
                for r in x["qbs"]: pool[r["norm"]] = (r["name"], t)
        miss = {k: v for k, v in pool.items() if k not in table}
        print(f"pool QBs (engine norms, {len(pool)}): {len(pool) - len(miss)} matched, {len(miss)} unmatched" + (": " + ", ".join(f"{v[0]} ({v[1]})" for v in sorted(miss.values())) if miss else ""))
        # second pass: unmatched by qkey + team
        byq = {}
        for k, r in table.items(): byq.setdefault((r["qkey"], r["tm"]), k)
        for k, (nm, t) in miss.items():
            alt = byq.get((qkey(nm), t))
            print(f"    {nm} ({t}): " + (f"qkey+team match -> '{alt}' (alias needed)" if alt else "no history at all -> replacement level"))

if __name__ == "__main__":
    main()
