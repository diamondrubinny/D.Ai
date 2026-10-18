# OS basics: what was missing and what is being fixed

> Written on 2026-10-18 after "what else is missing as an operating system?". Every item: a check on the VM in CI (`tests/boot/serial_check.py`), then a fix.
> ✅ = fixed and passes the check · 🔧 = fix submitted, waiting for CI · ⏳ = next

## 1. Possibly broken (stage 1)

| What | Problem | Fix | Check on the VM | Status |
|------|---------|-----|-----------------|--------|
| Drives mount by themselves | `udisks2` and `gvfs` were not in the package list, and recommends are off | `udisks2`, `gvfs`, `gvfs-backends` | `os: drives mount by themselves` | 🔧 |
| Screens on Wayland | `lxqt-config-monitor` works only on X11 | `wlr-randr`, and `wdisplays` (a window, an optional package) | `os: screens on Wayland` | 🔧 |
| Screenshots | `screengrab` does not work well on Wayland | `dai-screenshot` (grim): Print for the whole screen, Shift+Print for an area (slurp). To `~/Pictures/Screenshots` and the clipboard | `os: screenshot (Print)` | 🔧 |
| Secure Boot | The ISO did not ask live-build for Debian's signed shim and GRUB | `lb config --uefi-secure-boot enable` | `os: secure boot shim` (information only for now) | 🔧 **Requires verification on real hardware with Secure Boot on** |

## 2. Next (in order)

1. **Recovery from the boot menu:** returning to a snapshot when the system does not boot.
2. **Firmware updates:** `fwupd`.
3. **Hibernation with LUKS:** swap or a swapfile.
4. **Unlocking with TPM:** `systemd-cryptenroll`.
5. **Night light, on-screen keyboard, screen magnifier.**
6. **Phone connection:** KDE Connect.
7. **Video codecs:** GStreamer.
8. **Common printer drivers.**
9. **A graphical app store:** on top of Flathub and Forge recipes.
10. **ARM.**

---

© 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0
