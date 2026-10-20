# Repo guard for the automations that commit to the shared main checkout
# (2026-10-14, after the 10-13 15:50 `pull --rebase` conflict left the checkout
# mid-rebase on a detached HEAD: every job kept committing on top, one commit
# carried conflict markers, and every push failed silently for ~17 h).
#
# Dot-source from a task script (after Set-Location to the repo):
#   . (Join-Path $PSScriptRoot 'repo_guard.ps1')
#   $bad = Get-RepoProblem; if ($bad) { ...; exit 0 }
#   Invoke-SafePullPush -Log { param($m) Write-Log $m } -What 'sim projections'
#
# The .git/hooks/pre-commit hook enforces the same rules for every committer.
#
# Repo turn (2026-10-20): the PC slept to 08:26, nine missed tasks all started at
# 08:32, their git calls collided, one died holding .git/index.lock, and every
# commit after it failed (three logs still said "committed + pushed"). Each job
# now takes the repo turn before its dirty-file check and keeps it through its
# push, so jobs run one at a time and never trip over each other's uncommitted
# files or ?v= bumps:
#   if (-not (Enter-RepoTurn -Log { param($m) Write-Log $m } -Job 'my job')) { exit 0 }
# The turn is an exclusive handle on _alerts\repo_turn.lock, so Windows releases
# it when the process exits, even on a crash. Child jobs (betting -> postgame,
# sim proj -> betting, Tuesday -> dynasty) inherit MFF_REPO_TURN and run inside
# the parent's turn. Exit-RepoTurn hands it back early before a long tail that
# never touches git.

. (Join-Path $PSScriptRoot 'mff_alert.ps1')

$script:RepoTurnLock = 'E:\MyFantasyFootball\_alerts\repo_turn.lock'
$script:RepoTurnRepo = Split-Path $PSScriptRoot -Parent

# Waits for the repo turn. $true = this job may touch git; $false = timed out (logged + alerted).
function Enter-RepoTurn {
    param([scriptblock]$Log = { param($m) Write-Host $m }, [string]$Job = 'job', [int]$TimeoutMin = 60)
    if ($global:MffRepoTurn) { return $true }
    if ($env:MFF_REPO_TURN) { & $Log "repo turn: running inside $env:MFF_REPO_TURN" | Out-Host; return $true }
    $ownerFile = "$RepoTurnLock.owner"
    $lockDir = Split-Path $RepoTurnLock -Parent
    if (-not (Test-Path $lockDir)) { New-Item -ItemType Directory -Force -Path $lockDir | Out-Null }   # else Open throws DirectoryNotFound (an IOException) and we'd wait forever
    $start = Get-Date
    $waitLogged = $false
    while ($true) {
        try {
            $fs = [System.IO.File]::Open($RepoTurnLock, 'OpenOrCreate', 'ReadWrite', 'None')
            break
        } catch [System.IO.IOException] {
            if (-not $waitLogged) {
                $owner = try { (Get-Content $ownerFile -Raw -ErrorAction Stop).Trim() } catch { 'unknown' }
                & $Log "repo turn: waiting - held by $owner" | Out-Host
                $waitLogged = $true
            }
            if (((Get-Date) - $start).TotalMinutes -ge $TimeoutMin) {
                & $Log "SKIP: no repo turn after $TimeoutMin min" | Out-Host
                Send-MffAlert -Key 'repo-turn-timeout' -Message "$Job waited $TimeoutMin min for the repo turn and skipped. Held by: $(try { (Get-Content $ownerFile -Raw).Trim() } catch { 'unknown' })"
                return $false
            }
            Start-Sleep -Seconds 10
        } catch {
            # lock infrastructure broken (permissions, missing drive): never block publishing on it
            & $Log "repo turn unavailable ($($_.Exception.Message)) - running without it" | Out-Host
            return $true
        }
    }
    $global:MffRepoTurn = $fs
    $env:MFF_REPO_TURN = "$Job (pid $PID)"
    try { Set-Content -Path $ownerFile -Value "$Job (pid $PID) since $(Get-Date -Format 'HH:mm:ss')" -Encoding utf8 } catch {}
    if ($waitLogged) { & $Log ("repo turn: got it after {0:N0}s" -f ((Get-Date) - $start).TotalSeconds) | Out-Host }
    Clear-StaleIndexLock -Log $Log
    return $true
}

