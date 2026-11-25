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

---

## Addendum 4: rolling tracked values forward, the yearly cycle, and predicting moves (Jack 11-24)

Jack: "can we use the ktc values we tracked" -> "Yes, test it" -> "the goal is to create more accurate ktc values ...
dynasty values move up and down cyclically ... a big leg up for players that are sell highs or buy lows".
**Nothing live changed, nothing on the branch changed.** Scripts: `backtest_ktc_rollforward.py`, `research_ktc_cycles.py`,
`backtest_ktc_forecast.py`, `_tmp/ktc_stale.py`, `_tmp/forecast_today.py`. Logs in `_dyn_cache/ktc_wb/`
(`rollforward.log`, `cycles_1qb.log`, `forecast.log`).

### 1. Frozen values go stale

| Age of frozen values (in season) | Order still matches | Typical move | Moved 10%+ |
|---|---|---|---|
| 7 days | .987 | 1.8% | 2% |
| 30 days | .925 | 5.3% | 24% |
| 60 days | .859 | 8.4% | 43% |
| 90 days | .818 | 10.3% | 51% |

### 2. Rolling them forward with our own data (tracking, not predicting)

Freeze a past list, then update each player from games played, points vs his old rate, games missed and (across a
draft) the draft capital his team spent at his position. Tested forward in time, KTC top 150:

| In season, age of the freeze | Order match: frozen -> rolled | Typical miss: frozen -> rolled | Within 10% of real: frozen -> rolled |
|---|---|---|---|
| 1 month | .962 -> .966 | 3.6% -> 4.6% | 86% -> 83% |
| 2 months | .901 -> .943 | 7.4% -> 6.1% | 64% -> 72% |
| 3 months | .887 -> .940 | 9.2% -> 7.0% | 55% -> 66% |
| 6 months | .849 -> .923 | 12.2% -> 8.7% | 45% -> 57% |

- When the roll said "up 10%+" the real move was +15% (2-3 months); "down 10%+" was -12 to -14%. It had the direction
  right on about 9 of 10 real 15%+ movers.
- **Off season it adds nothing** (3 months: .959 frozen vs .949 rolled). Off-season moves come from news we do not model.
- Across a whole offseason with a draft (price 6-7 months old): order match .653 frozen -> .846 rolled. MFF VALUE (new
  mix) .584 frozen -> .653 rolled vs .741 with fresh prices. It recovers under half of the loss.
- Rookies priced from draft slot + position: order .81 vs real, typical miss 21%. Adding our prospect score: .85, 20%.

### 3. The yearly cycle (average move, year by year; * = same direction every year)

| Window | What repeats |
|---|---|
| Jan -> May (free agency + draft) | Every veteran group drops as the rookie class enters: RBs -11 to -13% *, WRs -8 to -10% *, older TEs -15% *, QBs only -2 to -4%. |
| May -> Aug (camp) | Nothing. All groups within about 2%. |
| Aug -> Nov (first half) | Older WRs -11% *, prime-age QBs -8% *. 2nd- and 3rd-round rookie picks +7 to +11% *. Rookie RBs +5% on average but not every year. |
| Nov -> Jan (second half) | Older RBs -5% *, older WRs -4% *, older TEs -4% *. Rookie WRs +3% *. |

Held-out test (rank groups by their move in the other years, buy the top third, sell the bottom third): spread +3.8
points Jan->May (4 of 4 years), +0.5 May->Aug, +5.3 Aug->Nov (5 of 5), +5.5 Nov->Jan (4 of 4).

### 4. Predicting where a price goes next (the part that could beat KTC)

Uses only what is known on the list date: price, position, age, time of year, recent production and missed games, and
KTC's own recent move. Frozen KTC predicts "no change", so it scores zero on all of these. Forward in time, KTC top 150:

| Horizon | In season: liked most 20% / liked least 20% | Gap | Off season gap |
|---|---|---|---|
| 1 month | +0.5% / -2.3% | 2.8 pts | none |
| 2 months | -0.3% / -3.8% | 3.5 pts | 1.6 pts |
| 3 months | -1.6% / -6.9% | 5.3 pts | 2.8 pts |
| 6 months | -4.7% / -12.4% | 7.7 pts | 6.6 pts |

