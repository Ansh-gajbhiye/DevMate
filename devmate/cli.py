"""DevMate CLI (MVP, stdlib only).

Usage:
  python -m devmate.cli commit-msg [--staged|--working|--diff-file P|--range A..B]
  python -m devmate.cli review     [same diff sources] [--strict] [--no-record]
  python -m devmate.cli profile show
  python -m devmate.cli practice [--limit N]

Diff sources default to --staged. All model calls go to local Ollama;
failures exit non-zero with the Ollama hint (fail closed).
"""

from __future__ import annotations

import argparse
import os
import sys

from . import commit_msg, diff_reader, ollama_client, practice, profile, reviewer


def _load_diff(args) -> str:
    if args.diff_file:
        with open(args.diff_file) as fh:
            return fh.read()
    if args.range:
        if ".." in args.range:
            a, b = args.range.split("..", 1)
        else:
            a, b = args.range, "HEAD"
        return diff_reader.get_range_diff(a, b or "HEAD", repo=args.repo)
    if args.working:
        return diff_reader.get_working_diff(repo=args.repo)
    return diff_reader.get_staged_diff(repo=args.repo)


def _model_call(model: str, host: str):
    return lambda prompt: ollama_client.generate(prompt, model=model, host=host)


def cmd_commit_msg(args) -> int:
    try:
        diff = _load_diff(args)
    except diff_reader.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        msg = commit_msg.generate_commit_message(diff, call=_model_call(args.model, args.host))
    except (ValueError, ollama_client.OllamaError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(msg)
    return 0


def cmd_review(args) -> int:
    try:
        diff = _load_diff(args)
    except diff_reader.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not diff.strip():
        print("No changes to review.")
        return 0
    db = profile.connect(args.db)
    summary = profile.profile_summary(db)
    try:
        findings = reviewer.review_diff(diff, profile_summary=summary, call=_model_call(args.model, args.host))
    except (ValueError, ollama_client.OllamaError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not args.no_record:
        repo = os.path.abspath(args.repo or os.getcwd())
        profile.record_review(db, repo, findings, message="")
    if not findings:
        print("Clean. No issues found.")
        return 0
    for f in findings:
        print(f"[{f.severity}] {f.file}:{f.line} {f.issue} ({f.category})")
        print(f"  why: {f.why}")
        print(f"  fix: {f.fix}")
    top = profile.top_weaknesses(db, 1)
    if top and top[0][1] >= 3:
        print(f"\nRecurring weakness: {top[0][0]} x{top[0][1]} — try: python -m devmate.cli practice")
    if args.strict and any(f.severity == "high" for f in findings):
        return 1
    return 0


def cmd_profile(args) -> int:
    db = profile.connect(args.db)
    top = profile.top_weaknesses(db, args.limit)
    if not top:
        print("No history yet.")
        return 0
    for cat, count, last in top:
        print(f"{cat}: x{count} (last {last})")
    return 0


def cmd_practice(args) -> int:
    db = profile.connect(args.db)
    try:
        ex = practice.generate_for_weakest(db, call=_model_call(args.model, args.host))
    except (ValueError, ollama_client.OllamaError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if ex is None:
        print("No history yet — run `review` first.")
        return 0
    print(f"Weakness: {ex.category}\n")
    print(ex.prompt + "\n")
    print("Acceptance criteria:")
    for c in ex.criteria:
        print(f"- {c}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="devmate", description="Local-first developer assistant (MVP).")
    p.add_argument("--model", default=os.environ.get("DEVMATE_MODEL", ollama_client.DEFAULT_MODEL))
    p.add_argument("--host", default=os.environ.get("OLLAMA_HOST", ollama_client.DEFAULT_HOST))
    p.add_argument("--db", default=None, help="SQLite path (default ~/.devmate/devmate.db)")
    p.add_argument("--repo", default=None, help="Repo path (default cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_diff(a):
        a.add_argument("--diff-file", default=None)
        a.add_argument("--range", default=None, help="A..B or A (to HEAD)")
        a.add_argument("--working", action="store_true", help="use unstaged diff (default staged)")

    c = sub.add_parser("commit-msg", help="Generate a commit message from a diff.")
    add_diff(c)
    c.set_defaults(func=cmd_commit_msg)

    r = sub.add_parser("review", help="Review a diff with explanations.")
    add_diff(r)
    r.add_argument("--strict", action="store_true", help="exit 1 if any high-severity finding")
    r.add_argument("--no-record", action="store_true", help="skip SQLite recording")
    r.set_defaults(func=cmd_review)

    pr = sub.add_parser("profile", help="Show growth profile.")
    pr.add_argument("what", choices=["show"])
    pr.add_argument("--limit", type=int, default=10)
    pr.set_defaults(func=lambda a: cmd_profile(a))

    ex = sub.add_parser("practice", help="Generate an exercise for the top weakness.")
    ex.add_argument("--limit", type=int, default=3)
    ex.set_defaults(func=cmd_practice)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
