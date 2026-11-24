"""Dump JM prospect-model scores off the live site into data/jm_scores.json.

The JM model (21 weighted components + penalties) lives only in app.js and
needs the full lazy-loaded data bundle (college stats, PFF grades, combine),
so instead of porting it we load myfantasyfootball.co in headless Chrome,
wait until the page's data has finished loading, open the Prospect page so
buildProspectData() runs once on the complete data, and dump every scored
player with the site's own position-specific tier label/color (window._POS_TIERS).

Output: data/jm_scores.json
    { "exported_at": ..., "count": N,
      "scores": { "<Name>": {"jm": 75.8, "yr": 2019, "pos": "WR",
                              "tier": "Starter", "col": "#60a5fa"} } }

Re-run after any JM model / college-data / draft-capital change, then:
    python export_sleeper_extension_data.py   (re-bakes jmS into players.json)
"""
import json, os, sys, time

SITE = "https://www.myfantasyfootball.co"
OUT = "data/jm_scores.json"

DUMP_JS = """
const tiers = window._POS_TIERS || {};
return JSON.stringify(
  (window._pmBuiltData ? window._pmBuiltData() : [])
    .filter((p) => p.jm != null)
    .map((p) => {
      const tt = (tiers[p.pos] || []).find((t) => p.jm >= t.min) || null;
      return [p.name, p.jm, p.draftYr || null, p.pos || null,
              tt ? tt.label : null, tt ? tt.color : null,
              p.lowConfidence ? 1 : 0];
    })
);
"""


def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        path = ChromeDriverManager().install()
    except Exception:
        path = None
    opts = Options()
    # Our own GitHub Pages site — headless is fine (no bot detection).
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1400,900")
    drv = webdriver.Chrome(service=Service(path) if path else Service(), options=opts)
    drv.set_page_load_timeout(90)
    drv.set_script_timeout(90)
    return drv


def settle(drv, js, what, polls=3, every=3, limit=120):
    """Poll `js` until it returns the same truthy value `polls` times in a row."""
    last, same, t0 = None, 0, time.time()
    while time.time() - t0 < limit:
        v = drv.execute_script(js)
        same = same + 1 if (v and v == last) else (1 if v else 0)
        last = v
        if same >= polls:
            return v
        time.sleep(every)
    sys.exit("ERROR: %s never settled (%ds), last %r - nothing written" % (what, limit, last))


def main():
    drv = make_driver()
    try:
        print("loading", SITE)
        drv.get(SITE)
        # The prospect model is a lazy chunk (app-chunk-prospect.js) since the
        # 2026-10-13 app.js split: ask for it each poll (memoized, no-op when inline).
        for _ in range(60):
            if drv.execute_script(
                    "if (typeof window._ensureChunk === 'function') window._ensureChunk('prospect').catch(function(){});"
                    "return typeof window._pmBuiltData === 'function' && typeof window.switchPage === 'function'"):
                break
            time.sleep(1)
        else:
            sys.exit("ERROR: the prospect model never appeared - site load failed?")
        # WAIT BEFORE BUILDING (2026-11-24). buildProspectData() caches its first result,
        # and the site keeps adding to its inputs for several seconds after first paint: the
        # retired-player pool (ep_retired.js) is appended to D, and college stats / PFF /
        # backtest outcomes / draft picks are lazy scripts. A dump taken off an early build
        # came out ~170 past prospects short with ~250 scores shifted (1456 vs 1623 on the
        # same day), which moved every nearest-JM comparison downstream. So: let D stop
        # growing, wait for the loaders, and only then open the Prospect page, whose own
        # build also waits for the draft-capital / bio / roster overrides.
        pre = drv.execute_script("return window._pmBuiltData().length")
        if pre:
            print("note: a prospect build already existed before the data settled (%d rows)" % pre)
        settle(drv, "return (typeof EP_RETIRED !== 'undefined') ? D.length : 0", "player list (D)")
        drv.execute_async_script("""
            const done = arguments[arguments.length - 1];
            const f = (n) => (typeof window[n] === 'function') ? Promise.resolve(window[n]()).catch(() => null) : Promise.resolve();
            Promise.all(['_ensurePffData', '_ensureCollegeStatsData', '_ensureProspectStats',
                         '_ensureBacktestOutcomes', '_ensureDraftPicksData'].map(f)).then(() => done(true));
        """)
        n_d = settle(drv, "return D.length + ':' + performance.getEntriesByType('resource').length", "page data")
        drv.execute_script("window.switchPage('prospect')")
        # Count + score total of the build; unchanged over four polls = the build is final.
        sig = settle(drv, """
            const d = window._pmBuiltData(); let n = 0, t = 0;
            for (const p of d) { if (p.jm != null) { n++; t += p.jm; } }
            return n ? n + ':' + Math.round(t * 10) / 10 : 0;
        """, "prospect build", polls=4, every=3, limit=180)
        print("settled: D:resources", n_d, "| scored:total", sig)
        rows = json.loads(drv.execute_script(DUMP_JS))
    finally:
        drv.quit()

    scores = {}
    for name, jm, yr, pos, tier, col, lc in rows:
        rec = {"jm": jm, "yr": yr, "pos": pos, "tier": tier, "col": col}
        if lc:
            rec["lc"] = 1  # low-confidence: sparse data coverage, take with salt
        scores[name] = rec

    out = {
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": SITE,
        "count": len(scores),
        "scores": scores,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"   # write beside it, then swap: a failed run never leaves half a file
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print("Wrote", len(scores), "JM scores ->", OUT)


if __name__ == "__main__":
    main()
