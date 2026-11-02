# Weekly live-board refresh of the Daily Trivia library (Task Scheduler: "MFF Trivia Weekly").
#
#   scripts/trivia_library/refresh_live.js build   rebuild the boards that reach the current season
#                                                   (season / career / franchise / all-time games) - git-free
#   scripts/trivia_library/refresh_live.js merge   swap them into data/trivia_library.js + bump its ?v=
#
# Tuesday after the MNF postgame import (MFF Postgame Stats 00:45) and MFF Weekly Stats Tuesday
# (06:00). The build runs BEFORE the repo turn; merge + commit + push take it. Commits ONLY
# data/trivia_library.js and index.html, and skips the run if either already has someone else's
# uncommitted edits (a session working in this checkout).
# Log: E:\MyFantasyFootball\_alerts\trivia_weekly_log.txt (~300 lines)

$ErrorActionPreference = 'Continue'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Log = 'E:\MyFantasyFootball\_alerts\trivia_weekly_log.txt'
$Files = @('data/trivia_library.js', 'index.html')

function Write-Log($msg) {
    Add-Content -Path $Log -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg) -Encoding utf8
}

Set-Location $Repo
Write-Log '=== trivia weekly start ==='

$out = & node 'scripts\trivia_library\refresh_live.js' build 2>&1 | Out-String
Write-Log ('build: ' + ($out -split "`n" | Select-Object -Last 3 | Out-String).Trim())
if ($LASTEXITCODE -ne 0) { Write-Log "BUILD FAILED (exit $LASTEXITCODE) - library left as is"; exit 1 }

. (Join-Path $PSScriptRoot 'repo_guard.ps1')
if (-not (Enter-RepoTurn -Log { param($m) Write-Log $m } -Job 'trivia weekly')) { exit 0 }

$dirty = git status --porcelain -- $Files
if ($dirty) {
    Write-Log ('SKIPPED - uncommitted edits already in: ' + (($dirty -split "`n") -join ', '))
    Exit-RepoTurn
    exit 0
}

$out = & node 'scripts\trivia_library\refresh_live.js' merge 2>&1 | Out-String
Write-Log ('merge: ' + $out.Trim())
if ($LASTEXITCODE -ne 0) {
    Write-Log "MERGE FAILED (exit $LASTEXITCODE)"
    git checkout -- $Files 2>$null
} elseif (-not (git status --porcelain -- $Files)) {
    Write-Log 'no change - nothing to commit'
} else {
    $stamp = Get-Date -Format 'yyyy-MM-dd-HHmm'
    git add -- $Files
    git commit -m ('Auto trivia live boards refresh {0} (season/career/franchise boards + ?v= bump)' -f $stamp) -- $Files
    $global:LASTEXITCODE = $(if (Invoke-SafePullPush -Log { param($m) Write-Log $m } -What 'trivia weekly') { 0 } else { 1 })
    if ($LASTEXITCODE -eq 0) { Write-Log 'trivia weekly committed + pushed' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}
Exit-RepoTurn

$lines = Get-Content $Log
if ($lines.Count -gt 300) { $lines | Select-Object -Last 300 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
