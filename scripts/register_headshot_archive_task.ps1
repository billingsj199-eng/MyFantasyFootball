# One-time: register Task Scheduler job "MFF Headshot Archive Weekly" (Wednesdays 04:30, a quiet
# slot clear of the Tuesday stats jobs and the morning git burst). Run as the logged-in user (billi):
#   powershell -NoProfile -ExecutionPolicy Bypass -File "E:\MyFantasyFootball\MyFantasyFootball Files\scripts\register_headshot_archive_task.ps1"
# Re-running updates the task in place (-Force).
$name = 'MFF Headshot Archive Weekly'
$script = 'E:\MyFantasyFootball\MyFantasyFootball Files\scripts\headshot_archive_weekly_task.ps1'
# The main checkout gets the script once this branch is merged and pulled.
if (-not (Test-Path $script)) { Write-Host "note: $script is not in the main checkout yet - it arrives with the merge of the headshot-archive branch" }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $script + '"')
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Wednesday -At '04:30'
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 60) -MultipleInstances IgnoreNew -RestartCount 1 -RestartInterval (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force `
    -Description 'Weekly refresh of the private ESPN headshot archive E:\MyFantasyFootball\headshot_archive (scripts/archive_headshots.py). Git-free. Log: E:\MyFantasyFootball\_alerts\headshot_archive_log.txt' | Out-Null
Get-ScheduledTask -TaskName $name | Select-Object TaskName, State | Format-List
(Get-ScheduledTask -TaskName $name).Triggers | Select-Object StartBoundary, DaysOfWeek | Format-List
