#!/bin/bash
# Switches the Hue lamps to the movie look (audio reactive, follows the film's sound).
cd "$(dirname "$0")"
curl -s -m 60 -H "X-Token: $(tr -d '[:space:]' < rig_control.token)" "http://127.0.0.1:7040/m/lights?l=movie"
echo
echo "Movie lights on. You can close this window."
