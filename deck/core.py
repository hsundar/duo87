"""Page model and the main loop.

A Page produces twelve tiles and reacts to taps. The Deck owns the device, the
list of pages, and the event loop, and is the only thing that talks to the pad.

Two device facts shape this design (see PROTOCOL.md 2.6):

* Left/right swipes are pure input -- the pad does not change its own display --
  so they are used for page navigation.
* Up/down swipes make the pad switch to its own built-in page. That cannot be
  prevented, only undone, by sending DIS and repainting. The Deck does that, so
  a stray vertical swipe costs a brief flash of the stock image rather than
  leaving the user stuck on a page the application does not control.
"""
import io
import sys
import time

sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(
    __import__('os').path.abspath(__file__))))

import duo87
from . import render

KEYS = 12
COLS, ROWS = 3, 4


class Page:
    """Subclass this. The only required method is tiles().

    tiles() returns a dict {key: PIL.Image} or a list of 12 images (key order,
    1..12, left to right then top to bottom). Missing keys are left blank.
    """

    title = 'page'
    #: seconds between automatic repaints; None for a page that only changes
    #: when the user touches it.
    interval = None

    def on_show(self, deck):
        """Called when the page becomes visible."""

    def on_hide(self, deck):
        """Called when the user navigates away."""

    def on_press(self, deck, key):
        """A tile 1..12 was pressed."""

    def on_swipe(self, deck, direction):
        """Return True to consume the swipe and stop the Deck from paging."""
        return False

    def tiles(self, deck):
        raise NotImplementedError


class CanvasPage(Page):
    """A page that draws ONE image across the whole pad instead of twelve tiles.

    For anything that is a picture rather than a set of buttons -- album art, a
    graph, a clock -- thinking in tiles is the wrong model: it forces the layout
    into a 3x4 grid and wastes the space. Subclass this and implement draw();
    the framework splits the canvas, compensating for the physical dividers
    (see render.GAP), so lines stay straight across seams.

    Presses still arrive as tile numbers via on_press(), so a canvas page can
    take input -- it just is not laid out around it.
    """

    #: override to use a different bezel compensation than render.GAP
    gap = None

    @property
    def _gap(self):
        return render.GAP if self.gap is None else self.gap

    def canvas_size(self):
        """(width, height) of the virtual canvas, dividers included."""
        g = self._gap
        return (COLS * render.SIZE + (COLS - 1) * g,
                ROWS * render.SIZE + (ROWS - 1) * g)

    def row_bands(self):
        """[(y0, y1)] for each tile row: the strips that are actually visible.

        Anything drawn between two bands falls behind a divider and is lost, so
        text must sit inside one. Graphs and photographs can span freely -- the
        eye interpolates across a bezel, but it cannot read half a word.
        """
        g, size = self._gap, render.SIZE
        return [(r * (size + g), r * (size + g) + size) for r in range(ROWS)]

    def col_bands(self):
        """[(x0, x1)] for each tile column. See row_bands()."""
        g, size = self._gap, render.SIZE
        return [(c * (size + g), c * (size + g) + size) for c in range(COLS)]

    def draw(self, deck, im, d):
        """Draw on `im` (a PIL Image of canvas_size()) using ImageDraw `d`."""
        raise NotImplementedError

    # -- uncompensated overlay --------------------------------------------
    # Bezel compensation is right for pictures and wrong for words. A letter
    # that falls behind a divider is simply gone, so a compensated title reads
    # "Dil Hi T Hai Na". The overlay is therefore laid out on a contiguous
    # canvas (no gaps): every pixel of it survives, and text merely looks a
    # little more widely spaced where it crosses a divider.

    def overlay_size(self):
        return (COLS * render.SIZE, ROWS * render.SIZE)

    def overlay_row_bands(self):
        return [(r * render.SIZE, (r + 1) * render.SIZE) for r in range(ROWS)]

    def overlay_col_bands(self):
        return [(c * render.SIZE, (c + 1) * render.SIZE) for c in range(COLS)]

    def draw_overlay(self, deck, im, d):
        """Optional. Draw text here (RGBA, transparent) so nothing is lost."""

    def tiles(self, deck):
        from PIL import Image, ImageDraw
        im = Image.new('RGB', self.canvas_size(), render.BG)
        self.draw(deck, im, ImageDraw.Draw(im))
        parts = render.tile_block(im, COLS, ROWS, gap=self._gap)
        out = {render.key_at(c, r): t for (c, r), t in parts.items()}

        ov = Image.new('RGBA', self.overlay_size(), (0, 0, 0, 0))
        self.draw_overlay(deck, ov, ImageDraw.Draw(ov))
        if ov.getbbox():                      # nothing drawn -> skip the work
            size = render.SIZE
            for r in range(ROWS):
                for c in range(COLS):
                    patch = ov.crop((c * size, r * size, (c + 1) * size, (r + 1) * size))
                    if patch.getbbox():
                        key = render.key_at(c, r)
                        tile = out[key].convert('RGBA')
                        tile.alpha_composite(patch)
                        out[key] = tile.convert('RGB')
        return out


