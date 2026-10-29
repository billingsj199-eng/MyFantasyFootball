# Trivia Board Library audit — 2026-10-28

First full run of the admin **🔎 AUDIT LIBRARY** button (trivia page, builder panel).
It builds every Board Library combination once — type (season / career / game)
× stat (10) × era (All-Time, 2020s … 1970s) × positions (QB, RB, WR, TE, all) —
from the current data files and records thin boards, players with no photo and
squares with no team. Re-run only when the data pipelines change (PFR backfills,
headshot/cutout libraries); boards themselves rebuild from live data on every play.

**915 boards · 18 thin (<16 answers) · 258 players without a photo · 1 player without a team label**

## Thin boards (all of them: career TE boards for the 1970s and 1980s)

Only 6 (1970s) / 8 (1980s) tight ends have careers in the legend tables, so every
career-mode TE board for those decades is short. Fix = the 1970–1998 PFR season
totals backfill (own session), which adds every TE of the era.

| Board | Answers |
|---|---|
| career · 1980-1989 · TE (fpts, rcy, rec, rctd, ry, rtd, py, ptd, totalTd) | 8 |
| career · 1970-1979 · TE (same stats) | 6 |

## Players with no team label

- Dalvin Cook (19 boards) — all 7 career rows lack `tm` and no history table covers him.

## Players with no photo (count = boards they appear on)

No ESPN headshot id, no Commons photo (`LEGEND_HEADSHOTS`), no roster image. The
top of this list is where licensed photos or Jack's own scans would pay off most.

