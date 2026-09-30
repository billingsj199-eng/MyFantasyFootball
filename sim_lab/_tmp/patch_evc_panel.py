import io, os, re
os.chdir(r"E:\MyFantasyFootball\sim_lab")
p = "app.js"; s = io.open(p, encoding="utf-8").read()
anchor = "    var few = Object.keys(B.flags || {}).filter("
assert s.count(anchor) == 1 and "SIM_EVCLEAN_BT" not in s
panel = r"""    var EVC = window.SIM_EVCLEAN_BT;
    if (EVC && EVC.rows) {
      var evCuts = ['ALL weeks 2+ (no final)', 'weeks 2-4', 'weeks 5-9', '10 to playoffs', 'PLAYOFFS', 'ADP 1-60', 'ADP 61-150'];
      var evRow = function (r) { return '<tr><td class="l">' + esc(r.variant) + '</td>' + evCuts.map(function (c) { var x = r[c]; if (!x) return '<td></td>'; return '<td style="color:' + ((x.d <= -0.25 && x.wins >= 5) ? 'var(--acc)' : (x.d >= 0.15 ? '#f85149' : 'inherit')) + '">' + (x.d >= 0 ? '+' : '') + x.d.toFixed(2) + '% <span class="dim">(' + x.wins + '/7) \u03c1 ' + (x.drho >= 0 ? '+' : '') + x.drho.toFixed(4) + '</span></td>'; }).join('') + '</tr>'; };
      html += '<h4 style="margin:14px 0 4px">Cleaning the in-season evidence (backtest_evidence_clean.py, ' + esc(EVC.updated || '') + ') \u2014 Vegas-adjusted evidence SHIPPED shadow-only (v2.24)</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(EVC.summary || '') + '</b> Jack: "lets build the in season evidence test". Three ways the season-to-date average is dirty, each inside the full shadow, final week dropped, top 150 importance-weighted vs the current shadow (seasons better) and change in weekly rank. <b>A. Opponent / environment-adjusted</b>: each past game divided by the matchup multiplier the model gave that game \u2014 PASSES, and all of it is the Vegas half (points scored in a 30-point team total count for less); the points-allowed half does nothing. Strength 1 (the same multiplier the forecast uses, no new number) is shipped; 1.5 is a hair better, 3 is too much. <b>B. Partial games</b> (snap share under half / two thirds of his norm; ' + (EVC.notes ? (100 * EVC.notes.p50 / EVC.notes.games).toFixed(1) : '') + '% of games): dropping or rescaling them makes the projection WORSE \u2014 a player who leaves early or gets eased in keeps scoring below his full-game rate, the partial game is information. <b>C. Teammate context</b> (past games played with a star teammate or the QB in a different state from this week count less): no gain. Live projections unchanged; kill window.SIM_NC_VEGEV = false.' + (EVC.live ? ' <b>Same fix on the LIVE Clay blend (not applied, Jack’s call):</b> ' + EVC.live.filter(function (r) { return r.variant === 'A Vegas-only k=1'; }).map(function (r) { return esc(r.cut) + ' ' + (r.d >= 0 ? '+' : '') + r.d.toFixed(2) + '% (' + r.wins + '/7)'; }).join(' · ') + '.' : '') + '</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Variant</th>' + evCuts.map(function (c) { return '<th>' + esc(c) + '</th>'; }).join('') + '</tr></thead><tbody>' + EVC.rows.map(evRow).join('') + '</tbody></table></div>';
      if (EVC.pos) html += '<p class="dim" style="font-size:11px;margin:6px 0">By position: ' + EVC.pos.map(function (r) { return esc(r.variant.replace('A Vegas-only ', '')) + ' ' + r.pos + ' ' + (r.d >= 0 ? '+' : '') + r.d.toFixed(2) + '% (' + r.wins + '/7)'; }).join(' \u00b7 ') + '.</p>';
    }
"""
s = s.replace(anchor, panel + anchor); io.open(p, "w", encoding="utf-8", newline="\n").write(s)
h = io.open("index.html", encoding="utf-8").read()
tag = re.search(r'<script src="data/vs_espn\.js\?v=[^"]+"></script>', h).group(0)
if "evidence_clean.js" not in h:
    h = h.replace(tag, tag + "\n" + tag.replace("vs_espn.js", "evidence_clean.js")); io.open("index.html", "w", encoding="utf-8", newline="\n").write(h)
