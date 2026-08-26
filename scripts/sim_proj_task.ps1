# Sim Lab weekly-projection export (Task Scheduler: "MFF Sim Proj Export").
#
# Refreshes sim_lab's data mirror from the repo, runs the headless Sim Lab
# exporter (sim_lab/export_site_proj.js — all 18 weeks of per-player
# projections + boom/bust % from 1,000 Monte Carlo draws), and commits
# data/sim_proj_2026.js(.json) when they changed. Feeds the player-card
# LOGS tab 2026 PROJ/BOOM/BUST columns; NO simulation runs on the site.
#
# Schedule (one task, multiple triggers — all times local/ET):
#   daily 09:40 (after the 9am consensus-ADP job refreshes the inputs)
#   plus ~30 min before each in-season kickoff slot:
#   Thu 19:40 | Sun 09:00, 12:30, 15:35, 19:50 | Mon 18:40, 19:45
# Rows for games that already kicked off are FROZEN by the exporter itself
# (per-team kickoff times from ESPN), so extra runs never rewrite them.
#
# Log: scripts/sim_proj_log.txt (kept to last ~400 lines).

$ErrorActionPreference = 'Continue'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$SimLab = 'E:\MyFantasyFootball\sim_lab'
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$Node = 'E:\node\node.exe'
$Log = Join-Path $Repo 'scripts\sim_proj_log.txt'

function Write-Log($msg) {
    $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
    Add-Content -Path $Log -Value $line -Encoding utf8
}

Set-Location $Repo
Write-Log '=== sim proj export start ==='

# Refuse to run over uncommitted work on the target files.
$Files = @('data/sim_proj_2026.js', 'data/sim_proj_2026.json', 'index.html')
$dirty = git status --porcelain -- @Files
if ($dirty) {
    Write-Log "SKIP: uncommitted changes present:`n$dirty"
    exit 0
}

# 1. Refresh sim_lab's data mirror from the repo (Clay, sigma, betting lines,
#    Sleeper meta w/ injury designations, snaps).
$out = & $Python (Join-Path $SimLab 'refresh_data.py') 2>&1 | Out-String
Write-Log ("refresh_data: " + $out.Trim().Split("`n")[-1])
if ($LASTEXITCODE -ne 0) { Write-Log "REFRESH FAILED (exit $LASTEXITCODE) - aborting"; exit 1 }

# 2. Headless export into the repo data folder.
$out = & $Node (Join-Path $SimLab 'export_site_proj.js') --repo $Repo 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) { Write-Log "EXPORT FAILED (exit $LASTEXITCODE) - nothing committed"; exit 1 }

$changed = git status --porcelain -- @Files
if (-not $changed) {
    Write-Log 'projections unchanged - nothing to commit'
} else {
    # Bump the sim_proj ?v= tag (hour-stamped: game-day runs commit several
    # times per day). Read the CURRENT value from disk - never assume.
    $stamp = Get-Date -Format 'yyyy-MM-dd-HH'
    $idx = Join-Path $Repo 'index.html'
    $html = [System.IO.File]::ReadAllText($idx)
    $html2 = $html -replace 'sim_proj_2026\.js\?v=[\w.-]+', ('sim_proj_2026.js?v=' + $stamp)
    if ($html2 -ne $html) { [System.IO.File]::WriteAllText($idx, $html2) }

    git add data/sim_proj_2026.js data/sim_proj_2026.json index.html
    git commit -m ('Sim proj auto-export {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm'))
    git pull --rebase --autostash origin main
    git push origin main
    if ($LASTEXITCODE -eq 0) { Write-Log 'pushed updated sim projections' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}

$lines = Get-Content $Log
if ($lines.Count -gt 400) { $lines | Select-Object -Last 400 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
