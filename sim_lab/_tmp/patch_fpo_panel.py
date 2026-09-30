import io, os, re
os.chdir(r"E:\MyFantasyFootball\sim_lab")
p = "app.js"; s = io.open(p, encoding="utf-8").read()
anchor = "    var few = Object.keys(B.flags || {}).filter("
assert s.count(anchor) == 1 and "SIM_FPLAYOFF_BT" not in s
panel = r"""    var FPO = window.SIM_FPLAYOFF_BT;
    if (FPO && FPO.stage) {
      var fpM = ['Clay blend today', 'shadow', '70/30 blend', 'rank mix (shadow + ESPN)'];
      var fpRow = function (r) { return '<tr><td class="l">' + esc(r.stage) + '</td><td class="dim">' + r.n + '</td><td><b>' + r.ESPN.rmse.toFixed(2) + '</b> <span class="dim">\u03c1 ' + r.ESPN.rho.toFixed(3) + '</span></td>' + fpM.map(function (k) { var c = r[k]; return '<td style="color:' + ((c.vsEspn <= -0.3 && c.wins > c.years / 2) ? 'var(--acc)' : (c.vsEspn >= 0.3 ? '#f85149' : 'inherit')) + '">' + c.rmse.toFixed(2) + ' <span class="dim">(' + (c.vsEspn >= 0 ? '+' : '') + c.vsEspn.toFixed(2) + '%, ' + c.wins + '/' + c.years + ') \u03c1 ' + c.rho.toFixed(3) + '</span></td>'; }).join('') + '</tr>'; };
      html += '<h4 style="margin:14px 0 4px">Fantasy-playoff weeks, final week dropped (backtest_fantasy_playoffs.py, ' + esc(FPO.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(FPO.summary || '') + '</b> Jack: "dont worry about the final week of every season \u2026 the weeks besides last historically are very important as its fantasy playoffs". Final week = 17 (2019-20) / 18 (2021+), playoffs = the three weeks before it. Top 150, typical miss; brackets = error vs ESPN and seasons better than ESPN; \u03c1 = weekly within-position rank. With the final week out the rank mix beats ESPN on points in all 7 seasons and has the best ranking at every stage after week 1; in the playoffs every one of our own models trails ESPN on points (+2.6%) but ties it on ranking, and the mix is the best ranking we have (\u03c1 .421). The playoff loss sits with players whose last 4 games ran 3+ below their season rate (+8% vs ESPN; QBs and TEs over-projected ~1.5 points): cold finishes persist, hot ones regress. A cold-only recency term is right in direction but worth only \u22120.1 to \u22120.2% (4-5/7) with no rank gain, and symmetric recency, shorter in-season windows and a lighter late prior all lose \u2014 NOT applied.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Stage</th><th>n</th><th>ESPN</th><th>Clay blend today</th><th>Shadow</th><th>70/30 blend</th><th>Rank mix</th></tr></thead><tbody>' + FPO.stage.map(fpRow).join('') + '</tbody></table></div>';
      if (FPO.asym) html += '<p class="dim" style="font-size:11px;margin:6px 0">Cold-streak variants (top 150 weighted error vs the shadow, playoffs | all non-final weeks): ' + FPO.asym.map(function (r) { return esc(r.variant) + ' ' + (r.playoffs.d >= 0 ? '+' : '') + r.playoffs.d.toFixed(2) + '% (' + r.playoffs.wins + '/7) | ' + (r['all non-final'].d >= 0 ? '+' : '') + r['all non-final'].d.toFixed(2) + '% (' + r['all non-final'].wins + '/7)'; }).join(' \u00b7 ') + '.</p>';
    }
"""
s = s.replace(anchor, panel + anchor); io.open(p, "w", encoding="utf-8", newline="\n").write(s)
h = io.open("index.html", encoding="utf-8").read()
tag = re.search(r'<script src="data/vs_espn\.js\?v=[^"]+"></script>', h).group(0)
if "fantasy_playoffs.js" not in h:
    h = h.replace(tag, tag + "\n" + tag.replace("vs_espn.js", "fantasy_playoffs.js")); io.open("index.html", "w", encoding="utf-8", newline="\n").write(h)
