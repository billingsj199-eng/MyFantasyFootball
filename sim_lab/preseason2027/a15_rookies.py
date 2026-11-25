#!/usr/bin/env python3
"""
A15 - PROVISIONAL 2027 rookie class from Jack's JM scores (Jack 2026-11-23 "Yes, use JM": option A, the scores as they are,
including their draft-capital term, which for undrafted classes comes from an outside consensus mock draft).
Read-only on the site data. No ADP. Veterans are untouched.

Method (fixed constants, no tuning on 2027):
  past prospects = data/jm_scores.json entries with draft year 2015-2025; outcome = rookie season from player_weeks
  (games with a stat row, half-PPR points; never on the field = 0 games / 0 points), actual round from draft_picks.
  For a 2027 prospect at position p with score j: the K=20 past prospects at p with the nearest JM give the projection
  (mean total incl. zeros, mean games, ppg = total / games), the implied round (median, 25-75%), P(drafted);
  the range uses the K2=40 nearest (wider window, see A15) for the 10th / 90th percentile of season totals.
Backtest (leave-one-class-out, classes 2016-2025) vs the post-draft prior (the v5 model's walk-forward rookie per-game)
and a flat position average. Past JM includes the REAL pick, so (a) is an UPPER BOUND on pre-draft placement.

  python a15_rookies.py backtest     -> a15_backtest.log
  python a15_rookies.py insert       -> adds the rookies to output/2027_inhouse_early.csv/.md (v8 form); log a15_insert.log
"""
import os, sys, json, re, warnings
import numpy as np, pandas as pd
from scipy.stats import spearmanr
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM

SITE = r"E:\MyFantasyFootball\MyFantasyFootball Files"
JM_FILE = os.path.join(SITE, "data", "jm_scores.json")
COMBINE = os.path.join(SITE, "data", "combine_data.js")
CS_BASE = os.path.join(SITE, "data", "college_stats.js"); CS_DEVY = os.path.join(SITE, "data", "college_stats_devy.js")
BDAY = os.path.join(SITE, "scripts", "devy_birthdays_cache.json")
OUT = os.path.join(HERE, "output")
K, K2 = 20, 40
CLASS_YEAR = 2027
POS4 = ("QB", "RB", "WR", "TE")
LOG = None


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def load_jm(path=JM_FILE):
    d = json.load(open(path, encoding="utf-8"))
    rows = [{"name": n, "jm": v.get("jm"), "yr": v.get("yr"), "pos": v.get("pos")} for n, v in d["scores"].items()]
    J = pd.DataFrame(rows); J = J[J.pos.isin(POS4) & J.jm.notna() & J.yr.notna()].copy()
    J["yr"] = J.yr.astype(int); J["key"] = J.name.map(PM.nrm)
    return J, d.get("exported_at")


def outcomes(J):
    W = pd.read_parquet(os.path.join(PM.DATA, "player_weeks.parquet"), columns=["season", "week", "pid", "display_name", "half", "rec", "position"])
    W = W[W.week < W.season.map(PM.final_week)]
    W["key"] = W.display_name.fillna("").map(PM.nrm)
    S = W.groupby(["season", "key"]).agg(games=("week", "nunique"), total=("half", "sum"), rec=("rec", "sum"), pid=("pid", "first")).reset_index()
    J = J.merge(S.rename(columns={"season": "yr"}), on=["yr", "key"], how="left")
    J["games"] = J.games.fillna(0); J["total"] = J.total.fillna(0); J["rec"] = J.rec.fillna(0)
    dp = pd.read_parquet(os.path.join(PM.CACHE, "draft_picks.parquet"), columns=["season", "round", "pick", "pfr_player_name", "gsis_id"])
    dp["key"] = dp.pfr_player_name.fillna("").map(PM.nrm)
    byname = dp.drop_duplicates(["season", "key"]).set_index(["season", "key"])["round"]
    J["round"] = [byname.get((y, k), np.nan) for y, k in zip(J.yr, J.key)]
    J["round"] = J["round"].fillna(8)   # 8 = undrafted
    return J


