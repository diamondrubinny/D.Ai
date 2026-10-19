# D.Ai Server and D.Ai Standalone: internal servers, hardened by default

> Written on 2026-10-19 after "add a server version and a standalone version for internal servers, with an
> emphasis on stronger security". **Plan only, for approval. Nothing here is built.**
>
> This document does not claim compliance with any standard or law. Every such statement below is marked
> **requires verification against the official source** or **requires legal review**.

## 0. What I understood, and what I assume

- **Server:** a D.Ai image for a server inside an organisation: no desktop, no graphical apps, administered
  over SSH from another computer, running the services the organisation chooses.
- **Standalone:** I read it as a single hardened server that **works without any connection to the internet
  or to us**: updates arrive as a signed bundle on a USB drive, and nothing is downloaded at run time. This is
  the usual meaning of "air-gapped" or "appliance".
- **Assumptions** (change them if they are wrong):
  1. Both are amd64 only, as all D.Ai editions today (`docs/HARDWARE.md` §0).
  2. Both are installed by the existing installer (Calamares + LUKS, `docs/INSTALL.md`), with a server
     install path added.
  3. No local AI, no voice, no D.Ai Chat, no browser, and no mail client in either edition. Each is a
     source of attack surface that a server does not need.
  4. The administrator is technical. The graphical tools (D.Ai Tune's text commands, Command) are replaced by
     the command line, with the same plans, confirmations and undo.

## 1. Questions (answer them, or I take the stated default)

1. ~~**Standalone:**~~ **Answered:** air-gapped, with no network hardware at all (§1b).
   The two open questions of this variant are **decided in §1c** (media through a controlled station; signing
   by 2 of 3 holders, applying with a second confirmation).
2. **Which role first:** a general server (**default**: SSH, a firewall, backups, logs), file storage, or an
   internal web application?
3. **Administration:** only from a fixed list of computers on the internal network (**default**), or from
   anywhere through a VPN (requires a separate design)?

## 1b. Air-gapped variant for banks and highly sensitive data (decision, 19 October 2026)

The standalone edition is for computers with **no network connection at all**: no network cable, no wireless
devices, no phones, and no internet, ever. The rules below apply on top of §4, and they are stricter than the
defaults above:

1. **No network hardware in use.** The image has no driver or firmware for any network interface, Wi-Fi or
   Bluetooth. The kernel loads none of them (blacklisted, and the modules are removed from the image).
   Wi-Fi and Bluetooth are switched off in the firmware (BIOS/UEFI) and, where the hardware allows, disabled
   in hardware. The boot checks confirm that no network interface exists.
2. **No ports that can carry data out, by default.** USB ports are blocked for all devices, including
   keyboards and mice, except devices approved by serial number (USBGuard, **requires a check** on the
   hardware, since a keyboard that is blocked locks the person out). Thunderbolt, PCIe slots and similar
   ports are disabled in firmware when the hardware allows it.
3. **No phones, no external wireless devices:** the rules are part of the procedure for the room as well
   (a physical rule, not a software control; the software only detects and logs what it sees).
4. **Crossing the air gap is a procedure, not a convenience.** An update or a file comes in through one
   controlled media station, outside the air-gapped computer: the media is scanned, the signature and the
   hashes of the bundle are checked there, and only then is it moved in, on media approved for this purpose.
   The air-gapped computer checks the bundle again before it applies anything (§6 of this plan).
5. **Nothing leaves by design.** Logs and audit records stay on the computer. Exporting them is the same
   procedure as importing, in the other direction, with the same checks and a written record.
6. **Local console only:** no SSH, no remote administration. Administration happens at the machine, by two
   people where the policy requires it (**requires a decision**: the number of people and the roles).
7. **Physical and boot protection:** full-disk encryption with a passphrase only (no automatic unlock by a
   chip in the machine, so theft of the disk alone is not enough); a boot password; Secure Boot where
   possible; measured boot (TPM) for detecting changes, if the organisation wants it (**requires a check**).
8. **Keys are kept outside the computer.** The signing key of the update bundles is never on the computer
   that receives them. Who holds it, how it is rotated, and what happens if it is lost is a decision the
   organisation must make before stage 4 (§10).

**What this means for the design:** the update path in §6 is the most sensitive part. It is a transfer with
a human procedure, not an automatic one, and it has to be tested on paper and on the machine.

**Requires legal review and verification:** the requirements of the banking supervisor and of the
organisation's own information security policy are not summarised here. They must be checked against the
official text (for banks: the Bank of Israel's directives on information security) before this edition is
sold or installed for any bank.

## 1c. Decisions for the air-gapped variant (made on 19 October 2026 at the owner's request; changeable)

The owner asked the assistant to decide the two open questions. These are the decisions, with the reason for
each. Any of them can be changed, and each change is recorded here with its date.

**Decision 1: media may cross the air gap, but only through a controlled media station, never directly.**
- No USB storage device is ever connected to the air-gapped computer. Its USB ports accept only the approved
  keyboard and mouse (§1b, rule 2).
- Every file (an update bundle, or a file needed for work) arrives on **single-use, write-once media** from the
  media station, which is a separate computer with no connection to the air-gapped one.
- At the media station the file is scanned with ClamAV, its signature is checked, and its hash is written on
  paper and in the station's log. The station is run by a person who is not the one who approves the update.
- On the air-gapped computer the bundle is checked again (signature and hashes) before anything is applied.
- Every crossing is recorded in a log kept on the air-gapped computer and printed. Nothing leaves that way.
- **Why not a one-way data diode now:** it is the strongest option, but it is expensive, needs specialist
  hardware and a separate security review, and a badly built one is itself a new risk. It is a candidate for
  a later stage, after the owner sees the cost.

**Decision 2: two people for signing and two people for applying.**
- **Signing:** the update-signing key is held by **three holders, and any two of them are needed to sign** (2 of 3).
  The key is never on the air-gapped computer, and never on a computer that is connected to a network.
  It is kept on an offline device (an offline computer or a hardware token, to be chosen).
- **Applying:** an update is applied on the air-gapped computer by one administrator, and it is **confirmed by a
  second person** in the log (four eyes). The software refuses a bundle that lacks the second confirmation.
- **Verification:** the air-gapped computer holds only the **public** key. A lost or leaked key is handled by a
  written procedure: revoke the key, build and sign a new one, and deliver the new public key by the same media
  procedure.
- **Why 2 of 3:** one person cannot sign alone, and losing one holder does not lock the organisation out.
- **Requires legal review and the organisation's own procedure:** who the three holders are, how they are
  chosen and replaced, and the written key-ceremony steps. The plan defines the rule; a person must own it.

## 2. Editions

| | D.Ai Server | D.Ai Standalone |
|---|---|---|
| Desktop | None | None |
| Network | Connected; the organisation's network | Offline by default; the network is opt-in |
| Updates | From the organisation's own mirror of the D.Ai apt repository, signed (the repository already signs, `docs/RELEASE.md`) | A signed update bundle on USB, checked before it is applied |
| Telemetry | None (as all D.Ai) | None; no network calls at all after install |
| Admin access | SSH with keys, from listed computers | Local console with a password and a boot password; SSH off by default |
| Services | Chosen during install, each with its own firewall rule | None by default; a role is added explicitly |
| Snapshots | Btrfs, before every update, with a way back | Same, plus the bundle's hash recorded |
| Recovery | Encrypted backup to an external drive (D.Ai Backup) | Same, and an offline recovery USB created at install |

## 3. Threat model (short)

- **Assets:** the data on the server, the credentials and keys, the backups, the logs (they contain personal
  data: IP addresses and user names), and the update channel.
- **Entry points:** SSH, each service the role opens, the network port of each service, USB ports, the boot
  menu, and the update path (mirror or USB bundle).
- **Threats and the control planned:**

| Threat | Control |
|---|---|
| Guessed passwords and stolen passwords | SSH keys only; password login off; account lockout after repeated failures; optional second factor (**requires a check** of the PAM module before choosing one) |
| An unpatched service | Unattended security updates (server); signed bundles (standalone); only the services the role needs are installed |
| Spread inside the network after one break-in | Default-deny firewall per role; no shared passwords; each service in its own AppArmor profile |
| Stolen disk | Full-disk encryption (LUKS2), passphrase at boot; boot menu locked with a password |
| A tampered system file or program | AIDE baseline after install, checked daily; signed packages; Secure Boot where the hardware and the signing keys allow (**requires a check**: key management is a decision of its own) |
| Ransomware or a bad change | Btrfs snapshots before every update and change; encrypted backups, with a tested restore |
| No evidence after an incident | auditd rules for logins, privilege use, changes to `/etc`, and module loads; logs kept locally for a set time, then deleted |
| A fake or changed update | Signature check before anything is installed (apt for the server; the bundle's signature for the standalone) |
| Errors by the administrator | Plans and confirmations from Tune; every change has an undo; the risky changes ask twice |

## 4. The hardening baseline (what a fresh install gets)

The baseline is **the same for both editions**, with the differences in §2. Each item has a check that Tune's
posture score runs, so a person can see the state and the fix.

1. **Boot and disk:** LUKS2 full-disk encryption; GRUB password for editing the boot menu; no live user.
2. **Kernel:** `sysctl` hardening (reverse-path filtering, no ICMP redirects, `kptr_restrict`, `dmesg_restrict`,
   `unprivileged_bpf_disabled`, `yama.ptrace_scope`); modules for unused protocols and file systems blacklisted;
   kernel lockdown where the kernel supports it.
3. **Accounts:** no root login by SSH; `sudo` logged; password quality and aging; `faillock` after repeated
   failures; no guest account; inactive accounts locked after a set number of days.
4. **SSH:** key-only; `PermitRootLogin no`; `AllowUsers` list; short idle timeouts; strong ciphers only (the
   list is taken from the OpenSSH manual at build time, **requires verification against the official source**).
5. **Firewall:** `nftables` default-deny inbound; one rule per open port, with a source address list; rate limit
   on SSH; the existing `dai_filter` table (`docs/TUNE.md`) extended per role.
6. **Mandatory access control:** AppArmor in enforce mode for every installed service; the check counts the
   profiles in complain mode and fails if any.
7. **Audit:** `auditd` with rules for authentication, `sudo`, changes under `/etc`, `/boot` and `/usr/lib`, module
   loads, and time changes; a 90-day local retention, configurable (**requires legal review** for the
   retention period, see §7).
8. **Integrity:** AIDE, with a database created after the first boot and checked daily; the report is a local
   file and an alert.
9. **Services that are not needed are removed**, not only stopped: avahi, cups, bluetooth, and the desktop
   stack on the server edition.
10. **Time:** `chrony` against the organisation's time source (the default is none; the install asks for one).
11. **Secrets:** no password or key in any file of the image or in the repository. Services read secrets from
    `systemd` credentials or from a file with mode 0600, owned by the service.
12. **Logs:** no passwords, tokens or message bodies in logs (the same rule as all D.Ai apps).

## 5. Tune, the posture score, and the presets

- **New presets** in D.Ai Tune: `server-hardened` and `standalone-hardened`, each a plan that can be shown
  before it is applied, with an undo for each step (Tune already keeps a journal).
- **The posture score** gets new checks, each with a fix phrase: key-only SSH, root login off, auditd
  running with the rules, AIDE baseline present, AppArmor enforce count, unattended updates (server),
  no unexpected listening port, no unused services, and time synchronised.
- **Score rules:** the score says what is missing; it does **not** say the server is secure. That wording goes in
  the interface and the documentation.

## 6. Standalone: the offline update path

- An update is a **bundle** built by us: the packages, their hashes, and a signature made with a key kept
  offline (**requires a decision**: who holds the key, how it is rotated, and what happens if it is lost).
- The administrator copies the bundle to a USB drive. Tune checks the signature and the hashes, shows what will
  change, takes a snapshot, and applies it. It can be undone from the snapshot.
- The bundle and its signature are checked **before** anything on the system is changed.
- USB storage is blocked by default (Tune already has a preset for this, `docs/TUNE.md`), and enabled only for
  the update step.

## 7. Legal and compliance (requires legal review and verification)

- **Standards:** this plan does not claim that either edition complies with ISO/IEC 27001, SOC 2, NIST SP 800-53,
  or the Israeli national cyber directorate's baselines. Any mapping to them **requires verification against the
  official text** and a qualified assessor.
- **Israeli privacy law (the Protection of Privacy Law, including Amendment 13):** an internal server that stores
  personal data of staff or customers needs a data map, a retention policy, and a decision about who is the
  database owner. **Requires legal review.**
- **Logs as personal data:** IP addresses and user names in audit logs are personal data. Retention is a
  choice that needs a legal opinion; the 90-day default is a placeholder, not advice.
- **Cryptography:** the algorithms in §4 are chosen from current recommendations; the export and use rules for
  strong encryption **require legal review** before the edition is offered outside Israel.

## 8. Verification

1. **Build-time:** `nft -c` checks the firewall files; `sshd -t` checks the SSH configuration; `apparmor_parser -p`
   checks the profiles; `sysctl` files are checked for keys that do not exist on the kernel in use.
2. **Boot test in CI** (extends `tests/boot`): the server image boots with no desktop; the checks run over the
   serial console: key-only SSH (a password attempt is refused), default-deny firewall, auditd running, AIDE
   baseline present, AppArmor enforce. Each check fails the build.
3. **A benchmark scan** (OpenSCAP or Lynis) runs on every build and its report is published with the release.
   **It is a score, not a compliance result**, and the report says so.
4. **The standalone bundle:** a test that a modified bundle is refused, a bundle with a wrong hash is refused,
   and a valid bundle applies and can be undone.
5. **Before any production use:** the pre-production checklist (functional tests, roles and permissions,
   sessions and login, input and uploads, secrets, dependencies and known vulnerabilities, backup and restore,
   the data map, cookies and trackers if a web panel exists, the legal review of §7). **An external penetration
   test is required before production use. It is not replaced by anything in this repository.**

## 9. Stages (each one waits for approval)

1. **Answers to §1**, and approval of the baseline in §4 (this document).
2. **Server edition, headless:** the build (`build-iso.sh server`), no desktop, the baseline §4, and the boot
   checks in CI.
3. **Hardening presets and the posture checks** in Tune, with plans and undo, and tests for each.
4. **Standalone:** the offline bundle format, the signature check, the USB step, and its tests.
5. **Audit, AIDE and the log retention**, with the legal review of §7 done first.
6. **External review** of the configuration, and the documentation for administrators (the security guide
   and the recovery steps).

## 10. Risks and open decisions

- **Key management** for signed bundles and for Secure Boot: a decision with real consequences if a key is lost
  or leaked. Needs an owner before stage 4.
- **Maintenance burden:** each hardening rule is a rule someone must keep correct when a package changes. The
  CI checks in §8 are what keep this manageable.
- **Strong defaults break things:** key-only SSH and default-deny firewalls lock out people who do not
  have their key set up. The installer must check that a key works before it disables passwords.
- **Claims:** the interface and the documents must not say "secure" or "compliant" as a result. The posture
  score is a checklist, not a guarantee.
- **Not included in either edition:** a central management console, clustering, a web administration panel,
  and remote access from outside the network. Each is a separate design and a separate threat model.
