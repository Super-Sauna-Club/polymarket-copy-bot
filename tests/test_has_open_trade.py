"""TDD tests for db.has_open_trade_for_market().

The auto-buy path in copy_trader had a race where `buy_shares()` was
called BEFORE the DB INSERT, so if the INSERT then failed with
IntegrityError from idx_copy_trades_open_dedup, the on-chain order had
already spent real USDC and we were left with ghost shares.

Example damage: 2026-04-14 16:34-16:43, 40+ $1 Angels/Yankees Under
buys filled on-chain, only id=3547 actually tracked in copy_trades.
~$48 ghost exposure on a single market.

This helper matches the DB's UNIQUE partial index semantics exactly
(condition_id, wallet_address, WHERE status='open'). The 5 buy paths
call it BEFORE buy_shares so the order is never placed if the DB would
reject the insert.
"""
import unittest
from tests.conftest_helpers import setup_temp_db, teardown_temp_db, insert_copy_trade


class TestHasOpenTrade(unittest.TestCase):
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db
        # Seed wallets rows (FK constraint on copy_trades)
        with db.get_connection() as conn:
            for addr in ("0xdead", "0xOTHER"):
                conn.execute(
                    "INSERT OR IGNORE INTO wallets (address, username) VALUES (?, ?)",
                    (addr, addr[-4:]),
                )

    def tearDown(self):
        teardown_temp_db(self.db_path)

    def test_returns_true_when_open_row_exists(self):
        """Existing open row → cannot open another one (UNIQUE partial index)."""
        insert_copy_trade(
            self.db,
            wallet_address="0xdead",
            condition_id="COND-A",
            status="open",
        )
        self.assertTrue(self.db.has_open_trade_for_market("0xdead", "COND-A"))

    def test_returns_false_when_no_rows_exist(self):
        """Empty table → safe to open."""
        self.assertFalse(self.db.has_open_trade_for_market("0xdead", "COND-A"))

    def test_returns_false_when_only_closed_row_exists(self):
        """Closed rows don't block (partial index is WHERE status='open')."""
        insert_copy_trade(
            self.db,
            wallet_address="0xdead",
            condition_id="COND-A",
            status="closed",
        )
        self.assertFalse(self.db.has_open_trade_for_market("0xdead", "COND-A"))

    def test_returns_false_when_only_baseline_row_exists(self):
        """Baseline rows don't block — they're position snapshots, not live
        holdings, and the partial index excludes them."""
        insert_copy_trade(
            self.db,
            wallet_address="0xdead",
            condition_id="COND-A",
            status="baseline",
        )
        self.assertFalse(self.db.has_open_trade_for_market("0xdead", "COND-A"))

    def test_returns_false_when_open_row_is_different_wallet(self):
        """Open row for a DIFFERENT wallet on same market → safe. The index
        keys include wallet_address."""
        insert_copy_trade(
            self.db,
            wallet_address="0xOTHER",
            condition_id="COND-A",
            status="open",
        )
        self.assertFalse(self.db.has_open_trade_for_market("0xdead", "COND-A"))

    def test_returns_false_when_open_row_is_different_market(self):
        """Open row for a DIFFERENT market → safe."""
        insert_copy_trade(
            self.db,
            wallet_address="0xdead",
            condition_id="COND-OTHER",
            status="open",
        )
        self.assertFalse(self.db.has_open_trade_for_market("0xdead", "COND-A"))


if __name__ == "__main__":
    unittest.main()
