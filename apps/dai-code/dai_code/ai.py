# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Prompts and local-AI calls (daid, task "code"). The model only returns text."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Iterable, Iterator

from .project import MAX_EDIT


class AIError(RuntimeError):
    pass


ChatFn = Callable[..., Iterable[str]]

SYSTEM = (
    "You are D.Ai Code, a careful senior software engineer inside D.Ai OS. You work on the user's project, "
    "locally. Be accurate and concise; if the provided files are not enough to answer, say what is missing "
    "instead of guessing. Never invent APIs. Reply in the language of the question (Hebrew or English); keep "
    "code, identifiers and file names in English."
)

EDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "maxLength": 600},
        "content": {"type": "string", "maxLength": MAX_EDIT * 2},
    },
    "required": ["summary", "content"],
}


def default_chat() -> ChatFn:
    try:
        from dai_ai.client import AIUnavailable, chat
    except ImportError as exc:
        raise AIError("the local AI is not installed") from exc

    def run(*args: Any, **kwargs: Any) -> Iterator[str]:
        try:
            yield from chat(*args, **kwargs)
        except AIUnavailable as exc:
            raise AIError(f"{exc} — install a model: dai-models install qwen2.5-coder-1.5b") from exc

    return run


def stream_text(chat: ChatFn, user: str, max_tokens: int = 1200) -> Iterator[str]:
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    yield from chat(messages, max_tokens=max_tokens, task="code")


def ask_prompt(question: str, tree: str, context: str) -> str:
    return (f"Project files:\n{tree}\n\nRelevant file contents:\n{context or '(no matching files)'}\n\n"
            f"Question: {question}")


def explain_prompt(rel: str, text: str, lines: tuple[int, int] | None) -> str:
    where = f" (lines {lines[0]}-{lines[1]})" if lines else ""
    return (f"Explain what this code from {rel}{where} does, step by step, then list any bugs or risks you see.\n"
            f"```\n{text}\n```")


def review_prompt(diff: str) -> str:
    return ("Review this diff like a strict reviewer: correctness bugs first, then security, then readability. "
            "Quote the lines you refer to. If it looks good, say so briefly.\n```diff\n" + diff + "\n```")


def commit_prompt(diff: str) -> str:
    return ("Write a Conventional Commits message for this staged diff: a subject line under 72 characters, "
            "a blank line, then a short body explaining why. Output only the message.\n```diff\n" + diff + "\n```")


def edit(rel: str, original: str, instruction: str, chat: ChatFn,
         progress: Callable[[str], None] | None = None) -> dict[str, str]:
    user = (f"File: {rel}\n```\n{original}\n```\n\nChange request: {instruction}\n\n"
            "Return JSON: summary (what you changed and why, one or two sentences) and content (the COMPLETE "
            "updated file). Change only what the request needs; keep everything else exactly as it is.")
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    parts: list[str] = []
    for piece in chat(messages, schema=EDIT_SCHEMA, max_tokens=4096, task="code"):
        parts.append(piece)
        if progress:
            progress("".join(parts))
    try:
        data = json.loads("".join(parts))
    except json.JSONDecodeError as exc:
        raise AIError("the AI reply was incomplete (file too long for the model?)") from exc
    content = data.get("content") if isinstance(data, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise AIError("the AI did not return the updated file")
    content = re.sub(r"^```[a-zA-Z0-9]*\n|\n```\s*$", "", content)
    if original.endswith("\n") and not content.endswith("\n"):
        content += "\n"
    return {"summary": str(data.get("summary", "")).strip(), "content": content}
