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

    def test_sell_trades_filtered_but_advance_watermark(self):
        """Only BUYs create paper_trades, but the watermark advances on
        the newest-seen timestamp regardless of trade_type. This is the
        efficient behavior: a SELL-heavy window shouldn't cause the next
        scan to re-fetch the same SELL tail. The only data we can lose
        is >50 trades between scans — which is bounded by limit=50 and
        already assumed to be rare on the 3h scan interval."""
        t_sell, t_buy = 1_700_000_200, 1_700_000_100
        trades = [
            _mk_trade("cid-sell", t_sell, trade_type="SELL"),
            _mk_trade("cid-buy", t_buy, trade_type="BUY"),
        ]
        self._run_paper_follow(trades)

        self.assertEqual(self._paper_trade_count(), 1,
                         "only the BUY should become a paper_trade")
        self.assertEqual(self.db.get_candidate_paper_scan_ts(self.addr), t_sell,
                         "watermark should advance to the newest timestamp "
                         "regardless of trade_type, so next scan skips the "
                         "SELL tail")

    def test_empty_response_is_a_noop(self):
        """Empty wallet API response — paper_trades and watermark both untouched."""
        seed = 1_699_000_000
        self.db.set_candidate_paper_scan_ts(self.addr, seed)

        self._run_paper_follow([])

        self.assertEqual(self._paper_trade_count(), 0)
        self.assertEqual(self.db.get_candidate_paper_scan_ts(self.addr), seed,
                         "watermark should not be reset when response is empty")

    def test_set_candidate_paper_scan_ts_is_monotonic(self):
        """Concurrent-scan safety: a later scan that read a stale last_ts
        must never be able to roll the watermark backwards. Enforced by
        `SET last_paper_scan_ts = MAX(COALESCE(...), ?)`."""
        self.db.set_candidate_paper_scan_ts(self.addr, 2000)
        self.assertEqual(self.db.get_candidate_paper_scan_ts(self.addr), 2000)

        # Concurrent scan B finishes later but has an older last_ts in hand:
        self.db.set_candidate_paper_scan_ts(self.addr, 1500)

        self.assertEqual(self.db.get_candidate_paper_scan_ts(self.addr), 2000,
                         "watermark must not decrease — MAX guard required")


class TestPaperTradesUniqueIndex(unittest.TestCase):
    """The UNIQUE partial index on paper_trades(candidate_address,
    condition_id, side) WHERE status='open' prevents duplicate open rows
    for the same (trader, market, side) — which is exactly the collision
    surface that `add_paper_trade`'s INSERT OR IGNORE was silently failing
    to enforce (no constraint → OR IGNORE is a no-op).
    """
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO trader_candidates (address, username, status) "
                "VALUES (?, ?, ?)",
                ("0xCAND", "cand", "observing"),
            )

    def tearDown(self):
        teardown_temp_db(self.db_path)

    def test_second_add_paper_trade_is_a_noop_on_open_row(self):
        """Two add_paper_trade calls with identical (cand, cid, side) when
        the first row is status='open' → UNIQUE constraint hits, INSERT OR
        IGNORE swallows, only 1 row in DB."""
        self.db.add_paper_trade("0xCAND", "CID-1", "Q?", "YES", 0.55)
        self.db.add_paper_trade("0xCAND", "CID-1", "Q?", "YES", 0.56)  # dup

        with self.db.get_connection() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE candidate_address='0xCAND'"
            ).fetchone()[0]
        self.assertEqual(n, 1, "UNIQUE partial index must block the dup insert")

    def test_reentry_after_close_is_allowed(self):
        """Partial index is WHERE status='open', so closing row 1 and
        adding row 2 for the same (cand, cid, side) must succeed — we
        want to allow re-entry after a trade closes."""
        self.db.add_paper_trade("0xCAND", "CID-1", "Q?", "YES", 0.55)
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE paper_trades SET status='closed' "
                "WHERE candidate_address='0xCAND' AND condition_id='CID-1'"
            )
        # Reentry — should succeed because the only prior row is now closed
        self.db.add_paper_trade("0xCAND", "CID-1", "Q?", "YES", 0.60)

        with self.db.get_connection() as conn:
            n_total = conn.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE candidate_address='0xCAND'"
            ).fetchone()[0]
            n_open = conn.execute(
                "SELECT COUNT(*) FROM paper_trades "
                "WHERE candidate_address='0xCAND' AND status='open'"
            ).fetchone()[0]
        self.assertEqual(n_total, 2, "both rows should exist (one closed, one open)")
        self.assertEqual(n_open, 1, "exactly one open row after re-entry")

    def test_different_sides_allowed_on_same_market(self):
        """UNIQUE is on (cand, cid, side) — YES and NO on same market must
        both be allowed open simultaneously."""
        self.db.add_paper_trade("0xCAND", "CID-1", "Q?", "YES", 0.55)
        self.db.add_paper_trade("0xCAND", "CID-1", "Q?", "NO", 0.45)

        with self.db.get_connection() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE candidate_address='0xCAND'"
            ).fetchone()[0]
        self.assertEqual(n, 2)


