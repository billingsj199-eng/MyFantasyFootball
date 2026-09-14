@echo off
rem Live-projection tracker launcher (Task Scheduler "MFF Live Tracker").
rem   live_tracker_run.cmd            -> --all: every game in progress or kicking off within 2h
rem                                      of now (exits at once when there is none); games are
rem                                      claimed in data\live_claims.json so overlapping windows
rem                                      (Sun 12:55 / 16:00 / 20:05) never double-track a game.
rem   live_tracker_run.cmd NE,SEA     -> explicit teams
rem Output: sim_lab\data\live_track_<season>_w<week>_<label>.csv + _summary.json; console in
rem         data\live_track_run_<date>_<time>.log
cd /d E:\MyFantasyFootball\sim_lab
set PYTHONIOENCODING=utf-8
set STAMP=%DATE:~-4%%DATE:~4,2%%DATE:~7,2%_%TIME:~0,2%%TIME:~3,2%
set STAMP=%STAMP: =0%
if "%1"=="" (
  C:\Users\billi\AppData\Local\Programs\Python\Python313\python.exe live_tracker.py --all > data\live_track_run_%STAMP%.log 2>&1
) else (
  C:\Users\billi\AppData\Local\Programs\Python\Python313\python.exe live_tracker.py --teams %1 > data\live_track_run_%STAMP%.log 2>&1
)
