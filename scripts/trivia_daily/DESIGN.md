# Daily Trivia — news-driven boards (design note, 2026-10-28)

Jack: "make daily trivia be news related or current related — around the draft do
draft related trivias; if a major trade happens or a record is broken lean into that."

## What runs

Every evening at **19:30 ET** the Task Scheduler job **"MFF Trivia Daily"** runs
`scripts\trivia_daily_task.ps1` → `node scripts\trivia_daily\run.js lock` from the
main checkout. It decides TOMORROW's angle, builds the board, and writes
`trivia_daily/{tomorrow}` so the public Daily Trivia serves it at midnight ET.
Jack sees it the same evening in the admin Archive row as `YYYY-MM-DD · SCHEDULED · AUTO`
with the reason it was picked, and can replace it with LOCK AS DAILY (a hand lock is
never overwritten by the job). If nothing qualifies, nothing is written and the
template cycle serves the day exactly as before.

```
plan  → read signals, print candidates           node scripts\trivia_daily\run.js plan
build → plan + build headlessly, save JSON        node scripts\trivia_daily\run.js build
lock  → plan + build + write Firestore            node scripts\trivia_daily\run.js lock
options: --date YYYY-MM-DD   --theme <kind|key>   --offline (plan only, disk data)
```

## 1. Theme picker (`calendar.js`, `signals.js`, `themes.js`)

Rule-based, deterministic, no AI call (the pick and the phrasing come from fixed
templates, so there is nothing to bill and nothing to hallucinate). Signals:

| signal | source | used for |
|---|---|---|
| NFL calendar (ET) | computed: Labor Day → kickoff, week numbers, trade deadline = Tue after Wk 9, Super Bowl = 2nd Sun of Feb, Thanksgiving | hard + soft windows |
| news feed | `data/camp_news_2026.json` (daily 6pm ET news scan), fetched from the live site first, disk fallback; last 3 feed dates | trades, signings, records, season-ending injuries |
| latest slate | `data/weekly_stats_active.js` current season, latest week with a full slate | monster single games (Mon–Wed only) |
| fantasy trade market | `data/real_trades_redraft.json` (Sleeper crawl, every 3 h) | most-traded player since MNF |
| players | `data/d.js` | position, team, "star" test |
| lock history | Firestore `trivia_daily` (public read via REST) | skip hand-locked date, no repeats within 10 days |

"Star" is a general rule, not a list: overall rank ≤ 60, or QB/TE rank ≤ 12, RB/WR ≤ 24.

Priority (highest score wins; a key locked in the last 10 days is skipped):

| score | theme | board |
|---|---|---|
| 100 | NFL Draft window Apr 18 – May 2 | first-round picks of a class (rotates 2025 → 2018 by day) |
| 100 | Super Bowl week · kickoff week · Thanksgiving / Black Friday | career playoff leaders · best Week 1 games · DET / DAL all-time |
| 90 | trade of a star (news tag `transaction` + trade words) | that team's all-time leaders at his position (yards) |
| 88 | signing / extension of a star | same |
| 85 | record / milestone headline | that stat's all-time career board, or single-game board if the headline says single-game |
| 80 | monster game on the latest slate (175 rush/rec yds, 400 pass yds, 3 rush/rec TD, 5 pass TD, 40 fpts) | best single games ever at that stat |
| 70 | season-ending injury to a star | his team's all-time leaders at his position |
| 60 | playoffs · fantasy playoffs (Wk 15–17) · combine week · trade-deadline week | postseason boards · best Week N games · a draft class · most-traded player's team |
| 50 | most-traded player in fantasy leagues this week (≥ 15 trades, in-season) | his team's all-time leaders at his position |
| — | nothing qualifies | **no lock** — template cycle runs |

Each theme carries fallback variants (team board → team all-positions fantasy points
→ all-NFL board for the stat) so a thin franchise history still yields 16+ cells.

