"""Freedesktop icon-theme lookup and rasterization, for launcher tiles.

Resolves an icon *name* (e.g. "firefox", "org.gnome.Nautilus") to a file in the
system icon themes, or takes an absolute path, and rasterizes it -- SVG or PNG --
to a PIL RGBA image via GdkPixbuf (gi). No extra Python package and no Qt, so it
works on the deck's worker thread. Everything degrades to None if gi or the icon
is missing, and the caller falls back to a text tile.
"""
import functools
import glob
import os
import re
import subprocess

_BASE_DIRS = [
    os.path.expanduser('~/.local/share/icons'),
    os.path.expanduser('~/.icons'),
    '/usr/local/share/icons',
    '/usr/share/icons',
]
_PIXMAPS = ['/usr/local/share/pixmaps', '/usr/share/pixmaps']
_FALLBACK_THEMES = ['Adwaita', 'breeze', 'Papirus', 'hicolor']

_gdkpixbuf = None


def _pixbuf():
    global _gdkpixbuf
    if _gdkpixbuf is None:
        try:
            import gi
            gi.require_version('GdkPixbuf', '2.0')
            from gi.repository import GdkPixbuf
            _gdkpixbuf = GdkPixbuf
        except Exception:
            _gdkpixbuf = False
    return _gdkpixbuf or None


@functools.lru_cache(maxsize=1)
def _current_theme():
    """The desktop's configured icon theme, if we can find it."""
    out = None
    try:
        r = subprocess.run(['gsettings', 'get', 'org.gnome.desktop.interface', 'icon-theme'],
                           capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            out = r.stdout.strip().strip("'\"")
    except (OSError, subprocess.SubprocessError):
        pass
    return out or None


def _themes():
    order = []
    for t in ([_current_theme()] + _FALLBACK_THEMES):
        if t and t not in order:
            order.append(t)
    return order


@functools.lru_cache(maxsize=512)
def find_icon(name):
    """Return a file path for icon `name` (or an absolute path passed through)."""
    if not name:
        return None
    if os.path.isabs(name):
        return name if os.path.exists(name) else None

    cands = []
    for base in _BASE_DIRS:
        for theme in _themes():
            root = os.path.join(base, theme)
            if not os.path.isdir(root):
                continue
            for ext in ('svg', 'png'):
                cands.extend(glob.glob(os.path.join(root, '**', name + '.' + ext),
                                       recursive=True))
    for pm in _PIXMAPS:
        for ext in ('svg', 'png', 'xpm'):
            p = os.path.join(pm, name + '.' + ext)
            if os.path.exists(p):
                cands.append(p)
    if not cands:
        return None

    themes = _themes()

    def score(p):
        s = 0
        if os.sep + 'apps' + os.sep in p:
            s += 5000                       # prefer application icons
        # earliest matching theme wins (current theme first)
        for i, t in enumerate(themes):
            if (os.sep + t + os.sep) in p:
                s += (len(themes) - i) * 500
                break
        if p.endswith('.svg'):
            s += 300                        # scalable: crisp at any size
        m = re.findall(r'(?:^|\D)(\d{2,4})(?:x\d{2,4})?\D', p)
        if m:
            s += min(int(m[-1]), 512) // 8
        return s

    return max(cands, key=score)


def _to_pil(buf):
    from PIL import Image
    w, h = buf.get_width(), buf.get_height()
    mode = 'RGBA' if buf.get_has_alpha() else 'RGB'
    data = buf.get_pixels()
    im = Image.frombytes(mode, (w, h), data, 'raw', mode, buf.get_rowstride())
    return im.convert('RGBA')


@functools.lru_cache(maxsize=256)
def load_icon(name, size=96):
    """Resolve `name` and return a `size`x`size`-ish PIL RGBA image, or None."""
    pb = _pixbuf()
    if not pb:
        return None
    path = find_icon(name)
    if not path:
        return None
    try:
        buf = pb.Pixbuf.new_from_file_at_scale(path, size, size, True)
    except Exception:
        return None
    try:
        return _to_pil(buf)
    except Exception:
        return None


def guess_name(item):
    """Best-effort icon name for a launcher item lacking an explicit `icon`.

    Uses the first token of the command's basename (e.g. "firefox" from
    "firefox --new-window"), which matches the icon name for most apps. The user
    can always set `icon = "…"` explicitly for the rest.
    """
    if item.get('icon'):
        return item['icon']
    cmd = item.get('command')
    if isinstance(cmd, (list, tuple)):
        cmd = cmd[0] if cmd else ''
    if cmd:
        first = str(cmd).split()[0]
        return os.path.basename(first)
    return None
