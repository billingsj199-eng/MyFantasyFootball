# Daily betting-lines scan (Task Scheduler: "MFF Betting Lines Daily").
#
# Runs the keyless requests-only phases of pull_betting_lines.py every
# morning (Mon-Sat 8:00 since 2026-09-13; Sunday's first pull is the 7:00
# Sim Proj Export run, which nests this script) — ESPN game lines (spreads/totals), Underdog + FanDuel + BetMGM
# season props (FD/MGM automated 2026-09-08), and the UD + PrizePicks + DK +
# FD + MGM weekly prop boards — then commits + pushes ONLY when the
# data actually changed, so quiet offseason mornings are silent no-ops.
# The DK season-props phase (Selenium) runs daily too since 2026-09-08 so
# DK's season lines carry honest last-seen dates (stale ones grey out on
# the card); it is wrapped in try/except inside main() and can't abort.
# Since 2026-09-13 (Jack: "run injury with everything else") every run also
# pulls the Sleeper injury report (pull_injuries.py -> data/injury_updates.js,
# the site's card tags) and bumps its ?v= when it changed, so the daily /
# pregame / sim-export runs all refresh injuries together with the lines.
# Same for the official NFL practice report (pull_practice_reports.py ->
# data/practice_2026.js, a Sim Lab engine input; no index.html tag, so no
# ?v= bump) since 2026-09-13 as well, plus ESPN depth charts
# (pull_depth_charts.py -> data/depth_charts_2026.js, engine input, no tag)
# and game weather (pull_weather.py -> data/weather_2026.js, Start/Sit
# WEATHER box + card WEEKLY tab, ?v= bumped when changed).
# And post-game stats (scripts/postgame_stats.ps1, nested FIRST - it has its
# own guard/commit/rebase/push, so it runs before this script dirties the
# tree; FINAL games only, so overlapping a live window is safe).
# Finally (2026-09-13) the Sim Lab refresh: sim_lab/update_simlab.bat
# (refresh_data.py mirror + pace tracker + firebase deploy hosting:simlab,
# ~50 s) runs LAST so it mirrors the lines/injuries just committed. It
# used to be the second step of sim_lab/pregame_pull.ps1; that wrapper is
# now just this script. Log: E:\MyFantasyFootball\sim_lab\last_refresh.log.
# Then re-exports the draft-helper players.json (sleeper/espn/yahoo
# extensions) — the export derives team byes from betting_lines_2026.json,
# and the 9am ADP task runs the same step (wired 2026-08-28).
#
# Log: scripts/betting_pull_log.txt (kept to last ~400 lines).

$ErrorActionPreference = 'Continue'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$Log = Join-Path $Repo 'scripts\betting_pull_log.txt'

function Write-Log($msg) {
    $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
    Add-Content -Path $Log -Value $line -Encoding utf8
}

Set-Location $Repo
Write-Log '=== daily betting pull start ==='

# Refuse to run on a dirty data file so a half-finished manual session isn't clobbered.
$Files = @('data/betting_lines_2026.js', 'data/betting_lines_2026.json', 'data/lines_history_2026.json', 'data/injury_updates.js', 'data/practice_2026.js', 'data/depth_charts_2026.js', 'data/weather_2026.js', 'index.html')
$dirty = git status --porcelain -- @Files
if ($dirty) {
    Write-Log "SKIP: uncommitted changes present:`n$dirty"
    exit 0
}

# Post-game weekly stats first (2026-09-13, Jack: every lines run). The
# nested wrapper commits + pushes weekly_stats_active.js itself when new
# FINAL-game rows landed; quiet no-op otherwise. Log: postgame_stats_log.txt.
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Repo 'scripts\postgame_stats.ps1') 2>&1 | Out-Null
Write-Log ('postgame stats: exit ' + $LASTEXITCODE + ' (details in postgame_stats_log.txt)')

$out = & $Python 'scripts\pull_betting_lines.py' '--game-lines' '--season-props' '--underdog' '--fanduel' '--betmgm' '--weekly-props' 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) {
    Write-Log "PULL FAILED (exit $LASTEXITCODE) - nothing committed"
    exit 1
}

# Season-receptions watch: the puller prints this banner the first run any
# book posts a season receptions prop (PPR/Half/STD split from then on).
$recPosted = $out -match '\*\*\* SEASON RECEPTIONS PROP POSTED'
if ($recPosted) { Write-Log 'ALERT: season receptions prop posted - commit flagged for Jack' }

