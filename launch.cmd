@echo off
setlocal

set "ROOT=%~dp0"
set "WT_EXE=wt"

where %WT_EXE% >nul 2>nul
if not errorlevel 1 (
  %WT_EXE% ^
    new-tab --title "pomo_debrief" cmd /k "cd /d ""%ROOT%"" && python ""%ROOT%pomo_debrief.py""" ^
    ; new-tab --title "codex_auto_ping" cmd /k "cd /d ""%ROOT%"" && python -u ""%ROOT%codex_auto_ping.py"""
  exit /b %errorlevel%
)

start "pomo_debrief" cmd /k "cd /d ""%ROOT%"" && python ""%ROOT%pomo_debrief.py"""
start "codex_auto_ping" cmd /k "cd /d ""%ROOT%"" && python -u ""%ROOT%codex_auto_ping.py"""

endlocal
