// 2026 NFL regular-season schedule. Released 2026-05-14.
// 272 games × 18 weeks. Each entry is [AWAY, HOME].
//
// Consumers:
//   - BBM Monte-Carlo sim (bye-week stacking)
//   - Playoff SOS (weeks 15-17)
//   - Bringback game-pairing predictor (per memory: project_bringback_playoffs)
//
// Helpers exposed:
//   window.NFL_SCHEDULE_2026[week]            -> array of [away, home] pairings
//   window.getNflScheduleForTeam(team)        -> 18-entry array, 1-indexed; each entry is {wk, opp, home} or {wk, bye:true}
//   window.getNflBye2026(team)                -> bye week 5-14 (derived from schedule)
//   window.getNflGamePairings(week)           -> alias of NFL_SCHEDULE_2026[week]
//   window.getPlayoffOpponents(team, weeks?)  -> [{wk, opp, home}, ...] for weeks 15-17 (default)

window.NFL_SCHEDULE_2026 = {
  1: [
    ['NE','SEA'], ['SF','LAR'], ['CHI','CAR'], ['TB','CIN'],
    ['NO','DET'], ['BUF','HOU'], ['BAL','IND'], ['CLE','JAX'],
    ['ATL','PIT'], ['NYJ','TEN'], ['ARI','LAC'], ['MIA','LV'],
    ['GB','MIN'], ['WAS','PHI'], ['DAL','NYG'], ['DEN','KC'],
  ],
  2: [
    ['DET','BUF'], ['CAR','ATL'], ['NO','BAL'], ['MIN','CHI'],
    ['CIN','HOU'], ['PIT','NE'], ['GB','NYJ'], ['CLE','TB'],
    ['PHI','TEN'], ['JAX','DEN'], ['LV','LAC'], ['SEA','ARI'],
    ['WAS','DAL'], ['MIA','SF'], ['IND','KC'], ['NYG','LAR'],
  ],
  3: [
    ['LAC','BUF'], ['CAR','CLE'], ['NYJ','DET'], ['HOU','IND'],
    ['NE','JAX'], ['KC','MIA'], ['TEN','NYG'], ['CIN','PIT'],
    ['SEA','WAS'], ['ARI','SF'], ['MIN','TB'], ['BAL','DAL'],
    ['LV','NO'], ['LAR','DEN'], ['PHI','CHI'], ['ATL','GB'],
  ],
  4: [
    ['IND','WAS'], ['TEN','BAL'], ['NE','BUF'], ['NYJ','CHI'],
    ['JAX','CIN'], ['DAL','HOU'], ['ARI','NYG'], ['LAR','PHI'],
    ['GB','TB'], ['MIA','MIN'], ['KC','LV'], ['LAC','SEA'],
    ['DEN','SF'], ['DET','CAR'], ['ATL','NO'], ['PIT','CLE'],
  ],
  5: [
    // Byes: CAR, KC
    ['CIN','MIA'], ['LV','NE'], ['MIN','NO'], ['CLE','NYJ'],
    ['IND','PIT'], ['HOU','TEN'], ['NYG','WAS'], ['DEN','LAC'],
    ['DET','ARI'], ['CHI','GB'], ['SF','SEA'], ['BAL','ATL'],
    ['BUF','LAR'], ['TB','DAL'], ['PHI','JAX'],
  ],
  6: [
    // Byes: CIN, DET, MIA, MIN
    ['HOU','JAX'], ['CHI','ATL'], ['BAL','CLE'], ['TEN','IND'],
    ['NYJ','NE'], ['NO','NYG'], ['CAR','PHI'], ['PIT','TB'],
    ['ARI','LAR'], ['LAC','KC'], ['BUF','LV'], ['DAL','GB'],
    ['WAS','SF'], ['SEA','DEN'],
  ],
  7: [
    // Byes: BUF, JAX, LAC, WAS
    ['PIT','NO'], ['SF','ATL'], ['CIN','BAL'], ['TB','CAR'],
    ['NYG','HOU'], ['IND','MIN'], ['MIA','NYJ'], ['CLE','TEN'],
    ['DEN','ARI'], ['GB','DET'], ['LAR','LV'], ['KC','SEA'],
    ['DAL','PHI'], ['NE','CHI'],
  ],
  8: [
    // Byes: HOU, NO, NYG, SF
    ['BAL','BUF'], ['TEN','CIN'], ['ARI','DAL'], ['MIN','DET'],
    ['IND','JAX'], ['LV','NYJ'], ['CLE','PIT'], ['ATL','TB'],
    ['LAC','LAR'], ['KC','DEN'], ['NE','MIA'], ['PHI','WAS'],
    ['CHI','SEA'], ['CAR','GB'],
  ],
  9: [
    // Byes: PIT, TEN
    ['JAX','BAL'], ['CIN','ATL'], ['DAL','IND'], ['NYJ','KC'],
    ['DET','MIA'], ['CLE','NO'], ['NYG','PHI'], ['LAR','WAS'],
    ['HOU','LAC'], ['LV','SF'], ['GB','NE'], ['ARI','SEA'],
    ['TB','CHI'], ['BUF','MIN'], ['DEN','CAR'],
  ],
  10: [
    // Byes: CHI, DEN, PHI, TB
    ['NE','DET'], ['KC','ATL'], ['HOU','CLE'], ['MIN','GB'],
    ['MIA','IND'], ['CAR','NO'], ['BUF','NYJ'], ['JAX','TEN'],
    ['LAR','ARI'], ['SEA','LV'], ['SF','DAL'], ['PIT','CIN'],
    ['LAC','BAL'], ['WAS','NYG'],
  ],
  11: [
    // Byes: ATL, CLE, GB, LAR, NE, SEA
    ['MIA','BUF'], ['BAL','CAR'], ['NO','CHI'], ['TEN','DAL'],
    ['TB','DET'], ['ARI','KC'], ['JAX','NYG'], ['NYJ','LAC'],
    ['LV','DEN'], ['PIT','PHI'], ['MIN','SF'], ['CIN','WAS'],
    ['IND','HOU'],
  ],
  12: [
    ['GB','LAR'], ['CHI','DET'], ['PHI','DAL'], ['KC','BUF'],
    ['DEN','PIT'], ['NO','CIN'], ['LV','CLE'], ['BAL','HOU'],
    ['NYG','IND'], ['NYJ','MIA'], ['ATL','MIN'], ['TEN','JAX'],
    ['WAS','ARI'], ['SEA','SF'], ['NE','LAC'], ['CAR','TB'],
  ],
  13: [
    // Byes: BAL, IND, LV, NYJ
    ['KC','LAR'], ['DET','ATL'], ['JAX','CHI'], ['CIN','CLE'],
    ['GB','NO'], ['SF','NYG'], ['LAC','TB'], ['WAS','TEN'],
    ['PHI','ARI'], ['MIA','DEN'], ['CAR','MIN'], ['BUF','NE'],
    ['HOU','PIT'], ['DAL','SEA'],
  ],
  14: [
    // Byes: ARI, DAL
    ['MIN','NE'], ['TB','BAL'], ['NO','CAR'], ['ATL','CLE'],
    ['TEN','DET'], ['CHI','MIA'], ['DEN','NYJ'], ['IND','PHI'],
    ['HOU','WAS'], ['LAC','LV'], ['KC','CIN'], ['NYG','SEA'],
    ['LAR','SF'], ['BUF','GB'], ['PIT','JAX'],
  ],
  15: [
    ['SF','LAC'], ['SEA','PHI'], ['CHI','BUF'], ['CIN','CAR'],
    ['MIA','GB'], ['JAX','HOU'], ['CLE','NYG'], ['BAL','PIT'],
    ['NO','TB'], ['IND','TEN'], ['ATL','WAS'], ['NYJ','ARI'],
    ['DAL','LAR'], ['DEN','LV'], ['DET','MIN'], ['NE','KC'],
  ],
  16: [
    ['HOU','PHI'], ['GB','CHI'], ['BUF','DEN'], ['LAR','SEA'],
    ['CLE','BAL'], ['LAC','MIA'], ['ARI','NO'], ['NE','NYJ'],
    ['TEN','LV'], ['SF','KC'], ['JAX','DAL'], ['NYG','DET'],
    ['TB','ATL'], ['CIN','IND'], ['WAS','MIN'], ['CAR','PIT'],
  ],
  17: [
    ['NO','ATL'], ['SEA','CAR'], ['IND','CLE'], ['NYG','DAL'],
    ['BUF','MIA'], ['MIN','NYJ'], ['PIT','TEN'], ['LV','ARI'],
    ['DET','CHI'], ['PHI','SF'], ['WAS','JAX'], ['KC','LAC'],
    ['DEN','NE'], ['LAR','TB'], ['BAL','CIN'], ['HOU','GB'],
  ],
  18: [
    ['SF','ARI'], ['PIT','BAL'], ['NYJ','BUF'], ['ATL','CAR'],
    ['CLE','CIN'], ['LAC','DEN'], ['DET','GB'], ['TEN','HOU'],
    ['JAX','IND'], ['LV','KC'], ['SEA','LAR'], ['CHI','MIN'],
    ['MIA','NE'], ['TB','NO'], ['PHI','NYG'], ['DAL','WAS'],
  ],
};

