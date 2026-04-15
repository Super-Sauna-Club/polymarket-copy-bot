"""TDD test for scripts/remove_followed_trader.sql — orphan cleanup.

Scenario D Phase A1: the script must flip `wallets.followed` to 0 for a given
address and stay idempotent on repeated runs. It is the safe, documented way
to remove a trader whose live-copy status came from a historical gap (e.g.
0x3e5b23e9f7 was auto-followed during a 20h window between commits a248262
and ba70dbf on 2026-04-12/13, before the AUTO_DISCOVERY_AUTO_PROMOTE gate
existed).
"""
import os
import unittest

from tests.conftest_helpers import setup_temp_db, teardown_temp_db


ORPHAN_ADDR = "0x3e5b23e9f71d4f0123456789abcdef0000000000"
SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
    "remove_followed_trader.sql",
)


class TestOrphanCleanupSql(unittest.TestCase):
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO wallets (address, username, followed) VALUES (?, ?, 1)",
                (ORPHAN_ADDR, "test_whale"),
            )

    def tearDown(self):
        teardown_temp_db(self.db_path)

    def _run_script(self, addr: str):
        """Execute scripts/remove_followed_trader.sql with :addr bound."""
        with open(SCRIPT_PATH, "r") as f:
            script = f.read()
        with self.db.get_connection() as conn:
            conn.execute(script, {"addr": addr})

    def test_script_file_exists(self):
        self.assertTrue(
            os.path.exists(SCRIPT_PATH),
            "scripts/remove_followed_trader.sql must exist",
        )

    def test_followed_flipped_to_zero(self):
        with self.db.get_connection() as conn:
            before = conn.execute(
                "SELECT followed FROM wallets WHERE address=?", (ORPHAN_ADDR,)
            ).fetchone()
        self.assertEqual(before["followed"], 1, "fixture precondition")

        self._run_script(ORPHAN_ADDR)

        with self.db.get_connection() as conn:
            after = conn.execute(
                "SELECT followed FROM wallets WHERE address=?", (ORPHAN_ADDR,)
            ).fetchone()
        self.assertEqual(after["followed"], 0)

    def test_idempotent_second_run(self):
        self._run_script(ORPHAN_ADDR)
        # Second run must not raise and must not accidentally re-follow
        self._run_script(ORPHAN_ADDR)
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT followed FROM wallets WHERE address=?", (ORPHAN_ADDR,)
            ).fetchone()
        self.assertEqual(row["followed"], 0)

    def test_untargeted_wallet_is_not_affected(self):
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO wallets (address, username, followed) VALUES (?, ?, 1)",
                ("0xlegitimate_trader_should_stay", "bystander"),
            )

        self._run_script(ORPHAN_ADDR)

        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT followed FROM wallets WHERE address=?",
                ("0xlegitimate_trader_should_stay",),
            ).fetchone()
        self.assertEqual(row["followed"], 1, "bystander must stay followed")


if __name__ == "__main__":
    unittest.main()
