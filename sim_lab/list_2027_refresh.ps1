# Weekly 2027 list refresh (Jack 2026-11-24: "schedule the jm export and rookie step", then the
# same day "Yes, do those" to one weekly job for the whole list; replaces rookies_2027_refresh.ps1).
# Task Scheduler: "MFF 2027 List Refresh", weekly TUESDAY 10:00 - after Monday's devy refresh has
# pushed the week's college stats / mock draft to the site (JM is scored in the browser from those)
# and after the Tuesday stats chain and the morning play-by-play pull.
#
#   1. JM export: scripts\pull_jm_scores.py loads the live site in headless Chrome and dumps the
#      prospect-model scores to the site repo's data\jm_scores.json (git-excluded). The new file
#      must parse, still hold the 2027 class and not be more than 3% short of the previous one,
#      or the previous one is put back. A failed export does NOT stop step 2: the veterans are
#      still rebuilt and the rookies are re-placed from the previous export.
#      (The Tuesday Dynasty SIM refresh runs the same export earlier in the morning; this job
#      runs its own so the order of the two never matters.)
#   2. Full rebuild: preseason2027\refresh_2027.py (normal run) - veterans through the latest
#      completed 2026 week, the superflex view, then the PROVISIONAL rookie class from the JM
#      scores. It checks its inputs first, restores the outputs itself if a step fails, and
#      writes a dated snapshot, a changelog and output\2027_refresh_status.md. The output files
#      are also backed up here first and put back if the result does not check out.
#   3. Put the list on the site (Jack 2026-11-24: "make it so I dont have to load a file and its
#      just on the site"): upload_2027_list.py POSTs the CSV to the key-gated Cloud Function
#      importSim2027, which writes the private doc the admin-only 2027 tab reads. No file step
#      for Jack. If the upload fails the alert says so and gives the manual way (2027 tab ->
#      UPDATE SIM FILE -> output\2027_inhouse_early.csv -> SAVE SIM FILE).
#   4. If players moved (veterans 10+ points, rookies 1+, or anyone new / gone): toast / alert
#      Jack with the biggest movers.
#
# It fetches nothing but the JM scores, re-tunes nothing, and does not touch git. The only
# upload is the list itself, to the private admin-only database doc.
#
# -DryRun: runs the JM export into preseason2027\output\_list_dryrun\ and stops (the rebuild has
#          no scratch mode; use preseason2027\_gate_teamcodes\run_list_scratch.py for that).
# Exit 0 = list rebuilt (moved or not), 1 = the rebuild failed (previous files restored).
# Log: preseason2027\list_refresh.log (last ~400 lines kept).

param([switch]$DryRun, [string]$PullScript = '')   # -PullScript: another copy of pull_jm_scores.py (testing)

$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$SiteDir = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Here    = 'E:\MyFantasyFootball\sim_lab\preseason2027'
$OutDir  = Join-Path $Here 'output'
$Log     = Join-Path $Here 'list_refresh.log'
$SchedPy = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'      # has selenium (JM export)
$SimPy   = 'C:\Users\billi\AppData\Local\Programs\Python\Python313\python.exe'      # has pandas / scipy (Sim Lab)
$JmFile  = Join-Path $SiteDir 'data\jm_scores.json'
$ListCsv = Join-Path $OutDir '2027_inhouse_early.csv'
$OutFiles = @('2026_inhouse_check.csv', '2026_inhouse_check.md', '2027_inhouse_early.csv', '2027_inhouse_early.md', '2027_inhouse_early_norookies.csv', '2027_refresh_status.md')
$Tag = if ($DryRun) { 'list-2027 (dry run)' } else { 'list-2027' }

