"""TDD tests for db.sum_open_shares_held_for_market().

Backstop helper for the 2026-04-14 Angels/Yankees race where 84 Under
shares accumulated on-chain without a corresponding copy_trades row.
The set-level reconcile check saw id=3547 matching the condition_id
and classified the market as "tracked"; the dashboard similarly
preferred DB actual_size over chain initialValue. Both checks miss the
discrepancy because they compare presence/absence per market, not
share counts within a market.

This helper returns the sum of shares_held across all open copy_trades
rows for a given (wallet_address, condition_id) pair. Callers compare
it against on-chain size to detect "chain holds more than DB tracks"
scenarios.
"""
import unittest
from tests.conftest_helpers import setup_temp_db, teardown_temp_db, insert_copy_trade


class TestSumOpenSharesHeld(unittest.TestCase):
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db
        with db.get_connection() as conn:
            for addr in ("0xdead", "0xOTHER"):
                conn.execute(
                    "INSERT OR IGNORE INTO wallets (address, username) VALUES (?, ?)",
                    (addr, addr[-4:]),
                )

    def tearDown(self):
        teardown_temp_db(self.db_path)

    def test_sum_shares_held_zero_when_no_rows(self):
        """Empty table → 0.0, so callers can do arithmetic without None-checks."""
        result = self.db.sum_open_shares_held_for_market("0xdead", "COND-A")
        self.assertEqual(result, 0.0)

    def test_sum_shares_held_includes_multiple_open_rows(self):
        """Multiple open rows on the same (wallet, cond) sum correctly.
        The UNIQUE partial index blocks this in practice, but the helper
        must handle the theoretical case so it stays correct if the
        index changes to (cond, wallet, side) and allows YES+NO together."""
        insert_copy_trade(
            self.db,
            wallet_address="0xdead",
            condition_id="COND-A",
            status="open",
            shares_held=10.0,
            side="YES",
            market_question="Q1 YES",
        )
        # Circumvent UNIQUE by using side="NO" (not in current 2-col index,
        # but tested here for forward-compat with the 3-col schema).
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO copy_trades (wallet_address, wallet_username, "
                "market_question, side, entry_price, size, status, "
                "condition_id, shares_held, actual_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("0xdead", "dead", "Q1 NO", "NO", 0.5, 5.0, "open",
                 "COND-B", 5.5, 5.0),
            )
        # Second row with different cond to verify filter is per-market
        result_a = self.db.sum_open_shares_held_for_market("0xdead", "COND-A")
        result_b = self.db.sum_open_shares_held_for_market("0xdead", "COND-B")
        self.assertEqual(result_a, 10.0)
        self.assertEqual(result_b, 5.5)

    def test_sum_shares_held_excludes_closed_and_baseline_rows(self):
        """Only status='open' counts — closed/baseline rows don't contribute
        to the live on-chain tracking sum."""
        insert_copy_trade(
            self.db,
            wallet_address="0xdead",
            condition_id="COND-A",
            status="open",
            shares_held=3.0,
        )
        insert_copy_trade(
            self.db,
            wallet_address="0xdead",
            condition_id="COND-A",
            market_question="Closed version",
            status="closed",
            shares_held=99.0,
        )
        insert_copy_trade(
            self.db,
            wallet_address="0xdead",
            condition_id="COND-A",
            market_question="Baseline snapshot",
            status="baseline",
            shares_held=777.0,
        )
        result = self.db.sum_open_shares_held_for_market("0xdead", "COND-A")
        self.assertEqual(result, 3.0)

    def test_sum_shares_held_excludes_different_wallet_or_market(self):
        """Index-strict matching on (wallet, cond). Cross-wallet and
        cross-market rows must not leak into the sum."""
        insert_copy_trade(
            self.db,
            wallet_address="0xOTHER",
            condition_id="COND-A",
            status="open",
            shares_held=50.0,
        )
        insert_copy_trade(
            self.db,
            wallet_address="0xdead",
            condition_id="COND-DIFFERENT",
            status="open",
            shares_held=25.0,
        )
        result = self.db.sum_open_shares_held_for_market("0xdead", "COND-A")
        self.assertEqual(result, 0.0)

    def test_sum_shares_held_handles_null_shares_field(self):
        """Legacy rows may have shares_held=NULL (pre-close-path-fix era).
        COALESCE(shares_held, 0) keeps the sum numeric instead of
        returning None.

        Uses YES + NO sides to work under both the 2-col and 3-col
        variants of idx_copy_trades_open_dedup."""
        # Row 1: NULL shares_held, side=YES
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO copy_trades (wallet_address, wallet_username, "
                "market_question, side, entry_price, size, status, "
                "condition_id, shares_held, actual_size) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("0xdead", "dead", "Legacy row", "YES", 0.5, 1.0, "open",
                 "COND-A", None, 1.0),
            )
        # Row 2: real shares_held, side=NO (so 3-col unique index allows it)
        insert_copy_trade(
            self.db,
            wallet_address="0xdead",
            condition_id="COND-A",
            market_question="New row",
            side="NO",
            status="open",
            shares_held=7.0,
        )
        result = self.db.sum_open_shares_held_for_market("0xdead", "COND-A")
        # Legacy row contributes 0 (via COALESCE), new row contributes 7
        self.assertEqual(result, 7.0)


