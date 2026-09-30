import io, os, re, json
os.chdir(r"E:\MyFantasyFootball\sim_lab")
# 1. source fix: player-name aliases in the nightly feed builder (pbp name -> pool name)
p = "pull_pace_tracker.py"; s = io.open(p, encoding="utf-8").read()
i = s.index("def norm_name(n):"); j = s.index("\n", s.index("return", i)) + 1; body = s[i:j]
print("norm_name currently:\n" + body)
if "PLAYER_ALIAS" not in s:
    new = ("# pbp / PFF name -> the pool's name (audit_shadow.js 2026-09-17: 'kenny gainwell' orphaned Kenneth Gainwell's xFP + RB TD-luck rows)\n"
           "PLAYER_ALIAS = {\"kenny gainwell\": \"kenneth gainwell\"}\n" + body.replace("def norm_name(n):", "def _norm_name_raw(n):") +
           "def norm_name(n):\n    k = _norm_name_raw(n)\n    return PLAYER_ALIAS.get(k, k)\n")
    s = s[:i] + new + s[j:]; io.open(p, "w", encoding="utf-8", newline="\n").write(s); print("pull_pace_tracker.py: alias added")
# 2. patch today's data file in place so it is live before the next nightly run
f = "data/sim_routes.js"; t = io.open(f, encoding="utf-8").read(); n = t.count('"kenny gainwell"')
t = t.replace('"kenny gainwell"', '"kenneth gainwell"'); io.open(f, "w", encoding="utf-8", newline="\n").write(t); print("sim_routes.js keys renamed:", n)
