// Cloudflare Worker: late-wind-6322.billingsj199.workers.dev
// Proxy for the admin-only AI trivia builder (app.js _triviaGenerate).
//
// Paste into the worker in the Cloudflare dashboard (Workers & Pages ->
// late-wind-6322 -> Edit code) and keep the Anthropic key as a secret named
// ANTHROPIC_API_KEY (Settings -> Variables and Secrets; rename below if the
// existing secret uses a different name).
//
// Before 2026-10-28 the worker forwarded any POST, so anyone who read the URL
// out of app.js could spend the API key. Now a request must:
//   1. come from the site's origin,
//   2. carry a Firebase ID token for the admin account (verified here
//      against Google's public keys - no Firebase SDK needed), and
//   3. stay inside a model / max_tokens / tool allowlist.
// Raw fetch rather than the Anthropic SDK: the dashboard editor has no build
// step, and this only forwards one Messages request.

const FIREBASE_PROJECT = 'jackb933-website';
const ADMIN_EMAIL = 'billingsj199@gmail.com';
const ALLOWED_ORIGINS = ['https://www.myfantasyfootball.co', 'https://myfantasyfootball.co'];
const ALLOWED_MODELS = ['claude-sonnet-5-5', 'claude-opus-5-5'];
const ALLOWED_TOOL_TYPES = ['web_search_20250305', 'web_search_20260209'];
const MAX_TOKENS_CAP = 16000;
const WEB_SEARCH_MAX_USES = 8;
const JWKS_URL = 'https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com';

let _jwks = null;
let _jwksAt = 0;

export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin') || '';
    const cors = {
      'Access-Control-Allow-Origin': ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0],
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      'Access-Control-Max-Age': '86400',
      'Vary': 'Origin',
    };
    const reply = (status, obj) => new Response(JSON.stringify(obj), {
      status, headers: { ...cors, 'Content-Type': 'application/json' },
    });

    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
    if (request.method !== 'POST') return reply(405, { error: 'method not allowed' });
    if (!ALLOWED_ORIGINS.includes(origin)) return reply(403, { error: 'origin not allowed' });

    const auth = request.headers.get('Authorization') || '';
    const claims = auth.startsWith('Bearer ') ? await verifyFirebaseToken(auth.slice(7)).catch(() => null) : null;
    if (!claims) return reply(401, { error: 'sign in required' });
    if (claims.email !== ADMIN_EMAIL || claims.email_verified !== true) return reply(403, { error: 'admin only' });

    let body;
    try { body = await request.json(); } catch (_) { return reply(400, { error: 'bad json' }); }
    if (!ALLOWED_MODELS.includes(body.model)) return reply(400, { error: 'model not allowed' });
    if (!Array.isArray(body.messages) || !body.messages.length) return reply(400, { error: 'messages required' });

    const tools = (Array.isArray(body.tools) ? body.tools : [])
      .filter(t => t && ALLOWED_TOOL_TYPES.includes(t.type))
      .map(t => ({ type: t.type, name: 'web_search', max_uses: WEB_SEARCH_MAX_USES }));
    const out = {
      model: body.model,
      max_tokens: Math.max(1, Math.min(Number(body.max_tokens) || 4096, MAX_TOKENS_CAP)),
      messages: body.messages,
    };
    if (typeof body.system === 'string') out.system = body.system;
    if (tools.length) out.tools = tools;

    const resp = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'x-api-key': env.ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
      },
      body: JSON.stringify(out),
    });
    return new Response(resp.body, {
      status: resp.status,
      headers: { ...cors, 'Content-Type': 'application/json' },
    });
  },
};

// Firebase ID tokens are RS256 JWTs signed by securetoken@system. Checks the
// signature plus the claims Firebase documents for server-side verification.
async function verifyFirebaseToken(token) {
  const parts = token.split('.');
  if (parts.length !== 3) throw new Error('malformed');
  const header = JSON.parse(b64urlText(parts[0]));
  const payload = JSON.parse(b64urlText(parts[1]));
  if (header.alg !== 'RS256' || !header.kid) throw new Error('bad header');

  const now = Math.floor(Date.now() / 1000);
  if (payload.aud !== FIREBASE_PROJECT) throw new Error('bad aud');
  if (payload.iss !== 'https://securetoken.google.com/' + FIREBASE_PROJECT) throw new Error('bad iss');
  if (!payload.sub || typeof payload.sub !== 'string') throw new Error('bad sub');
  if (!(payload.exp > now) || !(payload.iat <= now + 300) || !(payload.auth_time <= now + 300)) throw new Error('expired');

  const jwk = (await getJwks()).find(k => k.kid === header.kid);
  if (!jwk) throw new Error('unknown kid');
  const key = await crypto.subtle.importKey('jwk', jwk, { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify']);
  const ok = await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, b64urlBytes(parts[2]),
    new TextEncoder().encode(parts[0] + '.' + parts[1]));
  if (!ok) throw new Error('bad signature');
  return payload;
}

async function getJwks() {
  if (_jwks && Date.now() - _jwksAt < 3600 * 1000) return _jwks;
  const r = await fetch(JWKS_URL);
  if (!r.ok) throw new Error('jwks fetch failed');
  _jwks = (await r.json()).keys || [];
  _jwksAt = Date.now();
  return _jwks;
}

function b64urlBytes(s) {
  const b = atob(s.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((s.length + 3) % 4));
  return Uint8Array.from(b, c => c.charCodeAt(0));
}
function b64urlText(s) {
  return new TextDecoder().decode(b64urlBytes(s));
}