def knn(past, pos, j, k):
    c = past[past.pos == pos]
    if len(c) == 0: return c
    return c.iloc[np.argsort(np.abs(c.jm.values - j), kind="stable")[:k]]


def project(past, pos, j):
    nb = knn(past, pos, j, K); nb2 = knn(past, pos, j, K2)
    g = nb.games.mean(); tot = nb.total.mean()
    played = nb[nb.games >= 4]
    return {"games": g, "total": tot, "ppg": tot / g if g > 0 else 0.0,
            "ppg_cond": (played.total / played.games).mean() if len(played) else np.nan,
            "tot_p10": float(np.quantile(nb2.total, .1)), "tot_p90": float(np.quantile(nb2.total, .9)),
            "rd_med": float(np.median(nb["round"])), "rd_lo": float(np.quantile(nb["round"], .25)), "rd_hi": float(np.quantile(nb["round"], .75)),
            "p_drafted": float((nb["round"] <= 7).mean()),
            # format columns (2026-11-23): receptions from the same K neighbours; PPR / STD ranges from the K2 neighbours'
            # own PPR / STD season totals (half +/- .5 x their receptions), not a shift of the half-PPR range
            "rec": nb.rec.mean(), "rec_pg": nb.rec.mean() / g if g > 0 else 0.0,
            "tot_p10_ppr": float(np.quantile(nb2.total + .5 * nb2.rec, .1)), "tot_p90_ppr": float(np.quantile(nb2.total + .5 * nb2.rec, .9)),
            "tot_p10_std": float(np.quantile(nb2.total - .5 * nb2.rec, .1)), "tot_p90_std": float(np.quantile(nb2.total - .5 * nb2.rec, .9))}


def rd_label(m, lo, hi):
    f = lambda r: "UDFA" if r >= 8 else f"R{int(round(r))}"
    return f"{f(m)} ({f(lo)}-{f(hi)})"


