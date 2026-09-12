"""Media control page: album art with hidden transport controls.

The first 3x3 grid (tiles 1-9) is the album art. Transport controls are overlaid
as faint, "hidden" buttons on the art: prev on tile 4, next on 6, play/pause on
the centre column (2, 5, 8). The bottom row is volume: down / mute+level / up.

Title and artist are not written over real art; instead, when there is no cover
art we *generate* one from the title/artist (or, failing that, the filename), so
the 3x3 area always shows something meaningful. Controls act on whatever is
playing via MPRIS (osapi.media_*).
"""
import hashlib
import os
import time

from PIL import Image, ImageDraw

from .. import render, osapi, icons
from ..core import Page

_CONTROLS = {
    'prev':  ('media-skip-backward', '|<'),
    'play':  ('media-playback-start', '>'),
    'pause': ('media-playback-pause', '||'),
    'next':  ('media-skip-forward', '>|'),
    'voldn': ('audio-volume-low', '-'),
    'mute':  ('audio-volume-muted', 'x'),
    'volup': ('audio-volume-high', '+'),
}
_ART = 3 * render.SIZE                       # 3x3 art canvas size


def _hash_color(s):
    """A deep, pleasant background colour derived deterministically from text."""
    h = int(hashlib.md5((s or 'music').encode('utf-8')).hexdigest(), 16)
    hue = (h % 360) / 360.0
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(hue, 0.45, 0.42)
    return (int(r * 255), int(g * 255), int(b * 255))


def _filename_title(url):
    if not url:
        return None
    base = os.path.basename(url.split('?')[0])
    stem = os.path.splitext(base)[0]
    return stem.replace('_', ' ').replace('-', ' ').strip() or None


class MediaPage(Page):
    title = 'media'
    interval = 1.0

    def __init__(self, volume_step=5):
        self.volume_step = volume_step
        self._info = {}
        self._art_key = None                 # (art path or generated signature)
        self._art_tiles = None

    def on_show(self, deck):
        self._info = osapi.media_status()

    # -- art ---------------------------------------------------------------
    def _generate_art(self, info):
        """A placeholder cover from title/artist, or the filename, or the player."""
        title = info.get('title') or _filename_title(info.get('url')) \
            or (info.get('player') or 'No track')
        artist = info.get('artist') or info.get('album') or ''
        bg = _hash_color(title + '|' + artist)
        im = Image.new('RGB', (_ART, _ART), bg)
        d = ImageDraw.Draw(im)
        # Note in the top third, text in the bottom third: the middle row is left
        # clear for the overlaid transport controls.
        d.text((_ART // 2, _ART // 6), '♪', font=render.font(96, True),
               fill=(255, 255, 255), anchor='mm')
        f = render.font(30, True)
        while d.textlength(title, font=f) > _ART - 40 and f.size > 14:
            f = render.font(f.size - 2, True)
        d.text((_ART // 2, int(_ART * 0.70), ), title, font=f, fill=(255, 255, 255), anchor='mm')
        if artist:
            fa = render.font(22, False)
            while d.textlength(artist, font=fa) > _ART - 40 and fa.size > 12:
                fa = render.font(fa.size - 2, False)
            d.text((_ART // 2, int(_ART * 0.82)), artist, font=fa,
                   fill=(225, 225, 230), anchor='mm')
        return im

    def _art_grid(self, info):
        """{(col,row): tile} for the 3x3 art -- real cover or generated."""
        path = info.get('art')
        if path and os.path.exists(path):
            key = ('file', path)
        else:
            key = ('gen', info.get('title'), info.get('artist'), info.get('url'),
                   info.get('player'))
        if key != self._art_key:
            try:
                if key[0] == 'file':
                    with Image.open(path) as raw:
                        raw.load()
                        src = raw.convert('RGB')
                else:
                    src = self._generate_art(info)
                self._art_tiles = render.tile_block(src, 3, 3, col0=0, row0=0)
                self._art_key = key
            except Exception:
                self._art_key, self._art_tiles = None, None
        return self._art_tiles

    def _overlay_control(self, base, which):
        """Composite a faint control icon onto an art tile (a 'hidden' button)."""
        name = _CONTROLS[which][0]
        icon = icons.load_symbolic(name, 56, tint=(255, 255, 255))
        tile = base.convert('RGBA')
        # A soft dark disc so the icon reads over any art, then the icon at
        # reduced opacity so the art still shows through.
        scrim = Image.new('RGBA', tile.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(scrim)
        cx = cy = render.SIZE // 2
        sd.ellipse([cx - 34, cy - 34, cx + 34, cy + 34], fill=(0, 0, 0, 90))
        tile.alpha_composite(scrim)
        if icon is not None:
            if max(icon.size) != 48:
                icon = icon.resize((48, 48), Image.LANCZOS)
            icon = icon.copy()
            icon.putalpha(icon.getchannel('A').point(lambda a: int(a * 0.85)))
            tile.alpha_composite(icon, (cx - icon.width // 2, cy - icon.height // 2))
        return tile.convert('RGB')

    # -- rendering ---------------------------------------------------------
    def tiles(self, deck):
        self._info = osapi.media_status()
        info = self._info
        playing = (info.get('status') or '').lower() == 'playing'
        vol, muted = osapi.get_volume()
        out = {}

        art = self._art_grid(info)
        for r in range(3):
            for c in range(3):
                out[render.key_at(c, r)] = art[(c, r)] if art else render.blank_tile()

        # Hidden transport overlays on the art: prev(4), play/pause(5), next(6).
        if art:
            out[4] = self._overlay_control(out[4], 'prev')
            out[5] = self._overlay_control(out[5], 'pause' if playing else 'play')
            out[6] = self._overlay_control(out[6], 'next')

        # Bottom row: volume. Mute button shows the level and muted state.
        out[10] = self._vol_btn('voldn', 'vol -', 10)
        vol_label = 'muted' if muted else ('%d%%' % vol if vol is not None else 'mute')
        out[11] = self._vol_btn('mute' if muted else 'volup', vol_label, 11,
                                accent=render.ALERT if muted else None)
        out[12] = self._vol_btn('volup', 'vol +', 12)
        return out

    def _vol_btn(self, which, label, key, accent=None):
        name, glyph = _CONTROLS[which]
        img = icons.load_symbolic(name, 44)
        return render.button_tile(img, label, glyph=glyph, glyph_size=24,
                                  accent=accent, key=key)

    def on_press(self, deck, key):
        if key in (2, 5, 8):
            osapi.media('play_pause')
        elif key == 4:
            osapi.media('previous')
        elif key == 6:
            osapi.media('next')
        elif key == 10:
            osapi.volume(-self.volume_step)
        elif key == 11:
            osapi.volume(mute=True)
        elif key == 12:
            osapi.volume(+self.volume_step)
        else:
            return
        time.sleep(0.2)      # let the player update its MPRIS state
        deck.repaint()
