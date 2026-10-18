# D.Ai OS

**A free, secure, open-source Linux desktop with a built-in local AI, a Hebrew-first experience, and a builder that extends the system from plain text.**

Based on Debian 13 · LXQt on labwc (Wayland) · Apache-2.0

![D.Ai Night desktop](https://github.com/diamondrubinny/D.Ai/blob/docs/os-plan/docs/screenshots/desktop.png?raw=true)

> **Status:** early development. The first working version builds and boots in CI; the installer works but a full end-to-end install is not yet automated. Not recommended as your only operating system.

---

## Why D.Ai OS

- **Private AI that stays on your computer.** A local model (llama.cpp) runs on a UNIX socket only. The AI service has no network access.
- **Configure the system by describing it.** Type what you want in Hebrew or English. Nothing you type ever becomes a shell command. It becomes a reviewable plan, with undo.
- **Extend the system by asking.** Ask for an antivirus, file sync, or a custom app. D.Ai Forge builds it, you review it, and it is installed.
- **A system that develops and repairs itself.** Every app the AI builds is tested in a sandbox and repaired before you see it; ask for an automation and it runs on a schedule; when something crashes, a chat explains it and fixes it with your OK.
- **Hebrew and RTL done properly.** HE/EN indicator, wrong-layout fixer (`akuo` becomes `שלום`), Hebrew app names and Hebrew voice dictation.
- **Secure by default.** Default-deny firewall, AppArmor, kernel hardening, locked root, automatic security updates, full-disk encryption in the installer.

## What's included

| Component | What it does | Docs |
|---|---|---|
| **D.Ai Night desktop** | A faceted diamond Start button, a real command field in the panel, HE/EN indicator, dark theme, lock screen | `docs/DESIGN.md` |
| **D.Ai Command** | Launch apps (also by Hebrew name), commands, safe calculator, layout fixer. `?` asks the local AI, `!` opens Tune, `+` opens Forge | |
| **D.Ai Tune** | Configure the system in text, through a closed catalog of validated actions, a root helper that re-validates everything, a journal and undo, and a security score | `docs/TUNE.md` |
| **Local AI** | Pinned llama.cpp, models downloaded on demand with pinned SHA-256, automatic coder model for code | `docs/AI.md` |
| **D.Ai Forge** | Recipes (antivirus, Syncthing, Flathub, Podman, WireGuard, Nextcloud, Steam, OnlyOffice and more), an AI app builder with sandboxed apps, the Workshop (build → test → repair) and scheduled automations | `docs/FORGE.md`, `docs/EVOLVE.md` |
| **D.Ai Heal** | When a program crashes or a service fails: a notification, a chat that explains it in plain words, and fixes from a closed list applied only when you click (`Super+F1`) | `docs/EVOLVE.md` |
| **D.Ai Voice** | Local Whisper dictation and voice commands | `docs/VOICE.md` |
| **D.Ai Code** | Local coding assistant: explain, review, edit with diff and undo | |
| **D.Ai Find** | "Find the PDF I downloaded last week", in Hebrew or English | `docs/FIND.md` |
| **D.Ai Doctor** | Why is it slow, what fills the disk, battery health, hardware check | `docs/DOCTOR.md` |
| **D.Ai Privacy** | Microphone and camera indicator with a local log | `docs/PRIVACY.md` |
| **D.Ai Backup** | Encrypted automatic backups (restic) to an external drive | `docs/BACKUP.md` |
| **D.Ai Move** | Bring your files and bookmarks over from Windows | `docs/MOVE.md` |
| **D.Ai Clip** | Clipboard history (Super+V) that never keeps passwords | |
| **D.Ai Welcome** | First-run setup wizard | `docs/WELCOME.md` |
| **D.Ai OEM** | Prepare a computer for its new owner (refurbishers, charities) | `docs/OEM.md` |
| **Installer** | Calamares with LUKS full-disk encryption, D.Ai branded | `docs/INSTALL.md` |
| **Snapshots** | Btrfs and snapper snapshots before updates, with a way back | `docs/SNAPSHOTS.md` |

### Editions

- **user**: the everyday desktop
- **dev**: user edition plus developer tools
- **edu**: user edition plus learning apps (GCompris, Tux Paint, TuxMath, Stellarium, KDE Edu, Marble) and organization policies for schools

## D.Ai Forge

![Forge: ask](https://github.com/diamondrubinny/D.Ai/blob/docs/os-plan/docs/screenshots/forge-home.png?raw=true)
![Forge: review the plan](https://github.com/diamondrubinny/D.Ai/blob/docs/os-plan/docs/screenshots/forge-plan.png?raw=true)
![Forge: the local AI writes the app](https://github.com/diamondrubinny/D.Ai/blob/docs/os-plan/docs/screenshots/forge-building.png?raw=true)

Press `Super+B`, or type `+` in the command field, and say what the computer should be able to do:

```
+ install an antivirus
+ add file sync
+ build an app for ...
```

Every recipe becomes a D.Ai Tune plan that is reviewed, authorized by polkit, validated again by the root helper, journaled and undoable. Apps built by the local AI run in a **bubblewrap sandbox**.

Before you see an app, the **Workshop** starts it in a stricter sandbox (no network, no home, no display). If it crashes, the AI fixes it from the error and tests again, at most twice. Ask for something recurring (`+ every morning tell me if the disk is almost full`) and it becomes an **automation**: a user-level systemd timer that runs the script in the sandbox and shows its result as a notification (`dai-forge auto list`).

## Security model, in short

- Text is never executed. It is parsed into requests for a **closed catalog** of typed actions.
- Weakening changes need a typed confirmation, and `--yes` is refused for them.
- AI-written plans are labelled, need manual review, and can only use catalog actions.
- The AI service runs with `RestrictAddressFamilies=AF_UNIX`, so it has no network.
- Models and releases are verified by pinned SHA-256 and signatures. D.Ai packages come from a signed repository, pinned so it can never replace a Debian package.

Details and threat models are in `docs/TUNE.md` and `docs/FORGE.md`. To report a vulnerability, see `SECURITY.md`.

## Try it

1. Download an ISO from the [Releases](../../releases) page, once a release is published.
2. Write it to a USB stick.
3. Boot it and try it live. In the live session, `dai-doctor hardware` or "will my wifi work?" in the command field checks your hardware.
4. Install with **Install D.Ai OS** and keep **Encrypt system** ticked.

Coming from Windows? Read `docs/FROM-WINDOWS.md` first.

## Build from source

Requires Debian or Ubuntu with `live-build`:

```bash
# build one edition: user, dev or edu
build/build-iso.sh user

# boot it in QEMU
build/run-qemu.sh
```

CI (`.github/workflows/build-iso.yml`) runs ShellCheck and unit tests, builds llama.cpp, whisper.cpp, the panel plugin and every ISO in `debian:trixie`, boots each ISO in QEMU/KVM, runs in-guest checks and publishes screenshots.

## Repository layout

```
apps/      D.Ai applications (command, tune, ai, forge, voice, code, ...)
build/     live-build configuration and build scripts
docs/      design, security model and user guides
site/      static Hebrew landing page
tests/     unit, VM and apt-repository tests
```

## Known limitations

- Sandboxed apps are not yet exposed to screen readers. This needs an accessibility and security review.
- ClamAV scans on a schedule. On-access scanning is not enabled yet.
- App quality depends on the local model (the 1.5B coder model is recommended).
- The end-to-end install is not automated in CI yet.
- Secure Boot signing is not done yet.
- `grub-btrfs` is not available in Debian 13, and the installer default stays ext4 until Btrfs is approved.

See `docs/PLAN.md` for the roadmap.

## Contributing

Contributions are welcome. Please read `CONTRIBUTING.md` first. The project uses the Developer Certificate of Origin (DCO), so sign off your commits with `git commit -s`. Please follow `CODE_OF_CONDUCT.md`.

## License and credits

Copyright (c) 2026 Diamond Rubinny (d.Ai). The code is licensed under Apache-2.0: copies must keep `LICENSE`, `NOTICE` and the copyright notices in the files.

**"D.Ai", "D.Ai OS" and the diamond logo are trademarks.** The license grants no rights to them, so modified versions may not be distributed under the D.Ai name or logo, or presented as official. See `TRADEMARKS.md`. Terms of use for the official releases: `docs/legal/TERMS.md` (draft, pending legal review). Debian packages in the images keep their own licenses.

Created by **Diamond Rubinny (d.Ai)**. Built with [Claude Code](https://claude.com/claude-code).

---

## בעברית

**D.Ai OS** היא מערכת הפעלה חופשית, מאובטחת ובקוד פתוח (מבוססת Debian 13) עם AI מקומי שרץ על המחשב שלכם, ממשק עברית מלא, ומבנה שמאפשר להרחיב את המערכת רק באמצעות טקסט.

- **AI פרטי:** המודל רץ מקומית, ושירות ה-AI לא מחובר לרשת.
- **הגדרות בטקסט:** כותבים מה רוצים ("חסום USB", "פתח פורט"), מקבלים תוכנית לבדיקה ואישור, ותמיד אפשר לבטל.
- **D.Ai Forge:** כותבים `+ תתקין אנטי וירוס`, והמערכת בונה תוכנית, אתם בודקים, והיא מותקנת. אפשר גם לבקש בניית אפליקציה.
- **מערכת שמפתחת ומתקנת את עצמה:** כל אפליקציה שה-AI בונה נבדקת בארגז חול ומתוקנת לפני שאתם רואים אותה; אוטומציות רצות לפי לוח זמנים; וכשמשהו קורס, נפתח צ'אט שמסביר ומתקן באישורכם.
- **עברית ו-RTL:** מחוון HE/EN, תיקון הקלדה בפריסה שגויה (`akuo` ל-`שלום`), הכתבה בעברית וחיפוש קבצים בעברית.
- **אבטחה כברירת מחדל:** חומת אש, AppArmor, הצפנת דיסק מלאה בהתקנה, גיבוי מוצפן ועדכוני אבטחה אוטומטיים.

**זכויות:** © 2026 Diamond Rubinny (d.Ai). הקוד ברישיון Apache-2.0. השם D.Ai והלוגו הם סימני מסחר: אסור להפיץ גרסה משונה בשמם (`TRADEMARKS.md`).

**סטטוס:** שלב מוקדם. מומלץ לנסות מ-USB (Live) לפני התקנה. מעבר מ-Windows: ראו `docs/FROM-WINDOWS.md`.
