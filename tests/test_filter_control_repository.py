from __future__ import annotations

import sqlite3
import unittest

from airmonitor.database import init_db
from airmonitor.database.repositories import FilterControlRepository


class FilterControlRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.repo = FilterControlRepository(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_initializes_default_filter_state(self):
        record = self.repo.get("bento")

        self.assertEqual(record.filter_id, "bento")
        self.assertEqual(record.manual_mode, "auto")
        self.assertEqual(record.automation_request, "unknown")
        self.assertEqual(record.actual_state, "unknown")

    def test_persists_manual_mode(self):
        record = self.repo.set_manual_mode("levoit", "on")

        self.assertEqual(record.manual_mode, "on")
        self.assertEqual(self.repo.get("levoit").manual_mode, "on")

    def test_updates_resolved_state(self):
        record = self.repo.update(
            "bento",
            automation_request="on",
            actual_state="off",
            effective_state="on",
            reason="printing ABS",
        )

        self.assertEqual(record.automation_request, "on")
        self.assertEqual(record.actual_state, "off")
        self.assertEqual(record.effective_state, "on")
        self.assertEqual(record.reason, "printing ABS")


if __name__ == "__main__":
    unittest.main()
