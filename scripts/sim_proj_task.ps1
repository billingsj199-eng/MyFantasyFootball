# Sim Lab weekly-projection export (Task Scheduler: "MFF Sim Proj Export").
#
# Refreshes sim_lab's data mirror from the repo, runs the headless Sim Lab
# exporter (sim_lab/export_site_proj.js — all 18 weeks of per-player
# projections + boom/bust % from 1,000 Monte Carlo draws), and commits
# data/sim_proj_2026.js(.json) when they changed. Feeds the player-card
# LOGS tab 2026 PROJ/BOOM/BUST columns; NO simulation runs on the site.
#
# Schedule (one task, multiple triggers — all times local/ET):
#   daily 10:00 (after the 9am consensus-ADP job + 9:45 Sim Lab refresh)
#   daily 20:15 (added 2026-09-09: after the day's NFL practice reports post,
#     ~4-7pm ET, west-coast teams last — so Wed/Thu/Fri game statuses reach
#     the site the same evening instead of next morning; IgnoreNew keeps it
#     clear of the Thu/Sun/Mon ~7:45 pre-kickoff runs)
#   plus ~30 min before each in-season kickoff slot:
#   Thu 19:40 | Sun 09:00, 12:30, 15:35, 19:50 | Mon 18:40, 19:45
#   Sun 07:00 (added 2026-09-13, Jack: early Sunday lines + sims before the
#     8:00/8:15 line pulls; the task is WakeToRun since the same day because
#     the PC sleeps overnight and a missed trigger only fires on wake)
# Rows for games that already kicked off are FROZEN by the exporter itself
# (per-team kickoff times from ESPN), so extra runs never rewrite them.
#
# EVERY run pulls its own fresh inputs first (Jack's spec 2026-08-26): the
# sportsbook lines (daily_betting_pull.ps1 — commits on movement itself) and
# the Sleeper injury report (pull_injuries.py, nested in that same script),
# so the pre-kickoff runs price the latest lines + actives/inactives.
# Sleeper injury DESIGNATIONS for the sim itself also arrive fresh via
# refresh_data.py (it re-pulls sleeper_meta live from the Sleeper API).
# Mon/Tue bring the big projection swings (new weekly stats + snaps land
# Tuesday); line moves later in the week nudge the numbers slightly
# (Vegas elasticity 0.5 in the engine).
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
$Files = @('data/sim_proj_2026.js', 'data/sim_proj_2026.json', 'data/injury_updates.js', 'data/weather_2026.js', 'index.html',
           'data/practice_2026.js', 'data/depth_charts_2026.js', 'data/matchup_edges_2026.js', 'data/proj_why_2026.json')  # the .json twins are gitignored (local-only, like weather_2026.json)
$dirty = git status --porcelain -- @Files
if ($dirty) {
    Write-Log "SKIP: uncommitted changes present:`n$dirty"
    exit 0
}

# 0a. Fresh sportsbook lines (quiet no-op when nothing moved; commits its own
#     files). The Sun 9:00/15:35/19:50 runs have no other pregame line pull.
#     NOTE: this nested script also re-exports the draft-helper players.json
#     (wired 2026-08-28), so every sim-proj run refreshes the extensions too —
#     do NOT add a second export step here; nothing produced below feeds it.
$out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Repo 'scripts\daily_betting_pull.ps1') 2>&1 | Out-String
Write-Log ("betting pull: exit " + $LASTEXITCODE)

# 0b. Injury report: since 2026-09-13 the nested betting pull above pulls
#     pull_injuries.py itself (and commits data/injury_updates.js + its ?v=),
#     so it is no longer repeated here. The injury_updates entries in $Files
#     and the ?v= bump below stay as a harmless safety net.

# 0b2/0c. Depth charts + weather: since 2026-09-13 the nested betting pull
#     above pulls pull_depth_charts.py and pull_weather.py itself (and
#     commits them, bumping weather's ?v=), like injuries + practice. The
#     $Files entries and the ?v= bumps below stay as a harmless safety net.

# 1. Refresh sim_lab's data mirror from the repo (Clay, sigma, betting lines,
#    Sleeper meta w/ injury designations, snaps).
$out = & $Python (Join-Path $SimLab 'refresh_data.py') 2>&1 | Out-String
Write-Log ("refresh_data: " + $out.Trim().Split("`n")[-1])
if ($LASTEXITCODE -ne 0) { Write-Log "REFRESH FAILED (exit $LASTEXITCODE) - aborting"; exit 1 }