class WallpaperCard:
    """A full-panel 320x480 card shown in the pad's screensaver carousel (LOG).

    Unlike a Page there is no bezel and no tile grid: LOG lights the whole panel
    seamlessly. But the host cannot choose which card the pad displays -- the pad
    shows slot 0 (its immutable stock wallpaper) on MOD '1' and the user swipes to
    cycle through the cards the host has loaded into slots 1..3 (PROTOCOL.md 2.9).
    So a card is glanceable content the user browses, refreshed by the Deck on a
    slow cadence; it cannot take touch and cannot be summoned on demand.
    """

    title = 'card'
    #: seconds between re-uploads; keep it slow -- each LOG write costs ~1.25 s.
    #: None means "render once and never refresh" (e.g. a static photo).
    interval = 300.0

    def render(self, deck):
        """Return a 320x480 PIL.Image. The Deck rotates and encodes it."""
        raise NotImplementedError

    def prefetch(self, timeout=4.0):
        """Optional: block up to `timeout` for network data before first upload.

        Cards that fetch over the network (weather, calendar URLs) override this
        so their first appearance already shows data instead of a "loading"
        placeholder. Cards with no network leave it a no-op.
        """


class Deck:
    def __init__(self, pages, cards=(), device=None, brightness=None, log=None):
        if not pages:
            raise ValueError('a Deck needs at least one page')
        self.pages = list(pages)
        # At most three cards: slots 1..3 (slot 0 is the immutable stock image).
        self.cards = list(cards)[:duo87.SCREENSAVER_SLOTS - 1]
        self.index = 0
        self.surface = 'edit'         # 'edit' (tiles) or 'wallpaper' (carousel)
        self.d = device or duo87.Duo87()
        self._cache = {}          # key -> jpeg bytes currently on the device
        self._tile_images = {}    # key -> PIL image last drawn (for press effect)
        self._card_cache = {}     # slot -> jpeg bytes currently in that slot
        self._card_due = {}       # slot -> monotonic time of next refresh
        self._stop = False
        self._brightness = brightness
        self.log = log or (lambda *a: None)
        self._pending = None      # tile held down but not yet released
        self._pressed_key = None  # tile currently shown in its pressed state

    # -- device ------------------------------------------------------------
    @property
    def page(self):
        return self.pages[self.index]

    def start(self):
        self.d.enable()           # one DIS; does not clear what is on screen
        if self._brightness is not None:
            self.d.set_brightness(self._brightness)
        # Populate the wallpaper carousel first: a LOG write leaves the pad's
        # display in screensaver mode, so switch to the tile surface AFTER, then
        # draw. Order matters -- doing set_mode(KEYS) first left the pad showing
        # a card instead of the tiles.
        for card in self.cards:               # let network cards fetch their data
            try:
                card.prefetch()
            except Exception as e:
                self.log('card %s prefetch failed: %s' % (getattr(card, 'title', '?'), e))
        self.load_cards(force=True)           # slots 1..3
        self.d.set_mode(duo87.MODE_KEYS)      # end on the tile surface
        self.surface = 'edit'
        self.page.on_show(self)
        self.repaint(force=True)

    # -- wallpaper cards ---------------------------------------------------
    def _card_slot(self, i):
        return i + 1                          # card 0 -> slot 1 (slot 0 is stock)

    def load_cards(self, force=False):
        """Render every card and upload the ones whose image changed.

        Called at start and on each entry to wallpaper mode -- never on a
        background timer, because a LOG write flips the display off the tiles.
        Rendering is cheap (~ms); the ~1.25 s LOG write only happens when the
        rendered card actually differs from what is already in its slot, so this
        also self-heals a card whose network data arrived after the first upload.
        """
        from PIL import ImageDraw
        for i, card in enumerate(self.cards):
            slot = self._card_slot(i)
            try:
                im = card.render(self)
            except Exception as e:                 # a card must never crash the deck
                self.log('card %s render failed: %s' % (getattr(card, 'title', '?'), e))
                continue
            if im.size != (duo87.PANEL_W, duo87.PANEL_H):
                im = im.resize((duo87.PANEL_W, duo87.PANEL_H))
            im = im.convert('RGB')
            # Mask the strips the tiles cannot cover, so nothing of the card is
            # left behind the tiles when the user returns to edit mode. Done in
            # viewing orientation (before the 180 upload rotate). See CARD_MARGIN_*.
            md = ImageDraw.Draw(im)
            if render.CARD_MARGIN_RIGHT:
                md.rectangle([duo87.PANEL_W - render.CARD_MARGIN_RIGHT, 0,
                              duo87.PANEL_W, duo87.PANEL_H], fill=render.BG)
            if render.CARD_MARGIN_BOTTOM:
                md.rectangle([0, duo87.PANEL_H - render.CARD_MARGIN_BOTTOM,
                              duo87.PANEL_W, duo87.PANEL_H], fill=render.BG)
            im = im.rotate(duo87.KEY_ROTATION)
            buf = io.BytesIO(); im.save(buf, 'JPEG', quality=88)
            jpeg = buf.getvalue()
            if not force and self._card_cache.get(slot) == jpeg:
                continue                            # unchanged -- skip the slow write
            self.d.set_screensaver(jpeg, slot=slot, wait=True, refresh=True)
            self._card_cache[slot] = jpeg
            self.log('card %d -> slot %d (%s)' % (i, slot, getattr(card, 'title', '?')))

    def _next_card_due(self):
        if not self.cards:
            return None
        return min(self._card_due.get(self._card_slot(i), 0) for i in range(len(self.cards)))

    def enter_wallpaper(self):
        # The pad auto-switches to its screensaver page on a down-swipe, so we
        # only need to make sure the cards are current and track the surface.
        self.surface = 'wallpaper'
        self.load_cards()

    def enter_edit(self):
        self.d.set_mode(duo87.MODE_KEYS)
        self.surface = 'edit'
        self.repaint(force=True)

    def _encode(self, im, quality=88):
        if im.size != (render.SIZE, render.SIZE):
            im = im.resize((render.SIZE, render.SIZE))
        im = im.convert('RGB').rotate(duo87.KEY_ROTATION)   # panel is mounted upside down
        buf = io.BytesIO()
        im.save(buf, 'JPEG', quality=quality)
        return buf.getvalue()

    def repaint(self, force=False):
        """Redraw the current page, uploading only the tiles that changed.

        A full twelve-tile repaint measures ~15 ms on the real device, so this is
        cheap; the cache matters for pages that tick once a second and only
        change one or two tiles.
        """
        out = self.page.tiles(self)
        if isinstance(out, dict):
            images = {k: v for k, v in out.items()}
        else:
            images = {i + 1: im for i, im in enumerate(out)}

        sent = 0
        for key in range(1, KEYS + 1):
            im = images.get(key) or render.blank_tile()
            self._tile_images[key] = im          # kept for the press effect
            jpeg = self._encode(im)
            if force or self._cache.get(key) != jpeg:
                self.d.set_key_jpeg(key, jpeg, refresh=False)
                self._cache[key] = jpeg
                sent += 1
        if sent:
            self.d.refresh()
        return sent

    # -- touch feedback ----------------------------------------------------
    def _show_pressed(self, key):
        """Flash one tile in its pushed state (a single fast upload)."""
        im = self._tile_images.get(key)
        if im is None:
            return
        self.d.set_key_jpeg(key, self._encode(render.press_effect(im)), refresh=True)
        self._pressed_key = key

    def _restore_pressed(self):
        """Undo the press flash, redrawing the tile as it was."""
        key, self._pressed_key = self._pressed_key, None
        if key is None:
            return
        jpeg = self._cache.get(key)
        if jpeg:
            self.d.set_key_jpeg(key, jpeg, refresh=True)

    # -- navigation --------------------------------------------------------
    def goto(self, index):
        index %= len(self.pages)
        if index == self.index:
            return
        self.page.on_hide(self)
        self.index = index
        self.page.on_show(self)
        self.repaint(force=True)

    def next_page(self):
        self.goto(self.index + 1)

    def prev_page(self):
        self.goto(self.index - 1)

    def stop(self):
        self._stop = True

    # -- main loop ---------------------------------------------------------
    def run(self):
        self.start()
        try:
            while not self._stop:
                # A card refresh writes LOG, which flips the display to
                # screensaver, so it must not run while the user is on the tile
                # surface. Cards are therefore refreshed only on entry to
                # wallpaper mode (and at start) -- exactly when freshness is
                # about to be seen -- not on a background timer here.
                timeout = max(0.05, self.page.interval or 3600)
                rep = self.d.read(timeout)
                ev = self.d.parse_report(rep) if rep else None
                if ev is not None:
                    self._handle(ev)
                    continue
                # Animate the tile surface only when it is actually on screen.
                if self.surface == 'edit' and self.page.interval:
                    self.repaint()
        except KeyboardInterrupt:
            pass

    def _handle(self, ev):
        self.log('%-18s page=%s' % (ev, self.page.title))

        # A swipe begins as a press on whatever tile the finger landed on, so
        # acting on PRESS would fire a button every time the user swiped across
        # the pad. Fire on RELEASE instead, and let a DRAG cancel the pending
        # tile -- the same rule a touchscreen uses to distinguish tap from scroll.
        if ev.kind == duo87.PRESS:
            self._pending = ev.key if ev.is_tile else None
            # Immediate touch feedback: flash the tile pushed. Only on the tile
            # surface (wallpaper has no tiles), and only for a real tile.
            if ev.is_tile and self.surface == 'edit':
                self._show_pressed(ev.key)
            return

        if ev.kind == duo87.DRAG:
            # The press became a swipe: cancel both the pending tap and its flash.
            self._pending = None
            self._restore_pressed()
            return

        if ev.kind == duo87.RELEASE:
            key, self._pending = self._pending, None
            self._restore_pressed()
            if key is not None and ev.is_tile and ev.key == key:
                self.page.on_press(self, key)
            return

        if ev.kind == duo87.SWIPE_EVENT:
            self._pending = None
            self._handle_swipe(ev.direction)

    def _handle_swipe(self, direction):
        """Two surfaces, verified against the hardware (PROTOCOL.md 2.6, 2.9):

        * Horizontal (left/right) pages through the tile pages in edit mode. In
          wallpaper mode the pad cycles its own carousel and reports nothing we
          need to act on.
        * Vertical DOWN drops from edit into the wallpaper carousel (the pad
          switches to its screensaver page by itself); vertical UP climbs back
          out to the tiles. Down-then-browse, up-to-exit.
        """
        if self.surface == 'edit':
            # 'left' (a right-to-left finger motion) advances, to match both the
            # pad's own wallpaper carousel -- which is fixed in firmware and goes
            # forward on the same swipe -- and the usual convention that dragging
            # content leftward moves to the next item. 'right' goes back.
            if direction == 'left':
                self.next_page()
            elif direction == 'right':
                self.prev_page()
            elif direction == 'down':
                self.enter_wallpaper()
            # 'up' in edit mode: nothing above to go to.
        else:  # wallpaper
            if direction == 'up':
                self.enter_edit()
            # down/left/right: the pad drives its own carousel; leave it be.
