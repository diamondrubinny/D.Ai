# D.Ai VM: Windows on D.Ai, natively

> Written on 2026-10-19 after "build a native Parallels that can run a legal Windows; the user enters their
> own Windows key".
>
> **Decided (19 October 2026, "from now on you decide"):** the recommendations of §5, all of them: the screen in
> a `remote-viewer` window managed by D.Ai VM; the key typed into Windows setup only (no answer file in stage 1);
> the user and dev editions; virtio-win downloaded once with a pinned hash; the name "D.Ai VM".
> **Status: stages 1, 2 and 3 built** (§10–§13). Stage 4 not started. The Windows install itself is a manual test on a
> physical computer (§7); it has not been run yet.

## 10. Stage 1: what was built

- `apps/dai-vm`: `hardware.py` (VT-x/AMD-V from the CPU flags, `/dev/kvm` and whether this user may open it, memory
  with D.Ai's 4 GB kept, free disk, the tools, OVMF with Secure Boot keys; every finding a sentence with ok/warn/fail),
  `iso.py` (the ISO 9660 label, a "looks like Windows media" hint, the SHA-256 for the person to compare),
  `drivers.py` (virtio-win 0.1.302-1 pinned by SHA-256 in `data/drivers.json`, https only, hashed as it arrives,
  kept only when it matches), `machine.py` (the choices, the folder, `qemu-img`, and the libvirt definition:
  q35, `firmware="efi"` with `secure="yes"` so libvirt picks Debian's Microsoft-keyed OVMF, `tpm-crb` on swtpm,
  VirtIO disk, VirtIO network with the passt backend, SPICE on a Unix socket, QXL, USB tablet, sound, balloon,
  RNG, Hyper-V enlightenments and `localtime` for Windows; the SPICE agent channel and a virtiofs folder only
  when asked), `control.py` (virsh on `qemu:///session`, fixed argv), `gui.py` (the window and the wizard),
  `cli.py` (`check`, `list`, `create`, `start|stop|poweroff|pause|resume|show|delete`, `drivers`, `iso`).
- **D.Ai Tune:** "allow virtual machines" / "אפשר מכונות וירטואליות" is `vm.kvm_access`: the root helper adds
  the person (named in the plan by the person running Tune) to the `kvm` group; undo removes them unless they
  were in it before; takes effect at the next login.
- **Tests:** 29 for D.Ai VM (the hardware check on fake computers, the ISO reader, the drivers download that
  keeps nothing wrong, the definition's every device, the lifecycle through a fake virsh, the window with its
  wizard, buttons, viewer and deletion, Raz's audit in three themes, the command line) and 4 for the Tune
  sentence. CI: a VM check (no KVM there) that proves the stack is installed, `dai-vm check` says so honestly,
  and libvirt accepts a whole definition (`define`, `domstate`, `undefine`).
- **Image:** `qemu-system-x86`, `qemu-system-modules-spice`, `qemu-utils`, `libvirt-daemon(-driver-qemu)`,
  `libvirt-clients`, `virt-viewer`, `swtpm(-tools)`, `ovmf`, `passt` in the user and dev editions.
- **Not yet:** the real Windows 11 install on hardware (the checklist in §7 is the test), USB and clipboard
  switches (stage 2), a udev rule for USB passthrough, Doctor/MOM/Backup integration (stage 3), the memory
  measurement on the standard profile.
## 11. Stage 2: working together (what was built)

- **Switches per machine, off by default** (`machine.json`): the clipboard (the SPICE agent channel appears in
  the definition only when on), a shared folder (virtiofs with `memoryBacking` memfd/shared; read-only unless
  "Windows may also write" is ticked; never the whole home or the disk), and USB devices by id. `machine.update()`
  rewrites the definition and `virsh define` replaces libvirt's copy; a running machine takes the clipboard and
  folder at its next start, USB devices go in and out live (`attach-device --live` with a hostdev element).
- **USB:** `dai_vm.usb` lists the devices from sysfs (hubs left out, nothing opened); the window shows them as
  check boxes, the command line as `dai-vm usb NAME [attach|detach ID]`. While a machine has a device, D.Ai does
  not see it; that is said next to the switch.
- **Snapshots:** internal qcow2 snapshots through `virsh snapshot-create-as` (with memory when the machine runs),
  listed with their time and the current one marked, reverted after a confirmation, deleted. `dai-vm snapshot
  NAME take [LABEL] [--note TEXT] | list | revert | delete`. "Before Windows Update" as a Tune sentence is stage 3.
- **Tests:** 32 for D.Ai VM (the definition with folder, read-only flag, memfd and hostdev; validation of ids and
  folders; live attach and detach through the fake virsh with no XML left behind; snapshot argv, listing,
  revert and delete; the three commands; the window's switches, USB ticks, snapshots and Raz's audit with the
  touch and narrow passes). The VM check defines a machine with all three switches and takes and deletes a
  snapshot of it (no KVM in CI: define and qemu-img only).
- **Requires verification on hardware** (§7 checklist): virtiofsd under qemu:///session (libvirt starts it as the
  user; Windows needs WinFsp and the virtio-win virtiofs service from the drivers CD), SPICE clipboard with
  the guest agent installed, a USB device claimed by QEMU without a udev rule (session mode needs the device
  node writable by the user; a udev rule for a `dai-vm` group may be needed and is listed under stage 3),
  internal snapshots of a running machine with swtpm state.
- **Not yet:** sound and USB redirection through the SPICE viewer itself (works through `remote-viewer` today
  by its own menu), suspend to disk at logout, autostart of the guest tools.

## 12. Stage 3a: the machine by sentence (what was built)

- **D.Ai Tune:** "start Windows" / "הפעל את ווינדוס", "shut down Windows" / "כבה את ווינדוס", "snapshot Windows
  before the update" / "צילום מצב של ווינדוס לפני העדכון" (the snapshot is called `before-update`; without those
  words it gets the date). A machine may be named ("the machine called office" / "המכונה בשם office"); with one
  machine it is meant, with several Tune lists them and asks. Everything goes through `dai-vm` as the person
  (user scope, no root); undo shuts down what was started, starts what was stopped, deletes the snapshot.
