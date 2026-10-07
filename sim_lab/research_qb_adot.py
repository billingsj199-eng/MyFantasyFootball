#!/usr/bin/env python3
"""
QB DEPTH OF TARGET AS RECEIVER CONTEXT (Jack 2026-10-07: "the team totals were extremely low for a reason and adot by
the qbs").  When a receiver's QB changes, does the replacement's depth of target (vs the regular's) tell us how the
receiver's role changes - deep receivers hurt by a check-down passer, short-area receivers helped?  RESEARCH.

Data: nflverse play-by-play 2019-26 (pbp_cache/play_by_play_<yr>.csv.gz): per passer per week attempts, air yards,
CPOE, EPA; per receiver per season aDOT. Rows: the graded-dock rows (WR/TE, regular QB not starting, or the replacement
already in 2+ weeks), live form 2019-25. Descriptive splits (receiver depth x replacement aDOT vs regular), then two
small rules tested LOYO. Also prints the 2026 Atlanta case (Rush vs Penix aDOT, London's aDOT). Log qb_adot.log.
"""
import os, sys, re, warnings
from collections import defaultdict, Counter
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_qb_injury_usage as QI
NW = QI.NW; cal = QI.cal; YEARS = QI.YEARS; POS4 = QI.POS4; FWD = QI.FWD
CACHE = r"E:\MyFantasyFootball\pbp_cache"
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "qb_adot.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
TM_ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI"}


def abbrev(nm):
    """'Cooper Rush' -> 'c.rush' (pbp passer_player_name style), suffix-insensitive"""
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\.?$", "", nm.strip(), flags=re.I).strip()
    parts = n.replace(".", "").split()
    if len(parts) < 2: return n.lower()
    return (parts[0][0] + "." + "".join(parts[1:])).lower().replace("'", "")


def load_pbp(years):
    qb = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0])   # (Y, team, wk, passer_abbrev) -> [att, air, cpoe_sum, epa_sum, n_cpoe]
    rc = defaultdict(lambda: [0, 0.0])                # (Y, receiver_gsis) -> [targets, air]
    rcw = defaultdict(lambda: [0, 0.0])               # (Y, receiver_gsis, wk)
    for Y in years:
        p = os.path.join(CACHE, f"play_by_play_{Y}.csv.gz")
        if not os.path.exists(p): continue
        d = pd.read_csv(p, compression="gzip", usecols=["season", "week", "posteam", "pass_attempt", "air_yards", "cpoe", "epa", "passer_player_name", "receiver_player_id", "season_type"], low_memory=False)
        d = d[(d.pass_attempt == 1) & (d.season_type == "REG") & d.passer_player_name.notna() & d.air_yards.notna()]
        for tm, wk, pn, ay, cp, ep, rid in zip(d.posteam, d.week, d.passer_player_name, d.air_yards, d.cpoe, d.epa, d.receiver_player_id):
            k = (Y, TM_ALIAS.get(str(tm), str(tm)), int(wk), str(pn).lower().replace("'", "").replace(" ", ""))
            a = qb[k]; a[0] += 1; a[1] += float(ay)
            if pd.notna(cp): a[2] += float(cp); a[4] += 1
            if pd.notna(ep): a[3] += float(ep)
            if isinstance(rid, str):
                r = rc[(Y, rid)]; r[0] += 1; r[1] += float(ay); r2 = rcw[(Y, rid, int(wk))]; r2[0] += 1; r2[1] += float(ay)
        P(f"  pbp {Y}: {len(d):,} pass attempts")
    return qb, rc, rcw


