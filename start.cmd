@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python -m app.server %*
) else (
  py -3 -m app.server %*
)
if errorlevel 1 pause
