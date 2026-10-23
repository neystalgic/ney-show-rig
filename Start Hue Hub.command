#!/bin/zsh -l
# Double-click to start the Hue Hub (or run start_hub() in TouchDesigner's Textport).
# If a Hue Hub is already running somewhere, it is stopped first, so you always get
# the newest one. Close this window or press Ctrl+C to stop -- the lights go back to normal.
cd "$(dirname "$0")"
if pgrep -f "hue_hub.py" >/dev/null; then
  echo "Stopping the Hue Hub that was already running..."
  pkill -INT -f "hue_hub.py"
  for i in 1 2 3 4 5 6; do
    pgrep -f "hue_hub.py" >/dev/null || break
    sleep 1
  done
  pkill -f "hue_hub.py" 2>/dev/null
  sleep 1
  pkill -9 -f "hue_hub.py" 2>/dev/null          # a hub stuck in the MIDI driver ignores the polite stop
  echo "Giving the bridge a moment to let go..."
  sleep 4
fi
echo "Starting the Hue Hub at $(date)" > hub_log.txt
python3 -u hue_hub.py "$@" 2>&1 | tee -a hub_log.txt
echo
read "?The Hue Hub has stopped. Press Return to close this window."
