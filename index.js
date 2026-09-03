/**
 * Cloud Functions for myfantasyfootball.org Premium / Stripe integration.
 *
 * Three functions:
 *   - createCheckoutSession  — callable from frontend; creates Stripe Checkout, returns URL
 *   - createPortalSession    — callable from frontend; opens Stripe Customer Portal so users can cancel
 *   - stripeWebhook          — HTTP endpoint Stripe POSTs to; updates users/{uid}.premium in Firestore
 *
 * Secrets (set via `firebase functions:secrets:set`):
 *   - STRIPE_SECRET_KEY      — Stripe secret key (sk_test_... or sk_live_...)
 *   - STRIPE_WEBHOOK_SECRET  — Webhook signing secret (whsec_...)
 */

const { onCall, onRequest, HttpsError } = require("firebase-functions/v2/https");
const { defineSecret } = require("firebase-functions/params");
const { setGlobalOptions } = require("firebase-functions");
const { initializeApp } = require("firebase-admin/app");
const { getFirestore, FieldValue } = require("firebase-admin/firestore");
const Stripe = require("stripe");

initializeApp();
setGlobalOptions({ maxInstances: 10, region: "us-central1" });

// === Secrets ===
const STRIPE_SECRET_KEY = defineSecret("STRIPE_SECRET_KEY");
const STRIPE_WEBHOOK_SECRET = defineSecret("STRIPE_WEBHOOK_SECRET");

// === Stripe Price IDs (LIVE mode) ===
// Test mode IDs (kept for reference if you ever switch back):
//   monthly: "price_1TQocXQaT88DSnVQdonwlz9M"
//   yearly:  "price_1TQofRQaT88DSnVQViOLeM7B"
const PRICE_IDS = {
  monthly: "price_1TQrIhHIcvDuU89Cyzca3sEV",
  yearly:  "price_1TQrIeHIcvDuU89CSm5NehUd",
};

// === Season Pass (one-time payment, fixed end date) ===
// The Season Pass costs $24.99 once and ALWAYS ends Jan 15 2027 at 11:59pm ET,
// no matter when it's purchased. It is NOT a subscription — nothing renews.
// UPDATE BOTH constants each season: create a fresh one-time Price in the
// Stripe dashboard (Products → Season Pass → Add price → One-off) and move
// the end date forward a year.
const SEASON_PASS_PRICE_ID = "price_1TytTLHIcvDuU89CrkaUR8mO"; // $24.99 one-time price (live)
const SEASON_PASS_END_MS = Date.UTC(2027, 0, 16, 4, 59, 59, 999); // Jan 15 2027 23:59:59 ET (UTC-5)

// === URLs ===
const SITE_URL = "https://myfantasyfootball.co";
const SUCCESS_URL = SITE_URL + "/?premium_success=1&session_id={CHECKOUT_SESSION_ID}";
const CANCEL_URL  = SITE_URL + "/?premium_cancel=1";

// Helper: pick plan name from a Stripe Price ID
function planFromPriceId(priceId) {
  if (priceId === PRICE_IDS.monthly) return "monthly";
  if (priceId === PRICE_IDS.yearly)  return "yearly";
  return "unknown";
}

// Helper: read current_period_end from a subscription, accounting for
// Stripe's March 2025 API change that moved it onto the subscription item.
function getPeriodEnd(subscription) {
  // Try top-level first (older API versions)
  if (typeof subscription.current_period_end === "number") {
    return subscription.current_period_end;
  }
  // Newer API: it lives on each item
  const item = subscription.items && subscription.items.data && subscription.items.data[0];
  if (item && typeof item.current_period_end === "number") {
    return item.current_period_end;
  }
  return 0;
}

// Helper: detect whether a subscription is scheduled to cancel.
// Newer Stripe API uses cancel_at (timestamp) instead of cancel_at_period_end (boolean).
// We treat either signal as "won't renew".
function isCanceling(subscription) {
  if (subscription.cancel_at_period_end === true) return true;
  if (typeof subscription.cancel_at === "number" && subscription.cancel_at > 0) return true;
  return false;
}

