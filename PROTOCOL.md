# Womier DUO87 display pad — USB/HID interface notes

Reverse-engineered on Windows 11 on 2026-09-11 from the vendor app
`DUO87_Play_Deck` (a rebranded MiraBox / HotSpot "Stream Dock" app, version
3.10.203.0820) by hooking its HID writes with Frida, by talking to the device
directly with hidapi, and by cross-checking against the public MiraBox
Stream Dock SDK. Anything marked **verified** was observed on the wire or
executed successfully against this unit. Anything marked *from SDK/binary*
was not exercised on this unit.

**Re-verified on Linux on 2026-09-11** (Manjaro, kernel 6.12.103, `duo87.py`
against the real pad): firmware read, start-up hand-shake, key images and
orientation, all twelve key codes, and brightness. Items confirmed on Linux
say so explicitly below.

## 1. Two USB devices, not one

The DUO87 enumerates as two independent USB devices:

| Role | VID:PID | Manufacturer / product strings | Interfaces |
|---|---|---|---|
| Keyboard | `342d:e542` | `ET` / `DUO87` (bcdDevice 0x0012) | IF0 boot keyboard; **IF1 raw HID, usage page `0xFF60` usage `0x61`, 32-byte in/out reports** (QMK/VIA raw HID); IF2 mouse + consumer + system control + NKRO keyboard |
| Display pad | `0600:3001` | `HOTSPOTEKUSB` / `HOTSPOTEKUSB HID DEMO` (bcdDevice 0x0002), serial `8730DB780B26` | **IF0 vendor HID, usage page `0xFFA0` usage `0x01`**; IF1 boot keyboard |

The vendor app only ever opens the **display pad, interface 0**. Everything
below is about that interface unless stated otherwise.

The keyboard's interface 1 is a standard QMK "raw HID" endpoint (report
descriptor: usage page FF60, usage 61, 32-byte input + 32-byte output). On
Linux that means the keymap side is most likely configurable with VIA
(`usevia.app` over WebHID) or Vial without any reverse engineering.
This was not tested.

## 2. Display pad HID interface (0600:3001, IF0)

Report descriptor (70 bytes, no report IDs):

```
06 A0 FF        Usage Page (vendor 0xFFA0)
09 01           Usage 1
A1 01           Collection Application
  09 02  A1 00  Collection Physical
    06 A1 FF    Usage Page 0xFFA1
    09 03 ... 75 08 95 01 81 02        Input  1 byte
    09 04 ... 75 08 96 FF 01 81 02     Input  511 bytes    -> input report  = 512 bytes
    09 05 ... 75 08 95 01 91 02        Output 1 byte
    09 06 ... 75 08 96 FF 03 91 02     Output 1023 bytes   -> output report = 1024 bytes
  C0
C0
```

* **Output (host to device): 1024-byte reports.** With hidapi/hidraw you
  write 1025 bytes: a leading `0x00` report-ID byte plus 1024 payload bytes,
  zero padded.
* **Input (device to host): 512-byte reports.** On Linux hidraw the data
  starts at byte 0 (no report-ID byte).
* No feature reports.

### 2.1 Firmware version — **verified**

A HID `GET_REPORT` control transfer for *input* report 0
(`bmRequestType 0xA1, bRequest 0x01, wValue 0x0100, wIndex = interface`)
returns an ASCII string. This unit answers `V3.X106_3_5.02.012`.

* hidapi: `dev.get_input_report(0, 513)` -> `b'\x00V3.X106_3_5.02.012'`
* Linux hidraw: `ioctl(fd, HIDIOCGINPUT(513), buf)` with `buf[0] = 0`
  (kernel 5.11+), string is in `buf[1:]`. **Verified on Linux** (kernel
  6.12.103): returns the same `V3.X106_3_5.02.012`.

The "V3" prefix is what the MiraBox SDK uses to select the "V3" command
set below (the same family as the Stream Dock 293V3 / N3 / N4).

### 2.2 Command packet format

Every command is one 1024-byte output report that starts with the 5-byte
prefix `43 52 54 00 00` (`"CRT\0\0"`) followed by an ASCII command name and
arguments. Unused bytes are zero. Offsets below are payload offsets
(i.e. after the report-ID byte).

