"""One-off patch: VOR bar in the DYN SIM view + header label (dyn-picks worktree)."""
p = r'E:\MyFantasyFootball\MyFantasyFootball Files\.claude\worktrees\dyn-picks\app.js'
s = open(p, encoding='utf-8', newline='').read()


def rep(a, b):
    global s
    assert s.count(a) == 1, (a[:90], s.count(a))
    s = s.replace(a, b)


rep("  document.body.classList.toggle('vor-bar-on', currentVersion === 'sims' || _statMode === 'vor');",
    "  document.body.classList.toggle('vor-bar-on', currentVersion === 'sims' || _statMode === 'vor' || _statMode === 'dyn');")
# header sub-label: league / custom lineup when DYN SIM is league-priced
rep("'SIM DYN', _f + ' ' + ({ ppr: 'PPR', half: 'HALF', std: 'STD' }[rankingScoringFmt] || 'PPR') + (_dynTep ? ' TEP' : ''));",
    "'SIM DYN', (function () { const c = _dynLeagueCtx(); return c ? (c.lg ? 'League' : 'Custom') : _f; })() + ' ' + ({ ppr: 'PPR', half: 'HALF', std: 'STD' }[rankingScoringFmt] || 'PPR') + (_dynTepEff() ? ' TEP' : ''));")
rep("' 12-team ' + fmtLabel + (_dynTep ? ' with a +' + _dynTep + ' TE premium per reception' : '') + ', ' + _f + ' replacement levels.",
    "(function () { const c = _dynLeagueCtx(); return c ? ' Priced for ' + (c.lg ? (c.lg.name || 'your league') : 'the custom lineup') + ' in the VOR bar (' + c.st.teams + ' teams, ' + c.st.QB + ' QB / ' + c.st.RB + ' RB / ' + c.st.WR + ' WR / ' + c.st.TE + ' TE / ' + c.st.FLEX + ' FLEX' + (+c.st.SF ? ' / ' + c.st.SF + ' SF' : '') + '): each season is re-priced against that league\\'s replacement level from the player\\'s range of comparable outcomes. ' : ' 12-team '; })() + fmtLabel + (_dynTepEff() ? ' with a +' + _dynTepEff() + ' TE premium per reception' : '') + (_dynLeagueCtx() ? '.' : ', ' + _f + ' replacement levels.') + '")
open(p, 'w', encoding='utf-8', newline='').write(s)
print('patched app.js')

p = r'E:\MyFantasyFootball\MyFantasyFootball Files\.claude\worktrees\dyn-picks\index.html'
s = open(p, encoding='utf-8', newline='').read()
nl = '\r\n' if '\r\n' in s[:2000] else '\n'
rep('body.vor-bar-on .vor-bar{display:flex}',
    'body.vor-bar-on .vor-bar{display:flex}' + nl +
    '/* DYN SIM view: the VOR bar sets the league / lineup only — weekly window, playoffs,' + nl +
    '   upside, waivers, K / D/ST / bench do not apply to dynasty values. */' + nl +
    'body[data-rnk-stat="dyn"] .vor-bar .vor-win, body[data-rnk-stat="dyn"] .vor-bar .vor-po,' + nl +
    'body[data-rnk-stat="dyn"] #vorPlayoffBtn, body[data-rnk-stat="dyn"] #vorUpsideBtn, body[data-rnk-stat="dyn"] #vorWaiverBtn,' + nl +
    'body[data-rnk-stat="dyn"] .vor-bar .vor-num:has(input[data-vor="K"]), body[data-rnk-stat="dyn"] .vor-bar .vor-num:has(input[data-vor="DST"]),' + nl +
    'body[data-rnk-stat="dyn"] .vor-bar .vor-num:has(input[data-vor="BN"]){display:none!important}')
open(p, 'w', encoding='utf-8', newline='').write(s)
print('patched index.html')
