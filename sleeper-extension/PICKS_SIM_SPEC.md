# Spec: Team-Aware Future-Pick Values in Sleeper Helper (v0.14.0)

Status: SHIPPED 2026-07-30 (v0.14.0) — implemented as specced; see README
"PICKS tab" section. Deviations from spec: PICKS tab is additionally gated to
dynasty/keeper leagues (`settings.type >= 1`); slMeta storage key bumped to
`sleeperHelper.slMeta3`; mock.html gained sim fixtures (full-season Vegas +
2 traded picks) so the harness runs the sim end-to-end.

## Goal

Season mode gets sim-driven values for 2027/2028 rookie picks, same math as Sim
Lab's Trade Analyzer (sim_lab/app.js `teamPickValue`): each pick is valued off
the ORIGINAL team's simmed finish distribution (draft order = inverse
standings), integrated over a slot-value curve through the KTC Early/Mid/Late
anchors. New **PICKS** tab in season mode: your inventory + a league-wide pick
board. A rebuilder's 1st should price above a contender's 1st automatically.

## Why the extension (not the site)

- Privacy: `sleeper-extension/` is local-only — `.git/info/exclude` whitelists
  site files, so the engine never reaches the public repo. (The three data
  inputs below are already public site files — no privacy delta there.)
- League context (rosters/users/matchups/records) is already loaded in season mode.
- Zero server cost: GitHub Pages is static; sims run in the browser. Only new
  network cost is ~14 cached Sleeper GETs per league per day.

## New files

1. **`engine_sim.js`** — verbatim copy of `E:\MyFantasyFootball\sim_lab\engine.js`.
   Source of truth stays sim_lab; add a copy step (export script or
   update_simlab.bat) so they can't drift. The engine already degrades
   gracefully when optional inputs are missing: no `SIM_2026` → jsMean
   collapses to Clay; no `SIM_SNAPS_2026` → snapMult 1; no team grades →
   defenseAdj 1; no overrides → auto-detected QB windows.
2. **`data/sim_pack.js`** — emitted by `export_sleeper_extension_data.py` (new
   section). Must declare bare top-level `var` globals exactly like the repo
   data files (the engine checks `typeof X !== 'undefined'`):
   - `MIKE_CLAY_PROJ` (from `data/mike_clay_projections.js`, verbatim — full
     stat components needed for league-scoring rescore)
   - `PLAYER_WEEKLY_SIGMA` (from `data/player_weekly_sigma.js`)
   - `CLAY_TEAM_GRADES_2026` (from `data/clay_team_grades_2026.js`)
   ~120 KB total, bundled (not fetched) so the tab works offline-ish.
3. **`data/sim_overrides.js`** (optional but cheap) — copy of
   `sim_lab/overrides.js` in the same copy step, so camp-news QB-room/injury
   tweaks flow through. Engine reads `window.QB_ROOM_OVERRIDES` /
   `window.INJURY_WINDOW_OVERRIDES`.

## Manifest

