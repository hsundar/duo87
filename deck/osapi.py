"""Operating-system adapters.

Everything platform-specific lives here so the pages stay portable. Each helper
degrades to a no-op that reports failure rather than raising, because a pad
button that silently does nothing is much better than one that kills the app.

Linux is the primary target; the Windows and macOS branches are written from the
documented behaviour of those tools and are **not tested**. They are marked so.
"""
import os
import shutil
import subprocess
import sys

LINUX = sys.platform.startswith('linux')
WINDOWS = sys.platform.startswith('win')
MACOS = sys.platform == 'darwin'


def _has(cmd):
    return shutil.which(cmd) is not None


def _run(args, **kw):
    """Fire and forget. Returns True if the process started."""
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True, **kw)
        return True
    except (OSError, ValueError):
        return False


def _capture(args, timeout=2):
    try:
        out = subprocess.run(args, capture_output=True, timeout=timeout, text=True)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


# --- launching --------------------------------------------------------------

def launch(command):
    """Start an application. `command` is a string (shell-style) or a list."""
    if isinstance(command, str):
        import shlex
        command = shlex.split(command)
    return _run(command)


def open_uri(uri):
    """Hand a URL, file or mailto: to the desktop's default handler."""
    if LINUX:
        return _run(['xdg-open', uri])
    if MACOS:
        return _run(['open', uri])
    if WINDOWS:                                   # untested
        try:
            os.startfile(uri)                     # noqa: S606  (Windows-only API)
            return True
        except (OSError, AttributeError):
            return False
    return False


# --- media control ----------------------------------------------------------
# MPRIS over D-Bus, which is what every desktop "now playing" widget uses. It
# covers Spotify, mpv, VLC, kew, Firefox and Chromium alike, including browser
# tabs, and needs no extra package: busctl ships with systemd and gdbus with
# glib. playerctl is used if present but is no longer required.

MPRIS_PREFIX = 'org.mpris.MediaPlayer2'
MPRIS_PATH = '/org/mpris/MediaPlayer2'
MPRIS_IFACE = 'org.mpris.MediaPlayer2.Player'

_PLAYERCTL = {'play_pause': 'play-pause', 'next': 'next', 'previous': 'previous',
              'stop': 'stop'}
_MPRIS_METHOD = {'play_pause': 'PlayPause', 'next': 'Next', 'previous': 'Previous',
                 'stop': 'Stop', 'play': 'Play', 'pause': 'Pause'}
# Virtual-key codes for the Windows fallback (untested).
_VK = {'play_pause': 0xB3, 'next': 0xB0, 'previous': 0xB1, 'stop': 0xB2}
# macOS key codes for System Events (untested).
_MAC_KEY = {'play_pause': 100, 'next': 101, 'previous': 98}


def _busctl():
    return LINUX and _has('busctl')


def mpris_players():
    """Bus names of every running MPRIS player, e.g. org.mpris.MediaPlayer2.kew."""
    if not _busctl():
        return []
    out = _capture(['busctl', '--user', 'list', '--no-pager', '--no-legend'])
    if not out:
        return []
    names = set()
    for line in out.splitlines():
        name = line.split()[0] if line.split() else ''
        if name.startswith(MPRIS_PREFIX + '.'):
            names.add(name)
    return sorted(names)


def _get_property(dest, name, iface=MPRIS_IFACE):
    """One MPRIS property, decoded from busctl's JSON. None if unavailable."""
    out = _capture(['busctl', '--user', 'get-property', '--json=short',
                    dest, MPRIS_PATH, iface, name])
    if not out:
        return None
    import json
    try:
        return json.loads(out).get('data')
    except (ValueError, AttributeError):
        return None


def _unwrap(value):
    """busctl JSON wraps each variant as {'type': ..., 'data': ...}."""
    if isinstance(value, dict) and set(value) == {'type', 'data'}:
        return _unwrap(value['data'])
    return value


def active_player():
    """The player to act on: one that is Playing, else Paused, else the first."""
    players = mpris_players()
    if not players:
        return None
    paused = None
    for p in players:
        status = _get_property(p, 'PlaybackStatus')
        if status == 'Playing':
            return p
        if status == 'Paused' and paused is None:
            paused = p
    return paused or players[0]


def media(action, player=None):
    """action: 'play_pause' | 'next' | 'previous' | 'stop'. True if dispatched."""
    if _busctl():
        dest = player or active_player()
        method = _MPRIS_METHOD.get(action)
        if dest and method:
            return _capture(['busctl', '--user', 'call', dest, MPRIS_PATH,
                             MPRIS_IFACE, method]) is not None
    if LINUX and _has('playerctl'):
        return _run(['playerctl', _PLAYERCTL.get(action, action)])
    if MACOS and action in _MAC_KEY:              # untested
        return _run(['osascript', '-e',
                     'tell application "System Events" to key code %d' % _MAC_KEY[action]])
    if WINDOWS and action in _VK:                 # untested
        try:
            import ctypes
            ctypes.windll.user32.keybd_event(_VK[action], 0, 0, 0)
            ctypes.windll.user32.keybd_event(_VK[action], 0, 2, 0)
            return True
        except Exception:
            return False
    return False


