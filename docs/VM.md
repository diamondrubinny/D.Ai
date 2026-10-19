# D.Ai VM: Windows on D.Ai, natively (plan for approval)

> Written on 2026-10-19 after "build a native Parallels that can run a legal Windows; the user enters their
> own Windows key". Nothing is built yet.
> The name "D.Ai VM" is descriptive. "Windows" is Microsoft's trademark and is used here only to name their
> product, never as part of D.Ai's name or branding (**requires a check** of Microsoft's trademark guidelines
> before publication).

## 0. What it is, and what it is not

- **A virtual machine manager built into D.Ai** for one purpose first: install and run the Windows the person
  already owns, from their own installation media, with their own key, inside a window on the D.Ai desktop.
  Other systems (another Linux, a test D.Ai) come for free, later.
- **Native:** KVM in the Linux kernel, QEMU (C), libvirt, and a PyQt6 window like every other D.Ai app. No
  proprietary hypervisor, no cloud, no account.
- **Legal by design, on D.Ai's side:**
  - D.Ai **never downloads, ships or mirrors Windows**. The person downloads the ISO from Microsoft themselves
    (D.Ai opens the official page in Ruby and then asks for the file).
  - D.Ai **never stores the product key** by default: the person types it into Windows setup, where it belongs.
    An optional "type it for me" fills it into an unattended-install answer file that is deleted after setup.
  - Whether a given Windows license may run in a virtual machine is set by **Microsoft's license terms for that
    edition** (retail, OEM, volume). D.Ai says this in the wizard and claims nothing (**requires legal review**
    of the exact wording).
- **Not Parallels:** no shared applications across the desktop at first ("Coherence"), no 3D games through the
  VM, no macOS. What Parallels does well and D.Ai will also do: one wizard, sensible defaults, shared folder,
  clipboard, USB devices, snapshots, and a machine that just appears as a window.

## 1. What is unique

1. **One sentence starts it:** "install Windows" in the Command bar opens the wizard; "start Windows",
   "snapshot Windows before the update", "give Windows the USB stick" are Tune sentences with undo.
2. **Private by default:** clipboard sharing and shared folders are **off** until turned on; the machine's
   network goes through `passt` in the person's own session, under D.Ai's default-deny firewall; the VM disk
   lives in the home folder, so it is on the encrypted disk. The wizard explains what Windows itself will send
   to Microsoft (telemetry), without pretending D.Ai can stop it.
