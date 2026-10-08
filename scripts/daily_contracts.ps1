# Player-card CONTRACT fields refresh (Task Scheduler: "MFF Player Contracts", daily 07:30, WakeToRun).
#
#   scripts/build_player_contracts.py   OverTheCap (via nflverse parquet, refreshed daily) ->
#                                        data/d.js  sal / cyr / out / cv / cn / cg / cs / cdead / csav
#
# Cadence (Jack 2026-10-08: "every 4ish weeks, but every day during the common times for
# contract renewals or negotiations"): the task fires daily; the build actually runs when
#   * today is inside a signing WINDOW (month-day ranges, inclusive):
#       02-15 .. 04-15  franchise tags, legal tampering, new league year, free agency, cap cuts
#       04-20 .. 05-15  draft week + post-draft veteran releases / trades
#       07-15 .. 09-12  camp extensions, cut-down day, pre-Week-1 extensions
#       10-25 .. 11-06  trade deadline
#   * or the last successful build is 28+ days old (stamp below).
# A failed run leaves the stamp alone, so it retries the next morning.
#
# Mirrors scripts/route_pct_daily.ps1 guards: refuses to run on a dirty data/d.js or index.html
# (another session's work), commits + pushes ONLY when d.js changed, bumping BOTH data/d.js ?v=
# (preload + script tag; read fresh from disk - other jobs bump ?v= concurrently).
# Stamp: E:\MyFantasyFootball\pbp_cache\player_contracts_last_build.txt
# Log:   scripts/contracts_log.txt (~300 lines)

$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
if (-not (Test-Path $Python)) { $Python = 'python' }
$Log = Join-Path $Repo 'scripts\contracts_log.txt'
$Stamp = 'E:\MyFantasyFootball\pbp_cache\player_contracts_last_build.txt'
$Windows = @(@('02-15', '04-15'), @('04-20', '05-15'), @('07-15', '09-12'), @('10-25', '11-06'))

function Write-Log($msg) {
    Add-Content -Path $Log -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg) -Encoding utf8
}

Set-Location $Repo
Write-Log '=== player contracts start ==='

$force = ($args -contains '-Force')
$md = Get-Date -Format 'MM-dd'
$inWindow = $false
foreach ($w in $Windows) { if ($md -ge $w[0] -and $md -le $w[1]) { $inWindow = $true } }
$ageDays = if (Test-Path $Stamp) { ((Get-Date) - (Get-Item $Stamp).LastWriteTime).TotalDays } else { 999 }
if (-not ($force -or $inWindow -or $ageDays -ge 28)) {
    Write-Log ('not due: outside signing windows, last build {0:N1} days ago (runs at 28)' -f $ageDays)
    Write-Log '=== done ==='
    exit 0
}
Write-Log ('due: ' + $(if ($force) { 'forced' } elseif ($inWindow) { 'signing window' } else { ('last build {0:N1} days ago' -f $ageDays) }))

# Refuse to run on dirty target files so another session's work isn't clobbered.
$dirty = git status --porcelain -- data/d.js index.html
if ($dirty) {
    Write-Log "SKIP: uncommitted changes present:`n$dirty"
    exit 0
}

$out = & $Python 'scripts\build_player_contracts.py' 2>&1 | Out-String
Write-Log ('build: ' + ($out -split "`n" | Select-Object -Last 4 | Out-String).Trim())
if ($LASTEXITCODE -ne 0) {
    Write-Log "CONTRACTS BUILD FAILED (exit $LASTEXITCODE) - d.js left as is, retry tomorrow"
    git checkout -- data/d.js 2>$null
    exit 1
}
Set-Content -Path $Stamp -Value (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') -Encoding utf8

$changed = git status --porcelain -- data/d.js
if (-not $changed) {
    Write-Log 'no contract changes - nothing to commit'
} else {
    $stamp = Get-Date -Format 'yyyy-MM-dd-HHmm'
    $idxPath = Join-Path $Repo 'index.html'
    $html = [System.IO.File]::ReadAllText($idxPath)
    $html = $html -replace 'data/d\.js\?v=[0-9A-Za-z.-]+', ('data/d.js?v=' + $stamp)
    [System.IO.File]::WriteAllText($idxPath, $html)
    git add data/d.js index.html
    git commit -m ('Auto player contracts (OverTheCap) {0} (?v= bump)' -f $stamp)
    git pull --rebase --autostash origin main
    git push origin main
    if ($LASTEXITCODE -eq 0) { Write-Log 'contracts committed + pushed' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}

$lines = Get-Content $Log
if ($lines.Count -gt 300) { $lines | Select-Object -Last 300 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
