# January JM outcomes refresh (Task Scheduler: "MFF January Outcomes Refresh",
# yearly - second Tuesday of January 07:30, after Week 18 has been imported by
# the Tuesday postgame job).
#
# 1. scripts/regen_backtest_outcomes.py   roll data/backtest_outcomes.js forward
#      one NFL season: finalize open windows (2024 RB/WR/TE, 2023 QBs after 2026),
#      add the two newest classes, keep every finalized verdict byte-for-byte.
#      Exit 2 = calibration gate failed (nothing written), exit 3 = the season is
#      not in weekly_stats_active.js yet.
# 2. node scripts/jm_optimize.js            LOYO weight tuner + component correlations
# 3. node scripts/jm_optimize.js --exp      flag-gated experiments grid (teammate
#      competition, RB schedule adjustment)
# 4. scripts/jm_segment_analysis.py + jm_feature_discovery.py + jm_sos_analysis.py
#      on the new results (FCS / transfers / teammates / schedule).
# Commits the outcomes file + results JSON only. WEIGHTS ARE NEVER CHANGED HERE -
# Jack reads scripts/jm_january_<yr>.txt (this run's console output) and decides.
#
# Log: scripts/january_outcomes_log.txt

$ErrorActionPreference = 'Continue'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$Node = 'E:\node\node.exe'
$Log = Join-Path $Repo 'scripts\january_outcomes_log.txt'
$Year = (Get-Date).Year
$Season = $Year - 1
$Report = Join-Path $Repo ("scripts\jm_january_{0}.txt" -f $Year)

function Write-Log($msg) {
    $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
    Add-Content -Path $Log -Value $line -Encoding utf8
}
function Run-Step($label, $exe, $argList) {
    $out = & $exe @argList 2>&1 | Out-String
    Add-Content -Path $Report -Value ("`n===== {0} =====`n{1}" -f $label, $out) -Encoding utf8
    Write-Log ("{0}: exit {1}" -f $label, $LASTEXITCODE)
    return $LASTEXITCODE
}

Set-Location $Repo
Write-Log ('=== January outcomes refresh start (season {0}) ===' -f $Season)
Set-Content -Path $Report -Value ("JM January refresh {0} - completed season {1}" -f (Get-Date -Format 'yyyy-MM-dd'), $Season) -Encoding utf8

# 0. Opponent-grade prior (added 2026-10-05): the completed season's touchdown-neutral
#    points allowed by position -> data/fpa_prior_<season>.js, the "last season" half of
#    the site's opponent grade (app.js _mtObservedFpa picks FPA_PRIOR_<points-allowed season - 1>).
#    Independent of the JM steps, so it runs and commits first. The season rollover still
#    has to point the <script> tag in index.html at the new file.
$PriorFile = ('data/fpa_prior_{0}.js' -f $Season)
$env:PYTHONIOENCODING = 'utf-8'
$rc = Run-Step 'opponent-grade prior' $Python @('scripts\build_fpa_prior.py', '--season', "$Season")
if ($rc -ne 0) {
    Write-Log "opponent-grade prior FAILED (exit $rc) - JM steps continue"
} elseif ((Test-Path $PriorFile) -and (git status --porcelain -- $PriorFile)) {
    git add $PriorFile
    git commit -m ('Opponent-grade prior for the {0} season (touchdown-neutral points allowed by position)' -f $Season)
    git pull --rebase --autostash origin main
    git push origin main
    if ($LASTEXITCODE -eq 0) { Write-Log 'opponent-grade prior pushed' } else { Write-Log "opponent-grade prior PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}

$Files = @('data/backtest_outcomes.js', 'index.html')
$dirty = git status --porcelain -- @Files
if ($dirty) { Write-Log "SKIP: uncommitted changes present:`n$dirty"; exit 0 }

$env:PYTHONIOENCODING = 'utf-8'
$rc = Run-Step 'regen outcomes' $Python @('scripts\regen_backtest_outcomes.py', '--season', "$Season")
if ($rc -eq 3) { Write-Log 'season not imported yet - rerun after the Tuesday postgame import'; exit 0 }
if ($rc -eq 2) { Write-Log 'calibration gate failed - outcomes NOT regenerated; see report'; exit 0 }
if ($rc -ne 0) { Write-Log "regen FAILED (exit $rc)"; exit 1 }

# Graded career outcomes (elite seasons + consistency, no hit / bust labels) -> tier chips on the Prospect page
Run-Step 'modelling table' $Node @('scripts\jm_extract_table.js', '--out', 'scripts\jm_table.json') | Out-Null
Run-Step 'career grades' $Python @('scripts\build_outcome_grades.py', '--table', 'scripts\jm_table.json', '--out', 'scripts\jm_outcome_grades.json', '--js', 'data\jm_career_grades.js', '--bump', '--last-season', "$Season") | Out-Null

$results = ("scripts\jm_optimize_results_{0}.json" -f (Get-Date -Format 'yyyy-MM-dd'))
Run-Step 'weight tuner (LOYO)' $Node @('scripts\jm_optimize.js', '--out', $results) | Out-Null
Run-Step 'experiments grid' $Node @('scripts\jm_optimize.js', '--exp', '--out', ("scripts\jm_experiments_{0}.json" -f (Get-Date -Format 'yyyy-MM-dd'))) | Out-Null
if (Test-Path $results) {
    Run-Step 'segments (FCS / transfers)' $Python @('scripts\jm_segment_analysis.py', $results) | Out-Null
    Run-Step 'teammate features' $Python @('scripts\jm_feature_discovery.py', $results) | Out-Null
    Run-Step 'schedule strength' $Python @('scripts\jm_sos_analysis.py', $results) | Out-Null
}

$commitFiles = @('data/backtest_outcomes.js', 'index.html', 'data/jm_career_grades.js', 'data/_bundle_lookups.js', 'scripts/jm_outcome_grades.json') + (Get-ChildItem 'scripts' -Filter ("jm_*{0}*.json" -f (Get-Date -Format 'yyyy-MM-dd')) | ForEach-Object { 'scripts/' + $_.Name }) + @(('scripts/jm_january_{0}.txt' -f $Year))
$changed = git status --porcelain -- @commitFiles
if (-not $changed) {
    Write-Log 'nothing changed - nothing to commit'
} else {
    git add @commitFiles
    git commit -m ('JM backtest outcomes rolled to the {0} season + January tuner/experiment results' -f $Season)
    git pull --rebase --autostash origin main
    git push origin main
    if ($LASTEXITCODE -eq 0) { Write-Log 'pushed' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}
Write-Log ('report: ' + $Report)
Write-Log '=== done ==='
