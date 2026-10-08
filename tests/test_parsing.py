"""Parsing-layer tests (stdlib unittest)."""

import unittest

from devmate import diff_reader, reviewer

SAMPLE = """diff --git a/app.py b/app.py
index 111..222 100644
--- a/app.py
+++ b/app.py
@@ -10,3 +10,5 @@ def main():
     config = load_config()
+def load(path):
+    return open(path).read()
     run(config)
"""


class TestParseDiff(unittest.TestCase):
    def test_files_and_hunks(self):
        files = diff_reader.parse_diff(SAMPLE)
        self.assertEqual([f.path for f in files], ["app.py"])
        self.assertEqual(len(files[0].hunks), 1)
        added = files[0].added_lines
        self.assertEqual([t for _, t in added], ["def load(path):", "    return open(path).read()"])

    def test_changed_files(self):
        self.assertEqual(diff_reader.get_changed_files(SAMPLE), ["app.py"])

    def test_empty_diff(self):
        self.assertEqual(diff_reader.parse_diff(""), [])


class TestReviewerValidation(unittest.TestCase):
    def setUp(self):
        self.parsed = diff_reader.parse_diff(SAMPLE)

    def test_accept_valid(self):
        raw = ('{"findings": [{"issue": "unhandled IO", "category": "missing-error-handling",'
               ' "severity": "medium", "file": "app.py", "line": 11,'
               ' "why": "open can raise", "fix": "wrap in try"}]}')
        out = reviewer.parse_findings(raw, self.parsed)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].category, "missing-error-handling")

    def test_reject_unknown_file(self):
        raw = ('{"findings": [{"issue": "x", "category": "other", "severity": "low",'
               ' "file": "nope.py", "line": 1, "why": "w", "fix": "f"}]}')
        with self.assertRaises(ValueError):
            reviewer.parse_findings(raw, self.parsed)

    def test_reject_line_outside_hunk(self):
        raw = ('{"findings": [{"issue": "x", "category": "other", "severity": "low",'
               ' "file": "app.py", "line": 999, "why": "w", "fix": "f"}]}')
        with self.assertRaises(ValueError):
            reviewer.parse_findings(raw, self.parsed)

    def test_reject_bad_category(self):
        raw = ('{"findings": [{"issue": "x", "category": "nope", "severity": "low",'
               ' "file": "app.py", "line": 11, "why": "w", "fix": "f"}]}')
        with self.assertRaises(ValueError):
            reviewer.parse_findings(raw, self.parsed)


if __name__ == "__main__":
    unittest.main()
