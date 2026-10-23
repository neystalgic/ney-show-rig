HUE RIG -- THE LAMPS AS PART OF THE SHOW
========================================

hue_rig gives every Hue lamp a colour every frame and sends it to the lights:
  - from the Feeling Palette (breathing nostalgia / hope / triumph colours)
  - from the projected picture, so the room glows with whatever is on the
    wall -- any Mapper Pack animation, sacred geometry, ISF shader...
  - or as a chase / flash / ripple that keeps time with the Mapper Pack

Until the bulbs are set up, it shows 5 VIRTUAL LAMPS on its preview, so you
can design the light show right now.

Files in this folder
  build_hue_rig.py          builds hue_rig in TouchDesigner (+ saves the .tox)
  hue_stream.py             the helper: pairs with the bridge and streams
  hue_engine.py             the brains (goes inside hue_rig)
  hue_downsample.glsl, hue_preview.glsl, hue_lampdata_callbacks.py
  hue_rig_preview.png       what the modes look like
  update_hue_rig.py         gives an existing hue_rig the newest engine (keeps wiring)
  hue_rig_controls.py       the Lamps and Cues pages (used by the two scripts above)
  build_show_clock.py       show_clock: one beat (Ableton Link) for lamps and visuals
  starter_cues.py           saves five ready-made cues
  -- created later --
  hue_config.json           your bridge address + keys (keep private)
  hue_lamps.csv             your lamps, in order, with their positions
  hue_cues.json             your saved cues


1. TRY IT NOW (no bulbs needed)
-------------------------------
  Textport:
  exec(open('/Users/michaelney/Touchdesigner Designs/Hue Rig/build_hue_rig.py').read())

  If a Mapper Pack animation is in the project, it's wired in automatically
  and the virtual lamps pick up its colours. Otherwise wire any picture into
  hue_rig. Change Mode on the Look page and watch the preview.


