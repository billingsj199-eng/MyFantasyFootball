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

## Mobile performance

```
cd tests
npm run perf                                   # live site, Lighthouse-mobile profile, 2 runs
node perf/mobile-perf.js http://localhost:8899/ --no-network-throttle
npm run perf:check                             # exit 1 if medians exceed perf/budget.json
```

Pixel 5 + 4x CPU + slow 4G (150 ms RTT, ~1.6 Mbps), cold cache, SW blocked.
Prints FCP / LCP / CLS / TBT, when the first rankings rows exist, and KB
downloaded before vs after them. Not part of `playwright test` — it hits the
network and varies run to run, so compare medians. Local servers don't gzip,
so use `--no-network-throttle` there and judge network time on the live site.
Tighten `perf/budget.json` as each phase of the app.js split plan ships.

## Notes

- `node_modules/`, `test-results/`, `playwright-report/` are gitignored;
  `package.json` + specs + config are committed (they deploy to Pages as inert
  static files — a few KB).
- The suite asserts ballparks (>400 rows) rather than exact counts where daily
  data churn would flake it.
- Season-strip states use the `window._seasonStripNow` time-machine hook.