**Two rules added the same evening (Jack):**
- **The player in the news must be on the board.** Every news theme (trade, signing,
  record, big game, season-ending injury, most-traded) carries `mustInclude`; a stat
  board that misses him is widened to top 25, then 30 (the site's count options), then
  the next variant is tried. Trades and injuries are strict (a plain trade falls back to
  his OLD team's all-time list, where he actually is); big games and records retry once
  without him rather than lose the theme. A calendar board has no such rule. Single-game
  boards also reject any player holding more than a quarter of the cells.
- **Boards don't have to be stats.** `trades.js` pulls nflverse's free trade + draft
  history (2002+ trades, 1980+ picks, all positions, cached 24 h outside the repo) and
  builds list boards: **"Traded for a First-Round Pick"** (a real player one way, a
  round-1 pick back the other way, newest first; Waddle, McDuffie, Gardner, Parsons,
  Rodgers, D.J. Moore, A.J. Brown, Hill, Watson, Stafford, Ramsey, Mack…) and **"Top-10
  Picks Who Got Traded"** (drafted ≤ #10, later dealt). A trade headline that mentions a
  first-round pick leads with the first list; a traded top-10 pick leads with the second;
  tonight's trade is injected on top when nflverse (which lags by days) lacks it. Trade-
  deadline week rotates the two lists with no news needed. nflverse encodes a later-used
  pick as the player it became, so an asset counts as a pick when the player's draft
  came after the trade. Answers match on the full name in the one search bar, so
  non-skill players (linemen, defenders) work; the autocomplete only suggests
  fantasy-position names.

## 2. Board builder (`build_board.js`)

The board is built by **the site's own generator**, not a re-implementation: Playwright
serves the checkout from disk under a private origin, opens `#trivia`, loads the
retired + weekly bundles, sets the structured filters exactly as `_triviaApplyTemplate`
does, runs `_triviaGenerate()`, and reads back `_triviaData` plus the verifier banner
`_renderBoard` drew. The saved items have the same shape `_triviaLockAsDaily` writes, so
the locked board is byte-for-byte what LOCK AS DAILY would have saved.

Acceptance per variant:
- ≥ 16 items (4×4 is the smallest layout);
- all-NFL career / playoff boards: the site verifier banner must be **green**
  (reference table + LEGEND_CAREERS cross-check);
- team boards: the site cross-check ignores the team filter, so the builder runs its own
  LEGEND_CAREERS + D[].career aggregation with per-season team credit and requires the
  top-10 **set** to match (same set-equal rule as the site verifier);
- single-game / week / draft boards: no reference exists on the site either — same
  standard as the template pool's own single-game and draft entries.

Browser: Playwright from `tests/node_modules`; the bundled Chromium is invisible to Task
Scheduler, so it falls back to installed Edge / Chrome (same as `sim_lab/export_notes.js`).
A full build takes ~10 s.

## 3. Firestore write (`lock.js` + Cloud Function `lockTriviaDaily`)

`trivia_daily` writes are `isJack()`-only, so the job cannot use the client SDK. Chosen
path: a **Cloud Function** (`E:\MyFantasyFootball\functions\index.js`, Gen 2, us-central1)
holds the Admin SDK; the PC authenticates with the **export feed key** it already uses for
the Jack's-board exporters (`E:\MyFantasyFootball\secrets\export_feed_key.txt`, sent as
`x-export-key`, matched against the `EXPORT_FEED_KEY` secret). Why not a service-account
JSON on disk: it is a standing Google credential with full project access, needs Jack to
generate it, and gives the job far more power than "write one trivia doc". The function:
- validates the doc (date today-or-later in ET, 16–40 items, string caps, `source:'auto'`);
- **409** if the date already holds a non-auto (hand) lock; replaces an earlier auto lock;
- writes `{date,title,desc,items,itemCount,colorway,layout,lockedBy:'auto-trivia-daily',
  source:'auto', auto:{key,kind,score,reason,hook,filters,verify,topN,tried}}`.

Site side: the daily panel already shows `desc` under the title; the admin archive row
now shows `· AUTO` + the reason. Hand locks keep `lockedBy: <uid>` and no `source`.

## 4. Fallback

No qualifying theme → the job logs "nothing qualifies" and exits 0; nothing is written;
`_triviaPlayDaily` finds no snapshot and the deterministic template cycle plays as today.
Job failure → `mff_alert.ps1` toast `trivia-daily-failed`; log at
`E:\MyFantasyFootball\_alerts\trivia_daily_log.txt`.

## Operating notes

- Re-run for a date: `node scripts\trivia_daily\run.js lock --date 2026-11-02`. Force a
  theme: `--theme trade` or a variant key such as `--theme team|DAL|rcy|WRTE`.
- Themes are keyed in `auto.key`; the repeat guard reads them from Firestore.
- Calendar constants to verify each August: trade deadline (Tue after Wk 9), draft window.
- Year filter on the site only reaches 2025 → "this season" boards are not built; big games
  use all-time single-game boards instead.
- AI phrasing (worker `late-wind-6322`, admin-credentialed) is deliberately not used; the
  hook headline from the news feed is the desc. Easy to add later in `themes.js` if wanted.

## College boards + college images (`college.js`, built the same evening)

Jack: "we can also add college football since we have plenty of stats … team or awards
based … I would like college images."

| board | source | example |
|---|---|---|
| `cfb\|season\|YEAR\|stat` | COLLEGE_STATS season rows | 2025 College Rushing Yards Leaders (Ahmad Hardy 1,649…) |
| `cfb\|school\|School\|stat` | season rows at that school, summed | Alabama Rushing Yards Leaders · Since 2007 (Najee, Henry, Yeldon…) |
| `cfb\|conf\|Conf\|YEAR\|stat` | season rows by conference | 2024 SEC Receiving Yards Leaders |
| `cfb\|game\|stat` | COLLEGE_WEEKLY game logs | Best Single-Game College Rushing Yards (Perine 427, Penny 418…) |
| `cfb\|career\|stat` | career sums, first season ≥ 2007 | College Career Receiving Yards (Corey Davis 5,285…) |
| `cfb\|class\|YEAR\|stat` | COMBINE_DATA draft year × careers | 2026 NFL Draft Class · College Receiving Yards |
| `cfb\|heisman` | Wikipedia "List of Heisman Trophy winners" (free, cached 7 d) | Heisman Trophy Winners · 2006–2025 (year → name) |

The college pool is the college years of NFL / draft-pool players (dense from 2007), so
"all-time" means that pool; titles say "Since 2007". Boards are built in Node (no site
generator), ≥ 16 rows, single-game boards reject one player holding > ¼ of the cells.

**When**: college Saturdays Sep 1 – Dec 7 (score 55, rotating season / school / conference /
game / career boards over 20 schools, 5 conferences, yards stats), Heisman week (the second
Saturday of December, score 100), bowl season Dec 15 – Jan 20 (60, Heisman mixed in), and
draft week alternates the pick lists with "the class by college numbers".

**Images**: every cell carries `logo` (ESPN NCAA logo by school, keyless teams API — the
site's own college logo map covers only 63 of the 273 schools) and, for names the NFL id
maps never see, `headshot`: a Wikimedia Commons photo when the Heisman table has one, else
ESPN's keyless player search — a college-football hit counts only when ESPN's subtitle names
one of the player's schools (same name at another school = different person; "Mike Williams"
stays blank), an NFL hit only when it is the single football result. NFL names are left
blank on purpose: the site resolves them at reveal. app.js: a cell uses `it.logo` before the
team map and the reveal uses `item.headshot` before the name lookup; the Cloud Function
whitelists `logo` (redeploy needed). Cache: `trivia_daily_cache\college_headshots_v2.json`,
`espn_cfb_teams.json`, `heisman.json`.
