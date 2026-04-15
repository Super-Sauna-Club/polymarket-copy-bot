"""TDD tests for Scenario D Phase A3 — rotation-based scanning.

Before this fix, `bot/auto_discovery.py::paper_follow_candidates` called
`db.get_active_candidates()[:20]` where `get_active_candidates()` ordered
by `paper_pnl DESC`. With 41 active candidates (38 observing + 3 promoted),
the bottom 21 were never scanned — they had no new paper_trades, so their
rank stayed pinned and they stayed starved forever.

Fix: new column `trader_candidates.last_paper_rotation_ts`; ORDER BY
`last_paper_rotation_ts ASC, paper_pnl DESC`; each scan advances the ts on
the candidate after processing. The `[:20]` budget stays — it's the scan
rate-limit, not the selection bias. All 41 candidates get scanned within
ceil(41/20) = 3 cycles.
"""
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


class TestPaperFollowRotation(unittest.TestCase):
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db
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

    def tearDown(self):
        import config
        for k, v in self._saved.items():
            setattr(config, k, v)
        teardown_temp_db(self.db_path)

    def _seed_candidates(self, n: int):
        """Insert N observing candidates, all with rotation_ts=0 and paper_pnl=0."""
        with self.db.get_connection() as conn:
            for i in range(n):
                conn.execute(
                    "INSERT INTO trader_candidates "
                    "(address, username, status, paper_pnl, last_paper_rotation_ts) "
                    "VALUES (?, ?, 'observing', 0, 0)",
                    ("0x%040x" % i, "cand%d" % i),
                )

    def _run_one_cycle(self):
        """Run paper_follow_candidates with all side effects mocked out."""
        from bot import auto_discovery
        with patch.object(auto_discovery, "fetch_wallet_recent_trades",
                          return_value=[]), \
             patch.object(auto_discovery, "close_paper_trades",
                          new=lambda: None), \
             patch.object(auto_discovery, "_load_settings_filters",
                          return_value=_permissive_filters()):
            auto_discovery.paper_follow_candidates()

    def _rotation_ts_map(self) -> dict:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT address, last_paper_rotation_ts "
                "FROM trader_candidates WHERE status='observing'"
            ).fetchall()
        return {r["address"]: r["last_paper_rotation_ts"] for r in rows}

    # Test 1: rotation reaches every candidate within ceil(N/budget) cycles
    def test_rotation_covers_all_candidates_in_three_cycles(self):
        self._seed_candidates(41)
        for _ in range(3):
            self._run_one_cycle()

        ts_map = self._rotation_ts_map()
        self.assertEqual(len(ts_map), 41)
        never_scanned = [addr for addr, ts in ts_map.items() if ts == 0]
        self.assertEqual(
            never_scanned, [],
            "after 3 cycles of budget-20 all 41 candidates must be scanned at least once",
        )

    # Test 2: oldest-first preference — candidates with the smallest
    # last_paper_rotation_ts come first
    def test_rotation_prefers_oldest_ts_first(self):
        self._seed_candidates(5)
        # Stagger manual rotation timestamps: cand0=100, cand1=200, ...
        with self.db.get_connection() as conn:
            for i in range(5):
                conn.execute(
                    "UPDATE trader_candidates SET last_paper_rotation_ts=? WHERE address=?",
                    ((i + 1) * 100, "0x%040x" % i),
                )

        from database import db
        ordered = db.get_active_candidates()
        ordered_addrs = [c["address"] for c in ordered]

        expected = ["0x%040x" % i for i in range(5)]  # ascending ts → ascending index
        self.assertEqual(ordered_addrs, expected)

    # Test 3: ts advances after scan and is >= the pre-scan value (monotonic)
    def test_rotation_advances_ts_after_scan(self):
        self._seed_candidates(3)
        before = self._rotation_ts_map()
        self.assertTrue(all(ts == 0 for ts in before.values()))

        self._run_one_cycle()

        after = self._rotation_ts_map()
        for addr in before:
            self.assertGreater(
                after[addr], before[addr],
                "candidate %s rotation_ts must advance after scan" % addr,
            )


if __name__ == "__main__":
    unittest.main()
