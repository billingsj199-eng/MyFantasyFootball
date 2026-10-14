#!/usr/bin/env python3
"""
ROOM ARCHETYPES -> FILL-IN OUTCOME DISTRIBUTION (Jack 2026-10-09: "pin down specific running back rooms and see if there are
correlations with higher and low end outcomes from RB injuries, same with WRs").

Weekly DB 2019-25, same trailing rules as research_absence_all_positions.py (last 3 team games, 2+ played; not traded; QB1 healthy).
RB: team's RB1 (most trailing carries; meaningful = >= .15 team carries or >= .08 targets) is OUT. Other absences allowed (counted).
    ABSORBER = the RB with the most carries that week (who actually got the job); DIRECT BACKUP = trailing RB2 (the pre-game read).
WR: WR1 out -> absorber = WR2 (pre-game next man); WR2 out -> WR3. Also the post-hoc max target gainer (descriptive only).
Outcome: PPR that week; HIGH >= 15, LOW <= 6. Features (pre-game unless marked SAME-WEEK): backup's trailing PPR/g, carry share of
RB room, tgt/g, draft round / pick, age, experience (nflverse players.csv); room shape (RB2-RB3 carry gap, # RBs with >= 2 car/g,
a pass-catching back >= 2.5 tgt/g); absent starter (room share, PPR/g, receiving share); team (Vegas implied total + spread from
ctx_features, team trailing skill PPR, QB1 trailing pts); SAME-WEEK: a no-baseline RB got carries.
Engine read: the weekly replica (research_absence_all_positions.eng_proj) for the direct backup -> residual by feature bin.
Writes absence_rooms.log, data/absence_rooms.json.
"""
import os, sys, json, re
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
_keep = open(os.path.join(HERE, "absence_all_positions.log"), encoding="utf-8").read()
import research_absence_all_positions as A
A.LOG.close(); open(os.path.join(HERE, "absence_all_positions.log"), "w", encoding="utf-8").write(_keep)
cal = A.cal; YEARS = A.YEARS; TRAIL = 3
LOG = open(os.path.join(HERE, "absence_rooms.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()
HI, LO = 15.0, 6.0

# ---- player bio (nflverse) + Vegas (ctx_features) ----
PL = pd.read_csv(os.path.join(r"E:\MyFantasyFootball\pbp_cache", "players.csv"), low_memory=False,
                 usecols=["display_name", "position", "birth_date", "rookie_season", "draft_round", "draft_pick", "draft_year"])
BIO = defaultdict(list)
for r in PL.itertuples(index=False):
    BIO[(cal.norm(str(r.display_name)), r.position)].append(r)
def bio(nm, pos, Y):
    c = [r for r in BIO.get((nm, pos), []) if (r.rookie_season != r.rookie_season) or r.rookie_season <= Y]
    if len(c) != 1: return dict(rnd=np.nan, pick=np.nan, age=np.nan, exp=np.nan)
    r = c[0]
    rnd = r.draft_round if r.draft_round == r.draft_round else 8.0   # undrafted = 8
    pick = r.draft_pick if r.draft_pick == r.draft_pick else 300.0
    try: age = Y + 0.7 - int(str(r.birth_date)[:4]) - (int(str(r.birth_date)[5:7]) - 1) / 12
    except Exception: age = np.nan
    exp = Y - r.rookie_season if r.rookie_season == r.rookie_season else np.nan
    return dict(rnd=float(rnd), pick=float(pick), age=age, exp=exp)
C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet"), columns=["year", "team", "wk", "implied", "spread"])
VEG = {}
for r in C.dropna(subset=["implied"]).itertuples(index=False):
    VEG[(int(r.year), A.TM_ALIAS.get(r.team, r.team), int(r.wk))] = (float(r.implied), float(r.spread))


def collect():
    RB, WR = [], []
    for Y in YEARS:
        rows, teams_of, hist = A.build(Y)
        tw = defaultdict(list)
        for (tm, wk) in rows: tw[tm].append(wk)
        for tm, wks in tw.items():
            wks.sort()
            for i, wk in enumerate(wks):
                if i < TRAIL: continue
                prev = wks[i - TRAIL:i]
                cur = {r["key"]: r for r in rows[(tm, wk)]}
                trail = {}
                for pw in prev:
                    for r in rows[(tm, pw)]:
                        t = trail.setdefault(r["key"], dict({k: 0.0 for k in A.F}, g=0, pos=r["pos"], n=r["n"]))
                        t["g"] += 1
                        for k in A.F: t[k] += r[k]
                trail = {k: v for k, v in trail.items() if v["g"] >= 2}
                for v in trail.values():
                    for k in A.F: v[k] /= v["g"]
                tsum = lambda f, cond=lambda r: True: sum(sum(r[f] for r in rows[(tm, pw)] if cond(r)) for pw in prev) / TRAIL
                T = dict(tgt=tsum("tgt"), ra=tsum("ra"), pa=tsum("pa"), skp=tsum("ppr", lambda r: r["pos"] != "QB"), rbra=tsum("ra", lambda r: r["pos"] == "RB"))
                if T["tgt"] < 15 or T["ra"] < 10 or T["pa"] < 15 or T["rbra"] < 8: continue
                rank = {}
                for pos, f in (("QB", "pa"), ("RB", "ra"), ("WR", "tgt"), ("TE", "tgt")):
                    L = sorted([k for k, v in trail.items() if v["pos"] == pos], key=lambda k: -(trail[k][f] + 1e-3 * trail[k]["tgt"]))
                    for j, k in enumerate(L): rank[k] = j + 1
                by = lambda pos, r: next((k for k, v in trail.items() if v["pos"] == pos and rank[k] == r), None)
                absent = {k for k in trail if k not in cur and not any(t2 != tm and w2 > wk for (t2, w2) in teams_of[k])}
                qb1 = by("QB", 1)
                if qb1 is None or qb1 in absent: continue
                meaningful = lambda k: trail[k]["pos"] != "QB" and (trail[k]["tgt"] / T["tgt"] >= A.TGT_MIN or trail[k]["ra"] / T["ra"] >= A.CAR_MIN)
                nabs = sum(1 for k in absent if meaningful(k))
                ret = any(k not in trail and len([x for x in hist[(k, tm)] if x[0] < wk]) >= 2 and np.mean([x[1] for x in hist[(k, tm)] if x[0] < wk]) >= 5 for k in cur)
                imp, spr = VEG.get((Y, tm, wk), (np.nan, np.nan))
                team = dict(Y=Y, wk=wk, tm=tm, nabs=nabs, ret=ret, implied=imp, spread=spr, team_skp=T["skp"], qb_pts=trail[qb1]["ppr"])
                # ---------- RB1 out
                r1 = by("RB", 1)
                if r1 in absent and meaningful(r1):
                    a = trail[r1]
                    rbs_h = sorted([k for k, v in trail.items() if v["pos"] == "RB" and k in cur], key=lambda k: rank[k])
                    now_rbs = sorted([r for r in cur.values() if r["pos"] == "RB"], key=lambda r: -(r["ra"] + 0.01 * r["tgt"]))
                    if not now_rbs: continue
                    ab = now_rbs[0]; abk = ab["key"]; abt = trail.get(abk)
                    b2 = rbs_h[0] if rbs_h else None; b3 = rbs_h[1] if len(rbs_h) > 1 else None
                    b2t = trail[b2] if b2 else None
                    ev = dict(team, a_n=a["n"], a_ppr=a["ppr"], a_room=a["ra"] / T["rbra"], a_recsh=a["recp"] / max(1e-9, a["ppr"]), a_tgt=a["tgt"],
                              ab_n=ab["n"], ab_act=ab["ppr"], ab_car=ab["ra"], ab_tgt=ab["tgt"], ab_has_base=abt is not None, ab_is_b2=(abk == b2),
                              ab_own=abt["ppr"] if abt else 0.0, ab_room=(abt["ra"] / T["rbra"]) if abt else 0.0, ab_tpg=abt["tgt"] if abt else 0.0,
                              b2_n=b2t["n"] if b2t else None, b2_own=b2t["ppr"] if b2t else np.nan, b2_room=b2t["ra"] / T["rbra"] if b2t else np.nan,
                              b2_tpg=b2t["tgt"] if b2t else np.nan, b2_act=(cur[b2]["ppr"] if b2 else np.nan), b2_car_now=(cur[b2]["ra"] if b2 else np.nan),
                              gap23=(b2t["ra"] - (trail[b3]["ra"] if b3 else 0.0)) if b2t else np.nan,
                              n_rbs=sum(1 for k in rbs_h if trail[k]["ra"] >= 2), pc_back=any(trail[k]["tgt"] >= 2.5 for k in rbs_h),
                              body_car=sum(r["ra"] for r in cur.values() if r["pos"] == "RB" and r["key"] not in trail))
                    ev.update({"ab_" + k: v for k, v in bio(ab["n"], "RB", Y).items()})
                    if b2t: ev.update({"b2_" + k: v for k, v in bio(b2t["n"], "RB", Y).items()})
                    # engine replica for the direct backup (single-absence form)
                    if b2t:
                        mem = [dict(slot="RB", pos=v["pos"], n=v["n"], rank=rank[k], pcrank=99, own=v["ppr"], ownh=v["half"], ownrec=v["recp"], ownrush=v["rushp"],
                                    bt=v["tgt"], bc=v["ra"], act=cur[k]["ppr"], at=cur[k]["tgt"], ac=cur[k]["ra"]) for k, v in trail.items() if k in cur and v["pos"] in ("RB", "WR", "TE")]
                        Aab = [dict(role="RB1", pos="RB", n=a["n"], ppr=a["ppr"], half=a["half"], recp=a["recp"], rushp=a["rushp"], tgt=a["tgt"], ra=a["ra"], pa=0,
                                    tsh=a["tgt"] / T["tgt"], roomsh=a["ra"] / T["rbra"], lead=False, pcrank=99)]
                        m2 = next(m for m in mem if m["n"] == b2t["n"] and m["pos"] == "RB")
                        ev["b2_eng"] = A.eng_proj(dict(A=Aab, mem=mem), m2)
                    RB.append(ev)
                # ---------- WR1 / WR2 out
                for wr_r in (1, 2):
                    w = by("WR", wr_r)
                    if w is None or w not in absent or not meaningful(w): continue
                    a = trail[w]
                    nxt = sorted([k for k, v in trail.items() if v["pos"] == "WR" and k in cur and rank[k] > wr_r], key=lambda k: rank[k])
                    if not nxt: continue
                    ab = nxt[0]; abt = trail[ab]
                    hl = [v["tgt"] for k, v in trail.items() if k in cur and v["pos"] in ("WR", "TE", "RB")]
                    hhi = sum((x / sum(hl)) ** 2 for x in hl) if hl and sum(hl) > 0 else np.nan
                    te1 = by("TE", 1); te_lvl = trail[te1]["ppr"] if te1 and te1 in cur else 0.0
                    gains = [(r["tgt"] - trail[k]["tgt"] if k in trail else r["tgt"], r) for k, r in cur.items() if r["pos"] in ("WR", "TE")]
                    mg = max(gains, key=lambda x: x[0])[1] if gains else None
                    wr1h = by("WR", 1) if wr_r == 2 else None
                    ev = dict(team, role=f"WR{wr_r}", a_n=a["n"], a_ppr=a["ppr"], a_tsh=a["tgt"] / T["tgt"], ab_n=abt["n"], ab_own=abt["ppr"], ab_tsh=abt["tgt"] / T["tgt"],
                              ab_tpg=abt["tgt"], ab_ypt=(abt["recp"] - abt["tgt"] * 0) / max(0.5, abt["tgt"]), ab_act=cur[ab]["ppr"], ab_tgt_now=cur[ab]["tgt"],
                              hhi=hhi, te_lvl=te_lvl, n_wr_h=len(nxt), mg_n=mg["n"] if mg else None, mg_act=mg["ppr"] if mg else np.nan,
                              wr1_act=(cur[wr1h]["ppr"] if wr1h in cur else np.nan) if wr1h else np.nan)
                    ev.update({"ab_" + k: v for k, v in bio(abt["n"], "WR", Y).items()})
                    mem = [dict(slot="X", pos=v["pos"], n=v["n"], rank=rank[k], pcrank=1 + sorted([x for x in trail if trail[x]["pos"] != "QB"], key=lambda x: -trail[x]["tgt"]).index(k),
                                own=v["ppr"], ownh=v["half"], ownrec=v["recp"], ownrush=v["rushp"], bt=v["tgt"], bc=v["ra"], act=cur[k]["ppr"], at=cur[k]["tgt"], ac=cur[k]["ra"])
                           for k, v in trail.items() if k in cur and v["pos"] in ("RB", "WR", "TE")]
                    top = max(v["tgt"] for v in trail.values() if v["pos"] != "QB")
                    Aab = [dict(role="WR", pos="WR", n=a["n"], ppr=a["ppr"], half=a["half"], recp=a["recp"], rushp=a["rushp"], tgt=a["tgt"], ra=a["ra"], pa=0,
                                tsh=a["tgt"] / T["tgt"], roomsh=0, lead=a["tgt"] >= top - 1e-9, pcrank=99)]
                    m2 = next(m for m in mem if m["n"] == abt["n"] and m["pos"] == "WR")
                    ev["ab_eng"] = A.eng_proj(dict(A=Aab, mem=mem), m2)
                    WR.append(ev)
    return RB, WR


def dist(vals):
    v = np.array(vals, float); v = v[np.isfinite(v)]
    if not len(v): return "n 0"
    return f"n {len(v):3d}  high {np.mean(v >= HI):4.0%}  low {np.mean(v <= LO):4.0%}  median {np.median(v):5.1f}  mean {v.mean():5.1f}"


def bins(L, f, edges, labels, out="ab_act", eng=None):
    P(f"  by {f}:")
    for (lo, hi), lab in zip(zip(edges[:-1], edges[1:]), labels):
        S = [e for e in L if e.get(f) is not None and np.isfinite(float(e[f])) and lo <= float(e[f]) < hi]
        if len(S) < 5: continue
        extra = ""
        if eng:
            E2 = [e for e in S if np.isfinite(e.get(eng, np.nan)) and np.isfinite(e.get(eng.replace("eng", "act"), np.nan))]
            if E2: extra = f" | engine {np.mean([e[eng] for e in E2]):5.1f} vs act {np.mean([e[eng.replace('eng', 'act')] for e in E2]):5.1f} (n {len(E2)})"
        P(f"    {lab:22s} {dist([e[out] for e in S])}{extra}")


def model(L, feats, out, title):
    from sklearn.linear_model import LogisticRegression
    from sklearn.tree import DecisionTreeClassifier
    from sklearn.metrics import roc_auc_score
    D = pd.DataFrame([{**{f: float(e.get(f, np.nan)) if e.get(f) is not None else np.nan for f in feats}, "y": e[out], "Y": e["Y"]} for e in L])
    D = D[np.isfinite(D.y)]
    Xf = D[feats].astype(float); Xf = Xf.fillna(Xf.median())
    res = {}
    for lab, yv in (("HIGH >= 15", (D.y >= HI).astype(int)), ("LOW <= 6", (D.y <= LO).astype(int))):
        pr_l = np.zeros(len(D)); pr_t = np.zeros(len(D))
        for y in YEARS:
            tr, te = (D.Y != y).values, (D.Y == y).values
            if te.sum() == 0 or yv[tr].nunique() < 2: continue
            mu, sd = Xf[tr].mean(), Xf[tr].std().replace(0, 1)
            lr = LogisticRegression(C=0.5, max_iter=500).fit((Xf[tr] - mu) / sd, yv[tr]); pr_l[te] = lr.predict_proba((Xf[te] - mu) / sd)[:, 1]
            dt = DecisionTreeClassifier(max_depth=2, min_samples_leaf=15).fit(Xf[tr], yv[tr]); pr_t[te] = dt.predict_proba(Xf[te])[:, 1]
        base = yv.mean()
        aucl = roc_auc_score(yv, pr_l) if yv.nunique() > 1 else np.nan; auct = roc_auc_score(yv, pr_t) if yv.nunique() > 1 else np.nan
        bs0 = np.mean((yv - base) ** 2); bsl = np.mean((yv - pr_l) ** 2); bst = np.mean((yv - pr_t) ** 2)
        mu, sd = Xf.mean(), Xf.std().replace(0, 1)
        lr = LogisticRegression(C=0.5, max_iter=500).fit((Xf - mu) / sd, yv)
        coefs = ", ".join(f"{f} {c:+.2f}" for f, c in sorted(zip(feats, lr.coef_[0]), key=lambda t: -abs(t[1]))[:5])
        dt = DecisionTreeClassifier(max_depth=2, min_samples_leaf=15).fit(Xf, yv)
        from sklearn.tree import export_text
        P(f"  {title} {lab}: base rate {base:.0%} n {len(D)} | held-out (LOYO) AUC logistic {aucl:.3f} tree {auct:.3f}; Brier vs base-rate {100*(bsl/bs0-1):+.1f}% / {100*(bst/bs0-1):+.1f}%")
        P(f"     logistic (std coefs, top 5): {coefs}")
        P("     tree: " + export_text(dt, feature_names=feats, decimals=1).replace("\n", "\n           ").rstrip())
        res[lab] = dict(auc_logit=aucl, auc_tree=auct, base=base, brier_logit=bsl / bs0 - 1)
    return res


def examples(L, out, k=6, fmt=None):
    S = sorted([e for e in L if np.isfinite(e[out])], key=lambda e: -e[out])
    P("    HIGH end: " + "; ".join(fmt(e) for e in S[:k]))
    P("    LOW end:  " + "; ".join(fmt(e) for e in S[-k:][::-1]))


def main():
    RB, WR = collect()
    out = {}
    # REGRESSION CORRECTION (2026-10-09): the replica's 'own' is a trailing-3 average; in NORMAL weeks depth players regress UP to
    # the mean (RB rank 2+ own < 4: +2.2; WR own 12+: -3.0). Every engine number below = replica + the control-week mean of
    # actual - own at the same position / own level (players ranked 2+ who played), so cells measure the ABSENCE effect only.
    import pickle
    _, CT = pickle.load(open(os.path.join(HERE, "data", "absence_events.pkl"), "rb"))
    edges = [0, 2, 4, 6, 8, 10, 13, 99]; G = {}
    for ps in ("RB", "WR"):
        ctl = [(m["own"], m["act"] - m["own"]) for c in CT for m in c["mem"] if m["pos"] == ps and m["rank"] >= 2]
        cx = np.array([c[0] for c in ctl]); cy = np.array([c[1] for c in ctl])
        G[ps] = [float(np.mean(cy[(cx >= a) & (cx < b)])) if ((cx >= a) & (cx < b)).sum() >= 20 else 0.0 for a, b in zip(edges[:-1], edges[1:])]
        P(f"control regression {ps} (rank 2+, by own PPR): " + " ".join(f"{a}-{b} {g:+.1f}" for a, b, g in zip(edges[:-1], edges[1:], G[ps])))
    gof = lambda ps, o: G[ps][min(len(G[ps]) - 1, max(0, int(np.searchsorted(edges, o, side="right")) - 1))]
    for e in RB:
        if np.isfinite(e.get("b2_eng", np.nan)): e["b2_eng_raw"] = e["b2_eng"]; e["b2_eng"] = e["b2_eng"] + gof("RB", e["b2_own"])
    for e in WR:
        e["ab_eng_raw"] = e["ab_eng"]; e["ab_eng"] = e["ab_eng"] + gof("WR", e["ab_own"])
    P(f"=== ROOM ARCHETYPES 2019-25: {len(RB)} RB1-out team-weeks, {sum(e['role']=='WR1' for e in WR)} WR1-out, {sum(e['role']=='WR2' for e in WR)} WR2-out (QB1 healthy) ===")
    P(f"\n##### RB1 OUT: who got the job?  direct backup (trailing RB2) {np.mean([e['ab_is_b2'] for e in RB]):.0%} | another RB with a baseline "
      f"{np.mean([e['ab_has_base'] and not e['ab_is_b2'] for e in RB]):.0%} | a no-baseline body {np.mean([not e['ab_has_base'] for e in RB]):.0%}")
    P(f"  ABSORBER (most carries that week): {dist([e['ab_act'] for e in RB])}; {np.mean([e['ab_car'] for e in RB]):.1f} car {np.mean([e['ab_tgt'] for e in RB]):.1f} tgt")
    B2 = [e for e in RB if np.isfinite(e['b2_act'])]
    P(f"  DIRECT BACKUP (pre-game RB2):      {dist([e['b2_act'] for e in B2])}; engine replica mean {np.nanmean([e.get('b2_eng', np.nan) for e in B2]):.1f}")
    for lab, sel in (("workhorse out (room >= .60)", lambda e: e["a_room"] >= .6), ("committee lead out", lambda e: e["a_room"] < .6)):
        S = [e for e in B2 if sel(e)]
        P(f"    {lab:28s} direct backup {dist([e['b2_act'] for e in S])} | engine {np.nanmean([e.get('b2_eng', np.nan) for e in S]):.1f}")
    P("\n  FEATURE BINS - direct backup outcome (engine replica mean vs actual mean on the right):")
    bins(B2, "b2_own", [0, 3, 6, 9, 99], ["own < 3 PPR", "own 3-6", "own 6-9", "own 9+"], "b2_act", "b2_eng")
    bins(B2, "b2_room", [0, .15, .30, .45, 1.01], ["room share < .15", ".15-.30", ".30-.45", ".45+"], "b2_act", "b2_eng")
    bins(B2, "b2_tpg", [0, 1, 2.5, 99], ["tgt/g < 1", "tgt/g 1-2.5", "tgt/g 2.5+"], "b2_act", "b2_eng")
    bins(B2, "b2_rnd", [1, 2, 4, 8, 9], ["round 1", "round 2-3", "round 4-7", "undrafted"], "b2_act", "b2_eng")
    bins(B2, "b2_exp", [0, 1, 3, 30], ["rookie", "yr 2-3", "yr 4+"], "b2_act", "b2_eng")
    bins(B2, "gap23", [-99, 2, 5, 99], ["RB2~RB3 (gap < 2 car)", "gap 2-5", "clear RB2 (gap 5+)"], "b2_act", "b2_eng")
    bins(B2, "n_rbs", [0, 2, 3, 9], ["1 other RB w/ 2+ car", "2", "3+"], "b2_act", "b2_eng")
    bins(B2, "a_room", [0, .5, .6, .7, 1.01], ["starter < .50 room", ".50-.60", ".60-.70", ".70+ (bell cow)"], "b2_act", "b2_eng")
    bins(B2, "a_ppr", [0, 11, 15, 99], ["starter < 11 PPR", "11-15", "15+"], "b2_act", "b2_eng")
    bins(B2, "a_recsh", [0, .25, .40, 1.01], ["starter rec share < .25", ".25-.40", ".40+"], "b2_act", "b2_eng")
    bins(B2, "implied", [0, 20, 24, 99], ["implied < 20", "20-24", "24+"], "b2_act", "b2_eng")
    bins(B2, "spread", [-99, -3.5, 3.5, 99], ["favored by 3.5+", "within 3.5", "underdog 3.5+"], "b2_act", "b2_eng")
    bins(B2, "team_skp", [0, 50, 62, 999], ["team skill PPR < 50", "50-62", "62+"], "b2_act", "b2_eng")
    bins(B2, "body_car", [0, 0.5, 6, 99], ["no body carries (SAME-WEEK)", "body 1-5 car", "body 6+ car"], "b2_act", "b2_eng")
    bins(B2, "nabs", [1, 2, 9], ["only the RB1 out", "+ another starter out"], "b2_act", "b2_eng")
    feats = ["b2_own", "b2_room", "b2_tpg", "b2_rnd", "b2_exp", "gap23", "n_rbs", "a_room", "a_ppr", "a_recsh", "implied", "team_skp"]
    out["rb_model"] = model(B2, feats, "b2_act", "RB direct backup")
    P("  examples (direct backup PPR; team year wk: backup for absent starter):")
    examples(B2, "b2_act", fmt=lambda e: f"{e['tm']} {e['Y']} w{e['wk']} {e['b2_n']} {e['b2_act']:.1f} (for {e['a_n']}; own {e['b2_own']:.1f}, eng {e.get('b2_eng', np.nan):.1f})")
    P("  ABSORBER examples (whoever got the most carries):")
    examples(RB, "ab_act", fmt=lambda e: f"{e['tm']} {e['Y']} w{e['wk']} {e['ab_n']} {e['ab_act']:.1f}{'' if e['ab_has_base'] else ' [body]'}")
    # archetype cells for the engine: residual (act - engine) by the two strongest separators, + quick LOYO of a cell lift
    P("\n  ARCHETYPE CELLS (direct backup, actual - engine replica):")
    cells = {
        "clear RB2 (gap 5+) behind a workhorse": lambda e: e["gap23"] >= 5 and e["a_room"] >= .6,
        "clear RB2 + catches (2.5+ tgt/g)": lambda e: e["gap23"] >= 5 and e["b2_tpg"] >= 2.5,
        "two similar backups (gap < 2)": lambda e: e["gap23"] < 2,
        "low-level backup (own < 6) w/ workhorse out": lambda e: e["b2_own"] < 6 and e["a_room"] >= .6,
        "day-3 / UDFA backup": lambda e: e.get("b2_rnd", np.nan) >= 4,
        "round 1-3 backup": lambda e: e.get("b2_rnd", np.nan) < 4,
        "implied 24+": lambda e: e["implied"] >= 24, "implied < 20": lambda e: e["implied"] < 20,
    }
    E2 = [e for e in B2 if np.isfinite(e.get("b2_eng", np.nan))]
    for lab, sel in cells.items():
        S = [e for e in E2 if sel(e)]
        if len(S) < 8: continue
        res = np.array([e["b2_act"] - e["b2_eng"] for e in S])
        sg = sum(np.mean([e["b2_act"] - e["b2_eng"] for e in S if e["Y"] == y]) > 0 for y in YEARS if any(e["Y"] == y for e in S))
        ny = len({e["Y"] for e in S})
        # quick check: multiply the engine by the training-season ratio (shrunk K 20) -> MSE on held-out season
        w = 0; fw = 0; tb = tn = 0
        for y in YEARS:
            tr = [e for e in S if e["Y"] != y]; te = [e for e in S if e["Y"] == y]
            if not te or not tr: continue
            r = sum(e["b2_act"] for e in tr) / sum(e["b2_eng"] for e in tr); k = len(tr) / (len(tr) + 20); r = 1 + k * (r - 1)
            a0 = np.mean([(e["b2_act"] - e["b2_eng"]) ** 2 for e in te]); a1 = np.mean([(e["b2_act"] - r * e["b2_eng"]) ** 2 for e in te]); w += a1 < a0; tb += a0 * len(te); tn += a1 * len(te)
        for y in YEARS[-4:]:
            tr = [e for e in S if e["Y"] < y]; te = [e for e in S if e["Y"] == y]
            if not te or not tr: continue
            r = sum(e["b2_act"] for e in tr) / sum(e["b2_eng"] for e in tr); k = len(tr) / (len(tr) + 20); r = 1 + k * (r - 1)
            fw += np.mean([(e["b2_act"] - r * e["b2_eng"]) ** 2 for e in te]) < np.mean([(e["b2_act"] - e["b2_eng"]) ** 2 for e in te])
        P(f"    {lab:44s} n {len(S):3d}: act {np.mean([e['b2_act'] for e in S]):5.1f} eng {np.mean([e['b2_eng'] for e in S]):5.1f} gap {res.mean():+5.2f} "
          f"(median {np.median(res):+.1f}; under in {sg}/{ny} seasons) | cell ratio LOYO {w}/{ny} MSE {100*(tn/max(tb,1e-9)-1):+.1f}%, fwd {fw}/4")
        out.setdefault("rb_cells", {})[lab] = dict(n=len(S), act=float(np.mean([e['b2_act'] for e in S])), eng=float(np.mean([e['b2_eng'] for e in S])), loyo=int(w), fwd=int(fw))

    for role in ("WR1", "WR2"):
        L = [e for e in WR if e["role"] == role]
        nx = "WR2" if role == "WR1" else "WR3"
        P(f"\n##### {role} OUT -> next man up {nx} (pre-game): {dist([e['ab_act'] for e in L])}; engine replica mean {np.mean([e['ab_eng'] for e in L]):.1f}")
        P(f"  post-hoc max target gainer (descriptive, selected on the outcome): {dist([e['mg_act'] for e in L])}")
        if role == "WR2": P(f"  healthy WR1 that week: {dist([e['wr1_act'] for e in L])}")
        bins(L, "ab_own", [0, 6, 9, 12, 99], ["own < 6 PPR", "6-9", "9-12", "12+"], "ab_act", "ab_eng")
        bins(L, "ab_tsh", [0, .12, .18, 1], ["tgt share < .12", ".12-.18", ".18+"], "ab_act", "ab_eng")
        bins(L, "ab_ypt", [0, 1.6, 2.0, 99], ["PPR/target < 1.6", "1.6-2.0", "2.0+ (big-play)"], "ab_act", "ab_eng")
        bins(L, "a_tsh", [0, .18, .24, 1], ["absent share < .18", ".18-.24", ".24+ (alpha)"], "ab_act", "ab_eng")
        bins(L, "hhi", [0, .17, .21, 1], ["targets spread (HHI < .17)", ".17-.21", "concentrated .21+"], "ab_act", "ab_eng")
        bins(L, "te_lvl", [0, 6, 10, 99], ["TE < 6 PPR", "TE 6-10", "TE 10+"], "ab_act", "ab_eng")
        bins(L, "qb_pts", [0, 15, 19, 99], ["QB < 15 pts", "QB 15-19", "QB 19+"], "ab_act", "ab_eng")
        bins(L, "implied", [0, 20, 24, 99], ["implied < 20", "20-24", "24+"], "ab_act", "ab_eng")
        bins(L, "ab_rnd", [1, 2, 4, 8, 9], ["round 1", "round 2-3", "round 4-7", "undrafted"], "ab_act", "ab_eng")
        bins(L, "ab_exp", [0, 1, 3, 30], ["rookie", "yr 2-3", "yr 4+"], "ab_act", "ab_eng")
        feats = ["ab_own", "ab_tsh", "ab_ypt", "a_tsh", "hhi", "te_lvl", "qb_pts", "implied", "ab_rnd", "ab_exp"]
        out[f"{role}_model"] = model(L, feats, "ab_act", f"{nx} with {role} out")
        examples(L, "ab_act", fmt=lambda e: f"{e['tm']} {e['Y']} w{e['wk']} {e['ab_n']} {e['ab_act']:.1f} (for {e['a_n']}; own {e['ab_own']:.1f}, eng {e['ab_eng']:.1f})")
        P("  ARCHETYPE CELLS (actual - engine replica):")
        cells = {"next man own 9+ (established)": lambda e: e["ab_own"] >= 9, "next man own < 6 (depth guy)": lambda e: e["ab_own"] < 6,
                 "alpha out (share .24+)": lambda e: e["a_tsh"] >= .24, "concentrated room (HHI .21+)": lambda e: e["hhi"] >= .21,
                 "strong TE (10+)": lambda e: e["te_lvl"] >= 10, "good QB (19+)": lambda e: e["qb_pts"] >= 19, "implied 24+": lambda e: e["implied"] >= 24}
        for lab, sel in cells.items():
            S = [e for e in L if sel(e)]
            if len(S) < 8: continue
            res = np.array([e["ab_act"] - e["ab_eng"] for e in S]); ny = len({e["Y"] for e in S})
            sg = sum(np.mean([e["ab_act"] - e["ab_eng"] for e in S if e["Y"] == y]) > 0 for y in YEARS if any(e["Y"] == y for e in S))
            P(f"    {lab:34s} n {len(S):3d}: act {np.mean([e['ab_act'] for e in S]):5.1f} eng {np.mean([e['ab_eng'] for e in S]):5.1f} gap {res.mean():+5.2f} (median {np.median(res):+.1f}; under in {sg}/{ny} seasons)")
    json.dump(out, open(os.path.join(HERE, "data", "absence_rooms.json"), "w"), indent=1, default=float)
    P("\nwrote data/absence_rooms.json")
    LOG.close()


if __name__ == "__main__":
    main()
