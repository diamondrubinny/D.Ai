# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import hashlib
import io
from contextlib import redirect_stderr, redirect_stdout
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



class ProviderTests(EnvTestCase):
    """External providers with your own key (docs/PROVIDERS.md)."""

    def setUp(self):
        super().setUp()
        from dai_ai import providers
        self.providers = providers

    def test_config_round_trip_is_private_and_masks_the_key(self):
        p = self.providers
        config = p.Config()
        config.providers["anthropic"] = p.make("anthropic")
        config.providers["anthropic"].key = "sk-ant-secret-key-1234"
        path = p.save(config)
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
        again = p.load(path)
        self.assertEqual(again.providers["anthropic"].key, "sk-ant-secret-key-1234")
        self.assertEqual(again.providers["anthropic"].masked_key(), "sk-…34")
        self.assertNotIn("secret", json.dumps(again.providers["anthropic"].public()))
        self.assertEqual(again.active, "")
        with mock.patch.dict(os.environ, {"DAI_PROVIDER_KEY_ANTHROPIC": "env-key"}):
            self.assertEqual(again.providers["anthropic"].resolved_key(), "env-key")

    def test_make_validates_names_kinds_and_urls(self):
        p = self.providers
        self.assertEqual(p.make("openai").kind, "openai")
        self.assertEqual(p.make("google").kind, "gemini")
        custom = p.make("lab", "openai", "http://192.168.1.20:11434/v1/", "llama3")
        self.assertEqual(custom.base_url, "http://192.168.1.20:11434/v1")
        for bad in (("Bad Name",), ("x", "openai", "http://example.com/v1", "m"), ("x", "weird", "https://a/v1", "m"), ("custom",)):
            with self.assertRaises(p.ProviderError):
                p.make(*bad)

    def test_requests_per_kind_and_json_schema(self):
        p = self.providers
        messages = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "hi"}]
        schema = {"type": "object"}
        with mock.patch.dict(os.environ, {"DAI_PROVIDER_KEY_ANTHROPIC": "k1", "DAI_PROVIDER_KEY_OPENAI": "k2", "DAI_PROVIDER_KEY_GOOGLE": "k3"}):
            url, headers, body = p.build_request(p.make("anthropic"), messages, schema, 100)
            self.assertEqual(url, "https://api.anthropic.com/v1/messages")
            self.assertEqual(headers["x-api-key"], "k1")
            self.assertIn("JSON schema", body["system"])
            self.assertEqual(body["messages"], [{"role": "user", "content": "hi"}])
            url, headers, body = p.build_request(p.make("openai"), messages, None, 100)
            self.assertEqual(url, "https://api.openai.com/v1/chat/completions")
            self.assertEqual(headers["authorization"], "Bearer k2")
            self.assertEqual(body["messages"][0], {"role": "system", "content": "Be brief."})
            self.assertNotIn("response_format", body)
            url, headers, body = p.build_request(p.make("google"), messages, schema, 100)
            self.assertTrue(url.endswith("/models/gemini-2.5-flash:generateContent"))
            self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
            self.assertEqual(body["contents"][0]["role"], "user")
        with self.assertRaises(p.ProviderError):
            p.build_request(p.make("openai"), messages, None, 100)   # no key anywhere
        self.assertEqual(p.parse_reply("anthropic", {"content": [{"type": "text", "text": "ok"}]}), "ok")
        self.assertEqual(p.parse_reply("gemini", {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}), "ok")
        self.assertEqual(p.parse_reply("openai", {"choices": [{"message": {"content": "ok"}}]}), "ok")
        with self.assertRaises(p.ProviderError):
            p.parse_reply("openai", {"nope": 1})

    def test_chat_talks_https_and_reports_failures_without_the_key(self):
        p = self.providers
        provider = p.make("openai")
        provider.key = "sk-top-secret"
        seen = {}

        class Response:
            def __init__(self, data): self.data = data
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n=-1): return self.data

        def opener(request, timeout):
            seen["url"], seen["auth"] = request.full_url, request.get_header("Authorization")
            return Response(json.dumps({"choices": [{"message": {"content": "hello"}}]}).encode())

        self.assertEqual(p.chat(provider, [{"role": "user", "content": "hi"}], opener=opener), "hello")
        self.assertEqual(seen["url"], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(seen["auth"], "Bearer sk-top-secret")
        import urllib.error
        def failing(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "x", {}, io.BytesIO(b'{"error": {"message": "bad key sk-top-secret"}}'))
        with self.assertRaises(p.ProviderError) as caught:
            p.chat(provider, [{"role": "user", "content": "hi"}], opener=failing)
        self.assertIn("HTTP 401", str(caught.exception))

    def test_routing_needs_consent_and_falls_back(self):
        from dai_ai import client, providers as p
        config = p.Config()
        config.providers["anthropic"] = p.make("anthropic")
        config.providers["anthropic"].key = "k"
        config.active = "anthropic"
        p.save(config)
        self.assertEqual(p.where(), {"code": "local", "general": "local", "speech": "local"})   # no consent yet
        p.record_consent(config, "anthropic")
        config.providers["anthropic"].tasks = ("code",)
        p.save(config)
        self.assertEqual(p.where(), {"code": "anthropic", "general": "local", "speech": "local"})
        self.assertEqual(client.where("code"), "anthropic")
        with mock.patch.object(p, "stream", return_value=iter(["from ", "the cloud"])):
            self.assertEqual("".join(client.chat([{"role": "user", "content": "x"}], task="code")), "from the cloud")
        local = [{"delta": "local answer"}, {"done": True}]
        with mock.patch.object(p, "stream", side_effect=p.ProviderError("anthropic: no route")), \
                mock.patch.object(client, "_request", return_value=iter(local)), redirect_stderr(io.StringIO()) as err:
            self.assertEqual("".join(client.chat([{"role": "user", "content": "x"}], task="code")), "local answer")
        self.assertIn("local Diamond instead", err.getvalue())
        config.fallback = False
        p.save(config)
        with mock.patch.object(p, "stream", side_effect=p.ProviderError("anthropic: no route")), self.assertRaises(client.AIUnavailable):
            "".join(client.chat([{"role": "user", "content": "x"}], task="code"))

    def test_cli(self):
        from dai_ai import providers_cli as cli, providers as p
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()), mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8"}):
            self.assertEqual(cli.main(["add", "anthropic"]), 0)
            self.assertEqual(cli.main(["key", "anthropic"], read_key=lambda prompt: "sk-ant-123456789"), 0)
            self.assertEqual(cli.main(["use", "anthropic", "--tasks", "code"], ask=lambda prompt: "no"), 1)
            self.assertEqual(p.load().active, "")
            self.assertEqual(cli.main(["use", "anthropic", "--tasks", "code"], ask=lambda prompt: "כן"), 0)
            self.assertEqual(p.where(), {"code": "anthropic", "general": "local", "speech": "local"})
            self.assertEqual(cli.main(["list"]), 0)
            self.assertEqual(cli.main(["use", "local"]), 0)
            self.assertEqual(p.load().active, "")
            self.assertEqual(cli.main(["add", "lab", "--kind", "openai", "--url", "http://10.0.0.5:11434/v1", "--model", "llama3"]), 0)
            self.assertEqual(cli.main(["remove", "anthropic"]), 0)
            self.assertEqual(cli.main(["remove", "anthropic"]), 1)
            self.assertEqual(cli.main(["fallback", "off"]), 0)
            self.assertEqual(cli.main(["dance"]), 2)
        text = out.getvalue()
        self.assertIn("will be sent to anthropic's servers", text)
        self.assertNotIn("sk-ant-123456789", text)
        self.assertIn("sk-…89", text)
        self.assertFalse(p.load().fallback)