function Exit-RepoTurn {
    if (-not $global:MffRepoTurn) { return }   # not the owner (nested job) - the parent releases
    try { Remove-Item "$RepoTurnLock.owner" -ErrorAction SilentlyContinue } catch {}
    $global:MffRepoTurn.Dispose()
    $global:MffRepoTurn = $null
    Remove-Item Env:\MFF_REPO_TURN -ErrorAction SilentlyContinue
}

# Called while holding the turn: an index.lock with no git process running is
# debris from a git that died, and blocks every commit until removed.
function Clear-StaleIndexLock {
    param([scriptblock]$Log = { param($m) Write-Host $m })
    $gitDir = (git -C $RepoTurnRepo rev-parse --absolute-git-dir 2>$null)
    if (-not $gitDir) { return }
    $lock = Join-Path $gitDir 'index.lock'
    if (-not (Test-Path $lock)) { return }
    $age = ((Get-Date) - (Get-Item $lock).LastWriteTime).TotalSeconds
    if ($age -lt 30 -or (Get-Process git -ErrorAction SilentlyContinue)) {
        & $Log ("repo turn: index.lock present ({0:N0}s old) but git is running or it is fresh - left alone" -f $age) | Out-Host
        return
    }
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
    & $Log ("repo turn: removed stale index.lock ({0:N0} min old, no git running)" -f ($age / 60)) | Out-Host
    Send-MffAlert -Key 'stale-index-lock' -Message ("Removed a stale .git/index.lock ({0:N0} min old) left by a git that died; commits resume." -f ($age / 60))
}

# Returns $null when the checkout is safe to commit on, else a short reason.
function Get-RepoProblem {
    $gitDir = (git rev-parse --git-dir 2>$null)
    if (-not $gitDir) { return 'not a git checkout' }
    foreach ($op in 'rebase-merge', 'rebase-apply', 'MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD') {
        if (Test-Path (Join-Path $gitDir $op)) { return "git $op in progress" }
    }
    $branch = (git symbolic-ref --short -q HEAD 2>$null)
    if (-not $branch) { return 'HEAD is detached' }
    if ($branch -ne 'main') { return "on branch '$branch', not main" }
    $unmerged = (git diff --name-only --diff-filter=U 2>$null)
    if ($unmerged) { return "unmerged files: $($unmerged -join ', ')" }
    return $null
}

# pull --rebase then push. A failed pull is aborted on the spot (it is this
# script's own seconds-old rebase), so the checkout returns to main with the
# commit kept locally, and an alert fires. Returns $true when pushed.
function Invoke-SafePullPush {
    param([scriptblock]$Log = { param($m) Write-Host $m }, [string]$What = 'data')
    # Every caller has just run git commit. Nothing ahead of origin/main means that
    # commit never landed (10-20: index.lock), and pushing "Everything up-to-date"
    # used to be logged as success.
    $ahead = [int](git rev-list --count 'origin/main..HEAD' 2>$null)
    if ($ahead -lt 1) {
        & $Log "COMMIT DID NOT LAND - nothing new to push ($What); see the git error above" | Out-Host
        Send-MffAlert -Key 'commit-failed' -Message "git commit failed for $What - changes left uncommitted, site not updated."
        return $false
    }
    git pull --rebase --autostash origin main | Out-Host   # Out-Host: keep git's stdout out of the return value
    if ($LASTEXITCODE -ne 0) {
        git rebase --abort 2>$null | Out-Host
        $after = Get-RepoProblem
        & $Log "PULL --REBASE FAILED - rebase aborted, commit kept local ($What); repo now: $(if ($after) { $after } else { 'ok on main' })" | Out-Host
        Send-MffAlert -Key 'pull-rebase-conflict' -Message "pull --rebase conflicted while pushing $What; aborted, commit is local. Resolve by hand (see E:\MyFantasyFootball\_alerts\alerts_log.txt)."
        return $false
    }
    git push origin main | Out-Host
    if ($LASTEXITCODE -ne 0) {
        & $Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local ($What)" | Out-Host
        Send-MffAlert -Key 'push-failed' -Message "git push failed for $What - commit is local, site not updated."
        return $false
    }
    return $true
}

# Pre-run gate: log + alert + $true when the job must not run.
function Test-RepoBlocked {
    param([scriptblock]$Log = { param($m) Write-Host $m }, [string]$Job = 'job')
    $bad = Get-RepoProblem
    if ($bad) {
        & $Log "SKIP: repo unhealthy - $bad" | Out-Host
        Send-MffAlert -Key 'repo-unhealthy' -Message "$Job skipped: $bad in the main checkout. Nothing will publish until it is fixed."
        return $true
    }
    return $false
}
