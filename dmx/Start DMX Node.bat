@echo off
rem Ney DMX node -- drives the Enttec from the hub. Leave this window open during shows.
rem Auto-update: on every start it fetches the newest node from the hub on the Mac (if reachable),
rem checks it, and keeps the previous version as app\dmx_node.prev.py.
cd /d "%~dp0"
title Ney DMX node

rem --- only ONE node at a time (two copies fight over the Enttec: DEVICE_NOT_OPENED) ---
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 7060 -State Listen -ErrorAction SilentlyContinue) { exit 1 }"
if errorlevel 1 (
  echo A DMX node is already running on this computer. Use that window, or close it first.
  pause
  exit /b 1
)

echo Checking the hub for a newer DMX node...
if exist app\dmx_node.new del app\dmx_node.new
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 6 -Uri http://neystalgic:7020/kit/dmx_node.py -OutFile app\dmx_node.new } catch { exit 0 }"
if not exist app\dmx_node.new goto nohub
py -3.12 -c "import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8').read())" app\dmx_node.new
if errorlevel 1 goto broken
fc /b app\dmx_node.new app\dmx_node.py >nul
if not errorlevel 1 goto same
copy /y app\dmx_node.py app\dmx_node.prev.py >nul
move /y app\dmx_node.new app\dmx_node.py >nul
echo     Updated to the newest version.
goto run
:same
del app\dmx_node.new
echo     Already up to date.
goto run
:broken
del app\dmx_node.new
echo     The download looked broken -- keeping the version on this computer.
goto run
:nohub
echo     Hub not reachable -- starting the version on this computer.

:run
py -3.12 app\dmx_node.py %*
echo.
echo The DMX node stopped. Switch the heads off before closing this window (without a signal they run their own show).
echo If it says no FTDI device: is the Enttec plugged in?   Test without it:  Start DMX Node.bat --sim
pause
