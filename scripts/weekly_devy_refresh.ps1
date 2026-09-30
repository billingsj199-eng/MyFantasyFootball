# Devy / prospect in-season stats refresh (Task Scheduler: "MFF Devy Weekly Refresh",
# weekly MONDAY 07:15 - after Saturday's college slate has settled on CFBD, after
# the 06:15 route-pct job, before the 07:45 K/DST + 8am/9am jobs).
#
# Runs scripts/refresh_devy_stats.py, which pulls the current college season's
# game logs off CFBD for every devy / future-class prospect in COMBINE_DATA and
# rewrites data/college_stats_devy.js (season row spliced into COLLEGE_STATS at
# load + card game log). The JM prospect model scores off COLLEGE_STATS in the
# browser, so pushing the data file is what moves the devy grades on the site.
# Bumps the file's ?v= only when its bytes change.
# Commits + pushes ONLY when data changed. Mirrors weekly_kdst_refresh.ps1.
#
# Log: scripts/devy_refresh_log.txt (kept to last ~300 lines).

$ErrorActionPreference = 'Continue'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$Log = Join-Path $Repo 'scripts\devy_refresh_log.txt'

function Write-Log($msg) {
    $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
    Add-Content -Path $Log -Value $line -Encoding utf8
}

Set-Location $Repo
Write-Log '=== weekly devy refresh start ==='

# Refuse to run on dirty target files so a half-finished manual session isn't clobbered.
$Files = @('data/college_stats_devy.js', 'scripts/devy_refresh_cache.json', 'index.html')
$dirty = git status --porcelain -- @Files
if ($dirty) {
    Write-Log "SKIP: uncommitted changes present:`n$dirty"
    exit 0
}

$out = & $Python 'scripts\refresh_devy_stats.py' 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) {
    Write-Log "REFRESH FAILED (exit $LASTEXITCODE) - nothing committed"
    exit 1
}

$changed = git status --porcelain -- @Files
if (-not $changed) {
    Write-Log 'no devy data movement - nothing to commit'
} else {
    git add @Files
    git commit -m ('Auto devy college stats refresh {0} (college_stats_devy.js + ?v= bump)' -f (Get-Date -Format 'yyyy-MM-dd'))
    # Other jobs/cloud routines can land commits mid-morning; rebase so the push fast-forwards.
    git pull --rebase --autostash origin main
    git push origin main
    if ($LASTEXITCODE -eq 0) { Write-Log 'pushed devy refresh' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}

# Trim log to last 300 lines.
$lines = Get-Content $Log
if ($lines.Count -gt 300) { $lines | Select-Object -Last 300 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
