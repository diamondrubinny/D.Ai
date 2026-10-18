# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai Rescue (docs/BASICS.md): finding the installed system, opening it, and always closing it again."""
import io
import json
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from dai_tune import rescue
from dai_tune.context import ActionError

LSBLK = {"blockdevices": [
    {"path": "/dev/nvme0n1", "fstype": None, "type": "disk", "mountpoints": [None], "children": [
        {"path": "/dev/nvme0n1p1", "fstype": "vfat", "type": "part", "mountpoints": [None]},
        {"path": "/dev/nvme0n1p2", "fstype": "crypto_LUKS", "type": "part", "mountpoints": [None], "size": "476G"},
    ]},
    {"path": "/dev/sda", "fstype": "iso9660", "type": "disk", "mountpoints": ["/run/live/medium"]},
    {"path": "/dev/sdb1", "fstype": "btrfs", "type": "part", "mountpoints": ["/media/dai/data"]},  # in use
    {"path": "/dev/sdc1; rm -rf /", "fstype": "btrfs", "type": "part", "mountpoints": [None]},  # not a device name
]}


class Recorder:
    def __init__(self, fail=()):
        self.calls, self.fail = [], fail

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs.get("input")))
        if argv[0] == "lsblk":
            return subprocess.CompletedProcess(argv, 0, json.dumps(LSBLK), "")
        code = 1 if argv[0] in self.fail else 0
        return subprocess.CompletedProcess(argv, code, "", "wrong key" if code else "")


class RescueTests(unittest.TestCase):
    def test_only_unused_btrfs_or_luks_partitions(self):
        found = rescue.disks(Recorder())
        self.assertEqual([(d.path, d.fstype) for d in found], [("/dev/nvme0n1p2", "crypto_LUKS")])

    def test_opens_with_the_passphrase_on_stdin_and_always_closes(self):
        run = Recorder()
        disk = rescue.Disk("/dev/nvme0n1p2", "crypto_LUKS")
        with rescue.Opened(disk, "correct horse", run) as opened:
            top = opened.top
            self.assertTrue(Path(top).is_dir())
            self.assertEqual(opened.root, "")  # no /etc/os-release in "@": not an installed system
        argvs = [c[0] for c in run.calls]
        self.assertEqual(argvs[0], ["cryptsetup", "open", "--type", "luks", "--key-file", "-", "/dev/nvme0n1p2",
                                    "dai-rescue"])
        self.assertEqual(run.calls[0][1], "correct horse")  # on stdin, never on the command line
        self.assertNotIn("correct horse", " ".join(" ".join(a) for a in argvs))
        self.assertEqual(argvs[1], ["mount", "-o", "subvolid=5", "/dev/mapper/dai-rescue", top])
        self.assertEqual(argvs[-2:], [["umount", top], ["cryptsetup", "close", "dai-rescue"]])
        self.assertFalse(Path(top).exists())

    def test_a_wrong_passphrase_leaves_nothing_open(self):
        run = Recorder(fail=("cryptsetup",))
        with self.assertRaisesRegex(ActionError, "wrong key"):
            with rescue.Opened(rescue.Disk("/dev/nvme0n1p2", "crypto_LUKS"), "nope", run):
                pass
        self.assertNotIn("mount", [c[0][0] for c in run.calls])
        with self.assertRaisesRegex(ActionError, "passphrase"):
            with rescue.Opened(rescue.Disk("/dev/nvme0n1p2", "crypto_LUKS"), None, Recorder()):
                pass

    def test_reads_snapper_files_and_swaps_back_to_the_pre_snapshot(self):
        run = Recorder()
        with rescue.Opened(rescue.Disk("/dev/sdb2", "btrfs"), None, run) as opened:
            top = Path(opened.top)
            (top / "@/etc").mkdir(parents=True)
            (top / "@/etc/os-release").write_text("ID=debian\n")
            for number, kind, extra in ((7, "pre", ""), (8, "post", "<pre_num>7</pre_num>"),
                                        (9, "single", ""), (10, "pre", "")):
                folder = top / "@/.snapshots" / str(number)
                (folder / "snapshot").mkdir(parents=True)
                (folder / "info.xml").write_text(f"<?xml version=\"1.0\"?><snapshot><type>{kind}</type><num>{number}"
                                                 f"</num><date>2026-10-17 21:0{number % 10}:00</date>"
                                                 f"<description>apt</description>{extra}</snapshot>")
            (top / "@/.snapshots/11").mkdir()
            (top / "@/.snapshots/11/info.xml").write_text("<not xml")  # broken files are skipped
            rows = rescue.updates(opened)
            self.assertEqual([r["number"] for r in rows], [7, 8, 9, 10])
            self.assertEqual(rows[1]["pre-number"], 7)
            self.assertEqual(rescue.undo_last_update(opened, stamp="T"), (7, 8, "@.before-rescue-T"))
        commands = [c[0] for c in run.calls if c[0][0] in ("btrfs", "mv", "rmdir")]
        self.assertEqual(commands, [
            ["btrfs", "subvolume", "snapshot", f"{top}/@/.snapshots/7/snapshot", f"{top}/@.dai-rescue-new"],
            ["mv", "-T", f"{top}/@", f"{top}/@.before-rescue-T"],
            ["mv", "-T", f"{top}/@.dai-rescue-new", f"{top}/@"],
            ["rmdir", f"{top}/@/.snapshots"],
            ["mv", "-T", f"{top}/@.before-rescue-T/.snapshots", f"{top}/@/.snapshots"],
        ])

    def test_undo_from_the_cli(self):
        rows = [{"number": 7, "type": "pre", "description": "apt"},
                {"number": 8, "type": "post", "pre-number": 7, "description": "apt", "date": "2026-10-17 21:04"}]
        out = io.StringIO()
        with mock.patch.object(rescue.Opened, "root", new_callable=mock.PropertyMock, return_value="/x/@"), \
                mock.patch.object(rescue, "updates", return_value=rows), \
                mock.patch.object(rescue, "undo_last_update", return_value=(7, 8, "@.before-rescue-T")) as undo, \
                redirect_stdout(out):
            code = rescue.main(["dai-rescue", "--undo-last-update", "--yes"], run=Recorder(), secret=lambda p: "pw")
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("2026-10-17 21:04", out.getvalue())
        self.assertIn("@.before-rescue-T", out.getvalue())
        undo.assert_called_once()
        with mock.patch.object(rescue.Opened, "root", new_callable=mock.PropertyMock, return_value="/x/@"), \
                mock.patch.object(rescue, "updates", return_value=rows), \
                mock.patch.object(rescue, "undo_last_update") as undo, redirect_stdout(io.StringIO()):
            code = rescue.main(["dai-rescue", "--undo-last-update"], run=Recorder(), ask=lambda p: "n",
                               secret=lambda p: "pw")
        self.assertEqual(code, 1)
        undo.assert_not_called()  # nothing changes before the person says yes

    def test_nothing_found(self):
        empty = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, '{"blockdevices": []}', "")  # noqa: E731
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            self.assertEqual(rescue.main(["dai-rescue"], run=empty), 1)
        self.assertIn("No installed D.Ai system", out.getvalue())


if __name__ == "__main__":
    unittest.main()
