# MFF automation alert (2026-10-14, after the 10-13 stuck-rebase incident that
# silently blocked every push for ~17 h).
#
#   powershell -NoProfile -File scripts\mff_alert.ps1 -AlertKey rebase-stuck -AlertMessage "..."
#   or dot-source and call Send-MffAlert -Key ... -Message ...
#
# Every alert is appended to E:\MyFantasyFootball\_alerts\alerts_log.txt and,
# unless the same -Key fired within -CooldownMin, shown as a Windows toast.
# Optional phone push: put an ntfy.sh topic name in
# E:\MyFantasyFootball\_alerts\ntfy_topic.txt (not set up by default).
param([string]$AlertKey = '', [string]$AlertMessage = '', [int]$AlertCooldownMin = 180)   # prefixed: this file is also dot-sourced

$script:AlertDir = 'E:\MyFantasyFootball\_alerts'

function Send-MffAlert {
    param([Parameter(Mandatory)][string]$Key, [Parameter(Mandatory)][string]$Message, [int]$CooldownMin = 180)
    if (-not (Test-Path $AlertDir)) { New-Item -ItemType Directory -Force -Path $AlertDir | Out-Null }
    $log = Join-Path $AlertDir 'alerts_log.txt'
    $stateFile = Join-Path $AlertDir 'alert_state.json'
    $now = Get-Date
    Add-Content -Path $log -Value ('[{0}] {1}: {2}' -f $now.ToString('yyyy-MM-dd HH:mm:ss'), $Key, $Message) -Encoding utf8

    # cooldown per key so a 30-min watchdog doesn't toast every run
    $state = @{}
    if (Test-Path $stateFile) {
        try { (Get-Content $stateFile -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $state[$_.Name] = $_.Value } } catch {}
    }
    if ($state.ContainsKey($Key)) {
        $last = [datetime]::Parse($state[$Key])
        if (($now - $last).TotalMinutes -lt $CooldownMin) { return }
    }
    $state[$Key] = $now.ToString('o')
    try { ($state | ConvertTo-Json) | Set-Content -Path $stateFile -Encoding utf8 } catch {}

    # Windows toast (works when the task runs in the logged-on session)
    try {
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $t = $xml.GetElementsByTagName('text')
        $t.Item(0).AppendChild($xml.CreateTextNode("MFF automation: $Key")) | Out-Null
        $t.Item(1).AppendChild($xml.CreateTextNode($Message)) | Out-Null
        $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
    } catch {
        Add-Content -Path $log -Value ('    (toast failed: {0})' -f $_.Exception.Message) -Encoding utf8
    }

    # optional phone push
    $topicFile = Join-Path $AlertDir 'ntfy_topic.txt'
    if (Test-Path $topicFile) {
        $topic = (Get-Content $topicFile -Raw).Trim()
        if ($topic) {
            try { Invoke-RestMethod -Method Post -Uri "https://ntfy.sh/$topic" -Body "${Key}: $Message" -Headers @{ Title = 'MFF automation' } -TimeoutSec 10 | Out-Null } catch {}
        }
    }
}

if ($AlertKey -and $AlertMessage) { Send-MffAlert -Key $AlertKey -Message $AlertMessage -CooldownMin $AlertCooldownMin }
