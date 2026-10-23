#!/bin/zsh -l
# Double-click: listens to all MIDI for 20 seconds and writes midi_check.txt. Only listens, never sends.
cd "$(dirname "$0")"
python3 -u midi_check.py
echo
read "?Done. Press Return to close this window."
