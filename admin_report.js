/**
 * adminReport — data feed for the admin-only MFF Report page (/report/).
 *
 * One auth-gated callable (Jack's verified email only) that gathers, for a
 * date range plus the equal-length period before it:
 *   - Stripe:    gross / fees / net / refunds per day (balance transactions),
 *                sales by plan (checkout sessions + subscription renewals),
 *                active subscriptions, MRR, paying members over time,
 *                recent payments.
 *   - Auth:      total accounts, signups per day, active (token refresh)
 *                1/7/30 days, sign-in providers.
 *   - Firestore: active premium by plan, gifted premium, Ask Jack questions.
 *   - GA4:       daily active users, new users, sessions, views, engagement,
 *                channels, pages, devices, key events, realtime users.
 *
 * Every section is fetched independently and returns {ok:false,error} on
 * failure so one broken source never blanks the whole page.
 *
 * Days are bucketed in America/New_York. GA4 buckets in the property's own
 * time zone.
 */

const { onCall, HttpsError } = require("firebase-functions/v2/https");
const { getFirestore } = require("firebase-admin/firestore");
const { getAuth } = require("firebase-admin/auth");
const Stripe = require("stripe");

const ADMIN_EMAIL = "billingsj199@gmail.com";
const TZ = "America/New_York";
const GA4_PROPERTY = "530487711";
const CACHE_MS = 5 * 60 * 1000;
const MAX_DAYS = 1500;

// ---------- date helpers (ET) ----------
const _dayFmt = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });
const _partsFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit",
});
function dayKey(ms) { return _dayFmt.format(new Date(ms)); }
function tzOffsetMs(ms) {
  const p = {};
  for (const x of _partsFmt.formatToParts(new Date(ms))) p[x.type] = x.value;
  const asUtc = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute, +p.second);
  return asUtc - Math.floor(ms / 1000) * 1000;
}
// ms of 00:00 ET on YYYY-MM-DD
function dayStartMs(ds) {
  const [y, m, d] = ds.split("-").map(Number);
  const utcMid = Date.UTC(y, m - 1, d);
  const guess = utcMid - tzOffsetMs(Date.UTC(y, m - 1, d, 12));
  return utcMid - tzOffsetMs(guess); // re-check at the guess (DST switch days)
}
function addDays(ds, n) {
  const [y, m, d] = ds.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + n));
  return t.toISOString().slice(0, 10);
}
function daysBetween(a, b) {
  const [y1, m1, d1] = a.split("-").map(Number);
  const [y2, m2, d2] = b.split("-").map(Number);
  return Math.round((Date.UTC(y2, m2 - 1, d2) - Date.UTC(y1, m1 - 1, d1)) / 86400000);
}
const isDs = (s) => typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s);

// ---------- small cache (per warm instance) ----------
const _cache = new Map();
async function cached(key, force, fn) {
  const hit = _cache.get(key);
  if (!force && hit && Date.now() - hit.at < CACHE_MS) return hit.val;
  const val = await fn();
  _cache.set(key, { at: Date.now(), val });
  return val;
}
async function safe(fn) {
  try { return await fn(); } catch (e) {
    console.warn("adminReport section failed:", e && (e.stack || e.message));
    return { ok: false, error: String((e && e.message) || e).slice(0, 400) };
  }
}

// ---------- Stripe ----------
async function listAll(iterable, cap) {
  const out = [];
  for await (const x of iterable) { out.push(x); if (out.length >= cap) break; }
  return out;
}
function priceOfLine(line) {
  if (!line) return null;
  if (line.price && line.price.id) return line.price.id;
  if (line.pricing && line.pricing.price_details && line.pricing.price_details.price) {
    const p = line.pricing.price_details.price;
    return typeof p === "string" ? p : p.id;
  }
  return null;
}

