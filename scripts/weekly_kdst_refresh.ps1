# Weekly K/DST data refresh (Task Scheduler: "MFF KDST Weekly Refresh",
# Tuesdays 7:00 AM — after MNF stats land on nflverse, before the 9am job).
#
# Runs scripts/refresh_kdst_data.py, which re-pulls kicker_history /
# kicker_weekly / dst_history+dst_weekly / kicker_splits off nflverse+ESPN
# and bumps the touched ?v= tags. Keeps game logs, L4 PPG, career tables,
# FG splits, and the kicker model's career inputs current all season.
# Commits + pushes ONLY when data changed. Mirrors daily_consensus_adp.ps1.
#
# Log: scripts/kdst_refresh_log.txt (kept to last ~300 lines).

$ErrorActionPreference = 'Continue'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$Log = Join-Path $Repo 'scripts\kdst_refresh_log.txt'

function Write-Log($msg) {
    $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
    Add-Content -Path $Log -Value $line -Encoding utf8
}

Set-Location $Repo
Write-Log '=== weekly K/DST refresh start ==='

# Refuse to run on dirty target files so a half-finished manual session isn't clobbered.
$Files = @('data/kicker_history.js', 'data/kicker_weekly.js', 'data/dst_history.js', 'data/dst_weekly.js', 'data/kicker_splits.js', 'index.html')
$dirty = git status --porcelain -- @Files
if ($dirty) {
    Write-Log "SKIP: uncommitted changes present:`n$dirty"
    exit 0
}

$out = & $Python 'scripts\refresh_kdst_data.py' 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) {
    Write-Log "REFRESH FAILED (exit $LASTEXITCODE) - nothing committed"
    exit 1
}

$changed = git status --porcelain -- @Files
if (-not $changed) {
    Write-Log 'no K/DST data movement - nothing to commit'
} else {
    git add @Files
    git commit -m ('Auto K/DST data refresh {0} (kicker+DST logs/history/splits)' -f (Get-Date -Format 'yyyy-MM-dd'))
    # Other jobs/cloud routines can land commits mid-morning; rebase so the push fast-forwards.
    git pull --rebase --autostash origin main
    git push origin main
    if ($LASTEXITCODE -eq 0) { Write-Log 'pushed K/DST refresh' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}

# Trim log to last 300 lines.
$lines = Get-Content $Log
if ($lines.Count -gt 300) { $lines | Select-Object -Last 300 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
