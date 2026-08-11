# Chrome Web Store — listing copy for all four MFF extensions

Dashboard: https://chrome.google.com/webstore/devconsole/
Prepared 2026-08-10. Upload zips are in this folder; rebuild them with the
session scratchpad `package_store.py` (or re-zip the extension dir minus
`mock*` / `*.md` / `*.bak*` / `*.tmp`) after any source change — the Store
requires each upload's `manifest.json` version to be HIGHER than the listed one.

Shared across all four listings:
- **Category:** Sports · **Language:** English (US)
- **Privacy policy URL:** `https://www.myfantasyfootball.co/privacy.html`
- **Remote code:** No (all JS is bundled; network calls fetch DATA only — JSON
  from the fantasy platform's own API, Sleeper's public API, and
  myfantasyfootball.co)
- **Premium gate (v0.27.0/0.18.0/0.7.0/0.16.x):** all four extensions require sign-in + Premium on myfantasyfootball.co (site bridge writes the auth state to extension storage; lock screen otherwise). Disclose in the detailed description (done below); monetization happens entirely on your own site, which Chrome Web Store policy allows.
- **Certifications:** check all three (no sale/transfer of user data, etc.)
- **Assets: DONE — in `screenshots/`** (captured 2026-08-10 via `shot.html`
  stage + headless Chrome, exact store sizes):
  - 1280×800 screenshots: `underdog-draft.png`, `sleeper-season.png` (live
    draft view), `espn-season.png`, `yahoo-draft.png` + `yahoo-season.png`
  - 440×280 promo tiles: `tile-underdog/sleeper/espn/yahoo.png`
  - Regenerate: serve the folder (`static` launch config) and run headless
    Chrome against `store_packages/shot.html?src=<harness>&panel=<sel>&...`
    (see the shot.html query params; `click=`/`drive=` advance the harness).

---

## 1. MFF Underdog Draft Helper — UPDATE existing listing (→ 0.17.1)

Upload: `mff-underdog-draft-helper-0.17.1.zip`

Paste-ready replacements for the existing listing (the old copy in
`underdog-extension/CHROME_STORE_SUBMISSION.md` references the dead `.org`
domain AND says the helper works "free without sign-in" — no longer true
since the premium gate).

**Detailed description (replaces the old one):**
```
The MFF Underdog Draft Helper is a Chrome extension that adds a live recommendation sidebar to your Underdog Fantasy drafts. Built for Best Ball Mania, it surfaces the best pick on your clock by combining Jack's rankings with a BBM advance-rate optimizer and statistical shrinkage so small-sample builds don't dominate.

WHAT IT SHOWS LIVE
• Best Player Available — value-weighted using Jack's rankings + Underdog ADP
• Stacking analysis — flags QB+pass-catcher pairings on your roster
• True-cliff milestones — get warned when a position is about to fall off
• Recency-weighted historical data — recent BBM seasons matter more
• Pick-by-rank-by-round priors so the tool understands draft context, not just BPA

HOW IT WORKS
The sidebar reads draft state from the Underdog page and matches it against rankings synced from your account at myfantasyfootball.co. All data stays on your computer in Chrome's local storage — nothing is transmitted to a third-party server.

REQUIREMENTS
A myfantasyfootball.co account with Premium is required — the helper unlocks automatically once you're signed in on the site. An active Underdog Fantasy account (the extension reads draft state from Underdog's own pages).

PRIVACY
Full privacy policy at https://www.myfantasyfootball.co/privacy.html. We don't collect, transmit, or share user data.

Not affiliated with Underdog Fantasy.
```

**Privacy policy URL:** `https://www.myfantasyfootball.co/privacy.html`

In the permission justifications, replace `myfantasyfootball.org` with
`myfantasyfootball.co` wherever it appears, and add to the host justification:

```
firestore.googleapis.com: the user's saved rankings on myfantasyfootball.co
are stored in Google Firestore; the extension reads the user's own boards
from it. betting-line/playoff-SOS data files are refreshed from
myfantasyfootball.co at startup. Read-only; no user data is written.
```

Since the last upload the extension gained: live Vegas playoff-SOS refresh,
JM prospect pills, the rec leapfrog guard and elite-QB/TE positional logic —
no new permissions, so mention in the "What's new" notes only if asked.