// ============================================================
// createCheckoutSession
// Frontend calls this when user clicks UPGRADE NOW.
// Returns { url } — the Stripe-hosted checkout page to redirect to.
// ============================================================
// Allowed origins for callable functions.
// Using a regex that matches both root and www, plus localhost for dev.
const ALLOWED_ORIGINS = [
  /^https:\/\/(www\.)?myfantasyfootball\.co$/,
  /^https:\/\/(www\.)?myfantasyfootball\.org$/,
  /^https:\/\/billingsj199-eng\.github\.io$/,
  /^https:\/\/jb-simlab-2026\.web\.app$/, // Sim Lab (unlisted) — Yahoo league import rides yahooProxy
  /^http:\/\/localhost(:\d+)?$/,
];

exports.createCheckoutSession = onCall(
  { secrets: [STRIPE_SECRET_KEY], cors: ALLOWED_ORIGINS },
  async (request) => {
    if (!request.auth) {
      throw new HttpsError("unauthenticated", "You must be signed in to upgrade.");
    }

    const plan = (request.data && request.data.plan) || "yearly";
    if (plan !== "season" && !PRICE_IDS[plan]) {
      throw new HttpsError("invalid-argument", "Invalid plan: " + plan);
    }
    if (plan === "season") {
      if (SEASON_PASS_PRICE_ID.indexOf("PASTE") === 0) {
        throw new HttpsError("failed-precondition", "Season Pass isn't available yet — check back soon.");
      }
      if (Date.now() >= SEASON_PASS_END_MS) {
        throw new HttpsError("failed-precondition", "Season Pass sales have ended for this season.");
      }
    }

    const stripe = new Stripe(STRIPE_SECRET_KEY.value());
    const uid = request.auth.uid;
    const email = (request.auth.token && request.auth.token.email) || "";
    const db = getFirestore();

    // Reuse Stripe customer if we already created one for this user
    const userRef = db.collection("users").doc(uid);
    const userSnap = await userRef.get();
    let customerId = userSnap.exists ? userSnap.data().stripeCustomerId : null;

    if (!customerId) {
      const customer = await stripe.customers.create({
        email: email,
        metadata: { firebaseUid: uid },
      });
      customerId = customer.id;
      await userRef.set({ stripeCustomerId: customerId }, { merge: true });
    }

    // Season Pass = one-time payment; Monthly/Yearly = recurring subscription.
    const session = await stripe.checkout.sessions.create({
      mode: plan === "season" ? "payment" : "subscription",
      customer: customerId,
      line_items: [{
        price: plan === "season" ? SEASON_PASS_PRICE_ID : PRICE_IDS[plan],
        quantity: 1,
      }],
      client_reference_id: uid,
      metadata: { plan: plan, firebaseUid: uid },
      success_url: SUCCESS_URL,
      cancel_url: CANCEL_URL,
      allow_promotion_codes: true,
    });

    return { url: session.url };
  }
);

// ============================================================
// createPortalSession
// Lets a premium user manage / cancel their subscription via
// Stripe's hosted Customer Portal page.
// ============================================================
exports.createPortalSession = onCall(
  { secrets: [STRIPE_SECRET_KEY], cors: ALLOWED_ORIGINS },
  async (request) => {
    if (!request.auth) {
      throw new HttpsError("unauthenticated", "You must be signed in.");
    }

    const stripe = new Stripe(STRIPE_SECRET_KEY.value());
    const uid = request.auth.uid;
    const db = getFirestore();
    const userSnap = await db.collection("users").doc(uid).get();
    const customerId = userSnap.exists ? userSnap.data().stripeCustomerId : null;

    if (!customerId) {
      throw new HttpsError("not-found", "No subscription on file for this account.");
    }

    const session = await stripe.billingPortal.sessions.create({
      customer: customerId,
      return_url: SITE_URL + "/?page=account",
    });

    return { url: session.url };
  }
);

