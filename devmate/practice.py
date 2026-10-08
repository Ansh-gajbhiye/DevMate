"""Practice-exercise generator (MVP).

Targets the top weakness categories from the growth profile.
Model drafts one small exercise + acceptance criteria; this module
validates the schema and persists the exercise row.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from . import ollama_client, profile


@dataclass
class Exercise:
    id: int
    category: str
    prompt: str
    criteria: list[str]


def past_examples(db: sqlite3.Connection, category: str, limit: int = 3) -> list[str]:
    rows = db.execute(
        "SELECT note, file, line FROM findings WHERE category=? ORDER BY id DESC LIMIT ?",
        (category, limit),
    ).fetchall()
    return [f"{r['file']}:{r['line']} {r['note']}" for r in rows if r["note"]]


def build_prompt(category: str, examples: list[str]) -> str:
    ex = "\n".join(f"- {e}" for e in examples) or "- (no examples yet)"
    return (
        "Write ONE small Python practice exercise (15-30 min) targeting "
        f"the weakness '{category}'.\n"
        "Past mistakes by this developer:\n" + ex + "\n"
        "Keep it minimal with starter code and 2-4 acceptance criteria.\n"
        'Reply with JSON ONLY: {"exercise": "...", "criteria": ["..."]}.'
    )


def parse_exercise(raw: str) -> tuple[str, list[str]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not JSON: {exc}") from exc
    text, criteria = data.get("exercise", ""), data.get("criteria", [])
    if not isinstance(text, str) or not text.strip():
        raise ValueError("missing/empty 'exercise'")
    if not isinstance(criteria, list) or not 1 <= len(criteria) <= 5:
        raise ValueError("'criteria' must be a list of 1-5 strings")
    crit = [str(c).strip() for c in criteria]
    if any(not c for c in crit):
        raise ValueError("empty criterion")
    return text.strip(), crit


def generate_exercise(
    category: str, examples: list[str], call=ollama_client.generate
) -> tuple[str, list[str]]:
    prompt = build_prompt(category, examples)
    last_err: Exception | None = None
    for _ in range(2):
        try:
            return parse_exercise(call(prompt))
        except (ValueError, TypeError, KeyError) as exc:
            last_err = exc
            prompt += "\nPrevious reply was invalid. Reply JSON only."
    raise ValueError(f"model did not return a valid exercise: {last_err}")


def generate_for_weakest(
    db: sqlite3.Connection, call=ollama_client.generate
) -> Exercise | None:
    top = profile.top_weaknesses(db, 1)
    if not top:
        return None
    category = top[0][0]
    text, criteria = generate_exercise(category, past_examples(db, category), call=call)
    cur = db.execute(
        "INSERT INTO exercises(category, prompt, status, created_at)"
        " VALUES(?,?, 'open', datetime('now'))",
        (category, text),
    )
    db.commit()
    return Exercise(int(cur.lastrowid), category, text, criteria)
