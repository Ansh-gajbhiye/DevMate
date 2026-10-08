"""Git diff reader (stdlib only).

Wraps `git diff` via subprocess and parses unified diffs into
structured hunks so prompts can cite real file:line locations.

tree-sitter is deliberately NOT required for the MVP (per
minimal-dependency rule). Function-name extraction uses cheap
regex heuristics; a tree-sitter upgrade can replace
`guess_changed_symbols` without changing the return shape.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field


class GitError(RuntimeError):
    pass


def _run_git(args: list[str], cwd: str | None = None) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=cwd or os.getcwd(),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise GitError("`git` binary not found on PATH.") from exc
    if out.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {out.stderr.strip()[:300]}")
    return out.stdout


def get_staged_diff(repo: str | None = None) -> str:
    return _run_git(["diff", "--staged", "--no-color", "--no-ext-diff"], cwd=repo)


def get_working_diff(repo: str | None = None) -> str:
    return _run_git(["diff", "--no-color", "--no-ext-diff"], cwd=repo)


def get_range_diff(from_ref: str, to_ref: str = "HEAD", repo: str | None = None) -> str:
    return _run_git(
        ["diff", f"{from_ref}..{to_ref}", "--no-color", "--no-ext-diff"], cwd=repo
    )


def get_changed_files(diff_text: str) -> list[str]:
    files: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            files.append(line[6:])
    return files


@dataclass
class HunkLine:
    kind: str  # ' ' | '+' | '-'
    new_lineno: int | None
    text: str


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[HunkLine] = field(default_factory=list)


@dataclass
class FileDiff:
    path: str
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def added_lines(self) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        for h in self.hunks:
            for ln in h.lines:
                if ln.kind == "+" and ln.new_lineno is not None:
                    out.append((ln.new_lineno, ln.text))
        return out


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_FUNC_RE = re.compile(r"^\s*(?:def|function|fn|func|class)\s+([A-Za-z_][\w]*)")


def parse_diff(diff_text: str) -> list[FileDiff]:
    """Parse a unified diff into FileDiff objects."""
    files: list[FileDiff] = []
    current: FileDiff | None = None
    hunk: Hunk | None = None
    new_lineno = 0
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git"):
            current = None
            hunk = None
        elif raw.startswith("+++ b/"):
            path = raw[6:]
            # /dev/null means deleted file; keep path from --- line instead
            current = FileDiff(path=path)
            files.append(current)
            hunk = None
        elif raw.startswith("--- a/") and current is None:
            # new file case where +++ is /dev/null handled below
            pass
        elif raw.startswith("+++ /dev/null"):
            if files:
                files.pop()  # deleted file placeholder; re-add on --- line is complex
        elif (m := _HUNK_RE.match(raw)):
            if current is None:
                continue
            old_start = int(m.group(1))
            old_count = int(m.group(2) or "1")
            new_start = int(m.group(3))
            new_count = int(m.group(4) or "1")
            hunk = Hunk(old_start, old_count, new_start, new_count)
            current.hunks.append(hunk)
            new_lineno = new_start
        elif hunk is not None and current is not None:
            if raw.startswith("+") and not raw.startswith("+++"):
                hunk.lines.append(HunkLine("+", new_lineno, raw[1:]))
                new_lineno += 1
            elif raw.startswith("-") and not raw.startswith("---"):
                hunk.lines.append(HunkLine("-", None, raw[1:]))
            elif raw.startswith(" "):
                hunk.lines.append(HunkLine(" ", new_lineno, raw[1:]))
                new_lineno += 1
            elif raw.startswith("\\"):
                pass  # "\ No newline" marker
            else:
                pass
    # Drop entries with no hunks (e.g. binary / mode-only changes)
    return [f for f in files if f.hunks]


def guess_changed_symbols(file_diffs: list[FileDiff]) -> list[str]:
    """Heuristic changed-symbol list (regex, no tree-sitter)."""
    syms: list[str] = []
    for fd in file_diffs:
        for h in fd.hunks:
            for ln in h.lines:
                if ln.kind == "+":
                    m = _FUNC_RE.match(ln.text)
                    if m:
                        syms.append(f"{fd.path}:{m.group(1)}")
    return syms


def deterministic_flags(file_diffs: list[FileDiff], raw: str) -> dict:
    files = [f.path for f in file_diffs]
    added = sum(1 for f in file_diffs for h in f.hunks for ln in h.lines if ln.kind == "+")
    removed = sum(1 for f in file_diffs for h in f.hunks for ln in h.lines if ln.kind == "-")
    has_test = any("test" in p.lower() for p in files)
    return {
        "files": files,
        "num_files": len(files),
        "added": added,
        "removed": removed,
        "has_test_changes": has_test,
        "symbols": guess_changed_symbols(file_diffs),
    }


def build_context(diff_text: str, max_chars: int = 12000) -> tuple[str, bool]:
    """Truncate diff for prompt context. Returns (text, was_truncated)."""
    if len(diff_text) <= max_chars:
        return diff_text, False
    cut = diff_text[:max_chars]
    # avoid splitting mid-line
    cut = cut.rsplit("\n", 1)[0]
    return cut + "\n... [truncated: diff exceeds budget]\n", True
