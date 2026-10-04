import unittest
from datetime import datetime, timedelta, timezone
from risk import RiskManager

class RiskTests(unittest.TestCase):
    def test_budget_and_minimum_lot(self):
        r = RiskManager(50)
        self.assertAlmostEqual(r.budget(), 0.25)
        self.assertIsNone(r.proposed_lots(3000, 2990, 100))

    def test_daily_limit_resets_next_day(self):
        day = datetime(2026, 10, 1, tzinfo=timezone.utc)
        r = RiskManager(50)
        self.assertTrue(r.record_closed_pnl(-1, day))
        self.assertEqual(r.budget(day), 0)
        self.assertGreater(r.budget(day + timedelta(days=1)), 0)

    def test_two_losses_require_review(self):
        day = datetime(2026, 10, 1, tzinfo=timezone.utc)
        r = RiskManager(50)
        self.assertFalse(r.record_closed_pnl(-0.2, day))
        self.assertTrue(r.record_closed_pnl(-0.2, day))
        self.assertEqual(r.budget(day + timedelta(days=1)), 0)
        r.reset_loss_streak_after_review()
        self.assertGreater(r.budget(day + timedelta(days=1)), 0)

    def test_emergency_stop_and_bad_values(self):
        r = RiskManager(50)
        self.assertIsNone(r.proposed_lots(float("nan"), 2990, 100))
        with self.assertRaises(ValueError):
            r.record_closed_pnl(float("nan"))
        r.emergency_stop()
        self.assertEqual(r.budget(), 0)

if __name__ == "__main__":
    unittest.main()
