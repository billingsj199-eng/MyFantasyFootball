# Weekly 2027 rookie-class refresh (Jack 2026-11-24: "schedule the jm export and rookie step").
# Task Scheduler: "MFF 2027 Rookies Refresh", weekly TUESDAY 10:00 - after Monday's devy refresh
# has pushed the week's college stats / mock draft to the site (JM is scored in the browser from
# those) and after the Tuesday stats chain.
#
#   1. JM export: scripts\pull_jm_scores.py loads the live site in headless Chrome and dumps the
#      prospect-model scores to the site repo's data\jm_scores.json (git-excluded). The new file
#      must parse, still hold the 2027 class and not be more than 3% short of the previous one,
#      or the previous one is put back. (The Tuesday Dynasty SIM refresh runs the same export
#      earlier in the morning; this job runs its own so the order of the two never matters.)
#   2. Rookie step: preseason2027\a15_rookies.py insert re-places the PROVISIONAL 2027 rookie
#      class in output\2027_inhouse_early.csv/.md from those scores (veterans' numbers are not
#      touched by that step). The three output files are backed up first and restored if the
#      step fails or the result does not check out.
#   3. If any rookie moved a point or more (or joined / left the class): toast / alert Jack. The site's admin-only 2027 board reads
#      the file from the private database, so the last step is still his: 2027 tab ->
#      UPDATE SIM FILE -> choose output\2027_inhouse_early.csv -> SAVE SIM FILE.
#
# It does NOT rebuild the veterans (that is preseason2027\refresh_2027.py, run by hand), touch
# git, or upload anything.
#
# -DryRun: same steps into preseason2027\output\_rookies_dryrun\ (its own copy of the JM export
#          and of the list); the real jm_scores.json and outputs are left alone, no alert.
# Exit 0 = ok (changed or not), 1 = a step failed (previous files restored).
# Log: preseason2027\rookies_refresh.log (last ~400 lines kept).

param([switch]$DryRun, [string]$PullScript = '')   # -PullScript: another copy of pull_jm_scores.py (testing)

$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$SiteDir = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Here    = 'E:\MyFantasyFootball\sim_lab\preseason2027'
$OutDir  = Join-Path $Here 'output'
$Log     = Join-Path $Here 'rookies_refresh.log'
$SchedPy = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'      # has selenium (JM export)
$SimPy   = 'C:\Users\billi\AppData\Local\Programs\Python\Python313\python.exe'      # has pandas / scipy (Sim Lab)
$JmFile  = Join-Path $SiteDir 'data\jm_scores.json'
$OutFiles = @('2027_inhouse_early.csv', '2027_inhouse_early.md', '2027_inhouse_early_norookies.csv')
$Tag = if ($DryRun) { 'rookies-2027 (dry run)' } else { 'rookies-2027' }

