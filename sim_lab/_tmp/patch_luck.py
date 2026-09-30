import io, os
os.chdir(r"E:\MyFantasyFootball\sim_lab")
p = "engine.js"; s = io.open(p, encoding="utf-8").read()
old = "    var ncBaseW = jsBasePg(p, sc, ncPrior, ncP, ncUse), ncVk = NC_SHADOW.vacatedK[p.pos];"
assert s.count(old) == 1
new = old + """
    // v2.22 TD-LUCK SCALE FOR THE SHADOW (2026-09-17, found tracing Justin Jefferson W2: prior 13.4 -> shadow 11.2 with no injury flag).
    // tdLuckAdj() is sized for the LIVE blend, whose evidence is points at weight g / (5 + g). The shadow's weight on POINTS is
    // (1 - lam) x g / (P + g): with the usage evidence (v2.18, lam = 1 for RB / WR after one game) and the WR one-game prior (v2.21, P = 40)
    // it is ~0, so the shadow was subtracting touchdown luck it never added. Scale the adjustment by the shadow's own weight on points.
    // The backtests of v2.18 / v2.21 never contained a luck term, so this restores parity with the graded form. Kill: window.SIM_NC_LUCKFIX = false.
    var ncLuckScale = 1;
    if (!(typeof window !== 'undefined' && window.SIM_NC_LUCKFIX === false)) {
      var lkRec = jsData().players ? jsData().players[p.norm] : null, lkG = lkRec && lkRec.g ? lkRec.g : 0;
      if (lkG > 0) {
        var lkLam = (ncUse && ncUse.lam > 0 && ncUse.xfpPg != null) ? ncUse.lam : 0, lkP = ncP != null ? ncP : JS_PRIOR_STRENGTH;
        var lkLive = lkG / (JS_PRIOR_STRENGTH + lkG), lkShadow = (1 - lkLam) * lkG / (lkP + lkG);
        ncLuckScale = lkLive > 0 ? Math.max(0, Math.min(1.5, lkShadow / lkLive)) : 1;
      }
    }"""
s = s.replace(old, new)
old = "      var ncFull = Math.max(0, ncBaseW * ncChainNoIA + tdLuckAdj(p, sc)), ncCap"
assert s.count(old) == 1; s = s.replace(old, "      var ncFull = Math.max(0, ncBaseW * ncChainNoIA + tdLuckAdj(p, sc) * ncLuckScale), ncCap")
old = "      ncMean = Math.max(0, ncBaseW * ncChain + luckAdj);"
assert s.count(old) == 1; s = s.replace(old, "      ncMean = Math.max(0, ncBaseW * ncChain + luckAdj * ncLuckScale);")
io.open(p, "w", encoding="utf-8", newline="\n").write(s); print("luck scale patched")
