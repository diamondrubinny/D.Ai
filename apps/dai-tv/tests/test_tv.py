# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai TV (dai_tv): JSON-RPC to a fake Kodi on a local socket, the commands and their exit codes, Diamond
answering (or saying it is not here), nothing sent anywhere else."""
import contextlib
import io
import json
import os
import socket
import threading
import unittest
from unittest import mock

from dai_tv import cli, rpc


class FakeKodi:
    """Kodi's TCP JSON-RPC: one object in, one object out, on 127.0.0.1 and a free port."""

    def __init__(self, playing=None, fail=()):
        self.playing, self.fail, self.calls = playing, set(fail), []
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(5)
        self.port = self.server.getsockname()[1]
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                request = json.loads(conn.recv(65536).decode("utf-8"))
                self.calls.append((request["method"], request.get("params")))
                method = request["method"]
                if method in self.fail:
                    answer = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found."}}
                elif method == "JSONRPC.Ping":
                    answer = {"jsonrpc": "2.0", "id": 1, "result": "pong"}
                elif method == "Player.GetActivePlayers":
                    answer = {"jsonrpc": "2.0", "id": 1, "result": [{"playerid": 1, "type": "video"}] if self.playing else []}
                elif method == "Player.GetItem":
                    answer = {"jsonrpc": "2.0", "id": 1, "result": {"item": self.playing}}
                else:
                    answer = {"jsonrpc": "2.0", "id": 1, "result": "OK"}
                conn.sendall(json.dumps(answer).encode("utf-8"))

    def close(self):
        self.server.close()


class TvTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8", "LC_ALL": "", "LANGUAGE": "", "DAI_LANG": "en"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def kodi(self, **kw):
        fake = FakeKodi(**kw)
        self.addCleanup(fake.close)
        return fake

    def run_cli(self, fake, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(rpc, "PORT", fake.port):
            code = cli.main(["dai-tv", *args])
        return code, out.getvalue(), err.getvalue()

    def test_ping_say_and_do(self):
        fake = self.kodi()
        self.assertEqual(self.run_cli(fake, "ping")[0:2], (0, "pong\n"))
        code, out, _ = self.run_cli(fake, "say", "שלום", "עולם")
        self.assertEqual(code, 0)
        self.assertIn("Shown on the TV", out)
        self.assertEqual(fake.calls[-1], ("GUI.ShowNotification", {"title": "D.Ai", "message": "שלום עולם", "displaytime": 6000}))
        self.assertEqual(self.run_cli(fake, "do", "pause")[0], 0)
        self.assertEqual(fake.calls[-1], ("Input.ExecuteAction", {"action": "pause"}))
        self.assertEqual(self.run_cli(fake, "do", "rm -rf")[0], 2)
        self.assertEqual(self.run_cli(fake, "say")[0], 2)
        self.assertEqual(self.run_cli(fake, "dance")[0], 2)
        code, out, _ = self.run_cli(fake, "--version")
        self.assertIn("dai-tv 0.1.0 — Diamond Rubinny (d.Ai)", out)

    def test_playing_and_nothing(self):
        fake = self.kodi(playing={"title": "The Film", "year": 1999, "plot": "A long story " * 50, "type": "movie", "label": "x"})
        code, out, _ = self.run_cli(fake, "playing")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("The Film (1999)\n"))
        self.assertLessEqual(len(out), 330)
        code, out, _ = self.run_cli(self.kodi(), "playing")
        self.assertEqual(out, "Nothing is playing.\n")

    def test_no_kodi_and_a_refusal(self):
        dead = socket.socket()
        dead.bind(("127.0.0.1", 0))
        port = dead.getsockname()[1]
        dead.close()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(rpc, "PORT", port), \
                mock.patch.object(rpc, "TIMEOUT", 1.0):
            code = cli.main(["dai-tv", "ping"])
        self.assertEqual(code, 1)
        self.assertIn("could not be reached", err.getvalue())
        fake = self.kodi(fail={"GUI.ShowNotification"})
        code, _, err = self.run_cli(fake, "say", "x")
        self.assertEqual(code, 1)
        self.assertIn("Method not found", err)

    def test_ask_goes_to_diamond_and_the_tv(self):
        fake = self.kodi(playing={"title": "The Film", "year": 1999, "plot": "", "type": "movie"})
        import sys, types
        module = types.ModuleType("dai_ai.client")
        module.ask = lambda q, max_tokens=512: iter(["A film ", "about a film."])
        package = types.ModuleType("dai_ai")
        package.client = module
        with mock.patch.dict(sys.modules, {"dai_ai": package, "dai_ai.client": module}):
            code, out, _ = self.run_cli(fake, "ask", "what is this about?")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "A film about a film.")
        self.assertEqual(fake.calls[-1][0], "GUI.ShowNotification")
        self.assertEqual(fake.calls[-1][1]["title"], "Diamond")
        with mock.patch.dict(sys.modules, {"dai_ai": None}):
            code, out, _ = self.run_cli(fake, "ask", "anything")
        self.assertIn("Diamond is not installed", out)


if __name__ == "__main__":
    unittest.main()
