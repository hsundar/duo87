"""Entry point: build pages from config and run the deck.

    python3 -m deck              run with the default or configured pages
    python3 -m deck --once       draw the first page and exit (useful for testing)
    python3 -m deck --list       show which pages would be built, and exit
    python3 -m deck -v           log every event the pad reports

Config is TOML, looked for at (first wins):

    $DUO87_CONFIG
    ~/.config/duo87/config.toml
    ./config.toml

Without a config file it falls back to a sensible built-in set, so the app runs
out of the box on a machine it has never seen.
"""
import os
import sys

from .core import Deck
from .pages import (LauncherPage, SysMonPage, MediaPage, CalendarPage, ZoomPage,
                    NowPlayingPage)
from .cards import ClockCard, NowPlayingCard, CalendarCard, WeatherCard

try:
    import tomllib                      # Python 3.11+
except ImportError:                     # pragma: no cover
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

CONFIG_PATHS = [
    os.environ.get('DUO87_CONFIG'),
    os.path.expanduser('~/.config/duo87/config.toml'),
    'config.toml',
]

DEFAULT_LAUNCHERS = [
    {'label': 'Terminal', 'command': 'xterm'},
    {'label': 'Files', 'command': 'xdg-open .'},
    {'label': 'Browser', 'uri': 'https://duckduckgo.com'},
]


def load_config():
    for path in CONFIG_PATHS:
        if path and os.path.exists(path):
            if tomllib is None:
                print('config found at %s but no TOML parser '
                      '(Python < 3.11 needs `pip install tomli`)' % path, file=sys.stderr)
                return {}, path
            with open(path, 'rb') as f:
                return tomllib.load(f), path
    return {}, None


def build_cards(cfg):
    """Build the wallpaper carousel (up to 3 cards) from config.

    `cards` names which and in what order (stock is always slot 0). Card config
    lives in per-card sections, e.g. [weather] latitude=.. or place="..".
    """
    order = cfg.get('cards')
    if order is None:
        order = ['clock', 'nowplaying']       # work out of the box, no config
    built = []
    for name in order:
        section = cfg.get(name, {}) if isinstance(cfg.get(name), dict) else {}
        if name == 'clock':
            built.append(ClockCard(
                time_fmt=section.get('time_format', '%H:%M'),
                date_fmt=section.get('date_format', '%A'),
                sub_fmt=section.get('sub_format', '%d %B %Y')))
        elif name == 'nowplaying':
            built.append(NowPlayingCard(show_progress=section.get('progress', True)))
        elif name == 'calendar':
            built.append(CalendarCard(sources=section.get('sources', []),
                                      slots=section.get('slots', 6)))
        elif name == 'weather':
            built.append(WeatherCard(latitude=section.get('latitude'),
                                     longitude=section.get('longitude'),
                                     place=section.get('place'),
                                     units=section.get('units', 'metric')))
        else:
            print('unknown card %r in config, skipped' % name, file=sys.stderr)
    return built


BUILTIN_PAGE_TYPES = {'launcher', 'media', 'system', 'zoom', 'calendar', 'nowplaying'}


def build_pages(cfg):
    """Build the page list from config. `pages` names which, and in what order.

    A page name is either a builtin type (launcher/media/system/zoom/...) or a
    custom name whose [<name>] section sets `type`. So several launcher pages can
    coexist under different names:

        pages = ["apps", "dev", "media"]
        [apps]  type = "launcher"  items = [...]
        [dev]   type = "launcher"  items = [...]
    """
    order = cfg.get('pages') or ['launcher', 'media', 'system', 'zoom']
    built = []
    for name in order:
        section = cfg.get(name, {}) if isinstance(cfg.get(name), dict) else {}
        ptype = section.get('type') or (name if name in BUILTIN_PAGE_TYPES else None)
        title = section.get('title', name)
        if ptype == 'launcher':
            built.append(LauncherPage(section.get('items') or cfg.get('launchers')
                                      or DEFAULT_LAUNCHERS,
                                      title=title,
                                      use_icons=section.get('icons', True),
                                      labels=section.get('labels', True),
                                      icon_size=section.get('icon_size')))
        elif ptype == 'system':
            built.append(SysMonPage(disk_path=section.get('disk', '/')))
        elif ptype == 'media':
            built.append(MediaPage(volume_step=section.get('volume_step', 5)))
        elif ptype == 'calendar':
            built.append(CalendarPage(sources=section.get('sources', []),
                                      slots=section.get('slots', 9),
                                      open_command=section.get('open_command')))
        elif ptype == 'nowplaying':
            built.append(NowPlayingPage(show_progress=section.get('progress', True)))
        elif ptype == 'zoom':
            built.append(ZoomPage(shortcuts=section.get('shortcuts'),
                                  join_uri=section.get('join_uri'),
                                  personal_room=section.get('personal_room'),
                                  open_command=section.get('open_command', 'zoom')))
        else:
            print('page %r has no type (set type=... in [%s]); skipped' % (name, name),
                  file=sys.stderr)
    return built


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cfg, path = load_config()
    pages = build_pages(cfg)
    cards = build_cards(cfg)
    if not pages:
        print('no pages configured', file=sys.stderr)
        return 1

    if '--list' in argv:
        print('config  : %s' % (path or '(built-in defaults)'))
        print('edit pages (horizontal swipe):')
        for i, p in enumerate(pages):
            print('  %d. %-12s interval=%s' % (i + 1, p.title, p.interval))
        print('wallpaper cards (swipe down; slots 1..%d):' % len(cards))
        for i, c in enumerate(cards):
            print('  %d. %-12s interval=%s' % (i + 1, c.title, c.interval))
        return 0

    verbose = '-v' in argv or '--verbose' in argv
    logger = (lambda m: print('%s  %s' % (__import__('time').strftime('%H:%M:%S'), m),
                              flush=True)) if verbose else None
    deck = Deck(pages, cards=cards, brightness=cfg.get('brightness'), log=logger)
    if '--once' in argv:
        deck.start()
        print('drew %r' % deck.page.title)
        deck.d.close()
        return 0

    print('config  : %s' % (path or '(built-in defaults)'))
    print('pages   : %s' % ', '.join(p.title for p in pages))
    print('cards   : %s' % (', '.join(c.title for c in cards) or '(none)'))
    print('swipe left/right = pages; swipe down = wallpaper cards; Ctrl-C to stop')
    try:
        deck.run()
    finally:
        deck.d.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