class TestSumByConditionIdSide(unittest.TestCase):
    """Tests for sum_open_shares_held_by_cid_side — used by reconcile and
    dashboard to detect partial ghosts.

    copy_trades.wallet_address stores the SOURCE trader's wallet (e.g.
    sovereign2013 at 0xee613b...), NOT our executing wallet (POLYMARKET_
    FUNDER at 0x53fe4d...). The chain /positions API returns positions at
    the FUNDER wallet. To compare DB shares_held against chain size, the
    helper must aggregate by (condition_id, side) across ALL source
    traders, because multiple traders can independently enter the same
    (market, side) and we'd have multiple rows covering one chain token.
    """

    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db
        with db.get_connection() as conn:
            for addr in ("0xSOV", "0xKING", "0xXSAG"):
                conn.execute(
                    "INSERT OR IGNORE INTO wallets (address, username) VALUES (?, ?)",
                    (addr, addr[-4:]),
                )

    def tearDown(self):
        teardown_temp_db(self.db_path)

    def test_sums_across_wallets_same_cid_and_side(self):
        """Two different traders open the same (market, side) → sum both."""
        insert_copy_trade(
            self.db,
            wallet_address="0xSOV",
            condition_id="COND-X",
            side="Under",
            status="open",
            shares_held=3.0,
        )
        insert_copy_trade(
            self.db,
            wallet_address="0xKING",
            condition_id="COND-X",
            side="Under",
            status="open",
            shares_held=5.0,
            market_question="same market, other trader",
        )
        result = self.db.sum_open_shares_held_by_cid_side("COND-X", "Under")
        self.assertEqual(result, 8.0)

    def test_excludes_other_side_of_same_market(self):
        """YES and NO on the same market are different chain tokens.
        Summing for one side must not pull in the opposite side."""
        insert_copy_trade(
            self.db,
            wallet_address="0xSOV",
            condition_id="COND-X",
            side="Under",
            status="open",
            shares_held=3.0,
        )
        insert_copy_trade(
            self.db,
            wallet_address="0xSOV",
            condition_id="COND-X",
            side="Over",
            status="open",
            shares_held=100.0,
            market_question="Over leg",
        )
        under_sum = self.db.sum_open_shares_held_by_cid_side("COND-X", "Under")
        over_sum = self.db.sum_open_shares_held_by_cid_side("COND-X", "Over")
        self.assertEqual(under_sum, 3.0)
        self.assertEqual(over_sum, 100.0)

    def test_case_insensitive_side_match(self):
        """Chain API returns 'Under', 'Yes', 'No', team names with varied
        capitalization. Must match DB side regardless of case."""
        insert_copy_trade(
            self.db,
            wallet_address="0xSOV",
            condition_id="COND-X",
            side="Yes",  # title case
            status="open",
            shares_held=4.0,
        )
        # Query with uppercase variants
        self.assertEqual(
            self.db.sum_open_shares_held_by_cid_side("COND-X", "YES"), 4.0
        )
        self.assertEqual(
            self.db.sum_open_shares_held_by_cid_side("COND-X", "yes"), 4.0
        )

    def test_returns_zero_when_no_match(self):
        """Empty table OR wrong cid OR wrong side → 0.0."""
        insert_copy_trade(
            self.db,
            wallet_address="0xSOV",
            condition_id="COND-X",
            side="Yes",
            status="open",
            shares_held=4.0,
        )
        self.assertEqual(
            self.db.sum_open_shares_held_by_cid_side("COND-OTHER", "Yes"), 0.0
        )
        self.assertEqual(
            self.db.sum_open_shares_held_by_cid_side("COND-X", "No"), 0.0
        )


if __name__ == "__main__":
    unittest.main()