def backtest():
    J, exp = load_jm(); H = outcomes(J[J.yr.between(2015, 2025)])
    P(f"=== A15 backtest: JM placement vs post-draft prior vs flat average (classes 2016-2025, leave-one-class-out) ===")
    P(f"  jm_scores.json exported {exp}; past prospects {len(H)}; matched to a rookie season with 1+ game: {int((H.games > 0).sum())}")
    P("  NOTE: past JM includes each player's REAL draft pick, so the JM column is an UPPER BOUND on pre-draft placement.")
    D = pd.read_parquet(os.path.join(HERE, "data", "rb_a14_D.parquet"), columns=["key", "season", "pos", "rookie", "pg", "g_use", "G"])
    D = D[D.rookie == 1].drop_duplicates(["season", "key"]).rename(columns={"season": "yr"})
    rows = []
    for y in range(2016, 2026):
        past = H[H.yr != y]; prev = H[H.yr < y]
        for r in H[H.yr == y].itertuples(index=False):
            pr = project(past, r.pos, r.jm)
            flat = prev[(prev.pos == r.pos) & (prev.games >= 4)]
            rows.append({"yr": y, "name": r.name, "pos": r.pos, "jm": r.jm, "games": r.games, "total": r.total, "round": r["round"] if isinstance(r, dict) else getattr(r, "_asdict")()["round"],
                         "a_ppg": pr["ppg_cond"], "a_tot": pr["total"], "lo": pr["tot_p10"], "hi": pr["tot_p90"],
                         "c_ppg": (flat.total / flat.games).mean() if len(flat) else np.nan, "c_tot": prev[prev.pos == r.pos].total.mean() if len(prev) else np.nan, "key": r.key})
    B = pd.DataFrame(rows).merge(D[["yr", "key", "pg", "g_use", "G"]], on=["yr", "key"], how="left")
    B["b_ppg"] = B.pg; B["b_tot"] = B.pg * B.g_use * B.G
    B["act_ppg"] = np.where(B.games > 0, B.total / B.games.replace(0, np.nan), np.nan)
    P("\n  per-game, rookies with 4+ games AND a post-draft prior row (common rows): games-weighted MAE / rank corr within class")
    P("| pos | n | (a) JM upper bound | (b) post-draft prior | (c) flat average | gap a-b (MAE) |")
    P("|---|---|---|---|---|---|")
    for p in POS4:
        m = (B.pos == p) & (B.games >= 4) & B.b_ppg.notna() & B.a_ppg.notna()
        x = B[m]
        def mae(c): return float(np.sum(x.games * np.abs(x[c] - x.act_ppg)) / x.games.sum())
        def rh(c): return float(np.nanmean([spearmanr(g[c], g.act_ppg).correlation for _, g in x.groupby("yr") if len(g) >= 5])) if c != "c_ppg" else float("nan")
        P(f"| {p} | {len(x)} | {mae('a_ppg'):.2f} / {rh('a_ppg'):.2f} | {mae('b_ppg'):.2f} / {rh('b_ppg'):.2f} | {mae('c_ppg'):.2f} / - | {mae('a_ppg')-mae('b_ppg'):+.2f} |")
    P("\n  season totals, every prospect in the class (non-players = 0): hit rate on each class's top 6 / top 12 rookies at the position")
    P("| pos | n | (a) JM top6 / top12 | (b) post-draft top6 / top12 (prospects with a model row) | totals MAE (a) | (c) flat MAE |")
    P("|---|---|---|---|---|---|")
    for p in POS4:
        x = B[B.pos == p]
        def hits(col, k, sub):
            v = []
            for _, g in sub.groupby("yr"):
                if len(g) < k + 2: continue
                v.append(len(set(g.nlargest(k, col).name) & set(g.nlargest(k, "total").name)) / k)
            return np.mean(v) if v else np.nan
        xb = x[x.b_tot.notna()]
        P(f"| {p} | {len(x)} | {hits('a_tot', 6, x):.2f} / {hits('a_tot', 12, x):.2f} | {hits('b_tot', 6, xb):.2f} / {hits('b_tot', 12, xb):.2f} (n {len(xb)}) | {np.mean(np.abs(x.a_tot - x.total)):.1f} | {np.mean(np.abs(x.c_tot - x.total)):.1f} |")
    P("\n  10th-90th range coverage of season totals (K2 = 40 nearest JM, leave-one-class-out; target 80%)")
    for p in POS4:
        x = B[B.pos == p]; cov = ((x.total >= x.lo) & (x.total <= x.hi)).mean()
        P(f"   {p}: {cov*100:.0f}% (n {len(x)}); median width {np.median(x.hi - x.lo):.0f} pts")
    for p in POS4:
        x = B[(B.pos == p) & (B.yr >= 2020)]
        P(f"   {p} classes 2020-25 only: {((x.total >= x.lo) & (x.total <= x.hi)).mean()*100:.0f}% (n {len(x)})")
    B.to_parquet(os.path.join(HERE, "data", "a15_backtest_rows.parquet"), index=False)


def college_years():
    yrs = {}
    for f in (CS_BASE, CS_DEVY):
        s = open(f, encoding="utf-8").read()
        for m in re.finditer(r'"([^"]+)":\[(.*?)\](?=,\s*"|\s*[,}]\s*\n|\s*};)', s, re.S):
            ys = [int(v) for v in re.findall(r"yr:(\d{4})", m.group(2))]
            if ys: yrs.setdefault(m.group(1), set()).update(ys)
    return yrs


def combine_info():
    s = open(COMBINE, encoding="utf-8").read()
    out = {}
    for m in re.finditer(r'"([^"]+)":\{([^{}]*)\}', s):
        body = m.group(2); g = lambda k: (re.search(rf'"{k}":"?([^",]*)"?', body) or [None, None])[1]
        out[m.group(1)] = {"school": g("school"), "eligYr": g("eligYr"), "pos": g("pos")}
    return out


