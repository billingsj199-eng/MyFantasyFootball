import io
p = "backtest_decayed_history.py"; s = io.open(p, encoding="utf-8").read()
old = "    def hand_with(h, fwd):\n"; assert s.count(old) == 1
s = s.replace(old, "    def hand_with(h, fwd, wvet=None):\n        wv = np.where(A[\"exp\"] == 1, 0.5, 0.75 if wvet is None else wvet)\n")
old = "    RLO = {\"cur\": SL.loyo(T, LIVE, \"ridge\", 10.0), **{h: SL.loyo(T, ridge_feats(h), \"ridge\", 10.0) for h in HLS}}\n"; assert s.count(old) == 1
s = s.replace(old, old + "    RLO[\"add\"] = SL.loyo(T, LIVE + [\"dk12\"], \"ridge\", 10.0)\n")
old = "    RFW = {\"cur\": SL.forward(T, LIVE, \"ridge\", 10.0), **{h: SL.forward(Tf, ridge_feats(h), \"ridge\", 10.0) for h in HLS}}\n"; assert s.count(old) == 1
s = s.replace(old, old + "    RFW[\"add\"] = SL.forward(T, LIVE + [\"dk12\"], \"ridge\", 10.0)\n")
old = "        return V\n"; assert s.count(old) == 1
s = s.replace(old, "        V[\"hl 12: ridge ADDS dk (keeps hist/h3/l8)\"] = shadow(hand0, R[\"add\"])\n        for wvv in (0.65, 0.55, 0.45): V[f\"hl 12 hand, market weight {wvv}\"] = shadow(hand_with(12, fwd, wvv), R[\"cur\"])\n        for wvv in (0.65, 0.55): V[f\"TODAY's history, market weight {wvv}\"] = shadow(np.where(tun, fb_pos + 0.8 * (mult * np.where(F[\"mkt_ok\"], (1 - np.where(A[\"exp\"] == 1, 0.5, wvv)) * hist0 + np.where(A[\"exp\"] == 1, 0.5, wvv) * curve, hist0) - fb_pos), hand0), R[\"cur\"])\n" + old)
s = s.replace("{nm:26s}", "{nm:42s}")
io.open(p, "w", encoding="utf-8", newline="\n").write(s); print("ok")