| Command | Bytes (payload) | Status | Meaning |
|---|---|---|---|
| Set key image | `CRT\0\0BAT` + `size:uint32 BE` (offset 8..11) + `key:uint8` (offset 12), then the JPEG in following 1024-byte reports (raw, no header, last one zero padded) | **verified (captured + sent, Linux)** | Upload a JPEG for one key. Not shown until `STP`. **The pad ignores `BAT` entirely until it has had the start-up hand-shake of section 2.5** — see the warning there. |
| Refresh | `CRT\0\0STP` | **verified** | Commit / redraw what was uploaded. The app sends it after every batch of `BAT`s. |
| Clear key | `CRT\0\0CLE\0\0\0` + `key` (offset 11) | **verified (captured)** | `key = 0xFF` clears all keys. App sends `CLE FF` twice, then `STP`, at start-up. |
| Wake | `CRT\0\0wake` | **verified (captured)** | Sent by the app right after opening the device. |
| Disconnect / reset | `CRT\0\0DIS` | **verified on Linux; the important one** | Sent by the app *before* `wake` at start-up; SDK calls it `disconnected()`. On this device it is what puts the pad under host control: **without it, image uploads are silently ignored** (section 2.5). Harmless to repeat, and it does not clear the screen. |
| Device config | `CRT\0\0QUCMD` + N config bytes | **verified (captured)** | App sends `1F 11 00 11 00 11` at start-up. In the SDK this is `set_device_config()`: one byte per setting, `0x11` = on, `0xFF` = off, `0x1F` = follow/default. The meaning of the six positions for this device is unknown. |
| Heartbeat | `CRT\0\0CONNECT` | **verified (captured); shown to be optional** | App sends it every 10 s. Device does **not** reply. **Tested on Linux: after 5 minutes with no `CONNECT` at all, the pad still accepted a `BAT`+`STP` upload and still reported key presses.** So it is not a keep-alive the host must maintain, at least on that timescale. Sending it anyway is cheap and matches the vendor. |
| Brightness | `CRT\0\0LIG\0\0` + `value` (offset 10), value 0..100 | **verified on Linux** | Screen brightness, 0..100. Swept 100/10/50/0/100 and watched: the panel dims and brightens as expected. **`0` is a floor, not off** — the screen stays faintly lit. Use `sleep` to actually blank it. |
| Sleep | `CRT\0\0sleep` | **verified on Linux** | Blanks the screen. **Touching the panel wakes it again on its own** — no `wake` command needed — and the display comes back **showing exactly the tiles it had before, with nothing redrawn by the host** (confirmed by eye). So an application does not need to restore its tiles after a sleep. Key events keep being delivered while the screen is dark, and the touch that wakes it reports its tile normally. `wake` still works to wake it from the host. |
| Full-screen image ("screensaver") | `CRT\0\0LOG` + `size:uint32 BE` (offset 8..11) + `slot:uint8` (offset 12, 0..3), then the JPEG in 1024-byte reports exactly like `BAT`. **The pad replies** with a 512-byte `ACK\0\0OK\0\0\0\0\0` (bytes 9 and 10 both `0x00`) about 3.5 s later, and the app sends `STP` only after that reply. | **verified (captured 2026-09-11, Windows session 2)** | A **320x480 JPEG**, pre-rotated 180 like the tiles, stored in one of four screensaver slots. It lights the **entire panel including the bottom/right margin** that `BAT` cannot reach (confirmed by eye). See 2.8. |
| Mode switch | `CRT\0\0MOD\0\0` + ASCII digit (offset 10): `'1'` = screensaver mode, `'2'` = keystroke (tile) mode | **verified (captured)** | The app sends `MOD '1'` when the user picks "Screensaver Mode" and `MOD '2'` + full repaint (`CLE FF` x2, `BAT` x N, `STP`) when going back to "Keystroke Mode". Corresponds to the SDK's `change_mode()`. |
| Other tokens found in the app binary | `HAN`, `SETLB`, `LBLIG`, `RGBS`, `LAYER`, `DELED`, `INTVID`, `WEB` (`CRT\0\0WEB\0\0\x01`) | *untested* | Probably keyboard-side settings (LED brightness, RGB, layer, OS mode) relayed through this device. The app also parses text replies beginning with `.DEVCFG` (keys `os`, `scr`, `led_info`, `mode`, `speed`, `brightness`), `rc:` and a JSON blob starting with `{"size"`. |

