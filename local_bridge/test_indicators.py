import unittest
from indicators import multi_timeframe
class IndicatorTest(unittest.TestCase):
    def test_rising_series(self):
        bars=[{'close':100+i*.1,'high':100+i*.1+.2,'low':100+i*.1-.2} for i in range(240)]
        result=multi_timeframe({x:bars for x in ('M5','M15','M30','H1')})
        self.assertGreater(result['H1']['ma20'],result['H1']['ma60'])
        self.assertGreater(result['H1']['+di'],result['H1']['-di'])
        self.assertIn('macd_hist',result['M5'])
if __name__=='__main__':unittest.main()

