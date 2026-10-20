# D.Ai TV: the television edition

> Written on 2026-10-20 after "I also want a version for televisions and mobile devices". Mobile is in
> `docs/MOBILE.md`. **Decided (under "from now on you decide"):** the editions and stages below; stage 1 begins
> now. **Status: stages 1, 2, 3a and 3b built** (§7–§12): Kodi in Hebrew on Wayland, the privacy defaults, nothing listening; D.Ai on the remote, by sentence, and live channels from the person's own playlist.

## 0. What a "television version" can honestly be

- **A smart TV's own chip cannot run D.Ai.** Samsung (Tizen), LG (webOS), Sony/TCL/Hisense (Android TV or
  Google TV) have locked firmware; nothing can be installed in their place. This is true for every Linux.
- **What can run D.Ai is the box next to the TV:** a mini PC or an old laptop on HDMI (x86-64, today's images),
  and later a Raspberry Pi 4/5 or a similar ARM box (`docs/HARDWARE.md`, ARM stage). A TV with HDMI-CEC lets
  its own remote drive that box.
- **So D.Ai TV is an edition for a TV-connected computer:** it boots straight into a 10-foot interface, is
  driven by the TV remote (CEC), a Bluetooth remote, a game pad or a phone, speaks Hebrew with right-to-left,
  listens (Whisper, on the box), and sends nothing anywhere.
- **What is different from a smart TV:** no automatic content recognition (ACR), no advertising, no account
  needed, no telemetry, nothing watching what you watch; updates for years from Debian; the whole D.Ai desktop
  one key away when a TV should also be a computer.

## 10. Stage 2c: D.Ai on the remote, night mode, the children's profile (what was built)

- **The remote's microphone:** `dai-tv listen` records a few seconds from the box's microphone through D.Ai
  Voice (whisper.cpp on this computer), then either does what was said, from a fixed table in Hebrew and
  English ("השהה", "pause", "הבא", "louder", "what is this"…), or asks Diamond and puts the answer on the TV.
  "Listening…" and "I heard nothing" are notifications on the screen; without Voice, a microphone or a model the
  TV says so and nothing else happens. Kodi runs it from a keymap shipped in every new user's `.kodi`
  (`userdata/keymaps/dai.xml`): the **blue** button of a CEC remote (Kodi maps CEC's "F1 blue" to it,
  `PeripheralCecAdapter.cpp`) and **F12** on a keyboard, both free in Kodi's global keymap (F9 and F10 are its
  MCE volume keys, so they were not taken). Kodi's windows that use blue themselves (teletext, the guide)
  keep it. Which key a given TV's remote sends for "voice" **requires a check** on real sets; the blue button is
  the one every CEC remote has.
- **Night mode** (`tv.night_mode`): "מצב לילה" / "night mode" dims the screen after 5 minutes (Kodi's built-in
  dim screensaver) and brings the volume down; the file gets the setting for the next start and the running
  Kodi is told at once through `dai-tv night on` (JSON-RPC `Settings.SetSettingValue`, `Application.SetVolume`
  to 40). "כבה מצב לילה" puts the time back to 10 minutes and the volume to 75. Undo does the same.
- **The children's profile** (`tv.children_profile`): "פרופיל ילדים עם קוד 2468" / "children's profile with
  pin 2468" (a 4-digit PIN is made and shown when none is said). Kodi's `profiles.xml` gets a "Children" profile
  with its own library and sources it cannot change, no settings and no add-on manager, no lock of its own, and
  Kodi logs into it on its own at start (`autologin`); the master profile gets a numeric lock whose code is the
  MD5 of the PIN, exactly as Kodi compares it (`CGUIPassword`, `GUIDialogNumeric.cpp`: the entered digits are
  MD5'd and compared to the stored code). Leaving the children's profile for the parents' one therefore asks
  the PIN. Sources for the children go into `profiles/Children/sources.xml` (the parents add them from their
  profile). "כבה פרופיל ילדים" removes the master lock and the automatic login; the profile and its library
  stay. The plan is marked as hardening; the note says to write the PIN down. Takes effect when Kodi starts
  again (a running Kodi rewrites the file on exit, so the sentence is best said from the desktop or before a
  restart; **requires a check** on the image).
- **Tests:** dai-tv (6): the spoken table, a question to Diamond with the answer on the TV, nothing heard, Voice
  absent (said on the TV, exit 1), night mode's three calls; Tune: the sentences (Hebrew and English, with and
  without a PIN, off), the files written and restored by undo, the PIN rule, a profiles file with other profiles
  kept. The tv VM check applies night mode and the children's profile through the real `dai-tune` with undo,
  checks the keymap parses and `dai-tv night` reaches the running Kodi.
