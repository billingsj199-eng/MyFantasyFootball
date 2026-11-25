# KTC lasting-value study + dynasty rating prototype (2026-11-24)

Jack: "look into updating our sims as a whole and even create a rating score for each player in fantasy (focus on
dynasty first)" / "players value isnt just based on solely production" / "do full study on ktc dynasty ratings as it is
public consensus and lets try to find players that have lasting value to create a rating" / "players may spike
historically week to week but we want to be able to beat the market long term".

**Nothing live changed.** No engine, site, export or extension file was touched. Everything is new research files.

## What was built

| File (sim_lab) | What it does |
|---|---|
| `pull_ktc_wayback.py` | Pulls one archived KTC dynasty list per month from the Wayback Machine. 47 lists, Sept 2020 to Nov 2026. 44 are full lists (345-464 players); 3 early ones are top-100 only. |
| `ktc_lasting_panel.py` | One row per player per list date: price that day, price 1-5 years later, and every trait known that day. 19,853 rows, 1,028 players. |
| `research_ktc_lasting.py` | The study (base rates, who holds value, held-out and forward tests). Logs in `_dyn_cache/ktc_wb/lasting_*.log`. |
| `ktc_lasting_rating.py` | The prototype rating for today's board. Output `_dyn_cache/ktc_wb/rating_1qb.csv` and `rating_sf.csv`. |

Why archived lists: KTC's own history only exists for players still listed today, so busts and retired players are
missing. An archived list has everybody who had a price that day.

