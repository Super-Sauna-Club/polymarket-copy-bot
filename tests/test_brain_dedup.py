import unittest
from unittest.mock import patch
from tests.conftest_helpers import setup_temp_db, teardown_temp_db, insert_copy_trade


class TestBrainDedup(unittest.TestCase):
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db
        # The copy_trades table has an FK to wallets.address; seed one.
        with db.get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO wallets (address, username) VALUES (?, ?)",
                ("0xdead", "sovereign2013"),
            )
        # 5 losing trades all in the same trader+category pair.
        # With dedup, brain should write exactly ONE BLACKLIST_CATEGORY
        # brain_decisions row, not 5.
        for i in range(5):
            insert_copy_trade(
                db,
                market_question="Will NHL game %d end in OT?" % i,
                category="nhl",
                wallet_username="sovereign2013",
                pnl_realized=-2.0,
                actual_size=5.0,
                status="closed",
                condition_id="cid-%d" % i,
            )
        # _classify_losses filters on closed_at >= now-7d, and the category
        # win-rate query counts all closed trades for (trader, category).
        # Set closed_at explicitly so the losses are visible to brain.
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE copy_trades SET closed_at = datetime('now','localtime')"
            )

    def tearDown(self):
        teardown_temp_db(self.db_path)

    def test_bad_category_losses_log_once(self):
        # Stub settings so brain doesn't touch the real settings.env, and
        # stub get_trader_rolling_pnl to a non-negative PnL so the losses
        # are classified as BAD_CATEGORY (not BAD_TRADER — a trader with
        # negative rolling PnL short-circuits before the category check).
        fake_stats = {"total_pnl": 0.0, "cnt": 5, "wins": 0, "losses": 5,
                      "verified_count": 0, "source": "test"}
        with patch("bot.brain._read_settings", return_value="CATEGORY_BLACKLIST_MAP=\n"), \
             patch("bot.brain._write_settings") as mock_write, \
             patch("database.db.get_trader_rolling_pnl", return_value=fake_stats):
            from bot import brain
            brain._classify_losses()
            # 5 identical losses --> at most ONE settings write.
            self.assertLessEqual(mock_write.call_count, 1)
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM brain_decisions WHERE action='BLACKLIST_CATEGORY'"
            ).fetchone()
        # Exactly one row for one unique (trader, category) pair.
        self.assertEqual(row[0], 1)

    def test_already_blacklisted_early_return(self):
        # Pair is already in the CATEGORY_BLACKLIST_MAP --> helper must return
        # without writing or logging anything.
        fake_stats = {"total_pnl": 0.0, "cnt": 5, "wins": 0, "losses": 5,
                      "verified_count": 0, "source": "test"}
        with patch("bot.brain._read_settings",
                   return_value="CATEGORY_BLACKLIST_MAP=sovereign2013:nhl\n"), \
             patch("bot.brain._write_settings") as mock_write, \
             patch("database.db.get_trader_rolling_pnl", return_value=fake_stats):
            from bot import brain
            brain._classify_losses()
            self.assertEqual(mock_write.call_count, 0)
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM brain_decisions WHERE action='BLACKLIST_CATEGORY'"
            ).fetchone()
        self.assertEqual(row[0], 0)


if __name__ == "__main__":
    unittest.main()