- **Not yet (2d):** the Living Diamond on the TV status, "what this add-on sends" before an install.

## 11. Stage 3a: live channels from the person's own playlist (what was built)

- **Nothing asks at first start.** Kodi stores a binary add-on it meets for the first time as disabled unless
  it is in Kodi's own manifest (`CAddonDatabase::SyncInstalled`: `enable = 0`), which is why Debian's
  `kodi-pvr-iptvsimple` and `kodi-inputstream-adaptive` were taken out in stage 1. They are back: the TV
  session runs `dai-tv seed` before Kodi starts, which creates Kodi 21's `Addons33.db` with its exact schema
  (`CreateTables`, `CreateAnalytics`, the `version` table with 33; copied from the source, not guessed) and
  writes the two add-ons into `installed` as enabled. A row that already exists is left alone by Kodi, and a row
  the person disabled themselves (`disabledReason` = user) is left alone by D.Ai. On the CI image Kodi itself
  reports `pvr.iptvsimple` enabled over JSON-RPC, and the window at the end of boot is the home screen.
- **The channels:** "ערוצים מהרשימה שלי ~/channels.m3u" / "live channels from ~/channels.m3u" (`tv.channels` in
  D.Ai Tune; the file must exist on this computer and be `.m3u`/`.m3u8`) writes IPTV Simple's first instance
  (`addon_data/pvr.iptvsimple/instance-settings-1.xml`: the instance name and enabled flag Kodi reads from
  `IAddon.h`, `m3uPathType` 0 = a local file, the path, no cache, an EPG address when `--epg URL` is given to
  `dai-tv channels`). "כבה ערוצים חיים" / "turn off live channels" removes it; undo puts the file back. Kodi
  shows the channels when it starts again. The playlist is the person's own: D.Ai ships no channel list and
  no address, and says nothing about what a given list may lawfully carry (**requires legal review** per
  source before any list is recommended).
- **Tests:** dai-tv (8): the schema and version, the rows with their dates, the person's own disabling kept,
  idempotence, the instance file and its removal, the commands; Tune: the sentences (a path in both
  languages, off, a sentence without a path refused rather than half-done), the file rule, the dai-tv calls.
  The tv VM check: the add-ons on the image, the seeded rows, Kodi's own answer, the sentence and its undo.
- **Not yet (3b):** the broadcasters' web players through Ruby in TV mode; Widevine (**requires verification**
  per service); an EPG by sentence.

## 12. Stage 3b: the broadcasters' sites through Ruby in TV mode (what was built)