# Injury report (Sleeper statuses -> data/injury_updates.js). Bump its ?v=
# (hour-stamped) when it changed - read the CURRENT html from disk, never
# assume (two-?v=-writers rule).
$out = & $Python 'scripts\pull_injuries.py' 2>&1 | Out-String
Write-Log ('injury pull: ' + $out.Trim().Split("`n")[-1])
$injChanged = git status --porcelain -- data/injury_updates.js
if ($injChanged) {
    $idx = Join-Path $Repo 'index.html'
    $html = [System.IO.File]::ReadAllText($idx)
    $html2 = $html -replace 'injury_updates\.js\?v=[\w.-]+', ('injury_updates.js?v=' + (Get-Date -Format 'yyyy-MM-dd-HH'))
    if ($html2 -ne $html) { [System.IO.File]::WriteAllText($idx, $html2) }
}

# Official NFL practice report (participation + game status). Non-fatal:
# the puller exits non-zero when the page layout changes and writes nothing.
$out = & $Python 'scripts\pull_practice_reports.py' 2>&1 | Out-String
Write-Log ('practice pull: ' + $out.Trim().Split("`n")[-1])
$pracChanged = git status --porcelain -- data/practice_2026.js

# ESPN depth charts (engine input for the vacated-share layer). Non-fatal.
$out = & $Python 'scripts\pull_depth_charts.py' 2>&1 | Out-String
Write-Log ('depth pull: ' + $out.Trim().Split("`n")[-1])
$depthChanged = git status --porcelain -- data/depth_charts_2026.js

# Game weather (ESPN roof/headline + Open-Meteo kickoff-hour forecast).
# Bump its ?v= when changed - same read-from-disk rule as injuries.
$out = & $Python 'scripts\pull_weather.py' 2>&1 | Out-String
Write-Log ('weather pull: ' + $out.Trim().Split("`n")[-1])
$wxChanged = git status --porcelain -- data/weather_2026.js
if ($wxChanged) {
    $idx = Join-Path $Repo 'index.html'
    $html = [System.IO.File]::ReadAllText($idx)
    $html2 = $html -replace 'weather_2026\.js\?v=[\w.-]+', ('weather_2026.js?v=' + (Get-Date -Format 'yyyy-MM-dd-HH'))
    if ($html2 -ne $html) { [System.IO.File]::WriteAllText($idx, $html2) }
}

$changed = git status --porcelain -- @Files
if (-not $changed) {
    Write-Log 'no line movement, no injury/practice/depth/weather change - nothing to commit'
} else {
    git add @Files
    $msg = ('Auto betting-lines scan {0} (game lines + UD season + weekly props)' -f (Get-Date -Format 'yyyy-MM-dd'))
    if ($injChanged) { $msg += ' + injuries' }
    if ($pracChanged) { $msg += ' + practice' }
    if ($depthChanged) { $msg += ' + depth' }
    if ($wxChanged) { $msg += ' + weather' }
    if ($recPosted) { $msg = 'SEASON RECEPTIONS POSTED - ' + $msg }
    git commit -m $msg
    git push origin main
    if ($LASTEXITCODE -eq 0) { Write-Log 'pushed updated lines' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}

# Draft-helper extension data (players.json x3 + sim packs) from the fresh
# betting lines + d.js + Jack's live Firestore boards. Extension dirs are
# git-excluded from main, so this never touches the commit above.
# Non-fatal: a failure just leaves the previous export on disk.
$out = & $Python 'export_sleeper_extension_data.py' 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) { Write-Log "extension export FAILED (exit $LASTEXITCODE) - helpers keep previous data" }

# Sim Lab refresh + deploy (non-fatal; the bat logs REFRESH/DEPLOY FAILED
# itself). Runs after the commit above so the mirror carries this run's data.
& 'E:\MyFantasyFootball\sim_lab\update_simlab.bat' 2>&1 | Out-Null
Write-Log ('sim lab refresh: exit ' + $LASTEXITCODE + ' (details in sim_lab\last_refresh.log)')

# Trim log to last 400 lines.
$lines = Get-Content $Log
if ($lines.Count -gt 400) { $lines | Select-Object -Last 400 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