def rookies_2027(J=None):
    J0, exp = load_jm() if J is None else J
    H = outcomes(J0[J0.yr.between(2015, 2025)])
    cls = J0[J0.yr == CLASS_YEAR].copy()
    CY = college_years(); CB = combine_info()
    try: bd = json.load(open(BDAY, encoding="utf-8"))
    except Exception: bd = {}
    rows = []
    for r in cls.itertuples(index=False):
        pr = project(H, r.pos, r.jm)
        seasons = sorted(CY.get(r.name, []))
        n_seas = (2026 - seasons[0] + 1) if seasons else np.nan
        status = "senior" if (n_seas == n_seas and n_seas >= 4) else ("likely" if (n_seas == 3 and r.jm >= 60) else "uncertain")
        b = (bd.get(r.name) or {}).get("birth")
        age = (pd.Timestamp("2027-09-01") - pd.Timestamp(b)).days / 365.25 if b else np.nan
        rows.append({"name": r.name, "pos": r.pos, "team": "", "provisional": 1, "jm": r.jm, "school": (CB.get(r.name) or {}).get("school") or "",
                     "class_status": status, "college_seasons": n_seas, "implied_round": rd_label(pr["rd_med"], pr["rd_lo"], pr["rd_hi"]),
                     "p_drafted": round(pr["p_drafted"], 2), "ppg": round(pr["ppg"], 2), "games": round(pr["games"], 1), "total": round(pr["total"], 1),
                     "tot_p10": round(pr["tot_p10"], 1), "tot_p90": round(pr["tot_p90"], 1), "age": round(age, 1) if age == age else np.nan,
                     "rec_pg": round(pr["rec_pg"], 3),
                     "ppg_ppr": round((pr["total"] + .5 * pr["rec"]) / pr["games"], 2) if pr["games"] > 0 else 0.0,
                     "total_ppr": round(pr["total"] + .5 * pr["rec"], 1),
                     "tot_p10_ppr": round(pr["tot_p10_ppr"], 1), "tot_p90_ppr": round(pr["tot_p90_ppr"], 1),
                     "ppg_std": round(max(0.0, (pr["total"] - .5 * pr["rec"]) / pr["games"]), 2) if pr["games"] > 0 else 0.0,
                     "total_std": round(max(0.0, pr["total"] - .5 * pr["rec"]), 1),
                     "tot_p10_std": round(max(0.0, pr["tot_p10_std"]), 1), "tot_p90_std": round(max(0.0, pr["tot_p90_std"]), 1)})
    return pd.DataFrame(rows), exp


def rank_all(R):
    import sf_view_a10 as SV
    REPL = {"QB": 12, "RB": 31, "WR": 41, "TE": 12}
    R["pos_rank"] = R.sort_values(["total", "name"], ascending=[False, True]).groupby("pos").cumcount().reindex(R.index) + 1
    repl = {ps: R[R.pos == ps].sort_values("total", ascending=False).total.values[min(REPL[ps], (R.pos == ps).sum() - 1)] for ps in REPL}
    R["vor"] = R.total - R.pos.map(repl)
    R = R.sort_values(["vor", "total", "name"], ascending=[False, False, True]).reset_index(drop=True); R["rank"] = np.arange(1, len(R) + 1)
    R = SV.sf_cols(R)
    R = SV.format_ranks(R)   # rank_ppr / pos_rank_ppr / rank_std / pos_rank_std over the merged pool
    return R


