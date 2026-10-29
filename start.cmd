@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Creating a local Python environment...
  python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -c "import fish_story, requests, mcp" >nul 2>nul
if errorlevel 1 (
  echo Installing Fish Story Player dependencies...
  ".venv\Scripts\python.exe" -m pip install -e .
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m fish_story.cli serve --open
if errorlevel 1 goto failed
exit /b 0
:failed
echo Startup failed. See README.md for Python installation and manual commands.
pause
exit /b 1