### 2.3 Key images — **verified**

* Format: baseline JPEG (JFIF), RGB, **80 x 80 pixels**. The app uses
  quality ~90; a typical icon is 5-6 KB, i.e. 6 reports.
* Orientation: **the panel displays each key image rotated 180 degrees**
  (verified: un-rotated test digits appeared upside down; the vendor app's
  captured clock icon is only in its natural layout after a 180 degree
  rotation). Rotate every image 180 degrees before JPEG-encoding it, like the
  293V3 class in the SDK (`key_rotate_angle = 180`). `duo87.py` does this.
  **Confirmed on Linux**, twice over: with `KEY_ROTATION = 180` the digits
  drawn by `duo87.py demo` read upright on the panel; and the captured vendor
  JPEG in `captures/` displays *upside down* if you let `duo87.py` rotate it,
  because it came off the wire already in device orientation.
* Therefore: JPEGs captured from the vendor app (or any JPEG already in device
  orientation) must be sent **unrotated** — `Duo87.set_key_jpeg()`, or
  `duo87.py image KEY FILE --raw`. `set_key_image()` is for ordinary images
  that are the right way up in the file.
* Key numbering (verified by eye): **3 columns x 4 rows** physically, key 1
  is top-left, key 3 top-right, counting left to right then top to bottom,
  key 12 bottom-right. (The vendor app describes it to plugins as 4x3, which
  is just its on-screen layout.) **Confirmed on Linux**: `duo87.py demo` puts
  1 top-left, 3 top-right and 12 bottom-right, all upright.
* Sequence per key: `BAT(size,key)`, then `ceil(size/1024)` data reports,
  then `STP`. Several keys can be uploaded before a single `STP`.

Capture sample (payload bytes, key 4, 5759-byte JPEG):

```
43525400 00 424154 0000167f 04 00...      "CRT\0\0BAT" size=0x167f key=4
ffd8ffe000104a464946...  (1024 bytes)     JPEG chunk 1
...                                       chunks 2..5
...ffd9 00 00 ...        (639 bytes + pad) JPEG chunk 6
43525400 00 535450 00...                  "CRT\0\0STP"
```

### 2.4 Key events (device to host) — **verified**

512-byte input report, one on press and one on release:

```
41 43 4B 00 00 4F 4B 00 00 kk ss 00 ...
'A' 'C' 'K'       'O' 'K'       ^  ^
                                |  state: 0x01 = pressed, 0x00 = released (offset 10)
                                key code (offset 9)
```

Observed on this unit (`captures/key_press_input_reports.log`): all twelve
tiles report codes `0x01..0x0C`, i.e. **the tile number is the key code**
(same numbering as `BAT`). The pad has no other buttons.

**`0xFF` = a touch that hit no tile — solved 2026-09-11.** It is the code the
firmware reports for a press in the gaps between tiles or on the margin around
the grid. It is a normal, complete DOWN/UP pair, indistinguishable from a real
press except for the code, so it is a deliberate report rather than a glitch.

Evidence: tapping only the dividers and the outer margin produced `0xFF` for
**9 of 11** taps (the other two landed on tiles 6 and 9 and reported those
numbers), while 22 deliberate tile-centre presses across the whole grid produced
**zero** `0xFF`. This also explains both earlier sightings: the Windows burst
`04 FF 05 06 FF 08 07 FF FF` was a fast sweep clipping the dividers, and the
Linux one was a blind touch at a dark screen after `sleep`.

Applications should simply ignore any code outside 1..12 — or treat `0xFF` as
"touched, but not on a button", which is a usable signal in its own right (e.g.
to wake a screensaver without activating anything).

**Re-verified on Linux**: every tile 1..12 was pressed and each reported its
own number, one `state=1` report on press and one `state=0` on release, e.g.
`41434b00004f4b0000 0c 01 00` for tile 12 down.

`0xFF` was seen once more on Linux, as a clean DOWN/UP pair immediately
followed by a normal `key=6` DOWN/UP, on the first touch after a `sleep`. An
early guess — "the touch that wakes the panel reports 0xFF" — was tested and
disproved (a second sleep/touch cycle reported `key=1`). The real cause is the
off-tile touch described above.

