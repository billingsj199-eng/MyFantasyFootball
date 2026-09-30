import io, json, os, re
os.chdir(r"E:\MyFantasyFootball\sim_lab")
BS = chr(92); NL = BS + "n"
# ---- A. refresh_data.py ----
p = "refresh_data.py"; s = io.open(p, encoding="utf-8").read()
old = '        f.write("window.SIM_SLEEPER_WEEKLY = ")\n        json.dump(sw, f, separators=(",", ":"))\n        f.write(";' + NL + '")\n'
if "SIM_ESPN_WEEKLY" not in s:
    assert s.count(old) == 1, s.count(old)
    new = old + ("        # ESPN current-week projection per player [half, ppr, std] (repo weekly_projections.json key e), for the RANK MIX\n"
                 "        # (engine rmMean = 50% Clay-free shadow + 50% ESPN; backtest_best_rankings.py 2026-09-17: rank rho .388 vs .378 each alone, 6/7 seasons).\n"
                 '        ew = {"week": None, "p": {}}\n'
                 "        try:\n"
                 '            ew["week"] = wp.get("week")\n'
                 '            for nm, rec in (wp.get("players") or {}).items():\n'
                 '                e_ = rec.get("e") if isinstance(rec, dict) else None\n'
                 '                if isinstance(e_, list) and len(e_) == 3 and all(isinstance(v, (int, float)) for v in e_): ew["p"][_cbnorm(nm)] = e_\n'
                 "        except Exception as e:  # noqa: BLE001\n"
                 '            print(f"WARN ESPN weekly unreadable ({e}) - SIM_ESPN_WEEKLY empty")\n'
                 '        f.write("// ESPN current-week projection per player [half-PPR, PPR, standard]' + NL + '")\n'
                 '        f.write("window.SIM_ESPN_WEEKLY = ")\n'
                 '        json.dump(ew, f, separators=(",", ":"))\n'
                 '        f.write(";' + NL + '")\n')
    s = s.replace(old, new); io.open(p, "w", encoding="utf-8", newline="\n").write(s)


def cbn(n):
    n = n.lower().replace(".", "").replace("'", "").replace("-", " "); n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n); return re.sub(r"\s+", " ", n).strip()


wp = json.load(open(r"E:\MyFantasyFootball\MyFantasyFootball Files\data\weekly_projections.json", encoding="utf-8")); ew = {"week": wp.get("week"), "p": {}}
for nm, rec in wp["players"].items():
    e_ = rec.get("e") if isinstance(rec, dict) else None
    if isinstance(e_, list) and len(e_) == 3 and all(isinstance(v, (int, float)) for v in e_): ew["p"][cbn(nm)] = e_
