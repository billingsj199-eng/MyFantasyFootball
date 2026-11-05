# Real redraft trades refresh (Task Scheduler: "MFF Real Trades").
#
#   scripts/pull_trade_trends.py    (2026-11-04) Yahoo Buzz Index + CBS most-traded counts since MNF
#                                    + trades detected in users' synced My Teams leagues (Cloud
#                                    Function exportLeagueTrades) -> data/real_trades_redraft.json
#   scripts/pull_sleeper_trades.py   the old public-Sleeper snowball crawl - NO LONGER RUN (Jack
#                                    2026-11-04); kept so it can be switched back on.
#
# Feeds the Trade Calc RECENT REAL TRADES panel + MOST TRADED SINCE MNF chips (redraft modes).
# The pull is git-free (a handful of requests) and runs BEFORE the repo turn; only the
# commit + push takes the turn. No ?v= bump: app.js fetches the JSON with an hourly ?d= stamp.
# Commits ONLY data/real_trades_redraft.json.
# Log: E:\MyFantasyFootball\sleeper_trades_cache\task_log.txt (~300 lines)

$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
if (-not (Test-Path $Python)) { $Python = 'python' }
$CacheDir = 'E:\MyFantasyFootball\sleeper_trades_cache'
New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
$Log = Join-Path $CacheDir 'task_log.txt'
$Data = 'data/real_trades_redraft.json'

function Write-Log($msg) {
    Add-Content -Path $Log -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg) -Encoding utf8
}

Set-Location $Repo
Write-Log '=== real trades start ==='

$out = & $Python 'scripts\pull_trade_trends.py' 2>&1 | Out-String
Write-Log ('pull: ' + ($out -split "`n" | Select-Object -Last 3 | Out-String).Trim())
if ($LASTEXITCODE -ne 0) {
    Write-Log "PULL FAILED (exit $LASTEXITCODE) - $Data left as is"
    git checkout -- $Data 2>$null
    exit 1
}

. (Join-Path $PSScriptRoot 'repo_guard.ps1')
if (-not (Enter-RepoTurn -Log { param($m) Write-Log $m } -Job 'real trades')) { exit 0 }

$changed = git status --porcelain -- $Data
if (-not $changed) {
    Write-Log 'no change - nothing to commit'
} else {
    $stamp = Get-Date -Format 'yyyy-MM-dd-HHmm'
    git add -f -- $Data
    git commit -m ('Auto trade trends (Yahoo + CBS + synced leagues) {0}' -f $stamp) -- $Data
    $global:LASTEXITCODE = $(if (Invoke-SafePullPush -Log { param($m) Write-Log $m } -What 'real trades') { 0 } else { 1 })
    if ($LASTEXITCODE -eq 0) { Write-Log 'real trades committed + pushed' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}
Exit-RepoTurn

$lines = Get-Content $Log
if ($lines.Count -gt 300) { $lines | Select-Object -Last 300 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
