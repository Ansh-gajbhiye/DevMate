"""Commit-message generator (MVP).

Model does the summarization; this module builds the constrained
prompt and validates the result. Fails closed if the model is
unavailable or returns invalid JSON.
"""

from __future__ import annotations

import json

from . import diff_reader, ollama_client

MAX_SUBJECT = 72


def build_prompt(diff_text: str, flags: dict) -> str:
    files = ", ".join(flags.get("files", [])) or "(unknown)"
    return (
        "Write a conventional commit message for the diff below.\n"
        "Rules: <type>(<scope>): <subject> using one of "
        "feat, fix, docs, refactor, test, chore. Subject imperative, "
        f"<= {MAX_SUBJECT} chars, no period. Then a blank line and 1-3 "
        "bullet lines explaining what/why if the change is non-trivial.\n"
        f"Changed files: {files}\n"
        "Reply with JSON ONLY: {\"message\": \"...\"}.\n"
        "Diff:\n" + diff_text
    )


def _validate(message: str) -> str:
    message = message.strip().strip("`").strip()
    if not message:
        raise ValueError("empty commit message")
    subject = message.splitlines()[0].strip()
    if len(subject) > 100:
        raise ValueError(f"subject too long ({len(subject)} chars)")
    return message


def generate_commit_message(
    diff_text: str,
    call=ollama_client.generate,
    max_chars: int = 12000,
) -> str:
    if not diff_text.strip():
        raise ValueError("empty diff: nothing staged?")
    ctx, _ = diff_reader.build_context(diff_text, max_chars)
    parsed = diff_reader.parse_diff(diff_text)
    flags = diff_reader.deterministic_flags(parsed, diff_text)
    prompt = build_prompt(ctx, flags)
    last_err: Exception | None = None
    for _ in range(2):  # initial + 1 retry
        try:
            raw = call(prompt)
            data = json.loads(raw)
            return _validate(str(data["message"]))
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            last_err = exc
            prompt = prompt + "\nPrevious reply was invalid JSON/schema. Reply JSON only."
    raise ValueError(f"model did not return a valid commit message: {last_err}")
