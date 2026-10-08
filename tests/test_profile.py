"""Database-layer tests (stdlib unittest, in-memory SQLite)."""

import sqlite3
import unittest
from types import SimpleNamespace

from devmate import practice, profile

F = SimpleNamespace(category="missing-error-handling", severity="medium",
                    file="a.py", line=3, issue="unhandled open")


class TestProfile(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        profile.init_db(self.db)

    def tearDown(self):
        self.db.close()

    def test_record_and_summary(self):
        profile.record_review(self.db, "demo", [F], message="m")
        profile.record_review(self.db, "demo", [F], message="m2")
        self.assertEqual(profile.profile_summary(self.db), "missing-error-handling x2")

    def test_empty_summary(self):
        self.assertEqual(profile.profile_summary(self.db), "No history yet.")

    def test_top_ordering(self):
        other = SimpleNamespace(category="broad-except", severity="low",
                                file="b.py", line=1, issue="bare except")
        profile.record_review(self.db, "d", [other])
        profile.record_review(self.db, "d", [F, F])
        top = profile.top_weaknesses(self.db, 1)
        self.assertEqual(top[0][0], "missing-error-handling")
        self.assertEqual(top[0][1], 2)

    def test_exercise_roundtrip(self):
        profile.record_review(self.db, "d", [F])
        ex = practice.generate_for_weakest(
            self.db,
            call=lambda p: '{"exercise": "Add try/except", "criteria": ["handles OSError"]}',
        )
        self.assertIsNotNone(ex)
        self.assertEqual(ex.category, "missing-error-handling")
        row = self.db.execute("SELECT COUNT(*) c FROM exercises").fetchone()
        self.assertEqual(row["c"], 1)


if __name__ == "__main__":
    unittest.main()
