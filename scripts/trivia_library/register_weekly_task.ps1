# One-time: register Task Scheduler job "MFF Trivia Weekly" (Tuesdays 07:30, after the MNF
# postgame import and MFF Weekly Stats Tuesday). Run as the logged-in user (billi):
#   powershell -NoProfile -ExecutionPolicy Bypass -File "E:\MyFantasyFootball\MyFantasyFootball Files\scripts\trivia_library\register_weekly_task.ps1"
# Re-running updates the task in place (-Force).
$name = 'MFF Trivia Weekly'
$script = 'E:\MyFantasyFootball\MyFantasyFootball Files\scripts\trivia_library_weekly_task.ps1'
# The main checkout gets the script with the next job's pull (the overnight postgame run).
if (-not (Test-Path $script)) { Write-Host "note: $script is not in the main checkout yet - it arrives with the next pull of main" }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $script + '"')
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday -At '07:30'
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew -RestartCount 1 -RestartInterval (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force `
    -Description 'Weekly refresh of the Daily Trivia library boards that reach the current season (scripts/trivia_library/refresh_live.js). Log: E:\MyFantasyFootball\_alerts\trivia_weekly_log.txt' | Out-Null
Get-ScheduledTask -TaskName $name | Select-Object TaskName, State | Format-List
(Get-ScheduledTask -TaskName $name).Triggers | Select-Object StartBoundary, DaysOfWeek | Format-List
