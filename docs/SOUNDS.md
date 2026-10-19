# D.Ai sounds: the diamond family

> Status: built. Unit tests pass, and a VM check runs in CI.

> Written on 2026-10-19 after "operating system sounds from the diamond family: beautiful, pleasant and comfortable sounds".

## 1. The sound

- **Glass and crystal:** every sound is a struck crystal. The overtones are not quite harmonic, like glass: ×1, ×2.32, ×4.25, ×6.63. The high ones fade fast, and a short, soft reverb gives "air".
- **One family:** all the sounds come from the D major pentatonic (D, E, F#, A, B: "D" for Diamond). So any two sounds that play together sound good together.
- **Comfortable:**
  - A soft attack (5 ms), with no clicks.
  - Short: most are under a second.
  - Peak volume -12 dBFS.
  - An error is two low, gentle notes, not an alarm.
- **Accessible:**
  - A sound is never the only sign of anything: there is always a notification or something on screen.
  - Turning sounds off, or making them quiet, is one sentence.
  - "Do not disturb" also silences them.

## 2. The sounds (names from the freedesktop "Sound Naming" specification)

| Sound | When | Notes |
|-------|------|-------|
| `desktop-login` | Entering the desktop | D-F#-A-D rising, a shimmering tail (1.6 s) |
| `desktop-logout` | Leaving | The same, falling |
| `message-new-instant`, `dialog-information` | A notification | A then D, "ding-ding" |
| `complete` | Something finished (text copied, backup done) | D then A, a rising fifth |
| `dialog-warning` | A warning | A single soft F# |
| `dialog-error` | An error | B then F#, low and gentle |
| `bell` | The terminal bell | A short, quiet E |
| `device-added` / `device-removed` | A USB device | A short rise / fall |
| `power-plug` / `power-unplug` | The charger | A rising / falling interval |
| `screen-capture` | A screenshot | A soft "click" and a high sparkle |
| `audio-volume-change` | Changing the volume | A small A "tick" |
| `trash-empty` | Emptying the trash | A quick falling sparkle |

## 3. How it works

- **The theme:** `/usr/share/sounds/dai`, with `index.theme` and `stereo/*.oga`, as the specification defines.
  - GTK apps (through libcanberra) use it once `gtk-sound-theme-name=dai`.
- **`dai-sound <name>`** plays a sound from the theme with `pw-play` (PipeWire, already on the image).
  - It respects the choice in `~/.config/dai/sounds`: `on`, `quiet` or `off`.
  - It respects "Do not disturb", except at login and logout, which are rare and signal a change of state.
- **`dai-sound watch`** (in autostart) listens to udev for USB devices being added and removed, and for the charger. It needs no special permissions.
- **D.Ai plays sounds at:**
  - login;
  - a screenshot;
  - text copied with OCR;
  - a volume change in D.Ai Quick.
- **D.Ai Tune:** "sounds off", "quiet sounds", "sounds on", and in Hebrew "השתק צלילי מערכת", "צלילים שקטים", "הפעל צלילים". With undo.
- **The files** come from `build/scripts/make-sounds.py` (numpy, then Vorbis with ffmpeg). The sounds are committed, so the image build needs no tools.

## 4. Checks

- **Unit tests:**
  - every name in the table has a file;
  - `index.theme` is valid;
  - `dai-sound` chooses correctly between on, quiet, off and "Do not disturb";
  - the watcher understands udev lines.
- **VM:** `dai-sound complete` plays through PipeWire (the exit code of `pw-play`), and `dai-sound watch` is running.

---

© 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0
