@echo off
rem Ney DMX -- one-time setup in this folder (C:\NeyDMX)
cd /d "%~dp0"
where py >nul 2>nul || (echo Python 3.12 is not installed. Install it from python.org, tick "Add python.exe to PATH". & pause & exit /b 1)
echo [1/3] Python add-ons for the Enttec...
py -3.12 -m pip install --upgrade ftd2xx pyserial
echo.
echo [2/3] Bringing over your head calibration from the old folders (if any)...
if not exist "config" mkdir config
if not exist "config\heads_config.json" (
  for %%F in ("%USERPROFILE%\Downloads\NeyDMX\NeyDMX\heads_config.json" "%USERPROFILE%\Downloads\NeyDMX\heads_config.json") do (
    if exist %%F if not exist "config\heads_config.json" copy %%F "config\heads_config.json" >nul && echo     copied %%~F
  )
)
if exist "config\heads_config.json" (echo     calibration: config\heads_config.json) else (echo     none found -- a fresh one is made on first start)
echo.
echo [3/3] Desktop shortcut "Ney DMX Node"...
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Ney DMX Node.lnk'); $s.TargetPath='%~dp0Start DMX Node.bat'; $s.WorkingDirectory='%~dp0'; $s.Save()"
echo.
echo Done. Start it with the "Ney DMX Node" shortcut on your desktop (or Start DMX Node.bat here).
pause
