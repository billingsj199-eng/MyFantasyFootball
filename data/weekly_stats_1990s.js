// Per-game stat lines 1990-1998 for every NFL skill player (Pro-Football-Reference box
// scores; built by scripts/pull_pfr_boxscores.py). Keyed by PFR player id; the merge into
// WEEKLY_STATS (index.html _mergeWeeklyStatsLegacy) resolves display names. fpts = half-PPR,
// INT -2, FL -2 (the weekly basis); zero stats omitted; po:1 = playoff game (wk 19-22).
(function(d){var L=window.WEEKLY_STATS_LEGACY=window.WEEKLY_STATS_LEGACY||{};for(var k in d){var r=L[k];if(!r){L[k]=d[k];continue;}for(var y in d[k].seasons)r.seasons[y]=d[k].seasons[y];}})({});
