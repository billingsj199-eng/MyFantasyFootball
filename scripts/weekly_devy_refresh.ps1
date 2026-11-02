# Devy / 2027-class weekly refresh (Task Scheduler: "MFF Devy Weekly Refresh",
# weekly MONDAY 07:15 - after Saturday's college slate has settled on CFBD and
# PFF, after the 06:15 route-pct job, before the 07:45 K/DST + 8am/9am jobs).
#
# Steps (each non-fatal for the next; commit only what changed):
#   1. scripts/pull_draft_boards.py --add   consensus (NFL Mock Draft Database)
#        + PFF big boards -> draftProj for the NEXT draft class in
#        data/combine_data.js, adds any consensus/PFF top-100 skill player
#        missing from the site (devy entry). Exit 3 = consensus board down,
#        nothing changed.
#   2. scripts/pull_pff_ncaa.py              PFF Premium COLLEGE weekly facets
#        (passing/rushing/receiving/offense) from the official PFF Developer API ->
#        pbp_cache/pff/ncaa (git-ignored cache). Exit 2 = no key / key refused; the
#        refresh below then keeps the previous PFF fields.
#   3. scripts/refresh_devy_stats.py         CFBD box scores (current season +
#        prior-season backfill for new adds) + PFF per-game / season grades ->
#        data/college_stats_devy.js; ht/wt bio patches; scripts/devy_audit.json
#        (school mismatches are logged).
# The JM prospect model scores off COLLEGE_STATS + draftProj in the browser, so
# pushing these files is what moves the devy grades on the site. ?v= tags are
# bumped only when the data files change. Mirrors weekly_kdst_refresh.ps1.
#
# Log: scripts/devy_refresh_log.txt (kept to last ~300 lines).

$ErrorActionPreference = 'Continue'
$Repo = 'E:\MyFantasyFootball\MyFantasyFootball Files'
$Python = 'C:\Users\billi\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$Log = Join-Path $Repo 'scripts\devy_refresh_log.txt'

function Write-Log($msg) {
    $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
    Add-Content -Path $Log -Value $line -Encoding utf8
}

Set-Location $Repo
Write-Log '=== weekly devy refresh start ==='

# Commit + push exactly $paths (data files) plus ONLY their ?v= tags in index.html
# (scripts/stage_vbump.py stages HEAD's index.html with just those tags swapped), so
# another session's uncommitted index.html edits never block or ride along.
. (Join-Path $PSScriptRoot 'repo_guard.ps1')
# Repo turn (2026-10-20) only around each commit, not the whole run: a PFF login wait
# can hold this job for up to an hour, and its files never overlap the other jobs'
# (index.html goes through stage_vbump, never the working copy).
# Log + toast (2026-11-02: three Mondays 10-19..11-02 skipped on a dirty combine_data.js
# while Task Scheduler showed result 0 - a skip or failure must be loud, not just logged).
function Send-DevyAlert($key, $msg) {
    Write-Log $msg
    Send-MffAlert -Key ('devy-' + $key) -Message ('Devy/CFB refresh: ' + $msg)
}

function Commit-Push($paths, $msg) {
    if (-not (Enter-RepoTurn -Log { param($m) Write-Log $m } -Job 'devy refresh')) { Send-DevyAlert 'no-turn' "$msg left uncommitted (no repo turn)"; return }
    try {
        $chg = git status --porcelain -- @paths
        if (-not $chg) { Write-Log "$msg - no movement, nothing to commit"; return }
        git add -- @($paths | Where-Object { Test-Path $_ })
        $o = & $Python 'scripts\stage_vbump.py' @paths 2>&1 | Out-String
        Write-Log $o.Trim()
        git commit -m ('{0} {1}' -f $msg, (Get-Date -Format 'yyyy-MM-dd'))
        if ($LASTEXITCODE -ne 0) { Send-DevyAlert 'commit-failed' "COMMIT FAILED (exit $LASTEXITCODE) - $msg left uncommitted"; return }
        # Other jobs/cloud routines can land commits mid-morning; rebase so the push fast-forwards.
        $global:LASTEXITCODE = $(if (Invoke-SafePullPush -Log { param($m) Write-Log $m } -What 'devy refresh') { 0 } else { 1 })   # aborts + alerts a conflicted pull --rebase (2026-10-14)
        if ($LASTEXITCODE -eq 0) { Write-Log "pushed: $msg" } else { Send-DevyAlert 'push-failed' "PUSH FAILED (exit $LASTEXITCODE) - $msg commit is local" }
    } finally { Exit-RepoTurn }
}

