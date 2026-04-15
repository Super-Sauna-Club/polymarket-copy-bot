"""TDD for Scenario D Phase γ.4 — cooldown + circuit breaker.

Two independent safety rails that sit between `evaluate_promotion`
(which says "this candidate MEETS the criteria") and the actual
`_add_followed_trader` call (which would add them to the live
follow set).

Cooldown
--------
Max 1 auto-promotion within PROMOTE_COOLDOWN_DAYS. Prevents a single
noisy weekend from flipping multiple traders live simultaneously.
Implemented by reading the most-recent activity_log row with
event_type='promotion' and checking its age.

Circuit breaker
---------------
If any auto-promoted trader has accumulated more than
CIRCUIT_BREAKER_MAX_LOSS_USD in losses during the first
CIRCUIT_BREAKER_WINDOW_DAYS of live trading, HALT all future
auto-promotions until a human investigates. Uses:
- `trader_candidates.auto_promoted_at` (new column, Phase γ.4)
- `copy_trades.pnl_realized` summed within the window

No persistent "halted" flag — the computation is always fresh. The
log trail via activity_log provides the audit history.
"""
import unittest

from tests.conftest_helpers import setup_temp_db, teardown_temp_db


def _ms_ago(days: float) -> str:
    """Return a SQLite-datetime string `days` days ago (localtime)."""
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


class TestPromotionCooldown(unittest.TestCase):
    def setUp(self):
        self.path = setup_temp_db()
        from database import db
        self.db = db
        import config
        self._saved = getattr(config, "PROMOTE_COOLDOWN_DAYS", 7)
        config.PROMOTE_COOLDOWN_DAYS = 7

    def tearDown(self):
        import config
        config.PROMOTE_COOLDOWN_DAYS = self._saved
        teardown_temp_db(self.path)

    def _seed_promotion_log(self, days_ago: float):
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO activity_log (event_type, icon, title, detail, pnl, created_at) "
                "VALUES ('promotion', '', 'Auto-promo', 'test', 0, ?)",
                (_ms_ago(days_ago),),
            )

    def test_cooldown_inactive_when_no_recent_promotions(self):
        from bot.promotion import promotion_cooldown_active
        active, reason = promotion_cooldown_active()
        self.assertFalse(active)
        self.assertEqual(reason, "ok")

    def test_cooldown_active_when_recent_promotion_exists(self):
        self._seed_promotion_log(days_ago=2)

        from bot.promotion import promotion_cooldown_active
        active, reason = promotion_cooldown_active()
        self.assertTrue(active)
        self.assertTrue(reason.startswith("cooldown"),
                        "expected reason to start with 'cooldown', got: %s" % reason)

    def test_cooldown_inactive_when_recent_promotion_outside_window(self):
        self._seed_promotion_log(days_ago=10)  # older than 7d cooldown

        from bot.promotion import promotion_cooldown_active
        active, reason = promotion_cooldown_active()
        self.assertFalse(active)

    def test_cooldown_respects_most_recent_event(self):
        """Two events: one 10d ago (outside window), one 1d ago (inside).
        Must detect the 1d one."""
        self._seed_promotion_log(days_ago=10)
        self._seed_promotion_log(days_ago=1)

        from bot.promotion import promotion_cooldown_active
        active, _ = promotion_cooldown_active()
        self.assertTrue(active)


