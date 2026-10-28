#!/bin/bash
# Ney Sky — install on the Pi (run from ~/ney-show-rig/pi/sky):  bash install_sky.sh
# 1) runs the sky server as a service (port 7050)  2) opens the sky full-screen when the desktop starts
# 3) stops the screen from blanking.  Safe to run again.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="$(id -un)"
sudo tee /etc/systemd/system/ney-sky.service >/dev/null <<UNIT
[Unit]
Description=Ney Sky server (ceiling sky, port 7050)
After=network-online.target
[Service]
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=/usr/bin/python3 $DIR/sky_server.py
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now ney-sky.service

BROWSER="$(command -v chromium || command -v chromium-browser)"
LINE="$BROWSER --kiosk --noerrdialogs --disable-infobars --password-store=basic --autoplay-policy=no-user-gesture-required http://localhost:7050/ &"
mkdir -p ~/.config/labwc
touch ~/.config/labwc/autostart
grep -q 'localhost:7050' ~/.config/labwc/autostart || echo "$LINE" >> ~/.config/labwc/autostart
sudo raspi-config nonint do_blanking 1 || true
echo "Ney Sky installed. Server: http://$(hostname).local:7050/   Aim it from your phone: http://$(hostname).local:7050/calibrate"
echo "The sky opens full-screen next time the Pi's desktop starts (or reboot now: sudo reboot)."
