# D.Ai on every computer, from very old to new: a plan for approval

> Written on 2026-10-19 after "the operating system should work on every computer, with versions from very
> old computers to the newest, and run smoothly", and the question "can it be written as a native operating
> system?".
>
> **Decided (19 October 2026):** start with measurements (stage 1, §4). **No 32-bit edition**: D.Ai stays
> 64-bit only. **Still open:** the memory minimum for Lite (§5.2).

## 0. Where D.Ai stands today

- **One edition family (user, dev, edu), 64-bit PCs only (amd64)**, on Debian 13.
- **Starts from BIOS and UEFI:** a hybrid ISO, with syslinux and GRUB.
- **Already good for older computers:**
  - zram (compressed memory);
  - a light desktop (labwc and LXQt);
  - a local AI built for every CPU generation. llama.cpp and whisper.cpp pick their CPU code at run time (`GGML_CPU_ALL_VARIANTS`), so a processor without AVX still works, just more slowly.
- **What blocks very old computers:**
  - Debian 13 no longer supports 32-bit PCs (i386): no kernel and no installer. Debian recommends reinstalling as amd64 where possible, or retiring the hardware. ([Debian 13 announcement](https://www.debian.org/News/2025/20250809.en.html))
  - Debian 12 still supports i386 in its long-term support, **until 30 June 2028**. ([bookworm LTS](https://www.debian.org/News/2026/20260712.en.html))
  - After that only paid extended support remains (Freexian ELTS), outside Debian.
- **What we do not measure yet:**
  - how long it takes from power-on to the desktop;
  - how much memory an idle desktop uses;
  - how long each window takes to open on a weak computer.

  Without numbers, "smooth" is a guess.

## 1. The editions (proposal)

| Edition | For | Base | Inside | Minimum (target) |
|---|---|---|---|---|
| **D.Ai** (today's) | Computers from about 2012 on, and new ones | Debian 13, amd64 | Everything, including the local AI and voice | 4 GB memory, 2 cores, 32 GB disk. AI: 8 GB recommended |
| **D.Ai Lite** | Old 64-bit computers, roughly 2007–2012 (Core 2, Athlon 64), hard disks | Debian 13, amd64 | All of D.Ai except the local AI and voice (they can be added later); lighter defaults | 2 GB memory, 1 core, 16 GB disk |
| **D.Ai ARM** (started) | ARM boxes and laptops with UEFI firmware now (the tv edition, `docs/TV.md` §14, and the phone, `docs/MOBILE.md` C1a, both booted in QEMU in CI); the Raspberry Pi 4/5 with their own firmware later | Debian 13, arm64 | Like Lite: no local AI or voice (amd64 runtimes) | Measured on the device |

**Notes:**
- **New hardware:** the newest computers (new Wi-Fi, graphics cards and processors) sometimes need a newer kernel than Debian's.
  - Proposal: the installer offers the trixie-backports kernel when it finds hardware the regular kernel does not run. Tune keeps a way back.
  - Firmware (non-free-firmware) stays on the image.
- **32-bit, honestly:** a second Debian base (12 next to 13) means a second set of packages to build, test and update, and it ends in 2028.
  - The other option is to tell the owners of these computers clearly that D.Ai needs a 64-bit processor (almost every computer since about 2007).
  - **This is a decision for you** (§5).

### Stage 1 results (CI, run 39272473637, user edition, one run each)

| Profile | Memory | CPUs | Login | Desktop (LXQt panel) | Memory in use, 60 s idle | Load 1 min after |
|---|---|---|---|---|---|---|
| weak | 2 GB | 1 | 132 s | 162 s | 525 MB of 1973 MB | 5.27 |
| standard | 4 GB | 2 | 113 s | 127 s | 641 MB of 3921 MB | 2.48 |

**How to read these:**
- **Acceleration: TCG for both**, which is software emulation of the CPU. The CI runner has no KVM, so **the times say nothing about a real computer**. A real CPU is many times faster.
- **Memory in use** does not depend much on emulation, so it is the most useful number here. It is still one idle minute of one run.
- **Only one run per profile.** The spread is unknown until the job has run several times.
- **The guesses in §2** (25 s, 900 MB, and so on) were written before any measurement. The memory guesses are in the same range as these results, but that proves nothing yet.

## 2. Smooth on every computer: measured, not assumed

1. **A performance budget in CI, per edition.** Every build boots in QEMU with a weak setup and measures:
   - the time to the desktop;
   - idle memory;
   - how long D.Ai Command, Tune and the Chat window take to open.

   Over budget fails the build, like a failed test. First targets (to tune after the first measurement):

   | | D.Ai (4 GB, 2 cores) | Lite (2 GB, 1 core, HDD) |
   |---|---|---|
   | To the desktop | 25 s | 40 s |
   | Idle memory | 900 MB | 550 MB |
   | Command bar opens | 0.3 s | 0.6 s |

   These numbers are guesses until stage 1 measures them on real hardware. They are not gates yet.

2. **A profile chosen at first start, from the hardware, shown and undoable in Tune.**
   - Little memory: no AI model loaded at startup, and no animations.
   - A hard disk: the BFQ I/O scheduler and fewer background scans.
   - A weak graphics card: no transparency.
   - A laptop: power saving.
3. **Windows that open fast.**
   - The command bar stays loaded in the background, so it appears at once.
   - Programs load what they need only when it is needed.
   - Python bytecode is built when the package is installed, not on first run.
4. **Background work never competes with the person.** Scans, updates, indexing and backups run at low priority and pause on battery or when the computer is busy (MOM already watches for runaways).

## 3. "Native": what it means, and what we recommend

- **D.Ai is already a native operating system:**
  - the Linux kernel, drivers, the compositor (labwc), Qt, the panel plugin (C++) and the AI engines (C/C++) are all native code;
  - the Python parts are the apps' logic. Their windows are drawn by Qt, which is native code.
- **Writing a whole operating system from scratch (our own kernel) is not recommended.**
  - Hardware support, Wi-Fi, graphics cards, printers and sleep on thousands of devices took Linux decades and thousands of developers.
  - A kernel of our own would run on very few computers: the opposite of "every computer".
- **The recommendation:**
  - keep Linux and Debian;
  - **measure** (§2), and rewrite as native code (C++ with Qt, or Rust) only what is over budget on weak computers. The first candidates are the command bar and the Chat background service;
  - one cheap step before a rewrite: compile the Python apps to native binaries with Nuitka, then measure whether it helps (it **requires a check**; the gain is usually in startup time).

## 4. Stages (each one waits for approval)

1. **Measure (started):** `tests/boot/measure.py`, run by `boot-test.sh` with `MEASURE_JSON`, in a CI job `measure` after the user edition's build. Two profiles on the same ISO: **weak** (2 GB, 1 CPU) and **standard** (4 GB, 2 CPUs). It records seconds to the login prompt, seconds to the LXQt panel, and memory in use after a minute idle, and says whether KVM or emulation was used. The job is not required, and nothing is gated yet: budgets come after a few runs show the spread. Not measured yet: how long a window takes to open (needs a GUI timer), and real hardware (needs a physical old computer).
2. **Lite:** a "lite" edition in `build-iso.sh` (without the AI and voice runtimes), the first-start hardware profile through Tune, and the budget checks for Lite.
3. **New hardware:** the backports kernel offered when needed, with a test on new hardware (a QEMU machine type, plus reports from people).
4. **Native where it pays:** rewrite what the measurements show is slow.
5. **ARM** (started): arm64 images build and boot in CI for the tv and phone editions (generic UEFI; `DAI_ARCH=arm64 build-iso.sh <edition>`); the Raspberry Pi's own firmware and boot partition are the next step.

## 5. Decisions needed

1. ~~**32-bit computers:**~~ **Decided: no 32-bit edition.** D.Ai needs a 64-bit processor, and the download page says so.
2. **The minimum for Lite:** 2 GB of memory (the proposal), or lower? To be set from the stage 1 measurements.
3. ~~**Order:**~~ **Decided: start with measuring.**

## 6. Risks

- **Budgets that are too tight** can fail builds because of CI noise. They should be measured a few times before they block.
- **Very old graphics cards:** labwc (Wayland) needs a working kernel graphics driver. On a card without one, a software fallback is slow.
  - A computer that needs X11 instead of Wayland would need a check on real hardware (**requires a check**). D.Ai does not support X11 today.
