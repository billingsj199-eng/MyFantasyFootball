// verify_learned_shadow.js - checks engine.js's LightGBM evaluator reproduces Python's predictions on the saved
// test vectors (learned_shadow_testvec.json from build_learned_shadow.py). Run: node verify_learned_shadow.js
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm');
global.window = global;
['data/learned_shadow_model.js', 'engine.js'].forEach(f => vm.runInThisContext(fs.readFileSync(path.join(__dirname, f), 'utf8'), { filename: f }));
const E = global.SimEngine, M = global.SIM_LEARNED_SHADOW;
const V = JSON.parse(fs.readFileSync(path.join(__dirname, 'learned_shadow_testvec.json'), 'utf8'));
if (V.features.join('|') !== M.features.join('|')) { console.error('feature order mismatch'); process.exit(1); }
let worst = 0;
V.rows.forEach((r, i) => { const js = E.lgbPredict(M, r.map(v => (v == null ? NaN : v))); worst = Math.max(worst, Math.abs(js - V.pred[i])); });
console.log(`rows ${V.rows.length} | trees ${M.trees.length} | max |JS - Python| ${worst.toExponential(2)}`);
process.exit(worst < 1e-4 ? 0 : 1);
