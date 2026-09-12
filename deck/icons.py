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


def _score_path(p, themes):
    s = 0
    if os.sep + 'apps' + os.sep in p:
        s += 5000                           # prefer application icons
    for i, t in enumerate(themes):          # current theme first
        if (os.sep + t + os.sep) in p:
            s += (len(themes) - i) * 500
            break
    if p.endswith('.svg'):
        s += 300                            # scalable: crisp at any size
    m = re.findall(r'(?:^|\D)(\d{2,4})(?:x\d{2,4})?\D', p)
    if m:
        s += min(int(m[-1]), 512) // 8
    return s


@functools.lru_cache(maxsize=1)
def _index():
    """Build {name: best path} and the set of app-icon names, in one bounded scan.

    Icon themes lay files out three levels below the theme root (size/category/
    name or category/size/name), so a fixed-depth glob finds everything without
    the recursive `**` walk that made per-name lookups pathologically slow (and
    hung the icon picker). Built once and cached.
    """
    themes = _themes()
    best = {}                               # name -> (score, path)
    apps = set()

    def consider(name, path):
        sc = _score_path(path, themes)
        cur = best.get(name)
        if cur is None or sc > cur[0]:
            best[name] = (sc, path)

    for base in _BASE_DIRS:
        for theme in themes:
            root = os.path.join(base, theme)
            if not os.path.isdir(root):
                continue
            for ext in ('svg', 'png'):
                for path in glob.glob(os.path.join(root, '*', '*', '*.' + ext)):
                    name = os.path.splitext(os.path.basename(path))[0]
                    consider(name, path)
                    if os.sep + 'apps' + os.sep in path:
                        apps.add(name)
    for pm in _PIXMAPS:
        for ext in ('svg', 'png', 'xpm'):
            for path in glob.glob(os.path.join(pm, '*.' + ext)):
                name = os.path.splitext(os.path.basename(path))[0]
                consider(name, path)
                apps.add(name)
    return {k: v[1] for k, v in best.items()}, apps


def find_icon(name):
    """Return a file path for icon `name` (or an absolute path passed through)."""
    if not name:
        return None
    if os.path.isabs(name):
        return name if os.path.exists(name) else None
    return _index()[0].get(name)


def _to_pil(buf):
    from PIL import Image
    w, h = buf.get_width(), buf.get_height()
    mode = 'RGBA' if buf.get_has_alpha() else 'RGB'
    data = buf.get_pixels()
    im = Image.frombytes(mode, (w, h), data, 'raw', mode, buf.get_rowstride())
    return im.convert('RGBA')


@functools.lru_cache(maxsize=256)
def load_icon(name, size=96, tint=None):
    """Resolve `name` and return a `size`-ish PIL RGBA image, or None.

    `tint` (r, g, b) recolours the icon to that colour using its alpha as a
    mask -- for monochrome *symbolic* icons, which are usually dark and would be
    invisible on a dark button. Do not tint full-colour app icons.
    """
    pb = _pixbuf()
    if not pb:
        return None
    path = find_icon(name)
    if not path:
        return None
    try:
        buf = pb.Pixbuf.new_from_file_at_scale(path, size, size, True)
        im = _to_pil(buf)
    except Exception:
        return None
    if tint is not None:
        from PIL import Image
        solid = Image.new('RGBA', im.size, (tint[0], tint[1], tint[2], 0))
        solid.putalpha(im.getchannel('A'))
        return solid
    return im


def load_symbolic(name, size=96, tint=(235, 235, 240)):
    """A monochrome control icon recoloured light: try `name`-symbolic, then `name`.

    Used by control pages (media, zoom) so icons read on dark buttons. Falls back
    to None -> the caller shows a text glyph.
    """
    return (load_icon(name + '-symbolic', size, tint=tint)
            or load_icon(name, size, tint=tint))


def list_icon_names():
    """Sorted app-icon names available in the themes (for the settings picker)."""
    apps = _index()[1]
    return sorted(n for n in apps if not n.endswith('-symbolic'))


def icon_path(name):
    """Path for `name` without theme scoring -- for fast picker previews."""
    return find_icon(name)


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