The device sends nothing in response to `CONNECT`, `QUCMD`, `wake` or image
uploads. The pad itself does nothing when a key is pressed; acting on the
event is entirely the host application's job.

### 2.5 Start-up — **`DIS` is the only part that matters**

**A freshly plugged-in pad silently ignores `BAT` uploads and keeps showing its
stock images until it receives `CRT\0\0DIS`.** The writes all succeed, the
device NAKs nothing, and nothing changes on screen — which is exactly what
happened on the first Linux attempt. One `DIS` and the same `BAT` + `STP` code
works immediately. It is needed once per plug-in, not once per process.

**Bisected against the hardware on 2026-09-11**, one physical replug per trial
(a replug is the only known way back to stock mode):

| Prefix sent after replug, then `BAT`+`STP` | Images appear? |
|---|---|
| `wake` only | **no** |
| `GET_REPORT` (firmware read) only | **no** |
| `DIS` only | **yes** |
| `DIS`, `wake` | yes |
| `DIS`, `wake`, `QUCMD`, `CLE FF`x2/`STP`, `CLE FF`x2/`STP` (full vendor) | yes |

So `DIS` alone is necessary and sufficient; `wake`, `QUCMD` and the `CLE`/`STP`
block are vendor ceremony. Note the irony that the SDK calls this one
`disconnected()` — on this device it is what *attaches* the pad to the host.

`Duo87.enable()` / `duo87.py enable` sends just the `DIS`, and **does not clear
the screen** — that is the call to use when reattaching to a pad that already
has tiles on it. `Duo87.startup()` / `duo87.py init` still sends the full vendor
sequence and blanks the screen.

```
GET_REPORT input 0            -> "V3.X106_3_5.02.012"
CRT DIS
CRT wake
CRT QUCMD 1F 11 00 11 00 11
CRT CLE FF   (x2)
CRT STP
CRT CLE FF   (x2)
CRT STP
... key images (BAT + chunks), STP ...
CRT CONNECT   every 10 s
```

`QUCMD 1F 11 00 11 00 11` is sent verbatim by the vendor app; the meaning of
the six bytes is still unknown, and as the table above shows it is not needed to
get images on screen.

### 2.6 Swipe gestures — **verified on Linux 2026-09-11**

The pad has a **native gesture engine**. A swipe is not something the host has
to infer from a run of tile codes: the firmware recognises it and reports a
direction. The reports arrive on the same 512-byte `ACK`/`OK` channel as key
presses, so the byte at offset 9 is overloaded and offset 10 disambiguates.

A **state byte (offset 10) of `0x02`** is the new piece — it had not been seen
before, because a plain tap only ever produces `0x01` then `0x00`:

| offset 9 | offset 10 | meaning |
|---|---|---|
| `0x01`..`0x0C` | `0x01` | tile pressed |
| `0x01`..`0x0C` | `0x00` | tile released |
| `0x01`..`0x0C` / `0xFF` | **`0x02`** | contact turned into a drag; this is the tile the finger started on, *instead of* the usual release |
| `0x31`..`0x34` (ASCII `'1'`..`'4'`) | `0x00` | **the swipe direction**, sent after the `0x02` |

Direction codes are ASCII digits, not tile numbers:

| code | ASCII | direction |
|---|---|---|
| `0x31` | `'1'` | top to bottom |
| `0x32` | `'2'` | bottom to top |
| `0x33` | `'3'` | left to right |
| `0x34` | `'4'` | right to left |

A full left-to-right swipe therefore looks like:

```
41434b00004f4b0000 07 01     tile 7 touched
41434b00004f4b0000 07 02     ... became a drag
41434b00004f4b0000 33 00     '3' = left to right
```

The leading tile report is **not** reliable — a swipe that starts on a divider
reports `0xFF` first, and one observed swipe produced only the direction report
with no tile report at all. Parse on the direction code alone.

**Do not confuse a direction code with a tile.** `0x31`..`0x34` would otherwise
be read as tiles 49..52, which is what a naive parser does (and what ours did on
first contact with a swipe).

