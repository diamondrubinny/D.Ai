# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from dai_doctor import cli
from dai_doctor.clean import clean_user
from dai_doctor.diagnose import diagnose, topic_for
from dai_doctor.facts import Battery, Facts, Proc, battery, collect, meminfo, processes

GB = 2**30
MB = 2**20


def quiet(argv):
    return subprocess.CompletedProcess(list(argv), 0, "", "")


class FakeSystem(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "root"
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        (self.root / "proc").mkdir(parents=True)
        (self.root / "proc/meminfo").write_text(
            "MemTotal:       8000000 kB\nMemAvailable:    400000 kB\nSwapTotal: 2000000 kB\nSwapFree: 500000 kB\n")
        (self.root / "proc/loadavg").write_text("6.50 3.00 1.00 2/300 1234\n")
        (self.root / "proc/uptime").write_text(f"{20 * 86400}.0 0.0\n")
        self.process(4242, "firefox-esr", rss_pages=400_000)
        self.process(1, "systemd", rss_pages=1000)

    def tearDown(self):
        self.tmp.cleanup()

    def process(self, pid, name, rss_pages):
        folder = self.root / "proc" / str(pid)
        folder.mkdir()
        (folder / "comm").write_text(name + "\n")
        (folder / "statm").write_text(f"999999 {rss_pages} 0 0 0 0 0\n")
        (folder / "stat").write_text(f"{pid} ({name}) S 1 1 1 0 -1 0 0 0 0 0 100 50 0 0 20 0 1 0 0 0\n")


class FactTests(FakeSystem):
    def test_proc_parsing(self):
        mem = meminfo(self.root)
        self.assertEqual((mem["MemTotal"], mem["MemAvailable"]), (8000000 * 1024, 400000 * 1024))
        procs = {p.name: p for p in processes(self.root, sample=0)}
        self.assertEqual(procs["firefox-esr"].rss, 400_000 * os.sysconf("SC_PAGE_SIZE"))
        facts = collect(self.root, self.home, runner=quiet, sample=0, topics=("slow",))
        self.assertEqual((facts.load1, round(facts.uptime_days)), (6.5, 20))

    def test_battery(self):
        bat = self.root / "sys/class/power_supply/BAT0"
        bat.mkdir(parents=True)
        for name, value in {"capacity": "25", "status": "Discharging", "energy_full": "30000000",
                            "energy_full_design": "50000000"}.items():
            (bat / name).write_text(value + "\n")
        self.assertEqual(battery(self.root), Battery(25, 60, "Discharging"))
        self.assertIsNone(battery(self.home))


class DiagnoseTests(FakeSystem):
    def facts(self, **overrides):
        base = dict(cores=4, load1=0.5, mem_total=8 * GB, mem_available=4 * GB, swap_total=0, swap_free=0,
                    uptime_days=1, processes=[], disks={"/": (100 * GB, 50 * GB)}, folders=[], caches={})
        base.update(overrides)
        return Facts(**base)

    def keys(self, findings, level=None):
        return [f.key for f in findings if level is None or f.level == level]

    def test_healthy_computer(self):
        findings = diagnose(self.facts(), ("slow", "disk", "battery"))
        self.assertEqual(self.keys(findings, "bad") + self.keys(findings, "warn"), [])

    def test_slow_reasons_are_explained(self):
        facts = self.facts(mem_available=int(0.5 * GB), swap_total=2 * GB, swap_free=int(0.5 * GB), load1=7,
                           uptime_days=20, failed_units=["cups.service"],
                           processes=[Proc(10, "firefox-esr", 180.0, 3 * GB), Proc(11, "labwc", 90.0, 1 * GB)])
        findings = diagnose(facts, ("slow",))
        self.assertEqual(findings[0].level, "bad")
        self.assertTrue({"memory", "cpu", "swap", "services", "uptime"} <= set(self.keys(findings)))
        memory = next(f for f in findings if f.key == "memory")
        self.assertIn("firefox-esr", memory.detail)
        cpu = next(f for f in findings if f.key == "cpu")
        self.assertNotIn("labwc", cpu.detail)  # the desktop itself is never blamed

    def test_windows_machine_reasons(self):
        """docs/VM.md §13: no KVM, too much memory given away, Windows busy, little room for the disk."""
        facts = self.facts(machines=[("office", 6144, 4)], kvm=False, machines_free=3 * GB, mem_available=int(0.8 * GB),
                           processes=[Proc(20, "qemu-system-x86", 80.0, 5 * GB)])
        findings = diagnose(facts, ("machine",))
        self.assertEqual(self.keys(findings), ["kvm", "machine-memory", "machine-busy", "machine-squeeze", "machine-disk"])
        self.assertEqual(findings[0].level, "bad")
        self.assertIn("BIOS/UEFI", findings[0].fixes[0].label)
        self.assertIn("6.0 GB of the computer's 8.0 GB", findings[1].detail)
        fine = diagnose(self.facts(machines=[("office", 4096, 2)], kvm=True, machines_free=50 * GB), ("machine",))
        self.assertEqual([(f.key, f.level) for f in fine], [("machine", "ok")])
        self.assertIn("office (4 GB, 2 CPU); hardware acceleration is on.", fine[0].detail)
        none = diagnose(self.facts(), ("machine",))
        self.assertEqual((none[0].level, "dai-vm create" in none[0].detail), ("ok", True))
        hebrew = diagnose(facts, ("machine",), "he")
        self.assertIn("האצת חומרה", hebrew[0].title)

    def test_why_windows_cannot_see_my_files(self):
        """docs/VM.md §14: nothing shared by design (warn, with the command), read-only (ok), writable (ok)."""
        machines = [("office", 4096, 2), ("lab", 2048, 1), ("open", 2048, 1)]
        sharing = {"office": {"shared_folder": "", "shared_readonly": True, "clipboard": False, "usb": 0},
                   "lab": {"shared_folder": "/home/dana/Shared", "shared_readonly": True, "clipboard": True, "usb": 2},
                   "open": {"shared_folder": "/home/dana/Shared", "shared_readonly": False, "clipboard": False, "usb": 0}}
        findings = diagnose(self.facts(machines=machines, sharing=sharing), ("sharing",))
        self.assertEqual([(f.key, f.level) for f in findings],
                         [("sharing-office", "warn"), ("sharing-lab", "ok"), ("sharing-open", "ok")])
        self.assertIn("dai-vm share office --folder", findings[0].fixes[0].label)
        self.assertIn("clipboard not shared.", findings[0].detail)
        self.assertIn("2 USB devices", findings[1].detail)
        self.assertIn("dai-vm share lab --writable", findings[1].fixes[0].label)
        self.assertIn("reads and writes /home/dana/Shared", findings[2].title)
        self.assertEqual(diagnose(self.facts(), ("sharing",))[0].level, "ok")
        for text, topic in (("why can't windows see my files", "sharing"), ("למה ווינדוס לא רואה את הקבצים שלי", "sharing"),
                            ("how do i share a folder with windows", "sharing"), ("why is windows slow", "machine"), ("my files are gone", None)):
            self.assertEqual(topic_for(text), topic, text)

    def test_machine_facts_come_from_dai_vm_files(self):
        folder = self.home / ".local/share/dai/vm/machines/office"
        folder.mkdir(parents=True)
        (folder / "machine.json").write_text('{"name": "office", "memory_mb": 4096, "cpus": 2, "disk_gb": 64}')
        (self.home / ".local/share/dai/vm/machines/broken").mkdir()
        (self.home / ".local/share/dai/vm/machines/broken/machine.json").write_text("{")
        facts = collect(self.root, self.home, runner=quiet, topics=("machine", "sharing"))
        self.assertEqual(facts.machines, [("office", 4096, 2)])
        self.assertEqual(facts.sharing, {"office": {"shared_folder": "", "shared_readonly": True, "clipboard": False, "usb": 0}})
        self.assertFalse(facts.kvm)  # no /dev/kvm in the fake root
        self.assertGreater(facts.machines_free, 0)
        self.assertTrue(any(p.name == "firefox-esr" for p in facts.processes))

    def test_disk_findings_and_fixes(self):
        facts = self.facts(disks={"/": (100 * GB, int(1.5 * GB))},
                           caches={"apt": 600 * MB, "journal": 900 * MB, "trash": 300 * MB, "thumbnails": 20 * MB},
                           folders=[("Videos", 40 * GB), ("Downloads", 9 * GB)])
        findings = diagnose(facts, ("disk",))
        self.assertEqual(findings[0].level, "bad")
        fixes = {fix.kind: fix.payload for f in findings for fix in f.fixes}
        self.assertEqual(fixes, {"tune": "free up disk space", "clean": "user"})
        self.assertIn("Videos", next(f for f in findings if f.key == "folders").detail)
        # A large disk with 11% free is fine.
        self.assertEqual(diagnose(self.facts(disks={"/": (252 * GB, 29 * GB)}), ("disk",))[0].level, "ok")

    def test_tune_sentences_are_understood_by_tune(self):
        try:
            from dai_tune.parser import parse
        except ImportError:
            self.skipTest("dai_tune not on the path")
        for sentence in ("free up disk space", "battery saver mode"):
            result = parse(sentence)
            self.assertTrue(result.requests and not result.unknown, sentence)

    def test_battery_advice(self):
        facts = self.facts(battery=Battery(20, 55, "Discharging"), power_profile="balanced")
        findings = diagnose(facts, ("battery",), "he")
        self.assertEqual(self.keys(findings), ["battery-health", "battery-low"])
        self.assertIn("שחוקה", findings[0].title)
        self.assertEqual(findings[1].fixes[0].payload, "battery saver mode")
        self.assertEqual(diagnose(self.facts(battery=None), ("battery",)), [])

    def test_questions(self):
        for text, topic in [("why is my computer slow", "slow"), ("למה המחשב איטי?", "slow"),
                            ("מה תופס את הדיסק", "disk"), ("what's taking my disk space", "disk"),
                            ("כמה סוללה נשארה?", "battery"), ("slow motion.mp4", None), ("firefox", None),
                            ("why is windows so slow?", "machine"), ("למה ווינדוס איטי?", "machine"),
                            ("why is my computer slow", "slow")]:
            self.assertEqual(topic_for(text), topic, text)


class UpdateTests(FakeSystem):
    """"It broke after the update" (docs/SNAPSHOTS.md)."""

    HISTORY = ("Start-Date: 2026-10-01  10:00:00\nCommandline: apt upgrade\nUpgrade: a:amd64 (1, 2)\nEnd-Date: x\n\n"
               "Start-Date: 2026-10-16  09:12:44\nCommandline: apt full-upgrade\n"
               "Upgrade: libfoo:amd64 (1.0, 1.1), bar:amd64 (2, 3)\nInstall: linux-image-6.12:amd64 (6.12, automatic)\n"
               "End-Date: 2026-10-16  09:14:02\n")

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def test_facts(self):
        self.write("proc/mounts", "sysfs /sys sysfs rw 0 0\n/dev/mapper/luks-1 / btrfs rw,subvol=/@ 0 0\n")
        self.write("var/log/apt/history.log", self.HISTORY)
        facts = collect(self.root, self.home, runner=quiet, topics=("update",))
        self.assertEqual((facts.root_fs, facts.snapshots), ("btrfs", False))
        self.assertEqual(facts.last_update, ("2026-10-16  09:12:44", 3))
        self.write("etc/snapper/configs/root", "")
        self.assertTrue(collect(self.root, self.home, runner=quiet, topics=("update",)).snapshots)

    def test_answers(self):
        undo = diagnose(Facts(root_fs="btrfs", snapshots=True, last_update=("2026-10-16", 3)), ("update",), "he")[0]
        self.assertEqual(undo.fixes[0].payload, "undo the last update")
        self.assertIn("3 חבילות", undo.detail)
        off = diagnose(Facts(root_fs="btrfs"), ("update",))[0]
        self.assertEqual(off.fixes[0].payload, "snapshots before updates")
        ext4 = diagnose(Facts(root_fs="ext4"), ("update",))[0]
        self.assertEqual([f.kind for f in ext4.fixes], ["advice"])
        self.assertIn("ext4", ext4.detail)

    def test_questions(self):
        for text in ("המדפסת לא עובדת מאז העדכון", "my wifi stopped working after the update", "העדכון שבר לי את המחשב"):
            self.assertEqual(topic_for(text), "update", text)
        self.assertEqual(topic_for("will my printer work?"), "hardware")


class HardwareTests(FakeSystem):
    def pci(self, slot, cls, driver=None):
        dev = self.root / "sys/bus/pci/devices" / slot
        dev.mkdir(parents=True)
        (dev / "class").write_text(cls + "\n")
        (dev / "vendor").write_text("0x8086\n")
        (dev / "device").write_text("0x2723\n")
        if driver:
            target = self.root / "sys/bus/pci/drivers" / driver
            target.mkdir(parents=True, exist_ok=True)
            (dev / "driver").symlink_to(target)

    def test_scan_and_findings(self):
        from dai_doctor import hardware
        self.pci("0000:00:14.3", "0x028000", "iwlwifi")
        self.pci("0000:01:00.0", "0x030000")              # graphics without a driver
        self.pci("0000:00:1f.3", "0x040300", "snd_hda_intel")
        self.pci("0000:00:00.0", "0x060000", "skl_uncore")  # host bridge: not listed
        kill = self.root / "sys/class/rfkill/rfkill0"
        kill.mkdir(parents=True)
        (kill / "type").write_text("wlan\n")
        (kill / "soft").write_text("1\n")
        (kill / "hard").write_text("0\n")
        usb = self.root / "sys/bus/usb/devices"
        (usb / "1-2").mkdir(parents=True)
        (usb / "1-2" / "manufacturer").write_text("HP\n")
        (usb / "1-2" / "product").write_text("LaserJet 1020\n")
        (usb / "1-2:1.0").mkdir()
        (usb / "1-2:1.0" / "bInterfaceClass").write_text("07\n")
        devices = hardware.scan(self.root)
        self.assertEqual([(d.kind, d.driver) for d in devices],
                         [("wifi", "iwlwifi"), ("audio", "snd_hda_intel"), ("graphics", None), ("printer", None)])
        facts = collect(self.root, self.home, runner=quiet, topics=("hardware",))
        findings = {f.key: f for f in diagnose(facts, ("hardware",), "he")}
        self.assertEqual(findings["hw:graphics"].level, "bad")
        self.assertEqual(findings["hw:wifi"].title, "Wi-Fi: במצב תקין")
        self.assertEqual(findings["hw:wifi-off"].level, "warn")
        self.assertEqual(findings["hw:printer"].fixes[0].kind, "forge")
        self.assertEqual(findings["hw:printer"].fixes[0].payload, "install printer")
        self.assertIn("HP LaserJet 1020", findings["hw:printer"].title)

    def test_lspci_names(self):
        from dai_doctor.hardware import parse_lspci_mm
        vm = '00:02.0 "VGA compatible controller" "Vendor 1234" "Device 1111" -r02 -p00 "Red Hat, Inc." "Device 1100"'
        self.assertEqual(parse_lspci_mm(vm), "Vendor 1234 Device 1111")
        intel = '00:14.3 "Network controller" "Intel Corporation" "Wi-Fi 6 AX201" -r30 "Intel Corporation" "Wi-Fi 6 AX201"\n'
        self.assertEqual(parse_lspci_mm(intel), "Intel Corporation Wi-Fi 6 AX201")
        self.assertEqual(parse_lspci_mm(""), "")
        self.assertEqual(parse_lspci_mm('broken "quote'), "")

    def test_hardware_questions(self):
        for text in ("will my wifi work?", "המדפסת שלי לא עובדת", "האם המצלמה תעבוד במחשב הזה?", "my sound is not working"):
            self.assertEqual(topic_for(text), "hardware", text)


class CleanTests(FakeSystem):
    def test_only_trash_and_previews_and_no_symlink_following(self):
        trash = self.home / ".local/share/Trash/files"
        trash.mkdir(parents=True)
        (trash / "old.iso").write_bytes(b"x" * 100_000)
        (trash / "folder").mkdir()
        (trash / "folder" / "a.txt").write_text("a")
        precious = self.home / "Documents"
        precious.mkdir()
        (precious / "thesis.odt").write_text("keep me")
        (trash / "link-to-documents").symlink_to(precious)
        thumbs = self.home / ".cache/thumbnails/large"
        thumbs.mkdir(parents=True)
        (thumbs / "t.png").write_bytes(b"x" * 5000)
        freed = clean_user(self.home)
        self.assertGreater(freed, 100_000)
        self.assertEqual(list(trash.iterdir()), [])
        self.assertEqual(list((self.home / ".cache/thumbnails").iterdir()), [])
        self.assertEqual((precious / "thesis.odt").read_text(), "keep me")

    def test_symlinked_trash_folder_is_left_alone(self):
        elsewhere = self.home / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "keep.txt").write_text("x")
        (self.home / ".local/share/Trash").mkdir(parents=True)
        (self.home / ".local/share/Trash/files").symlink_to(elsewhere)
        clean_user(self.home)
        self.assertTrue((elsewhere / "keep.txt").exists())


