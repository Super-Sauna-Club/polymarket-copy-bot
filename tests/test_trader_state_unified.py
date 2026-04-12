import unittest
from tests.conftest_helpers import setup_temp_db, teardown_temp_db


class TestUnifiedTraderState(unittest.TestCase):
    def setUp(self):
        self.db_path = setup_temp_db()
        from database import db
        self.db = db
        # Seed one trader in BOTH systems with different states.
        db.set_trader_status("alice", "throttled", 0.5, "Soft throttle")
        db.upsert_lifecycle_trader("0xaaa", "alice", "LIVE_FOLLOW", "bootstrap")

    def tearDown(self):
        teardown_temp_db(self.db_path)

    def test_effective_state_soft_throttle_but_hard_live(self):
        state = self.db.get_trader_effective_state("alice")
        self.assertEqual(state["hard_status"], "LIVE_FOLLOW")
        self.assertEqual(state["soft_status"], "throttled")
        self.assertAlmostEqual(state["multiplier"], 0.5, places=2)
        self.assertFalse(state["is_paused"])

    def test_effective_state_hard_pause_overrides(self):
        self.db.update_lifecycle_status("0xaaa", "PAUSED", "brain test")
        state = self.db.get_trader_effective_state("alice")
        self.assertEqual(state["hard_status"], "PAUSED")
        self.assertTrue(state["is_paused"])

    def test_is_trader_paused_helper(self):
        # Throttled + live → not paused
        self.assertFalse(self.db.is_trader_paused("alice"))
        # Hard pause via lifecycle
        self.db.update_lifecycle_status("0xaaa", "PAUSED", "test")
        self.assertTrue(self.db.is_trader_paused("alice"))

    def test_soft_paused_also_reads_as_paused(self):
        # Soft pause via trader_status should also count as paused.
        self.db.set_trader_status("alice", "paused", 0.0, "Hard via status")
        self.assertTrue(self.db.is_trader_paused("alice"))


if __name__ == "__main__":
    unittest.main()
