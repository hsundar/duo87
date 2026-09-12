#!/usr/bin/env python3
"""
duo87.py - Linux driver / CLI for the Womier DUO87 display pad (USB 0600:3001).

Stdlib only (hidraw + ioctl). Pillow is optional and only needed to convert
arbitrary images to 80x80 JPEG (`image`, `demo`).

Usage:
  duo87.py info                      show device node, firmware version
  duo87.py enable                    minimum to accept images (one DIS); keeps the screen
  duo87.py init                      full vendor hand-shake; clears the screen
  duo87.py listen [--no-heartbeat]   print every input report (press keys!)
  duo87.py demo                      draw "1".."12" on the keys (needs Pillow)
  duo87.py image KEY FILE [--raw]    put an image on KEY (1..12)
  duo87.py brightness N              0..100
  duo87.py clear [KEY]               clear one key, or all
  duo87.py refresh | wake | sleep | heartbeat | disconnect
  duo87.py raw HEX                   send one raw 1024-byte report (hex payload)
  duo87.py config HEX                send CRT QUCMD + config bytes (hex)
Options: --dev /dev/hidrawN to bypass auto-detection.
"""
import glob, io, os, struct, sys, time
from collections import namedtuple as _namedtuple

try:                            # Linux only; the hidapi backend does not need them
    import fcntl, select
except ImportError:             # pragma: no cover - Windows/macOS
    fcntl = select = None


class DeviceNotFound(Exception):
    """No DUO87 display pad on any transport."""

VID, PID = 0x0600, 0x3001
OUT_LEN = 1024          # output report payload (device wants 1024 bytes)
IN_LEN = 512            # input report length
KEY_W = KEY_H = 80      # key image size in pixels
KEY_ROTATION = 180      # the panel shows images upside down; pre-rotate (vendor app does too)
KEYS = 12               # physically 3 columns x 4 rows; key 1 = top-left, 3 = top-right, 12 = bottom-right
PANEL_W, PANEL_H = 320, 480    # full panel size (Windows session 2); LOG covers all of it
SCREENSAVER_SLOTS = 4          # LOG slots 0..3

# Display modes (MOD command, verified Windows session 2):
MODE_SCREENSAVER = b'1'        # full-panel LOG image, no touch input
MODE_KEYS = b'2'               # 12 touchable tiles (BAT)
DEFAULT_CONFIG = bytes((0x1F, 0x11, 0x00, 0x11, 0x00, 0x11))   # what the vendor app sends in QUCMD
USAGE_PAGE = 0xFFA0     # the control interface; the pad's other interface is a boot keyboard

# Swipe directions. The pad recognises swipes itself and reports the direction as
# an ASCII digit in the key byte, with state 0. See PROTOCOL.md 2.6.
SWIPE = {0x31: 'down', 0x32: 'up', 0x33: 'right', 0x34: 'left'}
OFF_TILE = 0xFF         # a touch that landed in a gap or on the margin

# event kinds yielded by parse_report()
PRESS, RELEASE, DRAG, SWIPE_EVENT = 'press', 'release', 'drag', 'swipe'

# ----------------------------------------------------------------- discovery

def find_hidraw():
    """Return the /dev/hidraw path of the vendor (0xFFA0) interface, or None."""
    for dev in sorted(glob.glob('/sys/class/hidraw/hidraw*')):
        try:
            uevent = open(os.path.join(dev, 'device', 'uevent')).read()
        except OSError:
            continue
        if 'HID_ID=0003:%08X:%08X' % (VID, PID) not in uevent:
            continue
        try:
            rd = open(os.path.join(dev, 'device', 'report_descriptor'), 'rb').read()
        except OSError:
            rd = b''
        if rd[:3] == b'\x06\xa0\xff':           # usage page 0xFFA0 -> the control interface
            return '/dev/' + os.path.basename(dev)
    return None

# ------------------------------------------------------------------- device

