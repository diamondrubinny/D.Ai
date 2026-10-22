# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import hashlib
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from dai_ai import client, daid, models


def model(sha="", size=10, url="https://huggingface.co/x/y.gguf"):
    return models.Model(
        id="test-model", name="Test", url=url, file="test.gguf", sha256=sha,
        size=size, license="Apache-2.0", ram_mb=512, purpose="test",
    )


class EnvTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {
            "XDG_DATA_HOME": str(base / "data"),
            "XDG_CONFIG_HOME": str(base / "config"),
            "XDG_RUNTIME_DIR": str(base / "run"),
        })
        self.env.start()
        (base / "run").mkdir()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()


class ModelTests(EnvTestCase):
    def opener(self, data):
        return lambda url: io.BytesIO(data)

    def test_install_verifies_sha256(self):
        data = b"GGUF-model-bytes"
        m = model(hashlib.sha256(data).hexdigest(), size=len(data))
        path = models.install(m, opener=self.opener(data))
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")

    def test_mismatch_is_discarded(self):
        m = model("0" * 64, size=16)
        with self.assertRaises(models.ModelError):
            models.install(m, opener=self.opener(b"tampered-model!!"))
        self.assertFalse(m.path.exists())
        self.assertFalse(m.path.with_suffix(".part").exists())

    def test_unpinned_and_oversized_are_refused(self):
        with self.assertRaises(models.ModelError):
            models.install(model(""), opener=self.opener(b"x"))
        with self.assertRaises(models.ModelError):
            models.install(model("1" * 64, size=4), opener=self.opener(b"far too many bytes"))

    def test_only_https_on_allowed_hosts(self):
        with self.assertRaises(models.ModelError):
            models._open("https://evil.example.com/model.gguf")
        with self.assertRaises(models.ModelError):
            models._open("http://huggingface.co/model.gguf")

    def test_host_allowlist_matches_whole_domains(self):
        for host in ["huggingface.co", "cdn-lfs.hf.co", "us.aws.cdn.hf.co", "cas-bridge.xethub.hf.co", "HF.CO."]:
            self.assertTrue(models.host_allowed(host), host)
        for host in ["evilhf.co", "huggingface.co.evil.com", "nothuggingface.co", "hf.co.example", "", None]:
            self.assertFalse(models.host_allowed(host), host)

    def test_redirect_policy(self):
        handler = models._HttpsOnlyRedirects()
        request = urllib.request.Request("https://huggingface.co/a.gguf")
        with self.assertRaises(models.ModelError):
            handler.redirect_request(request, None, 302, "Found", {}, "https://evilhf.co/a.gguf")
        with self.assertRaises(models.ModelError):
            handler.redirect_request(request, None, 302, "Found", {}, "http://us.aws.cdn.hf.co/a.gguf")
        follow = handler.redirect_request(request, None, 302, "Found", {}, "https://us.aws.cdn.hf.co/a.gguf")
        self.assertEqual(follow.full_url, "https://us.aws.cdn.hf.co/a.gguf")

    def test_catalog_validation(self):
        path = Path(self.tmp.name) / "catalog.json"
        good = {"id": "ok-model", "name": "x", "url": "https://huggingface.co/a.gguf", "file": "a.gguf",
                "sha256": "", "size": 1, "license": "MIT", "ram_mb": 1, "purpose": "x"}
        for bad in [{"url": "http://huggingface.co/a.gguf"}, {"file": "../a.gguf"}, {"file": "a.bin"}, {"id": "Bad ID"}]:
            path.write_text(json.dumps({"models": [{**good, **bad}]}))
            with self.subTest(bad=bad), self.assertRaises(models.ModelError):
                models.load_catalog(path)

    def test_shipped_catalog_is_valid(self):
        # Pinned hashes are verified against the real downloads by the
        # "AI models" workflow (build/scripts/verify-models.py).
        shipped = Path(__file__).resolve().parents[1] / "data" / "models.json"
        catalog = models.load_catalog(shipped)
        self.assertIn("qwen2.5-0.5b", catalog)
        self.assertTrue(all(m.license in ("Apache-2.0", "MIT") for m in catalog.values()))
        speech = [m for m in catalog.values() if "speech" in m.tasks]
        self.assertTrue(speech and all(m.file.endswith(".bin") and m.tasks == ("speech",) for m in speech))


