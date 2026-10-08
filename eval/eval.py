"""Tiny offline eval over eval/diffs/*.diff (stdlib only).

Each .diff may have a sibling .expected.json: {"categories": [...]}.
With --fake (default when Ollama is unreachable) a rule-based stand-in
produces findings so the pipeline (parse -> validate -> profile) is
exercised without a model. With --real, calls local Ollama.

Reports per-file catches vs expected + false positives on clean diffs.
Exit 0 only if every file meets its expectation.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from devmate import diff_reader, practice, profile, reviewer  # noqa: E402


def fake_call_for(diff_text: str):
    """Rule-based stand-in keyed off diff content (offline, deterministic)."""
    parsed = diff_reader.parse_diff(diff_text)
    ranges = {}
    for fd in parsed:
        for h in fd.hunks:
            ranges.setdefault(fd.path, []).append((h.new_start, h))
    def call(prompt: str) -> str:
        findings = []
        for fd in parsed:
            text = "\n".join(ln.text for h in fd.hunks for ln in h.lines if ln.kind == "+")
            line = fd.hunks[0].new_start + 1 if fd.hunks else 1
            if "except:" in text:
                findings.append({"issue": "bare except clause", "category": "broad-except",
                                 "severity": "medium", "file": fd.path, "line": line,
                                 "why": "hides real errors", "fix": "catch specific exceptions"})
            if "open(" in text and "try" not in diff_text:
                findings.append({"issue": "unhandled file IO", "category": "missing-error-handling",
                                 "severity": "medium", "file": fd.path, "line": line,
                                 "why": "open() can raise", "fix": "wrap in try/except"})
            if ".get(" not in text and "[" in text and "try" not in diff_text:
                pass  # keep rule set small and explicit
        if "GENERATE_EXERCISE" in prompt:
            return json.dumps({"exercise": "stub exercise", "criteria": ["criterion one"]})
        return json.dumps({"findings": findings})
    return call


def run(eval_dir: str, use_real: bool, model: str, host: str) -> int:
    diffs = sorted(glob.glob(os.path.join(eval_dir, "diffs", "*.diff")))
    if not diffs:
        print(f"no .diff files in {eval_dir}/diffs")
        return 2
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    profile.init_db(db)
    failures = 0
    print(f"{'file':40} {'expected':28} {'got':28} result")
    for path in diffs:
        name = os.path.basename(path)
        with open(path) as fh:
            diff_text = fh.read()
        exp_path = os.path.splitext(path)[0] + ".expected.json"
        expected = []
        if os.path.exists(exp_path):
            with open(exp_path) as fh:
                expected = json.load(fh).get("categories", [])
        if use_real:
            from devmate import ollama_client
            call = lambda p: ollama_client.generate(p, model=model, host=host)  # noqa: E731
        else:
            call = fake_call_for(diff_text)
        try:
            findings = reviewer.review_diff(diff_text, call=call)
            got = sorted({f.category for f in findings})
            profile.record_review(db, "eval", findings, message=name)
            ok = sorted(expected) == got if expected else (len(got) == 0)
        except Exception as exc:  # noqa: BLE001
            got, ok = [f"ERROR: {exc}"], False
        failures += 0 if ok else 1
        print(f"{name:40} {','.join(expected) or '(clean)':28} {','.join(got):28} {'PASS' if ok else 'FAIL'}")
    print(f"\nprofile after eval: {profile.profile_summary(db)}")
    print(f"{len(diffs) - failures}/{len(diffs)} passed")
    return 0 if failures == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--real", action="store_true", help="use local Ollama instead of fake")
    ap.add_argument("--model", default=os.environ.get("DEVMATE_MODEL", "qwen2.5-coder"))
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    args = ap.parse_args(argv)
    return run(args.dir, args.real, args.model, args.host)


if __name__ == "__main__":
    raise SystemExit(main())
