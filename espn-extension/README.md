# MFF ESPN Helper (Chrome extension)

Three personalities on fantasy.espn.com: **league import** (to
myfantasyfootball.co), **draft helper** (live draft sidebar), and — since
v0.9.0 — **SEASON mode** (weekly lineup + waivers, ported from the Sleeper
helper).

## Season mode (v0.9.0)

Opening any league page (`fantasy.espn.com/football/*?leagueId=…` outside the
draft room) flips the sidebar to SEASON automatically; the header
DRAFT/SEASON toggle overrides either way (from a draft room it reuses the
room's league). One authenticated fetch
(`?view=mTeam&view=mRoster&view=mSettings`, polled every 60s) carries
everything: rosters, each team's CURRENT lineup (`lineupSlotId`; 20=BN
21=IR), and per-player `injuryStatus`.

- **League-aware everything** — the real `scoringSettings` re-bake every
  projection (rec value + pass-TD points via statIds 53/4; the full K
  distance buckets and DST stat values + points-allowed brackets map into
  the same sleeper-style dict the K/DST models read), and the real
  `lineupSlotCounts` drive the optimizer slots (RB/WR and WR/TE flexes keep
  their narrow eligibility). Superflex = OP slot or 2×QB; keeper leagues
  count as dynasty for the mode default.
- **LINEUP tab** — greedy optimal lineup, weekly value = the site's Wk-N
  prop boards (UD+PP blend from `betting_lines_2026.json` `weeklyProps`)
  blended 80/20 with the Clay base; in-season the base decays toward actual
  2026 PPG (Sleeper public stats endpoint — `players.json` sids bridge the
  ids; prior worth ~6 games). K/DST fully modeled from the league's real
  rules + Vegas (same models as the Sleeper helper). Byes are derived from
  the Vegas schedule (a team with 8+ mapped weeks and no game this week);
  OUT zeroed, Doubtful ×0.3, Questionable ×0.85, ±1.5ppg Jack's-rank nudge.
  Start/sit moves with deltas, toss-ups under 1.5 ppg, verdict-colored rows,
  Vegas matchup pills, bench list, expandable profiles.
- **WAIVERS tab** — free agents = full export pool minus every rostered
  player in the league, ranked by **upgrade delta** (the ppg each FA adds to
  YOUR optimal lineup — a top-10 QB behind your stud reads DEPTH). Sleeper
  24h trending adds (🔥), KTC tiebreak in keeper leagues, suggested drop +
  drop watch.
