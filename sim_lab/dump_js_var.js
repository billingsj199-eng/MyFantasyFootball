// dump_js_var.js <file> <varName> -> prints JSON of the variable after evaluating the file under a window shim
'use strict';
const fs = require('fs'), vm = require('vm');
global.window = global;
vm.runInThisContext(fs.readFileSync(process.argv[2], 'utf8'), { filename: process.argv[2] });
process.stdout.write(JSON.stringify(global[process.argv[3]] !== undefined ? global[process.argv[3]] : vm.runInThisContext(process.argv[3])));
