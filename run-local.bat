@echo off
rem Run the wallboard on this PC for testing. Optional demo mode: run-local live
cd /d "%~dp0.."
set DEMO=%1
set NIGHT=off
echo Starting on http://localhost:8080  (Ctrl+C to stop)
python app.py
