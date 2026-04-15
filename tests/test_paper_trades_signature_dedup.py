"""TDD tests for Scenario D Phase A2 — signature-based full dedup.

The partial UNIQUE index `idx_paper_trades_open_dedup` only covers
`status='open'`. Once a row closes, the index no longer sees it, and the next
`INSERT OR IGNORE` for the same `(candidate_address, condition_id, side)`
succeeds. Combined with Polymarket's activity API returning one logical order
as N microprice fill-split rows, this inflates closed paper_trades massively
— live prod measured 83.7% duplicate rows, up to 123x inflation per candidate.

Fix: hour-bucket signature
`MD5(candidate_address:condition_id:side:YYYYMMDDHH)`.
- Microprice fills within the same clock hour collapse to 1 row.
- Reentry after 1h+ creates a new row (preserves existing reentry semantics).
- Legacy closed dup rows get backfilled + deduped on next init_db run.
"""
import unittest
from unittest.mock import patch
from datetime import datetime

from tests.conftest_helpers import setup_temp_db, teardown_temp_db


CAND = "0xcand00000000000000000000000000000000dead"
CID = "0xcid000000000000000000000000000000000babe"


class TestPaperTradeSignature(unittest.TestCase):
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db
        # Seed the candidate so rollup recompute has a row to update
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO trader_candidates (address, username, status, paper_trades, paper_wins, paper_pnl) "
                "VALUES (?, 'testcand', 'observing', 0, 0, 0)",
                (CAND,),
            )

    def tearDown(self):
        teardown_temp_db(self.db_path)

    def _count_rows_for_cand(self) -> int:
        with self.db.get_connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE candidate_address=?", (CAND,)
            ).fetchone()[0]

    # Test 1: microprice fill-split within the same hour collapses
    def test_microprice_fills_collapse_within_same_hour(self):
        fixed = datetime(2026, 4, 15, 10, 30, 0)
        with patch("database.db._now", return_value=fixed):
            prices = [0.81, 0.8100000026, 0.810000043, 0.81000042, 0.8100005,
                      0.81000123, 0.8101, 0.8102, 0.81035, 0.8104, 0.81051]
            for p in prices:
                self.db.add_paper_trade(CAND, CID, "Will X win?", "YES", p)

        self.assertEqual(
            self._count_rows_for_cand(), 1,
            "11 microprice fills in the same hour must collapse to 1 row",
        )

    # Test 2: reentry after 1h creates a new row (mirrors production: the
    # first row gets closed by close_paper_trades before the second scan).
    def test_reentry_after_one_hour_creates_new_row(self):
        t1 = datetime(2026, 4, 15, 10, 30, 0)
        t2 = datetime(2026, 4, 15, 11, 35, 0)  # 1h5min later = different hour bucket

        with patch("database.db._now", return_value=t1):
            self.db.add_paper_trade(CAND, CID, "Will X win?", "YES", 0.55)
        # Close the first row — partial UNIQUE index no longer covers it;
        # signature index is the only remaining dedup guard.
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE paper_trades SET status='closed', pnl=-0.10 "
                "WHERE candidate_address=?",
                (CAND,),
            )
        with patch("database.db._now", return_value=t2):
            self.db.add_paper_trade(CAND, CID, "Will X win?", "YES", 0.55)

        self.assertEqual(
            self._count_rows_for_cand(), 2,
            "after-close reentry 1h+ apart must be treated as distinct",
        )

    # Test 3: migration dedupes legacy rows lacking signatures
    def test_migration_dedupes_legacy_dup_rows_and_recomputes_rollups(self):
        # Seed 5 closed dup rows for the same logical trade, all in the same
        # clock hour, with different pnl to simulate pre-cleanup state.
        with self.db.get_connection() as conn:
            for i, pnl in enumerate([-0.20, -0.19, -0.18, -0.21, -0.22]):
                conn.execute(
                    "INSERT INTO paper_trades "
                    "(candidate_address, condition_id, market_question, side, "
                    " entry_price, current_price, status, pnl, created_at, signature) "
                    "VALUES (?, ?, 'Q', 'YES', 0.81, 0.80, 'closed', ?, "
                    " '2026-04-12 15:00:%02d', NULL)" % i,
                    (CAND, CID, pnl),
                )

        self.assertEqual(self._count_rows_for_cand(), 5, "precondition")

        # Run backfill + dedupe
        self.db._backfill_paper_trades_signature_and_dedupe()

        # Post-migration: exactly 1 row for this logical trade
        self.assertEqual(self._count_rows_for_cand(), 1)

        # Recompute rollups and verify trader_candidates matches surviving row
        self.db._recompute_candidate_rollups()
        with self.db.get_connection() as conn:
            cand = conn.execute(
                "SELECT paper_trades, paper_wins, paper_pnl FROM trader_candidates WHERE address=?",
                (CAND,),
            ).fetchone()
        self.assertEqual(cand["paper_trades"], 1)
        self.assertEqual(cand["paper_wins"], 0)  # all seeded pnls were negative
        # surviving row is MIN(rowid) = first seeded = -0.20
        self.assertAlmostEqual(cand["paper_pnl"], -0.20, places=4)

    # Test 4: migration on clean DB is a no-op
    def test_migration_is_idempotent_on_clean_db(self):
        # Seed one clean row with a proper signature
        fixed = datetime(2026, 4, 15, 10, 30, 0)
        with patch("database.db._now", return_value=fixed):
            self.db.add_paper_trade(CAND, CID, "Q", "YES", 0.55)
        self.assertEqual(self._count_rows_for_cand(), 1)

        # Run backfill + dedupe twice — no new deletes, no errors
        self.db._backfill_paper_trades_signature_and_dedupe()
        self.db._backfill_paper_trades_signature_and_dedupe()

        self.assertEqual(self._count_rows_for_cand(), 1)

    # Test 5: signature is deterministic and matches the documented format
    def test_signature_is_deterministic(self):
        dt = datetime(2026, 4, 15, 10, 30, 0)
        sig1 = self.db._paper_trade_signature(CAND, CID, "YES", dt=dt)
        sig2 = self.db._paper_trade_signature(CAND, CID, "YES", dt=dt)
        self.assertEqual(sig1, sig2, "same inputs must yield same sig")
        self.assertEqual(len(sig1), 32, "md5 hexdigest is 32 chars")

        # Different side -> different sig
        sig_no = self.db._paper_trade_signature(CAND, CID, "NO", dt=dt)
        self.assertNotEqual(sig1, sig_no)

        # Different hour -> different sig
        dt_next = datetime(2026, 4, 15, 11, 0, 0)
        sig_next = self.db._paper_trade_signature(CAND, CID, "YES", dt=dt_next)
        self.assertNotEqual(sig1, sig_next)

        # Same minute, different second within the same hour -> same sig
        dt_same_hr = datetime(2026, 4, 15, 10, 59, 59)
        sig_same_hr = self.db._paper_trade_signature(CAND, CID, "YES", dt=dt_same_hr)
        self.assertEqual(sig1, sig_same_hr)


if __name__ == "__main__":
    unittest.main()
