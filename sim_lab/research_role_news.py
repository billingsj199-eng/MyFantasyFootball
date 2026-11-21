#!/usr/bin/env python3
"""
ROLE-NEWS STUDY (mff-sim-engineer STATS mode, first run 2026-11-10; agent file "Autonomous modes" step 4). Read-only on live files.

Every riser / faller / role / transaction item the daily news scan has written since July (all versions of
data/camp_news_2026.json in git, collected to _tmp/role_news_items.json) is graded against that player's NEXT 3 GAMES after the
item's date: actual half-PPR points vs the number the sim LOCKED for that game (data/snapshots, shipped mean; also the model
number before the book anchor and the shadow number). The lock for each game is made after the news, so this measures what the
question needs: once news of this kind is out, does the model's own next number still miss in the news' direction, and by how
much - i.e. should NEWS mode bump, and what size.

Control = every other locked player-week of the same position in the same week (the model's general lean that week is taken out).
Output: _tmp/role_news_study.log (+ _tmp/role_news_rows.csv).
"""
import json, os, re, sys, datetime
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"; CACHE = r"E:\MyFantasyFootball\pbp_cache"
LOG = open(os.path.join(HERE, "_tmp", "role_news_study.log"), "w", encoding="utf-8")
def P(s=""):
    print(s, flush=True); LOG.write(s + "\n")
POS4 = ("QB", "RB", "WR", "TE")
def norm(s):
    s = (s or "").lower().replace(".", "").replace("'", "").replace("-", " "); s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s); return re.sub(r"\s+", " ", s).strip()

items = json.load(open(os.path.join(HERE, "_tmp", "role_news_items.json"), encoding="utf-8"))
news = [i for i in items if i.get("tag") in ("riser", "faller", "role", "transaction") and i.get("pos") in POS4 and i.get("player") and i.get("date")]
# game dates per team-week
d = pd.read_csv(os.path.join(CACHE, "play_by_play_2026.csv.gz"), low_memory=False, usecols=["season_type", "week", "posteam", "game_date"])
d = d[(d.season_type == "REG") & d.posteam.notna()]; TM = {"LA": "LAR", "WSH": "WAS", "JAC": "JAX"}
gdate = {(TM.get(t, t), int(w)): str(x) for (t, w), x in d.groupby(["posteam", "week"]).game_date.first().items()}
raw = open(os.path.join(REPO, "data", "weekly_stats_active.js"), encoding="utf-8").read(); D = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
acts = defaultdict(dict)
for nm, rec in D.items():
    for w in (rec.get("seasons") or {}).get("2026") or []:
        if isinstance(w.get("fpts"), (int, float)): acts[w.get("wk")][norm(nm)] = float(w["fpts"])
rows = []
for wk in range(1, 19):
    f = os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{wk}.json")
    if not os.path.exists(f): continue
    for p in json.load(open(f, encoding="utf-8"))["players"]:
        if p.get("pos") not in POS4 or not isinstance(p.get("mean"), (int, float)): continue
        nk = norm(p["name"]); a = acts[wk].get(nk); tm = TM.get(p.get("tm"), p.get("tm")); gd = gdate.get((tm, wk))
        if a is None or gd is None: continue
        num = lambda k: float(p[k]) if isinstance(p.get(k), (int, float)) else np.nan
        rows.append(dict(nk=nk, name=p["name"], pos=p["pos"], wk=wk, gd=gd, ship=float(p["mean"]), js=num("jsMean"), nc=num("ncMean"), prop=num("propMean"), act=a))
