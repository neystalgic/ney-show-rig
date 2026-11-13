#!/bin/bash
# Restart the Ney brain with the newest code. (Run as a script so pkill never matches the SSH shell itself.)
pkill -f ney_brain.py
sleep 2
if systemctl is-enabled --quiet ney-brain 2>/dev/null; then
  systemctl is-active --quiet ney-brain || echo "systemd will restart it"
else
  cd "$HOME/NeyBrain" && setsid -f python3 -u ney_brain.py >> brain.log 2>&1 < /dev/null
fi
sleep 4
pgrep -f ney_brain.py >/dev/null && echo running
systemctl is-enabled ney-brain 2>/dev/null || echo not-installed
