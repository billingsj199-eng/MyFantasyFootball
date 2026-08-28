# MFF smoke tests

Playwright smoke suite for the rankings page — covers the 2026-08-27 feature
sweep (progressive render + skeleton, position/TOP-N filters, watchlist,
saved view presets, injury detail popover, print cheat sheet, view-options
collapse, in-season strip states, mobile bottom nav).

## Run

```
cd tests
npm install            # first time only (also: npx playwright install chromium)
npx playwright test
```

The config starts its own `http-server` on :8899 serving the repo checkout
this `tests/` dir lives in — so running from a worktree tests the worktree's
code. Service workers are **blocked** (`serviceWorkers: 'block'`) so every run
loads the on-disk files instead of the SW cache — the standing local-testing
gotcha.

Tests run signed-out on purpose: free-tier gates (Jack's board top-36 in the
print test) are part of what's asserted.

## Notes

- `node_modules/`, `test-results/`, `playwright-report/` are gitignored;
  `package.json` + specs + config are committed (they deploy to Pages as inert
  static files — a few KB).
- The suite asserts ballparks (>400 rows) rather than exact counts where daily
  data churn would flake it.
- Season-strip states use the `window._seasonStripNow` time-machine hook.
