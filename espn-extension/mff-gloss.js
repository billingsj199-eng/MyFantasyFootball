/* MFF helper glossary (X-20261121-32). The same file ships in all four helpers so every tag, chip and
 * column means the same thing everywhere.
 *  - Tooltips: set lazily on hover (one delegated listener, nothing added to the render path).
 *  - Legend: the "?" button in the sidebar header opens the list below as a small panel.
 * Display only: it never reads or changes picks, ranks, projections or sims. */
(function () {
  'use strict';
  if (window.__mffGloss) return;

  // key -> [label shown in the legend, plain-words meaning]
  var T = {
    top: ['Green card', 'The helper’s #1 recommended pick right now.'],
    score: ['Pick score', 'The number on the right of a recommended player: value, roster need, tiers and ADP rolled into one. Higher = better pick right now. In the full player list it is the value you sorted by.'],
    vor: ['VOR', 'Value over replacement: projected points above a replacement-level starter at the same position. Bigger = more valuable.'],
    adp: ['ADP', 'Average draft position: where drafters usually take this player.'],
    ppg: ['PPG', 'Projected fantasy points per game, in this league’s scoring.'],
    tier: ['Tier', 'A group of similarly valued players at one position. The next tier down is a real drop.'],
    tiercliff: ['TIER!', 'Tier cliff: a big drop in VOR to the next few players at this position. Take one now or wait a long time.'],
    jacktier: ['S / A / B / C / D / E', 'Jack’s tier grades, best to worst: S (elite), then A through E.'],
    bob: ['Best on board', 'The highest-rated player still available.'],
    need: ['NEED', 'You still need a starter at this position.'],
    open: ['Open slot', 'This player would fill an empty starting spot on your roster.'],
    needsvalue: ['Needs value', 'Your roster is short on quality at this position, so this pick gets a boost.'],
    cliff: ['Cliff', 'How much worse the next-best player at this position is. A big number means do not wait.'],
    scoring: ['Scoring +/−', 'This league’s scoring settings move this player up or down by this many points per game compared with standard scoring.'],
    steal: ['STEAL ($$)', 'Still available 2 or more rounds after their ADP.'],
    value: ['Value ($)', 'Still available about a round after their ADP.'],
    stretch: ['Stretch', 'About a round earlier than their ADP.'],
    reach: ['Reach', '20 or more picks earlier than their ADP.'],
    wait: ['WAIT', 'ADP says this player should still be there at your next pick, so you can take someone scarcer first.'],
    stack: ['STACK (blue)', 'A QB and a pass catcher from the same NFL team. Their big weeks come together.'],
    bringback: ['BB (bring-back)', 'A player on the team your stack plays in a fantasy playoff week. If that game is high-scoring, both sides score.'],
    w1517: ['W15-17', 'Matchups in the fantasy playoff weeks 15-17. Pale = easier, orange = harder.'],
    w1617: ['W16 / W17 outline', 'Two of your players meet in a week 16 or 17 game.'],
    sos: ['SOS', 'Strength of schedule: how tough the opposing defenses are for this position.'],
    dome: ['Ⓓ', 'The game is played in a dome (no weather).'],
    boom: ['▲ boom / ▼ bust', 'Chance of a big week (▲) and of a dud week (▼), from the weekly sim.'],
    port: ['Port %', 'Portfolio exposure: the share of your synced drafts that already have this player.'],
    udadp: ['UD', 'This player’s current ADP on Underdog.'],
    adpmove: ['↑ / ↓ ADP', 'How far this player’s ADP has moved over the ADP movement window you picked in Settings.'],
    jm: ['JM', 'Jack’s prospect-model score and grade for the player.'],
    age: ['Age', 'The player’s age in years.'],
    bye: ['Bye', 'The week this player’s NFL team does not play.'],
    jack: ['Jack’s', 'Jack’s rankings from MyFantasyFootball, in this league’s format.'],
    fp: ['FP', 'FantasyPros expert consensus rank.'],
    slpr: ['SLPR', 'Sleeper’s own rank.'],
    espnrank: ['ESPN #', 'ESPN’s own rank for this player in the draft room.'],
    ktc: ['KTC', 'KeepTradeCut dynasty trade value.'],
    pk: ['PK', 'Draft picks (rookie and future picks) instead of players.'],
    fmt: ['SF / 1QB', 'Superflex (SF) leagues can start a second QB in a flex spot; 1QB leagues start one.'],
    ppr: ['PPR / ½PPR / STD', 'Points per reception: 1 (PPR), 0.5 (½PPR) or 0 (STD). paTD = points per passing touchdown.'],
    flex: ['FLEX / SFLX', 'FLEX takes a RB, WR or TE. SFLX (superflex) also takes a QB.'],
    inj: ['Q / OUT', 'Injury status: Q = questionable for this week, OUT = will not play.'],
    lineupplus: ['LINEUP +', 'Adding this player would raise your best starting lineup by this many points per game.'],
    depth: ['DEPTH', 'Would not start for you this week: a bench add.'],
    adds: ['🔥 adds', 'How many leagues added this player in the last day.'],
    live: ['● live / ✓ final', 'Points scored so far in a game in progress (●) or a finished game (✓).'],
    swapgain: ['Start / Sit +', 'How many more projected points the suggested starter is expected to score than the player he replaces.'],
    tossup: ['≈ Toss-up', 'Two players projected within a point or so of each other: either is fine.'],
    simrec: ['Rec', 'Projected final record (wins-losses).'],
    simpf: ['PF', 'Points for: projected total points scored.'],
    simpo: ['PO', 'Chance of making the playoffs.'],
    simtitle: ['Title', 'Chance of winning the championship.'],
    simfin: ['Fin', 'Most likely finishing place.'],
    simwin: ['Win', 'Chance of winning that week’s matchup.'],
    until: ['Until you', 'How many picks are left before your next turn.'],
    feed: ['LIVE', 'The helper is connected to the draft and picks update on their own.']
  };

  // [css selector or null, regex on the element text, glossary key]. First match wins.
  var RULES = [
    [null, /^(STEAL|\$\$)$/, 'steal'],
    [null, /^(Value|\$)$/, 'value'],
    [null, /^Reach$/i, 'reach'],
    [null, /^Stretch$/i, 'stretch'],
    [null, /^TIER!$/, 'tiercliff'],
    [null, /^Tier \S+ (QB|RB|WR|TE|K|DST|DEF)$/i, 'tier'],
    ['.mff-tier-sep-badge, .mff-tier-sep-label, .mff-jtier', /^(S|A|B|C|D|E|ELITE|TIER [A-E])$/i, 'jacktier'],
    [null, /^NEED \S+$/, 'need'],
    [null, /^(LAST open slot|Open \S+ slot)/i, 'open'],
    [null, /^Needs \S+ value$/i, 'needsvalue'],
    [null, /^Cliff: next/i, 'cliff'],
    [null, /^Best on board$/i, 'bob'],
    [null, /^Scoring [+\-−]/i, 'scoring'],
    [null, /^WAIT$/, 'wait'],
    [null, /^STACK\b/, 'stack'],
    [null, /^LINEUP \+/i, 'lineupplus'],
    [null, /^DEPTH$/, 'depth'],
    [null, /\badds$/i, 'adds'],
    [null, /^ADP\b/, 'adp'],
    [null, /^UD [\d.]+$/, 'udadp'],
    [null, /^Port\b/, 'port'],
    [null, /VOR/, 'vor'],
    [null, /^JM\b/, 'jm'],
    [null, /^(PPG\b.*|[\d.]+ ?ppg( · B\d+)?)$/i, 'ppg'],
    [null, /^\d{2}y$/, 'age'],
    [null, /^PLAYOFFS$/, 'w1517'],
    ['.tag', /^\+[\d.]+$/, 'swapgain'],
    [null, /\bBye \d+$/, 'bye'],
    [null, /^KTC$/, 'ktc'],
    [null, /^(JACK'S|Jack's|Jack's Rank|Jack #\d+)$/i, 'jack'],
    [null, /^(FP|FantasyPros)$/, 'fp'],
    [null, /^(SLPR|Sleeper Rank)$/, 'slpr'],
    [null, /^ESPN #\d+$/, 'espnrank'],
    ['.pos-filter', /^PK$/, 'pk'],
    ['.pl-mine', /(SF|1QB|Superflex)$/, 'fmt'],
    ['.pl-mine, .pos-filter', /(PPR|STD|paTD)/, 'ppr'],
    ['.t', /^(FLEX|FLX|SFLX|W\/R\/T|Q\/W\/R\/T)$/, 'flex'],
    [null, /^(Q|OUT)$/, 'inj'],
    ['th', /^Rec$/, 'simrec'],
    ['th', /^PF$/, 'simpf'],
    ['th', /^PO$/, 'simpo'],
    ['th', /^Title$/, 'simtitle'],
    ['th', /^(Fin|Proj fin)$/, 'simfin'],
    ['th', /^Win$/, 'simwin'],
    ['.pl-until', /./, 'until'],
    [null, /^you in \d+$/, 'until'],
    ['.badge', /^LIVE\b/, 'feed'],
    ['.score', /^\+[\d.]+$/, 'lineupplus'],
    ['.score', /^[\d.,]+$/, 'score']
  ];

  // what each helper's legend lists (only terms that helper actually shows), in reading order
  var COMMON_DRAFT = ['top', 'score', 'bob', 'tier', 'need', 'open', 'cliff', 'scoring', 'steal', 'value', 'stretch', 'reach', 'stack', 'vor', 'adp', 'ppg', 'w1517'];
  var COMMON_SEASON = ['swapgain', 'boom', 'live', 'tossup', 'lineupplus', 'depth', 'adds', 'simrec', 'simpf', 'simpo', 'simtitle', 'simfin', 'inj'];
  var SETS = {
    sleeper: { draft: COMMON_DRAFT.concat(['jm', 'jack', 'fp', 'slpr', 'ktc', 'pk', 'fmt']), season: COMMON_SEASON },
    espn: { draft: COMMON_DRAFT.concat(['jacktier', 'jm', 'jack', 'espnrank', 'fmt']), season: COMMON_SEASON },
    yahoo: { draft: COMMON_DRAFT.concat(['needsvalue', 'bye', 'jack', 'fp', 'slpr', 'fmt']), season: COMMON_SEASON },
    underdog: { draft: ['top', 'score', 'tiercliff', 'jacktier', 'steal', 'value', 'wait', 'stack', 'bringback', 'w1517', 'w1617', 'dome', 'vor', 'udadp', 'adpmove', 'ppg', 'port'], season: [] }
  };

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  function lookup(el) {
    var txt = (el.textContent || '').replace(/\s+/g, ' ').trim();
    if (!txt || txt.length > 30) return null;
    for (var i = 0; i < RULES.length; i++) {
      var r = RULES[i];
      if (r[0]) { try { if (!el.matches(r[0])) continue; } catch (e) { continue; } }
      if (r[1].test(txt)) return T[r[2]][1];
    }
    return null;
  }

  // hover: give an untitled chip its meaning. Leaves anything that already has (or sits inside) a tooltip alone.
  function onOver(root, ev) {
    var el = ev.target;
    if (!el || el.nodeType !== 1 || el === root) return;
    for (var n = el, d = 0; n && n !== root && d < 4; n = n.parentElement, d++) {
      if (n.hasAttribute('title') || n.hasAttribute('data-mff-gl')) return;
    }
    for (var m = el, k = 0; m && m !== root && k < 2; m = m.parentElement, k++) {
      if (m.children.length > 2) break;
      var tip = lookup(m);
      if (tip) { m.setAttribute('title', tip); m.setAttribute('data-mff-gl', '1'); return; }
    }
    el.setAttribute('data-mff-gl', '0');
  }

  var panel = null, panelRoot = null, watch = null;
  function closeLegend() {
    if (panel && panel.parentNode) panel.parentNode.removeChild(panel);
    panel = null; panelRoot = null;
    if (watch) { clearInterval(watch); watch = null; }
    document.removeEventListener('keydown', onKey, true);
    document.removeEventListener('mousedown', onDocDown, true);
  }
  function onKey(e) { if (e.key === 'Escape') closeLegend(); }
  function onDocDown(e) {
    if (!panel) return;
    if (panel.contains(e.target)) return;
    if (e.target && e.target.closest && e.target.closest('[data-mff-help]')) return; // the "?" button toggles itself
    closeLegend();
  }
  function rows(keys) {
    var h = '';
    for (var i = 0; i < keys.length; i++) {
      var t = T[keys[i]]; if (!t) continue;
      h += '<div class="mff-gloss-row"><b>' + esc(t[0]) + '</b><span>' + esc(t[1]) + '</span></div>';
    }
    return h;
  }
  function openLegend(root, helper) {
    closeLegend();
    var set = SETS[helper] || SETS.sleeper;
    var cs = getComputedStyle(root);
    var accent = (cs.getPropertyValue('--mff-accent') || '').trim() || (helper === 'yahoo' ? '#b388ff' : '#ffd166');
    var muted = (cs.getPropertyValue('--mff-muted') || '').trim() || '#a6a9b3';
    var r = root.getBoundingClientRect();
    var hdr = root.querySelector('#mff-header, #mffYdHead');
    var top = r.top + (hdr ? hdr.getBoundingClientRect().height : 36);
    var maxH = Math.max(220, Math.min(window.innerHeight - top - 8, Math.max(r.bottom - top, 320)));
    panel = document.createElement('div');
    panel.id = 'mff-gloss-panel';
    panel.className = 'mff-gloss';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'What the tags mean');
    panel.style.cssText = 'position:fixed;z-index:2147483647;box-sizing:border-box;overflow-y:auto;padding:8px 10px 10px;' +
      'font:12px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;border:1px solid ' + accent + ';border-top:none;' +
      'border-radius:0 0 8px 8px;box-shadow:0 8px 24px rgba(0,0,0,.5);' +
      'left:' + Math.round(r.left) + 'px;top:' + Math.round(top) + 'px;width:' + Math.round(r.width) + 'px;max-height:' + Math.round(maxH) + 'px;' +
      'background:' + (cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)' ? cs.backgroundColor : '#0e0f12') + ';color:' + (cs.color || '#e9e9ec') + ';';
    var st = '<style>#mff-gloss-panel .mff-gloss-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:4px}' +
      '#mff-gloss-panel .mff-gloss-head b{font-size:12px;letter-spacing:.5px;color:' + accent + '}' +
      '#mff-gloss-panel .mff-gloss-x{background:none;border:1px solid ' + muted + ';color:inherit;border-radius:4px;min-width:24px;height:24px;cursor:pointer;font-size:12px}' +
      '#mff-gloss-panel .mff-gloss-x:focus-visible{outline:2px solid ' + accent + ';outline-offset:1px}' +
      '#mff-gloss-panel .mff-gloss-sec{font-size:10px;letter-spacing:.8px;text-transform:uppercase;color:' + muted + ';margin:8px 0 2px}' +
      '#mff-gloss-panel .mff-gloss-row{display:flex;gap:8px;padding:3px 0;border-top:1px solid rgba(255,255,255,.07)}' +
      '#mff-gloss-panel .mff-gloss-row b{flex:0 0 92px;font-size:11px;color:' + accent + '}' +
      '#mff-gloss-panel .mff-gloss-row span{flex:1;font-size:11px}' +
      '#mff-gloss-panel .mff-gloss-foot{margin-top:8px;font-size:10px;color:' + muted + '}</style>';
    panel.innerHTML = st +
      '<div class="mff-gloss-head"><b>WHAT THE TAGS MEAN</b><button type="button" class="mff-gloss-x" aria-label="Close">✕</button></div>' +
      '<div class="mff-gloss-sec">Draft</div>' + rows(set.draft) +
      (set.season.length ? '<div class="mff-gloss-sec">Season</div>' + rows(set.season) : '') +
      '<div class="mff-gloss-foot">Tip: hover any tag or number in the helper to see what it means.</div>';
    document.body.appendChild(panel);
    panelRoot = root;
    panel.querySelector('.mff-gloss-x').addEventListener('click', closeLegend);
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('mousedown', onDocDown, true);
    // close if the sidebar goes away or is collapsed/hidden (only ticks while the legend is open)
    watch = setInterval(function () {
      if (!panelRoot || !panelRoot.isConnected || !panelRoot.getBoundingClientRect().width || panelRoot.classList.contains('collapsed')) closeLegend();
    }, 1000);
  }
  function toggleLegend(root, helper) { if (panel && panelRoot === root) closeLegend(); else openLegend(root, helper); }

  // attach(root, helper): hover tooltips + the "?" legend. Any [data-mff-help] element inside root opens it;
  // helpers with a free header get a "?" button added to the header controls.
  function attach(root, helper) {
    if (!root || root.__mffGloss) return;
    root.__mffGloss = true;
    root.addEventListener('mouseover', function (ev) { try { onOver(root, ev); } catch (e) {} });
    root.addEventListener('click', function (ev) {
      var b = ev.target && ev.target.closest && ev.target.closest('[data-mff-help]');
      if (!b || !root.contains(b)) return;
      ev.preventDefault(); ev.stopPropagation();
      toggleLegend(root, helper);
    });
    // Sleeper/ESPN headers also hold the DRAFT/SEASON switch: no room there, so their "?" sits in the footer status row.
    var ctl = root.querySelector('#mff-header .controls');
    if (ctl && !root.querySelector('#mff-header #mff-appmode') && !ctl.querySelector('[data-mff-help]')) {
      var b = document.createElement('button');
      b.id = 'mff-help';
      b.setAttribute('data-mff-help', '1');
      b.setAttribute('title', 'What the tags and numbers mean');
      b.setAttribute('aria-label', 'What the tags and numbers mean');
      b.textContent = '?';
      ctl.insertBefore(b, ctl.firstChild);
    }
  }

  window.__mffGloss = { attach: attach, lookup: lookup, terms: T, sets: SETS, close: closeLegend };
})();
