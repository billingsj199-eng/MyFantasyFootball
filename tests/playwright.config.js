// Playwright smoke suite for the rankings page. Serves the repo checkout this
// tests/ dir lives in (so worktree runs test the worktree's code) on :8899.
// serviceWorkers are BLOCKED — the site's SW serves stale app.js from cache
// otherwise (the established local-testing gotcha); blocking it means every
// run loads the on-disk files.
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: '.',
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 2,
  retries: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:8899',
    serviceWorkers: 'block',
    viewport: { width: 1440, height: 900 },
  },
  webServer: {
    command: 'npx http-server .. -p 8899 -c-1 --silent',
    url: 'http://127.0.0.1:8899',
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
