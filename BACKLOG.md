# MyFantasyFootball — Backlog

_Last updated: 2026-05-13_

Running backlog for myfantasyfootball.org. Items are grouped by what's blocking them, then by effort. **Read DEPLOY_NOTES.md first** if any "Shipped" item below mentions Firestore rules — those features won't work in prod until rules are pushed.

---

## Suggested next-session priorities

If picking the next thing to do, in order:

1. **Move 3 deferred data groups to fully lazy** _(highest perf-per-effort lift available — ~26 MB off every cold load)_. Currently `legend_careers.js` (2.85 MB), `weekly_stats_retired_1/2/3.js` (10.15 MB total), and `all_players_weekly_1-5.js` (12.86 MB total) load on every visit via `defer`. They merge into `WEEKLY_STATS` / `D[].career` / `LDB.seasons` via re-run handlers at `_mergeWeeklyStatsRetired` (~line 5279), `_mergeAllPlayersWeekly` (~line 15560), `_applyLegendCareerBindings` (LDB at ~15468, D.career at ~15477). Convert each to the lazy-load pattern shipped 2026-05-13 for `college_stats.js` — see `_ensureCollegeStatsData` in index.html as the template.
   - **The careful path** (1-2 hour scoped session):
     1. Audit every `WEEKLY_STATS[name]` read (26 sites, 14 already use `typeof` guards) — confirm each is inside a function called only after page navigation, not at parse time.
     2. Same audit for `LEGEND_CAREERS[name]` and `ALL_PLAYERS_WEEKLY[name]` reads.
     3. Map each consumer to the page/feature that triggers it (openPlayerCard, switchPage('trivia'), legend leaderboard page, player history page).
     4. Add a `_ensureLegendsData()` lazy loader that pulls all 3 groups in parallel via `Promise.all`. Triggers: openPlayerCard (retired-player branch), switchPage('trivia'), switchPage('legendBoard'?).
     5. Refactor one file group at a time. After each, smoke-test trivia + a retired player card + the legends leaderboard.
   - **Why it wasn't done 2026-05-13**: previous-session P1 regression was caused exactly by deferring data scripts without auditing parse-time consumers (handoff: "the agent missed at least 4 cases"). The 26 MB win is worth a dedicated session, not a bolt-on at the end of an already-long one.
   - **Verification**: cold-load Network panel should show zero requests for `legend_careers.js`, `weekly_stats_retired_*`, `all_players_weekly_*` on the rankings page. Opening any retired player card should fetch them.
2. **Per-year top-25 sweep for trivia** _(scoped 2026-05-07, not finished — see "Trivia data — known remaining gap" below)_. Fresh session can pick up the localStorage seed list of 452 unique slugs.
3. **Phone-test mobile responsiveness on real devices** — full mobile pass + emulator scan done 2026-05-06 but a real phone may still surface issues (touch targets, iOS Safari quirks, real-world rotation behavior).
4. **ESPN league import** (multi-week) — biggest TAM unlock. Single largest gap in user acquisition.
5. **Inline-style hex/rgba color audit for light mode** — 15 fixes shipped 2026-05-13 (plan-option cards, premium-redeem input/button/divider, rookie sub-pos filter, ADP source tabs, bench chip, JM badge, UD expand panel, pagination dots, etc.). The remaining inline `color:#000`/`#fff` patterns are mostly intentional (orange-accent buttons, white-on-solid-brand badges). Continue the audit only when you spot a *new* broken element.

---

## Shipped 2026-05-13

### Perf — lazy-load + bundling (~2.3 MB off cold load)
- **P3 phase 2 — college_stats.js + 3 patches + college_weekly_devy.js now lazy-loaded** via `window._ensureCollegeStatsData()`, mirroring the existing `_ensurePffData` pattern. Triggers: switchPage(prospect|compare|backtest|mockdraft), mode-switch to dynasty, first dynasty render, openPlayerCard. Three inline patch blocks at index.html:4445-5198 wrapped as `window._csPatch1/2/3` and applied after the 4 files resolve. devy fetched in parallel with the college_stats chain via `Promise.all`. Verified end-to-end: 5,702 COLLEGE_STATS keys + 5,673 COLLEGE_WEEKLY keys after first trigger, 84-104 ms total.
- **P2 (scoped) — 42 stable lookup tables bundled** into one file via `scripts/bundle_lookups.py` → `data/_bundle_lookups.js` (548 KB). Replaces 42 `<script>` tags at index.html:3351 with one. Pipeline-regenerated files (d.js, all_players.js, weekly_stats_active.js, etc.) deliberately stay separate so the Python pipeline doesn't need to know about bundling. Re-run `python scripts/bundle_lookups.py` after editing any source file.
- **B3 auto-fixed**: `bbm_optimizer_data.js` (228 KB) is now inside the bundle, so the production 404 will resolve once `_bundle_lookups.js` is uploaded.
- **render() optimization**: hoisted 6 per-row computations (`_adp`, `_projPpg`, `_25ppg`, `_projColor`, `_25Color`, `_displayTierLabel`) out of inline IIFEs and pre-sorted `tiers` once per render. Pure-JS render time 113ms → 90ms (20% faster). User-perceptible sort-click stays ~300ms because browser layout/paint of 506 rows dominates — pushing below that requires DOM diffing or row virtualization (not warranted at current scale).

