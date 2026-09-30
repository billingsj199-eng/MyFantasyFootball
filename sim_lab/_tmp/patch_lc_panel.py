import io, os, re
os.chdir(r"E:\MyFantasyFootball\sim_lab")
p = "app.js"; s = io.open(p, encoding="utf-8").read()
anchor = "    var few = Object.keys(B.flags || {}).filter("
assert s.count(anchor) == 1 and "SIM_LIVECAND_BT" not in s
panel = r"""    var LCB = window.SIM_LIVECAND_BT;
    if (LCB && LCB.ladder) {
      var lcFw = {}; (LCB.forward || []).forEach(function (r) { lcFw[r.model] = r; });
      var lcRow = function (r) { var f = lcFw[r.model], hot = /^5|^6/.test(r.model); return '<tr' + (hot ? ' style="font-weight:600"' : '') + '><td class="l">' + esc(r.model) + '</td><td style="color:' + (r.d <= -0.3 && r.wins >= 5 ? 'var(--acc)' : 'inherit') + '">' + (r.d >= 0 ? '+' : '') + r.d.toFixed(2) + '% <span class="dim">(' + r.wins + '/7)</span></td><td class="dim">' + (r.step != null ? (r.step >= 0 ? '+' : '') + r.step.toFixed(2) : '') + '</td><td>' + r.rho.toFixed(4) + '</td><td>' + r.pairs.toFixed(2) + '%</td><td>' + r.rmse.toFixed(3) + '</td><td class="dim">' + (f ? (f.d >= 0 ? '+' : '') + f.d.toFixed(2) + '% (' + f.wins + '/5)' : '') + '</td></tr>'; };
      html += '<h4 style="margin:14px 0 4px">The combined LIVE CANDIDATE (backtest_live_candidate.py, ' + esc(LCB.updated || '') + ') \u2014 NOT applied, Jack\u2019s decision</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(LCB.summary || '') + '</b> Jack: "lets build the combined live candidate". The five fixes that each passed alone, stacked one at a time on today\u2019s live pre-book number (Clay per-game prior, 5-game strength, x Vegas x points-allowed); top 150 importance-weighted, final week dropped; last column = the same ladder with the shadow\u2019s learned prior fitted on earlier seasons only, 2021-25. The gains stack almost fully: steps 1-3 touch only the Clay blend (\u22121.6%, 7/7), step 4 adds nothing and can be skipped, the 70/30 mix with the shadow takes it to \u22122.5% (7/7; forward \u22122.7%, 5/5), and mixing ESPN 50/50 on top reaches \u22123.3% (7/7) with the best ranking measured. Once ESPN is in, the Clay side adds nothing (candidate + ESPN = shadow + ESPN). Weakest cuts: fantasy playoffs (\u22121.0%, 4/7 without ESPN; \u22122.8%, 6/7 with it), QB and TE (4/7). The live board then anchors 70% to book lines where they exist; that layer cannot be backtested and sits on top of whichever base is chosen.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Step</th><th>Error vs today</th><th>Step</th><th>Rank \u03c1</th><th>Pairs right</th><th>Typical miss</th><th>Forward 2021-25</th></tr></thead><tbody>' + LCB.ladder.map(lcRow).join('') + '</tbody></table></div>';
      if (LCB.espn) html += '<p class="dim" style="font-size:11px;margin:6px 0">vs ESPN on ESPN-graded rows: ' + LCB.espn.filter(function (r) { return r.model !== 'ESPN'; }).map(function (r) { return esc(r.cut) + ' \u2014 ' + esc(r.model.split(':')[0]) + ' ' + (r.vsEspn >= 0 ? '+' : '') + r.vsEspn.toFixed(2) + '% (' + r.wins + '/7)'; }).join(' \u00b7 ') + '.</p>';
    }
"""
s = s.replace(anchor, panel + anchor); io.open(p, "w", encoding="utf-8", newline="\n").write(s)
h = io.open("index.html", encoding="utf-8").read()
tag = re.search(r'<script src="data/vs_espn\.js\?v=[^"]+"></script>', h).group(0)
if "live_candidate.js" not in h:
    h = h.replace(tag, tag + "\n" + tag.replace("vs_espn.js", "live_candidate.js")); io.open("index.html", "w", encoding="utf-8", newline="\n").write(h)
