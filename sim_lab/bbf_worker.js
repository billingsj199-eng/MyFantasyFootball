// ============================================================================
// bbf_worker.js — one core's share of the BEST BALL -> OVERALL STANDINGS sim.
//
// The whole-field sim (engine bbFieldRun) costs 1.5-3 s per sim on one core,
// and the sims are independent, so app.js (bbfRunParallel) deals them out to
// several of these workers. Each one:
//   1. loads the SAME data scripts + overrides.js + engine.js the page loaded
//      (their URLs come in the message, cache-bust and all) — the engine only
//      needs `window`, so it is aliased to the worker global, exactly like the
//      headless Node exporters do;
//   2. rebuilds the schedule + player pool and re-applies the in-season injury
//      layer the page armed at boot, so its projections match the page's;
//   3. maps the roster's players back onto its own pool (Sleeper id, else
//      normalised name; stubs = rostered players with no projection);
//   4. runs its sims with its own seed and posts back the engine's running
//      sums, which app.js adds together across workers.
// A script that fails to import (anything page-only) is skipped — the engine
// refusing to load is the only fatal case.
// ============================================================================
'use strict';
self.window = self;

self.onmessage = function (ev) {
  var m = ev.data;
  if (!m || m.cmd !== 'run') return;
  try {
    m.scripts.forEach(function (src) {
      try { importScripts(src); } catch (e) { if (/engine\.js/.test(src)) throw e; }
    });
    var E = self.SimEngine;
    if (!E || !E.bbFieldRun) throw new Error('engine did not load in the worker');
    var schedule = E.buildSchedule(), players = E.buildPlayers(schedule);
    if (m.injury) E.applyInSeasonInjuries(players, m.injury.week, { active: m.injury.active, force: m.injury.force || null });   // force = Jack's in/out list (2026-10-08)
    var plist = m.players.map(function (rp) {
      var p = rp.stub ? null : ((rp.sid != null && players.bySid[rp.sid]) || players.byNorm[rp.norm]);
      return p || { name: rp.name, pos: rp.pos, sid: null, stub: true };
    });
    var run = E.bbFieldRun({
      sims: m.sims, seed: m.seed, scoring: E.PRESETS.half, regTo: m.regTo, schedule: schedule, players: players,
      roster: { players: plist, start: m.start, ix: m.ix }, banked: m.banked, weight: m.weight, mine: m.mine,
      fromWeek: m.fromWeek, unavailable: m.unavailable, cutRanks: m.cutRanks,
      lockMask: m.lockMask, lockVals: m.lockVals, all: m.all, playoff: m.playoff
    });
    while (!run.done()) self.postMessage({ type: 'progress', done: run.step(1) });
    var r = run.result(), T = r.teams.length, S = m.sims, xfer = [];
    var totals = new Float64Array(T * S), ranks = new Float64Array(T * S);
    var squads = new Int32Array(T), banked = new Float64Array(T), curRank = new Float64Array(T);
    r.teams.forEach(function (t, i) {
      totals.set(t.totals, i * S); ranks.set(t.ranks, i * S);
      squads[i] = t.squad; banked[i] = t.banked; curRank[i] = t.curRank;
    });
    Object.keys(r.all).forEach(function (k) { xfer.push(r.all[k].buffer); });
    xfer.push(totals.buffer, ranks.buffer);
    self.postMessage({
      type: 'done', sims: S, A: r.all, totals: totals, ranks: ranks, squads: squads, banked: banked, curRank: curRank,
      cuts: r.cuts.map(function (c) { return { rank: c.rank, cur: c.cur, raw: c.raw }; }),
      playoff: r.playoff, fromWeek: r.fromWeek, regTo: r.regTo, weeksSimmed: r.weeksSimmed,
      nSquads: r.nSquads, fieldWeight: r.fieldWeight, nPlayers: r.nPlayers
    }, xfer);
  } catch (e) {
    self.postMessage({ type: 'error', message: String((e && e.message) || e) });
  }
};
