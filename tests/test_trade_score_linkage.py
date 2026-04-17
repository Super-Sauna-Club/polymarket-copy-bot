"""TDD for trade_scores.trade_id linkage after successful buy.

Bug: trade_scores rows are created with trade_id=NULL by the scorer,
but after create_copy_trade() succeeds, nobody writes the new trade_id
back. Result: "Trades Scored: 0" on the brain dashboard because the
JOIN on trade_id finds nothing.

Fix: db.link_trade_score(condition_id, trader_name, trade_id) updates
the newest unlinked trade_scores row for that (cid, trader) pair.
"""
import unittest
from tests.conftest_helpers import setup_temp_db, teardown_temp_db


class TestLinkTradeScore(unittest.TestCase):
    def setUp(self):
        self.path = setup_temp_db()
        from database import db
        self.db = db

    def tearDown(self):
        teardown_temp_db(self.path)

    def _seed_score(self, cid, trader, action="EXECUTE", score=65):
        with self.db.get_connection() as conn:
            conn.execute(
                "INSERT INTO trade_scores "
                "(condition_id, trader_name, side, entry_price, market_question, "
                " score_total, score_trader_edge, score_category_wr, "
                " score_price_signal, score_conviction, score_market_quality, "
                " score_correlation, action) "
                "VALUES (?, ?, 'YES', 0.55, 'Q', ?, 10, 10, 10, 10, 10, 10, ?)",
                (cid, trader, score, action),
            )

    def test_link_sets_trade_id_on_newest_unlinked_row(self):
        """After buy, the newest NULL-trade_id score row gets linked."""
        self._seed_score("cid1", "alice")

        linked = self.db.link_trade_score("cid1", "alice", 42)

        self.assertEqual(linked, 1)
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT trade_id FROM trade_scores "
                "WHERE condition_id='cid1' AND trader_name='alice'"
            ).fetchone()
        self.assertEqual(row["trade_id"], 42)

    def test_link_only_affects_newest_row(self):
        """If multiple score rows exist, only the newest gets linked."""
        self._seed_score("cid1", "alice")
        self._seed_score("cid1", "alice")  # newer row

        linked = self.db.link_trade_score("cid1", "alice", 99)

        self.assertEqual(linked, 1)
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT id, trade_id FROM trade_scores "
                "WHERE condition_id='cid1' AND trader_name='alice' "
                "ORDER BY id"
            ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0]["trade_id"])
        self.assertEqual(rows[1]["trade_id"], 99)

    def test_link_returns_zero_when_no_match(self):
        """No matching unlinked row → returns 0, no crash."""
        linked = self.db.link_trade_score("nonexistent", "nobody", 1)
        self.assertEqual(linked, 0)

    def test_link_skips_already_linked_rows(self):
        """Rows that already have trade_id are not overwritten."""
        self._seed_score("cid1", "alice")  # row 1
        self.db.link_trade_score("cid1", "alice", 10)

        self._seed_score("cid1", "alice")  # row 2 (will stay unlinked)
        self._seed_score("cid1", "alice")  # row 3 (newest, will get linked)
        linked = self.db.link_trade_score("cid1", "alice", 20)

        self.assertEqual(linked, 1)
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT trade_id FROM trade_scores "
                "WHERE condition_id='cid1' AND trader_name='alice' "
                "ORDER BY id"
            ).fetchall()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["trade_id"], 10)
        self.assertIsNone(rows[1]["trade_id"])
        self.assertEqual(rows[2]["trade_id"], 20)


if __name__ == "__main__":
    unittest.main()
