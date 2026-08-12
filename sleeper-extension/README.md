# MFF Sleeper Helper

Chrome extension (MV3) that overlays a helper sidebar on sleeper.com. Two
modes, toggled from the header (v0.12): **DRAFT** (live draft tracking) and
**SEASON** (weekly lineup + waivers for a league). Sister project to
`underdog-extension/`, but with one big architectural difference: **no DOM
scraping**. Sleeper exposes a public read-only API, so the helper polls it
directly:

- `GET api.sleeper.app/v1/draft/<id>` — teams, rounds, type (snake/linear), 3rd-round-reversal, draft order
- `GET api.sleeper.app/v1/draft/<id>/picks` — every pick with `player_id`, `draft_slot`, `picked_by`
- `GET api.sleeper.app/v1/user/<username>` — auto-find your slot from your username
- `GET api.sleeper.app/v1/league/<id>` (+ `/rosters`, `/users`, `/matchups/<wk>`) — season mode
- `GET api.sleeper.app/v1/state/nfl` — current week; `/players/nfl` — injury statuses (cached 12h)

## Season mode (v0.12)

Opening a league page (`sleeper.com/leagues/<id>/…`) flips the sidebar to
SEASON automatically; the header toggle overrides either way (from a draft
room it reuses the draft's league, or lists your leagues by username).

- **League-aware everything** — the league doc's real `scoring_settings`
  (PPR value, pass-TD points, TE premium) re-bake every projection via
  `applyLeagueScoring`, its real `roster_positions` drive the lineup slots,
  and SF/dynasty are auto-detected (overridable in SETTINGS). The detected
  scoring shows in the header line so you can sanity-check it.
- **LINEUP tab** — greedy optimal lineup from your actual roster (dedicated
  slots → narrow flexes → FLEX → SUPER_FLEX). Weekly value (v0.12.1) = the
  site's Wk-N prop boards (UD+PP blend from `betting_lines_2026.json`
  `weeklyProps`, league-scored, receptions estimated from receiving yards,
  anytime-TD odds → expected TDs) blended 80/20 with the Clay-based base
  when a board exists (sportsbooks are always the primary source; base-only
  otherwise). In-season decay (v0.13.1): after every played week the base
  shrinks toward the player's ACTUAL 2026 PPG (Sleeper public stats
  endpoint, cached 6h; prior worth ~6 games — 3 gm → 33% actuals, 10 gm →
  63%); K/DST get the same as an additive correction on their models.
  Preseason nothing has been played, so projections stand. Byes zeroed
  (regular season; v0.17.1 — derived from the site Vegas schedule, since
  `players.json` carries no bye field: a team with 8+ mapped weeks in
  `gameTotals` but no game this week is on bye),
  OUT/IR zeroed, Doubtful ×0.3, Questionable ×0.85, then a ±1.5ppg nudge
  from Jack's redraft rank. K/DST (v0.13.0) are fully MODELED from the
  league's real scoring rules + Vegas: kickers = Clay's per-kicker FG/XP
  volumes (`kFgm/kFga/kXpm/kXpa`) scaled by the week's implied total, with
  each kicker's own FG distance mix (`kD`, ESPN actuals via
  `scripts/pull_kicker_splits.py` — Aubrey takes ~3x the 50+ shots Moody
  does) scored through the league's `fgm_*` buckets + miss penalties;
  DSTs = expected sacks/INTs/fumbles/TDs vs the opponent's implied total,
  quality-scaled by Clay's defense rank (`dRk`), plus the league's
  points-allowed brackets integrated over a distribution centered on the
  opponent implied. Flat-scoring sanity: the K model reproduces Clay's own
  ppg exactly when no distance bonuses exist. Diffs against
  your current starters (matchup,
  falling back to roster) into explicit "▲ Start X over Y (+ppg)" moves;
  swaps under 1.5 ppg apart show as "≈ Toss-up" instead. Rows are verdict-
  colored: green = should start (benched), red = should sit (starting),
  orange = toss-up. Every row gets a Vegas matchup pill (opp + O/U +
  implied total from `gameTotals`, green/red by implied tiers, inverted
  for DST) plus BYE/OUT/DTD/Q badges; bench list, expandable profiles.
- **WAIVERS tab** — free agents = full pool minus every rostered id in the
  league, ranked by **upgrade delta**: the ppg each FA would add to YOUR
  optimal lineup. A top-10 QB behind your rostered stud scores ~0 and reads
  DEPTH (the "you already have Josh Allen" rule); a WR who beats your WR3
  jumps the queue. Ties broken by ROS pPg, Sleeper 24h trending adds (🔥
  badge), and KTC in dynasty leagues. Suggested drop (lowest keep-score:
  marginal lineup contribution + ROS value + dynasty KTC; your only K/DST/
  QB at a required slot is protected) + a Drop watch bottom-3.
