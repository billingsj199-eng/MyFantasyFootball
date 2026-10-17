// fetch_mockdb.js - load an NFL Mock Draft Database page with Jack's Mock+ session.
//
// The consensus mock draft shows round 1 to everyone; rounds 2+ need a Mock+ login.
// The session lives in a DEDICATED Chrome profile outside the repo (never Jack's
// everyday profile, never a stored password or cookie file in git):
//     E:\MyFantasyFootball\mockdb_chrome_profile
//
// One-time / when the session expires (Jack signs in himself in the window):
//     node scripts/fetch_mockdb.js --login
// Fetch (headless; used by pull_draft_boards.py):
//     node scripts/fetch_mockdb.js <url> <out.html>
// Exit codes: 0 = page written and unlocked, 4 = page written but still locked
// (signed out - run --login), 1 = error.
const fs = require('fs');
const path = require('path');

const REPO = path.resolve(__dirname, '..');
const PROFILE = path.resolve(REPO, '..', 'mockdb_chrome_profile');
const LOGIN_URL = 'https://www.nflmockdraftdatabase.com/mock-drafts/2027/consensus-mock-draft-2027';
const LOCKED = /Unlock Round \d+ with Mock\+/;

async function open(chromium, headless) {
  // Installed Chrome first (Task Scheduler can't see session-installed Playwright browsers),
  // then Edge. The profile dir is tied to whichever opened it first - keep it Chrome.
  let last;
  for (const channel of ['chrome', 'msedge']) {
    try {
      return await chromium.launchPersistentContext(PROFILE, { channel, headless, viewport: { width: 1280, height: 900 } });
    } catch (e) { last = e; }
  }
  throw last;
}

(async () => {
  const { chromium } = require(path.join(REPO, 'tests', 'node_modules', 'playwright'));
  const args = process.argv.slice(2);
  if (args[0] === '--login') {
    // Plain Chrome on the profile, NOT a Playwright window: Google sign-in refuses
    // automation-controlled browsers ("this browser may not be secure").
    const { spawn } = require('child_process');
    const exe = ['C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
      'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe'].find((p) => fs.existsSync(p));
    if (!exe) throw new Error('chrome.exe not found');
    const ch = spawn(exe, [`--user-data-dir=${PROFILE}`, '--no-first-run', '--no-default-browser-check', '--new-window', LOGIN_URL], { stdio: 'ignore' });
    console.log('Sign in to NFL Mock Draft Database in the window, then close it.');
    await new Promise((res) => ch.on('exit', res));
    console.log('profile saved:', PROFILE);
    return;
  }
  const [url, out] = args;
  if (!url || !out) throw new Error('usage: fetch_mockdb.js <url> <out.html> | --login');
  const ctx = await open(chromium, true);
  try {
    const page = ctx.pages()[0] || await ctx.newPage();
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
    const html = await page.content();
    fs.writeFileSync(out, html, 'utf8');
    const locked = LOCKED.test(html);
    const short = html.length < 10000;   // bot check / error page, not the mock
    console.log(`${short ? 'SHORT PAGE' : locked ? 'LOCKED' : 'ok'} ${html.length} bytes -> ${out}`);
    process.exitCode = short ? 1 : locked ? 4 : 0;
  } finally {
    await ctx.close();
  }
})().catch((e) => { console.error(String(e && e.stack || e)); process.exitCode = 1; });