def insert(csv_path=os.path.join(OUT, "2027_inhouse_early.csv"), md_path=os.path.join(OUT, "2027_inhouse_early.md")):
    V = pd.read_csv(csv_path)
    if "provisional" in V: V = V[V.provisional.fillna(0) != 1].copy()       # re-insert from scratch
    V.to_csv(os.path.join(OUT, "2027_inhouse_early_norookies.csv"), index=False)
    V["provisional"] = 0
    Rk, exp = rookies_2027()
    R = pd.concat([V, Rk], ignore_index=True)
    old = V.set_index(["name", "pos", "team"])[["rank", "pos_rank"]]
    R = rank_all(R)
    vet = R[R.provisional == 0].set_index(["name", "pos", "team"])
    chg = vet.join(old, rsuffix="_old")
    P(f"=== A15 insert: {len(Rk)} PROVISIONAL rookies added to {len(V)} veterans (JM export {exp}) ===")
    P(f"  veterans' ppg/games/total unchanged by construction; position ranks moved for {int((chg.pos_rank != chg.pos_rank_old).sum())} veterans, overall ranks for {int((chg['rank'] != chg.rank_old).sum())} (only because rookies were slotted above them)")
    num = R.select_dtypes("number").columns; R[num] = R[num].round(4)   # drop float-order noise (1e-12) so reruns match exactly
    FMT = ["rec_pg", "ppg_ppr", "total_ppr", "tot_p10_ppr", "tot_p90_ppr", "rank_ppr", "pos_rank_ppr",
           "ppg_std", "total_std", "tot_p10_std", "tot_p90_std", "rank_std", "pos_rank_std"]
    R = R[[c for c in R.columns if c not in FMT] + [c for c in FMT if c in R.columns]]   # format columns last: the old header stays a prefix
    R.to_csv(csv_path, index=False)
    md = open(md_path, encoding="utf-8").read()
    md = re.sub(r"\n## PROVISIONAL 2027 rookie class.*", "", md, flags=re.S)
    lines = ["", "## PROVISIONAL 2027 rookie class (JM placeholders, NOT drafted players)", "",
             f"- Built from Jack's JM scores (data/jm_scores.json, exported {exp}). JM includes a draft-capital term that, for this undrafted class, comes from an OUTSIDE consensus mock draft (NFL Mock Draft Database, data/draft_proj.js). Jack approved using it for undrafted 2027 rookies only (2026-11-23).",
             "- No team: each rookie is placed from the rookie seasons of the 20 past prospects at his position with the nearest JM (non-players count as 0). Ranges use the 40 nearest. Class status from years in college (4+ = senior; 3 with JM 60+ = likely to declare; else uncertain).",
             "- The overall and position tables above are the veterans-only order; the CSV carries the merged ranks (column provisional = 1). Veterans' projections are NOT adjusted for rookies who may land on their team.", ""]
    for p in POS4:
        x = R[(R.provisional == 1) & (R.pos == p)].sort_values("pos_rank").head(12)
        lines += [f"### {p}", "", "| Pos rk | Overall | Player | School | Class | JM | Implied round | P(drafted) | PPG | G | Total | p10-p90 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        lines += [f"| {r.pos_rank} | {r['rank']} | {r['name']} | {r.school} | {r.class_status} | {r.jm:.1f} | {r.implied_round} | {r.p_drafted:.2f} | {r.ppg:.1f} | {r.games:.1f} | {r.total:.0f} | {r.tot_p10:.0f}-{r.tot_p90:.0f} |" for _, r in x.iterrows()]
        lines.append("")
    open(md_path, "w", encoding="utf-8").write(md.rstrip("\n") + "\n" + "\n".join(lines) + "\n")
    for p in POS4:
        x = R[(R.provisional == 1) & (R.pos == p)].sort_values("pos_rank").head(6)
        P(f"  {p}: " + "; ".join(f"{r['name']} ({r.school}, {r.class_status}, JM {r.jm:.0f}, {r.implied_round}) {p}{r.pos_rank} / #{r['rank']} {r.total:.0f} [{r.tot_p10:.0f}-{r.tot_p90:.0f}]" for _, r in x.iterrows()))
    return R


def main():
    global LOG
    mode = sys.argv[1] if len(sys.argv) > 1 else "insert"
    LOG = open(os.path.join(HERE, f"a15_{mode}.log"), "w", encoding="utf-8")
    backtest() if mode == "backtest" else insert()


if __name__ == "__main__":
    main()