- **TEAM tab** — roster values by source (KTC / Jack's / FP / Sleeper),
  format-aware, with KTC subtotals + team total.
- **SETTINGS tab** — your team is auto-detected from the SWID cookie vs
  `teams[].owners` (URL `teamId` and saved prefs win); tap to override.
  Format override + refresh. Prefs persist per league.
- **Injuries** — mRoster `injuryStatus` for rostered players, the Sleeper
  `/players/nfl` dump (12h cache) for free agents.
- **SIMS tab (v0.10.0)** — the Sleeper helper's Monte Carlo season sims on
  ESPN data: `engine_sim.js` + `data/sim_pack.js` (synced from sim_lab by the
  export script) run 1,500 seeded seasons over the league — real `mMatchup`
  pairings (round-robin synth fallback), mid-season records carried, IR/OUT
  exclusions, lineups from the real slots + scoring (yardage/TD statIds
  3/24/42/25/43 feed the engine's scoring). Projected standings (record, PF,
  playoff/title odds, modal finish) + per-week win odds drill-down, cached
  per league+day+records. No traded-pick valuations (ESPN leagues don't
  trade future picks).
- **On-page decoration (v0.10.0)** — every rostered player name ESPN renders
  as a link gets inline pills: verdict (▲ START / ▼ SIT / ≈ TOSS-UP, your
  roster only), the colored Vegas matchup pill, and this week's projected
  ppg. Matches on anchor TEXT (raw ESPN name or the D/ST rename), not
  selectors, so it survives ESPN markup churn; 2s re-scan,
  signature-cached.
- Not ported (yet): trade verdicts.
- **Test without a league:** serve this folder over HTTP and open
  `mock_season.html` — a 10-team mock league (you are team 2, lineup
  deliberately wrong, one OUT + one Q starter) exercising LINEUP / WAIVERS /
  TEAM end-to-end.

# MFF ESPN League Import

Imports ESPN fantasy football leagues into [myfantasyfootball.co](https://myfantasyfootball.co).
Why an extension: ESPN's league API sends **no CORS headers** (the static MFF
site can never call it directly) and private leagues need the `espn_s2`/`SWID`
cookies. Running inside the user's logged-in ESPN session solves both — no
cookie pasting, no DOM scraping.

## How it works

1. **`espn.js`** (content script on `fantasy.espn.com/football/*`): when the URL
   has a `leagueId`, shows a floating **Export league to MFF** button. Click →
   fetches `lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{yr}/segments/0/leagues/{id}?view=mTeam&view=mRoster&view=mSettings`
   with `credentials: include`, normalizes, saves to `chrome.storage.local`
   under `mff_espn_leagues` (keyed by leagueId — multiple leagues accumulate).
   Reads the (non-HttpOnly) `SWID` cookie to flag which team is the user's.
2. **`normalize.js`**: pure ESPN-JSON → MFF payload mapping. Handles positions,
   NFL team abbrevs, old+new team/owner name formats, PPR detection (stat 53),
   lineup slots → Sleeper-style `rosterPositions` (superflex = OP slot 7 or
   2×QB; IR excluded), keeper detection, W/L/PF records, and DST renaming
   ("Ravens D/ST" → "Baltimore Ravens D/ST" so the site's `D[]` lookup matches).
3. **`mff-bridge.js`** (content script on `myfantasyfootball.co`): pushes the
   stored leagues to the page via the `mff-espn-league-from-extension`
   CustomEvent — on load and on every storage change.

## Site-side (wired since app.js v2026-07-23f)

The My Teams module listens for the event, lists synced leagues in the **ESPN
LEAGUE** import card, and `window._mtImportEspn(leagueId)` feeds the payload
through the existing Sleeper pipeline (`_mtDetectFormat` → `_mtScoreRoster` →
`_mtBestLineup` → `_mtRenderLeague`) and saves to Firestore `savedLeagues`
under the key `espn_<leagueId>`. Player names resolve via `_mtLookupD` with
Jr./III suffix fallbacks; unmatched names stay on the roster and score 0.

Payload contract (one entry per league in `e.detail.leagues`):

```
{ platform:'espn', leagueId, season, name, scoring:'ppr'|'half'|'std',
  pprValue, rosterPositions:[...Sleeper-style...], sf, keeper, teamCount,
  drafted, syncedAt,
  teams:[{teamId, name, owner, isMine, wins, losses, fpts,
          roster:[{espnId, name, pos, team}]}] }
```

## Draft-feed probe (Phase 1 of the draft helper, v0.3.0)

Instrumentation to decide how a future ESPN draft helper should read live
picks. Two paths, both recorded into one rolling log:

- **`draft-probe.js`** (isolated, all fantasy.espn.com pages): in a REAL
  league draft (URL has a leagueId) it polls `?view=mDraftDetail` every 5s
  and logs whether `picksMade` climbs during the draft. Mock-lobby drafts
  have no API-readable league, so there it only collects sniffer events.
- **`ws-sniffer.js`** (MAIN world, document_start): passively wraps
  WebSocket + fetch in the draft room and samples frames that look like
  picks (`pick|draft|onclock|select|roster`), capped to avoid flooding.

An amber **MFF PROBE** chip (bottom-left) shows it's recording — **click it
to copy the full log JSON to the clipboard**. The log also persists to
chrome.storage `mff_espn_draft_probe` (latest page-load wins) and streams to
the console as `[MFF/espn-draft-probe]`. To capture a draft already in
progress: reload the extension, then refresh the draft-room tab (the room
reconnects; document_start hooks must load before the socket opens).

## Draft-feed probe RESULTS (captured live 2026-07-23, 12-team mock)

Both paths answered in one probed mock draft:

- **Path 1 (`?view=mDraftDetail` polling) is DEAD during drafts** — while
  `inProgress: true`, every pick slot sits at `playerId: -1`; `picksMade`
  stayed 0 the whole draft. BUT the picks array's *structure* (overall pick
  number → round/teamId) is fully populated mid-draft, so it's still the
  source of truth for draft ORDER / snake math. Bonus: mock drafts DO create
  an API-addressable league (contrary to the earlier assumption) — it shows
  up in the user's fan API league list.
- **Path 2 (WebSocket) is the live feed — and it's trivial.** The room speaks
  a line-based text protocol:

  ```
  SELECTING <teamId> <clockMs>                      # on the clock (30000 = 30s)
  SELECTED  <teamId> <playerId> <n> <memberSWID>    # manual pick
  SELECTED  <teamId> <playerId> <n>                 # autopick (no SWID)
  AUTODRAFT <teamId> <true|false>                   # autodraft toggle
  ```

  `<n>` (single small int: 3/5/7/10 observed) is undecoded — likely the
  roster slot the pick filled; decode in Phase 2 by cross-referencing player
  positions. Socket auth comes from
  `GET lm-api-reads…/leagues/{id}/teams/{teamId}/draftSecurity` and the WSS
  URL carries the token in its query string.

**Phase-2 design consequence:** the draft helper should stay PASSIVE — keep
the MAIN-world WebSocket wrap (never open our own socket, no auth needed),
parse `SELECTING`/`SELECTED` lines for live state, and use one `mDraftDetail`
fetch at start for the full pick order + `mTeam` for team names + a player-id
→ name map (site data espnIds + ESPN player list API as fallback).

## Draft helper (Phase 2, v0.4.0; RECOMMENDED section v0.5.0)

**RECOMMENDED (v0.5.0)** — top-3 pick cards above Available, scored by a
composite of board position (current rank source) + format-aware VOR +
roster need / open starter slots + ADP value + stacks + positional-cliff
detection (next same-pos player ≥12 VOR or ≥2.5 ppg worse). Every bonus
doubles as a reason chip on the card ("Fills RB need", "Cliff: next RB −21
VOR", "STEAL vs ADP"). K/DST suppressed until the last rounds. Click a card
for the full profile.

- **Leapfrog guard (2026-08-03, all draft helpers):** a lower-board player only out-ranks a higher-board player in RECOMMENDED when the better player's ADP says he'll still be there at your NEXT pick AND the two are ranked very close (same-position and cross-position alike); a cross-position jump is also allowed for a genuine position of NEED over a position with abundant startable supply. Otherwise the better board player stays on top regardless of bonuses.

Lineup-redraft tuning (Jack, 2026-07-23): once your starting QB/TE count is
filled, another QB/TE takes a HUGE penalty early (−40 through rd 9, −15 mid,
−5 late) — you can only start one, a backup there is a wasted pick (superflex
raises the QB starter count; dynasty modes exempt). Stacks are near-neutral
in redraft modes (+1, no reason chip — they're a best-ball lever); +3 with a
chip in dynasty modes.


`sidebar.js` + `sidebar.css` — the Sleeper helper ported onto the ESPN feed.
Mounts automatically in any `fantasy.espn.com/football/draft` room (league
drafts AND lobby mocks — both carry `leagueId`/`teamId` in the URL, so your
team is auto-detected and tracking starts by itself).

- **Pick feed**: passive — parses the `SELECTING`/`SELECTED` lines the
  MAIN-world sniffer captures from the room's own WebSocket. Never opens its
  own socket. On a mid-draft refresh it asks the sniffer to replay its buffer,
  reconstructing the full pick history (dedup by playerId).
- **Pick source = the room's draft board DOM (v0.6.0, THE fix).** Live-probing
  a real draft settled how ESPN actually works: it exposes **no** pick history
  over HTTP mid-draft (`mDraftDetail` AND `mRoster` stay empty — all
  `playerId:-1`), and the WebSocket join snapshot is an opaque base64 `INIT`
  **binary** frame (NOT resent `SELECTED` text — the v0.5.2 assumption was
  wrong; the room only WS-pushes NEW picks going forward). But the room
  decodes `INIT` into a live `.draftBoardGrid` of `.completedPick` cells
  (`.roundPick` "R.P" + `.playerFirstName/.playerLastName` + `.positionPill`
  + `.playerProTeam`). `pollBoard()` scrapes that grid every 2.5 s → the
  authoritative full pick history, **refresh-proof for free** because the room
  always rebuilds the grid from `INIT`. teamId per overall comes from
  `mDraftDetail`'s pick *structure* (teamIds are populated even though
  playerIds aren't); DST cells ("Chiefs D/ST") are rebuilt to the site's
  "Kansas City Chiefs D/ST" via the pro-team abbrev. When a grid exists it is
  the ONLY pick source (WS is used only for the instant on-the-clock signal);
  the mock harness (no grid) still exercises the WS path.
- **Storage restore (v0.5.1)** still runs as a pre-grid stopgap: picks persist
  to `espnPicks_<leagueId>` (now with names, since scraped picks have no ESPN
  playerId) and repopulate on boot until the grid scrape overrides them. Boot
  stages are independent: a league-API 404 (some lobby mocks) degrades to a
  grid-only helper and retries after 30 s. Probe: chip counts only real
  playerIds (>0), dump relay `mff-espn-probe-dump-request` → `-dump`.
- **Draft order**: one authenticated league fetch
  (`?view=mDraftDetail&view=mTeam&view=mSettings`) — explicit teamId per
  overall slot (no snake math needed; pre-draft falls back to
  `draftSettings.pickOrder` snake). Also supplies team names, lineup slots
  (superflex = OP), and scoring (rec + pass-TD re-scores Clay projections).
- **Player identity**: ESPN playerIds → names via the `players_wl` list API
  (x-fantasy-filter, ~1–3k actives), then name-matched into `data/players.json`
  (same file as the Sleeper helper — `export_sleeper_extension_data.py` now
  syncs a copy here on every export; DSTs renamed via normalize.js maps).
- **UI**: identical to the Sleeper helper — DRAFT/ROSTER/SETTINGS tabs, Jack's
  live Firestore boards, KTC/FP/Sleeper sources, mode-aware ADP value tags,
  VOR sort, needs, stacks, playoff SOS pills (live-Vegas refreshed straight
  from the site JSON — GitHub Pages sends CORS `*`, no background worker),
  manual ✕/＋ search fallback, ON-THE-CLOCK flash.
- **Not ported (yet)**: ESPN-page DOM decoration, slow-draft notifications
  (ESPN drafts are live-attended; the API pick feed is dead anyway), undo
  handling (use the manual search ✕/＋ if ESPN's undo desyncs a pick).

**Test without a draft:** serve this folder over HTTP and open
`mock_draft.html` — a 10-team snake mock that feeds the sidebar synthetic
sniffer frames every 2s (you are team 2), with Force-next-pick and pause
buttons. NOTE: if the repo's service worker has ever been registered on your
localhost origin, unregister it first (DevTools → Application) or it serves
the main site instead of the harness.

## Testing without a drafted league

- **Mock harness:** open `mock.html` (directly or via the repo dev server) —
  runs `normalize.js` against a canned ESPN payload with pass/fail checks.
  ESPN **mock drafts won't help**: the mock lobby is ephemeral and creates no
  league the API can read.
- **Real end-to-end:** create your own free ESPN league (any size). The league
  is readable pre-draft (settings/teams); run its draft with autopick filling
  the empty slots to get full rosters. Then visit the league page and click
  the export button.
- **Site side without the extension:** on the site, dispatch the bridge event
  from the console with a canned payload — the ESPN card and import flow run
  exactly as if the bridge had fired.

## Install (dev)

`chrome://extensions` → Developer mode → **Load unpacked** → this folder.
After any code change here, **bump `version` in manifest.json** and reload the
extension so the new build is verifiable.
