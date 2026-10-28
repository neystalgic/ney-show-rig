@echo off
rem Ney DMX node -- one-time setup on the Zephyrus
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python is not installed yet. Install Python 3.12 from python.org first
  echo and tick "Add python.exe to PATH" on the first screen. Then run this again.
  pause
  exit /b 1
)
py -3.12 -m pip install --upgrade ftd2xx pyserial
echo.
echo Done. Now double-click "Start DMX Node.bat".
echo The first time, Windows asks about the firewall: allow it on PRIVATE networks.
pause
