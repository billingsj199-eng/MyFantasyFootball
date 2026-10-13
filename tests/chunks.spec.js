// Lazy app chunks (scripts/split_app.js): each page whose code lives in a chunk must load
// it on entry and work — via nav click, deep link and back/forward. Runs against the unsplit
// checkout by default (chunks inline: everything must behave exactly the same) and against
// the deploy-style split build with MFF_SPLIT=1 (see playwright.config.js).
const { test, expect } = require('@playwright/test');

const SPLIT = process.env.MFF_SPLIT === '1';

async function boot(page, path = '/') {
  await page.addInitScript(() => { try { localStorage.setItem('mff_seen_intro', '1'); } catch (e) {} });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(path);
  await expect(page.locator('#tbody tr[data-idx]').first()).toBeAttached({ timeout: 60_000 });
  return errors;
}
const chunkRequests = page => page.evaluate(() =>
  performance.getEntriesByType('resource').map(e => e.name).filter(n => /app-chunk-/.test(n)).map(n => n.split('/').pop().split('?')[0]));

test.describe('lazy app chunks', () => {
  test('first paint loads no chunk', async ({ page }) => {
    const errors = await boot(page);
    await page.waitForTimeout(1500);
    expect(await chunkRequests(page)).toEqual([]);
    expect(errors).toEqual([]);
  });

  test('mock draft: nav loads its chunk and the draft starts', async ({ page }) => {
    const errors = await boot(page);
    await page.evaluate(() => window.switchPage('mockdraft'));
    await expect(page.locator('#pageMockdraft')).toHaveClass(/active/);
    await expect.poll(() => page.evaluate(() => window._chunkLoaded('mock'))).toBe(true);
    if (SPLIT) expect(await chunkRequests(page)).toContain('app-chunk-mock.js');
    // the mock IIFE wired the start button on load — clicking it starts a draft board
    await page.locator('#mdStartBtn').click();
    await expect.poll(() => page.evaluate(() => document.querySelectorAll('#pageMockdraft .md-pick, #pageMockdraft [class*="md-board"] *, #pageMockdraft table tr').length), { timeout: 20_000 }).toBeGreaterThan(5);
    expect(errors).toEqual([]);
  });

  test('draft strategy: renders after its chunk loads', async ({ page }) => {
    const errors = await boot(page);
    await page.evaluate(() => window.switchPage('draftstrategy'));
    await expect.poll(() => page.evaluate(() => (document.getElementById('dsBody') || {}).innerText || ''), { timeout: 30_000 }).toMatch(/\w{20,}/);
    if (SPLIT) expect(await chunkRequests(page)).toContain('app-chunk-draftstrategy.js');
    expect(errors).toEqual([]);
  });

  test('deep link #mockdraft loads the chunk; back returns to it from another page', async ({ page }) => {
    const errors = await boot(page, '/#mockdraft');
    await expect(page.locator('#pageMockdraft')).toHaveClass(/active/);
    await expect.poll(() => page.evaluate(() => window._chunkLoaded('mock'))).toBe(true);
    await page.evaluate(() => window.switchPage('draftstrategy'));
    await expect(page.locator('#pageDraftStrategy')).toHaveClass(/active/);
    await page.goBack();
    await expect(page.locator('#pageMockdraft')).toHaveClass(/active/);
    expect(errors).toEqual([]);
  });

  test('trivia embed (public) loads the trivia chunk', async ({ page }) => {
    const errors = await boot(page, '/?embed=trivia');
    await expect.poll(() => page.evaluate(() => typeof window._triviaTabSwitch), { timeout: 30_000 }).toBe('function');
    await expect(page.locator('#pageTrivia')).toHaveClass(/active/);
    if (SPLIT) expect(await chunkRequests(page)).toContain('app-chunk-trivia.js');
    expect(errors).toEqual([]);
  });

  test('prospect page loads its chunk and builds the model', async ({ page }) => {
    const errors = await boot(page);
    await page.evaluate(() => window.switchPage('prospect'));
    await expect(page.locator('#pageProspect')).toHaveClass(/active/);
    await expect.poll(() => page.evaluate(() => window._pmBuiltData ? window._pmBuiltData().length : 0), { timeout: 60_000 }).toBeGreaterThan(100);
    if (SPLIT) expect(await chunkRequests(page)).toContain('app-chunk-prospect.js');
    expect(errors).toEqual([]);
  });

  test('dynasty board pulls the prospect chunk and attaches JM scores', async ({ page }) => {
    const errors = await boot(page);
    expect(await chunkRequests(page)).toEqual([]);
    await page.click('.mode-tab[data-mode="dynasty"]');
    await expect.poll(() => page.evaluate(() => D.filter(d => d._pmJm != null).length), { timeout: 60_000 }).toBeGreaterThan(50);
    if (SPLIT) expect(await chunkRequests(page)).toContain('app-chunk-prospect.js');
    expect(errors).toEqual([]);
  });

  test('player card pulls the prospect chunk and shows the JM tile', async ({ page }) => {
    const errors = await boot(page);
    await page.evaluate(() => window.openPlayerCard(D.find(d => d.n === 'Ashton Jeanty')));
    await expect.poll(() => page.evaluate(() => window._chunkLoaded('prospect'))).toBe(true);
    await expect.poll(() => page.evaluate(() => /\bJM\b/.test(document.getElementById('playerCard').innerText)), { timeout: 60_000 }).toBe(true);
    expect(await page.evaluate(() => window._cardOpenName)).toBe('Ashton Jeanty');
    expect(errors).toEqual([]);
  });

  test('games: chunk loads after ep_retired; daily Guess Who pick is the pinned one', async ({ page }) => {
    const errors = await boot(page);
    await page.evaluate(() => window.switchPage('games'));
    await expect(page.locator('#pageGames')).toHaveClass(/active/);
    await expect.poll(() => page.evaluate(() => typeof window._gwDailyPickInfo), { timeout: 30_000 }).toBe('function');
    const info = await page.evaluate(() => window._gwDailyPickInfo());
    expect(info.retired).toBeGreaterThan(400);          // expanded retired pool, not the empty/311 one
    if (process.env.MFF_DAILY_PICK) expect(info.name + '|' + info.pool).toBe(process.env.MFF_DAILY_PICK);
    console.log('daily pick', JSON.stringify(info));
    if (SPLIT) {
      const order = await page.evaluate(() => performance.getEntriesByType('resource').map(e => e.name.split('/').pop().split('?')[0]).filter(n => /ep_retired|app-chunk-games/.test(n)));
      expect(order).toEqual(['ep_retired.js', 'app-chunk-games.js']);
    }
    expect(errors).toEqual([]);
  });

  test('retired players reach D (search) after first paint without visiting games', async ({ page }) => {
    const errors = await boot(page);
    await expect.poll(() => page.evaluate(() => window._RETIRED_NAMES ? window._RETIRED_NAMES.size : 0), { timeout: 30_000 }).toBeGreaterThan(400);
    expect(await page.evaluate(() => !!D.find(d => d.n === 'Tom Brady' && d._retired))).toBe(true);
    if (SPLIT) expect(await chunkRequests(page)).toEqual([]);
    expect(errors).toEqual([]);
  });

  test('rankings rows (incl. SOS) render without the my teams chunk', async ({ page }) => {
    const errors = await boot(page);
    await page.waitForTimeout(2500);
    const sos = await page.evaluate(() => [...document.querySelectorAll('#tbody tr[data-idx] .psos-cell')].slice(0, 40).map(td => td.textContent.trim()));
    expect(sos.filter(s => /^\d+$/.test(s)).length).toBeGreaterThan(30);
    if (SPLIT) expect((await chunkRequests(page)).filter(n => /myteams|trade/.test(n))).toEqual([]);
    expect(errors).toEqual([]);
  });

  test('my teams page loads trade + my teams and renders', async ({ page }) => {
    const errors = await boot(page);
    await page.evaluate(() => window.switchPage('myteams'));
    await expect(page.locator('#pageMyTeams')).toHaveClass(/active/);
    await expect.poll(() => page.evaluate(() => window._chunkLoaded('myteams') && window._chunkLoaded('trade')), { timeout: 30_000 }).toBe(true);
    await expect.poll(() => page.evaluate(() => typeof window._mtImportSleeper)).toBe('function');
    await expect(page.locator('#mtSleeperImportBtn')).toBeVisible();
    if (SPLIT) { const c = await chunkRequests(page); expect(c.indexOf('app-chunk-trade.js')).toBeLessThan(c.indexOf('app-chunk-myteams.js')); }
    expect(errors).toEqual([]);
  });

  test('trade page loads its chunk and values a trade', async ({ page }) => {
    const errors = await boot(page);
    await page.evaluate(() => window.switchPage('trade'));
    await expect.poll(() => page.evaluate(() => typeof window._getTradeValue), { timeout: 30_000 }).toBe('function');
    for (const [id, q] of [['tradeSearchA', 'Bijan'], ['tradeSearchB', 'Jahmyr']]) {
      await page.fill('#' + id, q);
      await page.locator('#' + id).locator('xpath=..').locator('.trade-dropdown > *').first().click();
    }
    await expect.poll(() => page.evaluate(() => (document.querySelector('.trade-verdict') || {}).textContent || '')).toMatch(/WINS|EVEN|FAIR/i);
    if (SPLIT) expect(await chunkRequests(page)).toEqual(['app-chunk-trade.js']);
    expect(errors).toEqual([]);
  });

  test('returning My Teams user: chunk auto-loads after first paint', async ({ page }) => {
    await page.addInitScript(() => { try { localStorage.setItem('mt_last_opened', String(Date.now())); } catch (e) {} });
    const errors = await boot(page);
    await expect.poll(() => page.evaluate(() => window._chunkLoaded('myteams')), { timeout: 30_000 }).toBe(true);
    expect(await page.evaluate(() => document.getElementById('pageRankings').classList.contains('active'))).toBe(true);
    expect(errors).toEqual([]);
  });

  test('extension calls/events before my teams loads are replayed into it', async ({ page }) => {
    const errors = await boot(page);
    const res = await page.evaluate(async () => {
      let seen = 0;
      document.addEventListener('mff-espn-league-from-extension', () => { seen++; });
      // what the Underdog page-bridge / ESPN mff-bridge do on an MFF tab
      window._mffSetPortfolio({ drafts: { t1: { id: 't1', tournament: 'Test', fee: 5, picks: [{ name: 'Bijan Robinson', pos: 'RB', team: 'ATL', pick: 1 }] } }, syncedAt: Date.now() });
      document.dispatchEvent(new CustomEvent('mff-espn-league-from-extension', { detail: { leagues: {}, pushedAt: Date.now() } }));
      for (let i = 0; i < 100 && !window._chunkLoaded('myteams'); i++) await new Promise(r => setTimeout(r, 200));
      await new Promise(r => setTimeout(r, 1000));
      return { loaded: window._chunkLoaded('myteams'), realFn: !/calls\.push/.test(String(window._mffSetPortfolio)), seen,
               portfolio: !!(window._udPortfolio && window._udPortfolio.drafts && Object.keys(window._udPortfolio.drafts).length) };
    });
    expect(res.loaded).toBe(true);
    expect(res.realFn).toBe(true);
    expect(res.portfolio).toBe(true);
    if (SPLIT) expect(res.seen).toBe(2);   // original + replay after the chunk's listener exists
    expect(errors).toEqual([]);
  });

  test('research (admin) loads its chunk and renders', async ({ page }) => {
    const errors = await boot(page);
    await page.evaluate(() => { window.isAdmin = () => true; window.switchPage('research'); });
    await expect(page.locator('#pageResearch')).toHaveClass(/active/);
    await expect.poll(() => page.evaluate(() => typeof window._renderResearch), { timeout: 30_000 }).toBe('function');
    if (SPLIT) expect(await chunkRequests(page)).toContain('app-chunk-research.js');
    expect(errors).toEqual([]);
  });
});
