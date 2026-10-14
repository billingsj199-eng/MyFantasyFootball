"""One-off patch: TRENDS button / CSS / KTC history meta in index.html (rank-trends worktree)."""
p = r'E:\MyFantasyFootball\MyFantasyFootball Files\.claude\worktrees\rank-trends\index.html'
s = open(p, encoding='utf-8', newline='').read()
nl = '\r\n' if '\r\n' in s[:2000] else '\n'


def rep(a, b):
    global s
    assert s.count(a) == 1, (a[:90], s.count(a))
    s = s.replace(a, b)


rep('<meta name="mff-dyn-sim-v" content="2026-10-09-tep">',
    '<meta name="mff-dyn-sim-v" content="2026-10-09-tep">' + nl +
    '<!-- KTC daily value history (data/ktc_history.js, lazy-loaded by TRENDS) — bumped by scripts/build_ktc_history.py -->' + nl +
    '<meta name="mff-ktc-hist-v" content="2026-10-09">')
rep('    body[data-rnk-stat="dyn"] #pageRankings tbody tr:not(.devy-row) .ppg-proj-cell::after{content:"DYN"}',
    '    body[data-rnk-stat="dyn"] #pageRankings tbody tr:not(.devy-row) .ppg-proj-cell::after{content:"DYN"}' + nl +
    '    body[data-rnk-stat="trend"] #pageRankings tbody tr:not(.devy-row) .ppg-proj-cell::after{content:"RANK"}')
rep('  body:not(.format-dynasty) .rnk-statmode-btn[data-rnkstatmode="dyn"] { display: none !important; }',
    '  body:not(.format-dynasty) .rnk-statmode-btn[data-rnkstatmode="dyn"] { display: none !important; }' + nl +
    '  body:not(.trend-ok) .rnk-statmode-btn[data-rnkstatmode="trend"] { display: none !important; }')
i = s.index('<button class="rnk-statmode-btn" data-rnkstatmode="dyn"')
j = s.index('</button>', i) + len('</button>')
s = s[:j] + nl + ('<button class="rnk-statmode-btn" data-rnkstatmode="trend" title="Rank movement — '
                  'consensus rank history on REDRAFT, KeepTradeCut rank history on DYNASTY: rank today, '
                  '7- and 30-day change, a sparkline, and on dynasty the Dynasty SIM vs KTC gap (BUY / SELL).">TRENDS</button>') + s[j:]
open(p, 'w', encoding='utf-8', newline='').write(s)
print('patched index.html')
