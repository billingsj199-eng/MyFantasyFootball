import io, os
os.chdir(r"E:\MyFantasyFootball\sim_lab")
p = "engine.js"; s = io.open(p, encoding="utf-8").read()
old = "    if (ncSrc !== 'clay-fallback') {\n      var sa = shadowAgeAdjust(p, ncPrior / scale);   // curves live in half-PPR units"
assert s.count(old) == 1
s = s.replace(old, "    var ncRawHist = ncPrior;   // raw history blend before the age / regression curves (v2.23 parity)\n" + old)
old = "        var hbo = occ[0] + occ[1] * (ncPrior / scale) + occ[2] * opr.half;"
assert s.count(old) == 1
new = ("        // v2.23 PARITY (2026-09-17, audit after Jack's 'are there any other bugs like that'): the HIST + OPP calibration (backtest_opp_prior.py)\n"
       "        // was FITTED on the raw 3-season weighted PPG (.5 / .3 / .2, no last-8, no age curve), and the weekly harness uses that fitted value\n"
       "        // (SHADOWCAL) directly. Live was feeding it the age-adjusted 50/50 blend of 3-season and LAST 8, so one bad stretch hit a veteran's\n"
       "        // prior about twice as hard as the graded form (Jefferson: 3-season 12.6, last 8 9.0). History-window test the same day: when the\n"
       "        // last 8 sits 3+ below the 3-season level the next season comes in at 14.6 vs 15.2 / 11.2 - best-fit weight on the last 8 is 0.18.\n"
       "        // Kill: window.SIM_NC_OPPHIST = false.\n"
       "        var opHist = (h3 != null && !(typeof window !== 'undefined' && window.SIM_NC_OPPHIST === false)) ? h3 / scale : ncPrior / scale;\n"
       "        var hbo = occ[0] + occ[1] * opHist + occ[2] * opr.half;")
s = s.replace(old, new)
io.open(p, "w", encoding="utf-8", newline="\n").write(s); print("patched")