// ============================================================
// redeemCode
// Frontend calls this when a user redeems a premium code.
// Validates the code server-side (built-in map OR premium_codes/{CODE}),
// enforces once-per-user, then grants premium via the admin SDK by writing
// gifted_premium/{emailDoc}. Because this runs with admin privileges the
// client never needs write access to premium_codes / redeem_uses / gifted_premium
// (their rules stay admin-only), so premium can't be self-granted.
// Returns { ok, days, expires (ms), label }.
// ============================================================

// Built-in redeem codes — mirror of the client REDEEM_CODES map (kept here so
// ALL redeems, built-in and admin-created, are validated + granted server-side).
// "expires" = last day the code is redeemable (inclusive, end-of-day UTC).
const BUILTIN_REDEEM_CODES = {
  DRAFT: { days: 7, expires: "2026-04-28" },
  CHROMEREVIEW: { days: 365, expires: "2027-06-01" },
};

// End-of-day (23:59:59.999 UTC) in ms for a YYYY-MM-DD string; 0 if malformed.
function endOfDayMs(dateStr) {
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(String(dateStr || ""));
  if (!m) return 0;
  return Date.UTC(+m[1], +m[2] - 1, +m[3], 23, 59, 59, 999);
}

exports.redeemCode = onCall(
  { cors: ALLOWED_ORIGINS },
  async (request) => {
    if (!request.auth) {
      throw new HttpsError("unauthenticated", "Please sign in to redeem a code.");
    }
    const uid = request.auth.uid;
    const email = ((request.auth.token && request.auth.token.email) || "").toLowerCase();
    if (!email) {
      throw new HttpsError("failed-precondition", "Your account has no email address.");
    }

    const raw = String((request.data && request.data.code) || "").trim().toUpperCase();
    if (!raw || raw.length > 64) {
      throw new HttpsError("invalid-argument", "Enter a valid code.");
    }

    const db = getFirestore();

    // Resolve the code definition: built-in first, then Firestore.
    let def = null;
    let source = null;
    let codeRef = null;
    if (BUILTIN_REDEEM_CODES[raw]) {
      def = BUILTIN_REDEEM_CODES[raw];
      source = "builtin";
    } else {
      codeRef = db.collection("premium_codes").doc(raw);
      const codeSnap = await codeRef.get();
      if (!codeSnap.exists) {
        throw new HttpsError("not-found", "Invalid code.");
      }
      const d = codeSnap.data() || {};
      if (d.disabled) {
        throw new HttpsError("failed-precondition", "This code has been disabled.");
      }
      def = { days: d.days, expires: d.expires };
      source = "firestore";
    }

    if (!def.days || !def.expires) {
      throw new HttpsError("failed-precondition", "Invalid code.");
    }

    // Hard-expiry check.
    const codeExpiresAt = endOfDayMs(def.expires);
    const now = Date.now();
    if (!codeExpiresAt || now > codeExpiresAt) {
      throw new HttpsError("failed-precondition", "This code has expired.");
    }

    // Once-per-user enforcement (deterministic doc id = atomic guard).
    const useRef = db.collection("redeem_uses").doc(uid + "__" + raw);
    const useSnap = await useRef.get();
    if (useSnap.exists) {
      throw new HttpsError("already-exists", "You have already redeemed this code.");
    }

    // Grant `days` from now, capped at the code's hard expiry; never shorten an
    // existing longer grant.
    const grantEnd = Math.min(now + def.days * 86400000, codeExpiresAt);
    const emailDocId = email.replace(/[^a-z0-9]/g, "_");
    const giftedRef = db.collection("gifted_premium").doc(emailDocId);
    const giftedSnap = await giftedRef.get();
    const existingExpires = (giftedSnap.exists && typeof giftedSnap.data().expires === "number")
      ? giftedSnap.data().expires : 0;
    const finalExpires = Math.max(existingExpires, grantEnd);
    const nowIso = new Date().toISOString();

    // Grant premium (admin SDK — bypasses security rules).
    await giftedRef.set({
      email: email,
      expires: finalExpires,
      days: def.days,
      label: "Code: " + raw,
      grantedBy: "redeem:" + raw,
      grantedAt: nowIso,
    }, { merge: true });

    // Log the redemption (also the once-per-user source).
    await useRef.set({
      uid: uid,
      email: email,
      code: raw,
      days: def.days,
      source: source,
      grantedUntil: new Date(finalExpires).toISOString(),
      at: nowIso,
    });

    // Best-effort uses counter on Firestore codes.
    if (source === "firestore" && codeRef) {
      try {
        await codeRef.update({ uses: FieldValue.increment(1) });
      } catch (e) {
        console.warn("[redeemCode] uses increment failed for", raw, e && e.message);
      }
    }

    return { ok: true, days: def.days, expires: finalExpires, label: "Code: " + raw };
  }
);

