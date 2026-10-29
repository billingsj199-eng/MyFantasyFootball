# Trivia Board Library — audit report

Built 2026-10-29T03:22:39.409Z · 619 boards · 21 s · 1.43 MB

| verifier | boards |  | PFR cross-check | boards |
|---|---|---|---|---|
| green | 420 |  | green | 301 |
| amber | 25 |  | amber | 12 |
| none (no reference available) | 174 |  | n/a | 306 |

Green = every check that could run agreed with the board (set-equal on the top 10: rank swaps never flag; a name missing or extra does).
Only the amber boards are listed below — everything else passed or had no reference to meet (single-game boards, 1999+ fantasy-point / total-TD season boards, in-season boards).

## How to review

1. Trivia page (admin) → BOARD LIBRARY · ADMIN REVIEW → status filter **Amber**. Each row shows the diff; PREVIEW plays the board.
2. Board right (the check is the one that is off) → tick **reviewed**. Board wrong → leave it unticked (it never enters the daily rotation) and note the data fix.
3. **✓ APPROVE ALL GREEN** marks every green, complete board reviewed in one write — that is the daily pool.
4. Marks go to Firestore `trivia_library/overrides` (deploy `firestore.rules` once). Rebuilding the file never clears them.

Checks, by board kind: season boards 1966-2025 yards/TD stats → PFR top-25 tables (`SEASON_LEADERS`), plus the full-league PFR season totals (`SEASON_TOTALS_7098`) before 1999; career / era / team boards → the site verifier (record-book table + `LEGEND_CAREERS` direct aggregation). "VALUE differs" = a name in both lists whose number is off by more than 1 %.