class TestCircuitBreaker(unittest.TestCase):
    def setUp(self):
        self.path = setup_temp_db()
        from database import db
        self.db = db
        import config
        self._saved_max = getattr(config, "CIRCUIT_BREAKER_MAX_LOSS_USD", 10.0)
        self._saved_win = getattr(config, "CIRCUIT_BREAKER_WINDOW_DAYS", 7.0)
        config.CIRCUIT_BREAKER_MAX_LOSS_USD = 10.0
        config.CIRCUIT_BREAKER_WINDOW_DAYS = 7.0

    def tearDown(self):
        import config
        config.CIRCUIT_BREAKER_MAX_LOSS_USD = self._saved_max
        config.CIRCUIT_BREAKER_WINDOW_DAYS = self._saved_win
        teardown_temp_db(self.path)

    def _seed_candidate(self, addr: str, username: str, auto_promoted_days_ago: float):
        with self.db.get_connection() as conn:
            # Wallet row is needed because copy_trades.wallet_address has a
            # FOREIGN KEY constraint on wallets.address.
            conn.execute(
                "INSERT INTO wallets (address, username, followed) VALUES (?, ?, 1)",
                (addr, username),
            )
            conn.execute(
                "INSERT INTO trader_candidates "
                "(address, username, status, auto_promoted_at) "
                "VALUES (?, ?, 'promoted', ?)",
                (addr, username, _ms_ago(auto_promoted_days_ago)),
            )

    def _seed_copy_trade(self, addr: str, username: str, pnl: float, closed_days_ago: float):
        from tests.conftest_helpers import insert_copy_trade
        cid = "cid_%s_%s" % (username, closed_days_ago)
        insert_copy_trade(
            self.db,
            wallet_username=username,
            wallet_address=addr,
            status="closed",
            pnl_realized=pnl,
            condition_id=cid,
        )
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE copy_trades SET closed_at = ? WHERE condition_id = ?",
                (_ms_ago(closed_days_ago), cid),
            )

    def test_circuit_breaker_ok_when_no_auto_promoted_traders(self):
        from bot.promotion import compute_circuit_breaker_state
        halted, reason = compute_circuit_breaker_state()
        self.assertFalse(halted)
        self.assertEqual(reason, "ok")

    def test_circuit_breaker_halts_when_recent_autopromote_big_loss(self):
        self._seed_candidate("0xhlt", "halter", auto_promoted_days_ago=2)
        self._seed_copy_trade("0xhlt", "halter", pnl=-15.0, closed_days_ago=1)

        from bot.promotion import compute_circuit_breaker_state
        halted, reason = compute_circuit_breaker_state()
        self.assertTrue(halted, "−$15 in the last 2d must trip the $10 breaker")
        self.assertTrue(reason.startswith("circuit_breaker"),
                        "expected circuit_breaker reason, got: %s" % reason)
        self.assertIn("halter", reason)

    def test_circuit_breaker_ok_when_loss_within_limit(self):
        self._seed_candidate("0xok", "safe", auto_promoted_days_ago=2)
        self._seed_copy_trade("0xok", "safe", pnl=-5.0, closed_days_ago=1)

        from bot.promotion import compute_circuit_breaker_state
        halted, reason = compute_circuit_breaker_state()
        self.assertFalse(halted, "−$5 < −$10 threshold, must not halt, reason=%s" % reason)

    def test_circuit_breaker_ignores_old_auto_promotions(self):
        """Auto-promoted 10d ago → outside 7d window → losses ignored."""
        self._seed_candidate("0xold", "oldpromo", auto_promoted_days_ago=10)
        self._seed_copy_trade("0xold", "oldpromo", pnl=-50.0, closed_days_ago=9)

        from bot.promotion import compute_circuit_breaker_state
        halted, _ = compute_circuit_breaker_state()
        self.assertFalse(halted,
                         "auto-promo outside the 7d window must not count toward breaker")

    def test_circuit_breaker_ignores_losses_before_auto_promotion(self):
        """A trader who had losses BEFORE being auto-promoted (historical
        pre-promotion trades) must not trigger the breaker — only trades
        closed_at > auto_promoted_at count."""
        self._seed_candidate("0xhist", "histpromo", auto_promoted_days_ago=2)
        # Loss was 5 days ago (3 days before auto-promote at day -2)
        self._seed_copy_trade("0xhist", "histpromo", pnl=-20.0, closed_days_ago=5)

        from bot.promotion import compute_circuit_breaker_state
        halted, _ = compute_circuit_breaker_state()
        self.assertFalse(halted,
                         "pre-promotion losses must not trip the breaker")

    def test_circuit_breaker_sums_multiple_trades(self):
        """Small individual losses below threshold but cumulative above."""
        self._seed_candidate("0xsum", "summer", auto_promoted_days_ago=3)
        self._seed_copy_trade("0xsum", "summer", pnl=-4.0, closed_days_ago=2)
        self._seed_copy_trade("0xsum", "summer", pnl=-3.5, closed_days_ago=1)
        self._seed_copy_trade("0xsum", "summer", pnl=-3.5, closed_days_ago=0.5)
        # total -11.0 > -10.0 threshold

        from bot.promotion import compute_circuit_breaker_state
        halted, reason = compute_circuit_breaker_state()
        self.assertTrue(halted,
                        "cumulative losses $11 must trip the $10 breaker, reason=%s" % reason)


if __name__ == "__main__":
    unittest.main()