// ============================================================
// stripeWebhook
// Stripe POSTs subscription lifecycle events here.
// We verify the signature, then mirror the subscription state
// onto users/{uid}.premium in Firestore.
// ============================================================
exports.stripeWebhook = onRequest(
  { secrets: [STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET] },
  async (req, res) => {
    const stripe = new Stripe(STRIPE_SECRET_KEY.value());
    const sig = req.headers["stripe-signature"];

    let event;
    try {
      event = stripe.webhooks.constructEvent(
        req.rawBody,
        sig,
        STRIPE_WEBHOOK_SECRET.value()
      );
    } catch (err) {
      console.error("Webhook signature verification failed:", err.message);
      res.status(400).send("Webhook Error: " + err.message);
      return;
    }

    const db = getFirestore();

    try {
      switch (event.type) {
        // Initial purchase — fires when checkout completes successfully.
        case "checkout.session.completed": {
          const session = event.data.object;
          const uid = session.client_reference_id;
          const customerId = session.customer;
          const subscriptionId = session.subscription;

          // Season Pass — one-time payment, no subscription object. Grant
          // premium with the fixed season end date regardless of purchase date.
          const isSeasonPass = session.mode === "payment" &&
            session.metadata && session.metadata.plan === "season";
          if (isSeasonPass && uid) {
            const userRef = db.collection("users").doc(uid);
            const snap = await userRef.get();
            const existing = snap.exists ? (snap.data().premium || null) : null;
            const existingActive = existing &&
              (existing.status === "active" || existing.status === "trialing") &&
              existing.currentPeriodEnd > Date.now();
            if (existingActive && existing.currentPeriodEnd >= SEASON_PASS_END_MS) {
              // They already have premium running past the season end — don't downgrade it.
              console.log("Season Pass bought by", uid, "— kept existing longer premium");
              break;
            }
            await userRef.set({
              stripeCustomerId: customerId,
              premium: {
                plan: "season",
                status: "active",
                stripeSubscriptionId: null, // one-time payment — nothing to renew or cancel
                stripePriceId: SEASON_PASS_PRICE_ID,
                currentPeriodEnd: SEASON_PASS_END_MS,
                cancelAtPeriodEnd: true,
                activatedAt: FieldValue.serverTimestamp(),
                updatedAt: FieldValue.serverTimestamp(),
              },
            }, { merge: true });
            console.log("Season Pass activated for", uid, "— ends", new Date(SEASON_PASS_END_MS).toISOString());
            break;
          }

          if (!uid || !subscriptionId) {
            console.warn("Skipping incomplete session:", session.id);
            break;
          }

          const subscription = await stripe.subscriptions.retrieve(subscriptionId);
          const priceId = subscription.items.data[0].price.id;
          const plan = planFromPriceId(priceId);

          await db.collection("users").doc(uid).set({
            stripeCustomerId: customerId,
            premium: {
              plan: plan,
              status: subscription.status, // "active" or "trialing"
              stripeSubscriptionId: subscriptionId,
              stripePriceId: priceId,
              currentPeriodEnd: getPeriodEnd(subscription) * 1000, // ms
              cancelAtPeriodEnd: isCanceling(subscription),
              activatedAt: FieldValue.serverTimestamp(),
              updatedAt: FieldValue.serverTimestamp(),
            },
          }, { merge: true });

          console.log("Premium activated for", uid, "plan", plan);
          break;
        }

        // Renewals, plan changes, cancellations scheduled at period end, etc.
        case "customer.subscription.updated":
        case "customer.subscription.deleted": {
          const subscription = event.data.object;
          const customerId = subscription.customer;

          // Find the user by their Stripe customer ID
          const userQuery = await db.collection("users")
            .where("stripeCustomerId", "==", customerId)
            .limit(1)
            .get();

          if (userQuery.empty) {
            console.warn("No user found for Stripe customer:", customerId);
            break;
          }

          const userDoc = userQuery.docs[0];

          // Don't let a lingering old subscription event (e.g. a canceled
          // monthly's deletion) clobber an active fixed-date Season Pass.
          const existingPrem = (userDoc.data() || {}).premium || null;
          if (existingPrem && existingPrem.plan === "season" &&
              existingPrem.status === "active" &&
              existingPrem.currentPeriodEnd > Date.now() &&
              existingPrem.currentPeriodEnd >= getPeriodEnd(subscription) * 1000) {
            console.log("Ignoring", event.type, "for", userDoc.id, "— active Season Pass takes precedence");
            break;
          }

          const priceId = subscription.items.data[0].price.id;
          const plan = planFromPriceId(priceId);

          // For deleted subscriptions, mark as canceled but keep currentPeriodEnd
          // so the frontend knows when access actually ends.
          const status = event.type === "customer.subscription.deleted"
            ? "canceled"
            : subscription.status;

          await userDoc.ref.set({
            premium: {
              plan: plan,
              status: status,
              stripeSubscriptionId: subscription.id,
              stripePriceId: priceId,
              currentPeriodEnd: getPeriodEnd(subscription) * 1000,
              cancelAtPeriodEnd: isCanceling(subscription),
              updatedAt: FieldValue.serverTimestamp(),
            },
          }, { merge: true });

          console.log("Subscription", event.type, "for user", userDoc.id, "status", status);
          break;
        }

        default:
          // Ignore other event types
          break;
      }

      res.json({ received: true });
    } catch (err) {
      console.error("Webhook handler error:", err);
      res.status(500).send("Webhook handler error: " + err.message);
    }
  }
);

