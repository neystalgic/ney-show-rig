NEY DMX -- the moving heads, through the Zephyrus          (folder: C:\NeyDMX)
==============================================================================

  Start DMX Node.bat              run this (or the desktop shortcut). Leave the window open during shows.
  Heads Desk.url                  calibration desk in your browser (also on the Mac: http://zephyrus:7060/desk)
  Install (run once).bat          Python add-ons, brings over your old calibration, desktop shortcut
  Start with Windows (optional)   starts the node minimised when you log in
  app\       the program: dmx_node.py, the phone page, the Heads Desk page   (replace these to update)
  config\    heads_config.json = addresses + each head's calibration and avoid zones   (keep this!)

ORDER: start the DMX node FIRST, then power the heads. Switch the heads off BEFORE closing the node --
without a signal they run their own built-in show (including their strobe).

UPDATING: close the node, replace the files in app\ with the new ones, start it again. config\ is never touched.

SAFETY (enforced here, whatever the hub sends)
  * the heads' own strobe, auto programs, colour macros and reset are locked off (master 8-134 only)
  * tilt stays in each head's calibrated window; optional pan window; avoid zones keep the beam within
    4 deg of straight up when it leans toward the projection, mirror or glass door
  * uncalibrated heads stay dark; laser channels stay at 0 until it has a profile
  * flash guard: max 3 flashes a second per head; hub silent -> heads fade to dark and point up
  * strobe hits come from the hub only: when a drop lands and each 4-bar phrase in it, in colour, inside the
    ceiling cone (45-135 deg above the surface), max 3 a second
