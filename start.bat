@echo off
cd /d "%~dp0"
python setup.py
if errorlevel 1 (
  echo Setup failed. Check your Internet connection and try again.
  pause
  exit /b 1
)
echo Open http://127.0.0.1:8765 in your browser.
python server.py
pause

