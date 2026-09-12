"""Tile and card rendering for the DUO87 pad.

Two surfaces (see PROTOCOL.md 2.7/2.9 and deck/core.py):

* Tiles: each key window is SIZE x SIZE (112, not 80 -- 80 under-fills the
  window). Pages build tiles with the helpers here so spacing, colour and font
  sizes stay consistent. CanvasPage draws one image across all 12 tiles, split
  with GAP / COL_SHIFT bezel compensation.
* Cards: a full 320x480 panel image shown via LOG in the pad's screensaver
  carousel. WallpaperCard renders these; the Deck masks CARD_MARGIN_* before
  upload so nothing lingers behind the tiles on return to edit mode.

Pillow is required for the application layer (it is only optional for the bare
duo87.py driver).
"""
from PIL import Image, ImageDraw, ImageFont

#: Tile size in device pixels. **112, not 80.** The key window on this panel is
#: ~112x112: an 80x80 image is drawn 1:1 at the window's anchor corner and the
#: remaining third of the window stays unlit, which is most of what looks like a
#: "gap" between tiles. Measured on the hardware 2026-09-11 by growing one tile
#: until it met its neighbours; 112 was also the only nearby size that rendered
#: without resampling artefacts. The vendor app sends 80x80 and under-fills too.
SIZE = 112

# --- palette ---------------------------------------------------------------
# Deliberately dark and low-saturation: the panel is small, glossy and sits in
# peripheral vision, so high-chroma backgrounds make white text hard to read.
BG        = (18, 18, 22)
FG        = (238, 238, 242)
MUTED     = (150, 152, 160)
ACCENT    = (70, 130, 230)
OK        = (60, 170, 110)
WARN      = (215, 150, 40)
ALERT     = (200, 70, 70)
SURFACE   = (34, 35, 42)

#: Wallpaper cards are 320x480, but the 12 tiles only cover part of the panel: a
#: strip along the bottom and right is reachable ONLY by LOG. Content drawn there
#: lingers behind the tiles when the user swipes back to edit (clearing it via
#: LOG-in-keystroke resets the device; bouncing through stock flickers), so the
#: Deck masks these strips to BG before upload. **Measured on the hardware
#: 2026-09-11** by lining a card up to the tile outline: right 16, bottom 36.
CARD_MARGIN_RIGHT = 16
CARD_MARGIN_BOTTOM = 36

#: Full-panel card size (mirrors duo87.PANEL_W/H).
CARD_W, CARD_H = 320, 480


def card_canvas(bg=BG):
    """A blank 320x480 card. Cards draw upright; the Deck rotates on upload."""
    return Image.new('RGB', (CARD_W, CARD_H), bg)


def card_safe():
    """(x0, y0, x1, y1) content-safe rect: inside the strips the Deck masks.

    Backgrounds may fill the whole card (the masked edges just go dark), but
    text and anything that must stay whole belongs inside this rectangle.
    """
    return (0, 0, CARD_W - CARD_MARGIN_RIGHT, CARD_H - CARD_MARGIN_BOTTOM)

# --- fonts -----------------------------------------------------------------
# Found once, by trying the usual locations on each OS before falling back to
# Pillow's bitmap default (which is tiny and ugly, but always present).
_FONT_CANDIDATES = [
    # Linux
    '/usr/share/fonts/TTF/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/noto/NotoSans-Regular.ttf',
    # macOS
    '/System/Library/Fonts/Helvetica.ttc',
    '/System/Library/Fonts/Supplemental/Arial.ttf',
    # Windows
    'C:\\Windows\\Fonts\\segoeui.ttf',
    'C:\\Windows\\Fonts\\arial.ttf',
]
_BOLD_CANDIDATES = [
    '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/noto/NotoSans-Bold.ttf',
    '/System/Library/Fonts/Helvetica.ttc',
    '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
    'C:\\Windows\\Fonts\\segoeuib.ttf',
    'C:\\Windows\\Fonts\\arialbd.ttf',
]
_cache = {}


def font(size=14, bold=False):
    key = (size, bold)
    if key not in _cache:
        for path in (_BOLD_CANDIDATES if bold else _FONT_CANDIDATES):
            try:
                _cache[key] = ImageFont.truetype(path, size)
                break
            except OSError:
                continue
        else:
            _cache[key] = ImageFont.load_default()
    return _cache[key]


def blank(bg=BG):
    return Image.new('RGB', (SIZE, SIZE), bg)


def _fit(draw, text, size, bold, max_w=SIZE - 8):
    """Shrink `size` until `text` fits the tile width. Returns the font used."""
    while size > 7:
        f = font(size, bold)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 1
    return font(7, bold)