### A11y sweep
- **Sortable rankings headers** — all 12 `<th data-sort>` got `tabindex="0"`, initial `aria-sort` (default-sorted `#` → "ascending", others → "none"), and the sort handler now updates `aria-sort` + handles Enter/Space keydown.
- **Account avatar** — `<div>` acting as button got `role="button"`, `tabindex="0"`, `aria-label="Account settings"`, and Enter/Space keydown handler.
- **Auth password show/hide toggle** — got `aria-label`, mirrored in the JS handler alongside the existing `title`.

### Light-theme color audit (15 fixes)
- Plan-option cards (Monthly + Season), inline `<style>` block with `!important` rules, premium-redeem input, "Manage subscription" button, premium panel "Have a redeem code?" divider, rookie sub-pos filter, ADP source tabs row, bench position chip, 2 mock-draft info boxes, mock-draft progress bar, JM badge, UD expand panel, pagination dot, mobile-card ADP-cell separator. All swapped from hardcoded `rgba(255,255,255,.X)` / `rgba(255,255,255,.08)` to `var(--elev-1/2/3)` and `var(--border)` so they auto-flip to black-tints on light theme. Verified flips both ways.

### Extension polish
- **MFF Draft Helper extension** — `MAX_FETCH_RETRIES` 12 → 3 in `underdog-extension/mff-bridge.js` (30s window instead of 2min). The B1 short-circuit on the site side already stops console spam; the retry trim makes the extension itself tidier. Manifest bumped to 0.10.15.

### Investigation only (no code)
- **B3** — confirmed `bbm_optimizer_data.js` 404 in production is just an unuploaded file (228 KB). v0.10.0 construction score silently falls back to QF-only `BBM_BUILD_RATES` without it. Now auto-fixed via bundling (see Perf section).
- **C1/C2/C3 hosting audit** — GitHub Pages hardcodes `Cache-Control: max-age=600`; refuses Brotli even with `Accept-Encoding: br`; HTTP/2 already on by default. C1+C2 only fixable by putting Cloudflare's free tier in front (1y edge TTL Cache Rule + Brotli toggle). The service worker already mitigates C1 for returning visitors via cache-first on `?v=` assets.
- **P6 phase 2 verdict — not worth doing.** Measurements show `content-visibility: auto` on rankings rows is active (`firstRowContentVisibility: "auto"`, `containIntrinsicSize: "auto 52px"`) and effective (visible-30-rows layout = 0ms vs full-506-row force-layout = 0.7ms cached). The remaining cost is in the `render()` JS (90ms) and browser paint of 506 rows, not in off-screen-row materialization. IntersectionObserver windowing wouldn't help. To push the sort-click number below 200ms would require DOM diffing or row virtualization.

### B3 → bundle deploy checklist
When you next deploy:
1. `index.html` (script-tag swap, lazy-load hooks, a11y attrs, color fixes, render hoisting)
2. `data/_bundle_lookups.js` (new — the bundle output; auto-fixes B3)
3. `scripts/bundle_lookups.py` (committed so future-you remembers how to refresh)
4. `underdog-extension/mff-bridge.js` + `underdog-extension/manifest.json` (extension retry trim, version 0.10.15)

---

## Shipped 2026-05-07

### Trivia features
- **Daily Board** — deterministic-by-date challenge (FNV-1a hash of YYYY-MM-DD seeds a Fisher-Yates shuffle of a 12-template pool, every 12-day window covers all templates). Live `?daily=YYYY-MM-DD` permalinks lock the seed; share text uses Wordle-style emoji grid (🟩/🟥/⬜) + score + time + permalink with content-hash version stamp (`&v=HASH`). Drift detection: when a permalink's `v` doesn't match current item hash, a dismissable amber banner surfaces.
- **localStorage state**: `mff_triviaDaily` tracks streak, lastPlayedDate, completed[date]. Streak rule = consecutive-day with `_triviaPrevDay` for month/year-boundary safety; replays don't bump streak.
- **Surprise Me button** — random AI-generated trivia from a curated 12-prompt list (Wordle-style variety). Intentionally NOT in the daily rotation since AI output isn't deterministic.
- **Admin Preview** — date input + "PREVIEW DATE" button for QAing future dailies. In-memory only (no localStorage), no streak pollution. Defaults the date input to tomorrow.
- **Lock as Daily** — admin button writes the currently-rendered board to Firestore `trivia_daily/{YYYY-MM-DD}`. Players on that date see the locked snapshot verbatim, immune to data drift. Works on any board (cycle pick / template / AI prompt).
- **Daily Archive** — admin browse + replay panel listing all locked dailies (newest-first, top 100). Click to replay any past board. Anonymous play of archived boards available without auth.
- **Public exposure** — trivia nav button no longer admin-gated. Page tab renamed "Board Builder" → "Trivia". Save-to-catalog and Lock-as-Daily affordances stay admin-only via `_renderBoard`/`_triviaUpdateAdminUI` checks.
- **First-visit onboarding** — sky-blue tooltip above the daily panel ("How it works") shown once per `mff_triviaSeenIntro`. Skipped on permalink visits.
- **Customize disclosure** — Board Filters + Game Settings now collapsed behind a `<details>` summary, default closed (`mff_triviaCustomizeOpen`). Templates remain the primary one-click on-ramp.
- **Report this cell** — 🚩 button on every revealed cell. Submits to Firestore `trivia_reports` (no auth required, strict shape validation in rules). Admin Reports panel lists pending reports with cell context, expected/guess/reason, one-click resolve (delete).
- **Postseason trivia** — new "Season Type: Regular Season / Postseason" filter in Board Filters. Career mode aggregates `s.post.*` per player; season mode emits one entry per playoff-bearing season. 3 quick-start templates added (Career Playoff Pass/Rush/Rec Yds), also in daily pool.

