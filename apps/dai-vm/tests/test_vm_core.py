# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai VM without a window: the hardware check, the ISO reader, the drivers catalog and download, the machine
definition, and virsh."""
import hashlib
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from dai_vm import control, drivers, hardware, iso, machine

from . import fakes


class HardwareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def check(self, **kwargs):
        root = fakes.fake_root(self.root, **{k: v for k, v in kwargs.items() if k in ("flags", "mem_kb", "kvm", "firmware")})
        extra = {k: v for k, v in kwargs.items() if k in ("which", "access", "disk_free")}
        return fakes.check("en", root=root, home=root, **extra)

    def test_a_good_computer(self):
        report = self.check()
        self.assertTrue(report.can_run)
        self.assertEqual(report.virtualization, "intel")
        self.assertTrue(report.kvm)
        self.assertEqual(report.memory_mb, 15625)
        self.assertEqual(report.recommended_memory_mb(), 7812)
        self.assertEqual({f.key for f in report.findings if f.level == "ok"}, {"kvm", "memory", "disk"})

    def test_no_virtualization_is_a_fail_with_the_reason(self):
        report = self.check(flags="fpu sse2")
        self.assertFalse(report.can_run)
        self.assertIn("VT-x or AMD-V", [f for f in report.findings if f.key == "virt"][0].text)
        amd = self.check(flags="fpu svm")
        self.assertEqual(amd.virtualization, "amd")

    def test_kvm_access_points_to_tune(self):
        report = self.check(access=lambda p, m: False)
        texts = [f.text for f in report.findings if f.level == "fail"]
        self.assertTrue(any("allow virtual machines" in t for t in texts))
        missing = self.check(kvm=False)
        self.assertTrue(any(f.key == "kvm" and f.level == "fail" for f in missing.findings))

    def test_memory_limits(self):
        small = self.check(mem_kb=4_000_000)
        self.assertEqual(small.recommended_memory_mb(), 0)
        self.assertTrue(any(f.key == "memory" and f.level == "fail" for f in small.findings))
        eight = self.check(mem_kb=8_000_000)
        self.assertEqual(eight.recommended_memory_mb(), 3716)  # what is left after D.Ai's 4 GB (less than half)
        self.assertTrue(any(f.key == "memory" and f.level == "warn" for f in eight.findings))

    def test_missing_tools_firmware_and_disk(self):
        report = self.check(which=lambda name: None if name in ("swtpm", "passt") else f"/usr/bin/{name}")
        self.assertIn("swtpm, passt", [f.text for f in report.findings if f.key == "tools"][0])
        report = self.check(firmware=False)
        self.assertTrue(any(f.key == "firmware" for f in report.findings))
        full = self.check(disk_free=lambda p: 12.0)
        self.assertTrue(any(f.key == "disk" and f.level == "fail" for f in full.findings))
        tight = self.check(disk_free=lambda p: 60.0)
        self.assertTrue(any(f.key == "disk" and f.level == "warn" for f in tight.findings))

    def test_firmware_descriptor_counts_too(self):
        root = fakes.fake_root(self.root, firmware=False)
        (root / "usr/share/qemu/firmware").mkdir(parents=True)
        (root / "usr/share/qemu/firmware/40-edk2-x86_64-secure-enrolled.json").write_text('{"features": ["secure-boot"]}')
        self.assertTrue(hardware.firmware_present(root))


class IsoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_label_and_windows_hint(self):
        info = iso.inspect(fakes.fake_iso(self.dir / "win.iso"))
        self.assertEqual((info.label, info.windows_hint, info.size), ("CCCOMA_X64FRE_EN-US_DV9", True, 60 * 1024 * 1024))
        other = iso.inspect(fakes.fake_iso(self.dir / "d.iso", label="Debian 13.1.0 amd64 n"))
        self.assertFalse(other.windows_hint)

    def test_errors(self):
        with self.assertRaises(iso.IsoError):
            iso.inspect(self.dir / "none.iso")
        small = self.dir / "small.iso"
        small.write_bytes(b"x" * 1000)
        with self.assertRaises(iso.IsoError):
            iso.inspect(small)
        bad = self.dir / "bad.iso"
        bad.write_bytes(b"x" * (60 * 1024 * 1024))
        with self.assertRaises(iso.IsoError):
            iso.inspect(bad)

    def test_sha256_with_progress(self):
        path = fakes.fake_iso(self.dir / "win.iso")
        seen = []
        digest = iso.sha256(path, progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(seen[-1], (path.stat().st_size, path.stat().st_size))


class DriversTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.data = b"ISO" * 1000
        self.entry = drivers.Driver("virtio-win", "0.1.302-1", "https://example.org/virtio-win.iso", "virtio-win.iso",
                                    hashlib.sha256(self.data).hexdigest(), len(self.data), "Apache-2.0")

    def test_the_catalog_is_pinned(self):
        entry = drivers.catalog()["virtio-win"]
        self.assertTrue(entry.pinned)
        self.assertTrue(entry.url.startswith("https://fedorapeople.org/"))
        self.assertEqual(entry.size, 877373440)

    def test_download_verifies_and_marks(self):
        fetch = fakes.FakeFetch(self.data)
        seen = []
        path = drivers.download(self.entry, self.home, fetch=fetch, progress=lambda d, t: seen.append(d))
        self.assertEqual(path, self.home / ".local/share/dai/vm/drivers/virtio-win.iso")
        self.assertEqual(path.read_bytes(), self.data)
        self.assertTrue(drivers.present(self.entry, self.home))
        self.assertEqual(fetch.urls, [self.entry.url])
        self.assertEqual(seen[-1], len(self.data))

    def test_a_wrong_file_is_not_kept(self):
        with self.assertRaises(drivers.DriverError):
            drivers.download(self.entry, self.home, fetch=fakes.FakeFetch(b"ISO" * 999 + b"XXX"))
        self.assertFalse(drivers.present(self.entry, self.home))
        self.assertEqual(list(drivers.drivers_dir(self.home).glob("*")), [])
        with self.assertRaises(drivers.DriverError):
            drivers.download(self.entry, self.home, fetch=fakes.FakeFetch(self.data + b"more"))

    def test_unpinned_and_http_are_refused(self):
        unpinned = drivers.Driver("x", "1", "https://example.org/x.iso", "x.iso", "", 3, "")
        with self.assertRaises(drivers.DriverError):
            drivers.download(unpinned, self.home, fetch=fakes.FakeFetch(b"abc"))
        plain = drivers.Driver("x", "1", "http://example.org/x.iso", "x.iso", hashlib.sha256(b"abc").hexdigest(), 3, "")
        with self.assertRaises(drivers.DriverError):
            drivers.download(plain, self.home)

    def test_present_needs_the_marker(self):
        path = drivers.iso_path(self.entry, self.home)
        path.parent.mkdir(parents=True)
        path.write_bytes(self.data)
        self.assertFalse(drivers.present(self.entry, self.home))  # never verified
        path.with_suffix(".iso.sha256").write_text(self.entry.sha256 + "\n")
        self.assertTrue(drivers.present(self.entry, self.home))


class MachineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.iso = fakes.fake_iso(self.home / "win.iso")
        self.drivers = fakes.fake_iso(self.home / "virtio.iso", label="virtio-win-0.1.302")

    def machine(self, **kwargs):
        base = dict(name="win11", memory_mb=4096, cpus=2, disk_gb=64, iso=str(self.iso), drivers_iso=str(self.drivers))
        return machine.Machine(**{**base, **kwargs})

    def test_validation(self):
        self.machine().validate()
        for bad in (dict(name="bad name"), dict(name="../x"), dict(memory_mb=512), dict(memory_mb=99999), dict(cpus=0),
                    dict(disk_gb=5), dict(windows="95"), dict(iso=str(self.home / "none.iso"))):
            with self.assertRaises(machine.MachineError, msg=bad):
                self.machine(**bad).validate()

    def test_the_definition_for_windows_11(self):
        xml = machine.domain_xml(self.machine(), self.home)
        root = ET.fromstring(xml)
        self.assertEqual(root.find("name").text, "dai-win11")
        self.assertEqual(root.find("os").get("firmware"), "efi")
        self.assertEqual(root.find("os/loader").get("secure"), "yes")
        self.assertEqual(root.find("os/type").get("machine"), "q35")
        self.assertEqual(root.find("memory").text, "4096")
        self.assertEqual(root.find("features/smm").get("state"), "on")
        self.assertIsNotNone(root.find("features/hyperv/relaxed"))
        self.assertEqual(root.find("cpu").get("mode"), "host-passthrough")
        self.assertEqual(root.find("clock").get("offset"), "localtime")
        tpm = root.find("devices/tpm")
        self.assertEqual((tpm.get("model"), tpm.find("backend").get("type"), tpm.find("backend").get("version")),
                         ("tpm-crb", "emulator", "2.0"))
        disks = root.findall("devices/disk")
        self.assertEqual([d.get("device") for d in disks], ["disk", "cdrom", "cdrom"])
        self.assertEqual(disks[0].find("target").get("bus"), "virtio")
        self.assertEqual(disks[0].find("source").get("file"), str(self.home / ".local/share/dai/vm/machines/win11/disk.qcow2"))
        self.assertEqual(disks[1].find("source").get("file"), str(self.iso))
        self.assertEqual(disks[2].find("source").get("file"), str(self.drivers))
        net = root.find("devices/interface")
        self.assertEqual((net.get("type"), net.find("backend").get("type"), net.find("model").get("type")),
                         ("user", "passt", "virtio"))
        self.assertEqual(root.find("devices/graphics/listen").get("type"), "socket")
        self.assertEqual(root.find("devices/video/model").get("type"), "qxl")
        self.assertIsNone(root.find("devices/channel"))      # no clipboard agent channel unless asked
        self.assertIsNone(root.find("devices/filesystem"))   # no shared folder unless asked
        self.assertIsNotNone(root.find("devices/rng"))
        self.assertIsNotNone(root.find("devices/memballoon"))

    def test_clipboard_and_folder_only_when_asked(self):
        m = self.machine(clipboard=True, shared_folder=str(self.home))
        root = ET.fromstring(machine.domain_xml(m, self.home))
        self.assertEqual(root.find("devices/channel/target").get("name"), "com.redhat.spice.0")
        self.assertEqual(root.find("devices/filesystem/source").get("dir"), str(self.home))
        other = self.machine(windows="other", drivers_iso=None)
        root = ET.fromstring(machine.domain_xml(other, self.home))
        self.assertIsNone(root.find("features/hyperv"))
        self.assertEqual(root.find("clock").get("offset"), "utc")
        self.assertEqual(len(root.findall("devices/disk")), 2)

    def test_create_save_load_list(self):
        run = fakes.FakeRun()
        definition = machine.create(self.machine(), self.home, run)
        self.assertEqual(definition, self.home / ".local/share/dai/vm/machines/win11/domain.xml")
        self.assertEqual(run.calls[0][:4], ["qemu-img", "create", "-f", "qcow2"])
        self.assertEqual(run.calls[0][5], "64G")
        self.assertTrue((definition.parent / "disk.qcow2").exists())
        loaded = machine.load("win11", self.home)
        self.assertEqual(loaded, self.machine())
        self.assertEqual([m.name for m in machine.list_machines(self.home)], ["win11"])
        with self.assertRaises(machine.MachineError):
            machine.create(self.machine(), self.home, run)  # exists already
        with self.assertRaises(machine.MachineError):
            machine.load("nope", self.home)


class VirshTests(unittest.TestCase):
    def test_the_lifecycle_through_fixed_argv(self):
        run = fakes.FakeRun()
        v = control.Virsh(run)
        self.assertEqual(v.state("win11"), "missing")
        v.define(Path("/x/machines/win11/domain.xml"))
        self.assertEqual(run.calls[-1][:3], ["virsh", "-c", "qemu:///session"])
        self.assertEqual(v.state("win11"), "shut off")
        v.start("win11")
        self.assertEqual(v.state("win11"), "running")
        self.assertTrue(v.display("win11").startswith("spice+unix://"))
        v.pause("win11")
        self.assertEqual(v.state("win11"), "paused")
        v.resume("win11")
        v.shutdown("win11")
        self.assertEqual(v.state("win11"), "shut off")
        self.assertEqual(v.defined(), ["dai-win11"])
        v.undefine("win11")
        self.assertEqual(v.state("win11"), "missing")
        run.fail.add("start")
        with self.assertRaises(control.VmError) as caught:
            v.start("win11")
        self.assertIn("refused", str(caught.exception))
        self.assertEqual(control.viewer_argv("win11 · D.Ai VM", "spice+unix:///x"), ["remote-viewer", "--title", "win11 · D.Ai VM", "spice+unix:///x"])


if __name__ == "__main__":
    unittest.main()
