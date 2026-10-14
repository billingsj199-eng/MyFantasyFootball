"""One-off patch: AUG '27 expected market value column in the dynasty TRENDS view (mkt-next worktree)."""
p = r'E:\MyFantasyFootball\MyFantasyFootball Files\.claude\worktrees\mkt-next\app.js'
s = open(p, encoding='utf-8', newline='').read()


def rep(a, b):
    global s
    assert s.count(a) == 1, (a[:90], s.count(a))
    s = s.replace(a, b)


rep("  const showLanding = _isAdpCmp || (_isDynBoard && filter === 'ROOKIE');",
    "  const showLanding = _isAdpCmp || (_isDynBoard && filter === 'ROOKIE') || (_statMode === 'trend' && _trendIsDyn());")
rep("    let _statJmCell = null; // VOR season view: GMS rides the JM column",
    "    let _statJmCell = null; // VOR season view: GMS rides the JM column\n"
    "    let _statLandingCell = null; // dynasty TRENDS: AUG '27 expected market value rides the Landing column")
# landing cell content override
i = s.index('      <td class="pts-cell landing-cell${_isAdpCmp ? _adpCmpAvgCellCls(d) : \'\'}" style="display:none">${')
j = i + len('      <td class="pts-cell landing-cell${_isAdpCmp ? _adpCmpAvgCellCls(d) : \'\'}" style="display:none">${')
s = s[:j] + "_statLandingCell != null ? _statLandingCell : " + s[j:]
# fill it in the TRENDS branch (after the SIM GAP cell)
rep("""          _statJmCell = `<span title="${tip}" style="cursor:help;font-weight:700;color:${col}">${g.call || (g.sp < g.kp ? '+' : g.sp > g.kp ? '−' : '') + Math.abs(g.kp - g.sp)}</span>`;
        }""",
"""          _statJmCell = `<span title="${tip}" style="cursor:help;font-weight:700;color:${col}">${g.call || (g.sp < g.kp ? '+' : g.sp > g.kp ? '−' : '') + Math.abs(g.kp - g.sp)}</span>`;
        }
        if (g && g.mkt && !_dynLocked(g.x)) {
          const mk = g.mkt, edge = mk.chg - mk.peer;
          const pct = v => (v >= 0 ? '+' : '−') + Math.abs(Math.round(v * 100)) + '%';
          const col = edge >= 0.05 ? '#22c55e' : edge <= -0.05 ? '#ef4444' : 'var(--text2)';
          const tip = ('Expected KTC value by next preseason (Aug 2027): about ' + Math.round(mk.val).toLocaleString() + ' (now ' + Math.round(mk.cur).toLocaleString() + ', ' + pct(mk.chg) + ')' + (mk.ovr ? ' — around KTC #' + mk.ovr + ' today\\'s scale.' : ' — out of the KTC top 200.')
            + ' Typical for his KTC rank: ' + pct(mk.peer) + ', so ' + (Math.abs(edge) < 0.05 ? 'in line with his rank.' : pct(edge) + (edge > 0 ? ' better' : ' worse') + ' than peers.')
            + ' Most values fall a year out because a new rookie class slots in ahead and older players slide; the color is the part beyond that. Model: market rank, Dynasty SIM rank, rookie, position and age by position, fit on 2015-23 dynasty ADP (next-year rank Spearman .70 vs .66 for no change; .26 on who beats his rank\\'s drift).').replace(/"/g, '&quot;');
          _statLandingCell = `<span title="${tip}" style="cursor:help;font-weight:700;color:${col}">${pct(mk.chg)}</span>`;
        } else if (g && g.mkt) {
          _statLandingCell = '<span class="cons-lock" aria-label="Premium" title="' + _DYN_LOCK_TIP + '">🔒</span>';
        } else {
          _statLandingCell = '<span style="color:var(--text2)" title="Needs a Dynasty SIM value and a KTC top-200 rank">—</span>';
        }""")
# header relabel
rep("    } else if (_statMode === 'trend' && _trendIsDyn() && id === 'jmHeader') {",
    "    } else if (_statMode === 'trend' && _trendIsDyn() && id === 'landingHeader') {\n"
    "      sp.innerHTML = 'AUG \\'27 ';\n"
    "      sp.setAttribute('data-gloss', 'Expected KTC value change by next preseason (August 2027). Predicted from his KTC rank, Dynasty SIM rank, rookie status, position and age by position — fit on 2015-23 dynasty ADP, where it ranked next year\\'s market better than \"no change\" (.70 vs .66). Most values fall a year out (a new rookie class slots in, older players slide); green / red = better / worse than the typical change for his current rank by 5%+, the part the model adds (.26 Spearman on who beats his rank\\'s drift). Free: Dynasty SIM top 30.');\n"
    "    } else if (_statMode === 'trend' && _trendIsDyn() && id === 'jmHeader') {")
# sort
rep("        case 'landing': if (_sm === 'adp')",
    "        case 'landing': if (_sm === 'trend') { av = _trendSortVal(a, 'mkt'); bv = _trendSortVal(b, 'mkt'); break; } if (_sm === 'adp')")
open(p, 'w', encoding='utf-8', newline='').write(s)
print('patched')