class DaidTests(EnvTestCase):
    def test_request_validation(self):
        self.assertEqual(daid.validate_request({"op": "status"}), {"op": "status"})
        for bad in [
            {"op": "exec", "cmd": "id"},
            {"op": "chat", "messages": []},
            {"op": "chat", "messages": [{"role": "root", "content": "x"}]},
            {"op": "chat", "messages": [{"role": "user", "content": "x"}], "max_tokens": 10**6},
            {"op": "chat", "messages": [{"role": "user", "content": "x"}], "schema": "x"},
            ["op", "status"],
        ]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                daid.validate_request(bad)

    def test_client_server_roundtrip(self):
        class FakeBackend:
            def status(self):
                return {"ok": True, "model": "fake", "running": False}

            def chat(self, messages, schema, max_tokens, task):
                yield f"[{task}] " if task != "general" else ""
                yield "שלום "
                yield messages[-1]["content"]

            def reap(self):
                pass

        server = daid.Server(None, FakeBackend())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            sock = Path(os.environ["XDG_RUNTIME_DIR"]) / "dai" / "daid.sock"
            self.assertEqual(oct(sock.stat().st_mode & 0o777), "0o600")
            self.assertEqual(client.status()["model"], "fake")
            self.assertEqual("".join(client.ask("world")), "שלום world")
        finally:
            server.shutdown()
            server.server_close()

    def test_client_reports_unavailable(self):
        with self.assertRaises(client.AIUnavailable):
            client.status()


if __name__ == "__main__":
    unittest.main()


class TaskTests(EnvTestCase):
    def test_code_task_prefers_coder_model(self):
        shipped = Path(__file__).resolve().parents[1] / "data" / "models.json"
        catalog = models.load_catalog(shipped)
        self.assertIn("code", catalog["qwen2.5-coder-1.5b"].tasks)
        self.assertIsNone(models.default_model_id(catalog, "code"))
        for model in catalog.values():
            model.path.parent.mkdir(parents=True, exist_ok=True)
            model.path.write_bytes(b"x")
        self.assertEqual(models.default_model_id(catalog), "qwen2.5-0.5b")  # smallest for general use
        self.assertEqual(models.default_model_id(catalog, "code"), "qwen2.5-coder-1.5b")
        # Memory saver (docs/BEYOND.md §14): prefer_small wins over the chosen model, and only while it is set.
        larger = max((m for m in catalog.values() if "general" in m.tasks), key=lambda m: m.ram_mb).id
        models.set_default(larger)
        self.assertEqual(models.default_model_id(catalog), larger)
        path = models.config_file()
        data = json.loads(path.read_text())
        path.write_text(json.dumps({**data, "prefer_small": True}))
        self.assertEqual(models.default_model_id(catalog), "qwen2.5-0.5b")
        path.write_text(json.dumps(data))
        self.assertEqual(models.default_model_id(catalog), larger)

    def test_task_is_validated(self):
        base = {"op": "chat", "messages": [{"role": "user", "content": "x"}]}
        self.assertEqual(daid.validate_request(base)["task"], "general")
        self.assertEqual(daid.validate_request({**base, "task": "code"})["task"], "code")
        with self.assertRaises(ValueError):
            daid.validate_request({**base, "task": "root"})

    def test_speech_models_are_separate(self):
        shipped = Path(__file__).resolve().parents[1] / "data" / "models.json"
        catalog = models.load_catalog(shipped)
        whisper = catalog["whisper-base"]
        whisper.path.parent.mkdir(parents=True, exist_ok=True)
        whisper.path.write_bytes(b"x")
        self.assertIsNone(models.default_model_id(catalog))  # never used for chat
        self.assertEqual(models.default_model_id(catalog, "speech"), "whisper-base")
        catalog["whisper-small"].path.write_bytes(b"x")
        self.assertEqual(models.default_model_id(catalog, "speech"), "whisper-base")  # smallest by default
        models.set_default("whisper-small", "speech_model")
        self.assertEqual(models.default_model_id(catalog, "speech"), "whisper-small")
        models.set_default("qwen2.5-0.5b")  # chat choice kept separately
        self.assertEqual(models.default_model_id(catalog, "speech"), "whisper-small")

    def test_speech_file_suffix(self):
        path = Path(self.tmp.name) / "catalog.json"
        entry = {"id": "voice", "name": "x", "url": "https://huggingface.co/a.gguf", "file": "a.gguf", "sha256": "",
                 "size": 1, "license": "MIT", "ram_mb": 1, "purpose": "x", "tasks": ["speech"]}
        path.write_text(json.dumps({"models": [entry]}))
        with self.assertRaises(models.ModelError):
            models.load_catalog(path)

