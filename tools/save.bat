@echo off
rem Save your work to the "dev" branch on GitHub. The wall display ignores dev.
rem Usage: save "what you changed"
cd /d "%~dp0.."
for /f %%b in ('git branch --show-current') do set BRANCH=%%b
if not "%BRANCH%"=="dev" (
    echo You're on "%BRANCH%", not "dev". Switch with: git checkout dev
    exit /b 1
)
git add -A
git commit -m "%~1" || echo Nothing new to commit.
git push origin dev