2. THE MODES (Look page) -- and what they pair with
---------------------------------------------------
  Palette            each lamp breathes one of the feeling colours
                     (follows the Feeling Palette's Stage fader)
  Sample the Picture each lamp takes the colour of the wall where it sits.
                     (Nothing wired in? It breathes the palette instead, and says so.)
                     Pairs with everything -- try mp_line_sweep (bars passing
                     light the lamps one by one), mp_plasma (slow colour
                     washes), mp_grid_pulse, or a whole mapped scene.
  Chase              light runs across the lamps left to right.
                     Pairs with mp_line_sweep and mp_edge_chase.
  Flash              all lamps hit the accent colour once a cycle and on the
                     kick. Pairs with mp_strobe.
  Ripple             waves from the middle of the room outward.
                     Pairs with mp_grid_pulse (Ripple) and mp_tunnel.
  Rainbow Show       red, orange, yellow, green, blue, indigo, violet, on the beat
                     (Rate 1 = one step per beat). Loops every 12 bars:
                       4 bars  the rainbow spread across the room, scrolling
                       4 bars  the whole room one colour, next colour every 2 beats
                       4 bars  each colour sweeps across the room left to right
                     Set each lamp's place on the Lamps page so it runs in order.

  Keep in time with an animation (same Rate / Sync / BPM):
      link_clock(op('hue_rig'), op('mp_line_sweep'))
  Kick           wire your kick envelope here later -- every mode pulses
  Intensity      master brightness.   Max Brightness: a ceiling.
  Blackout       all lamps fade to dark
  Smoothing      0 = instant, 1 = slow washes (fades up quicker than down)
  Flicker Guard  how many flashes a second the lamps may make (0.5 - 3)
  Colour Boost / Brightness Boost / Sample Area (Sample mode)
  Follow the Feeling Palette (on by default), or use the three colours below


2b. EACH LAMP ON ITS OWN (Lamps page)
-------------------------------------
  Every lamp has a row, named like in the Hue app:
    Role         Follow the Mode        does whatever Mode says (default)
                 Slow wash              breathes a feeling colour, ignores Mode
                 Hit on the beat / kick dim, then hits its own colour on every
                                        beat of the clock (and on the Kick)
                 Steady colour          just its own colour
                 Off
    colour       the lamp's own colour (Steady colour / Hit on the beat)
    brightness   this lamp only
  Example: Behind Desk = Slow wash, Floor Shade = Hit on the beat (red),
  the rest = Follow the Mode with Mode = Sample the Picture.
  Added more lamps? Run "python3 hue_stream.py areas", press Reload Lamp List,
  then run update_hue_rig.py again -- it adds rows for the new lamps.


2d. KEEPING EVERYTHING TOGETHER
--------------------------------
  ON THE BEAT -- the Show Clock (one beat for lamps AND visuals)
    Textport:
      exec(open('/Users/michaelney/Touchdesigner Designs/Hue Rig/build_show_clock.py').read())
      follow_all()
    In Ableton Live switch on Link (top-left, next to the tempo). show_clock
    then follows Live's tempo and beat, and hue_rig plus every mp_ animation
    keep time with it (Sync on, BPM from the clock).
    show_clock's Clock page: Source (Ableton Link / Free), Tap Tempo,
    "Now Is Beat 1" (press on a downbeat to line up the bar), Nudge.
    Readout page: Beats, Tempo, Bar, Beat, Status.
    Rate then means "cycles per beat": 1 = every beat, 0.25 = once a bar.
    Lights Ahead (Look page, default 60 ms) fires the lamps a touch early,
    because Hue bulbs take a moment to change.

  ORDER ACROSS THE ROOM -- Lamps page, "place" of each lamp
    left-right 0 = far left, 1 = far right (as the audience sees it)
    height     0 = floor, 1 = ceiling
    Chases travel left to right in this order, Ripple spreads from the
    middle, and Sample the Picture copies the part of the wall that matches.
    Two lamps with the same place act like one. Watch the dots on hue_rig's
    preview move as you change them.

  MATCH THE PROJECTION -- Look page
    Colours From = The Picture      every mode uses the projection's colours
                                    (left side, right side, brightest accent)
    Hits from the Picture           the lamps punch when the wall flashes

  ONE RIG, NOT SIX LAMPS -- Look page
    Togetherness   0 = every lamp its own colour and timing,
                   1 = the whole room is one colour, breathing as one


2c. CUES (Cues page) -- save looks and fire them
------------------------------------------------
  1. Set up a look (Mode, colours, timing, the Lamps page).
  2. Type a name in "Name for a New Cue" (e.g. intro, drop, outro) and press
     "Save Current Look as Cue". Same name again = replace it.
  3. Pick a cue in "Cue" and press Go. Previous / Next step through them.
     Cross-fade Time = how long the change takes (0 = instant).
  From anywhere (Textport, or later a button / MIDI):  hue_cue('drop')
  Cues are kept in hue_cues.json in this folder, so every project sees them.
  Not stored in cues: Kick, Blackout and the Flicker Guard (safety stays yours).


TRUE COLOURS
------------
  The helper sends each colour to the bridge as an exact Hue colour point
  (x, y) plus brightness, using Philips' own conversion -- so an orange you
  pick in TouchDesigner is the same orange on the bulb, a dim colour stays
  the same colour (just dimmer), and nothing goes pastel on the way.
  Togetherness and cue cross-fades blend round the colour wheel, so lamps
  never pass through grey.
  Check it any time (Terminal, helper not running):
      python3 hue_stream.py colours
  Every lamp shows red, orange, yellow, green, cyan, blue, violet, magenta,
  pink, warm white and white for 3 seconds each. Compare with a Constant TOP.
  The old way, to compare:   python3 hue_stream.py colours --colour rgb
  Limits of the bulbs themselves: deep cyan and turquoise come out paler than
  on a screen, and Hue color lamps can't reach the deepest greens.


FLICKER PROTECTION (always on)
------------------------------
  Lamps react instantly -- a drop, a kick, a cue change -- but none of them,
  and not the room as a whole, can FLASH more often than the Flicker Guard
  allows: every flash (a big change one way and then back) has to wait its
  turn. Changes that keep going one way (fades, a single hit) are never
  slowed. When it steps in, hue_rig's Status says "Flicker Guard is
  softening fast changes".
  The helper checks again right before the bulbs, with a hard limit of 3
  flashes a second whatever TouchDesigner sends. There is no way to switch
  it off: fast flashing light can trigger seizures in people with
  photosensitive epilepsy.
  Hits on the beat keep up with the music up to about:
      Flicker Guard 2  ->  ~105 BPM      Flicker Guard 3  ->  ~150 BPM
  Faster than that, some hits are skipped or softened.


3. WHEN THE BULBS ARRIVE
------------------------
  a. Hue app: add the bridge and lamps, name them, then
     Settings > Entertainment areas > Add. Drag each lamp to where it
     really is. Left-right and HEIGHT matter: hue_rig uses them to decide
     which part of the projected picture each lamp copies.
  b. Terminal (Applications > Utilities > Terminal), one line at a time:

     cd '/Users/michaelney/Touchdesigner Designs/Hue Rig'
     python3 -m pip install --user python-mbedtls
     python3 hue_stream.py pair         (press the bridge's round button)
     python3 hue_stream.py areas        (writes hue_lamps.csv)
     python3 hue_stream.py test         (each lamp lights up in turn)

  c. TouchDesigner: on hue_rig's Hue page press "Reload Lamp List" -- the
     virtual lamps become your real ones, in their real places.


4. PLAYING
----------
  Terminal:   python3 hue_stream.py run        (leave it running; Ctrl+C stops)
  hue_rig:    Send to the Lights = on, How = Stream through the helper
  The Status line on the Hue page says what's happening.

  No helper? Set How = "Direct to the bridge": no Terminal needed, but only
  about 10 changes a second across all lamps -- fine for slow palette
  washes, too slow for beats.

  While streaming, the Hue app / Apple Home can't change those lamps. Ctrl+C
  in Terminal hands them back.


Tested before it reached you: the helper ran against a stand-in Hue Bridge
(pairing with the button, reading the Entertainment area and lamp names,
the encrypted DTLS connection with the bridge's exact cipher, and 50
colour messages a second), and hue_rig's engine sent real colours through
the helper to it -- left lamp red, middle green, right blue, exactly as
sampled. Not yet tried: your real bridge and the inside of TouchDesigner.
If anything prints an error, send it to me.
