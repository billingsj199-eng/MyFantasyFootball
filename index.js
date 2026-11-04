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

// === Ask Jack line skip (2026-11-04) ===
// A free member's open Ask Jack question can jump ahead of every other free
// question in Jack's queue for a one-off $4.99 (premium questions still go
// first). The price is created inline on the Checkout Session (no dashboard
// Price needed); after Stripe confirms, applyLineSkip marks the question
// tier 'skip' — the client can't write that field (firestore.rules).
const LINE_SKIP_CENTS = 499;
const LINE_SKIP_SUCCESS_URL = SITE_URL + "/?skip_success=1&session_id={CHECKOUT_SESSION_ID}#askjack";
const LINE_SKIP_CANCEL_URL  = SITE_URL + "/?skip_cancel=1#askjack";

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
    if (plan !== "season" && plan !== "lineskip" && !PRICE_IDS[plan]) {
      throw new HttpsError("invalid-argument", "Invalid plan: " + plan);
    }
    // Ask Jack line skip: the question must be the caller's, still open, and
    // a free-line question (premium ones are already ahead of the skips).
    let qaDoc = null;
    if (plan === "lineskip") {
      const raw = request.data && request.data.qaDoc;
      qaDoc = typeof raw === "string" ? raw.trim() : "";
      if (!qaDoc || qaDoc.length > 160 || !/^[A-Za-z0-9_-]+$/.test(qaDoc)) {
        throw new HttpsError("invalid-argument", "Invalid question id.");
      }
      const qSnap = await getFirestore().collection("qa_questions").doc(qaDoc).get();
      const q = qSnap.exists ? qSnap.data() : null;
      if (!q || q.uid !== request.auth.uid) {
        throw new HttpsError("not-found", "That question isn't yours or no longer exists.");
      }
      if (q.status !== "open") {
        throw new HttpsError("failed-precondition", "Jack already answered that one.");
      }
      if (q.tier === "skip") {
        throw new HttpsError("failed-precondition", "That question already has a line skip.");
      }
      if (q.tier !== "free") {
        throw new HttpsError("failed-precondition", "Premium questions already go to the front of the line.");
      }
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

    if (plan === "lineskip") {
      const session = await stripe.checkout.sessions.create({
        mode: "payment",
        customer: customerId,
        line_items: [{
          price_data: {
            currency: "usd",
            unit_amount: LINE_SKIP_CENTS,
            product_data: {
              name: "Ask Jack — Skip the Line",
              description: "Moves your question ahead of every free question in Jack's queue (premium members' questions still go first).",
            },
          },
          quantity: 1,
        }],
        client_reference_id: uid,
        metadata: { plan: "lineskip", firebaseUid: uid, qaDoc: qaDoc },
        success_url: LINE_SKIP_SUCCESS_URL,
        cancel_url: LINE_SKIP_CANCEL_URL,
      });
      return { url: session.url };
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
// activateFromCheckoutSession
// Grants premium from a completed Checkout Session. Shared by the
// stripeWebhook checkout.session.completed branch and the client-driven
// verifyCheckoutSession callable (webhook-independent activation, 2026-10-15)
// so both paths write users/{uid}.premium identically.
// `session.subscription` / `session.customer` may be ids or expanded objects.
// Returns { ok, plan, currentPeriodEnd, kept? } or { ok:false, reason }.
// ============================================================
async function activateFromCheckoutSession(db, stripe, session, source) {
  const uid = session.client_reference_id;
  const customerId = typeof session.customer === "string"
    ? session.customer
    : (session.customer && session.customer.id) || null;

  // Ask Jack line skip — not premium at all: mark the question and stop.
  if (session.mode === "payment" && session.metadata && session.metadata.plan === "lineskip") {
    return applyLineSkip(db, session, source);
  }

  // Season Pass — one-time payment, no subscription object. Grant premium
  // with the fixed season end date regardless of purchase date.
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
      console.log(source + ": Season Pass bought by", uid, "— kept existing longer premium");
      return { ok: true, plan: existing.plan || "season", currentPeriodEnd: existing.currentPeriodEnd, kept: true };
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
    console.log(source + ": Season Pass activated for", uid, "— ends", new Date(SEASON_PASS_END_MS).toISOString());
    return { ok: true, plan: "season", currentPeriodEnd: SEASON_PASS_END_MS };
  }

  const subscriptionId = typeof session.subscription === "string"
    ? session.subscription
    : (session.subscription && session.subscription.id) || null;
  if (!uid || !subscriptionId) {
    console.warn(source + ": skipping incomplete session:", session.id);
    return { ok: false, reason: "incomplete" };
  }

  const subscription = (session.subscription && typeof session.subscription === "object")
    ? session.subscription
    : await stripe.subscriptions.retrieve(subscriptionId);
  const priceId = subscription.items.data[0].price.id;
  const plan = planFromPriceId(priceId);
  const periodEndMs = getPeriodEnd(subscription) * 1000;

  await db.collection("users").doc(uid).set({
    stripeCustomerId: customerId,
    premium: {
      plan: plan,
      status: subscription.status, // "active" or "trialing"
      stripeSubscriptionId: subscriptionId,
      stripePriceId: priceId,
      currentPeriodEnd: periodEndMs, // ms
      cancelAtPeriodEnd: isCanceling(subscription),
      activatedAt: FieldValue.serverTimestamp(),
      updatedAt: FieldValue.serverTimestamp(),
    },
  }, { merge: true });

  console.log(source + ": Premium activated for", uid, "plan", plan);
  return { ok: true, plan: plan, currentPeriodEnd: periodEndMs, status: subscription.status };
}

// ============================================================
// applyLineSkip
// A paid "Ask Jack — Skip the Line" Checkout Session (metadata.plan
// 'lineskip', metadata.qaDoc = the question id): mark that question tier
// 'skip' so it sorts ahead of every free question in Jack's queue. Shared by
// the webhook and verifyCheckoutSession; idempotent (a second call keeps it).
// ============================================================
async function applyLineSkip(db, session, source) {
  const uid = session.client_reference_id;
  const qaDoc = session.metadata && session.metadata.qaDoc;
  if (!uid || !qaDoc || typeof qaDoc !== "string" || !/^[A-Za-z0-9_-]{1,160}$/.test(qaDoc)) {
    console.warn(source + ": line skip session missing uid/qaDoc:", session.id);
    return { ok: false, reason: "incomplete" };
  }
  if (session.payment_status !== "paid") {
    console.warn(source + ": line skip session not paid:", session.id, session.payment_status);
    return { ok: false, reason: "unpaid" };
  }
  const ref = db.collection("qa_questions").doc(qaDoc);
  const snap = await ref.get();
  if (!snap.exists) {
    console.warn(source + ": line skip for a missing question:", qaDoc, "by", uid);
    return { ok: false, reason: "missing" };
  }
  const q = snap.data() || {};
  if (q.uid !== uid) {
    console.warn(source + ": line skip uid mismatch:", qaDoc, q.uid, "vs", uid);
    return { ok: false, reason: "mismatch" };
  }
  if (q.tier === "skip") {
    return { ok: true, plan: "lineskip", qaDoc: qaDoc, kept: true };
  }
  await ref.update({
    tier: "skip",
    skipPaidAt: FieldValue.serverTimestamp(),
    skipSession: session.id,
    skipAmount: typeof session.amount_total === "number" ? session.amount_total : LINE_SKIP_CENTS,
  });
  console.log(source + ": line skip applied to", qaDoc, "for", uid);
  return { ok: true, plan: "lineskip", qaDoc: qaDoc };
}

// ============================================================
// verifyCheckoutSession
// Webhook-independent activation. Stripe sends the buyer back to
// /?premium_success=1&session_id=cs_… and the client calls this right away,
// so premium lands even when stripeWebhook is late or fails. Auth-gated: the
// session must belong to the caller (client_reference_id) and be paid.
// Idempotent with the webhook — same helper, same writes, same guards.
// ============================================================
const VERIFY_SESSION_MAX_AGE_S = 7 * 24 * 3600; // ignore stale session ids (refund replay guard)
exports.verifyCheckoutSession = onCall(
  { secrets: [STRIPE_SECRET_KEY], cors: ALLOWED_ORIGINS },
  async (request) => {
    if (!request.auth) {
      throw new HttpsError("unauthenticated", "Sign in with the account you used at checkout to activate premium.");
    }
    const uid = request.auth.uid;
    const raw = request.data && request.data.sessionId;
    const sessionId = typeof raw === "string" ? raw.trim() : "";
    if (!sessionId || sessionId.length > 200 || !/^cs_(live|test)_[A-Za-z0-9]+$/.test(sessionId)) {
      throw new HttpsError("invalid-argument", "Invalid checkout session id.");
    }

    const stripe = new Stripe(STRIPE_SECRET_KEY.value());
    let session;
    try {
      session = await stripe.checkout.sessions.retrieve(sessionId, { expand: ["subscription"] });
    } catch (err) {
      console.warn("verifyCheckoutSession: retrieve failed for", uid, sessionId, "—", err && err.message);
      throw new HttpsError("not-found", "Checkout session not found.");
    }

    if (session.client_reference_id !== uid) {
      console.warn("verifyCheckoutSession: uid mismatch", uid, "vs", session.client_reference_id, sessionId);
      throw new HttpsError("permission-denied", "This checkout belongs to a different account.");
    }
    if (session.payment_status !== "paid") {
      throw new HttpsError("failed-precondition", "Payment not completed yet (" + session.payment_status + ").");
    }
    if (typeof session.created === "number" && (Date.now() / 1000 - session.created) > VERIFY_SESSION_MAX_AGE_S) {
      throw new HttpsError("failed-precondition", "This checkout session is too old to activate — contact support.");
    }

    const result = await activateFromCheckoutSession(getFirestore(), stripe, session, "verifyCheckoutSession");
    if (!result.ok) {
      throw new HttpsError("failed-precondition", "Checkout session is incomplete.");
    }
    return { ok: true, plan: result.plan, currentPeriodEnd: result.currentPeriodEnd || null, qaDoc: result.qaDoc || null, kept: !!result.kept };
  }
);

// ============================================================
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
          // Shared with verifyCheckoutSession (client-driven fallback) so both
          // paths write users/{uid}.premium identically.
          await activateFromCheckoutSession(db, stripe, event.data.object, "stripeWebhook");
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

// === lockTriviaDaily: news-driven Daily Trivia board (scheduled job on Jack's PC) ===
// scripts/trivia_daily/run.js (site repo) picks tomorrow's theme from the
// news feed / calendar, builds the board with the site's own trivia generator
// headlessly, and POSTs the lock doc here. This endpoint is the only writer
// of trivia_daily/* outside the admin UI: the PC sends the export feed key
// (outside the repo, E:\MyFantasyFootball\secrets\export_feed_key.txt, the same
// file the Jack's-board exporters use) and it is matched against the
// EXPORT_FEED_KEY secret, so no Google credential ever lives on disk.
// Rules: an admin-locked board for the date is never overwritten (409);
// an earlier auto board for the same date is replaced; the date must be
// today (ET) or later; the doc shape is validated and size-capped.

exports.lockTriviaDaily = onRequest(
  { secrets: [EXPORT_FEED_KEY], memory: "256MiB", timeoutSeconds: 60 },
  async (req, res) => {
    try {
      const supplied = req.get("x-export-key") || "";
      if (!supplied || supplied !== EXPORT_FEED_KEY.value()) {
        res.status(403).json({ error: "forbidden" });
        return;
      }
      if (req.method !== "POST") { res.status(405).json({ error: "POST only" }); return; }
      const bad = (msg) => { res.status(400).json({ error: msg }); };
      // {op:'unlock', date}: remove an AUTO lock (never a hand lock) so the
      // template cycle serves that date again.
      if (req.body && req.body.op === "unlock") {
        const d = String(req.body.date || "");
        if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return bad("bad date");
        const ref = getFirestore().collection("trivia_daily").doc(d);
        const snap = await ref.get();
        if (!snap.exists) { res.json({ ok: true, date: d, removed: false }); return; }
        if ((snap.data() || {}).source !== "auto") { res.status(409).json({ error: "locked-by-admin" }); return; }
        await ref.delete();
        res.json({ ok: true, date: d, removed: true });
        return;
      }
      const doc = req.body && req.body.doc;
      if (!doc || typeof doc !== "object") return bad("doc required");
      const date = String(doc.date || "");
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return bad("bad date");
      const todayET = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
      if (date < todayET) return bad("date is in the past (ET)");
      if (doc.source !== "auto") return bad("source must be 'auto'");
      const title = String(doc.title || "").trim();
      if (!title || title.length > 120) return bad("bad title");
      const desc = String(doc.desc || "").slice(0, 200);
      if (!Array.isArray(doc.items) || doc.items.length < 16 || doc.items.length > 40) return bad("items must be 16-40");
      const str = (v, n) => (v == null ? "" : String(v)).slice(0, n);
      const items = doc.items.map((it) => ({
        rank: (typeof it.rank === "number") ? it.rank : str(it.rank, 8),
        answer: str(it.answer, 80),
        value: (typeof it.value === "number") ? it.value : str(it.value, 40),
        hint: str(it.hint, 80),
        team: str(it.team, 6),
        category: str(it.category, 40),
        headshot: str(it.headshot, 300),
        logo: str(it.logo, 300),
      }));
      if (items.some((it) => !it.answer)) return bad("every item needs an answer");
      const colorway = /^[a-z]{3,12}$/.test(String(doc.colorway || "")) ? doc.colorway : "purple";
      const layout = /^(auto|\dx\d)$/.test(String(doc.layout || "")) ? doc.layout : "auto";
      let auto = null;
      if (doc.auto && typeof doc.auto === "object") {
        const raw = JSON.stringify(doc.auto);
        if (raw.length > 40000) return bad("auto payload too large");
        auto = JSON.parse(raw);
      }
      const out = {
        date, title, desc, items, itemCount: items.length,
        colorway, customColor: null, layout,
        lockedBy: "auto-trivia-daily", lockedByEmail: "",
        lockedAt: new Date().toISOString(),
        source: "auto",
        auto,
      };
      const ref = getFirestore().collection("trivia_daily").doc(date);
      const prev = await ref.get();
      let replaced = false;
      if (prev.exists) {
        const p = prev.data() || {};
        if (p.source !== "auto") {
          res.status(409).json({ error: "locked-by-admin", title: p.title || "", lockedBy: p.lockedByEmail || p.lockedBy || "" });
          return;
        }
        replaced = true;
      }
      await ref.set(out);
      res.json({ ok: true, date, title, itemCount: items.length, replaced });
    } catch (err) {
      console.error("lockTriviaDaily error:", err);
      res.status(500).json({ error: "internal" });
    }
  }
);

// ============================================================================
// triviaResult — pooled Daily Trivia results (2026-10-29, survey R11/R13).
//
// Callable. Records ONE completed daily run per player per date and folds it
// into the public aggregate trivia_results/{date}:
//   { date, total, count, scoreSum, timeSum,
//     hist:    { s0..s40: n }          exact-score histogram
//     buckets: { b0..b4: n }           0-4 / 5-9 / 10-14 / 15-19 / 20+
//     found:   { i0..i39: n }          players who found each square
//     updatedAt }
// The run itself lives in trivia_runs/{date}_{who}. Rules deny every client
// read/write on trivia_runs and every client write on trivia_results, so the
// admin SDK here is the only writer and the aggregate the only client read.
//
// Identity: the signed-in uid, else "anon:" + a device id the page keeps in
// localStorage, so an anonymous player still counts once per date.
//
// Payload: { date, timeMs, results: ['correct'|'wrong'|null, ...], deviceId? }.
// The score is recomputed from results. The date must be today or yesterday
// in ET (a run that straddles midnight still counts).
// Response: { ok, recorded, already, yourScore, agg }. A second call for the
// same date just returns the aggregate (replays never re-count).
// ============================================================================
const TRIVIA_RESULT_MAX_SQUARES = 40;
function triviaBucket(score) {
  return score >= 20 ? 4 : Math.floor(score / 5);
}
function triviaEtDate(offsetDays) {
  const d = new Date(Date.now() + (offsetDays || 0) * 86400000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
}
exports.triviaResult = onCall(
  { memory: "256MiB", timeoutSeconds: 30 },
  async (request) => {
    const data = request.data || {};
    const date = String(data.date || "");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new HttpsError("invalid-argument", "bad date");
    if (date !== triviaEtDate(0) && date !== triviaEtDate(-1)) throw new HttpsError("failed-precondition", "not today");
    const results = Array.isArray(data.results) ? data.results : null;
    if (!results || results.length < 4 || results.length > TRIVIA_RESULT_MAX_SQUARES) throw new HttpsError("invalid-argument", "bad results");
    const total = results.length;
    const found = results.map((r) => (r === "correct" ? 1 : 0));
    const score = found.reduce((s, v) => s + v, 0);
    let timeMs = Number(data.timeMs);
    if (!Number.isFinite(timeMs) || timeMs < 0) timeMs = 0;
    timeMs = Math.min(Math.round(timeMs), 6 * 3600 * 1000);

    let who;
    if (request.auth && request.auth.uid) {
      who = "u:" + request.auth.uid;
    } else {
      const dev = String(data.deviceId || "");
      if (!/^[a-z0-9]{8,40}$/.test(dev)) throw new HttpsError("unauthenticated", "sign in or send a device id");
      who = "anon:" + dev;
    }

    const db = getFirestore();
    const runRef = db.collection("trivia_runs").doc(date + "_" + who.replace(/[^A-Za-z0-9_:-]/g, ""));
    const aggRef = db.collection("trivia_results").doc(date);
    const out = await db.runTransaction(async (tx) => {
      const [runSnap, aggSnap] = await Promise.all([tx.get(runRef), tx.get(aggRef)]);
      if (runSnap.exists) {
        const prev = runSnap.data() || {};
        return { recorded: false, already: true, yourScore: prev.score, agg: aggSnap.exists ? aggSnap.data() : null };
      }
      const now = new Date().toISOString();
      tx.set(runRef, { date, who, score, total, timeMs, results: found, createdAt: now });
      const inc = FieldValue.increment;
      const nested = { date, total, count: inc(1), scoreSum: inc(score), timeSum: inc(timeMs), updatedAt: now, hist: {}, buckets: {}, found: {} };
      nested.hist["s" + score] = inc(1);
      nested.buckets["b" + triviaBucket(score)] = inc(1);
      found.forEach((v, i) => { if (v) nested.found["i" + i] = inc(1); });
      tx.set(aggRef, nested, { merge: true });
      // Return the post-write aggregate without a second read: apply the same
      // increments to what the transaction read.
      const agg = aggSnap.exists ? aggSnap.data() : { date, total, count: 0, scoreSum: 0, timeSum: 0, hist: {}, buckets: {}, found: {} };
      agg.count = (agg.count || 0) + 1;
      agg.scoreSum = (agg.scoreSum || 0) + score;
      agg.timeSum = (agg.timeSum || 0) + timeMs;
      agg.hist = Object.assign({}, agg.hist); agg.hist["s" + score] = (agg.hist["s" + score] || 0) + 1;
      agg.buckets = Object.assign({}, agg.buckets); agg.buckets["b" + triviaBucket(score)] = (agg.buckets["b" + triviaBucket(score)] || 0) + 1;
      agg.found = Object.assign({}, agg.found);
      found.forEach((v, i) => { if (v) agg.found["i" + i] = (agg.found["i" + i] || 0) + 1; });
      agg.total = agg.total || total;
      agg.updatedAt = now;
      return { recorded: true, already: false, yourScore: score, agg };
    });
    return Object.assign({ ok: true }, out);
  }
);

// === exportLeagueTrades: trades detected in users' synced leagues ===
// (2026-11-04) Replaces the Sleeper snowball crawl as the "real trades" source
// for the Trade Calc. The site's My Teams save path already diffs every league
// snapshot and logs trades in savedLeagues[*].changeLog[*].trades; this reads
// every user's saved leagues server-side and returns ONLY the traded player
// names + league format. No uids, league ids, league or team names leave here:
// the trade id is a hash, and a trade synced by several leaguemates collapses
// to one (earliest detection wins). Gated by EXPORT_FEED_KEY like the other
// feed endpoints; called by scripts/pull_trade_trends.py (Task "MFF Real Trades").
//   GET ?days=8  -> { generated, users, leagues, trades:[{id,date,type,qbs,ppr,teams,src,s1:[names],s2:[names]}] }
// Only diff entries whose snapshot gap is <= 72h count: across a longer gap a
// player dropped by team A and later claimed by team B looks like an A->B flow.
exports.exportLeagueTrades = onRequest(
  { secrets: [EXPORT_FEED_KEY], memory: "512MiB", timeoutSeconds: 120 },
  async (req, res) => {
    try {
      const supplied = req.get("x-export-key") || "";
      if (!supplied || supplied !== EXPORT_FEED_KEY.value()) {
        res.status(403).json({ error: "forbidden" });
        return;
      }
      const days = Math.min(Math.max(parseFloat(req.query.days) || 8, 1), 21);
      const cutoff = Date.now() - days * 86400000;
      const MAX_GAP = 72 * 3600000;
      const crypto = require("crypto");
      const snap = await getFirestore().collection("user_game_data").select("savedLeagues").get();
      const out = new Map();
      const leagueKeys = new Set();
      let users = 0;
      snap.forEach((doc) => {
        const saved = (doc.data() || {}).savedLeagues;
        if (!saved || typeof saved !== "object") return;
        users++;
        Object.keys(saved).forEach((key) => {
          const lg = saved[key];
          if (!lg || typeof lg !== "object") return;
          leagueKeys.add(key);
          const log = Array.isArray(lg.changeLog) ? lg.changeLog : [];
          const fmt = lg.format || {};
          const src = key.indexOf("espn_") === 0 ? "espn" : key.indexOf("yahoo_") === 0 ? "yahoo" : "sleeper";
          log.forEach((e) => {
            if (!e || !Array.isArray(e.trades) || !e.trades.length) return;
            const at = Date.parse(e.at || "");
            if (!isFinite(at) || at < cutoff) return;
            const since = Date.parse(e.since || "");
            if (!isFinite(since) || at - since > MAX_GAP) return;
            e.trades.forEach((t) => {
              const s1 = (Array.isArray(t.aToB) ? t.aToB : []).filter((n) => typeof n === "string" && n);
              const s2 = (Array.isArray(t.bToA) ? t.bToA : []).filter((n) => typeof n === "string" && n);
              if (!s1.length || !s2.length) return;
              const sig = [s1.slice().sort().join("|"), s2.slice().sort().join("|")].sort().join("||");
              const id = "lg" + crypto.createHash("sha1").update(key + "#" + sig).digest("hex").slice(0, 12);
              const prev = out.get(id);
              if (prev && Date.parse(prev.date) <= at) return;
              out.set(id, {
                id, date: new Date(at).toISOString(),
                type: fmt.type || "redraft",
                qbs: fmt.sf ? 2 : 1,
                ppr: fmt.ppr == null ? 1 : +fmt.ppr,
                teams: Array.isArray(lg.teams) ? lg.teams.length : 12,
                src, s1, s2,
              });
            });
          });
        });
      });
      const trades = [...out.values()].sort((a, b) => Date.parse(b.date) - Date.parse(a.date));
      res.json({ generated: new Date().toISOString(), days, users, leagues: leagueKeys.size, trades });
    } catch (err) {
      console.error("exportLeagueTrades error:", err);
      res.status(500).json({ error: "internal" });
    }
  }
);
