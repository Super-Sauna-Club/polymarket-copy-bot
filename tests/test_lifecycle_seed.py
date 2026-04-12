import unittest
from unittest.mock import patch
from tests.conftest_helpers import setup_temp_db, teardown_temp_db


class TestLifecycleSeed(unittest.TestCase):
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db

    def tearDown(self):
        teardown_temp_db(self.db_path)

    def test_seeds_all_followed_traders(self):
        followed = "alice:0xaaa,bob:0xbbb,charlie:0xccc"
        fake_content = "FOLLOWED_TRADERS=%s\n" % followed
        with patch("bot.trader_lifecycle._read_settings", return_value=fake_content):
            from bot import trader_lifecycle
            trader_lifecycle.ensure_followed_traders_seeded()
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT username, address, status FROM trader_lifecycle "
                "ORDER BY username"
            ).fetchall()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["username"], "alice")
        self.assertEqual(rows[0]["status"], "LIVE_FOLLOW")
        self.assertEqual(rows[1]["username"], "bob")
        self.assertEqual(rows[2]["username"], "charlie")

    def test_idempotent_does_not_duplicate(self):
        fake_content = "FOLLOWED_TRADERS=alice:0xaaa\n"
        with patch("bot.trader_lifecycle._read_settings", return_value=fake_content):
            from bot import trader_lifecycle
            trader_lifecycle.ensure_followed_traders_seeded()
            trader_lifecycle.ensure_followed_traders_seeded()
            trader_lifecycle.ensure_followed_traders_seeded()
        with self.db.get_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM trader_lifecycle WHERE username='alice'"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_handles_entry_without_address(self):
        # Legacy entries without address should be skipped, not crash.
        fake_content = "FOLLOWED_TRADERS=alice,bob:0xbbb\n"
        with patch("bot.trader_lifecycle._read_settings", return_value=fake_content):
            from bot import trader_lifecycle
            trader_lifecycle.ensure_followed_traders_seeded()
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT username FROM trader_lifecycle ORDER BY username"
            ).fetchall()
        # alice has no address → skipped. bob has one → seeded.
        self.assertEqual([r["username"] for r in rows], ["bob"])


if __name__ == "__main__":
    unittest.main()