async function stripeSection(cfg, range, force) {
  const stripe = new Stripe(cfg.STRIPE_SECRET_KEY.value());
  const fromSec = Math.floor(dayStartMs(range.prevStart) / 1000);
  const toSec = Math.floor(dayStartMs(addDays(range.end, 1)) / 1000) - 1;
  const planOfPrice = (pid) => {
    if (pid === cfg.PRICE_IDS.monthly) return "monthly";
    if (pid === cfg.PRICE_IDS.yearly) return "yearly";
    if (pid === cfg.SEASON_PASS_PRICE_ID) return "season";
    return "other";
  };

  // Range-independent pulls (cached): every subscription + every completed checkout.
  const [subs, sessions] = await Promise.all([
    cached("stripe_subs", force, () => listAll(stripe.subscriptions.list({ status: "all", limit: 100 }), 5000)),
    cached("stripe_sessions", force, () => listAll(stripe.checkout.sessions.list({ status: "complete", limit: 100 }), 10000)),
  ]);

  const [bts, invoices] = await Promise.all([
    listAll(stripe.balanceTransactions.list({ created: { gte: fromSec, lte: toSec }, limit: 100, expand: ["data.source"] }), 20000),
    listAll(stripe.invoices.list({ created: { gte: fromSec - 3 * 86400, lte: toSec }, status: "paid", limit: 100 }), 20000),
  ]);

  // Money per day from the balance ledger.
  const daily = {};
  const bump = (ds, k, v) => { (daily[ds] = daily[ds] || { gross: 0, fees: 0, net: 0, refunds: 0, payments: 0 })[k] += v; };
  const recent = [];
  for (const bt of bts) {
    const ds = dayKey(bt.created * 1000);
    if (bt.type === "charge" || bt.type === "payment") {
      bump(ds, "gross", bt.amount); bump(ds, "fees", bt.fee); bump(ds, "net", bt.net); bump(ds, "payments", 1);
      const src = bt.source && typeof bt.source === "object" ? bt.source : null;
      recent.push({
        at: bt.created * 1000,
        amount: bt.amount,
        net: bt.net,
        email: src && src.billing_details && src.billing_details.email || src && src.receipt_email || "",
        desc: src && src.description || bt.description || "",
        pi: src && typeof src.payment_intent === "string" ? src.payment_intent : "",
      });
    } else if (bt.type === "refund" || bt.type === "payment_refund" || bt.type === "payment_failure_refund") {
      bump(ds, "refunds", -bt.amount); bump(ds, "fees", bt.fee); bump(ds, "net", bt.net);
    } else if (bt.type === "stripe_fee" || bt.type === "tax_fee") {
      bump(ds, "fees", -bt.net); bump(ds, "net", bt.net);
    } else if (bt.type === "adjustment" || bt.type === "dispute") {
      bump(ds, "refunds", -bt.amount); bump(ds, "fees", bt.fee); bump(ds, "net", bt.net);
    }
  }

  // Sales by plan: first purchases from checkout sessions, renewals from invoices.
  const byPlan = {};
  const addPlan = (ds, plan, cents) => { const o = (byPlan[ds] = byPlan[ds] || {}); o[plan] = (o[plan] || 0) + cents; };
  const newPaid = {}; // first-time paid purchases per day (count)
  const piPlan = {};
  for (const s of sessions) {
    if (s.payment_status !== "paid") continue;
    const plan = (s.metadata && s.metadata.plan) || (s.mode === "subscription" ? "subscription" : "other");
    if (typeof s.payment_intent === "string") piPlan[s.payment_intent] = plan;
    if (s.created < fromSec || s.created > toSec) continue;
    const ds = dayKey(s.created * 1000);
    addPlan(ds, plan, s.amount_total || 0);
    if (plan !== "lineskip") newPaid[ds] = (newPaid[ds] || 0) + 1;
  }
  for (const inv of invoices) {
    if (inv.billing_reason !== "subscription_cycle") continue;
    const paidAt = (inv.status_transitions && inv.status_transitions.paid_at) || inv.created;
    if (paidAt < fromSec || paidAt > toSec) continue;
    const line = inv.lines && inv.lines.data && inv.lines.data[0];
    const plan = planOfPrice(priceOfLine(line));
    addPlan(dayKey(paidAt * 1000), plan + "_renewal", inv.amount_paid || 0);
  }
  for (const r of recent) if (r.pi && piPlan[r.pi]) r.plan = piPlan[r.pi];
  recent.sort((a, b) => b.at - a.at);

  // Active subscriptions + MRR now.
  const nowSec = Date.now() / 1000;
  const live = { monthly: 0, yearly: 0, other: 0 };
  let mrr = 0, canceling = 0, pastDue = 0;
  for (const s of subs) {
    if (!["active", "trialing", "past_due"].includes(s.status)) continue;
    const item = s.items && s.items.data && s.items.data[0];
    const price = item && item.price;
    const plan = planOfPrice(price && price.id);
    live[plan in live ? plan : "other"]++;
    if (s.status === "past_due") pastDue++;
    if (s.cancel_at_period_end || (s.cancel_at && s.cancel_at > nowSec)) canceling++;
    const amt = (price && price.unit_amount) || 0;
    const iv = price && price.recurring && price.recurring.interval;
    const n = (price && price.recurring && price.recurring.interval_count) || 1;
    mrr += iv === "year" ? amt / (12 * n) : iv === "week" ? amt * 52 / 12 / n : iv === "day" ? amt * 30 / n : amt / n;
  }

  // Paying members per day (subs alive that day + unexpired season passes).
  const spans = [];
  for (const s of subs) {
    const start = (s.start_date || s.created) * 1000;
    const end = s.ended_at ? s.ended_at * 1000 : Infinity;
    if (s.status === "incomplete" || s.status === "incomplete_expired") continue;
    spans.push([start, end]);
  }
  let seasonSold = 0;
  for (const s of sessions) {
    if (s.payment_status !== "paid" || !s.metadata || s.metadata.plan !== "season") continue;
    seasonSold++;
    spans.push([s.created * 1000, cfg.SEASON_PASS_END_MS]);
  }
  const members = {};
  const nDays = daysBetween(range.prevStart, range.end);
  for (let i = 0; i <= nDays; i++) {
    const ds = addDays(range.prevStart, i);
    const t = Math.min(dayStartMs(addDays(ds, 1)) - 1, Date.now());
    let c = 0;
    for (const [a, b] of spans) if (a <= t && t < b) c++;
    members[ds] = c;
  }
  let seasonActive = 0;
  for (const s of sessions) {
    if (s.payment_status === "paid" && s.metadata && s.metadata.plan === "season" && Date.now() < cfg.SEASON_PASS_END_MS) seasonActive++;
  }

  // All-time totals (lifetime revenue from completed checkouts + renewals is costly; use sessions only).
  let lifetimeCheckout = 0;
  for (const s of sessions) if (s.payment_status === "paid") lifetimeCheckout += s.amount_total || 0;

  return {
    ok: true,
    livemode: subs.length ? !!subs[0].livemode : (sessions.length ? !!sessions[0].livemode : null),
    daily, byPlan, newPaid, members,
    snapshot: {
      subs: live, mrr: Math.round(mrr), canceling, pastDue,
      seasonActive, seasonSold, lifetimeCheckout,
      payingNow: live.monthly + live.yearly + live.other + seasonActive,
    },
    recent: recent.slice(0, 25),
  };
}

