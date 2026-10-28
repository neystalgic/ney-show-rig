# =============================================================================
# HUE HUB -- VIBES: one tap sets up a whole auto show (Hue lamps + moving heads)
#
# A vibe is a recipe: which palette the room uses, how the lamps answer the music,
# and how the moving heads move and when they strobe. ENERGY (0..1) scales the
# recipe from laid-back to full-on. The Light Desk's Perform page calls:
#     POST /api {"op": "vibe", "name": "hype", "energy": 0.7}
# The flicker protection and every head safety rule still apply on top.
# =============================================================================

VIBES = {
    # name: (label, blurb, palette, recipe(e) -> settings, live)
    'dreamy': dict(label='Dreamy', blurb='Soft pastel drift, slow sweeping beams', palette='music', colours=['#7b8cff', '#c38bff', '#ff9ad5'],
                   heads=True),
    'hype': dict(label='Hype', blurb='Punchy, fast colour, beams wide open, strobe hits on drops', palette='music',
                 colours=['#ff3b6b', '#ffb02e', '#3bd5ff'], heads=True),
    'chill': dict(label='Chill', blurb='The lava rainbow, calm and steady', palette='lava', colours=['#ff8a3d', '#ffd23d', '#56d18b'],
                  heads=True),
    'rainbow': dict(label='Rainbow', blurb='The whole spectrum across the room, pulsing with the music', palette='music',
                    colours=['#ff4d4d', '#ffe14d', '#4dff88', '#4db8ff', '#b84dff'], heads=True),
    'movie': dict(label='Movie', blurb='Lamps and a soft ceiling wash follow the film', palette='sync', colours=['#2a3cff', '#7a2aff', '#ff2a7a'],
                  heads=True),
    'rest': dict(label='Rest', blurb='Everything dark', palette=None, colours=['#14161f', '#1d2030'], heads=False),
}
ORDER = ['dreamy', 'hype', 'chill', 'rainbow', 'movie', 'rest']


def lerp(a, b, t):
    return a + (b - a) * max(0.0, min(1.0, t))


def recipe(name, e):
    """(settings, live) for vibe `name` at energy e (0..1)."""
    s, live = {}, {}
    if name == 'dreamy':
        s.update(palette='music', music_attack=lerp(0.15, 0.06, e), music_release=lerp(0.9, 0.5, e), music_base=0.10,
                 music_boost=lerp(0.45, 0.68, e), music_spread=lerp(20, 40, e), music_period=lerp(160, 90, e),
                 music_from=250.0, music_to=350.0, music_sat=lerp(0.55, 0.75, e),      # blue -> violet -> pink, pastel
                 dmx_level=lerp(0.35, 0.7, e), dmx_move=lerp(0.35, 0.7, e), dmx_strobe='off')
    elif name == 'hype':
        s.update(palette='music', music_attack=0.03, music_release=lerp(0.4, 0.22, e), music_base=0.04,
                 music_boost=lerp(0.6, 0.76, e), music_spread=lerp(60, 160, e), music_period=lerp(60, 25, e),
                 music_from=None, music_to=None, music_sat=1.0,                          # the whole rainbow, full colour
                 dmx_level=lerp(0.7, 1.0, e), dmx_move=lerp(0.6, 1.0, e), dmx_strobe='phrase' if e >= 0.5 else 'drop')
    elif name == 'chill':
        s.update(palette='lava', dmx_level=lerp(0.25, 0.55, e), dmx_move=lerp(0.25, 0.5, e), dmx_strobe='off')
        live.update(speed=lerp(0.25, 0.5, e))
    elif name == 'rainbow':
        s.update(palette='music', music_attack=0.05, music_release=lerp(0.6, 0.35, e), music_base=0.12,
                 music_boost=lerp(0.5, 0.66, e), music_spread=lerp(240, 330, e), music_period=lerp(90, 40, e),
                 music_from=None, music_to=None, music_sat=1.0,
                 dmx_level=lerp(0.4, 0.85, e), dmx_move=lerp(0.4, 0.85, e), dmx_strobe='off')
    elif name == 'movie':
        s.update(palette='sync', dmx_strobe='off', dmx_movie=True, dmx_movie_level=lerp(0.3, 0.6, e), sync_idle=0.18)
    live['tint'] = 0.0                           # each vibe starts from its own colours (the Colour knob shifts them)
    return s, live