- **Ruby in TV mode:** `dai-tv browse URL` starts Firefox ESR (Ruby's policies apply: no telemetry, tracking
  protection, HTTPS only) in a kiosk window with a profile of its own (`~/.config/dai/ruby-tv`, mode 0700,
  `user.js` written at every start: scale 1.75 for the sofa, autoplay allowed so a player starts, nothing
  restored from a crash, everything cleared at exit, links in the same window). Only `https://` and `http://`
  addresses (and D.Ai's own start page) are accepted. One instance at a time; its PID is kept in the profile.
- **The broadcasters:** Kodi's favourites (`userdata/favourites.xml`, seeded from `/etc/skel`) carry כאן 11,
  קשת 12 and רשת 13 as the broadcasters' public home pages (`kan.org.il`, `mako.co.il`, `13tv.co.il`), each
  opening in Ruby in TV mode, and "חזרה לטלוויזיה". The path of each live player, and whether it plays on this
  box (Widevine is not enabled by D.Ai; Firefox asks, and the answer **requires verification** per service, and
  is "no" on ARM), is not claimed. Nothing of the broadcasters' is shipped: D.Ai opens their sites, that is all.
- **The way back, whatever the remote:** `dai-tv browse --close` ends the browser (only the instance D.Ai
  started: its PID, checked alive). It is bound in labwc for the TV session to `XF86Back`, `XF86HomePage`
  and `XF86Close` (the Back/Home keys of keyboard and air-mouse remotes, with any window in front) and in
  Kodi's keymap to the remote's **My TV** button (CEC remotes, which Kodi holds). Alt+F4 works too.
- **A limit said plainly:** a remote that reaches the box only through CEC is held by Kodi; Firefox never sees
  its arrows, so with such a remote the sites can be opened and closed from the TV but not browsed. A keyboard,
  an air mouse or (stage 4) the phone drives the pages. Arrow-key navigation inside the pages (moving the focus
  from link to link) needs a content script in Ruby's extension, which Firefox loads only once it is signed
  (docs/BROWSER.md §10); that is 3c, after signing, not a flag that turns signature checks off.
- **Also, from stage 2c:** the blue button on a CEC remote now runs D.Ai's listen (it opened Kodi's Pictures
  by default); red, green and yellow keep Kodi's meanings.
- **Tests:** dai-tv (9): the command line Firefox gets, the profile and its prefs and mode, one instance at a
  time, "back to the TV" signalling only that PID, a dead PID ignored, addresses that are refused, the commands.
  The tv VM check opens D.Ai's start page on the image, sees the process and the prefs, closes it, and checks
  the favourites, the keymap and the labwc keys.
- **Not yet (3c):** arrow navigation in pages (the signed extension), a sentence "open Kan 11" in Tune, an EPG.

## 1. Stages

| Stage | What | Size |
|---|---|---|
| **1. The edition** | `build-iso.sh tv`: the common layer plus Kodi 21 (GPL-2.0, in Debian 13), `cec-utils`, `mpv`; a `dai-tv` session that starts Kodi full screen on labwc with the D.Ai look and autologin; the desktop reachable from Kodi's power menu ("switch to the desktop"); Hebrew and RTL in Kodi (its Estuary skin supports both); CEC on; no network services listening; the boot menu says "D.Ai TV"; a boot test and a screenshot in CI | Medium |
| **2. D.Ai inside the TV** | Diamond and Voice on the remote's microphone button or a phone ("find comedies from the 90s", "what is this film about", in Hebrew); D.Ai Tune sentences for the TV ("night mode", "children's profile"); the Living Diamond on the TV status; "what this app sends" shown before a Kodi add-on is installed | Medium |
| **3. Israeli television** | Live channels through `kodi-pvr-iptvsimple` from the person's own playlist; the broadcasters' web players (Kan, Keshet 12, Reshet 13) through Ruby in TV mode (big fonts, remote navigation); DRM (Widevine) only where Firefox gets it on x86 (**requires verification** per service, and it is not available on ARM) | Medium |
| **4. The phone as the remote** | Diamond Chat's pairing (codes and six symbols) pairs a D.Ai phone or the companion app (`docs/MOBILE.md`) to the TV: remote, keyboard, "send this picture to the TV", on the local network only | Medium |
| **5. ARM boxes** | arm64 images for the Raspberry Pi 4/5 (hardware video decoding **requires a check**: H.264/HEVC on the Pi 5 is software only) | Large |

Out of scope, plainly: installing on a smart TV itself; Netflix, Disney+ and the like (their apps are not
available to Linux boxes, and their web players need Widevine at a level Linux does not get in 4K); game
streaming; the ARM boxes until stage 5.

## 2. Threat model (short)

