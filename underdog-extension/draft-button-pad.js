/* MFF draft-button-pad — keeps Underdog's "Draft" confirmation button
 * usable alongside the player list.
 *
 * Three fixes:
 *  1. Bottom padding on the scrolling player list while a floating
 *     (fixed/sticky) Draft button is visible, so every row can scroll
 *     clear of it instead of being covered.
 *  2. Click-through wrapper: a floating button usually sits inside a
 *     larger transparent strip that swallows clicks on the rows around
 *     and beneath it. The strip gets pointer-events:none and the button
 *     pointer-events:auto.
 *  3. In-row overlay boost: the per-row Draft confirm overlay can lose
 *     the stacking fight against the row's own stat cells — notably on
 *     rows our sidebar decorated (decoratePlayerList sets
 *     position:relative on outlined rows for the corner label, which
 *     changes paint/hit-test order). Symptom: stat numbers bleed over
 *     the yellow Draft button and clicks on it die. The button and its
 *     positioned ancestors inside the row get a very high z-index so
 *     the button always paints and hit-tests on top.
 *
 * Identifies Draft buttons by exact text ("Draft" — strict, so the
 * "Drafting…" loading state and unrelated buttons never match), and the
 * floating wrapper by walking ancestors for computed fixed/sticky —
 * robust against Underdog's hashed class names. Skips the extension's
 * own sidebar (#mff-sidebar).
 */
