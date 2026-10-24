NEY PI  --  setup (about 20 minutes, most of it waiting)
=========================================================

WHAT IT DOES
  - Health watch: the Hue Hub sends it a heartbeat; if the hub, the lights or
    TouchDesigner go quiet mid-set, your phone gets a push alert (ntfy app).
  - Backups: a nightly copy of this repo, and (optional) the 1 TB SSD as a
    Time Machine drive for the whole Mac.
  - Later: Ableton Link / MIDI bridge for the Zephyrus, DMX via OLA.

1. FLASH THE CARD (on the Mac)
   - Raspberry Pi Imager: https://www.raspberrypi.com/software/
   - Device: your Pi model   OS: Raspberry Pi OS Lite (64-bit)
   - Edit settings:  hostname  ney-pi     username  ney  (+ your own password)
                     Wi-Fi: your network (until the Ethernet arrives)
                     Services: enable SSH (password)
   - Write, put the card in the Pi, power on, wait ~2 minutes.

2. LOG IN (Terminal on the Mac)
   ssh ney@ney-pi.local

3. GET THE CODE (the repo is private, so sign in once -- you type the code, not me)
   sudo apt-get update && sudo apt-get install -y gh git
   gh auth login            (GitHub.com > HTTPS > Login with a web browser)
   gh repo clone neystalgic/ney-show-rig

4. INSTALL
   bash ~/ney-show-rig/pi/install.sh
   (with the SSD plugged in and mounted at /mnt/ssd, for Time Machine too:)
   bash ~/ney-show-rig/pi/install.sh --timemachine /mnt/ssd

5. TELL THE HUB WHERE THE PI IS (Claude can do this part)
   Light Desk setting  pi_url = http://ney-pi.local:7030/beat

6. PHONE ALERTS (optional)
   Install the free "ntfy" app, subscribe to a long random topic name, and put
   that name in ~/ney-show-rig/pi/config.json  ("ntfy_topic": "...").
   Only short status lines (e.g. "Lights offline") are ever sent.

CHECK IT:  http://ney-pi.local:7030/   (shows the last heartbeat and any problems)
