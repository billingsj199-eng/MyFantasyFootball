# Trivia & daily-puzzle site survey — what the best products do, and what we should borrow

Written 2026-10-28 for Jack. Research only, no code changes. Every site below was opened in the in-app browser
today (desktop and, where it mattered, a 375px phone viewport); a few facts that the pages did not show
(prices, scoring formulas) come from the sources listed at the end and are marked as such.

Our pages as read today: `myfantasyfootball.co/#trivia` (public Daily Trivia, one board-wide search bar,
grid / Tiers layout, give-up, result modal with emoji grid + permalink, Daily Trivia streak leaderboard) and
`#games` (Daily Elite Pull with era tabs, Elite Pull, Guess Who, Fantasy Game with era/year filters + CHEAT sort,
Leaderboard with Games / Daily tabs).

**Capabilities other sessions are building right now** (mentioned where a format needs them, never assumed):
era-correct player PNG cutouts (Commons, free licences), 1970-1998 season totals and weekly box scores,
and the news-driven daily board picker.

---

## 0. The one-paragraph verdict

Our Daily Trivia already has the three things that made Wordle work: one board for everyone, a spoiler-free
emoji share with a permalink, and a streak. What it lacks is everything the best sites built *around* that core:
a guess budget that creates tension, graduated feedback so a miss still teaches, a stats panel (played / win % /
distribution), a visible board number + "next board in" clock, an archive that does not touch the streak,
social comparison (average score, "beat X% of players", per-answer rarity), and a hub that sends a finished
player straight into the next game. None of these are big builds. The two biggest wins are (1) a proper
**end-of-game modal** (rarity + percentile + stats + "play next") and (2) a **Trivia hub** that shows today's
boards, the countdown, your stats and the archive instead of a lone card on an empty page.

---

## 1. Site-by-site notes (what was actually on the page)

### 1.1 Sporcle — sporcle.com (quiz library, est. 2007, "6.87 billion quizzes played")

**Whole-site structure.** Orange brand bar: logo, site search, Sign In; second row Categories · Games · Newest
Quizzes · Badges · Create · Quiz Lab, then two pill buttons on the right: **Remove Ads** and **Random Quiz** (the
"Sporcle at Random" habit). Home hero: "Unlimited quizzes and puzzle games / Let your brain play every day", then
a horizontal rail of quiz cards (title, category, play length "2m / 15s / 60s", difficulty "Very Easy / Moderate"),
"New Featured Quizzes" (with a one-line hook: *"Spoiler alert: not everyone makes it."*), dated "More Featured
Quizzes", a **Daily Dose** strip (Word Ladder, Quick Pick, Get the Picture, Short Order, Mixed Word, Mini
Crossword, all dated today), a **Sporcle Games** strip (Acrostic, WorldPlay, Steps, Chess Attack, Quizzle, Boxed In),
a Featured Badge, Find a Trivia Night, popular searches, and per-category rows. The footer lists the quiz *types*:
Classic, Clickable, Grid, Map, Multiple Choice, Order Up, Picture Box, Picture Click, Slideshow, Sortable.

**Category page** (Sports › Football): "150,917 quizzes · 268,568,151 plays", category search, Random Football
Quiz, then rails: Latest Picks, Recommended For You, Popular All-Time, Most Popular Today, subcategories.

**Quiz page** ("NFL Teams", 8.9M plays). Above the fold: breadcrumb pills (Sports · Football · Classic),
hero image, title, the question as a sentence ("Can you name the National Football League teams?"), author,
plays, comments (467), kudos (699), rating 4.7 (1,580), one display ad, then **PLAY QUIZ** (big orange pill),
SCORE 0/32 and TIMER 06:00 side by side, and the answer grid below (8 division tables, blank rows).
Playing: a single **"Enter team name:"** input sits directly above the grid with score, pause and timer to its
right and a tiny **Give Up** link under the timer. Matching is **as-you-type with no Enter**: typing `Bills`
filled "Buffalo Bills" instantly and the box kept accepting the next name. Correct cells fill gold.
Give Up fires a **video interstitial ad** before the results.