class CliTests(FakeSystem):
    def test_json_and_text(self):
        fake = Facts(cores=2, load1=0.1, mem_total=8 * GB, mem_available=6 * GB, disks={"/": (100 * GB, 60 * GB)})
        with mock.patch.object(cli, "collect", return_value=fake), mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8"}):
            out = io.StringIO()
            with redirect_stdout(out), mock.patch("sys.stderr", io.StringIO()):
                self.assertEqual(cli.main(["dai-doctor", "--json", "slow"]), 0)
            self.assertEqual({f["key"] for f in json.loads(out.getvalue())}, {"memory", "cpu"})
            out = io.StringIO()
            with redirect_stdout(out), mock.patch("sys.stderr", io.StringIO()):
                cli.main(["dai-doctor"])
            self.assertIn("Everything looks fine", out.getvalue())


class CommandTests(unittest.TestCase):
    def test_command_bar_rows(self):
        try:
            from dai_command import core
        except ImportError:
            self.skipTest("dai_command not on the path")
        facts = Facts(cores=2, load1=5, mem_total=8 * GB, mem_available=int(0.3 * GB),
                      processes=[Proc(5, "chromium", 150.0, 4 * GB)], disks={"/": (100 * GB, 60 * GB)})
        core._DOCTOR_CACHE.clear()
        with mock.patch("dai_doctor.facts.collect", return_value=facts) as collect_mock, \
                mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8"}):
            rows = core.doctor_actions("why is my computer so slow")
            self.assertEqual(rows[0].kind, "doctor")
            self.assertEqual(rows[0].payload, "slow")
            self.assertIn("Memory is almost full", [r.title for r in rows])
            core.doctor_actions("why is my computer so slow?")  # cached while typing
            self.assertEqual(collect_mock.call_count, 1)
            self.assertIsNone(core.doctor_actions("slow motion.mp4"))
        core._DOCTOR_CACHE.clear()


class LanguageTests(unittest.TestCase):
    """D.Ai Doctor in the six other languages (docs/I18N.md §10)."""

    def test_questions(self):
        from dai_doctor.diagnose import topic_for

        for text, topic in (("почему компьютер тормозит?", "slow"), ("что занимает место на диске?", "disk"),
                            ("por qué mi ordenador está lento", "slow"), ("pourquoi mon ordinateur rame", "slow"),
                            ("mon imprimante ne marche pas depuis la mise à jour", "update"),
                            ("was belegt meinen Speicherplatz", "disk"), ("por que meu computador está lento", "slow"),
                            ("لماذا حاسوبي بطيء", "slow"), ("batería de mi portátil", "battery"),
                            ("installiere vlc", None), ("why is my computer slow", "slow"),
                            ("почему виндовс тормозит?", "machine"), ("warum ist die virtuelle maschine langsam", "machine")):
            with self.subTest(text):
                self.assertEqual(topic_for(text), topic)

if __name__ == "__main__":
    unittest.main()
