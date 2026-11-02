# Weekly refresh of the private headshot archive (Task Scheduler: "MFF Headshot Archive Weekly").
#
#   python scripts\archive_headshots.py   -> E:\MyFantasyFootball\headshot_archive (outside the repo)
#
# Git-free: only READS the id tables in the main checkout, so it takes no repo turn and never
# commits. Unchanged faces come back 304, so a normal week is a ~15 s run. Alerts (toast +
# _alerts\alerts_log.txt) when ESPN drops a face we have archived, or when the run fails.
# Log: E:\MyFantasyFootball\_alerts\headshot_archive_log.txt (~300 lines)

$ErrorActionPreference = 'Continue'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Log = 'E:\MyFantasyFootball\_alerts\headshot_archive_log.txt'
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
if (-not (Test-Path $Python)) { $Python = 'python' }

function Write-Log($msg) {
    Add-Content -Path $Log -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg) -Encoding utf8
}

. (Join-Path $PSScriptRoot 'mff_alert.ps1')
Set-Location $Repo
Write-Log '=== headshot archive start ==='

$out = & $Python 'scripts\archive_headshots.py' 2>&1 | Out-String
$code = $LASTEXITCODE
$tail = ($out -split "`r?`n" | Where-Object { $_ -and $_ -notmatch '^\s+\d+/\d+$' } | Select-Object -Last 6) -join ' | '
Write-Log $tail

if ($code -ne 0) {
    Write-Log "RUN FAILED or had fetch errors (exit $code)"
    Send-MffAlert -Key 'headshot-archive-failed' -Message "Headshot archive run exit $code - see headshot_archive_log.txt"
}
$gone = [regex]::Match($out, 'newly gone this run: (\d+)(.*)')
if ($gone.Success -and [int]$gone.Groups[1].Value -gt 0) {
    Send-MffAlert -Key 'headshot-gone' -Message ('ESPN dropped {0} archived headshot(s){1} - copies kept in headshot_archive' -f $gone.Groups[1].Value, $gone.Groups[2].Value.TrimEnd())
}

$lines = Get-Content $Log
if ($lines.Count -gt 300) { $lines | Select-Object -Last 300 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
exit $code
