# Live projection tracker (cloud)

Grades the helpers' in-game LIVE projections against finals on real games,
from GitHub Actions (`.github/workflows/live-tracker.yml`) at every NFL
kickoff window — no home machine needed.

- `live_tracker.py --all` — every game in progress or kicking off within 2h;
  claims games in the results branch so overlapping windows never double-track.
- Inputs: site `data/sim_proj_2026.json` (Sim Lab week row + `liveModel`),
  Sleeper `/v1/stats/nfl/regular/<season>/<week>` (scored so far),
  ESPN public scoreboard (clock + score). `live_model.json` here is the
  fallback coefficient table (snapshot of `sim_lab/data/live_model.json`).
- Results: branch **`live-tracker-logs`**, `data/live_track_<season>_w<week>_<label>.csv`
  (one row per player per minute) + `_summary.json` (|live − final| by quarter and
  per player, fitted vs v1 heuristic vs naive).
- Re-grade a week: `python live_tracker.py --grade "data/live_track_2026_w1_*.csv"`
  from a checkout of the logs branch.
- Manual run: Actions → "Live projection tracker" → Run workflow (optional teams).

Machine-local twin: `E:\MyFantasyFootball\sim_lab\live_tracker.py` (Task Scheduler
"MFF Live Tracker", wake-to-run).
