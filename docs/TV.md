# D.Ai TV: the television edition

> Written on 2026-10-20 after "I also want a version for televisions and mobile devices". Mobile is in
> `docs/MOBILE.md`. **Decided (under "from now on you decide"):** the editions and stages below; stage 1 begins
> now. **Status: stage 1 built and verified in CI** (§7): Kodi in Hebrew on Wayland, the privacy defaults, nothing listening.

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
  stage 1; stage 3 (IPTV) brings them back and seeds Kodi's add-on database (`Addons33.db`, `installed` table)
  at the first start so nothing asks.
- **Not yet:** the measurement on the weak profile, stages 2–5.
