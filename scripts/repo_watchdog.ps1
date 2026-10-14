# MFF repo watchdog (Task Scheduler "MFF Repo Watchdog", every 30 min).
# Added 2026-10-14 after the 10-13 stuck-rebase incident: nothing noticed for
# ~17 h that every automation push was failing. Read-only on the checkout
# (only `git fetch`); it never repairs anything, it alerts.
#
# Checks (each alert has its own key + 3 h cooldown, see mff_alert.ps1):
#   repo-unhealthy   rebase / merge in progress (older than 10 min), detached HEAD, not on main
#   unpushed         local main has commits not on origin, oldest > 45 min
#   conflict-markers committed <<<<<<< / >>>>>>> lines in index.html / app.js / sw.js
#   stale-sim-export live myfantasyfootball.co sim_proj_2026.json `updated` > 16 h old (Sep-Jan)
# Log: E:\MyFantasyFootball\_alerts\watchdog_log.txt (last ~500 lines)

$ErrorActionPreference = 'Continue'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
. (Join-Path $PSScriptRoot 'mff_alert.ps1')
$WLog = 'E:\MyFantasyFootball\_alerts\watchdog_log.txt'
if (-not (Test-Path (Split-Path $WLog))) { New-Item -ItemType Directory -Force -Path (Split-Path $WLog) | Out-Null }
function W($m) { Add-Content -Path $WLog -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) -Encoding utf8 }

Set-Location $Repo
$problems = @()

# 1. in-progress operation / branch state
$gitDir = Join-Path $Repo '.git'
foreach ($op in 'rebase-merge', 'rebase-apply', 'MERGE_HEAD', 'CHERRY_PICK_HEAD') {
    $p = Join-Path $gitDir $op
    if (Test-Path $p) {
        $age = ((Get-Date) - (Get-Item $p).LastWriteTime).TotalMinutes
        if ($age -gt 10) {
            $problems += "git $op in progress for $([int]$age) min"
            Send-MffAlert -Key 'repo-unhealthy' -Message "Main checkout stuck: git $op in progress for $([int]$age) min. Automations cannot publish."
        }
    }
}
$branch = (git symbolic-ref --short -q HEAD 2>$null)
if (-not $branch) {
    $problems += 'HEAD detached'
    Send-MffAlert -Key 'repo-unhealthy' -Message 'Main checkout HEAD is detached. Automations cannot publish.'
} elseif ($branch -ne 'main') {
    $problems += "on branch $branch"
    Send-MffAlert -Key 'repo-unhealthy' -Message "Main checkout is on branch '$branch', not main."
}

# 2. unpushed commits
git fetch -q origin main 2>$null
if ($LASTEXITCODE -eq 0) {
    $ahead = @(git rev-list --reverse 'origin/main..HEAD' 2>$null)
    if ($ahead.Count -gt 0) {
        $oldest = [datetime]::Parse((git log -1 --format=%cI $ahead[0]))
        $mins = [int]((Get-Date) - $oldest).TotalMinutes
        if ($mins -gt 45) {
            $problems += "$($ahead.Count) unpushed commits, oldest $mins min"
            Send-MffAlert -Key 'unpushed' -Message "$($ahead.Count) local commits not on origin (oldest $mins min) - pushes are failing, the site is stale."
        }
    }
} else { W 'fetch failed (offline?)' }

# 3. committed conflict markers in the site shell files
$hits = git grep -n -E '^(<<<<<<<|>>>>>>>)( |$)' HEAD -- index.html app.js sw.js 2>$null
if ($hits) {
    $problems += 'conflict markers committed'
    Send-MffAlert -Key 'conflict-markers' -Message ("Conflict markers committed at HEAD: " + (($hits | Select-Object -First 2) -join ' | '))
}

# 4. live sim export freshness (in-season only: Sep-Jan)
$m = (Get-Date).Month
if ($m -ge 9 -or $m -le 1) {
    try {
        $j = Invoke-RestMethod -Uri ('https://myfantasyfootball.co/data/sim_proj_2026.json?wd=' + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) -TimeoutSec 30
        $hrs = [math]::Round(((Get-Date).ToUniversalTime() - ([datetime]$j.updated).ToUniversalTime()).TotalHours, 1)
        if ($hrs -gt 16) {
            $problems += "live sim export $hrs h old"
            Send-MffAlert -Key 'stale-sim-export' -Message "Live sim projections are $hrs h old (updated $($j.updated))."
        }
    } catch { W ('live sim check failed: ' + $_.Exception.Message) }
}

W ($(if ($problems) { 'PROBLEMS: ' + ($problems -join '; ') } else { 'ok' }))
$lines = Get-Content $WLog
if ($lines.Count -gt 500) { $lines | Select-Object -Last 500 | Set-Content -Path $WLog -Encoding utf8 }