#### Horizontal is free, vertical is claimed by the firmware

This is the part that matters for an application:

* **Left/right (`'3'`, `'4'`) are pure input.** The display does not change. They
  are reliable and distinguish direction correctly — 12 out of 12 in testing,
  with no visual artefact. **Use these for page navigation.**
* **Up/down (`'1'`, `'2'`) switch the pad to its own on-board page**, which shows
  the stock images it boots with. Two further problems make them unusable for
  navigation:
  - the firmware reports **`'1'` for both directions** in practice (`'2'` was
    seen once in about a dozen vertical swipes);
  - the page switch happens in firmware, before the host can react, so there is
    a visible flash of the stock page.

While the pad is showing its own page, **`BAT` uploads still land** — they are
simply not displayed. Sending `DIS` returns the display to the host's page with
its content intact; `DIS` alone restores host mode but does not repaint, so send
`DIS` + `STP` (or redraw) to get the pixels back. Reacting to a `'1'`/`'2'`
report by doing exactly that suppresses the page switch, but the flash is still
briefly visible, so it is a mitigation rather than a fix.

Whether on-board paging can be disabled outright is **not known** — the `QUCMD`
config bytes (`1F 11 00 11 00 11`, one byte per setting, `0xFF` = off in the
SDK) are the obvious place to look and have not been probed.

#### What the vendor app does with swipes — **captured on Windows, session 2**

The "own on-board page" is the pad's **screensaver mode** (the `LOG` slots,
see 2.2/2.8); the stock picture seen on Linux is the factory content of
screensaver slot 1. The vendor app's reactions, three cycles observed:

| pad reports | vendor app sends | effect |
|---|---|---|
| `'1'` (0x31) | **nothing** | pad has switched itself to screensaver mode; the app lets it |
| `'2'` (0x32) | `MOD '2'`, `CLE FF` x2, all `BAT`s, `STP` | pad has switched itself back to keystroke mode; app repaints |
| `'4'` (0x34) | `CLE FF` x2, (`BAT`s of the new page), `STP` | app pages forward (page 2 was empty, so no `BAT`s) |
| `'3'` (0x33) | `CLE FF` x2, all `BAT`s, `STP` | app pages back |

While in screensaver mode the pad reports **no tile codes at all** — the
`'2'` arrived with no preceding `01`/`02` tile report — whereas in keystroke
mode a vertical swipe is preceded by the usual `tile 01` / `tile 02` pair.

**`'1'` and `'2'` are mode transitions, not directions — verified.** Ten
vertical swipes all in the *same* direction (top to bottom) produced, five
times over: `tile 01`, `tile 02`, `'1'` (pad entered its screensaver page),
then on the next swipe a bare `'2'` with no tile report (pad left it). The user
confirmed by eye that each swipe toggled the mode regardless of direction.
So:

| code | meaning |
|---|---|
| `'1'` | a vertical swipe **switched the pad to its screensaver page** |
| `'2'` | a vertical swipe **switched it back to the tile page** |
| `'3'` / `'4'` | horizontal swipe left-to-right / right-to-left, pure input |

This is why Linux saw `'1'` for "both directions": the driver answered every
`'1'` with `DIS`, putting the pad straight back on the tile page, so every
vertical swipe was again an *entry* and again reported `'1'`. The lone `'2'`
seen there was a swipe that landed before the `DIS` took effect. The direction
table above (down = `'1'`, up = `'2'`) should be read with that in mind: the
firmware does not report vertical direction at all.

While on the screensaver page the pad reports no tile codes and no `0x02` drag
report, only the `'2'` when it leaves.

So `MOD '2'` + repaint is the vendor's way back from the screensaver page,
equivalent to the `DIS` + repaint found on Linux. Neither prevents the pad
from switching in the first place.

### 2.7 Panel geometry — **partly solved, partly open (2026-09-11)**

The tile model in 2.3 is correct but incomplete, and the gaps between tiles are
not what they appear to be.

#### The panel is one continuous screen — **verified**

The dark bands between tiles are **not a bezel**. Two independent checks:

* The pad's own stock screen (the one it shows before `DIS`, or after a vertical
  swipe) is a single image that **spans the gaps**.
* The glass is flat and continuous to the fingernail; there is no ridge.

