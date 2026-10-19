# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Can this computer run a machine well? (docs/VM.md §1, point 3; §8.)

Read-only, as the user. Every finding is a sentence in the person's language, with a level:
  ok     fine
  warn   it will work, with a cost
  fail   a machine cannot run (or should not be created) until this changes
"""
from __future__ import annotations

import grp
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from dai_i18n import pick

MIN_HOST_MB = 4096        # what D.Ai keeps for itself
MIN_GUEST_MB = 2048       # the least Windows 10/11 runs with at all
MAX_GUEST_MB = 16384
MIN_DISK_GB = 40          # Windows 11 wants 64 GB; a qcow2 grows as used, so this is a floor for sanity
TOOLS = ("qemu-system-x86_64", "qemu-img", "virsh", "swtpm", "remote-viewer", "passt")


def say(lang: str, en: str, he: str, **kwargs: object) -> str:
    return pick(lang, en, he).format(**kwargs)


@dataclass
class Finding:
    level: str   # ok | warn | fail
    key: str
    text: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    memory_mb: int = 0
    free_gb: float = 0.0
    kvm: bool = False
    virtualization: str | None = None   # "intel" | "amd" | None

    @property
    def can_run(self) -> bool:
        return not any(f.level == "fail" for f in self.findings)

    def recommended_memory_mb(self) -> int:
        """Half the memory, never above 8 GB, never leaving D.Ai less than 4 GB; 0 when the computer is too small."""
        if self.memory_mb < MIN_HOST_MB + MIN_GUEST_MB:
            return 0
        return max(MIN_GUEST_MB, min(8192, self.memory_mb // 2, self.memory_mb - MIN_HOST_MB))


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def virtualization(root: Path = Path("/")) -> str | None:
    """"intel" (VT-x), "amd" (AMD-V) or None, from the CPU flags."""
    for line in _read(root / "proc/cpuinfo").splitlines():
        if line.startswith("flags"):
            flags = set(line.split(":", 1)[1].split())
            if "vmx" in flags:
                return "intel"
            if "svm" in flags:
                return "amd"
            return None
    return None


def memory_mb(root: Path = Path("/")) -> int:
    for line in _read(root / "proc/meminfo").splitlines():
        if line.startswith("MemTotal:"):
            try:
                return int(line.split()[1]) // 1024
            except (IndexError, ValueError):
                return 0
    return 0


def kvm_usable(root: Path = Path("/"), access=os.access) -> tuple[bool, bool]:
    """(the device exists, this user can open it)."""
    device = root / "dev/kvm"
    if not device.exists():
        return False, False
    return True, access(device, os.R_OK | os.W_OK)


def in_kvm_group(groups=None) -> bool:
    ids = set(os.getgroups() if groups is None else groups)
    try:
        return grp.getgrnam("kvm").gr_gid in ids
    except KeyError:
        return False


def firmware_present(root: Path = Path("/")) -> bool:
    """OVMF with Secure Boot keys, as Debian ships it (the exact file name is libvirt's business: it picks one
    from /usr/share/qemu/firmware; we only check that something with Secure Boot is there)."""
    ovmf = root / "usr/share/OVMF"
    if any(ovmf.glob("OVMF_CODE*.ms.fd")) or any(ovmf.glob("OVMF_CODE*secboot*.fd")):
        return True
    descriptors = root / "usr/share/qemu/firmware"
    for desc in descriptors.glob("*.json"):
        if "secure-boot" in _read(desc):
            return True
    return False


def missing_tools(which=shutil.which) -> list[str]:
    return [tool for tool in TOOLS if which(tool) is None]


def free_gb(path: Path) -> float:
    try:
        return shutil.disk_usage(path).free / 1024 ** 3
    except OSError:
        return 0.0


def check(lang: str, root: Path = Path("/"), home: Path | None = None, which=shutil.which, groups=None,
          access=os.access, disk_free=free_gb) -> Report:
    report = Report(memory_mb=memory_mb(root), virtualization=virtualization(root))
    home = home or Path.home()
    report.free_gb = disk_free(home if home.exists() else root)
    add = report.findings.append

    if report.virtualization is None:
        add(Finding("fail", "virt", say(lang, "This processor does not offer hardware virtualization (VT-x or AMD-V), "
                                             "or it is turned off in the BIOS. Without it Windows would run 10 to 50 "
                                             "times slower, so D.Ai VM does not start it.",
                                       "המעבד הזה לא מציע וירטואליזציה בחומרה (VT-x או AMD-V), או שהיא כבויה ב-BIOS. "
                                       "בלעדיה Windows היה רץ פי 10 עד 50 לאט יותר, ולכן D.Ai VM לא מפעיל אותו.")))
    exists, usable = kvm_usable(root, access)
    if report.virtualization is not None and not exists:
        add(Finding("fail", "kvm", say(lang, "/dev/kvm is missing: virtualization is off in the BIOS, or the kvm "
                                            "module did not load.",
                                      "‏/dev/kvm חסר: הווירטואליזציה כבויה ב-BIOS, או שמודול kvm לא נטען.")))
    elif exists and not usable:
        add(Finding("fail", "kvm-access", say(lang, "This user may not use KVM yet. Say \"allow virtual machines\" to "
                                                   "D.Ai Tune (it adds you to the kvm group; log out and in again).",
                                             "המשתמש הזה עדיין לא רשאי להשתמש ב-KVM. אמרו ל-D.Ai Tune \"אפשר מכונות "
                                             "וירטואליות\" (זה מוסיף אתכם לקבוצת kvm; צאו והיכנסו שוב).")))
    else:
        report.kvm = exists and usable
        if report.kvm:
            add(Finding("ok", "kvm", say(lang, "Hardware virtualization is on ({kind}) and usable.",
                                         "וירטואליזציה בחומרה פועלת ({kind}) וזמינה.",
                                         kind="VT-x" if report.virtualization == "intel" else "AMD-V")))

    recommended = report.recommended_memory_mb()
    if recommended == 0:
        add(Finding("fail", "memory", say(lang, "This computer has {mb} MB of memory. A Windows machine needs at least "
                                               "{need} MB and D.Ai keeps {host} MB for itself.",
                                         "למחשב הזה יש {mb} MB זיכרון. מכונת Windows צריכה לפחות {need} MB, ו-D.Ai "
                                         "שומר לעצמו {host} MB.", mb=report.memory_mb, need=MIN_GUEST_MB, host=MIN_HOST_MB)))
    elif recommended < 4096:
        add(Finding("warn", "memory", say(lang, "{mb} MB of memory: Windows will run, with {rec} MB, but it will be slow.",
                                         "{mb} MB זיכרון: Windows ירוץ, עם {rec} MB, אבל לאט.", mb=report.memory_mb,
                                         rec=recommended)))
    else:
        add(Finding("ok", "memory", say(lang, "{mb} MB of memory: {rec} MB for the machine is a good default.",
                                        "{mb} MB זיכרון: {rec} MB למכונה הם ברירת מחדל טובה.", mb=report.memory_mb,
                                        rec=recommended)))

    if report.free_gb < MIN_DISK_GB:
        add(Finding("fail", "disk", say(lang, "{free:.0f} GB free: a Windows machine needs at least {need} GB of space.",
                                       "{free:.0f} GB פנויים: מכונת Windows צריכה לפחות {need} GB מקום.",
                                       free=report.free_gb, need=MIN_DISK_GB)))
    elif report.free_gb < 2 * MIN_DISK_GB:
        add(Finding("warn", "disk", say(lang, "{free:.0f} GB free: enough to start; Windows updates will fill it.",
                                       "{free:.0f} GB פנויים: מספיק להתחלה; עדכוני Windows ימלאו אותו.", free=report.free_gb)))
    else:
        add(Finding("ok", "disk", say(lang, "{free:.0f} GB free.", "{free:.0f} GB פנויים.", free=report.free_gb)))

    missing = missing_tools(which)
    if missing:
        add(Finding("fail", "tools", say(lang, "Missing on this computer: {tools}.", "חסרים במחשב הזה: {tools}.",
                                        tools=", ".join(missing))))
    if not firmware_present(root):
        add(Finding("fail", "firmware", say(lang, "The UEFI firmware with Secure Boot keys (OVMF) is missing; Windows 11 "
                                                 "needs it.",
                                           "קושחת UEFI עם מפתחות Secure Boot ‏(OVMF) חסרה; Windows 11 צריך אותה.")))
    return report
