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
- D.Ai Welcome: first-run wizard — security level through D.Ai Tune, local models sized to the computer's memory, privacy facts.
- Installer (Calamares) with full-disk encryption (LUKS) and D.Ai branding.
- Hardening: nftables firewall (deny inbound), AppArmor, kernel/sysctl hardening, automatic Debian security updates.
- D.Ai components shipped as Debian packages; signed, pinned update repository in each GitHub Release.

### Known limitations
- Full end-to-end installation and Secure Boot are not yet tested automatically (see docs/INSTALL.md).
- Not reviewed by a lawyer, accessibility consultant or penetration tester yet.

---

© 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0
