// Mike Clay 2026 NFL Unit Grades (extracted from NFLDK2026_CS_ClayProjections2026.pdf page 63).
// Updated 5/8/2026. Scale 1-10 per unit (10=best). Total/Off/Def grades are weighted.
// Fields:
//   qb/rb/wr/te/ol  = offensive position unit grades (1-10)
//   di/ed/lb/cb/s   = defensive position unit grades (1-10) [DI=interior, ED=edge, LB, CB, S=safety]
//   totGr/totRk     = team total grade + rank (1=best)
//   offGr/offRk     = offense composite grade + rank
//   defGr/defRk     = defense composite grade + rank (KEY FOR PLAYOFF SOS)
window.CLAY_TEAM_GRADES_2026 = {
  'ARI': {qb:3,rb:7,wr:6,te:8,ol:6,di:5,ed:4,lb:4,cb:4,s:4,totGr:4.6,totRk:31,offGr:2.5,offRk:29,defGr:2.1,defRk:31},
  'ATL': {qb:4,rb:7,wr:6,te:6,ol:6,di:5,ed:4,lb:5,cb:5,s:7,totGr:5.0,totRk:27,offGr:2.6,offRk:23,defGr:2.4,defRk:28},
  'BAL': {qb:8,rb:7,wr:5,te:5,ol:6,di:7,ed:5,lb:5,cb:5,s:9,totGr:6.3,totRk:2,offGr:3.3,offRk:5,defGr:3.0,defRk:4},
  'BUF': {qb:9,rb:7,wr:5,te:6,ol:7,di:5,ed:6,lb:3,cb:5,s:5,totGr:6.1,totRk:6,offGr:3.7,offRk:2,defGr:2.4,defRk:29},
  'CAR': {qb:4,rb:4,wr:5,te:4,ol:6,di:6,ed:5,lb:5,cb:5,s:5,totGr:5.1,totRk:25,offGr:2.5,offRk:28,defGr:2.6,defRk:16},
  'CHI': {qb:6,rb:5,wr:5,te:6,ol:7,di:4,ed:5,lb:7,cb:6,s:5,totGr:5.7,totRk:15,offGr:3.1,offRk:15,defGr:2.6,defRk:14},
  'CIN': {qb:8,rb:6,wr:8,te:4,ol:5,di:6,ed:5,lb:4,cb:5,s:5,totGr:5.9,totRk:12,offGr:3.4,offRk:3,defGr:2.4,defRk:25},
  'CLE': {qb:3,rb:5,wr:5,te:6,ol:5,di:5,ed:7,lb:7,cb:4,s:6,totGr:5.0,totRk:28,offGr:2.2,offRk:31,defGr:2.8,defRk:9},
  'DAL': {qb:7,rb:6,wr:7,te:5,ol:6,di:6,ed:5,lb:4,cb:5,s:6,totGr:5.9,totRk:10,offGr:3.4,offRk:4,defGr:2.6,defRk:18},
  'DEN': {qb:6,rb:5,wr:6,te:4,ol:8,di:6,ed:5,lb:5,cb:6,s:6,totGr:5.9,totRk:8,offGr:3.2,offRk:11,defGr:2.8,defRk:10},
  'DET': {qb:6,rb:7,wr:7,te:7,ol:6,di:6,ed:6,lb:8,cb:5,s:7,totGr:6.1,totRk:4,offGr:3.2,offRk:9,defGr:2.9,defRk:7},
  'GB': {qb:7,rb:7,wr:5,te:6,ol:5,di:5,ed:5,lb:5,cb:5,s:7,totGr:5.7,totRk:13,offGr:3.1,offRk:13,defGr:2.6,defRk:15},
  'HOU': {qb:5,rb:5,wr:6,te:5,ol:5,di:5,ed:6,lb:6,cb:8,s:5,totGr:5.6,totRk:17,offGr:2.6,offRk:24,defGr:3.0,defRk:3},
  'IND': {qb:5,rb:8,wr:5,te:7,ol:6,di:5,ed:5,lb:3,cb:6,s:4,totGr:5.3,totRk:23,offGr:2.8,offRk:19,defGr:2.5,defRk:24},
  'JAX': {qb:6,rb:4,wr:6,te:6,ol:6,di:4,ed:6,lb:5,cb:5,s:4,totGr:5.4,totRk:20,offGr:2.9,offRk:18,defGr:2.5,defRk:22},
  'KC': {qb:7,rb:7,wr:6,te:6,ol:6,di:5,ed:5,lb:7,cb:5,s:5,totGr:5.9,totRk:9,offGr:3.3,offRk:7,defGr:2.6,defRk:12},
  'LAC': {qb:7,rb:6,wr:5,te:5,ol:6,di:5,ed:6,lb:4,cb:4,s:7,totGr:5.7,totRk:14,offGr:3.1,offRk:12,defGr:2.6,defRk:19},
  'LAR': {qb:9,rb:6,wr:7,te:4,ol:7,di:6,ed:6,lb:5,cb:8,s:6,totGr:7.0,totRk:1,offGr:3.8,offRk:1,defGr:3.1,defRk:1},
  'LV': {qb:4,rb:7,wr:4,te:7,ol:6,di:4,ed:6,lb:5,cb:5,s:5,totGr:4.9,totRk:29,offGr:2.5,offRk:27,defGr:2.4,defRk:27},
  'MIA': {qb:4,rb:7,wr:3,te:4,ol:5,di:5,ed:3,lb:6,cb:3,s:2,totGr:4.0,totRk:32,offGr:2.2,offRk:32,defGr:1.9,defRk:32},
  'MIN': {qb:4,rb:4,wr:7,te:6,ol:6,di:6,ed:5,lb:5,cb:5,s:4,totGr:5.3,totRk:22,offGr:2.8,offRk:21,defGr:2.5,defRk:21},
  'NE': {qb:7,rb:5,wr:6,te:6,ol:6,di:6,ed:5,lb:6,cb:7,s:7,totGr:6.1,totRk:5,offGr:3.2,offRk:10,defGr:2.9,defRk:8},
  'NO': {qb:4,rb:6,wr:6,te:5,ol:6,di:5,ed:5,lb:5,cb:5,s:6,totGr:5.1,totRk:26,offGr:2.6,offRk:25,defGr:2.5,defRk:23},
  'NYG': {qb:5,rb:5,wr:6,te:5,ol:6,di:4,ed:8,lb:5,cb:4,s:5,totGr:5.3,totRk:21,offGr:2.8,offRk:20,defGr:2.5,defRk:20},
  'NYJ': {qb:4,rb:6,wr:6,te:5,ol:6,di:6,ed:4,lb:8,cb:5,s:6,totGr:5.4,totRk:19,offGr:2.6,offRk:22,defGr:2.7,defRk:11},
  'PHI': {qb:6,rb:8,wr:6,te:6,ol:7,di:7,ed:6,lb:8,cb:7,s:4,totGr:6.2,totRk:3,offGr:3.2,offRk:8,defGr:3.0,defRk:5},
  'PIT': {qb:4,rb:5,wr:6,te:5,ol:6,di:7,ed:8,lb:4,cb:7,s:5,totGr:5.6,totRk:18,offGr:2.5,offRk:26,defGr:3.1,defRk:2},
  'SEA': {qb:6,rb:5,wr:7,te:5,ol:6,di:7,ed:5,lb:5,cb:7,s:7,totGr:6.0,totRk:7,offGr:3.1,offRk:14,defGr:2.9,defRk:6},
  'SF': {qb:7,rb:7,wr:6,te:6,ol:7,di:5,ed:6,lb:7,cb:5,s:4,totGr:5.9,totRk:11,offGr:3.3,offRk:6,defGr:2.6,defRk:17},
  'TB': {qb:6,rb:5,wr:6,te:5,ol:7,di:6,ed:5,lb:5,cb:5,s:6,totGr:5.6,totRk:16,offGr:3.0,offRk:16,defGr:2.6,defRk:13},
  'TEN': {qb:4,rb:5,wr:6,te:5,ol:5,di:5,ed:5,lb:6,cb:5,s:5,totGr:4.9,totRk:30,offGr:2.5,offRk:30,defGr:2.4,defRk:26},
  'WAS': {qb:7,rb:4,wr:5,te:4,ol:6,di:5,ed:4,lb:5,cb:4,s:4,totGr:5.2,totRk:24,offGr:3.0,offRk:17,defGr:2.2,defRk:30},
};
