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

1. 🔧 **Recovery when the system does not boot: `dai-rescue` from the D.Ai USB.**
   - **Why not the boot menu:** `grub-btrfs` does not exist in Debian 13.
   - **What it does:**
     - Finds the installed disk (a Btrfs or LUKS partition that is not in use) and opens it. The passphrase goes to cryptsetup on stdin.
     - Runs the snapper of the installed system (`--root`) and shows when the last update was.
     - After confirmation, undoes that update. First it takes a safety snapshot, so the rescue itself can be undone too.
     - At the end the disk is always unmounted and closed again.
   - **Checks:**
     - **Unit:** finding disks, the passphrase only on stdin, closing even after a wrong passphrase, nothing changes without confirmation.
     - **VM** (`rescue: undo an update from the USB`): a real "installed system" on a Btrfs image, a pretend update, then `dai-rescue`. The file goes back, and a safety snapshot exists.
2. 🔧 **Packages and shortcuts:** in an optional list (`basics.list.optional`), so a package Debian 13 does not have is left out rather than breaking the build.
   - **Firmware updates:** `fwupd`.
   - **Video and audio codecs:** GStreamer, including `libav`.
   - **Printers:** most work with no driver (IPP Everywhere): `ipp-usb`, `cups-browsed`, `avahi-daemon`. For the rest: `printer-driver-gutenprint`, `printer-driver-brlaser`, `hplip`.
   - **Night light:** Super+Alt+N (`dai-nightlight`, ‏wlsunset, 19:00-07:00).
   - **On-screen keyboard:** Super+Alt+K (`dai-keyboard`, ‏wvkbd).
   - **Screen magnifier:** labwc's own. Super+= closer, Super+- back, Super+Alt+M on and off. **Requires verification** that the labwc version in Debian 13 supports these actions.
   - **Checks on the VM:** `os: firmware, codecs, printers` and `os: night light and on-screen keyboard`. Information only (WARN) until we see what Debian has.
3. **Hibernation with LUKS:** swap or a swapfile.
4. **Unlocking with TPM:** `systemd-cryptenroll`.
5. **Phone connection:** KDE Connect.
6. **A graphical app store:** on top of Flathub and Forge recipes.
7. **ARM.**

---

© 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0
