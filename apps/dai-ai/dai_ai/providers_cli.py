# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-models provider …: external AI providers with your own key (docs/PROVIDERS.md §3).

  dai-models provider list
  dai-models provider add NAME [--kind openai|anthropic|gemini] [--url URL] [--model MODEL]
  dai-models provider key NAME            (the key is read from the input, never from the arguments)
  dai-models provider use NAME [--tasks code,general] [--yes]   |   use local
  dai-models provider test NAME
  dai-models provider remove NAME
  dai-models provider fallback on|off
"""
from __future__ import annotations

import getpass
import sys
from typing import Callable

from dai_i18n import pick, ui_lang

from . import providers


def _option(args: list[str], name: str) -> str:
    if name in args and args.index(name) + 1 < len(args):
        return args[args.index(name) + 1]
    return ""


def _read_key(prompt: str) -> str:
    """From the terminal without echo; from standard input when it is a pipe (a script, the VM check)."""
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    return sys.stdin.readline()


def main(args: list[str], read_key: Callable[[str], str] = _read_key, ask: Callable[[str], str] = input,
         opener=None) -> int:
    lang = ui_lang()
    say = lambda en, he, **kw: pick(lang, en, he).format(**kw)  # noqa: E731
    config = providers.load()
    sub, rest = (args[0] if args else "list"), args[1:]
    name = rest[0] if rest and not rest[0].startswith("--") else ""
    try:
        if sub == "list":
            print(say("active: {who}", "פעיל: {who}", who=config.active or "local (Diamond on this computer)"))
            for provider in config.providers.values():
                p = provider.public()
                mark = "*" if provider.name == config.active else " "
                consent = p["consented"] or say("no consent yet", "עדיין בלי הסכמה")
                print(f"{mark} {p['name']:12} {p['kind']:9} {p['model']:28} {','.join(p['tasks']):13} key {p['key']:10} {consent}")
            known = ", ".join(k for k in providers.KNOWN if k not in config.providers)
            if known:
                print(say("known, not set up: {known} (dai-models provider add NAME)", "מוכרים, לא מוגדרים: {known} (dai-models provider add NAME)", known=known))
            return 0
        if sub == "add" and name:
            provider = providers.make(name, _option(rest, "--kind"), _option(rest, "--url"), _option(rest, "--model"))
            old = config.providers.get(name)
            if old:
                provider.key, provider.tasks, provider.consented = old.key, old.tasks, old.consented
            config.providers[name] = provider
            providers.save(config)
            print(say("✓ {name}: {model} at {url}. Next: dai-models provider key {name}",
                      "✓ {name}: {model} ב־{url}. הבא: dai-models provider key {name}",
                      name=name, model=provider.model, url=provider.base_url))
            return 0
        if sub == "key" and name:
            provider = config.providers.get(name)
            if provider is None:
                raise providers.ProviderError(say("unknown provider {name} (dai-models provider add {name})", "ספק לא מוכר {name} (dai-models provider add {name})", name=name))
            key = read_key(say("API key for {name} (not shown): ", "מפתח API ל־{name} (לא מוצג): ", name=name)).strip()
            if not key or any(ch.isspace() for ch in key):
                raise providers.ProviderError(say("the key is empty or has spaces", "המפתח ריק או מכיל רווחים"))
            provider.key = key
            providers.save(config)
            print(say("✓ key saved for {name} ({masked}), in your config only (0600).", "✓ המפתח של {name} נשמר ({masked}), רק בהגדרות שלך (0600).",
                      name=name, masked=provider.masked_key()))
            return 0
        if sub == "use" and name:
            if name == "local":
                config.active = ""
                providers.save(config)
                print(say("✓ Everything runs on this computer again.", "✓ הכול רץ שוב במחשב הזה."))
                return 0
            provider = config.providers.get(name)
            if provider is None:
                raise providers.ProviderError(say("unknown provider {name}", "ספק לא מוכר {name}", name=name))
            tasks = tuple(t for t in _option(rest, "--tasks").split(",") if t in providers.TASKS) or provider.tasks
            provider.tasks = tasks
            if not provider.consented:
                print(providers.consent_text(provider, lang))
                answer = "yes" if "--yes" in rest else ask(say('Type "yes" to agree: ', 'הקלידו "כן" כדי להסכים: ')).strip().casefold()
                if answer not in ("yes", "כן"):
                    print(say("Not agreed. Nothing was changed.", "לא אושר. לא בוצע שינוי."))
                    return 1
                providers.record_consent(config, name)
            config.active = name
            providers.save(config)
            print(say("✓ {name} answers for: {tasks}. Speech stays local. Back: dai-models provider use local",
                      "✓ {name} עונה עבור: {tasks}. דיבור נשאר מקומי. חזרה: dai-models provider use local",
                      name=name, tasks=", ".join(tasks)))
            return 0
        if sub == "test" and name:
            provider = config.providers.get(name)
            if provider is None:
                raise providers.ProviderError(say("unknown provider {name}", "ספק לא מוכר {name}", name=name))
            reply = providers.chat(provider, [{"role": "user", "content": "Reply with the single word: ok"}], max_tokens=16,
                                   **({"opener": opener} if opener else {}))
            print(say("✓ {name} answered: {reply}", "✓ {name} ענה: {reply}", name=name, reply=reply.strip()[:60]))
            return 0
        if sub == "remove" and name:
            if name not in config.providers:
                raise providers.ProviderError(say("unknown provider {name}", "ספק לא מוכר {name}", name=name))
            del config.providers[name]
            if config.active == name:
                config.active = ""
            providers.save(config)
            print(say("✓ {name} and its key were removed.", "✓ {name} והמפתח שלו הוסרו.", name=name))
            return 0
        if sub == "fallback" and name in ("on", "off"):
            config.fallback = name == "on"
            providers.save(config)
            print("✓")
            return 0
    except providers.ProviderError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(__doc__.strip(), file=sys.stderr)
    return 2
