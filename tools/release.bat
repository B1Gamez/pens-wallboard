@echo off
rem Run the checks, then send "dev" to "main". The wall display picks up main
rem within 5 minutes. Usage: release "what changed"
cd /d "%~dp0.."
for /f %%b in ('git branch --show-current') do set BRANCH=%%b
if not "%BRANCH%"=="dev" (
    echo You're on "%BRANCH%", not "dev". Switch with: git checkout dev
    exit /b 1
)
python tools\check.py
if errorlevel 1 (
    echo.
    echo Checks failed. Nothing was released.
    exit /b 1
)
git add -A
git commit -m "%~1" || echo Nothing new to commit.
git push origin dev || exit /b 1
git checkout main || exit /b 1
git pull --ff-only origin main
git merge --ff-only dev || (
    echo main has changes dev doesn't. Run: git checkout dev ^&^& git merge main
    git checkout dev
    exit /b 1
)
git push origin main
git checkout dev
echo.
if defined WALLBOARD_HOST (
    echo Released. Telling the wall display to update now...
    curl -s -X POST http://%WALLBOARD_HOST%/api/update
    echo.
) else (
    echo Released. The wall display will update within 5 minutes.
    echo Tip: run "setx WALLBOARD_HOST 192.168.x.x:8080" once to make it update right away.
)
