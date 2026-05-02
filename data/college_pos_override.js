/* _COLLEGE_POS_OVERRIDE — extracted from index.html for performance */
      var _COLLEGE_POS_OVERRIDE = {
        'Tim Tebow': 'QB'  // Played QB at Florida, briefly attempted TE conversion in NFL
      ,'Cam Edwards':'RB'
      // Backtest TEs that are missing 'pos' in COMBINE_DATA and not in D array.
      // Without this override they fall through to the receiving-stats heuristic
      // which defaults to 'WR', causing them to be processed with WR scoring rules
      // (incl. WR tmBonus multiplier). Confirmed via ALL_PLAYERS_DB lookup.
      ,'Brayden Willis':'TE','Cade Stover':'TE','Cameron Latu':'TE','Charlie Woerner':'TE'
      ,'Davis Allen':'TE','Devin Culp':'TE','Grant Calcaterra':'TE','Hunter Long':'TE'
      ,'Jaheim Bell':'TE','Jared Wiley':'TE','Jeremy Ruckert':'TE','Josh Whyle':'TE'
      ,'Luke Farrell':'TE','Payne Durham':'TE','Stephen Sullivan':'TE','Tanner McLachlan':'TE'
      ,'Tip Reiman':'TE','Will Mallory':'TE'};
