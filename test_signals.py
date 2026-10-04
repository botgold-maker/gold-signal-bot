import unittest
from unittest.mock import patch
import pandas as pd
from main import signal, fetch

class SignalTests(unittest.TestCase):
    def test_insufficient_bars_cannot_trade(self):
        # A short history must never be treated as a high-confidence setup.
        bars = pd.DataFrame([{'open': 3000, 'high': 3001, 'low': 2999, 'close': 3000}] * 60)
        self.assertEqual(signal(bars)['signal'], 'WAIT')

    def test_feed_failure_does_not_invent_prices(self):
        with patch('main.websocket.create_connection', side_effect=OSError('offline')):
            with self.assertRaises(RuntimeError):
                fetch()

if __name__ == '__main__':
    unittest.main()
