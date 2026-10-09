@echo off
cd /d "%~dp0"
if exist "portable\jav-data\jav-data.exe" (
  start "" "portable\jav-data\jav-data.exe" %*
  exit /b 0
)
if not exist ".venv\Scripts\python.exe" (
  echo Project environment missing. Follow README.md setup instructions.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m jav_data.desktop %*
if errorlevel 1 pause
