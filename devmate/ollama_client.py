"""Minimal Ollama client (stdlib only).

Talks to a local Ollama daemon (default http://localhost:11434).
No third-party dependencies: uses urllib + json.

The client is intentionally thin. Prompting, schema validation and
retry live in the caller modules (commit_msg, reviewer, practice).
If Ollama is not running, all functions raise OllamaError with an
actionable message instead of returning template output.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class OllamaError(RuntimeError):
    pass


DEFAULT_MODEL = os.environ.get("DEVMATE_MODEL", "qwen2.5-coder")
DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def _endpoint(host: str) -> str:
    return host.rstrip("/") + "/api/generate"


def generate(
    prompt: str,
    model: str = DEFAULT_MODEL,
    host: str = DEFAULT_HOST,
    timeout: int = 120,
    options: dict | None = None,
    request_json: bool = True,
) -> str:
    """Call Ollama /api/generate (non-streaming) and return response text.

    Raises OllamaError on connection problems, non-200 status, or
    malformed responses.
    """
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if request_json:
        payload["format"] = "json"
    if options:
        payload["options"] = options
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _endpoint(host),
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise OllamaError(
            f"Cannot reach Ollama at {host}. Is `ollama serve` running "
            f"and model '{model}' pulled? ({exc})"
        ) from exc
    except TimeoutError as exc:
        raise OllamaError(f"Ollama request timed out after {timeout}s.") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise OllamaError(f"Ollama returned non-JSON: {body[:200]!r}") from exc
    if "response" not in parsed:
        raise OllamaError(f"Unexpected Ollama response keys: {sorted(parsed)}")
    return parsed["response"]