// ---------- Firebase Auth ----------
async function authSection(range, force) {
  const users = await cached("auth_users", force, async () => {
    const out = [];
    let token;
    do {
      const page = await getAuth().listUsers(1000, token);
      for (const u of page.users) {
        out.push({
          c: Date.parse(u.metadata.creationTime) || 0,
          s: Date.parse(u.metadata.lastSignInTime || "") || 0,
          r: Date.parse(u.metadata.lastRefreshTime || "") || 0,
          p: (u.providerData[0] && u.providerData[0].providerId) || (u.email ? "password" : "anonymous"),
          v: !!u.emailVerified,
        });
      }
      token = page.pageToken;
    } while (token && out.length < 200000);
    return out;
  });
  const fromMs = dayStartMs(range.prevStart);
  const toMs = dayStartMs(addDays(range.end, 1));
  const signups = {};
  const activeDaily = {}; // last-activity day (only meaningful for recent days)
  const providers = {};
  const now = Date.now();
  let a1 = 0, a7 = 0, a30 = 0, first = Infinity;
  for (const u of users) {
    if (u.c && u.c < first) first = u.c;
    if (u.c >= fromMs && u.c < toMs) { const ds = dayKey(u.c); signups[ds] = (signups[ds] || 0) + 1; }
    const last = Math.max(u.r, u.s);
    if (last >= now - 86400000) a1++;
    if (last >= now - 7 * 86400000) a7++;
    if (last >= now - 30 * 86400000) a30++;
    providers[u.p] = (providers[u.p] || 0) + 1;
    if (last >= fromMs && last < toMs) { const ds = dayKey(last); activeDaily[ds] = (activeDaily[ds] || 0) + 1; }
  }
  // total accounts at the end of each day
  const sortedC = users.map((u) => u.c).sort((a, b) => a - b);
  const totalAt = {};
  const nDays = daysBetween(range.prevStart, range.end);
  let j = 0;
  for (let i = 0; i <= nDays; i++) {
    const ds = addDays(range.prevStart, i);
    const t = dayStartMs(addDays(ds, 1));
    while (j < sortedC.length && sortedC[j] < t) j++;
    totalAt[ds] = j;
  }
  return {
    ok: true, total: users.length, signups, totalAt, lastSeenDaily: activeDaily,
    active1: a1, active7: a7, active30: a30, providers,
    firstAccount: isFinite(first) ? dayKey(first) : null,
  };
}

