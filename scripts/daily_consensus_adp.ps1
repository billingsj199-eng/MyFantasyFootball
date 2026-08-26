# Daily consensus-ADP refresh (Task Scheduler: "MFF Consensus ADP Daily").
#
# Runs scripts/pull_consensus_adp.py every morning — FantasyPros consensus
# rankings (4 modes), ESPN rank, CBS rank, Yahoo O-Rank, Sleeper ADP ranks
# (4 modes, via repo-root pull_sleeper_adp.py; wired 2026-08-26), Underdog
# ADP (extension Firestore mirror), DraftKings best-ball ADP (Occupy
# Fantasy public feed -> d.js dk fields, scripts/update_dk_adp.py; wired
# 2026-08-26), KeepTradeCut dynasty values, and an NFL
# roster sync (Sleeper players dump -> d.js team assignments,
# scripts/update_rosters.py) — which rewrites the Site Rankings CSVs + KTC
# maps, re-runs inject_rankings.py into data/d.js, and bumps the touched
# ?v= tags in index.html. Commits + pushes ONLY when data changed.
#
# Log: scripts/consensus_adp_log.txt (kept to last ~400 lines).

$ErrorActionPreference = 'Continue'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$Log = Join-Path $Repo 'scripts\consensus_adp_log.txt'

function Write-Log($msg) {
    $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
    Add-Content -Path $Log -Value $line -Encoding utf8
}

Set-Location $Repo
Write-Log '=== daily consensus ADP pull start ==='

# Refuse to run on dirty target files so a half-finished manual session isn't clobbered.
# (Site Rankings CSVs are git-excluded local files — these are the tracked targets.)
$Files = @('data/d.js', 'index.html', 'data/_bundle_lookups.js', 'data/ktc_rankings.js', 'data/ud_adp_history.json', 'data/mike_clay_projections.js', 'data/injury_updates.js', 'data/weekly_projections.js', 'data/site_projections.js')
$dirty = git status --porcelain -- @Files
if ($dirty) {
    Write-Log "SKIP: uncommitted changes present:`n$dirty"
    exit 0
}

$out = & $Python 'scripts\pull_consensus_adp.py' 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) {
    Write-Log "PULL FAILED (exit $LASTEXITCODE) - nothing committed"
    exit 1
}

$changed = git status --porcelain -- @Files
if (-not $changed) {
    Write-Log 'no ADP movement - nothing to commit'
} else {
    git add @Files
    git commit -m ('Auto data refresh {0} (consensus ADPs + KTC + UD mirror + Clay + rosters)' -f (Get-Date -Format 'yyyy-MM-dd'))
    # Cloud routines (camp news) can land commits mid-morning; rebase so the push fast-forwards.
    git pull --rebase --autostash origin main
    git push origin main
    if ($LASTEXITCODE -eq 0) { Write-Log 'pushed updated ADPs' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}

# Trim log to last 400 lines.
$lines = Get-Content $Log
if ($lines.Count -gt 400) { $lines | Select-Object -Last 400 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
