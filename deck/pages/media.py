"""Media control page (the interactive counterpart to the now-playing card).

Transport and volume as icon buttons, plus a small album-art thumbnail and the
title/artist. Controls whatever is playing via MPRIS (osapi.media_*). The full
-panel art view lives in the wallpaper NowPlayingCard; this page is the buttons.
"""
import os
import time

from PIL import Image

from .. import render, osapi, icons
from ..core import Page

# freedesktop icon names, with an ASCII glyph fallback if the theme lacks them.
_CONTROLS = {
    'prev':  ('media-skip-backward', '|<'),
    'play':  ('media-playback-start', '>'),
    'pause': ('media-playback-pause', '||'),
    'next':  ('media-skip-forward', '>|'),
    'voldn': ('audio-volume-low', '−'),
    'mute':  ('audio-volume-muted', 'x'),
    'volup': ('audio-volume-high', '+'),
}


def _mmss(seconds):
    if seconds is None:
        return None
    s = int(max(0, seconds))
    return '%d:%02d' % (s // 60, s % 60)


class MediaPage(Page):
    title = 'media'
    interval = 1.0

    def __init__(self, volume_step=5):
        self.volume_step = volume_step
        self._info = {}
        self._art_path = None
        self._art_tiles = None

    def on_show(self, deck):
        self._info = osapi.media_status()

    def _btn(self, which, label, accent=None):
        name, glyph = _CONTROLS[which]
        img = icons.load_icon(name, 64)
        return render.button_tile(img, label, glyph=glyph, glyph_size=30, accent=accent)

    def _art(self):
        path = self._info.get('art')
        if not path or not os.path.exists(path):
            self._art_path, self._art_tiles = None, None
            return None
        if path != self._art_path:
            try:
                with Image.open(path) as im:
                    im.load()
                    self._art_tiles = render.tile_block(im, 2, 2)
                self._art_path = path
            except Exception:
                self._art_path, self._art_tiles = None, None
        return self._art_tiles

    def tiles(self, deck):
        self._info = osapi.media_status()
        info = self._info
        playing = (info.get('status') or '').lower() == 'playing'
        out = {}

        # Rows 1-2: transport + volume as icon buttons.
        out[1] = self._btn('prev', 'prev')
        out[2] = self._btn('pause' if playing else 'play', 'pause' if playing else 'play',
                           accent=render.OK if playing else None)
        out[3] = self._btn('next', 'next')
        out[4] = self._btn('voldn', 'vol -')
        out[5] = self._btn('mute', 'mute')
        out[6] = self._btn('volup', 'vol +')

        # Rows 3-4: album art (2x2 on the right) + title/artist (left column).
        art = self._art()
        if art:
            mapping = {(0, 0): 8, (1, 0): 9, (0, 1): 11, (1, 1): 12}
            for (c, r), key in mapping.items():
                out[key] = art[(c, r)]
        else:
            for k in (8, 9, 11, 12):
                out[k] = render.blank_tile()

        title = info.get('title') or ('paused' if info.get('status') else 'nothing playing')
        out[7] = render.text_tile(title, bg=render.BG, size=13,
                                  accent=render.OK if playing else None)
        out[10] = (render.text_tile(info['artist'], bg=render.BG, size=12, fg=render.MUTED)
                   if info.get('artist') else render.blank_tile())
        return out

    def on_press(self, deck, key):
        actions = {
            1: lambda: osapi.media('previous'),
            2: lambda: osapi.media('play_pause'),
            3: lambda: osapi.media('next'),
            4: lambda: osapi.volume(-self.volume_step),
            5: lambda: osapi.volume(mute=True),
            6: lambda: osapi.volume(+self.volume_step),
        }
        act = actions.get(key)
        if act:
            act()
            time.sleep(0.2)      # let the player update its MPRIS state
            deck.repaint()
