HUE HUB -- THE LIGHT SHOW, REBUILT
==================================

What changed, and why
---------------------
Kept (it worked):   the bridge connection, exact colours, flicker protection,
                    Ableton's beat (show_clock), lamps copying the projection.
Replaced (it didn't): settings spread over hue_rig's pages, no way to paint
                    exact colours, slow to change live, no song structure.

Now ONE program, the Hue Hub, is the brain. It runs in Terminal and you steer
it from the LIGHT DESK (inside TouchDesigner, in a browser, or on your phone)
and from PUSH 2. TouchDesigner only feeds it the picture and the beat.

  Ableton Link --> show_clock --> hue_feed (TD) --+
  any picture  ------------------> hue_feed      +--> Hue Hub --> bulbs (50/s,
  Light Desk + Push 2 ----------------------------+               exact colours,
                                                                   flicker-safe)

Files (Hue Rig folder)
  hue_hub.py            the Hub (Terminal)
  desk.html             the Light Desk page (the Hub serves it)
  hub_push2.py          Push 2 control (used by the Hub)
  hub_audio.py          listens to the gear through the Scarlett (kick, snare, hats)
  hub_audioshow.py      the audio light show (sidechain pump, accents, drops)
  build_hue_hub_td.py   builds hue_feed + light_desk in TouchDesigner
  hue_stream.py         pairing, scan, colour check (as before)
  hub_lamps.json        your lamps and their colour zones (written by scan)
  hub_state.json        everything you make: looks, songs, lamp places


1. FIRST TIME (Terminal, in the Hue Rig folder)
-----------------------------------------------
  cd '/Users/michaelney/Touchdesigner Designs/Hue Rig'
  python3 -m pip install --user mido python-rtmidi       (for Push 2)
  python3 hue_stream.py scan

  scan lists every lamp, its model, and how many colours it can show at once.
  A gradient floor lamp the area splits into zones gets one colour per zone.
  If it says a lamp "can show several colours but your area only gives it
  one channel": in the Hue app remove that lamp from the Entertainment area
  and add it again (or make a new area), then scan again.


2. EVERY SHOW
-------------
  Terminal:      python3 hue_hub.py
                 (stop the old "python3 hue_stream.py run" first -- only one
                 program can stream to the bridge)
  TouchDesigner Textport, once per project:
                 exec(open('/Users/michaelney/Touchdesigner Designs/Hue Rig/build_hue_hub_td.py').read())
                 open_desk()
  Wire the picture you want the lamps to see into hue_feed.
  Ableton: Link on (and show_clock built, see the main README).

  The desk also opens in any browser at http://localhost:7020
  Phone: start with   python3 hue_hub.py --phone   and open the address it
  prints (same Wi-Fi).
  No bulbs around?    python3 hue_hub.py --rehearse   (desk + preview only)


3. THE LIGHT DESK
-----------------
  Top bar     Lights / TouchDesigner / tempo, bar, beat / Push 2 at a glance.
              HOLD freezes all motion, HIT = one white hit, TAP = tap tempo
              (only used when there's no Ableton beat), BLACKOUT fades to dark.
              Keys (desk focused): space = hit, B = blackout, H = hold,
              T = tap, 1-9 = looks 1-9.

  SHOW tab
    Room      your lamps where they really are; gradient floor lamps show
              each zone. Tap a zone (or a lamp's name for all its zones),
              shift-click to add more, then tap a colour to PAINT it.
              "Spread over selection" paints a gradient across the selection
              (left to right, top to bottom).
    Looks     tap = play it (fades over "Look fade"). Long-press or
              right-click = edit it without playing it. Painting always goes
              to the look marked "editing". "New copy" copies it to start a
              new one.
    Editing   Name, Motion, Speed (in beats/bars, locked to Ableton),
              Movement (how strong the motion is), Together (all lamps at
              once vs travelling across the room), Brightness, Wall hits
              (lamps punch when the projection flashes).
    Motions   still    exactly your colours
              breathe  brightness rises and falls
              pulse    a hit each cycle, fading out
              chase    a bright spot runs left to right
              wave     waves from the middle of the room
              sparkle  random zones flare
              drift    your colours slide from lamp to lamp
              rainbow  red, orange, yellow, green, blue, indigo, violet
              picture  each zone copies the projection where it sits
    Live      Master, Speed (x0.25-x4 on top of the look), Smoothing, Look
              fade, Colour (turns every colour round the wheel), Vibrance,
              Movement (x0-x2), Flicker Guard (max flashes a second,
              never above 3), Tempo (no-Ableton fallback). Double-click a
              fader to reset it.

  SONGS tab
    New song, name it, set its length in bars. Tap a bar number to put a
    section there and choose its look, label (intro, build, drop...) and fade
    in beats. "Start at next bar" starts bar 1 on the next downbeat and the
    looks change by themselves; "Next section" jumps at the next bar; Loop
    repeats it.

  SETUP tab
    Move lamps: drag them in the Room to where they really are. Gradient
    lamps: zones run bottom to top or left to right. "Now is beat 1" lines
    up the bars. "Connect lights again" if the bridge dropped.


4. PUSH 2  (press USER on Push 2 to play the lights; again to go back to Live)
-------------------------------------------------------------------------------
  Push 2 starts in PLAY mode (all 64 pads lit) as soon as you press User.
  Push 2 always shapes the look that is PLAYING (and saves it).
  SESSION button   LOOKS mode: top 6 pad rows = looks 1-48 (playing one white),
                   bottom 2 rows = song sections (go there at the next bar)
  NOTE button      PLAY mode -- the light instrument. All 64 pads play live:
                     columns  red orange yellow green cyan blue violet pink
                     rows (bottom to top)  wash, glow (slow swell), hit (one
                     punch), pulse (on the beat), chase (across the room once
                     a bar), sparkle, sweep (fills left to right)
                     top row  MULTI-COLOUR: rainbow, fire, sunset, aurora,
                     ocean, golden (golden-angle colours), galaxy, confetti --
                     the colours spread across the room and drift along it
                   PATTERNS (desk > Pads, OFF for now): with it off, rows 1-7
                   make no patterns -- every pad is just its column's colour.
                   Turn it on to get wash / glow / hit / pulse / chase /
                   sparkle / sweep back. The top row always plays its effects.
                   Each ROW picks the sacred geometry the TouchDesigner
                   visuals show (the last pad you push decides):
                     row 1 = flower of life     row 2 = golden angle
                     row 3 = Metatron's cube    row 4 = Chladni plate
                     row 5 = Sri Yantra         row 6 = reaction-diffusion
                     row 7 = tesseract
                     top row = the geometries take turns: one at 100%,
                               held, then it morphs into the next along a
                               curve, each in a different lamp's colour
                               (geo_show > Blend page in TouchDesigner:
                               Hold Each and Morph Into Next in beats, Morph
                               Curve = Sine / Smoothstep / Smootherstep /
                               Cubic / Exponential / Circular / Linear,
                               Order = In Order / Golden Steps; Showing says
                               what's on now. A morph never goes quicker than
                               0.4 s, and a whole step never quicker than 1 s.)
                   ACROSS the pads (columns, left to right) shapes it instead
                   of restarting it: smaller -> bigger, an extra turn (up to
                   157.5 degrees), partly drawn -> whole, thin -> bold lines.
                   It glides to the new shape over about a third of a second.
                   (a visual not in the project falls back to the nearest one)
                   Velocity = how bright it starts. Pressure = a little
                   brighter and fuller while held (resting a finger does
                   nothing; desk > Pads > Pressure sets how much, 0 = off).
                   Touch strip = bends the colour.
                   A pad's colour is exact on the lamps whatever the Colour
                   and Vibrance knobs are set to -- those turn the LOOK
                   underneath, not the pads. A held pad keeps its true colour
                   on Push (Setup > Timing can make held pads white again).
                   LATCH (on): the last pad you pushed keeps playing after
                   you let go, until you push another pad. Hits play over it.
                   DELETE (or "All pads off" on the desk) clears it. Turn
                   Latch off on the desk's Pads tab.
  SCALE button     GEOMETRY mode -- sacred geometry you play:
                     columns  golden, flower, yantra, metatron, chladni,
                              spiral, cube, tesseract
                     rows (bottom to top)  white light, golden, triad, hexad,
                              opposite, warm, cool, fibonacci
                   Pressure grows the shape, the touch strip spins it (the
                   visuals in TouchDesigner spin with it). Knobs as in PLAY.
                   Buttons below the screen set the PLAYING look to these
                   eight forms. Latch works here too.
                   Knobs: 1 Master 2 Colour 3 Vibrance 4 Pad level 5 Attack
                   6 Release 7 Pad speed 8 Spread. Hold several pads to layer
                   them. The desk's Pads tab shows the same grid (and you can
                   play it with the mouse).
  LAYOUT button    PAINT mode: top 6 rows = every lamp / colour zone in room
                   order, lit in its colour (bright = selected, tap to select,
                   SELECT = all / none); bottom 2 rows = 16 colours: tap one to
                   paint the selected zones (nothing selected = all of them)
  Buttons below the screen   pattern: still breathe pulse chase wave sparkle drift rainbow
  Buttons above the screen   speed: 4 bars 2 bars 1 bar 2 beats 1 beat 1/2 beat,
                             then picture, wall hits on/off
  Knobs 1-8   Master, Colour, Vibrance, Brightness, Movement, Together, Speed, Smoothing
              LOOKS mode: Colour / Vibrance turn the whole room's colours live
              PAINT mode: Colour / Vibrance / Brightness change the selected zones' paint
  Master knob = Master     Tempo knob = Look fade     Swing knob = Flicker Guard
  Left / Right arrows = previous / next look      New = copy the playing look
  Tap Tempo = tap   Metronome = hold   Mute = blackout   Accent = hit
  Play = start / stop the song   Record = "now is beat 1"
  The same map is on the desk's Setup tab.


4a. SACRED GEOMETRY
-------------------
  Light forms (desk > Show > Editing > "Sacred geometry" row): every lamp and
  zone sits at its place in the room and the figure decides its light.
    golden     golden angle: one zone per cycle, chosen by the golden ratio,
               each 137.5 degrees further round the colour wheel
    flower     Flower of Life: centre breathes, six petals around it in turn
    yantra     Sri Yantra: your colours and their opposites interlock as up
               and down triangles; the centre (bindu) pulses
    metatron   a point of light travels the lines of Metatron's Cube
    chladni    Chladni sound-plate patterns, a new mode every 4 cycles
    spiral     a golden spiral turning through the room
    tetrahedron, cube, tesseract   the solid rotates; its corners light the
               zones they pass
  Together = how wide the shape is. Speed = how fast (locked to the beat).

  Sacred colours (desk > Show, under the Room): pick a colour, then
  Golden / Triad / Hexad / Opposite / Analogous / Fibonacci paints the
  selected zones (or all) in room order.

  Visuals in step (TouchDesigner, in the project with the Sacred Geometry
  set and/or the Mapper Pack, after running build_hue_hub_td.py):
      sync_geometry()          then   open_show()
  What the visuals follow:
    colours      the room's two main colours -- what the lamps really show
                 (a geometry pad: its harmony)
    pads         the row picks the geometry; the column (left -> right) makes
                 it bigger, turned further, more fully drawn and bolder
    brightness   the room's brightness makes the lines glow; Blackout and
                 Master darken the visuals too
    rotation     turns with the lamps; the touch strip spins it
    chladni      the same plate modes as the lamps
  geo_show (in /project1) is the finished picture: it cross-fades to the
  visual that matches what's playing (the geometry pad's form, the PLAY
  pad's row, or the look's geometry motion), with a Mapper Pack effect added
  on top. geo_show > Show page: Mapper Effect, Effect Amount, Cross-fade.
  Wire geo_show to your projector output (or use any visual on its own).
  Mapper effects follow the room's colours, tempo, brightness and pressure;
  mp_strobe is left out on purpose.
  Without the hub the visuals keep moving on their own in TouchDesigner.
  hue_feed > Sync page shows what's coming in; td_sync_log.txt notes when the
  hub connects or stops.
  unsync_geometry() gives everything its own settings back.
  Flicker safety: the colours, build, glow and master the visuals get go
  through the same flicker protection as the lamps, the visual changes at
  most once per 1 / Flicker Guard seconds (cross-faded), and mapper effects
  never run more cycles a second than the Flicker Guard.


4b. COLOUR MATCH (desk > Setup)
-------------------------------
  One colour language everywhere. Every colour (a pad, a painted lamp, the
  picture from TouchDesigner) becomes ONE Hue colour point, the standard sRGB
  way, so the hue on the bulb is the hue on the screen. That same point is
  what the bulbs get and what Push 2's pads show: the pads are driven with
  their own red / green / blue LEDs mixed to that point (Push's LEDs and the
  Hue bulbs have very similar primaries, and Push's LED levels are linear).
  The desk shows the colour as a screen can show it.
  How hard you play a pad changes only its BRIGHTNESS, never its colour.
  Vividness (Lamps): 1 = fully saturated colours use the bulbs' deepest
  version (closest to Push's LEDs); 0 = exactly the screen colour.
  Fine-tune by eye: tap a test colour -- every lamp and every pad shows it --
  and turn down whichever of red / green / blue makes the lamps or Push look
  off. Start with white.
  Push 2 tip: plug in its power supply. On USB power alone Push dims its LEDs
  to 8 of 127, and dim LEDs can't show colours accurately (orange goes red).


4d. ABLETON PLAYS THE LIGHTS (IAC Driver) -- Push 2 stays in Live mode
------------------------------------------------------------------------
  In User mode Push 2 can't launch Live's scenes or clips. To keep Push in
  Live mode (scenes, clips, Expressive Chords) and still play the lights,
  send Live's MIDI to the hub. Each note goes through the SAME pad data as
  User mode: colour, geometry, latch, flicker protection.
  Once:
    1. Mac: Audio MIDI Setup > Window > Show MIDI Studio > double-click
       IAC Driver > tick "Device is online".
    2. Live: Settings > Link, Tempo & MIDI > Output "IAC Driver": Track on.
    3. A MIDI track: MIDI From = the track you play (Post FX to send the
       chords Expressive Chords makes), MIDI To = IAC Driver, Monitor = In.
       Clips on that track (or launched from scenes) play the lights too.
  Desk > Setup > "Ableton plays the lights":
    Notes become   "the same pads" (note number = the User-mode pad; 36-99,
                   other notes folded in by octaves) or "colours by pitch"
                   (C red, D orange, E green, G blue, A violet...; the
                   octave picks the row, so the geometry follows the register)
    Program change N plays look N -- put a program change on a clip, and a
                   scene launch changes the look
    MPE pressure per note (Expressive Chords, MPE instruments)
  Velocity = brightness, pitch bend = bends the colour, Live's stop = pads off.
  Push's User mode keeps working exactly as before (press User any time).


4c. TIMING (desk > Setup)
-------------------------
  The bulbs show a colour a little after it is sent: the bridge passes it to
  the lamps over Zigbee 25 times a second. Push 2 and the TouchDesigner
  visuals wait "Lamp delay" (60 ms to start) so all three change together.
  Press Sync test: lamps, every Push pad and the visuals swap red / blue once
  a second -- move Lamp delay until they swap at the same moment.
  Smoothing only softens BRIGHTNESS now; colour changes arrive at once.
  Push 2 PAINT mode shows every zone's live colour, in step with the bulbs.
  If Push 2 runs on USB power only it dims its LEDs (its manual: brightness
  limited to 8 of 127) and colours go wrong -- the desk says so.
  TouchDesigner: if your project uses a linear colour space (Preferences >
  Color, 2025 builds), the colours sent to the visuals and the picture sent to
  the lamps are converted, so they still match.


4e. THE GEAR PLAYS THE LIGHTS (desk > Audio)
--------------------------------------------
  Your chain: Scarlett MIDI out > Digitone > (audio + MIDI) > Digitakt >
  Evil Pet > Scarlett inputs 1 + 2. The hub listens to inputs 1 + 2 -- the
  finished sound, Evil Pet and all -- and hears the kick, the snare (claps,
  rims) and the hats, how loud the music is and how bright it sounds.
  Levels adapt to how loud you play: no calibration.

  Once (Terminal):
    python3 -m pip install --user sounddevice numpy
  then start the hub as usual. macOS asks whether Terminal may use the
  microphone the first time: Allow. (If you missed it: System Settings >
  Privacy & Security > Microphone > Terminal on, then restart the hub.)

  What it looks like -- a club rig, never a strobe. The MUSIC drives the
  brightness; the look, your pads and Ableton give the COLOURS (a dim look
  no longer means a dim show):
    Between hits  a solid, coloured room (Breathe: how much it follows
              the loudness)
    Kick      the room punches to full and settles back (a smooth swell)
    Snare     every other lamp flips to the room's accent colour and lights up
    Hats      one lamp at a time shimmers, paler and brighter
    Colour moves  the colours step round the room every bar (4 kicks) and on
              every drop; a one-colour room goes two-tone with its accent
    Drops     kick gone for ~3 s while the music plays = BREAKDOWN: the room
              goes low and pale, the build's snare rolls lift it. Kick back =
              the DROP: full brightness, full colour, and the visuals burst.
    Sound colour  off by default, so a pad's colour stays the pad's colour
  "Audio show" is how much the music takes over (0 = off, the look alone).

  TEMPO LOCK + BEAT GRID: the hub works out the tempo and where the beats
  fall from the music itself (like a DJ mixer's sync) -- the top bar says
  "heard in the music (128.0 BPM)". Once locked:
    - the kicks fire ON the beat grid, sent early (Setup > Lamp delay) so
      the bulbs light exactly on the beat instead of a beat-detector late
    - bass notes and synth stabs between the beats stop counting as kicks
    - looks, chases and the TouchDesigner visuals all run in that tempo
  If the Digitakt sends MIDI clock (Settings > MIDI config > Sync > clock
  send, with "Digitakt MIDI" On on the Audio tab), that wins -- exact.
  Your input level is fine anywhere around -6 to -18 dB peaks: the hub
  adapts to it. Turn the SPEAKERS down for the neighbours, not the Scarlett
  input gain -- the lights don't care how loud the room is.

  THE SHOW: PROGRAMMED (default) or REACTIVE (Audio tab, button by "The show")
  Programmed = a lighting operator on the beat grid. Once the hub has locked
  onto the tempo (a few seconds of music), nothing is triggered late or at
  random: the lamps move together, or in clean steps, in two colours (from
  your look / pads / Ableton) held for a whole phrase:
    Pulse      the whole room on every beat (the snare leans it to the second
               colour on 2 and 4)
    Ping-pong  the left half, then the right half, in turn
    Chase      a light runs through your order on the 8ths
    Rings      from the middle out, one ring per 16th
    Sweep      a soft band crosses the room over a bar, and back
    Columns    left to right in 16th steps, and back
    Pass       every colour moves on one bulb with each beat (the look's own
               colours if it has several -- a rainbow look passes the
               rainbow round the room -- otherwise a blend of colours A and B)
    Relay      one bulb in colour B, handed on bulb to bulb on the beat
    Wipe       each bar a new colour wipes across the room, bulb by bulb
    Mirror     colours pass outward from the middle, both ways at once
    Wheel      the colours turn round the room, once every 2 bars
    (Pass, Relay, Wipe and Mirror follow your order: Setup > Set the order.)
    Auto       a new cue every phrase (beat 1 is found from the snare on 2
               and 4), the colours trade places every other phrase; the
               breakdown goes slow and soft, the drop hits full.
  Pulses are shaped to suit the Flicker Guard (quick swell, short hold,
  decay) so it never has to squash them. If the tempo is too fast for a
  full pulse on every beat within your Flicker Guard, the room pulses on
  1 and 3 instead: Flicker Guard 2 = every beat up to ~100 BPM; 3 = every
  beat up to ~143 BPM.
  Reactive = every detected hit plays straight away (the patterns below).

  PATTERNS (Reactive): how each hit travels through the room.
    Kick: Pump (all together), Ripple out / in from a point, Wave left to
      right / right to left / bottom to top, Bounce (alternating
      directions), Spin round the centre, Chase (one lamp per kick, in your
      order). Auto = a new pattern every phrase (8 bars) and on every drop.
    Snare: its lamps (Who does what), Burst out from the centre, Left /
      right swap, Chase in your order.
    Ripples start at: the middle, the left, the right, or any lamp.
    Ripple travel: how long a hit takes to cross the room.
  The little room on the Audio tab shows your lamps live, where they are.
  Map your room once (Setup):
    1. Move lamps: ON, drag each lamp to where it really is (as the
       audience sees it), then Move lamps off.
    2. Set the order: tap the lamps one after another in the order chases
       should run (1, 2, 3 ...). "Order: left to right" undoes it.
  More pixels: your Hue Play floor lamp can show 10 zones instead of 1 --
  in Terminal, in the Hue Rig folder, run  python3 hue_stream.py scan
  then restart the hub. Ripples and waves then run along it too. Who does what: pick which
  lamps each drum plays and its colour (the lamp's own / the room's accent /
  a colour you pick). Sensitivity: higher catches quieter hits.
  When the music stops, the show steps back within ~2 seconds.
  Smoothing (Show tab) softens look and pad changes only -- the drums are
  added after it, so they keep their punch at any Smoothing.
  Self-check: the "Hearing" line (and the Terminal / hub_log.txt every 30 s)
  says whether real sound arrives. "PURE SILENCE" = macOS is blocking the
  microphone for Terminal: System Settings > Privacy & Security >
  Microphone > Terminal on, quit Terminal, start the hub again.

  Visuals: TouchDesigner gets the same hits (hue_feed > Sync page: Audio
  Kick, Snare, Hats, Loudness, Drop, Music Section). After rebuilding, run
  sync_geometry(): the geometry pumps with the kick, glows with the
  loudness, lifts on the snare, its lines shimmer with the hats and it
  bursts on the drop. Mapper FX kick with the kick.
  The hub also updates itself: when its files change it restarts as a
  fresh program in the same Terminal window (Ctrl+C still stops it).
  TouchDesigner updates itself: when build_hue_hub_td.py changes, hue_feed
  rebuilds and re-syncs the geometry on its own within a few seconds (save
  the project afterwards to keep it).
  The music picks the visual too: a new one every 2 bars (Audio tab >
  "Visuals change every": 1, 2, 4 or 8 bars) and on drops
  (sacred geometry plus six procedural pieces), slow ones in breakdowns,
  everything blended after a drop. A Push pad you touch takes over for 20 s.
  See PROCEDURAL ART NOTES.txt.
  If the geometry doesn't move: in the Textport run  geo_check()  -- it
  prints what each visual is following and saves td_check.txt in this
  folder. td_sync_log.txt also gets a heartbeat line every 15 seconds.

  Digitakt MIDI (optional, exact timing): the Digitakt's MIDI out goes into
  the Scarlett. The Audio tab lists every channel notes arrive on while it
  plays. Type a channel into kick / snare / hats and those lights hit exactly
  on its steps (the sound still covers anything without notes). If no
  channels show up, the sound alone runs the show -- nothing to set.
  Tempo: if the Digitakt sends MIDI clock (Settings > MIDI config > Sync >
  clock send), "Follow gear clock" puts the lights' beat on the gear's tempo
  (the top bar says "gear MIDI clock"). Press Play on the Digitakt so it
  sends Start: the bar count then lines up with its pattern.

  Safety: every effect still goes through the Flicker Guard (no lamp or
  visual changes more than 3 times a second, 2 by default), there are no
  white strobes, and every hit swells in over a few hundredths of a second
  instead of switching on.


4f. MOVIE MODE (Movie button, top right; settings in Setup > Movie mode)
------------------------------------------------------------------------
  The lamps take the colours of what's on the projector, around where they
  sit -- left lamps the left of the picture, and so on -- like an ambilight,
  with no Hue sync box. Only while Movie mode is on; press it again and the
  show (look, pads, music) comes back. The Flicker Guard still applies.
  Where the picture comes from (TouchDesigner builds movie_in for it):
    Capture card   PS5 / PC -> an HDMI splitter -> projector + a USB capture
                   card into this Mac. PS5: Settings > System > HDMI > turn
                   off "Enable HDCP" (games work; Netflix and other video
                   apps won't play while it's off).
    This Mac's screen  for films playing on this Mac; macOS asks once to
                   allow Screen Recording for TouchDesigner (protected
                   streaming video shows black).
    Camera         any webcam aimed at the projection -- works with anything,
                   no extra hardware. Trim its view to just the screen in
                   movie_in > camera_crop, and keep the lamps from shining on
                   the screen (they'd see themselves).
  In TouchDesigner pick the device on movie_in > capture / camera (Device).
  Brightness, Colour richness and Follow speed are in Setup > Movie mode.


5. SAFETY
---------
  Every colour goes through the flicker protection before the bulbs: no lamp,
  and not the room as a whole, can flash more than the Flicker Guard allows
  (default 2 a second, never more than 3) -- tested with a 6.7-per-second
  strobe pushed in, which came out at 2. Fast flashing light can trigger
  seizures in people with photosensitive epilepsy; this can't be switched off.


6. IF SOMETHING'S OFF
---------------------
  Desk says "Lights: not connected"   another program is streaming (old
        hue_stream.py run, Hue Sync) -- stop it, then Setup > Connect lights.
  "TD: not sending"     hue_feed's Status line says why; check it's in the
        project that's open, and Send to the Hub is on.
  Clicks in the desk inside TouchDesigner land in the wrong place:
        light_desk > Desk page > Flip Mouse Up/Down. Or use the browser.
  Your own cues from the old hue_rig were brought over as looks named
        "... (old)". The old hue_rig is left in your project, switched off.
  Everything you make is saved in hub_state.json as you go.
