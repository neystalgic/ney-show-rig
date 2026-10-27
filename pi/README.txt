NEY PI  --  setup (about 20 minutes, most of it waiting)
=========================================================

WHAT IT DOES
  - Health watch: the Hue Hub sends it a heartbeat; if the hub, the lights or
    TouchDesigner go quiet mid-set, your phone gets a push alert (ntfy app).
  - Backups: a nightly copy of this repo, and (optional) the 1 TB SSD as a
    Time Machine drive for the whole Mac.
  - Later: Ableton Link / MIDI bridge for the Zephyrus, DMX via OLA.

0. PUT IT TOGETHER (Pi 5 8 GB + Active Cooler + M.2 HAT+ + NVMe SSD)
   (Raspberry Pi's official M.2 HAT+ steps; unplugged the whole time)
   - Active Cooler first: peel the film off the pads, push both pins through, plug its
     cable into FAN.
   - Screw the 4 spacers onto the Pi; press the GPIO stacking header onto the pins.
   - Unhook the ribbon from the HAT+. Into the Pi's PCIe port: lift the latch, metal
     contacts facing the USB PORTS, fully in, latch down.
   - HAT+ onto the spacers, screws in. Ribbon into the HAT+: copper contacts facing UP,
     latch down.
   - SSD: slide it in at a slight angle, press flat, turn the screw clockwise (don't
     over-tighten).
   - The official Pi 5 case only fits with its lid and fan off.

1. FLASH THE microSD (on the Mac) -- only used once, to get onto the SSD
   - Raspberry Pi Imager: https://www.raspberrypi.com/software/
   - Device: Raspberry Pi 5   OS: Raspberry Pi OS Lite (64-bit)   Storage: the microSD
   - Edit settings:  hostname  ney-pi     username  ney  (+ your own password)
                     Wi-Fi: your network (until the Ethernet arrives)
                     time zone: America/Los_Angeles
                     Services: enable SSH (password)
   - Write, put the card in the Pi, plug in the 27W supply, wait ~2 minutes.

2. LOG IN (Terminal on the Mac)
   ssh ney@ney-pi.local          (type yes the first time, then your password)

2b. MOVE EVERYTHING ONTO THE SSD (then the card is never needed again)
   lsblk                          (the SSD shows up as nvme0n1)
   sudo apt-get update && sudo apt-get install -y git rsync parted dosfstools
   git clone https://github.com/geerlingguy/rpi-clone.git && cd rpi-clone && sudo cp rpi-clone rpi-clone-setup /usr/local/sbin && cd ~
   sudo rpi-clone nvme0n1         (answer yes; it copies the card, settings and all, onto the SSD)
   sudo raspi-config              (Advanced Options > Boot Order > NVMe/USB Boot, then Finish)
   sudo poweroff
   Take the microSD out, power the Pi on again, wait ~1 minute, log in again:
   ssh ney@ney-pi.local
   findmnt /                      (should say /dev/nvme0n1p2 -- you're running from the SSD)

3. GET THE CODE (the repo is private, so sign in once -- you type the code, not me)
   sudo apt-get update && sudo apt-get install -y gh git
   gh auth login            (GitHub.com > HTTPS > Login with a web browser)
   gh repo clone neystalgic/ney-show-rig

4. INSTALL
   bash ~/ney-show-rig/pi/install.sh
   (and to make the Pi a Time Machine backup for the Mac too -- the SSD is the Pi's own drive now:)
   bash ~/ney-show-rig/pi/install.sh --timemachine /srv

5. TELL THE HUB WHERE THE PI IS (Claude can do this part)
   Light Desk setting  pi_url = http://ney-pi.local:7030/beat

6. PHONE ALERTS (optional)
   Install the free "ntfy" app, subscribe to a long random topic name, and put
   that name in ~/ney-show-rig/pi/config.json  ("ntfy_topic": "...").
   Only short status lines (e.g. "Lights offline") are ever sent.

CHECK IT:  http://ney-pi.local:7030/   (shows the last heartbeat and any problems)