// === Export feed: full Jack's boards for the local data exporters ===
// Board-gating Phase B (2026-08-11): rankings/jacks-official goes premium-only
// read in Phase C, which would break the tokenless REST fetch the players.json
// exporters use. This endpoint returns the full doc via the admin SDK, gated
// by a static secret only Jack's PC holds (E:\MyFantasyFootball\secrets\
// export_feed_key.txt, sent as the x-export-key header). The response mirrors
// the Firestore REST document shape so the exporters' existing parser
// (doc.fields.data.stringValue) works unchanged.
const EXPORT_FEED_KEY = defineSecret("EXPORT_FEED_KEY");
exports.exportJacksBoards = onRequest(
  { secrets: [EXPORT_FEED_KEY] },
  async (req, res) => {
    try {
      const supplied = req.get("x-export-key") || "";
      if (!supplied || supplied !== EXPORT_FEED_KEY.value()) {
        res.status(403).json({ error: "forbidden" });
        return;
      }
      const snap = await getFirestore().collection("rankings").doc("jacks-official").get();
      if (!snap.exists) {
        res.status(404).json({ error: "missing" });
        return;
      }
      const d = snap.data() || {};
      res.json({
        fields: {
          data: { stringValue: d.data || "" },
          ir: { stringValue: d.ir || "" },
          updatedAt: { stringValue: d.updatedAt || "" },
        },
      });
    } catch (err) {
      console.error("exportJacksBoards error:", err);
      res.status(500).json({ error: "internal" });
    }
  }
);

