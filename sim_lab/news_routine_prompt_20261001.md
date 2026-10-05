You are running a TWICE-DAILY NFL fantasy football news scan for the 2026 season (runs at ~12pm ET and ~10pm ET). Get the current US Eastern date/time with `TZ=America/New_York date`. If the Eastern hour is before 5pm, this is the MIDDAY run (slug `midday`); otherwise it is the END-OF-DAY run (slug `eod`). Use the EASTERN date for all filenames and commit messages. Work out the current NFL week (Week 1 opened Wed 2026-09-09; a week runs Tuesday through Monday night) - you need it for the `avail` field below.

STEP 1 — GATHER (only news since the previous scan, roughly the last 10-14 hours — the midday run covers overnight/morning insider news and, on game days, inactives; the end-of-day run covers the day's practice reports, game injuries and evening news). Use WebSearch (and WebFetch on promising results) across several angles:
- Injuries and availability (the most important angle in season): "NFL injury news today", "NFL practice report" + today's date, "ruled out", "placed on injured reserve", "expected to play", "game-time decision", and on game days "NFL inactives".
- Insiders / X chatter: search "site:x.com NFL injury" and for what top insiders and beat reporters (Adam Schefter, Ian Rapoport, Tom Pelissero, Jeremy Fowler, Mike Garafolo, team beat writers) posted, plus aggregators that mirror X reports: NBC Sports player news (Rotoworld), FantasyPros headlines, CBS Sports, ESPN, Yahoo, RotoWire.
- Injury analysts ("fantasy doctors") — sports-medicine professionals who publish expected return timelines and play/sit reads: Dr. Deepak Chona (SportsMedAnalytics, also on FantasyPros), Dr. Jesse Morse (The Injury Expertz / The Fantasy Doctors), Dr. David Chao (Sports Injury Central / SICscore), Dr. Edwin Porras (Fantasy Points), Jeff Mueller PT (PFF), and the weekly injury report at 4for4. Search e.g. "Deepak Chona injury update", "SICscore injury", "fantasy doctors injury report week N". When one of them gives a concrete timeline or a play / sit expectation for a fantasy-relevant player, record it (see STEP 3, `src_type`).
- Roles and usage: depth-chart changes, starter announcements, snap / touch share notes, coach quotes about usage, rookies gaining or losing work, trades / signings / releases.
Prioritize: injuries / recoveries and return timelines, who is expected to play or sit this week, role changes, standout or struggling performers. Check the most recent file in camp_reports/ and do not repeat items already covered there unless the story has developed.

ACCURACY RULES for injury news (these items now move projections, so a wrong one costs more than a missing one):
- An item must be about the player named in "player". Never attach another player's injury, timeline or status to him (a backup's item must not carry the starter's "season-ending" phrase in its headline — put that context in "take").
- Do not report that a player was placed on IR / PUP, ruled out, or given a timeline unless the source says so explicitly about THAT player and it is current. If unsure, leave it out.
- Prefer the team's or an insider's stated timeline over speculation. If reports conflict, use the most recent credible one and say so in "take".

STEP 2 — WRITE DIGEST. Create camp_reports/YYYY-MM-DD-midday.md or camp_reports/YYYY-MM-DD-eod.md per the slug above (make the camp_reports/ directory if it doesn't exist) with these sections:
- **Top Storylines** — 5–10 bullets, each with a one-line fantasy takeaway
- **Injury Report** — player, team, injury (specific diagnosis when known), expected timeline, who said it, fantasy impact
- **Injury Analysts** — what the sports-medicine analysts above said about specific players (timeline, re-injury risk, expected workload on return), with the analyst named
- **Depth Chart / Usage Notes** — role changes, coach quotes
- **Rookie Watch**
- **Risers / Fallers** — players whose fantasy stock moved since the last scan
- **Sources** — list of URLs used
Every item must say WHY it matters for fantasy. Keep it concise and skimmable. If it's a slow half-day, a short digest is fine — do not pad.

STEP 3 — UPDATE THE STRUCTURED NEWS FEED. Maintain data/camp_news_2026.json — this file feeds the news strip on the site's player cards AND the projection engine's injury windows, so accuracy matters more than volume. Format (strict JSON):
{"updated": "<ISO 8601 UTC timestamp>", "items": [ {"player": "Full Name", "team": "KC", "pos": "RB", "date": "YYYY-MM-DD", "headline": "short headline (<= 90 chars)", "take": "one-line fantasy takeaway", "url": "https://...", "tag": "injury|role|riser|faller|transaction|other", "avail": {...}, "src_type": "team|insider|expert|report"}, ... ] }
Rules:
- Only items about ONE specific NFL fantasy-relevant player (QB/RB/WR/TE, plus notable K/DST news). Skip team-level or generic items.
- "team" MUST be a standard abbreviation: ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LAC LAR LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS.
- "player" uses the common fantasy spelling of the name (suffixes like Jr./III as commonly written).
- "url" MUST be a direct link to the specific source — the article page or the x.com post — never a homepage or search page. Prefer the original X post when the news broke on X.
- "date" is the Eastern date the news broke.
- "avail" (OPTIONAL, injury items only) is the machine-readable availability read. Include it ONLY when the source states it about this player; omit the key entirely otherwise. Exactly one of these shapes:
    {"k": "season"}                                  out for the rest of the season (confirmed, or "likely" per the team / an insider)
    {"k": "weeks", "lo": 4, "hi": 6, "unit": "w"}    expected to miss lo to hi weeks counted from "date" (unit "g" = games). For "at least N weeks" use lo = N, hi = N + 2
    {"k": "ret", "wk": 7}                            earliest / targeted return is NFL Week 7 (IR players: the first week they are eligible if that is all that is known)
    {"k": "out", "wk": 4}                            ruled out / will not play in NFL Week 4 (BEFORE the game only — a player hurt during a game he started is NOT "out" for that week)
    {"k": "doubt", "wk": 4}                          doubtful / unlikely / not expected to play in Week 4
    {"k": "gtd", "wk": 4}                            true game-time decision for Week 4
    {"k": "play", "wk": 4}                           expected to play / cleared / off the injury report for Week 4
  When a player's status changes, add a NEW item with the new "avail" (e.g. a "play" item when he is cleared ahead of schedule) — the newest item wins.
- "src_type" (OPTIONAL): "team" (coach / team announcement), "insider" (Schefter, Rapoport, etc.), "expert" (one of the injury analysts above — start the headline with his name, e.g. "Dr. Chona: ..."), "report" (anything else). An "expert" item may carry "avail" only when the analyst gives a concrete expectation; a team or insider timeline for the same player is a separate item and takes precedence.
- Read the existing file first (create it with an empty items array if missing). PREPEND new items (newest first). Do NOT re-add a story already in the file for that player unless there is a genuine new development. You MAY add a missing "avail" (and "src_type") to an EXISTING injury item from the last 14 days when its own headline already states the timeline or status — change nothing else on existing items. Prune items older than 21 days, EXCEPT keep the most recent item that carries an "avail" of kind season / weeks / ret for any player who is still out. Validate the final file parses as JSON (e.g. `python3 -c "import json;json.load(open('data/camp_news_2026.json'))"`).

STEP 4 — COMMIT. Stage ONLY the new digest file and data/camp_news_2026.json, commit with message "Auto camp report YYYY-MM-DD midday" (or "... eod"), and push to main. Do not touch any other files in the repo.