# 1. draft boards -> draftProj (+ new 2027-class adds). Runs FIRST and commits on its
#    own every week (Jack 2026-10-10: consensus boards must run weekly) - a later step
#    failing, a PFF login wait hitting the 1h task limit, or another session's dirty
#    index.html can no longer lose or skip it (10-05: the 07:15 pull sat uncommitted).
# The Mock+ rounds 1-2 mock, signed-in big board and Official MDDB mock come from CSVs
# pulled by hand in Jack's Chrome (nflmdd_extract_chrome.js + save_nflmdd_csv.py);
# pull_draft_boards.py drops them after MOCK_CSV_MAX_AGE (10) days and silently falls back
# to the public round-1 / top-100 pages. Warn from day 7, alert loudly once expired.
$CsvMaxAge = 10
$expired = @(); $aging = @()
foreach ($c in 'mock_draft_2027', 'big_board_2027', 'official_mock_2027') {
    $p = Join-Path $Repo "Site Rankings\$c.csv"
    $pulled = if (Test-Path $p) { Import-Csv $p | ForEach-Object { $_.pulled } | Where-Object { $_ } | Sort-Object | Select-Object -Last 1 }
    if (-not $pulled) { $expired += "$c (missing)"; continue }
    $age = ((Get-Date).Date - [datetime]::ParseExact($pulled, 'yyyy-MM-dd', $null)).Days
    if ($age -gt $CsvMaxAge) { $expired += "$c (pulled $pulled)" }
    elseif ($age -ge 7) { $aging += "$c ($age days)" }
    else { Write-Log "$c.csv fresh (pulled $pulled, $age days)" }
}
if ($expired) { Send-DevyAlert 'csv-expired' ("NFLMDD CSVs EXPIRED: " + ($expired -join ', ') + " - draftProj fell back to the public round-1 / top-100 pages; re-pull them in Jack's Chrome") }
if ($aging) { Send-DevyAlert 'csv-aging' ("NFLMDD CSVs aging: " + ($aging -join ', ') + " - they stop counting after $CsvMaxAge days; re-pull them in Jack's Chrome this week") }

$BoardFiles = @('data/combine_data.js', 'data/draft_proj.js', 'scripts/draft_boards_2027.json')
$dirty = git status --porcelain -- @BoardFiles
if ($dirty) {
    Send-DevyAlert 'boards-skip' ("BOARDS SKIP: uncommitted changes in " + (($dirty | ForEach-Object { $_.Substring(3) }) -join ', ') + ' - commit or revert them, then rerun')
} else {
    $out = & $Python 'scripts\pull_draft_boards.py' '--add' 2>&1 | Out-String
    Write-Log ('draft boards: ' + $out.Trim())
    if ($LASTEXITCODE -eq 3) { Write-Log 'consensus board unavailable - draftProj unchanged this week' }
    elseif ($LASTEXITCODE -ne 0) { Send-DevyAlert 'boards-failed' "draft boards FAILED (exit $LASTEXITCODE) - continuing" }
    Commit-Push $BoardFiles 'Auto draft boards (NFLMDD mock + big board -> 2027 draftProj)'
}

# Refuse to run the rest on dirty target files so a half-finished manual session isn't
# clobbered (index.html is NOT checked - Commit-Push stages only our ?v= tags in it).
$Files = @('data/college_stats_devy.js', 'data/combine_data.js', 'scripts/devy_refresh_cache.json',
           'scripts/devy_audit.json', 'scripts/draft_boards_2027.json', 'data/devy_headshots.js',
           'scripts/devy_headshots_cache.json', 'data/projected_testing.js', 'data/draft_proj.js', 'scripts/projected_testing_hits.json',
           'data/legend_birth_years.js', 'data/_bundle_lookups.js', 'data/_bundle_bbm.js', 'scripts/devy_birthdays_cache.json')
