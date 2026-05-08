@echo off
setlocal

set "ROOT=%~dp0"
set "WT_EXE=wt"
set "PWSH_EXE=pwsh"

where %WT_EXE% >nul 2>nul
if not errorlevel 1 (
  %WT_EXE% ^
    new-tab --title "pomo_debrief" %PWSH_EXE% -NoExit -Command "Set-Location -LiteralPath '%ROOT%'; python '%ROOT%pomo_debrief.py'" ^
    ; new-tab --title "codex_auto_ping" %PWSH_EXE% -NoExit -Command "Set-Location -LiteralPath '%ROOT%'; python -u '%ROOT%codex_auto_ping.py'"
  exit /b %errorlevel%
)

start "pomo_debrief" %PWSH_EXE% -NoExit -Command "Set-Location -LiteralPath '%ROOT%'; python '%ROOT%pomo_debrief.py'"
start "codex_auto_ping" %PWSH_EXE% -NoExit -Command "Set-Location -LiteralPath '%ROOT%'; python -u '%ROOT%codex_auto_ping.py'"

endlocal
