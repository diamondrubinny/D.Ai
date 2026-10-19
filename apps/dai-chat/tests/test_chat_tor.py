# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Diamond Chat's own Tor (dai_chat/tor.py): the key Tor gets, the control protocol, and a real Tor when one
is installed (CI installs it): start, authenticate, publish the onion service, check its address, stop."""
import importlib.util
import os
import shutil
import socket
import stat
import tempfile
import threading
import unittest
from pathlib import Path

if importlib.util.find_spec("nacl") is None:  # python3-nacl, in Debian
    raise unittest.SkipTest("PyNaCl is missing")

from nacl.bindings import crypto_scalarmult_ed25519_base_noclamp
from nacl.signing import SigningKey

from dai_chat import invite, tor


class KeyTests(unittest.TestCase):
    def test_the_expanded_key_belongs_to_the_seed(self):
        for _ in range(20):
            seed = os.urandom(32)
            expanded = tor.expanded_key(seed)
            self.assertEqual(len(expanded), 64)
            self.assertEqual(crypto_scalarmult_ed25519_base_noclamp(expanded[:32]), bytes(SigningKey(seed).verify_key))

    def test_torrc_keeps_everything_in_private_folders(self):
        paths = tor.Paths(Path("/run/user/1000/dai-chat"), Path("/home/dana/.local/share/dai/chat/tor"))
        text = tor.torrc(paths, 4242)
        self.assertIn("SocksPort unix:/run/user/1000/dai-chat/socks.sock", text)
        self.assertIn("ControlPort unix:/run/user/1000/dai-chat/control.sock", text)
        self.assertIn("CookieAuthentication 1", text)
        self.assertIn("__OwningControllerProcess 4242", text)
        self.assertNotIn("9050", text)  # no TCP port that other users on the computer could use


class FakeTor:
    """Answers like Tor's control port, over a socket pair."""

    def __init__(self, replies):
        self.mine, theirs = socket.socketpair()
        self.replies, self.heard = replies, []
        self.thread = threading.Thread(target=self.serve, args=(theirs,), daemon=True)
        self.thread.start()

    def serve(self, sock):
        data = b""
        with sock:
            for reply in self.replies:
                while b"\r\n" not in data:
                    data += sock.recv(4096)
                line, data = data.split(b"\r\n", 1)
                self.heard.append(line.decode())
                sock.sendall(reply.encode())


class ControllerTests(unittest.TestCase):
    def test_commands_and_replies(self):
        seed = os.urandom(32)
        address = invite.onion_address(bytes(SigningKey(seed).verify_key))
        fake = FakeTor(["250 OK\r\n",
                        '250-status/bootstrap-phase=NOTICE BOOTSTRAP PROGRESS=100 TAG=done SUMMARY="Done"\r\n250 OK\r\n',
                        f"250-ServiceID={address[:-6]}\r\n250 OK\r\n",
                        "552 Unrecognized command\r\n"])
        control = tor.Controller(Path("unused"), connect=lambda path: fake.mine)
        control.authenticate(b"\x01\xab")
        self.assertEqual(control.bootstrap(), 100)
        self.assertEqual(control.add_onion(seed), address)
        with self.assertRaises(tor.TorError):
            control.command("NOPE")
        with self.assertRaises(tor.TorError):
            control.command("GETINFO x\r\nSIGNAL HALT")  # one command per line: no smuggling
        self.assertEqual(fake.heard[0], "AUTHENTICATE 01ab")
        self.assertTrue(fake.heard[2].startswith("ADD_ONION ED25519-V3:"))
        self.assertTrue(fake.heard[2].endswith(" Port=7714,127.0.0.1:7714"))  # loopback only
        control.close()

    def test_a_wrong_address_is_refused(self):
        other = invite.onion_address(os.urandom(32))
        fake = FakeTor([f"250-ServiceID={other[:-6]}\r\n250 OK\r\n"])
        runner = tor.Tor(tor.Paths(Path("/nonexistent"), Path("/nonexistent")))
        runner.control = tor.Controller(Path("unused"), connect=lambda path: fake.mine)
        self.addCleanup(runner.stop)
        with self.assertRaises(tor.TorError):
            runner.publish(os.urandom(32))

    def test_tor_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            def missing(*args, **kwargs):
                raise FileNotFoundError("tor")

            with self.assertRaises(tor.TorError):
                tor.Tor(tor.Paths(Path(tmp) / "run", Path(tmp) / "data"), popen=missing).start()


@unittest.skipIf(shutil.which("tor") is None, "Tor is not installed")
class RealTorTests(unittest.TestCase):
    def test_start_publish_and_stop(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:  # Unix socket paths must stay short
            runner = tor.Tor(tor.Paths(Path(tmp) / "run", Path(tmp) / "data"))
            try:
                runner.start(timeout=60)
                self.assertEqual(stat.S_IMODE((Path(tmp) / "run").stat().st_mode), 0o700)
                seed = os.urandom(32)
                address = runner.publish(seed)
                self.assertEqual(address, invite.onion_address(bytes(SigningKey(seed).verify_key)))
                self.assertEqual(runner.publish(seed), address)  # twice is fine
                self.assertTrue((Path(tmp) / "run" / "socks.sock").exists())
                process = runner.process
            finally:
                runner.stop()
            self.assertIsNotNone(process.poll())  # Tor is gone with Chat


if __name__ == "__main__":
    unittest.main()