$dirty = git status --porcelain -- @Files
if ($dirty) {
    Send-DevyAlert 'skip' ("SKIPPED - no CFB stats this week: uncommitted changes in " + (($dirty | ForEach-Object { $_.Substring(3) }) -join ', ') + ' - commit or revert them, then rerun')
    exit 2   # nonzero so Task Scheduler's Last Run Result shows the skip (was exit 0)
}

# 2. PFF college weekly facets (needs the PFF Pro API key in pbp_cache/pff/api_key.txt)
$out = & $Python 'scripts\pull_pff_ncaa.py' 2>&1 | Out-String
Write-Log ('pff ncaa: ' + $out.Trim())
if ($LASTEXITCODE -eq 2) { Send-DevyAlert 'pff-key' 'PFF API KEY MISSING OR REFUSED - college PFF grades stay at last pull until the key in pbp_cache/pff/api_key.txt works' }
elseif ($LASTEXITCODE -ne 0) { Write-Log "pff ncaa FAILED (exit $LASTEXITCODE) - continuing with cached files" }

# 2b. Published projected forties (Stick to the Model board; Jack's DraftBuzz rows in the CSV win)
$out = & $Python 'scripts\pull_projected_testing.py' 2>&1 | Out-String
Write-Log ('projected testing pull: ' + $out.Trim())
$out = & $Python 'scripts\apply_projected_testing.py' 2>&1 | Out-String
Write-Log ('projected testing apply: ' + $out.Trim())

# 3. CFBD stats + PFF enrichment -> college_stats_devy.js
$out = & $Python 'scripts\refresh_devy_stats.py' 2>&1 | Out-String
Write-Log $out
if ($LASTEXITCODE -ne 0) {
    Send-DevyAlert 'refresh-failed' "REFRESH FAILED (exit $LASTEXITCODE) - nothing committed"
    exit 1
}

# 4. ESPN college headshot ids + team logo ids for the devy board (new adds / transfers)
$out = & $Python 'scripts\pull_devy_headshots.py' 2>&1 | Out-String
Write-Log ('devy headshots: ' + $out.Trim())
if ($LASTEXITCODE -ne 0) { Write-Log "devy headshots FAILED (exit $LASTEXITCODE) - continuing" }

# 5. Birth dates for devy prospects still missing one (Wikidata; rebuilds data/_bundle_lookups.js)
$out = & $Python 'scripts\pull_devy_birthdays.py' 2>&1 | Out-String
Write-Log ('devy birthdays: ' + $out.Trim())
if ($LASTEXITCODE -ne 0) { Write-Log "devy birthdays FAILED (exit $LASTEXITCODE) - continuing" }

# 6. Birth dates for drafted / signed players from NFL data (nflverse players file);
#    devy players are never touched by this step. Rebuilds data/_bundle_lookups.js on change.
$out = & $Python 'scripts\sync_nfl_birthdates.py' 2>&1 | Out-String
Write-Log ('nfl birthdates: ' + ($out.Trim() -split "`n" | Select-Object -Last 3 | Out-String).Trim())
if ($LASTEXITCODE -ne 0) { Write-Log "nfl birthdates FAILED (exit $LASTEXITCODE) - continuing" }

# Stage only paths that exist (Commit-Push filters): apply_projected_testing.py writes
# projected_testing_hits.json only once a projected time has a real result to grade, and one
# missing path makes git add stage nothing (2026-10-05: the whole refresh sat uncommitted).
Commit-Push $Files 'Auto devy refresh (college_stats_devy.js + headshots + birthdays + ?v= bump)'

# Trim log to last 300 lines.
$lines = Get-Content $Log
if ($lines.Count -gt 300) { $lines | Select-Object -Last 300 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
