# D.Ai OS

**A lightweight, secure, open-source operating system with a built-in, fully local AI coding assistant and voice control (Whisper).**

> **מערכת הפעלה קלה, מאובטחת וקוד פתוח, עם עוזר AI מקומי לכתיבת קוד ושליטה קולית (Whisper). כל המידע נשאר במחשב ומוצפן.**

⚠️ Status: **pre-alpha** — Phase 1 (bootable base image). Not for production use.

## Goals

- **Lightweight & fast** — Debian 13 base, Wayland desktop (labwc + LXQt components), zram swap.
- **Secure by default** — AppArmor, default-deny inbound firewall (nftables), kernel hardening, automatic security updates, full-disk encryption in the installer (planned), sandboxed AI tool execution (planned).
- **Private by design** — AI and speech recognition run locally; no telemetry; no cloud AI in the default build.
- **AI built in** — `daid` system service, `dai` CLI and desktop assistant for writing, explaining and fixing code (planned, Phase 3+).
- **Voice** — push-to-talk dictation and commands with whisper.cpp, Hebrew and English (planned, Phase 5).
- **Two editions** — `user` (end users) and `dev` (developer tooling).

See the full specification and roadmap in [docs/PLAN.md](docs/PLAN.md).

## Repository layout

```
build/live-build/common/     Shared live-build config (packages, hardening, desktop defaults)
build/live-build/editions/   Edition overlays: user, dev
build/scripts/               build-iso.sh, run-qemu.sh
build/assets/                Wallpaper generator
apps/dai-command/            D.Ai Command (PyQt6) + unit tests
apps/dai-tune/               D.Ai Tune: text-driven configuration, root helper, polkit policy + unit tests
tests/boot/                  Headless QEMU boot test
docs/                        Specification, architecture, threat model
```

## Building an ISO

The build must run as root in a **disposable Debian trixie** container or VM (live-build creates chroots).

```bash
docker run --rm --privileged -v "$PWD:/src" -w /src debian:trixie \
  bash build/scripts/build-iso.sh user /src/out      # or: dev
```

Output: `out/dai-os-<edition>-<version>-amd64.iso` with a `.sha256` file and a package manifest.

CI builds both editions on every change under `build/` and boots them in QEMU (`.github/workflows/build-iso.yml`). Built ISOs are available as workflow artifacts for 7 days.

## Testing

```bash
# Automated headless boot test (needs qemu-system-x86, xorriso, python3)
bash tests/boot/boot-test.sh out/dai-os-user-*.iso boot-artifacts

# Interactive (BIOS or UEFI)
bash build/scripts/run-qemu.sh out/dai-os-user-*.iso
bash build/scripts/run-qemu.sh out/dai-os-user-*.iso --uefi
```

Live session: user `dai`, Hebrew/English keyboard toggle with `Alt+Shift`.
Shortcuts: `Super+Space` D.Ai Command, `Super+Enter` terminal, `Super+E` files, `Super+L` lock,
`Super+←/→` snap windows, `Super+Alt+S` screen reader (Orca).

## Desktop

![D.Ai OS desktop: Start button and command bar on the taskbar](docs/screenshots/desktop.png)

![D.Ai Command open over the file manager](docs/screenshots/command-bar.png)

*Screenshots are captured automatically by CI from the live ISO booted in QEMU.*

- **Taskbar** with a **Start** menu and, right next to it, the **D.Ai Command** bar.
- **D.Ai Command** (`apps/dai-command`): one bar to launch apps (also by Hebrew name), run commands
  (`>` in a terminal, `$` in the background), calculate (`2*(3+4)`, `15% of 80`) and **fix text typed in
  the wrong keyboard layout** (`akuo` → `שלום`). `?` will ask the local AI (Phase 3).
- **D.Ai Tune** (`apps/dai-tune`): configure the system by **writing what you need**, in Hebrew or English —
  `dai-tune "חסום דיסק און קי, כבה בלוטות' ונעל מסך אחרי 5 דקות"`. Text is never executed: it maps to a
  closed catalog of validated actions, shown as a plan (scope, risk, security effect) before anything changes.
  System changes go through a minimal root helper authorized by polkit, are journaled and can be undone
  (`dai-tune undo`). `dai-tune status` gives a security score with a phrase to fix each finding.
  In D.Ai Command, type `!` followed by the request. Design and threat model: [docs/TUNE.md](docs/TUNE.md).
- **D.Ai Night** theme: dark, high-contrast (WCAG AA) palette with a violet→cyan accent, custom wallpaper,
  matching window decorations. Design system: [docs/DESIGN.md](docs/DESIGN.md).

## Contributing

Everyone is welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).
Security issues: see [SECURITY.md](SECURITY.md) — please do not open public issues for vulnerabilities.

## License

D.Ai OS's own code is licensed under the [Apache License 2.0](LICENSE).
The ISO images bundle Debian packages that keep their own licenses (including `non-free-firmware` for hardware support); see each image's package manifest.