class HidrawTransport:
    """Linux hidraw. Stdlib only, and the default on Linux."""

    def __init__(self, path=None):
        self.path = path or find_hidraw()
        if not self.path:
            raise DeviceNotFound(
                'DUO87 display pad (%04x:%04x) not found on any /dev/hidraw*. '
                'Plugged in? udev rule installed? Try: ls -l /dev/hidraw*' % (VID, PID))
        self.fd = os.open(self.path, os.O_RDWR)

    def write(self, buf):
        n = os.write(self.fd, buf)
        if n != len(buf):
            raise IOError('short write %d/%d' % (n, len(buf)))

    def read(self, timeout=None):
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return None
        return os.read(self.fd, IN_LEN * 2)

    def input_report(self, length):
        buf = bytearray(length)
        fcntl.ioctl(self.fd, HIDIOCGINPUT(len(buf)), buf, True)
        return bytes(buf)

    def close(self):
        os.close(self.fd)


class HidApiTransport:
    """Cross-platform backend built on hidapi (`pip install hidapi`).

    This is how the driver reaches the pad on Windows and macOS, where there is
    no hidraw. Not exercised on those platforms yet -- the protocol is identical,
    only the plumbing differs."""

    def __init__(self, path=None):
        import hid
        self._hid = hid
        if path is None:
            for info in hid.enumerate(VID, PID):
                # usage_page is filled in on Windows/macOS; on Linux it may be 0,
                # in which case interface_number 0 is the vendor interface.
                if info.get('usage_page') == USAGE_PAGE or info.get('interface_number') == 0:
                    path = info['path']
                    break
            if path is None:
                raise DeviceNotFound('DUO87 display pad (%04x:%04x) not found by hidapi' % (VID, PID))
        self.path = path
        self.dev = hid.Device(path=path)
        self.dev.nonblocking = False

    def write(self, buf):
        self.dev.write(bytes(buf))

    def read(self, timeout=None):
        ms = -1 if timeout is None else max(0, int(timeout * 1000))
        data = self.dev.read(IN_LEN, ms)
        return bytes(data) if data else None

    def input_report(self, length):
        return bytes(self.dev.get_input_report(0, length))

    def close(self):
        self.dev.close()


def open_transport(path=None, backend=None):
    """Pick a transport. 'hidraw' and 'hidapi' force one; None auto-detects."""
    if backend == 'hidraw' or (backend is None and sys.platform.startswith('linux')):
        try:
            return HidrawTransport(path)
        except DeviceNotFound:
            if backend == 'hidraw':
                raise
    return HidApiTransport(path)


def _IOC(dir_, type_, nr, size):
    return (dir_ << 30) | (size << 16) | (ord(type_) << 8) | nr

def HIDIOCGINPUT(length):       # linux/hidraw.h, kernel >= 5.11
    return _IOC(3, 'H', 0x0A, length)