(function() {
  let _byTeam = null;
  let _byes = null;

  function _buildIndexes() {
    if (_byTeam) return;
    const idx = {};
    const byes = {};
    const allTeams = new Set();
    for (let w = 1; w <= 18; w++) {
      const games = window.NFL_SCHEDULE_2026[w] || [];
      games.forEach(function(g) {
        const away = g[0], home = g[1];
        allTeams.add(away); allTeams.add(home);
        if (!idx[away]) idx[away] = [];
        if (!idx[home]) idx[home] = [];
        idx[away][w] = { wk: w, opp: home, home: false };
        idx[home][w] = { wk: w, opp: away, home: true };
      });
    }
    // Bye = the single week (1-18) where team doesn't appear.
    allTeams.forEach(function(t) {
      for (let w = 1; w <= 18; w++) {
        if (!idx[t][w]) {
          idx[t][w] = { wk: w, bye: true };
          byes[t] = w;
          break;
        }
      }
    });
    _byTeam = idx;
    _byes = byes;
  }

  window.getNflScheduleForTeam = function(team) {
    _buildIndexes();
    return _byTeam[String(team).toUpperCase()] || null;
  };

  window.getNflBye2026 = function(team) {
    _buildIndexes();
    return _byes[String(team).toUpperCase()] || null;
  };

  window.getNflGamePairings = function(week) {
    return window.NFL_SCHEDULE_2026[week] || [];
  };

  window.getPlayoffOpponents = function(team, weeks) {
    weeks = weeks || [15, 16, 17];
    const sched = window.getNflScheduleForTeam(team);
    if (!sched) return [];
    return weeks.map(function(w) { return sched[w]; }).filter(function(g) { return g && !g.bye; });
  };

  // Propagate bye into the D array. D's `t` field is the full team name
  // ("Kansas City Chiefs"), so convert via TEAM_ABBR_MAP. Deferred to
  // DOMContentLoaded because index.html appends retired-player entries
  // to D via inline D.push() calls that haven't run yet at script-load.
  function _propagateByes() {
    if (!Array.isArray(window.D) || typeof TEAM_ABBR_MAP === 'undefined') return;
    _buildIndexes();
    window.D.forEach(function(p) {
      if (!p || p.bye) return;
      const abbr = TEAM_ABBR_MAP[p.t] || p.t;
      const bye = _byes[String(abbr).toUpperCase()];
      if (bye) p.bye = bye;
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _propagateByes);
  } else {
    _propagateByes();
  }
})();