# 2. Headless export into the repo data folder. The exporter also AUTO-LOCKS
#    Sim Lab tracking snapshots for games kicking off within ~75 min
#    (sim_lab/data/snapshots/*.json); when one changed, redeploy Sim Lab
#    hosting so the TRACKING tab picks the lock up (step 2b).
$SnapDir = Join-Path $SimLab 'data\snapshots'
function Get-SnapSig {
    $files = Get-ChildItem -Path $SnapDir -Filter '*.json' -ErrorAction SilentlyContinue
    if (-not $files) { return '' }
    return (($files | Get-FileHash -Algorithm MD5 | ForEach-Object { $_.Hash }) -join ',')
}
$snapBefore = Get-SnapSig
$out = & $Node (Join-Path $SimLab 'export_site_proj.js') --repo $Repo 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) { Write-Log "EXPORT FAILED (exit $LASTEXITCODE) - nothing committed"; exit 1 }

# 2a. Start/Sit MATCHUP EDGES + player-card WHY (2026-09-16): headless Sim Lab NOTES -> data/matchup_edges_2026.js
#     and data/proj_why_2026.json.
#     Needs the sim_lab page (scheme / zones / defense availability), so it runs through export_notes.js
#     (Playwright); non-fatal - a failure just leaves the previous board up.
$out = & $Node (Join-Path $SimLab 'export_notes.js') --scoring half --repo $Repo 2>&1 | Out-String
Write-Log ("matchup edges: " + (($out -split "`n" | Where-Object { $_ -match 'matchup|failed' } | Select-Object -First 2) -join ' | '))

# 2b. Sim Lab deploy when a per-game lock landed (hosting only — no data
#     refresh; refresh_data.py already ran in step 1 for this same export).
if ((Get-SnapSig) -ne $snapBefore) {
    Write-Log 'auto-lock snapshot changed - deploying Sim Lab hosting'
    Push-Location 'E:\MyFantasyFootball'
    try {
        $out = & 'C:\Users\billi\AppData\Roaming\npm\firebase.cmd' deploy --only hosting:simlab --project jackb933-website 2>&1 | Out-String
        Write-Log ("simlab deploy: " + (($out -split "`n" | Where-Object { $_ -match 'Deploy complete|Error|error' } | Select-Object -First 2) -join ' | '))
    } catch { Write-Log ("simlab deploy FAILED: " + $_.Exception.Message) }
    finally { Pop-Location }
}

$changed = git status --porcelain -- @Files
if (-not $changed) {
    Write-Log 'projections unchanged - nothing to commit'
} else {
    # Bump ?v= tags for the data files this run changed (minute-stamped:
    # game-day runs commit several times per day). Read the CURRENT html
    # from disk - never assume.
    $stamp = Get-Date -Format 'yyyy-MM-dd-HHmm'   # minute-stamped: two runs in one hour must still bust the cache
    $idx = Join-Path $Repo 'index.html'
    $html = [System.IO.File]::ReadAllText($idx)
    $html2 = $html
    if ($changed -match 'sim_proj_2026') {
        $html2 = $html2 -replace 'sim_proj_2026\.js\?v=[\w.-]+', ('sim_proj_2026.js?v=' + $stamp)
    }
    if ($changed -match 'injury_updates') {
        $html2 = $html2 -replace 'injury_updates\.js\?v=[\w.-]+', ('injury_updates.js?v=' + $stamp)
    }
    if ($changed -match 'matchup_edges_2026') {
        $html2 = $html2 -replace 'matchup_edges_2026\.js\?v=[\w.-]+', ('matchup_edges_2026.js?v=' + $stamp)
    }
    if ($changed -match 'weather_2026') {
        $html2 = $html2 -replace 'weather_2026\.js\?v=[\w.-]+', ('weather_2026.js?v=' + $stamp)
    }
    if ($html2 -ne $html) { [System.IO.File]::WriteAllText($idx, $html2) }

    git add data/sim_proj_2026.js data/sim_proj_2026.json data/injury_updates.js data/weather_2026.js index.html data/practice_2026.js data/depth_charts_2026.js data/matchup_edges_2026.js data/proj_why_2026.json   # proj_why: lazy-loaded with ?d= (no ?v= bump); tracked despite the local data/*.json exclude
    git commit -m ('Sim proj auto-export {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm'))
    git pull --rebase --autostash origin main
    git push origin main
    if ($LASTEXITCODE -eq 0) { Write-Log 'pushed updated sim projections' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}

$lines = Get-Content $Log
if ($lines.Count -gt 400) { $lines | Select-Object -Last 400 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
