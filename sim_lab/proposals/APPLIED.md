

## P-20261013-2 - Fade the vacancy boost in LATER weeks by games already played without the absent regular
- What: shadow vacancy gain for weeks after the current one x f, f = max(0, 1 - seen / 4), seen = games this player already played
  on this team while the absent regular (largest absent share) sat. Current week unchanged.
- File / knob: engine.js shadow vacx gain (and live pool iA > 1 part) for wk > _inj.week; new NC_SHADOW.next.vacSeenFade 4.
- Evidence (research_volume_budget_c.py, volume_budget_c.log part C2; ROS harness, 4+ games left): -0.63% (6/7, fwd 3/4);
  LOYO across fades -0.56% (6/7), forward -0.34% (3/4), MAE -0.40%, rank .6287 -> .6317. Pool rows by seen games, ROS act/proj:
  seen 0 1.014, 1 1.004, 2 0.981, 3-4 0.958, 5+ 0.961 (RB 0.896). NEXT GAME the fade FAILS (LOYO keeps the boost 5/7) -
  do not apply to the current week.
- Caveat: harness ROS carries the next-week boost flat; the engine already decays absences with the availability curve, so the
  live effect is smaller - re-grade on the engine form. Confidence: medium. Expiry: 2026-11-10.
- APPLIED 2026-10-13 (Jack approved). ENGINE-FORM RE-GRADE (research_vacfade_ctx_regrade.py, vacfade_ctx_regrade_p2*.log): per-future-week
  availability, 4,665 rest-of-season checkpoints. All positions c 4: -0.48% (6/7, fwd 4/4) but TE alone FAILS (+0.39%, 3/7, fwd 1/4) ->
  shipped RB / WR only: -0.52% (6/7, fwd 4/4), affected checkpoints -1.54% (6/7, 4/4), LOYO -0.52% (5/7) fwd -0.47% (3/4).
  Folds (RB/WR, c 4): 2019 +0.07 | 2020 -0.27 | 2021 -1.35 | 2022 -1.97 | 2023 -0.34 | 2024 -0.01 | 2025 -0.26 (%).
  LOSING SEASON 2019 (+0.07%): James Washington PIT wk10-12 (JuJu out; 2nd-year WR kept growing into the role, seen 5),
  Miles Sanders PHI wk12 (rookie, took Jordan Howard's job for good), Anthony Miller CHI wk12 (2nd-year, Gabriel out), McCaffrey wk9
  (tiny). Pattern = young players who WIN the job during the absence (consistent with project_injury_volume_persist: organic /
  young job winners keep it) - possible exemption for rookies / 2nd-year absorbers; n small, mostly noise at +0.07%.
  Wired: engine.js VAC_FADE {c 4, RB/WR} + vacFadeF(); faded per absent teammate (seen = his 2026 games before the current week
  without that teammate; only teammates with 1+ game); current week untouched; tag +vfadeN; why.vfade / vfadeSeen; app.js ntWhy
  step 'vfade' split out of the blend step (sum unchanged) + NOTES chip. Kill window.SIM_NC_VACFADE = false.
  Backups engine.js / app.js .bak_pre_vacfade_20261013. W6 headless: 237 later-week player-weeks / 63 players move, current week
  0 (parity with the pre-change engine on all 423 W6 rows); Kamara W7 10.25 -> 9.05, Ollie Gordon -1.0/wk, E. Wilson W7 -0.9,
  Miller W7 6.38 -> 5.82, Donaldson 2.21 -> 1.99.

## P-20261014-1 - TreVeyon Henderson (NE RB) out-window W6-W7, soft return by W9 (NEWS)
- What: add an IN_SEASON_OUT_OVERRIDES entry so the sim stops treating his stale W5 "Ankle, Out" tag as a one-week x0.75 and
  returns him at full strength W7.
- File / knob: sim_lab/overrides.js IN_SEASON_OUT_OVERRIDES -> `'TreVeyon Henderson': [6, 7, '2026-10-12', 9],` (high ankle,
  Schefter "multiple weeks", no surgery). Group redistribution (RB 60%) goes to Stevenson / Kiner automatically.
- Size (current export 2026-10-13 14:05Z): W6 5.9 -> 0, W7 8.4 -> 0, W8 9.3 -> ~4.7 (50% landing), W9 9.2 -> ~8.3 (90%).
  Teammates W7 rise (Stevenson 11.4 today assumes Henderson back).
- Evidence: news 2026-10-12 Schefter via camp_news ("high ankle sprain ... will cost him 'multiple weeks'; no surgery needed");
  the feed did NOT tag it (avail = none), so build_injury_signals has no window. Sim row: inj src out-unconfirmed m .75 for W6
  only (Sleeper W6 proj h 6.0 still present, so the out-flag guard correctly refused to zero). W5 usage confirms in-game injury:
  4 carries / 1 target vs 8-16 carries W2-4. Hit rate: timeline windows played 8% (news_status.log, 5/62) -> zero inside the
  window is the right size; "multiple weeks" = at least 2 games, high-ankle no-surgery typically 2-4 -> latest expected W9.
- Confidence: high (insider timeline + usage). Expiry: 2026-10-18 (W6 kickoff Sunday) - if not applied by then, re-size as [7,7,...].
- APPLIED 2026-10-14 (Jack "approve P-20261014-1"): overrides.js entry added (backup overrides.js.bak_pre_henderson_20261014). Dry-run export: W6 5.9->0, W7 8.4->0, W8 9.3->4.1, W9 9.2->8.1; Stevenson W7 11.4->13.4. NOT YET LIVE: shared checkout stuck mid-rebase since 10-13 15:50, all automation pushes failing.
