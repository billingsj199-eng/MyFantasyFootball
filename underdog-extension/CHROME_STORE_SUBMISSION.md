# Chrome Web Store Submission Guide

Copy/paste fields for the Chrome Web Store Developer Dashboard.
Submission URL: https://chrome.google.com/webstore/devconsole/

---

## Item details

### Name
```
MFF Underdog Draft Helper
```

### Short summary (132 char limit)
```
Live Underdog draft recommendations powered by Jack's rankings — BPA, ADP value, BBM advance-rate, stacking, and true-cliff alerts.
```

### Detailed description
```
The MFF Underdog Draft Helper is a Chrome extension that adds a live recommendation sidebar to your Underdog Fantasy drafts. Built for Best Ball Mania, it surfaces the best pick on your clock by combining Jack's rankings with a BBM advance-rate optimizer and statistical shrinkage so small-sample builds don't dominate.

WHAT IT SHOWS LIVE
• Best Player Available — value-weighted using Jack's rankings + Underdog ADP
• Stacking analysis — flags QB+pass-catcher pairings on your roster
• True-cliff milestones — get warned when a position is about to fall off
• Recency-weighted historical data — recent BBM seasons matter more
• Pick-by-rank-by-round priors so the tool understands draft context, not just BPA

HOW IT WORKS
The sidebar reads draft state from the Underdog page and matches it against rankings synced from your account at myfantasyfootball.org. All data stays on your computer in Chrome's local storage — nothing is transmitted to a third-party server.

REQUIREMENTS
• A myfantasyfootball.org account if you want to use your custom rankings (free — Jack's official rankings work without sign-in)
• Active Underdog Fantasy account (the extension reads draft state from Underdog's own pages)

PRIVACY
Full privacy policy at https://myfantasyfootball.org/privacy.html. We don't collect, transmit, or share user data.

SOURCE
This is a personal project, not affiliated with Underdog Fantasy.
```

### Category
`Sports`

### Language
`English (US)`

---

## Privacy practices

### Single purpose description
```
Display live draft pick recommendations on Underdog Fantasy draft pages, using rankings synced from the user's myfantasyfootball.org account.
```

### Permission justifications

**`storage`**
```
Required to persist the user's draft state (which players have been picked, which slot they hold), the sidebar's size and position, and a local copy of their MFF rankings synced from myfantasyfootball.org. All data is stored locally in chrome.storage.local — never transmitted to any server we operate.
```

**`cookies`**
```
Required to read the user's existing Underdog Fantasy session cookies so authenticated calls to Underdog's own draft API work reliably. Some Underdog endpoints reject calls that rely solely on credentials:'include' from a service worker context, so the extension reads cookies directly and forwards them in the Cookie header. Cookies are only read for underdogfantasy.com and underdogsports.com, are only sent back to Underdog's own servers, and are never logged, transmitted, or stored elsewhere.
```

**Host permission justification (for `https://*.underdogfantasy.com/*` and `https://*.underdogsports.com/*`)**
```
The extension's primary function is to inject a draft-helper sidebar onto Underdog Fantasy draft pages. It needs to read the page's DOM to track picks, intercept Underdog's WebSocket frames to detect new picks live, and call Underdog's own draft API to fetch player metadata. Without these host permissions, the sidebar cannot function on the page where it's needed.
```

**Host permission justification (for `https://myfantasyfootball.org/*` and `https://*.myfantasyfootball.org/*` and `https://billingsj199-eng.github.io/*`)**
```
The extension's recommendations are powered by rankings the user maintains on myfantasyfootball.org. When the user opens that site, a small bridge content script reads their saved rankings into chrome.storage.local so the Underdog sidebar can use them as the recommendation source. Without this access, the extension would have no way to use the user's custom rankings — they would have to manually export and import them. billingsj199-eng.github.io is the GitHub Pages backing host for myfantasyfootball.org and serves the same content; both are listed because the site is occasionally accessed via either URL.
```

**Are you using remote code?** `No`
(All JavaScript is bundled in the extension package; data files are loaded from the extension itself, not over the network.)

### Data usage disclosure
- ☐ Personally identifiable information — *No*
- ☐ Health information — *No*
- ☐ Financial and payment information — *No*
- ☐ Authentication information — *Yes* — *Underdog session cookies are read locally and forwarded to Underdog's own API only; never transmitted to any third-party server.*
- ☐ Personal communications — *No*
- ☐ Location — *No*
- ☐ Web history — *No*
- ☐ User activity — *Yes* — *The user's draft picks on Underdog are read from the page so the sidebar can update its recommendations. Stored locally only.*
- ☐ Website content — *Yes* — *The extension reads the Underdog draft page DOM to extract draft state. Read-only, processed locally, never transmitted.*

### Privacy policy URL
```
https://myfantasyfootball.org/privacy.html
```

### Certifications
- [x] I do not sell or transfer user data to third parties, outside of the approved use cases
- [x] I do not use or transfer user data for purposes that are unrelated to my item's single purpose
- [x] I do not use or transfer user data to determine creditworthiness or for lending purposes

---

## Store assets needed (you'll have to create these)

Required:
- **Icon 128×128** — already in `icons/icon-128.png`
- **At least 1 screenshot** at 1280×800 or 640×400 — capture the sidebar in action on a real or mock Underdog draft

Optional but help conversion:
- **Small promo tile** 440×280
- **Marquee promo tile** 1400×560
- A 30-second YouTube demo URL

---

## Pre-submission cleanup checklist

Before zipping the folder for upload, delete these files (they're dev artifacts that will trigger reviewer questions or just bloat the package):

```
underdog-extension/sidebar.js.bak
underdog-extension/sidebar.js.bak-bbm-20260501-182031
underdog-extension/sidebar.js.tmp
underdog-extension/sidebar.css.bak-bbm-20260501-182031
underdog-extension/engine.js.bak
underdog-extension/engine.js.bak-bbm-20260501-182031
underdog-extension/engine.js.tmp
underdog-extension/manifest.json.bak-20260501-182031
```

PowerShell one-liner to clean (run from project root):
```powershell
Get-ChildItem underdog-extension -Recurse -Include *.bak,*.bak-*,*.tmp | Remove-Item -Force
```

Then zip the folder for upload:
```powershell
Compress-Archive -Path "underdog-extension\*" -DestinationPath "mff-draft-helper.zip" -Force
```

The same `mff-draft-helper.zip` works as both:
1. The Chrome Web Store upload package
2. The fallback download at `myfantasyfootball.org/mff-draft-helper.zip` for users who prefer dev-mode install

---

## After publication

Once the extension is approved, swap the modal's download link in `index.html`:
```html
<!-- Before -->
<a id="draftHelperDownload" href="/mff-draft-helper.zip" download ...>Download the extension</a>

<!-- After -->
<a id="draftHelperDownload" href="https://chrome.google.com/webstore/detail/<EXTENSION-ID>" target="_blank" ...>Add to Chrome</a>
```

Also update the install steps (3-step → 1-step "Click Add to Chrome").
