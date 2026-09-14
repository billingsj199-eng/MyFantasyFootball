# Tuesday in-season stats chain (Task Scheduler: "MFF Weekly Stats Tuesday").
# Runs after MNF stats are final:
#   1. fetch_weekly_stats.py   -> refreshes weekly_stats_active.js (2017-2026)
#   2. build_player_sigma.py   -> rebuilds per-player weekly sigma table
#   3. update_simlab.bat       -> feeds JS Weekly (sim_2026.js) + new sigma
#                                 into Sim Lab and deploys
#   4. export_sleeper_extension_data.py -> draft-helper players.json + sim
#      packs (the new player_weekly_sigma.js is baked into the helpers'
#      sim_pack.js; wired 2026-08-28, closes the 8:30->9am gap)
# Preseason runs are harmless (2026 weeks return empty payloads).
# Log: E:\MyFantasyFootball\sim_lab\tuesday_stats.log

$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'   # sigma builder prints Unicode; scheduler console is cp1252
$DataDir = 'E:\MyFantasyFootball\MyFantasyFootball Files\data'
$Log = 'E:\MyFantasyFootball\sim_lab\tuesday_stats.log'

function Write-Log($msg) {
    Add-Content -Path $Log -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
}

Set-Content -Path $Log -Value '' -Encoding utf8
Write-Log '=== tuesday stats chain start ==='

Set-Location $DataDir
$out = & python 'fetch_weekly_stats.py' 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) { Write-Log "FETCH FAILED (exit $LASTEXITCODE) - stopping"; exit 1 }

$out = & python 'build_player_sigma.py' 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) { Write-Log "SIGMA BUILD FAILED (exit $LASTEXITCODE) - stopping"; exit 1 }

# Weekly model scorecard (added 2026-09-14): archive last week's consensus
# projections BEFORE the 9am job flips them, then grade the pre-kickoff lock
# snapshot vs actuals (score_week.py + diagnose_week.py) -> scorecards\wN.log.
# Headless twin of the Sim Lab TRACKING SCORE ritual. Non-fatal.
$out = & python 'E:\MyFantasyFootball\sim_lab\weekly_scorecard.py' 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) { Write-Log "SCORECARD FAILED (exit $LASTEXITCODE) - continuing" }

# Snap counts (nflverse) -> data/snap_counts.js. Feeds the player card's
# SNP%/TS% columns AND Sim Lab's in-season snap-trend layer (refresh_data.py
# trims it to sim_snaps.js — the layer self-activates once 2026 weeks land).
# Was never scheduled anywhere before 2026-08-31; without this the snap trend
# would run stale all season. Non-fatal: stats/sigma still publish on failure.
$out = & python 'E:\MyFantasyFootball\MyFantasyFootball Files\scripts\pull_snap_counts.py' 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) { Write-Log "SNAP PULL FAILED (exit $LASTEXITCODE) - continuing without fresh snaps" }

# Route participation (RT%) -> data/route_pct.js (2026-09-14): nflverse
# participation for past seasons + PFF weekly exports dropped in
# pbp_cache\pff\weekly\ for the current one. Non-fatal.
$out = & python 'E:\MyFantasyFootball\MyFantasyFootball Files\scripts\pull_route_pct.py' --years 2026 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) { Write-Log "ROUTE PCT FAILED (exit $LASTEXITCODE) - continuing" }

# Publish the refreshed stats to the site repo. Without this the website never
# sees Tuesday's stats: no other job stages these two files, and the SW serves
# versioned URLs cache-first, so index.html's ?v= must bump in the same commit.
# (Sim Lab and the extension sim packs get the data via the steps below either
# way — this step is what gets it to myfantasyfootball.co.) Modeled on
# scripts/weekly_kdst_refresh.ps1. Added 2026-08-31.
$SiteDir = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$StatFiles = @('data/weekly_stats_active.js', 'data/player_weekly_sigma.js', 'data/snap_counts.js', 'data/route_pct.js')
$changedStats = git -C $SiteDir status --porcelain -- @StatFiles
if (-not $changedStats) {
    Write-Log 'weekly stats unchanged - no site commit'
} else {
    $dirtyIdx = git -C $SiteDir status --porcelain -- index.html
    if ($dirtyIdx) {
        Write-Log 'SKIP site publish: index.html has uncommitted changes from another session'
    } else {
        $stamp = Get-Date -Format 'yyyy-MM-dd'
        $idxPath = Join-Path $SiteDir 'index.html'
        # Read from disk immediately before bumping - other jobs bump ?v= concurrently.
        $html = [System.IO.File]::ReadAllText($idxPath)
        $html = $html -replace 'weekly_stats_active\.js\?v=[0-9A-Za-z.-]+', ('weekly_stats_active.js?v=' + $stamp)
        $html = $html -replace 'player_weekly_sigma\.js\?v=[0-9A-Za-z.-]+', ('player_weekly_sigma.js?v=' + $stamp)
        $html = $html -replace 'snap_counts\.js\?v=[0-9A-Za-z.-]+', ('snap_counts.js?v=' + $stamp)
        $html = $html -replace 'route_pct\.js\?v=[0-9A-Za-z.-]+', ('route_pct.js?v=' + $stamp)
        [System.IO.File]::WriteAllText($idxPath, $html)
        git -C $SiteDir add data/weekly_stats_active.js data/player_weekly_sigma.js data/snap_counts.js data/route_pct.js index.html
        git -C $SiteDir commit -m ('Auto weekly-stats refresh {0} (weekly_stats_active + sigma + snaps + routes + ?v= bump)' -f $stamp)
        git -C $SiteDir pull --rebase --autostash origin main
        git -C $SiteDir push origin main
        if ($LASTEXITCODE -eq 0) { Write-Log 'site weekly stats committed + pushed' } else { Write-Log "SITE PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
    }
}

# Volume x share model inputs for the JS model (shares/team volumes update
# as the season's weekly stats land). Non-fatal — local-only site.
$out = & python 'E:\MyFantasyFootball\js_model_site\scripts\build_vs_model.py' 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) { Write-Log "VS MODEL BUILD FAILED (exit $LASTEXITCODE) - continuing" }

& 'E:\MyFantasyFootball\sim_lab\update_simlab.bat'
if ($LASTEXITCODE -ne 0) { Write-Log "SIMLAB DEPLOY FAILED (exit $LASTEXITCODE)"; exit 1 }

# Draft-helper extension data (players.json x3 + sim packs) — the sigma
# table rebuilt above is one of the three files baked into the helpers'
# sim_pack.js. Outputs are git-excluded from the site repo. Non-fatal.
Set-Location 'E:\MyFantasyFootball\MyFantasyFootball Files'
$out = & python 'export_sleeper_extension_data.py' 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) { Write-Log "extension export FAILED (exit $LASTEXITCODE) - helpers keep previous data" }

# BBM full-field scoring (final weekly numbers, post-MNF). No-ops until the
# BBM VII field CSV is dropped in Best Ball Mania Files\BBM VII\. Non-fatal.
# Fri/Mon partial runs are the separate "MFF Field Scoring" task.
& powershell -NoProfile -ExecutionPolicy Bypass -File 'E:\MyFantasyFootball\sim_lab\field_scoring.ps1'
if ($LASTEXITCODE -ne 0) { Write-Log "FIELD SCORING FAILED (exit $LASTEXITCODE) - continuing (see field_scoring.log)" }

Write-Log '=== done ==='