L = pd.DataFrame(rows); L = L[L.ship >= 3].reset_index(drop=True)
P(f"lock rows W{L.wk.min()}-W{L.wk.max()}: {len(L):,} played player-weeks with a shipped number >= 3 | news items since {min(i['date'] for i in news)}: {len(news)} role-type (riser {sum(i['tag']=='riser' for i in news)}, faller {sum(i['tag']=='faller' for i in news)}, role {sum(i['tag']=='role' for i in news)}, transaction {sum(i['tag']=='transaction' for i in news)})")
# control: position x week mean of (act - proj) and ratio, leaving the news rows in (they are a small share) - computed after tagging below
PERF = re.compile(r"\b(rushed for|caught|hauled|scored|touchdowns?|tds?\b|yards|yds|broke|career[- ]high|led (the )?team|\d+ (catches|receptions|carries|targets))", re.I)
ROLE = re.compile(r"\b(start(er|ing|s)?|first[- ]team|lead back|rb1|wr1|te1|qb1|no\. ?1|snap share|snaps|named|promot|depth chart|workload|role|featured|bell[- ]cow|every[- ]down|committee|split|benched|demot|losing|lost|behind)", re.I)
byp = defaultdict(list)
for _, r in L.iterrows(): byp[r.nk].append(r)
tag_rows = []
for it in news:
    g = sorted([r for r in byp.get(norm(it["player"]), []) if r.gd > it["date"]], key=lambda r: r.wk)[:3]
    h = it.get("headline") or ""; kind = "performance recap" if PERF.search(h) else ("role statement" if ROLE.search(h) else "other")
    first_wk = g[0].wk if g else None
    for j, r in enumerate(g, start=1):
        lag = (datetime.date.fromisoformat(r.gd) - datetime.date.fromisoformat(it["date"])).days
        tag_rows.append(dict(tag=it["tag"], kind=kind, src=it.get("src_type") or "none", date=it["date"], pre=it["date"] < "2026-09-10", gi=j, lag=lag, nk=r.nk, name=r["name"], pos=r.pos, wk=r.wk, ship=r.ship, js=r.js, nc=r.nc, act=r.act, headline=h[:90]))
N = pd.DataFrame(tag_rows)
matched = N.groupby(["nk", "date"]).ngroups if len(N) else 0
P(f"items with at least one graded game: {N.drop_duplicates(['nk','date','headline']).shape[0]} of {len(news)} (the rest: no locked + played game after the item - cut, hurt, deep bench, or too recent)")
N.to_csv(os.path.join(HERE, "_tmp", "role_news_rows.csv"), index=False)
ctl = L.groupby(["pos", "wk"]).apply(lambda x: pd.Series({"c_res": (x.act - x.ship).mean(), "c_ratio": x.act.sum() / x.ship.sum()})).reset_index()
N = N.merge(ctl, on=["pos", "wk"], how="left")
rng = np.random.default_rng(7)
def cell(lab, m, col="ship"):
    x = N[m].sort_values("gi").drop_duplicates(["nk", "wk"])     # one row per player-week inside a cell
    if len(x) < 12: P(f"  {lab:44s} n {len(x):4d}  (too few)"); return None
    ratio = x.act.sum() / x[col].sum(); cr = float(np.average(x.c_ratio, weights=x[col])); rel = ratio / cr
    ex = (x.act - x[col]) - x.c_res
    # player-cluster bootstrap of the relative ratio
    pl = x.nk.unique(); idx = {k: np.where(x.nk.values == k)[0] for k in pl}; bs = []
    av, pv, cv = x.act.values, x[col].values, x.c_ratio.values
    for _ in range(600):
        ii = np.concatenate([idx[k] for k in rng.choice(pl, len(pl))]); bs.append((av[ii].sum() / pv[ii].sum()) / np.average(cv[ii], weights=pv[ii]))
    lo, hi = np.quantile(bs, [.05, .95])
    over = float(np.mean(x.act > x[col] * x.c_ratio))
    P(f"  {lab:44s} n {len(x):4d} p {len(pl):3d} | proj {x[col].mean():5.1f} act {x.act.mean():5.1f} | act/proj {ratio:5.3f} control {cr:5.3f} | vs control x{rel:5.3f} (90% {lo:.2f}-{hi:.2f}) | extra pts {ex.mean():+5.2f} | beat the number {100*over:3.0f}%")
    return rel, lo, hi, len(x)
