@echo off
rem Ney DMX node -- drives the Enttec from the hub. Leave this window open during shows.
cd /d "%~dp0"
title Ney DMX node
py -3.12 app\dmx_node.py %*
echo.
echo The DMX node stopped. Switch the heads off before closing this window (without a signal they run their own show).
echo If it says no FTDI device: is the Enttec plugged in?   Test without it: Start DMX Node.bat --sim
pause