function Write-Log($msg) {
    Add-Content -Path $Log -Value ('[{0}] {1}: {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Tag, $msg) -Encoding utf8
}
. (Join-Path $SiteDir 'scripts\mff_alert.ps1')
function Send-Alert($key, $msg) {
    Write-Log $msg
    if (-not $DryRun) { Send-MffAlert -Key ('list-2027-' + $key) -Message ('2027 list refresh: ' + $msg) }
}
# JM export summary: @{ ok; n27; count; exported } - ok = parses and still carries the 2027 class.
function Read-Jm($path) {
    try {
        $j = Get-Content $path -Raw -Encoding utf8 | ConvertFrom-Json
        $n27 = @($j.scores.PSObject.Properties | Where-Object { $_.Value.yr -eq 2027 }).Count
        return @{ ok = ($n27 -ge 50); n27 = $n27; count = [int]$j.count; exported = [string]$j.exported_at }
    } catch { return @{ ok = $false; n27 = 0; count = 0; exported = '' } }
}
# The list: 'name|pos' -> row.
function Read-List($csv) {
    $m = @{}
    if (Test-Path $csv) { Import-Csv $csv | ForEach-Object { $m[$_.name + '|' + $_.pos] = $_ } }
    return $m
}
function Is-Rookie($r) { return ($r.provisional -and [double]$r.provisional -eq 1) }

Write-Log '=== start ==='
if (-not $PullScript) { $PullScript = Join-Path $SiteDir 'scripts\pull_jm_scores.py' }
foreach ($p in $SchedPy, $SimPy, $PullScript, (Join-Path $Here 'refresh_2027.py'), $ListCsv) {
    if (-not (Test-Path $p)) { Send-Alert 'missing' "MISSING $p - nothing done"; exit 1 }
}

$Work = if ($DryRun) { Join-Path $OutDir '_list_dryrun' } else { Join-Path $OutDir '_list_bak' }
New-Item -ItemType Directory -Force -Path $Work | Out-Null

# ---- 1. JM export -------------------------------------------------------------------------
# The export must be the version that waits for the site's data before the prospect build
# (pull_jm_scores.py "def settle", 2026-11-24). The older one dumped whatever the page had built
# first: two exports on the same day came out 1456 vs 1623 scores, and that noise alone moved 124
# of 137 rookies. With the old script the export is skipped and the previous scores are used.
$prevJm = Read-Jm $JmFile
if (-not (Select-String -Path $PullScript -Pattern 'def settle' -SimpleMatch -Quiet)) {
    Send-Alert 'old-export' 'JM export SKIPPED - scripts\pull_jm_scores.py in the site checkout is the old version that exports before the page has loaded (unstable scores). Rookies stay on the previous export.'
} else {
    if ($DryRun) {
        # pull_jm_scores.py writes data\jm_scores.json under the current folder: run it from the dry-run folder.
        New-Item -ItemType Directory -Force -Path (Join-Path $Work 'data') | Out-Null
        $jmTarget = Join-Path $Work 'data\jm_scores.json'
        Push-Location $Work
    } else {
        if (Test-Path $JmFile) { Copy-Item $JmFile (Join-Path $Work 'jm_scores.json') -Force }
        $jmTarget = $JmFile
        Push-Location $SiteDir
    }
    $pull = & $SchedPy $PullScript 2>&1 | Out-String
    $pullExit = $LASTEXITCODE
    Pop-Location
    $newJm = Read-Jm $jmTarget
    # A real week adds or drops a handful of scored players; a short export (page not fully loaded)
    # came out 10% light. 3% is the line.
    $jmOk = ($pullExit -eq 0) -and $newJm.ok -and ($newJm.count -ge 0.97 * $prevJm.count)
    if ($jmOk) {
        Write-Log ("JM export ok: $($newJm.count) scores, $($newJm.n27) in the 2027 class (exported $($newJm.exported); previous $($prevJm.exported))")
    } else {
        if (-not $DryRun -and (Test-Path (Join-Path $Work 'jm_scores.json'))) { Copy-Item (Join-Path $Work 'jm_scores.json') $JmFile -Force }
        $why = if ($pullExit -ne 0) { "exit $pullExit" } else { "$($newJm.n27) 2027 prospects, $($newJm.count) scores (was $($prevJm.count))" }
        Send-Alert 'jm-failed' ("JM EXPORT FAILED ($why) - kept the " + $prevJm.exported + ' export; rookies stay on it. ' + ($pull.Trim() -split "`n" | Select-Object -Last 1))
    }
}
if ($DryRun) { Write-Log 'dry run - rebuild not run'; Write-Log '=== done ==='; exit 0 }

# ---- 2. full rebuild ----------------------------------------------------------------------
$before = Read-List $ListCsv
foreach ($f in $OutFiles) { $src = Join-Path $OutDir $f; if (Test-Path $src) { Copy-Item $src (Join-Path $Work $f) -Force } }
Push-Location $Here
$res = & $SimPy (Join-Path $Here 'refresh_2027.py') 2>&1 | Out-String
$stepExit = $LASTEXITCODE
Pop-Location

$after = @{}; $problem = ''
if ($stepExit -ne 0) { $problem = "exit $stepExit" }
else {
    try {
        $after = Read-List $ListCsv
        $nRk = @($after.Values | Where-Object { Is-Rookie $_ }).Count
        $nVet = $after.Count - $nRk
        $nVetBefore = @($before.Values | Where-Object { -not (Is-Rookie $_) }).Count
        if ($nRk -lt 50) { $problem = "only $nRk rookies in the result" }
        elseif ($nVet -lt 0.9 * $nVetBefore) { $problem = "veterans fell from $nVetBefore to $nVet" }
        elseif (@($after.Values | Where-Object { -not $_.total -or -not $_.rank }).Count) { $problem = 'rows without a total or rank' }
    } catch { $problem = 'result could not be read: ' + $_.Exception.Message }
}
if ($problem) {
    foreach ($f in $OutFiles) { $bak = Join-Path $Work $f; if (Test-Path $bak) { Copy-Item $bak (Join-Path $OutDir $f) -Force } }
    Send-Alert 'rebuild-failed' ("REBUILD FAILED ($problem) - previous list restored. " + ($res.Trim() -split "`n" | Select-Object -Last 1))
    exit 1
}
$wk = ''
$st = Select-String -Path (Join-Path $OutDir '2027_refresh_status.md') -Pattern 'through week (\d+)' | Select-Object -First 1
if ($st) { $wk = 'through week ' + $st.Matches[0].Groups[1].Value + ': ' }
$cl = ($res -split "`n" | Where-Object { $_ -match '^change log (\S+\.md)' } | Select-Object -Last 1)

# ---- 3. what moved ------------------------------------------------------------------------
$vets = @(); $rks = @()
foreach ($k in $after.Keys) {
    $a = $after[$k]; $rk = Is-Rookie $a
    if (-not $before.ContainsKey($k)) { $m = [pscustomobject]@{ who = $a.name; d = [double]$a.total; note = 'new' } }
    else {
        $d = [double]$a.total - [double]$before[$k].total
        if ([math]::Abs($d) -lt $(if ($rk) { 1 } else { 10 })) { continue }
        $m = [pscustomobject]@{ who = $a.name; d = $d; note = ('{0}{1} -> {0}{2}' -f $a.pos, $before[$k].pos_rank, $a.pos_rank) }
    }
    if ($rk) { $rks += $m } else { $vets += $m }
}
foreach ($k in @($before.Keys | Where-Object { -not $after.ContainsKey($_) })) {
    $m = [pscustomobject]@{ who = $before[$k].name; d = -[double]$before[$k].total; note = 'gone' }
    if (Is-Rookie $before[$k]) { $rks += $m } else { $vets += $m }
}
Write-Log ("rebuilt: $($after.Count) rows ($nVet veterans, $nRk rookies). " + $(if ($cl) { $cl.Trim() } else { '' }))

# ---- put the list on the site (the function skips a file identical to the one it has) ------
$Uploader = 'E:\MyFantasyFootball\sim_lab\upload_2027_list.py'
$upOk = $false; $upMsg = 'upload_2027_list.py is missing'
if (Test-Path $Uploader) {
    $up = & $SimPy -I $Uploader 2>&1 | Out-String
    $upOk = ($LASTEXITCODE -eq 0)
    $upMsg = ($up.Trim() -split "`n" | Select-Object -Last 1)
}
Write-Log ('site upload: ' + $upMsg)
$Manual = 'Do it by hand: 2027 tab -> UPDATE SIM FILE -> sim_lab\preseason2027\output\2027_inhouse_early.csv -> SAVE SIM FILE.'
$siteNote = if ($upOk) { ' The 2027 tab on the site shows the new list.' } else { ' SITE UPLOAD FAILED (' + $upMsg + '). ' + $Manual }

if (-not $vets.Count -and -not $rks.Count) {
    Write-Log "${wk}nobody moved (veterans 10+ points, rookies 1+)"
    if (-not $upOk) { Send-Alert 'upload-failed' ('the list was rebuilt but did not reach the site (' + $upMsg + '). ' + $Manual) }
} else {
    $byAbs = { -[math]::Abs($_.d) }
    foreach ($m in (@($vets) + @($rks) | Sort-Object $byAbs | Select-Object -First 30)) { Write-Log ('  {0}: {1:+0.0;-0.0} pts ({2})' -f $m.who, $m.d, $m.note) }
    $lead = { param($a) (($a | Sort-Object $byAbs | Select-Object -First 3 | ForEach-Object { '{0} {1:+0;-0}' -f $_.who, $_.d }) -join ', ') }
    $parts = @()
    if ($vets.Count) { $parts += ("$($vets.Count) veterans moved 10+ points (" + (& $lead $vets) + ')') }
    if ($rks.Count)  { $parts += ("$($rks.Count) rookies moved (" + (& $lead $rks) + ')') }
    Send-Alert 'updated' ($wk + ($parts -join '; ') + '.' + $siteNote)
}

$lines = Get-Content $Log
if ($lines.Count -gt 400) { $lines | Select-Object -Last 400 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
exit 0
