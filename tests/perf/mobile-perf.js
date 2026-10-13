// Mobile load-performance check for the rankings landing page.
//
//   cd tests
//   node perf/mobile-perf.js                                  # live site, 2 runs
//   node perf/mobile-perf.js http://localhost:8899/ --runs 3  # any URL
//   node perf/mobile-perf.js --check                          # exit 1 if over perf/budget.json
//   node perf/mobile-perf.js --no-network-throttle            # CPU throttle only (local servers
//                                                             # don't gzip, so network time there is
//                                                             # meaningless — compare CPU-side only)
//
// Profile matches Lighthouse "mobile": Pixel 5 viewport/UA, 4x CPU slowdown, slow 4G
// (150 ms RTT, ~1.6 Mbps down). Cold cache per run, service workers blocked, onboarding
// tour pre-dismissed. Reports Web Vitals (FCP/LCP/CLS/TBT), when the first rankings rows
// exist, and bytes downloaded before vs after those rows (from resource timing — note
// cross-origin files without Timing-Allow-Origin, e.g. the Firebase SDK, report 0).
//
// Built 2026-10-13 for the mobile perf work (see BACKLOG / app.js split plan). Not part of
// the smoke suite: it hits the network and its numbers vary run to run — judge medians.
const { chromium, devices } = require('playwright');
const fs = require('fs');
const path = require('path');

const args = process.argv.slice(2);
const url = args.find(a => /^https?:/.test(a)) || 'https://www.myfantasyfootball.co/';
const runs = +(args[args.indexOf('--runs') + 1] || 0) || 2;
const throttleNet = !args.includes('--no-network-throttle');
const check = args.includes('--check');

const median = a => { const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };

async function once(browser) {
  const ctx = await browser.newContext({ ...devices['Pixel 5'], serviceWorkers: 'block' });
  await ctx.addInitScript(() => {
    try { localStorage.setItem('mff_seen_intro', '1'); } catch (e) {}
    window.__lcp = 0; window.__cls = 0; window.__long = []; window.__rowsAt = 0;
    new PerformanceObserver(l => { for (const e of l.getEntries()) window.__lcp = e.startTime; }).observe({ type: 'largest-contentful-paint', buffered: true });
    new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; }).observe({ type: 'layout-shift', buffered: true });
    new PerformanceObserver(l => { for (const e of l.getEntries()) window.__long.push([e.startTime, e.duration]); }).observe({ type: 'longtask', buffered: true });
    const iv = setInterval(() => {
      if (!window.__rowsAt && document.querySelector('#pageRankings tbody tr[data-idx]')) { window.__rowsAt = performance.now(); clearInterval(iv); }
    }, 25);
  });
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  await cdp.send('Network.enable');
  if (throttleNet) await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: 1.6 * 1024 * 1024 / 8, uploadThroughput: 750 * 1024 / 8 });
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
  await page.goto(url, { waitUntil: 'load', timeout: 240000 });
  await page.waitForFunction(() => window.__rowsAt > 0, null, { timeout: 240000, polling: 100 });
  await page.waitForTimeout(6000);
  const m = await page.evaluate(() => {
    const fcpE = performance.getEntriesByName('first-contentful-paint')[0];
    const fcp = fcpE ? fcpE.startTime : 0;
    const tbt = window.__long.filter(([s]) => s > fcp).reduce((a, [, d]) => a + Math.max(0, d - 50), 0);
    const res = performance.getEntriesByType('resource');
    const kb = list => Math.round(list.reduce((a, e) => a + (e.encodedBodySize || e.transferSize || 0), 0) / 1024);
    const pre = res.filter(e => e.startTime < window.__rowsAt);
    const post = res.filter(e => e.startTime >= window.__rowsAt);
    const fbBeforeRows = pre.filter(e => /firebasejs|apis\.google\.com|gapi/.test(e.name)).length;
    return {
      fcp: Math.round(fcp), lcp: Math.round(window.__lcp), cls: +window.__cls.toFixed(3), tbt: Math.round(tbt),
      maxLongTask: Math.round(Math.max(0, ...window.__long.map(x => x[1]))),
      rowsVisible: Math.round(window.__rowsAt),
      kbBeforeRows: kb(pre), kbAfterRows: kb(post), requestsBeforeRows: pre.length,
      firebaseRequestsBeforeRows: fbBeforeRows
    };
  });
  await ctx.close();
  return m;
}

(async () => {
  const browser = await chromium.launch();
  const all = [];
  for (let i = 0; i < runs; i++) { const r = await once(browser); all.push(r); console.log('run', i + 1, JSON.stringify(r)); }
  await browser.close();
  const keys = Object.keys(all[0]);
  const med = Object.fromEntries(keys.map(k => [k, median(all.map(r => r[k]))]));
  console.log('\nmedian of', runs, 'runs —', url, throttleNet ? '(slow 4G + 4x CPU)' : '(4x CPU, no network throttle)');
  console.log(JSON.stringify(med, null, 1));
  if (check) {
    const budget = JSON.parse(fs.readFileSync(path.join(__dirname, 'budget.json'), 'utf8'));
    const over = Object.entries(budget.max || {}).filter(([k, v]) => med[k] != null && med[k] > v);
    if (over.length) { console.log('\nOVER BUDGET:', over.map(([k, v]) => `${k} ${med[k]} > ${v}`).join(', ')); process.exit(1); }
    console.log('\nwithin budget');
  }
})().catch(e => { console.error(e); process.exit(1); });