- **SETTINGS tab** — username → auto-find your team (or tap it), format
  override, refresh. Team choice persists per league.
- **On-page TEAM decoration** (v0.12.2) — the league team page's own rows
  (`.team-roster-item` → `.cell-player-meta` → `.player-name-row`) get inline
  pills after "POS - TM (bye)": verdict (▲ START / ▼ SIT / ≈ TOSS-UP), the
  colored matchup pill, and this week's projected ppg, plus a green/red/
  orange row outline matching the sidebar verdicts. Names on that page are
  abbreviated ("L Jackson") → matched by first initial + last name + pos
  (+ team), roster first then full pool; DST rows match by team abbr;
  "POS -" free agents and empty slots are skipped. 2s re-scan like the
  draft decorators.
- Data refreshes every 60s while the tab is open. Read-only by design — it
  recommends; you click Sleeper's own buttons to make moves.

Picks carry exact Sleeper player IDs and the picking user's ID, so roster
attribution never guesses (the Underdog helper's biggest failure mode).

## Install

1. `chrome://extensions` → Developer mode → Load unpacked → this folder.
2. Open a Sleeper draft room. The draft ID is read from the URL automatically.
3. Type your Sleeper username → FIND (or tap your slot number) → Start Tracking.

## What it shows

- **Format mode** — Dynasty SF / Dynasty 1QB / Redraft SF / Redraft 1QB.
  Auto-detected from the draft (superflex slot or 2-QB slots → SF;
  `scoring_type` like `dynasty_2qb` or league `settings.type` → dynasty; the
  detected mode gets a ✓ in the dropdown) and always overridable. Mode sets the
  default rank source (KTC SF / KTC 1QB / Jack's rank), the QB need floor
  (2 in SF, 1 in 1QB), and which KTC value the roster panel totals.
- **Pick line** — current pick (rd.pick + overall), your roster count, picks until
  you're on the clock (snake, linear, and 3rd-round-reversal all handled).
- **My Roster** — position counts + every player with their KTC SF value and a
  running total.
- **Available** — best available, ordered by: KTC Superflex, KTC 1QB,
  Jack's rank, FantasyPros, or Sleeper rank (default follows the mode).
  Jack's/FP/Sleeper sources are **mode-aware**: each resolves to the matching
  column for the current format (e.g. Dynasty SF → Jack's live dynastysf board
  from Firestore `rankings/jacks-official`, `fpDsf`, `slDsf`; Redraft 1QB →
  d.js order, `fpR`, `slR`).
  Position filter chips incl. K and DST; `PK` shows KTC rookie-pick values for
  startup drafts that include picks (reference only, not auto-tracked).
  Cyan NEED flag follows the mode's QB floor; K/DST needs only nag in the last
  rounds and only if the draft actually rosters them (`slots_k`/`slots_def`).
- **Stack awareness** — green STACK badge/border when a player pairs QB↔WR/TE
  with your roster (slate TEAM badge for softer same-team overlap); stack
  partners listed in the profile.
- **ADP value tags** — mode-aware ADP (`a`/`sfa`/`da`/`sa`) vs the current pick:
  STEAL (2+ rounds late), Value, Stretch, Reach. ADP + Clay proj PPG shown in
  the card meta.
- **Proj starters PPG** — greedy best lineup from the draft's actual roster
  slots (slots_qb/rb/wr/te/flex/super_flex/…), summed Clay ½PPR, shown under
  the roster panel next to the KTC total.
- **Manual search box** — type 2+ letters, then ✕ marks a player drafted or ＋
  force-adds them to your roster (tagged "(manual)", removable, survives
  refresh). Safety valve for anything the API misses.
- Click a player → profile: both KTC values, Jack's/FP/Sleeper mode ranks,
  Jack's redraft rank, ADP, Clay proj PPG/season, ceiling PPG, VOR + upside
  (SF-aware replacement levels), age, '25 PPG, bye + MARK DRAFTED button.
- Panel is draggable and resizable from the corner and all edges (N/E/S).
- **Tabs** (v0.6): DRAFT (board + search), ROSTER (counts, remaining starters,
  proj-PPG-by-position grid, full player list with KTC totals), SETTINGS
  (username/slot, draft info, data freshness + version).
- **VOR chip** next to the position filters re-sorts the board by format-aware
  VOR (replacement-level value) instead of the rank source.
- **Recent-picks ticker** under the pick line — last 3 picks with the drafter's
  Sleeper display name (league drafts) or slot number.
- **REMAINING starters row** — how many starting slots you still have to fill
  per position, from the league's real lineup settings (SF counts toward QB).
- Header flashes green when you're ON THE CLOCK.
- **✕ close button** (v0.7) hides the panel; a floating yellow MFF chip
  (bottom-right) brings it back without a reload.
- **Playoff SOS** (v0.7) — color-coded W15/16/17 matchup pills in the player
  profile (green=easy, red=hard; hover for SOS rank + implied total). Data:
  `data/playoff_sos_2026.js`, shared with the Underdog extension.
- **Stacks section** (v0.7, ROSTER tab) — each of your QBs with rostered
  stack partners (✓) and the top 3 available same-team WR/TEs by KTC.
- **On-page decoration** (v0.8–0.9.4) — Sleeper's own player list rows get
  three one-line (fixed-height-safe) injections: `#x` (Jack's mode rank) +
  KTC value stacked in the **RK column**; `★ <QB>` stack badge + `$$`/`$`
  (STEAL/VALUE vs mode ADP) at the **top-right of the name cell** (UD
  corner-badge placement); and colored playoff pills **with opponents**
  (`15 @PIT 16 vsCLE 17 @CIN`) under the name. Everything has a hover tooltip
  with the full detail. The whole row is outlined green for STACK / slate for
  same-TEAM (like UD's stacked cards) and gets a cyan left edge for positional
  NEED. Survives Sleeper's list virtualization via a 2s re-scan.
- **Slow-draft notifications** (v0.10) — the background worker polls tracked
  drafts once a minute (chrome.alarms) and fires a desktop notification when
  your pick is ≤1 away or you're on the clock — works with the Sleeper tab
  closed (Chrome itself must be running). Click the notification to open the
  draft room. Toggle per draft in SETTINGS. Notifies once per pick-state.
- **Live Jack's boards** (v0.10) — on load the sidebar fetches the
  `rankings/jacks-official` Firestore doc directly and overrides the baked
  jSf/jDy/jDsf/redraft ranks, so Jack's Rank is always the site's current
  boards without re-running the export (status line shows "boards live
  <date>"). KTC/ADP/projections still come from the export.
- **Roster panel decoration** (v0.9.3) — Sleeper's ROSTER panel rows get
  UD-style inline playoff pills with opponents (`15 @PIT 16 vsCLE 17 @CIN`,
  colored by matchup difficulty) on the team line, plus a green outline + ★
  when two of YOUR rostered players form a QB↔WR/TE stack. Other teams'
  rosters get the schedule pills only.

## SIMS tab (v0.14.0 picks → v0.15.0 full sims) — Monte Carlo season sims

Every league gets a SIMS tab in season mode (v0.29.6; the pick sections
below are dynasty/keeper only — redraft shows standings/odds/week-by-week
without them). It runs the Sim Lab
season-sim engine (`engine_sim.js`, a verbatim copy synced by the export
script) over the league — 1,500 sims, fixed seed, real matchups (or a
round-robin synth preseason), mid-season records carried, IR/PUP exclusions,
lineups picked from the league's real slots and scoring — and keeps each
team's FULL finish distribution plus per-week results.

- **Projected standings** — every team's simmed record, PF, playoff odds,
  title odds, and modal finish. Tap any team for the drill-down.
- **Week by week** (selected team, defaults to yours) — each remaining
  regular-season week: opponent, win probability (color-coded), projected
  points, opponent's projected points; header line has playoff/bye/finals/
  title odds.
- **My picks** — your actual 2027/2028 inventory from Sleeper's
  `traded_picks` record (dealt picks gone, acquired picks shown "via" the
  original team and valued by THAT team's projected finish), each with a ±%
  vs the generic Mid anchor. Pick values integrate the owner-of-record
  team's finish distribution over the KTC Early/Mid/Late curve (1QB or SF
  per the league): draft order = inverse standings, 2028s regressed 50%
  toward league average — a rebuilder's 1st prices above a contender's 1st.
- **League pick board** — every team worst-projected-first with their own
  '27 1st / '27 2nd / '28 1st values; picks no longer with the original team
  carry a → marker.
- Sim runs lazily on first tab open (~1-2s), cached per league+day+records in
  extension storage; RE-RUN clears the cache. If Vegas lines or the sim data
  are unavailable it falls back to generic KTC tier pick values (tab hidden
  entirely if `engine_sim.js`/`data/sim_pack.js` are missing).

## Trade decoration (v0.16.0) — on-page trade verdicts

Sleeper's Trade Offer modal (`.trade-center-wrapper`) gets decorated in place:

- Every asset gets a pill: players show KTC + Jack's rank (league-format
  aware); picks show their KTC value — team-aware from the season sim for
  2027+, generic tiers for 2026, extrapolated with a `~` past 2028 (15%/yr
  discount off 2028 — KTC has no anchors there yet).
- Picks are valued by the ACTUAL pick, not the holder (v0.16.1): the modal
  only says "From X", so each pick is resolved against the traded_picks-
  adjusted inventory — a pick X previously acquired is valued by the TRUE
  origin team's finish (pill shows "via <team>"); if X holds several picks of
  that year/round the candidates' values are averaged (pill shows "(avg of
  N)", tooltip lists them); no inventory yet → assume X's own. Inventory
  tracks 2027-2029 for this.
- KTC's REAL value adjustment (v0.17.0): a verbatim port of
  keeptradecut.com's trade-calculator algorithm (processV / reverseAdjust /
  adjustPackage, pulled from their site bundle and validated to the exact
  number against their calculator) runs between the two packages — the side
  consolidating into the best asset gets a "Value Adjustment +X" chip on its
  panel per KTC's display rules, and the verdict compares ADJUSTED totals
  with KTC's 5% fairness band.
- Each manager gets an "MFF: <name> WINS/LOSES/FAIR" net line: adjusted net
  KTC, the optimal-lineup PPG change for their actual roster (colored by its
  OWN sign — a value-winning side can show red PPG), and Δ season wins +
  Δ title odds from same-seed before/after 1,500-sim season runs (also
  independently colored). Verdict wash: winner green, loser red, fair both
  orange; 3+-way trades get neutral net lines.
- Runs on the shared 2s decorate tick; opening a trade lazily kicks the
  season sim (pick values + Δwins upgrade in place when it lands).

## TEAM tab (v0.15.0) — roster values by source

Season mode, all league types. Your full roster grouped by position with a
source switcher — KTC value / Jack's rank / FantasyPros / Sleeper rank — each
resolved to the league's detected format (dynasty/redraft × SF/1QB), exactly
like the draft-mode source dropdown. KTC mode adds per-position subtotals and
a team total; rows carry team, age, and injury flags. Source choice persists
per league.

## Data pipeline

`python export_sleeper_extension_data.py` (project root) regenerates
`data/players.json` from:

- `data/d.js` — Jack's redraft rankings (order = rank), teams, ages, and the
  mode-flavored FP/Sleeper ranks (`fpSf/fpDy/fpDsf`, `slSf/slDy/slDsf`)
- Firestore `rankings/jacks-official` (public read, fetched live) — Jack's
  superflex / dynasty / dynastysf boards → `jSf` / `jDy` / `jDsf` ranks
- `data/_bundle_lookups.js` — `KTC_SF` / `KTC_1QB` dynasty values
- `sleeper_nfl.json` — Sleeper player-ID mapping
  (refresh occasionally: `curl -o sleeper_nfl.json https://api.sleeper.app/v1/players/nfl`)

Run it after every rankings/KTC refresh, then reload the extension.

The same run also rebuilds the PICKS-tab sim bundle: `data/sim_pack.js`
(verbatim concat of `data/mike_clay_projections.js` +
`data/player_weekly_sigma.js` + `data/clay_team_grades_2026.js`) and syncs
`engine_sim.js` + `data/sim_overrides.js` from `../sim_lab/` (edit the
sim_lab originals, never the copies).

## Testing without a live draft

`mock.html` — serve the folder over HTTP (file:// won't fetch players.json) and
open it. Simulates a 12-team SF dynasty startup with 3RR, one pick every 4s,
plus a "Force next pick" button. The sidebar runs the exact same code path via
the `window.__MFF_MOCK` hook. The mock also serves season-mode league L1
(PPR · 5pt paTD, deliberately wrong starters, one Q + one OUT player, trending
adds) — hit the SEASON toggle, SETTINGS → username `jack` → FIND to exercise
LINEUP and WAIVERS. The mock also loads the sim bundle + a full-season Vegas
fixture + two traded picks, so the PICKS tab runs the real sim end-to-end in
the harness. Remember the site sw.js gotcha: if the harness serves the site's
index instead of mock.html, unregister the service worker + clear caches.

## Known limitations (v0.2)

- Auction drafts: picks tracked, but no on-the-clock countdown.
- Rookie-pick assets are reference-only.
- No un-mark for manually marked players (reload the page to reset manual marks
  for the draft via SLOT → re-track).
- `sleeper_nfl.json` teams can go stale between refreshes; d.js team wins.

## Console hooks

`window.__mffSleeper` → `{ state, render, pollOnce, initForDraft, initForLeague,
wkVal, kickerProjFor, dstProjFor, ensurePickSim, pkTeamPickValue, pkExpFinish,
simAvailable }`
