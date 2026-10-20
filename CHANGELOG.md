# Changelog

All notable changes to D.Ai OS. Versions follow [Semantic Versioning](https://semver.org/);
pre-releases are marked `-alpha`, `-beta` or `-rc`.

## [0.1.0-alpha] — unreleased

First public alpha, built on Debian 13 (trixie). User and developer editions.

### Added
- D.Ai PDF: the PDF reader. Every file opens through a bubblewrap helper (no network, no home folder, memory and
  CPU limits); what the file wants (JavaScript, launching programs, submitting forms, attachments, XFA) is shown
  in a bar and never done; links ask before opening and local ones are refused; Hebrew made readable; search,
  outline, thumbnails, print. The default handler for `application/pdf`; qpdfview left the image.
- D.Ai PDF, editing: pages turned, moved, removed, inserted from another file, merged and split; forms filled
  (text, check boxes, radio groups, drop-downs) and flattened; undo and redo; every save built by a one-shot
  sandboxed editor that sees only the inputs read-only and an empty output folder. `dai-pdf merge|split|rotate|
  delete|fields|fill` on the command line.
- D.Ai PDF, marks: highlight, underline, strike through, notes, text (Hebrew drawn right) and stamped pictures
  (a signature), placed with a drag, listed, undone, written by the sandboxed editor into the saved file.
- D.Ai VM: Windows in a window with the person's own media and key. A hardware check that says plainly when a
  computer cannot (no VT-x/AMD-V, too little memory); machines under qemu:///session with UEFI Secure Boot,
  TPM 2.0, VirtIO disk and network through passt, SPICE over a local socket; the VirtIO drivers ISO downloaded
  once with a pinned SHA-256; no clipboard, folder or USB sharing until asked; "allow virtual machines" in
  D.Ai Tune adds the person to the kvm group, with undo. User and dev editions.
- D.Ai VM, working together: the clipboard, a shared folder (read-only unless allowed) and USB devices as
  switches per machine, off by default, applied through libvirt; USB devices in and out while the machine runs;
  snapshots taken, listed, reverted and deleted, in the window and on the command line.
- D.Ai TV, the television edition (`build-iso.sh tv`): Kodi 21 full screen on labwc, autologin, the bundled
  Hebrew language pack, no web server, UPnP, AirPlay or Zeroconf, hardware decoding, CEC tools; "Exit" in Kodi turns the
  session into the desktop. Plans for phones and tablets in `docs/MOBILE.md`.
- D.Ai TV: "remote control from the phone" in D.Ai Tune turns Kodi's remote services on with a password and
  opens their ports to the local network only, with undo.
- Touch mode (`docs/MOBILE.md` A1): on a touch screen, or after "touch mode" in D.Ai Tune, every D.Ai control
  is at least 44 px and the on-screen keyboard waits hidden behind Super+Alt+K; Raz audits the command bar, Quick
  and Welcome for finger-sized targets; the login screen's buttons grew to 44 px.
- Responsive windows (`docs/MOBILE.md` A2): Chat, J, PDF and VM stack their panes one above the other under
  700 px, toolbars wrap, lists follow the finger; Raz checks that nothing is cut off at a phone-like width; the
  taskbar grows for touch at login (`dai-panel-touch`).
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
