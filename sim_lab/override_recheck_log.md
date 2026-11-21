# IN_SEASON_OUT_OVERRIDES recheck log

## 2026-11-15 (Week 10, Saturday recheck run late on Sunday morning)
Backup: overrides.js.bak_20261115. Statuses come from data/injury_updates.js (Sleeper) and practice_2026.json (NFL report, 11-13), plus web reports. `node --check` passed. IN_SEASON_OUT_OVERRIDES_ASOF changed 2026-09-27 -> 2026-11-15.

### Changed
- Jonathon Brooks | [3,8,'10-05',10] -> [3,10,'11-15',12] | IR-DTR window opened 11/11; Doubtful, then Out for W10; expected back before the end of November | https://www.thefantasyfootballers.com/news/647132/jonathon-brooks-team-opens-21-day-practice-window/
- Mike Evans | [6,6,'10-20',9] -> [6,10,'11-15',12] | Achilles tendinitis, missed W7 and W9, DNP all week, Out W10; Shanahan "sooner than later" | https://www.49erswebzone.com/news/amp-204813/ , https://www.nbcsportsbayarea.com/nfl/san-francisco-49ers/mike-evans-likely-miss-week-9/1977142/
- Alec Pierce | [3,6,'10-05',9] -> [3,11,'11-15',15] | heel, still on IR, practice window not opened, no timetable (11/11) | https://www.4for4.com/node/182178 , https://www.rotoballer.com/?p=1990569
- James Conner | [3,5,'10-05',8] -> [3,11,'11-15',14] | foot, still on IR, no window, no timeline (RotoWire 11/5) | https://www.rotowire.com/football/headlines/james-conner-injury-officially-sent-to-injured-reserve-607228
- Christian Kirk | [3,6,'10-05',8] -> [9,12,'11-15',15] | new injury: right meniscus, back on IR 11/7, surgery undecided | https://www.thefantasyfootballers.com/news/646441/christian-kirk-moves-to-injured-reserve/ , https://www.49erswebzone.com/articles/204838-christian-suffers-meniscus-require-surgery/
- Isiah Pacheco | [3,13,'10-05',15] -> [3,13,'11-15',15] | date refreshed only; no November news; 12-week timeline puts him around Dec 7 | https://africa.espn.com/nfl/story/_/id/49943755/source-lions-pacheco-significant-back-surgery
- Dart, Pearsall, Reed, Higgins, Benson, Brazzell II | [3,18,'10-05'] -> [3,18,'11-15'] | date refreshed; Sleeper still shows IR, season over

### Added
- Jeremiyah Love | new [9,12,'11-15',14] | high ankle, IR 11/3, out 4-5 weeks | https://www.azfamily.com/2026/11/03/cardinals-rookie-rb-jeremiyah-love-out-several-weeks-with-ankle-injury-sources-say/
- Brian Robinson Jr. | new [9,12,'11-15'] | hamstring, IR 11/7, at least 4 games | https://www.ajc.com/sports/2026/11/falcons-brian-robinson-jr-injured-reserve/
- Romeo Doubs | new [7,11,'11-15',13] | shoulder, IR 10/19, aiming for W12 after the bye; Vrabel gives no timeline | https://fantasynerds.com/news/story/2026/10/20/romeo-doubs-shoulder-injury-not-expected-to-be-long-term-targeting-post-bye-return-1655941
- RJ Harvey | new [9,12,'11-15',13] | knee, short-term IR, can't return before W13 vs MIA (season dating of the sources is unclear) | https://www.thefantasyfootballers.com/news/645227/rj-harvey-lands-on-injured-reserve/

### Removed (window ended)
- No designation now or practicing, so the daily designation decides: Justin Jefferson, Rico Dowdle, Caleb Douglas, Marquise Brown, Jordan Mason, Jayden Daniels (FP), Caleb Williams, Jordyn Tyson, Dallas Goedert, Jonah Coleman, Dylan Sampson, Eli Stowers, Mason Taylor, Tank Dell (FP)
- Single-week designation handles it: A.J. Brown (Q, LP), Omar Cooper Jr. (Q, FP), David Njoku (IR-DTR, LP, Q for MNF), TreVeyon Henderson (illness, Out)
- Covered by newer news windows in sim_injury_signals: Lamar Jackson (thumb surgery, likely out for the season, 11/2), Josh Jacobs (finger surgery, 2-3 weeks, 11/11)

### Unchanged
- none (all 33 old entries were refreshed, rewritten or removed)

### Could not verify / left to the IR designation
- Tyrone Tracy Jr. (hamstring, IR ~10/27; GM says not season-ending; return week unclear), Michael Pittman Jr. (foot, IR, running again, no timeline), Travis Etienne Jr. (hamstring, IR since early Oct; no news after that), Xavier Legette (IR, practice window opened 11/11), Jacory Croskey-Merritt, Jaylin Noel. No entry was added for any of them.
- SEASON_SCENARIOS 'Josh Jacobs' note still says "Commissioner's Exempt List - no ruling yet", back: 6. This is stale (he is now out after finger surgery). Left for Jack.
