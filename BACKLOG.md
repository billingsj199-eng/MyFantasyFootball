# MyFantasyFootball — Backlog

_Last updated: 2026-08-28_

Running backlog for myfantasyfootball.co. Items are grouped by what's blocking them, then by effort. **Read DEPLOY_NOTES.md first** if any "Shipped" item below mentions Firestore rules — those features won't work in prod until rules are pushed.

---

## Shipped 2026-08-28 (chip sweep + fixes)

Five queued task chips resolved in one session — each struck in place where it lived (FPA SOS blend in Day-scale items, Playwright suite in Code health, SEO pack + the /p/-layer rescue in SEO/social, COMBINE↔ALL collision closure in next-session priorities; UD injury popover stays properly queued behind the store appeal in Awaiting external action). Plus one bugfix with no prior backlog line:

- **Sticky header gap/overlap after the view-options toggle** (e486061) — Jack's screenshot: table rows bled through a gap above the stuck stats bar. Root cause: the 08-27 declutter hides the sticky `.rnk-scoring-row` by toggling display on its PARENT (`#viewOptsWrap`), and **ResizeObserver never fires for ancestor-display changes**, so `_stickyFilterBar`'s measured offsets went stale in both directions (gap after collapsing, overlap after expanding). Fix: the sync is exported as `window._stickyFilterSync` and `_viewOptsApply` calls it on every toggle. Locked in by a new smoke test ("sticky header stack stays flush through the view-options toggle" — gap 0 collapsed, gap = scoring-row height expanded, gap 0 re-collapsed); suite now 10/10. Durable lesson for any future sticky-stack change: if an element in the measured stack can be hidden via an ancestor, the observer won't see it — resync explicitly at the toggle site.
- **Ops note (same session):** GitHub billing incidents can fail ONLY the deploy-pages step (all build steps green, 3 runs in a row) — retrigger commit-free via the workflow's `workflow_dispatch` endpoint using the token from `git credential fill`.

---

## Shipped 2026-08-27 (draft-week UI sweep — 12 features, one session)

All merged to main and deploy-verified on production the same day (commits `fbeb429`..`e6fb101`, app.js `?v=` walked 2026-08-26m → 2026-08-27g). Rankings-page focus, timed for the Labor Day draft weekend + Week 1.

### Draft-week wins
- **Print cheat sheet** — EXPORT ▸ PRINT SHEET: standalone 3-column printable doc from `getFiltered()` (mode/format/scoring/position/TOP-N carry over), tier section breaks, cross-off box per row, hidden-iframe print. Same premium cutoff + toasts as the CSV export. Works with the ★ watchlist filter on = print your watchlist.
- **Data-freshness line** (`#dataFreshness`, under the stats bar) — "⟳ ADP today 9:00am · Lines today · Projections today 9:00am" from ud_adp_history `updated`, newest `asOf` in BETTING_2026, `WEEKLY_PROJ.updated`.
- **In-season strip** (`#seasonStrip`, top of rankings) — current week + kickoff countdown (ticks each minute), "Games in progress" Thu–Mon, rolls to next week Tuesday 09:00 UTC, WEEKLY RANKINGS jump button gated on `#weeklyModeTab` visibility. ⚠️ `_SEASON_KICKS_2026` in app.js is a hardcoded 18-week kickoff table (DST flip W9, Thanksgiving W12, W18 Sunday finale) — **regenerate for the 2027 season**. Test hook: `window._seasonStripNow`.

### Rankings-table features
- **ADP-trend sparklines** — 40×12 inline SVG in the ADP cell: last ~15 daily Underdog BBM snapshots (same ud_adp_history.json the MOVERS ticker fetches). Risers slope UP green, fallers red, |Δ|<2 gray; hidden ≤600px; tooltip labels the source (always Underdog regardless of selected ADP column).
- **Watchlist** — ☆ star per row (hover-reveal desktop / faint-always touch) + ★ pill by the position filters (ANDs with position filter, skips TOP-N, auto-exits when emptied). localStorage `mff_watchlist`.
- **Watchlist cloud sync** — `users/{uid}/data/watchlist` (existing per-user rules — NO rules deploy needed). Newer-side-wins reconcile (`mff_watchlist_at` vs doc `updatedAt`); a different account's existing cloud list beats device leftovers (`mff_watchlist_uid`); full-array `set()` debounced 1.5s. Reconcile verified against a stubbed Firestore — **Jack action: real two-device round-trip while signed in**.
- **Saved view presets** — MORE ▸ SAVE VIEW snapshots board/format/scoring/stats/position/ADP-source/TOP-N as named chips above the stats bar (localStorage `mff_view_presets`, cap 8). Applies by clicking the real control buttons so every gate still runs; ADP source applied last. Chip row renders only when presets exist.
- **Tier bands** — 3px left-edge stripe per row in its tier's color (`tierband-<letter>` class, gated on `showTiers` so it vanishes on sort/search). Desktop only; mobile cards already tier-color the rank chip.