def media_available():
    """True if anything on this machine can report or control playback."""
    return bool(mpris_players()) or (LINUX and _has('playerctl')) or MACOS or WINDOWS


def get_volume():
    """Return (percent:int|None, muted:bool). Reads PipeWire (wpctl) or Pulse."""
    if LINUX and _has('wpctl'):
        out = _capture(['wpctl', 'get-volume', '@DEFAULT_AUDIO_SINK@'])
        if out:
            muted = 'MUTED' in out
            try:
                vol = float(out.split('Volume:')[1].split()[0])
                return int(round(vol * 100)), muted
            except (IndexError, ValueError):
                return None, muted
    if LINUX and _has('pactl'):
        vol = _capture(['pactl', 'get-sink-volume', '@DEFAULT_SINK@'])
        mut = _capture(['pactl', 'get-sink-mute', '@DEFAULT_SINK@'])
        pct = None
        if vol:
            import re
            m = re.search(r'(\d+)%', vol)
            if m:
                pct = int(m.group(1))
        return pct, (bool(mut) and 'yes' in mut)
    return None, False


def media_status():
    """Everything the pad might show about what is playing.

    Returns a dict with keys: player, status, title, artist, album, art (a local
    file path or None), position and length (seconds, or None). Values are None
    when the player does not publish them -- most do not publish Position.
    """
    blank = dict(player=None, status=None, title=None, artist=None, album=None,
                 art=None, position=None, length=None)
    if _busctl():
        dest = active_player()
        if dest:
            meta = _get_property(dest, 'Metadata') or {}
            get = lambda k: _unwrap(meta.get(k)) if isinstance(meta, dict) else None
            artist = get('xesam:artist')
            if isinstance(artist, list):
                artist = ', '.join(a for a in artist if a) or None
            length = get('mpris:length')
            pos = _get_property(dest, 'Position')
            art = get('mpris:artUrl')
            if isinstance(art, str) and art.startswith('file://'):
                from urllib.parse import unquote, urlparse
                art = unquote(urlparse(art).path)
            elif isinstance(art, str) and not os.path.exists(art):
                art = None            # remote cover art is not fetched
            return dict(player=dest.rsplit('.', 1)[-1],
                        status=_get_property(dest, 'PlaybackStatus'),
                        title=get('xesam:title') or None,
                        artist=artist or None,
                        album=get('xesam:album') or None,
                        art=art or None,
                        position=(pos / 1e6) if isinstance(pos, (int, float)) else None,
                        length=(length / 1e6) if isinstance(length, (int, float)) else None)
    if LINUX and _has('playerctl'):
        status = _capture(['playerctl', 'status'])
        meta = _capture(['playerctl', 'metadata', '--format',
                         '{{artist}}\x1f{{title}}\x1f{{album}}'])
        parts = meta.split('\x1f') if meta else []
        blank.update(status=status,
                     artist=parts[0] or None if parts else None,
                     title=parts[1] or None if len(parts) > 1 else None,
                     album=parts[2] or None if len(parts) > 2 else None)
    return blank


def volume(delta=None, mute=False):
    """Change output volume by `delta` percent, or toggle mute."""
    if delta is None and not mute:
        return False
    if LINUX:
        if _has('wpctl'):                          # PipeWire
            tgt = '@DEFAULT_AUDIO_SINK@'
            if mute:
                return _run(['wpctl', 'set-mute', tgt, 'toggle'])
            sign = '+' if delta >= 0 else '-'
            return _run(['wpctl', 'set-volume', tgt, '%d%%%s' % (abs(delta), sign)])
        if _has('pactl'):                          # PulseAudio
            tgt = '@DEFAULT_SINK@'
            if mute:
                return _run(['pactl', 'set-sink-mute', tgt, 'toggle'])
            return _run(['pactl', 'set-sink-volume', tgt, '%+d%%' % delta])
    if MACOS:                                      # untested
        if mute:
            return _run(['osascript', '-e',
                         'set volume output muted not (output muted of (get volume settings))'])
        return _run(['osascript', '-e',
                     'set volume output volume (output volume of (get volume settings) %+d)' % delta])
    return False


# --- synthetic keystrokes ---------------------------------------------------
# Needed by the Zoom page, because Zoom has no local control API -- its shortcuts
# are the only interface. This is the least portable thing in the project.
#
# Wayland deliberately forbids one application injecting input into another, so
# xdotool does not work there. ydotool does, but needs its daemon running and
# access to /dev/uinput. If neither is available the Zoom page will say so on
# screen rather than pretending to work.