class StreamingTests(unittest.TestCase):
    """docs/PROVIDERS.md §2b: the answer piece by piece, from each provider's event stream."""

    def setUp(self):
        from dai_ai import providers
        self.p = providers

    @staticmethod
    def response(lines: list[str]):
        class Response:
            def __init__(self, data): self.data = data
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def __iter__(self): return iter(self.data)
        return Response([(line + "\n").encode("utf-8") for line in lines])

    def provider(self, name):
        provider = self.p.make(name)
        provider.key = "k"
        return provider

    def test_stream_requests_and_events_per_kind(self):
        p = self.p
        url, headers, body = p.stream_request(self.provider("openai"), [{"role": "user", "content": "hi"}], 50)
        self.assertTrue(body["stream"])
        self.assertEqual(headers["accept"], "text/event-stream")
        url, _, body = p.stream_request(self.provider("google"), [{"role": "user", "content": "hi"}], 50)
        self.assertTrue(url.endswith(":streamGenerateContent?alt=sse"))
        self.assertNotIn("stream", body)
        self.assertEqual(p.parse_event("openai", {"choices": [{"delta": {"content": "he"}}]}), "he")
        self.assertEqual(p.parse_event("openai", {"choices": [{"delta": {"role": "assistant"}}]}), "")
        self.assertEqual(p.parse_event("anthropic", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "l"}}), "l")
        self.assertEqual(p.parse_event("anthropic", {"type": "message_start", "message": {}}), "")
        self.assertEqual(p.parse_event("gemini", {"candidates": [{"content": {"parts": [{"text": "lo"}]}}]}), "lo")
        self.assertEqual(p.parse_event("gemini", {"usageMetadata": {}}), "")
        self.assertEqual(p.parse_event("openai", "junk"), "")

    def test_stream_yields_pieces_and_stops_on_done_or_error(self):
        p = self.p
        seen = {}

        def opener(request, timeout):
            seen["url"] = request.full_url
            return self.response([
                "event: ping", ": comment", "",
                'data: {"choices": [{"delta": {"role": "assistant"}}]}',
                'data: {"choices": [{"delta": {"content": "hel"}}]}',
                "data: not json",
                'data: {"choices": [{"delta": {"content": "lo"}}]}',
                "data: [DONE]",
            ])

        pieces = list(p.stream(self.provider("openai"), [{"role": "user", "content": "hi"}], opener=opener))
        self.assertEqual(pieces, ["hel", "lo"])
        self.assertEqual(seen["url"], "https://api.openai.com/v1/chat/completions")

        def erroring(request, timeout):
            return self.response(['data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "a"}}',
                                  'data: {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}'])
        out = []
        with self.assertRaises(p.ProviderError) as caught:
            for piece in p.stream(self.provider("anthropic"), [{"role": "user", "content": "hi"}], opener=erroring):
                out.append(piece)
        self.assertEqual(out, ["a"])
        self.assertIn("Overloaded", str(caught.exception))

        def huge(request, timeout):
            return self.response(['data: {"choices": [{"delta": {"content": "' + "x" * 1000 + '"}}]}'] * 300)
        with self.assertRaises(p.ProviderError) as caught:
            list(p.stream(self.provider("openai"), [{"role": "user", "content": "hi"}], opener=huge))
        self.assertIn("too large", str(caught.exception))

    def test_client_streams_text_and_keeps_whole_answers_for_schemas(self):
        from dai_ai import client, providers as p
        config = p.Config()
        config.providers["openai"] = self.provider("openai")
        p.record_consent(config, "openai")
        calls = []
        with mock.patch.object(p, "load", lambda path=None: config), \
                mock.patch.object(p, "stream", lambda provider, messages, max_tokens=512, opener=None: (calls.append("stream"), iter(["a", "b"]))[1]), \
                mock.patch.object(p, "chat", lambda provider, messages, schema=None, max_tokens=512, opener=None: (calls.append("chat"), '{"ok": 1}')[1]):
            self.assertEqual(list(client.chat([{"role": "user", "content": "hi"}])), ["a", "b"])
            self.assertEqual(list(client.chat([{"role": "user", "content": "hi"}], schema={"type": "object"})), ['{"ok": 1}'])
        self.assertEqual(calls, ["stream", "chat"])

        def half(provider, messages, max_tokens=512, opener=None):
            yield "first"
            raise p.ProviderError("cut")
        with mock.patch.object(p, "load", lambda path=None: config), mock.patch.object(p, "stream", half):
            out = []
            with self.assertRaises(client.AIUnavailable):      # no fallback after a piece was shown
                for piece in client.chat([{"role": "user", "content": "hi"}]):
                    out.append(piece)
        self.assertEqual(out, ["first"])