### Layout / navigation
- **Control-bar declutter** — SCORING / STATS / ADP-source rows collapse behind one ⚙ toggle (default collapsed, persists in `mff_view_opts_open`); live summary beside it tints accent when off-default, so collapsed ≠ hidden state.
- **Mobile bottom nav** — fixed 4-tab bar ≤600px (Rankings / My Teams / Trade / Mock) with safe-area padding; taps click the real `.nav-btn`s, `switchPage` syncs the bar via `_syncBottomNav`; hidden in embed mode. **Jack action: real-iOS thumb-through still recommended.**

### Performance
- **Boot skeleton rows** — 10 static shimmer rows in `#tbody` (pure CSS, theme tokens, reduced-motion respected) replaced by the first render; no more blank table during the boot chain.
- **Progressive table rendering** — viewers get the first ~120 rows painted synchronously (~28ms measured live vs ~300ms for all 502), tail appended next tick with the cell-visibility pass re-run (`window._applyCellVisibility`); `_renderSeq` guards racing renders. **Editors keep the full synchronous render** (drag rect-caching + keyboard-reorder re-grab assume all rows exist).

### Small pieces
- **Shortcuts help completed** — the `?` overlay's KEYBOARD SHORTCUTS section (already existed, with `g <letter>` nav) gained the drag-handle reorder keys and the player-card ←/→ pin cycling.
- **ADP MOVERS share button** — Web Share sheet on mobile / clipboard elsewhere; text lists the rendered movers with arrows + % moves.
- **Preload gotcha fixed twice** — app.js AND styles/main.css each appear in index.html as a `<link rel="preload">` (~lines 64–69) **plus** the real tag: any `?v=` bump must hit both or the preload double-fetches the old URL.
- **Private player notes** (4267d68) — MY NOTES on the player card (collapsed when empty, autosave textarea). localStorage `mff_player_notes` + Firestore `users/{uid}/data/player_notes`; PER-NOTE newer-wins merge, empty-text tombstones for deletes (60d prune), account-switch takes cloud wholesale. Same Jack two-device check as the watchlist.