// === refreshJacksPublic: server-side rebuild of rankings/jacks-public ===
// Bootstrap + backstop for the board-gating public slice (the site's admin
// session also writes it on every save via _writeJacksPublicSlice — that
// client code is authoritative; keep the two slicers in sync). Gated by the
// same EXPORT_FEED_KEY secret as exportJacksBoards.
exports.refreshJacksPublic = onRequest(
  { secrets: [EXPORT_FEED_KEY] },
  async (req, res) => {
    try {
      const supplied = req.get("x-export-key") || "";
      if (!supplied || supplied !== EXPORT_FEED_KEY.value()) {
        res.status(403).json({ error: "forbidden" });
        return;
      }
      const db = getFirestore();
      const snap = await db.collection("rankings").doc("jacks-official").get();
      if (!snap.exists || !snap.data().data) {
        res.status(404).json({ error: "official missing" });
        return;
      }
      const full = JSON.parse(snap.data().data);
      const CUT_ALL = 36, CUT_POS = 12;
      // _pubSchema 2 (2026-09-03): slice carries _cut / _cutPos per mode so
      // free/anon viewers get the cut line (keep in sync with the site's
      // _buildJacksPublicPayload / _PUB_SCHEMA).
      const out = { jacks: {}, _pubSchema: 2 };
      for (const m of ["redraft", "bestball", "superflex", "dynasty", "dynastysf", "weekly"]) {
        const src = full.jacks && full.jacks[m];
        if (!src) continue;
        const slice = { _order: (src._order || []).slice(0, CUT_ALL), _posTiers: {} };
        const pt = src._posTiers || {};
        for (const pk of Object.keys(pt)) {
          const cut = pk === "ALL" ? CUT_ALL : CUT_POS;
          const kept = (pt[pk] || []).filter((t) => t && t.afterRank >= 1 && t.afterRank <= cut);
          if (kept.length) slice._posTiers[pk] = kept;
        }
        if (m === "weekly" && src._week != null) slice._week = src._week;
        if (src._cut >= 1) slice._cut = src._cut;
        if (src._cutPos && typeof src._cutPos === "object" && Object.keys(src._cutPos).length) slice._cutPos = src._cutPos;
        out.jacks[m] = slice;
      }
      // Precomputed ticker movers (same rules as the site: 300-rank window,
      // top 8 by |delta|) so free sessions keep the home-page ticker.
      const prev = full._prev && full._prev.redraft;
      const cur = (full.jacks && full.jacks.redraft && full.jacks.redraft._order) || [];
      if (Array.isArray(prev) && prev.length && cur.length) {
        const prevRanks = {};
        let pc = 0;
        for (const n of prev) prevRanks[n] = ++pc;
        const movers = [];
        cur.forEach((n, i) => {
          const nr = i + 1;
          if (nr > 300) return;
          const or = prevRanks[n];
          if (!or || or > 300) return;
          if (or !== nr) movers.push({ n: n, delta: or - nr, newRank: nr });
        });
        movers.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
        out._movers = movers.slice(0, 8);
      }
      await db.collection("rankings").doc("jacks-public").set({
        data: JSON.stringify(out),
        ir: snap.data().ir || "{}",
        updatedAt: new Date().toISOString(),
      }, { merge: true });
      res.json({
        ok: true,
        modes: Object.keys(out.jacks),
        redraftLen: (out.jacks.redraft && out.jacks.redraft._order.length) || 0,
        movers: (out._movers || []).length,
      });
    } catch (err) {
      console.error("refreshJacksPublic error:", err);
      res.status(500).json({ error: "internal" });
    }
  }
);