readme = """

## Fantasy-playoff weeks, final week dropped (backtest_fantasy_playoffs.py) - 2026-09-17 - grading rule; no model change

Jack: "dont worry about the final week of every season usually fantasy seasons are over but the weeks besides last
historically are very important as its fantasy playoffs". RULE from now on: drop the final week (17 in 2019-20, 18 from
2021) from every grade and fit; report a FANTASY PLAYOFFS cut (the three weeks before it).
- Top 150, ESPN-graded rows, final week out (10,403): ESPN 7.11 rho .379 | Clay blend today +2.59% (0/7) .369 | shadow
  +0.91% (2/7) .381 | 70/30 blend +0.72% (3/7) .382 | RANK MIX (50 shadow + 50 ESPN) -0.99% (7/7) .389.
- Playoffs (1,869): ESPN 7.27 rho .409 | Clay +3.34% | shadow +2.64% (2/7) .407 | 70/30 +2.61% | rank mix +0.01% rho .421.
  The final week itself was our worst stage (shadow +4.4%, Clay +8.8%) - rested starters; it was inflating every gap.
- Where the playoff loss sits: last 4 games 3+ below the season rate (n 271): shadow +8.2% vs ESPN, projected 13.20 vs
  actual 12.28 (ESPN 12.48). Hot finishes: shadow BEATS ESPN (-1.9%; ESPN chases them, 14.11 vs 13.36). By position for
  cold players weeks 10+: QB 19.96 vs 18.52, TE 9.30 vs 7.77, RB 13.36 vs 13.09, WR 11.62 vs 11.15. Team implied 24+ +4.0%.
- Fixes (top 150 weighted, vs the shadow): in-season decayed PPG hl 3 / 5 / 8 = +0.97 / +0.36 / +0.12% in the playoffs;
  .4 x last 4 +0.48%; prior x0.5 / x0 / x2 after 10 games all lose; COLD-ONLY recency w .25 = -0.21% playoffs (4/7),
  -0.10% all (4/7), rho +.001; QB+TE only -0.15% (5/7). Right direction, too small - NOT applied.
- Takeaway: late-season edge = the ESPN mix (news we do not have: rest, role changes), not another evidence window.
"""
r = io.open("README.md", encoding="utf-8").read()
if "Fantasy-playoff weeks, final week dropped" not in r: io.open("README.md", "a", encoding="utf-8", newline="\n").write(readme)
M = r"C:\Users\billi\.claude\projects\E--MyFantasyFootball-MyFantasyFootball-Files\memory"
mem = """---
name: project_fantasy_playoffs
description: 09-17 final week dropped + fantasy-playoff cut - rank mix beats ESPN 7/7 (-1.0%, rho .389); playoffs shadow +2.6% vs ESPN on points but tied on rank, mix rho .421; loss = cold-finish players (cold persists, hot regresses); cold-only recency -0.1-0.2% NOT applied
metadata:
  type: project
---

sim_lab/backtest_fantasy_playoffs.py; ZONES panel SIM_FPLAYOFF_BT. Implements [[feedback_final_week_excluded]].
- Final week out, top 150: ESPN 7.11 / Clay blend today +2.6% (0/7) / shadow +0.9% / 70-30 +0.7% / rank mix -1.0% (7/7),
  rho .379 / .369 / .381 / .382 / .389. The final week was our worst stage and inflated every earlier gap.
- Playoffs: shadow +2.6% vs ESPN (2/7) but rank tied (.407 vs .409); rank mix rho .421, points +0.0%.
- Loss concentrated in players whose last 4 ran 3+ below season PPG (+8% vs ESPN, over-projected ~0.9; QB/TE ~1.5).
  Hot finishers: shadow beats ESPN, which chases them. Asymmetry: cold persists, hot regresses.
- Tested and NOT applied: in-season decayed PPG, last-4 blend, lighter/heavier late prior (all lose); cold-only recency
  w .25 -0.21% playoffs / -0.10% all (4/7), no rank gain.

**Why:** Jack plays for the fantasy playoffs; the week after them is noise.
**How to apply:** new backtests should mask the final week and print a playoff cut. Late-season accuracy comes from the
ESPN mix ([[project_rank_mix]]), not another evidence window. See [[project_vs_espn]].
"""
io.open(M + r"\project_fantasy_playoffs.md", "w", encoding="utf-8", newline="\n").write(mem)
f = M + r"\MEMORY.md"; t = io.open(f, encoding="utf-8").read()
line = "- [Fantasy-playoff weeks](project_fantasy_playoffs.md) — 09-17: final week out, rank mix beats ESPN 7/7 (rho .389); playoffs = tied on rank, mix .421; cold finishes persist / hot regress, cold-only recency too small, NOT applied\n"
if "project_fantasy_playoffs" not in t: t = t.replace("- [Season-long harness]", line + "- [Season-long harness]", 1)
io.open(f, "w", encoding="utf-8", newline="\n").write(t); print("ok")
