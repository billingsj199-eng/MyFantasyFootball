"""One-off patch: dynasty boards — drop SOS / P-SOS / L4 PPG, show AGE, add VALUE (dyn-cols worktree)."""
p = r'E:\MyFantasyFootball\MyFantasyFootball Files\.claude\worktrees\dyn-cols\app.js'
s = open(p, encoding='utf-8', newline='').read()


def rep(a, b):
    global s
    assert s.count(a) == 1, (a[:90], s.count(a))
    s = s.replace(a, b)


# 1. FANTASY view cell: VALUE (Dynasty SIM) in the L4 PPG slot on the dynasty boards
rep("""      _statTds = `<td class="pts-cell ppg25-cell"${_25Tip}${_25Color?' style="color:'+_25Color+';font-weight:700"':''}>${_25ppg!=null?_25ppg:'—'}</td>
      <td class="pts-cell l4ppg-cell"${_l4Cell.color?' style="color:'+_l4Cell.color+';font-weight:700"':''}>${_l4Cell.html}</td>`;
    } else if (_statMode === 'sims') {""",
"""      // DYNASTY boards (Jack 2026-10-09): VALUE (Dynasty SIM) replaces L4 PPG.
      let _l4Td = `<td class="pts-cell l4ppg-cell"${_l4Cell.color?' style="color:'+_l4Cell.color+';font-weight:700"':''}>${_l4Cell.html}</td>`;
      if (_isDynSimMode()) {
        const _dv = window.DYNASTY_SIM_2026 ? _dynSimFor(d) : null;
        const _dvc = v => v >= 300 ? '#22c55e' : v >= 150 ? '#4ade80' : v >= 50 ? '#facc15' : 'var(--text2)';
        _l4Td = !window.DYNASTY_SIM_2026 ? '<td class="pts-cell l4ppg-cell" style="color:var(--text2)">…</td>'
          : !_dv ? '<td class="pts-cell l4ppg-cell" style="color:var(--text2)">—</td>'
          : _dynLocked(_dv) ? '<td class="pts-cell l4ppg-cell"><span class="cons-lock" aria-label="Premium" title="' + _DYN_LOCK_TIP + '">🔒</span></td>'
          : `<td class="pts-cell l4ppg-cell" title="Dynasty SIM #${_dv.rk} — 3-season window ${_dv.win3} + youth credit ${_dv.youth} (open DYN SIM for the season split and comparables)" style="color:${_dvc(_dv.val)};font-weight:700;cursor:help">${_dv.val}</td>`;
      }
      _statTds = `<td class="pts-cell ppg25-cell"${_25Tip}${_25Color?' style="color:'+_25Color+';font-weight:700"':''}>${_25ppg!=null?_25ppg:'—'}</td>
      ${_l4Td}`;
    } else if (_statMode === 'sims') {""")
# 2. header label in FANTASY on the dynasty boards
rep("""    _set(c3, 'l4ppgHeader', 'Average fantasy PPG over the player\\'s last 4 games PLAYED — 2026 games to date, then the end of 2025 (refreshed after every game). Compared to the season PPG column it shows which way a player is trending: ▲ = trending up, ▼ = trending down.', 'L4 PPG', fmtLabel);""",
"""    if (_isDynSimMode()) _set(c3, 'l4ppgHeader', 'Dynasty SIM value — expected points over a replacement starter for the rest of this season and the next two, plus a youth credit for the seasons after (' + (currentMode === 'dynastysf' ? 'superflex' : '1QB') + ', follows the scoring toggle). Same number as the player card\\'s OUR VALUE and the DYN SIM view; open DYN SIM for the season split and comparables. Free: the Dynasty SIM top 30.', 'Value', 'Dyn SIM');
    else _set(c3, 'l4ppgHeader', 'Average fantasy PPG over the player\\'s last 4 games PLAYED — 2026 games to date, then the end of 2025 (refreshed after every game). Compared to the season PPG column it shows which way a player is trending: ▲ = trending up, ▼ = trending down.', 'L4 PPG', fmtLabel);""")
# 3. sort: the L4 slot sorts by value on the dynasty boards (FANTASY view)
rep("        case 'l4ppg': if (_sm === 'trend')",
    "        case 'l4ppg': if (_sm === 'fantasy' && _isDynSimMode()) { av = _dynSortVal(a, 'val'); bv = _dynSortVal(b, 'val'); break; } if (_sm === 'trend')")
# 4. headers follow every board switch (redraft <-> dynasty swaps L4 PPG / VALUE)
rep("    if (_isDynSimMode() && typeof window._updateRnkStatHeaders === 'function') window._updateRnkStatHeaders();",
    "    if (typeof window._updateRnkStatHeaders === 'function') window._updateRnkStatHeaders();")
# 5. COLS toggle: dynasty boards show AGE (default-off in season elsewhere) and never force P-SOS back on
rep("""      const visible = _isOn(state, k);""",
"""      // DYNASTY boards (Jack 2026-10-09): AGE on, P-SOS off (SOS hides by CSS).
      const _dyn = document.body.classList.contains('format-dynasty');
      const visible = _dyn && k === 'age' ? true : _dyn && k === 'ppsos' ? false : _isOn(state, k);""")
rep("""      const forced = state[k] === true && !document.body.classList.contains('format-weekly');""",
"""      const forced = state[k] === true && !document.body.classList.contains('format-weekly') && !(_dyn && k === 'age');""")
open(p, 'w', encoding='utf-8', newline='').write(s)
print('patched app.js')

p = r'E:\MyFantasyFootball\MyFantasyFootball Files\.claude\worktrees\dyn-cols\index.html'
s = open(p, encoding='utf-8', newline='').read()
nl = '\r\n' if '\r\n' in s[:2000] else '\n'
rep('  body:not(.trend-ok) .rnk-statmode-btn[data-rnkstatmode="trend"] { display: none !important; }',
    '  body:not(.trend-ok) .rnk-statmode-btn[data-rnkstatmode="trend"] { display: none !important; }' + nl +
    '  /* DYNASTY boards (Jack 2026-10-09): no SOS / P-SOS — schedule strength is a this-season read. */' + nl +
    '  body.format-dynasty #pageRankings #psosHeader, body.format-dynasty #pageRankings .psos-cell,' + nl +
    '  body.format-dynasty #pageRankings #ppsosHeader, body.format-dynasty #pageRankings .ppsos-cell { display: none !important; }')
open(p, 'w', encoding='utf-8', newline='').write(s)
print('patched index.html')