def keystroke_backend():
    """Return the name of the usable backend, or None."""
    if LINUX:
        wayland = bool(os.environ.get('WAYLAND_DISPLAY'))
        if wayland and _has('ydotool'):
            return 'ydotool'
        if not wayland and _has('xdotool'):
            return 'xdotool'
        if _has('ydotool'):
            return 'ydotool'
        return None
    if MACOS or WINDOWS:
        return 'untested'
    return None


# ydotool uses Linux input-event key names; xdotool uses X keysyms.
_YDO = {'alt': 56, 'ctrl': 29, 'shift': 42, 'cmd': 125,
        'a': 30, 'v': 47, 'q': 16, 's': 31, 'h': 35, 'm': 50, 'w': 17}


def keystroke(combo):
    """Send a chord such as 'alt+a'. Returns True if it was dispatched."""
    backend = keystroke_backend()
    keys = [k.strip().lower() for k in combo.split('+')]
    if backend == 'xdotool':
        return _run(['xdotool', 'key', '+'.join(keys)])
    if backend == 'ydotool':
        codes = [_YDO.get(k) for k in keys]
        if any(c is None for c in codes):
            return False
        seq = ['%d:1' % c for c in codes] + ['%d:0' % c for c in reversed(codes)]
        return _run(['ydotool', 'key'] + seq)
    if MACOS:                                      # untested
        mods = {'cmd': 'command down', 'alt': 'option down',
                'ctrl': 'control down', 'shift': 'shift down'}
        using = [mods[k] for k in keys if k in mods]
        letters = [k for k in keys if k not in mods]
        if not letters:
            return False
        script = 'tell application "System Events" to keystroke "%s"' % letters[0]
        if using:
            script += ' using {%s}' % ', '.join(using)
        return _run(['osascript', '-e', script])
    return False


# --- system metrics ---------------------------------------------------------
# psutil if present (portable and accurate); otherwise /proc on Linux. The
# fallback means the monitor page works on a bare Python install, which matters
# because this project deliberately avoids hard dependencies.

try:
    import psutil
except ImportError:
    psutil = None

_prev_cpu = {}


def cpu_percent():
    if psutil:
        return psutil.cpu_percent(interval=None)
    if LINUX:
        try:
            with open('/proc/stat') as f:
                parts = [float(x) for x in f.readline().split()[1:]]
        except OSError:
            return None
        idle, total = parts[3] + parts[4], sum(parts)
        p_idle, p_total = _prev_cpu.get('idle', 0), _prev_cpu.get('total', 0)
        _prev_cpu['idle'], _prev_cpu['total'] = idle, total
        dt, di = total - p_total, idle - p_idle
        return None if dt <= 0 else max(0.0, min(100.0, 100.0 * (dt - di) / dt))
    return None


def memory_percent():
    if psutil:
        return psutil.virtual_memory().percent
    if LINUX:
        try:
            info = {}
            with open('/proc/meminfo') as f:
                for line in f:
                    k, v = line.split(':', 1)
                    info[k] = float(v.split()[0])
            total, avail = info['MemTotal'], info.get('MemAvailable', info['MemFree'])
            return 100.0 * (total - avail) / total
        except (OSError, KeyError, ValueError):
            return None
    return None


def disk_percent(path='/'):
    try:
        st = os.statvfs(path) if hasattr(os, 'statvfs') else None
        if st:
            used = st.f_blocks - st.f_bfree
            return 100.0 * used / st.f_blocks if st.f_blocks else None
    except OSError:
        pass
    if psutil:
        try:
            return psutil.disk_usage(path).percent
        except OSError:
            return None
    return None


def load_average():
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return None


def temperature():
    """Hottest sensor in degrees C, or None."""
    if psutil and hasattr(psutil, 'sensors_temperatures'):
        try:
            temps = psutil.sensors_temperatures() or {}
            vals = [s.current for group in temps.values() for s in group if s.current]
            if vals:
                return max(vals)
        except Exception:
            pass
    if LINUX:
        best = None
        try:
            import glob
            for p in glob.glob('/sys/class/thermal/thermal_zone*/temp'):
                try:
                    with open(p) as f:
                        v = int(f.read().strip()) / 1000.0
                    best = v if best is None else max(best, v)
                except (OSError, ValueError):
                    continue
        except Exception:
            return None
        return best
    return None


def battery_percent():
    if psutil and hasattr(psutil, 'sensors_battery'):
        try:
            b = psutil.sensors_battery()
            return b.percent if b else None
        except Exception:
            return None
    if LINUX:
        for p in ('/sys/class/power_supply/BAT0/capacity',
                  '/sys/class/power_supply/BAT1/capacity'):
            try:
                with open(p) as f:
                    return float(f.read().strip())
            except OSError:
                continue
    return None