Albert Connell 105 · Andrew Glover 72 · Wesley Walls 58 · Mel Gray 58 · Keith Jackson 52 · Dave Krieg 52 · Kordell Stewart 49 · Adrian Murrell 39 · Corey Dillon 38 · Jeff George 36 · Henry Ellard 34 · Larry Centers 33 · Billy Joe Hobert 33 · Abdul-Karim al-Jabbar 33 · Greg Landry 32 · Carl Pickens 31 · Andre Rison 31 · Todd Christensen 28 · Herman Moore 27 · Wade Wilson 27 · Stephen Davis 26 · Az-Zahir Hakim 26 · Mark Bavaro 25 · Clarence Williams 24 · Terry Allen 23 · James Wilder 23 · Bob Tucker 23 · Ronnie Harmon 23 · Marcus Robinson 23 · Byron Chamberlain 23 · Mike Quick 22 · Ernie Conwell 22 · Aaron Shea 22 · Neil Lomax 21 · Danny White 21 · Curt Warner 21 · Ted Kwalick 21 · Terance Mathis 20 · Mark Duper 20 · Charlie Garner 20 · David Sloan 20 · Neal Anderson 19 · David LaFleur 19 · Isaac Curtis 19 · Mike Anderson 19 · Eric Green 17 · Rickey Dudley 17 · Terry Kirby 17 · William Andrews 16 · Rich Caster 16 · Jackie Harris 16 · Freddie Jones 16 · Erik Kramer 16 · Quinn Early 16 · James Stewart 16 · Brett Perriman 15 · Tony Martin 15 · Carlos Carson 15 · Bubby Brister 15 · Riley Odoms 14 · Cameron Cleeland 14 · Christian Fauria 14 · Damon Jones 14 · Charle Young 13 · Dave Moore 13 · Glyn Milburn 13 · Jay Riemersma 13 · Qadry Ismail 13 · Robert Brooks 12 · Walter White 12 · Leroy Hoard 12 · Jack Snow 12 · Drew Bennett 12 · Patrick Jeffers 11 · Bob Christian 11 · Bobby Hebert 11 · Mark Carrier 10 · Tory Woodbury 10 · Steve Stenstrom 10 · Darnay Scott 10 · Stan Humphries 10 · Errict Rhett 10 · Robert Smith 10 · Tim Biakabutuka 10 · Dick Gordon 9 · Roland Williams 9 · Peter Warrick 9 · Greg Clark 9 · Bam Morris 9 · Ken O'Brien 9 · Jerry Smith 8 · Eric Johnson 8 · Pete Mitchell 8 · Eric Martin 8 · Andre Hastings 8 · Mikhael Ricks 8 · Bert Emanuel 8 · Curtis Enis 8 · Brent Jones 7 · Alfred Jenkins 7 · Steve Jordan 7 · Amp Lee 7 · Kimble Anders 7 · Johnnie Morton 7 · Germane Crowell 7 · Itula Mili 7 · Mike Tomczak 7 · Cory Schlesinger 7 · Luther Broughton 7 · Stephen Alexander 7 · Joe Senser 6 · Derrick Ramsey 6 · Otis Armstrong 6 · Courtney Hawkins 6 · Eric Bjornson 6 · Greg Bell 6 · Pete Johnson 6 · Bobby Shaw 6 · Natrone Means 6 · Ray Lucas 6 · Terry Glenn 6 · Derrick Blaylock 6 · David Boston 5 · Steve Watson 5 · Dan Ross 5 · Tony Hill 5 · Wallace Francis 5 · J.T. Smith 5 · Dave Ragone 5 · Dameyune Craig 5 · Bob Chandler 5 · Alvin Reed 5 · Richard Huntley 5 · Chris Doering 5 · Jeff Graham 5 · Brian Blades 5 · Ernest Givins 5 · Jacquez Green 5 · John Spagnola 4 · Henry Childs 4 · Michael Jackson 4 · Warren Wells 4 · Ted Brown 4 · Rickey Young 4 · MacArthur Lane 4 · Milt Morin 4 · James McKnight 4 · Cecil Collins 4 · Chris Fuamatu-Ma'afala 4 · Chris Sanders 4 · Corey Bradford 4 · D'Wayne Bates 4 · Jed Weaver 4 · Jeff Thomason 4 · Joe Ferguson 4 · Ken Dilger 4 · Webster Slaughter 4 · T.J. Duckett 4 · Steve Heiden 4 · Fred Beasley 4 · Olandis Gary 4 · Greg Hill 3 · Dameane Douglas 3 · Marlin Briscoe 3 · Ken Burrough 3 · Moe Williams 3 · Derek Loville 3 · Butch Woolfolk 3 · Peerless Price 3 · Ryan Neufeld 3 · Randal Williams 3 · Lamar Smith 3 · Karim Abdul-Jabbar 3 · Derrick Fenner 3 · Cleveland Gary 3 · David Sims 3 · Travis Henry 3 · Ryan Wetnight 3 · Troy Drayton 3 · Tom Tupa 3 · Eddie Kennison 3 · Ben Troupe 3 · Bryan Fletcher 3 · Mario Bates 3 · Mark Campbell 3 · Derrick Mayes 3 · Ryan Krause 2 · Mack Herron 2 · Mike McMahon 2 · Jim Jensen 2 · Tony Nathan 2 · Paul Hofer 2 · Frank Lewis 2 · John Gilliam 2 · Haywood Jeffires 2 · Earl Cooper 2 · Tony Galbreath 2 · Pat Tilley 2 · Kyle Johnson 2 · Domanick Williams 2 · Tyrone Wheatley 2 · Donny Anderson 2 · Travis Taylor 2 · Barry Foster 2 · Lawrence Dawsey 2 · Don Nottingham 2 · Bill Kenney 2 · Sean Dawkins 2 · Tony McGee 2 · John Taylor 2 · Michael Roan 2 · Napoleon Kaufman 2 · Gary Brown 2 · Andre Hall 2 · Anthony Thomas 2 · Arlen Harris 2 · Artose Pinner 2 · Aveion Cason 2 · Brandon Bennett 2 · Antonio Chatman 2 · Bethel Johnson 2 · Billy McMullen 2 · Casey Fitzsimmons 2 · Scott Slutzker 2 · Rod Gardner 2 · Kevin Dyson 2 · Michael Westbrook 2 · Frank Sanders 2 · Jermaine Lewis 2 · Cory Ross 2 · Jermaine Fazande 2 · Kelly Holcomb 2 · Charlie Brown 1 · Lorenzo White 1 · Cid Edwards 1 · Reuben Gant 1 · Tim Smith 1 · Clark Gaines 1 · Terry Metcalf 1 · John Fuqua 1 · David Hill 1 · Stanley Pritchett 1 · Jeff Moore 1 · Bryan Gilmore 1 · Shaun King 1 · Rob Johnson 1 · Kenny Bynum 1 · Rashaan Shehee 1 · James Allen 1 · Rob Konrad 1 · Ron Rivers 1 · Jon Ritchie 1 · Joseph Morgan 1 · Stoney Case 1 · Rick Mirer 1 · Dwight Stone 1 · Keith Poole 1 · Kent Graham 1

Note: "Abdul-Karim al-Jabbar" and "Karim Abdul-Jabbar" are the same player under two spellings in the data; "Eric Johnson", "Michael Jackson", "Gary Brown", "Charlie Brown" are namesake-prone and may be collisions.
