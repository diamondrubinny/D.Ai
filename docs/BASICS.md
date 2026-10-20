# OS basics: what was missing and what is being fixed

> Written on 2026-10-18 after "what else is missing as an operating system?". Every item: a check on the VM in CI (`tests/boot/serial_check.py`), then a fix.
> ✅ = fixed and passes the check · 🔧 = fix submitted, waiting for CI · ⏳ = next

## 1. Possibly broken (stage 1)

| What | Problem | Fix | Check on the VM | Status |
|------|---------|-----|-----------------|--------|
| Drives mount by themselves | `udisks2` and `gvfs` were not in the package list, and recommends are off | `udisks2`, `gvfs`, `gvfs-backends` | `os: drives mount by themselves` | ✅ udisks2 active, gvfs present |
| Screens on Wayland | `lxqt-config-monitor` works only on X11 | `wlr-randr`, and `wdisplays` (a window, an optional package) | `os: screens on Wayland` | ✅ `wlr-randr` reads the screen (1280x800), `wdisplays` installed |
| Screenshots | `screengrab` does not work well on Wayland | `dai-screenshot` (grim): Print for the whole screen, Shift+Print for an area (slurp). To `~/Pictures/Screenshots` and the clipboard | `os: screenshot (Print)` | ✅ a real screenshot is saved |
| Secure Boot | The ISO did not ask live-build for Debian's signed shim and GRUB | `lb config --uefi-secure-boot enable` | `os: secure boot shim` (information only for now) | ✅ on the medium `EFI/boot/bootx64.efi` is Debian's shim, and `grubx64.efi` is next to it. **Still requires verification on real hardware with Secure Boot on** |

## 2. Next (in order)

**Screenshots** (the `ci-screenshots` branch, from every CI run): in addition to the existing ones, `j.png`, `find.png`, `doctor.png`, `heal.png`, `keyboard.png`, `magnifier.png`, and the boot menu: `boot-menu.png` and `boot-languages.png`. For the boot menu, a second short boot of the ISO through its own menu runs at the end of the test.


1. ✅ **Recovery when the system does not boot: `dai-rescue` from the D.Ai USB.** Passes on the VM in CI (be82d51).
   - **Why not the boot menu:** `grub-btrfs` does not exist in Debian 13.
   - **What it does:**
     - Finds the installed disk (a Btrfs or LUKS partition that is not in use) and opens it. The passphrase goes to cryptsetup on stdin.
     - Reads snapper's snapshots straight from the disk (`@/.snapshots/N/info.xml`) and shows when the last update was.
     - After confirmation, the whole system goes back to its snapshot from before that update:
       - a writable copy of the "pre" snapshot becomes `@`;
       - the system as it was is kept whole as `@.before-rescue-<time>`;
       - the snapshots move into the new `@`.
     - **Only `btrfs` and `mv` from the USB.** Nothing runs inside the installed system.
     - To undo the rescue: rename the subvolumes back.
     - At the end the disk is always unmounted and closed again.
   - **What was learned in CI:** the first version ran snapper with `--root` on the installed disk. On the VM it turned out that snapper looks at the filesystem of the system it runs on (the overlay of the live USB) and not at the disk. That is dangerous for an undo, so snapper is not used for it at all.
   - **Checks:**
     - **Unit:** finding disks, the passphrase only on stdin, closing even after a wrong passphrase, reading snapper's files, the exact order of the commands, nothing changes without confirmation.
     - **VM** (`rescue: undo an update from the USB`): an "installed system" on a Btrfs image, with snapper's layout and read-only snapshots. After `dai-rescue` the file is as before the update, the old system is kept with its file from after the update, and the snapshots stay.
2. ✅ **Packages and shortcuts:** in an optional list (`basics.list.optional`), so a package Debian 13 does not have is left out rather than breaking the build.
   - **Firmware updates:** `fwupd`.
   - **Video and audio codecs:** GStreamer, including `libav`.
   - **Printers:** most work with no driver (IPP Everywhere): `ipp-usb`, `cups-browsed`, `avahi-daemon`. For the rest: `printer-driver-gutenprint`, `printer-driver-brlaser`, `hplip`.
   - **Night light:** Super+Alt+N (`dai-nightlight`, ‏wlsunset, 19:00-07:00).
   - **On-screen keyboard:** Super+Alt+K (`dai-keyboard`, ‏wvkbd). In touch mode ([MOBILE.md](MOBILE.md) A1) it starts hidden at login and the key shows and hides it.
   - **Screen magnifier:** labwc's own. Super+= closer, Super+- back, Super+Alt+M on and off. **Requires verification** that the labwc version in Debian 13 supports these actions.
   - **Checks on the VM:** `os: night light and on-screen keyboard` ✅ (labwc 0.8.3, wlsunset runs, wvkbd installed). `os: firmware, codecs, printers`: the first run showed fwupd and hplip installed. The check itself was wrong (`fwupdmgr --version` does not print "fwupd"), and it was fixed.
3. **Hibernation with LUKS:** swap or a swapfile.
4. **Unlocking with TPM:** `systemd-cryptenroll`.
5. **Phone connection:** KDE Connect.
6. **A graphical app store:** on top of Flathub and Forge recipes.
7. **ARM.**

---

© 2026 Diamond Rubinny (d.Ai) · D.Ai OS · Apache-2.0
