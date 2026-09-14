#!/usr/bin/env python3
"""
Backtest: is the JS Weekly hybrid baseline (Clay workload^0.65 x history^0.35)
more accurate than Clay alone?

For each season Y in 2021-2025, using ONLY what was knowable that preseason:
  clay   = Clay's preseason half-PPR per-game projection (pts - rec/2) / gm
  hist   = 3-yr weighted (0.5/0.3/0.2) half-PPR PPG from actual weekly results
           entering season Y (>=4 gm per contributing season, >=8 total)
  hybrid = exp(W*ln(clay) + (1-W)*ln(hist)),  W = 0.65

Graded against actual half-PPR PPG in season Y (players with >=8 games).
Reports MAE + head-to-head per season and overall, plus a W sweep.
"""
import json, re, math, os

REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"
W_MAIN = 0.65
SEASONS = [2021, 2022, 2023, 2024, 2025]
WTS = [0.5, 0.3, 0.2]

clay_hist = json.load(open(os.path.join(REPO, "data", "clay_history.json"), encoding="utf-8"))
raw = open(os.path.join(REPO, "data", "weekly_stats_active.js"), encoding="utf-8").read()
weekly, _ = json.JSONDecoder().raw_decode(raw, raw.index("{"))

def norm(n):
    n = n.lower().replace(".", "").replace("'", "").replace("-", " ")
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return re.sub(r"\s+", " ", n).strip()

wk_by_norm = {norm(k): v for k, v in weekly.items()}

def ppg(name, season, min_g=1):
    rec = wk_by_norm.get(norm(name))
    if not rec: return None, 0
    wks = rec.get("seasons", {}).get(str(season), [])
    pts = [w["fpts"] for w in wks if isinstance(w.get("fpts"), (int, float))]
    if len(pts) < min_g: return None, len(pts)
    return sum(pts) / len(pts), len(pts)

def hist_entering(name, season):
    num = den = 0.0; total_g = 0
    for i, yr in enumerate([season - 1, season - 2, season - 3]):
        p, g = ppg(name, yr, min_g=4)
        if p is None: continue
        num += WTS[i] * p; den += WTS[i]; total_g += g
    if den == 0 or total_g < 8: return None
    return num / den

def run(w_role):
    per_season = {}
    for Y in SEASONS:
        proj = clay_hist.get(str(Y), {})
        rows = []
        for name, c in proj.items():
            gm = c.get("gm") or 0
            pts = c.get("pts") or 0
            rec = c.get("rec") or 0
            if gm < 8 or pts < 40: continue          # projected regulars only
            clay = max(0.2, (pts - rec / 2.0) / gm)   # half-PPR per game
            hist = hist_entering(name, Y)
            if hist is None: continue                 # hybrid needs history; same pool for both
            hist = max(0.2, hist)
            hyb = math.exp(w_role * math.log(clay) + (1 - w_role) * math.log(hist))
            actual, g = ppg(name, Y, min_g=8)
            if actual is None: continue
            rows.append((abs(clay - actual), abs(hyb - actual), abs(hist - actual)))
        if rows:
            n = len(rows)
            per_season[Y] = {
                "n": n,
                "clay_mae": sum(r[0] for r in rows) / n,
                "hyb_mae": sum(r[1] for r in rows) / n,
                "hist_mae": sum(r[2] for r in rows) / n,
                "hyb_wins": sum(1 for r in rows if r[1] < r[0]),
                "hyb_losses": sum(1 for r in rows if r[1] > r[0]),
            }
    return per_season

res = run(W_MAIN)
print(f"=== W (Clay role weight) = {W_MAIN} — graded vs actual half-PPR PPG, players w/ >=8 games ===")
tot_n = tot_c = tot_h = tot_hist = tot_w = tot_l = 0
for Y, r in res.items():
    print(f"{Y}: n={r['n']:3d}  MAE clay={r['clay_mae']:.3f}  hybrid={r['hyb_mae']:.3f}  hist-only={r['hist_mae']:.3f}"
          f"  | hybrid beats clay {r['hyb_wins']}-{r['hyb_losses']} ({100*r['hyb_wins']/(r['hyb_wins']+r['hyb_losses']):.0f}%)")
    tot_n += r['n']; tot_c += r['clay_mae']*r['n']; tot_h += r['hyb_mae']*r['n']; tot_hist += r['hist_mae']*r['n']
    tot_w += r['hyb_wins']; tot_l += r['hyb_losses']
print(f"ALL:  n={tot_n}  MAE clay={tot_c/tot_n:.3f}  hybrid={tot_h/tot_n:.3f}  hist-only={tot_hist/tot_n:.3f}"
      f"  | hybrid beats clay {tot_w}-{tot_l} ({100*tot_w/(tot_w+tot_l):.0f}%)")

print("\n=== W sweep (overall MAE) ===")
for w in [1.0, 0.9, 0.8, 0.7, 0.65, 0.6, 0.5, 0.4, 0.3, 0.0]:
    rs = run(w)
    n = sum(r['n'] for r in rs.values())
    mae = sum(r['hyb_mae']*r['n'] for r in rs.values()) / n
    print(f"W={w:.2f}  hybrid MAE={mae:.4f}" + ("   <- pure Clay" if w == 1.0 else ("   <- pure history" if w == 0.0 else "")))
