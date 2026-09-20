import unittest

from mt5_reader import _completed_rates


class CompletedRatesTests(unittest.TestCase):
    def test_forming_bar_is_removed(self):
        rates=[{"time":1},{"time":2},{"time":3}]
        self.assertEqual(_completed_rates(rates), [{"time":1},{"time":2}])
        self.assertEqual(rates[-1]["time"], 3)


if __name__ == "__main__":
    unittest.main()