- Positive in every test year: 3 months +4.8 (2023), +5.0 (2024), +5.1 (2025), +1.7 (2026) points; 6 months +8.5, +7.8,
  +9.4, +3.0.
- **It finds sells far better than buys.** The liked-least group falls hard; the liked-most group roughly holds.
- In season the drivers are KTC's move over the last month (fallers keep falling), production over a starter, age, and
  the last 60 days. Off season almost nothing short-term is predictable.

### 5. Today's board (1QB), forecast applied

Typical top-150 player: -3% in 3 months, -9% in 6 months (the rookie class arriving). Full list:
`_dyn_cache/ktc_wb/forecast_today_1qb.csv`.

- **Sell high (3 / 6 month forecast):** Diggs -18 / -28%, Metcalf -17 / -21%, Darnold -11 / -23%, Ollie Gordon -13 / -19%,
  Evans -11 / -20%, Barkley -11 / -19%, D. Adams -11 / -19%, Jaylen Warren -10 / -15%, A.J. Brown -10 / -14%,
  Jonathan Taylor -9 / -13%, Waddle -10 / -15%, D.J. Moore -7 / -17%.
- **Holds best:** Omar Cooper, Stroud, Maye, Nabers, Tate, Smith-Njigba, McMillan, Pickens, Bowers, Loveland, Fannin.

### Limits

- The forecast needs a current price to start from. In season our roll can supply that for a few months; across an
  offseason it cannot.
