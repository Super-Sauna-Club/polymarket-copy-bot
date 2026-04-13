"""Regression tests for the log_blocked_trade and log_brain_decision
dedup guards added on 2026-04-13.

Both helpers were exhibiting cross-cycle / cross-scan spam:
- log_blocked_trade: same (trader, cid, reason) wrote a row every scan
  cycle (~6 rows per market per 10s scan)
- log_brain_decision: same (action, target) wrote a row every brain
  cycle (~5 duplicate rows per 2h cycle)

Both guards must drop subsequent calls within their dedup window
without raising and without writing a new row.
"""
import unittest
from tests.conftest_helpers import setup_temp_db, teardown_temp_db


class TestBlockedTradeDedup(unittest.TestCase):
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db
        db._blocked_dedup_cache.clear()

    def tearDown(self):
        teardown_temp_db(self.db_path)

    def test_first_call_writes_row(self):
        self.db.log_blocked_trade(
            trader="alice", market_question="Will X?",
            condition_id="cid-1", side="YES", trader_price=0.5,
            block_reason="price_range", block_detail="x"
        )
        with self.db.get_connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM blocked_trades").fetchone()[0]
        self.assertEqual(n, 1)

    def test_duplicate_within_ttl_is_skipped(self):
        for _ in range(10):
            self.db.log_blocked_trade(
                trader="alice", market_question="Will X?",
                condition_id="cid-1", side="YES", trader_price=0.5,
                block_reason="price_range", block_detail="x"
            )
        with self.db.get_connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM blocked_trades").fetchone()[0]
        self.assertEqual(n, 1)

    def test_different_reason_writes_separate_row(self):
        self.db.log_blocked_trade(
            trader="alice", market_question="Will X?",
            condition_id="cid-1", side="YES", trader_price=0.5,
            block_reason="price_range", block_detail="x"
        )
        self.db.log_blocked_trade(
            trader="alice", market_question="Will X?",
            condition_id="cid-1", side="YES", trader_price=0.5,
            block_reason="exposure_limit", block_detail="y"
        )
        with self.db.get_connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM blocked_trades").fetchone()[0]
        self.assertEqual(n, 2)

    def test_different_trader_writes_separate_row(self):
        for trader in ("alice", "bob"):
            self.db.log_blocked_trade(
                trader=trader, market_question="Will X?",
                condition_id="cid-1", side="YES", trader_price=0.5,
                block_reason="price_range", block_detail="x"
            )
        with self.db.get_connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM blocked_trades").fetchone()[0]
        self.assertEqual(n, 2)

    def test_different_cid_writes_separate_row(self):
        for cid in ("cid-1", "cid-2"):
            self.db.log_blocked_trade(
                trader="alice", market_question="Will X?",
                condition_id=cid, side="YES", trader_price=0.5,
                block_reason="price_range", block_detail="x"
            )
        with self.db.get_connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM blocked_trades").fetchone()[0]
        self.assertEqual(n, 2)

    def test_simulated_scan_loop_only_keeps_one(self):
        for _ in range(500):
            self.db.log_blocked_trade(
                trader="sovereign2013",
                market_question="Bucks vs. 76ers: O/U 225.5",
                condition_id="0x14d57e73", side="Under",
                trader_price=0.515,
                block_reason="exposure_limit",
                block_detail="$3 >= $3 max"
            )
        with self.db.get_connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM blocked_trades").fetchone()[0]
        self.assertEqual(n, 1)


class TestBrainDecisionDedup(unittest.TestCase):
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db

    def tearDown(self):
        teardown_temp_db(self.db_path)

    def test_first_call_writes_row(self):
        self.db.log_brain_decision(
            action="PAUSE_TRADER", target="xsaghav",
            reason="7d PnL bad", data="", expected_impact="x"
        )
        with self.db.get_connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM brain_decisions").fetchone()[0]
        self.assertEqual(n, 1)

    def test_duplicate_action_target_skipped(self):
        for reason in ("7d PnL $-100", "7d PnL $-105", "7d PnL $-110"):
            self.db.log_brain_decision(
                action="PAUSE_TRADER", target="xsaghav",
                reason=reason, data="", expected_impact=""
            )
        with self.db.get_connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM brain_decisions").fetchone()[0]
        self.assertEqual(n, 1)

    def test_different_target_writes_separate_row(self):
        for trader in ("xsaghav", "fsavhlc", "sovereign2013"):
            self.db.log_brain_decision(
                action="PAUSE_TRADER", target=trader,
                reason="7d PnL bad", data="", expected_impact=""
            )
        with self.db.get_connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM brain_decisions").fetchone()[0]
        self.assertEqual(n, 3)

    def test_different_action_writes_separate_row(self):
        for action in ("TIGHTEN_FILTER", "RELAX_FILTER"):
            self.db.log_brain_decision(
                action=action, target="KING7777777",
                reason="x", data="", expected_impact=""
            )
        with self.db.get_connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM brain_decisions").fetchone()[0]
        self.assertEqual(n, 2)

    def test_dedup_hours_zero_disables_guard(self):
        for _ in range(3):
            self.db.log_brain_decision(
                action="KICK_TRADER", target="xsaghav",
                reason="kicked", data="", expected_impact="",
                dedup_hours=0
            )
        with self.db.get_connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM brain_decisions").fetchone()[0]
        self.assertEqual(n, 3)

    def test_simulated_brain_cycles_dedup(self):
        for _ in range(5):
            self.db.log_brain_decision("TIGHTEN_FILTER", "KING7777777",
                                        "12 BAD_PRICE losses", "", "")
            self.db.log_brain_decision("PAUSE_TRADER", "sovereign2013",
                                        "5 consecutive losses", "", "")
            self.db.log_brain_decision("PAUSE_TRADER", "xsaghav",
                                        "7d PnL bad", "", "")
            self.db.log_brain_decision("PAUSE_TRADER", "fsavhlc",
                                        "7d PnL bad", "", "")
            self.db.log_brain_decision("RELAX_FILTER", "KING7777777",
                                        "tier=solid", "", "")
        with self.db.get_connection() as conn:
            n = conn.execute("SELECT COUNT(*) FROM brain_decisions").fetchone()[0]
        self.assertEqual(n, 5)


if __name__ == "__main__":
    unittest.main()
