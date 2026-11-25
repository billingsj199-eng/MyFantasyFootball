# Weekly MFF VALUE edge + value forecast + in-house KTC roll (Jack 2026-11-24 "Go live";
# proposals P-20261124-1..3) - called by tuesday_stats.ps1 right after the Dynasty SIM step.
#
#   1. GATE: does nothing until the re-tune is on the site's app.js (looks for _fairEdge).
#   2. build_lasting_edge.py -> a STAGING copy of data\mff_lasting_edge.js (about 10-15 min: panel,
#      rating edge, 3- / 6-month forecast for 1QB + SF, and - while our KTC copy is 3+ weeks frozen
#      in season - the rolled prices). No repo turn is held while it computes.
#   3. Takes the repo turn, copies the file into the site checkout, bumps
#      <meta name="mff-lasting-edge-v"> in index.html, commits just those two files, pull --rebase, push.
#
# -DryRun: builds with --dry-run (nothing written to the site), no git.
# Exit 0 = ok / skipped, 1 = build failed (the chain treats it as non-fatal: the site keeps last
# week's file; app.js ignores a rolled order older than 10 days and hides a forecast whose
# starting price is older than 21 days).
# Log: appended to the caller's log via -Log (default sim_lab\lasting_edge_refresh.log).

param(
    [switch]$DryRun,
    [string]$SiteDir = 'E:\MyFantasyFootball\MyFantasyFootball Files',
    [string]$Log = 'E:\MyFantasyFootball\sim_lab\lasting_edge_refresh.log'
)

$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$SimLab = 'E:\MyFantasyFootball\sim_lab'

function Write-Log($msg) {
    Add-Content -Path $Log -Value ('[{0}] lasting-edge: {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
}

$appJs = Join-Path $SiteDir 'app.js'
if (-not (Select-String -Path $appJs -Pattern '_fairEdge' -SimpleMatch -Quiet)) {
    Write-Log 'MFF VALUE re-tune not on this checkout yet (no _fairEdge in app.js) - skipped'
    exit 0
}

$dataRel = 'data/mff_lasting_edge.js'
$stage = Join-Path $SimLab '_dyn_cache\edge_stage'
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'data') | Out-Null
$staged = Join-Path $stage 'data\mff_lasting_edge.js'
if (Test-Path $staged) { Remove-Item $staged -Force }

$sw = [Diagnostics.Stopwatch]::StartNew()
$pyArgs = @((Join-Path $SimLab 'build_lasting_edge.py'), '--site', $stage)
if ($DryRun) { $pyArgs += '--dry-run' }
$res = & python @pyArgs 2>&1 | Out-String
Write-Log ($res.Trim())
if ($LASTEXITCODE -ne 0) { Write-Log "BUILD FAILED (exit $LASTEXITCODE) - site keeps last week's file"; exit 1 }
Write-Log ('built in {0:N0}s' -f $sw.Elapsed.TotalSeconds)
if ($DryRun) { Write-Log 'dry run - nothing written to the site, no git'; exit 0 }
if (-not (Test-Path $staged)) { Write-Log 'BUILD wrote no file - site keeps last week''s file'; exit 1 }

# Repo turn only for the publish (one automation at a time in the site checkout).
. (Join-Path $SiteDir 'scripts\repo_guard.ps1')
if (-not (Enter-RepoTurn -Log { param($m) Write-Log $m } -Job 'MFF VALUE edge refresh')) { exit 0 }

$dirty = git -C $SiteDir status --porcelain -- index.html $dataRel
if ($dirty) {
    Write-Log 'SKIP publish: index.html or the edge file has uncommitted changes from another session'
    Exit-RepoTurn
    exit 0
}
Copy-Item $staged (Join-Path $SiteDir 'data\mff_lasting_edge.js') -Force
$changed = git -C $SiteDir status --porcelain -- $dataRel
if (-not $changed) { Write-Log 'file unchanged - no site commit'; Exit-RepoTurn; exit 0 }

$stamp = Get-Date -Format 'yyyy-MM-dd'
$idxPath = Join-Path $SiteDir 'index.html'
# Read from disk immediately before bumping - other jobs bump ?v= concurrently.
$html = [System.IO.File]::ReadAllText($idxPath)
$new = [regex]::Replace($html, '(<meta name="mff-lasting-edge-v" content=")[^"]*(")', ('${1}' + $stamp + '${2}'))
if ($html -notmatch '<meta name="mff-lasting-edge-v" content="') {
    Write-Log 'SKIP publish: mff-lasting-edge-v meta tag not found in index.html (edge file restored)'
    git -C $SiteDir checkout -- $dataRel
    Exit-RepoTurn
    exit 0
}
[System.IO.File]::WriteAllText($idxPath, $new)
git -C $SiteDir add $dataRel index.html
git -C $SiteDir commit -m ('Auto MFF VALUE edge + forecast refresh {0} (data/mff_lasting_edge.js + meta version bump)' -f $stamp)
Push-Location $SiteDir
$ok = Invoke-SafePullPush -Log { param($m) Write-Log $m } -What 'MFF VALUE edge refresh'
Pop-Location
if ($ok) { Write-Log 'committed + pushed' } else { Write-Log 'NOT PUBLISHED - see the line above (commit failed or push failed)' }
Exit-RepoTurn
exit 0
