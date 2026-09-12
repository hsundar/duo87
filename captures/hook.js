// Frida hook for DUO87_Play_Deck.exe -- logs its traffic with the display pad.
//
// v2 (2026-09-11). The first version filtered by transfer SIZE, and as a result
// captured no device-to-host traffic at all: three capture sessions produced
// zero ReadFile lines, so we still have no idea what the pad replies with (the
// app is known to parse ".DEVCFG", which very likely carries the panel
// resolution). This version instead tracks the HANDLE: it watches CreateFile for
// anything that looks like the pad, then logs every read and write on those
// handles whatever the size, plus the HidD_* helpers that bypass ReadFile
// entirely.

// v2.1: also track the keyboard's own HID interfaces (342d:e542), because the
// keyboard-side settings and the ".DEVCFG" reply may travel over its raw HID
// endpoint rather than through the pad. OPEN lines say which device a handle is.
const VID_MARKERS = ['vid_0600', 'pid_3001', 'hotspotek', 'vid_342d', 'pid_e542'];
const hidHandles = new Set();          // handles known to be the pad
const pending = new Map();             // overlapped ptr -> {buf, n, h}

function looksLikePad(name) {
  if (!name) return false;
  const low = name.toLowerCase();
  return VID_MARKERS.some(m => low.indexOf(m) !== -1);
}

function dump(tag, buf, n, extra) {
  if (n <= 0 || n > 4096) return;
  const bytes = new Uint8Array(buf.readByteArray(n));
  let hex = '';
  for (let i = 0; i < n; i++) hex += ('0' + bytes[i].toString(16)).slice(-2);
  send({ tag: tag, n: n, hex: hex, extra: extra || '' });
}

// --- learn which handles are the pad ---------------------------------------
const k32 = Process.getModuleByName('kernel32.dll');
['CreateFileW', 'CreateFileA'].forEach(function (fn) {
  const addr = k32.findExportByName(fn);
  if (!addr) return;
  Interceptor.attach(addr, {
    onEnter(args) {
      try {
        this.name = fn.endsWith('W') ? args[0].readUtf16String() : args[0].readAnsiString();
      } catch (e) { this.name = null; }
    },
    onLeave(ret) {
      if (this.name && looksLikePad(this.name) && !ret.equals(ptr('-1'))) {
        hidHandles.add(ret.toString());
        send({ tag: 'OPEN', n: 0, hex: '', extra: this.name });
      }
    }
  });
});

function isPad(h) {
  // Before any CreateFile is seen (e.g. when attaching to a running process)
  // fall back to the old size heuristic so nothing is missed.
  return hidHandles.size === 0 || hidHandles.has(h.toString());
}

// --- host -> device ---------------------------------------------------------
Interceptor.attach(k32.getExportByName('WriteFile'), {
  onEnter(args) {
    const n = args[2].toInt32();
    if (!isPad(args[0])) return;
    if (hidHandles.size === 0 && !(n === 1025 || n === 513 || n === 65 || n === 33)) return;
    dump('W', args[1], n);
  }
});

// --- device -> host ---------------------------------------------------------
// No size filter this time: whatever the app asks for, we log what comes back.
Interceptor.attach(k32.getExportByName('ReadFile'), {
  onEnter(args) {
    this.ok = isPad(args[0]);
    this.buf = args[1];
    this.n = args[2].toInt32();
    this.cnt = args[3];
    this.ov = args[4];
    if (this.ok && !this.ov.isNull()) pending.set(this.ov.toString(), { buf: this.buf, n: this.n });
  },
  onLeave(ret) {
    if (!this.ok) return;
    if (ret.toInt32() !== 0) {
      let got = this.n;
      try { if (!this.cnt.isNull()) got = this.cnt.readU32(); } catch (e) {}
      dump('R', this.buf, Math.min(got, this.n));
      if (!this.ov.isNull()) pending.delete(this.ov.toString());
    }
  }
});

Interceptor.attach(k32.getExportByName('GetOverlappedResult'), {
  onEnter(args) { this.ov = args[1]; this.cnt = args[2]; },
  onLeave(ret) {
    const p = pending.get(this.ov.toString());
    if (p && ret.toInt32() !== 0) {
      let got = p.n;
      try { got = this.cnt.readU32(); } catch (e) {}
      dump(p.tag ? 'IO:out' : 'R', p.buf, Math.min(got, p.n), p.tag || '');
      pending.delete(this.ov.toString());
    }
  }
});

// --- DeviceIoControl: hidapi on Windows fetches input/feature reports with
// IOCTL_HID_GET_INPUT_REPORT (0xB01A2) / IOCTL_HID_GET_FEATURE (0xB0192) and
// sends feature/output reports with 0xB0191 / 0xB0195, never via hid.dll.
// Logged as 'IO' lines: the ioctl code, the input buffer and the returned bytes.
Interceptor.attach(k32.getExportByName('DeviceIoControl'), {
  onEnter(args) {
    this.ok = isPad(args[0]);
    if (!this.ok) return;
    this.code = args[1].toUInt32();
    this.inb = args[2]; this.inn = args[3].toInt32();
    this.outb = args[4]; this.outn = args[5].toInt32();
    this.cnt = args[6]; this.ov = args[7];
    if (this.inn > 0) dump('IO:in', this.inb, this.inn, 'ioctl=0x' + this.code.toString(16));
    if (!this.ov.isNull()) pending.set(this.ov.toString(), { buf: this.outb, n: this.outn, tag: 'IO:out ioctl=0x' + this.code.toString(16) });
  },
  onLeave(ret) {
    if (!this.ok) return;
    if (ret.toInt32() !== 0) {
      let got = this.outn;
      try { if (!this.cnt.isNull()) got = this.cnt.readU32(); } catch (e) {}
      dump('IO:out', this.outb, Math.min(got, this.outn), 'ioctl=0x' + this.code.toString(16));
      if (!this.ov.isNull()) pending.delete(this.ov.toString());
    }
  }
});

// --- the HID helper APIs, which bypass ReadFile/WriteFile -------------------
// HidD_GetInputReport is how the firmware string is fetched; the others are how
// feature reports would be exchanged. Any of them may carry the ".DEVCFG" reply.
const hid = Process.findModuleByName('hid.dll');
if (hid) {
  [['HidD_GetInputReport', 'R:input'],
   ['HidD_GetFeature', 'R:feature'],
   ['HidD_SetFeature', 'W:feature'],
   ['HidD_SetOutputReport', 'W:output']].forEach(function (pair) {
    const addr = hid.findExportByName(pair[0]);
    if (!addr) return;
    Interceptor.attach(addr, {
      onEnter(args) { this.buf = args[1]; this.n = args[2].toInt32(); },
      onLeave(ret) {
        if (ret.toInt32() !== 0) dump(pair[1].startsWith('R') ? 'R' : 'W',
                                      this.buf, this.n, pair[0]);
      }
    });
  });
}

send({ tag: 'ready', n: 0, hex: '', extra: 'v2 handle-tracking' });
