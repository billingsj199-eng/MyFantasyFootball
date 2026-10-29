# News-driven Daily Trivia board for TOMORROW (Task Scheduler: "MFF Trivia Daily").
#
#   node scripts\trivia_daily\run.js lock   picks tomorrow's theme (news feed / NFL calendar /
#                                           big games / fantasy trade market), builds the board
#                                           with the site's own trivia generator headlessly, and
#                                           writes trivia_daily/{tomorrow} through the
#                                           lockTriviaDaily Cloud Function.
#
# Git-free: reads the checkout on disk, never commits. Jack reviews the result in the admin
# Archive row ("· SCHEDULED"); locking a different board by hand replaces it and the job
# never overwrites a hand lock. If no theme qualifies nothing is written and the template
# cycle serves tomorrow as before.
# Runs 19:30 ET daily — after the 6pm news scan has committed + deployed.
# Log: E:\MyFantasyFootball\_alerts\trivia_daily_log.txt (~400 lines)

$ErrorActionPreference = 'Continue'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$LogDir = 'E:\MyFantasyFootball\_alerts'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir 'trivia_daily_log.txt'

function Write-Log($msg) {
    Add-Content -Path $LogFile -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg) -Encoding utf8
}

Set-Location $Repo
Write-Log '=== trivia daily start ==='

$out = & node 'scripts\trivia_daily\run.js' lock 2>&1 | Out-String
$code = $LASTEXITCODE
($out -split "`r?`n") | Where-Object { $_.Trim() } | ForEach-Object { Write-Log $_ }
if ($code -ne 0) {
    Write-Log "FAILED (exit $code)"
    $alert = Join-Path $PSScriptRoot 'mff_alert.ps1'
    if (Test-Path $alert) {
        try { . $alert; Send-MffAlert -Key 'trivia-daily-failed' -Message ('Trivia daily job failed (exit ' + $code + ') - see trivia_daily_log.txt') } catch {}
    }
}

$lines = Get-Content $LogFile
if ($lines.Count -gt 400) { $lines | Select-Object -Last 400 | Set-Content -Path $LogFile -Encoding utf8 }
Write-Log '=== done ==='
exit $code
