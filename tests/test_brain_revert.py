import unittest
from unittest.mock import patch
from tests.conftest_helpers import setup_temp_db, teardown_temp_db, insert_copy_trade


class TestBrainRevert(unittest.TestCase):
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db
        # Seed a wallets row for FK (matches pattern from test_brain_dedup).
        with db.get_connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO wallets (address, username) VALUES (?, ?)",
                    ("0xking", "KING7777777")
                )
            except Exception:
                pass
        # 5 recent winning trades in cs for KING -> blacklist should revert.
        for i in range(5):
            insert_copy_trade(
                db,
                wallet_username="KING7777777",
                wallet_address="0xking",
                category="cs",
                pnl_realized=+1.5,
                actual_size=5.0,
                status="closed",
                condition_id="cid-win-%d" % i,
            )
        # The revert helper filters on closed_at >= now-7d; insert_copy_trade
        # leaves closed_at NULL, so set it explicitly to "now" for visibility.
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE copy_trades SET closed_at = datetime('now','localtime')"
            )

        self.content_ref = {
            "content": "CATEGORY_BLACKLIST_MAP=KING7777777:cs\n"
        }

    def tearDown(self):
        teardown_temp_db(self.db_path)

    def _fake_read(self):
        return self.content_ref["content"]

    def _fake_write(self, content):
        self.content_ref["content"] = content

    def test_revert_removes_blacklist_when_data_improved(self):
        with patch("bot.brain._read_settings", side_effect=self._fake_read), \
             patch("bot.brain._write_settings", side_effect=self._fake_write):
            from bot import brain
            brain._revert_obsolete_blacklists()
        import re
        m = re.search(r'^CATEGORY_BLACKLIST_MAP=(.*)$', self.content_ref["content"], re.MULTILINE)
        remaining = (m.group(1) if m else "").strip()
        self.assertEqual(remaining, "")
        with self.db.get_connection() as conn:
            reverts = conn.execute(
                "SELECT COUNT(*) FROM brain_decisions WHERE action='REVERT_BLACKLIST'"
            ).fetchone()[0]
        self.assertGreaterEqual(reverts, 1)

    def test_revert_keeps_blacklist_when_data_still_bad(self):
        # Overwrite the 5 wins with 5 losses -> condition still holds.
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE copy_trades SET pnl_realized = -1.5 WHERE wallet_username='KING7777777'"
            )
        with patch("bot.brain._read_settings", side_effect=self._fake_read), \
             patch("bot.brain._write_settings", side_effect=self._fake_write):
            from bot import brain
            brain._revert_obsolete_blacklists()
        self.assertIn("KING7777777:cs", self.content_ref["content"])


if __name__ == "__main__":
    unittest.main()