So the bands are pixels nobody is writing, not structure.

#### The key window is ~112x112, not 80x80 — **verified**

An 80x80 image is drawn **1:1** at the window's anchor corner; it does not fill
the window, and the remaining ~third stays unlit. That unlit margin is most of
what looks like a "gap". Measured by growing one tile's image until it met its
neighbours:

| image size | result |
|---|---|
| 80 | fills only part of the window (the vendor app's size -- it under-fills too) |
| 104 | close to meeting the neighbours, but visibly resampled |
| **112** | **sharp, no resampling artefacts; gaps nearly disappear** |
| 120 | resampled again |

Sharpness only at 112 implies 112 is the native window size: at any other size
the firmware rescales. **Drawing tiles at 112x112 is a straight win** -- bigger,
sharper, and far less dark space -- and `deck/render.py` now does so.

#### Placement is anchored, and the edges are clipped — **verified**

An oversized image is not clipped to the window: it **spills**. With images
pre-rotated 180 as usual, a growing tile extends **up and to the left** (its
right and bottom edges stay put), so the anchor is the bottom-right corner in
the viewer's orientation. Column 1 is therefore clipped by the panel edge, which
is why its content sits off-centre at 112.

#### Only keys 1..12 exist — **verified**

`BAT` with key `0`, or `13`..`20`, is accepted without error and draws nothing,
at both 80x80 and 112x112. There is no extra index for the margin at the bottom
and right of the panel, which stays dark.

#### The pitch is not uniform — **solved empirically**

Splitting one picture across tiles would not line up at *any* uniform gap
(swept 0..24, then -2..+2; `0` was merely the least bad). The reason is that the
columns are not evenly spaced: **the seam between columns 1 and 2 jumps further
than the one between 2 and 3**, because column 1 is clipped by the panel's left
edge and so shows less of its image than the others.

Modelling it as a per-column crop nudge on top of a zero gap does work. Measured
by eye with `tools/gapcal.py`:

| | shift (tile px) |
|---|---|
| column 1 | **+24** (clipped at the left edge) |
| column 2 | 0 (reference) |
| column 3 | **-9** |
| all rows | 0 |

With those, a shallow diagonal crosses every seam cleanly. `deck/render.py`
carries them as `COL_SHIFT` / `ROW_SHIFT`.

This is a fit, not an understanding: the underlying window size, pitch and origin
in true panel pixels are still unmeasured, and the numbers are in tile-pixel
units at `SIZE = 112`. They will need redoing if the tile size changes, and are
worth checking against Windows (see `captures/WINDOWS_CAPTURE.md`).

#### The panel is 320 x 480 — **stated by the vendor app (Windows session 2)**

The screensaver upload dialog says "Supported Image Resolutions: 320*480",
and a 320x480 JPEG uploaded through it (`LOG`, see 2.2) fills the panel edge
to edge, upright after the app's 180 rotation, with a 4 px frame visible on
all four sides. So the panel is 320 wide by 480 tall in the viewer's
orientation (3 columns x 4 rows), and the "unreachable" bottom/right margin is
simply panel area that no `BAT` window covers. With 112 px windows the row
pitch is 480 / 4 = 120 and the column pitch is 320 / 3 = 106.67, which is why
no uniform gap ever fitted and why column 1 is clipped: three 112 px windows
need 336 px on a 320 px wide panel. The `COL_SHIFT` numbers in
`deck/render.py` are a fit to exactly that.

#### Warning: large images wedge the device — **verified, reproducible**

A 420x620 JPEG sent to a key rendered as corrupt pixels and then **locked the
USB endpoint**: every subsequent write failed with `ETIMEDOUT`, and even the
`GET_REPORT` firmware read stopped answering. Only a physical replug recovered
it. 276x374 was tolerated; keep uploads near the native tile size, and treat
anything much larger as capable of hanging the pad.

### 2.8 Windows session 2 (2026-09-11 evening) — what the vendor app really does

Captured with `captures/hook.js` v2.1, which tracks the HID handles of both
the pad and the keyboard and logs every `ReadFile`/`WriteFile`/`DeviceIoControl`
on them. Raw log: `captures/windows_session2_full.log`; the time index of what
was done when is in `captures/WINDOWS_SESSION2_INDEX.md`.

**Full-screen image (`LOG`) — verified.** The only UI for it is "Screensaver
Mode" > "Edit Screensaver", which accepts jpg/jpeg/png/gif/mp4/mov at
**320x480** into one of four slots ("1 gif", "2/3/4 jpg jpeg png"). Wire
format in 2.2. The app re-encodes the file (my 21 KB test JPEG went out as
45 KB, same 320x480, rotated 180) and waits for the pad's `ACK OK` (~3.5 s,
presumably a flash write) before `STP`. Confirmed by eye: the image fills the
panel to all four edges, upright. **This is the only known way to light the
bottom/right margin.** Not yet tested from Linux: whether `LOG` works in
keystroke mode (the app only sends it in screensaver mode), whether a slot
can be shown on demand, and how big a JPEG is safe (44 chunks was fine).

