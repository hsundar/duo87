# Windows session plan

> **Done 2026-09-11 (session 2).** Every section below was executed; results are
> in `../PROTOCOL.md` 2.8 and `WINDOWS_SESSION2_INDEX.md`. Kept for the method.

What to do next time Windows is booted. Read `../PROTOCOL.md` first, especially
**2.7 (panel geometry)** — most of this exists to close the questions that opened
there.

The goal is not to clone the vendor app. It is to learn two things Linux cannot
answer alone:

1. **The panel's true resolution**, and whether anything can light the strip
   along the bottom and right edges that `BAT` provably cannot reach.
2. The byte layout of commands the app sends and we have never seen (`LOG`, and
   the keyboard-side settings).

---

## 0. Setup

```
pip install frida frida-tools
```

Copy this `captures/` folder across. Attach to the app **while it is already
running**:

```
tasklist | findstr DUO87
python capture.py <pid> out.log
```

Attaching beats spawning: the start-up burst (`DIS`, `wake`, `QUCMD`,
`CLE`/`STP`) is already captured in `vendor_app_startup_hid_writes.log`, and
spawning buries the interesting packet under it. Attached to a running app the
log is idle except for `CONNECT` every 10 s, so whatever appears when you touch a
control is unmistakable.

Spawning is still available if you need the very first packets:

```
python capture.py "C:\path\to\DUO87_Play_Deck.exe" out.log
```

### The hook was rewritten — check it works before trusting a session

`hook.js` is **v2**. The original filtered by transfer size and, as a result,
captured **no device-to-host traffic whatsoever**: three sessions produced zero
`R` lines. That is why we still do not know what the pad replies with, even
though the app is known to parse a `.DEVCFG` string.

v2 instead watches `CreateFile` for a handle whose name contains `vid_0600`,
`pid_3001` or `hotspotek`, then logs **every** read and write on that handle at
any size, plus `HidD_GetInputReport` / `HidD_GetFeature` / `HidD_SetFeature` /
`HidD_SetOutputReport`, which bypass `ReadFile` entirely.

**Sanity check first, before capturing anything you care about:** attach, then
press a key on the pad. You should see `R` lines appear (the `ACK…OK` key
events). If no `R` lines ever appear, the hook is still missing the read path —
say so rather than concluding the device is silent, and try spawning instead of
attaching so `CreateFile` is seen.

A log starting with an `OPEN` line means handle tracking is active. Without it,
v2 falls back to the old size filter.

### Method for every measurement

1. A **fresh log file per control** — never two settings in one log.
2. Let it idle ~15 s so the `CONNECT` baseline is visible.
3. Change **one** control, once.
4. Wait ~5 s, change the **same** control to a **different** value.
5. Ctrl-C.

Two distinct values for one control is what separates the command name from the
payload and reveals the encoding. A single sample usually cannot be decoded.
Name logs for their intent: `lig_brightness_10_then_90.log`.

---

## 1. Panel geometry and the bottom/right margin — **top priority**

What we know from Linux (all verified):

- The panel is **one continuous screen**: the pad's own stock screen spans the
  bands between tiles, and the glass is flat to a fingernail.
- The key window is **~112x112**, not 80x80. An 80x80 image is drawn 1:1 and
  leaves about a third of the window unlit. The vendor app sends 80x80, so **it
  under-fills too**.
- Only keys **1..12** exist. `BAT` with key 0 or 13..20 is accepted and draws
  nothing.
- Images are anchored **bottom-right** and grow **up and left**, so nothing we
  can send reaches the strip along the bottom and right edges. Only the firmware
  lights it.

### 1.1 Look, before capturing anything

With the vendor app running and showing its own icons:

- **Is there a dark margin around each key icon**, exactly like ours? (Compare
  against the stock screen, which definitely fills the panel.) If yes, that
  independently confirms the 112 window / 80 image finding.
- **Does the app light the strip along the bottom and right edges at any point** —
  at start-up, on a theme change, in a screensaver, while dragging? If it ever
  does, capture that moment. It is the single most valuable packet on this list,
  because it is the one thing we have proven we cannot do.
- Does the app expose the pad's **resolution** anywhere — settings, About, a
  device-info panel, a tooltip? Write down the number; it makes everything below
  unnecessary.

### 1.2 Measure the margin physically

Do this on Linux before you reboot (`python3 tools/margin.py` lights all twelve
windows white and prints the arithmetic), or on Windows with the app closed and
the pad showing whatever it shows. Measure in millimetres with a ruler on the
glass:

- the width of one key window (a bright square, edge to edge)
- the dark strip along the **right** edge, outside the outermost squares
- the dark strip along the **bottom** edge

A key window is 112 px, which converts the millimetres to pixels and gives the
panel's real size. Record the numbers in `../PROTOCOL.md` 2.7.

### 1.3 Confirm the image size the app sends

Reassemble one `BAT` payload from a capture and check the JPEG's dimensions. Ours
(`captured_key4_80x80.jpg`) is 80x80. If a newer app version sends 112x112, that
settles the native size outright.

```
# the header is  CRT\0\0BAT <size:uint32 BE> <key>, then size bytes of JPEG
# across following 1024-byte writes
```

### 1.4 Why this matters

`deck/render.py` carries `COL_SHIFT = [24, 0, -9]` — per-column nudges fitted by
eye so that one picture can span several tiles without kinking at the seams. It
works, but it is a fit, not an understanding. The true window size, pitch and
origin in panel pixels would replace it with arithmetic.

---

## 2. `LOG` — the full-screen / background image

Still the only unexplored *display* feature, and the obvious candidate for
lighting the whole panel.

Be aware the evidence is discouraging: `LOG` (`4c 4f 47`) appears in **none** of
the captures we have, and three plausible header framings sent blind on Linux did
nothing at all. It may exist only in the shared Stream Dock codebase and not be
wired up for this device.

In the app, look for wallpaper / background / boot logo / screensaver — anything
setting an image that covers the pad rather than one key. Set it, apply, capture.

Record alongside the log:
- the **source image file** and its pixel size
- whether the pad shows it stretched, cropped or letterboxed

From the bytes we need: whether the header is `CRT\0\0LOG` + `size:uint32 BE`
like `BAT`, whether a key/index byte follows the size, and above all **what the
payload is** — one panel-sized JPEG, or twelve tile JPEGs concatenated. Check the
first data chunk for the `ff d8 ff e0` signature and count chunks against the
declared size.

If the app has no such feature, write that down and skip it. A confirmed absence
is a useful result.

---

## 3. Device replies (`.DEVCFG`) — newly reachable with the v2 hook

The app parses strings beginning with `.DEVCFG` (keys `os`, `scr`, `led_info`,
`mode`, `speed`, `brightness`), plus `rc:` and a JSON blob starting with
`{"size"`. We have **never captured any of them**, because v1 logged no reads.

`scr` and `{"size"` are very likely the screen geometry — which would answer
section 1 directly.

So: with v2 attached, exercise anything that would make the app ask the device
about itself — open settings, a device-info or firmware page, reconnect the
device, switch profiles. Keep any `R` line carrying readable ASCII.

---

## 4. The keyboard-side settings

`SETLB`, `LBLIG`, `RGBS`, `LAYER`, `DELED`, `INTVID`, `WEB`. These probably reach
the *keyboard* (`342d:e542`) relayed through the pad, so they are out of scope for
the display driver but wanted for a full DUO87 app.

Guesses to confirm by capture, not by name:

| String | Likely control |
|---|---|
| `LBLIG` | keyboard LED / backlight brightness |
| `RGBS` | RGB mode, effect or speed |
| `SETLB` | backlight generally |
| `LAYER` | layer switch (Win/Mac, or Fn) |
| `INTVID` | screen-off / sleep timeout |
| `DELED` | LEDs off |
| `WEB` | seen as `CRT\0\0WEB\0\0\x01`; probably a flag, no payload |

For sliders capture **min then max**, not two nearby values.

---

## 5. Cheap sanity checks while you are there

- Does the pad revert to its **stock images** when the vendor app closes, or do
  the app's tiles persist? (`DIS` puts it under host control; what hands it back
  is unknown.)
- With the app **closed**, does the pad still report key presses? (On Linux it
  does, indefinitely, with no heartbeat.)
- Does the vendor app ever send anything after a **vertical swipe**? On Linux a
  vertical swipe makes the pad switch to its own page and the host must send
  `DIS` + a repaint to get back. If the Windows app suppresses that more
  gracefully, the packet it sends is worth having.

---

## 6. Safety

**Do not send oversized images.** On Linux a 420x620 JPEG to a key rendered as
corrupt pixels and then **locked the USB endpoint**: every write returned
`ETIMEDOUT` and even the firmware read stopped answering, until the pad was
physically replugged. 276x374 was tolerated. Keep uploads near the native tile
size.

---

## 7. Bringing it back

Copy the new `*.log` files here and note in `../CLAUDE.md` what each one was.
Decoding is easy once the bytes exist; the hard part is capturing one control at
a time, with two distinct values, and confirming the hook is logging reads.