Known causes seen in this build (decide once, then tick or fix):
- 1999-2000 season boards: the game logs (nflverse) miss games those years, so yards run short of PFR (Kurt Warner 1999: 3,956 vs 4,353). PFR is right; the hint is low.
- 2022 Bengals / Bills: the site counts the cancelled Week 17 game (Burrow 4,527 vs PFR 4,475).
- Career / team boards: the cross-check reads `LEGEND_CAREERS` with D[] positions and no in-season rows, so it can be the wrong side (Mel Gray is a WR; Jarvis Landry's 3,560 Browns yards are right).

## Amber boards (25) — review these

### season (12)

- [ ] **s1999-ry-rb** — 1999 Rushing Yards · RB
  - vs PFR season leaders (SEASON_LEADERS): VALUE differs: Edgerrin James board 1474 vs PFR 1553; Stephen Davis board 1366 vs PFR 1405; Eddie George board 1277 vs PFR 1304; Marshall Faulk board 1267 vs PFR 1381; Duce Staley board 1257 vs PFR 1273; Charlie Garner board 1200 vs PFR 1229; Corey Dillon board 1172 vs PFR 1200
  - board top 10: Edgerrin James 1,474, Curtis Martin 1,453, Emmitt Smith 1,392, Stephen Davis 1,366, Eddie George 1,277, Marshall Faulk 1,267, Duce Staley 1,257, Charlie Garner 1,200, Ricky Watters 1,198, Corey Dillon 1,172
- [ ] **s1999-rcy-wrte** — 1999 Receiving Yards · WR/TE
  - vs PFR season leaders (SEASON_LEADERS): VALUE differs: Marvin Harrison board 1635 vs PFR 1663; Randy Moss board 1392 vs PFR 1413; Cris Carter board 1194 vs PFR 1241
  - board top 10: Jimmy Smith 1,636, Marvin Harrison 1,635, Randy Moss 1,392, Marcus Robinson 1,389, Germane Crowell 1,338, Tim Brown 1,335, Muhsin Muhammad 1,249, Cris Carter 1,194, Michael Westbrook 1,191, Amani Toomer 1,183
- [ ] **s1999-py-qb** — 1999 Passing Yards · QB
  - vs PFR season leaders (SEASON_LEADERS): VALUE differs: Peyton Manning board 4047 vs PFR 4135; Kurt Warner board 3956 vs PFR 4353
  - board top 10: Steve Beuerlein 4,413, Brett Favre 4,068, Peyton Manning 4,047, Brad Johnson 3,988, Drew Bledsoe 3,969, Kurt Warner 3,956, Rich Gannon 3,819, Elvis Grbac 3,360, Jon Kitna 3,328, Doug Flutie 3,145
- [ ] **s2000-ry-rb** — 2000 Rushing Yards · RB
  - vs PFR season leaders (SEASON_LEADERS): VALUE differs: Edgerrin James board 1690 vs PFR 1709; Robert Smith board 1505 vs PFR 1521; Eddie George board 1455 vs PFR 1509; Fred Taylor board 1363 vs PFR 1399; Corey Dillon board 1360 vs PFR 1435; Marshall Faulk board 1341 vs PFR 1359; Jamal Lewis board 1338 vs PFR 1364; Jerome Bettis board 1302 vs PFR 1341; Stephen Davis board 1292 vs PFR 1318
  - board top 10: Edgerrin James 1,690, Robert Smith 1,505, Mike Anderson 1,491, Eddie George 1,455, Fred Taylor 1,363, Corey Dillon 1,360, Marshall Faulk 1,341, Jamal Lewis 1,338, Jerome Bettis 1,302, Stephen Davis 1,292
- [ ] **s2000-rcy-wrte** — 2000 Receiving Yards · WR/TE
  - vs PFR season leaders (SEASON_LEADERS): VALUE differs: Torry Holt board 1596 vs PFR 1635; Rod Smith board 1578 vs PFR 1602; Terrell Owens board 1436 vs PFR 1451; Isaac Bruce board 1434 vs PFR 1471; Eric Moulds board 1275 vs PFR 1326
  - board top 10: Torry Holt 1,596, Rod Smith 1,578, Terrell Owens 1,436, Isaac Bruce 1,434, Randy Moss 1,428, Marvin Harrison 1,408, Joe Horn 1,340, Ed McCaffrey 1,313, Eric Moulds 1,275, Cris Carter 1,274
- [ ] **s2000-py-qb** — 2000 Passing Yards · QB
  - vs PFR season leaders (SEASON_LEADERS): VALUE differs: Elvis Grbac board 3848 vs PFR 4169; Brett Favre board 3764 vs PFR 3812; Vinny Testaverde board 3692 vs PFR 3732; Steve Beuerlein board 3691 vs PFR 3730; Kurt Warner board 3383 vs PFR 3429
  - board top 10: Peyton Manning 4,388, Jeff Garcia 4,238, Daunte Culpepper 3,924, Elvis Grbac 3,848, Brett Favre 3,764, Vinny Testaverde 3,692, Steve Beuerlein 3,691, Mark Brunell 3,640, Kerry Collins 3,576, Kurt Warner 3,383
- [ ] **s2006-rcy-wrte** — 2006 Receiving Yards · WR/TE
  - vs PFR season leaders (SEASON_LEADERS): VALUE differs: Donald Driver board 1261 vs PFR 1295
  - board top 10: Chad Johnson 1,370, Marvin Harrison 1,366, Reggie Wayne 1,310, Roy Williams 1,310, Lee Evans 1,291, Donald Driver 1,261, Anquan Boldin 1,203, Torry Holt 1,188, Terrell Owens 1,180, Steve Smith Sr. 1,166
- [ ] **s2008-rcy-wrte** — 2008 Receiving Yards · WR/TE
  - vs PFR season leaders (SEASON_LEADERS): VALUE differs: Reggie Wayne board 1128 vs PFR 1145
  - board top 10: Andre Johnson 1,575, Larry Fitzgerald 1,434, Steve Smith Sr. 1,417, Roddy White 1,382, Calvin Johnson 1,331, Greg Jennings 1,292, Brandon Marshall 1,265, Antonio Bryant 1,248, Wes Welker 1,165, Reggie Wayne 1,128
- [ ] **s2011-rcy-wrte** — 2011 Receiving Yards · WR/TE
  - vs PFR season leaders (SEASON_LEADERS): VALUE differs: Steve Smith Sr. board 1471 vs PFR 1394
  - board top 10: Calvin Johnson 1,686, Wes Welker 1,569, Victor Cruz 1,536, Steve Smith Sr. 1,471, Larry Fitzgerald 1,411, Rob Gronkowski 1,327, Jimmy Graham 1,310, Roddy White 1,296, Jordy Nelson 1,263, Brandon Marshall 1,214
- [ ] **s2011-py-qb** — 2011 Passing Yards · QB
  - vs PFR season leaders (SEASON_LEADERS): VALUE differs: Drew Brees board 5535 vs PFR 5476; Matthew Stafford board 5100 vs PFR 5038
  - board top 10: Drew Brees 5,535, Tom Brady 5,235, Matthew Stafford 5,100, Eli Manning 4,933, Aaron Rodgers 4,636, Philip Rivers 4,624, Tony Romo 4,184, Matt Ryan 4,177, Ben Roethlisberger 4,077, Cam Newton 4,051
- [ ] **s2022-rcy-wrte** — 2022 Receiving Yards · WR/TE
  - vs PFR season leaders (SEASON_LEADERS): VALUE differs: Stefon Diggs board 1455 vs PFR 1429
  - board top 10: Justin Jefferson 1,809, Tyreek Hill 1,710, Davante Adams 1,516, A.J. Brown 1,496, Stefon Diggs 1,455, CeeDee Lamb 1,359, Jaylen Waddle 1,356, Travis Kelce 1,338, DeVonta Smith 1,196, Terry McLaurin 1,191
- [ ] **s2022-py-qb** — 2022 Passing Yards · QB
  - vs PFR season leaders (SEASON_LEADERS): VALUE differs: Joe Burrow board 4527 vs PFR 4475
  - board top 10: Patrick Mahomes 5,250, Justin Herbert 4,739, Tom Brady 4,694, Kirk Cousins 4,547, Joe Burrow 4,527, Jared Goff 4,438, Josh Allen 4,316, Geno Smith 4,282, Trevor Lawrence 4,113, Jalen Hurts 3,701

### career (5)

- [ ] **c-1970s-rcy-wrte** — 1970s Receiving Yards · WR/TE
  - vs LEGEND_CAREERS direct: MISSING from board: john gilliam · EXTRA on board: mel gray
  - board top 10: Harold Jackson 7,724, Ken Burrough 6,343, Gene Washington 6,145, Harold Carmichael 6,080, Charlie Joiner 5,990, Haven Moses 5,786, Reggie Rucker 5,765, Drew Pearson 5,713, Fred Biletnikoff 5,621, Mel Gray 5,591
- [ ] **c-1990s-fpts-all** — 1990s Fantasy Points · All Positions
  - vs LEGEND_CAREERS direct: MISSING from board: ricky watters · EXTRA on board: warren moon
  - board top 10: Emmitt Smith 2697.6, Barry Sanders 2,342, Steve Young 2,324, Jerry Rice 2312.6, Brett Favre 2230.6, John Elway 2072.3, Cris Carter 1981.1, Thurman Thomas 1954.7, Dan Marino 1939.6, Warren Moon 1855.7
- [ ] **c-2010s-ry-rb** — 2010s Rushing Yards · RB
  - vs LEGEND_CAREERS direct: EXTRA on board: arian foster
  - board top 10: LeSean McCoy 10,434, Frank Gore 9,786, Adrian Peterson 9,732, Marshawn Lynch 7,812, Matt Forte 7,629, DeMarco Murray 7,174, Mark Ingram II 7,029, Chris Johnson 6,417, LeGarrette Blount 6,306, Arian Foster 6,268
- [ ] **c-2020s-fpts-all** — 2020s Fantasy Points · All Positions
  - vs LEGEND_CAREERS direct: MISSING from board: christian mccaffrey · EXTRA on board: dak prescott
  - board top 10: Josh Allen 2571.1, Patrick Mahomes 2171.6, Justin Herbert 1928.3, Lamar Jackson 1912.3, Jalen Hurts 1898.2, Jared Goff 1804.2, Derrick Henry 1743.5, Matthew Stafford 1699.4, Joe Burrow 1683.4, Dak Prescott 1616.5
- [ ] **c-since2010-ry-rb** — Rushing Yards Since 2010 · RB
  - vs LEGEND_CAREERS direct: EXTRA on board: aaron jones
  - board top 10: Derrick Henry 13,597, LeSean McCoy 10,465, Frank Gore 10,439, Adrian Peterson 10,434, Ezekiel Elliott 9,130, Saquon Barkley 8,600, Jonathan Taylor 8,185, Mark Ingram II 8,115, Aaron Jones 8,062, Christian McCaffrey 7,978

### team (8)

- [ ] **t-ari-rcy-wrte** — Cardinals Receiving Yards Leaders Since 1966 · WR/TE
  - vs LEGEND_CAREERS direct: MISSING from board: ernie jones · EXTRA on board: michael floyd
  - board top 10: Larry Fitzgerald 17,524, Roy Green 8,496, Anquan Boldin 7,521, Pat Tilley 7,005, Jackie Smith 6,168, Rob Moore 5,110, J.T. Smith 4,701, Trey McBride 3,947, Michael Floyd 3,739, David Boston 3,655
- [ ] **t-cle-rcy-wrte** — Browns Receiving Yards Leaders Since 1966 · WR/TE
  - vs LEGEND_CAREERS direct: MISSING from board: jarvis landry · EXTRA on board: kevin johnson
  - board top 10: Ozzie Newsome 7,980, Reggie Rucker 4,953, Webster Slaughter 4,834, Paul Warfield 4,260, Dave Logan 4,247, Milt Morin 4,208, David Njoku 4,062, Kevin Johnson 3,833, Braylon Edwards 3,696, Reggie Langhorne 3,597
- [ ] **t-det-rcy-wrte** — Lions Receiving Yards Leaders Since 1966 · WR/TE
  - vs LEGEND_CAREERS direct: EXTRA on board: roy williams
  - board top 10: Calvin Johnson 11,624, Herman Moore 9,174, Amon-Ra St. Brown 6,777, Johnnie Morton 6,431, Brett Perriman 5,264, Charlie Sanders 4,817, Marvin Jones 4,331, Golden Tate 4,224, Roy Williams 3,882, Freddie Scott 3,651
- [ ] **t-hou-rcy-wrte** — Texans All-Time Receiving Yards Leaders · WR/TE
  - vs LEGEND_CAREERS direct: MISSING from board: will fuller · EXTRA on board: corey bradford
  - board top 10: Andre Johnson 13,597, DeAndre Hopkins 10,009, Nico Collins 4,676, Owen Daniels 4,615, Kevin Walter 4,083, Will Fuller V 3,110, Brandin Cooks 2,886, Dalton Schultz 2,266, Jabar Gaffney 2,009, Corey Bradford 1,992
- [ ] **t-lac-ry-rb** — Chargers Rushing Yards Leaders Since 1970 · RB
  - vs LEGEND_CAREERS direct: EXTRA on board: mike garrett
  - board top 10: LaDainian Tomlinson 12,492, Austin Ekeler 4,355, Marion Butts 4,297, Melvin Gordon 4,240, Ryan Mathews 4,058, Natrone Means 3,881, Chuck Muncie 3,309, Don Woods 2,858, Gary Anderson 2,250, Mike Garrett 2,235
- [ ] **t-lar-rcy-wrte** — Rams Receiving Yards Leaders Since 1966 · WR/TE
  - vs LEGEND_CAREERS direct: MISSING from board: tyler higbee · EXTRA on board: ron jessie
  - board top 10: Isaac Bruce 13,933, Torry Holt 12,577, Henry Ellard 9,761, Cooper Kupp 7,776, Jack Snow 5,808, Puka Nacua 4,676, Robert Woods 4,626, Harold Jackson 3,591, Kenny Britt 2,431, Ron Jessie 2,386
- [ ] **t-lv-rcy-wrte** — Raiders Receiving Yards Leaders Since 1970 · WR/TE
  - vs LEGEND_CAREERS direct: MISSING from board: amari cooper · EXTRA on board: hunter renfrow
  - board top 10: Tim Brown 14,532, Cliff Branch 8,685, Todd Christensen 5,872, Fred Biletnikoff 5,621, Jerry Porter 3,939, Darren Waller 3,469, Jerry Rice 3,278, Willie Gault 3,239, Dave Casper 3,024, Hunter Renfrow 2,973
- [ ] **t-no-ry-rb** — Saints All-Time Rushing Yards Leaders · RB
  - vs LEGEND_CAREERS direct: EXTRA on board: tony galbreath
  - board top 10: Alvin Kamara 7,375, Mark Ingram II 6,504, Deuce McAllister 6,096, George Rogers 4,267, Dalton Hilliard 4,164, Pierre Thomas 3,744, Rueben Mayes 3,408, Chuck Muncie 3,393, Ricky Williams 3,098, Tony Galbreath 2,865

## In-season boards (8) — frozen mid-season, rebuild when 2026 ends

s2026-fpts-all, s2026-fpts-qb, s2026-fpts-rb, s2026-fpts-wrte, s2026-ry-rb, s2026-rcy-wrte, s2026-py-qb, s2026-totaltd-all

## Skipped (0) — fewer than 16 items or no board

_none_
