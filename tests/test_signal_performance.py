import unittest
from tests.conftest_helpers import setup_temp_db, teardown_temp_db, insert_copy_trade


class TestSignalPerformance(unittest.TestCase):
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db
        # The copy_trades table has an FK to wallets.address; seed one.
        with db.get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO wallets (address, username) VALUES (?, ?)",
                ("0xdead", "trader1"),
            )
        # 3 winning closed trades, 2 losing closed trades
        for i in range(3):
            insert_copy_trade(
                db, pnl_realized=+2.0, current_price=0.95,
                actual_entry_price=0.5, entry_price=0.5,
                status="closed", condition_id="cid-win-%d" % i,
            )
        for i in range(2):
            insert_copy_trade(
                db, pnl_realized=-1.5, current_price=0.05,
                actual_entry_price=0.5, entry_price=0.5,
                status="closed", condition_id="cid-lose-%d" % i,
            )

    def tearDown(self):
        teardown_temp_db(self.db_path)

    def test_signal_performance_counts_real_wins_and_losses(self):
        from bot import clv_tracker
        clv_tracker.update_clv_for_closed_trades()
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT wins, losses, trades_count FROM signal_performance "
                "WHERE signal_type='clv_tracking'"
            ).fetchone()
        self.assertEqual(row["wins"], 3)
        self.assertEqual(row["losses"], 2)
        self.assertEqual(row["trades_count"], 5)


if __name__ == "__main__":
    unittest.main()