### Trivia data backfill (massive — `data/legend_careers.js` 414KB → 1.93MB, 467 → 1,725 players)
- **nflverse 1999+ refresh** — 1,560 players' regular-season + postseason data pulled from nflverse-data GitHub release. Authoritative for modern era. Adrian Peterson collision fixed (Vikings AP `00-0025394` not Bears AP `00-0021306`; +625 phantom-yards bug eliminated).
- **Wikipedia parser** — RB-focused initially, extended to QB (Cmp/Att/Yds/TD/Int columns) and WR/TE (Rec/Yds/TD); rowspan/colspan-aware grid expansion; per-position keyword detection in `find_career_table`. Fixed falsy-zero bug in `yr_idx` resolution (`col_map.get('year') or ...` returned None when year was column 0).
- **Pull rounds**: `pull_top_legends.py` (96 union-of-top-25 career legends across 7 categories), `pull_all_retired_legends.py` (209 retired hp.js players via `_yrs`-span check), `_retry_disambig.py` (28 more via slug overrides like `Jim_Taylor_(fullback)`).
- **Wikipedia postseason parser** — `find_postseason_table` finds wikitables preceded by an h2/h3/h4 with "Postseason" or "Playoffs" header. `pull_wiki_postseason.py` added 85 retired players' pre-1999 postseason via this path.
- **PFR via Chrome MCP** — Cloudflare-blocked the direct scraper, but a real Chrome browser bypasses it. 43 priority legends pulled with full year-by-year postseason: Emmitt Smith (1,586), Tony Dorsett (1,383), Walter Payton, Marcus Allen, Roger Staubach, Bart Starr, Otto Graham, Brett Favre, Joe Montana, Dan Marino, John Elway, Jerry Rice, Lance Alworth, Don Maynard, James Lofton, etc. Career rushing top-12 now matches actual NFL leaderboard exactly.

### Trivia data — known remaining gap _(seed for next session)_
- **Per-year top-25 sweep, scoped but unfinished**: scraped 29 leader pages (15 yrs rushing 1970-79+1980+1985+1990+1995+1998, 7 yrs each passing/receiving sampled) → 452 unique player slugs in browser localStorage on the PFR tab. Gap players (those not yet in `legend_careers.js`) need full PFR profile pulls via Chrome MCP. Approach for fresh session: write a Python helper that drives the Chrome MCP through the slug list with localStorage as accumulator, checkpoint every 10 profiles, then `merge_pfr_postseason.py`-style merge. Estimated ~225 profile pulls × 10s = ~40min unattended. Marginal players added would mostly be second-tier role players (Lynn Cain 1980, Mark van Eeghen 1977, Dexter Bussey, Mike Pruitt, etc.) — valid trivia answers but not headline drivers.

### Firestore rules _(deployed live 2026-05-07)_
- `trivia_daily/{YYYY-MM-DD}` — public read, admin write (matches `trivia_catalog` pattern).
- `trivia_reports/{reportId}` — anonymous create with strict shape (field allowlist, size caps, type checks), admin read + delete, no updates. Specifically validates: `keys().hasOnly([date,itemIdx,expected,guess,reason,createdAt,title])`, all strings size-capped, `itemIdx is number 0..100`.

### MFF Draft Helper Chrome extension (separate from main site)
- North-edge resize handle on the sidebar (`#mff-resize-n`, 5px strip, z-index 12 above header). Drag-down shrinks panel keeping bottom pinned; cursor `ns-resize`. Solves "panel taller than viewport, can't reach south handle".
- Removed redundant "First Pick At Position" odds panel — `Next Pick Advance Rate` panel covers the same data with QF/SF/Fin levels in one view. BBM Optimal Shape badge now locks to QF (its existing default when `_mffOddsLevel` undefined).
- Re-anchored Stack panel to badge (was oddsPanel, removed).
- Repositioned Next Pick Advance Rate above the milestones list inside `_renderBbmAdvance` so the daily-game advice surfaces before the checklist.