- `content_scripts.js` order: `data/playoff_sos_2026.js`, `data/sim_pack.js`,
  `data/sim_overrides.js`, `engine_sim.js`, `sidebar.js`.
  (All content scripts of one extension share the isolated world, so the
  engine sees the pack's globals.)
- Version 0.13.2 → **0.14.0**; bump on every later edit (house rule).

## Runtime wiring (sidebar.js)

- **Vegas**: the existing live fetch of `betting_lines_2026.json` additionally
  does `window.BETTING_2026 = res.data` before calling the ENGINE's
  `SimEngine.buildSchedule()` (it reads `window.BETTING_2026.gameTotals`).
  Keep the extension's own `buildSchedule()` untouched — other features use it.
- **`window.SIM_SLEEPER`**: synthesize from already-loaded players.json:
  `{ players: state.players.map(p => ({n: p.n, sid: p.sid, a: p.a, age: p.age,
  ktc1qb: p.ktc1qb, ktcSf: p.ktcSf})) }`. This is how the engine maps Clay
  names → Sleeper ids/age/KTC. No new export fields needed.
- **`window.SIM_SLEEPER_META`**: engine wants `{sid: {exp, inj, st}}` for TRUE
  rookie detection (`years_exp === 0`) + injury windows. `fetchInjuries()`
  already pulls `/players/nfl` on a 12h cache — extend the trimmed `slMeta`
  entries to keep `years_exp`, raw `injury_status`, raw `status`, and build the
  META map from it. (Bump the storage cache key, e.g. `slMeta` → v3, so stale
  cached maps without `exp` don't linger for 12h.)

## League sim inputs (new fetches)

- `/league/<lid>/matchups/<wk>` for weeks 1..(playoff_week_start−1) →
  `pairsByWeek` via matchup_id pairing (mirror sim_lab app.js). ~13 GETs,
  cached per league per calendar day in chrome.storage. Offseason/no matchups
  → port sim_lab's `roundRobin` fallback.
- `/league/<lid>/traded_picks` (1 GET) → pick inventory: every team starts
  with own 2027/2028 rd 1–4, traded_picks moves them, `orig` roster stays
  attached (it drives valuation). Mirror sim_lab logic verbatim.
- Already available: records (`roster.settings` w/l/fpts — sim only remaining
  weeks in-season), lineup slots (`roster_positions` minus BN/IR/TAXI),
  scoring (`SimEngine.scoringFromLeague(league.scoring_settings)`),
  playoffTeams/playoffStart (`league.settings`), team names (`userNames`).
- `teams[]` = `{rosterId, name, playerIds (players minus reserve/taxi),
  record}`. `unavailable` map from slMeta: IR/PUP/Sus-type status → `'ir'`;
  `injury_status` Out → `'out'` (current week, regular season only) — same
  rules as sim_lab.

## Sim run + cache

- Lazy: first open of the PICKS tab per league (not on league load).
- `SimEngine.buildPlayers(schedule)` once (cached), then
  `SimEngine.simLeague({sims: 1500, seed: 99, ...})` → keep only
  `placeCounts` per rosterId (mirrors sim_lab's `state.tradeFinish`).
- Cache `{leagueId, day, recordsHash → placeCounts}` in memory +
  chrome.storage; invalidate on record change or day roll.
- ~1–2 s runtime. Render "Running 1,500 season sims…" first, `setTimeout(0)`
  the sim so the status actually paints, then re-render.

## Valuation (port verbatim from sim_lab app.js:545–583)

- `pickAnchors(year, round, sf)` from `state.pickAssets` (players.json already
  carries all 36 picks with `ktc1qb` + `ktcSf`).
- `slotValue`: piecewise-linear through Early/Mid/Late anchors at slots
  2.5/6.5/10.5 scaled ×(n/12).
- `teamPickValue`: EV over the FULL placeCounts distribution, draft order =
  inverse standings (slot = n+1−place); 2028 picks blend 50% toward uniform;
  no finish data → anchor average.
- SF detection: lineupSlots contains `SUPER_FLEX` → ktcSf, else ktc1qb
  (Rville is 1QB).
- 2026 picks: generic tier values only (order already known).

## UI — season tab PICKS

Tab strip becomes LINEUP / WAIVERS / PICKS / SETTINGS.

1. **Your picks** — my inventory rows:
   `2027 1st via TeamX · 7,193 (+26% vs mid)` — the delta vs the Mid anchor
   makes the team-awareness premium/discount visible; sub-line shows the
   driving team's modal finish (`TeamX proj 11th (34%)`).
2. **League pick board** — one row per team sorted by expected finish: team,
   modal finish + %, value of their own 2027 1st / 2027 2nd / 2028 1st.
   Picks the orig team no longer owns get a `→ traded to Y` marker.
3. Footnote (mirror sim_lab's): draft order = inverse simmed standings over
   the whole distribution (collapse-tail convexity credit), 2028s regress 50%,
   assumes rest-of-season rosters as-is, players without Clay projection
   contribute 0.

## Failure modes

- Betting fetch failed / no schedule → skip sim, show generic tier values
  with a "no live lines — generic values" note.
- engine_sim.js or sim_pack.js missing (fresh clone) → hide the tab entirely.
- mock.html: graceful-degrade path is the requirement (tab hidden or
  generic values); full canned-league sim fixture is optional/v2.

## Out of scope (v2 candidates)

- Full trade ledger UI in the extension (Sim Lab already does before/after
  sims — don't duplicate at v1).
- Draft-mode integration (valuing pick assets during rookie drafts).
- ESPN extension port.

## Acceptance checks

- Rville (1QB): pick ordering matches Sim Lab Trade tab given same data
  vintage — SEX 2027 1st ≈ 7.2k > Hegel29 2027 1st ≈ 5.7k.
- A traded pick appears under its new owner with `via` + orig-team valuation,
  and is gone from the orig team's list.
- SF league flips to ktcSf anchors.
- Second tab open is instant (cache); record change re-sims.

## Effort

~60 lines export script, ~250–300 lines sidebar.js, manifest/README/version.
One session including verification against Sim Lab numbers.
