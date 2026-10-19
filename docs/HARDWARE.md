# D.Ai on every computer, from very old to new: a plan for approval

> Written on 2026-10-19 after "the operating system should work on every computer, with versions from very
> old computers to the newest, and run smoothly", and the question "can it be written as a native operating
> system?". **Nothing here is built yet: it waits for approval.**

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
| **D.Ai Legacy 32** | 32-bit-only computers (Pentium 4, Atom N270 and older) | Debian 12, i386 | Desktop, browser, Command, Tune, Find, Backup, Chat; no AI | 1 GB memory. **Until June 2028 only** |
| **D.Ai ARM** (later) | Raspberry Pi 4/5, ARM laptops | Debian 13, arm64 | Like Lite at first | Measured on the device |

**Notes:**
- **New hardware:** the newest computers (new Wi-Fi, graphics cards and processors) sometimes need a newer kernel than Debian's.
  - Proposal: the installer offers the trixie-backports kernel when it finds hardware the regular kernel does not run. Tune keeps a way back.
  - Firmware (non-free-firmware) stays on the image.
- **32-bit, honestly:** a second Debian base (12 next to 13) means a second set of packages to build, test and update, and it ends in 2028.
  - The other option is to tell the owners of these computers clearly that D.Ai needs a 64-bit processor (almost every computer since about 2007).
  - **This is a decision for you** (§5).

## 2. Smooth on every computer: measured, not assumed

1. **A performance budget in CI, per edition.** Every build boots in QEMU with a weak setup and measures:
   - the time to the desktop;
   - idle memory;
   - how long D.Ai Command, Tune and the Chat window take to open.

   Over budget fails the build, like a failed test. First targets (to tune after the first measurement):

   | | D.Ai (4 GB, 2 cores) | Lite (2 GB, 1 core, HDD) | Legacy 32 (1 GB) |
   |---|---|---|---|
   | To the desktop | 25 s | 40 s | 60 s |
   | Idle memory | 900 MB | 550 MB | 350 MB |
   | Command bar opens | 0.3 s | 0.6 s | 1 s |

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

1. **Measure:** the performance budget in CI for today's edition, plus a weak QEMU run (2 GB, 1 core). The numbers become the baseline.
2. **Lite:** a "lite" edition in `build-iso.sh` (without the AI and voice runtimes), the first-start hardware profile through Tune, and the budget checks for Lite.
3. **New hardware:** the backports kernel offered when needed, with a test on new hardware (a QEMU machine type, plus reports from people).
4. **Native where it pays:** rewrite what the measurements show is slow.
5. **Legacy 32** (only if approved): a Debian 12 i386 build with a limited set of apps, its own budget, and an end date stated on the download page.
6. **ARM** (later): arm64 images for the Raspberry Pi first.

## 5. Decisions needed

1. **32-bit computers:** build Legacy 32 on Debian 12 until June 2028, or state that D.Ai needs a 64-bit processor?
2. **The minimum for Lite:** 2 GB of memory (the proposal), or lower?
3. **Order:** start with measuring (stage 1, recommended), or with Lite?

## 6. Risks

- **Legacy 32:** a second base to maintain; it ends in 2028, and after that it is unsafe without paid support.
- **Budgets that are too tight** can fail builds because of CI noise. They should be measured a few times before they block.
- **Very old graphics cards:** labwc (Wayland) needs a working kernel graphics driver. On a card without one, a software fallback is slow.
  - Legacy 32 may need X11 instead (**requires a check** on real hardware).
