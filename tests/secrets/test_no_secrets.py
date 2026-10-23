# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""No secret may be committed (docs/PRODUCTION.md §6): API keys, tokens, private keys, passwords in config.

Every tracked text file outside tests/ is scanned for the shapes real secrets have. Test fixtures live under
tests/ and use obviously fake values; this gate does not read them.
"""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATTERNS = {
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Anthropic key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    "OpenAI-style key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b"),
    "Slack token": re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY"),
    "password in config": re.compile(r"^\s*(?:password|passwd|secret|api[_-]?key)\s*[:=]\s*['\"]?[^'\"\s$<{]{8,}", re.I | re.M),
}
TEXT_SUFFIXES = {".py", ".sh", ".json", ".yml", ".yaml", ".md", ".html", ".css", ".js", ".conf", ".desktop", ".service",
                 ".timer", ".path", ".env", ".txt", ".xml", ".toml", ".ini", ".cfg", ".dway", ".po", ".pot", ".svg", ""}
# A literal password or key in a configuration file; code that reads one at run time is not that.
CONFIG_SUFFIXES = {".json", ".yml", ".yaml", ".conf", ".env", ".ini", ".cfg", ".toml", ".desktop", ".service", ".xml", ".txt", ".md"}
ALLOWED_LINES = (
    "password: 1234",           # documentation of what Clip refuses to keep
)


def tracked() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / line for line in out.splitlines() if line and "/tests/" not in f"/{line}" and not line.startswith("tests/")]


class NoSecretsTests(unittest.TestCase):
    def test_no_tracked_file_holds_a_secret(self):
        found = []
        for path in tracked():
            if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for name, pattern in PATTERNS.items():
                if name == "password in config" and path.suffix.lower() not in CONFIG_SUFFIXES:
                    continue
                for match in pattern.finditer(text):
                    line = text[text.rfind("\n", 0, match.start()) + 1:text.find("\n", match.end()) if text.find("\n", match.end()) != -1 else None]
                    if any(allowed in line for allowed in ALLOWED_LINES) or "example" in line.lower() or "placeholder" in line.lower():
                        continue
                    found.append(f"{path.relative_to(ROOT)}: {name}: {line.strip()[:80]}")
        self.assertEqual(found, [], "\n".join(found))

    def test_the_patterns_catch_real_shapes(self):
        self.assertTrue(PATTERNS["Anthropic key"].search("sk-ant-api03-" + "a" * 40))
        self.assertTrue(PATTERNS["private key block"].search("-----BEGIN OPENSSH PRIVATE KEY-----"))
        self.assertTrue(PATTERNS["password in config"].search("password = hunter2hunter2"))
        self.assertFalse(PATTERNS["password in config"].search("password = ${DB_PASSWORD}"))