---

## 2. MFF Sleeper Helper — UPDATE existing listing (published 0.27.1 → 0.28.1)

Upload: `mff-sleeper-helper-0.28.1.zip`

**Short summary (130 chars, matches manifest):**
```
Draft + season helper for Sleeper leagues: live pick recs, optimal lineups, waiver upgrades, and roster values from Jack's boards.
```

**Detailed description:**
```
The MFF Sleeper Helper adds a live sidebar to sleeper.com fantasy football leagues.

DRAFT MODE
• Live pick recommendations on your clock — best player available blended with format-aware value-over-replacement, positional tiers and cliffs, roster needs, and ADP timing ("will he last to your next pick?")
• Understands your league's real settings: superflex, PPR scoring, roster slots
• Dynasty support with KTC market values and rookie-pick awareness

SEASON MODE
• Optimal weekly lineup from your league's exact lineup slots and scoring
• Start/sit verdicts with Vegas matchup context on Sleeper's own pages
• Waiver targets ranked by the points they'd actually add to YOUR lineup
• Roster values by source (Jack's boards, KTC, FantasyPros, Sleeper ranks)

HOW IT WORKS
Draft and league state come from Sleeper's public API — the extension never scrapes your credentials. Rankings come bundled and can sync with your account at myfantasyfootball.co. Everything is processed and stored locally in Chrome storage.

REQUIREMENTS
A myfantasyfootball.co account with Premium is required — the helper unlocks automatically once you're signed in on the site. Rankings and recommendations are powered by that account.

Not affiliated with Sleeper.
```

**Single purpose:**
```
Display draft-pick recommendations and lineup/waiver advice on Sleeper fantasy football pages, using rankings from myfantasyfootball.co.
```

**Permission justifications:**
- `storage` — persists draft state, panel position, cached rankings and league
  settings locally in chrome.storage.local; nothing is transmitted.
- `alarms` — schedules the periodic background refresh of league state during
  drafts/season polling.
- `notifications` — optional on-your-clock draft alerts.
- Host `sleeper.com` / `*.sleeper.com` — the pages the sidebar is injected into.
- Host `api.sleeper.app` — Sleeper's own public JSON API for league/draft/player
  state (read-only).