// ---------- Firestore ----------
async function premiumSection(force) {
  return cached("premium", force, async () => {
    const db = getFirestore();
    const now = Date.now();
    const [usersSnap, giftSnap] = await Promise.all([
      db.collection("users").where("premium.currentPeriodEnd", ">", now).get(),
      db.collection("gifted_premium").where("expires", ">", now).get(),
    ]);
    const byPlan = {};
    usersSnap.forEach((d) => {
      const p = d.get("premium") || {};
      if (p.status && !["active", "trialing", "past_due"].includes(p.status)) return;
      const k = p.plan || "unknown";
      byPlan[k] = (byPlan[k] || 0) + 1;
    });
    let gifted = 0;
    giftSnap.forEach((d) => { if ((d.id || "") !== ADMIN_EMAIL.replace(/[^a-z0-9]/g, "_")) gifted++; });
    const paid = Object.values(byPlan).reduce((a, b) => a + b, 0);
    return { ok: true, byPlan, paid, gifted, total: paid + gifted };
  });
}

async function askJackSection(range) {
  const db = getFirestore();
  const fromIso = new Date(dayStartMs(range.prevStart)).toISOString();
  const toMs = dayStartMs(addDays(range.end, 1));
  const snap = await db.collection("qa_questions").where("createdAt", ">=", fromIso).get();
  const daily = {};
  let open = 0;
  snap.forEach((d) => {
    const x = d.data();
    if (x.testN) return;
    const t = Date.parse(x.createdAt);
    if (!t || t >= toMs) return;
    const ds = dayKey(t);
    const tier = x.tier || "free";
    const o = (daily[ds] = daily[ds] || {});
    o[tier] = (o[tier] || 0) + 1;
    if (x.status === "open") open++;
  });
  return { ok: true, daily, openInRange: open };
}

// ---------- GA4 ----------
let _ga;
function gaClient() {
  if (!_ga) {
    const { BetaAnalyticsDataClient } = require("@google-analytics/data");
    _ga = new BetaAnalyticsDataClient();
  }
  return _ga;
}
const HOST_FILTER = { filter: { fieldName: "hostName", stringFilter: { matchType: "CONTAINS", value: "myfantasyfootball" } } };
function rowsOf(resp, dimN) {
  const mh = (resp.metricHeaders || []).map((m) => m.name);
  const dh = (resp.dimensionHeaders || []).map((d) => d.name);
  return (resp.rows || []).map((r) => {
    const o = {};
    (r.dimensionValues || []).forEach((v, i) => { o[dh[i]] = v.value; });
    (r.metricValues || []).forEach((v, i) => { o[mh[i]] = Number(v.value); });
    return o;
  });
}
const gaDs = (s) => s.slice(0, 4) + "-" + s.slice(4, 6) + "-" + s.slice(6, 8);