def tile(label=None, value=None, bg=BG, fg=FG, accent=None, sub=None,
         value_size=30, label_size=12):
    """The standard tile: a big `value`, a `label` under it, optional `sub` above.

    `accent` draws a 3px bar down the left edge -- used to show state (e.g. a
    muted microphone, a page that owns the current selection) without needing a
    second colour for the whole background, which would hurt legibility.
    """
    im = blank(bg)
    d = ImageDraw.Draw(im)
    if accent:
        d.rectangle([0, 0, 2, SIZE], fill=accent)

    y = 14
    if sub:
        f = _fit(d, sub, 11, False)
        d.text((SIZE // 2, y), sub, font=f, fill=MUTED, anchor='mm')
        y += 13
    if value is not None:
        v = str(value)
        f = _fit(d, v, value_size, True)
        d.text((SIZE // 2, SIZE // 2 + (0 if not sub else 6)), v, font=f, fill=fg, anchor='mm')
    if label:
        f = _fit(d, label, label_size, False)
        d.text((SIZE // 2, SIZE - 12), label, font=f, fill=MUTED if value is not None else fg,
               anchor='mm')
    return im


def text_tile(text, bg=BG, fg=FG, size=15, bold=True, accent=None):
    """A tile that is just words, wrapped over up to three lines and centred."""
    im = blank(bg)
    d = ImageDraw.Draw(im)
    if accent:
        d.rectangle([0, 0, 2, SIZE], fill=accent)
    words, lines, cur = text.split(), [], ''
    f = font(size, bold)
    for w in words:
        trial = (cur + ' ' + w).strip()
        if d.textlength(trial, font=f) <= SIZE - 8 or not cur:
            cur = trial
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    lines = lines[:3]
    while lines and d.textlength(max(lines, key=len), font=f) > SIZE - 8 and size > 8:
        size -= 1
        f = font(size, bold)
    lh = size + 3
    y0 = SIZE // 2 - (len(lines) - 1) * lh // 2
    for i, ln in enumerate(lines):
        d.text((SIZE // 2, y0 + i * lh), ln, font=f, fill=fg, anchor='mm')
    return im


def bar_tile(label, fraction, value=None, bg=BG, colour=ACCENT):
    """A labelled horizontal meter. `fraction` is 0..1; used by the monitor page."""
    im = blank(bg)
    d = ImageDraw.Draw(im)
    frac = max(0.0, min(1.0, float(fraction)))
    d.text((SIZE // 2, 16), label, font=font(12, False), fill=MUTED, anchor='mm')
    shown = value if value is not None else '%d%%' % round(frac * 100)
    f = _fit(d, str(shown), 24, True)
    d.text((SIZE // 2, 40), str(shown), font=f, fill=FG, anchor='mm')
    x0, x1, y0, y1 = 8, SIZE - 8, 60, 68
    d.rectangle([x0, y0, x1, y1], fill=SURFACE)
    if frac > 0:
        d.rectangle([x0, y0, x0 + (x1 - x0) * frac, y1], fill=colour)
    return im


def blank_tile():
    return blank(BG)


#: Per-column extra inset (left, right) in tile pixels for button faces. Some
#: columns' physical windows are clipped -- column 1 loses pixels on its right --
#: so a button inset the same on every column gets cropped there. Column index
#: is (key - 1) % 3. Calibrated on the hardware with tools/gapcal.py --button.
COL_BUTTON_INSET = {0: (0, 22)}      # column 1: 22px extra on the right


def button_tile(icon_img=None, label=None, glyph=None, bg=BG, face=SURFACE,
                accent=None, glyph_size=40, inset=9, radius=16, icon_size=None,
                key=None, label_size=12):
    """A discrete button: a rounded face inset in the tile on a dark ground.

    Smaller than a full-bleed tile, so buttons read as buttons with breathing
    room. Shows `icon_img` (PIL RGBA) if given, else a `glyph` string, then an
    optional `label`. `accent` tints the face's left edge for state. Pass `key`
    (1..12) so a clipped column gets extra edge inset (COL_BUTTON_INSET).
    """
    im = blank(bg)
    d = ImageDraw.Draw(im)
    el, er = COL_BUTTON_INSET.get((key - 1) % 3, (0, 0)) if key else (0, 0)
    x0, y0, x1, y1 = inset + el, inset, SIZE - inset - er, SIZE - inset
    d.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=face)
    if accent:
        # a short accent tab on the left edge of the face
        d.rounded_rectangle([x0, y0 + 10, x0 + 5, y1 - 10], radius=2, fill=accent)

    has_label = bool(label)
    fcx = (x0 + x1) // 2          # centre within the face, not the whole tile
    cy = (y0 + y1) // 2 - (8 if has_label else 0)
    if icon_img is not None:
        # Icons sit comfortably inside the face rather than filling it.
        target = icon_size or (44 if has_label else 56)
        ic = icon_img.convert('RGBA')
        if max(ic.size) != target:
            sc = target / max(ic.size)
            ic = ic.resize((max(1, round(ic.width * sc)), max(1, round(ic.height * sc))),
                           Image.LANCZOS)
        im.paste(ic, (fcx - ic.width // 2, cy - ic.height // 2), ic)
    elif glyph:
        f = _fit(d, glyph, glyph_size, True, max_w=(x1 - x0) - 12)
        d.text((fcx, cy), glyph, font=f, fill=FG, anchor='mm')
    if has_label:
        f = _fit(d, label, label_size, False, max_w=(x1 - x0) - 8)
        d.text((fcx, y1 - 13), label, font=f, fill=MUTED, anchor='mm')
    return im


def icon_tile(icon_img, label=None, bg=SURFACE, accent=None, icon_size=None,
              label_size=13):
    """A tile showing an icon (PIL RGBA), optionally with a label beneath it.

    `icon_img` is composited centred; if None the caller should fall back to a
    text tile. With a label the icon sits a little higher to leave room.
    """
    im = blank(bg)
    if accent:
        ImageDraw.Draw(im).rectangle([0, 0, 2, SIZE], fill=accent)
    if icon_img is not None:
        target = icon_size or (SIZE - 30 if label else SIZE - 20)
        ic = icon_img.convert('RGBA')
        if max(ic.size) != target:
            scale = target / max(ic.size)
            ic = ic.resize((max(1, round(ic.width * scale)),
                            max(1, round(ic.height * scale))), Image.LANCZOS)
        cy = (SIZE // 2 - 10) if label else SIZE // 2
        im.paste(ic, (SIZE // 2 - ic.width // 2, cy - ic.height // 2), ic)
    if label:
        d = ImageDraw.Draw(im)
        f = _fit(d, label, label_size, False)
        d.text((SIZE // 2, SIZE - 13), label, font=f, fill=MUTED, anchor='mm')
    return im


def press_effect(im):
    """Return a "pushed" version of a tile image for touch feedback.

    Darkens the tile and draws an inset dark frame so it reads as pressed in --
    the same cue the vendor app gave on tap, which made buttons feel alive. Kept
    generic so every page's tiles get it without any per-page work.
    """
    from PIL import ImageEnhance
    out = ImageEnhance.Brightness(im.convert('RGB')).enhance(0.55)
    d = ImageDraw.Draw(out)
    d.rectangle([0, 0, SIZE - 1, SIZE - 1], outline=(0, 0, 0), width=3)
    d.rectangle([2, 2, SIZE - 3, SIZE - 3], outline=(70, 72, 82), width=1)
    return out


# --- multi-tile images ------------------------------------------------------

def key_at(col, row):
    """Tile number for a zero-based (col, row) on the 3x4 grid."""
    return row * 3 + col + 1


#: Pixels hidden by the physical divider between two adjacent tiles. The pad's
#: tiles are separate windows in a bezel, so an image split naively across them
#: looks wrong at every seam: the parts either side of a divider are drawn as if
#: they were adjacent when physically they are not. Discarding GAP pixels of
#: image per seam -- the trick video walls use -- keeps lines straight and
#: circles round across the whole block. Calibrate with tools/gapcal.py.
#: Calibrated at SIZE=112; re-run tools/gapcal.py if SIZE ever changes, because
#: the value is in tile-pixel units and does not carry over.
#:
#: 0 measured best on the hardware once SIZE was 112: at native size the tiles
#: are effectively contiguous, so no compensation is wanted. (At SIZE=80, which
#: under-filled each window by a third, 18 was best -- that was compensating for
#: unlit margin, not for a bezel.)
#:
#: A residual kink remains where a line crosses the first column's seam, because
#: column 1's image is clipped at the panel edge (its content sits a few pixels
#: off from where the canvas mapping assumes). Fixing that needs the per-tile
#: visible window and anchor measured exactly -- see PROTOCOL.md 2.7.
GAP = 0

#: Per-column and per-row crop nudges, in tile pixels, applied on top of GAP.
#: The panel's pitch is NOT uniform, so no single gap can make a line cross
#: every seam cleanly -- that is why GAP alone never worked.
#:
#: Measured on the hardware 2026-09-11 with tools/gapcal.py:
#:   column 1: +24  (clipped by the panel's left edge, so its visible width is
#:                   smaller than the others -- the 1->2 seam jumps furthest)
#:   column 2:   0  (reference)
#:   column 3:  -9
#:   rows:       0  (no row needed a nudge)
#:
#: Calibrate with:  python3 tools/gapcal.py --col N <values...>
#:                  python3 tools/gapcal.py --row N <values...>
#: Note the crop is clamped to the canvas, so a negative shift on row/column 1
#: and a positive one on the last row/column have no effect -- they would move
#: the window off the canvas. If a sweep shows "all the same", that is why.
COL_SHIFT = [24, 0, -9]
ROW_SHIFT = []


def tile_block(im, cols, rows, gap=None, col_shift=None, row_shift=None,
               col0=0, row0=0):
    """Scale `im` to cover a cols x rows block and split it into tiles.

    Returns {(col, row): image} with coordinates relative to the block, so a
    caller maps them onto real keys with key_at(). Used for album art, which
    looks far better spanning 2x2 than squeezed into one 80x80 tile.

    `gap` is the bezel compensation in image pixels per seam (default GAP); pass
    0 for a naive contiguous split. `col0`/`row0` say where the block sits on the
    3x4 grid, so the correct slice of COL_SHIFT/ROW_SHIFT is used -- a 2x2 art
    block at columns 2-3 needs those columns' shifts, not columns 1-2's.
    """
    gap = GAP if gap is None else gap
    # Lay the image out on a virtual canvas that includes the dividers, then
    # read back only the windows the tiles actually show. `gap` may be
    # fractional (and negative, for overlapping windows), so positions are
    # rounded and the canvas is sized to hold the last tile exactly.
    tw = round(cols * SIZE + (cols - 1) * gap)
    th = round(rows * SIZE + (rows - 1) * gap)
    src = im.convert('RGB')
    sw, sh = src.size
    scale = max(tw / sw, th / sh)          # cover, not fit: no letterboxing
    resized = src.resize((max(1, round(sw * scale)), max(1, round(sh * scale))),
                         Image.LANCZOS)
    rw, rh = resized.size
    left, top = (rw - tw) // 2, (rh - th) // 2
    cropped = resized.crop((left, top, left + tw, top + th))
    # Per-column / per-row nudges. The pitch is not uniform on this panel: the
    # first column is clipped by the panel edge, so its visible width is smaller
    # than the others and the seam between columns 1 and 2 jumps further than
    # the one between 2 and 3. A uniform `gap` cannot express that; these can.
    # Use the shift slice for the columns/rows this block actually occupies.
    if col_shift is None:
        gcs = COL_SHIFT or []
        cs = [gcs[col0 + i] if col0 + i < len(gcs) else 0 for i in range(cols)]
    else:
        cs = list(col_shift)
    if row_shift is None:
        grs = ROW_SHIFT or []
        rs = [grs[row0 + i] if row0 + i < len(grs) else 0 for i in range(rows)]
    else:
        rs = list(row_shift)
    cs += [0] * (cols - len(cs))
    rs += [0] * (rows - len(rs))

    out = {}
    for r in range(rows):
        for c in range(cols):
            x = max(0, min(round(c * (SIZE + gap)) + round(cs[c]), tw - SIZE))
            y = max(0, min(round(r * (SIZE + gap)) + round(rs[r]), th - SIZE))
            out[(c, r)] = cropped.crop((x, y, x + SIZE, y + SIZE))
    return out


def progress_tile(label, fraction, left_text=None, right_text=None, bg=SURFACE,
                  colour=ACCENT):
    """A tile dominated by a progress bar, with times either side."""
    im = blank(bg)
    d = ImageDraw.Draw(im)
    frac = max(0.0, min(1.0, float(fraction or 0)))
    if label:
        f = _fit(d, label, 12, False)
        d.text((SIZE // 2, 16), label, font=f, fill=FG, anchor='mm')
    x0, x1, y0, y1 = 6, SIZE - 6, 42, 48
    d.rectangle([x0, y0, x1, y1], fill=(60, 62, 70))
    if frac > 0:
        d.rectangle([x0, y0, x0 + (x1 - x0) * frac, y1], fill=colour)
    small = font(10, False)
    if left_text:
        d.text((x0, 60), left_text, font=small, fill=MUTED, anchor='lm')
    if right_text:
        d.text((x1, 60), right_text, font=small, fill=MUTED, anchor='rm')
    return im