- Host `myfantasyfootball.co` + `firestore.googleapis.com` — refreshes the
  bundled rankings/Vegas data files and reads the user's own saved boards
  (Firestore is the site's database). Read-only.

**Data usage disclosure:** User activity = Yes (draft picks/lineups read from
Sleeper's API to power recommendations, stored locally only). Everything else No.

---

## 3. MFF ESPN Helper — UPDATE existing listing (published 0.18.1 → 0.19.1)

Upload: `mff-espn-helper-0.19.1.zip`

**Short summary (129 chars, matches manifest):**
```
Draft helper + season mode for ESPN leagues: live pick recs, optimal lineups, waiver upgrades, sims, and one-click league import.
```

**Detailed description:**
```
The MFF ESPN Helper adds a live sidebar to ESPN Fantasy Football.

DRAFT MODE
• Live pick recommendations in the ESPN draft room — best available blended with format-aware value-over-replacement, tiers, cliffs, roster needs, and ADP timing
• Reads your league's real scoring and lineup slots automatically
• Tracks every pick from the draft board — refresh-proof

SEASON MODE
• Optimal weekly lineup from your league's exact slots and scoring
• Start/sit pills and Vegas matchup context on ESPN's own roster pages
• Waiver targets ranked by the points they'd add to YOUR lineup
• SIMS tab: 1,500 Monte Carlo season simulations — projected standings, playoff and title odds, week-by-week win probabilities
• One-click league import to your myfantasyfootball.co account

HOW IT WORKS
League data comes from ESPN's own fantasy API for your logged-in account; public player data (byes, injuries, actuals) from Sleeper's public API. Rankings are bundled and can sync with myfantasyfootball.co. All processing is local.

REQUIREMENTS
A myfantasyfootball.co account with Premium is required — the helper unlocks automatically once you're signed in on the site. Rankings and recommendations are powered by that account.

Not affiliated with ESPN.
```

**Single purpose:**
```
Display draft-pick recommendations and lineup/waiver/season-sim advice on ESPN Fantasy Football pages, using rankings from myfantasyfootball.co.
```

**Permission justifications:**
- `storage` — local persistence of draft state, league cache, panel prefs.
- Host `fantasy.espn.com` — the pages the sidebar is injected into.
- Host `lm-api-reads.fantasy.espn.com` — ESPN's own league-read API for the
  user's logged-in league (rosters, settings, matchups). Read-only.
- Host `api.sleeper.app` — public NFL state/injury/actuals data.
- Host `myfantasyfootball.co` / `.org` / `billingsj199-eng.github.io` — data
  refresh + the league-import bridge to the user's own MFF account (the
  GitHub host serves the same site).
- **Data usage disclosure:** Website content = Yes (reads the ESPN draft board
  DOM to track picks; local only). User activity = Yes (league rosters/picks,
  local only). Authentication info = No (relies on the browser's own session;
  never reads or stores credentials).

---

## 4. MFF Yahoo Helper — UPDATE existing listing (published 0.7.1 → 0.8.1)

Upload: `mff-yahoo-helper-0.8.1.zip`

**Short summary (124 chars, matches manifest):**
```
Draft assistant + season helper for Yahoo leagues: live pick recs, optimal lineups, waivers, season sims, and league export.
```

**Detailed description:**
```
The MFF Yahoo Helper adds a live sidebar to Yahoo Fantasy Football.

DRAFT MODE
• Live pick recommendations in the Yahoo draft room — best available blended with format-aware value-over-replacement, tiers, cliffs, roster needs, and ADP timing
• Reads your league's real scoring and roster slots automatically (PPR, superflex, flex types)
• Tracks every pick live and rebuilds instantly after a refresh

SEASON MODE
• Optimal weekly lineup from your league's exact slots and scoring
• Start/sit moves, Vegas matchup context, and waiver targets ranked by the points they'd add to YOUR lineup
• SIMS tab: 1,500 Monte Carlo season simulations — projected standings, playoff and title odds, week-by-week win probabilities
• One-click league export to your myfantasyfootball.co account

HOW IT WORKS
League settings and players come from Yahoo's own fantasy API for your logged-in league; the pick feed passively listens to the draft room's own connection (nothing extra is opened). Public NFL data from Sleeper's public API. Rankings are bundled and sync with myfantasyfootball.co. All processing is local.

REQUIREMENTS
A myfantasyfootball.co account with Premium is required — the helper unlocks automatically once you're signed in on the site. Rankings and recommendations are powered by that account.

Not affiliated with Yahoo.
```

**Single purpose:**
```
Display draft-pick recommendations and lineup/waiver/season-sim advice on Yahoo Fantasy Football pages, using rankings from myfantasyfootball.co.
```

**Permission justifications:**
- `storage` — local persistence of draft state, league cache, panel prefs.
- Host `football.fantasysports.yahoo.com` — the pages the sidebar is injected
  into; also the origin whose league pages are read for rosters.
- Host `api.sleeper.app` — public NFL state/injury/actuals data.
- Host `myfantasyfootball.co` + `firestore.googleapis.com` — data refresh and
  the user's own saved boards (Firestore is the site's database); league
  export writes only to the user's own MFF account.
- **Data usage disclosure:** Website content = Yes (reads the user's Yahoo
  league pages to build rosters; local only). User activity = Yes (draft
  picks, local only). Authentication info = No (relies on the browser's own
  session cookies implicitly; never reads, stores, or transmits them).

---

## Upload order + notes

1. Underdog first (it's an update — fastest approval, no new permissions).
2. The three new listings can go in the same sitting; each needs its own
   screenshots + promo tile.
3. Visibility: pick **Unlisted** if you want install-by-link from the site
   only; Public if you want store search traffic. Can be changed later.
4. After approval, swap the site's extension modal links to
   `https://chromewebstore.google.com/detail/<EXTENSION-ID>` (see the
   "After publication" section of underdog-extension/CHROME_STORE_SUBMISSION.md).
5. KNOWN FOLLOW-UP (before going wide publicly): bundled `data/players.json`
   carries Jack's FULL board while the site gates free users at 36/12 — ship
   the free slice + premium Firestore fetch if that matters for conversion.
