import io, os, re
os.chdir(r"E:\MyFantasyFootball\sim_lab")
p = "app.js"; s = io.open(p, encoding="utf-8").read()
anchor = "    var few = Object.keys(B.flags || {}).filter("
assert s.count(anchor) == 1 and "SIM_DECAYHIST_BT" not in s
panel = r"""    var DKH = window.SIM_DECAYHIST_BT;
    if (DKH && DKH.weekly) {
      var dkCuts = ['TOP 150 wtd', 'ADP 1-30', '31-60', '61-100', '101-150', 'games 1-3', 'games 4+'];
      var dkTab = function (rows, yrs) { var by = {}; rows.forEach(function (r) { (by[r.variant] = by[r.variant] || {})[r.cut] = r; }); return Object.keys(by).filter(function (k) { return k !== 'current shadow'; }).map(function (k) { return '<tr><td class="l">' + esc(k) + '</td>' + dkCuts.map(function (c) { var r = by[k][c]; if (!r) return '<td></td>'; return '<td style="color:' + ((r.d <= -0.3 && r.wins > yrs / 2) ? 'var(--acc)' : (r.d >= 0.3 ? '#f85149' : 'inherit')) + '">' + (r.d >= 0 ? '+' : '') + r.d.toFixed(2) + '% <span class="dim">(' + r.wins + '/' + yrs + ')</span></td>'; }).join('') + '</tr>'; }).join(''); };
      var dkHead = '<thead><tr><th class="l">Variant</th>' + dkCuts.map(function (c) { return '<th>' + esc(c) + '</th>'; }).join('') + '</tr></thead>';
      html += '<h4 style="margin:14px 0 4px">Decayed-games history inside the full shadow (backtest_decayed_history.py, ' + esc(DKH.updated || '') + ') \u2014 NOT APPLIED</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(DKH.summary || '') + '</b> Jack: "lets build the decayed history". As a stand-alone predictor the decayed average of past games (half-life 12) is clearly better: refitting the veterans\u2019 history + opportunity blend on it cuts that blend\u2019s error ' + (DKH.blend && DKH.blend.length > 2 ? ((DKH.blend[2].mse / DKH.blend[0].mse - 1) * 100).toFixed(1) : '') + '% and the opportunity model\u2019s weight falls to about zero (the decayed history already carries it). But inside the finished shadow the history is a minor input \u2014 75% ADP market curve, 0.8 shrink, half the prior from the ridge (which already weighs 3-season and last-8 separately), and the in-season blend takes over after a few games \u2014 so nothing moves: every variant is within \u00b10.15% of today\u2019s shadow and weekly rank accuracy is flat to slightly worse. Swapping the ridge\u2019s three history features for the one decayed number loses information (+0.1%). Verdict: no live game-log feed built; shadow unchanged. Cells = error vs the current shadow (negative = better) and seasons better.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto">' + dkHead + '<tbody><tr><td class="l dim" colspan="8"><b>Leave-one-season-out, 2019-25</b></td></tr>' + dkTab(DKH.weekly, 7) + '<tr><td class="l dim" colspan="8" style="padding-top:6px"><b>Forward, 2021-25</b></td></tr>' + dkTab(DKH.forward, 5) + '</tbody></table></div>';
    }
"""
s = s.replace(anchor, panel + anchor); io.open(p, "w", encoding="utf-8", newline="\n").write(s)
h = io.open("index.html", encoding="utf-8").read()
tag = re.search(r'<script src="data/vs_espn\.js\?v=[^"]+"></script>', h).group(0)
if "decayed_history.js" not in h:
    h = h.replace(tag, tag + "\n" + tag.replace("vs_espn.js", "decayed_history.js")); io.open("index.html", "w", encoding="utf-8", newline="\n").write(h)
