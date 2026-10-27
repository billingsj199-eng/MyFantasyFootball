# Post-game weekly stats publish (Task Scheduler: "MFF Postgame Stats").
#
# Runs scripts/pull_postgame_stats.py after every game window so 2026 game
# logs, L4 PPG and the '26 PPG column land the same night. Only players whose
# game is FINAL (ESPN scoreboard) get rows, so the schedule can be generous:
#   daily 00:45      (TNF / SNF / MNF single game / Saturday slates)
#   Sun 13:05        (London 9:30am games)
#   Sun 16:50        (1pm slate)
#   Sun 20:15        (4:05 / 4:25 slate)
#   Tue 01:45        (MNF doubleheader late game)
# Since 2026-09-13 it is ALSO nested at the top of scripts/daily_betting_pull.ps1,
# so every lines run (Mon-Sat 8:00 daily, Pregame Lines, Sim Proj Export)
# publishes fresh final-game stats too; the guards below make that safe.
# The Tuesday 8:30 full chain (sim_lab/tuesday_stats.ps1) still rebuilds
# sigma / Sim Lab / extension packs; this job is stats -> site only.
#
# Since 2026-09-14 the importer ALSO writes data/fpa_2026.js (+ .json twin for the extensions) (complete-league
# fantasy points allowed per defense/week -> SOS in-season blend + Sim Lab
# opponent layer); it is staged + ?v=-bumped here alongside the stats file.
# Since 2026-10-27 the importer ALSO fills data/snap_counts.js with the weeks nflverse
# has not posted yet (Sleeper snaps + team target / carry totals -> card SNP% / TS% /
# CAR%), and this wrapper then re-runs scripts/pull_route_pct.py --years 2026 so RT%
# gets its snap-share estimate for the new week (real PFF routes replace it in the
# 06:15 "MFF Route Pct Daily" run, which also swaps in the nflverse snaps).
# Commits + pushes ONLY when weekly_stats_active.js / fpa_2026.js / snap_counts.js changed, bumping ?v=
# in index.html in the same commit (sw.js serves versioned URLs cache-first).
# Mirrors scripts/weekly_kdst_refresh.ps1 / tuesday_stats.ps1 guards.
#
# Log: scripts/postgame_stats_log.txt (kept to last ~300 lines).

$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
if (-not (Test-Path $Python)) { $Python = 'python' }
$Log = Join-Path $Repo 'scripts\postgame_stats_log.txt'

function Write-Log($msg) {
    Add-Content -Path $Log -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg) -Encoding utf8
}

Set-Location $Repo
Write-Log '=== postgame stats start ==='
. (Join-Path $PSScriptRoot 'repo_guard.ps1')
if (-not (Enter-RepoTurn -Log { param($m) Write-Log $m } -Job 'postgame stats')) { exit 0 }   # one job at a time (2026-10-20)

# Refuse to run on dirty target files so another session's work isn't clobbered.
$Files = @('data/weekly_stats_active.js', 'data/fpa_2026.js', 'data/fpa_2026.json', 'data/snap_counts.js', 'data/route_pct.js', 'index.html')
$dirty = git status --porcelain -- @Files
if ($dirty) {
    Write-Log "SKIP: uncommitted changes present:`n$dirty"
    exit 0
}

$out = & $Python 'scripts\pull_postgame_stats.py' 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) {
    Write-Log "IMPORT FAILED (exit $LASTEXITCODE) - nothing committed"
    exit 1
}

# RT% estimate for the new snap weeks. Best-effort: on failure route_pct.js is
# put back so a half-built file is never published.
$rtBuilt = $false
if (git status --porcelain -- data/snap_counts.js) {
    $rtOut = & $Python 'scripts\pull_route_pct.py' '--years' '2026' 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        Write-Log "route pct FAILED (exit $LASTEXITCODE) - route_pct.js left as is: $rtOut"
        git checkout -- data/route_pct.js
    } else {
        $rtBuilt = $true
        Write-Log ('route pct: ' + (($rtOut -split "`n" | Where-Object { $_ -match '2026: \d+ players|^wrote' }) -join ' | '))
    }
}

# Accuracy tracker (admin page /accuracy/): archive today's weekly_projections.json
# version + regrade every week against the fresh rows. Best-effort - a failure
# here never blocks the stats publish. Skipped if another session has accuracy/
# edits in flight.
$accBuilt = $false
$accDirty = git status --porcelain -- accuracy/
if ($accDirty) {
    Write-Log "accuracy: SKIP build (uncommitted accuracy/ changes present)"
} elseif (Test-Path 'scripts\build_accuracy.py') {
    $accOut = & $Python 'scripts\build_accuracy.py' 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { Write-Log "accuracy build FAILED (exit $LASTEXITCODE): $accOut" }
    else { $accBuilt = $true; Write-Log ('accuracy: ' + (($accOut -split "`n" | Where-Object { $_ -match '^(week|season_|locks:)' }) -join ' | ')) }
}

$changedPaths = @('data/weekly_stats_active.js', 'data/fpa_2026.js', 'data/fpa_2026.json', 'data/snap_counts.js')
if ($rtBuilt) { $changedPaths += 'data/route_pct.js' }
if ($accBuilt) { $changedPaths += 'accuracy/data' }
$changed = git status --porcelain -- @changedPaths
if (-not $changed) {
    Write-Log 'no new final-game rows - nothing to commit'
} else {
    # Read index.html from disk immediately before bumping - other jobs bump ?v= concurrently.
    $stamp = Get-Date -Format 'yyyy-MM-dd-HHmm'
    $idxPath = Join-Path $Repo 'index.html'
    $html = [System.IO.File]::ReadAllText($idxPath)
    $html = $html -replace 'weekly_stats_active\.js\?v=[0-9A-Za-z.-]+', ('weekly_stats_active.js?v=' + $stamp)
    $html = $html -replace 'fpa_2026\.js\?v=[0-9A-Za-z.-]+', ('fpa_2026.js?v=' + $stamp)
    $html = $html -replace 'snap_counts\.js\?v=[0-9A-Za-z.-]+', ('snap_counts.js?v=' + $stamp)
    $html = $html -replace 'route_pct\.js\?v=[0-9A-Za-z.-]+', ('route_pct.js?v=' + $stamp)
    [System.IO.File]::WriteAllText($idxPath, $html)
    git add data/weekly_stats_active.js data/fpa_2026.js data/fpa_2026.json data/snap_counts.js index.html
    if ($rtBuilt) { git add data/route_pct.js }
    if ($accBuilt) { git add accuracy/data }
    git commit -m ('Auto postgame stats {0} (weekly_stats_active 2026 rows + fpa_2026 + provisional snaps/TS/RT + accuracy regrade + ?v= bump)' -f $stamp)
    . (Join-Path $PSScriptRoot 'repo_guard.ps1')   # 2026-10-14: a conflicted pull --rebase is aborted + alerted, never left stuck
    $global:LASTEXITCODE = $(if (Invoke-SafePullPush -Log { param($m) Write-Log $m } -What 'postgame stats') { 0 } else { 1 })
    if ($LASTEXITCODE -eq 0) { Write-Log 'postgame stats committed + pushed' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}

# Trim log to last 300 lines.
$lines = Get-Content $Log
if ($lines.Count -gt 300) { $lines | Select-Object -Last 300 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
