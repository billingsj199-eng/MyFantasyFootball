import io, os
os.chdir(r"E:\MyFantasyFootball\sim_lab")
p = "engine.js"; s = io.open(p, encoding="utf-8").read()
assert "vegEvK" not in s
old = "    earlyP: { WR: { mult: 5, games: 1 } },"
assert s.count(old) == 1
i = s.index(old); j = s.index("\n", i) + 1
s = s[:j] + "    vegEvK: 1,   // v2.24 Vegas-adjusted points evidence: each past game / its own Vegas multiplier ^ k (kill: window.SIM_NC_VEGEV = false)\n" + s[j:]
old = "  function shadowUsage(p, wk, sc) {"
assert s.count(old) == 1
new = """  // v2.24 VEGAS-ADJUSTED EVIDENCE (backtest_evidence_clean.py, 2026-09-17; Jack: 'lets build the in season evidence test'). The points a
  // player has scored this season were scored in specific game environments; the forecast multiplies by this week's Vegas multiplier,
  // so the evidence it multiplies should be environment-neutral. Each past game is divided by the Vegas multiplier the model gave THAT
  // game (same elasticities, no new number). Top 150 weighted, final week dropped: -0.30% (6/7 seasons), rank +.0026, QB -0.69% (6/7),
  // RB -0.43% (6/7), weeks 10-to-playoffs -0.45% (6/7); on the 14% of rows it moves by 0.3+ points: -1.36% (6/7). The FPA half of the
  // matchup adds nothing (multiplier too small); dropping / rescaling partial games and teammate-context weights all FAIL.
  // Returns the ratio adjusted / raw points per game (half-PPR), or null.
  function shadowVegasScale(p, wk, schedule) {
    if (typeof window !== 'undefined' && window.SIM_NC_VEGEV === false) return null;
    var k = NC_SHADOW.vegEvK; if (!k) return null;
    var d = jsData(), rec = d.players && d.players[p.norm], bt = schedule && schedule.byTeam && schedule.byTeam[p.tm];
    if (!rec || !rec.wf || !bt) return null;
    var raw = 0, adj = 0, n = 0;
    Object.keys(rec.wf).forEach(function (w) {
      if (+w >= wk) return; var pts = +rec.wf[w]; if (!isFinite(pts)) return;
      var s0 = bt[w] || bt[+w], m = s0 && s0.implied != null ? vegasMult(s0.implied, schedule.avgImplied, p.pos) : 1;
      raw += pts; adj += pts / Math.pow(Math.max(0.6, Math.min(1.6, m)), k); n++;
    });
    if (!n || !(raw > 0)) return null;
    return Math.max(0.75, Math.min(1.35, adj / raw));
  }
"""
s = s.replace(old, new + old)
old = "    if (ncUse && ncUse.lam > 0) ncSrc += '+xfp' + Math.round(ncUse.lam * 100);\n"
assert s.count(old) == 1
s = s.replace(old, old + "    var ncVegEv = (ncV2 && ncSrc !== 'clay-fallback') ? shadowVegasScale(p, wk, schedule) : null;\n    if (ncVegEv != null && Math.abs(ncVegEv - 1) > 1e-9) { ncUse = ncUse || { xfpPg: null, lam: 0 }; ncUse.ptsScale = ncVegEv; ncSrc += '+vegEv'; }\n")
old = "    if (usage && usage.lam > 0 && usage.xfpPg != null) ppg = usage.lam * usage.xfpPg + (1 - usage.lam) * ppg;"
assert s.count(old) == 1
s = s.replace(old, "    if (usage && usage.ptsScale != null) ppg *= usage.ptsScale;   // v2.24 Vegas-adjusted points evidence (shadow only)\n" + old)
io.open(p, "w", encoding="utf-8", newline="\n").write(s)
# feed: per-week half-PPR points
p = "refresh_data.py"; s = io.open(p, encoding="utf-8").read()
old = '        players26[_norm(name)] = {"g": g, "ppg": round(sum(w["fpts"] for w in rows) / g, 2), "pg": pg, "wks": wks_played,'
assert s.count(old) == 1 and '"wf"' not in s
s = s.replace(old, old + '\n                                  "wf": {str(int(w["wk"])): round(float(w["fpts"]), 2) for w in rows if str(w.get("wk", "")).isdigit()},   # per-week points: Vegas-adjusted evidence (shadow v2.24)')
io.open(p, "w", encoding="utf-8", newline="\n").write(s); print("patched")