readme = """

## Decayed-games history inside the full shadow (backtest_decayed_history.py) - 2026-09-17 - NOT APPLIED

Jack: "lets build the decayed history". backtest_opp_prior.py now also dumps raw OPP / HIST / HISTREG (SHADOWCAL
unchanged on 1982 of 1982). dk = exponentially decayed mean of games before the season (4 prior seasons, 8+ games).
- HIST + OPP blend refit on dk (926 vets, LOYO): MSE 9.36 (regressed 3-season) -> 8.68 (hl 8) / 8.60 (hl 12 and 16), -8%.
  The opportunity coefficient collapses to ~0 (RB .10, WR .04, TE .18 at hl 12): dk already carries what the
  opportunity model knows.
- In the FULL weekly shadow (v2.22 form; top 150 importance-weighted, LOYO | forward 2021-25):
  hand prior on dk -0.00% (4/7) | +0.01% (2/5); ridge hist/h3/l8 -> dk +0.12% (0/7) | +0.07%; both +0.12%; ridge ADDS dk
  +0.01% | +0.04% (0/5). Rank rho .3781 -> .3775 / .3765.
- Giving history more weight vs the ADP market (vet market weight .75 -> .55): dk -0.10% (5/7) | -0.14% (5/5), ADP 1-30
  -0.19% (6/7); today's history at .55 gets -0.06% | -0.13% of that on its own; rho flat/slightly lower. Too small to act on.
- Why: history is a minor input by the time the shadow is finished (75% market curve, 0.8 shrink, 50% ridge that
  already weighs 3-season and last-8 separately, in-season blend). The -3% stand-alone gain is real but has nowhere to go.
- Verdict: no live game-log feed, engine unchanged. ZONES panel SIM_DECAYHIST_BT.
"""
r = io.open("README.md", encoding="utf-8").read()
if "Decayed-games history inside the full shadow" not in r: io.open("README.md", "a", encoding="utf-8", newline="\n").write(readme)
M = r"C:\Users\billi\.claude\projects\E--MyFantasyFootball-MyFantasyFootball-Files\memory"
mem = """---
name: project_decayed_history
description: 09-17 REJECTED - decayed-games history (half-life 8-16) beats 3-season history by 8% inside the HIST+OPP blend but moves the full weekly shadow by 0.0% (rank flat); history is a minor input after the ADP curve, shrink and ridge; no live feed built
metadata:
  type: project
---

Jack (2026-09-17): "lets build the decayed history". sim_lab/backtest_decayed_history.py; ZONES panel SIM_DECAYHIST_BT.
- backtest_opp_prior.py now dumps raw OPP / HIST / HISTREG into opp_prior_preds.json (SHADOWCAL unchanged).
- HIST+OPP refit on decayed games: blend MSE 9.36 -> 8.60 (-8%); opportunity coefficient falls to ~0.
- Full weekly shadow, top 150 weighted: hand prior on dk 0.00% (4/7), fwd +0.01%; replacing ridge hist/h3/l8 with dk
  +0.12% (0/7); adding dk to the ridge +0.01%. Rank rho .3781 -> .3765-.3775.
- Lowering the vets' ADP market weight .75 -> .55 with dk: -0.10% (5/7), fwd -0.14% (5/5), ADP 1-30 -0.19%; rank flat.

**Why:** the shadow's prior is 75% ADP curve + 0.8 shrink + 50% ridge, and in-season evidence takes over within weeks, so
a better raw history has nowhere to go.
**How to apply:** do not build a live game-log feed for this; prior-side history work is exhausted - in-season gains must
come from evidence/usage/matchup, not the preseason history. See [[project_shadow_audit]], [[project_opp_prior]],
[[feedback_inseason_rank_objective]].
"""
io.open(M + r"\project_decayed_history.md", "w", encoding="utf-8", newline="\n").write(mem)
f = M + r"\MEMORY.md"; t = io.open(f, encoding="utf-8").read()
line = "- [Decayed-games history](project_decayed_history.md) — 09-17 REJECTED: -8% inside the HIST+OPP blend but 0.0% in the full shadow (rank flat); history is a minor input; no live feed\n"
if "project_decayed_history" not in t: t = t.replace("- [Season-long harness]", line + "- [Season-long harness]", 1)
io.open(f, "w", encoding="utf-8", newline="\n").write(t); print("ok")