class Duo87:
    def __init__(self, path=None, backend=None, transport=None):
        self.t = transport or open_transport(path, backend)
        self.path = getattr(self.t, 'path', None)

    def close(self):
        self.t.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- low level -------------------------------------------------------
    def send(self, payload: bytes):
        """Write one 1024-byte output report (report id 0 prefixed)."""
        if len(payload) > OUT_LEN:
            raise ValueError('payload > %d bytes' % OUT_LEN)
        self.t.write(b'\x00' + payload + b'\x00' * (OUT_LEN - len(payload)))

    def cmd(self, name: bytes, args: bytes = b''):
        self.send(b'CRT\x00\x00' + name + args)

    def read(self, timeout=None):
        """Return one input report (bytes) or None on timeout."""
        return self.t.read(timeout)

    # --- info ------------------------------------------------------------
    def firmware_version(self):
        try:
            buf = self.t.input_report(IN_LEN + 1)      # buf[0] = report id 0
        except OSError as e:
            return '<input report failed: %s (hidraw needs kernel >= 5.11)>' % e
        return bytes(buf[1:]).split(b'\x00', 1)[0].decode('ascii', 'replace')

    # --- commands (see PROTOCOL.md) --------------------------------------
    def refresh(self):            self.cmd(b'STP')
    def wake(self):               self.cmd(b'wake')
    def sleep(self):              self.cmd(b'sleep')
    def disconnect(self):         self.cmd(b'DIS')
    def heartbeat(self):          self.cmd(b'CONNECT')
    def set_config(self, cfg: bytes):   self.cmd(b'QUCMD', cfg)
    def set_brightness(self, pct):      self.cmd(b'LIG', b'\x00\x00' + bytes([max(0, min(100, int(pct)))]))
    def clear_key(self, key):           self.cmd(b'CLE', b'\x00\x00\x00' + bytes([key]))
    def clear_all(self):                self.clear_key(0xFF)

    def enable(self):
        """The minimum needed to make the pad accept images: a single DIS.

        Until it gets this, a freshly plugged-in pad ignores BAT uploads and
        keeps showing its stock images -- the writes all succeed and nothing
        appears. Bisected against the hardware on 2026-09-11: DIS alone is both
        necessary and sufficient; wake, QUCMD and the CLE/STP block are not
        needed, and the GET_REPORT firmware read on its own does nothing.

        Unlike startup() this does NOT clear the screen, so it is the one to use
        when reconnecting to a pad that already has tiles on it."""
        self.disconnect()

    def startup(self, config=DEFAULT_CONFIG):
        """The full vendor start-up sequence, faithful to the Windows app.

        Only the leading DIS is actually required (see enable()); the rest is
        kept because it is what the vendor app does. Leaves the screen blank, so
        call it once at start-up and then draw."""
        self.firmware_version()
        self.disconnect(); time.sleep(0.05)
        self.wake();       time.sleep(0.05)
        self.set_config(config); time.sleep(0.05)
        for _ in range(2):
            self.clear_all(); self.clear_all(); self.refresh()
            time.sleep(0.05)

    def set_mode(self, mode):
        """Switch the pad between screensaver and keystroke mode (MOD command).

        mode is MODE_SCREENSAVER (b'1') or MODE_KEYS (b'2'). Verified on the
        wire in Windows session 2. The vendor app follows MODE_KEYS with a full
        CLE/BAT/STP repaint, because switching away from screensaver mode leaves
        the tile windows undefined -- callers that want tiles back must repaint.
        """
        if mode not in (MODE_SCREENSAVER, MODE_KEYS):
            raise ValueError('mode must be MODE_SCREENSAVER or MODE_KEYS')
        self.cmd(b'MOD', b'\x00\x00' + mode)

    def set_screensaver(self, jpeg: bytes, slot=0, wait=True, refresh=True):
        """Upload a full-panel JPEG to a screensaver slot (LOG command).

        This is the ONLY way to light the whole 320x480 panel, including the
        margin between and around the tiles that BAT cannot reach. Same framing
        as BAT (size:u32 BE + slot:u8, then 1024-byte chunks) but the pad writes
        it to flash and replies with an ACK ~3.5 s later; the vendor app waits
        for that reply before sending STP. The image must be 320x480, pre-rotated
        180 like tile images. Verified Windows session 2.

        Returns the ACK report (or None if wait=False / timed out).
        """
        if not (0 <= slot < SCREENSAVER_SLOTS):
            raise ValueError('slot out of range 0..%d' % (SCREENSAVER_SLOTS - 1))
        if jpeg[:2] != b'\xff\xd8':
            raise ValueError('not a JPEG')
        self.cmd(b'LOG', struct.pack('>I', len(jpeg)) + bytes([slot]))
        for off in range(0, len(jpeg), OUT_LEN):
            self.send(jpeg[off:off + OUT_LEN])
        ack = None
        if wait:
            # The flash write takes a few seconds; give it generous headroom.
            ack = self.read(timeout=8.0)
        if refresh:
            self.refresh()
        return ack

    def set_screensaver_image(self, path_or_image, slot=0, wait=True, quality=90,
                              rotate=True):
        """Any image -> 320x480 JPEG (cover-cropped, rotated 180) -> slot. Pillow."""
        from PIL import Image
        im = Image.open(path_or_image) if isinstance(path_or_image, str) else path_or_image
        im = im.convert('RGB')
        if im.size != (PANEL_W, PANEL_H):
            sw, sh = im.size
            scale = max(PANEL_W / sw, PANEL_H / sh)
            im = im.resize((max(1, round(sw * scale)), max(1, round(sh * scale))), Image.LANCZOS)
            left, top = (im.width - PANEL_W) // 2, (im.height - PANEL_H) // 2
            im = im.crop((left, top, left + PANEL_W, top + PANEL_H))
        if rotate:
            im = im.rotate(KEY_ROTATION)
        buf = io.BytesIO(); im.save(buf, 'JPEG', quality=quality)
        return self.set_screensaver(buf.getvalue(), slot=slot, wait=wait)

    def set_key_jpeg(self, key, jpeg: bytes, refresh=True):
        """Upload an 80x80 JPEG to key 1..12. Raw JPEGs are sent as-is: the panel
        displays them rotated 180 degrees, so rotate before encoding."""
        if not (1 <= key <= 0xFE):
            raise ValueError('key out of range')
        if jpeg[:2] != b'\xff\xd8':
            raise ValueError('not a JPEG')
        self.cmd(b'BAT', struct.pack('>I', len(jpeg)) + bytes([key]))
        for off in range(0, len(jpeg), OUT_LEN):
            self.send(jpeg[off:off + OUT_LEN])
        if refresh:
            self.refresh()

    def set_key_image(self, key, path_or_image, refresh=True, quality=90, rotate=True):
        """Any image file (or PIL image) -> 80x80 JPEG (rotated 180) -> key. Needs Pillow."""
        from PIL import Image
        im = Image.open(path_or_image) if isinstance(path_or_image, str) else path_or_image
        im = im.convert('RGB')
        if im.size != (KEY_W, KEY_H):
            im = im.resize((KEY_W, KEY_H), Image.LANCZOS)
        if rotate:
            im = im.rotate(KEY_ROTATION)   # panel is mounted upside down: pre-rotate 180
        buf = io.BytesIO(); im.save(buf, 'JPEG', quality=quality)
        self.set_key_jpeg(key, buf.getvalue(), refresh)

    # --- events ----------------------------------------------------------
    @staticmethod
    def parse_report(rep: bytes):
        """Decode one input report into an Event, or None if it is not one.

        Returns an Event whose .kind is one of:
          PRESS / RELEASE  -- .key is 1..12, or OFF_TILE (0xFF) for a touch that
                              landed in a gap between tiles or on the margin
          DRAG             -- the contact became a swipe; .key is where it started
                              and is NOT reliable (a swipe from a divider reports
                              0xFF, and some swipes report no tile at all)
          SWIPE_EVENT      -- .direction is 'left'/'right'/'up'/'down'

        Only act on SWIPE_EVENT for gestures. In particular do not treat the
        direction codes 0x31..0x34 as tiles 49..52. See PROTOCOL.md 2.6."""
        if len(rep) < 11 or rep[0:3] != b'ACK' or rep[5:7] != b'OK':
            return None
        key, state = rep[9], rep[10]
        if state == 0 and key in SWIPE:
            return Event(SWIPE_EVENT, None, SWIPE[key])
        if state == 0x02:
            return Event(DRAG, key, None)
        return Event(PRESS if state else RELEASE, key, None)

    @staticmethod
    def parse_event(rep: bytes):
        """Old two-tuple interface: (key, state) or None. Kept for the CLI.

        Note this cannot express swipes -- it reports a direction code as if it
        were a tile. Prefer parse_report()."""
        if len(rep) >= 11 and rep[0:3] == b'ACK' and rep[5:7] == b'OK':
            return rep[9], rep[10]
        return None

    def events(self, timeout=None):
        """Yield Events until timeout (None = forever). Unknown reports are skipped."""
        end = None if timeout is None else time.time() + timeout
        while end is None or time.time() < end:
            rep = self.read(None if end is None else max(0, end - time.time()))
            if rep is None:
                return
            ev = self.parse_report(rep)
            if ev is not None:
                yield ev

    def wait_key(self, timeout=None):
        """Block for the next key event -> (key, pressed) ; None on timeout."""
        end = None if timeout is None else time.time() + timeout
        while True:
            rep = self.read(None if end is None else max(0, end - time.time()))
            if rep is None:
                return None
            ev = self.parse_event(rep)
            if ev:
                return ev