| Asset | Threat | Control |
|---|---|---|
| Privacy | Watching habits leave the box | No telemetry in Kodi (Debian's build sends none; the setting is off and checked); no accounts; the firewall default-deny; Kodi's web server and UPnP off by default; add-ons from Kodi's repository only after "what this sends" is shown (stage 2) |
| The home network | The box as a listening service | Nothing listens: no SSH, no Kodi remote control port, no UPnP until the person turns one on in Tune (with the posture shown) |
| The box | A malicious add-on | Add-ons run as the `tv` user with no sudo; D.Ai's AppArmor and the Forge sandbox ideas apply in stage 2; the system is read-only to Kodi |
| Children | Content | A children's profile in Kodi with its own sources (stage 2); a PIN to leave it |
| Availability | A remote that stops working | The keyboard and the phone always work; the desktop is one key away |

## 3. Architecture (stage 1)

```
build/live-build/editions/tv/
  package-lists/tv.list.chroot          kodi, cec-utils, mpv, VA-API drivers (the binary add-ons come with stage 3)
  hooks/normal/0150-dai-tv.hook.chroot  the tv session as the default, autologin to it, Kodi's settings (Hebrew, no web server, no UPnP)
  includes.chroot_after_packages/
    usr/share/wayland-sessions/dai-tv.desktop     "D.Ai TV": starts labwc with the TV autostart
    usr/bin/dai-tv-session                        labwc -s "kodi --windowing=wayland"; back to the desktop on exit with a code
    etc/dai/tv/guisettings.xml                    Kodi's defaults: Hebrew/English, RTL, no telemetry, no servers, CEC on
    etc/xdg/labwc/rc-tv.xml                       no panel, no decorations, Kodi full screen
```

- **Why Kodi, not a launcher of our own:** Kodi is the only mature, GPL, Debian-packaged 10-foot interface
  with remotes, CEC, subtitles, Hebrew, PVR and a library. A D.Ai launcher of our own would be years behind it.
  D.Ai's work goes into what Kodi does not have: Diamond, Voice, privacy, Tune, the phone pairing.
- **Why labwc under Kodi:** Kodi can also run straight on the GPU (GBM). labwc keeps one path for the screen,
  the keyboard layouts, the lock and the switch to the desktop, at a small cost. Measured in stage 1.
- **Autologin:** the TV box is a single-user appliance; the live and installed systems log the `tv` user in
  without a password, like a smart TV. Full-disk encryption then asks a passphrase at boot (the installer's
  default), which a TV box owner may turn off in the installer.

## 4. Decisions (taken)

1. Kodi as the 10-foot interface, D.Ai around it (not a launcher of our own).
2. The edition is `tv`, built in CI like the others; not in the edu or server images.
3. Autologin into the TV session; the desktop reachable from Kodi's power menu.
4. No network service on by default; Tune sentences turn them on, with the posture shown.
5. ARM after x86, in the HARDWARE.md order.

## 5. Tests and verification

- CI: `build (tv)` boots the ISO, the boot test sees the `dai-tv` session as the default, Kodi starts on the
  Wayland session (process present, no crash within 60 s), the guisettings have the telemetry and servers off,
  `cec-client -l` runs, nothing listens (`ss -ltn` empty), and a screenshot of Kodi's home in Hebrew.
- Measure: memory with Kodi idle on the weak profile.

## 6. Risks and limits

- **Video decoding in a VM:** CI runs without a GPU; Kodi falls back to software rendering, which proves the
  session, not the playback. Real boxes with Intel/AMD graphics decode in hardware (VA-API, in the image).
- **CEC** needs a CEC adapter on the box (Pulse-Eight USB, or built in on the Pi); most x86 mini PCs lack one:
  then a Bluetooth remote or the phone.
- **DRM services:** said above; nothing promised.
- **The name:** "D.Ai TV" is descriptive, like the other editions.

## 7. Stage 1: what was built

- `build/live-build/editions/tv/`: the package list (Kodi 21, `cec-utils`, `mpv`, VA-API drivers), `/etc/dai-release` with `EDITION=tv`, the `dai-tv.desktop` Wayland
  session, `startdai-tv` (labwc with `/etc/dai/tv/labwc/rc.xml`: no decorations, no panel, `Super+Enter` a
  terminal, `Ctrl+Alt+Del` the leave dialog) and `dai-tv-kodi` (Kodi full screen on Wayland; on exit the same
  labwc runs `lxqt-session`, so "Exit" in Kodi's power menu reaches the desktop; Kodi's power-off and reboot
  exit codes end the session instead), the live autologin into the TV session, `DefaultSession=dai-tv.desktop`
  for SDDM, and Kodi's defaults in `/etc/skel/.kodi` (copied once per user).
- **Hebrew without a download:** Kodi's language packs are add-ons fetched from its repository; the Hebrew one
  (`resource.language.he_il` 11.0.81, GPL-2.0-or-later, Team Kodi) is bundled under `/etc/skel/.kodi/addons`
  and chosen in `guisettings.xml` (with the "Arial" font so Hebrew letters draw). **Verified** on the CI
  screenshot: Kodi enables the pre-placed language pack at its first start and the whole interface is in Hebrew,
  right to left.
- **Privacy defaults:** web server, UPnP (server and renderer), AirPlay, Zeroconf and the event server off;
  unknown add-on sources off; add-on update notifications off. The firewall is D.Ai's default-deny one.
- **The boot test** reads `/etc/dai-release`; on tv the desktop's checks become information only, the
  desktop's interactive screenshots are skipped, and the TV check must pass (session default, Kodi running,
  no LXQt, the defaults, `cec-client`, nothing listening). CI builds `tv` in the matrix with the others.
