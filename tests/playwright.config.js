// Playwright smoke suite for the rankings page. Serves the repo checkout this
// tests/ dir lives in (so worktree runs test the worktree's code) on :8899.
// serviceWorkers are BLOCKED — the site's SW serves stale app.js from cache
// otherwise (the established local-testing gotcha); blocking it means every
// run loads the on-disk files.
const { defineConfig } = require('@playwright/test');
const path = require('path');

// MFF_SPLIT=1 → build the deploy-style split (scripts/split_app.js --site-copy into
// ../.split-preview: core app.js + lazy app-chunk-*.js) and test THAT on :8898.
// Default serves the unsplit checkout on :8899 (chunks inline, as in local dev).
const SPLIT = process.env.MFF_SPLIT === '1';
if (SPLIT && !process.env.MFF_SPLIT_BUILT) {
  require('child_process').execFileSync('node', [path.join(__dirname, '..', 'scripts', 'split_app.js'), '--site-copy', path.join(__dirname, '..', '.split-preview')], { stdio: 'inherit' });
  process.env.MFF_SPLIT_BUILT = '1';   // workers re-load this config — build once
}
const PORT = SPLIT ? 8898 : 8899;
const SITE = SPLIT ? '../.split-preview' : '..';

module.exports = defineConfig({
  testDir: '.',
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 2,
  retries: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:' + PORT,
    serviceWorkers: 'block',
    viewport: { width: 1440, height: 900 },
  },
  webServer: {
    command: `npx http-server ${SITE} -p ${PORT} -c-1 --silent`,
    url: 'http://127.0.0.1:' + PORT,
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