function Write-Log($msg) {
    Add-Content -Path $Log -Value ('[{0}] {1}: {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Tag, $msg) -Encoding utf8
}
. (Join-Path $SiteDir 'scripts\mff_alert.ps1')
function Send-Alert($key, $msg) {
    Write-Log $msg
    if (-not $DryRun) { Send-MffAlert -Key ('rookies-2027-' + $key) -Message ('2027 rookies refresh: ' + $msg) }
}
# JM export summary: @{ ok; n27; count; exported } - ok = parses and still carries the 2027 class.
function Read-Jm($path) {
    try {
        $j = Get-Content $path -Raw -Encoding utf8 | ConvertFrom-Json
        $n27 = @($j.scores.PSObject.Properties | Where-Object { $_.Value.yr -eq 2027 }).Count
        return @{ ok = ($n27 -ge 50); n27 = $n27; count = [int]$j.count; exported = [string]$j.exported_at }
    } catch { return @{ ok = $false; n27 = 0; count = 0; exported = '' } }
}
# Provisional rookie rows of a list: 'name|pos' -> row.
function Read-Rookies($csv) {
    $m = @{}
    if (Test-Path $csv) {
        Import-Csv $csv | Where-Object { $_.provisional -and [double]$_.provisional -eq 1 } | ForEach-Object { $m[$_.name + '|' + $_.pos] = $_ }
    }
    return $m
}

Write-Log '=== start ==='
foreach ($p in $SchedPy, $SimPy, (Join-Path $Here 'a15_rookies.py'), (Join-Path $OutDir '2027_inhouse_early.csv')) {
    if (-not (Test-Path $p)) { Send-Alert 'missing' "MISSING $p - nothing done"; exit 1 }
}

# The export must be the version that waits for the site's data before the prospect build
# (pull_jm_scores.py "def settle", 2026-11-24). The older one dumped whatever the page had built
# first: two exports on the same day came out 1456 vs 1623 scores, and that noise alone moved 124
# of 137 rookies. Without the fix this job would only publish noise, so it stops here.
if (-not $PullScript) { $PullScript = Join-Path $SiteDir 'scripts\pull_jm_scores.py' }
if (-not (Select-String -Path $PullScript -Pattern 'def settle' -SimpleMatch -Quiet)) {
    Send-Alert 'old-export' 'SKIPPED - scripts\pull_jm_scores.py in the site checkout is the old version that exports before the page has loaded (unstable scores). Merge the fix (branch feat/board-2027) and rerun.'
    exit 1
}

$Work = if ($DryRun) { Join-Path $OutDir '_rookies_dryrun' } else { Join-Path $OutDir '_rookies_bak' }
New-Item -ItemType Directory -Force -Path $Work | Out-Null

# ---- 1. JM export -------------------------------------------------------------------------
$prevJm = Read-Jm $JmFile
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
if (-not $jmOk) {
    if (-not $DryRun -and (Test-Path (Join-Path $Work 'jm_scores.json'))) { Copy-Item (Join-Path $Work 'jm_scores.json') $JmFile -Force }
    $why = if ($pullExit -ne 0) { "exit $pullExit" } else { "$($newJm.n27) 2027 prospects, $($newJm.count) scores (was $($prevJm.count))" }
    Send-Alert 'jm-failed' ("JM EXPORT FAILED ($why) - kept the " + $prevJm.exported + ' export, rookie step not run. ' + ($pull.Trim() -split "`n" | Select-Object -Last 1))
    exit 1
}
Write-Log ("JM export ok: $($newJm.count) scores, $($newJm.n27) in the 2027 class (exported $($newJm.exported); previous $($prevJm.exported))")

# ---- 2. rookie step -----------------------------------------------------------------------
$before = Read-Rookies (Join-Path $OutDir '2027_inhouse_early.csv')
$vetsBefore = @(Import-Csv (Join-Path $OutDir '2027_inhouse_early.csv') | Where-Object { -not $_.provisional -or [double]$_.provisional -ne 1 }).Count
foreach ($f in $OutFiles) { $src = Join-Path $OutDir $f; if (Test-Path $src) { Copy-Item $src (Join-Path $Work $f) -Force } }
if ($DryRun) {
    # Same code, pointed at the dry-run copies of the JM export and the list.
    $resultCsv = Join-Path $Work '2027_inhouse_early.csv'
    $code = "import sys; sys.path.insert(0, r'$Here'); import a15_rookies as A; A.load_jm.__defaults__ = (r'$jmTarget',); A.OUT = r'$Work'; A.insert(r'$resultCsv', r'$(Join-Path $Work '2027_inhouse_early.md')')"
    Push-Location $Here
    $res = & $SimPy -c $code 2>&1 | Out-String
} else {
    $resultCsv = Join-Path $OutDir '2027_inhouse_early.csv'
    Push-Location $Here
    $res = & $SimPy (Join-Path $Here 'a15_rookies.py') 'insert' 2>&1 | Out-String
}
$stepExit = $LASTEXITCODE
Pop-Location

$after = @{}; $vetsAfter = -1; $problem = ''
if ($stepExit -ne 0) { $problem = "exit $stepExit" }
else {
    try {
        $after = Read-Rookies $resultCsv
        $vetsAfter = @(Import-Csv $resultCsv | Where-Object { -not $_.provisional -or [double]$_.provisional -ne 1 }).Count
        if ($after.Count -lt 50) { $problem = "only $($after.Count) rookies in the result" }
        elseif ($vetsAfter -ne $vetsBefore) { $problem = "veteran rows changed ($vetsBefore -> $vetsAfter)" }
        elseif (@($after.Values | Where-Object { -not $_.total -or -not $_.rank }).Count) { $problem = 'rookie rows without a total or rank' }
    } catch { $problem = 'result could not be read: ' + $_.Exception.Message }
}
if ($problem) {
    if (-not $DryRun) { foreach ($f in $OutFiles) { $bak = Join-Path $Work $f; if (Test-Path $bak) { Copy-Item $bak (Join-Path $OutDir $f) -Force } } }
    Send-Alert 'step-failed' ("ROOKIE STEP FAILED ($problem) - previous list restored. " + ($res.Trim() -split "`n" | Select-Object -Last 1))
    exit 1
}

# ---- 3. what moved ------------------------------------------------------------------------
$moves = @()
foreach ($k in $after.Keys) {
    $a = $after[$k]
    if (-not $before.ContainsKey($k)) { $moves += [pscustomobject]@{ who = $a.name; d = [double]$a.total; note = 'new to the class' }; continue }
    $d = [double]$a.total - [double]$before[$k].total
    if ([math]::Abs($d) -ge 1) {   # a point or more on the season; rank-only reshuffles are not news
        $moves += [pscustomobject]@{ who = $a.name; d = $d; note = ('JM {0} -> {1}, #{2} -> #{3}' -f $before[$k].jm, $a.jm, $before[$k].rank, $a.rank) }
    }
}
$gone = @($before.Keys | Where-Object { -not $after.ContainsKey($_) })
foreach ($k in $gone) { $moves += [pscustomobject]@{ who = $before[$k].name; d = -[double]$before[$k].total; note = 'no longer in the class' } }

if (-not $moves.Count) {
    Write-Log "rookie step ok: $($after.Count) rookies, nobody moved a point or more"
} else {
    $top = $moves | Sort-Object { -[math]::Abs($_.d) } | Select-Object -First 5
    foreach ($m in ($moves | Sort-Object { -[math]::Abs($_.d) } | Select-Object -First 25)) { Write-Log ('  {0}: {1:+0.0;-0.0} pts ({2})' -f $m.who, $m.d, $m.note) }
    $lead = ($top | ForEach-Object { '{0} {1:+0;-0}' -f $_.who, $_.d }) -join ', '
    Send-Alert 'updated' ("$($moves.Count) of $($after.Count) rookies moved a point or more ($lead). Open the 2027 tab -> UPDATE SIM FILE -> sim_lab\preseason2027\output\2027_inhouse_early.csv -> SAVE SIM FILE.")
}

$lines = Get-Content $Log
if ($lines.Count -gt 400) { $lines | Select-Object -Last 400 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
exit 0
