#!/usr/bin/env python3
"""
A16 (research only, 2026-11-24) - how good is the A15 JM placement when JM does NOT know the real pick?

The honest test the disk allows: the site repo holds scripts/jm_nov_picks_2021_2024.json = the NFL Mock Draft
Database consensus big board as archived in NOVEMBER of each class's final college season (2020-11-22, 2021-11-26,
2022-11-20, 2023-11-19), matched to every DRAFTED skill player of the 2021-2024 classes (269 players). Those four
boards are the only pre-draft projected-pick data on disk (no raw board pages, no earlier draft_proj snapshots:
the repo's first draft_proj.js is 2026-09-30 and is the 2027 class).

Steps
  echo {} > e.json ; node a16_jm_eval.js --scenarios e.json --out data/a16_jm_rows_real0.json   (lists the prospects)
  python a16_predraft_jm.py scenarios   -> data/a16_scen.json          (projected picks per scenario)
  node   a16_jm_eval.js --scenarios data/a16_scen.json --out data/a16_jm_rows.json
                                          (the site's own JM, rebuilt in memory with each scenario's picks; read-only)
  python a16_predraft_jm.py backtest    -> a16_predraft_jm.log, data/a16_backtest_rows.parquet

Scenarios
  real              real picks (the A15 upper bound, same build as the others)
  nov_live          drafted 2021-24 players get the November projection under the LIVE draft_proj rule:
                    consensus mock pick -> big-board rank if <= 262 -> 'U' (projected UDFA)
  nov_raw           same but the big-board rank is used at any depth (the 11-18 jm_projpick_study rule)
  nocomb            real picks, combine testing (RAS, forty, vert, broad, bench, cone, shuttle) removed
  nov_live_nocomb   November picks AND no combine testing = what the site would have known that November
                    (still full final-season college stats / PFF: not removable, see the log)
  sim_XX / simc_XX  all nine classes 2017-2025: 2021-24 keep their real November board; 2017-20 and 2025 get a
                    November pick drawn from the 2022-24 boards' own error (a donor in the same actual round supplies
                    his log(nov/actual) or his off-board status). simc = also without combine testing.
  simu_XX           simc + a GUESS for players who went undrafted: 15% of them carry a November rank 130-262.
Undrafted prospects have NO November information on disk, so everywhere except simu they keep their real
(undrafted) JM. That favours the pre-draft numbers; simu shows the size of that hole under a stated guess.

Backtest = A15's own (imported from a15_rookies.py, K=20 / K2=40, leave-one-class-out): the neighbours always carry
their REAL-pick JM (as the live 2027 placement does); only the held-out class's query JM changes.
"""
import os, sys, json, warnings
import numpy as np, pandas as pd
from scipy.stats import spearmanr
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM
import a15_rookies as A

