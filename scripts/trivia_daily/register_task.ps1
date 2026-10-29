# One-time: register Task Scheduler job "MFF Trivia Daily" (19:30 ET daily).
# Run from an elevated-or-not PowerShell as the logged-in user (billi):
#   powershell -NoProfile -ExecutionPolicy Bypass -File "E:\MyFantasyFootball\MyFantasyFootball Files\scripts\trivia_daily\register_task.ps1"
# Re-running updates the task in place (-Force). Pass -Disabled to register it off (allowed
# before the branch is merged); enable later with: Enable-ScheduledTask -TaskName 'MFF Trivia Daily'
param([switch]$Disabled)

$name = 'MFF Trivia Daily'
$script = 'E:\MyFantasyFootball\MyFantasyFootball Files\scripts\trivia_daily_task.ps1'
if (-not (Test-Path $script)) {
    if (-not $Disabled) { Write-Host "missing $script (merge the trivia-news-daily branch first, or register with -Disabled now and Enable-ScheduledTask after the merge)"; exit 1 }
    Write-Host "note: $script is not on main yet - registering DISABLED; run Enable-ScheduledTask -TaskName '$name' after the merge"
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $script + '"')
$trigger = New-ScheduledTaskTrigger -Daily -At '19:30'
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew -RestartCount 1 -RestartInterval (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force `
    -Description 'News-driven Daily Trivia board for tomorrow (scripts/trivia_daily/run.js lock via lockTriviaDaily Cloud Function). Log: E:\MyFantasyFootball\_alerts\trivia_daily_log.txt' | Out-Null
if ($Disabled) { Disable-ScheduledTask -TaskName $name | Out-Null }
Get-ScheduledTask -TaskName $name | Select-Object TaskName, State | Format-List
(Get-ScheduledTask -TaskName $name).Triggers | Select-Object StartBoundary, DaysInterval | Format-List