(function () {
  "use strict";
  if (window.__mffDraftBtnPadLoaded) return;
  window.__mffDraftBtnPadLoaded = true;

  var POLL_MS = 1500;
  var PAD_BUFFER = 24; // extra px above the button so rows aren't flush against it
  var APPLIED_ATTR = "data-mff-draft-pad";
  var ORIG_ATTR = "data-mff-orig-pb";
  var PE_ATTR = "data-mff-draft-pe"; // marks wrapper/button we set pointer-events on
  var BOOST_ATTR = "data-mff-draft-boost"; // marks in-row nodes we z-boosted
  var ROW_MAX_H = 140; // anything taller than this is beyond row scale

  // Every visible button reading exactly "Draft".
  function findAllDraftButtons() {
    var buttons = document.querySelectorAll("button");
    var out = [];
    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      var text = (btn.textContent || "").trim();
      if (text !== "Draft") continue;
      var rect = btn.getBoundingClientRect();
      if (rect.height < 16 || rect.height > 200) continue;
      if (rect.width < 40) continue;
      out.push({ btn: btn, rect: rect });
    }
    return out;
  }

  // Innermost fixed/sticky ancestor (the floating wrapper), or null for
  // in-row buttons. The button itself is often static/absolute inside the
  // floating strip, which is why a button-only position check misses it.
  function floatingWrapperOf(btn) {
    var node = btn;
    for (var depth = 0; node && node !== document.body && depth < 8; depth++) {
      var cs = window.getComputedStyle(node);
      if (cs.position === "fixed" || cs.position === "sticky") return node;
      node = node.parentElement;
    }
    return null;
  }

  // The floating Draft button (fixed/sticky wrapper) if one is up.
  function findDraftButton() {
    var all = findAllDraftButtons();
    for (var i = 0; i < all.length; i++) {
      var wrapper = floatingWrapperOf(all[i].btn);
      if (!wrapper) continue;
      // Floating UI lives in the lower part of the viewport; the player-list
      // panel can end well above the viewport bottom, so allow up to 320px.
      if (window.innerHeight - all[i].rect.bottom > 320) continue;
      return { btn: all[i].btn, rect: all[i].rect, wrapper: wrapper };
    }
    return null;
  }

  // Fix 3: lift in-row Draft overlays above their row's other content.
  // Walks from the button up through row-scale ancestors, giving each
  // positioned node (and the button itself) a huge z-index. Scoped hard:
  // the walk stops at the first ancestor taller than ROW_MAX_H, so
  // nothing outside the row is ever touched. Boosted nodes are marked and
  // skipped on later passes; the nodes vanish with the row when Underdog
  // removes or reuses it, which is why there's no restore path.
  function boostInRowButtons() {
    var all = findAllDraftButtons();
    for (var i = 0; i < all.length; i++) {
      var btn = all[i].btn;
      if (floatingWrapperOf(btn)) continue; // floating strip: fixes 1+2 handle it
      if (btn.getAttribute(BOOST_ATTR)) continue;
      btn.setAttribute(BOOST_ATTR, "1");
      btn.style.pointerEvents = "auto";
      var node = btn;
      for (var depth = 0; node && node !== document.body && depth < 6; depth++) {
        var r = node.getBoundingClientRect();
        if (r.height > ROW_MAX_H) break;
        var cs = window.getComputedStyle(node);
        if (node === btn || cs.position !== "static") {
          if (cs.position === "static") node.style.position = "relative";
          node.style.zIndex = "999999";
          node.setAttribute(BOOST_ATTR, "1");
        }
        node = node.parentElement;
      }
    }
  }

  function findScrollContainers(sidebarEl) {
    var all = document.querySelectorAll("div, main, section, ul, ol");
    var out = [];
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      // Skip our own sidebar tree.
      if (sidebarEl && (el === sidebarEl || sidebarEl.contains(el))) continue;
      if (el.id && el.id.indexOf("mff-") === 0) continue;
      var cs = window.getComputedStyle(el);
      if (cs.overflowY !== "auto" && cs.overflowY !== "scroll") continue;
      if (el.scrollHeight <= el.clientHeight) continue;
      // Only substantial scrollers — avoids targeting tiny dropdowns.
      if (el.clientHeight < 240) continue;
      if (el.clientWidth < 200) continue;
      out.push(el);
    }
    return out;
  }

  function applyPadding(neededPad) {
    var sidebarEl = document.getElementById("mff-sidebar");
    var containers = findScrollContainers(sidebarEl);
    var padStr = neededPad + "px";
    for (var i = 0; i < containers.length; i++) {
      var c = containers[i];
      if (c.getAttribute(APPLIED_ATTR) === padStr) continue;
      if (!c.hasAttribute(ORIG_ATTR)) {
        c.setAttribute(ORIG_ATTR, c.style.paddingBottom || "");
      }
      c.style.paddingBottom = padStr;
      c.setAttribute(APPLIED_ATTR, padStr);
    }
    // Also clean up containers we previously padded that no longer match
    // (e.g. Underdog swapped the scroll container during a re-render).
    var stale = document.querySelectorAll("[" + APPLIED_ATTR + "]");
    var live = new Set(containers);
    for (var j = 0; j < stale.length; j++) {
      if (live.has(stale[j])) continue;
      restoreEl(stale[j]);
    }
  }

  function restoreEl(el) {
    var orig = el.getAttribute(ORIG_ATTR);
    el.style.paddingBottom = orig || "";
    el.removeAttribute(APPLIED_ATTR);
    el.removeAttribute(ORIG_ATTR);
  }

  function clearAllPadding() {
    var padded = document.querySelectorAll("[" + APPLIED_ATTR + "]");
    for (var i = 0; i < padded.length; i++) restoreEl(padded[i]);
  }

  // Make the wrapper strip click-through while keeping the button live.
  // Only when the wrapper is meaningfully larger than the button — a
  // wrapper that hugs the button isn't blocking anything.
  function applyClickThrough(found) {
    var wRect = found.wrapper.getBoundingClientRect();
    var bRect = found.rect;
    // Never neutralize a large container — if the fixed/sticky ancestor is
    // bigger than a confirm strip, everything inside it except the Draft
    // button would go dead. Bail and leave pointer-events alone.
    if (wRect.height > 220) return;
    var blocking =
      wRect.width - bRect.width > 40 || wRect.height - bRect.height > 24;
    if (!blocking) return;
    if (!found.wrapper.hasAttribute(PE_ATTR)) {
      found.wrapper.setAttribute(PE_ATTR, found.wrapper.style.pointerEvents || "");
      found.wrapper.style.pointerEvents = "none";
    }
    if (!found.btn.hasAttribute(PE_ATTR)) {
      found.btn.setAttribute(PE_ATTR, found.btn.style.pointerEvents || "");
      found.btn.style.pointerEvents = "auto";
    }
  }

  function clearClickThrough(current) {
    var marked = document.querySelectorAll("[" + PE_ATTR + "]");
    for (var i = 0; i < marked.length; i++) {
      var el = marked[i];
      if (current && (el === current.wrapper || el === current.btn)) continue;
      el.style.pointerEvents = el.getAttribute(PE_ATTR) || "";
      el.removeAttribute(PE_ATTR);
    }
  }

  function tick() {
    try {
      var found = findDraftButton();
      if (found) {
        // Pad by the distance from the button's top edge to the viewport
        // bottom — every row can then scroll clear of the button.
        applyPadding(Math.ceil(window.innerHeight - found.rect.top) + PAD_BUFFER);
        applyClickThrough(found);
        clearClickThrough(found); // drop stale marks from prior renders
      } else {
        clearAllPadding();
        clearClickThrough(null);
      }
      boostInRowButtons();
    } catch (_) {}
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", tick);
  } else {
    tick();
  }
  setInterval(tick, POLL_MS);
})();
