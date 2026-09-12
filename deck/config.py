"""Load, validate and save the deck configuration (TOML).

Reading uses stdlib tomllib. There is no stdlib TOML writer, so `dumps` is a
small serializer for exactly the shapes this config uses: top-level scalars and
string arrays, named tables, string arrays inside tables, and arrays of inline
tables (the launcher items). It round-trips through tomllib (see tests below).

Secrets note: calendar `sources` may contain private URLs. They live only in the
user's own config file (default ~/.config/duo87/config.toml), never in the repo.
"""
import os

try:
    import tomllib
except ImportError:                      # pragma: no cover
    import tomli as tomllib

DEFAULT_PATH = os.path.expanduser('~/.config/duo87/config.toml')

CONFIG_PATHS = [
    os.environ.get('DUO87_CONFIG'),
    DEFAULT_PATH,
    'config.toml',
]

# The names the app knows how to build (kept here so the editor can offer them).
PAGE_TYPES = ['launcher', 'media', 'system', 'zoom']
CARD_TYPES = ['clock', 'nowplaying', 'weather', 'calendar']
MAX_CARDS = 3                            # slots 1..3 (slot 0 is the stock image)


def default_config():
    return {
        'brightness': 80,
        'pages': ['launcher', 'media', 'system', 'zoom'],
        'cards': ['clock', 'nowplaying'],
        'launcher': {'items': [
            {'label': 'Terminal', 'command': 'xterm'},
            {'label': 'Files', 'command': 'xdg-open .'},
        ]},
        'weather': {'place': '', 'units': 'metric'},
        'calendar': {'slots': 6, 'sources': []},
    }


def find_path():
    for p in CONFIG_PATHS:
        if p and os.path.exists(p):
            return p
    return None


def load(path=None):
    """Return (config dict, path or None). Missing file -> ({}, None)."""
    path = path or find_path()
    if not path or not os.path.exists(path):
        return {}, None
    with open(path, 'rb') as f:
        return tomllib.load(f), path


# --- serialization ----------------------------------------------------------

def _fmt_scalar(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v).replace('\\', '\\\\').replace('"', '\\"')
    return '"%s"' % s


def _fmt_array(vs):
    return '[%s]' % ', '.join(_fmt_scalar(v) for v in vs)


def _fmt_inline_table(d):
    return '{ %s }' % ', '.join('%s = %s' % (k, _fmt_scalar(v)) for k, v in d.items())


def _emit_value(out, key, value):
    if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
        out.append('%s = [' % key)
        for item in value:
            out.append('  %s,' % _fmt_inline_table(item))
        out.append(']')
    elif isinstance(value, list):
        out.append('%s = %s' % (key, _fmt_array(value)))
    else:
        out.append('%s = %s' % (key, _fmt_scalar(value)))


def dumps(cfg):
    """Serialize a config dict to TOML text (scalars/tables first, then sections)."""
    out, sections = [], []
    for key, value in cfg.items():
        if isinstance(value, dict):
            sections.append((key, value))
        else:
            _emit_value(out, key, value)
    for name, table in sections:
        out.append('')
        out.append('[%s]' % name)
        for key, value in table.items():
            _emit_value(out, key, value)
    return '\n'.join(out) + '\n'


def save(cfg, path=None):
    """Write config to `path` (default the user's config), creating the dir.

    Validates by re-parsing before replacing the file, and writes atomically.
    """
    path = path or find_path() or DEFAULT_PATH
    text = dumps(cfg)
    tomllib.loads(text)                  # raises if we produced invalid TOML
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)
    return path