sm = "data/sleeper_meta.js"; t = io.open(sm, encoding="utf-8").read(); i = t.find("// ESPN current-week projection")
if i >= 0: t = t[:i]
t = t.rstrip("\n") + "\n// ESPN current-week projection per player [half-PPR, PPR, standard]\nwindow.SIM_ESPN_WEEKLY = " + json.dumps(ew, separators=(",", ":")) + ";\n"
io.open(sm, "w", encoding="utf-8", newline="\n").write(t); print("ESPN weekly: week", ew["week"], "players", len(ew["p"]))
# ---- B. engine.js ----
p = "engine.js"; s = io.open(p, encoding="utf-8").read()
if "rankMixW" not in s:
    old = "    return { mean: mean, mult: mult, slot: slot, comps: compsWk, gameIdx: gameIdx, jsMean: jsMean, propMean: propMean, propSrc: propSrc, propW: propWUsed, luckAdj: luckAdj, ncMean: ncMean, ncSrc: ncSrc, lcCorr: lcCorr,"
    assert s.count(old) == 1
    new = ("    // RANK MIX (backtest_best_rankings.py, 2026-09-17; Jack: build the rankings mix). A THIRD graded number beside the live mean and the\n"
           "    // shadow: 50% Clay-free shadow + 50% ESPN weekly projection, then the same book anchor the live mean gets. Seven seasons, top 150,\n"
           "    // ranking inside each position each week: rho .3874 vs ESPN .3777, our shadow .3776, Clay blend today .3655; better than ESPN in 6 of 7\n"
           "    // seasons; best pairs ordered (64.86%), top-N hit and points captured; Clay adds nothing once ESPN is in. Never feeds the live mean.\n"
           "    var espnPts = null, rmMean = null, rmFinal = null;\n"
           "    var EWk = typeof window !== 'undefined' ? window.SIM_ESPN_WEEKLY : null;\n"
           "    if (EWk && EWk.p && +EWk.week === +wk && !(typeof window !== 'undefined' && window.SIM_RANKMIX === false)) {\n"
           "      var eRow = EWk.p[p.norm];\n"
           "      if (eRow && eRow.length === 3 && eRow[2] != null && eRow[1] != null) { espnPts = eRow[2] + sc.rec * (eRow[1] - eRow[2]); if (p.pos === 'TE' && sc.bonus_rec_te) espnPts += sc.bonus_rec_te * (eRow[1] - eRow[2]); }\n"
           "    }\n"
           "    if (ncMean != null) {\n"
           "      rmMean = (espnPts != null && espnPts > 0.5 && ncMean > 0) ? NC_SHADOW.rankMixW * ncMean + (1 - NC_SHADOW.rankMixW) * espnPts : ncMean;\n"
           "      rmFinal = (propSrc === 'line' && propMean != null && propWUsed != null) ? Math.max(0, propMean + (1 - propWUsed) * (rmMean - baseM)) : rmMean;   // same market, our base swapped in\n"
           "    }\n") + old.replace("ncMean: ncMean, ncSrc: ncSrc,", "ncMean: ncMean, ncSrc: ncSrc, rmMean: rmMean, rmFinal: rmFinal, espnPts: espnPts,")
    s = s.replace(old, new)
    old = "        ncProj: p._wk.ncMean != null ? p._wk.ncMean : null, ncSrc: p._wk.ncSrc || null,   // Clay-free shadow base"; assert s.count(old) == 1
    s = s.replace(old, old + "\n        rmProj: p._wk.rmMean != null ? p._wk.rmMean : null, rmFinal: p._wk.rmFinal != null ? p._wk.rmFinal : null, espnPts: p._wk.espnPts != null ? p._wk.espnPts : null,   // rank mix (shadow + ESPN), with books, and ESPN alone")
    old = "    qbTotalC: 0.03,"; assert s.count(old) == 1
    s = s.replace(old, "    rankMixW: 0.5,                      // rank mix: weight on the shadow vs the ESPN weekly projection (kill: window.SIM_RANKMIX = false)\n" + old)
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)
# ---- C. app.js lock writer ----
p = "app.js"; s = io.open(p, encoding="utf-8").read()
if "rmMean: r.rmProj" not in s:
    old = "        ncMean: r.ncProj != null ? +r.ncProj.toFixed(2) : null, ncSrc: r.ncSrc || null,   // SHADOW: Clay-free base (own 3-yr PPG prior)"; assert s.count(old) == 1
    s = s.replace(old, old + "\n        rmMean: r.rmProj != null ? +r.rmProj.toFixed(2) : null, rmFinal: r.rmFinal != null ? +r.rmFinal.toFixed(2) : null, espn: r.espnPts != null ? +r.espnPts.toFixed(2) : null,   // RANK MIX: 50% shadow + 50% ESPN; with the book anchor; ESPN alone")
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)
# ---- D. score_week.py ----
p = "score_week.py"; s = io.open(p, encoding="utf-8").read()
if '"mix": p.get("rmMean")' not in s:
    old = '"nc": p.get("ncMean"), "ncSrc": p.get("ncSrc"),'; assert s.count(old) == 1
    s = s.replace(old, old + ' "mix": p.get("rmMean"), "mixb": p.get("rmFinal"), "espnLock": p.get("espn"),')
    old = '("nc", "No-Clay shadow"), ("lc", "Learned shadow"), ("lcc", "Learned centered"), ("clay", "Clay stack"), ("prop", "prop-anchored"),'; assert s.count(old) == 1
    s = s.replace(old, '("nc", "No-Clay shadow"), ("mix", "Rank mix"), ("mixb", "Rank mix+books"), ("lc", "Learned shadow"), ("lcc", "Learned centered"), ("clay", "Clay stack"), ("prop", "prop-anchored"),')
    old = 'for key, lab in (("mean", "SHIPPED"), ("js", "JS Weekly"), ("nc", "No-Clay shadow"), ("lc", "Learned shadow"), ("clay", "Clay stack")):'; assert s.count(old) == 1
    s = s.replace(old, 'for key, lab in (("mean", "SHIPPED"), ("js", "JS Weekly"), ("nc", "No-Clay shadow"), ("mix", "Rank mix"), ("mixb", "Rank mix+books"), ("lc", "Learned shadow"), ("clay", "Clay stack")):')
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("all patched")
