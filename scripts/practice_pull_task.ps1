# Practice-report pull (Task Scheduler: "MFF Practice Reports", daily 16:05 + 19:10 ET).
#
# Jack 2026-10-08: "can we have practice reports run 2 times 4ish and 7ish - reports
# are usually out by then". The NFL practice reports post mid-to-late afternoon ET;
# the betting-lines scan (daily_betting_pull.ps1) also pulls them, but only at
# 8:00 / 10:00 / 20:15 on most days. This runs JUST the practice pull
# (scripts/pull_practice_reports.py -> data/practice_2026.js + the card's day log
# data/practice_days_2026.js), bumps practice_days_2026.js?v= in index.html when
# the day log changed, and commits + pushes only those files.
#
# Day filing: a report day counts as released from 16:00 ET, so the 16:05 run can
# file a team that has not posted yet under today with yesterday's status; the
# 19:10 run (and the 20:15 sim export) overwrite that day once the team posts.
#
# Log: scripts/practice_pull_log.txt (kept to the last 400 lines).

$ErrorActionPreference = 'Continue'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$Log = Join-Path $Repo 'scripts\practice_pull_log.txt'

function Write-Log($msg) {
    $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
    Add-Content -Path $Log -Value $line -Encoding utf8
}

Set-Location $Repo
Write-Log '=== practice pull start ==='

# Refuse to run over uncommitted work on the files this job writes.
$Files = @('data/practice_2026.js', 'data/practice_days_2026.js', 'index.html')
$dirty = git status --porcelain -- @Files
if ($dirty) {
    Write-Log "SKIP: uncommitted changes present:`n$dirty"
    exit 0
}

$out = & $Python 'scripts\pull_practice_reports.py' 2>&1 | Out-String
foreach ($l in ($out.Trim() -split "`r?`n")) { if ($l.Trim()) { Write-Log ('pull: ' + $l.Trim()) } }

$pdChanged = git status --porcelain -- data/practice_days_2026.js
if ($pdChanged) {
    $idx = Join-Path $Repo 'index.html'
    $html = [System.IO.File]::ReadAllText($idx)
    $html2 = $html -replace 'practice_days_2026\.js\?v=[\w.-]+', ('practice_days_2026.js?v=' + (Get-Date -Format 'yyyy-MM-dd-HHmm'))
    if ($html2 -ne $html) { [System.IO.File]::WriteAllText($idx, $html2) }
}

$changed = git status --porcelain -- @Files
if (-not $changed) {
    Write-Log 'no practice change - nothing to commit'
} else {
    git add -- @Files
    # pathspec commit: only these files, whatever else happens to be staged
    git commit -m ('Auto practice report {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm')) -- @Files
    git push origin main
    if ($LASTEXITCODE -ne 0) {
        # main moved on (another session pushed): replay on top, same as the sim export task
        git pull --rebase --autostash origin main
        git push origin main
    }
    if ($LASTEXITCODE -eq 0) { Write-Log 'pushed practice report' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}

$lines = Get-Content $Log
if ($lines.Count -gt 400) { $lines | Select-Object -Last 400 | Set-Content -Path $Log -Encoding utf8 }