class TestPaperTradesCleanupMigration(unittest.TestCase):
    """The init_db migration must DELETE duplicate open paper_trades
    (keeping the MIN(rowid) per group) before creating the UNIQUE index —
    otherwise the index creation would fail on existing contaminated DBs."""

    def test_init_db_collapses_existing_open_dupes(self):
        """Seed a DB with 5 duplicate open rows for the same (cand, cid,
        side), run init_db (which re-applies migrations idempotently),
        and assert only 1 row remains."""
        import os
        import sys
        import tempfile
        import importlib

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            import config
            config.DB_PATH = tmp.name
            if "database.db" in sys.modules:
                importlib.reload(sys.modules["database.db"])
            from database import db
            # First init_db — creates schema WITHOUT the new UNIQUE index
            # (the index migration is what we're testing). We simulate a
            # "legacy" DB by applying the base schema but bypassing the
            # UNIQUE index migration, then poisoning it.
            db.init_db()

            with db.get_connection() as conn:
                # Drop the UNIQUE index if it was created by the first init,
                # so we can seed dupes that wouldn't otherwise be allowed.
                try:
                    conn.execute("DROP INDEX IF EXISTS idx_paper_trades_open_dedup")
                except Exception:
                    pass
                conn.execute(
                    "INSERT INTO trader_candidates (address, username, status) "
                    "VALUES (?, ?, ?)",
                    ("0xDUP", "dup", "observing"),
                )
                for price in [0.55, 0.56, 0.57, 0.58, 0.59]:
                    conn.execute(
                        "INSERT INTO paper_trades "
                        "(candidate_address, condition_id, market_question, "
                        "side, entry_price, status) VALUES (?, ?, ?, ?, ?, 'open')",
                        ("0xDUP", "CID-X", "Q?", "YES", price),
                    )
            # Verify seeded state
            with db.get_connection() as conn:
                pre = conn.execute(
                    "SELECT COUNT(*) FROM paper_trades WHERE candidate_address='0xDUP'"
                ).fetchone()[0]
            self.assertEqual(pre, 5)

            # Re-run init_db — the cleanup migration should collapse to 1
            importlib.reload(sys.modules["database.db"])
            from database import db as db2
            db2.init_db()

            with db2.get_connection() as conn:
                post = conn.execute(
                    "SELECT COUNT(*) FROM paper_trades WHERE candidate_address='0xDUP'"
                ).fetchone()[0]
            self.assertEqual(post, 1, "cleanup migration must collapse open dupes")

            # Verify UNIQUE index now exists and blocks future dupes
            with db2.get_connection() as conn:
                idx = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='index' "
                    "AND name='idx_paper_trades_open_dedup'"
                ).fetchone()
            self.assertIsNotNone(idx,
                                 "UNIQUE partial index must be created by migration")
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
