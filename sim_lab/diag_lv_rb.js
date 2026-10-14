'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm');
global.window = global;
const log = console.log; console.log = () => {}; console.warn = () => {};
const src = fs.readFileSync(path.join(__dirname, 'export_site_proj.js'), 'utf8');
const files = eval(src.match(/\[\s*'data\/mike_clay_projections\.js'[\s\S]*?'engine\.js'\s*\]/)[0]).filter(f => f !== 'data/sim_future_totals.js');
files.forEach(f => vm.runInThisContext(fs.readFileSync(path.join(__dirname, f), 'utf8'), { filename: f }));
const E = global.SimEngine;
const schedule = E.buildSchedule(), players = E.buildPlayers(schedule);
E.applyInSeasonInjuries(players, 5, { active: true });
players.list.filter(p => p.tm === 'LV' && ['RB','TE','WR'].includes(p.pos)).forEach(p => {
  const c = p.comps || {}, div = p.qbWindow ? (p.qbWindow.games || 17) : (p.clayGames || 17);
  log(p.name, p.pos, 'div', div, 'ptsPPR/g', ((p.ptsPPR||0)/div).toFixed(2), 'car/g', ((c.ry||0)/4.3/div).toFixed(1), 'tgt/g', ((c.rec||0)/0.77/div).toFixed(1),
      'ppc', c.ry ? (((c.ry*0.1+(c.rtd||0)*6)/div)/((c.ry/4.3)/div)).toFixed(2) : '-', 'injPlay5', E.injPlay ? E.injPlay(p,5) : '?');
});
const sc = E.PRESETS.ppr || E.PRESETS.full || E.PRESETS.half;
log('preset keys', Object.keys(E.PRESETS));
const pick = n => players.list.find(p => p.name === n);
const show = tag => ['Ashton Jeanty','Mike Washington Jr.','Dylan Laube','Brock Bowers','Michael Mayer','Tre Tucker'].forEach(n => { const p = pick(n); if (!p) return log(tag, n, 'missing'); const w = E.weeklyProjection(p, 5, sc, schedule); log(tag, n, w && (w.mean != null ? w.mean.toFixed(2) : JSON.stringify(w).slice(0,200)), w && w.src); });
E.applyInSeasonInjuries(players, 5, { active: true }); show('BASE');
E.applyInSeasonInjuries(players, 5, { active: true, force: { 'Ashton Jeanty': 'out' } }); show('JEANTY OUT');
{ const p = pick('Mike Washington Jr.'); const w = E.weeklyProjection(p, 5, sc, schedule); const o={};for(const k in w){if(typeof w[k]!=="object")o[k]=w[k]};log(JSON.stringify(o)); log("bookCapped",p._bookCapped); log('adj', JSON.stringify((E.injState ? E.injState() : {}) ).slice(0,100)); }
global.SIM_BOOK_CAP = false;
E.applyInSeasonInjuries(players, 5, { active: true, force: { 'Ashton Jeanty': 'out' } });
['Mike Washington Jr.','Brock Bowers','Michael Mayer','Tre Tucker'].forEach(n => { const p = pick(n); const w = E.weeklyProjection(p, 5, sc, schedule); log('NOCAP JEANTY OUT', n, 'eff', E.effMean(w).toFixed(2), 'nc', w.ncMean && w.ncMean.toFixed(2), 'propW', w.propW); });
global.SIM_BOOK_CAP = true;
E.applyInSeasonInjuries(players, 5, { active: true });
['Mike Washington Jr.','Brock Bowers','Michael Mayer','Tre Tucker'].forEach(n => { const p = pick(n); const w = E.weeklyProjection(p, 5, sc, schedule); log('BASE eff', n, E.effMean(w).toFixed(2), 'nc', w.ncMean && w.ncMean.toFixed(2), 'capped', p._bookCapped); });
E.applyInSeasonInjuries(players, 5, { active: true, force: { 'Ashton Jeanty': 'out' } });
['Mike Washington Jr.','Brock Bowers','Michael Mayer','Tre Tucker'].forEach(n => { const p = pick(n); const w = E.weeklyProjection(p, 5, sc, schedule); log('OUT eff', n, E.effMean(w).toFixed(2), 'nc', w.ncMean && w.ncMean.toFixed(2), 'capped', p._bookCapped, w.ncSrc); });