class PolicyTests(unittest.TestCase):
    """docs/PROVIDERS.md §4c: under a forbidding policy every task is local and use refuses."""

    def test_policy_file_routes_everything_local_and_use_refuses(self):
        from dai_ai import providers as p, providers_cli as cli
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(os.environ, {"DAI_ROOT": root, "LANG": "en_US.UTF-8"}):
            self.assertFalse(p.policy_forbids())
            config = p.Config()
            config.providers["anthropic"] = p.make("anthropic")
            config.providers["anthropic"].key = "k"
            p.record_consent(config, "anthropic")
            self.assertEqual(config.for_task("general").name, "anthropic")
            path = Path(root) / "etc/dai/policy-ai.env"
            path.parent.mkdir(parents=True)
            path.write_text("DAI_AI_PROVIDERS=forbidden\n")
            self.assertTrue(p.policy_forbids())
            self.assertIsNone(config.for_task("general"))
            self.assertEqual(p.where(config)["general"], "local")
            with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home, "XDG_CONFIG_HOME": home + "/.config"}):
                p.save(config)
                out = io.StringIO()
                with redirect_stdout(out), redirect_stderr(out):
                    self.assertEqual(cli.main(["use", "anthropic"], ask=lambda prompt: "yes"), 1)
                self.assertIn("policy", out.getvalue())
