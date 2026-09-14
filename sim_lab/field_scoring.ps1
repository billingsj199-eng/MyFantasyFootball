# BBM full-field scoring runner (Task Scheduler: "MFF Field Scoring",
# Fri + Mon 8:00 AM; also called as the last step of tuesday_stats.ps1).
# No-ops harmlessly until BOTH are true:
#   1. the BBM VII pick-by-pick CSV exists in
#      E:\MyFantasyFootball\MyFantasyFootball Files\Best Ball Mania Files\BBM VII\
#      (drop the official rd1 file there when it lands on underdognetwork.com
#      — expected ~mid-Sep 2026 if they repeat the BBM VI timing)
#   2. the regular season is underway (--weeks auto exits quietly otherwise)
# Output: sim_lab\field_out\field_leaderboard_2026.csv (+ dist json) and the
# jackb933 pod report in the log. Fri run = through TNF, Mon = through Sunday,
# Tue (via the stats chain) = final with MNF.
# Log: E:\MyFantasyFootball\sim_lab\field_scoring.log
# NOTE (2026-08-28): the draft-helper extension export does NOT belong
# here — this task only writes sim_lab\field_out\ leaderboard CSVs,
# which the export never reads. The 7am/8am/9am repo tasks + the
# Tuesday stats chain already run export_sleeper_extension_data.py.
$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$SimLab = 'E:\MyFantasyFootball\sim_lab'
$Log = Join-Path $SimLab 'field_scoring.log'
$CsvDir = 'E:\MyFantasyFootball\MyFantasyFootball Files\Best Ball Mania Files\BBM VII'

function Write-Log($msg) {
    Add-Content -Path $Log -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
}

Set-Content -Path $Log -Value '' -Encoding utf8
Write-Log '=== field scoring start ==='

$csv = Get-ChildItem -Path $CsvDir -Filter '*rd1*.csv' -ErrorAction SilentlyContinue |
       Sort-Object Length -Descending | Select-Object -First 1
if (-not $csv) {
    $csv = Get-ChildItem -Path $CsvDir -Filter '*.csv' -ErrorAction SilentlyContinue |
           Sort-Object Length -Descending | Select-Object -First 1
}
if (-not $csv) {
    Write-Log "no BBM VII field CSV in $CsvDir yet - skipping (drop the official rd1 file there when it releases)"
    exit 0
}

Set-Location $SimLab
$out = & python 'field_scores.py' $csv.FullName --season 2026 --weeks auto --user jackb933 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) { Write-Log "FIELD SCORING FAILED (exit $LASTEXITCODE)"; exit 1 }
Write-Log '=== done ==='