**Results block** (replaces the Play button, grid stays): **YOU GOT 9%** with a quip ("Don't crash out. Just hit
replay."), **AVG SCORE 87%**, **AVG FRIEND SCORE** (locked: "Go Orange"), SCORE 3/32, TIMER 05:45, then four
buttons: **REPLAY**, **STATS**, **PLAY NEXT** (next quiz in the playlist "Name the Big 4 Sports Teams 1-10") and
**PLAY ANOTHER** (random from the same category, "Picture Spelling: NFL Quarterbacks III"). Missed answers show in
red. Below: playlist, Details (type, 6m, 32 questions, last updated), badge hook ("Play Quiz to Earn This Badge:
Dream Team — Sign up to Earn"), Quiz Scoreboard ("Challenge — Join for Free"), comments ("May contain spoilers").

**Mobile (375px).** Hero image with category chip, title, question, a full-width PLAY QUIZ pill, Score / Timer,
then the grid scrolls **horizontally** (two division columns visible). Workable, not great.

**Monetization.** Display + video ads for free users; **Sporcle Orange** (official page: 7-day trial then
$3.99/mo or $43.99/yr; the app lists $5.99/mo) removes ads, unlocks the games archive + early access, advanced
search, expanded stats, unlimited quiz creation, a members forum, and extra "Florins"/daily-mission rewards.
Badges and daily missions are the retention layer; the daily "Dose" strip is the habit layer.

**What makes it sticky.** Infinite supply + playlists + "Play Another". The results block always offers the next
thing before the player can leave.

### 1.2 JetPunk — jetpunk.com (quiz library, "1.62 billion quizzes taken")

**Whole-site.** Blue header: Menu · Create · Random · search · Create Account / Login. Home is a **dated feed**
("October 28, 2026" then quiz titles with a one-line description, then "October 27, 2026" …) with two daily chips
at the top (**Daily Trivia Challenge**, Word Search) and a right rail of Greatest Hits. Quiz types seen: classic
type-in, **Sudden Death** ("click the NATO members without clicking any that don't"), **whammy** penalty quizzes,
**Blind Ranking** ("10 random numbers — put them in order, if a number cannot be placed the quiz ends"), map
jigsaws, "by clue" quizzes.

**Quiz page.** Title, question sentence, two bullet tips ("Guess the team name, not the city"), author card
(Profile · Quizzes · Subscribe?), Featured star, + Playlist, rate stars, last updated, **"You have not attempted
this quiz yet"**, "More quiz info >>", green **Start Quiz** (shortcut Ctrl+Shift+S), 8 division tables. Right
rail: New and Popular with language tabs, Random / Top Today / **Daily Challenge** buttons, "Your Next Quiz" list,
100 Recent Comments, Similar Quizzes by Tag. Playing: timer 3:53 with pause, **"Enter team name here:"**,
"1 / 32 guessed", **Give Up?**; type-to-match; correct cells go green.

**Results** (the best "learn from your result" block of the survey):
- Scoring box: *"You scored 2/32 = 6%. This beats or equals 1.1% of test takers. The average score is 25. Your
  high score is 2. New high!"* + "more stats" / "shared scores" ("Copied!" link).
- Points for this Quiz: "Your point total remains at 0 of 5", scoring scale, **Next Level 0/5** progress bar
  (level 1 → 2). Levels are the account progression.
- **Retake Quiz** · **Challenge Users**; a **Save Your Stats** signup card inline (email, screen name, password).
- **Answer Stats** table: every answer with **% Correct** across all players and **Your %** (Packers 86 %,
  Bills 73 %, Patriots 90 % … Titans 7x %). This is per-answer rarity shown openly.
- Right rail display ads; no video interstitial.

**What makes it sticky.** Percentile + average + high score on every result, levels, the dated feed ("what is new
today"), and the daily challenge chip at the top of the home page.

### 1.3 Immaculate Grid (Football) — sports-reference.com/immaculate-grid/football (grid #1197 today)

**Page.** Dark navy. Header: "Immaculate Grid powered by Pro Football Reference", **My Stats** (NEW), sport nav
(Baseball · Men's Basketball · Women's Basketball · Football · Hockey · Soccer). One line of meta: **GRID #1197 •
Previous Grids • Today's Results • Rules**. Then the 3×3: top headers MIN logo, CAR logo, "5000+ YDS RECEIVING /
CAREER"; left headers SF, DET, ARI; **GUESSES LEFT 9** and **Give Up** on the right. Footnote: "Players must have
played in a regular season or playoff game for that team to qualify. Tap on a logo or category for help. More
Tips & Tricks". Nothing else above the fold. Ads: one leaderboard under the grid plus a floating video.

**Onboarding.** First visit opens an **About / How to Play** modal: "Select a player for each cell that matches the
criteria for that cell's row and column. You have nine guesses to fill out the grid. Each guess, whether correct
or incorrect, counts as a guess. NEW: After nine guesses, the game will end and you will be given a score (number
correct out of nine) and a rarity score (based on how obscure your answers were). If any of your guesses were
incorrect, you can keep guessing after that but those guesses will not impact your score. **There is a new grid
every day at 6:00am ET.**" plus "Remind me to play tomorrow" and social follow buttons.

**Cell interaction.** Tap a cell → it turns gold and a search sheet drops from the top: suggestions are **name +
career years** ("Calvin Johnson 2007-2015") with a green **Select** button each. A wrong pick turns that row red
in the list, GUESSES LEFT drops to 8, and an inline card appears: "NEW Don't Give Up: Try **Overtime** —
complete your grid no matter how many guesses it takes. Your first nine guesses count toward your score and
stats." Correct picks fill the cell with the player's headshot and a small rarity % in the corner.

**Give up / end.** Cells flip to "Keep Guessing" (overtime), the right rail shows **RARITY 900** and **Show
Summary**. Rarity = sum over the nine cells of the % of players who used that same answer; a miss counts 100, so
900 is the worst possible and lower is better (Wikipedia confirms the score was added to reward obscure answers).
**Summary modal**: "SUMMARY / IMMACULATE GRID 1197", a 3×3 mini-grid, **RARITY SCORE ⓘ 900**, the Overtime card
("Keep Guessing" / "No thanks, maybe later"), then: *"With a free Grid account you can share a link to your Grid so
others can view it with no spoilers and no screenshots needed"* (Sign up for free / Maybe Later), **Copy Results
for Sharing**, **Remind me to play tomorrow**, Sports Reference Hub promo. Share text (known format): `Immaculate
Grid 1197 7/9:` / `Rarity: 312` / three rows of ✅/❌ / link.

**Mobile.** The 3×3 fills the width; logos become the left column, headers the top row; summary modal overlays
the grid. Fully one-column, no horizontal scroll.

**Monetization.** Ads; the free Grid account is the hook (My Stats, spoiler-free share links, Today's Results).

**What makes it sticky.** Rarity: a correct answer is no longer binary, so there is a reason to come back and
play "better" even after 9/9. Also the 6:00am ET reset and the numbered grid give a shared daily reference.

### 1.4 Crossover Grid — crossovergrid.com (the multi-sport, multi-mode clone that out-shipped the original)

**Home.** App-store push first ("Introducing our mobile app"), sport chips (Basketball · Football · Baseball ·
Geography · Soccer · More), then **mode cards**: **Grids** ("Fill a 3×3 grid with the correct criteria"),
**Multiplayer** ("Play others in live unlimited tic-tac-toe grids"), **Trivia** ("Select the leaders in order for the
provided criteria"), **Guess The Player** ("Guess the player based on their career path"), **Random-Generator**,
**Connections**. Footer lists each sport × each mode.

**NFL grid.** A horizontally scrolling emoji chip nav (🏠 Home 🏀 NBA 🏈 NFL 🎬 Movies 🤼 WWE 🧠 Trivia 👾
Multiplayer … CFB, CBB, F1, PGA, Bonus) — more than 30 destinations. **Grid History** button, sponsor line
("Today's grid is brought to you by Crossover Games Mobile App"). Headers today: LAC, ARI, **"1980s All-Rookie
Team"** × DET, DEN, **"1990s All-Pro"** (award/era criteria, not just stat thresholds); a faint player silhouette
is watermarked in the centre cell. Under the grid: **Guesses Remaining 9**, 🔄 **Start over**, ♾️ **Unlimited
Guesses** toggle; **Yesterday Grids · Bonus Grids · Main Grids**; a newsletter box ("Daily newsletter featuring our
rarest answers and exclusive glimpses into special grids!"). First-visit tooltip: "Your goal is to identify a
specific player for each grid cell… LEARN MORE / LET'S GO". Skyscraper ads both sides + banner.

**Guess The Player (NFL).** **SWITCH TO UNLIMITED** at the top; a stats strip **🏆 Win %: 0% · 🎮 Total: 0 · 🔥
Streak: 0 · ⭐ Best: 0**; input + GUESS; **Guesses Left: 3**; clue cards revealed progressively: *College Drafted
From* (logo + "Louisiana"), *Team Drafted By* (Rams logo), *Teams Played For* (Browns, Texans logos), *Career Info*
(Games: 3, Games Started: N/A); "Available players: 17083". The whole page is one narrow column — it is a phone
layout shown on desktop.

**What makes it sticky.** Breadth: one habit (the grid) multiplied across sports and modes, plus Unlimited for
the players who want more than one a day. The Multiplayer "tic-tac-toe grid" is the only live head-to-head
format in this survey built on a grid.

### 1.5 NYT Games — Wordle / Connections (nytimes.com is blocked in the in-app browser; from the NYT Help Center
plus the well-known product)

**Hub.** One card per game (Wordle, Connections, Connections: Sports Edition, Strands, Spelling Bee, The Mini,
Pips, Sudoku, Crossword) with the state baked into the button: **Play / Resume / Completed**, today's date and
the editor's byline. Free: Wordle, Connections, Sports Connections, Strands, Pips, limited Spelling Bee. A
Games subscription unlocks the archive ("over 10,000 past puzzles"), full Spelling Bee and Wordle Bot (price not
verified today; third-party pages quote roughly $6/mo, $50/yr).

**Daily-ritual pattern (Wordle).** Landing is a splash ("Get 6 chances to guess a 5-letter word" · Play · date ·
puzzle number · editor). Onboarding = a **How to Play** modal with the colour rules. End = a **Statistics** modal:
Played, Win %, Current Streak, Max Streak, a **Guess Distribution** bar chart with today's bar highlighted, a
**NEXT WORDLE** countdown, and a **Share** button that copies `Wordle 1,592 4/6` + the ⬛🟨🟩 grid with no letters.
Connections: 16 tiles, 4 groups, **four mistakes** (dots), colour = difficulty (yellow → green → blue → purple);
share is `Connections / Puzzle #868 /` four rows of coloured squares in the order you solved them. NYT Help
Center rules: win rate = solved with fewer than four mistakes; stats track current streak, max streak, **perfect
puzzles** and a **mistake histogram**; the puzzle must be solved before midnight local time to count; **archive
play never affects streaks**.

**What makes it sticky.** The number + the countdown make the puzzle a shared daily event; the distribution chart
turns "I got it in 4" into an identity; the share grid is spoiler-free so it spreads.

### 1.6 Sports "-dle" dailies — Poeltl (NBPA), Weddle (ProDay), Pro Football Network

**Poeltl** (poeltl.nbpa.com, No. 1707). Landing: "Guess the mystery player in 8 guesses!" · Play · date · number.
Game: Help · Stats · About · **Flashback** buttons; input "Guess a player…", **Show Silhouette** (the hint), a live
timer, then an 8-row table Name · Team · Conf · Div · Pos · Ht · Age · #. Rules: green exact; yellow close (Team
= previously played for that team; Position = plays at least one of those positions; Height/Age/Number off by
at most 2). "New players are released every day at midnight (EST)". Stats modal: **Guess Distribution 1-8**,
Games Played, Current Streak, Longest Streak, Win Percentage. Flashback: "Play a previous day — will NOT count
towards your stats or be saved." A **global leaderboard** is advertised as coming (email capture). Ads via a
1,752-partner consent banner.

**Weddle** (weddlegame.com, the NFL one). It sits inside the **ProDay** network: PRO / COLLEGE toggle, nav
WEDDLES · DRAFTLES · MOSSWORD · UNITS · GRIDS · SCRAMBLE · 2 MINUTE DRILL · FILM ROOM (eight formats on one
brand). Toggles **DAILY / UNLIMITED** and **BOARD / STATS**. "WEDDLE CLASSIC — NFL GUESSING GAME", input "Guess a
player", "0 of 8 guesses". After a guess: a row Name | Team | Div | Pos | Ht | Age | # with **↑/↓ arrows** and
yellow for "close" (Age 30 was yellow today). Ads top and bottom.

**Pro Football Network NFL Player Guessing Game.** Lives inside PFN's NFL HQ tool sidebar (Mock Draft Simulator,
Trade Machine, Connections, Word Fumble…). Tabs **Oct. 28 · Archive · Leaderboard**; search box; a **Clues**
button; a tooltip gives a free opening clue ("This current player has five All-Pro selections…"). Eight tries;
six columns Team · Division · Position · Number · Touchdowns · Experience; green exact, yellow = right
conference / within 2, arrows for higher-lower. **Points**: start at 500, −1 per second, −25 per guess, −100 to
reveal the clue (clue unlocks after the 5th guess); a **daily leaderboard** ranks points; free account saves stats
and streaks; archive replay.

**What makes them sticky.** Graduated feedback (every wrong guess narrows the field), a hint with a price, and
Daily + Unlimited side by side.

### 1.7 Framed — framed.wtf (#1692) — progressive-reveal daily

One still from a film; "Search for movie **or submit to skip**"; **6 GUESSES REMAINING**; each wrong guess or skip
unlocks the next frame (frame picker 1-6 above the image). Menu modes: **CLASSIC** (6 frames), **ONE FRAME**,
**TITLESHOT**, **POSTER**, **ARCHIVE** ("Play the days you missed"), **OSCARS** (community results), STATS,
INSTRUCTIONS. Two cross-promo bars under the game ("POSTER CHALLENGE →", "TITLESHOT CHALLENGE →"). Share:
`Framed #1692` + 🎥 🟥 🟥 🟩 ⬛ ⬛ ⬛ + link. Monetization: merch + a ShotDeck referral; no ads seen.

### 1.8 Wikitrivia — wikitrivia.tomjwatson.com — ordering game

Tagline "Put the world's knowledge in chronological order." Two buttons: **Daily** / **Free play**. Game: three
life dots at the top, the card to place (title, type, image: "Sudanese civil war begins · Conflict") above a
timeline that starts with one placed card ("'Guernica' is painted · 1937"); drag it left/right of placed cards.
Correct = green, wrong = red + slides to the right spot and shows the year; cards flip for the Wikipedia blurb.
Streak = cards placed; best streak kept. Data credit line ("All data sourced from Wikidata and Wikipedia"), GitHub
link, no ads. The daily rolled to "OCT 29TH" at 20:00 ET (UK midnight) — a reminder that the reset time must
match the audience.

### 1.9 Live / multiplayer — Kahoot!, Trivia Crack

**Kahoot!** (kahoot.com). Host screen shows the question and four coloured shapes; players join at kahoot.it with
a game PIN and answer on their phone. Timer per question; up to **1,000 points** scaled by speed (official
formula: 1 − (response time ÷ timer) ÷ 2, × max points); **streak bonus** for consecutive correct answers; a
**podium** / leaderboard between questions. Modes: live hosted, student-paced (assigned), team mode (team score =
average of members), single-player practice. Pricing on the home page today: Kahoot!+ from $3/mo, One from $19/mo,
360 from $9/mo; free tier = basic quiz + true/false.

**Trivia Crack** (web is an app-download splash). Classic = spin a wheel of six categories, win a **character /
crown** per category by answering three in a row, turn-based vs a friend or random opponent; **Challenge** (up to
10 players answering the same stream), **Survival** (real-time elimination), **Triviathon** (solo ladder);
**lives** limit how much you can play, **coins** buy power-ups; ads + coin packs + a premium pass. The format
lesson is the 1v1 async turn (you answer, the opponent gets a push notification).

---

## 2. One-page comparison table

Legend: ✅ has it · ◐ partial · ✗ missing · n/a not that kind of product. "MFF" = our Daily Trivia + Games today.

| Feature | Sporcle | JetPunk | Immaculate Grid | Crossover Grid | NYT Wordle/Connections | Poeltl / Weddle / PFN | Framed | Wikitrivia | Kahoot / Trivia Crack | **MFF today** |
|---|---|---|---|---|---|---|---|---|---|---|
| One shared daily, numbered | ◐ (Daily Dose strip) | ◐ (Daily Challenge) | ✅ #1197 | ✅ | ✅ #1,592 / #868 | ✅ No. 1707 | ✅ #1692 | ✅ dated | n/a | ◐ dated, **no number** |
| Visible reset time / countdown | ✗ | ✗ | ✅ "6:00am ET" | ✗ | ✅ NEXT WORDLE timer | ✅ "midnight EST" | ✅ | ✗ | n/a | ✗ |
| How-to-play modal on first visit | ✗ | ✗ | ✅ | ✅ tooltip | ✅ | ✅ | ✅ | ✗ | ✅ | ◐ inline tip |
| Guess budget / lives | ✗ (timer) | ✗ (timer) | ✅ 9 guesses | ✅ 9 | ✅ 6 / 4 mistakes | ✅ 8 / 8 / 8 | ✅ 6 | ✅ 3 lives | ✅ timer | ✗ unlimited |
| Timer | ✅ | ✅ | ✗ | ✗ | ✗ | ◐ Poeltl shows one | ✗ | ✗ | ✅ | ✅ elapsed |
| Graduated feedback per guess | ✗ | ✗ | ◐ (rarity %) | ◐ | ✅ colours | ✅ colours + arrows | ✅ next frame | ✅ year shown | ✗ | ✗ hit / miss |
| Hint system with a cost | ✗ | ✗ | ✗ | ✗ | ✗ | ✅ silhouette / clue −100 | ✅ skip = frame | ✗ | ✗ | ✗ |
| Type-ahead with rich rows | ◐ match-as-you-type | ◐ | ✅ name + years | ✅ | n/a | ✅ | ✅ | n/a | n/a | ✅ pos + team |
| Stats modal (played, win %, streaks, distribution) | ◐ account stats | ✅ + levels | ✅ My Stats | ✅ strip | ✅ | ✅ | ✅ | ◐ best streak | n/a | ✗ streak only |
| Average / percentile / per-answer rarity | ✅ avg + friend avg | ✅ beats X %, avg, per-answer % | ✅ rarity score | ✅ rarity | ✗ | ◐ leaderboard pts | ✗ | ✗ | n/a | ✗ |
| Spoiler-free emoji share | ✗ | ◐ score link | ✅ + account link | ✅ | ✅ | ✅ | ✅ | ✗ | n/a | ✅ 🟩🟥⬜ + permalink |
| Leaderboard | ◐ quiz scoreboard | ◐ shared scores | ◐ Today's Results | ✗ | ✗ | ✅ PFN daily | ✗ | ✗ | ✅ podium | ✅ streak + games |
| Archive / previous days (streak-safe) | ✅ (Orange) | ✅ | ✅ Previous Grids | ✅ Yesterday / History | ✅ (sub) | ✅ Flashback / Archive | ✅ Archive | ✗ | n/a | ✗ (permalink only) |
| Unlimited / Overtime after the daily | ✅ library | ✅ library | ✅ Overtime | ✅ Unlimited toggle | ✗ | ✅ Unlimited | ◐ other modes | ✅ Free play | ✅ | ◐ Elite Pull eras, Guess Who |
| "Play next" at game end | ✅ Replay / Next / Another | ✅ Retake / Next quiz | ◐ Hub promo | ◐ Bonus grids | ✗ | ✗ | ✅ 2 promo bars | ✗ | n/a | ✗ |
| Multiple modes on one brand | ✅ 10 types + 6 games | ✅ | ✗ (one per sport) | ✅ 6 modes | ✅ 9 games | ✅ ProDay 8 | ✅ 4 | ◐ 2 | ✅ | ◐ 4 games + trivia |
| Live / head-to-head | ✗ (trivia nights) | ◐ Challenge Users | ✗ | ✅ Multiplayer | ✗ | ✗ | ✗ | ✗ | ✅ | ✗ |
| Photos | ◐ | ◐ | ✅ headshots | ✅ silhouette | n/a | ✅ silhouette | ✅ (the game) | ✅ | ✗ | ✅ logos + legend headshots |
| Account hook | badges, stats | levels, stats | spoiler-free link, stats | app | streaks sync | leaderboard | stats | ✗ | required | leaderboard post |
| Monetization | ads + Orange $3.99/mo | ads | ads | ads + app + newsletter | subscription (archive, Bee, Bot) | ads (PFN: free) | merch | none | SaaS plans / IAP | Season Pass $24.99 (not tied to trivia) |
| Phone layout | ◐ grid scrolls sideways | ◐ | ✅ one column | ✅ phone-first | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ one column |

---

## 3. The 10 patterns that recur, and which we lack

1. **A numbered, shared daily with a visible clock.** Grid #1197, No. 1707, Framed #1692, Wordle 1,592, "new grid
   every day at 6:00am ET", "NEXT WORDLE 04:12:33". The number makes the result quotable; the clock tells the
   player when to come back. **We have the date only, no number, no countdown.**
2. **A rules modal before the first guess.** Every daily opens with How to Play (budget, colours, reset time) and
   a "remind me tomorrow" hook. **We have an inline tip; it does not state a budget because we have none.**
3. **A guess budget (or lives) instead of a timer.** 9 / 8 / 6 guesses, 4 mistakes, 3 lives. The budget creates
   the tension the share grid then records. Timers are the library-quiz model (Sporcle/JetPunk); every *daily* uses a
   budget. **We count misses but never end the game on them.**
4. **Graduated feedback: a wrong guess still teaches.** Colours + arrows, a new frame, the real year, "right
   conference wrong division". **Ours is binary: hit lands, miss is counted.**
5. **A stats modal with a distribution.** Played, Win %, Current, Max, and a histogram of *how* you won. This is
   the identity layer ("I am a 4-guess Wordler"). **We show a streak number and nothing else.**
6. **Social comparison in the result.** Average score, "beats 1.1 % of test takers", per-answer % correct,
   rarity score. **We have none; our leaderboard ranks streaks only.**
7. **A spoiler-free share with a link back.** We already do this well (🟩🟥⬜ rows that mirror the board,
   score · time, permalink). Immaculate Grid adds an account-backed *view my grid* link; Framed and Wordle add
   the number. **Ours lacks the board number and any "beat me" hook (rarity / percentile).**
8. **Archive and Unlimited that never touch the streak.** Flashback, Previous Grids, Yesterday Grids, Archive,
   Overtime, Unlimited toggle; all explicitly "will not count towards your stats". **We have a permalink
   (`?daily=…`) but no archive UI; Elite Pull eras and Guess Who are our de-facto unlimited modes but live on another
   page.**
9. **"Play next" before the player leaves.** Sporcle: Replay · Stats · Play Next · Play Another. Framed: two
   promo bars. Crossover: Bonus grids. **Our modal offers Share and Close.**
10. **A hub of mode cards with state.** NYT's Play / Resume / Completed buttons; Crossover's six mode cards;
    ProDay's eight formats under one nav. **Our Games page has tabs; our Trivia page is a lone card on an empty
    screen, with only "← Games" to go anywhere.**

Two more worth naming: **hint with a price** (silhouette, clue −100 pts, skip = reveal a frame) and **type-ahead
rows with years** (Immaculate Grid's "Calvin Johnson 2007-2015" removes the namesake problem that our boards hit
with the Steve Smiths and Adrian Petersons).

---

## 4. Prioritized recommendations

Effort: **S** = under a day, **M** = 1-3 days, **L** = a week or more. All front-end unless noted.

### 4.1 Trivia page (the hub)

**R1 — Turn `#trivia` into a hub, not a card (M).** Above the fold on a phone: today's board card with number,
title, era chip, your state (Play / Resume / Completed 14/20), the countdown to the next board (ET), then a row
of secondary cards that already exist elsewhere (Daily Elite Pull, Guess Who, Fantasy Game) with their own state
("Completed", "Best streak 64"), then **Yesterday / Archive** and **Your stats**. NYT's hub and Crossover's mode
cards are the model; the JetPunk dated feed is the alternative if the news-driven picker ships several boards a day.

```
┌──────────────────────────────────────────────────────┐
│ DAILY TRIVIA                              ⏱ next 6h 12m│
│ ┌──────────────────────────────────────────────────┐ │
│ │ BOARD #214 · Tue Oct 28                          │ │
│ │ Career Playoff Rush Yds · Top 20 · RB · 1970-now │ │
│ │ 🔥 streak 7     14/20 today     [ RESUME ]       │ │
│ └──────────────────────────────────────────────────┘ │
│ MORE TODAY                                           │
│ [Elite Pull ✔ 3/6] [Guess Who 🔥12] [Fantasy Game ▶]  │
│ YESTERDAY  #213 · 1990s WR yards  ▶ play (no streak) │
│ YOUR STATS  played 41 · win 78% · best streak 19      │
│ ARCHIVE ▸   LEADERBOARD ▸   HOW TO PLAY ▸            │
└──────────────────────────────────────────────────────┘
```

**R2 — Number the boards and show the reset clock (S).** `BOARD #214` in the card, the title bar and the share
text; a "next board in h:mm" line that counts to 00:00 ET (our boundary). Immaculate Grid states the time in the
rules; NYT shows the timer in the stats modal. Do both.

**R3 — How-to-play modal with the budget and the reset time (S).** Replace the inline tip with a modal on first
visit (and a ? button always): one board a day, same for everyone, type any name, N misses allowed, 00:00 ET,
"remind me tomorrow" (Web Push later). Keep the admin "Surprise Me" note out of the public copy.

**R4 — Stats modal (S-M).** Played · Win % · Current streak · Max streak · a **score distribution** histogram
(buckets 0-4, 5-9, 10-14, 15-19, 20) with today's bucket highlighted, and a **time distribution** if cheap.
Store locally (we already keep daily results) and sync to Firestore for signed-in users so the leaderboard can
rank by win % and average score, not just streak.

**R5 — Archive page (M).** List of past boards (number, date, title, era, your result or "—"), each opening the
existing `?daily=YYYY-MM-DD` permalink in **archive mode**: no streak change, result shown with "(archive)" in the
share text. Poeltl's Flashback copy is the one to copy: "This will NOT count towards your stats." Free for the
last 7 days; **the full archive is a natural Season Pass perk** (NYT and Sporcle both gate the archive).

### 4.2 Board layout

**R6 — A miss budget (S).** Default 5 misses per board (20 squares) shown as five dots under the search bar
(Connections' mistake dots); at zero the board ends and the modal opens. Keep "give up" for the impatient.
Unlimited stays available as **Overtime** after the board ends ("keep guessing, does not count"), which is exactly
Immaculate Grid's framing. Tune the number per board size (3 misses for 9-12 squares, 6-7 for 25-30).

**R7 — Graduated feedback on a miss (M).** When a typed name is a real player but not on the board, say *why* in
one line under the bar, computed from our data: "Barry Sanders · RB · 0 playoff rush yds in this window" or
"Jerry Rice is on the board — wrong hint? (he's the 1,000-yd square)". Even "RB ✓ · era ✗" chips (Weddle's
yellow) turn a dead miss into information.

**R8 — Hint with a price (S).** A **Reveal first letter** / **Reveal team** button per square (or a global
"Silhouette" when the cutout pipeline lands) that costs one miss. Poeltl's Show Silhouette and PFN's −100-point
clue are the models; the price is what keeps the share honest.

**R9 — Type-ahead rows with years and a headshot (S).** We show position + team; add career span ("1991-2004")
and the small headshot so namesakes are disambiguated before the guess lands (Immaculate Grid's "Calvin Johnson
2007-2015"). Match-as-you-type with auto-commit on an exact unique match (Sporcle) is worth testing for speed on
desktop; on phones keep Enter/tap.

**R10 — Cell anatomy on phones (S).** Today a square shows the hint twice (purple label + grey caption) and a
logo. Use the top strip for the hint, the middle for logo → headshot on reveal, and the bottom line for **the
rarity % once solved** (Immaculate Grid puts it in the corner of every solved cell). The Tiers layout already
mirrors the rankings cards; give it the same three-line anatomy so the two layouts share one cell component.

### 4.3 Game-over and share flow

**R11 — Rebuild the result modal in this order (M):**

```
┌──────────────────────────────────────┐
│ BOARD #214 COMPLETE                ✕ │
│ 14/20 · 2:41 · 🔥 7                   │
│ 🟩🟩🟩🟥🟩                           │
│ 🟩⬜🟩🟩🟥   ← mirrors the board      │
│ ⬜🟩🟩🟩🟩                           │
│ 🟩🟩⬜🟩🟩                           │
│ Rarity 412  · beats 63% of players   │
│ avg today 11.2 · your best 18        │
│ ▁▂▅█▃  score distribution (41 played)│
│ [ SHARE RESULT ]  [ VIEW ANSWERS ]   │
│ Up next: Daily Elite Pull ▶ · Yesterday's board ▶ │
│ Next board in 6h 12m                 │
└──────────────────────────────────────┘
```

- **Rarity (M, needs a Cloud Function):** per board, count how many players found each square; a player's rarity
  = sum of the found-% of their solved squares (lower = rarer finds) or, simpler for our format, show the **three
  rarest squares you found** ("only 8 % found Joseph Addai"). This is the single strongest "come back and do
  better" hook in the survey and our data model (one board, fixed answer set) fits it better than Immaculate Grid's.
- **Percentile + average (S once results are pooled):** JetPunk's "beats 63 % of test takers · average 11.2".
- **Distribution + streak:** from R4.
- **Play next:** two links, never zero (Sporcle: four buttons).
- **Countdown:** from R2.

**R12 — Share text (S).** Add the number and the hook, keep the grid: `MFF Daily #214 · 14/20 · 2:41` /
`Career Playoff Rush Yds` / rows / `Rarity 412 · top 37%` / permalink. Keep Web Share on phones. Generate an
**OG image** for the permalink (we already have html2canvas and the og/ folder) so a shared link unfurls as the
board thumbnail with the score, the one thing none of the free sites do well.

**R13 — Results page for the day (S-M).** "Today's Results" (Immaculate Grid): the found-% per square, average
score, the rarest correct answer, and the leaderboard tab for today. Lives behind the modal's "VIEW ANSWERS".

### 4.4 Cross-site plumbing

**R14 — Reset time copy (S).** Our boards flip at 00:00 ET; Wikitrivia flipping at UK midnight while I played at
20:00 ET shows what it looks like when the clock is wrong for the audience. State "new board at midnight ET" in
the rules and the countdown everywhere.

**R15 — Fix the tab bar overlap (S, bug).** At ~800px the Games page's LEADERBOARD tab sits under the header's
search button; it was unreachable by click today and needed a script click. Worth a look on Jack's phone in
landscape too.

**R16 — Season Pass hooks that match the market (S):** full archive, ad-free is already true, rarity history and
the "view my board" link (Immaculate Grid gates spoiler-free links behind a free account; we can gate it behind
sign-in and put the *history* behind the pass). Do not gate the daily itself: no site in the survey does.

---

## 5. New game formats that fit our data (with effort)

| # | Format | Model | What it uses | Daily or unlimited | Effort |
|---|---|---|---|---|---|
| G1 | **MFF Grid** — 3×3, rows = teams / eras, columns = stat thresholds, fantasy finishes ("top-12 RB season"), draft facts, college | Immaculate Grid / Crossover | season totals back to 1970 (incl. the 1970-98 backfill), team stints, draft data, college stats | daily + unlimited | **L** (criteria engine, 9-guess budget, rarity) |
| G2 | **Career Path** — guess the player from a card-by-card reveal: college → draft team → year-by-year team/fpts → award | Crossover Guess The Player | ALL_PLAYERS season rows, college stats, contracts | daily (3 guesses) + unlimited | **M** |
| G3 | **Box Score** — a weekly stat line revealed one field at a time (opp, week, yds, TD…); guess player and/or year | Framed | weekly logs 1999+ (2000-98 box scores when the backfill lands) | daily | **M** |
| G4 | **Timeline** — drag players onto a line by rookie year / MVP season / first 1,000-yd season | Wikitrivia | LEGEND_CAREERS + season totals | daily + free play | **M** |
| G5 | **Fantasy Connections** — 16 players, 4 groups (same college, 2015 Broncos, 300-carry seasons, Pro Bowl kickers…) | NYT Connections | season totals, college, team history | daily (4 mistakes) | **M** (needs a curated-group generator + the news picker's themes) |
| G6 | **Higher / Lower** — which player had more fantasy points in 2019? streak game | classic | season totals | unlimited, best streak on the leaderboard | **S** |
| G7 | **Blind Ranking** — 10 players appear one at a time, slot each by career PPG without seeing the rest | JetPunk Blind Ranking | careers | daily | **S-M** |
| G8 | **Who's That Player (silhouette)** — era-correct cutout darkens to a silhouette, each guess brightens it / reveals a stat | Poeltl silhouette, Framed | **player cutouts (in progress)** + legend headshots | daily | **M** (depends on the cutout pipeline) |
| G9 | **Draft Day** — Fantasy Game with a daily seeded team so everyone drafts the same roster; one shared leaderboard per day | Sporcle "same quiz, compare score" | Fantasy Game as built, seed by date | daily | **S** (seed + leaderboard bucket) |
| G10 | **League Trivia Night** — host screen + phones via PIN, 10 questions from our generator, speed scoring, podium | Kahoot | daily-board generator, Firestore rooms | live, Season Pass / league feature | **L** |
| G11 | **Weddle-style player of the day** with our columns (Pos · Team · Draft yr · Age · 2025 fpts ↑↓) — we have this as Elite Pull | Weddle / PFN | current pool | already live; add arrows + points scoring (−25/guess) | **S** |

Quick wins by value ÷ effort: **G9** (a day, reuses Fantasy Game, instantly comparable), **G6** (a day, endless
content, strong on phones), **G11** polish (arrows + points make Elite Pull shareable), then **G2** and **G3** as
the first new dailies because the data is already on the site. **G1** is the flagship but is the biggest build and
competes head-on with two incumbents; it is stronger as "fantasy-stat criteria nobody else has" (top-12 finishes,
ADP, playoff weeks) than as another team × team grid.

---

## 6. Suggested order of work

1. R2 + R3 + R6 + R12 (board number, rules modal, miss budget, share text) — one sprint, all S.
2. R11 + R4 + R13 (result modal with distribution, stats modal, today's results) — needs a results-pooling
   Cloud Function; rarity and percentile come from the same aggregate.
3. R1 + R5 (hub + archive) — the page becomes a destination.
4. G9, G6, G11 — three cheap formats that fill the hub.
5. R7, R8, R9, R10 (feedback, hints, type-ahead years, cell anatomy).
6. G2 / G3 / G8 as the next dailies when the cutout and box-score pipelines land; G1 and G10 as the big bets.

---

## Sources (beyond the pages read in the browser)

- Sporcle memberships page (Orange pricing and perks): https://www.sporcle.com/memberships/ · Sporcle hidden
  features: https://www.sporcle.com/blog/2018/06/hidden-features-of-sporcle
- Immaculate Grid (rarity history): https://en.wikipedia.org/wiki/Immaculate_Grid · JHU on the grid's appeal:
  https://scienceoflearning.jhu.edu/tof/beyond-perfection-the-allure-of-the-immaculate-grid
- NYT Help Center, Connections stats and streak rules:
  https://thenewyorktimeshelpcenter.helpjuice.com/360011158491-New-York-Times-Games/28525912587924-Connections
  · NYT Games subscription: https://thenewyorktimeshelpcenter.helpjuice.com/360011158491-New-York-Times-Games/360052272251-New-York-Times-Games-Subscription
- Pro Football Network guessing game rules and points: https://www.profootballnetwork.com/nfl-player-guessing-game
- Kahoot points formula: https://support.kahoot.com/hc/articles/115002303908 · how to play:
  https://kahoot.com/how-to-play-kahoot/
- Trivia Crack modes (store listings + 2015 review): https://www.apkmirror.com/apk/etermax/trivia-crack/ ·
  https://tidbits.com/2015/01/09/funbits-trivia-crack-simultaneously-attracts-and-repels/
- Wikitrivia rules: https://en.wikipedia.org/wiki/Wikitrivia · Framed coverage:
  https://www.nme.com/news/wordle-spin-off-framed-asks-cinema-fans-to-guess-films-from-still-images-3189472
- Sportsdle / Huddle comparison (other NFL dailies): https://sportsdle.com/blog/huddle-vs-sportsdle
