import io
p = "backtest_fantasy_playoffs.py"; s = io.open(p, encoding="utf-8").read()
old = "    V4[\"hot only, weight 0.5 (contrast)\"]"; assert s.count(old) == 1
new = '''    qt = (pos == "QB") | (pos == "TE")
    for a_ in (0.25, 0.5): V4[f"cold only, QB + TE only, weight {a_}"] = shadow(ppg + a_ * np.where(qt, cold, 0.0))
    V4["cold only, RB + WR only, weight 0.25"] = shadow(ppg + 0.25 * np.where(~qt, cold, 0.0))
'''
s = s.replace(old, new + old); io.open(p, "w", encoding="utf-8", newline="\n").write(s); print("ok")