- **VM check:** the sentence applied on the CI machine and undone, the snapshot seen and gone.
- **Not yet (stage 3b, see §13):** the taskbar entry and MOM's cost line for a running machine, Doctor's
  "Windows is slow because…", Backup's choice to include or skip the disks, Find skipping the disks.

## 13. Stage 3b: a machine like an app (what was built)

- **Its own entry in the menu and the taskbar:** `dai-vm create` writes `~/.local/share/applications/dai-vm-NAME.desktop`
  (name, "Windows 11 in D.Ai VM", the D.Ai VM icon, `Exec=dai-vm start NAME --show`, so one click starts the
  machine and opens its screen); `dai-vm delete` and the window's delete remove it with the machine. The entry
  carries `X-DAi-Machine=NAME` and `StartupWMClass=remote-viewer` (**requires a check** on the image that the
  viewer's Wayland app id is `remote-viewer`, so the taskbar groups its window under the entry).
- **MOM:** a running machine is one app, named after its launcher (or after the machine when there is none):
  QEMU, its TPM and the rest of its tree are counted together, with their memory and CPU, like any app; the
  D.Ai VM manager window stays its own app (a machine launcher's `dai-vm` command never captures it).
- **Doctor:** "why is Windows slow?" / "למה ווינדוס איטי?" (and in the six other languages) is the `machine`
  topic: no hardware acceleration (/dev/kvm not usable: virtualization off in the firmware) is the first and
  worst reason; a machine given 60% or more of the memory; Windows itself busy (QEMU at 50% or more: an
  update or an installer inside); little memory left while it runs; less than 8 GB where the disks live. Facts
  are read from D.Ai VM's own files, so Doctor needs nothing from `dai-vm`. All advice, no fix is applied.
- **Backup:** the machines' disks are left out unless asked (`dai-backup machines on`; the status shows the
  choice); when included, the machines folder is copied with the rest (restic deduplicates, but the first copy
  is tens of GB and takes a while, said plainly).
- **Find:** a machine's disk is never a search result (the machines folder is hidden under `~/.local`; a disk
  image the person keeps among their own files is still theirs to find).
- **USB passthrough without root:** `/etc/udev/rules.d/70-dai-vm-usb.rules` tags every non-hub USB device
  `uaccess`, so the person at the seat owns the device node while logged in and QEMU, running as them, can
  claim it. The trade-off is written in the rule: any program of the logged-in user may then talk to a
  plugged-in USB device directly (**requires a check** on real hardware, and a security review before release).
- **Tests:** the launcher written and removed with the machine, `start --show`; MOM's grouping (QEMU and its
  TPM under the launcher, a launcher-less machine named after itself, the manager window separate); Doctor's
  five reasons with levels, the healthy and the no-machine answers, Hebrew, facts from the files (a broken
  file skipped), the questions in English, Hebrew, Russian and German; Backup leaving the disk out, then
  copying it after `machines on`; Find. The VM check on the image: the launcher exists and is gone with the
  machine, `dai-doctor machine` answers (and sees that the CI machine has no acceleration), `udevadm verify`
  accepts the rule.
- **Not yet (stage 4):** Diamond's help inside the machine, a second machine kind (another Linux), the
  Tune posture sentence "Windows cannot see my files".

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