One fix that matters: KTC's numbers inflate. The 300th player was worth 291 in Jan 2021 and 1,781 in July 2026. Every date
was put on one scale by rank (a player's value = what KTC gives that rank on the 2025-26 curve). A player who later
fell off the list counts as 0.

## Finding 1: how long a price lasts (1QB, players ranked in KTC's top 250)

| KTC rank that day | value kept +1 yr | +2 yr | +3 yr | +5 yr |
|---|---|---|---|---|
| 1-12 | 91% | 84% | 71% | 51% |
| 13-24 | 92% | 81% | 72% | 47% |
| 25-50 | 92% | 82% | 70% | 48% |
| 51-100 | 87% | 70% | 53% | 27% |
| 101-175 | 82% | 62% | 44% | - |
| 176-250 | 75% | 52% | 32% | - |

Top-50 assets hold about the same no matter where in the top 50 they sit. Below rank 50 value melts much faster:
half of the rank 51-100 players have lost at least half their value three years later.

## Finding 2: the market's one big, repeatable miss is age by position

"Excess" = value kept compared with the average player bought at the SAME price. Plus means he was worth more later
than his price said.

| Group | +1 yr | +2 yr | +3 yr |
|---|---|---|---|
| TE under 23.5 | +12% | +23% | +33% |
| TE 23.5-25.5 | +11% | +17% | +16% |
| WR under 22.5 | +4% | +11% | +17% |
| WR 22.5-24.5 | +4% | +11% | +9% |
| QB 24-27 | +2% | +9% | +23% |
| RB under 24 | 0% | +3% | +2% |
| WR 24.5-26.5 | +3% | 0% | -1% |
| RB 24-25.5 | +1% | 0% | -8% |
| WR 26.5-28.5 | -8% | -14% | -16% |
| RB 25.5-27 | -4% | -13% | -19% |
| RB 27+ | -19% | -25% | -24% |
| WR 28.5+ | -19% | -28% | -26% |

It showed up in every single year, not just on average (1-year excess by the year the player was bought):

| Group | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|
| RB 25.5+ | -16% | -15% | -15% | -11% | -5% |
| WR 26.5+ | -14% | -13% | -15% | -13% | -12% |
| TE under 25.5 | +20% | +7% | +8% | +7% | +16% |
| Vets who missed 6+ games | -10% | -7% | -15% | -12% | -5% |

Superflex gives the same picture. The one difference: quarterbacks 33 and older melt (-17% / -21% / -23%).

## Finding 3: older players do score more, but not enough to pay for the melt

Same price tier, next two years (points = PPR points over the starter line, per year):

| KTC rank | Older: points / value kept | Young: points / value kept |
|---|---|---|
| 1-24 | 100 / 70% | 82 / 87% |
| 25-50 | 65 / 69% | 42 / 90% |
| 51-100 | 37 / 60% | 21 / 81% |
| 101-175 | 11 / 42% | 7 / 73% |

Older = RB 25.5+, WR 26.5+, TE 27.5+, QB 30+. Young = RB under 24, WR under 24.5, TE under 25.5, QB under 27.

An older player at the same price gives you about 20 more points a year and costs you about 20 more points of value
over two years (roughly 1,000-1,250 KTC). What the market itself pays for a point: about 12 KTC per point across the
top 100 (value lost in a year divided by points scored), about 24 across the top 250. At 12, the older player nets out
about 10-12% of his price worse over two years. At 24 it is close to even. So older producers are fair for a team that
is winning now and overpriced for everyone else. That is the contender / rebuilder dial, with a number on it.

## Finding 4: with age held equal, almost nothing else beats the price

Tested against players of the same price, same position AND same age:

| Trait | Result |
|---|---|
| Draft capital (young or veteran) | Nothing. Already in the price. |
| Track record (top-12 / top-24 seasons) | Nothing. |
| Price above or below production ("hype" vs "proven") | Nothing. |
| KTC move over the last 6 / 12 months | Nothing useful. Fallers do not bounce, risers do not give it back. |
| Distance from his KTC peak | Nothing. No buy-the-dip edge. |
| Contract size, years left | Small. Veterans on deals under 2% of the cap: -5% at 1 year. |
| TD reliance, QB rushing share, RB role, target share | Nothing reliable. |
| KTC crowd "keep" votes | Nothing once age is equal (it was an age stand-in). |
| **Games missed in the last 12 months (veterans)** | **Real. 0-5 games: -8% at 1 yr. 6-11 games: -6%. 16+ games: +3%.** |
| WR size | Weak. Under 6-0: -6% at 3 years. Under 190 lb: -3% at 1 year. |

This matches the October research on a different market (FFC dynasty ADP): the market is good, the event stuff is
priced in, and the lasting misses are age and injuries.

## Does it hold up on players and years the model never saw?

Model = price + position + age + games in the last 12 months + experience. "Beyond-price" = rank correlation between
what the model says the price is missing and what really happened (0 = no edge).

| Test | +1 yr | +2 yr |
|---|---|---|
| Forward in time, beyond-price | +0.149 (2023 +0.11, 2024 +0.16, 2025 +0.17) | +0.262 (2024 only) |
| Forward, model's AVOID third vs BUY third (vs same-price average) | -4% vs +9% | -9% vs +18% |
| Players held out (5 folds), beyond-price | +0.155 | +0.251 |
| Rank correlation with future value, price alone -> price + model (forward) | .809 -> .803 | .706 -> .735 |

Reading: price alone is already a strong forecast, and at one year the model does not improve the overall order.
The edge is in the gap (who is over- or under-priced), and it grows with the holding period. A bigger model with all
36 traits tested worse going forward (+0.092 at 1 year, error up), so the rating uses the small one.

Three-year results exist only inside the sample (14 dates, 2021-23). There is not enough history yet to test three
years forward.

## The prototype rating

- **Lasting value** = expected KTC value averaged over the next 1, 2 and 3 years (same-price average, moved by
  position x age and games missed).
- **Points** = expected points over the starter line per year for the next two years.
- **Total** = lasting value + 12 x points. (12 = neutral team. 24 = contender. 0 = rebuild.)
- **Rating 0-99** = 99 x square root of (total / best total on the board).
- **Edge** = total vs the average total at his KTC price. LASTING at +8% or better, MELTING at -8% or worse.

Today, 1QB top 25 (KTC rank in brackets): Smith-Njigba 99 (2), Gibbs 96 (1), Bijan 94 (3), Chase 90 (4), Nabers 88 (11),
Nacua 88 (8), Bowers 87 (5), St. Brown 86 (7), Josh Allen 86 (6), Burden 85 (15), Golden 84 (14), P. Washington 83 (19),
London 83 (16), Love 82 (18), K. Walker 82 (9), Lamb 82 (10), McBride 81 (12), Tate 81 (30), Loveland 81 (37),
Burrow 79 (27), McMillan 79 (26), Caleb Williams 79 (28), Irving 78 (22), Cook 77 (17), Jefferson 77 (13).

Biggest LASTING edges in KTC's top 150 (1QB): Raridon, Stowers, Cam Ward, Loveland, Nix, Bryce Young, Stroud, Fannin,
Mayer, Tate, Chris Bell, Strange, Herbert, Shough, Downs, Sadiq, Pitts, Fields, Nabers, Maye.

Biggest MELTING edges (1QB): Diggs, Evans, D. Adams, A.J. Brown, Metcalf, Mason, Dell, D.J. Moore, Etienne, Henry,
Pierce, Jacobs, Allgeier, Barkley, DeVonta Smith, Swift, Stevenson, McCaffrey, Jefferson, Javonte Williams.

Full tables: `sim_lab/_dyn_cache/ktc_wb/rating_1qb.csv`, `rating_sf.csv` (300 players each, with the contender and
rebuild versions).

## What this cannot say yet

- Six seasons of KTC lists is a short history: five buy-years for the 1-year test, four for 2 years.
- The rating is mostly price + age + health. It will not find a breakout or a bust inside an age group. The study
  says the public price already does that about as well as any trait we have.
- Rookie picks are not in it (players only).
- Today's rows use the Nov 8 archived list re-priced with the Nov 23 site KTC pull (488 of 500 matched).
- The points piece barely beats price alone (.646 vs .645 rank correlation), so it mostly matters through the dial.
- KTC's raw scale understates stars in real trades; the rating inherits that.

## Where this leaves the sims

1. **The October rejection of age terms in MFF VALUE needs a second look.** Those tests graded on production only
   (points over replacement). Graded on production plus what the player is still worth, age by position is the biggest
   and steadiest effect in the data. Re-test MFF VALUE against that target before changing it.
2. **Missed games** is the second lever (the injury-slide note on the card already says this; the value does not).
3. **Open sim proposals from the 11-21 review are still waiting**: opposing-QB correlation (P-20261121-2, recommended),
   late-season consensus weight (-3, your call), ADP in the 2027 preseason model (-7, parked), data pulls (-5), product
   builds (-6), plus the older P-20261013-3, P-20261023-2 and P-20261110-1.
4. **Redraft rating** would be a separate build: rest-of-season projection plus role security, graded weekly.

## Decisions for Jack

1. Is the rating its own number, or does it become the new MFF VALUE order?
2. Default dial: neutral (12 per point), or contender / rebuilder chosen per team?
3. Start a daily forward tracker now so it has a real record by the offseason?

---

## Addendum: rating tested as the MFF VALUE order (Jack 11-24 "Test as MFF VALUE")

`backtest_rating_vs_fair.py` (logs `_dyn_cache/ktc_wb/rating_vs_fair_1qb.log`, `_sf.log`). Nothing live changed.

How it was graded: five preseason KTC lists (2021-07-24, 2022-08-14, 2023-10-01, 2024-08-13, 2025-08-25), top 250
players, 238-245 per year with a Dynasty SIM value. For each list the past MFF VALUE order was rebuilt (shipped
weights 0.5 / 0.3 / 0.5, shipped market coefficients, time-honest sim). The rating was refit without the test year.
Target = KTC value at the end of the hold + 12 x points over the starter line scored while held. Number = rank
correlation with that target (higher is better).

**1QB, neutral team (12 per point)**

| Hold | KTC price | MFF VALUE (shipped) | Rating | Rating vs MFF VALUE | By year |
|---|---|---|---|---|---|
| 1 year | .779 | .775 | .768 | -.007 | 2021 +.005, 2023 +.002, 2024 -.012, 2025 -.021 |
| 2 years | .691 | .697 | .722 | +.025 | 2022 +.019, 2023 +.030, 2024 +.028 |
| 3 years | .665 | .674 | .710 | +.036 | 2021 +.032, 2022 +.024, 2023 +.049 |

**Superflex, neutral team**

| Hold | KTC price | MFF VALUE (shipped) | Rating | Rating vs MFF VALUE |
|---|---|---|---|---|
| 1 year | .792 | .775 | .778 | +.003 (2025: -.016) |
| 2 years | .699 | .691 | .726 | +.035 |
| 3 years | .669 | .671 | .709 | +.038 |

Other reads (1QB):
- **Inside the KTC top 100 nothing beats the plain KTC price at 1 year**: price .674, rating .658, MFF VALUE .635.
  At 2 years .600 / .596 / .587. At 3 years .585 / .574 / .566.
- Share of the best possible top-50 captured: about equal for all three (1 yr 92.7 / 92.2 / 91.7%, 2 yr 87.2 / 86.9 /
  87.8%, 3 yr 84.2 / 83.0 / 84.6% for price / rating / MFF VALUE).
- Rebuild grading (resale only): rating wins bigger at 2 and 3 years (.724 vs .690, .699 vs .646) and also in the top
  100 (.651 vs .610 at 2 years). Still loses at 1 year (.779 vs .786).
- Contender grading (24 per point): same shape (1 yr .757 vs .762, 2 yr .722 vs .699, 3 yr .709 vs .679).
- Trained only on outcomes known on the list date (the honest forward version): 2023 +.012, 2024 +.007,
  2025 -.019 vs MFF VALUE (1QB; mean of the 1- and 2-year numbers).
- MFF VALUE plus half the rating's age/health edge, strength picked leave-one-year-out: +.005 a year, 4 of 5 years.
  Too small to call.

**Verdict: no straight swap.** The rating is the better order for holds of 2-3 years and for rebuilding teams, in
both formats and in every year tested. It is not better for a 1-year hold in 1QB, and it lost the most recent year
(2025) in both formats, when older running backs held their value better than usual.

**Side finding that matters more:** on this target the shipped MFF VALUE barely beats the plain KTC price in 1QB
(-.004 at 1 year, +.006 at 2, +.009 at 3) and is below it in superflex at 1 and 2 years, and below it inside the top
100 in both. MFF VALUE's weights were tuned in October on a different market (FFC ADP) and on production only.

Limits: the two small MFF VALUE terms (RB yards-after-catch tilt, QB team-scoring term) were not rebuilt for past
years. The 2023 list is from Oct 1 with a preseason sim. Only 3 list-years have a 2- or 3-year result. The rating was
designed on this same data, so the leave-one-year-out numbers flatter it a little; the forward version is the honest one.

---

## Addendum 2: MFF VALUE re-tuned on points plus resale (Jack 11-24 "Yes, re-tune it")

`backtest_fair_retune_tr.py` (logs `_dyn_cache/ktc_wb/fair_retune_tr_1qb.log`, `_sf.log`), plus `_tmp/retune_checks.py`,
`_tmp/retune_calls.py`, `_tmp/retune_candidates.py`, `_tmp/retune_final.py`, `_tmp/retune_today.py`.
**Nothing live changed.** The result is queued as proposal **P-20261124-1** in `proposals/PENDING.md`.

MFF VALUE today is a mix of three ranks: 0.5 next-year market predictor + 0.3 our Dynasty SIM + 0.5 KTC. The re-tune
tried 720 mixes of those three plus the rating's age/health edge, on the same five past lists and the same target
(KTC value at the end of the hold + 12 x points scored over a starter). Score = average of the whole-board rank
correlation and the same inside the KTC top 100, over 1-3 year holds.

### What the search found

| Order | 1QB whole board / top 100 | SF whole board / top 100 |
|---|---|---|
| MFF VALUE as shipped | .721 / .600 | .719 / .588 |
| KTC price alone | .718 / .625 | .727 / .616 |
| Search winner: KTC price + small age/health edge, no sim | .739 / .629 | .745 / .620 |
| **Proposed: half the sim weight + age/health edge** | **.739 / .619** | **.741 / .611** |

The pure search winner drops our sim completely. Picked leave-one-year-out it beat shipped by +.018 a year in 1QB
and +.025 in superflex (4 of 5 years each), and with the edge trained only on past data it won all three testable
years in both formats.

Why the sim scores badly here: on these lists the sim does not add to the KTC price even for points alone (1QB rank
correlation with points scored over 2 years: price .642, shipped MFF VALUE .611, sim alone .552; superflex .628 /
.581 / .506). The October tune that set the 0.3 sim weight used a thinner market (FFC draft ADP, 2016-23).

### Why the proposal is not the search winner

Grading only the calls (top and bottom 10% of each order's gap vs KTC, players in the KTC top 150), excess total
return vs same-price players:

| 1QB | BUY minus SELL, 1 / 2 / 3 yr | BUY at 2 yr | SELL at 2 yr |
|---|---|---|---|
| MFF VALUE as shipped | +9.7 / +16.7 / +16.0 pts | +12.7% | -4.0% |
| Search winner (no sim) | +1.4 / +17.9 / +15.8 | +0.9% | -17.0% |
| **Proposed** | **+5.0 / +28.1 / +24.3** | **+9.8%** | **-18.2%** |

| Superflex | BUY minus SELL, 1 / 2 / 3 yr | BUY at 2 yr | SELL at 2 yr |
|---|---|---|---|
| MFF VALUE as shipped | +1.3 / +9.0 / -1.2 pts | +5.5% | -3.5% |
| Search winner (no sim) | +3.5 / +22.3 / +25.6 | +3.5% | -18.8% |
| **Proposed** | **+3.9 / +24.1 / +18.8** | **+9.4%** | **-14.7%** |

Reading: in 1QB our sim is what finds the BUYS (underpriced producers), and the age/health edge is what finds the
SELLS. The no-sim winner loses the buys and would make almost no calls at all (3 BUY / 1 SELL today in 1QB). In
superflex the shipped calls have not worked; both alternatives fix that.

### The proposed weights, year by year

0.25 market predictor + 0.15 sim + 0.75 KTC, minus 1.0 x the age/health edge (the two small RB and QB terms unchanged).

| | vs shipped, per year | Years won | Edge trained on past data only |
|---|---|---|---|
| 1QB | +.016 | 5 of 5 | +.013, 3 of 3 |
| Superflex | +.019 | 5 of 5 | +.014, 2 of 3 (2025 -.004) |

Same sign when graded for a rebuilding team (+.023, 5 of 5 in 1QB) and for a contender (+.014, 5 of 5).

### What it would change today

- 1QB: 18 BUY / 15 SELL calls become 21 / 18. 58 of 200 players move 10+ spots.
  - New sells are the aging group: Davante Adams, A.J. Brown, Mike Evans, Stefon Diggs, Alec Pierce, Javonte Williams.
  - New buys are mostly young tight ends and quarterbacks: Stowers, Raridon, Mason Taylor, Barner, Gadsden, Bo Nix, McCarthy.
  - Dropped: buys on Hurts, Gainwell, Concepcion, Bernard, Jacobs, Sampson; sells on Warren, McBride, LaPorta.
- Superflex: 21 / 23 becomes 25 / 26. 63 of 200 move 10+ spots.
- Full lists: `_dyn_cache/ktc_wb/retuned_today_1qb.csv`, `retuned_today_sf.csv`.

### Honest limits

- Five list-years; three have a 2- or 3-year result.
- The proposed weights were picked by eye from 12 candidates after seeing these results. They then beat shipped every
  year, but that is not the same as a blind pick.
- The 1-year payoff of 1QB calls is lower than shipped (+5.0 vs +9.7 pts).
- Each call number rests on 45-60 calls.
- Shipping needs site work that has not been built: the weights in app.js, a weekly-built edge number per player, the
  Python copy the tracker uses, and a job that keeps the KTC history current.

---

## Addendum 3: built on a branch (Jack 11-24 "Approve, build it") - NOT live

- **Branch:** `feat/mff-value-lasting-edge`, commit 02ec519a, in its own worktree
  (`MyFantasyFootball Files\.claude\worktrees\mff-value-lasting-edge`). Not pushed, not merged.
- **Site change (3 files):** app.js reads the new weights and each player's age/health edge from a new small data
  file, `data/mff_lasting_edge.js` (306 players). If that file is missing the site uses the old weights, so removing
  the file is the off switch. index.html gets a version tag for the file.
- **sim_lab:** `build_lasting_edge.py` writes the file. The tracker's Python copy (`mff_value.py`, `mff_tracker.py`)
  reads the same file, and gives exactly the old output until the file exists on main (checked: identical).
- **Checked in a local browser on the branch:** new weights and edge load; 1QB shows 21 buys / 18 sells on both the
  site and the Python copy; superflex 26 / 24 on the site vs 25 / 25 in Python. 43 of 200 players sit one spot
  apart between the two (on the old weights the two already differed for 76 players, by up to 6 spots).
- **Not done, needs your go-ahead:** merge and push (that deploys), the cache-bust bump for app.js at merge, adding
  the weekly rebuild to the Tuesday job, and the sim_lab backup.

### Blocker found while building: KTC changed its page today (2026-11-24)

KTC no longer puts the player list in the rankings page. It now loads from `/dynasty-rankings/player-pool`, and KTC's
robots.txt disallows that path (and `/dynasty-rankings/histories`, which our history job has been reading). Today's
9am run logged "KTC unchanged/skipped", "KTC players list not found" and "vote capture FAILED". KTC values on the
site are frozen at Nov 23. I did not pull the disallowed path. Every KTC-based number on the site (MFF VALUE, trade
calculator source, KTC columns, this rating) goes stale until there is a decision on the source.
