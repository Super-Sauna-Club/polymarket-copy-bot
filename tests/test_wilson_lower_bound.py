"""TDD for Scenario D Phase γ.1 — Wilson score interval lower bound.

The Wilson LB is used as a conservative estimate of true win-rate when
deciding whether to auto-promote a candidate. Gating on WL instead of
the point-estimate WR prevents small-sample noise from triggering false
promotions — a candidate with 28/50 observed wins (56% WR) has a WL of
~0.413, well below fee-adjusted break-even, so it won't pass the gate
even though the point estimate looks good.

Reference values cross-checked against `project_promotion_criteria.md`
and standard Wilson score interval tables. z=1.96 gives a 95% two-sided
confidence interval; we use the LOWER bound only.
"""
import unittest

from bot.stats import wilson_lower_bound


class TestWilsonLowerBound(unittest.TestCase):
    def test_zero_trades_returns_zero(self):
        self.assertEqual(wilson_lower_bound(0, 0), 0.0)

    def test_one_win_one_trade_wide_interval(self):
        """n=1, p=1.0 → Wilson LB is ~0.21 (very wide CI at low n)."""
        lb = wilson_lower_bound(1, 1)
        self.assertLess(lb, 0.5, "n=1 must have very wide confidence interval")
        self.assertGreater(lb, 0.1, "even a single win should lift LB above 0.1")

    def test_zero_wins_n_is_zero_lower_bound(self):
        self.assertAlmostEqual(wilson_lower_bound(0, 10), 0.0, places=3)

    def test_55pct_at_n50_matches_briefing_math(self):
        """Classic n=50, observed WR=56% → Wilson LB ≈ 0.42.

        This is the smoking-gun statistic in project_promotion_criteria.md:
        a 28/50 candidate cannot be distinguished from a 42%-winner at 95%
        confidence. Must NOT pass a 0.50 Wilson LB gate."""
        lb = wilson_lower_bound(28, 50)
        self.assertAlmostEqual(lb, 0.42, delta=0.02)
        self.assertLess(lb, 0.50,
                        "28/50 must not clear the 0.50 Wilson LB threshold")

    def test_55pct_at_n100_still_below_50(self):
        """n=100, 55/100 wins → Wilson LB ≈ 0.45. Still below 0.50 gate."""
        lb = wilson_lower_bound(55, 100)
        self.assertAlmostEqual(lb, 0.45, delta=0.02)
        self.assertLess(lb, 0.50)

    def test_60pct_at_n100_clears_50(self):
        """n=100, 60/100 wins → Wilson LB ≈ 0.50. Clears the gate."""
        lb = wilson_lower_bound(60, 100)
        self.assertAlmostEqual(lb, 0.50, delta=0.02)

    def test_high_n_converges_to_point_estimate(self):
        """With n=1000, Wilson LB for p=0.60 is close to 0.57 (tight CI)."""
        lb = wilson_lower_bound(600, 1000)
        self.assertGreater(lb, 0.55)
        self.assertLess(lb, 0.60)

    def test_invalid_wins_negative_raises(self):
        with self.assertRaises(ValueError):
            wilson_lower_bound(-1, 10)

    def test_invalid_wins_greater_than_n_raises(self):
        with self.assertRaises(ValueError):
            wilson_lower_bound(11, 10)

    def test_monotonic_in_wins_for_fixed_n(self):
        """More wins at same n → higher lower bound."""
        for n in (10, 50, 100, 500):
            prev = -1.0
            for w in range(0, n + 1, max(1, n // 10)):
                lb = wilson_lower_bound(w, n)
                self.assertGreaterEqual(lb, prev)
                prev = lb

    def test_z_parameter_shifts_bound(self):
        """Higher z (stricter confidence) → lower bound (wider interval)."""
        lb_95 = wilson_lower_bound(60, 100, z=1.96)
        lb_99 = wilson_lower_bound(60, 100, z=2.58)
        self.assertLess(lb_99, lb_95,
                        "99% CI lower bound must be below 95% CI lower bound")


if __name__ == "__main__":
    unittest.main()
