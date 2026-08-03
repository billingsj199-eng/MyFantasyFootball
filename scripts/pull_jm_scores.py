"""Dump JM prospect-model scores off the live site into data/jm_scores.json.

The JM model (21 weighted components + penalties) lives only in app.js and
needs the full lazy-loaded data bundle (college stats, PFF grades, combine),
so instead of porting it we load myfantasyfootball.co in headless Chrome,
let buildProspectData() run, and dump every scored player with the site's
own position-specific tier label/color (window._POS_TIERS).

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


def main():
    drv = make_driver()
    try:
        print("loading", SITE)
        drv.get(SITE)
        # Wait for the app's inline script + deferred data chain to expose the hook.
        for _ in range(60):
            if drv.execute_script("return typeof window._attachJmScores === 'function'"):
                break
            time.sleep(1)
        else:
            sys.exit("ERROR: _attachJmScores never appeared — site load failed?")
        # Kicks off the async college-stats/PFF loaders on first call.
        drv.execute_script("window._attachJmScores()")
        for _ in range(90):
            n = drv.execute_script(
                "return window._pmBuiltData ? window._pmBuiltData().length : 0")
            if n:
                break
            time.sleep(1)
        else:
            sys.exit("ERROR: prospect build never completed (90s)")
        time.sleep(2)  # let the final attach/render pass settle
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
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("Wrote", len(scores), "JM scores ->", OUT)


if __name__ == "__main__":
    main()
