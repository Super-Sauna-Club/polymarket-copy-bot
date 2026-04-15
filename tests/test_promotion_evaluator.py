"""TDD for Scenario D Phase γ.3 — promotion gate evaluator.

Pure-function gate that takes candidate stats + threshold dict and
returns `(pass: bool, reason: str)`. Used by both the production
`check_promotions` caller AND the read-only dry-run endpoint so they
give identical verdicts.

Gate order matters — the first failing gate determines the rejection
reason, so the order represents "easiest failure first" for dry-run
readability:

    1. insufficient_trades      (data quantity)
    2. low_win_rate             (observable quality)
    3. weak_wilson_lb           (statistical significance)
    4. low_roi                  (economic viability)
    5. below_abs_pnl_floor      (magnitude)
    6. stale                    (recency)
"""
import unittest


DECOUPLED_THRESHOLDS = {
    "min_trades":       100,
    "min_wr":           55.0,
    "min_wilson_lower": 0.55,  # tighter than what WR=55 gives at n=100
    "min_roi":          0.05,
    "min_abs_pnl":      5.0,
    "max_age_days":     14.0,
}


class TestEvaluatePromotion(unittest.TestCase):
    def test_happy_path_clears_all_gates(self):
        from bot.promotion import evaluate_promotion
        passed, reason = evaluate_promotion(
            n_trades=150, wins=95, total_pnl=8.25, newest_trade_age_days=1.0,
            thresholds=DECOUPLED_THRESHOLDS,
        )
        self.assertTrue(passed, "clean candidate must pass, got reason: %s" % reason)
        self.assertEqual(reason, "ok")

    def test_insufficient_trades_rejected_first(self):
        from bot.promotion import evaluate_promotion
        passed, reason = evaluate_promotion(
            n_trades=50, wins=40, total_pnl=20.0, newest_trade_age_days=1.0,
            thresholds=DECOUPLED_THRESHOLDS,
        )
        self.assertFalse(passed)
        self.assertTrue(reason.startswith("insufficient_trades"),
                        "expected insufficient_trades, got %s" % reason)

    def test_low_win_rate_rejected(self):
        from bot.promotion import evaluate_promotion
        passed, reason = evaluate_promotion(
            n_trades=150, wins=60, total_pnl=20.0, newest_trade_age_days=1.0,
            thresholds=DECOUPLED_THRESHOLDS,
        )
        self.assertFalse(passed)
        self.assertTrue(reason.startswith("low_win_rate"),
                        "expected low_win_rate, got %s" % reason)

    def test_weak_wilson_lb_rejected(self):
        """Candidate passes min_wr=55 but fails min_wilson_lower=0.55.
        n=100, wins=58 -> WR=58% but Wilson LB ~0.48 — classic small-sample
        noise that the raw WR gate would let through."""
        from bot.promotion import evaluate_promotion
        passed, reason = evaluate_promotion(
            n_trades=100, wins=58, total_pnl=10.0, newest_trade_age_days=1.0,
            thresholds=DECOUPLED_THRESHOLDS,
        )
        self.assertFalse(passed)
        self.assertTrue(reason.startswith("weak_wilson_lb"),
                        "expected weak_wilson_lb, got %s" % reason)

    def test_low_roi_rejected(self):
        """n=150, total_pnl=2.0 -> ROI = 2/150 ~0.013 < 0.05. Relax Wilson
        LB and absolute-floor gates for this test so ROI is the first fail."""
        from bot.promotion import evaluate_promotion
        thresholds = dict(DECOUPLED_THRESHOLDS)
        thresholds["min_wilson_lower"] = 0.30
        passed, reason = evaluate_promotion(
            n_trades=150, wins=95, total_pnl=2.0, newest_trade_age_days=1.0,
            thresholds=thresholds,
        )
        self.assertFalse(passed)
        self.assertTrue(reason.startswith("low_roi"),
                        "expected low_roi, got %s" % reason)

    def test_below_abs_pnl_floor_rejected(self):
        from bot.promotion import evaluate_promotion
        thresholds = dict(DECOUPLED_THRESHOLDS)
        thresholds["min_roi"] = 0.001  # relax ROI so abs_pnl is the first fail
        passed, reason = evaluate_promotion(
            n_trades=150, wins=95, total_pnl=3.0,
            newest_trade_age_days=1.0, thresholds=thresholds,
        )
        self.assertFalse(passed)
        self.assertTrue(reason.startswith("below_abs_pnl_floor"),
                        "expected below_abs_pnl_floor, got %s" % reason)

    def test_stale_newest_trade_rejected(self):
        from bot.promotion import evaluate_promotion
        passed, reason = evaluate_promotion(
            n_trades=150, wins=95, total_pnl=20.0, newest_trade_age_days=15.0,
            thresholds=DECOUPLED_THRESHOLDS,
        )
        self.assertFalse(passed)
        self.assertTrue(reason.startswith("stale"),
                        "expected stale, got %s" % reason)

    def test_zero_trades_returns_insufficient_not_crash(self):
        from bot.promotion import evaluate_promotion
        passed, reason = evaluate_promotion(
            n_trades=0, wins=0, total_pnl=0.0, newest_trade_age_days=0.0,
            thresholds=DECOUPLED_THRESHOLDS,
        )
        self.assertFalse(passed)
        self.assertTrue(reason.startswith("insufficient_trades"))

    def test_defaults_read_from_config_when_thresholds_is_none(self):
        """When thresholds=None, the function reads from config module.
        Use production defaults and confirm a clean candidate passes."""
        from bot.promotion import evaluate_promotion
        import config
        n = config.PROMOTE_MIN_PAPER_TRADES + 50
        passed, reason = evaluate_promotion(
            n_trades=n,
            wins=int(n * 0.70),  # 70% WR well above 60 threshold
            total_pnl=15.0,
            newest_trade_age_days=5.0,
            thresholds=None,
        )
        self.assertTrue(passed, "70%% WR at n=%d must clear production defaults, reason=%s" % (n, reason))

    def test_invalid_wins_exceeding_n_raises(self):
        from bot.promotion import evaluate_promotion
        with self.assertRaises(ValueError):
            evaluate_promotion(
                n_trades=10, wins=11, total_pnl=0, newest_trade_age_days=0,
                thresholds=DECOUPLED_THRESHOLDS,
            )


if __name__ == "__main__":
    unittest.main()