async function ga4Section(range) {
  const ga = gaClient();
  const property = "properties/" + GA4_PROPERTY;
  const cur = { startDate: range.start, endDate: range.end, name: "cur" };
  const prev = { startDate: range.prevStart, endDate: range.prevEnd, name: "prev" };
  const base = { property, dimensionFilter: HOST_FILTER };
  const M = ["activeUsers", "newUsers", "sessions", "screenPageViews", "engagedSessions", "userEngagementDuration"];
  const run = (req) => ga.runReport({ ...base, ...req }).then((r) => r[0]);
  const [daily, totals, channels, sources, pages, devices, events, rt] = await Promise.all([
    run({ dateRanges: [{ startDate: range.prevStart, endDate: range.end }], dimensions: [{ name: "date" }], metrics: M.map((name) => ({ name })), limit: 5000 }),
    run({ dateRanges: [cur, prev], metrics: M.map((name) => ({ name })) }),
    run({ dateRanges: [cur, prev], dimensions: [{ name: "sessionDefaultChannelGroup" }], metrics: [{ name: "sessions" }, { name: "activeUsers" }], limit: 20 }),
    run({ dateRanges: [cur, prev], dimensions: [{ name: "sessionSource" }], metrics: [{ name: "sessions" }, { name: "activeUsers" }], limit: 25, orderBys: [{ metric: { metricName: "sessions" }, desc: true }] }),
    run({ dateRanges: [cur], dimensions: [{ name: "pagePath" }], metrics: [{ name: "screenPageViews" }, { name: "activeUsers" }], limit: 25, orderBys: [{ metric: { metricName: "screenPageViews" }, desc: true }] }),
    run({ dateRanges: [cur], dimensions: [{ name: "deviceCategory" }], metrics: [{ name: "activeUsers" }] }),
    run({ dateRanges: [cur, prev], dimensions: [{ name: "eventName" }], metrics: [{ name: "eventCount" }, { name: "totalUsers" }], limit: 80 }),
    ga.runRealtimeReport({ property, metrics: [{ name: "activeUsers" }] }).then((r) => r[0]).catch(() => null),
  ]);
  const byDay = {};
  for (const r of rowsOf(daily)) {
    byDay[gaDs(r.date)] = {
      activeUsers: r.activeUsers, newUsers: r.newUsers, sessions: r.sessions, views: r.screenPageViews,
      engaged: r.engagedSessions, engSec: r.userEngagementDuration,
    };
  }
  const split = (resp, key) => {
    const out = {};
    for (const r of rowsOf(resp)) {
      const k = key ? r[key] : "_";
      const o = (out[k] = out[k] || { name: k, cur: {}, prev: {} });
      const which = r.dateRange === "prev" ? "prev" : "cur";
      for (const [mk, mv] of Object.entries(r)) if (typeof mv === "number") o[which][mk] = mv;
    }
    return Object.values(out);
  };
  const tot = split(totals)[0] || { cur: {}, prev: {} };
  return {
    ok: true,
    daily: byDay,
    totals: { cur: tot.cur, prev: tot.prev },
    channels: split(channels, "sessionDefaultChannelGroup"),
    sources: split(sources, "sessionSource"),
    pages: rowsOf(pages).map((r) => ({ name: r.pagePath, views: r.screenPageViews, users: r.activeUsers })),
    devices: rowsOf(devices).map((r) => ({ name: r.deviceCategory, users: r.activeUsers })),
    events: split(events, "eventName"),
    realtime: rt && rt.rows && rt.rows[0] ? Number(rt.rows[0].metricValues[0].value) : (rt ? 0 : null),
  };
}

// ---------- callable ----------
function build(cfg) {
  return onCall(
    { secrets: [cfg.STRIPE_SECRET_KEY], cors: cfg.ALLOWED_ORIGINS, memory: "512MiB", timeoutSeconds: 120 },
    async (request) => {
      const tok = request.auth && request.auth.token;
      if (!tok || String(tok.email || "").toLowerCase() !== ADMIN_EMAIL || tok.email_verified !== true) {
        throw new HttpsError("permission-denied", "Admin only.");
      }
      const d = request.data || {};
      const today = dayKey(Date.now());
      const start = isDs(d.start) ? d.start : addDays(today, -29);
      const end = isDs(d.end) ? d.end : today;
      if (start > end) throw new HttpsError("invalid-argument", "start is after end");
      const len = daysBetween(start, end) + 1;
      if (len > MAX_DAYS) throw new HttpsError("invalid-argument", "range too long");
      const prevEnd = addDays(start, -1);
      const prevStart = addDays(start, -len);
      const range = { start, end, prevStart, prevEnd, days: len };
      const force = !!d.force;

      const key = [start, end].join("|");
      return cached("report|" + key, force, async () => {
        const [stripe, auth, premium, askjack, ga4] = await Promise.all([
          safe(() => stripeSection(cfg, range, force)),
          safe(() => authSection(range, force)),
          safe(() => premiumSection(force)),
          safe(() => askJackSection(range)),
          safe(() => ga4Section(range)),
        ]);
        if (ga4 && ga4.ok === false) {
          ga4.setup = {
            // Gen 2 functions run as the default compute service account.
            serviceAccount: "732824763527-compute@developer.gserviceaccount.com",
            steps: [
              "Enable the Google Analytics Data API on project jackb933-website",
              "GA4 Admin > Property access management > add the functions service account as Viewer",
            ],
          };
        }
        return { generatedAt: Date.now(), tz: TZ, range, stripe, auth, premium, askjack, ga4 };
      });
    }
  );
}

module.exports = { build, _test: { dayKey, dayStartMs, addDays, daysBetween } };
