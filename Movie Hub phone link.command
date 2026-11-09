#!/bin/bash
# Opens the Movie Hub remote in Safari on this Mac, with its key, so you can
# AirDrop it to your phone (Share > AirDrop). The key never leaves this Mac otherwise.
cd "$(dirname "$0")"
IP=$(ipconfig getifaddr en15 2>/dev/null || ipconfig getifaddr en0 2>/dev/null || echo 127.0.0.1)
open -a Safari "http://$IP:7040/hub?token=$(tr -d '[:space:]' < rig_control.token)"
echo "Movie Hub is open in Safari. Share > AirDrop it to your iPhone, then on the phone: Share > Add to Home Screen."
