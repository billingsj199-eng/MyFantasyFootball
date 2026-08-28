// Rankings-page smoke suite — covers the 2026-08-27 feature sweep so future
// refactors can't silently break it. Signed-out state throughout (free-tier
// gates are part of what's asserted). See README.md for how to run.
const { test, expect } = require('@playwright/test');

// The table boots asynchronously (deferred data files + app.js + first
// render). Waiting for real rows is the universal readiness signal.
// mff_seen_intro suppresses the first-visit tour overlay — Playwright
// contexts are pristine profiles, so without it #mffTourOverlay intercepts
// every click (this never bites manual testing in a lived-in browser).
async function bootRankings(page) {
  await page.addInitScript(() => {
    try { localStorage.setItem('mff_seen_intro', '1'); } catch (e) {}
  });
  await page.goto('/');
  await expect(page.locator('#tbody tr[data-idx]').first()).toBeVisible({ timeout: 60_000 });
  // Progressive render appends the tail on the next tick — settle it.
  await page.waitForFunction(() => document.querySelectorAll('#tbody tr[data-idx]').length > 200);
}

test.describe('rankings page', () => {
  test('boot: skeleton is replaced by the full progressive render', async ({ page }) => {
    // Skeleton rows are baked into the served HTML (loading state)…
    const html = await (await page.request.get('/')).text();
    expect(html.split('skel-row').length - 1).toBeGreaterThan(5);
    // …and the first render replaces them wholesale with real rows.
    await page.goto('/');
    await page.waitForFunction(() => document.querySelectorAll('#tbody tr[data-idx]').length > 400);
    expect(await page.locator('#tbody .skel-row').count()).toBe(0);
    // Roster churn moves the exact count — assert the ballpark, not 502.
    expect(await page.locator('#tbody tr[data-idx]').count()).toBeGreaterThan(400);
  });

  test('position filter + TOP-N cap the visible pool', async ({ page }) => {
    await bootRankings(page);
    await page.click('.pos-btn[data-pos="QB"]');
    await page.waitForFunction(() => {
      const rows = document.querySelectorAll('#tbody tr[data-idx]');
      return rows.length > 0 && [...rows].every(r => r.querySelector('.pos-badge').textContent === 'QB');
    });
    await page.fill('#rankTopNInput', '20');
    await page.waitForFunction(() =>
      document.querySelectorAll('#tbody tr[data-idx]').length === 20);
    expect(await page.locator('#tbody tr[data-idx]').count()).toBe(20);
  });

  test('watchlist: star a row, filter by it, persist it', async ({ page }) => {
    await bootRankings(page);
    const star = page.locator('#tbody .watch-star').first();
    const name = await star.getAttribute('data-watch');
    await star.click({ force: true }); // hover-reveal chip — force past opacity
    await expect(page.locator('#watchFilterCount')).toHaveText('1');
    await page.click('#watchFilterBtn');
    await page.waitForFunction(() =>
      document.querySelectorAll('#tbody tr[data-idx]').length === 1);
    const stored = await page.evaluate(() => localStorage.getItem('mff_watchlist'));
    expect(JSON.parse(stored)).toEqual([name]);
    await page.click('#watchFilterBtn'); // off again
    await page.waitForFunction(() =>
      document.querySelectorAll('#tbody tr[data-idx]').length > 200);
  });

  test('saved view preset round-trips the control state', async ({ page }) => {
    await page.addInitScript(() => { window.prompt = () => 'Smoke Preset'; });
    await bootRankings(page);
    // Distinct state: Jack's board + Superflex + Half PPR + QB
    await page.click('.version-tab[data-version="jacks"]');
    await page.click('.mode-tab[data-mode="superflex"]');
    await page.evaluate(() => document.querySelector('.rnk-scoring-btn[data-rnkscoring="half"]').click());
    await page.click('.pos-btn[data-pos="QB"]');
    await page.evaluate(() => window._saveViewPreset());
    await expect(page.locator('.vp-chip')).toHaveCount(1);
    // Scramble everything, then apply the chip
    await page.click('.version-tab[data-version="consensus"]');
    await page.click('.mode-tab[data-mode="redraft"]');
    await page.evaluate(() => document.querySelector('.rnk-scoring-btn[data-rnkscoring="ppr"]').click());
    await page.click('.pos-btn[data-pos="ALL"]');
    await page.click('.vp-chip');
    await page.waitForFunction(() =>
      document.querySelector('.version-tab[data-version="jacks"]').classList.contains('active')
      && document.querySelector('.mode-tab[data-mode="superflex"]').classList.contains('active')
      && document.querySelector('.rnk-scoring-btn[data-rnkscoring="half"]').classList.contains('active')
      && document.querySelector('.pos-btn[data-pos="QB"]').classList.contains('active'));
  });

  test('injury pill opens the detail popover, not the player card', async ({ page }) => {
    await bootRankings(page);
    const pill = page.locator('#tbody .inj-pill').first();
    await expect(pill).toBeVisible();
    await pill.click();
    await expect(page.locator('#injPopover')).toBeVisible();
    const popText = await page.locator('#injPopover').textContent();
    expect(popText).toMatch(/Injury/);
    expect(await page.evaluate(() =>
      document.getElementById('modal').classList.contains('open'))).toBe(false);
    await page.keyboard.press('Escape');
    await expect(page.locator('#injPopover')).toBeHidden();
  });

  test("print sheet builds the printable doc from Jack's board", async ({ page }) => {
    await bootRankings(page);
    await page.click('.version-tab[data-version="jacks"]');
    // Capture the hidden print iframe and stub its print() before it fires.
    await page.evaluate(() => {
      const orig = Document.prototype.createElement.bind(document);
      window.__printed = false;
      document.createElement = function (tag) {
        const el = orig(tag);
        if (String(tag).toLowerCase() === 'iframe') {
          window.__pf = el;
          setTimeout(() => { try { el.contentWindow.print = () => { window.__printed = true; }; } catch (e) {} }, 50);
        }
        return el;
      };
      document.getElementById('btnPrintSheet').click();
    });
    await page.waitForFunction(() => window.__printed === true);
    const result = await page.evaluate(() => {
      const d = window.__pf.contentDocument;
      return { rows: d.querySelectorAll('.pr').length, tiers: d.querySelectorAll('.tiersep').length };
    });
    // Signed-out Jack's board = free top-36 with tier breaks.
    expect(result.rows).toBe(36);
    expect(result.tiers).toBeGreaterThan(3);
  });

  test('view-options row is collapsed by default with a live summary', async ({ page }) => {
    await bootRankings(page);
    await expect(page.locator('#viewOptsWrap')).toBeHidden();
    await expect(page.locator('#viewOptsSummary')).toContainText('PPR');
    await page.click('#viewOptsToggle');
    await expect(page.locator('#viewOptsWrap')).toBeVisible();
    await expect(page.locator('#viewOptsSummary')).toHaveText('');
  });

  test('sticky header stack stays flush through the view-options toggle', async ({ page }) => {
    await bootRankings(page);
    const gapAfter = async () => page.evaluate(() => new Promise(r => {
      const pg = document.getElementById('pageRankings');
      pg.scrollTop = 600;
      requestAnimationFrame(() => requestAnimationFrame(() => {
        const c = pg.querySelector('.controls').getBoundingClientRect();
        const s = pg.querySelector('.stats-bar').getBoundingClientRect();
        r(Math.round(s.top - c.bottom) || 0); // || 0 normalizes -0 (Object.is)
      }));
    }));
    // Collapsed (default): stats-bar flush under the controls block.
    expect(await gapAfter()).toBe(0);
    // Expand: the sticky scoring row joins the stack — offset must grow with it
    // (the 2026-08-28 regression: the wrap hides it via PARENT display, which
    // ResizeObserver can't see; _viewOptsApply now resyncs explicitly).
    await page.evaluate(() => { document.getElementById('pageRankings').scrollTop = 0; window._toggleViewOpts(); });
    const expandedGap = await gapAfter();
    const scoringH = await page.evaluate(() =>
      Math.round(document.querySelector('#pageRankings .rnk-scoring-row').getBoundingClientRect().height));
    expect(scoringH).toBeGreaterThan(0);
    expect(expandedGap).toBe(scoringH); // stats-bar sits exactly below the scoring row
    // Collapse again: back to flush (this was the user-visible gap bug).
    await page.evaluate(() => { document.getElementById('pageRankings').scrollTop = 0; window._toggleViewOpts(); });
    expect(await gapAfter()).toBe(0);
  });

  test('season strip states via the time-machine hook', async ({ page }) => {
    await bootRankings(page);
    const probe = () => page.evaluate(() => ({
      shown: document.getElementById('seasonStrip').style.display,
      week: document.getElementById('ssWeek').textContent,
      msg: document.getElementById('ssMsg').textContent,
    }));
    const at = (ms) => page.evaluate((t) => { window._seasonStripNow = t; window._seasonStripRefresh(); }, ms);
    await at(Date.UTC(2026, 8, 1, 12, 0)); // preseason
    expect((await probe()).msg).toContain('Season kicks off');
    await at(Date.UTC(2026, 8, 13, 18, 0)); // W1 Sunday
    expect((await probe()).msg).toContain('in progress');
    await at(Date.UTC(2026, 8, 15, 15, 0)); // Tue after W1 -> W2 countdown
    expect((await probe()).week).toContain('WEEK 2');
    await at(Date.UTC(2027, 1, 1, 0, 0)); // post-season
    expect((await probe()).shown).toBe('none');
    await page.evaluate(() => { window._seasonStripNow = null; window._seasonStripRefresh(); });
  });
});

test.describe('mobile', () => {
  test.use({ viewport: { width: 375, height: 812 } });
  test('bottom nav shows and switches pages', async ({ page }) => {
    await bootRankings(page);
    const nav = page.locator('#bottomNav');
    await expect(nav).toBeVisible();
    await nav.locator('[data-bnav="myteams"]').click();
    await page.waitForFunction(() =>
      document.querySelector('.page.active').id === 'pageMyTeams');
    await expect(nav.locator('[data-bnav="myteams"]')).toHaveClass(/active/);
    await nav.locator('[data-bnav="rankings"]').click();
    await page.waitForFunction(() =>
      document.querySelector('.page.active').id === 'pageRankings');
  });
});
