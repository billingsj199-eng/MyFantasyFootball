"""
Coaching staffs per team-season (HC / OC / DC) -> pbp_cache/coaches.json
    {"2025": {"DAL": {"hc": "...", "oc": "...", "dc": "..."}}, ...}

Jack 2026-09-15: "make sure we are aware of coaches and playcallers at this time and we
can maybe assign tendencies or strengths/weakness potentially offensively and defensively".
Scheme profiles (build_scheme.py) travel with the COORDINATOR, not the franchise: a defense
whose DC changed inherits its prior from the DC's last defense, not from last year's team.

Source: Pro-Football-Reference team season pages (Coach / Offensive Coordinator /
Defensive Coordinator lines), fetched with Selenium (PFR blocks plain requests; the
Chrome here uses its own temp profile so it never collides with the PFF profile; the window
must stay VISIBLE - headless gets a block page).
Rate-limited (~3.5 s per page - PFR 429s faster clients). 2018-2026 x 32 = 288 pages,
~17 min the first time; existing team-seasons are skipped, so re-runs only pull the new
season (2026 staffs change in-season when a coordinator is fired - re-run then).

Playcaller: PFR does not say who calls plays. coach_overrides.json (next to this file,
hand-edited) maps team-season -> {"oc_play": name, "dc_play": name} when the HC calls
plays; otherwise the OC / DC is assumed to be the playcaller.

    python pull_coaches.py            # fills missing team-seasons 2018-2026
    python pull_coaches.py --years 2026 --force
"""
import argparse, json, os, re, sys, time

CACHE = r"E:\MyFantasyFootball\pbp_cache"
OUT = os.path.join(CACHE, "coaches.json")
PFR = {"ARI": "crd", "ATL": "atl", "BAL": "rav", "BUF": "buf", "CAR": "car", "CHI": "chi", "CIN": "cin", "CLE": "cle",
       "DAL": "dal", "DEN": "den", "DET": "det", "GB": "gnb", "HOU": "htx", "IND": "clt", "JAX": "jax", "KC": "kan",
       "LV": "rai", "LAC": "sdg", "LAR": "ram", "MIA": "mia", "MIN": "min", "NE": "nwe", "NO": "nor", "NYG": "nyg",
       "NYJ": "nyj", "PHI": "phi", "PIT": "pit", "SF": "sfo", "SEA": "sea", "TB": "tam", "TEN": "oti", "WAS": "was"}


def _driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        path = ChromeDriverManager().install()
    except Exception:  # noqa: BLE001
        path = None
    o = Options()
    # VISIBLE window on purpose: PFR serves a 28 KB block page to headless Chrome (probe 2026-09-15)
    # no custom user-agent / --no-sandbox either: a UA that does not match the real Chrome build also gets the block page
    o.add_argument("--window-size=1200,900")
    o.add_experimental_option("excludeSwitches", ["enable-automation"]); o.add_experimental_option("useAutomationExtension", False)
    o.add_argument("--disable-blink-features=AutomationControlled")
    d = webdriver.Chrome(service=Service(path) if path else Service(), options=o)
    d.set_page_load_timeout(60)
    return d


def parse(html):
    """PFR meta block: 'Coach: <a>Name</a> (rec)', 'Offensive Coordinator: <a>Name</a>', 'Defensive Coordinator: ...'."""
    out = {}
    for label, key in (("Coach", "hc"), ("Offensive Coordinator", "oc"), ("Defensive Coordinator", "dc")):
        m = re.search(r"<strong>\s*" + label + r":?\s*</strong>\s*(.*?)(?:<br|</p)", html, re.S | re.I)
        if not m:
            continue
        names = re.findall(r"<a[^>]*>([^<]+)</a>", m.group(1))
        txt = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        out[key] = ", ".join(n.strip() for n in names) if names else re.sub(r"\s*\(.*?\)\s*", "", txt).strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2018-2026")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--delay", type=float, default=3.5)
    a = ap.parse_args()
    if "-" in a.years:
        y0, y1 = a.years.split("-"); years = list(range(int(y0), int(y1) + 1))
    else:
        years = [int(y) for y in a.years.split(",")]
    data = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    todo = [(y, t) for y in years for t in PFR if a.force or not data.get(str(y), {}).get(t, {}).get("hc")]
    print(f"coaches: {len(todo)} team-seasons to fetch", flush=True)
    if not todo:
        return 0
    d = _driver()
    try:
        for i, (y, t) in enumerate(todo):
            url = f"https://www.pro-football-reference.com/teams/{PFR[t]}/{y}.htm"
            try:
                d.get(url)
                # PFR fronts a JS challenge page (~28 KB) that resolves in a few seconds - poll for the real page
                html = d.page_source
                for _ in range(20):
                    if "<strong>Coach" in html or "Coordinator" in html:
                        break
                    time.sleep(1.0); html = d.page_source
            except Exception as e:  # noqa: BLE001
                print(f"  {y} {t}: load error {str(e)[:60]}", flush=True); time.sleep(a.delay); continue
            if "429" in html[:2000] and "Too Many" in html[:4000]:
                print("  429 rate limited - sleeping 60s", flush=True); time.sleep(60)
                d.get(url); html = d.page_source
            rec = parse(html)
            if rec.get("hc"):
                data.setdefault(str(y), {})[t] = rec
                if i % 8 == 0 or i == len(todo) - 1:
                    json.dump(data, open(OUT, "w", encoding="utf-8"), indent=1)
                    print(f"  {y} {t}: HC {rec.get('hc')} | OC {rec.get('oc', '?')} | DC {rec.get('dc', '?')}  ({i + 1}/{len(todo)})", flush=True)
            else:
                print(f"  {y} {t}: no coach block parsed ({len(html)} bytes)", flush=True)
            time.sleep(a.delay)
    finally:
        d.quit()
        json.dump(data, open(OUT, "w", encoding="utf-8"), indent=1)
    print(f"wrote {OUT}: " + ", ".join(f"{y} {len(v)}" for y, v in sorted(data.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