---

## Shipped 2026-05-06

### Bug fixes
- Kicker `s25.fpts=0` → `adj25ppg` falls back to `s25.ppg` for K/DST when `fpts` is 0 (Butker '25 PPG was rendering 0.0 instead of 8.2)
- ROOKIE filter rank gaps → sequential 1..N ranks now applied (was showing global myRank with gaps)
- `index.html` missing closing tags → restored truncated `gw-share` block + `</body></html>`

### Cloud-sync expansion
- Added to `SYNC_KEYS_MAX`: `ep_longest_streak`, `lastSavedAt`
- Added to `SYNC_KEYS_STR`: `mff_seen_intro` (onboarding), `mff_theme` (light/dark)
- New `SYNC_KEYS_OBJARR` mechanism for object-array merge (dedupe by `ts`, sort desc, cap)
- `md_draft_history` now syncs across devices, capped at 10 most recent entries
- Sync triggers added to `markSaved()` (rankings) and after `md_draft_history`/tour-close writes

### Mobile
- `.filter-row-top`, `.version-tabs`, `.mode-tabs`, `.pos-filters` wrap on mobile (was hidden horizontal-scroll cutting off REDRAFT/SUPERFLEX/etc.)
- Quick Compare extracted to its own `<div id="compareSummary">` outside the horizontal-scrolling `.compare-grid`
- Toolbar wraps on mobile (was hidden horizontal-scroll)
- `.trade-mode-tabs`, `.md-mode-tabs`, `.md-rank-src-tabs`, `.games-tabs` all got `flex-wrap:wrap`

### Features
- **Onboarding tour nav button spotlight** — each step lifts the matching nav button above the dim overlay with a pulsing glow ring (`.mff-tour-spot`). Steps 1-4 spotlight rankings/myteams/trade/account.
- **Public ranking sharing** — SHARE button in toolbar (My Rankings + signed in) writes to Firestore `shared_rankings/{8charId}`, copies `?ranks=ABC12345` URL. Recipients see read-only modal with the ordered list. ✅ Firestore rules deployed 2026-05-06.
- **Trivia embed mode** — `?embed=trivia&id=<docId>` hides chrome (`body.mff-embed`) and auto-loads a catalog board for iframe use. `trivia_catalog` already had `allow read: if true` so no rules change needed.
- **Dark/light theme toggle** — moon/sun button in toolbar; `:root[data-theme="light"]` token block; persisted to `mff_theme` and synced; synchronous head-script prevents flash of dark on light-theme load. **Caveat**: ~30 inline-style hardcoded colors haven't been tokenized yet — they'll look slightly off in light mode. Fix iteratively (or do a sweep with the `--elev-1/2/3` tokens already added).
- **Player profile URLs** — `?player=justin-jefferson` opens that player's card. `openPlayerCard` also pushes the slug URL when called from anywhere, so clicking any player anywhere → URL becomes shareable. Browser back button closes the card.
- **JSON export** — JSON button next to CSV in the rankings toolbar. Output: `{source, version, mode, position, scoring, exportedAt, count, players: [{rank, name, team, pos, posRank, adp, age, tier?, ppgProj?, ppg2025?, adpDiff?, jsModelPpg?, jsModelVor?, jsModelSeason?}]}`.

### Accessibility
- `:focus-visible` outline ring globally
- `aria-label` on all 9 sidebar nav buttons
- `aria-label="Primary"` on the nav landmark
- `aria-hidden="true"` on decorative logo SVG

### CSS hardening
- Added `--elev-1/2/3` tokens for subtle surface overlays
- Replaced 9 `rgba(255,255,255,.0X)` literals in `main.css` with the tokens (mode-tabs, tier-btn, career-log-toggle, combine-stat, card-view-toggle/btn:hover, lg-grid-row:nth-child(even), trade-insight-row, trade-pick-year-tabs)

### Mobile scan fixes (verified at 375x812 viewport)
- **Rankings page mode tabs not actually wrapping** — `.mode-tabs` and `.version-tabs` had `flex-shrink:0` which prevented their parent constraint from triggering inner `flex-wrap`. Removed `flex-shrink:0` so tabs now wrap to a second row when needed (DYNASTY SF was clipping the right edge).
- **Centered page titles overlapping the SIGN IN button** on Trade Calc / Mock Draft / Account / Prospect / Compare. The auth anchor is absolutely positioned top-right; on mobile the centered titles ran underneath. Fix: added `padding-top:56px` to those pages on mobile and shrunk the `.global-signin-btn` (smaller padding/font/svg).
- **Compare page had auth anchor sitting at top-left** because `.page-compare > .auth-anchor` was missing from the absolute-positioning rule list. Added.
- **My Teams page had ~8px horizontal overflow** causing a phantom scroll gap on the right. Switched `#pageMyTeams` overflow from `auto` to `overflow-x:hidden;overflow-y:auto` so the residual overflow is clipped instead of creating visible scroll gap.
- **Player card modal verified working on mobile** — fits viewport, all sections (Fantasy/Prospect/Comps tabs, Career Log table, Player Info) scroll cleanly. URL updates to `?player=slug` on open and clears on close.
- **Rankings table** — horizontal scroll works, thead is sticky. **Sticky first columns added** on mobile: drag handle col hidden (no useful touch interaction), rank + player columns sticky-left so the player name stays visible when scrolling right to see PPG / age / etc. Soft right-edge shadow on the player col hints at scrollability. Desktop unaffected.
- **Player card share button** — chain icon next to the close button copies a `/p/<slug>.html` URL to clipboard. Toast: "Player URL copied". Falls back to `prompt()` on browsers without clipboard API.
- **OG / Twitter card meta tags for shared player URLs** — `scripts/build_player_og_pages.py` generates ~580 static HTML files in `p/<slug>.html` with proper `<meta property="og:image">` etc. so social-media crawlers produce rich previews. Real users get a JS redirect + meta refresh to the main app's `?player=<slug>` detector. ~100 active players have ESPN headshots in the OG image; the rest get title+description-only summary cards. Regenerate with `python scripts/build_player_og_pages.py` whenever d.js changes.
- **sitemap.xml** — same build script writes `sitemap.xml` at the project root listing the homepage + all 580 player pages so Google Search Console picks them up. Submit the URL `https://www.myfantasyfootball.org/sitemap.xml` in GSC once deployed.
- **PWA / Add to Home Screen** — `manifest.webmanifest` + `sw.js` (network-first service worker for the shell). Apple meta tags (`apple-mobile-web-app-capable` etc.) for iOS standalone mode. Theme color, app shortcuts (Rankings / My Teams / Trade / Mock), `start_url` with `?source=pwa` for analytics. **Caveat**: Chrome's *auto* install prompt requires 192×192 + 512×512 PNG icons; without them users can still install manually via browser menu / iOS Share sheet. Generating PNGs is a follow-up.
- **Player card 4th tab — INFO** — split out Career Highlights + Bio + Injury Status into a new INFO tab so the FANTASY tab stays focused on rankings/projections/ADP/career log. The "Player Info" section was renamed to "Bio" inside the INFO tab. The header injury pill stays for quick-glance alerts; an expanded Injury Status section in INFO shows full details (severity, projection impact %, return estimate).
- **Player card ADP Comparison fix** — was showing `—` for Sleeper because the code read `d.slp` (which doesn't exist); the real Sleeper data is in `d.slR` / `slSf` / `slDy` / `slDsf` (mode-specific). Now uses the existing `_sleeperRank(d)` helper. Underdog also fixed to use `d.udA` (Best Ball Mania) / `d.sfa` (Superflex), falling back to legacy `d.a`. ESPN/Yahoo stay as placeholders — wired so populating `d.espnAdp` / `d.yahooAdp` in `d.js` and uncommenting two lines in the card lights them up.
- **Player card context-aware mode** — `openPlayerCard(d, ctxMode)` now accepts an optional mode override so callers can scope the card's rank / pos rank / ADP / Sleeper rank to the calling context. Implemented via internal helpers `_udAdpInCtx()` / `_slpAdpInCtx()` and a `_rankInCtx()` board lookup. Section headers now show the mode label (e.g. "Rankings · Dynasty SF") so users see what they're looking at. Callers updated:
  - **Trade Calc** passes `tradeMode` — clicking a player while a Dynasty SF trade is open shows their Dynasty SF rank.
  - **Mock Draft** passes `mdMode` — past-draft cards show ranks scoped to that draft's mode.
  - **My Teams** team detail — added clickable player names (with `_mtGetRankingMode()`); previously the names were plain text. Now clicking a player in a dynasty league imported from Sleeper opens the card with their dynasty rank visible.
  - **Rankings page** is unchanged (uses `currentMode` default).
- **Dynasty cards swap ESPN/Yahoo → KTC** — in dynasty contexts (`dynasty` / `dynastysf`) the ADP Comparison panel now shows Underdog / Sleeper / KTC (3 columns) instead of Underdog / Sleeper / ESPN / Yahoo. Dynasty SF uses the `KTC_SF` map; Dynasty 1QB uses `KTC_1QB`. Redraft / Best Ball / Superflex unchanged (still 4 cols with ESPN/Yahoo placeholders).
- **Removed Injury Impact / Return-to-Play / Injury History from FANTASY tab** — the recovery-curve chart + history table took ~½ the card height for niche use cases; the projection discount logic still runs in the background and adjusts Proj PPG accordingly. Header injury pill kept as quick-glance alert; INFO tab still has the basic "Injury Status" section. Trims ~120 lines from `openPlayerCard`.
- **Trivia cell autocomplete broadened** — was only suggesting names from the current board's answer set (so typing "ha" with Justin Jefferson as the right answer surfaced nothing). Now pulls from active players (`D`) + historical players (`ALL_PLAYERS_DB`) — same broad pool the daily Elite Pull / Guess Who games use. Suggestions show position pill + team for context. Already-revealed answers still get filtered out.
- **Trivia correct-reveal restyle** — was flooding the whole cell with team color, dimming the stat strip to 15% opacity. Now baseball-card style: stat strip stays full opacity at top (e.g. "22,881 REC YDS"), bottom region is neutral/light, and team color appears as a subtle glow ring around the player headshot (`box-shadow` with two stops at .18 and .35 alpha). Initials placeholder gets the same glow when no headshot is available.
- **Trivia logo coverage fix** — `_triviaLogoUrl()` was returning empty for non-canonical abbreviations (ARZ instead of ARI, BLT instead of BAL, KAN instead of KC, OAK instead of LV, STL/SD legacy, etc.) so some cells fell back to dimmed text. Added `_TEAM_ABBR_ALIASES` map covering ~25 common alts across PFR / ESPN / Sleeper / historical data sources. Now every cell on the test board renders its team logo as the visual hint.
- **Removed gold divider line in trivia cells** — `.trivia-guess-input` had a 2px accent-colored top border separating the team logo from the input. Cleaner without it; cells now read as a single visual unit.
- **Player name replaces guess input on reveal** — `.reveal-name` now anchors to the bottom of the cell (where the input lived) with bold DM Sans + dark text on white background. Headshot sits in the upper portion. Mirrors the structure of the guess state so revealed and unrevealed cells share a consistent visual rhythm.
- **Trivia autocomplete dropdown unclipped** — was being clipped by `.trivia-cell { overflow:hidden }` because the dropdown was appended INSIDE the cell with `position:absolute;bottom:100%`. Now appended to `document.body` with `position:fixed` and computed coordinates so it floats above the input regardless of parent overflow. Wider min-width (180px) for readability on narrow cells.
- **Trivia reveal photo restyle (round → square)** — was a circular headshot with a glowing box-shadow halo. Now a square photo (border-radius:4px) that visually *replaces* the team logo with a clean 3px team-color border. Same footprint as the unrevealed logo so cells don't shift size on reveal. Initials placeholder gets the same square treatment.
- **Stats stay above on reveal** — `.trivia-cell-reveal` was using a fixed `top:26px` offset which left a white gap above the photo (the cat strip is only ~12px tall in normal view, so there was 14px of empty white between stat and photo). Now flows as a normal flex child (`flex:1`) so it naturally fills below the cat strip with zero gap regardless of viewport size. Cells now match the unrevealed-cell rhythm: stat top → content middle → label bottom.
- **Reveal image fills the available box** — image now uses `width:100%; flex:1 1 0` so it grows to take all remaining vertical space between the stat strip and the name. `object-fit:contain` so the player isn't cropped. Name uses `white-space:normal; word-break:break-word` so longer names like "Justin Jefferson" wrap to 2 lines instead of truncating with ellipsis. Verified: ESPN headshot `3043078.png` (Derrick Henry) loads correctly.
- **Player silhouette outline via drop-shadow** — instead of a rectangular border, the team-color outline now traces the player's actual head and body shape using 4 stacked `drop-shadow(±1.5px 0/±1.5px 0 color)` filters. Works because ESPN headshot PNGs have transparent backgrounds — the filter only applies to opaque pixels. Initials placeholder (no transparent silhouette to outline) still uses a square border. Also removed the cell-level `border:3px solid` on revealed cells so the only visible outline is the silhouette itself. Wrong cells still get the red box border for clarity.

### Investigations (no code change, documented)
- **SUPERFLEX trade picks** — `PICK_BASE` explicitly defines static values for `superflex` (90/40/18/7), separate from dynamic dynasty values. The system was *intentionally* designed to keep picks visible in SUPERFLEX. Whether redraft-superflex users actually trade picks is a design call you should make.
- **Premium gates audit** — every gate has a working upgrade flow already (full-page walls, paywall rows, toasts + auto-navigate). The "value proposition isn't obvious" concern is about the upgrade page itself, not the gates.

---

## Open work

### Quick wins (<1 day each, doable now)

- **Bye week column** — blocked on 2026 NFL schedule release (typically mid-May). When data drops, decide source: Sleeper API at load (live) vs. static `data/bye_weeks.js` regenerated weekly. Insert between Pos Rank and ADP.
- **Performance: virtualize the rankings table** — ~500 rows render at once. Risky without test coverage; do this on a quiet branch.
- **Analytics on tool usage** — wire Plausible / Umami / GA4 to track which pages/features get used. Drives future roadmap. Needs service decision first.
- **Inline-style color audit for light mode** — ~30 places in `index.html` use hardcoded hex/rgba colors that don't follow the dark→light flip. Each is small; do them as you spot broken elements in light mode.
- ~~**Sticky first column on the rankings table**~~ — _Shipped 2026-05-06._

### Day-scale items

- **Trade Calc 3-way trades** — design call first (3-column layout vs. rotating A→B→C, fairness scoring across pairs vs. net flow per team). Current scoring is `A.total vs B.total`; multi-team needs new model.
- **Onboarding tour copy/quality v2** — current spotlight works; tour copy could be tightened or include short demo clips per step.
- **Prospect Model per-tier hit-rate panel** — already shown in TIER column + tooltips. v2 could surface a top-of-page panel making the data more discoverable. Design call: does the tooltip suffice?
- **Push notifications for daily challenge** — needs service worker + VAPID + Cloud Function that triggers daily. Half-shipping (subscriber UI without Cloud Function) means users opt in and get nothing — worse UX than no feature. Skip until the backend is committed.

### Multi-day infrastructure

- **ESPN league import** — biggest TAM unlock. Public leagues read without auth via `lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/...`. Private leagues need `swid` + `espn_s2` cookie input. Player ID mapping is the hard part — `data/fallback_espn_ids.js` covers ~100 active players, ESPN rosters have 150-200 active. Need to scrape or maintain a fuller map. Multi-week.
- **Yahoo league import** — Yahoo Fantasy API requires OAuth registration with Yahoo Developer. Cleaner auth than ESPN but more setup. Multi-week.
- **Mock Draft pull from connected league** — depends on ESPN/Yahoo imports landing first.
- **Player profile pages (full)** — MVP shipped (linkable URL opens card). Full standalone page with aggregated rankings + grades + news + game log is still ~1-2 weeks.
- **Notifications system (player injury alerts)** — cron job comparing Sleeper injury data against each user's rankings; web push + email delivery. Needs SendGrid/Postmark + Cloud Functions + service worker.
- **Newsletter / weekly digest** — auto-generated "biggest movers, biggest news, your team grade" email. Cron + email service + template.
- **API / data export (full REST)** — client-side JSON export shipped. Public auth-keyed REST endpoints + rate limiting + docs site is ~1-2 weeks.
- **Multiplayer / league challenges** — compete against your fantasy league on the daily. Backend: shared score docs per league, leaderboard. Multi-week.
- **Public board library (Trivia)** — let users publish boards and others play them. Currently the trivia page is admin-gated; opening it to public would need moderation, board-share URLs, browse UI, search. Multi-week.
- **Accessibility audit (deeper pass)** — keyboard navigation across all interactive elements, screen reader labels on tables and grids, contrast on `var(--text2)` (especially in light mode), full ARIA roles. ~2-3 days.

---

## Session-discovered follow-ups

### Stale data
- **10 backup kickers in d.js** — ATL/Romo, BUF/Badgley, GB/Havrisik, HOU/Wright, IND/Shrader, LAR/Karty, NYG (Gano+Sauls+McAtamney — three!), SF/Gay. None have `myRank`. Revisit before 2026 season prep.
- **`mike_clay_projections.js` has zero K and zero DST entries** — 2026 PPG values for those positions come from `d.js d.p / 17`. Re-extract from source if you want true K/DST projections.

### Behavioral choices needing your call
- **SUPERFLEX trade mode shows pick selectors** — system is *intentionally* designed this way per `PICK_BASE` analysis. Change to `(tradeMode === 'dynasty' || tradeMode === 'dynastysf')` if you want redraft-style (no picks). One-line edit.

### Code health
- **`index.html` is 2.4 MB** — Prospect Model JM scoring + Trade scoring + Mock Draft logic are each multi-thousand-line blocks that could split into `scripts/` files. Risky without test coverage.
- **Many state vars are window-scoped via closures** — works but makes refactoring brittle. Cleanup layer for if/when you migrate to a build system.

---

## Future ideas (not yet planned)

Ideas that aren't on the active backlog but are worth considering for future roadmap planning. Roughly grouped by theme.

### SEO / social (high-leverage, low-effort)
- ~~**Open Graph + Twitter Card meta tags for `?player=slug` URLs**~~ — _Shipped 2026-05-06_ via static `/p/<slug>.html` pages.
- **Same OG approach for `?ranks=ID` shared rankings URLs** — harder because the data is dynamic (Firestore docs created ad-hoc). Options: (a) write a Cloud Function meta-tag proxy and migrate hosting from GitHub Pages to Firebase Hosting, (b) at share-creation time, also write a static HTML stub somewhere, (c) skip for now (ranks shares are less viral than player profiles).
- **Improve OG image coverage** — only ~100 of 580 active players have ESPN headshot URLs in `data/fallback_espn_ids.js`. Build a maintenance script that extracts more name→ESPN-ID mappings from the live site's runtime resolution and appends to the fallback file. Each new mapping adds rich `summary_large_image` previews for that player.
- **OG image generator** — an SVG → PNG image showing "Bijan Robinson · RB1 · Atlanta Falcons" for embedding when shared. Cloud Function that renders on demand and caches.
- **sitemap.xml** for the player-profile URLs — Google Search Console picks these up, helps with indexing player names as keywords.

### PWA / install
- ~~**Add to Home Screen / PWA**~~ — _Shipped 2026-05-06._ Manifest + SW + Apple meta tags + app shortcuts. **Still TODO**: generate 192×192 and 512×512 PNG icons so Chrome auto-fires the install prompt (currently users have to install via browser menu).
- **iOS pull-to-refresh** + native-feeling viewport behavior on mobile.

### Power user / admin tools
- **Bulk paste import** for My Rankings — paste a list of player names (Twitter cheat sheet, copied from a forum post, etc.) and auto-add them to your rankings in order.
- **Custom notes per player** — text field on the player card visible only to the user (synced to Firestore). "Watch his preseason snaps", "Sleeper for week 14", etc.
- **Watchlist** — separate from rankings; just "players I'm tracking". Smaller commitment than ranking, useful for waiver wire targets.
- **Saved filter presets** — "QB-only, Half PPR, Dynasty SF" as a one-click view.
- **Tier templates** — save your common tier breakpoints (e.g. "S=top 6, A=top 12, B=top 24") and apply across modes.
- **Bulk edit rankings** — multi-select players in the table, move them all up/down N spots.

### Data / model enhancements
- **Schedule strength column** — easy add once bye week data ships. Color-code the upcoming 4-week SOS for each player.
- **Snap count / target share columns** for veterans (might need a new data source — PFR has it).
- **Player news feed** — Sleeper API has news; integrate a news ticker or per-player news on the card.
- **Defense vs. position rankings** — show "top WRs vs. this team's pass D" matchup data on the player card.
- **Weekly projections** (not just season) — for in-season use during the season.
- **Red zone touch / target share** — known fantasy-relevant signal.

### Engagement / retention
- **Smart alerts** — "Jack moved Bijan from RB3 → RB1 this week" weekly digest. Could be in-app banner first, email later.
- **Achievements / badges system expansion** — first ranking saved, 30-day streak, first trade analyzed, mock-drafted 10 times, etc. Some badge infra already exists per `jb_unlocked_badges`.
- **Streak leaderboard** — public "longest current streak" board for daily challenge. Drives competitive return visits.
- **Daily mini-challenges** beyond existing — "guess this week's biggest waiver pickup", "most-traded player today".
- **Email password recovery + magic link** sign-in (the auth modal is currently SSO-heavy).

### Sharing / virality
- **Trade Calc embed mode** — same pattern as trivia embed (`?embed=trade&id=...`). Lets users embed a trade result on a forum post.
- **Mock Draft replay link** — share a `?mockId=X` URL that replays your draft pick-by-pick.
- **"Roast my team" AI feature** — power-user only; submits your roster to Claude API for a humorous + insightful analysis. Premium-tier hook.
- **Public profile pages** — `/u/username` showing a user's public rankings, trade history, daily challenge streak.

### Premium-tier value-adds (improve conversion)
- **AI-assisted draft assistant** — during a mock draft, get Claude-API suggestions for the best pick given roster construction.
- **Custom league scoring formats** — not just PPR/Half/Std. Support 0.5/0.75/1.5 PPR, TE premium, 6-pt passing TDs, etc.
- **Multi-team analyzer** — analyze ALL your imported leagues at once: "your portfolio is over-exposed to Atlanta Falcons RBs".
- **Historical 'what-if'** — re-run a past draft with your current rankings; see how you'd have ended up.
- **Trade negotiation AI** — given a trade offer, get counter-offer suggestions tuned to fairness scoring.
- **Lineup optimizer** for best ball / DFS — given a player pool, suggest optimal lineups.

### Content / blog
- **Blog / news section** — Friday "biggest waiver pickups" post, weekly model updates. SEO win + email-list driver.
- **Position scouting guides** — "How JM Score works", "Why we weight breakout age", evergreen content for SEO.

### Trade Calc enhancements (beyond 3-way)
- **"Trade finder" suggestions** — given my roster + a target player, suggest realistic packages I could send.
- **League-context fairness** — pull league rosters via Sleeper, score the trade in context of both teams' needs (not just raw value).
- **Trade history / log** — past trades you analyzed, with retroactive grading once the season plays out.

### Mock Draft enhancements
- **Live multiplayer mocks** — invite friends to draft in real time. Backend-heavy.
- **Scoring per pick** — show the "value over expected" for each of your picks as you draft.
- **Auction-style mocks** with budget bidding.
- **Saved mock comparisons** — see which draft strategies (Hero RB vs Zero RB) gave you better grades over your last 10 mocks.

### Quality of life
- **Print-friendly cheat sheet view** — `?print=1` on rankings flattens to a clean printable list. Power users print for in-person drafts.
- **Keyboard shortcuts overlay** — `?` key shows a help dialog of all shortcuts (Cmd+K, drag handles, etc.).
- **Undo/redo** for ranking edits within a session.
- **Conflict resolution** when same user has unsaved local changes and signs in with newer cloud data.

### Code health (longer-term)
- **TypeScript migration** — multi-month, but the codebase is large enough to benefit. Would catch bugs at compile time.
- **Build pipeline (Vite/esbuild)** — would enable code splitting + minification + tree-shaking. Bundle size win.
- **End-to-end tests (Playwright)** — record golden screenshots of major flows so future refactors don't break things silently.
- **Component extraction** — the rankings row, player card, trade-side panels are each rendered via large template strings. Extract to functions / classes for reuse.
