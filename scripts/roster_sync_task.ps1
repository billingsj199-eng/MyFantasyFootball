# Fast roster-only sync (Task Scheduler: "MFF Roster Sync").
#
# Jack 2026-11-10 (trade deadline day): trades and signings only reached the
# player cards through the once-a-day 8:00 consensus-ADP job, so a noon trade
# showed the old team until the next morning. This runs JUST the roster part:
#   scripts/update_rosters.py            Sleeper players dump -> d.js "t" teams
#                                        (bumps data/d.js?v= itself)
#   scripts/sync_active_team_history.py  carries the move into the 2026 end of
#                                        ACTIVE_TEAM_HISTORY (bumps its own ?v=)
# and commits + pushes only data/d.js, data/active_team_history.js and
# index.html, and only when a team actually changed. A run with no moves is one
# Sleeper GET and no git writes.
#
# Everything downstream that reads d.t follows on the next page load: card
# header / logo / colors, bye week, remaining schedule, depth-chart and team
# pages. The sim projections take the new team from Sleeper themselves on their
# own next export (10:00 / 20:15 + pre-kickoff runs).
#
# Guard rails are update_rosters.py's own: aborts on a short Sleeper payload or
# on more than -MaxChanges moves in one diff (default 25; a failed run changes
# nothing and alerts, so a real 26-move burst needs one manual run with a higher
# -MaxChanges).
#
#   -DryRun   report the diff, write nothing, touch no git state
#
# Log: scripts/roster_sync_log.txt (kept to the last 400 lines).

param([switch]$DryRun, [int]$MaxChanges = 25)

$ErrorActionPreference = 'Continue'
$Repo = Split-Path $PSScriptRoot -Parent   # the checkout this script lives in
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$Log = Join-Path $Repo 'scripts\roster_sync_log.txt'

function Write-Log($msg) {
    $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
    Add-Content -Path $Log -Value $line -Encoding utf8
}
function Write-Lines($prefix, $text) {
    foreach ($l in ("$text".Trim() -split "`r?`n")) { if ($l.Trim()) { Write-Log ($prefix + $l.TrimEnd()) } }
}

Set-Location $Repo
$env:PYTHONIOENCODING = 'utf-8'

if ($DryRun) {
    & $Python 'scripts\update_rosters.py' '--dry-run' '--max-changes' $MaxChanges
    exit $LASTEXITCODE
}

Write-Log '=== roster sync start ==='
. (Join-Path $PSScriptRoot 'repo_guard.ps1')
# Short wait: this job comes round again in minutes, so never queue behind a long one.
if (-not (Enter-RepoTurn -Log { param($m) Write-Log $m } -Job 'roster sync' -TimeoutMin 8)) { exit 0 }
if (Test-RepoBlocked -Log { param($m) Write-Log $m } -Job 'roster sync') { exit 0 }

# Refuse to run over uncommitted work on the files this job writes.
$Files = @('data/d.js', 'data/active_team_history.js', 'index.html')
$dirty = git status --porcelain -- @Files
if ($dirty) {
    Write-Log "SKIP: uncommitted changes present:`n$dirty"
    exit 0
}

$out = & $Python 'scripts\update_rosters.py' '--max-changes' $MaxChanges 2>&1 | Out-String
$rc = $LASTEXITCODE
# "  Davante Adams (WR): Los Angeles Rams -> New York Jets  [name]" -> names for the commit message
$names = @($out -split "`r?`n" | ForEach-Object { if ($_ -match '^\s{2}(.+?) \((?:QB|RB|WR|TE|K|FB)\): .+ -> .+\[') { $Matches[1] } })
# The "no Sleeper match" lines are the same handful every run - keep the log to what moved.
Write-Lines 'sync: ' (($out -split "`r?`n" | Where-Object { $_ -notmatch 'no Sleeper match|ambiguous Sleeper match' }) -join "`n")
if ($rc -ne 0) {
    Write-Log "ROSTER SYNC FAILED (exit $rc) - teams left as-is"
    Send-MffAlert -Key 'roster-sync-failed' -Message "Roster sync failed (exit $rc) - player-card teams are not updating. See scripts\roster_sync_log.txt."
    git checkout -- @Files 2>$null   # update_rosters verifies before it writes, so this is belt and braces
    exit 1
}

$moved = git status --porcelain -- data/d.js
if (-not $moved) {
    Write-Log 'rosters in sync - nothing to commit'
} else {
    # Team-by-year history follows d.js. Non-fatal: the next run retries it.
    $out = & $Python 'scripts\sync_active_team_history.py' '--write' 2>&1 | Out-String
    Write-Lines 'history: ' $out
    if ($LASTEXITCODE -ne 0) { Write-Log "team history sync FAILED (exit $LASTEXITCODE) - continuing with the d.js move" }

    $n = $names.Count
    $what = if ($n -gt 0 -and $n -le 6) { $names -join ', ' } elseif ($n -gt 6) { "$n players" } else { 'team changes' }
    git add -- @Files
    # pathspec commit: only these files, whatever else happens to be staged
    git commit -m ('Auto roster sync {0} ({1})' -f (Get-Date -Format 'yyyy-MM-dd HH:mm'), $what) -- @Files
    if ($LASTEXITCODE -ne 0) {
        Write-Log "COMMIT FAILED (exit $LASTEXITCODE) - nothing pushed"
        Send-MffAlert -Key 'commit-failed' -Message 'git commit failed for the roster sync - changes left uncommitted, site not updated.'
    } else {
        git push origin main
        if ($LASTEXITCODE -ne 0) {
            # main moved on (another job pushed): replay on top; a conflicted rebase is aborted + alerted
            $global:LASTEXITCODE = $(if (Invoke-SafePullPush -Log { param($m) Write-Log $m } -What 'roster sync') { 0 } else { 1 })
        }
        if ($LASTEXITCODE -eq 0) { Write-Log "pushed roster moves ($what)" } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
    }
}
Exit-RepoTurn

$lines = Get-Content $Log
if ($lines.Count -gt 400) { $lines | Select-Object -Last 400 | Set-Content -Path $Log -Encoding utf8 }