**Mode switch (`MOD`) — verified.** `MOD '1'` = screensaver mode, `MOD '2'` =
keystroke mode. Switching back to keystroke mode is followed by `CLE FF` x2 and
a full `BAT` repaint + `STP`.

**Sleep timer is host-side — verified.** "Automatic screen off" sends nothing
when changed; the app simply sends `CRT\0\0sleep` 60 s (for the 1-minute
setting) after its last `wake`. The app sends `wake` on every click in its own
window and on start-up; it does not send `wake` on pad key presses (the pad
wakes itself on touch).

**Rotate is host-side.** Changing it re-encodes and re-sends all tiles to the
same key numbers; nothing else goes to the pad.

**Page switching and key actions are host-side.** Page 1/2 = repaint. A pad
key press is answered by the app with a bare `STP` (per press and per
release), nothing else.

**No brightness control** exists in this app version (3.10.203.0820); the
Settings > Device tab shows only serial, firmware, screen-off and rotate.
`LIG` therefore remains SDK-derived, but it visibly works from Linux.

**No keyboard-side traffic.** The app opens every HID interface of both USB
devices once during enumeration (the `OPEN` lines), reads their attributes and
strings, and then keeps only the pad's vendor interface. It never writes to the
keyboard's raw HID interface, and the "RGB Control" plugin's actions (which
target MiraBox N4-class LED products by VID/PID) produce no pad traffic either.
The `SETLB`/`LBLIG`/`RGBS`/`LAYER`/`DELED`/`INTVID`/`WEB` strings are part of
the shared Stream Dock code base and, on the evidence, unused for the DUO87.
Keyboard lighting/layers are the keyboard's own QMK/VIA business.

**No `.DEVCFG` / `{"size"` reply exists on this device.** With every read and
ioctl logged, the pad's only device-to-host traffic is key/swipe events and the
`LOG` acknowledgement. The firmware string is fetched with
`IOCTL_HID_GET_INPUT_REPORT` (0xB01A2) on report 0, as documented in 2.1.

### 2.9 `MOD` and `LOG` driven from Linux — **verified 2026-09-11**

Both commands work from Linux exactly as captured on Windows, with `duo87.py`'s
`set_mode()` and `set_screensaver()`:

* `MOD '1'` puts the pad in screensaver mode; `MOD '2'` returns to tiles (and the
  caller must repaint the tiles, as the vendor app does).
* `LOG` to a slot 0..3 stores a 320x480 JPEG and the pad replies
  `41 43 4b 00 00 4f 4b 00 00 00 00` (512 bytes on hidraw; the leading report-id
  byte the Windows capture shows is stripped by the kernel). It lights the whole
  panel, all four edges, upright.

Two behaviours matter for the application layer and were not visible on Windows:

* **Screensaver mode is a user-driven carousel; the host cannot pick the slot.**
  `MOD '1'` shows the pad's stock wallpaper. A freshly uploaded slot does **not**
  display until the user physically swipes to it, and swipes cycle through the
  cards. Tested every way to force a slot from the host and all failed: uploading
  then `STP`, overwriting the (unknown) shown slot, and uploading a slot *then*
  sending `MOD '1'` — all left the stock wallpaper on screen. There is no known
  "show slot N" command. So `LOG` populates up to four cards, but **which card is
  on screen is entirely the user's choice via swipe (or the pad's idle cycling),
  never the host's.** The pad also sleeps to a dark screen after idle in this
  mode. (The vendor app appeared to show an uploaded image immediately, but only
  ever did so inside its own Edit-Screensaver preview flow, which we could not
  reproduce as a plain host command.)
