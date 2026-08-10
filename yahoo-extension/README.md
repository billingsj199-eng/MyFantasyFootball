# MFF Yahoo Helper

Chrome extension (MV3) that overlays the MFF season helper on
football.fantasysports.yahoo.com — the Sleeper/ESPN helpers' SEASON mode
(optimal weekly lineup, start/sit verdicts, waivers by upgrade delta, roster
values) brought to Yahoo leagues. Season-only for now: Yahoo drafts run in a
separate client the helper doesn't cover.

## The Yahoo constraint (why DOM scraping)

Yahoo's web app exposes **no cookie-auth JSON API** — the official Fantasy
API is OAuth-only (app registration + token flow, not available to a plain
content script), and the league pages are server-rendered. So v0.1 reads the
DOM, the same play as the Underdog helper:

- **Roster + current starters + lineup slots** — scraped from YOUR team page
  (`/f1/<league>/<teamId>`): rows whose first cell is a lineup slot (QB, WR,
  W/R/T, Q/W/R/T, BN, IR…) containing Yahoo's stable `.ysf-player-name`
  markup (`a` = name, `span` = "Buf - RB", status span for Q/O/IR). Persisted
  per league so other pages keep working; matchup pages are ignored (they
  render BOTH teams' rosters). Team abbrevs map onto the site's (WAS → WSH);
  DEF rows match by team abbr to the site's "… D/ST" entries.
- **Free agents** — captured from the league's **Players** page as you browse
  it (rows with an owning-team link are skipped as taken; the count shows in
  WAIVERS/SETTINGS, CLEAR FA CACHE resets). No full-league roster dump is
  possible over the DOM, so browse with the Available filter to feed the pool.
- **probe.js** (MAIN world) — passively records which internal endpoints
  Yahoo's own pages fetch (URLs only, param values stripped). SETTINGS →
  COPY PROBE LOG. Whatever shows up there is the upgrade path to an
  API-driven v2, the same probe-first play that cracked the ESPN draft room.

Everything else rides the same open endpoints as the other helpers: Jack's
live Firestore boards, the baked KTC/Clay/FP data (`data/players.json`,
synced by `export_sleeper_extension_data.py`), the site's Vegas lines +
weekly prop boards (`betting_lines_2026.json`), and Sleeper's public API for
week/injuries/actuals/trending (players.json sids bridge the ids).

## Tabs

- **LINEUP** — greedy optimal lineup over your scraped slots (narrow flexes
  first: W/R, W/T, then W/R/T, then Q/W/R/T). Weekly value = site Wk-N prop
  boards (UD+PP) blended 80/20 with the league-scored Clay base; in-season
  the base decays toward actual PPG (prior worth ~6 games). K/DST fully
  modeled from Vegas (the models' built-in defaults ARE Yahoo's default
  K/DST scoring). Byes derived from the Vegas schedule; OUT zeroed, D ×0.3,
  Q ×0.85 (Yahoo's own status wins over the Sleeper dump), ±1.5ppg Jack's-
  rank nudge. Start/sit moves with deltas, toss-ups under 1.5 ppg,
  verdict-colored rows, Vegas matchup pills, expandable profiles.
- **WAIVERS** — captured free agents ranked by the ppg they'd add to YOUR
  optimal lineup (a top-10 QB behind your stud reads DEPTH), Sleeper 24h
  trending 🔥, suggested drop + drop watch.
- **TEAM** — roster values by source (KTC / Jack's / FP / Sleeper),
  format-aware, KTC subtotals + total.
- **SETTINGS** — scoring (Yahoo's settings page isn't scraped yet: pick
  PPR/½/STD + 4/6pt passing TD; defaults are Yahoo's ½PPR/4pt), format
  (SF auto-detects from your slots; dynasty can't be scraped — set it),
  FA cache, probe log. Everything persists per league.
- **On-page decoration (v0.2.0)** — Yahoo's own `.ysf-player-name` rows get
  inline pills: verdict (▲ START / ▼ SIT / ≈ TOSS-UP) on your team page, the
  colored Vegas matchup pill, this week's projected ppg — and on the league
  Players page, the "LINEUP +x.x" upgrade delta each captured free agent
  would add to your optimal lineup. 2.5s re-scan, signature-cached.

No SIMS tab: league sims need every team's roster and Yahoo's DOM only
exposes yours — other rosters would take a page-by-page crawl. If the probe
turns up a usable league-wide endpoint, sims come with the API v2.

## Install (dev)

`chrome://extensions` → Developer mode → Load unpacked → this folder.
After any code change here, **bump `version` in manifest.json** and reload.

## Testing without a Yahoo league

Serve this folder over HTTP and open `mock.html` — a canned Yahoo team page
(deliberately wrong lineup, one OUT + one Q starter, an IR row) plus a fake
Players page (one taken row that must be skipped). The sidebar runs the real
scrape path against it.

## Known limitations (v0.1)

- Roster reads require visiting your team page (persisted after that).
- FA pool = only what you've browsed on the Players page.
- League scoring beyond rec/passTD uses Yahoo defaults (real K distance
  buckets already match).
- Yahoo markup drift will break the scraper — mock.html is the regression
  harness; probe log is the way out.

## Console hooks

`window.__mffYahoo` → `{ state, render, initForLeague, scrapeTeamPage,
scrapePlayersPage, wkVal, kickerProjFor, dstProjFor, optimalLineup,
waiverRecs, seasonLineupCalc }`
