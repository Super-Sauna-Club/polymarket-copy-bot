"""TDD tests for stateful paper_follow watermark.

Before this fix, `bot/auto_discovery.py::paper_follow_candidates` used a
fixed `ENTRY_TRADE_SEC=300` (5 min) staleness filter copied from the live
copy path. The live copy path scans every 60s, so a 5min freshness window
makes sense. But paper_follow runs inside `discovery_scan` (every 3h
nominally), so 300s of freshness covers only 300/10800 = 2.78% of the
time between scans — ~97% of each trader's BUY trades were silently
dropped.

Fix: replace the fixed window with a per-candidate `last_paper_scan_ts`
watermark stored on `trader_candidates`. Each scan picks up BUYs strictly
newer than the watermark, then advances the watermark to the newest
captured timestamp. Robust against any scan cadence, produces no
duplicates, loses no trades.
"""
import time
import unittest
from unittest.mock import patch

from tests.conftest_helpers import setup_temp_db, teardown_temp_db


def _permissive_filters():
    return {
        "min_entry_price": 0.01,
        "max_entry_price": 0.99,
        "bet_size_pct": 0.01,
        "min_trade_size": 1.0,
        "max_position_size": 10.0,
        "detect_category": None,
    }


def _mk_trade(cid: str, ts: int, side: str = "YES", price: float = 0.55,
              trade_type: str = "BUY", market: str = "Q?"):
    return {
        "transaction_hash": "0x" + cid,
        "condition_id": cid,
        "side": side,
        "outcome_label": "",
        "price": price,
        "usdc_size": 100.0,
        "timestamp": ts,
        "market_question": market,
        "market_slug": "",
        "event_slug": "",
        "trade_type": trade_type,
        "end_date": "",
    }


class TestPaperFollowStateful(unittest.TestCase):
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db
        # Make config loose so non-watermark filters pass
        import config
        self._saved = {
            "MIN_TRADER_USD": getattr(config, "MIN_TRADER_USD", 0),
            "MIN_CONVICTION_RATIO": getattr(config, "MIN_CONVICTION_RATIO", 0),
            "MAX_FEE_BPS": getattr(config, "MAX_FEE_BPS", 0),
            "GLOBAL_CATEGORY_BLACKLIST": getattr(config, "GLOBAL_CATEGORY_BLACKLIST", ""),
        }
        config.MIN_TRADER_USD = 0
        config.MIN_CONVICTION_RATIO = 0
        config.MAX_FEE_BPS = 0
        config.GLOBAL_CATEGORY_BLACKLIST = ""
        self.addr = "0xCANDIDATE1"
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO trader_candidates (address, username, status) "
                "VALUES (?, ?, ?)",
                (self.addr, "cand1", "observing"),
            )

    def tearDown(self):
        import config
        for k, v in self._saved.items():
            setattr(config, k, v)
        teardown_temp_db(self.db_path)

    def _run_paper_follow(self, mock_trades):
        """Call paper_follow_candidates with filters + close stubbed."""
        from bot import auto_discovery
        with patch.object(auto_discovery, "fetch_wallet_recent_trades",
                          return_value=mock_trades), \
             patch.object(auto_discovery, "close_paper_trades",
                          new=lambda: None), \
             patch.object(auto_discovery, "_load_settings_filters",
                          return_value=_permissive_filters()), \
             patch.object(auto_discovery, "_paper_bet_size",
                          return_value=1.0):
            auto_discovery.paper_follow_candidates()

    def _paper_trade_count(self) -> int:
        with self.db.get_connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE candidate_address=?",
                (self.addr,)
            ).fetchone()[0]

    def test_first_scan_captures_all_new_trades_and_advances_watermark(self):
        """Fresh candidate (last_paper_scan_ts=0) — all 3 BUYs become paper_trades
        and the watermark advances to the newest timestamp."""
        t1, t2, t3 = 1_700_000_000, 1_700_000_100, 1_700_000_200
        trades = [_mk_trade("cid-1", t1), _mk_trade("cid-2", t2), _mk_trade("cid-3", t3)]
        self._run_paper_follow(trades)

        self.assertEqual(self._paper_trade_count(), 3,
                         "all 3 BUYs should be captured on first scan")
        self.assertEqual(self.db.get_candidate_paper_scan_ts(self.addr), t3,
                         "watermark should advance to newest timestamp")

    def test_second_scan_skips_already_seen_trades(self):
        """Watermark at t3 — API returns [t1, t2, t3, t4]. Only t4 is new."""
        t1, t2, t3, t4 = 1_700_000_000, 1_700_000_100, 1_700_000_200, 1_700_000_300
        self.db.set_candidate_paper_scan_ts(self.addr, t3)

        trades = [
            _mk_trade("cid-1", t1),
            _mk_trade("cid-2", t2),
            _mk_trade("cid-3", t3),  # equal to watermark → skip
            _mk_trade("cid-4", t4),  # newer → capture
        ]
        self._run_paper_follow(trades)

        self.assertEqual(self._paper_trade_count(), 1,
                         "only the trade newer than the watermark should be captured")
        self.assertEqual(self.db.get_candidate_paper_scan_ts(self.addr), t4,
                         "watermark should advance to t4")

    def test_no_duplicates_on_consecutive_scans_with_identical_response(self):
        """Back-to-back scans with the same API response — second scan is a no-op."""
        t1, t2 = 1_700_000_000, 1_700_000_100
        trades = [_mk_trade("cid-A", t1), _mk_trade("cid-B", t2)]

        self._run_paper_follow(trades)
        self.assertEqual(self._paper_trade_count(), 2)
        first_watermark = self.db.get_candidate_paper_scan_ts(self.addr)

        # Second scan — same trades, should not duplicate
        self._run_paper_follow(trades)
        self.assertEqual(self._paper_trade_count(), 2,
                         "second scan with identical trades must not duplicate")
        self.assertEqual(self.db.get_candidate_paper_scan_ts(self.addr), first_watermark,
                         "watermark stays the same when no new trades arrive")

    def test_sell_trades_do_not_advance_watermark(self):
        """BUYs are paper-tracked; SELLs are filtered and must not advance
        the watermark (otherwise the next scan would skip the BUY we missed
        by reading in BUY/SELL order)."""
        t_sell, t_buy = 1_700_000_200, 1_700_000_100
        trades = [
            _mk_trade("cid-sell", t_sell, trade_type="SELL"),
            _mk_trade("cid-buy", t_buy, trade_type="BUY"),
        ]
        self._run_paper_follow(trades)

        self.assertEqual(self._paper_trade_count(), 1,
                         "only the BUY should become a paper_trade")
        self.assertEqual(self.db.get_candidate_paper_scan_ts(self.addr), t_buy,
                         "watermark should match the newest BUY, not the SELL")

    def test_empty_response_is_a_noop(self):
        """Empty wallet API response — paper_trades and watermark both untouched."""
        seed = 1_699_000_000
        self.db.set_candidate_paper_scan_ts(self.addr, seed)

        self._run_paper_follow([])

        self.assertEqual(self._paper_trade_count(), 0)
        self.assertEqual(self.db.get_candidate_paper_scan_ts(self.addr), seed,
                         "watermark should not be reset when response is empty")


if __name__ == "__main__":
    unittest.main()
