"""Diff reviewer (MVP).

Returns structured findings: {issue, category, severity, file, line,
why, fix}. Validates schema + grounding (file must be in the diff,
line must fall inside a changed hunk) and retries once on failure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import diff_reader, ollama_client

CATEGORIES = (
    "missing-error-handling",
    "no-test-coverage",
    "broad-except",
    "unclear-naming",
    "missing-null-check",
    "other",
)

SEVERITIES = ("low", "medium", "high")


@dataclass
class Finding:
    issue: str
    category: str
    severity: str
    file: str
    line: int
    why: str
    fix: str


def build_prompt(diff_text: str, flags: dict, profile_summary: str = "") -> str:
    files = ", ".join(flags.get("files", [])) or "(unknown)"
    profile = profile_summary or "No history yet."
    return (
        "Review the diff below as a senior engineer. Be specific, prefer "
        "fewer high-confidence findings over many guesses.\n"
        f"Changed files: {files}\n"
        f"Developer weakness history: {profile}\n"
        "Categories allowed: " + ", ".join(CATEGORIES) + ".\n"
        "Severities allowed: low, medium, high.\n"
        "Rules: every finding MUST cite a real file from Changed files and "
        "a line number inside a + hunk. Explain WHY it matters and give a "
        "minimal fix. No generic advice.\n"
        'Reply with JSON ONLY: {"findings": ['
        '{"issue": "...", "category": "...", "severity": "...", '
        '"file": "...", "line": 123, "why": "...", "fix": "..."}]}. '
        'Empty list if clean: {"findings": []}.\n'
        "Diff:\n" + diff_text
    )


def _line_ranges(parsed: list[diff_reader.FileDiff]) -> dict[str, list[tuple[int, int]]]:
    ranges: dict[str, list[tuple[int, int]]] = {}
    for fd in parsed:
        rs = ranges.setdefault(fd.path, [])
        for h in fd.hunks:
            rs.append((h.new_start, h.new_start + max(h.new_count, 1) - 1))
    return ranges


def parse_findings(raw: str, parsed: list[diff_reader.FileDiff]) -> list[Finding]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not JSON: {exc}") from exc
    if not isinstance(data, dict) or "findings" not in data:
        raise ValueError("missing 'findings' key")
    items = data["findings"]
    if not isinstance(items, list):
        raise ValueError("'findings' must be a list")
    known = _line_ranges(parsed)
    out: list[Finding] = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise ValueError(f"finding {i} not an object")
        for key in ("issue", "category", "severity", "file", "line", "why", "fix"):
            if key not in it:
                raise ValueError(f"finding {i} missing '{key}'")
        category = str(it["category"])
        severity = str(it["severity"]).lower()
        path = str(it["file"])
        line = int(it["line"])
        if category not in CATEGORIES:
            raise ValueError(f"finding {i} bad category {category!r}")
        if severity not in SEVERITIES:
            raise ValueError(f"finding {i} bad severity {severity!r}")
        if path not in known:
            raise ValueError(f"finding {i} unknown file {path!r}")
        if line < 1 or not any(a <= line <= b for a, b in known[path]):
            raise ValueError(f"finding {i} line {line} outside changed hunks of {path}")
        for key in ("issue", "why", "fix"):
            if not str(it[key]).strip():
                raise ValueError(f"finding {i} empty '{key}'")
        out.append(
            Finding(
                issue=str(it["issue"]).strip(),
                category=category,
                severity=severity,
                file=path,
                line=line,
                why=str(it["why"]).strip(),
                fix=str(it["fix"]).strip(),
            )
        )
    return out


def review_diff(
    diff_text: str,
    profile_summary: str = "",
    call=ollama_client.generate,
    max_chars: int = 12000,
) -> list[Finding]:
    if not diff_text.strip():
        raise ValueError("empty diff: nothing to review?")
    ctx, _ = diff_reader.build_context(diff_text, max_chars)
    parsed = diff_reader.parse_diff(diff_text)
    if not parsed:
        return []
    flags = diff_reader.deterministic_flags(parsed, diff_text)
    prompt = build_prompt(ctx, flags, profile_summary)
    last_err: Exception | None = None
    for _ in range(2):
        try:
            return parse_findings(call(prompt), parsed)
        except (ValueError, TypeError) as exc:
            last_err = exc
            prompt += "\nPrevious reply failed validation. Reply JSON only, grounded file:line."
    raise ValueError(f"model did not return valid review JSON: {last_err}")
