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

. (Join-Path $PSScriptRoot 'mff_alert.ps1')

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
