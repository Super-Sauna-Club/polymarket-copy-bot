"""Statistical helpers for the promotion gate and related analytics.

Pure functions only — no DB, no I/O, no module-level state. Written
this way so they can be used from any layer (auto_discovery,
trader_lifecycle, dashboard dry-run endpoint) without tangling
dependencies.
"""
import math


def wilson_lower_bound(wins: int, n: int, z: float = 1.96) -> float:
    """Return the Wilson score interval lower bound of a binomial proportion.

    The Wilson LB is a conservative estimate of the true underlying
    success probability. Using it as a promotion gate (instead of the
    raw observed win rate) prevents small-sample noise from triggering
    false promotions — a candidate with 28 wins in 50 trades has an
    observed WR of 56% but a Wilson LB of only ~0.42, meaning we
    cannot rule out that their TRUE underlying WR is below 42% at 95%
    confidence.

    Formula (Wilson 1927):
        p_hat = wins / n
        z2    = z * z
        center = p_hat + z2 / (2n)
        spread = z * sqrt( (p_hat * (1 - p_hat) + z2 / (4n)) / n )
        lower  = (center - spread) / (1 + z2 / n)

    Args:
        wins: number of observed successes (must satisfy 0 <= wins <= n)
        n:    total number of observations
        z:    confidence level z-score (1.96 = 95% two-sided, 2.58 = 99%)

    Returns:
        Lower bound of the confidence interval, clamped to [0.0, 1.0].
        Returns 0.0 for n=0 to signal "no data, do not promote".

    Raises:
        ValueError if wins is negative or wins > n.
    """
    if n <= 0:
        return 0.0
    if wins < 0 or wins > n:
        raise ValueError("wins must be in [0, n]")

    p = wins / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = p + z2 / (2.0 * n)
    spread = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)
    lower = (center - spread) / denom
    return max(0.0, min(1.0, lower))
