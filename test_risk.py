import unittest
from risk import RiskManager
class RiskTests(unittest.TestCase):
    def test_budget(self):
        r=RiskManager(50)
        self.assertAlmostEqual(r.budget(),.25)
        self.assertIsNone(r.proposed_lots(3000,2990,100))
    def test_daily_stop(self):
        r=RiskManager(50)
        self.assertTrue(r.record_closed_pnl(-1))
        self.assertEqual(r.budget(),0)
    def test_two_losses(self):
        r=RiskManager(50)
        self.assertFalse(r.record_closed_pnl(-.2))
        self.assertTrue(r.record_closed_pnl(-.2))
        self.assertEqual(r.budget(),0)
if __name__=="__main__":unittest.main()
