#!/bin/zsh -l
# Double-click to stop any running Hue Hub (the lights go back to normal Hue control).
if pgrep -f "hue_hub.py" >/dev/null; then
  pkill -INT -f "hue_hub.py"
  sleep 3
  pkill -f "hue_hub.py" 2>/dev/null
  echo "The Hue Hub is stopped."
else
  echo "No Hue Hub was running."
fi
sleep 2