readme = """

## Cleaning the in-season evidence (backtest_evidence_clean.py) -> shadow v2.24 Vegas-adjusted evidence - 2026-09-17

Jack: "lets build the in season evidence test". 127,728 past games scanned; final week dropped; top 150 importance-
weighted error vs the current shadow (seasons better of 7), change in weekly rank rho. No fitted numbers.
- A. OPPONENT / ENVIRONMENT-ADJUSTED (each past game / the matchup multiplier the model gave that game ^ k):
  full matchup k=.5 -0.18% (6/7), k=1 -0.30% (6/7). VEGAS half alone k=1 -0.30% (6/7), rho +.0026, ADP 1-60 -0.33% (6/7),
  weeks 5-9 -0.33%, 10-to-playoffs -0.45% (6/7), playoffs -0.37% (5/7); QB -0.69% (6/7), RB -0.43% (6/7), TE -0.20%, WR
  -0.04%. k=1.5 -0.36% (6/7), k=2 -0.36%, k=3 -0.22% (4/7). FPA half alone 0.00% (multiplier too small to matter).
  On the 14% of rows moved 0.3+: -1.36% (6/7); moved DOWN n=1059: actual 16.68, old 17.72, new 17.19.
- B. PARTIAL GAMES (snap share < .50 / .65 of his median in his other games; 2.9% / 5.8% of games): drop +0.19% / +0.21%
  (2/7), rescale +0.06%; on touched rows +2.7% (old 11.16, new 11.93, actual 11.00). The partial game is information.
- C. TEAMMATE CONTEXT (lead star WR/TE ADP<=60 or RB ADP<=100, primary QB; mismatched games weight w): w=.5 -0.02% (3/7),
  w=.25 +0.03%, w=0 +0.10%; rank worse. Side note: with the lead star OUT this week the harness shadow is 1.3 low on
  his position mates (live has the opportunity pool for that; the harness does not).
- SHIPPED shadow-only v2.24: NC_SHADOW.vegEvK = 1, shadowVegasScale() scales the POINTS part of the evidence by
  mean(pts / vegasMult(that week)) / mean(pts), clamp .75-1.35; tag '+vegEv'; kill window.SIM_NC_VEGEV = false.
  Feed: refresh_data.py now writes per-week points wf {week: half-PPR pts} into SIM_2026.players; past weeks' lines
  stay in BETTING_2026.gameTotals. W2: 38 of 144 top-150 shadows move, max 0.09 (one game; grows with games), LIVE 0.
  audit_shadow.js: 0 of 144 unexplained.
- SAME FIX ON THE LIVE CLAY BLEND (not applied - Jack's call): -0.72% vs today's Clay blend (6/7), rho +.0037, ADP 1-60
  -0.89% (7/7), weeks 2-4 -0.29% (6/7), 10-to-playoffs -0.97% (7/7), playoffs -0.76% (5/7); k=1.5 -0.90% (6/7).
"""
r = io.open("README.md", encoding="utf-8").read()
if "Cleaning the in-season evidence (backtest_evidence_clean.py)" not in r: io.open("README.md", "a", encoding="utf-8", newline="\n").write(readme)
M = r"C:\Users\billi\.claude\projects\E--MyFantasyFootball-MyFantasyFootball-Files\memory"
mem = """---
name: project_evidence_clean
description: 09-17 in-season evidence cleaning - Vegas-adjusted points evidence SHIPPED shadow-only v2.24 (-0.30% 6/7, QB -0.7%, RB -0.4%, weeks 10+ -0.45%); dropping partial games FAILS (they are information); teammate-context weights FAIL; FPA-adjusting evidence does nothing
metadata:
  type: project
---

sim_lab/backtest_evidence_clean.py; ZONES panel SIM_EVCLEAN_BT. Graded under [[feedback_final_week_excluded]].
- Each past game divided by the Vegas multiplier the model gave THAT game (k=1, no new number): top 150 weighted -0.30%
  (6/7), rank +.0026, 10-to-playoffs -0.45% (6/7), QB -0.69%, RB -0.43%, WR ~0. k=1.5-2 -0.36%, k=3 too much.
- Partial games (snap share < half his norm): dropping / rescaling is +0.2% WORSE - early exits and eased-in games predict
  lower output next week too.
- Teammate-context weighting of past games: nothing (w .5 -0.02%, w 0 +0.10%).
- Live: engine shadowVegasScale(), NC_SHADOW.vegEvK, tag '+vegEv', kill SIM_NC_VEGEV=false; refresh_data.py writes
  SIM_2026.players[*].wf = per-week half-PPR points. LIVE numbers unchanged.

**Why:** the forecast multiplies by this week's Vegas multiplier, so the evidence it multiplies should be environment-neutral.
**How to apply:** the same fix on the LIVE Clay blend = -0.72% (6/7), ADP 1-60 -0.89% (7/7), weeks 10-to-playoffs -0.97% (7/7) - NOT ported, awaiting Jack's go ('port the Vegas-adjusted evidence to live'). Evidence-side ideas left:
none obvious - partial games and with/without splits are closed. See [[project_inseason_usage]], [[project_noclay_weekly_ladder]].
"""
io.open(M + r"\project_evidence_clean.md", "w", encoding="utf-8", newline="\n").write(mem)
f = M + r"\MEMORY.md"; t = io.open(f, encoding="utf-8").read()
line = "- [In-season evidence cleaning v2.24](project_evidence_clean.md) — 09-17 SHIPPED shadow-only: Vegas-adjusted points evidence -0.30% 6/7 (QB/RB, weeks 10+); dropping partial games + teammate-context weights FAIL\n"
if "project_evidence_clean" not in t: t = t.replace("- [Season-long harness]", line + "- [Season-long harness]", 1)
t = t.replace("TD-luck scale fix v2.22) ~ -2.0%", "TD-luck scale fix v2.22, opp-hist parity v2.23, Vegas-adjusted evidence v2.24) ~ -2.0%")
io.open(f, "w", encoding="utf-8", newline="\n").write(t); print("ok")
