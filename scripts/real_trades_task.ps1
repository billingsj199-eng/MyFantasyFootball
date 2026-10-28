# Real redraft trades refresh (Task Scheduler: "MFF Real Trades").
#
#   scripts/pull_sleeper_trades.py   public Sleeper redraft leagues (snowball-found, pool cached in
#                                     E:\MyFantasyFootball\sleeper_trades_cache) -> data/real_trades_redraft.json
#
# Feeds the Trade Calc RECENT REAL TRADES panel + MOST TRADED SINCE MNF chips (redraft modes).
# The crawl is git-free and runs BEFORE the repo turn (~15-30 min of Sleeper calls); only the
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

$out = & $Python 'scripts\pull_sleeper_trades.py' 2>&1 | Out-String
Write-Log ('crawl: ' + ($out -split "`n" | Select-Object -Last 3 | Out-String).Trim())
if ($LASTEXITCODE -ne 0) {
    Write-Log "CRAWL FAILED (exit $LASTEXITCODE) - $Data left as is"
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
    git commit -m ('Auto real redraft trades (Sleeper) {0}' -f $stamp) -- $Data
    $global:LASTEXITCODE = $(if (Invoke-SafePullPush -Log { param($m) Write-Log $m } -What 'real trades') { 0 } else { 1 })
    if ($LASTEXITCODE -eq 0) { Write-Log 'real trades committed + pushed' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}
Exit-RepoTurn

$lines = Get-Content $Log
if ($lines.Count -gt 300) { $lines | Select-Object -Last 300 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
