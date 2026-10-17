// nflmdd_extract_chrome.js - run INSIDE Jack's Chrome (Claude in Chrome javascript_tool)
// on any https://www.nflmockdraftdatabase.com page while he is signed in to Mock+.
// Same-origin fetches the consensus mock (4 windows) + consensus big board, keeps
// QB/RB/WR/TE rows, and stores compact pipe text in window.__nflmdd:
//   P|period|n_mocks|picks         header for the M rows that follow
//   M|pick|name|pos|pct
//   D|depth|updated                 header for the big board
//   B|rank|name|pos|school          (skill rows through rank 300)
// Evaluates to a summary; read the text back in 900-char slices (the tool cuts
// results off near 1000 chars):  window.__nflmdd.slice(i*900, (i+1)*900)
// then save it to a file and run: python scripts/save_nflmdd_csv.py <file>
// Year: next April's draft (Oct 2026 -> 2027).
(async () => {
  const now = new Date();
  const yr = now.getMonth() >= 4 ? now.getFullYear() + 1 : now.getFullYear();
  const S = new Set(['QB', 'RB', 'HB', 'WR', 'TE']);
  const clean = (t) => t.replace(/\s+/g, ' ').trim();
  const lines = [];
  const summary = { yr, mock: {}, board: null };
  for (const per of ['1_week', '2_weeks', '1_month', 'all_time']) {
    const html = await fetch(`/mock-drafts/${yr}/consensus-mock-draft-${yr}?period=${per}`, { credentials: 'include' }).then((r) => r.text());
    const d = new DOMParser().parseFromString(html, 'text/html');
    const n = (html.match(/Aggregated from\s*<strong>\s*(\d+)/) || [])[1] || '';
    let picks = 0; const rows = [];
    d.querySelectorAll('span.font-black.leading-none').forEach((s) => {
      const card = s.closest('div.flex.items-stretch'); if (!card) return;
      const a = card.querySelector(`a[href^="/players/${yr}/"]`); if (!a) return;
      const pick = +s.textContent.trim(); picks = Math.max(picks, pick);
      let pos = clean((a.parentElement.querySelector('span') || {}).textContent || '');
      if (pos === 'HB') pos = 'RB';
      if (!S.has(pos)) return;
      const pct = [...card.querySelectorAll('span')].map((x) => x.textContent.trim()).filter((t) => /^\d{1,3}%$/.test(t)).pop();
      rows.push([pick, clean(a.textContent), pos, parseInt(pct, 10) || 0]);
    });
    lines.push(['P', per, n, picks].join('|'));
    rows.forEach((r) => lines.push(['M', ...r].join('|')));
    summary.mock[per] = { n, picks, skill: rows.length, locked: /Unlock Round \d+ with Mock\+/.test(html) };
  }
  const bh = await fetch(`/big-boards/${yr}/consensus-big-board-${yr}`, { credentials: 'include' }).then((r) => r.text());
  const upd = (bh.match(/Updated\W+(?:<[^>]*>\W*)*([A-Z][a-z]+ \d{1,2}, \d{4})/) || [])[1] || '';
  const re = new RegExp(`font-black[^>]*>\\s*(\\d{1,4})\\s*</span>.*?href="/players/${yr}/[^"]+"[^>]*>\\s*([^<]+?)\\s*</a>.*?rounded">\\s*([A-Z]{1,4})\\s*</span>(?:(?:(?!font-black).)*?href="/colleges/${yr}/[^"]+"[^>]*>\\s*([^<]+?)\\s*</a>)?`, 'gs');
  const tx = document.createElement('textarea');
  const dec = (s) => { tx.innerHTML = s || ''; return clean(tx.value); };
  const seen = new Set(); const brows = []; let depth = 0;
  for (const m of bh.matchAll(re)) {
    depth = Math.max(depth, +m[1]);
    const name = dec(m[2]);
    const pos = m[3] === 'HB' ? 'RB' : m[3];
    if (!S.has(pos) || seen.has(name) || +m[1] > 300) continue;
    seen.add(name); brows.push([+m[1], name, pos, dec(m[4])]);
  }
  lines.push(['D', depth, upd].join('|'));
  brows.forEach((r) => lines.push(['B', ...r].join('|')));
  summary.board = { depth, skill300: brows.length, updated: upd };
  window.__nflmdd = lines.join('\n');
  summary.chars = window.__nflmdd.length;
  summary.slices = Math.ceil(window.__nflmdd.length / 900);
  return summary;
})()