// === premiumCheck: diagnostic for the Phase C premium read rules ===
// Given ?email=, evaluates EXACTLY the conditions the firestore.rules premium
// helpers apply (gifted_premium/{email-key}.expires, users/{uid}.premium
// status + currentPeriodEnd) against live data, so a premium account's access
// to rankings/jacks-official can be verified without an interactive sign-in.
// Secret-gated like the other ops endpoints; reveals premium metadata only.
const { getAuth } = require("firebase-admin/auth");
exports.premiumCheck = onRequest(
  { secrets: [EXPORT_FEED_KEY] },
  async (req, res) => {
    try {
      const supplied = req.get("x-export-key") || "";
      if (!supplied || supplied !== EXPORT_FEED_KEY.value()) {
        res.status(403).json({ error: "forbidden" });
        return;
      }
      const email = String(req.query.email || "").toLowerCase();
      if (!email) { res.status(400).json({ error: "email required" }); return; }
      const giftKey = email.replace(/[^a-z0-9]/g, "_");
      const db = getFirestore();
      const now = Date.now();
      const gift = await db.collection("gifted_premium").doc(giftKey).get();
      const giftExpires = gift.exists ? (gift.data().expires || 0) : null;
      const giftOk = gift.exists && giftExpires > now;
      let uid = null, prem = null;
      try {
        const u = await getAuth().getUserByEmail(email);
        uid = u.uid;
        const ud = await db.collection("users").doc(uid).get();
        prem = ud.exists ? (ud.data().premium || null) : null;
      } catch (_) { /* no auth user — stripe check stays false */ }
      const stripeOk = !!(prem
        && ["active", "trialing"].includes(prem.status)
        && (prem.currentPeriodEnd || 0) > now);
      res.json({
        email, giftKey,
        gifted: { exists: gift.exists, expires: giftExpires, ok: giftOk },
        stripe: { uid, status: prem ? prem.status : null, currentPeriodEnd: prem ? prem.currentPeriodEnd : null, ok: stripeOk },
        rulesWouldAllowOfficialRead: giftOk || stripeOk,
      });
    } catch (err) {
      console.error("premiumCheck error:", err);
      res.status(500).json({ error: "internal" });
    }
  }
);

// === yahooProxy: CORS bridge for the in-site Yahoo league importer ===
// Yahoo's fantasy endpoints answer anonymously for link-viewable leagues but
// send no CORS headers for our origin, so the browser can't read them from
// myfantasyfootball.co. This proxies a strict GET allowlist:
//   - pub-api settings/teams JSON (exact scoring + lineup slots + team list)
//   - football.fantasysports.yahoo.com/f1/<id>[/<teamId>] HTML (standings +
//     rosters — the JSON API has no roster route)
//   - football.fantasysports.yahoo.com/f1/<id>/draftresults HTML (My Teams
//     draft board, added 2026-08-31)
//   - football.fantasysports.yahoo.com/f1/<id>/transactions[?transactionsfilter=…]
//     HTML (My Teams trade log, added 2026-09-02)
// Truly private leagues redirect to login.yahoo.com upstream → 403 "private"
// so the site can steer those users to the Yahoo extension instead.
// Request: GET ?url=<encoded absolute url>
const YAHOO_PROXY_ALLOWED = [
  /^https:\/\/pub-api\.fantasysports\.yahoo\.com\/fantasy\/v3\/(settings|teams)\/nfl\/\d{1,10}\?format=rawjson$/,
  /^https:\/\/football\.fantasysports\.yahoo\.com\/f1\/\d{1,10}(\/\d{1,4}|\/draftresults|\/transactions(\?transactionsfilter=(all|trade|add|drop))?)?$/,
];
exports.yahooProxy = onRequest(
  { cors: ALLOWED_ORIGINS },
  async (req, res) => {
    try {
      const url = String(req.query.url || "");
      if (!YAHOO_PROXY_ALLOWED.some((re) => re.test(url))) {
        res.status(400).json({ error: "url not allowed" });
        return;
      }
      const upstream = await fetch(url, {
        headers: {
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MFF-league-import",
          "Accept": "text/html,application/json",
        },
        redirect: "follow",
      });
      if (/login\.yahoo\.com/.test(upstream.url)) {
        res.status(403).json({ error: "private" });
        return;
      }
      const body = await upstream.text();
      res.status(upstream.status)
        .set("Content-Type", upstream.headers.get("content-type") || "text/plain")
        .set("Cache-Control", "private, max-age=60")
        .send(body);
    } catch (err) {
      console.error("yahooProxy error:", err);
      res.status(502).json({ error: "upstream unreachable" });
    }
  }
);
