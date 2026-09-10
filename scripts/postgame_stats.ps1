# Post-game weekly stats publish (Task Scheduler: "MFF Postgame Stats").
#
# Runs scripts/pull_postgame_stats.py after every game window so 2026 game
# logs, L4 PPG and the '26 PPG column land the same night. Only players whose
# game is FINAL (ESPN scoreboard) get rows, so the schedule can be generous:
#   daily 00:45      (TNF / SNF / MNF single game / Saturday slates)
#   Sun 13:05        (London 9:30am games)
#   Sun 16:50        (1pm slate)
#   Sun 20:15        (4:05 / 4:25 slate)
#   Tue 01:45        (MNF doubleheader late game)
# The Tuesday 8:30 full chain (sim_lab/tuesday_stats.ps1) still rebuilds
# sigma / Sim Lab / extension packs; this job is stats -> site only.
#
# Commits + pushes ONLY when weekly_stats_active.js changed, bumping its ?v=
# in index.html in the same commit (sw.js serves versioned URLs cache-first).
# Mirrors scripts/weekly_kdst_refresh.ps1 / tuesday_stats.ps1 guards.
#
# Log: scripts/postgame_stats_log.txt (kept to last ~300 lines).

$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
if (-not (Test-Path $Python)) { $Python = 'python' }
$Log = Join-Path $Repo 'scripts\postgame_stats_log.txt'

function Write-Log($msg) {
    Add-Content -Path $Log -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg) -Encoding utf8
}

Set-Location $Repo
Write-Log '=== postgame stats start ==='

# Refuse to run on dirty target files so another session's work isn't clobbered.
$Files = @('data/weekly_stats_active.js', 'index.html')
$dirty = git status --porcelain -- @Files
if ($dirty) {
    Write-Log "SKIP: uncommitted changes present:`n$dirty"
    exit 0
}

$out = & $Python 'scripts\pull_postgame_stats.py' 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) {
    Write-Log "IMPORT FAILED (exit $LASTEXITCODE) - nothing committed"
    exit 1
}

$changed = git status --porcelain -- data/weekly_stats_active.js
if (-not $changed) {
    Write-Log 'no new final-game rows - nothing to commit'
} else {
    # Read index.html from disk immediately before bumping - other jobs bump ?v= concurrently.
    $stamp = Get-Date -Format 'yyyy-MM-dd-HHmm'
    $idxPath = Join-Path $Repo 'index.html'
    $html = [System.IO.File]::ReadAllText($idxPath)
    $html = $html -replace 'weekly_stats_active\.js\?v=[0-9A-Za-z.-]+', ('weekly_stats_active.js?v=' + $stamp)
    [System.IO.File]::WriteAllText($idxPath, $html)
    git add data/weekly_stats_active.js index.html
    git commit -m ('Auto postgame stats {0} (weekly_stats_active 2026 rows + ?v= bump)' -f $stamp)
    git pull --rebase --autostash origin main
    git push origin main
    if ($LASTEXITCODE -eq 0) { Write-Log 'postgame stats committed + pushed' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}

# Trim log to last 300 lines.
$lines = Get-Content $Log
if ($lines.Count -gt 300) { $lines | Select-Object -Last 300 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
