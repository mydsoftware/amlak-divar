# -*- coding: utf-8 -*-
"""آزمون‌های پایه بدون نیاز به پنجره گرافیکی."""
import ast
from pathlib import Path
import unittest

APP = Path(__file__).resolve().parents[1] / "app.py"

class SmokeTests(unittest.TestCase):
    def test_app_syntax(self):
        ast.parse(APP.read_text(encoding="utf-8"))

    def test_database_schema_contains_campaigns_and_leads(self):
        source = APP.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS campaigns", source)
        self.assertIn("CREATE TABLE IF NOT EXISTS leads", source)
        self.assertIn("UNIQUE", source)

if __name__ == "__main__":
    unittest.main()
