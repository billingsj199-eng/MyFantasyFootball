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

# Refuse to run on dirty target files so a half-finished manual session isn't clobbered.
$Files = @('data/college_stats_devy.js', 'data/combine_data.js', 'scripts/devy_refresh_cache.json',
           'scripts/devy_audit.json', 'scripts/draft_boards_2027.json', 'data/devy_headshots.js',
           'scripts/devy_headshots_cache.json', 'data/projected_testing.js', 'data/draft_proj.js', 'scripts/projected_testing_hits.json',
           'data/legend_birth_years.js', 'data/_bundle_lookups.js', 'data/_bundle_bbm.js', 'scripts/devy_birthdays_cache.json', 'index.html')
$dirty = git status --porcelain -- @Files
if ($dirty) {
    Write-Log "SKIP: uncommitted changes present:`n$dirty"
    exit 0
}

# 1. draft boards -> draftProj (+ new 2027-class adds)
$out = & $Python 'scripts\pull_draft_boards.py' '--add' 2>&1 | Out-String
Write-Log ('draft boards: ' + $out.Trim())
if ($LASTEXITCODE -eq 3) { Write-Log 'consensus board unavailable - draftProj unchanged this week' }
elseif ($LASTEXITCODE -ne 0) { Write-Log "draft boards FAILED (exit $LASTEXITCODE) - continuing" }

# 2. PFF college weekly facets (needs the PFF Pro API key in pbp_cache/pff/api_key.txt)
$out = & $Python 'scripts\pull_pff_ncaa.py' 2>&1 | Out-String
Write-Log ('pff ncaa: ' + $out.Trim())
if ($LASTEXITCODE -eq 2) { Write-Log 'PFF API KEY MISSING OR REFUSED - college PFF grades stay at last pull until the key in pbp_cache/pff/api_key.txt works' }
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
    Write-Log "REFRESH FAILED (exit $LASTEXITCODE) - nothing committed"
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

$changed = git status --porcelain -- @Files
if (-not $changed) {
    Write-Log 'no devy data movement - nothing to commit'
} else {
    # Stage only paths that exist: apply_projected_testing.py writes projected_testing_hits.json
    # only once a projected time has a real result to grade, and one missing path makes git add
    # stage nothing (2026-10-05: the whole refresh sat uncommitted and blocked the sim export).
    git add -- @($Files | Where-Object { Test-Path $_ })
    git commit -m ('Auto devy refresh {0} (college_stats_devy.js + 2027 draftProj + ?v= bump)' -f (Get-Date -Format 'yyyy-MM-dd'))
    if ($LASTEXITCODE -ne 0) { Write-Log "COMMIT FAILED (exit $LASTEXITCODE) - devy files left uncommitted" }
    # Other jobs/cloud routines can land commits mid-morning; rebase so the push fast-forwards.
    git pull --rebase --autostash origin main
    git push origin main
    if ($LASTEXITCODE -eq 0) { Write-Log 'pushed devy refresh' } else { Write-Log "PUSH FAILED (exit $LASTEXITCODE) - commit is local" }
}

# Trim log to last 300 lines.
$lines = Get-Content $Log
if ($lines.Count -gt 300) { $lines | Select-Object -Last 300 | Set-Content -Path $Log -Encoding utf8 }
Write-Log '=== done ==='
