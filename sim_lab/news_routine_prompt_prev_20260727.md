You are running a TWICE-DAILY NFL training camp fantasy football news scan for the 2026 preseason (runs at ~12pm ET and ~10pm ET). Get the current US Eastern date/time with `TZ=America/New_York date`. If the Eastern hour is before 5pm, this is the MIDDAY run (slug `midday`); otherwise it is the END-OF-DAY run (slug `eod`). Use the EASTERN date for all filenames and commit messages.

STEP 1 — GATHER (only news since the previous scan, roughly the last 10-14 hours — the midday run covers overnight/morning insider news, the end-of-day run covers the day's practice reports and evening news). Use WebSearch (and WebFetch on promising results) across several angles:
- General: "NFL training camp news fantasy football" + today's date; "training camp standouts"; "NFL camp battle updates"
- Injuries: "NFL training camp injury news today"
- X/Twitter chatter: search "site:x.com NFL training camp" and for what top insiders/beat reporters (Adam Schefter, Ian Rapoport, Tom Pelissero, team beat writers) posted, plus aggregators that mirror X reports: NBC Sports player news (Rotoworld), FantasyPros headlines, CBS Sports, ESPN, Yahoo.
- Rookies: "rookie training camp report fantasy"
Prioritize: injuries/recoveries, depth-chart battles and starter announcements, standout or struggling performers, rookie buzz, holdouts/contract standoffs, coach quotes about usage/roles, and any trades/signings/releases. Check the most recent file in camp_reports/ and do not repeat items already covered there unless the story has developed.

STEP 2 — WRITE DIGEST. Create camp_reports/YYYY-MM-DD-midday.md or camp_reports/YYYY-MM-DD-eod.md per the slug above (make the camp_reports/ directory if it doesn't exist) with these sections:
- **Top Storylines** — 5–10 bullets, each with a one-line fantasy takeaway
- **Injury Report** — player, team, injury, expected timeline, fantasy impact
- **Depth Chart / Usage Notes** — role changes, camp battles, coach quotes
- **Rookie Watch**
- **Risers / Fallers** — players whose fantasy stock moved since the last scan
- **Sources** — list of URLs used
Every item must say WHY it matters for fantasy. Keep it concise and skimmable. If it's a slow half-day, a short digest is fine — do not pad.

STEP 3 — UPDATE THE STRUCTURED NEWS FEED. Maintain data/camp_news_2026.json — this file feeds the "Camp News" strip on the site's player cards, so accuracy matters more than volume. Format (strict JSON):
{"updated": "<ISO 8601 UTC timestamp>", "items": [ {"player": "Full Name", "team": "KC", "pos": "RB", "date": "YYYY-MM-DD", "headline": "short headline (<= 90 chars)", "take": "one-line fantasy takeaway", "url": "https://...", "tag": "injury|role|riser|faller|transaction|other"}, ... ] }
Rules:
- Only items about ONE specific NFL fantasy-relevant player (QB/RB/WR/TE, plus notable K/DST news). Skip team-level or generic items.
- "team" MUST be a standard abbreviation: ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LAC LAR LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS.
- "player" uses the common fantasy spelling of the name (suffixes like Jr./III as commonly written).
- "url" MUST be a direct link to the specific source — the article page or the x.com post — never a homepage or search page. Prefer the original X post when the news broke on X.
- "date" is the Eastern date the news broke.
- Read the existing file first (create it with an empty items array if missing). PREPEND new items (newest first). Do NOT re-add a story already in the file for that player unless there is a genuine new development. Prune items older than 21 days. Validate the final file parses as JSON (e.g. `python3 -c "import json;json.load(open('data/camp_news_2026.json'))"`).

STEP 4 — COMMIT. Stage ONLY the new digest file and data/camp_news_2026.json, commit with message "Auto camp report YYYY-MM-DD midday" (or "... eod"), and push to main. Do not touch any other files in the repo.
