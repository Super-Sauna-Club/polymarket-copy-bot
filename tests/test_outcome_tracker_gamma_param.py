"""Regression test: Gamma /markets filter param must be `condition_ids`
(plural, snake_case).

Empirical finding on walter (2026-04-15): the Gamma API silently ignores
`conditionId` (camelCase), `condition_id` (singular snake_case), and
`conditionIds` (camelCase plural). ALL of them return the default
unfiltered first-20-markets list. Only `condition_ids` (plural snake_case)
actually filters to the requested market.

Pre-this-fix both `bot/outcome_tracker.py::_get_market_price` and the
piff-cherry-picked `dashboard/app.py::api_paper_traders` were using
the wrong param. The worst case isn't just "missing data" — it's
silently-wrong data, because `_get_market_price` does `markets[0]`
on the unfiltered default list and assigns the FIRST random market's
prices to our target condition_id.

This test locks the contract so future regressions are caught at CI time.
"""
import unittest
from unittest.mock import patch, MagicMock


class TestGammaMarketsFilterParam(unittest.TestCase):
    def test_outcome_tracker_uses_condition_ids_plural(self):
        from bot import outcome_tracker

        fake_response = MagicMock()
        fake_response.ok = True
        fake_response.json = MagicMock(return_value=[
            {
                "conditionId": "0xabc",
                "resolved": False,
                "closed": False,
                "outcomePrices": '["0.55", "0.45"]',
            }
        ])

        with patch("bot.outcome_tracker.requests.get",
                   return_value=fake_response) as mock_get:
            # Strategy 2 branch: no asset, so CLOB book is skipped and
            # the Gamma fallback fires.
            outcome_tracker._get_market_price("0xabc", asset="")

            gamma_calls = [
                c for c in mock_get.call_args_list
                if "gamma-api" in str(c).lower()
                or "GAMMA_API" in str(c)
                or "/markets" in str(c)
            ]
            self.assertTrue(
                gamma_calls,
                "_get_market_price must call the Gamma /markets endpoint "
                "when only condition_id is provided",
            )
            _, kwargs = gamma_calls[0]
            params = kwargs.get("params", {})
            self.assertIn(
                "condition_ids", params,
                "Gamma /markets filter param must be 'condition_ids' "
                "(plural, snake_case). Got: %s" % sorted(params.keys()),
            )
            self.assertEqual(
                params["condition_ids"], "0xabc",
                "condition_ids value must be the passed condition_id",
            )
            # Belt-and-suspenders: the broken variants must NOT be present.
            for bad in ("conditionId", "condition_id", "conditionIds"):
                self.assertNotIn(
                    bad, params,
                    "'%s' is silently ignored by Gamma and must not be used" % bad,
                )


if __name__ == "__main__":
    unittest.main()
