#!/usr/bin/env python3
"""
NEXT CANDIDATES screen (Jack 2026-10-02: "anything else we can look into or add for correlation?").
A first look only - which untested ideas show a consistent gap between actual points and the projection. Anything
that shows up still needs the usual leave-one-season-out + forward test before it goes near the engine.

Graded against two numbers on the same rows: the Clay-free shadow (backtest_shadow_next form) and the live-form
harness number ("shipped"). Per segment: rows, actual / projection, t of the residual, seasons on the same side.

  A  the game after a player left early (last game under 60% of his prior snap share), split by how he was listed
  B  rest: short week, long week / after the bye
  C  changed teams during the season (first three games with the new team)
  D  playing through an injury, by body part (listed on the report that week and played)
  E  his quarterback running hot / cold against his own projection (receivers and tight ends)
Log next_candidates.log.
"""
import os, sys
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
from bt_common import load_games
cal = SN.cal; YEARS = SN.YEARS; CACHE = r"E:\MyFantasyFootball\pbp_cache"

def main():
    log = open(os.path.join(HERE, "next_candidates.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n"); log.flush()
    X = SN.setup(); n = X["n"]; act, year, wk, pos, g, name, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["name"], X["team"]
    SH = SN.shadow(X)
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = X["A"]["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    LV = colv("shipped"); LV = np.where(np.isnan(LV), SH, LV)
    finw = np.where(year <= 2020, 17, 18); ok = (wk != finw) & (SH >= 3)
    allr_sh = act[ok].sum() / SH[ok].sum(); allr_lv = act[ok].sum() / LV[ok].sum()
    P(f"=== next candidates: {int(ok.sum()):,} player-weeks 2019-25; everyone: actual / shadow {allr_sh:.3f}, actual / live-form {allr_lv:.3f} ===")
    def seg(lab, m, minn=40):
        m = m & ok
        if m.sum() < minn: P(f"    {lab:46s} n {int(m.sum()):4d} (too few)"); return
        out = f"    {lab:46s} n {int(m.sum()):5d}  actual {act[m].mean():5.2f}"
        for tag, pr in (("shadow", SH), ("live-form", LV)):
            r = act[m] - pr[m]; t = r.mean() / (r.std(ddof=1) / np.sqrt(m.sum()))
            ys = [(act[m & (year == y)] - pr[m & (year == y)]).mean() for y in YEARS if (m & (year == y)).sum() >= 6]
            side = sum(1 for v in ys if np.sign(v) == np.sign(r.mean()))
            out += f"  | / {tag} {act[m].sum()/pr[m].sum():.3f} (t {t:+.1f}, {side}/{len(ys)})"
        P(out)

    seq = defaultdict(list)
    for i in range(n): seq[(name[i], pos[i], int(year[i]))].append(i)
    prev = np.full(n, -1); nprev = np.zeros(n, int)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i])
        for a, i in enumerate(ix):
            nprev[i] = a
            if a: prev[i] = ix[a - 1]
    hasp = prev >= 0; pv = np.maximum(prev, 0)

    # ---------------- A exit games ----------------
    P("\n--- A  THE GAME AFTER HE LEFT EARLY (last game under 60% of the snap share he had before it, 50%+ before) ---")
    l1 = X["snap_l1"]; std_before = np.where(hasp, X["snap_std"][pv], np.nan)
    repq, dnp, lim = colv("rep_q") == 1, colv("prac_dnp") > 0, colv("prac_lim") > 0
    exitm = ~np.isnan(std_before) & (std_before >= 50) & (l1 < 0.6 * std_before)
    for ps in ("RB", "WR", "TE"):
        e = exitm & (pos == ps)
        seg(f"{ps}: all", e)
        seg(f"{ps}: listed Questionable", e & repq, 25)
        seg(f"{ps}: missed or limited practice, not Q", e & ~repq & (dnp | lim), 25)
        seg(f"{ps}: clean report", e & ~repq & ~dnp & ~lim, 25)
    seg("for scale: Questionable, no early exit (RB/WR/TE)", repq & ~exitm & np.isin(pos, ["RB", "WR", "TE"]))

    # ---------------- B rest ----------------
    P("\n--- B  REST (days since the team's last game) ---")
    rest = np.full(n, np.nan); away_long = np.zeros(n, bool)
    for Y in YEARS:
        games = load_games(Y); bt = defaultdict(list)
        for (t, w), gm in games.items():
            if isinstance(gm, dict) and gm.get("date"): bt[t].append((w, pd.Timestamp(gm["date"])))
        gap = {}
        for t, L in bt.items():
            L.sort()
            for a in range(1, len(L)): gap[(t, L[a][0])] = (L[a][1] - L[a - 1][1]).days
        for i in np.where(year == Y)[0]:
            v = gap.get((team[i], int(wk[i])))
            if v is not None: rest[i] = v
    for ps in ("QB", "RB", "WR", "TE"):
        m = pos == ps
        seg(f"{ps}: short week (4-5 days)", m & (rest <= 5))
        seg(f"{ps}: normal (6-8 days)", m & (rest >= 6) & (rest <= 8))
        seg(f"{ps}: long (9-11 days)", m & (rest >= 9) & (rest <= 11))
        seg(f"{ps}: after the bye (12+ days)", m & (rest >= 12))

    # ---------------- C changed teams in season ----------------
    P("\n--- C  CHANGED TEAMS DURING THE SEASON ---")
    moved_at = np.full(n, 99)
    for ix in seq.values():
        since = None
        for a, i in enumerate(ix):
            if a and team[i] != team[ix[a - 1]]: since = 0
            if since is not None: moved_at[i] = since; since += 1
    for ps in ("RB", "WR", "TE"):
        seg(f"{ps}: first game with the new team", (pos == ps) & (moved_at == 0), 15)
        seg(f"{ps}: games 2-3 with the new team", (pos == ps) & (moved_at >= 1) & (moved_at <= 2), 15)
        seg(f"{ps}: game 4+ with the new team", (pos == ps) & (moved_at >= 3) & (moved_at < 99), 15)
    seg("all positions: first three games", (moved_at <= 2), 15)

    # ---------------- D injury type when active ----------------
    P("\n--- D  PLAYING THROUGH AN INJURY, by body part (on that week's report and played) ---")
    inj = {}
    for Y in YEARS:
        f = os.path.join(CACHE, f"injuries_{Y}.parquet")
        if not os.path.exists(f): continue
        d = pd.read_parquet(f, columns=["week", "game_type", "full_name", "report_primary_injury", "report_status", "practice_primary_injury", "practice_status"])
        d = d[d.game_type == "REG"]
        for r in d.itertuples(index=False):
            part = r.report_primary_injury if isinstance(r.report_primary_injury, str) and r.report_primary_injury else r.practice_primary_injury
            if not isinstance(part, str) or not part: continue
            inj[(Y, int(r.week), cal.norm(str(r.full_name)))] = (part.split(",")[0].strip().lower(), r.report_status if isinstance(r.report_status, str) else "")
    part = np.array([inj.get((int(year[i]), int(wk[i]), cal.norm(name[i])), ("", ""))[0] for i in range(n)])
    stat = np.array([inj.get((int(year[i]), int(wk[i]), cal.norm(name[i])), ("", ""))[1] for i in range(n)])
    P(f"  rows on a report {int(((part != '') & ok).sum()):,}; listed Questionable {int(((stat == 'Questionable') & ok).sum()):,}")
    GR = {"hamstring": ["hamstring"], "ankle": ["ankle"], "knee": ["knee"], "calf / achilles": ["calf", "achilles"], "groin / hip / quad": ["groin", "hip", "quadricep", "quad", "thigh"],
          "foot / toe": ["foot", "toe"], "shoulder": ["shoulder"], "back / ribs / chest": ["back", "rib", "ribs", "chest", "oblique", "abdomen"], "hand / wrist / finger": ["hand", "wrist", "finger", "thumb"],
          "concussion": ["concussion"], "rest / not injury": ["not injury related - resting player", "rest", "not injury related", "nir - resting vet"], "illness": ["illness"]}
    skill = np.isin(pos, ["RB", "WR", "TE"])
    seg("RB / WR / TE: on the report, any", skill & (part != ""))
    seg("RB / WR / TE: Questionable, any", skill & (stat == "Questionable"))
    for lab, keys in GR.items():
        m = skill & np.isin(part, keys)
        seg(f"{lab}: on the report", m)
        seg(f"{lab}: Questionable", m & (stat == "Questionable"), 30)
    for ps in ("RB", "WR"):
        for lab in ("hamstring", "ankle", "knee"):
            seg(f"{ps} {lab}: Questionable", (pos == ps) & np.isin(part, GR[lab]) & (stat == "Questionable"), 25)
    qbm = pos == "QB"
    for lab in ("shoulder", "hand / wrist / finger", "ankle", "knee", "back / ribs / chest"):
        seg(f"QB {lab}: on the report", qbm & np.isin(part, GR[lab]), 25)

    # ---------------- E passer form ----------------
    P("\n--- E  HIS QUARTERBACK HOT / COLD vs his own projection (receivers and tight ends, 3+ team games in) ---")
    qrow = {}
    for i in np.where(qbm)[0]:
        k = (int(year[i]), team[i], int(wk[i]))
        if k not in qrow or SH[i] > SH[qrow[k]]: qrow[k] = i
    form = np.full(n, np.nan)
    for i in np.where(np.isin(pos, ["WR", "TE"]))[0]:
        q = qrow.get((int(year[i]), team[i], int(wk[i])))
        if q is not None and g[q] >= 3 and X["prior"][q] > 5: form[i] = X["ppg"][q] / X["prior"][q] - 1
    for ps in ("WR", "TE"):
        m = (pos == ps) & ~np.isnan(form)
        if m.sum() > 200:
            r = (act - SH)[m & ok]; P(f"    {ps}: correlation of quarterback form with the receiver's miss: r {np.corrcoef(form[m & ok], r)[0, 1]:+.3f} (n {int((m & ok).sum())})")
        seg(f"{ps}: quarterback 20%+ under his projection", m & (form <= -0.20))
        seg(f"{ps}: quarterback within 20%", m & (form > -0.20) & (form < 0.20))
        seg(f"{ps}: quarterback 20%+ over his projection", m & (form >= 0.20))
    log.close()

if __name__ == "__main__":
    main()