SITE = r"E:\MyFantasyFootball\MyFantasyFootball Files"
NOV = os.path.join(SITE, "scripts", "jm_nov_picks_2021_2024.json")
SCEN = os.path.join(HERE, "data", "a16_scen.json")
ROWS = os.path.join(HERE, "data", "a16_jm_rows.json")
REAL0 = os.path.join(HERE, "data", "a16_jm_rows_real0.json")   # a first headless dump with an empty scenario file (real picks), used to list the prospects
STRIP = ["ras", "forty", "vert", "broad", "bench", "cone", "shuttle"]
POS4 = A.POS4
NSIM, NSIMU = 12, 6
NOVY = (2021, 2022, 2023, 2024)
LOG = None


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def rnd(pick):
    return int(min(7, (pick - 1) // 32 + 1))


def nov_table():
    N = json.load(open(NOV, encoding="utf-8"))["players"]
    d = pd.DataFrame([{"key": k, **v} for k, v in N.items()])
    d["nov_any"] = d.mock.fillna(d.board_rank)
    d["nov_live"] = np.where(d.nov_any.notna() & (d.nov_any <= 262), d.nov_any, np.nan)
    d["rd"] = d.pick.map(rnd)
    return d


def scenarios():
    d = nov_table()
    real = json.load(open(REAL0))["real"]          # [name, pos, yr, jm, used, lc, stored]
    allp = pd.DataFrame(real, columns=["name", "pos", "yr", "jm", "used", "lc", "stored"])
    S = {}
    live = {r.key: (int(r.nov_live) if r.nov_live == r.nov_live else "U") for r in d.itertuples()}
    raw = {r.key: (int(r.nov_any) if r.nov_any == r.nov_any else "U") for r in d.itertuples()}
    S["nov_live"] = {"picks": live}
    S["nov_raw"] = {"picks": raw}
    S["nocomb"] = {"picks": {}, "strip": STRIP, "stripYears": [2017, 2025]}
    S["nov_live_nocomb"] = {"picks": live, "strip": STRIP, "stripYears": [2017, 2025]}
    # donor pool: the 2022-24 boards (600-1,055 deep, like today's); 2021's archived board was only 200 deep
    don = d[d.yr >= 2022]
    pool = {r: don[don.rd == r] for r in range(1, 8)}
    drafted = allp[allp.stored.map(lambda v: isinstance(v, int)) & ~allp.yr.isin(NOVY)]
    undrafted = allp[~allp.stored.map(lambda v: isinstance(v, int))]
    rng = np.random.default_rng(20261124)
    for i in range(NSIM):
        picks = dict(live)
        for r in drafted.itertuples():
            dn = pool[rnd(r.stored)].iloc[rng.integers(len(pool[rnd(r.stored)]))]
            if dn.nov_live != dn.nov_live: picks[f"{r.name}|{r.yr}"] = "U"; continue
            v = int(round(r.stored * dn.nov_live / dn.pick))
            picks[f"{r.name}|{r.yr}"] = "U" if v > 262 else max(1, v)
        S[f"sim_{i:02d}"] = {"picks": picks}
        S[f"simc_{i:02d}"] = {"picks": picks, "strip": STRIP, "stripYears": [2017, 2025]}
        if i < NSIMU:
            pu = dict(picks)
            for r in undrafted.itertuples():
                if rng.random() < .15: pu[f"{r.name}|{r.yr}"] = int(rng.integers(130, 263))
            S[f"simu_{i:02d}"] = {"picks": pu, "strip": STRIP, "stripYears": [2017, 2025]}
    json.dump(S, open(SCEN, "w"))
    print(f"wrote {SCEN}: {len(S)} scenarios; November players {len(d)}; simulated drafted players {len(drafted)}; undrafted prospects {len(undrafted)}")


# ------------------------------------------------------------------ backtest
def frame(rows):
    J = pd.DataFrame(rows, columns=["name", "pos", "yr", "jm", "used", "lc", "stored"])
    J = J[J.pos.isin(POS4) & J.jm.notna()].copy(); J["yr"] = J.yr.astype(int); J["key"] = J.name.map(PM.nrm)
    return J


def knn_range(past, pos, j, k2, qlo=.1, qhi=.9):
    nb = A.knn(past, pos, j, k2)
    return float(np.quantile(nb.total, qlo)), float(np.quantile(nb.total, qhi))


def place(H, q, classes, extra=()):
    """A15 placement of every prospect in `classes`, query JM = column q of H, neighbours = real JM of the other classes."""
    D = pd.read_parquet(os.path.join(HERE, "data", "rb_a14_D.parquet"), columns=["key", "season", "pos", "rookie", "pg", "g_use", "G"])
    D = D[D.rookie == 1].drop_duplicates(["season", "key"]).rename(columns={"season": "yr"})
    rows = []
    for y in classes:
        past = H[H.yr != y]
        for r in H[H.yr == y].to_dict("records"):
            pr = A.project(past, r["pos"], r[q])
            row = {"yr": y, "name": r["name"], "pos": r["pos"], "key": r["key"], "jm_real": r["jm"], "jm_q": r[q], "games": r["games"], "total": r["total"],
                   "round": r["round"], "a_ppg": pr["ppg_cond"], "a_tot": pr["total"], "lo": pr["tot_p10"], "hi": pr["tot_p90"]}
            for tag, k2, ql, qh in extra:
                row["lo_" + tag], row["hi_" + tag] = knn_range(past, r["pos"], r[q], k2, ql, qh)
            rows.append(row)
    B = pd.DataFrame(rows).merge(D[["yr", "key", "pg", "g_use", "G"]], on=["yr", "key"], how="left")
    B["b_ppg"] = B.pg; B["b_tot"] = B.pg * B.g_use * B.G
    B["act_ppg"] = np.where(B.games > 0, B.total / B.games.replace(0, np.nan), np.nan)
    return B


def hits(sub, col, k):
    v = []
    for _, g in sub.groupby("yr"):
        if len(g) < k + 2: continue
        v.append(len(set(g.nlargest(k, col).name) & set(g.nlargest(k, "total").name)) / k)
    return float(np.mean(v)) if v else np.nan


def metrics(B, p, col_ppg="a_ppg", col_tot="a_tot", lo="lo", hi="hi"):
    x = B[B.pos == p]
    m = (x.games >= 4) & x.b_ppg.notna() & x[col_ppg].notna(); pg = x[m]
    mae = float(np.sum(pg.games * np.abs(pg[col_ppg] - pg.act_ppg)) / pg.games.sum()) if len(pg) else np.nan
    bias = float(np.sum(pg.games * (pg[col_ppg] - pg.act_ppg)) / pg.games.sum()) if len(pg) else np.nan
    rho = float(np.nanmean([spearmanr(g[col_ppg], g.act_ppg).correlation for _, g in pg.groupby("yr") if len(g) >= 5])) if len(pg) else np.nan
    rho_t = float(np.nanmean([spearmanr(g[col_tot], g.total).correlation for _, g in x.groupby("yr") if len(g) >= 5]))
    cov = float(((x.total >= x[lo]) & (x.total <= x[hi])).mean())
    return {"n_pg": len(pg), "mae_pg": mae, "bias_pg": bias, "rho_pg": rho, "n": len(x), "top6": hits(x, col_tot, 6), "top12": hits(x, col_tot, 12),
            "mae_tot": float(np.mean(np.abs(x[col_tot] - x.total))), "bias_tot": float(np.mean(x[col_tot] - x.total)), "rho_tot": rho_t,
            "cov": cov, "below": float((x.total < x[lo]).mean()), "above": float((x.total > x[hi]).mean()), "width": float(np.median(x[hi] - x[lo]))}


def boot_diff(Ba, Bb, p, n=2000, seed=7):
    """paired bootstrap (players) of per-game MAE and totals MAE, scenario b minus scenario a."""
    a = Ba[Ba.pos == p].reset_index(drop=True); b = Bb[Bb.pos == p].reset_index(drop=True)
    assert (a.name.values == b.name.values).all()
    m = ((a.games >= 4) & a.b_ppg.notna() & a.a_ppg.notna() & b.a_ppg.notna()).values
    w = a.games.values[m]; ea = np.abs(a.a_ppg - a.act_ppg).values[m]; eb = np.abs(b.a_ppg - b.act_ppg).values[m]
    ta = np.abs(a.a_tot - a.total).values; tb = np.abs(b.a_tot - b.total).values
    rng = np.random.default_rng(seed); d1 = []; d2 = []
    for _ in range(n):
        i = rng.integers(0, m.sum(), m.sum()); d1.append((w[i] * (eb[i] - ea[i])).sum() / w[i].sum())
        j = rng.integers(0, len(a), len(a)); d2.append((tb[j] - ta[j]).mean())
    return np.percentile(d1, [5, 95]), np.percentile(d2, [5, 95])


def fmt(m):
    return f"{m['mae_pg']:.2f} / {m['rho_pg']:.2f}"


def table(title, Bs, classes_note):
    """Bs = {label: B}; prints the four A15 blocks side by side."""
    P(f"\n### {title} ({classes_note})")
    labs = list(Bs)
    P("\n  per-game (4+ games AND a post-draft prior row): games-weighted MAE / within-class rank corr; signed bias in ()")
    P("| pos | n | " + " | ".join(labs) + " | post-draft prior |"); P("|---|---|" + "---|" * (len(labs) + 1))
    for p in POS4:
        ms = {l: metrics(Bs[l], p) for l in labs}; m0 = ms[labs[0]]
        mb = metrics(Bs[labs[0]], p, col_ppg="b_ppg")
        P(f"| {p} | {m0['n_pg']} | " + " | ".join(f"{fmt(ms[l])} ({ms[l]['bias_pg']:+.2f})" for l in labs) + f" | {fmt(mb)} |")
    P("\n  season totals, every prospect (non-players = 0): top-6 / top-12 hit rate; totals MAE; within-class rank corr of totals")
    P("| pos | n | " + " | ".join(labs) + " |"); P("|---|---|" + "---|" * len(labs))
    for p in POS4:
        ms = {l: metrics(Bs[l], p) for l in labs}
        P(f"| {p} | {ms[labs[0]]['n']} | " + " | ".join(f"{ms[l]['top6']:.2f} / {ms[l]['top12']:.2f}; MAE {ms[l]['mae_tot']:.1f}; rho {ms[l]['rho_tot']:.2f}" for l in labs) + " |")
    P("\n  10th-90th range coverage of season totals, K2 = 40 (target 80%): coverage (below / above), median width")
    P("| pos | n | " + " | ".join(labs) + " |"); P("|---|---|" + "---|" * len(labs))
    for p in POS4:
        ms = {l: metrics(Bs[l], p) for l in labs}
        P(f"| {p} | {ms[labs[0]]['n']} | " + " | ".join(f"{ms[l]['cov']*100:.0f}% ({ms[l]['below']*100:.0f} / {ms[l]['above']*100:.0f}), {ms[l]['width']:.0f} pts" for l in labs) + " |")


def backtest():
    R = json.load(open(ROWS))
    real = frame(R["real"])
    H = A.outcomes(real[real.yr.between(2015, 2025)])
    scen = {}
    for s, rows in R.items():
        if s == "real": continue
        f = frame(rows).set_index(["name", "yr"]).jm
        H[s] = [f.get((n, y), np.nan) for n, y in zip(H.name, H.yr)]
        scen[s] = int(H[s].isna().sum())
    P("=== A16: A15 JM placement rebuilt on PRE-DRAFT information (leave-one-class-out; neighbours carry real-pick JM) ===")
    P(f"  prospects 2017-2025 with a JM: {len(H)}; drafted (actual round 1-7): {int((H['round'] <= 7).sum())}; undrafted: {int((H['round'] > 7).sum())}")
    P(f"  scenarios {len(scen)}; prospects that lose their JM in a scenario (kept out of that scenario's rows): " + ", ".join(f"{k} {v}" for k, v in scen.items() if v) or "none")
    N = nov_table()
    P("\n## 0. The November boards vs the real draft (drafted skill players, the only ones the archive file carries)")
    P("| class | board depth | n | on the board at all | projected inside 262 (live rule) | rank corr Nov vs actual pick | median |log ratio| |")
    P("|---|---|---|---|---|---|---|")
    for y, g in N.groupby("yr"):
        on = g[g.nov_live.notna()]
        P(f"| {y} | {int(g.depth.iloc[0])} | {len(g)} | {g.nov_any.notna().mean()*100:.0f}% | {g.nov_live.notna().mean()*100:.0f}% | {spearmanr(g.nov_any.fillna(1200), g.pick).correlation:.2f} | {np.abs(np.log(on.nov_live / on.pick)).median():.2f} |")
    P("| actual round | n (2022-24) | projected inside 262 | median Nov projection | sd of log(Nov / actual) |"); P("|---|---|---|---|---|")
    for r, g in N[N.yr >= 2022].groupby("rd"):
        on = g[g.nov_live.notna()]
        P(f"| {r} | {len(g)} | {g.nov_live.notna().mean()*100:.0f}% | {on.nov_live.median():.0f} | {np.log(on.nov_live / on.pick).std():.2f} |")
    # how far JM moves
    P("\n## 1. How far the JM score itself moves (drafted players of the 2021-24 classes)")
    P("| pos | n | mean |JM nov_live - JM real| | sd of the change | corr(JM nov_live, JM real) | + no combine: mean |change| | corr |"); P("|---|---|---|---|---|---|---|")
    hh = H[H.yr.isin(NOVY) & (H["round"] <= 7)]
    for p in POS4:
        x = hh[hh.pos == p]; d = x.nov_live - x.jm; d2 = x.nov_live_nocomb - x.jm
        x = x[x.nov_live.notna() & x.nov_live_nocomb.notna()]; d = x.nov_live - x.jm; d2 = x.nov_live_nocomb - x.jm
        P(f"| {p} | {len(x)} | {d.abs().mean():.1f} | {d.std():.1f} | {np.corrcoef(x.nov_live, x.jm)[0,1]:.2f} | {d2.abs().mean():.1f} | {np.corrcoef(x.nov_live_nocomb.fillna(x.jm), x.jm)[0,1]:.2f} |")

    def run(q, classes, extra=()):
        Hq = H[H[q].notna()] if q != "jm" else H
        return place(Hq, q, classes, extra)

    EXTRA = (("k60", 60, .1, .9), ("k80", 80, .1, .9), ("k120", 120, .1, .9), ("q0595", 40, .05, .95), ("k60q", 60, .075, .925), ("k80q", 80, .05, .95))
    common = H[["nov_live", "nov_raw", "nocomb", "nov_live_nocomb"]].notna().all(axis=1)
    Hc = H[common].copy()
    def runc(q, classes, extra=()): return place(Hc, q, classes, extra)

    for classes, note in ((NOVY, "classes 2021-2024, real November boards"), ((2022, 2023, 2024), "classes 2022-2024 only: boards 600+ deep like today's")):
        Bs = {"(a) real pick = A15 upper bound": runc("jm", classes, EXTRA), "(b) Nov pick, live rule": runc("nov_live", classes, EXTRA),
              "(c) Nov pick, raw rank": runc("nov_raw", classes), "(d) real pick, no combine": runc("nocomb", classes),
              "(e) Nov pick + no combine": runc("nov_live_nocomb", classes, EXTRA)}
        table("2. THE HONEST TEST" if classes == NOVY else "2b. same, without the shallow 2021 board", Bs, note)
        if classes == NOVY:
            keep = Bs
            P("\n  paired bootstrap (players, 2,000 draws) of the MAE change vs (a), 90% interval")
            P("| pos | per-game MAE (b)-(a) | totals MAE (b)-(a) | per-game MAE (e)-(a) | totals MAE (e)-(a) |"); P("|---|---|---|---|---|")
            la, lb, le = list(Bs)[0], list(Bs)[1], list(Bs)[4]
            for p in POS4:
                b1, b2 = boot_diff(Bs[la], Bs[lb], p); e1, e2 = boot_diff(Bs[la], Bs[le], p)
                ma, mb, me = metrics(Bs[la], p), metrics(Bs[lb], p), metrics(Bs[le], p)
                P(f"| {p} | {mb['mae_pg']-ma['mae_pg']:+.2f} [{b1[0]:+.2f}, {b1[1]:+.2f}] | {mb['mae_tot']-ma['mae_tot']:+.1f} [{b2[0]:+.1f}, {b2[1]:+.1f}] | {me['mae_pg']-ma['mae_pg']:+.2f} [{e1[0]:+.2f}, {e1[1]:+.2f}] | {me['mae_tot']-ma['mae_tot']:+.1f} [{e2[0]:+.1f}, {e2[1]:+.1f}] |")
            P("\n  drafted players only (the rows whose JM actually changes): totals MAE / signed bias / within-class rank corr")
            P("| pos | n | (a) real | (b) Nov live | (e) Nov + no combine |"); P("|---|---|---|---|---|")
            for p in POS4:
                o = []
                for l in (la, lb, le):
                    x = Bs[l][(Bs[l].pos == p) & (Bs[l]["round"] <= 7)]
                    rh = np.nanmean([spearmanr(g.a_tot, g.total).correlation for _, g in x.groupby("yr") if len(g) >= 5])
                    o.append(f"{np.mean(np.abs(x.a_tot - x.total)):.1f} / {np.mean(x.a_tot - x.total):+.1f} / {rh:.2f}")
                P(f"| {p} | {len(x)} | " + " | ".join(o) + " |")
            P("\n  where the miss sits: signed totals error (projected - actual) by the PRE-DRAFT projection's own third within position, scenario (e)")
            P("| pos | top third: n, bias | middle: n, bias | bottom: n, bias | slope of actual on projected (1.00 = calibrated) | slope under (a) |"); P("|---|---|---|---|---|---|")
            for p in POS4:
                x = Bs[le][Bs[le].pos == p].copy(); x["t"] = pd.qcut(x.a_tot.rank(method="first"), 3, labels=["bot", "mid", "top"])
                xa = Bs[la][Bs[la].pos == p]
                sl = np.polyfit(x.a_tot, x.total, 1)[0]; sla = np.polyfit(xa.a_tot, xa.total, 1)[0]
                g = {k: v for k, v in x.groupby("t")}
                P(f"| {p} | " + " | ".join(f"{len(g[k])}, {np.mean(g[k].a_tot - g[k].total):+.1f}" for k in ("top", "mid", "bot")) + f" | {sl:.2f} | {sla:.2f} |")

    # ---------------- range width
    P("\n## 3. Range width for the pre-draft stage (classes 2021-24, season totals, target 80%)")
    la, lb, le = list(keep)[0], list(keep)[1], list(keep)[4]
    P("| pos | n | rule | (a) real pick | (b) Nov live | (e) Nov + no combine | median width (e) |"); P("|---|---|---|---|---|---|---|")
    rules = (("K2 40, p10-p90 (live)", "lo", "hi"), ("K2 60, p10-p90", "lo_k60", "hi_k60"), ("K2 80, p10-p90", "lo_k80", "hi_k80"), ("K2 120, p10-p90", "lo_k120", "hi_k120"),
             ("K2 60, p7.5-p92.5", "lo_k60q", "hi_k60q"), ("K2 40, p5-p95", "lo_q0595", "hi_q0595"), ("K2 80, p5-p95", "lo_k80q", "hi_k80q"))
    for p in POS4:
        for nm, lo, hi in rules:
            c = [metrics(keep[l], p, lo=lo, hi=hi) for l in (la, lb, le)]
            P(f"| {p} | {c[0]['n']} | {nm} | " + " | ".join(f"{m['cov']*100:.0f}% ({m['below']*100:.0f} / {m['above']*100:.0f})" for m in c) + f" | {c[2]['width']:.0f} |")
    P("  drafted players only (JM actually changed), K2 40 p10-p90:")
    for p in POS4:
        o = []
        for l in (la, lb, le):
            x = keep[l][(keep[l].pos == p) & (keep[l]["round"] <= 7)]
            o.append(f"{((x.total >= x.lo) & (x.total <= x.hi)).mean()*100:.0f}%")
        P(f"   {p} (n {len(x)}): (a) {o[0]}  (b) {o[1]}  (e) {o[2]}")

    # ---------------- candidate fix: map the November JM back to an expected real JM (fit on the other three classes)
    P("\n## 4. Candidate fix (leak-free): shrink the pre-draft JM toward what it usually turns into")
    P("  per position, regress real JM on the Nov + no-combine JM using the OTHER three November classes, apply to the held-out class, then place as usual")
    Hf = Hc.copy(); Hf["fix"] = Hf.nov_live_nocomb
    for y in NOVY:
        for p in POS4:
            tr = Hf[Hf.yr.isin(NOVY) & (Hf.yr != y) & (Hf.pos == p)]; te = (Hf.yr == y) & (Hf.pos == p)
            b, a = np.polyfit(tr.nov_live_nocomb, tr.jm, 1)
            Hf.loc[te, "fix"] = a + b * Hf.loc[te, "nov_live_nocomb"]
    Bf = place(Hf, "fix", NOVY)
    P("| pos | (e) Nov + no combine: per-game MAE / rho; totals MAE; top6 / top12; coverage | (f) with the map | slope real~pre (all four classes) |"); P("|---|---|---|---|")
    for p in POS4:
        me, mf = metrics(keep[le], p), metrics(Bf, p); x = Hc[Hc.yr.isin(NOVY) & (Hc.pos == p)]
        s = lambda m: f"{m['mae_pg']:.2f} / {m['rho_pg']:.2f}; {m['mae_tot']:.1f}; {m['top6']:.2f} / {m['top12']:.2f}; {m['cov']*100:.0f}%"
        P(f"| {p} | {s(me)} | {s(mf)} | {np.polyfit(x.nov_live_nocomb, x.jm, 1)[0]:.2f} |")

    # ---------------- all nine classes with simulated boards
    P("\n## 5. All nine classes 2017-2025 (2021-24 real boards; 2017-20 and 2025 SIMULATED from the 2022-24 boards' error) - mean over draws [min, max]")
    allc = tuple(range(2017, 2026))
    Ba = run("jm", allc)
    def agg(prefix, n):
        out = {p: [] for p in POS4}
        for i in range(n):
            B = run(f"{prefix}_{i:02d}", allc)
            for p in POS4: out[p].append(metrics(B, p))
        return out
    sims = {"sim (Nov pick)": agg("sim", NSIM), "simc (Nov pick + no combine)": agg("simc", NSIM), "simu (simc + 15% of undrafted on the board: GUESS)": agg("simu", NSIMU)}
    for key, lab, f in (("mae_pg", "per-game MAE", "{:.2f}"), ("rho_pg", "per-game within-class rank corr", "{:.2f}"), ("mae_tot", "totals MAE", "{:.1f}"), ("rho_tot", "totals within-class rank corr", "{:.2f}"),
                        ("top6", "top-6 hit rate", "{:.2f}"), ("top12", "top-12 hit rate", "{:.2f}"), ("cov", "p10-p90 coverage (K2 40)", "{:.3f}"), ("above", "share finishing ABOVE the range", "{:.3f}"), ("below", "share finishing BELOW the range", "{:.3f}")):
        P(f"\n  {lab}")
        P("| pos | n | (a) real pick, 9 classes | " + " | ".join(sims) + " |"); P("|---|---|---|" + "---|" * len(sims))
        for p in POS4:
            ma = metrics(Ba, p)
            P(f"| {p} | {ma['n_pg'] if key.endswith('_pg') else ma['n']} | {f.format(ma[key])} | " + " | ".join(f"{f.format(np.mean([m[key] for m in sims[s][p]]))} [{f.format(np.min([m[key] for m in sims[s][p]]))}, {f.format(np.max([m[key] for m in sims[s][p]]))}]" for s in sims) + " |")
    out = pd.concat([keep[l].assign(scenario=t) for l, t in ((la, "real"), (lb, "nov_live"), (le, "nov_live_nocomb"))] + [Bf.assign(scenario="fix_map")], ignore_index=True)
    out.to_parquet(os.path.join(HERE, "data", "a16_backtest_rows.parquet"), index=False)
    P("\n  rows -> data/a16_backtest_rows.parquet")


def main():
    global LOG
    mode = sys.argv[1] if len(sys.argv) > 1 else "backtest"
    if mode == "scenarios": return scenarios()
    LOG = open(os.path.join(HERE, "a16_predraft_jm.log"), "w", encoding="utf-8")
    backtest()


if __name__ == "__main__":
    main()
