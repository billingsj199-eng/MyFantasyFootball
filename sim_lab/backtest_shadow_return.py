#!/usr/bin/env python3
"""
SHADOW RETURN TIMING (Jack 2026-10-02: "can we add a return timing that we just created with all the injury
reports / past data" to the Clay-free model). The shadow held anyone currently out at ZERO for every later week
(v2.9: out until the status changes) - right for this week, wrong for a rest-of-season number. Same absence states
as backtest_avail_recency.py (starter, missed k games so far, 2019-25); for each of his next four team games:
    hold    he does not play (the shadow's old rule for every later week)
    back    he plays every one (the live engine before 09-30)
    curve   P(plays) from the shipped availability curve v2 (position + injury on his report), leave-one-season-out
graded on whether he actually played (Brier) and on expected games played over the next four. Log shadow_return.log.
"""
import os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_avail_recency as AR
def main():
    log = open(os.path.join(HERE, "shadow_return.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n")
    S = AR.spells(); br = {"hold": [], "back": [], "curve": []}; gp = {"act": [], "hold": [], "back": [], "curve": []}; byj = {j: {"act": [], "curve": []} for j in range(4)}
    for Y in AR.YEARS:
        cont = AR.fit([r for r in S if r["year"] != Y], use_pos=True, use_grp=True)[0]
        for r in [r for r in S if r["year"] == Y]:
            surv = 1.0; pc = []
            for j in range(4):
                surv *= cont(min(AR.KMAX, r["k"] + j), r["pos"], r["g"]); pc.append(1 - surv)
            for j, a in enumerate(r["nxt"]):
                if a is None: continue
                br["hold"].append((0 - float(a)) ** 2); br["back"].append((1 - float(a)) ** 2); br["curve"].append((pc[j] - float(a)) ** 2)
                byj[j]["act"].append(float(a)); byj[j]["curve"].append(pc[j])
            if all(a is not None for a in r["nxt"]):
                gp["act"].append(sum(float(a) for a in r["nxt"])); gp["hold"].append(0.0); gp["back"].append(4.0); gp["curve"].append(sum(pc))
    P(f"=== return timing for a player who is out now: {len(S)} absence states, 2019-25 ===")
    P("  plays game +1 / +2 / +3 / +4 after today: actual " + " / ".join(f"{100*np.mean(byj[j]['act']):.0f}%" for j in range(4)) + "   curve " + " / ".join(f"{100*np.mean(byj[j]['curve']):.0f}%" for j in range(4)) + "   (hold = 0%, back = 100%)")
    for k, lab in (("hold", "held out every later week (shadow before today)"), ("back", "back the next game (no return timing)"), ("curve", "availability curve v2 (shipped)")):
        P(f"  {lab:48s} Brier {np.mean(br[k]):.3f}   games played over the next four: {np.mean(gp[k]):.2f} vs actual {np.mean(gp['act']):.2f} (miss {np.mean(np.abs(np.array(gp[k]) - np.array(gp['act']))):.2f})")
    P(f"  curve vs hold: Brier {100*(np.mean(br['curve'])/np.mean(br['hold'])-1):+.0f}%")
    log.close()
if __name__ == "__main__": main()
