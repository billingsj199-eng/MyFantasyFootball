// college_stats_manual_patch.js — Phase 2 hand-curated FCS/D2 data
// Source: Wikipedia per-season narratives (see phase2_report.txt for confidence).
// Uses _csReplace() — OVERWRITES existing entries for these 7 players because
// the pre-patch CFBD data was FBS-crossover junk (e.g. Kupp's 2013 showed 2 GP).
// Safe to load after college_stats.js + phase1 patch.
(function(){
  if (typeof COLLEGE_STATS === 'undefined') return;
  function _csReplace(name, entries){
    // Full replace — Wikipedia-sourced season totals are ground truth,
    // existing CFBD data was only FBS crossover games.
    COLLEGE_STATS[name] = entries.slice();
  }

  // high confidence — Wikipedia per-season table (D2 Western State Colorado)
  _csReplace("Austin Ekeler", [{yr:2013,tm:"Western State Colorado",conf:"RMAC",gp:9,ra:182,ry:1049,rtd:7,rec:27,rcy:260,rctd:1,rypc:5.8},{yr:2014,tm:"Western State Colorado",conf:"RMAC",gp:11,ra:298,ry:1676,rtd:14,rec:38,rcy:417,rctd:2,rypc:5.6},{yr:2015,tm:"Western State Colorado",conf:"RMAC",gp:10,ra:227,ry:1637,rtd:19,rec:32,rcy:402,rctd:2,rypc:7.2},{yr:2016,tm:"Western State Colorado",conf:"RMAC",gp:10,ra:232,ry:1495,rtd:15,rec:18,rcy:236,rctd:3,rypc:6.4}]);

  // high confidence — Wikipedia per-season table
  _csReplace("Carson Wentz", [{yr:2012,tm:"North Dakota State",conf:"Missouri Valley",gp:6,pa:16,pc:12,py:144,ptd:2,int:0,ra:5,ry:22,rtd:1},{yr:2013,tm:"North Dakota State",conf:"Missouri Valley",gp:6,pa:30,pc:22,py:209,ptd:1,int:0,ra:10,ry:70,rtd:0},{yr:2014,tm:"North Dakota State",conf:"Missouri Valley",gp:16,pa:358,pc:228,py:3111,ptd:25,int:10,ra:138,ry:642,rtd:6,pct:0.64},{yr:2015,tm:"North Dakota State",conf:"Missouri Valley",gp:8,pa:208,pc:130,py:1651,ptd:17,int:4,ra:63,ry:294,rtd:6,pct:0.63}]);

  // high confidence — Wikipedia prose (explicit per-season receptions/yds/TDs)
  _csReplace("Cooper Kupp", [{yr:2013,tm:"Eastern Washington",conf:"Big Sky",gp:15,rec:93,rcy:1691,rctd:21,rypr:18.2},{yr:2014,tm:"Eastern Washington",conf:"Big Sky",gp:13,rec:104,rcy:1431,rctd:16,rypr:13.8},{yr:2015,tm:"Eastern Washington",conf:"Big Sky",gp:11,rec:114,rcy:1642,rctd:19,rypr:14.4},{yr:2016,tm:"Eastern Washington",conf:"Big Sky",gp:14,rec:117,rcy:1700,rctd:17,rypr:14.5}]);

  // medium confidence — Wikipedia 2016-17 explicit; 2014-15 estimated from career totals
  _csReplace("Dallas Goedert", [{yr:2014,tm:"South Dakota State",conf:"Missouri Valley",gp:11,rec:7,rcy:70,rctd:0},{yr:2015,tm:"South Dakota State",conf:"Missouri Valley",gp:11,rec:27,rcy:514,rctd:3},{yr:2016,tm:"South Dakota State",conf:"Missouri Valley",gp:14,rec:92,rcy:1293,rctd:11,rypr:14.1},{yr:2017,tm:"South Dakota State",conf:"Missouri Valley",gp:14,rec:72,rcy:1111,rctd:7,rypr:15.4}]);

  // high confidence — Wikipedia per-season table
  _csReplace("Jimmy Garoppolo", [{yr:2010,tm:"Eastern Illinois",conf:"Ohio Valley",gp:8,pa:211,pc:124,py:1639,ptd:14,int:13,ra:41,ry:-138,rtd:1,pct:0.59},{yr:2011,tm:"Eastern Illinois",conf:"Ohio Valley",gp:11,pa:349,pc:217,py:2644,ptd:20,int:14,ra:66,ry:-61,rtd:1,pct:0.62},{yr:2012,tm:"Eastern Illinois",conf:"Ohio Valley",gp:12,pa:540,pc:331,py:3823,ptd:31,int:15,ra:83,ry:0,rtd:2,pct:0.61},{yr:2013,tm:"Eastern Illinois",conf:"Ohio Valley",gp:14,pa:568,pc:375,py:5050,ptd:53,int:9,ra:70,ry:62,rtd:4,pct:0.66}]);

  // medium confidence — Wikipedia narrative; att/cmp not explicit
  _csReplace("Joe Flacco", [{yr:2004,tm:"Pittsburgh",conf:"Big East",gp:3,pa:4,pc:1,py:11,ptd:0,int:0},{yr:2006,tm:"Delaware",conf:"Colonial Athletic Association",gp:11,py:2783,ptd:18,int:10},{yr:2007,tm:"Delaware",conf:"Colonial Athletic Association",gp:15,py:4263,ptd:23,int:5}]);

  // high confidence — Wikipedia per-season prose. Fixes CFBD wrong-identity bug (was matching Nebraska backup, not Louisville Heisman winner).
  _csReplace("Lamar Jackson", [{yr:2015,tm:"Louisville",conf:"ACC",gp:12,pa:247,pc:135,py:1840,ptd:12,int:8,pct:0.55,ra:162,ry:960,rtd:11},{yr:2016,tm:"Louisville",conf:"ACC",gp:13,pa:409,pc:230,py:3543,ptd:30,int:9,pct:0.56,ra:260,ry:1571,rtd:21},{yr:2017,tm:"Louisville",conf:"ACC",gp:13,pa:430,pc:254,py:3660,ptd:27,int:10,pct:0.59,ra:232,ry:1601,rtd:18}]);

  // high confidence — Wikipedia per-season table
  _csReplace("Trey Lance", [{yr:2019,tm:"North Dakota State",conf:"Missouri Valley",gp:16,pa:287,pc:192,py:2786,ptd:28,int:0,ra:169,ry:1100,rtd:14,pct:0.67},{yr:2020,tm:"North Dakota State",conf:"Missouri Valley",gp:1,pa:30,pc:15,py:149,ptd:2,int:1,ra:15,ry:143,rtd:2,pct:0.5}]);

  console.log('[college_stats_manual_patch] Replaced stats for 8 FCS/D2 players.');
})();
