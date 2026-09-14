# Pregame lines pull + Sim Lab deploy — runs ~1 hour before kickoffs so the
# per-game LOCK captures the freshest lines (Task Scheduler: "MFF Pregame Lines"):
#   Thursday 7:00 PM ET  (TNF kicks ~8:15)
#   Sunday  12:00 PM ET  (early slate kicks 1:00; the Sun 8:15 trigger was
#                         dropped 2026-09-13 - the 7:00 Sim Proj Export covers it)
#   Monday   7:00 PM ET  (MNF kicks ~8:15)
# Reuses the daily betting pull, which since 2026-09-13 ends with the Sim Lab
# refresh + deploy itself (update_simlab.bat) - plus postgame stats,
# injuries, practice, depth charts and weather - so the hosted site has the
# fresh lines before locking. Offseason runs are harmless no-ops.
# NOTE (2026-08-28): the nested betting pull already ends with
# export_sleeper_extension_data.py, so every pregame run refreshes the
# draft-helper extensions too — do NOT add a second export step here
# (update_simlab.bat produces nothing the export reads; see its header).

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'E:\MyFantasyFootball\MyFantasyFootball Files\scripts\daily_betting_pull.ps1'