ALL = np.ones(len(N), bool)
P("\n=== 1. by tag, next 3 games after the item (shipped lock number; 'vs control' = act/proj relative to the same position + week, 1.00 = news adds nothing) ===")
for t in ("riser", "faller", "role", "transaction"): cell(t, N.tag == t)
P("\n=== 2. preseason items (before 09-10; games = weeks 1-3) vs in-season items ===")
for t in ("riser", "faller", "role", "transaction"):
    cell(f"{t} preseason", (N.tag == t) & N.pre); cell(f"{t} in-season", (N.tag == t) & ~N.pre)
P("\n=== 3. by game after the item (in-season items only: is it the first game, or does it last?) ===")
for t in ("riser", "faller", "role"):
    for j in (1, 2, 3): cell(f"{t} in-season game {j}", (N.tag == t) & ~N.pre & (N.gi == j))
P("\n=== 3b. preseason items by game (weeks 1 / 2 / 3) ===")
for t in ("riser", "faller", "role"):
    for j in (1, 2, 3): cell(f"{t} preseason game {j}", (N.tag == t) & N.pre & (N.gi == j))
P("\n=== 4. risers by position and by size of the number ===")
for ps in POS4: cell(f"riser {ps}", (N.tag == "riser") & (N.pos == ps))
for lab, lo_, hi_ in (("proj 3-7", 3, 7), ("proj 7-12", 7, 12), ("proj 12+", 12, 99)):
    cell(f"riser {lab}", (N.tag == "riser") & (N.ship >= lo_) & (N.ship < hi_)); cell(f"riser in-season {lab}", (N.tag == "riser") & ~N.pre & (N.ship >= lo_) & (N.ship < hi_))
P("\n=== 5. risers / role items by what the headline is (in-season) ===")
for t in ("riser", "role"):
    for k in ("performance recap", "role statement", "other"): cell(f"{t} in-season: {k}", (N.tag == t) & ~N.pre & (N.kind == k))
P("  first game only:")
for k in ("performance recap", "role statement"): cell(f"riser in-season game 1: {k}", (N.tag == "riser") & ~N.pre & (N.kind == k) & (N.gi == 1))
P("\n=== 6. source (in-season risers + role) ===")
for s in sorted(N.src.unique()): cell(f"riser+role in-season src {s}", N.tag.isin(["riser", "role"]) & ~N.pre & (N.src == s))
P("\n=== 7. same cells on the MODEL number before the book anchor (jsMean) and on the shadow number (ncMean) ===")
for col in ("js", "nc"):
    M2 = N[col].notna() & (N[col] >= 3)
    for t in ("riser", "faller", "role"):
        cell(f"[{col}] {t} in-season", (N.tag == t) & ~N.pre & M2, col); cell(f"[{col}] {t} in-season game 1", (N.tag == t) & ~N.pre & (N.gi == 1) & M2, col)
P("\n=== 8. would a flat bump have helped? in-season items, game 1 after the item: MAE of shipped x m vs shipped ===")
for t, grid in (("riser", (1.0, 1.03, 1.05, 1.08, 1.10, 1.15)), ("faller", (1.0, .97, .95, .92, .90)), ("role", (1.0, 1.03, 1.05, 1.08, .97, .95))):
    for scope, mm in (("game 1", (N.gi == 1)), ("games 1-3", ALL)):
        x = N[(N.tag == t) & ~N.pre & mm].sort_values("gi").drop_duplicates(["nk", "wk"])
        if len(x) < 12: continue
        wk_ok = [w for w in sorted(x.wk.unique()) if (x.wk == w).sum() >= 4]
        P(f"  {t:7s} {scope:9s} n {len(x):3d} | " + " | ".join(f"x{m:.2f}: MAE {np.abs(x.act - x.ship*m).mean():.3f} ({sum(np.abs(x.act[x.wk==w]-x.ship[x.wk==w]*m).mean() < np.abs(x.act[x.wk==w]-x.ship[x.wk==w]).mean() for w in wk_ok)}/{len(wk_ok)} wks)" for m in grid))
LOG.close()
