@echo off
REM ============================================================
REM Sim Lab daily refresh + deploy.
REM Task 'MFF Sim Lab Daily' 06:45 (was 09:45 until 2026-09-15, wake-to-run
REM on) - after nflverse's ~06:20 ET pbp publish so the TD-luck / zones /
REM pressure maps include Monday night; the 08:00 betting pull and the 10:00
REM export re-run refresh_data.py with the day's fresh lines/Clay. Pushes to
REM https://jb-simlab-2026.web.app
REM Log: E:\MyFantasyFootball\sim_lab\last_refresh.log
REM NOTE (2026-08-28): the draft-helper extension export does NOT
REM belong here - data flows repo -> sim_lab in this task, and the
REM export's only sim_lab inputs (engine.js / overrides.js) are
REM never written by refresh_data / pace pull. The 7am/8am/9am repo
REM tasks already run export_sleeper_extension_data.py.
REM ============================================================
setlocal
set LOG=E:\MyFantasyFootball\sim_lab\last_refresh.log

echo ===== Sim Lab refresh %date% %time% ===== > "%LOG%"

cd /d E:\MyFantasyFootball\sim_lab
python refresh_data.py >> "%LOG%" 2>&1
if errorlevel 1 (
  echo REFRESH FAILED ? skipping deploy >> "%LOG%"
  exit /b 1
)

python pull_pace_tracker.py >> "%LOG%" 2>&1
if errorlevel 1 echo PACE PULL FAILED - continuing >> "%LOG%"

REM NOTES sheet (2026-09-15): headless twin of the NOTES tab -> notes
otes_w<N>_half.txt
REM + notes
otes_latest.txt (deploys with the site: /notes/notes_latest.txt). Non-fatal.
set NODE=E:
ode
ode.exe
if not exist "%NODE%" set NODE=node
"%NODE%" export_notes.js >> "%LOG%" 2>&1
if errorlevel 1 echo NOTES EXPORT FAILED - continuing >> "%LOG%"

cd /d E:\MyFantasyFootball
call C:\Users\billi\AppData\Roaming\npm\firebase.cmd deploy --only hosting:simlab --project jackb933-website >> "%LOG%" 2>&1
if errorlevel 1 (
  echo DEPLOY FAILED >> "%LOG%"
  exit /b 1
)

echo ===== done %date% %time% ===== >> "%LOG%"
endlocal