def main():
    qb, rc, rcw = load_pbp(YEARS + [2026])
    # season-to-date passer aDOT lookup: (Y, abbrev) over weeks < wk (all teams), with prior-season fallback
    by_passer = defaultdict(list)
    for (Y, tm, wk, pn), a in qb.items(): by_passer[(Y, pn)].append((wk, a[0], a[1], a[2], a[3], a[4]))
    def qb_adot(Y, nm, wk, min_att=40):
        pn = abbrev(nm)
        for Yq in (Y, Y - 1, Y - 2):
            rows = [r for r in by_passer.get((Yq, pn), []) if Yq < Y or r[0] < wk]
            att = sum(r[1] for r in rows); air = sum(r[2] for r in rows)
            if att >= min_att: return air / att, att, Yq
        return np.nan, 0, None
    X = QI.setup(); n = X["n"]
    act, year, wk, pos, g, adp, name, team, pid = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["team"], X["pid"]
    F = X["F"]; finw = np.where(year <= 2020, 17, 18); final = wk == finw; adpx = np.where(np.isnan(adp), 999.0, adp); top150 = adp <= 150
    games, roster, starter, team_weeks = QI.build_games(X)
    BASE = np.maximum(0.0, QI.live_base(X, X["ppg"], g.astype(float), X["xfp"], X["snap"])[0] * X["chain"] + QI.live_base(X, X["ppg"], g.astype(float), X["xfp"], X["snap"])[1])
    okN = (g >= 1) & ~final & ~X["inh"]; RECV = np.isin(pos, ("WR", "TE"))
    reg_ad = np.full(n, np.nan); rep_ad = np.full(n, np.nan); rcv_ad = np.full(n, np.nan); outrow = np.zeros(n, bool); newrow = np.zeros(n, bool); regnm = [None] * n; repnm = [None] * n
    for i in range(n):
        if not RECV[i] or not team[i] or not okN[i]: continue
        Y = int(year[i]); tm_ = team[i]
        prior_w = [w for w in team_weeks.get((Y, tm_), []) if w < wk[i]]
        s_now = starter.get((Y, tm_, int(wk[i])))
        if s_now is None or not prior_w: continue
        cnt = Counter(starter[(Y, tm_, w)] for w in prior_w); top = max(cnt.values()); cands = [q for q, c in cnt.items() if c == top]
        r_ = cands[0] if len(cands) == 1 else max(cands, key=lambda q: max(w for w in prior_w if starter[(Y, tm_, w)] == q))
        if s_now == r_: continue
        last2 = [starter[(Y, tm_, w)] for w in prior_w[-2:]]
        newrow[i] = len(last2) == 2 and all(q == s_now for q in last2); outrow[i] = not newrow[i]
        regnm[i], repnm[i] = r_, s_now
        reg_ad[i] = qb_adot(Y, r_, int(wk[i]))[0]; rep_ad[i] = qb_adot(Y, s_now, int(wk[i]))[0]
        # receiver aDOT season to date (weeks < wk), else prior season
        if isinstance(pid[i], str):
            t = sum(rcw[(Y, pid[i], w)][0] for w in range(1, int(wk[i]))); a = sum(rcw[(Y, pid[i], w)][1] for w in range(1, int(wk[i])))
            if t >= 15: rcv_ad[i] = a / t
            elif rc.get((Y - 1, pid[i]), [0, 0])[0] >= 30: rcv_ad[i] = rc[(Y - 1, pid[i])][1] / rc[(Y - 1, pid[i])][0]
    m_all = (outrow | newrow) & ~np.isnan(reg_ad) & ~np.isnan(rep_ad) & ~np.isnan(rcv_ad)
    P(f"\nrows with a QB change and aDOT for both QBs and the receiver: {int(m_all.sum())} (out this week {int((m_all & outrow).sum())}, replacement in 2+ weeks {int((m_all & newrow).sum())}); top-150 {int((m_all & top150).sum())}")
    dd = rep_ad - reg_ad
    P(f"replacement aDOT - regular aDOT: mean {np.nanmean(dd[m_all]):+.2f} yds, quartiles {np.nanpercentile(dd[m_all], 25):+.2f} / {np.nanpercentile(dd[m_all], 50):+.2f} / {np.nanpercentile(dd[m_all], 75):+.2f}")
    def ratio(m): return f"act/live {act[m].sum()/BASE[m].sum():.3f} n{int(m.sum())}" if m.sum() >= 12 else f"n{int(m.sum())}"
    P("\n--- actual / live by receiver depth x replacement aDOT vs regular (WR + TE, all QB-change rows) ---")
    DEP = [("deep receiver (aDOT >= 11)", rcv_ad >= 11), ("mid (8-11)", (rcv_ad >= 8) & (rcv_ad < 11)), ("short (< 8)", rcv_ad < 8)]
    DQ = [("replacement throws SHORTER (-1.5 yds+)", dd <= -1.5), ("similar", (dd > -1.5) & (dd < 1.5)), ("replacement throws DEEPER (+1.5+)", dd >= 1.5)]
    for dl, dm in DEP:
        P(f"  {dl:30s} " + " | ".join(f"{ql}: {ratio(m_all & dm & qm)}" for ql, qm in DQ))
    P("  by position:")
    for ps in ("WR", "TE"):
        P(f"  {ps:30s} " + " | ".join(f"{ql}: {ratio(m_all & (pos == ps) & qm)}" for ql, qm in DQ))
    P("  top-150 only:")
    for dl, dm in DEP:
        P(f"  {dl:30s} " + " | ".join(f"{ql}: {ratio(m_all & top150 & dm & qm)}" for ql, qm in DQ))
    P("  out-this-week rows only:")
    for dl, dm in DEP:
        P(f"  {dl:30s} " + " | ".join(f"{ql}: {ratio(m_all & outrow & dm & qm)}" for ql, qm in DQ))
    # interaction: deep receiver x shorter passer vs the rest
    P("\n--- the two cells Jack's read predicts: deep receiver + shorter passer (hurt) and short receiver + deeper passer... and the mirror ---")
    hurt = m_all & (rcv_ad >= 10) & (dd <= -1.5); help_ = m_all & (rcv_ad >= 10) & (dd >= 1.5); shortshort = m_all & (rcv_ad < 8) & (dd <= -1.5)
    P(f"  deep receiver, shorter replacement: {ratio(hurt)} | deep receiver, deeper replacement: {ratio(help_)} | short receiver, shorter replacement: {ratio(shortshort)}")
    # rules
    mse = lambda p, m: float(np.mean((p[m] - act[m]) ** 2)) if m.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    def test(title, fam, tm):
        preds = {"off": BASE, **fam}; names = list(preds)
        P(f"\n=== {title}: rows {int(tm.sum())}, act/live {act[tm].sum()/BASE[tm].sum():.3f} ===")
        for k in names[1:]:
            wins = sum(1 for y in YEARS if (tm & (year == y)).sum() >= 6 and mse(preds[k], tm & (year == y)) < mse(BASE, tm & (year == y)) - 1e-12)
            P(f"    {k:50s} {100*(mse(preds[k], tm)/mse(BASE, tm)-1):+6.2f}% ({wins}/7)  act/pred {act[tm].sum()/preds[k][tm].sum():.3f}")
        pick = lambda yrs: min(names, key=lambda k: mse(preds[k], tm & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = BASE.copy()
            for tr_, te in folds:
                k = pick(tr_); picks.append(k); m = year == te; pr[m] = preds[k][m]; wins += mse(preds[k], tm & m) < mse(BASE, tm & m) - 1e-12
            tem = np.isin(year, [te for _, te in folds]); return 100 * (mse(pr, tm & tem) / mse(BASE, tm & tem) - 1), wins, picks
        lo = run(LOSO); fw = run(FORW)
        P(f"    LOYO {lo[0]:+.2f}% {lo[1]}/7 picks {lo[2]}"); P(f"    FWD  {fw[0]:+.2f}% {fw[1]}/4 picks {fw[2]}")
    def mult_rule(k_hurt, k_help, deep=10.0, step=1.5):
        out = BASE.copy()
        mh = m_all & (rcv_ad >= deep) & (dd <= -step); mp = m_all & (rcv_ad >= deep) & (dd >= step)
        out[mh] *= k_hurt; out[mp] *= k_help; return out
    test("RULE A: deep receiver (aDOT >= 10) x shorter replacement docked / deeper replacement boosted", {f"x{kh} / x{kp}": mult_rule(kh, kp) for kh, kp in ((0.9, 1.0), (0.85, 1.0), (0.9, 1.05), (0.85, 1.1))}, m_all)
    def slope_rule(b):
        out = BASE.copy(); m = m_all
        out[m] = BASE[m] * np.clip(1 + b * dd[m] * np.clip((rcv_ad[m] - 8.0) / 4.0, -1, 1), 0.7, 1.3); return out
    test("RULE B: multiplier = 1 + b x (aDOT change) x (receiver depth above 8 yds, scaled)", {f"b {b}": slope_rule(b) for b in (0.01, 0.02, 0.03)}, m_all)
    # Atlanta 2026
    P("\n=== 2026 ATLANTA: passer aDOT by week (season to date) and Drake London ===")
    for nm in ("Cooper Rush", "Michael Penix Jr.", "Michael Penix"):
        pn = abbrev(nm); rows = sorted([(k[2], a[0], a[1], a[2], a[4], a[3]) for k, a in qb.items() if k[0] == 2026 and k[3] == pn])
        if rows: P(f"  {nm:18s} " + " | ".join(f"wk{w}: {att} att, aDOT {air/att:.1f}, CPOE {cp/max(1, nc):+.1f}, EPA/att {ep/att:+.2f}" for w, att, air, cp, nc, ep in rows))
        else: P(f"  {nm}: no 2026 attempts found under '{pn}'")
    for nm, Y in (("Michael Penix Jr.", 2025), ("Kirk Cousins", 2025), ("Cooper Rush", 2025), ("Tua Tagovailoa", 2025)):
        a, att, Yq = qb_adot(2026, nm, 1)
        P(f"  {nm:18s} aDOT entering 2026 {a:.1f} over {att} att (from {Yq})" if att else f"  {nm}: no history")
    lid = None
    for i in range(n):
        if name[i] == "Drake London": lid = pid[i]; break
    if lid:
        for Y in (2024, 2025, 2026):
            t, a = rc.get((Y, lid), [0, 0.0]); P(f"  Drake London aDOT {Y}: {a/t:.1f} over {t} targets" if t else f"  Drake London {Y}: no targets found")
        P("  London 2026 by week: " + " | ".join(f"wk{w}: {rcw[(2026, lid, w)][0]} tgt aDOT {rcw[(2026, lid, w)][1]/rcw[(2026, lid, w)][0]:.1f}" for w in range(1, 6) if rcw.get((2026, lid, w), [0])[0]))
    LOG.close()


if __name__ == "__main__":
    main()
