# Daily snap share + route participation publish (Task Scheduler: "MFF Route Pct Daily").
#
# Feeds the SNP% and RT% columns on the player-card game log for the current season:
#   1. scripts/pull_snap_counts.py   nflverse snap counts (in-season, updates nightly)
#                                     -> data/snap_counts.js
#   2. scripts/pull_pff_weekly.py    PFF Premium weekly receiving table (routes) via a
#                                     dedicated logged-in Chrome profile
#                                     -> pbp_cache/pff/weekly/pff_receiving_<yr>_w<N>.csv
#                                     Not logged in => exit 2, logged, NOT fatal: the RT%
#                                     column keeps its ~snap-share estimate until Jack
#                                     logs in to premium.pff.com in that Chrome window
#                                     (run `python scripts/pull_pff_weekly.py --login-wait 600`
#                                     by hand once; the profile keeps the session).
#   3. scripts/pull_route_pct.py     real weeks from the PFF files, estimate for the rest
#                                     -> data/route_pct.js
#   4. scripts/build_player_roles.py depth-chart archetypes for the card ROLE row (ESPN depth
#                                     chart + nflverse pbp usage + PFF alignment)
#                                     -> data/player_roles_2026.js
# Schedule: daily 06:15 (WakeToRun). PFF has Sunday's routes by Monday morning, MNF by
# Tuesday, TNF by Friday. Commits + pushes ONLY when either data file changed, bumping
# both ?v= in index.html (read fresh from disk - other jobs bump ?v= concurrently).
# Mirrors scripts/postgame_stats.ps1 guards. Log: scripts/route_pct_log.txt (~300 lines).

$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
if (-not (Test-Path $Python)) { $Python = 'python' }
$Log = Join-Path $Repo 'scripts\route_pct_log.txt'

function Write-Log($msg) {
    Add-Content -Path $Log -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg) -Encoding utf8
}

Set-Location $Repo
Write-Log '=== route pct start ==='

# Refuse to run on dirty target files so another session's work isn't clobbered.
$Files = @('data/snap_counts.js', 'data/route_pct.js', 'data/player_roles_2026.js', 'index.html')
$dirty = git status --porcelain -- @Files
if ($dirty) {
    Write-Log "SKIP: uncommitted changes present:`n$dirty"
    exit 0
}

$out = & $Python 'scripts\pull_snap_counts.py' 2>&1 | Out-String
Write-Log ('snap counts: ' + ($out -split "`n" | Select-Object -Last 3 | Out-String).Trim())
if ($LASTEXITCODE -ne 0) { Write-Log "SNAP PULL FAILED (exit $LASTEXITCODE) - continuing with the file on disk" }

$out = & $Python 'scripts\pull_pff_weekly.py' '--login-wait' '90' 2>&1 | Out-String
Write-Log ('pff weekly: ' + $out.Trim())
if ($LASTEXITCODE -eq 2) { Write-Log 'PFF LOGIN NEEDED - RT% stays estimated until Jack logs in to premium.pff.com in the PFF Chrome profile' }
elseif ($LASTEXITCODE -ne 0) { Write-Log "PFF PULL FAILED (exit $LASTEXITCODE) - using the weekly files already on disk" }

$out = & $Python 'scripts\pull_route_pct.py' '--years' '2026' 2>&1 | Out-String
Write-Log ('route pct: ' + $out.Trim())
if ($LASTEXITCODE -ne 0) {
    Write-Log "ROUTE BUILD FAILED (exit $LASTEXITCODE) - nothing committed"
    exit 1
}

$out = & $Python 'scripts\build_player_roles.py' 2>&1 | Out-String
Write-Log ('player roles: ' + ($out -split "`n" | Select-Object -Last 2 | Out-String).Trim())
if ($LASTEXITCODE -ne 0) { Write-Log "ROLE BUILD FAILED (exit $LASTEXITCODE) - roles file left as is" }

$changed = git status --porcelain -- data/snap_counts.js data/route_pct.js data/player_roles_2026.js
if (-not $changed) {
    Write-Log 'no snap / route changes - nothing to commit'
} else {
    $stamp = Get-Date -Format 'yyyy-MM-dd-HHmm'
    $idxPath = Join-Path $Repo 'index.html'
    $html = [System.IO.File]::ReadAllText($idxPath)
    $html = $html -replace 'snap_counts\.js\?v=[0-9A-Za-z.-]+', ('snap_counts.js?v=' + $stamp)
    $html = $html -replace 'route_pct\.js\?v=[0-9A-Za-z.-]+', ('route_pct.js?v=' + $stamp)
    $html = $html -replace 'player_roles_2026\.js\?v=[0-9A-Za-z.-]+', ('player_roles_2026.js?v=' + $stamp)
    [System.IO.File]::WriteAllText($idxPath, $html)
    git add data/snap_counts.js data/route_pct.js data/player_roles_2026.js index.html
    git commit -m ('Auto snap share + route participation + player roles {0} (snap_counts + route_pct + player_roles + ?v= bump)' -f $stamp)
    git pull --rebase --autostash origin main
    git push origin main
    if ($LASTEXITCODE -eq 0) { Write-Log 'snap/route data committed + pushed' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}

$lines = Get-Content $Log
if ($lines.Count -gt 300) { $lines | Select-Object -Last 300 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
