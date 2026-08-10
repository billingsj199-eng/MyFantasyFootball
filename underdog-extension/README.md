# MFF Underdog Draft Helper

Chrome extension that surfaces live draft recommendations on Underdog using Jack's rankings as the input.

**Format:** Underdog Best Ball Mania (12 teams, 18 rounds, 1QB/2RB/3WR/1TE/1FLEX/12BN, half-PPR).

## Status: v0.1 (skeleton)

What works:
- Slim player export from `data/d.js` (411 players with rank, position, team, Underdog ADP)
- Recommendation engine (BPA + position need + ADP value + bye/stack hints + round priors)
- Floating sidebar UI (drag, collapse, hide)
- Manual pick logging (always-available fallback)
- Mock test harness for offline validation

What's stubbed pending real-draft inspection:
- WebSocket parser uses heuristics that haven't been validated against an actual Underdog draft frame. The interceptor logs every WS frame to console with `[MFF/WS]` prefix so we can refine the parser once we see a real one.
- "Mine vs other" detection — we need to identify the user's draft entry ID. Set `window.__mffMyEntryId = '<your-id>'` from the console for now (or use the manual buttons).

## How to load

1. Open `chrome://extensions`
2. Toggle "Developer mode" (top-right)
3. Click "Load unpacked"
4. Select this folder (`underdog-extension/`)
5. Pin the extension if you want easy access

The sidebar will appear automatically when you visit any `*.underdogfantasy.com` page.

## How to use

**For now (manual mode):**
1. On the draft page, the sidebar appears in the top-right
2. Click your draft slot (1–12) and "Start Tracking"
3. As picks happen, click any recommended player to log them:
   - If it's your turn, the click adds to YOUR roster
   - Otherwise it marks the player as drafted (someone else)
4. Use "Search a player..." to manually log picks not in the recommendation list
5. Use "Drafted (other)" / "Add to MY Roster" / "Undo Last" / "Reset Draft" as needed

**Once live mode works:**
- Picks should auto-flow from Underdog's WS into the sidebar — no manual logging needed.

## How to refine the live-mode parser

After loading the extension on a real draft:

1. Open Chrome DevTools → Console
2. You'll see `[MFF/WS] WebSocket wrapped...` on page load
3. Run: `window.__mffCaptureWS = true`
4. Make/observe one or more picks
5. Run: `copy(JSON.stringify(window.__mffCaptured.slice(-10), null, 2))`
6. Paste into a chat with me — I'll write a tighter parser

## Refreshing player data

When `data/d.js` updates (new rankings, new ADP, etc.):

```bash
python3 export_extension_data.py
```

This regenerates `underdog-extension/data/players.json`. Reload the extension at `chrome://extensions` to pick up the new data.

## Mock testing without Underdog

Open `underdog-extension/mock.html` directly in a browser:

```bash
# From the underdog-extension folder
python3 -m http.server 8000
# Then visit http://localhost:8000/mock.html
```

The mock page simulates opponents drafting near Underdog ADP so you can play with the engine and validate that recommendations make sense.

## Files

```
manifest.json          — Chrome MV3 manifest
content.js             — Content script (isolated world)
injected.js            — WebSocket interceptor (page main world)
sidebar.html           — Sidebar markup
sidebar.css            — Self-contained styles
sidebar.js             — Sidebar logic + render loop
engine.js              — Pure recommendation engine (no DOM)
mock.html              — Offline harness for engine validation
data/players.json      — Slim player data (rebuilt via export script)
icons/icon-128.png     — Extension icon
```

## Recommendation logic (current version)

For each undrafted player, score = `base × need × adp × bye × stack × round_prior`

- **base**: rank-derived score (rank 1 ≈ 100, decays exponentially)
- **need**: position-need multiplier (boost when below positional floor, penalize when at ceiling)
- **adp**: STEAL/Value when Jack ranks much higher than UD, Reach/Stretch when UD ranks much higher
- **bye**: penalty when stacking same-bye-week players at same position
- **stack**: bonus for QB-WR / QB-TE on same NFL team (week 16/17 correlation — gets stronger when schedule loads)
- **round_prior**: encodes "what the field usually does" by round (R1-2 RB lean, R3-4 WR lean, etc.)

Top 6 are surfaced; #1 is highlighted. Click any rec to mark it drafted.
