/* MFF Underdog Draft Helper — content script (isolated world)
 *
 * Responsibilities:
 *   1. Inject the WebSocket interceptor (injected.js) into the page's main world.
 *      Content scripts can't override window globals like WebSocket because they
 *      run in an isolated world; injected scripts run in the page's main context.
 *   2. Inject the sidebar UI (sidebar.js handles its own DOM).
 *   3. Bridge messages: page (injected.js) → window.postMessage → sidebar.js.
 *
 * Only runs on Underdog draft URLs (manifest match patterns).
 */
(function () {
  "use strict";

  // Step 1: Inject the WebSocket interceptor INTO the page (main world).
  function injectScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = chrome.runtime.getURL(src);
      s.onload = () => { s.remove(); resolve(); };
      s.onerror = (e) => reject(e);
      (document.head || document.documentElement).appendChild(s);
    });
  }

  // Run immediately at document_start so we hook WebSocket before page constructs them
  injectScript("injected.js").catch(e => console.error("[MFF] injected.js failed:", e));

  // Step 2: Inject the sidebar after DOMContentLoaded so document.body exists
  function bootSidebar() {
    if (document.body) {
      // Sidebar injects itself via fetch + script tag (handles its own asset loading)
      const s = document.createElement("script");
      s.src = chrome.runtime.getURL("sidebar.js");
      document.body.appendChild(s);
    } else {
      window.addEventListener("DOMContentLoaded", bootSidebar);
    }
  }
  bootSidebar();
})();