readme = """

## The combined LIVE CANDIDATE (backtest_live_candidate.py) - 2026-09-17 - NOT applied, Jack's decision

Jack: "lets build the combined live candidate". Five pending fixes stacked on today's live pre-book number; top 150
importance-weighted, final week dropped, 10,542 player-weeks; (seasons better of 7) | forward 2021-25 (ridge on earlier seasons).
  0 TODAY                                  0.00%          rho .3697 pairs 63.83% miss 7.197
  1 + Vegas-adjusted evidence             -0.67% (6/7)    .3732                         | fwd -0.72% (4/5)
  2 + tiered Clay prior ADP<=60           -1.27% (7/7)    .3764                         | -1.22% (5/5)
  3 + backup-QB WR dock                   -1.59% (7/7)    .3769 64.02%                  | -1.60% (5/5)
  4 + usage / WR one-game / QB total      -1.62% (7/7)    .3781   (adds nothing - skip) | -1.58%
  5 LIVE CANDIDATE 70/30 shadow + step 4  -2.45% (7/7)    .3857 64.39% miss 7.120       | -2.65% (5/5)
  6 + ESPN 50/50                          -3.34% (7/7)    .3891 64.88% miss 7.067       | -3.53% (5/5)
  shadow v2.24 alone -2.28% (6/7) .3837 | rank mix (shadow + ESPN) -3.34% (7/7) .3890 | ESPN alone -2.20% (7/7) .3803
- Cuts (candidate | + ESPN): week 1 -2.1% | -3.8% (5/7); weeks 2-4 -3.9% (7/7) | -4.5%; 5-9 -2.3% (7/7) | -2.9%; 10-to-playoffs
  -2.6% (7/7) | -3.3%; PLAYOFFS -1.0% (4/7) | -2.8% (6/7); ADP 1-30 -3.4% (7/7); 31-60 -1.3% (6/7) | -2.2%; 61-100 -1.7% |
  -3.4%; 101-150 -1.4% | -3.9%; QB -1.4% (4/7) | -2.4% (6/7); RB -2.7% (7/7); WR -2.8% (7/7); TE -1.5% (4/7) | -2.5% (6/7).
- vs ESPN (ESPN-graded rows): today +2.59% (0/7); candidate +0.46% (3/7), rho .385 vs ESPN .379; candidate + ESPN -1.04%
  (7/7); ADP 1-60 candidate -0.36% (4/7), + ESPN -1.08% (7/7); playoffs candidate +2.3% (1/7), + ESPN -0.02%.
- Once ESPN is in, Clay adds nothing (candidate + ESPN == shadow + ESPN). Step 4 is not worth porting.
- Porting plan if Jack says go: (a) Clay-side steps 1-3 in jsBasePg / weeklyProjection (kill switches), (b) live mean =
  0.7 x ncMean + 0.3 x that, (c) optional ESPN 50/50 (rmMean form) before the book anchor.
"""
r = io.open("README.md", encoding="utf-8").read()
if "The combined LIVE CANDIDATE (backtest_live_candidate.py)" not in r: io.open("README.md", "a", encoding="utf-8", newline="\n").write(readme)
M = r"C:\Users\billi\.claude\projects\E--MyFantasyFootball-MyFantasyFootball-Files\memory"
mem = """---
name: project_live_candidate
description: 09-17 combined live candidate (DECISION PENDING) - 5 pending fixes stacked = -2.45% vs today's live pre-book number 7/7 (fwd -2.65% 5/5), rho .370->.386; + ESPN 50/50 -3.34% 7/7 rho .389; Clay-only steps 1-3 = -1.6% 7/7; step 4 adds nothing; NOT applied
metadata:
  type: project
---

sim_lab/backtest_live_candidate.py; ZONES panel SIM_LIVECAND_BT. Graded under [[feedback_final_week_excluded]] + [[feedback_projection_focus_top150]].
Ladder vs today's live pre-book number (top 150 weighted): Vegas-adjusted evidence -0.67% -> + tiered Clay prior (ADP<=60:
QB16/RB8/WR12/TE12) -1.27% -> + backup-QB WR dock -1.59% (7/7) -> + usage/WR-one-game/QB-total -1.62% (nothing, skip) ->
70/30 shadow v2.24 + that = -2.45% (7/7), fwd -2.65% (5/5), rho .3697 -> .3857, pairs 63.83 -> 64.39% -> + ESPN 50/50
-3.34% (7/7), rho .3891, pairs 64.88%. Candidate + ESPN == shadow + ESPN (Clay adds nothing once ESPN is in).
Weak cuts: fantasy playoffs -1.0% (4/7) without ESPN, -2.8% (6/7) with; QB/TE 4/7. vs ESPN: candidate +0.46% (3/7) but
better rank; + ESPN -1.04% (7/7).

**Why:** Jack wanted one decision instead of five; the gains stack almost fully.
**How to apply:** live is unchanged until Jack says which tier: (A) Clay-side steps 1-3 only, (B) the 70/30 candidate,
(C) B + ESPN 50/50. Supersedes the separate pending items in [[project_most_accurate_base]], [[project_clay_blend_retune]],
[[project_backup_qb_wr_dock]], [[project_evidence_clean]], [[project_rank_mix]]. Book anchor sits on top either way.
"""
io.open(M + r"\project_live_candidate.md", "w", encoding="utf-8", newline="\n").write(mem)
f = M + r"\MEMORY.md"; t = io.open(f, encoding="utf-8").read()
line = "- [Combined LIVE CANDIDATE (DECISION PENDING)](project_live_candidate.md) — 09-17: 5 pending fixes stacked -2.45% 7/7 (fwd -2.65%), rho .370->.386; + ESPN -3.34% 7/7; Clay-only steps -1.6%; tiers A/B/C await Jack\n"
if "project_live_candidate" not in t: t = t.replace("- [Season-long harness]", line + "- [Season-long harness]", 1)
io.open(f, "w", encoding="utf-8", newline="\n").write(t); print("ok")