* **Slot 0 is the immutable stock wallpaper.** `MOD '1'` always displays slot 0,
  and the host cannot replace what slot 0 shows (writes to it are ACKed but the
  stock image remains). Writable user cards go in **slots 1..3**, and are only
  seen when the user swipes to them.
* **A slot write costs ~1.25 s** (measured: chunk writes ~1 ms, then a ~1250 ms
  ACK delay, on every overwrite of every slot; a write whose content is unchanged
  can return in ~50 ms). This is a flash write. **`LOG` is therefore a wallpaper
  mechanism for slowly-changing content, not a live display.** Anything that
  animates (a clock, a progress bar, system graphs) belongs in tile mode, where
  a `BAT` upload is ~15 ms.

**Hazard: never send `LOG` while in keystroke (tile) mode.** Trying that to
paint the panel margin behind the tiles reset the device on 2026-09-11: it
re-enumerated to a different `/dev/hidraw` node and lost its display state.
`LOG` belongs only in screensaver mode. (`duo87.py` re-detects the node on
each open so it recovers, but the on-screen content is gone.)

Design consequence: read-only cards (weather, calendar, album art that changes
per track) use `LOG`; live and interactive content uses `BAT` tiles.

## 3. Linux specifics

* Kernel driver: generic `hid-generic`; the vendor interface shows up as
  `/dev/hidrawN`. Identify it by `/sys/class/hidraw/hidrawN/device/uevent`
  containing `HID_ID=0003:00000600:00003001` and a report descriptor
  starting with `06 A0 FF`.
* Identified in practice as **`/dev/hidraw0`** on this machine; the pad's other
  interface (IF1, boot keyboard) is the adjacent node and starts `05 01 09 06`.
  `duo87.py` picks the right one by report descriptor, so don't hard-code it.
* Permissions: install `99-duo87.rules` into `/etc/udev/rules.d/`, then
  `sudo udevadm control --reload && sudo udevadm trigger --action=add --subsystem-match=hidraw`.
  A plain `udevadm trigger` sends a *change* event, which re-applies `MODE` but
  **not** `TAG+="uaccess"`, so the node stays root-only.
* **`uaccess` alone was not sufficient here** (systemd 261, Manjaro): the tag and
  `CURRENT_TAGS=:uaccess:seat:` were both set and other uaccess devices
  (`/dev/dri/card1`, `/dev/snd/*`) had the ACL, yet logind never put an ACL on
  the freshly-tagged hidraw node, even across a physical replug. The rule
  therefore also sets `GROUP="wheel"`, which takes effect immediately. Change
  that group to one your desktop user is actually in.
* `duo87.py` in this folder is a stdlib-only driver (Pillow optional for
  resizing) with a CLI: `info`, `listen`, `demo`, `image`, `brightness`,
  `clear`, `refresh`, `wake`, `sleep`, `raw`.
* The vendor app on Windows keeps the device open; on Linux nothing else will
  claim it. Sending `CONNECT` every 10 s is cheap and matches the vendor
  behaviour, so `duo87.py listen` does it — but it is **not required**: see the
  heartbeat row in section 2.2. `duo87.py listen --no-heartbeat` suppresses it
  if you want to re-test that.

## 4. Where the evidence is

* `captures/vendor_app_startup_hid_writes.log` — every 1025-byte WriteFile the
  vendor app issued from process start (Frida hook).
* `captures/vendor_app_key_image_updates_sample.log` — steady-state traffic
  (clock widget redrawing keys 4 and 5 once per second).
* `captures/captured_key4_80x80.jpg` — one key image reassembled from the
  capture.
* `captures/hook.js`, `captures/capture.py` — the Frida hook, reusable if a
  brightness/keyboard-setting capture is wanted later (attach to
  `DUO87_Play_Deck.exe`, then move sliders in the app).
* Public references: MiraBox `StreamDock-Device-SDK` (GitHub), community
  `rigor789/mirabox-streamdock-node` and `OH1KK/mirabox`.
