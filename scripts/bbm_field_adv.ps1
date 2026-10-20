# Full-field BBM VII advance rate publish (Task Scheduler: "MFF BBM Field Adv").
#
# Runs scripts/bbm_field_adv.py: re-scores all 672,324 Best Ball Mania VII
# teams (rosters from the one-time full pull in E:\MyFantasyFootball\bbm_field,
# NEVER committed — it carries usernames) on Sleeper weekly stats, ranks each
# 12-team draft group, and writes per-player advance counts to
# data/bbm_field_adv.js (My Teams > Underdog > DRAFT BOARD "OVERALL ADV RATE").
# A week counts only once every game in it is FINAL on ESPN, so:
#   Tue 03:15  (after MNF)
#   Wed 03:15  (backup if a Monday game ran late / Tuesday run missed)
# Idempotent: the script leaves the file untouched when no new week is final,
# and this wrapper commits + pushes ONLY when the data file changed, bumping
# its ?v= in index.html in the same commit (read fresh — other jobs bump too).
# Mirrors scripts/postgame_stats.ps1 guards.
#
# Log: scripts/bbm_field_adv_log.txt (kept to last ~300 lines).

$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
if (-not (Test-Path $Python)) { $Python = 'python' }
$Log = Join-Path $Repo 'scripts\bbm_field_adv_log.txt'

function Write-Log($msg) {
    Add-Content -Path $Log -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg) -Encoding utf8
}

Set-Location $Repo
Write-Log '=== bbm field adv start ==='

. (Join-Path $PSScriptRoot 'repo_guard.ps1')
if (-not (Enter-RepoTurn -Log { param($m) Write-Log $m } -Job 'BBM field adv')) { exit 0 }   # one job at a time (2026-10-20)
if (Test-RepoBlocked -Log { param($m) Write-Log $m } -Job 'BBM field adv') { exit 1 }

# Refuse to run on dirty target files so another session's work isn't clobbered.
$Files = @('data/bbm_field_adv.js', 'index.html')
$dirty = git status --porcelain -- @Files
if ($dirty) {
    Write-Log "SKIP: uncommitted changes present:`n$dirty"
    exit 0
}

$out = & $Python 'scripts\bbm_field_adv.py' 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) {
    Write-Log "BUILD FAILED (exit $LASTEXITCODE) - nothing committed"
    exit 1
}

$changed = git status --porcelain -- data/bbm_field_adv.js
if (-not $changed) {
    Write-Log 'no new final week - nothing to commit'
} else {
    # Read index.html from disk immediately before bumping - other jobs bump ?v= concurrently.
    $stamp = Get-Date -Format 'yyyy-MM-dd-HHmm'
    $idxPath = Join-Path $Repo 'index.html'
    $html = [System.IO.File]::ReadAllText($idxPath)
    $html = $html -replace 'bbm_field_adv\.js\?v=[0-9A-Za-z.-]+', ('bbm_field_adv.js?v=' + $stamp)
    [System.IO.File]::WriteAllText($idxPath, $html)
    git add data/bbm_field_adv.js index.html
    git commit -m ('Auto BBM VII full-field advance rate {0} (bbm_field_adv.js + ?v= bump)' -f $stamp)
    $global:LASTEXITCODE = $(if (Invoke-SafePullPush -Log { param($m) Write-Log $m } -What 'bbm field adv') { 0 } else { 1 })
    if ($LASTEXITCODE -eq 0) { Write-Log 'bbm field adv committed + pushed' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}

# Trim log to last 300 lines.
$lines = Get-Content $Log
if ($lines.Count -gt 300) { $lines | Select-Object -Last 300 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
