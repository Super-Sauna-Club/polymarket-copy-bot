"""TDD test for db.get_active_candidates().

`bot/auto_discovery.py::paper_follow_candidates` was only calling
`get_all_candidates("observing")`, so promoted candidates never got
paper-scanned — even though promoted is the stage AFTER observing
where we already decided the trader is interesting. Piff spotted this
on his side where denizz is promoted but has 0 new paper_trades.

Fix is a new helper `db.get_active_candidates()` that returns
observing + promoted candidates, excluding inactive.
"""
import unittest
from tests.conftest_helpers import setup_temp_db, teardown_temp_db


class TestActiveCandidates(unittest.TestCase):
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db

    def tearDown(self):
        teardown_temp_db(self.db_path)

    def _insert_candidate(self, address: str, status: str):
        """Insert a trader_candidates row with a given status."""
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO trader_candidates (address, username, profit_total, "
                "volume_total, winrate, markets_traded, status) "
                "VALUES (?, ?, 0, 0, 0, 0, ?)",
                (address, address[-4:], status),
            )

    def test_get_active_candidates_returns_observing_and_promoted(self):
        """Active = observing OR promoted. Inactive excluded."""
        self._insert_candidate("0xOBSERVING", "observing")
        self._insert_candidate("0xPROMOTED", "promoted")
        self._insert_candidate("0xINACTIVE", "inactive")

        active = self.db.get_active_candidates()
        addrs = {c["address"] for c in active}

        self.assertIn("0xOBSERVING", addrs)
        self.assertIn("0xPROMOTED", addrs)
        self.assertNotIn("0xINACTIVE", addrs)
        self.assertEqual(len(active), 2)


if __name__ == "__main__":
    unittest.main()