### Injury system (evening additions — 611bd9b, 551214c, 9519209)
- **Clickable injury detail popover** — tapping a Q/D/O/IR/PUP/SUS pill opens an anchored popover: full status word, injury (body part), start date + full Sleeper note, an outlook line derived from the tag, the injury model's projection discount, the newest camp-news line for the player, and the feed's refresh date. Toggle / outside-click / Esc / scroll close it. Shared entry points: `_injShowDetail(d, pillEl)` and `_injPillByName(name)` (wraps the pill with a `data-injname` hook), plus a document-level delegate scoped to `.trade-player-chip` / `[data-injname]`.
- **Coverage: every player surface** — rankings table (all formats incl. WEEKLY — same tbody), Mock Draft available list (both standard + rookie row templates), Trade Calc side chips, My Teams rosters (by-position rows, lineup starters, bench — name-keyed via `_injPillByName`, unresolvable names silently skip like headshots). Card-header pills and the popover's own header pill deliberately keep plain tooltips.
- **Pipeline enrichment** — `pull_injuries.py` now emits a parallel `detail` map (Sleeper `injury_start_date` + full `injury_notes`, 200-char cap) alongside the untouched name→tag `players` map; regenerated same day (225 injured, 32 with notes). Rides the daily 9am job from here.
- **August tags un-hidden** — `_isOffseasonNow()` window shortened Feb–Aug → Feb–Jul: camp Q/O tags are live daily-refreshed feed data behind the 8-day staleness guard and are exactly what draft-season users need. Rankings went from long-term-only pills to ~97 visible statuses. (The old window predates the automated feed — it was guarding against stale hand-set tags.)
- **Extensions too** (`extensions-backup` 581fb72) — Sleeper 0.29.12 / ESPN 0.20.13 / Yahoo 0.9.9: injury chips clickable everywhere they render, and ADDED to draft rec rows (Sleeper draft recs + injury fetch in draft mode; ESPN draft/value/rookie recs + fetch in `initForLeague`; Yahoo season rows via `snBadges`). Popover detail (status, roster designation, body part, start date, note) comes from the Sleeper `/players/nfl` dump the helpers already fetch — zero new network cost; slMeta cache keys bumped so old maps refresh; chips without a Sleeper id stay plain (never wrong-player detail). Sleeper verified end-to-end in mock.html against the live dump; ESPN/Yahoo mocks boot clean with chips rendering. **NOT store-submitted** — 0.29.7/0.20.8/0.9.5 still in review from 08-25; these builds supersede whenever Jack next uploads. **UD helper skipped**: no Sleeper plumbing (would need a new `api.sleeper.app` host permission), store uploads frozen pending the 0.17.7 appeal, and Underdog's room shows designations natively — revisit after the appeal clears. Flow gotcha: the shared `.git/info/exclude` `/*` whitelist blocks even tracked-file staging in the backup worktree — `git add -f <exact files>` is required.
- **Sleeper season-mode harness coverage** (`extensions-backup` d85a71c, Sleeper 0.29.13) — the draft mock.html ALREADY doubles as a season harness (api shim serves canned league L1: users/rosters/matchups/traded picks/actuals — don't rebuild it); its two injured fixtures (Puka Q, Gibbs OUT) gained full detail fields (body part / start date / note), giving the season-mode injury popover direct regression coverage. Verified in-harness: LINEUP chips clickable, full popover cards, toggle + Esc close. Harness-only change — 0.29.13 ≡ 0.29.12 in shipped behavior. Harness entry recipe after a storage clear: SEASON toggle → SETTINGS → username `jack` → FIND → pick team `jack`.
- **ESPN + Yahoo mock injury fixtures** (`extensions-backup` d7725f2 — ESPN 0.20.14, Yahoo 0.9.10) — Sleeper-parity harness coverage: ESPN's mock_season.html roster builder records its sabotaged starters' sids and attaches full slMeta detail (clickable chips verified on Jordan Mason OUT + Ricky Pearsall Q); Yahoo's mock.html name-resolves its scraped-status fixtures (Michael Wilson Q + Jonah Coleman O, both in the players export) with detail. All four popover cards + toggle/Esc verified. Harness-only — 0.20.14 ≡ 0.20.13, 0.9.10 ≡ 0.9.9 in shipped behavior. All three helper harnesses now regression-cover the injury popover.

---

## Shipped 2026-08-13 (single-session sweep)

Everything below went from "sitting unmerged/broken" to live on production in one day.

### Merged + deployed (four worktree branches)
- **Yahoo direct league import** (a4aa346) — paste league URL/ID on My Teams, browser-direct via the `yahooProxy` Cloud Function (deployed + backed up 4bf7baf on functions-backup). Live smoke test: Jack's league 1301476 imported 10 teams, ½ PPR detected from the API.
- **Draft Strategy page** (14553ce) — `#draftstrategy`, nav "STRATEGY": written guide + 6-season ESPN ADP value tables. Prose lives in app.js next to the numbers by design.
- **Research page** (e8893b8, admin-only) — `#research` ADP-vs-outcome explorer (4,820 player-seasons 1999-2025) + player lookup + OTC contracts. Merge had real conflicts (pageMap union, two modules sharing one trailing `})();` — draft-strategy IIFE re-closed explicitly). Also fixed the non-admin blank-'home' redirect (falls back to rankings).
- **K/DST Playoff SOS** (3fded38) — `POSITION_SIGNAL_MIX` (K 1:3 def:tot, DST 1:2), DST matchup axis = opposing offense, DST implied-total **baseline-relative** via `_mtOppImpliedBaselines` (the raw-number bug Jack caught 2026-08-04). Also landed the weekly-only-columns sort fix + 2 D/ST research scripts. Verified: skill ranks byte-identical to prior live; K distinct from WR (8/10 teams); DST independent (NE DST#4 vs K#25).

### Chrome Web Store
- ESPN Helper **0.20.7** + Yahoo Helper **0.9.4** uploaded + submitted for review via `store_upload.py` API (store was at 0.19.3/0.8.3). `jackSlice:36` verified in both zips — no premium-board leak. Sleeper 0.29.6 confirmed already published (same-version re-upload rejected = review passed). Underdog untouched (appeal freeze). extensions-backup pushed (a5ff886 + 4c6cb6d).

### Rankings save-path hardening (65af1c2 + 59aeb33)
- **Blind-save guard**: pre-save read failure now requires explicit confirm instead of silently skipping the safety check — the exact chain behind the 2026-08-07 wipe.
- **Post-save server verify** on BOTH jacks + user save paths (`get({source:'server'})`, warn toast on mismatch) — catches offline-masked/rules-rejected writes (user saves were silently broken ~3 months once).
- `rankings_history` backup failure now toasts. Backup confirmed ALIVE (92 docs — started working with the 2026-08-11 rules deploy; the "rules missing" note was stale).

### Injury feed — live for the first time ever (ddb2295)
- Old Firestore design was triply dead (parse-time bail, no site_data rules, writer was console-paste code). Replaced with `scripts/pull_injuries.py` → `data/injury_updates.js` (Sleeper, QB/RB/WR/TE/K + healthy-cleared list), running as **Phase I of the 9am daily job**. app.js merge: suffix-tolerant names, never overwrites hand-set tags, 8-day staleness guard (dead job fails safe). 86 tags applied at ship; offseason filter correctly shows long-term only (Aiyuk ACL) until September.

### Bug fixes + data
- **`?embed=trivia` fixed** (1cb60a3) — embed mode exempted from the trivia admin gate; builder stays admin-only.
- **Mario Bates 1994-1998 backfilled** (b725fb6) — wiki-sourced, totals verified vs official career line; legend_careers only (all_players is nflverse-regenerated).
- **QB rushing backfill** (c47a6ca) — 135 seasons / 29 QBs adopted from all_players (2%-passing collision guard, suffix fallback, d.js for 2025). Lamar 2019 = 1,206 ry in trivia/compare at last. Residual: ~1,129 pre-1999 zero-rush seasons (needs PFR; Young/Cunningham/Elway already clean).
- **Kyle Williams COMBINE_DATA** — verified already fixed by `combine_d_patches.js` (memory was stale).

### Old top-3 backlog priorities — ALL closed
- **Cloud-sync completion** (18edcb0) — audit found the stragglers: FG college highscores, 10 unlimited Guess-Who era counters, fg_scoring/mff_sosRange/mt_value_src prefs; triggers added at set-sites. My Teams leagues were already cloud-native.
- **Mobile pass** (656007b) — full 375px sweep; ONE real bug: the new Strategy tab pushed GAMES off the bottom bar (fixed: tabs flex:1, 40px floor, 44px+ touch height, desktop untouched). Compare/Trade/modal/all pages verified clean. **Jack: real-iPhone thumb-through still worthwhile.**
- ESPN import had shipped 2026-08-10.

### Awaiting external action
- Jack's Season Pass checkout click-test (site side verified live; Stripe session opening is the only unverified step).
- ESPN 0.20.7 + Yahoo 0.9.4 store reviews (keep jdhpsports@gmail.com premium).
- Real-device iOS pass (emulated Chrome only).
- **UD helper injury popover — QUEUED behind the 0.17.7 store appeal** (agreed 2026-08-27). When the appeal clears: port the Sleeper-0.29.12 pattern (`fetchInjuries` slMeta capture w/ ib/idt/inx + `injTagHTML` chips on rec rows + `showInjPopover` appended to host body — reference implementation in `sleeper-extension/sidebar.js`). UD-specific work: the helper has NO Sleeper API plumbing today, so manifest.json needs a new `https://api.sleeper.app/*` host permission (expect extra store scrutiny — ship it WITH the next feature release, not alone), and UD rec rows render from `sidebar.js`/`content.js` name-based templates, so matching is name→sid via the players.json export (sids are in the shared export). Bump manifest version; commit to extensions-backup (`git add -f` exact paths).

---

## Suggested next-session priorities

**Shipped 2026-07-20/22 (was #1 here):** the ~26 MB deferred-data lazy-load is DONE. `legend_careers.js` + `all_players.js` + `hp.js` load via `window._loadRetiredData()`, `weekly_stats_active/retired_1-3` + `all_players_weekly_1-5` + `snap_counts.js` via `window._loadWeeklyData()` — both kicked off at idle after `load` (staggered one file per idle window) and forced on-demand by the surfaces that read them (openPlayerCard, Games/Compare navigation). Merges re-run on `mff:retireddata` / `mff:weeklydata` events. See index.html ~line 4774.

**Shipped 2026-07-22 (draft-season quick wins):**
- **Bye weeks** — `scripts/pull_bye_weeks.py` (ESPN scoreboard API) → `data/bye_weeks.js` → `d.bye` stamped at boot → fills the Bye box in the player card's Playoff Schedule row (that box existed but always showed `—`). Per Jack: player card only, NO rankings column. Cross-checked against the hand-typed `BB_BYE_WEEKS_2026` table in app.js (~line 44264) — identical; that table is still its own copy inside the BBM sim closure.
- **PWA PNG icons** — `scripts/make_icons.py` (Pillow, redraws the manifest SVG logo) → `icons/icon-180/192/512.png`, registered in manifest.webmanifest. Chrome auto-install prompt criteria now met. The old `apple-touch-icon` was a data-URI SVG which iOS *ignores* — now a real 180px PNG.
- **GA4 analytics stub** — inert loader in index.html head; `switchPage()` in app.js sends SPA `page_view` events. ~~Jack action required~~ **DONE**: `MFF_GA_ID = 'G-EJSTRKFBXZ'` is live on prod — gtag loads and the dataLayer populates (verified 2026-08-31).

If picking the next thing to do, in order:

1. ~~**Activate analytics**~~ — DONE (verified live 2026-08-31: `G-EJSTRKFBXZ`, gtag firing). Real usage data is accumulating for future prioritization.
2. ~~**Dynasty JS Model**~~ — shipped 2026-07-22, then the whole JS Model moved OFF-SITE 2026-07-23 to `E:\MyFantasyFootball\js_model_site\` (see roadmap note below).
3. **Draft-season data hygiene sweep** — kickers + K projections DONE 2026-07-22:
   - ~~Stale kickers~~ — Sleeper depth-chart audit (`scripts/fix_kickers_20260722.py`): added missing starters Tyler Bass (BUF, K13), Trey Smack (GB rookie, K18), Jason Sanders (NYJ, K21); existing editorial K order preserved (splice + renumber, NOT a p-sort — first attempt p-sorted and clobbered the board, reverted from `d.js.bak_pre_kickers_20260722`). Bass/Sanders have no 2025 stats (ESPN-confirmed didn't play) so their `p` values are hand-estimates; Clay's PDF independently confirms Bass as BUF K1.
   - ~~K Clay projections~~ — `extract_clay_projections.py` now parses the per-team kicker row (FGM/FGA/XPM/XPA; pts = 3×FGM+XPM, no distance-bonus data) → 32 K entries in `mike_clay_projections.js`; `adjProjPpg()` prefers Clay for K with `d.p/17` fallback. DST stays on `d.p/17` — the PDF has only a unit rank, no DST points.
   - ~~151 COMBINE↔ALL name collisions~~ — CLOSED 2026-08-28 (3ce7a37): only 2 were active-facing (whole-entry identity collisions in all_players, renamed to suffixed keys via new re-runnable `scripts/fix_combine_all_collisions.py`); the ~80 reverse-direction cases (retired player sharing a name with a newer combine athlete) were already `_getValidCB`-guarded on the Athletic Profile, and the two remaining raw-lookup card leaks (header `_cbRow`, JM badge on retired players) are now guarded too. Still open: MIA rank order (Patterson K17 above Gonzalez K31) contradicts Sleeper's current depth chart (Gonzalez is the listed starter) — Jack call, since it's an editorial board.
4. ~~**Fix the injury/roster Firestore feed**~~ — DONE 2026-08-13 (see Shipped section: static-file rebuild, daily Phase I, staleness guard).
5. **Weekly format completion → public launch by Week 1** — see "Weekly format expansion" below. Weekly props + board sync landed 2026-07-21/22; remaining: true weekly projections (consensus blend), weekly player-card tab, K/DST support, un-gate `_weeklyAdminCheck`.
6. ~~**Phone-test mobile responsiveness**~~ — emulated 375px sweep DONE 2026-08-13 (nav-tab overflow fixed; all pages clean). Real-iOS thumb-through by Jack still recommended.
7. ~~**ADP movement tracking**~~ — SHIPPED 2026-08-13 (4a1a909): ADP MOVERS card on the rankings page, top-6 BBM risers/fallers vs the snapshot ~7 days back, computed client-side from `data/ud_adp_history.json` (Phase F snapshots, accumulating since 2026-07-26). Rows open the player card; collapsible; hidden gracefully with <2 snapshot days. Share button shipped 2026-08-27 (Web Share / clipboard); OG image still future (pairs with "smart alerts").
8. ~~**ESPN league import**~~ — SHIPPED 2026-08-10 (direct in-site sync for public leagues + extension for private). Yahoo direct import followed 2026-08-13.

Still open, lower urgency: per-year top-25 trivia sweep (452-slug seed list); light-mode inline-color audit (only when a new broken element is spotted).

**New Jack-only checks from the 2026-08-27 sweep:** (a) watchlist cloud sync — star a player while signed in on one device, reload signed in on another, confirm it appears (client logic verified against a stubbed Firestore only); (b) mobile bottom nav — real-iOS thumb-through (emulated 375px verified, joins the standing real-device check from item 6); (c) January reminder — regenerate `_SEASON_KICKS_2026` in app.js for the 2027 season or the in-season strip stays dark after Week 18.

---

## JS Model roadmap (overhaul shipped 2026-07-21)

> **MOVED OFF-SITE 2026-07-23**: the JS Model was removed from the deployed app
> and now lives as its own local-only site at `E:\MyFantasyFootball\js_model_site\`
> (engine.js + shims + minimal UI; generator/backtest scripts moved there too,
> reading shared data from this repo's `data/`). Everything below is history of
> the on-site era.

Shipped this session (commits `becd845`..`c705e52`): backtest harness (`scripts/backtest_js_model.py`, 2018-2025), 50/30/20 × games-played recency-weighted base rates via committed generator (`scripts/generate_js_model_data.py`), QB age-curve removed, experience curves (young jump / production-tiered vet fade), Vegas team context from `BETTING_2026.gameTotals`, vacated targets/carries from roster diffs, market slot-curve allocation (within-position order = model, cross-position mix = Underdog ADP), Clay games-played blend + 85% Clay cap for low-info cores, betting-props third ensemble leg (20% wt), devy draft-capital fix, positional tiers. Historical Clay projections (2019-2025) parsed from ESPN draft-kit CDN PDFs (`scripts/parse_clay_history.py` → `data/clay_history.json`, gitignored — regenerate locally): **full model beats Clay alone at every position** (MAE QB 3.07 vs 3.36, RB 2.25/2.26, WR 2.03/2.14, TE 1.42/1.44).

Remaining, in rough priority order:

1. ~~**Dynasty JS Model**~~ — SHIPPED 2026-07-22. `V = Σ PPG(Y+k) × 0.85^k`, H=4, chaining age-curve ratios (non-QB, clamped to the curve's 23-41 range) + compounded per-year experience jump/fade factors off the full one-year projection. Backtested first (`scripts/backtest_dynasty_model.py`, 2018-2023, truth = realized 3yr fpts/17 discounted @0.85, pool = base≥6 PPG w/ nflverse-roster birth years): chained model beats the one-year board at every position (Spearman QB +.004 / RB +.011 / WR +.010 / TE +.009); the no-exp-chain variant LOSES to one-year everywhere, so the compounding carries the signal. γ/H grids are flat — 0.85/H4 chosen as the agreed design default. Age-conditional diagnostic (realized 3yr value ÷ flat projection): WR decays monotonically .68→.41 by age, RB cliffs at 26-27, QB is age-flat with a big ≤23 breakout premium, **TE INVERTS (old TEs hold value better, .50→.66)** — remember this if TE dynasty ranks ever look off. Implementation: `_jsComputeBoard(boardMode)` is pure now (returns {board, stats}); `_jsRebuild` computes base + dyn1qb + dynsf boards, fills `versionBoards.jsmodel.dynasty/dynastysf` (trade calc + cards see real dynasty orders), stamps display stats from the rendered board; KTC_1QB/KTC_SF replace UD ADP as the cross-position slot anchor for dynasty; dynsf forces SFLEX roster (8 QBs in top 24, Allen #2). New DYNASTY / DYNASTY SF buttons in the JS Model format selector. Verified: CMC RB3→RB5, Henry RB9→RB14, Achane RB6→RB3, young WRs rise; Evans WR36→WR27 is intentional (elite-vet WR fade is mild, -3.9% measured).
2. **Rookie template calibration** — templates + boosts are the only major hand-made component. Fit year-1 PPG by draft round × position × JM score from BACKTEST_OUTCOMES + weekly stats.
3. **Context-normalized historical rates** — project target/carry *share* × new-team volume instead of raw per-game production (the Mike Evans "solid despite bad offense/target competition" class of cases). Core redesign; backtest first.
4. **Games-played / availability model** — projected GP is still weighted historical GP (+ Clay blend). INJURY_HISTORY could support a real availability projection (age × position × injury count).
5. **January 2027: score the 2026 board vs actuals** — harness is ready (includes `clay`/`full` models). Also tag the repo at season start so the exact deployed model is easy to retrieve. Props weight (20%) is the one unvalidated number — an archived props season or two makes it backtestable (git history of `betting_lines_2026.js` already preserves the data).

---

## Weekly format expansion (scoped 2026-05-18, foundation shipped)

The WEEKLY format tab + admin week selector + OPP column landed 2026-05-18 (admin-only at launch — see [index.html](index.html) `_weeklyAdminCheck`, `_weeklyOppFor`, `body.format-weekly` CSS). Roadmap before going live to all users:

1. ~~**TEAM TOTAL data wiring**~~ — DONE (predates 2026-08): `_weeklyTeamTotalFor` derives implied totals from the betting-lines game data (total ± spread) / 2; `_weeklyOppTeamTotalFor` mirrors it for D/ST rows.
2. **Weekly yards + TD odds columns** — DK player props (Anytime TD, O/U receiving/rushing/passing yards) per player per week. Add as 2-3 additional columns visible only in WEEKLY format. Same `weekly-only-col` / `.weekly-only-cell` CSS hooks already in place — just add `<th>` + cells and a helper like `window._weeklyPropFor(playerName, propKind)`. Decide: one combined "Odds" column with hover-popover, or separate Yds + TD columns. Data source TBD — DK API or scrape.
3. ~~**Weekly tab on player cards**~~ — SHIPPED 2026-08-13 (71e1438): WEEKLY tab (skill positions) with Week-N matchup (OPP/spread/implied totals/O/U + position-weighted E/M/H rating + opp Clay units + PA/gm), the PROJ number **with its source labeled** (props / Sleeper consensus / heuristic / DST — `_weeklyAdjustPpg` out-param), Sleeper + season references, and a Recent Games section that self-activates in-season. Default tab in WEEKLY format. Prop-line detail deliberately stays on the LINES tab.
4. **K and D/ST weekly support** — OPP/SPREAD/TEAM TOTAL columns SHIPPED for K + DST 2026-07-22 (guards dropped in the row template). K rows show their own implied total (high = green, no opp-difficulty color — FG volume vs. opposing D quality cuts both ways). DST rows show the OPPONENT's implied total with the color scale inverted (low = green, tooltip explains) via new `_weeklyOppTeamTotalFor`, and opp-difficulty graded on the opponent's Clay OFFENSE rank (`_weeklyOppDifficulty(team, pos)`). Still open: K FG/XP odds or points O/U props; DST sacks/INTs/defensive props.
5. ~~**Weekly PROJ value**~~ — DONE in layers: props-first scoring 2026-07-22 (fc8cf4e, books primary), DST branch + in-season decay 2026-07-28, and **Sleeper consensus projections 2026-08-13 (bfd42ba)** as the fallback for board-less players (data/weekly_projections.js, daily Phase J). The old position-blind heuristic survives only as the last resort for players in neither source.
6. **Hand-authored "Jack's Week N" rankings** — if you want the WEEKLY row order to differ from season rankings, need a separate storage path. Suggested: `rankings/jacks-weekly-{N}` in Firestore. Currently WEEKLY falls through to redraft-mode ranks (because `currentMode === 'weekly'` doesn't match any of the `dynasty*/superflex` checks in `[adp|sl]For()` helpers around index.html:6084).
7. ~~**Public launch** (flip `_weeklyAdminCheck`)~~ — SUPERSEDED by the shipped publish system: `_weeklyAdminCheck` is a PUBLISH gate, not an admin switch. Admin always sees the tab + week selector; non-admins see the tab only while a week is published (`settings/active_week.publishedWeek`, set by the admin PUBLISH button) and are hard-locked to that single week ("LIVE — WEEK N" chip, no selector; un-publish bounces them out and hides the tab). Launch = click PUBLISH on Week 1 when ready — no code change. Items 1-5 (data) all shipped as of 2026-08-13.

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
- **sitemap.xml** — same build script writes `sitemap.xml` at the project root listing the homepage + all 580 player pages so Google Search Console picks them up. Submit the URL `https://www.myfantasyfootball.co/sitemap.xml` in GSC once deployed.
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

- ~~**Bye week column**~~ — _Shipped 2026-07-22 as a player-card field instead (Jack: no rankings column). `scripts/pull_bye_weeks.py` → `data/bye_weeks.js`._
- ~~**Performance: virtualize the rankings table**~~ — _mostly superseded 2026-08-27: progressive rendering paints the first ~120 rows sync (viewers) and appends the tail next tick, plus boot skeleton rows. True windowed virtualization only worth revisiting if scroll-perf complaints surface._
- ~~**Analytics on tool usage**~~ — _GA4 stub shipped 2026-07-22; needs Jack to create the property + paste the measurement ID (see priorities above)._
- **Inline-style color audit for light mode** — ~30 places in `index.html` use hardcoded hex/rgba colors that don't follow the dark→light flip. Each is small; do them as you spot broken elements in light mode.
- ~~**Sticky first column on the rankings table**~~ — _Shipped 2026-05-06._

### Day-scale items

- ~~**In-season SOS: swap defensive priors for observed FPA-by-position**~~ _(Jack, 2026-07-24)_ — **SHIPPED 2026-08-27 (8e3beba)**, built preseason so it self-activates as 2026 games land. `_mtObservedFpa()` builds per-team FPA to QB/RB/WR/TE from `WEEKLY_STATS_ACTIVE` 2026 rows; blended at `_mtMatchupZ` (the single choke point both the season-window AND weekly SOS builders flow through) over the preseason priors with Jack's exact ramp (W1 0% → W5+ 100%, priors then fully dropped). Vegas layer untouched; DST untouched (its matchup is the opposing offense); K rides an OVERALL map (mean of the 4 position z's); 24+ teams-per-position gate before z-scoring; `mff:weeklydata` clears FPA + both SOS caches. Verified: preseason byte-identical (share 0 live), synthetic W3 harness moved WR-generous DEN's opponents to easiest ranks and stingy PHI's to hardest, W5 full-replacement clean. `window._mtObservedFpa()` in the console shows live state. Still open from the spec: light schedule-adjustment on early FPA (deliberately skipped for v1 — the 24-team gate + ramp keep early noise bounded); revisit only if W2-3 SOS looks skewed by who-faced-whom.

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
- ~~**10 backup kickers in d.js**~~ — **DONE 2026-08-31** (`scripts/fix_kickers_20260831.py`, splice+renumber, no p-sort). Teams were already fixed by the daily roster sync (Phase H); the audit against Sleeper post-cutdown depth charts found 8 of the 10 genuinely FA/backup (left in place: Romo/Badgley/Havrisik/Wright/Karty/Gano/McAtamney FA, Sauls NYG backup) and 2 now STARTERS who got promoted: Shrader IND K36→K26 (swapped slots+p with Grupe, now the IND backup, K24→K38) and Gay LV K32→K24. Also promoted two starters found buried during the audit: Zvada NYG K46→K33 (p null→99.9, null broke the d.p/17 fallback) and Stevens WAS K47→K14.
- ~~**`mike_clay_projections.js` has zero K and zero DST entries**~~ — **STALE, closed 2026-08-31**: this bullet predated the 2026-07-22 extractor fix (see "Draft-season data hygiene sweep" above). The file carries 32 K entries, auto-refreshed by the daily job (verified 08-31: guide updated post-cutdown, all 32 current Sleeper starters present by name incl. Shrader/Zvada/Stevens/Gay, and Clay lists Patterson as the MIA K). Zero DST remains **by design** — the Clay PDF has only unit ranks, no DST points, so DST stays on `d.p/17`.

### Behavioral choices needing your call
- ~~**MIA kicker order (Patterson vs Gonzalez)**~~ — **CLOSED 2026-08-31, Jack approved Patterson.** The old question resolved itself at cutdowns: ESPN depth chart, Sleeper, and Clay's guide all list Riley Patterson as the MIA starter; Zane Gonzalez is teamless/Inactive (absent from Clay entirely). Patterson stays K18, Gonzalez K34 among the buried FA vets. No board change needed.
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
- ~~**Improve OG image coverage**~~ — _Done 2026-08-28 (41ba587): build_player_og_pages.py now also reads BAKED_ESPN_IDS (data/headshot_espn_ids.js) — image cards 102 → 453 of 585 pages. **Same commit SHIPPED the entire /p/ + sitemap + robots layer for the first time — it had 404'd on prod since May** (the .git/info/exclude `/*` whitelist silently blocked the adds; 4th occurrence of the check-ignore-first gotcha) while the player-card SHARE button copied /p/ links. All 200 + verified live._
- **OG image generator** — an SVG → PNG image showing "Bijan Robinson · RB1 · Atlanta Falcons" for embedding when shared. Cloud Function that renders on demand and caches.
- ~~**sitemap.xml** for the player-profile URLs~~ — _Live 2026-08-28 (41ba587, existed locally since May): 587 URLs incl. /movers.html (daily changefreq), XML-validated, robots.txt Sitemap line. **Jack action: register https://www.myfantasyfootball.co/sitemap.xml in Google Search Console.**_

### PWA / install
- ~~**Add to Home Screen / PWA**~~ — _Shipped 2026-05-06; PNG icons (192/512 + 180 apple-touch) shipped 2026-07-22 via `scripts/make_icons.py`, so Chrome's auto install prompt criteria are met._
- **iOS pull-to-refresh** + native-feeling viewport behavior on mobile.

### Power user / admin tools
- **Bulk paste import** for My Rankings — paste a list of player names (Twitter cheat sheet, copied from a forum post, etc.) and auto-add them to your rankings in order.
- ~~**Custom notes per player**~~ — _Shipped 2026-08-27 (4267d68): MY NOTES section on the player card (collapsed when empty, autosave textarea). localStorage `mff_player_notes` + Firestore `users/{uid}/data/player_notes` (existing rules); PER-NOTE newer-wins merge with empty-text tombstones for deletes (pruned after 60d); account-switch takes cloud wholesale. Merge verified vs stubbed Firestore — same Jack two-device check as the watchlist applies._
- ~~**Watchlist**~~ — _Shipped 2026-08-27: row stars + ★ filter pill + Firestore sync (users/{uid}/data/watchlist)._
- ~~**Saved filter presets**~~ — _Shipped 2026-08-27 as view presets (MORE ▸ SAVE VIEW; chips above the stats bar)._
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
- ~~**Print-friendly cheat sheet view**~~ — _Shipped 2026-08-27 as EXPORT ▸ PRINT SHEET (no URL param; tier breaks + cross-off boxes)._
- ~~**Keyboard shortcuts overlay**~~ — _Already existed (`?` help overlay + `g <letter>` nav); completed 2026-08-27 with the drag-handle and card-pin rows._
- **Undo/redo** for ranking edits within a session.
- **Conflict resolution** when same user has unsaved local changes and signs in with newer cloud data.

### Code health (longer-term)
- **TypeScript migration** — multi-month, but the codebase is large enough to benefit. Would catch bugs at compile time.
- **Build pipeline (Vite/esbuild)** — would enable code splitting + minification + tree-shaking. Bundle size win.
- ~~**End-to-end tests (Playwright)**~~ — _Smoke suite shipped 2026-08-28 (610f88f): `tests/` — 9 rankings-page flows (progressive render/skeleton, filters+TOP-N, watchlist, presets round-trip, injury popover, print sheet w/ free-tier top-36 assert, view-options collapse, season-strip time-machine states, mobile bottom nav), 9/9 in ~29s. Run: `cd tests && npm i && npx playwright test`. Config blocks service workers (the SW-staleness gotcha) and serves whichever checkout the tests live in. **Fixture gotcha: pristine profiles trigger the first-visit tour and `#mffTourOverlay` swallows every click — the boot helper pre-seeds `mff_seen_intro=1`.** Golden SCREENSHOTS still unstarted — this is behavioral assertions only; add visual diffs later if wanted._
- **Component extraction** — the rankings row, player card, trade-side panels are each rendered via large template strings. Extract to functions / classes for reuse.
