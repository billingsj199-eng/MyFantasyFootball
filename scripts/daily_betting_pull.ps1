# Daily betting-lines scan (Task Scheduler: "MFF Betting Lines Daily").
#
# Runs the keyless requests-only phases of pull_betting_lines.py every
# morning — ESPN game lines (spreads/totals), Underdog season props, and
# UD + PrizePicks weekly prop boards — then commits + pushes ONLY when the
# data actually changed, so quiet offseason mornings are silent no-ops.
# The DK season-props phase (Selenium, visible Chrome) is NOT run here;
# run it manually when wanted: python scripts/pull_betting_lines.py --season-props
#
# Log: scripts/betting_pull_log.txt (kept to last ~400 lines).

$ErrorActionPreference = 'Continue'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$Log = Join-Path $Repo 'scripts\betting_pull_log.txt'

function Write-Log($msg) {
    $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
    Add-Content -Path $Log -Value $line -Encoding utf8
}

Set-Location $Repo
Write-Log '=== daily betting pull start ==='

# Refuse to run on a dirty data file so a half-finished manual session isn't clobbered.
$Files = @('data/betting_lines_2026.js', 'data/betting_lines_2026.json', 'index.html')
$dirty = git status --porcelain -- @Files
if ($dirty) {
    Write-Log "SKIP: uncommitted changes present:`n$dirty"
    exit 0
}

$out = & $Python 'scripts\pull_betting_lines.py' '--game-lines' '--underdog' '--weekly-props' 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) {
    Write-Log "PULL FAILED (exit $LASTEXITCODE) - nothing committed"
    exit 1
}

# Season-receptions watch: the puller prints this banner the first run any
# book posts a season receptions prop (PPR/Half/STD split from then on).
$recPosted = $out -match '\*\*\* SEASON RECEPTIONS PROP POSTED'
if ($recPosted) { Write-Log 'ALERT: season receptions prop posted - commit flagged for Jack' }

$changed = git status --porcelain -- @Files
if (-not $changed) {
    Write-Log 'no line movement - nothing to commit'
} else {
    git add @Files
    $msg = ('Auto betting-lines scan {0} (game lines + UD season + weekly props)' -f (Get-Date -Format 'yyyy-MM-dd'))
    if ($recPosted) { $msg = 'SEASON RECEPTIONS POSTED - ' + $msg }
    git commit -m $msg
    git push origin main
    if ($LASTEXITCODE -eq 0) { Write-Log 'pushed updated lines' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}

# Trim log to last 400 lines.
$lines = Get-Content $Log
if ($lines.Count -gt 400) { $lines | Select-Object -Last 400 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
