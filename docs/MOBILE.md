# D.Ai Mobile: phones and tablets

> Written on 2026-10-20 after "I also want a version for televisions and mobile devices". Television is in
> `docs/TV.md`. **Decided (under "from now on you decide"):** the three tracks below and their order.
> **Status:** plan; track A (touch profile) begins after D.Ai TV stage 1.

## 0. What a "mobile version" can honestly be

- **Not a replacement for Android or iOS on the phones people own.** Mainstream phones (Samsung, Xiaomi, Apple
  and most others) have locked bootloaders and proprietary drivers; no Linux can be installed on them in a way a
  person could trust for daily use. Saying otherwise would be a lie.
- **Linux phones exist, and Debian runs on them:** the PinePhone and PinePhone Pro, the Librem 5, and a
  growing list of phones that upstream Linux supports (the Fairphone 4 and 5, the OnePlus 6/6T and others,
  through the postmarketOS and Mobian work). Debian 13 itself ships the phone shells: **Phosh** 0.46
  (GNOME's phone shell), **Plasma Mobile** 6.3, the on-screen keyboard `squeekboard`, `gnome-calls` and
  `chatty` for calls and SMS. The modem, the camera and power management are the hard, device-specific parts,
  and they are the reason "Debian on phones" is a project of its own (Mobian), not a package list.
- **Tablets and 2-in-1 laptops with x86 processors** can run today's D.Ai image already; what they lack is a
  touch-first interface.
- **So there are three honest tracks**, in this order:
  - **A. D.Ai Touch:** the existing D.Ai, with a touch and small-screen profile: larger targets, an on-screen
    keyboard everywhere, the command bar and every D.Ai window usable with a finger, the taskbar's touch
    layout. For x86 tablets and 2-in-1s now, and the foundation for phones. Testable in CI (a small screen and
    touch events in QEMU).
  - **B. D.Ai Companion:** an app for the phones people already have (Android first, iOS later): Diamond Chat
    (the same protocol, the same pairing), the TV remote (`docs/TV.md` stage 4), sending a picture or a file to
    the D.Ai computer, and "my computer's status" (the Living Diamond). Open source, no account, no server.
    This is how D.Ai reaches a phone in people's pockets this year.
  - **C. D.Ai Phone:** Debian 13 with Phosh (**decided: Phosh**, because it is the shell Mobian and the Librem
    5 ship, it is in Debian 13, and its stack is GTK/Wayland, which coexists with D.Ai's Qt apps) plus the D.Ai
    Touch apps, for the Linux phones above, starting with the PinePhone Pro as the reference device. A real
    phone must be bought and tested by hand; CI can only build the image and boot it in QEMU.

## 1. Stages

| Track | Stage | What | Size |
|---|---|---|---|
| A | A1 | A touch profile in `dai_style` (sizes, spacing, 44 px targets) chosen from the hardware at first start and in Tune ("touch mode"); `squeekboard`-style on-screen keyboard through `wvkbd` or `squeekboard` on labwc (**requires a check** which one works under labwc); the command bar, Quick, Welcome and the login screen pass a touch audit (Raz: target size, spacing) | Medium |
| A | A2 | Every D.Ai window responsive: one column under 700 px, bigger fonts, swipe where a list scrolls; the taskbar in touch mode (bottom, big, the diamond as a home button) | Large |
| A | A3 | Gestures on labwc (edge swipes for the taskbar and Quick), rotation, the camera and the privacy indicator on tablets | Medium |
| B | B1 | The Companion for Android: Diamond Chat (Kotlin, the same PyNaCl-compatible primitives through libsodium), pairing with the computer, pictures re-drawn before sending, the TV remote; F-Droid first, no Google services needed | Large |
| B | B2 | iOS: the same, in Swift, when B1 has users (Apple's review and the Tor transport **require a check**) | Large |
| C | C1 | `build-iso.sh phone`: Debian 13 + Phosh + the D.Ai Touch apps, built for arm64 and booted in QEMU (`virt` machine) in CI; the reference device is the PinePhone Pro; calls, SMS and the camera through Phosh's own apps; D.Ai's privacy indicator, Tune and Raz adapted | Large |
| C | C2 | A second device from the mainline list; the installer for phones (`jumpdrive`-style flashing) | Large |

## 2. What D.Ai brings to a phone that others do not (the reason to do C at all)

- Hebrew first, right to left, in every app and the shell (Phosh supports RTL; its apps vary; D.Ai's own are
  built for it).
- Diamond on the phone itself (a small model, no cloud), Voice in Hebrew, D.Ai Tune in sentences.
- The privacy indicator for the microphone, camera and location at the system level, with a local log.
- Diamond Chat between the phone and the computer with no account.
- No app store account, no telemetry, no advertising ID.

## 3. Risks and limits, said plainly

- **Devices:** a Linux phone is a hobbyist device today (camera quality, battery life, some carriers' VoLTE).
  D.Ai Phone will be the same until the hardware ecosystem matures; the plan does not promise otherwise.
- **The Companion app** depends on the Chat protocol's external security review (`docs/SEND.md`); it must
  not ship to phones before that.
- **App stores:** Google Play and Apple's App Store have policies and fees; F-Droid is the first channel for
  Android. Apple requires a developer account (**requires a check** of cost and terms).
- **Legal:** calls and SMS on a phone image touch telecommunications rules per country; nothing here claims
  compliance (**requires legal review** before any phone image is offered).
- **Time:** tracks B and C are each as large as everything built so far. A1 and B1 are where the value is
  first.

## 4. Decisions (taken)

1. Order: TV stage 1 → A1 → B1 → A2 → C1. B2, A3, C2 after.
2. Phosh for track C; Qt for D.Ai's own apps on every track.
3. The Companion app is open source, Apache-2.0, in this repository under `apps/dai-companion`, with the Chat
   protocol as its only wire format.
4. No phone image is published until a physical reference device has run it and the legal review is done.

## 5. Status

### A1 — the touch profile (built and verified in CI, run 39381912535)

- **`dai_style.touch()`** decides the profile: `~/.config/dai/touch` (`on`, `off`, `auto`) or `DAI_TOUCH` for one
  app; `auto` means a direct-touch input device is attached (the kernel's `INPUT_PROP_DIRECT` bit under
  `/sys/class/input`, so a pen tablet counts and a touchpad does not). `with_touch(sheet)` appends the touch
  rules: every control at least 44 px (WCAG 2.5.5), bigger check boxes, scroll bars and slider handles, 12 pt text.
  No colors in those rules, so the three themes are untouched.
- **D.Ai Tune:** `appearance.touch` — "מצב מגע" / "touch mode", "כבה מצב מגע" / "touch mode off", "מצב מגע
  אוטומטי" / "automatic touch mode"; user scope, with undo; translated in the six other languages.
- **Raz:** a fourth audit rule, `target` (44 × 44 px), and `assert_accessible(case, window, touch=True)` runs
  the audit again with the touch stylesheet on. The command bar, Quick and Welcome pass it in CI; Quick's
  slider needed the rule (it was 15 px tall).
- **The login screen:** the round buttons (session, language, power) and the pill button grew from 36–42 px to
  44 px; the show-password eye too.
- **On-screen keyboard:** `wvkbd` (it is a wlroots layer-shell client and already ran under labwc in the VM
  check `os: night light and on-screen keyboard`). `squeekboard` needs Phosh's text-input integration and is
  left for track C. In touch mode labwc's autostart starts `wvkbd-mobintl -L 260 --hidden` and
  `dai-keyboard` (Super+Alt+K) toggles it with SIGRTMIN. Verified against wvkbd 0.15 (Debian 13): `--hidden`
  and the SIGUSR1/SIGUSR2/SIGRTMIN handlers are in its source; the first VM run showed that `-H` is the portrait
  height, not "hidden", and it was corrected. The check `touch: the profile, Tune, the keyboard` covers it.
- **Not in A1:** showing the keyboard by itself when a text field gets focus (needs the Wayland text-input
  protocol on the compositor side; A3), the taskbar in touch mode (A2), gestures (A3).

### A2 — every window responsive, the taskbar in touch mode (built and verified in CI, run 39435881034)

**What "responsive" means for a Qt window here.** Three things, each testable:

1. **Panes stack.** A window with two panes side by side (Chat: people | talk; J: folders | messages | message;
   PDF: side panel | page; VM: machines | details) shows them one above the other when the window is narrower
   than **700 px**. `dai_style.panes.Panes` is a `QSplitter` that turns vertical on its own `resizeEvent` under
   that width and horizontal above it, keeping the sizes of each orientation. The apps replace their `QSplitter`
   with it; nothing else changes.
2. **Nothing is cut off.** At a phone-like width (640 × 900) every interactive widget lies inside the window and
   no label without word wrap is wider than its space. Raz gets two rules for that, `fits` and `clipped`, run
   in a third pass of `assert_accessible(case, window, touch=True)`: the window is resized to 640 × 900 with the
   touch stylesheet on. The pane apps, Command, Quick and Welcome are gated by it in CI.
3. **Fingers scroll.** `dai_style.touch_scrolling(window)` puts a `QScroller` touch gesture on every scroll area's
   viewport, so a list or a page follows the finger with inertia. Called by the apps' windows; a no-op without
   touch.

**Fixed widths.** The command bar (720 px) and Quick (420 px) take the screen's width minus a margin when it is
smaller, so they fit a phone-sized screen.

**The taskbar in touch mode.** The same panel, bigger: `panelSize=72`, `iconSize=36`, task buttons 64 px, the
island the full width. `dai-panel-touch on|off` rewrites those keys in the person's `panel.conf` (idempotent),
and `startdai-wayland` calls it at every login with the profile's answer, so turning touch mode on in Tune takes
effect at the next login, and turning it off restores the desktop sizes. The diamond stays the Start button;
a separate "home" gesture is A3.

**Not in A2.** Gestures (edge swipes, A3), rotation (A3), the on-screen keyboard appearing by itself (A3).

**A2, what was built.** `dai_style.panes`: `Panes` (the splitter that stacks under 700 px), `WrapRow` (a
toolbar row that wraps; Qt's flow layout, right-to-left aware), `touch_scrolling()` (QScroller's touch gesture on
every scroll area) and `fit_width()` (a fixed width no wider than the screen). Chat, J, PDF and VM use `Panes`;
the PDF toolbar and VM's action row use `WrapRow`; VM's details pane scrolls; the command bar and Quick take
`fit_width`; the command bar's footer wraps. Raz: `fits` and `clipped`, and the narrow pass in
`assert_accessible(touch=True)` (a fixed width is lifted for it, so the layout is judged). Those seven windows
pass the touch and narrow passes in CI. The findings the new rules made before the fixes: the PDF window could not
go under 1067 px (the toolbar), VM under 722 px (the action row), the command bar's hints were clipped at 640 px,
and VM's details were squeezed to 7 px lines when stacked (now a scroll area). `dai-panel-touch on|off` and the
login hook; the VM check `touch: the panel and the responsive pieces`. Not yet: the other windows' narrow pass
(Forge, Heal, MOM, Clip, Welcome's dialogs; they get it as they are touched), the screenshot of a stacked window.
