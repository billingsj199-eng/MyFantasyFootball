# Weekly Dynasty SIM rebuild (Jack 2026-10-09) — called by tuesday_stats.ps1
# after the weekly stats publish (the generator reads the fresh
# weekly_stats_active.js; it auto-detects completed 2026 weeks).
#
#   1. GATE: does nothing until DYN SIM is merged into the site's app.js
#      (looks for _dynSimSrc) — the prototype is not published early.
#   2. build_dynasty_sim.py -> data\dynasty_sim_2026.js (PPR/HALF/STD x 1QB/SF + TEP)
#   3. if the file changed: bump <meta name="mff-dyn-sim-v"> in index.html,
#      commit just those two files, pull --rebase, push.
#
# -DryRun: builds to sim_lab\_dyn_cache\dynasty_sim_dryrun.js, no git.
# Exit 0 = ok / skipped, 1 = build failed (the chain treats it as non-fatal).
# Log: appended to the caller's log via -Log (default sim_lab\dynasty_sim_refresh.log).

param(
    [switch]$DryRun,
    [string]$SiteDir = 'E:\MyFantasyFootball\MyFantasyFootball Files',
    [string]$Log = 'E:\MyFantasyFootball\sim_lab\dynasty_sim_refresh.log'
)

$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$SimLab = 'E:\MyFantasyFootball\sim_lab'

function Write-Log($msg) {
    Add-Content -Path $Log -Value ('[{0}] dynasty-sim: {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
}

$appJs = Join-Path $SiteDir 'app.js'
if (-not (Select-String -Path $appJs -Pattern '_dynSimSrc' -SimpleMatch -Quiet)) {
    Write-Log 'DYN SIM not on main yet (no _dynSimSrc in app.js) - skipped'
    exit 0
}

# Repo turn (2026-10-20): one automation at a time in the site checkout. Nested in
# tuesday_stats.ps1 this runs inside the chain's turn; standalone it waits its own.
. (Join-Path $SiteDir 'scripts\repo_guard.ps1')
if (-not $DryRun -and -not (Enter-RepoTurn -Log { param($m) Write-Log $m } -Job 'dynasty SIM refresh')) { exit 0 }

# Fresh JM prospect scores for the rookie-pick class read (dyn_picks.py):
# headless Chrome on the live site via the scheduler Python (has selenium).
# data/jm_scores.json is git-excluded. Non-fatal: keeps the last snapshot.
$SchedPy = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
if (-not $DryRun -and (Test-Path $SchedPy)) {
    Push-Location $SiteDir
    $jm = & $SchedPy 'scripts\pull_jm_scores.py' 2>&1 | Out-String
    Pop-Location
    if ($LASTEXITCODE -ne 0) { Write-Log "JM refresh FAILED (exit $LASTEXITCODE) - using the last jm_scores.json" } else { Write-Log ($jm.Trim() -split "`n" | Select-Object -Last 1) }
}

$dataRel = 'data/dynasty_sim_2026.js'
$out = if ($DryRun) { Join-Path $SimLab '_dyn_cache\dynasty_sim_dryrun.js' } else { Join-Path $SiteDir $dataRel }
$sw = [Diagnostics.Stopwatch]::StartNew()
# --jm-cond: conditional JM credit for years 1-3 (shipped 10-09, 9530295)
$res = & python (Join-Path $SimLab 'build_dynasty_sim.py') --out $out --jm-cond 2>&1 | Out-String
Write-Log ($res.Trim())
if ($LASTEXITCODE -ne 0) { Write-Log "BUILD FAILED (exit $LASTEXITCODE) - site keeps last week's values"; exit 1 }
Write-Log ('built in {0:N0}s -> {1}' -f $sw.Elapsed.TotalSeconds, $out)
if ($DryRun) { Write-Log 'dry run - no git'; exit 0 }

$changed = git -C $SiteDir status --porcelain -- $dataRel
if (-not $changed) { Write-Log 'values unchanged - no site commit'; exit 0 }

# Weekly point for the player-card DYNASTY chart (data/dynasty_sim_history.js;
# one entry per valuation week, replaced if the same week is rebuilt). Non-fatal.
$histRel = 'data/dynasty_sim_history.js'
$h = & python (Join-Path $SimLab 'build_dynasty_sim_history.py') --add $out --out (Join-Path $SiteDir $histRel) 2>&1 | Out-String
Write-Log ($h.Trim())
$histOk = ($LASTEXITCODE -eq 0)

$dirtyIdx = git -C $SiteDir status --porcelain -- index.html
if ($dirtyIdx) {
    Write-Log 'SKIP publish: index.html has uncommitted changes from another session (data file left modified)'
    exit 0
}
$stamp = Get-Date -Format 'yyyy-MM-dd'
$idxPath = Join-Path $SiteDir 'index.html'
# Read from disk immediately before bumping - other jobs bump ?v= concurrently.
$html = [System.IO.File]::ReadAllText($idxPath)
$new = [regex]::Replace($html, '(<meta name="mff-dyn-sim-v" content=")[^"]*(")', ('${1}' + $stamp + '${2}'))
if ($new -eq $html -and $html -notmatch 'mff-dyn-sim-v" content="' + [regex]::Escape($stamp)) {
    Write-Log 'SKIP publish: mff-dyn-sim-v meta tag not found in index.html'
    exit 0
}
if ($histOk) { $new = [regex]::Replace($new, '(<meta name="mff-dyn-hist-v" content=")[^"]*(")', ('${1}' + $stamp + '${2}')) }
[System.IO.File]::WriteAllText($idxPath, $new)
git -C $SiteDir add $dataRel index.html
if ($histOk) { git -C $SiteDir add $histRel }
git -C $SiteDir commit -m ('Auto dynasty SIM refresh {0} (data/dynasty_sim_2026.js + weekly history + meta version bumps)' -f $stamp)
# 2026-10-20: was a bare pull + push that logged "committed + pushed" even when the
# commit failed; Invoke-SafePullPush checks it landed and aborts a conflicted rebase.
Push-Location $SiteDir
$ok = Invoke-SafePullPush -Log { param($m) Write-Log $m } -What 'dynasty SIM refresh'
Pop-Location
if ($ok) { Write-Log 'committed + pushed' } else { Write-Log 'NOT PUBLISHED - see the line above (commit failed or push failed)' }
exit 0