- **Verified in CI** (run 39381912535): `kodi --windowing=wayland` works on Debian's build ("using the wayland
  windowing system" in kodi.log), the session is `dai-tv.desktop`, no LXQt, the web server and the other
  services off, nothing listening outside loopback, `cec-client` present. The screenshot (run 39386058886, no
  dialog) is `docs/screenshots/tv-desktop.png`.
- **A lesson from the screenshot:** Debian's binary add-ons (`kodi-pvr-iptvsimple`, `kodi-inputstream-adaptive`)
  are installed disabled, and Kodi's first start asks "enable this add-on?" for each. They were taken out of
  stage 1; stage 3a (§11) brought them back and seeds Kodi's add-on database (`Addons33.db`, `installed` table)
  before the first start, so nothing asks.
- **Not yet:** the measurement on the weak profile, stages 2–5.

## 8. Stage 2a: the first D.Ai sentence for the TV (what was built)

- **"שלט מהטלפון" / "remote control from the phone"** in D.Ai Tune: `tv.remote_control` turns on Kodi's web server
  (user `kodi`, a password made for the person and shown in the plan), the JSON-RPC and event services on all
  interfaces, and opens 8080/tcp, 9090/tcp and 9777/udp **to the local network only**; the plan is marked as
  weakening, so it is confirmed, and undo closes the ports and puts `guisettings.xml` back as it was. "כבה שלט
  מהטלפון" turns it off and closes the ports. Kodi takes the change when it starts again. The phone side is any
  Kodi remote app (Kore, GPL) until stage 4 brings D.Ai's own.
- **A lesson:** the Hebrew for "in the TV" (בטלוויזיה) contains the word for "cancel" (בטל); the sentence is
  checked for an "off" with that word set aside.
- **VM check** (tv edition): the sentence applied through the real helper, the settings and the three nft rules
  checked, then undone and compared with the file as it was.
- **Not yet:** Diamond and Voice on the remote's microphone, "children's profile" and "night mode", the Living
  Diamond on the TV, "what this add-on sends" before an install (stage 2b).

## 9. Stage 2b: D.Ai talks to Kodi (what was built)

- **`dai-tv`** (`apps/dai-tv`): Kodi's JSON-RPC over its local TCP port only (127.0.0.1:9090; the service is on
  for this computer, "allow remote control from applications on other systems" stays off until Tune's "remote
  control from the phone"). `ping`, `playing` (title, year, the plot's first lines), `say TEXT` (a notification on
  the TV), `ask QUESTION` (Diamond, with what plays now as context; the answer printed and shown on the TV; a
  plain sentence when Diamond is not installed or not running), `do ACTION` (play, pause, stop, back, select,
  the arrows, info, volume; a fixed list). Nothing leaves the computer.
- **Tune's "turn off remote control"** now closes the service to the network and keeps it for this computer.
- **Tests:** 4 (a fake Kodi on a local socket: every command, exit codes, a refusal, no Kodi, Diamond answering
  and Diamond absent). The tv VM check sees the port bound to 127.0.0.1 only and every command answered by
  the real Kodi.
- **Not yet (built in 2c, §10):** the remote's microphone button, "children's profile" and "night mode"; still
  to come: the Living Diamond on the TV, "what this add-on sends" before an install.
