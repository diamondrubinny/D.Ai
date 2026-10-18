# Changelog

All notable changes to D.Ai OS. Versions follow [Semantic Versioning](https://semver.org/);
pre-releases are marked `-alpha`, `-beta` or `-rc`.

## [0.1.0-alpha] — unreleased

First public alpha, built on Debian 13 (trixie). User and developer editions.

### Added
- Live ISO for amd64 (BIOS and UEFI), D.Ai Night design, diamond Start button, Hebrew/English (RTL) throughout.
- D.Ai Command: search, commands, calculator and wrong-layout fixer in one bar; command field in the panel.
- D.Ai Tune: change system settings in plain Hebrew or English, with a visible plan, security score and undo.
- Local AI (llama.cpp, models pinned by SHA-256, nothing leaves the computer); `?` in the command bar.
- D.Ai Forge: install integrations (antivirus, VPN, sync…) and build sandboxed apps (bubblewrap) by asking.
- D.Ai Voice: push-to-talk dictation and voice commands with a local, pinned whisper.cpp.
- D.Ai Code: local coding assistant (`dai-code`): diffs to approve, backups and undo, confined to the project.
- D.Ai Find: natural-language file search in Hebrew and English (type, time, folder, name), in D.Ai Command and `dai-find`.
- D.Ai Doctor: "why is my computer slow?", disk space and battery health in plain Hebrew/English, with safe fixes.
- D.Ai Tune: `system.clean` (free disk space) and `power.profile` (battery saver / balanced / performance); power-profiles-daemon installed.
- D.Ai Privacy: a panel dot only while the microphone or camera is in use, notifications, and a local 30-day log.
- D.Ai Backup: encrypted automatic backups to an external drive (restic), recovery key, retention, weekly verification, safe restore.
- For people leaving Windows: D.Ai Move (files, bookmarks, Wi-Fi names), `dai-doctor hardware`, and Forge recipes for Steam, Bottles, ONLYOFFICE, Zoom, Spotify, Discord, printers, scanners, OpenVPN and Cisco-compatible VPN.
- D.Ai Clip: clipboard history (`Super+V`) in memory only; password-manager copies, keys, tokens, card and ID numbers are never kept, and keys/tokens are cleared from the clipboard after 90 seconds.
- Snapshots before updates on Btrfs system disks (snapper): "snapshots before updates" and "undo the last update" in D.Ai Tune, and D.Ai Doctor answers "it broke after the update".
- The Workshop: AI-built apps are tested in the sandbox and repaired from their error before you see them.
- Automations: "+ every morning …" becomes a scheduled, sandboxed script on a user timer (schedule parsed by rules), with notifications and a log; `dai-forge auto`.
- D.Ai Heal: crashes and failed services lead to a help & repair chat (Super+F1) with fixes applied only after you agree; D.Ai Tune `service.restart`.
- D.Ai Evolve: notices what is missing (a file type no program opens, a command run again and again, a request Forge could not fulfil, Doctor and Heal findings) and suggests it in D.Ai Command, with at most one notification a day; local, 30 days, `dai-evolve off`. "Build or add it" in D.Ai Command when nothing is found. New Forge recipes: e-book reader, video player, image editor, archives.
- The D.Ai Diamond Bar: a centered, floating taskbar with windows as glowing icons, and the Living Diamond - the Start button shows a red circle while an app records, an amber triangle when D.Ai Heal found a problem and a cyan diamond when D.Ai has an idea (also in its accessible name).
- D.Ai Quick (Super+N or the clock): Wi-Fi, Bluetooth, do not disturb, battery saver, mute mic, volume, the security score, D.Ai Heal and who is recording, in one panel; no root, switches that a computer lacks are hidden.
- Languages, stage 1: every app reads the language and its texts through one module (`dai_i18n`, gettext); 575 texts in `i18n/dai-os.pot` ready for Arabic, Russian, Spanish, French, German and Portuguese; translations are used only when their placeholders match. Fixed texts that showed Hebrew for any non-English language.
- D.Ai OEM: `dai-oem prepare` for refurbishers; a first-boot wizard where the new owner creates their account, names the computer and replaces the temporary disk encryption password; temporary users removed before the first login.
- Education edition (`edu`) and organization policies (`/etc/dai/policy.d`, applied at boot and on change), including a screen-lock limit for every user.
- LibreOffice (Writer, Calc, Impress) with the Hebrew interface and Hebrew/English spell checking in every edition.
- D.Ai Welcome: first-run wizard — security level through D.Ai Tune, local models sized to the computer's memory, privacy facts.
- Installer (Calamares) with full-disk encryption (LUKS) and D.Ai branding.
- Copyright and brand: trademark policy (TRADEMARKS.md), terms of use draft (docs/legal/TERMS.md, site/terms.html), a Debian copyright file in every package, and a CI check that every source file keeps its copyright notice.
- Hardening: nftables firewall (deny inbound), AppArmor, kernel/sysctl hardening, automatic Debian security updates.
- D.Ai components shipped as Debian packages; signed, pinned update repository in each GitHub Release.

### Known limitations
- Full end-to-end installation and Secure Boot are not yet tested automatically (see docs/INSTALL.md).
- Not reviewed by a lawyer, accessibility consultant or penetration tester yet.

---

© 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0
