# Windows session 2 — capture index (2026-09-11, hook v2.1)

Log: `windows_session2_full.log` (spawned `DUO87_Play_Deck.exe` under
`capture.py` + `hook.js` v2.1; every line is `HH:MM:SS.mmm TAG len=N hex`).
Lines before the first `OPEN` (20:30:55) are unfiltered process I/O (config
files, caches) and can be ignored. `newcmds.sh LOG HH:MM:SS` lists the
interesting lines after a time (drops `CONNECT`, JPEG chunks, 65-byte log
writes).

| time | what was done | what appeared |
|---|---|---|
| 20:30:55 | app opens devices | `OPEN` x17 (enumeration of every HID interface), ioctls 0xB01A8/0xB01BA/0xB01BE/0xB01C2 (attributes, strings), 0xB01E2 (indexed string), **0xB01A2 GET_INPUT_REPORT -> firmware string** |
| 20:30:55.4 | start-up | `DIS`, `wake`, `QUCMD 1F 11 00 11 00 11`, `CLE FF` x2, `STP`, x2, then 10 `BAT` (keys 1-9, 12; 80x80) + `STP`, twice |
| 20:33:31 | opened Settings > Device | `wake` only |
| 20:33:54-20:34:05 | Automatic screen off: 1 min, 5 min, Never | `wake` per click, nothing else |
| 20:34:56 | Rotate: 180 | `wake`, `CLE FF` x2, 10 `BAT` (re-encoded), `STP` |
| 20:35:03 | Rotate: Default | same |
| 20:35:32 | Screensaver Mode radio | `wake`, **`MOD '1'`** |
| 20:36:32 | Edit Screensaver, slot 1, `screensaver_test_320x480.jpg`, Update | **`LOG size=0xAF9B slot=00`**, 44 chunks, **`R ACK OK 00 00` at +3.5 s**, then `STP` |
| 20:37:35 | same file, slot 2 | `LOG size=0xAF9B slot=01`, chunks, ACK, `STP` |
| 20:39:21 | Keystroke Mode radio | `wake`, **`MOD '2'`**, `CLE FF` x2, 10 `BAT`, `STP` |
| 20:39:41-45 | page 2, page 1 | repaints only |
| 20:40:22 | dragged RGB Control "Off" onto key 10 | nothing |
| 20:41:07-08 | user pressed key 10 five times | `R ACK OK 0a 01/00` per press/release, app replied `STP` each time; **no keyboard-side write** |
| 20:43:16 | screen-off set to 1 minute, then idle | **`sleep` at 20:44:16**, exactly 60 s after the last `wake` |
| 20:46:15 | user pressed tile 2 | `R 02 01`, app `BAT`(key 2)+`STP`; `R 02 00`, app `BAT`+`STP` (pressed-state artwork) |
| 20:46:15-28 | user: vertical swipes down/up x3 | `R 02 01`, `R 02 02`, **`R '1'`** -> app silent (pad now in screensaver mode); ~5 s later **`R '2'`** (no tile report) -> app `MOD '2'`, `CLE FF` x2, 10 `BAT`, `STP`. Repeated 3 times (`0b`, then `ff` as the start tile) |
| 20:46:45 | user: horizontal swipe right-to-left | `R ff 01`, `R ff 02`, **`R '4'`** -> app `CLE FF` x2, `STP` (page 2 is empty) |
| 20:46:46 | user: horizontal swipe left-to-right | `R 07 01`, `R 07 02`, **`R '3'`** -> app `CLE FF` x2, 10 `BAT`, `STP` (page 1) |
| 20:48:00 | screen-off restored to Never | `wake` per click |

Files produced: `screensaver_test_320x480.jpg/.png` (the upload),
`captured_screensaver_LOG_payload.jpg` (what the app actually sent: 320x480,
rotated 180, re-encoded).
