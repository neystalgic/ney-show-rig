@echo off
rem Ney DMX node -- drives the Enttec from the hub. Leave this window open during shows.
cd /d "%~dp0"
title Ney DMX node
py -3.12 dmx_node.py %*
echo.
echo The DMX node stopped. If it says no FTDI device: is the Enttec plugged in?
echo (Test without the Enttec: Start DMX Node.bat --sim)
pause
