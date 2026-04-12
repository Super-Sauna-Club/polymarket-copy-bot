import unittest
from unittest.mock import patch
from tests.conftest_helpers import setup_temp_db, teardown_temp_db, insert_copy_trade


class TestLiveCountRace(unittest.TestCase):
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db
        # Three traders, each with -$15 in the last 7 days → all trigger PAUSE.
        # Use FULL 42-char addresses so _remove_followed_trader's substring
        # match against the wallet_address in copy_trades actually works.
        self.settings_content_ref = {
            "content": (
                "FOLLOWED_TRADERS=a:%s,b:%s,c:%s\n"
                "CATEGORY_BLACKLIST_MAP=\n"
            ) % ("0x" + "a" * 40, "0x" + "b" * 40, "0x" + "c" * 40)
        }
        # Seed wallets table (FK) matching the pattern from test_brain_dedup.
        for t in ("a", "b", "c"):
            with db.get_connection() as conn:
                try:
                    conn.execute(
                        "INSERT INTO wallets (address, username) VALUES (?, ?)",
                        ("0x" + t * 40, t)
                    )
                except Exception:
                    pass
            for i in range(5):
                insert_copy_trade(
                    db, wallet_username=t, wallet_address="0x" + t * 40,
                    pnl_realized=-3.0, actual_size=10.0, status="closed",
                    category="cs", condition_id="cid-%s-%d" % (t, i),
                )

    def tearDown(self):
        teardown_temp_db(self.db_path)

    def _fake_read(self):
        return self.settings_content_ref["content"]

    def _fake_write(self, content):
        self.settings_content_ref["content"] = content

    def test_does_not_pause_below_min_live(self):
        import re
        from bot import brain
        with patch("bot.brain._read_settings", side_effect=self._fake_read), \
             patch("bot.brain._write_settings", side_effect=self._fake_write), \
             patch("bot.trader_lifecycle._read_settings", side_effect=self._fake_read), \
             patch("bot.trader_lifecycle._write_settings", side_effect=self._fake_write):
            # MIN_LIVE_TRADERS=2 → we must keep 2 traders live even if all 3 trigger pause.
            brain._check_trader_health()
        # Count how many remain in FOLLOWED_TRADERS after the pause loop.
        m = re.search(r'^FOLLOWED_TRADERS=(.*)$', self.settings_content_ref["content"], re.MULTILINE)
        remaining = [e for e in (m.group(1) if m else "").split(",") if e.strip()]
        self.assertGreaterEqual(len(remaining), 2)


if __name__ == "__main__":
    unittest.main()
