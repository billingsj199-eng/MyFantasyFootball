// ============================================================================
// export_notes.js — headless twin of the Sim Lab NOTES tab (Jack 2026-09-15:
// "write the notes sheet to a file every morning").
//
// Serves E:\MyFantasyFootball over a local static server, opens sim_lab/
// index.html in headless Chromium (Playwright from the site repo's
// tests/node_modules), waits for the injury layer to arm (kickoffs fetch),
// selects "All games" on the NOTES tab and saves the plain-text sheet:
//   sim_lab/notes/notes_w<N>_<scoring>.txt   and   sim_lab/notes/notes_latest.txt
// The notes/ folder deploys with the Sim Lab hosting site, so the latest
// sheet is also readable at https://jb-simlab-2026.web.app/notes/notes_latest.txt
//
// Same code path as the tab: whatever renderNotesTab writes into #nt-text.
// Usage: node export_notes.js [--week N] [--scoring half|ppr|std]
// Runs from update_simlab.bat (06:45 daily) after pull_pace_tracker.py.
// ============================================================================
'use strict';
const fs = require('fs');
const path = require('path');
const http = require('http');

const ROOT = 'E:/MyFantasyFootball';
const LAB = path.join(ROOT, 'sim_lab');
const OUT_DIR = path.join(LAB, 'notes');
const ARGS = process.argv.slice(2);
function argOf(flag, dflt) { const i = ARGS.indexOf(flag); return i >= 0 && ARGS[i + 1] ? ARGS[i + 1] : dflt; }
const WEEK = argOf('--week', null);
const SCORING = argOf('--scoring', 'half');
const REPO = argOf('--repo', null);   // when set: also write <repo>/data/matchup_edges_2026.js (main site Start/Sit MATCHUP EDGES)

const MIME = { '.html': 'text/html', '.js': 'application/javascript', '.json': 'application/json', '.css': 'text/css', '.txt': 'text/plain' };
function serve() {
  return new Promise(resolve => {
    const srv = http.createServer((req, res) => {
      const p = decodeURIComponent(req.url.split('?')[0]);
      const f = path.resolve(ROOT, '.' + p);
      if (!f.startsWith(path.resolve(ROOT)) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
      fs.createReadStream(f).pipe(res);
    });
    srv.listen(0, '127.0.0.1', () => resolve(srv));
  });
}

(async () => {
  const { chromium } = require(path.join(ROOT, 'MyFantasyFootball Files', 'tests', 'node_modules', 'playwright'));
  const srv = await serve();
  const port = srv.address().port;
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
    page.on('requestfailed', r => errors.push('reqfail: ' + r.url()));
    await page.goto(`http://127.0.0.1:${port}/sim_lab/index.html`, { waitUntil: 'load' });
    await page.waitForFunction(() => document.getElementById('nt-text') && document.getElementById('nt-text').value.length > 100, null, { timeout: 60000 });
    // injury layer arms asynchronously (kickoffs_2026.json); give it up to 15s, then re-render
    await page.waitForFunction(() => /injury layer/.test(document.getElementById('status').textContent), null, { timeout: 15000 }).catch(() => {});
    const info = await page.evaluate(({ week, scoring }) => {
      const wk = document.getElementById('nt-week'), g = document.getElementById('nt-game'), sc = document.getElementById('nt-scoring');
      if (week) { wk.value = String(week); wk.dispatchEvent(new Event('change')); }
      sc.value = scoring; sc.dispatchEvent(new Event('change'));
      g.value = '__all'; g.dispatchEvent(new Event('change'));
      return { week: wk.value, games: g.options.length - 1, status: document.getElementById('status').textContent, text: document.getElementById('nt-text').value };
    }, { week: WEEK, scoring: SCORING });
    fs.mkdirSync(OUT_DIR, { recursive: true });
    const header = `# Sim Lab notes — Week ${info.week} (${SCORING}) — generated ${new Date().toISOString().slice(0, 16).replace('T', ' ')}Z\n# ${info.status}\n\n`;
    const body = header + info.text + '\n';
    const f1 = path.join(OUT_DIR, `notes_w${info.week}_${SCORING}.txt`);
    fs.writeFileSync(f1, body); fs.writeFileSync(path.join(OUT_DIR, 'notes_latest.txt'), body);
    console.log(`wrote ${f1} (${body.length} chars, ${info.games} games) + notes_latest.txt` + (errors.length ? ` | page errors: ${errors.slice(0, 2).join(' | ')}` : ''));
    if (!/injury layer/.test(info.status)) console.log('note: injury layer did not arm within 15s (kickoffs fetch) - OUT/docked chips may be missing');
    if (REPO) {
      const edges = await page.evaluate(({ week }) => window.SimLabMatchupEdges ? window.SimLabMatchupEdges(week, 'half') : null, { week: info.week });
      if (edges && edges.rows && edges.rows.length) {
        const f2 = path.join(REPO, 'data', 'matchup_edges_2026.js');
        // keep earlier weeks so a published week never loses its board mid-week
        let prev = {};
        try { const t = fs.readFileSync(f2, 'utf8'); prev = JSON.parse(t.slice(t.indexOf('{'), t.lastIndexOf('}') + 1)).weeks || {}; } catch (_) {}
        const keep = {}; Object.keys(prev).map(Number).filter(w => w >= edges.week - 2 && w !== edges.week).forEach(w => { keep[w] = prev[w]; });
        keep[edges.week] = { generated: edges.generated, scoring: edges.scoring, rows: edges.rows };
        const out = '// built by sim_lab/export_notes.js --repo (Sim Lab NOTES matchup edges) - Start/Sit page MATCHUP EDGES. % of each player\'s projection;\n'
          + '// priced = already inside the projection, the rest are matchup reads (context, not added to the number).\n'
          + 'window.MATCHUP_EDGES_2026 = ' + JSON.stringify({ latest: edges.week, weeks: keep }) + ';\n';
        let old = ''; try { old = fs.readFileSync(f2, 'utf8'); } catch (_) {}
        const strip = s => s.replace(/"generated":"[^"]*"/g, '');
        if (strip(old) !== strip(out)) { fs.writeFileSync(f2, out); console.log(`wrote ${f2} (week ${edges.week}, ${edges.rows.length} players)`); }
        else console.log('matchup edges unchanged');
      } else console.log('matchup edges: nothing to write');
      const why = await page.evaluate(({ week }) => window.SimLabWhy ? window.SimLabWhy(week) : null, { week: info.week });
      if (why && why.players && Object.keys(why.players).length) {
        const f3 = path.join(REPO, 'data', 'proj_why_2026.json');
        const body3 = JSON.stringify(why);
        let old3 = ''; try { old3 = fs.readFileSync(f3, 'utf8'); } catch (_) {}
        const strip3 = s => s.replace(/"generated":"[^"]*"/g, '');
        if (strip3(old3) !== strip3(body3)) { fs.writeFileSync(f3, body3); console.log(`wrote ${f3} (week ${why.week}, ${Object.keys(why.players).length} players, ${Math.round(body3.length / 1024)} KB)`); }
        else console.log('projection why unchanged');
      } else console.log('projection why: nothing to write');
    }
  } finally {
    await browser.close(); srv.close();
  }
})().catch(e => { console.error('export_notes failed: ' + e.message); process.exit(1); });
