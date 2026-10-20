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

    def test_the_remotes_microphone(self):
        """docs/TV.md §10: a spoken command is done; anything else goes to Diamond; no Voice is said on the TV."""
        fake = self.kodi()
        with mock.patch.object(cli, "_voice_text", return_value=" השהה "):
            code, out, _ = self.run_cli(fake, "listen", "--seconds", "3")
        self.assertEqual((code, out.strip()), (0, "Heard: השהה → pause"))
        self.assertEqual(fake.calls[0], ("GUI.ShowNotification", {"title": "D.Ai", "message": "Listening… (3 seconds)", "displaytime": 3000}))
        self.assertEqual(fake.calls[-1], ("Input.ExecuteAction", {"action": "pause"}))
        with mock.patch.object(cli, "_voice_text", return_value="who directed this film"), \
                mock.patch.object(cli, "_ask_diamond", return_value="Someone famous."):
            code, out, _ = self.run_cli(fake, "listen")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["Heard: who directed this film", "Someone famous."])
        self.assertEqual(fake.calls[-1][0], "GUI.ShowNotification")
        self.assertEqual(fake.calls[-1][1]["title"], "Diamond")
        with mock.patch.object(cli, "_voice_text", return_value="  "):
            self.assertEqual(self.run_cli(fake, "listen")[0], 3)
        with mock.patch.object(cli, "_voice_text", side_effect=RuntimeError("D.Ai Voice is not installed on this TV")):
            code, _, err = self.run_cli(fake, "listen")
        self.assertEqual(code, 1)
        self.assertIn("not installed", err)
        self.assertIn("not installed", fake.calls[-1][1]["message"])
        for text, action in (("Pause.", "pause"), ("חזק יותר", "volumeup"), ("what is this?", "info"), ("rm -rf /", None),
                             ("pause " * 20, None)):
            self.assertEqual(cli.spoken_action(text), action, text)

    def test_night_mode_in_the_running_kodi(self):
        fake = self.kodi()
        code, out, _ = self.run_cli(fake, "night", "on")
        self.assertEqual((code, out.strip()), (0, "Night mode: on"))
        self.assertIn(("Settings.SetSettingValue", {"setting": "screensaver.mode", "value": "screensaver.xbmc.builtin.dim"}), fake.calls)
        self.assertIn(("Settings.SetSettingValue", {"setting": "screensaver.time", "value": 5}), fake.calls)
        self.assertIn(("Application.SetVolume", {"volume": 40}), fake.calls)
        self.assertEqual(self.run_cli(fake, "night", "off")[0], 0)
        self.assertIn(("Application.SetVolume", {"volume": 75}), fake.calls)
        self.assertEqual(self.run_cli(fake, "night", "dim")[0], 2)

    def test_the_addon_database_is_seeded_before_kodi(self):
        """docs/TV.md §11: Kodi 21's schema, the channel add-ons enabled, the person's own disabling respected."""
        import datetime
        import sqlite3
        import tempfile
        from pathlib import Path

        from dai_tv import seed
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".kodi"
            changed = seed.seed(home, now=datetime.datetime(2026, 10, 20, 9, 30))
            self.assertEqual(changed, ["pvr.iptvsimple", "inputstream.adaptive"])
            db = home / "userdata/Database/Addons33.db"
            self.assertEqual(oct(db.stat().st_mode & 0o777), "0o600")
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute("SELECT idVersion, iCompressCount FROM version").fetchall(), [(33, 0)])
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertEqual(tables, {"addons", "repo", "addonlinkrepo", "update_rules", "package", "installed", "version"})
                self.assertEqual(conn.execute("SELECT addonID, enabled, installDate, origin, disabledReason FROM installed ORDER BY id").fetchall(),
                                 [("pvr.iptvsimple", 1, "2026-10-20 09:30:00", "", 0), ("inputstream.adaptive", 1, "2026-10-20 09:30:00", "", 0)])
                conn.execute("UPDATE installed SET enabled = 0, disabledReason = 1 WHERE addonID = 'pvr.iptvsimple'")  # the person's choice
                conn.execute("UPDATE installed SET enabled = 0 WHERE addonID = 'inputstream.adaptive'")  # Kodi's default
            self.assertEqual(seed.seed(home), ["inputstream.adaptive"])
            self.assertEqual((seed.enabled(home, "pvr.iptvsimple"), seed.enabled(home, "inputstream.adaptive"), seed.enabled(home, "x")),
                             (False, True, None))
            self.assertEqual(seed.seed(home), [])  # idempotent
            playlist = Path(tmp) / "channels.m3u"
            playlist.write_text("#EXTM3U\n")
            path = seed.channels(home, playlist, epg="https://example.org/epg.xml")
            text = path.read_text()
            self.assertEqual(path.name, "instance-settings-1.xml")
            for piece in ('<setting id="kodi_addon_instance_name">D.Ai channels</setting>', '<setting id="kodi_addon_instance_enabled">true</setting>',
                          '<setting id="m3uPathType">0</setting>', f'<setting id="m3uPath">{playlist}</setting>',
                          '<setting id="epgUrl">https://example.org/epg.xml</setting>'):
                self.assertIn(piece, text)
            self.assertEqual(seed.current_playlist(home), str(playlist))
            self.assertTrue(seed.channels_off(home))
            self.assertFalse(seed.channels_off(home))
            self.assertEqual(seed.current_playlist(home), "")

    def test_channels_from_the_command_line(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(cli, "kodi_home", return_value=Path(tmp) / ".kodi"):
            fake = self.kodi()
            code, out, _ = self.run_cli(fake, "seed")
            self.assertEqual((code, "pvr.iptvsimple" in out), (0, True), out)
            code, _, err = self.run_cli(fake, "channels", str(Path(tmp) / "none.m3u"))
            self.assertEqual((code, "Which playlist" in err), (2, True))
            playlist = Path(tmp) / "my.m3u"
            playlist.write_text("#EXTM3U\n")
            self.assertEqual(self.run_cli(fake, "channels", str(playlist), "--epg", "ftp://x")[0], 2)
            code, out, _ = self.run_cli(fake, "channels", str(playlist))
            self.assertEqual((code, "Live channels from my.m3u" in out), (0, True), out)
            self.assertIn("m3uPath", (Path(tmp) / ".kodi/userdata/addon_data/pvr.iptvsimple/instance-settings-1.xml").read_text())
            code, out, _ = self.run_cli(fake, "channels", "--off")
            self.assertEqual((code, out.strip()), (0, "Live channels off."))
            self.assertEqual(fake.calls, [])  # nothing of this needs the running Kodi

    def test_ruby_in_tv_mode(self):
        """docs/TV.md §12: a kiosk Firefox in its own profile, one at a time, ended by "back to the TV"."""
        import tempfile
        from pathlib import Path

        from dai_tv import browse
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            spawned, killed = [], []
            pid = browse.open_url("https://www.kan.org.il/", home, spawn=lambda cmd: spawned.append(cmd) or os.getpid(), firefox="/bin/ff")
            self.assertEqual(pid, os.getpid())
            self.assertEqual(spawned, [["/bin/ff", "--new-instance", "--kiosk", "--profile", str(home / ".config/dai/ruby-tv"), "https://www.kan.org.il/"]])
            prefs = (home / ".config/dai/ruby-tv/user.js").read_text()
            self.assertIn('user_pref("layout.css.devPixelsPerPx", "1.75");', prefs)
            self.assertIn('user_pref("media.autoplay.default", 0);', prefs)
            self.assertIn('user_pref("privacy.sanitize.sanitizeOnShutdown", true);', prefs)
            self.assertEqual(oct((home / ".config/dai/ruby-tv").stat().st_mode & 0o777), "0o700")
            self.assertEqual(browse.running(home), os.getpid())
            self.assertTrue(browse.close(home, kill=lambda p, sig: killed.append((p, sig))))
            self.assertEqual(killed, [(os.getpid(), 15)])
            self.assertIsNone(browse.running(home))
            self.assertFalse(browse.close(home, kill=lambda p, sig: killed.append((p, sig))))
            for bad in ("ftp://x", "file:///etc/passwd", "javascript:alert(1)", "", "rm -rf /"):
                with self.assertRaises(ValueError):
                    browse.open_url(bad, home, spawn=lambda cmd: 1)
            self.assertTrue(browse.allowed("file:///usr/share/dai/ruby/start.html"))
            (home / ".config/dai/ruby-tv/ruby-tv.pid").write_text("999999999\n")  # a pid that is not alive
            self.assertIsNone(browse.running(home))
        fake = self.kodi()
        with mock.patch.object(browse, "open_url", return_value=4242), mock.patch.object(browse, "close", return_value=True):
            code, out, _ = self.run_cli(fake, "browse", "https://www.mako.co.il/")
            self.assertEqual((code, "pid 4242" in out), (0, True), out)
            code, out, _ = self.run_cli(fake, "browse", "--close")
            self.assertEqual((code, out.strip()), (0, "Back to the TV."))
        self.assertEqual(self.run_cli(fake, "browse", "ftp://x")[0], 2)

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
