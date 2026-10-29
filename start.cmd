@echo off
cd /d "%~dp0"
if exist "FishStoryPlayer.exe" goto portable
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch_windows.ps1"
if not errorlevel 1 exit /b 0
pause
exit /b 1
:portable
"%~dp0FishStoryPlayer.exe"
exit /b %errorlevel%
