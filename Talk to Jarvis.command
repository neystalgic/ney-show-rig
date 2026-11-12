#!/bin/bash
# Double-click to talk to Jarvis. Type a command, press Return. Type quit to stop.
cd "$(dirname "$0")"
clear
/usr/bin/python3 jarvis/jarvis.py --say
