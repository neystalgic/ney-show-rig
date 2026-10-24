#!/bin/bash
# Ney Pi -- one-command setup.   Run on the Pi:   bash ~/ney-show-rig/pi/install.sh
# Optional:  bash install.sh --timemachine /mnt/ssd   (makes the SSD a Time Machine backup for the Mac)
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(cd .. && pwd)"
USER_NAME="$(whoami)"
echo "== Ney Pi setup for user $USER_NAME, repo $REPO"

sudo apt-get update
sudo apt-get install -y git python3 python3-venv rsync avahi-daemon

# 1. health watch (always on, restarts itself)
[ -f config.json ] || cp config.example.json config.json
sed -e "s#User=ney#User=$USER_NAME#" -e "s#/home/ney/ney-show-rig#$REPO#g" ney-health.service | sudo tee /etc/systemd/system/ney-health.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now ney-health
echo "   health watch: http://$(hostname).local:7030/"

# 2. nightly copy of the show code from GitHub (03:30)
( crontab -l 2>/dev/null | grep -v 'ney-show-rig pull' ; echo "30 3 * * * cd $REPO && git pull --ff-only >> $REPO/pi/backup.log 2>&1 # ney-show-rig pull" ) | crontab -
echo "   nightly code backup: 03:30"

# 3. optional: Time Machine target on the SSD
if [ "${1:-}" = "--timemachine" ] && [ -n "${2:-}" ]; then
  SSD="$2"
  sudo apt-get install -y samba
  sudo mkdir -p "$SSD/timemachine" && sudo chown "$USER_NAME" "$SSD/timemachine"
  if ! grep -q "\[NeyTimeMachine\]" /etc/samba/smb.conf; then
    sudo tee -a /etc/samba/smb.conf >/dev/null <<SMB

[NeyTimeMachine]
   path = $SSD/timemachine
   valid users = $USER_NAME
   read only = no
   vfs objects = catia fruit streams_xattr
   fruit:time machine = yes
   fruit:time machine max size = 800G
SMB
  fi
  echo "   set a Samba password for $USER_NAME (you'll type it on the Mac once):"
  sudo smbpasswd -a "$USER_NAME"
  sudo systemctl restart smbd
  echo "   Time Machine: on the Mac, System Settings > General > Time Machine > + > NeyTimeMachine"
fi
echo "== done"
