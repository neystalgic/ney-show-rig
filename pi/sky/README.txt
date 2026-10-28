NEY SKY — a real-time sky for the ceiling
=========================================

Two styles (switch on the phone page)
  Dreamy (default): Pixar-style puffy cumulus with lumpy edges, soft pastel shading and a silver lining,
         storybook sky colours, a big storybook moon (real phase and position), little striped hot-air
         balloons drifting through now and then, sparkly bright stars, and a rare soft shooting star at night.
  Realistic: natural clouds and a true-size moon.
  Either way the stars, constellations, moon and sun are where they really are.

What it shows
  Day: blue sky with drifting clouds (follows real Burbank cloud cover and wind; always keeps a few clouds).
  Sunrise/sunset: colours timed to the real sun.
  Night: the real stars and constellations overhead right now, the moon in its real phase and place,
         and a faint Milky Way when it's up. Viewed from below: north up, east LEFT (like a star chart).
  Modes from the Hue Hub: music (tints to the show palette, gentle swells), movie (dim), rest (very dim), off.
  Flicker-safe: every change is eased (brightness fades at most 25%/s; music swells max ~18%). Nothing flashes.

Files
  index.html, sky.js      the sky (WebGL; runs in Chromium on the Pi)
  sky_data.js             ~4,100 stars to magnitude 5.8 + constellation lines
                          (d3-celestial by Olaf Frohn, BSD-3-Clause, from the HYG/Yale Bright Star catalogues)
  sky_server.py           tiny server on port 7050: serves the page, /state (from the hub), /config (aiming)
  calibrate.html          phone page for aiming: http://ney-pi.local:7050/calibrate
  install_sky.sh          installs the service + full-screen autostart on the Pi
  sky_config.json         created by the calibrate page (local to the Pi, not committed)

Preview on the Mac (no Pi needed)
  Open index.html in Chrome. Handy URL options (add after ?):
    t=2026-10-29T07:00:00Z   pick a moment (UTC)        speed=600   time-lapse (10 min per second)
    mode=music|movie|rest     preview a mode              calib=1     aiming grid + compass
    fov=110  rot=0  flip=1    view width / turn / mirror  weather=0   skip real weather
    instant=1                 skip the 4 s fade-in
    (style, balloons etc. are set on the phone page, or in SKY_DEFAULTS)

On the Pi (once the micro-HDMI cable arrives)
  1. Copy the repo to the Pi as before, then:  cd ~/ney-show-rig/pi/sky && bash install_sky.sh
  2. Plug the projector into the Pi's HDMI 0 port (the one nearest the USB-C power), reboot.
  3. On your phone: http://ney-pi.local:7050/calibrate
       - Show aiming grid, turn until the red N points to real north (use the Compass app), Mirror if E/W are swapped.
       - Drag the 4 corners until the orange border looks rectangular on the ceiling (fixes the angled projector).
       - Hide the grid.

Hub hook (next step): the Hue Hub POSTs {"mode": "music", "tint": [r,g,b], "level": 0..1} to http://ney-pi.local:7050/state.
If the hub goes quiet for 30 s during music mode, the sky drifts back to the real sky on its own.

Placement notes
  Aim at the ceiling beside the fan, not through it (blades would cast moving shadows).
  Keep the beam out of seated/standing head height, keep vents and lens clear, and cables off walkways.
  Weather lookup sends only Burbank's city-centre coordinates to Open-Meteo (free, no account). Turn it off on the calibrate page.
