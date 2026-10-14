"""One-off patch: wire the TRENDS stats view into app.js (rank-trends worktree)."""
p = r'E:\MyFantasyFootball\MyFantasyFootball Files\.claude\worktrees\rank-trends\app.js'
s = open(p, encoding='utf-8', newline='').read()


def rep(a, b):
    global s
    assert s.count(a) == 1, (a[:90], s.count(a))
    s = s.replace(a, b)


# sorts
rep("        case 'pts': if (_sm === 'dyn')",
    "        case 'pts': if (_sm === 'trend') { av = _trendSortVal(a, 'now'); bv = _trendSortVal(b, 'now'); break; } if (_sm === 'dyn')")
rep("        case 'fpts25': if (_sm === 'dyn')",
    "        case 'fpts25': if (_sm === 'trend') { av = _trendSortVal(a, 'd7'); bv = _trendSortVal(b, 'd7'); break; } if (_sm === 'dyn')")
rep("        case 'l4ppg': if (_sm === 'dyn')",
    "        case 'l4ppg': if (_sm === 'trend') { av = _trendSortVal(a, 'd30'); bv = _trendSortVal(b, 'd30'); break; } if (_sm === 'dyn')")
rep("        case 'yrr': if (_sm === 'dyn')",
    "        case 'yrr': if (_sm === 'trend') { av = _trendSortVal(a, 'd30'); bv = _trendSortVal(b, 'd30'); break; } if (_sm === 'dyn')")
rep("        case 'jm': if (_sm === 'vor')",
    "        case 'jm': if (_sm === 'trend') { av = _trendSortVal(a, 'gap'); bv = _trendSortVal(b, 'gap'); break; } if (_sm === 'vor')")
# body class for the TRENDS button
rep("  document.body.classList.toggle('format-dynasty', _isDynSimMode());   // DYN SIM button (prototype)",
    "  document.body.classList.toggle('format-dynasty', _isDynSimMode());   // DYN SIM button (prototype)\n"
    "  document.body.classList.toggle('trend-ok', _isTrendMode());          // TRENDS button")
# tail column visible + label
rep("const _yrrShow = showYrr || _adpCmpMode || _statMode === 'xfp' || _statMode === 'dyn' ||",
    "const _yrrShow = showYrr || _adpCmpMode || _statMode === 'xfp' || _statMode === 'dyn' || _statMode === 'trend' ||")
rep("yrrH.childNodes[0].textContent = _statMode === 'dyn' ? 'SIM RK ' :",
    "yrrH.childNodes[0].textContent = _statMode === 'trend' ? 'TREND ' : _statMode === 'dyn' ? 'SIM RK ' :")
# JM header doubles as SIM GAP on the dynasty TRENDS view
rep("    } else if (_vorSeasonCols && id === 'jmHeader') {",
    "    } else if (_statMode === 'trend' && _trendIsDyn() && id === 'jmHeader') {\n"
    "      sp.innerHTML = 'SIM GAP ';\n"
    "      sp.setAttribute('data-gloss', 'Dynasty SIM rank vs KTC rank among the players both rank (KTC top 200). BUY = the fifth the sim likes most beyond KTC, SELL = the fifth KTC likes most beyond the sim; otherwise the spots between the two ranks (+ = the sim has him higher). 2015-23 backtest: the market moved toward the sim the next year (t 7.4 holding market rank fixed) and the BUY fifth out-produced its market-rank peers by +27 three-year VOR while SELL ran -20. Free: players in the Dynasty SIM top 30.');\n"
    "    } else if (_vorSeasonCols && id === 'jmHeader') {")
# header labels
rep("  } else if (rnkStatMode === 'dyn') {",
    "  } else if (rnkStatMode === 'trend') {\n"
    "    const _src = _trendIsDyn() ? 'KTC' : 'Consensus';\n"
    "    const _H = _trendIsDyn() ? window.KTC_HISTORY : window._consRankHist;\n"
    "    const _since = _H && (_H.dates || (_H.days || []).map(x => x.date)).slice().sort()[0];\n"
    "    const _how = _trendIsDyn()\n"
    "      ? 'KeepTradeCut ' + (currentMode === 'dynastysf' ? 'Superflex' : '1QB') + ' rank (draft picks excluded), from the daily KTC values the site has stored since ' + (_since || 'June') + '.'\n"
    "      : 'The consensus board (the CONS column) rebuilt from the daily snapshots of its sources since ' + (_since || 'August') + ' — the same history as the RANKINGS MOVERS bar.';\n"
    "    _set(c1, null, _src + ' rank today. ' + _how + ' The sub-line is the 30-day change.', 'NOW', _src);\n"
    "    _set(c2, 'ppg25Header', 'Spots gained (▲) or lost (▼) in the ' + _src + ' rank over the last 7 days. ' + _how, '7D', 'Rank');\n"
    "    _set(c3, 'l4ppgHeader', 'Spots gained (▲) or lost (▼) in the ' + _src + ' rank over the last 30 days. In the 2015-23 dynasty backtest a player\\'s past market move did not predict his next one (Spearman -.02) — use it as context.', '30D', 'Rank');\n"
    "  } else if (rnkStatMode === 'dyn') {")
# stats button: load history first
rep("    if (rnkStatMode === 'dyn' && !window.DYNASTY_SIM_2026) {",
    "    if (rnkStatMode === 'trend' && !(_trendIsDyn() ? (window.KTC_HISTORY && window.DYNASTY_SIM_2026) : window._consRankHist)) {\n"
    "      _trendEnsure(() => { if (rnkStatMode === 'trend') { window._updateRnkStatHeaders(); render(); } });\n"
    "      return;\n"
    "    }\n"
    "    if (rnkStatMode === 'dyn' && !window.DYNASTY_SIM_2026) {")
# mode switch: leave TRENDS when the board has no history; reload history for the new board
rep("    if (!_isDynSimMode() && rnkStatMode === 'dyn') {",
    "    document.body.classList.toggle('trend-ok', _isTrendMode());\n"
    "    if (rnkStatMode === 'trend') {\n"
    "      if (!_isTrendMode()) {\n"
    "        rnkStatMode = 'fantasy';\n"
    "        document.querySelectorAll('.rnk-statmode-btn').forEach(b => b.classList.toggle('active', b.dataset.rnkstatmode === 'fantasy'));\n"
    "      } else {\n"
    "        _trendEnsure(() => { if (rnkStatMode === 'trend') { window._updateRnkStatHeaders(); render(); } });\n"
    "      }\n"
    "    }\n"
    "    if (!_isDynSimMode() && rnkStatMode === 'dyn') {")
open(p, 'w', encoding='utf-8', newline='').write(s)
print('patched app.js')
