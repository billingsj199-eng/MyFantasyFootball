#!/usr/bin/env python3
"""
WHERE DOES THE SHADOW STILL LOSE TO THE BLEND, BY POSITION? (Jack 2026-10-08: "what else can we improve to get rid of the blend")
Same decomposition that cracked tight ends (research_te_gap.py), run per position on the honest replica (TD luck + TE docks .5):
  1  prior alone at 0 games (shadow prior / hand / ridge / history / Clay) - next game AND rest of season
  2  evidence reads at 4+ games (raw PPG, context PPG, xFP, target-share and route-rate mixes) - Jack: are usage inputs under-weighted?
  3  where the shadow-minus-Clay error sits, next game and rest of season (cuts: ADP band, games, rookies, prior type)
  4  level by layer state (docked / neutral / lifted) and by scoring-over-usage
  5  component swaps: shadow with Clay's prior; with the live QB floor (QB); prior strength x .5 / x 2; TD luck off
Usage: python research_pos_gap.py QB|RB|WR   -> log pos_gap_<POS>.log. Research only.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
POS = sys.argv[1].upper() if len(sys.argv) > 1 else "QB"
LOG = open(os.path.join(HERE, f"pos_gap_{POS}.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
BBW = {"QB": 0.5, "RB": 0.8, "WR": 0.7, "TE": 0.0}


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, g, adp, name, pid = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], A["pid"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X); clay_gm = LV["clay_gm"]
    bw = np.array([BBW[p_] for p_ in pos]); BLEND = bw * SHADOW + (1 - bw) * TODAY
    base = top150 & ~final & ~LV["inh"]; PM = pos == POS; mP = base & PM
    hist = F["hist"]; has_hist = ~np.isnan(hist); vet_opp = F["vet_opp"]; hand = F["prior"]; prior = X["prior"]
    ridge_on = np.abs(prior - hand) > 1e-9; ridge = np.where(ridge_on, 2 * prior - hand, np.nan)
    L = X["layers"]
    # rest-of-season target / context
    seqn = defaultdict(list)
    for i in range(n):
        if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ix in seqn.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(L[ix], 0.5, 1.8)
        for a, i in enumerate(ix): nfut[i] = len(ix) - a; Tr[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    ctx0 = np.nan_to_num(ctx, nan=1.0); ros = lambda p: p / np.maximum(L, 0.3) * ctx0
    mR = mP & (g >= 1) & (g <= 10) & ~np.isnan(Tr) & (nfut >= 4)
    def wm(p, m, T=act): return float(np.average((p[m] - T[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    def line(lab, p, ref, m, T=act):
        wins = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and wm(p, m & (year == y), T) < wm(ref, m & (year == y), T) - 1e-12)
        r = RG.rank_stats(p, m, T, year, wk, pos)[0]; r0 = RG.rank_stats(ref, m, T, year, wk, pos)[0]
        return f"{lab:40s} {100*(wm(p, m, T)/wm(ref, m, T)-1):+6.2f}% ({wins}/7) | rho {r:.3f} ({r - r0:+.4f}) | level {T[m].sum()/p[m].sum():.3f}"
    P(f"=== {POS} GAP: {int(mP.sum()):,} top-150 {POS} player-weeks 2019-25 (honest replica: TD luck in, TE docks .5) ===")
    P("  next game:        " + line("shadow alone vs Clay form", SHADOW, TODAY, mP)); P("                    " + line("shadow alone vs the BLEND", SHADOW, BLEND, mP)); P("                    " + line("blend vs Clay form", BLEND, TODAY, mP))
    P("  rest of season:   " + line("shadow alone vs Clay form", ros(SHADOW), ros(TODAY), mR, Tr)); P("                    " + line("shadow alone vs the BLEND", ros(SHADOW), ros(BLEND), mR, Tr)); P("                    " + line("blend vs Clay form", ros(BLEND), ros(TODAY), mR, Tr))
    P(f"  inputs: ADP {100*(~np.isnan(adp[mP])).mean():.0f}% | history {100*has_hist[mP].mean():.0f}% | ridge {100*ridge_on[mP].mean():.0f}% | opportunity prior {100*vet_opp[mP].mean():.0f}% | rookies {100*X['rookie'][mP].mean():.0f}%")
    P("\n--- 1  PRESEASON PRIOR ALONE (0 games, x the game's layers) ---")
    m0 = mP & (g == 0)
    cands = {"shadow prior (wired)": prior * L, "hand prior": hand * L, "ridge (where it exists)": np.where(ridge_on, ridge, prior) * L, "Clay per game": clay_gm * L, "history prior (where it exists)": np.where(has_hist, hist, prior) * L, "50/50 shadow prior + Clay": 0.5 * (prior + clay_gm) * L}
    for lab, T, mm in (("next game", act, m0), ("rest of season 4+", Tr, m0 & ~np.isnan(Tr) & (nfut >= 4))):
        P(f"  {lab} (n{int(mm.sum())}):")
        for k, p in cands.items(): P("    " + line(k + " vs Clay", p, cands["Clay per game"], mm, T))
        for clab, cm in (("rookies", X["rookie"]), ("vets", ~X["rookie"]), ("ADP <= 60", adpx <= 60), ("ADP 61-150", adpx > 60)):
            mc = mm & cm
            if mc.sum() < 25: continue
            P(f"      {clab:12s} n{int(mc.sum()):4d} | shadow prior vs Clay {100*(wm(cands['shadow prior (wired)'], mc, T)/wm(cands['Clay per game'], mc, T)-1):+6.2f}% | level shadow {T[mc].sum()/cands['shadow prior (wired)'][mc].sum():.3f} Clay {T[mc].sum()/cands['Clay per game'][mc].sum():.3f}")
    P("\n--- 2  IN-SEASON EVIDENCE ALONE (4+ games, x layers) vs the next game: is usage under-weighted? ---")
    m4 = mP & (g >= 4)
    from backtest_inseason_usage import route_features
    rt, _ = route_features(year, pid, wk); tg = X["tgt_sh"]
    ev = {"raw PPG": X["ppg"] * L, "context-regressed PPG (ppg_v)": X["ppg_v"] * L, "xFP per game": X["xf"] * L, ".5 xFP + .5 ppg_v": (0.5 * X["xf"] + 0.5 * X["ppg_v"]) * L, ".25 xFP + .75 ppg_v": (0.25 * X["xf"] + 0.75 * X["ppg_v"]) * L}
    if POS in ("WR", "RB"):
        # target-share and route-rate scaled reads: ppg_v x (share / position median share)^.5
        for lab, s_ in (("target share", tg), ("route rate", rt)):
            ok_ = m4 & ~np.isnan(s_) & (s_ > 0); med = np.nanmedian(s_[ok_]) if ok_.any() else np.nan
            ev[f"ppg_v x ({lab}/median)^.5"] = np.where(ok_, X["ppg_v"] * np.sqrt(np.clip(s_ / max(med, 1e-9), 0.5, 2.0)), X["ppg_v"]) * L
    ev["shadow (prior + evidence + layers)"] = SHADOW; ev["blend"] = BLEND
    for k, p in ev.items(): P("  " + line(k + " vs Clay form", p, TODAY, m4))
    P("\n--- 3  WHERE THE GAP SITS: shadow minus Clay by cut (share of the total gap), next game | rest of season ---")
    cuts = (("ADP 1-30", adpx <= 30), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100)), ("101-150", adpx > 100), ("games 0", g == 0), ("games 1-3", (g >= 1) & (g <= 3)), ("games 4-8", (g >= 4) & (g <= 8)), ("games 9+", g >= 9), ("rookies", X["rookie"]), ("2nd year", (~X["rookie"]) & (np.array(A["exp"], float) == 1)), ("no history", ~has_hist), ("opportunity prior", vet_opp), ("history prior", has_hist & ~vet_opp))
    for hlab, T, m, tf in (("NEXT", act, mP, lambda p: p), ("ROS", Tr, mR, ros)):
        S_, C_ = tf(SHADOW), tf(TODAY); tot_s = float(np.sum(wt[m] * (S_[m] - T[m]) ** 2)); tot_c = float(np.sum(wt[m] * (C_[m] - T[m]) ** 2))
        P(f"  {hlab}: shadow vs Clay {100*(tot_s/tot_c-1):+.2f}% overall")
        for lab, cm in cuts:
            mm = m & cm
            if mm.sum() < 20: continue
            es = float(np.sum(wt[mm] * (S_[mm] - T[mm]) ** 2)); ec = float(np.sum(wt[mm] * (C_[mm] - T[mm]) ** 2))
            P(f"    {lab:18s} n{int(mm.sum()):4d} | shadow vs Clay {100*(es/ec-1):+6.2f}% | of the gap {100*(es-ec)/max(1e-9, abs(tot_s-tot_c)):+6.1f}% | level act/shadow {T[mm].sum()/S_[mm].sum():.3f} act/Clay {T[mm].sum()/C_[mm].sum():.3f}")
    P("\n--- 4  LEVEL by the shadow's layer state and scoring-over-usage (2+ games) ---")
    shl = SHADOW / np.maximum(SN.shadow(X), 1e-9)
    for lab, cm in (("extra layers < .95 (docked)", shl < 0.95), ("extra layers .95-1.05", (shl >= 0.95) & (shl <= 1.05)), ("extra layers > 1.05 (lifted)", shl > 1.05), ("game layers < .9", L < 0.9), ("game layers > 1.1", L > 1.1)):
        m = mP & (g >= 1) & cm
        if m.sum() < 20: continue
        P(f"  {lab:36s} n{int(m.sum()):4d} | act/shadow {act[m].sum()/SHADOW[m].sum():.3f} act/Clay {act[m].sum()/TODAY[m].sum():.3f} | shadow vs Clay {100*(wm(SHADOW, m)/wm(TODAY, m)-1):+6.2f}%")
    m2 = mP & (g >= 2) & X["has_x"] & (X["xf"] > 0); sou = np.where(m2, X["ppg"] / np.maximum(X["xf"], 0.1), np.nan)
    if m2.sum() >= 80:
        q = np.nanpercentile(sou[m2], [25, 50, 75]); e = [-9] + list(q) + [99]
        for a in range(4):
            m = m2 & (sou >= e[a]) & (sou < e[a + 1])
            P(f"  scoring/usage Q{a+1} ({e[a]:.2f}-{e[a+1]:.2f}) n{int(m.sum()):4d} | act/shadow {act[m].sum()/SHADOW[m].sum():.3f} act/Clay {act[m].sum()/TODAY[m].sum():.3f} | shadow vs Clay {100*(wm(SHADOW, m)/wm(TODAY, m)-1):+6.2f}%")
    P("\n--- 5  COMPONENT SWAPS on the shadow (position rows only), next game | rest of season, vs shadow and vs Clay form ---")
    def swap(**kw):
        X2 = dict(X)
        for k, v in kw.items(): X2[k] = v
        return BR.shadow_current(X2)[0]
    mu = None
    if POS == "QB":
        import json
        ch = json.load(open(os.path.join(BR.cal.REPO, "data", "clay_history.json"), encoding="utf-8")); mu_y = {}
        for y in YEARS:
            wy = 16.0 if y <= 2020 else 17.0
            lvq = sorted([max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0) / wy for c in ch[str(y)].values() if c.get("pos") == "QB"], reverse=True)[:32]; mu_y[y] = float(np.mean(lvq))
        mu = np.array([mu_y[int(y)] for y in year])
    V = {"Clay per game as the prior": swap(prior=np.where(PM, clay_gm, prior)), "50/50 shadow prior + Clay prior": swap(prior=np.where(PM, 0.5 * (prior + clay_gm), prior)),
         "prior strength x .5": None, "prior strength x 2": None, "TD luck off": BR.shadow_current(X, luck=False)}
    F2 = dict(F); F2["Pvec"] = np.where(PM, F["Pvec"] * 0.5, F["Pvec"]); V["prior strength x .5"] = swap(F=F2)
    F3 = dict(F); F3["Pvec"] = np.where(PM, F["Pvec"] * 2.0, F["Pvec"]); V["prior strength x 2"] = swap(F=F3)
    if POS == "QB" and mu is not None:
        fl = PM & (SHADOW >= 5) & (SHADOW < mu * L); V["live QB floor (mu + .7 x (x - mu) below mu)"] = np.where(fl, mu * L + 0.70 * (SHADOW - mu * L), SHADOW)
    for k, p in V.items():
        P("  NEXT " + line(k + " vs shadow", p, SHADOW, mP) + f" | vs Clay {100*(wm(p, mP)/wm(TODAY, mP)-1):+6.2f}%")
        P("  ROS  " + line(k + " vs shadow", ros(p), ros(SHADOW), mR, Tr) + f" | vs Clay {100*(wm(ros(p), mR, Tr)/wm(ros(TODAY), mR, Tr)-1):+6.2f}%")
    P("\nLimitations: harness replicas (no book anchor / docks / prior lift / QB window); ridge recovered from the 50/50 mix; nothing here is a layer test.")
    LOG.close()


if __name__ == "__main__":
    main()