- One "today" input (last month's KTC move) came from our own daily history because the archive has no list 30 days back.
- 2026 was the weakest test year at every horizon.
- Values are on the rank scale, so "everyone drops in spring" is the rookie class arriving, not each veteran getting worse.

---

## Addendum 5: value forecast built on the review branch (Jack 11-24 "Yes, build it") - NOT live

- **Branch:** `feat/mff-value-lasting-edge`, second commit 5bbb49df. Not pushed, not merged. Queued as P-20261124-2.
- **On the player card (DYNASTY tab):** a VALUE FORECAST line for every player with a forecast ("-18% in 3 months, -28% in
  6 months (typical top-150 player -3% / -9%)") and a SELL WINDOW or BUY WINDOW tag for the bottom and top fifth of the
  KTC top 150. It sits behind the same gate as the other value tags.
- **Two guards:** the forecast hides itself when its starting price is more than 21 days old, and a window that
  contradicts the BUY LOW / SELL HIGH call is not tagged (one case each way today).
- **Superflex was tested before shipping it:** in season the liked-least fifth lost 7.0% in 3 months and 11.4% in 6, the
  liked-most fifth 2.6% and 4.9%. Weaker than 1QB year by year (3-month gap +0.4, +2.1, +4.4, +1.4 points for 2023-26) and
  nothing at 1 month.
- **Checked in a local browser:** Diggs shows SELL HIGH + SELL WINDOW (-18% / -28%), Nabers BUY WINDOW, Bijan's real card
  shows the forecast line, superflex numbers load, 30 sell and 30 buy windows per format.
- **Not checked:** the logged-in premium view of a player outside the top 30 (tested by calling the card's tag code directly).

---

## Addendum 6: in-house roll wired into the weekly build (Jack 11-24 "Yes, wire it") - NOT live

- **Branch:** third commit c331de9e on `feat/mff-value-lasting-edge`. Not pushed, not merged. Queued as P-20261124-3.
- **What the weekly build (`build_lasting_edge.py`) now does by itself:**
  1. Finds the last day our KTC copy actually changed (today: Nov 23) and saves that day's list as a tracked list.
  2. If the copy is under 3 weeks old, or no games are being played, it changes nothing.
  3. Otherwise it rolls the top 250 forward from games played, points vs each player's old rate, games missed and
     share changes: half of the predicted move at 3-6 weeks, three-quarters after that.
  4. The rolled prices become "today" for the age/health edge and the forecast, and the rolled order is written
     to the data file for the site.
- **Site:** MFF VALUE uses the rolled order for its market input only when that section exists and is at most 10
  days old. KTC columns keep showing the real KTC copy. Not applied with a TE premium.
- **Why those cut-offs (forward-tested, in season, order match with real KTC, frozen -> rolled):**

  | Age of the freeze | Frozen | Best share of the move | Rolled |
  |---|---|---|---|
  | 3.5-6 weeks | .961 | 50% | .972 |
  | 6-10 weeks | .901 | 75% | .941 |
  | 10-14 weeks | .887 | 75% | .939 |
  | over 14 weeks | .849 | 75% | .921 |

  With only 1-2 team games since the freeze, rolling made the typical miss worse (5.7% -> 7.8%), so it waits.
- **Superflex tested too:** 2 months .911 -> .951, 3 months .895 -> .945.
- **Dry run on this season (model never saw 2026):** the Aug 16 list rolled to Nov 24 matched the real order .929
  vs .797 frozen (superflex .935 vs .806); typical miss 8.1% vs 12.9%.
- **End-to-end check:** ran the whole build with a pretend freeze on Sept 13. The file got rolled ranks for 416
  players; on the site, MFF VALUE's market ranks matched the Python copy for 198 of 200 players and the calls were
  23 buys / 22 sells vs 23 / 23; the off switch and the stale guard worked. Then re-ran the real build: copy is 1 day
  old, so nothing is rolled and the forecast's start date is Nov 23.
- **Timeline if KTC stays blocked:** the first rolled build would be on or after Dec 14. When the season ends the roll
  stops and the forecast hides itself 21 days later. The offseason is still unsolved.
- **Not done:** merge and push, the app.js cache-bust bump, adding the build to the Tuesday job, the sim_lab backup.

---

## Addendum 7: LIVE (Jack 11-24 "Go live")

- **Merged and deployed.** The branch was rebased on the latest main (7 commits had landed), re-checked in a local
  browser, the app.js cache-bust was bumped, and it was pushed to main (last commit 7b20354e). The Pages deploy
  succeeded after its built-in retry.
- **Verified on the live site:** new app.js and data file are served (306 players, 209 forecasts, forecast start
  Nov 23, nothing rolled yet). In the signed-in premium view, Stefon Diggs' card (outside the top 30) shows SELL
  WINDOW and "VALUE FORECAST -19% in 3 months, -29% in 6 months".
- **Tuesday job:** `lasting_edge_refresh.ps1` runs after the Dynasty SIM step. It builds for about 5 minutes without
  holding the site lock, then takes the lock only to publish. Dry run passed (266 seconds). First scheduled run: Dec 1.
- **Not done on purpose:** the sim_lab backup. That backup goes to a branch of a public repo, and it would publish the
  archived KTC lists, the rating and forecast files and this report.
- **Side effects to expect:** the daily tracker switches to the new weights once the main checkout pulls the new data
  file, so the "our value" history line on player cards can step that day. BUY / SELL calls changed for premium users
  (1QB 18 / 15 -> 21 / 18).
- **Still open:** a KTC source for the offseason, and everything else that reads the KTC copy (KTC columns, trade
  calculator KTC source) stays frozen at Nov 23.

---

## Addendum 8: redraft rating = the MFF "rankings" order (Jack 11-24) - PROTOTYPE, nothing live

Jack: "now build the redraft rating" / "this would be the mff 'rankings' order" / "because it isnt always as simple
as proj ppg with risk, upside etc".

Scripts: `backtest_redraft_rating.py`, `backtest_redraft_struct.py`, `redraft_rating.py`. Logs and tables in
`_dyn_cache/redraft/`.

### How it was tested

- History: 12,320 player-weeks, 2019-2025, from the sim's historical stand-in (half-PPR).
- At every checkpoint (before weeks 3 to 14), each candidate order was graded on what players were really worth
  the rest of the season: points over replacement in the weeks you would have started him (his projection that
  week was at or above replacement). Missed games count zero. Replacement is the best non-starter in a 12-team
  league (QB13 / RB26 / WR36 / TE13).
- Forward in time: trained on earlier seasons, tested on 2022-2025.

### What ranks players best (same 48 checkpoints, higher is better)

| Order | All | RB | WR | Top-24 value captured |
|---|---|---|---|---|
| Our projection over replacement | .548 | .650 | .545 | 73.3% |
| Our base projection x weeks left | .550 | .652 | .550 | 72.2% |
| Season points per game | .499 | .602 | .493 | 66.6% |
| Preseason ADP (benchmark) | .477 | .535 | .547 | 71.2% |
| ESPN's projection (benchmark) | .546 | .626 | .553 | 70.8% |
| 37-input model: projection + risk + upside | .527 | .629 | .538 | 70.9% |
| Projection + availability model | .550 | .655 | .550 | 72.1% |
| Projection + role-trend model | .466 | .622 | .516 | 69.5% |
| **Projection + option** | **.557** | .652 | .550 | 72.4% |
| **This week exact + option after** | **.558** | .654 | .552 | 72.2% |
| Our base + ESPN, equal ranks (benchmark) | .562 | .653 | .562 | 73.8% |

### What that says about risk and upside

- **Our projection already carries most of it.** It ties ESPN and beats season PPG and ADP at every stage of the season.
- **Risk inputs do not improve the order.** Injury report, practice status, age, snap trend, games missed, dud rate and
  volatility were tested together and as their own availability model. Players listed questionable went on to play 79%
  of the remaining weeks; healthy players 81%. Who misses time later is close to unpredictable from these.
- **Chasing role trends hurts.** A model of where the projection is heading predicts the projection well, but ranking
  on it is much worse (-.08), because production regresses.
- **Upside helps in one form: the option.** A projection can climb or fall, and you ride it when it climbs and bench it
  when it falls. Worth +.007 on the whole board in every season tested (+.013, +.008, +.002, +.004), and it is what
  separates bench stashes: among players projected below replacement the order goes from .034 to .077 and the top-24
  stashes capture 70.7% of the best possible instead of 67.6%. QB and TE order does not change.
- **A big model is worse than the projection.** Same lesson as the dynasty study.
- **The outside consensus adds a little.** Our base and ESPN ranked together beat either alone (+.012, better in 6 of 7
  seasons). That uses outside projections, so it is Jack's call (11-21: "keep it in-house").

### The prototype rating

- **Value** = this week: projection over replacement (zero if below) + each later fantasy week through 17: the
  expected points over replacement given how far projections really move that many weeks ahead (by position).
- **Rating 0-99** = 99 x square root of (value / best value on the board).
- **Shown beside it, not part of the order:** NOW (this week over replacement), FLOOR (share of his games at or above
  replacement), CEILING (share of games 8+ over replacement), UPSIDE (share of his value that is option), games missed.

This week (valuing weeks 12-17, half-PPR): Gibbs 99, Smith-Njigba 91, Bijan 83, McCaffrey 81, Chase 81, St. Brown 78,
Ken Walker 73, Lamb 72, Pollard 69, Bowers 68, Irving 67, Cook 65, Jonah Coleman 65, Burrow 65, Jefferson 64.
Full table: `_dyn_cache/redraft/redraft_rating_now.csv` (407 players, with the consensus rank beside each).

Against the FantasyPros rest-of-season consensus (benchmark): rank agreement .85 in the top 150. Because the rating
is value over replacement, it ranks top quarterbacks and tight ends higher than the consensus (Kittle 46 -> 16,
Daniels 79 -> 33, Kelce 85 -> 50) and deep wide receivers lower (Flowers 25 -> 63, Downs 47 -> 116).

### Limits

- The order is very close to what the SIM VOR board with its UPSIDE setting already shows; the new parts are the
  option for every position and week, the single 0-99 number and the floor / ceiling columns.
- Availability comes only from the sim's own weekly projections. Two cases to check by hand: Puka Nacua (consensus
  244, here 41) and Josh Jacobs (111 vs 25), where the sim expects a return the consensus does not.
- Half-PPR only so far. PPR and standard need the same build on the other export columns.
- The history uses the sim's stand-in, not a replay of the live engine, and has only players who had a projection
  that week.

---

## Addendum 9: redraft rating built on a review branch (Jack 11-24 "Yes, build it") - NOT live

- **Branch:** `feat/mff-redraft-rating`, commit 60dcd364, in its own worktree. Not pushed, not merged. Queued as
  P-20261124-4.
- **What it is on the site:** a new **MFF RATING** setting on the SIM VOR board (season boards, not weekly). Turning
  it on re-orders and re-tiers the board by the rating and shows the 0-99 number in the last column. ROS VOR,
  PLAYOFFS and UPSIDE keep their own numbers and order; nothing existing changes.
- **Why it sits on the SIM VOR board:** the rating is the same weeks, playoff weighting, league settings and scoring
  as ROS VOR, with each later week priced as an option. Building it there means PPR, half and standard, and synced
  leagues, all work without a second copy of that logic.
- **Two more tests before building:**
  - The option's strength barely matters. From half to triple the measured spread, top-24 and top-50 value are the
    same and stash picking stays at 74-78% of the best possible (52% with no option).
  - The site's current UPSIDE formula, run on the same history, picked stashes worse: 60% of the best possible, and
    below plain ROS VOR on the whole board in 3 of 4 seasons. This disagrees with the October test that shipped
    UPSIDE (a different history table), so it is flagged, not changed.
- **Checked in a local browser:**
  - Works in PPR, half and standard; every player gets a rating.
  - The top 24 are the same players as ROS VOR in all three formats; 56 to 89 players that ROS VOR scores 0 now have
    an order.
  - Half-PPR top 10 on the site: Gibbs 99, Bijan 87, Smith-Njigba 86, McCaffrey 85, Walker 78, Chase 77, Pollard 74,
    St. Brown 73, Irving 71, Cook 71. Agreement with the Python prototype .95 in the top 120 (the site adds the 1.5x
    playoff-week weight and its own replacement rule).
  - Pill, header ("RATING"), tiers and board label all switch; no console errors.
- **Not built:** floor and ceiling columns (the card already shows the sim's own boom / bust odds), and the rating is
  not the default order of any board.
- **Not checked:** a synced league's settings with the rating on, and the phone layout.

---

## Addendum 10: MFF RATING live on the board; trade calculator and My Teams built on the branch (Jack 11-24)

### Live (Jack "Go live")

- The MFF RATING setting on the SIM VOR board is on main (f90cb538, app.js cache-bust `2026-11-24-mffrating`). The
  Pages deploy succeeded and the live site serves the new code.
- Phone layout checked before the push: the pill fits beside UPSIDE and RESET, no sideways scroll, the board re-orders.
  On a phone the 0-99 number itself is not visible in the row (stat columns are hidden there); the order and tiers are.

### Built on the branch, NOT live (Jack "also have this in myteams and trade calc etc")

- **Branch:** `feat/mff-redraft-rating`, one commit ahead of main.
- **What it does:** the MFF source tab, which is MFF VALUE on dynasty, now also shows on redraft, labelled
  MFF RATING, in the trade calculator (and FIND TRADE, which shares the source) and in My Teams. Players are priced
  by the rating order through the same path every other source uses. It is opt-in and behind the same lock as
  MFF VALUE. No defaults change. Dynasty is unchanged.
- **Checked in a local browser (with a test premium flag that was removed afterwards):**
  - Redraft: the tab shows as MFF RATING and selects. Superflex: hidden, and the source falls back to Consensus.
    Dynasty: shows as MFF VALUE as before.
  - Example trade values, rating vs consensus: Gibbs 250 / 250, Kittle 134 / 61, Flowers 41 / 109, Jordan Mason 2 / 2.
  - The board builds once and is reused (no slowdown on repeated value lookups).
- **Not checked:** My Teams with a real synced league (the local preview has none), and a full trade run through
  the lineup-after section with this source selected.
- **Superflex left out on purpose.** The SIM VOR table's superflex quarterback replacement is the 25th QB by
  total points, read per game. Today that is a QB with a missed week who scores 17.2 a game, the same as the 13th QB,
  so superflex prices quarterbacks no higher than 1QB does. That affects the SIM VOR superflex board that is already
  live; flagged for a decision, not changed.
- **Testing note:** the site's service worker serves the old app.js until the cache-bust changes, so a local preview
  must bump it to see new code.
