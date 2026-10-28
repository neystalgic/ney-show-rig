NEY DMX NODE -- the moving heads, through the Zephyrus
======================================================

   Hue Hub (Mac)  --Art-Net over the network-->  dmx_node.py (Zephyrus)  --USB-->  Enttec  --DMX-->  heads 1-4

The Mac stays the show brain. The hub turns the room's light into head colours, brightness and slow
movement and sends it ~40 times a second. The Zephyrus node is the last word on safety:

  * the heads' strobe is never used (master channel 8-134 only), auto programs, colour macros and reset are locked off
  * STROBE HITS come from the hub instead: on the kick in drops, max 3 a second room-wide, in colour, and only
    while a head points into the ceiling cone (within 45 deg of straight up = 45-135 deg above its surface)
  * each head's tilt stays in its calibrated window (beams above head height); optional pan window (mirror, glass door)
  * a head stays DARK until it's calibrated
  * flash guard: no head turns round brighter/darker more than 3 times a second (and the hub limits it first)
  * heads never go white (colour kept 55%+ saturated; the white LED only softens pastels)
  * laser bar channels (57+) stay at 0 until it has a profile
  * hub stops or the network drops -> heads fade to dark over 2 s and point straight up
  * Movie mode, blackout, rest -> heads dark and straight up

FILES
  dmx_node.py            the node (Windows: FTDI D2XX driver; or --serial COMx; or --sim with no hardware)
  node_page.html         phone page: live view + calibration   http://<zephyrus>:7060/
  heads_config.json      created on first run: addresses + each head's calibration (stays on the Zephyrus)
  Install DMX Node.bat   one-time: installs the two Python packages
  Start DMX Node.bat     runs it (leave the window open)
  ../hub_dmx.py          the hub side (in the Hue Rig folder)

ZEPHYRUS SETUP (once)
  1. Finish Windows Update, restart.
  2. Tailscale: install from tailscale.com, sign in with the SAME account as the Mac and Pi.
     Note the Zephyrus' name in the Tailscale app (e.g. "zephyrus").
  3. Python 3.12 from python.org -- tick "Add python.exe to PATH".
  4. Copy this "dmx" folder to the Zephyrus (e.g. C:\NeyDMX), double-click "Install DMX Node.bat".
  5. Plug in the Enttec. Device Manager should show "USB Serial Converter" under Universal Serial Bus controllers.
     (If it shows with a yellow "!", install FTDI's "CDM" driver from ftdichip.com -- Drivers -> VCP/D2XX.)
  6. Double-click "Start DMX Node.bat". Allow the firewall prompt on PRIVATE networks.
     It prints the output it found ("Enttec Open DMX USB (D2XX: ...)").

CONNECT THE HUB
  Desk > Setup (or ask Claude): setting dmx_host = the Zephyrus' Tailscale name.
  The hub's status line "heads" then says "sending to zephyrus -- Enttec ..., 0 of 4 heads calibrated".

ONE HEAD TONIGHT (before the cables come)
  Enttec 5-pin -> your 5-pin-male/3-pin-female adapter -> the head's DMX IN.  Head menu: 14CH, address 001.
  Open http://<zephyrus>:7060/ on your phone, tap Head 1, calibrate (keep faces out of the beam while you do):
    Steer -> move Tilt until the beam points straight up -> "This is straight up" -> set Max lean ->
    (pan limits if needed) -> Calibrated.

ADDRESSES (14-channel mode on every head)
  Head 1  001   white-desk side table        Head 3  029   couch corner table
  Head 2  015   kitchen cube shelf           Head 4  043   rolly desk (terminator in its DMX OUT)
