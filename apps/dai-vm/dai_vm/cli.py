# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-vm: D.Ai VM, Windows (and other systems) in a window on D.Ai, with your own media and key (docs/VM.md).

  dai-vm                              the window
  dai-vm check                        can this computer run a machine? (exit 0 yes, 1 no)
  dai-vm list                         the machines and their state
  dai-vm create NAME --iso FILE [--windows 11|10|other] [--memory MB] [--cpus N] [--disk GB] [--no-drivers]
  dai-vm start|stop|poweroff|pause|resume|show|delete NAME     (delete asks; --yes skips the question)
  dai-vm drivers [--download]         the VirtIO drivers for Windows: present or not; --download fetches them
  dai-vm iso FILE                     what the media says about itself, and its SHA-256
  dai-vm --version | --help

D.Ai never downloads Windows: you bring the ISO from Microsoft and type your key into Windows setup. Machines run
as you (qemu:///session), in your home folder, with no shared folder and no clipboard until you turn them on.
"""
from __future__ import annotations

import datetime
import shutil
import subprocess
import sys
from pathlib import Path

from dai_i18n import pick, ui_lang

from . import control, drivers, hardware, iso, machine


def say(lang: str, en: str, he: str, **kwargs: object) -> str:
    return pick(lang, en, he).format(**kwargs)


def _option(args: list[str], name: str) -> str | None:
    if name in args and args.index(name) + 1 < len(args):
        return args[args.index(name) + 1]
    return None


def _positional(args: list[str], skip: set[str]) -> list[str]:
    out, hold = [], False
    for arg in args:
        if hold:
            hold = False
        elif arg in skip:
            hold = True
        elif not arg.startswith("--"):
            out.append(arg)
    return out


def cmd_check(lang: str, home: Path | None) -> int:
    report = hardware.check(lang, home=home)
    marks = {"ok": "✓", "warn": "!", "fail": "✗"}
    for finding in report.findings:
        print(f"{marks[finding.level]} {finding.text}")
    print(say(lang, "A machine can run here.", "מכונה יכולה לרוץ כאן.") if report.can_run else
          say(lang, "A machine cannot run here yet.", "מכונה עדיין לא יכולה לרוץ כאן."))
    return 0 if report.can_run else 1


def cmd_list(lang: str, home: Path | None, virsh: control.Virsh) -> int:
    machines = machine.list_machines(home)
    if not machines:
        print(say(lang, "No machines yet. dai-vm create NAME --iso FILE", "אין עדיין מכונות. dai-vm create NAME --iso FILE"))
        return 0
    for m in machines:
        state = virsh.state(m.name) if virsh.available() else "?"
        print(f"{m.name}\t{state}\t{m.memory_mb} MB · {m.cpus} CPU · {m.disk_gb} GB · Windows {m.windows}")
    return 0


def cmd_create(args: list[str], lang: str, home: Path | None, virsh: control.Virsh, run) -> int:
    names = _positional(args[1:], {"--iso", "--windows", "--memory", "--cpus", "--disk"})
    if not names:
        print(say(lang, "Which name? dai-vm create NAME --iso FILE", "איזה שם? dai-vm create NAME --iso FILE"), file=sys.stderr)
        return 2
    report = hardware.check(lang, home=home)
    if not report.can_run:
        for finding in report.findings:
            if finding.level == "fail":
                print("✗ " + finding.text, file=sys.stderr)
        return 1
    media = _option(args, "--iso")
    if media:
        try:
            info = iso.inspect(media)
        except iso.IsoError as exc:
            print(say(lang, "The media could not be used: {why}", "לא ניתן להשתמש במדיה: {why}", why=exc), file=sys.stderr)
            return 2
        if not info.windows_hint and (_option(args, "--windows") or "11") != "other":
            print(say(lang, "Note: {name} does not look like Windows media (label: {label}).",
                      "שימו לב: {name} לא נראה כמו מדיה של Windows (תווית: {label}).", name=info.name, label=info.label))
    drivers_iso = None
    if "--no-drivers" not in args:
        entry = drivers.catalog().get("virtio-win")
        if entry and drivers.present(entry, home):
            drivers_iso = str(drivers.iso_path(entry, home))
        else:
            print(say(lang, "The VirtIO drivers are not downloaded yet (dai-vm drivers --download); Windows setup will "
                            "not see the disk until they are attached.",
                      "דרייברי VirtIO עדיין לא הורדו (dai-vm drivers --download); התקנת Windows לא תראה את הדיסק עד "
                      "שיצורפו."), file=sys.stderr)
    try:
        m = machine.Machine(
            name=names[0],
            memory_mb=int(_option(args, "--memory") or report.recommended_memory_mb()),
            cpus=int(_option(args, "--cpus") or max(1, min(4, (hardware.os.cpu_count() or 2) // 2))),
            disk_gb=int(_option(args, "--disk") or 64),
            iso=media, drivers_iso=drivers_iso, windows=_option(args, "--windows") or "11",
            created=datetime.datetime.now().isoformat(timespec="seconds"),
        )
        definition = machine.create(m, home, run)
        virsh.define(definition)
    except (machine.MachineError, control.VmError, ValueError) as exc:
        print(say(lang, "Not created: {why}", "לא נוצר: {why}", why=exc), file=sys.stderr)
        return 1
    print(say(lang, "{name} is ready: {mb} MB, {cpus} CPUs, a {gb} GB disk. Start it with: dai-vm start {name}",
              "{name} מוכן: {mb} MB, {cpus} מעבדים, דיסק של {gb} GB. הפעלה: dai-vm start {name}",
              name=m.name, mb=m.memory_mb, cpus=m.cpus, gb=m.disk_gb))
    return 0


def cmd_machine(args: list[str], lang: str, home: Path | None, virsh: control.Virsh, spawn) -> int:
    verb = args[0]
    names = _positional(args[1:], set())
    if not names:
        print(say(lang, "Which machine? dai-vm {verb} NAME", "איזו מכונה? dai-vm {verb} NAME", verb=verb), file=sys.stderr)
        return 2
    name = names[0]
    try:
        m = machine.load(name, home)
    except machine.MachineError:
        print(say(lang, "No machine called {name}.", "אין מכונה בשם {name}.", name=name), file=sys.stderr)
        return 2
    try:
        if verb == "start":
            if virsh.state(name) == "missing":
                virsh.define(machine.machine_dir(name, home) / "domain.xml")
            virsh.start(name)
            print(say(lang, "{name} is starting.", "{name} מופעל.", name=name))
        elif verb == "stop":
            virsh.shutdown(name)
            print(say(lang, "{name} was asked to shut down.", "{name} התבקש להיכבות.", name=name))
        elif verb == "poweroff":
            virsh.poweroff(name)
            print(say(lang, "{name} was switched off.", "{name} כובה.", name=name))
        elif verb == "pause":
            virsh.pause(name)
            print(say(lang, "{name} is paused.", "{name} מושהה.", name=name))
        elif verb == "resume":
            virsh.resume(name)
            print(say(lang, "{name} goes on.", "{name} ממשיך.", name=name))
        elif verb == "show":
            spawn(control.viewer_argv(f"{m.name} · D.Ai VM", virsh.display(name)))
            print(say(lang, "The screen of {name} opens in its own window.", "המסך של {name} נפתח בחלון משלו.", name=name))
        elif verb == "delete":
            if "--yes" not in args:
                print(say(lang, "This deletes {name} and its disk for good. Add --yes to confirm.",
                          "זה מוחק את {name} ואת הדיסק שלו לתמיד. הוסיפו --yes לאישור.", name=name), file=sys.stderr)
                return 1
            if virsh.state(name) == "running":
                virsh.poweroff(name)
            virsh.undefine(name)
            shutil.rmtree(machine.machine_dir(name, home), ignore_errors=True)
            print(say(lang, "{name} was deleted.", "{name} נמחק.", name=name))
    except control.VmError as exc:
        print(say(lang, "That did not work: {why}", "זה לא הצליח: {why}", why=exc), file=sys.stderr)
        return 1
    return 0


def cmd_drivers(args: list[str], lang: str, home: Path | None) -> int:
    entry = drivers.catalog().get("virtio-win")
    if entry is None:
        print(say(lang, "No drivers in the catalog.", "אין דרייברים בקטלוג."), file=sys.stderr)
        return 1
    if drivers.present(entry, home):
        print(say(lang, "VirtIO drivers {version} are present: {path}", "דרייברי VirtIO ‏{version} קיימים: {path}",
                  version=entry.version, path=drivers.iso_path(entry, home)))
        return 0
    if "--download" not in args:
        print(say(lang, "VirtIO drivers {version} are not downloaded ({mb} MB from {host}). dai-vm drivers --download",
                  "דרייברי VirtIO ‏{version} לא הורדו ({mb} MB מ-{host}). dai-vm drivers --download",
                  version=entry.version, mb=entry.size // (1024 * 1024), host=entry.url.split("/")[2]))
        return 1
    if not entry.pinned:
        print(say(lang, "The catalog has no SHA-256 for these drivers, so they are not downloaded.",
                  "בקטלוג אין SHA-256 לדרייברים האלה, ולכן הם לא מורדים."), file=sys.stderr)
        return 1
    last = [-1]

    def progress(done: int, total: int) -> None:
        pct = done * 100 // max(1, total)
        if pct // 5 != last[0]:
            last[0] = pct // 5
            print(f"\r{pct}%", end="", flush=True)

    try:
        path = drivers.download(entry, home, progress=progress)
    except (drivers.DriverError, OSError) as exc:
        print()
        print(say(lang, "The download failed: {why}", "ההורדה נכשלה: {why}", why=exc), file=sys.stderr)
        return 1
    print()
    print(say(lang, "Downloaded and verified: {path}", "הורד ואומת: {path}", path=path))
    return 0


def cmd_iso(args: list[str], lang: str) -> int:
    names = _positional(args[1:], set())
    if not names:
        print(say(lang, "Which file? dai-vm iso FILE", "איזה קובץ? dai-vm iso FILE"), file=sys.stderr)
        return 2
    try:
        info = iso.inspect(names[0])
    except iso.IsoError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(say(lang, "Label: {label}", "תווית: {label}", label=info.label))
    print(say(lang, "Size: {gb:.2f} GB", "גודל: {gb:.2f} GB", gb=info.size / 1024 ** 3))
    print(say(lang, "Looks like Windows media: {yes}", "נראה כמו מדיה של Windows: {yes}",
              yes=say(lang, "yes", "כן") if info.windows_hint else say(lang, "no", "לא")))
    print("SHA-256: " + iso.sha256(info.path))
    print(say(lang, "Compare it with the checksum on the page you downloaded from.", "השוו אותו לסכום הבדיקה בעמוד שממנו הורדתם."))
    return 0


def main(argv: list[str] | None = None, home: Path | None = None, virsh: control.Virsh | None = None,
         run=subprocess.run, spawn=None) -> int:
    args = list(sys.argv if argv is None else argv)[1:]
    lang = ui_lang()
    virsh = virsh or control.Virsh(run)
    spawn = spawn or (lambda argv: subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    if "--help" in args or "-h" in args:
        print(__doc__.strip())
        return 0
    if "--version" in args:
        from . import __author__, __version__
        print(f"dai-vm {__version__} — {__author__}")
        return 0
    if not args:
        from .gui import main as window
        return window(["dai-vm"])
    verb = args[0]
    if verb == "check":
        return cmd_check(lang, home)
    if verb == "list":
        return cmd_list(lang, home, virsh)
    if verb == "create":
        return cmd_create(args, lang, home, virsh, run)
    if verb in ("start", "stop", "poweroff", "pause", "resume", "show", "delete"):
        return cmd_machine(args, lang, home, virsh, spawn)
    if verb == "drivers":
        return cmd_drivers(args, lang, home)
    if verb == "iso":
        return cmd_iso(args, lang)
    print(say(lang, "Unknown command: {verb}. dai-vm --help", "פקודה לא מוכרת: {verb}. dai-vm --help", verb=verb), file=sys.stderr)
    return 2