3. **Windows 11 that installs:** TPM 2.0 (swtpm), UEFI with Secure Boot (OVMF with Microsoft's keys),
   VirtIO drivers attached as a second CD, so setup finds the disk and the network. The wizard checks the
   computer first (VT-x/AMD-V on, enough memory and disk) and says plainly when a computer is too weak.
4. **A machine like an app:** it appears in the taskbar, MOM shows what it costs in memory and CPU, Doctor
   explains why it is slow, Raz keeps a snapshot before Windows Update, Backup knows to back it up (or not).
5. **No root for daily use:** machines run under `qemu:///session`, the person's own user. Only enabling KVM
   access (a group) is done once through Tune's helper, journaled and undoable.

## 2. Scope

| Stage | What | Size |
|---|---|---|
| **1. Install and run** | Hardware check; wizard: ISO (from a file; the Microsoft page opened for download), edition detection (Windows 10/11, from the ISO's label and `install.wim` index), memory, CPUs, disk size, a name; the machine: UEFI (OVMF), TPM 2.0 (swtpm), VirtIO disk, network and graphics, VirtIO drivers CD (downloaded once from Fedora's virtio-win, pinned SHA-256, Apache-2.0/GPL drivers, like D.Ai's models); start, stop (ACPI then force), pause, the screen in a window (SPICE through `remote-viewer`), full screen, send Ctrl+Alt+Del; D.Ai themes for the manager window; keyboard and screen reader | Medium |
| **2. Working together** | Clipboard (opt-in, both directions or one), a shared folder (virtiofs, opt-in, a chosen folder only), USB devices by choice (a list; the device is detached from D.Ai while Windows has it), sound, autostart of the SPICE guest tools from the drivers CD, snapshots (qcow2, internal, with names and dates; "before Windows Update" by one sentence), suspend to disk at logout | Medium |
| **3. Part of D.Ai** | Taskbar entry with the Windows icon of the machine; MOM: the machine as one app, its cost; Doctor: "Windows is slow because…" (memory, no KVM, disk full); Raz: a snapshot before updates; Backup: include or skip the machine's disk; Tune posture: "Windows cannot see my files"; Find: skip the VM disks | Small |
| **4. Faster, optional** | GPU passthrough for a second graphics card (VFIO) with Looking Glass, hugepages, CPU pinning, a display widget inside the Qt window instead of a separate viewer window (**requires a check**: no Qt SPICE widget exists in Debian 13; options in §5) | Large |

Out of scope: running Windows applications as if they were D.Ai windows, macOS, Windows ARM on x86, DirectX
acceleration without a passed-through GPU, migrating a physical Windows installation into the machine
(possible later with `qemu-img` from a disk image; stage 5 if wanted).

## 3. Threat model (short)

| Asset | Threat | Control |
|---|---|---|
| D.Ai and the person's files | Windows (or malware inside it) reaches the host | KVM isolation; QEMU as the person's user with libvirt's AppArmor profile; no shared folders and no clipboard until enabled; USB only by explicit choice; VirtIO only (no legacy emulation beyond what setup needs) |
| The network | The machine attacks the local network or is reached from it | `passt` user-mode networking (no bridge, no raw sockets); the machine sees the network as a NAT client; incoming ports closed by default; D.Ai's firewall applies to the host |
| The product key | Stored or logged | Not stored by D.Ai by default; the optional answer file is `0600`, inside the person's encrypted home, and deleted after the first boot; never in the journal |
| The ISO | A fake "Windows" from a wrong site | The wizard shows the ISO's embedded label and edition, and the SHA-256 for the person to compare with Microsoft's page; D.Ai does not verify it against a list it does not have |
| Drivers | A tampered virtio-win download | Pinned URL and SHA-256 in `data/drivers.json` (like `models.json`); verified before use; downloaded only with the person's OK |
| Availability | The machine takes all memory or CPU | Limits chosen in the wizard; MOM's guard sees QEMU like any app; memory balloon on |
| Privacy | Windows telemetry | Outside D.Ai's control; stated in the wizard; the "private" posture blocks nothing inside Windows and says so |

## 4. Architecture

```
dai-vm (PyQt6 manager window, dai_style, dai_i18n)
 ├─ hardware.py   KVM present and usable (/dev/kvm, vmx/svm, the kvm group), memory, free disk, Secure Boot firmware
 ├─ iso.py        reads the ISO's label and install.wim/esd indexes (through `wimlib-imagex`, GPL, a program);
 │                detects Windows 10 / 11 and the editions inside; SHA-256 for the person
 ├─ drivers.py    virtio-win ISO: pinned URL and hash, download with progress, kept in ~/.local/share/dai/vm
 ├─ machine.py    libvirt domain XML: q35, UEFI (OVMF_CODE_4M.ms.fd + per-machine VARS), TPM 2.0 (swtpm),
 │                virtio-blk (qcow2), virtio-net on passt, virtio-gpu, SPICE, virtio-serial for the agent,
 │                memory balloon, CPU host-passthrough; qemu:///session
 ├─ unattended.py optional autounattend.xml (key, language, keyboard, local account), deleted after setup
 ├─ control.py    start, stop, pause, snapshots, USB attach/detach, shared folder, clipboard: libvirt calls
 ├─ viewer.py     launches `remote-viewer` on the machine's SPICE socket; full screen; Ctrl+Alt+Del
 ├─ gui.py        wizard and the machine list; status; the "what Windows can see" panel
 └─ cli.py        dai-vm check | create | start | stop | snapshot | usb | share | list
```

- **Packages (Debian 13, verified on packages.debian.org):** `qemu-system-x86` 10.0, `qemu-utils`,
  `libvirt-daemon` + `libvirt-clients` + `python3-libvirt` 11.3, `virt-viewer` 11.0 (`remote-viewer`),
  `swtpm` 0.7, `ovmf` 2025.02, `passt`, `virtiofsd` 1.13, `spice-vdagent` is a guest-side package (not needed
  on the host), `wimlib-imagex` (**requires a check** of the package name in trixie).
- **Session, not system:** `qemu:///session` needs no root and no libvirtd system service; `passt` gives it a
  usable network without a bridge. virtiofs with a session machine **requires a check** (virtiofsd as the user
  with `--sandbox=namespace`); fallback: a SPICE folder share or SMB through `passt`.
- **Size added to the user image:** QEMU, OVMF, libvirt and the viewer come to roughly 150–200 MB (**requires
  a check** on the built image). Proposal: in the **user** and **dev** editions; not in **edu** (schools manage
  machines differently) and not in **Lite**/server.
- **Windows 11 hardware checks:** TPM 2.0 and Secure Boot are satisfied by swtpm and OVMF's Microsoft-keyed
  firmware; the CPU list check is not enforced by setup on a VM with these (**requires a check** on a real
  install in the VM test).

## 5. Decisions needed

1. **Where the screen lives:** (a) a separate `remote-viewer` window launched and managed by D.Ai VM
   (recommended for stage 1: mature, fast, SPICE with clipboard and USB); (b) a widget inside the Qt window,
   which needs a SPICE or VNC client written for Qt (none in Debian 13; a VNC client in Python would be slow);
   (c) QEMU's own GTK display. Recommendation: (a), and revisit (b) in stage 4.
2. **The key:** typed into Windows setup only (recommended), or also the optional "type it for me" answer file.
3. **Editions:** user and dev only (recommended), or everywhere.
4. **Drivers download:** ask once and download virtio-win from Fedora (recommended), or ship the ISO in the
   image (+ about 600 MB: no).
5. **Name:** "D.Ai VM" (recommended) or a product name (trademark check).

## 6. Security, privacy and accessibility checklist

- libvirt session only; AppArmor profile for QEMU active; the `kvm` group added through Tune's helper with
  undo; no setuid helpers of D.Ai's own.
- Shared folder and clipboard default off; each shown in the "what Windows can see" panel with one switch.
- The key never written anywhere by default; the answer file path, mode and deletion are unit-tested.
- Hardware check says plainly: "no KVM: Windows would run 10–50 times slower; enable virtualization in the
  BIOS, or this computer cannot do it".
- The manager window passes Raz's audit in three themes; the wizard works with keyboard and screen reader; the
  viewer window is GTK (virt-viewer) and keeps its own accessibility.
- Journal: machine names and events; never the key, never the ISO path beyond debug level.

## 7. Tests and verification

- **Unit:** domain XML built right (UEFI, TPM, VirtIO, passt, no shared folder, no clipboard); hardware check
  on fake `/proc/cpuinfo` and `/dev/kvm`; ISO detection on a fixture ISO with a tiny WIM; drivers hash check;
  unattended file written `0600` and deleted; snapshot naming; CLI.
- **VM check (CI):** D.Ai runs inside QEMU already, without nested KVM; the check creates a machine
  definition, starts `swtpm` and QEMU in TCG for a few seconds with a blank disk, confirms UEFI firmware
  loads (serial), and stops it. A real Windows install cannot run in CI (no media, no license): it is a
  manual test on a physical computer, documented with a checklist.
- **Measure:** memory of the host with a 4 GB machine running on the standard profile (docs/HARDWARE.md).

## 8. Risks and limits

- **No KVM** on old computers or inside other VMs: Windows is unusable in TCG; the wizard refuses with an
  explanation.
- **Windows licensing:** OEM keys tied to a computer may not activate in a VM; D.Ai cannot fix that and says so.
- **Secure Boot and the firmware:** Debian's `ovmf` ships `OVMF_CODE_4M.ms.fd` with Microsoft keys; its exact
  file names **require a check** on the built image.
- **virtio-win from Fedora:** an external download; if the URL moves, the pinned entry is updated like a model.
- **Sound and USB** in a session machine: SPICE handles both; USB passthrough needs device permissions
  (udev rule for the person's user) **requires a check**.
- **Memory on 8 GB computers:** a 4 GB Windows leaves D.Ai with 4 GB; the wizard's default is 25–50% of the
  memory, never more than leaves 4 GB to D.Ai.

## 9. Order of work

Stage 1 → unit tests and the CI firmware check → a manual Windows 11 install on real hardware with the
checklist → screenshots and README row → stage 2 → stage 3 → stage 4 only if asked.
