import unittest
from tests.conftest_helpers import setup_temp_db, teardown_temp_db


class TestFeedbackLoop(unittest.TestCase):
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db
        # Insert a trade_scores row
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO trade_scores (condition_id, trader_name, side, "
                "entry_price, market_question, score_total, action) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("cid-xyz", "trader1", "YES", 0.45, "Will X?", 75, "EXECUTE")
            )

    def tearDown(self):
        teardown_temp_db(self.db_path)

    def test_update_sets_outcome_pnl(self):
        updated = self.db.update_trade_score_outcome("cid-xyz", "trader1", 2.34)
        self.assertEqual(updated, 1)
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT outcome_pnl FROM trade_scores WHERE condition_id='cid-xyz'"
            ).fetchone()
        self.assertAlmostEqual(row["outcome_pnl"], 2.34, places=4)

    def test_update_is_idempotent_skips_already_set(self):
        # First call sets it.
        self.db.update_trade_score_outcome("cid-xyz", "trader1", 1.00)
        # Second call with different pnl must NOT overwrite (outcome already recorded).
        updated = self.db.update_trade_score_outcome("cid-xyz", "trader1", 999.0)
        self.assertEqual(updated, 0)
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT outcome_pnl FROM trade_scores WHERE condition_id='cid-xyz'"
            ).fetchone()
        self.assertAlmostEqual(row["outcome_pnl"], 1.00, places=4)

    def test_update_matches_newest_when_multiple(self):
        # Insert an older row with the same condition_id + trader.
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO trade_scores (condition_id, trader_name, side, "
                "entry_price, market_question, score_total, action, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now','-1 day'))",
                ("cid-xyz", "trader1", "YES", 0.5, "Will X?", 60, "EXECUTE")
            )
        self.db.update_trade_score_outcome("cid-xyz", "trader1", 3.14)
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT score_total, outcome_pnl FROM trade_scores "
                "WHERE condition_id='cid-xyz' ORDER BY id"
            ).fetchall()
        # Only the newest (score_total=75, inserted in setUp, id=1) should have
        # outcome_pnl set — the older row (-1 day) is outside the 120-minute window.
        self.assertAlmostEqual(rows[0]["outcome_pnl"], 3.14, places=4)
        self.assertIsNone(rows[1]["outcome_pnl"])


if __name__ == "__main__":
    unittest.main()
