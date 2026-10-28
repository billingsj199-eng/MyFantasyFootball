// Daily Trivia — write the locked board to Firestore trivia_daily/{date}
// through the lockTriviaDaily Cloud Function (functions/index.js in
// E:\MyFantasyFootball). The function holds the Admin SDK; this PC only
// holds the export feed key (outside the repo, the same file the Jack's-board
// exporters send as x-export-key) that the function compares against its
// EXPORT_FEED_KEY secret. No Google credentials live on disk.
'use strict';

const fs = require('fs');

const LOCK_URL = process.env.MFF_TRIVIA_LOCK_URL || 'https://us-central1-jackb933-website.cloudfunctions.net/lockTriviaDaily';
const KEY_FILE = process.env.MFF_TRIVIA_LOCK_KEY_FILE || 'E:\\MyFantasyFootball\\secrets\\export_feed_key.txt';

function readKey() {
  if (!fs.existsSync(KEY_FILE)) throw new Error('lock key file missing: ' + KEY_FILE);
  const k = fs.readFileSync(KEY_FILE, 'utf8').trim();
  if (k.length < 16) throw new Error('lock key file looks wrong (too short)');
  return k;
}

async function postLock(doc) {
  const key = readKey();
  const r = await fetch(LOCK_URL, { method: 'POST', headers: { 'content-type': 'application/json', 'x-export-key': key }, body: JSON.stringify({ doc }) });
  let body = null;
  try { body = await r.json(); } catch (_) { body = { error: 'non-JSON response', status: r.status }; }
  return { status: r.status, body };
}

module.exports = { postLock, LOCK_URL, KEY_FILE };
