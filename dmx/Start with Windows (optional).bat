@echo off
rem Optional: start the DMX node (minimised) whenever you log in to Windows, so the heads always get a signal.
rem Undo: delete "Ney DMX Node" from the folder that opens with  Win+R  ->  shell:startup
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\Ney DMX Node.lnk'); $s.TargetPath='%~dp0Start DMX Node.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
echo The DMX node will now start (minimised) when you log in. Undo: Win+R, shell:startup, delete "Ney DMX Node".
pause