class Event(_namedtuple('Event', 'kind key direction')):
    """One thing the pad reported. See Duo87.parse_report()."""
    __slots__ = ()

    @property
    def is_tile(self):
        return self.key is not None and 1 <= self.key <= KEYS

    def __str__(self):
        if self.kind == SWIPE_EVENT:
            return 'swipe %s' % self.direction
        where = 'off-tile' if self.key == OFF_TILE else 'key %s' % self.key
        return '%s %s' % (self.kind, where)


# ---------------------------------------------------------------------- CLI

def _demo_images():
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype('DejaVuSans-Bold.ttf', 40)
    except OSError:
        font = ImageFont.load_default()
    for key in range(1, KEYS + 1):
        im = Image.new('RGB', (KEY_W, KEY_H), (0, 40 + key * 15, 120))
        d = ImageDraw.Draw(im)
        d.rectangle([2, 2, KEY_W - 3, KEY_H - 3], outline=(255, 255, 255), width=2)
        d.text((KEY_W // 2, KEY_H // 2), str(key), fill=(255, 255, 255), font=font, anchor='mm')
        yield key, im


def main(argv):
    dev_path = None
    if '--dev' in argv:
        i = argv.index('--dev'); dev_path = argv[i + 1]; del argv[i:i + 2]
    if not argv:
        print(__doc__); return 1
    op, args = argv[0], argv[1:]
    d = Duo87(dev_path)
    try:
        if op == 'info':
            print('device  :', d.path)
            print('firmware:', d.firmware_version())
        elif op == 'listen':
            print('device  :', d.path, ' firmware:', d.firmware_version())
            if '--no-heartbeat' in args:
                print('heartbeat DISABLED (testing whether the pad cares)')
            print('press keys on the pad (Ctrl-C to stop); heartbeat every 10 s')
            last_hb = time.time()
            while True:
                rep = d.read(1.0)
                if rep is not None:
                    ev = d.parse_report(rep)
                    print('%s len=%d %-18s %s' % (time.strftime('%H:%M:%S'), len(rep),
                                                  ev or 'unknown', rep[:12].hex(' ')))
                if '--no-heartbeat' not in args and time.time() - last_hb > 10:
                    d.heartbeat(); last_hb = time.time()
        elif op == 'enable':
            d.enable(); print('DIS sent; pad will now accept images')
        elif op == 'init':
            d.startup(); print('full hand-shake sent; screen blank')
        elif op == 'demo':
            d.startup()
            for key, im in _demo_images():
                d.set_key_image(key, im, refresh=False)
            d.refresh(); print('drew 1..%d' % KEYS)
        elif op == 'image':
            key, path = int(args[0]), args[1]
            data = open(path, 'rb').read()
            if data[:2] == b'\xff\xd8' and '--raw' in args:
                d.set_key_jpeg(key, data)
            else:
                d.set_key_image(key, path)
            print('key %d <- %s' % (key, path))
        elif op == 'brightness':
            d.set_brightness(int(args[0])); print('brightness', args[0])
        elif op == 'clear':
            if args: d.clear_key(int(args[0]))
            else:    d.clear_all()
            d.refresh()
        elif op == 'refresh':     d.refresh()
        elif op == 'wake':        d.wake()
        elif op == 'sleep':       d.sleep()
        elif op == 'heartbeat':   d.heartbeat()
        elif op == 'disconnect':  d.disconnect()
        elif op == 'raw':         d.send(bytes.fromhex(args[0]))
        elif op == 'config':      d.set_config(bytes.fromhex(args[0]))
        else:
            print(__doc__); return 1
    except KeyboardInterrupt:
        pass
    finally:
        d.close()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
